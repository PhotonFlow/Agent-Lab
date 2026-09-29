"""ROS2 node: joins live Stage-1/Stage-2 output back to ground truth during
a dataset-replay bag playback, and writes the same report/overlay artifacts
as the offline Python evaluator.

Subscribes:
  - ``/pps/detections`` (vision_msgs/Detection2DArray) -- captures the
    actual live Stage-1 bbox per sample (mirrors the same
    class-filter + highest_confidence/largest_area selection that
    ``pallet_pose_cpp_node`` itself applies, via ``detection_utils.cpp``,
    so the recorded bbox matches what Stage-2 actually consumed).
  - ``/pps/pallet_pose_rich`` (pps_perception_msgs/PalletPoseStamped) --
    success path; joined by ``input_rgb_stamp``.
  - ``/pps/pallet_pose_diagnostics`` (diagnostic_msgs/DiagnosticArray) --
    failure path (``level == WARN`` only; ``OK`` diagnostics duplicate the
    rich-pose topic and are ignored); joined by the ``input_rgb_stamp``
    KeyValue string.

Every message is joined back to a ``sample_id`` via ``stamp_map.json``
(built by ``build_bag.py``), using the exact same
``"<sec>.<nanosec-9digit>"`` string format as
``pallet_pose_node.cpp::stamp_to_string``.

On shutdown (SIGINT from the driver script -> KeyboardInterrupt out of
``rclpy.spin`` -> this node's ``finalize()``), every sample that was
written into the replayed bag is joined to ``manifest.csv``'s GT columns
and written out via ``pallet_pose_estimation.eval_report_common`` --
the same ``per_sample_errors.csv`` / ``summary_by_group.csv`` /
``report.md`` / ``overlays/*.png`` schema the offline evaluator produces.
Samples with neither a rich-pose nor a diagnostics message by shutdown are
marked ``status="no_response"`` (distinct from an algorithmic
``"failed"``), separating sync/timing problems from Stage-2 rejections.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import rclpy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image
from vision_msgs.msg import Detection2DArray


def _find_repo_root() -> Path:
    """This file lives at
    pps_v3.3_ros/src/pps_dataset_replay/pps_dataset_replay/eval_recorder_node.py,
    so the repo root is 4 parents up -- true when running from source or a
    --symlink-install colcon build. A plain (non-symlink) install copies
    this file elsewhere, breaking that assumption; set PPS_REPO_ROOT to
    override in that case."""
    env_override = os.environ.get("PPS_REPO_ROOT")
    if env_override:
        return Path(env_override)
    return Path(__file__).resolve().parents[4]


REPO_ROOT = _find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pallet_pose_estimation import eval_report_common as erc  # noqa: E402
from pallet_pose_estimation.io.camera import RgbDepthCameraConfig  # noqa: E402

from pps_dataset_replay.build_bag import format_stamp, make_image_msg  # noqa: E402

from pps_perception_msgs.msg import PalletPoseStamped  # noqa: E402


_RELIABLE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    depth=50,
)


def select_best_detection(
    detections: list[Any], target_class_id: str, strategy: str
) -> dict[str, float] | None:
    """Python mirror of detection_utils.cpp's
    extract_detection_candidates()+select_detection(), so the bbox this
    recorder attributes to a sample is exactly the one pallet_pose_cpp_node
    itself would have selected from the same Detection2DArray."""
    candidates = []
    for det in detections:
        if not det.results:
            continue
        best = max(det.results, key=lambda r: r.hypothesis.score)
        class_id = best.hypothesis.class_id
        if target_class_id and class_id != target_class_id:
            continue
        cx, cy = det.bbox.center.position.x, det.bbox.center.position.y
        half_w, half_h = 0.5 * det.bbox.size_x, 0.5 * det.bbox.size_y
        x1, y1, x2, y2 = cx - half_w, cy - half_h, cx + half_w, cy + half_h
        area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        candidates.append(
            {"score": float(best.hypothesis.score), "area": float(area),
             "x1": x1, "y1": y1, "x2": x2, "y2": y2}
        )
    if not candidates:
        return None
    if strategy == "highest_confidence":
        return max(candidates, key=lambda c: (c["score"], c["area"]))
    if strategy == "largest_area":
        return max(candidates, key=lambda c: (c["area"], c["score"]))
    raise ValueError(f"unknown detection_selection strategy: {strategy!r}")


class EvalRecorderNode(Node):
    def __init__(self) -> None:
        super().__init__("eval_recorder_node")

        self.declare_parameter("dataset_root", "")
        self.declare_parameter("manifest_path", "")
        self.declare_parameter("camera_yaml_path", "")
        self.declare_parameter("replay_meta_dir", "")
        self.declare_parameter("output_dir", "")
        self.declare_parameter("detections_topic", "/pps/detections")
        self.declare_parameter("pose_topic", "/pps/pallet_pose_rich")
        self.declare_parameter("diagnostics_topic", "/pps/pallet_pose_diagnostics")
        self.declare_parameter("target_class_id", "pallet")
        self.declare_parameter("detection_selection", "highest_confidence")
        self.declare_parameter("pallet_width_m", erc.CORRECTED_PROTOTYPE["pallet_width_m"])
        self.declare_parameter("pallet_height_m", erc.CORRECTED_PROTOTYPE["pallet_height_m"])
        self.declare_parameter("publish_live_overlay", True)
        self.declare_parameter("live_overlay_topic", "/pps/debug/overlay_image")

        dataset_root = self._require_str("dataset_root")
        self._dataset_root = Path(dataset_root)
        manifest_path = self._str("manifest_path")
        self._manifest_path = Path(manifest_path) if manifest_path else (self._dataset_root / "manifest.csv")
        camera_yaml_path = self._require_str("camera_yaml_path")
        replay_meta_dir = Path(self._require_str("replay_meta_dir"))
        output_dir = self._require_str("output_dir")
        self._output_dir = Path(output_dir)

        self._target_class_id = self._str("target_class_id")
        self._detection_selection = self._str("detection_selection")
        self._pallet_width_m = float(self.get_parameter("pallet_width_m").value)
        self._pallet_height_m = float(self.get_parameter("pallet_height_m").value)
        self._publish_live_overlay = bool(self.get_parameter("publish_live_overlay").value)
        live_overlay_topic = self._str("live_overlay_topic")

        self._camera_cfg = RgbDepthCameraConfig.from_yaml(camera_yaml_path)
        self._manifest_rows = {row["sample_id"]: row for row in erc.load_manifest(self._manifest_path)}

        stamp_map_path = replay_meta_dir / "stamp_map.json"
        self._stamp_to_sample: dict[str, str] = json.loads(stamp_map_path.read_text(encoding="utf-8"))
        self._expected_sample_ids = sorted(set(self._stamp_to_sample.values()))
        self.get_logger().info(
            f"eval_recorder_node up: {len(self._expected_sample_ids)} expected sample(s) "
            f"from {stamp_map_path}"
        )

        # sample_id -> {"detection": {...}|None, "detection_recv_wall": float,
        #               "pose": {...}|None, "diag": {...}|None}
        self._results: dict[str, dict[str, Any]] = {}
        self._t0 = time.perf_counter()
        self._finalized = False

        self.create_subscription(
            Detection2DArray, self._str("detections_topic"), self._on_detections, _RELIABLE_QOS
        )
        self.create_subscription(
            PalletPoseStamped, self._str("pose_topic"), self._on_pose_rich, _RELIABLE_QOS
        )
        self.create_subscription(
            DiagnosticArray, self._str("diagnostics_topic"), self._on_diagnostics, _RELIABLE_QOS
        )
        self._overlay_pub = None
        if self._publish_live_overlay:
            self._overlay_pub = self.create_publisher(Image, live_overlay_topic, 10)

    def _str(self, name: str) -> str:
        return self.get_parameter(name).get_parameter_value().string_value

    def _require_str(self, name: str) -> str:
        value = self._str(name)
        if not value:
            raise ValueError(f"parameter '{name}' is required")
        return value

    # -- subscriptions ----------------------------------------------------

    def _on_detections(self, msg: Detection2DArray) -> None:
        key = format_stamp(msg.header.stamp.sec, msg.header.stamp.nanosec)
        sample_id = self._stamp_to_sample.get(key)
        if sample_id is None:
            return
        entry = self._results.setdefault(sample_id, {})
        entry["detection_recv_wall"] = time.time()
        best = select_best_detection(msg.detections, self._target_class_id, self._detection_selection)
        if best is not None:
            entry["detection"] = best

    def _on_pose_rich(self, msg: PalletPoseStamped) -> None:
        key = format_stamp(msg.input_rgb_stamp.sec, msg.input_rgb_stamp.nanosec)
        sample_id = self._stamp_to_sample.get(key)
        if sample_id is None:
            self.get_logger().warning(f"pallet_pose_rich stamp {key} not in stamp_map; dropping")
            return
        entry = self._results.setdefault(sample_id, {})
        entry["pose"] = {
            "pred_yaw_deg": math.degrees(msg.yaw_rad),
            "pred_tx": msg.pose.position.x,
            "pred_ty": msg.pose.position.y,
            "pred_tz": msg.pose.position.z,
            "n_face_points": msg.n_face_points,
            "plane_inlier_ratio": msg.plane_inlier_ratio,
            "chamfer_cost_m": msg.chamfer_cost_m,
        }
        entry["recv_wall"] = time.time()
        self._maybe_publish_live_overlay(sample_id)

    def _on_diagnostics(self, msg: DiagnosticArray) -> None:
        for status in msg.status:
            if status.level != DiagnosticStatus.WARN:
                continue  # OK diagnostics duplicate the rich-pose topic; skip.
            kv = {item.key: item.value for item in status.values}
            key = kv.get("input_rgb_stamp")
            if key is None:
                continue
            sample_id = self._stamp_to_sample.get(key)
            if sample_id is None:
                self.get_logger().warning(f"diagnostics stamp {key} not in stamp_map; dropping")
                continue
            entry = self._results.setdefault(sample_id, {})
            entry["diag"] = {"failure_reason": kv.get("failure_reason", status.message)}
            entry["recv_wall"] = time.time()
            self._maybe_publish_live_overlay(sample_id)

    # -- overlay ------------------------------------------------------------

    def _maybe_publish_live_overlay(self, sample_id: str) -> None:
        if self._overlay_pub is None:
            return
        manifest_row = self._manifest_rows.get(sample_id)
        if manifest_row is None:
            return
        record = self._build_record(sample_id, manifest_row)
        try:
            rgb_path = erc.resolve_asset(self._dataset_root, manifest_row["rgb_path"])
            bgr = erc.render_overlay(
                pd.Series(record), rgb_path, self._camera_cfg,
                pallet_width_m=self._pallet_width_m, pallet_height_m=self._pallet_height_m,
            )
        except Exception as exc:  # noqa: BLE001 - live preview must never crash the recorder
            self.get_logger().warning(f"live overlay render failed for {sample_id}: {exc}")
            return
        if bgr is None:
            return
        stamp = self.get_clock().now().to_msg()
        self._overlay_pub.publish(make_image_msg(bgr, "bgr8", stamp, "eval_recorder_overlay"))

    # -- record assembly -----------------------------------------------------

    def _build_record(self, sample_id: str, manifest_row: dict[str, str]) -> dict[str, Any]:
        record = erc.new_error_record(sample_id, manifest_row)
        result = self._results.get(sample_id, {})
        detection = result.get("detection")
        if detection is not None:
            record.update(
                {
                    "det_score": detection["score"],
                    "det_label": self._target_class_id,
                    "det_x1": detection["x1"],
                    "det_y1": detection["y1"],
                    "det_x2": detection["x2"],
                    "det_y2": detection["y2"],
                }
            )
        pose = result.get("pose")
        diag = result.get("diag")
        if pose is not None:
            record["n_face_points"] = pose["n_face_points"]
            record["plane_inlier_ratio"] = pose["plane_inlier_ratio"]
            record["chamfer_cost_m"] = pose["chamfer_cost_m"]
            detection_recv = result.get("detection_recv_wall")
            recv = result.get("recv_wall")
            if detection_recv is not None and recv is not None:
                record["runtime_s"] = recv - detection_recv
            erc.fill_prediction_error_fields(
                record,
                pred_yaw_deg=pose["pred_yaw_deg"],
                pred_tx=pose["pred_tx"],
                pred_ty=pose["pred_ty"],
                pred_tz=pose["pred_tz"],
            )
        elif diag is not None:
            record["status"] = "failed"
            record["failure_reason"] = diag["failure_reason"]
        else:
            record["status"] = "no_response"
            record["failure_reason"] = "no rich-pose or diagnostics message received before shutdown"
        return record

    # -- finalize ----------------------------------------------------------

    def finalize(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        runtime_s = time.perf_counter() - self._t0

        records = [
            self._build_record(sample_id, self._manifest_rows[sample_id])
            for sample_id in self._expected_sample_ids
            if sample_id in self._manifest_rows
        ]
        missing = [s for s in self._expected_sample_ids if s not in self._manifest_rows]
        for sample_id in missing:
            self.get_logger().warning(f"sample_id {sample_id!r} in stamp_map but not in manifest; skipping")

        df = pd.DataFrame(records)
        n_ok = int((df["status"] == "ok").sum()) if not df.empty else 0
        n_no_response = int((df["status"] == "no_response").sum()) if not df.empty else 0
        n_failed = int((df["status"] == "failed").sum()) if not df.empty else 0
        self.get_logger().info(
            f"finalizing: {len(df)} samples (ok={n_ok}, failed={n_failed}, no_response={n_no_response}); "
            f"writing report to {self._output_dir}"
        )

        method_lines = [
            "- Detector: live `rtdetr_detector_node` (ROS2), replayed via a rosbag2-recorded RGB/depth stream (`pps_dataset_replay`).",
            "- Pose estimator: live `pallet_pose_cpp_node` (compiled C++ `geometry_core::estimate_pose_chamfer_v3_2` port) over ROS2 topics -- not a direct library call, so this also exercises `depth_utils`/`detection_utils`/the `message_filters::ApproximateTime` sync.",
            f"- Detection selection mirrored client-side: target_class_id={self._target_class_id!r}, strategy={self._detection_selection!r} (must match `pallet_pose_cpp_node`'s own parameters for the recorded bbox to be accurate).",
        ]
        erc.write_all_reports(
            df, self._output_dir, self._dataset_root, self._camera_cfg,
            runtime_s=runtime_s,
            title="ROS2 Dataset Replay Evaluation Results",
            method_lines=method_lines,
            pallet_width_m=self._pallet_width_m,
            pallet_height_m=self._pallet_height_m,
            manifest_path=self._manifest_path,
        )


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = EvalRecorderNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        # On this rclpy version, a SIGINT delivered while spinning raises
        # ExternalShutdownException (from the global signal handler
        # rclpy.init() installs), not a plain KeyboardInterrupt -- catch
        # both so shutdown is always clean. finalize() below still ran
        # correctly even before this fix (finally: runs regardless of
        # which exception type escapes try:); this only silences the
        # cosmetic traceback + non-zero exit code that otherwise follows.
        pass
    finally:
        node.finalize()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
