"""Full mock-input pipeline launch test.

Brings up scene publisher -> mock RT-DETR detector -> chamfer stage-2 and
asserts a pose is published on ``/pps/pallet_pose`` with a plausible range
(tz ~ 2 m, the synthetic pallet distance) within a timeout.

Run with: ``launch_test src/pps_perception_bringup/test/test_full_pipeline_launch.py``
or via ``colcon test``.
"""

import time
import unittest

import numpy as np
import pytest
import rclpy
from geometry_msgs.msg import PoseStamped
from launch import LaunchDescription
from launch_testing.actions import ReadyToTest

from pps_perception_bringup.pipeline_nodes import POSE_TOPIC, mock_pipeline_nodes


@pytest.mark.launch_test
def generate_test_description():
    return LaunchDescription([*mock_pipeline_nodes(), ReadyToTest()])


class TestMockPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()

    @classmethod
    def tearDownClass(cls):
        rclpy.shutdown()

    def setUp(self):
        self.node = rclpy.create_node("mock_pipeline_test_listener")

    def tearDown(self):
        self.node.destroy_node()

    def test_pose_published_with_plausible_range(self):
        received = []
        self.node.create_subscription(
            PoseStamped, POSE_TOPIC, lambda m: received.append(m), 10
        )

        deadline = time.time() + 40.0
        while time.time() < deadline and not received:
            rclpy.spin_once(self.node, timeout_sec=0.2)

        self.assertTrue(received, f"no PoseStamped received on {POSE_TOPIC} within timeout")
        pose = received[-1].pose
        x, y, z = pose.position.x, pose.position.y, pose.position.z
        self.assertTrue(np.isfinite([x, y, z]).all(), f"non-finite pose: {x}, {y}, {z}")
        # Synthetic pallet is frontal at tz = 2.0 m.
        self.assertTrue(1.5 < z < 2.5, f"implausible tz={z:.3f} (expected ~2.0 m)")
        self.assertLess(abs(x), 0.20, f"implausible tx={x:.3f}")
        self.assertLess(abs(y), 0.20, f"implausible ty={y:.3f}")
