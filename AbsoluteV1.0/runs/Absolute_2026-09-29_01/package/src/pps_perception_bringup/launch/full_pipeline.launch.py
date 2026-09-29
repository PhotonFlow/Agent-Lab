"""Full production pipeline: RT-DETRv2 (TensorRT) -> geometry_core chamfer stage-2 (C++).

Set the engine path in ``config/detector.yaml`` (``engine_path``) and point your
camera driver at the configured RGB/depth topics. The camera calibration is the
vendored ``config/camera.yaml`` (rectified pinhole).
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    share = get_package_share_directory("pps_perception_bringup")
    camera_yaml = os.path.join(share, "config", "camera.yaml")
    detector_params = os.path.join(share, "config", "detector.yaml")
    pose_params = os.path.join(share, "config", "pallet_pose_cpp.yaml")

    detector_node = Node(
        package="pps_rtdetr_detector",
        executable="rtdetr_detector_node",
        name="rtdetr_detector_node",
        output="screen",
        parameters=[detector_params],
    )
    pose_node = Node(
        package="pps_pallet_pose_cpp",
        executable="pallet_pose_cpp_node",
        name="pallet_pose_cpp_node",
        output="screen",
        parameters=[pose_params, {"camera_yaml_path": camera_yaml}],
    )
    return LaunchDescription([detector_node, pose_node])
