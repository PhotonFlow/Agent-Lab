#!/usr/bin/env python3
"""Build a rosbag2 replay of ``eval_dataset_combined`` for the ROS2 dataset
replay tool.

Writes one paired RGB + depth ``sensor_msgs/Image`` per valid manifest
sample into an ``mcap`` bag, both stamped with the *same* ``header.stamp``
so ``message_filters::ApproximateTime`` (in ``pallet_pose_cpp_node``) and
the live detector's image subscription both see one coherent frame per
sample. Consecutive samples are spaced ``--pace-hz`` apart in the bag's own
recorded time, so ``ros2 bag play`` (at its default rate=1.0) paces samples
one at a time -- generous enough that one sample's full detector + Stage-2
latency finishes before the next sample's messages are due.

Also writes ``stamp_map.json`` (``{"<sec>.<nanosec-9digit>": "<sample_id>"}``,
the exact join-key format ``pallet_pose_node.cpp::stamp_to_string`` already
uses for its diagnostics) and ``bag_meta.json`` (topics/frame_id/pacing/
dataset paths) alongside the bag, both consumed by ``eval_recorder_node.py``.

No live ROS2 graph is needed to *run* this script -- it only needs the
ROS2 Python message/serialization packages importable (a sourced
workspace), not ``rclpy.init()`` or a running node.

Usage:
    ros2 run pps_dataset_replay build_bag \\
        --dataset-root /path/to/eval_dataset_combined \\
        --out /path/to/dataset_bag \\
        --pace-hz 1.0
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def _find_repo_root() -> Path:
    """This file lives at
    pps_v3.3_ros/src/pps_dataset_replay/pps_dataset_replay/build_bag.py, so
    the repo root is 4 parents up -- true when running from source or a
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

try:
    import rosbag2_py
    from builtin_interfaces.msg import Time
    from rclpy.serialization import serialize_message
    from sensor_msgs.msg import Image
except ImportError as exc:  # pragma: no cover - exercised only without a sourced ROS2 env
    raise ImportError(
        "build_bag.py needs a sourced ROS2 Python environment (rosbag2_py, "
        "sensor_msgs, builtin_interfaces, rclpy) even though it doesn't "
        "start a node or call rclpy.init()."
    ) from exc


DEFAULT_RGB_TOPIC = "/camera/color/image_rect"
DEFAULT_DEPTH_TOPIC = "/camera/depth/image_rect"
DEFAULT_FRAME_ID = "camera_rgb_optical_frame"
NS_PER_S = 1_000_000_000


def format_stamp(sec: int, nanosec: int) -> str:
    """Mirrors pallet_pose_node.cpp::stamp_to_string exactly, so this is
    the one join-key format used by both the success (rich pose) and
    failure (diagnostics) paths in eval_recorder_node.py."""
    return f"{sec}.{nanosec:09d}"


def stamp_from_ns(stamp_ns: int) -> Time:
    sec, nanosec = divmod(stamp_ns, NS_PER_S)
    return Time(sec=int(sec), nanosec=int(nanosec))


def make_image_msg(array: np.ndarray, encoding: str, stamp: Time, frame_id: str) -> Image:
    msg = Image()
    msg.header.stamp = stamp
    msg.header.frame_id = frame_id
    msg.height = int(array.shape[0])
    msg.width = int(array.shape[1])
    msg.encoding = encoding
    msg.is_bigendian = 0
    if encoding == "16UC1":
        msg.step = msg.width * 2
        msg.data = np.ascontiguousarray(array, dtype="<u2").tobytes()
    elif encoding in ("bgr8", "rgb8"):
        msg.step = msg.width * 3
        msg.data = np.ascontiguousarray(array, dtype=np.uint8).tobytes()
    else:
        raise ValueError(f"unsupported encoding {encoding!r}")
    return msg


def _topic_metadata(name: str, msg_type: str) -> "rosbag2_py.TopicMetadata":
    """rosbag2_py.TopicMetadata's constructor gained a leading ``id`` field
    on some ROS2 distros (Iron+), and ``offered_qos_profiles`` is typed as
    ``List[rosbag2_py.QoS]`` (not a YAML string) on those same distros --
    an empty list means "let ros2 bag play use its own default QoS," which
    is what we want. Try the newer signature first and fall back to the
    older ``id``-less one so this script works across distros without
    needing to know which one is installed."""
    try:
        return rosbag2_py.TopicMetadata(
            id=0, name=name, type=msg_type, serialization_format="cdr", offered_qos_profiles=[]
        )
    except TypeError:
        return rosbag2_py.TopicMetadata(
            name=name, type=msg_type, serialization_format="cdr", offered_qos_profiles=""
        )


def load_depth_u16_mm(path: Path) -> np.ndarray:
    depth = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if depth is None:
        raise ValueError(f"failed to read depth image: {path}")
    if depth.ndim != 2:
        raise ValueError(f"expected single-channel depth image, got shape {depth.shape}: {path}")
    if depth.dtype != np.uint16:
        raise ValueError(
            f"expected uint16 (mm) depth PGM, got dtype={depth.dtype} for {path}; "
            "this bag builder writes 16UC1 verbatim, matching depth_utils.hpp's "
            "16UC1-times-depth_scale contract."
        )
    return depth


def load_rgb_bgr(path: Path) -> np.ndarray:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"failed to read RGB image: {path}")
    return bgr


def build_bag(args: argparse.Namespace) -> None:
    dataset_root = args.dataset_root.resolve()
    manifest_path = args.manifest.resolve() if args.manifest else (dataset_root / "manifest.csv")
    rows = erc.load_manifest(manifest_path)
    valid_rows = [row for row in rows if erc.bool_from_str(row.get("valid"))]
    if args.limit:
        valid_rows = valid_rows[: args.limit]
    if not valid_rows:
        raise ValueError(f"no valid samples found in {manifest_path}")

    out_uri = args.out.resolve()
    if out_uri.exists():
        raise FileExistsError(
            f"{out_uri} already exists; rosbag2 refuses to write into an existing bag "
            "directory -- remove it or pick a different --out"
        )

    storage_options = rosbag2_py.StorageOptions(uri=str(out_uri), storage_id="mcap")
    converter_options = rosbag2_py.ConverterOptions(
        input_serialization_format="cdr", output_serialization_format="cdr"
    )
    writer = rosbag2_py.SequentialWriter()
    writer.open(storage_options, converter_options)
    writer.create_topic(_topic_metadata(args.rgb_topic, "sensor_msgs/msg/Image"))
    writer.create_topic(_topic_metadata(args.depth_topic, "sensor_msgs/msg/Image"))

    period_ns = int(round(NS_PER_S / args.pace_hz))
    start_ns = int(args.start_time_s * NS_PER_S)

    stamp_map: dict[str, str] = {}
    written = 0
    for index, row in enumerate(valid_rows):
        sample_id = row["sample_id"]
        try:
            depth_path = erc.resolve_asset(dataset_root, row["depth_path"])
            rgb_path = erc.resolve_asset(dataset_root, row["rgb_path"])
            depth_u16 = load_depth_u16_mm(depth_path)
            rgb_bgr = load_rgb_bgr(rgb_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"[{index + 1}/{len(valid_rows)}] {sample_id}: skipped ({exc})", file=sys.stderr)
            continue

        stamp_ns = start_ns + index * period_ns
        stamp = stamp_from_ns(stamp_ns)

        rgb_msg = make_image_msg(rgb_bgr, "bgr8", stamp, args.frame_id)
        depth_msg = make_image_msg(depth_u16, "16UC1", stamp, args.frame_id)

        writer.write(args.rgb_topic, serialize_message(rgb_msg), stamp_ns)
        writer.write(args.depth_topic, serialize_message(depth_msg), stamp_ns)

        stamp_map[format_stamp(stamp.sec, stamp.nanosec)] = sample_id
        written += 1
        if args.progress:
            print(f"[{index + 1}/{len(valid_rows)}] {sample_id}: wrote @ stamp={stamp.sec}.{stamp.nanosec:09d}")

    # rosbag2_py.SequentialWriter has no public close(): the storage plugin
    # flushes and finalizes metadata.yaml when the writer object is
    # destroyed. Dropping the reference here (falling out of scope at
    # function return) is the documented way to finalize the bag.
    del writer

    sidecar_dir = out_uri if out_uri.is_dir() else out_uri.parent
    (sidecar_dir / "stamp_map.json").write_text(json.dumps(stamp_map, indent=2), encoding="utf-8")

    meta: dict[str, Any] = {
        "dataset_root": str(dataset_root),
        "manifest_path": str(manifest_path),
        "rgb_topic": args.rgb_topic,
        "depth_topic": args.depth_topic,
        "frame_id": args.frame_id,
        "pace_hz": args.pace_hz,
        "start_time_s": args.start_time_s,
        "n_samples": written,
        "total_duration_s": written * (period_ns / NS_PER_S),
    }
    (sidecar_dir / "bag_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(
        f"wrote {written}/{len(valid_rows)} samples to {out_uri} "
        f"({meta['total_duration_s']:.1f} s @ {args.pace_hz} Hz); "
        f"stamp_map.json + bag_meta.json written to {sidecar_dir}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True, help="eval_dataset_combined root")
    parser.add_argument("--manifest", type=Path, default=None, help="defaults to <dataset-root>/manifest.csv")
    parser.add_argument("--out", type=Path, required=True, help="bag URI (becomes a directory, e.g. dataset_bag/)")
    parser.add_argument("--rgb-topic", default=DEFAULT_RGB_TOPIC)
    parser.add_argument("--depth-topic", default=DEFAULT_DEPTH_TOPIC)
    parser.add_argument("--frame-id", default=DEFAULT_FRAME_ID)
    parser.add_argument("--pace-hz", type=float, default=1.0, help="samples per second at ros2 bag play rate=1.0")
    parser.add_argument("--start-time-s", type=float, default=1_700_000_000.0, help="synthetic base epoch for sample 0's stamp")
    parser.add_argument("--limit", type=int, default=0, help="only build the first N valid samples (for smoke tests)")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()
    build_bag(args)


if __name__ == "__main__":
    main()
