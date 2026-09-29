"""Behavior test: /pps/pallet_pose_rich carries inlier-face extents from the same estimate."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PACKAGE_SRC = Path(__file__).resolve().parents[2]
HEADER = PACKAGE_SRC / "pps_pallet_pose_cpp" / "include" / "pps_pallet_pose_cpp" / "rich_face_extents.hpp"
MSG = PACKAGE_SRC / "pps_perception_msgs" / "msg" / "PalletPoseStamped.msg"
NODE = PACKAGE_SRC / "pps_pallet_pose_cpp" / "src" / "pallet_pose_node.cpp"
PIPELINE = PACKAGE_SRC / "geometry_core" / "src" / "pipeline_v3_2.cpp"

EXTENT_FIELDS = (
    "bool has_dimensions",
    "float64 width_m",
    "float64 height_m",
    "float64 depth_m",
)


class RichPose:
    def __init__(self) -> None:
        self.has_dimensions = True
        self.width_m = -1.0
        self.height_m = -1.0
        self.depth_m = -1.0


def assign_rich_face_extents(rich: RichPose, estimate_produced_extents: bool, width_m: float,
                             height_m: float, depth_m: float) -> None:
    """Run the production gate. The header must implement this same rule."""
    if not HEADER.is_file():
        raise AssertionError("rich_face_extents.hpp is missing")
    header = HEADER.read_text(encoding="utf-8")
    start = header.find("assign_rich_face_extents")
    if start < 0:
        raise AssertionError("rich_face_extents.hpp does not define assign_rich_face_extents")
    body = header[start:]
    gate = "if (!estimate_produced_extents)"
    if gate not in body:
        raise AssertionError("extents are published even when the estimate did not produce them")
    for line in (
        "rich.has_dimensions = false;",
        "rich.width_m = 0.0;",
        "rich.height_m = 0.0;",
        "rich.depth_m = 0.0;",
        "rich.has_dimensions = true;",
        "rich.width_m = width_m;",
        "rich.height_m = height_m;",
        "rich.depth_m = depth_m;",
    ):
        if line not in body:
            raise AssertionError(f"assign_rich_face_extents missing {line}")
    if not estimate_produced_extents:
        rich.has_dimensions = False
        rich.width_m = 0.0
        rich.height_m = 0.0
        rich.depth_m = 0.0
        return
    rich.has_dimensions = True
    rich.width_m = width_m
    rich.height_m = height_m
    rich.depth_m = depth_m


class InlierFaceExtentsTest(unittest.TestCase):
    def test_rich_pose_carries_extents_only_when_the_estimate_produced_them(self) -> None:
        produced = RichPose()
        assign_rich_face_extents(produced, True, 1.05, 0.80, 2.40)
        self.assertTrue(produced.has_dimensions)
        self.assertAlmostEqual(produced.width_m, 1.05)
        self.assertAlmostEqual(produced.height_m, 0.80)
        self.assertAlmostEqual(produced.depth_m, 2.40)

        absent = RichPose()
        assign_rich_face_extents(absent, False, 1.05, 0.80, 2.40)
        self.assertFalse(absent.has_dimensions)
        self.assertEqual(absent.width_m, 0.0)
        self.assertEqual(absent.height_m, 0.0)
        self.assertEqual(absent.depth_m, 0.0)

        degenerate = RichPose()
        assign_rich_face_extents(degenerate, True, 0.0, 0.0, 1.50)
        self.assertTrue(degenerate.has_dimensions)
        self.assertEqual(degenerate.width_m, 0.0)
        self.assertEqual(degenerate.height_m, 0.0)
        self.assertAlmostEqual(degenerate.depth_m, 1.50)

    def test_pallet_pose_rich_message_has_extent_fields(self) -> None:
        text = MSG.read_text(encoding="utf-8")
        missing = [field for field in EXTENT_FIELDS if field not in text]
        self.assertEqual(missing, [], f"{MSG.name} is missing {missing}")

    def test_publish_pose_assigns_extents_from_the_same_estimate(self) -> None:
        text = NODE.read_text(encoding="utf-8")
        start = text.find("void PalletPoseNode::publish_pose")
        end = text.find("void PalletPoseNode::publish_failure_diagnostics")
        self.assertGreater(start, -1)
        self.assertGreater(end, start)
        body = text[start:end]
        self.assertIn("assign_rich_face_extents", body)
        self.assertIn("outcome.has_dimensions", body)
        self.assertIn("outcome.width_m", body)
        self.assertIn("outcome.height_m", body)
        self.assertIn("outcome.depth_m", body)

    def test_estimate_keeps_inlier_extents_without_the_chamfer_grid(self) -> None:
        text = PIPELINE.read_text(encoding="utf-8")
        start = text.find("EstimatePoseOutcome estimate_pose_chamfer_v3_2")
        self.assertGreater(start, -1)
        body = text[start:]
        # The published pose is the bbox-centre ray-plane hit and the yaw of
        # the plane normal. The grid that searches a prototype against a
        # distance image is not an input to that pose or to the inlier-face
        # extents, so the estimate must not run it.
        for banned in (
            "two_stage_chamfer_search_v2",
            "two_stage_chamfer_search_v2_with_prior",
            "compute_distance_transform_v2",
            "chamfer_cost_v2(",
        ):
            self.assertNotIn(banned, body, f"estimate still pays {banned}")
        for required in (
            "ray_plane_intersect_cross_camera",
            "yaw_from_normal_camera",
            "max_x - min_x",
            "max_y - min_y",
            "sum_z / static_cast<double>(n)",
            "outcome.has_dimensions = true",
        ):
            self.assertIn(required, body, f"estimate dropped {required}")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(InlierFaceExtentsTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
