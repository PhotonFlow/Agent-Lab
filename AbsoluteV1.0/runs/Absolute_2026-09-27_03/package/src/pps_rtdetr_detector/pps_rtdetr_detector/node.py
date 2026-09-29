"""ROS2 node: RT-DETRv2 stage-1 detector wrapper.

Subscribes an RGB ``Image``, runs the detector (TensorRT or mock backend), and
publishes ``vision_msgs/Detection2DArray`` stamped with the *input image header*
so the stage-2 node can time-sync detections against the depth stream and reuse
the camera frame.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from pps_rtdetr_detector.image_conversions import image_to_rgb
from pps_rtdetr_detector.rtdetr import MockBackend, RtDetrDetector, load_tensorrt_backend
from pps_rtdetr_detector.rtdetr.types import Detection

try:  # pragma: no cover - ROS runtime only
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image
    from vision_msgs.msg import (
        BoundingBox2D,
        Detection2D,
        Detection2DArray,
        ObjectHypothesisWithPose,
    )
except ImportError:  # pragma: no cover
    rclpy = None
    Node = object
    qos_profile_sensor_data = None
    Image = Detection2D = Detection2DArray = BoundingBox2D = ObjectHypothesisWithPose = None


class RtDetrDetectorNode(Node):  # pragma: no cover - exercised via launch test
    def __init__(self):
        super().__init__("rtdetr_detector_node")

        self.declare_parameter("backend", "mock")  # mock | tensorrt
        self.declare_parameter("engine_path", "")
        self.declare_parameter("input_size", 640)
        self.declare_parameter("score_threshold", 0.5)
        self.declare_parameter("pallet_class_id", 0)
        self.declare_parameter("class_label", "pallet")
        self.declare_parameter("max_detections", 10)
        self.declare_parameter("image_topic", "/camera/color/image_raw")
        self.declare_parameter("detections_topic", "/pps/detections")
        self.declare_parameter("image_qos", "reliable")  # reliable | sensor
        # Mock backend configuration (used only when backend == mock).
        self.declare_parameter("mock_bbox_xyxy", [0.0, 0.0, 0.0, 0.0])
        self.declare_parameter("mock_score", 0.95)

        backend_kind = self._str_param("backend")
        input_size = int(self.get_parameter("input_size").value)
        self._class_label = self._str_param("class_label")
        self._pallet_class_id = int(self.get_parameter("pallet_class_id").value)

        backend = self._build_backend(backend_kind, input_size)
        self._detector = RtDetrDetector(
            backend,
            score_threshold=float(self.get_parameter("score_threshold").value),
            pallet_class_id=self._pallet_class_id,
            max_detections=int(self.get_parameter("max_detections").value),
        )

        qos = qos_profile_sensor_data if self._str_param("image_qos") == "sensor" else 10
        self._pub = self.create_publisher(Detection2DArray, self._str_param("detections_topic"), 10)
        self.create_subscription(Image, self._str_param("image_topic"), self._on_image, qos)
        self.get_logger().info(
            f"rtdetr_detector_node up: backend={backend_kind}, input={input_size}, "
            f"class_id={self._pallet_class_id} ('{self._class_label}')"
        )

    def _str_param(self, name: str) -> str:
        return self.get_parameter(name).get_parameter_value().string_value

    def _build_backend(self, kind: str, input_size: int):
        if kind == "mock":
            bbox = [float(v) for v in self.get_parameter("mock_bbox_xyxy").value]
            score = float(self.get_parameter("mock_score").value)
            if len(bbox) == 4 and any(abs(v) > 1e-9 for v in bbox):
                boxes = [bbox]
                scores = [score]
                labels = [self._pallet_class_id]
            else:
                boxes, scores, labels = None, None, None  # placeholder box
            return MockBackend(
                input_size=input_size, boxes_xyxy=boxes, scores=scores, labels=labels
            )
        if kind == "tensorrt":
            engine_path = self._str_param("engine_path")
            if not engine_path:
                raise ValueError("engine_path is required when backend=tensorrt")
            return load_tensorrt_backend(engine_path, input_size=input_size)
        raise ValueError(f"Unknown backend: {kind!r}")

    def _on_image(self, msg: Any) -> None:
        try:
            rgb = image_to_rgb(msg)
        except ValueError as exc:
            self.get_logger().warning(str(exc))
            return
        t0 = time.perf_counter()
        detections = self._detector.detect(rgb)
        dt_ms = (time.perf_counter() - t0) * 1e3

        out = Detection2DArray()
        out.header = msg.header
        out.detections = [self._to_detection2d(det, msg.header) for det in detections]
        self._pub.publish(out)
        self.get_logger().debug(f"published {len(detections)} detection(s) in {dt_ms:.1f} ms")

    def _to_detection2d(self, det: Detection, header: Any) -> Any:
        d = Detection2D()
        d.header = header
        x1, y1, x2, y2 = (float(v) for v in det.bbox_xyxy)
        bbox = BoundingBox2D()
        bbox.center.position.x = 0.5 * (x1 + x2)
        bbox.center.position.y = 0.5 * (y1 + y2)
        bbox.center.theta = 0.0
        bbox.size_x = abs(x2 - x1)
        bbox.size_y = abs(y2 - y1)
        d.bbox = bbox
        hyp = ObjectHypothesisWithPose()
        hyp.hypothesis.class_id = self._class_label
        hyp.hypothesis.score = float(det.score)
        d.results = [hyp]
        return d


def main(args: list[str] | None = None) -> None:  # pragma: no cover - ROS runtime
    if rclpy is None:
        raise RuntimeError("rclpy is not available in this environment")
    rclpy.init(args=args)
    node = RtDetrDetectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
