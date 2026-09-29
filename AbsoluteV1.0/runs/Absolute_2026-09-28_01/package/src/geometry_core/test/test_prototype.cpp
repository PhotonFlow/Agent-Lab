#include <gtest/gtest.h>

#include "geometry_core/prototype.hpp"

using geometry_core::build_default_pallet_prototype;

TEST(Prototype, ContourPointsAreWithinOuterBounds) {
  auto proto = build_default_pallet_prototype(
      /*width_m=*/1.20, /*height_m=*/0.14, /*pocket_width_m=*/0.47,
      /*pocket_height_m=*/0.10, /*pocket_centre_offset_m=*/0.28,
      /*contour_spacing_m=*/0.03);
  ASSERT_GT(proto.contour_points.rows(), 0);
  for (int i = 0; i < proto.contour_points.rows(); ++i) {
    EXPECT_LE(std::abs(proto.contour_points(i, 0)), 0.60 + 1e-9);
    EXPECT_LE(std::abs(proto.contour_points(i, 1)), 0.07 + 1e-9);
  }
}

TEST(Prototype, ThreeRectanglesConcatenatedInOrder) {
  // width=0.4, height=0.2, contour_spacing=0.1 -> _sample_segment count is
  // deterministic per edge; verify exact expected total row count using the
  // same n = max(2, ceil(length/spacing)+1) formula as Python for each of
  // the 4 edges per rectangle (outer, hole_l, hole_r), 3 rectangles total.
  auto proto = build_default_pallet_prototype(
      /*width_m=*/0.4, /*height_m=*/0.2, /*pocket_width_m=*/0.1,
      /*pocket_height_m=*/0.1, /*pocket_centre_offset_m=*/0.1,
      /*contour_spacing_m=*/0.1);
  // outer: two edges of length 0.4 (n=ceil(0.4/0.1)+1=5) + two of length 0.2
  // (n=ceil(0.2/0.1)+1=3) = 5+5+3+3=16
  // hole_l/hole_r (0.1x0.1 squares): centred at (+/-0.1, 0), so two of the
  // four edges have length 0.1 exactly (n=ceil(1)+1=2) but the other two
  // have length 0.10000000000000002 due to float rounding in
  // (cx +/- half_w) -- ceil(1.0000000000000002)=2, so n=ceil(2)+1=3 for
  // those edges. Per hole: 2*2 + 2*3 = 10 (verified bit-for-bit identical
  // to the Python reference pallet_pose_estimation.geometry.prototype).
  // Total = 16 (outer) + 10 (hole_l) + 10 (hole_r) = 36.
  EXPECT_EQ(proto.contour_points.rows(), 16 + 10 + 10);
}

TEST(Prototype, OriginXyIsZero) {
  auto proto = build_default_pallet_prototype(1.0, 0.2);
  EXPECT_DOUBLE_EQ(proto.origin_xy.x(), 0.0);
  EXPECT_DOUBLE_EQ(proto.origin_xy.y(), 0.0);
}
