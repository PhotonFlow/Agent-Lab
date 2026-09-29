"""Publish a synthetic RGB + depth pallet scene for mock end-to-end testing.

Publishes a neutral RGB image and a depth image (16UC1, mm) of a known frontal
pallet at ``TZ_M`` on a fixed timer, both stamped with the same time and frame
so the stage-2 ApproximateTime sync matches them. Paired with the mock-backend
detector (whose bbox is set to the projected face) this drives the whole
pipeline without a trained model or a real sensor.
"""

from __future__ import annotations

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image

from pps_perception_bringup.synthetic_scene import (
    TZ_M,
    load_camera,
    make_rgb,
    render_depth_mm,
)


def _image_msg(array: np.ndarray, encoding: str, stamp, frame_id: str) -> Image:
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
    elif encoding == "rgb8":
        msg.step = msg.width * 3
        msg.data = np.ascontiguousarray(array, dtype=np.uint8).tobytes()
    else:
        raise ValueError(f"unsupported encoding {encoding}")
    return msg


class ScenePublisher(Node):
    def __init__(self):
        super().__init__("synthetic_scene_publisher")
        self.declare_parameter("camera_yaml_path", "")
        self.declare_parameter("rgb_topic", "/camera/color/image_rect")
        self.declare_parameter("depth_topic", "/camera/depth/image_rect")
        self.declare_parameter("frame_id", "camera_rgb_optical_frame")
        self.declare_parameter("rate_hz", 10.0)
        self.declare_parameter("tz_m", TZ_M)

        camera_yaml = self.get_parameter("camera_yaml_path").get_parameter_value().string_value
        if not camera_yaml:
            raise ValueError("camera_yaml_path is required")
        self._cam = load_camera(camera_yaml)
        self._frame_id = self.get_parameter("frame_id").get_parameter_value().string_value
        tz = float(self.get_parameter("tz_m").value)

        self._depth_mm = render_depth_mm(self._cam, tz=tz)
        self._rgb = make_rgb(self._cam)

        self._rgb_pub = self.create_publisher(
            Image, self.get_parameter("rgb_topic").get_parameter_value().string_value, 10
        )
        self._depth_pub = self.create_publisher(
            Image, self.get_parameter("depth_topic").get_parameter_value().string_value, 10
        )
        period = 1.0 / max(1e-3, float(self.get_parameter("rate_hz").value))
        self.create_timer(period, self._tick)
        self.get_logger().info(
            f"synthetic_scene_publisher up: frontal pallet at tz={tz:.2f} m, "
            f"depth={self._depth_mm.shape}, rgb={self._rgb.shape}"
        )

    def _tick(self) -> None:
        stamp = self.get_clock().now().to_msg()
        self._rgb_pub.publish(_image_msg(self._rgb, "rgb8", stamp, self._frame_id))
        self._depth_pub.publish(_image_msg(self._depth_mm, "16UC1", stamp, self._frame_id))


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = ScenePublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
