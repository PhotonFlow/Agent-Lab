"""ROS2 dataset-replay evaluation tool for pps_pallet_pose_cpp / geometry_core.

Replays ``eval_dataset_combined`` through the real ``rtdetr_detector_node`` +
``pallet_pose_cpp_node`` graph via a pre-built rosbag2, joins results back to
ground truth by timestamp, and renders per-sample bbox/pose/GT overlays --
see ``build_bag.py`` and ``eval_recorder_node.py``.
"""
