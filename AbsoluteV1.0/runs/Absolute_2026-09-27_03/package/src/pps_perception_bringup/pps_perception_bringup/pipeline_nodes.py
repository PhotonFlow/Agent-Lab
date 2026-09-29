"""Shared node construction for the mock pipeline.

Imported by both ``launch/mock_pipeline.launch.py`` and the launch test so the
exact same graph is described in one place.
"""

from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch_ros.actions import Node

from .synthetic_scene import face_bbox_rgb_from_yaml

RGB_TOPIC = "/camera/color/image_rect"
DEPTH_TOPIC = "/camera/depth/image_rect"
DETECTIONS_TOPIC = "/pps/detections"
POSE_TOPIC = "/pps/pallet_pose"
RICH_POSE_TOPIC = "/pps/pallet_pose_rich"
FRAME_ID = "camera_rgb_optical_frame"


def camera_yaml_path() -> str:
    share = get_package_share_directory("pps_perception_bringup")
    return os.path.join(share, "config", "camera.yaml")


def mock_pipeline_nodes() -> list[Node]:
    camera_yaml = camera_yaml_path()
    bbox = face_bbox_rgb_from_yaml(camera_yaml)

    scene = Node(
        package="pps_perception_bringup",
        executable="synthetic_scene_publisher",
        name="synthetic_scene_publisher",
        output="screen",
        parameters=[
            {
                "camera_yaml_path": camera_yaml,
                "rgb_topic": RGB_TOPIC,
                "depth_topic": DEPTH_TOPIC,
                "frame_id": FRAME_ID,
                "rate_hz": 10.0,
            }
        ],
    )
    detector = Node(
        package="pps_rtdetr_detector",
        executable="rtdetr_detector_node",
        name="rtdetr_detector_node",
        output="screen",
        parameters=[
            {
                "backend": "mock",
                "input_size": 640,
                "score_threshold": 0.5,
                "pallet_class_id": 0,
                "class_label": "pallet",
                "image_topic": RGB_TOPIC,
                "detections_topic": DETECTIONS_TOPIC,
                "image_qos": "reliable",
                "mock_bbox_xyxy": bbox,
                "mock_score": 0.95,
            }
        ],
    )
    pose = Node(
        package="pps_pallet_pose_cpp",
        executable="pallet_pose_cpp_node",
        name="pallet_pose_cpp_node",
        output="screen",
        parameters=[
            {
                "camera_yaml_path": camera_yaml,
                "target_class_id": "pallet",
                "detection_selection": "highest_confidence",
                "depth_topic": DEPTH_TOPIC,
                "detections_topic": DETECTIONS_TOPIC,
                "pose_topic": POSE_TOPIC,
                "pallet_pose_topic": RICH_POSE_TOPIC,
                "camera_frame_id": FRAME_ID,
            }
        ],
    )
    return [scene, detector, pose]
