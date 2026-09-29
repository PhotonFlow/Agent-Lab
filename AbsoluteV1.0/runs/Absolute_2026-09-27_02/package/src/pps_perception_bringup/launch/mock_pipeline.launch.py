"""Mock end-to-end pipeline (no engine, no sensor).

Brings up: synthetic scene publisher -> mock-backend RT-DETR detector (bbox set
to the projected synthetic face) -> chamfer stage-2. Useful for CI, demos, and
validating wiring before a trained engine exists. The node graph is defined in
``pps_perception_bringup.pipeline_nodes`` and shared with the launch test.
"""

from launch import LaunchDescription

from pps_perception_bringup.pipeline_nodes import mock_pipeline_nodes


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(mock_pipeline_nodes())
