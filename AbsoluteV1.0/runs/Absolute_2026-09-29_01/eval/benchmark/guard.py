"""Independent checks for the analytical pose oracle.

Does not compile or score the candidate.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import oracle


class OracleTests(unittest.TestCase):
    def test_lever_arm_is_the_box_half_width_at_the_true_plane(self):
        self.assertAlmostEqual(oracle.yaw_lever_arm_m(), 300.0 / 900.0 * 2.0)
        self.assertAlmostEqual(oracle.yaw_lever_arm_m(), 2.0 / 3.0)

    def test_exact_ground_truth_has_zero_error(self):
        error = oracle.pose_error_m(0.0, 0.0, 2.0, 0.0, True)
        self.assertEqual(error, 0.0)

    def test_translation_error_is_euclidean_metres(self):
        error = oracle.pose_error_m(0.0, 0.03, 2.04, 0.0, True)
        self.assertAlmostEqual(error, math.hypot(0.03, 0.04))

    def test_yaw_uses_the_lever_arm_and_wraps(self):
        arm = oracle.yaw_lever_arm_m()
        error = oracle.pose_error_m(0.0, 0.0, 2.0, 0.3, True)
        self.assertAlmostEqual(error, 0.3 * arm)
        wrapped = oracle.pose_error_m(0.0, 0.0, 2.0, 2.0 * math.pi + 0.3, True)
        self.assertAlmostEqual(wrapped, error)

    def test_rejection_scores_the_depth_gate(self):
        self.assertEqual(oracle.FAILURE_PENALTY_M, 5.0)
        rejected = oracle.pose_error_m(0.0, 0.0, 2.0, 0.0, False)
        self.assertGreater(rejected, oracle.pose_error_m(0.15, 0.15, 2.15, 0.05, True))

    def test_scene_header_carries_the_same_construction(self):
        header = oracle.scene_header()
        self.assertIn("constexpr double kPlaneZM = 2;", header)
        self.assertIn("constexpr double kBboxHalfWidthPx = 300;", header)
        self.assertIn("constexpr double kRgbFx = 900;", header)
        self.assertIn("constexpr int kDepthWidth = 640;", header)

    def test_case_id_is_stable(self):
        self.assertEqual(oracle.CASE_ID, "synthetic_fronto_parallel")


if __name__ == "__main__":
    unittest.main()
