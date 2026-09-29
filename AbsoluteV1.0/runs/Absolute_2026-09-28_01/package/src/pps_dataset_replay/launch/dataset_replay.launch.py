"""Dataset-replay pipeline: rtdetr_detector_node -> pallet_pose_cpp_node ->
eval_recorder_node.

Brings up the same two production nodes as
``pps_perception_bringup``'s ``full_pipeline.launch.py`` (the detector and
the C++ Stage-2 node), plus ``eval_recorder_node`` which joins their output
back to ``eval_dataset_combined``'s ground truth. A pre-built rosbag2
(``pps_dataset_replay build_bag``) stands in for the camera driver --
``ros2 bag play`` it separately (see ``scripts/run_replay.sh``) once this
launch file reports both nodes are up.

The detector's image subscription QoS is forced to "reliable" here
(overriding ``detector.yaml``'s "sensor"/best-effort default) so bag
playback is delivered deterministically, matching the same override
``pps_perception_bringup``'s mock pipeline already applies.

Required launch arguments: ``dataset_root``, ``replay_meta_dir``,
``output_dir`` (see ``scripts/run_replay.sh`` for a full example).
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    bringup_share = get_package_share_directory("pps_perception_bringup")
    default_detector_params = os.path.join(bringup_share, "config", "detector.yaml")
    default_pose_params = os.path.join(bringup_share, "config", "pallet_pose_cpp.yaml")

    args = [
        DeclareLaunchArgument("dataset_root", description="eval_dataset_combined root used to build the replayed bag"),
        DeclareLaunchArgument("replay_meta_dir", description="directory containing stamp_map.json/bag_meta.json (build_bag.py's --out)"),
        DeclareLaunchArgument("output_dir", description="where eval_recorder_node writes per_sample_errors.csv/report.md/overlays"),
        DeclareLaunchArgument("manifest_path", default_value="", description="defaults to <dataset_root>/manifest.csv"),
        DeclareLaunchArgument(
            "camera_yaml_path",
            default_value=PathJoinSubstitution([LaunchConfiguration("dataset_root"), "camera_rectified.yaml"]),
            description="must match the calibration the dataset's GT/images were captured under -- NOT the production config/camera.yaml",
        ),
        DeclareLaunchArgument("detector_params", default_value=default_detector_params),
        DeclareLaunchArgument("pose_params", default_value=default_pose_params),
        DeclareLaunchArgument("rgb_topic", default_value="/camera/color/image_rect"),
        DeclareLaunchArgument("depth_topic", default_value="/camera/depth/image_rect"),
        DeclareLaunchArgument("detections_topic", default_value="/pps/detections"),
        DeclareLaunchArgument("pose_topic", default_value="/pps/pallet_pose_rich"),
        DeclareLaunchArgument("diagnostics_topic", default_value="/pps/pallet_pose_diagnostics"),
        DeclareLaunchArgument("target_class_id", default_value="pallet"),
        DeclareLaunchArgument("detection_selection", default_value="highest_confidence"),
        # geometry_core's built-in prototype defaults (EstimatePoseParams in
        # pipeline_v3_2.hpp) -- pallet_pose_cpp_node doesn't expose these as
        # ROS parameters (it always uses geometry_core's own defaults), so
        # these exist only to size the recorder's overlay quad to match.
        DeclareLaunchArgument("pallet_width_m", default_value="1.20"),
        DeclareLaunchArgument("pallet_height_m", default_value="0.14"),
        DeclareLaunchArgument("publish_live_overlay", default_value="true"),
        DeclareLaunchArgument("live_overlay_topic", default_value="/pps/debug/overlay_image"),
    ]

    detector_node = Node(
        package="pps_rtdetr_detector",
        executable="rtdetr_detector_node",
        name="rtdetr_detector_node",
        output="screen",
        parameters=[
            LaunchConfiguration("detector_params"),
            {
                "image_topic": LaunchConfiguration("rgb_topic"),
                "detections_topic": LaunchConfiguration("detections_topic"),
                # Override detector.yaml's "sensor" (best-effort) default --
                # bag playback must be delivered deterministically.
                "image_qos": "reliable",
            },
        ],
    )
    pose_node = Node(
        package="pps_pallet_pose_cpp",
        executable="pallet_pose_cpp_node",
        name="pallet_pose_cpp_node",
        output="screen",
        parameters=[
            LaunchConfiguration("pose_params"),
            {
                "camera_yaml_path": LaunchConfiguration("camera_yaml_path"),
                "target_class_id": LaunchConfiguration("target_class_id"),
                "detection_selection": LaunchConfiguration("detection_selection"),
                "depth_topic": LaunchConfiguration("depth_topic"),
                "detections_topic": LaunchConfiguration("detections_topic"),
                "pallet_pose_topic": LaunchConfiguration("pose_topic"),
                "diagnostics_topic": LaunchConfiguration("diagnostics_topic"),
            },
        ],
    )
    recorder_node = Node(
        package="pps_dataset_replay",
        executable="eval_recorder_node",
        name="eval_recorder_node",
        output="screen",
        parameters=[
            {
                "dataset_root": LaunchConfiguration("dataset_root"),
                "manifest_path": LaunchConfiguration("manifest_path"),
                "camera_yaml_path": LaunchConfiguration("camera_yaml_path"),
                "replay_meta_dir": LaunchConfiguration("replay_meta_dir"),
                "output_dir": LaunchConfiguration("output_dir"),
                "detections_topic": LaunchConfiguration("detections_topic"),
                "pose_topic": LaunchConfiguration("pose_topic"),
                "diagnostics_topic": LaunchConfiguration("diagnostics_topic"),
                "target_class_id": LaunchConfiguration("target_class_id"),
                "detection_selection": LaunchConfiguration("detection_selection"),
                "pallet_width_m": LaunchConfiguration("pallet_width_m"),
                "pallet_height_m": LaunchConfiguration("pallet_height_m"),
                "publish_live_overlay": LaunchConfiguration("publish_live_overlay"),
                "live_overlay_topic": LaunchConfiguration("live_overlay_topic"),
            }
        ],
    )

    return LaunchDescription([*args, detector_node, pose_node, recorder_node])
