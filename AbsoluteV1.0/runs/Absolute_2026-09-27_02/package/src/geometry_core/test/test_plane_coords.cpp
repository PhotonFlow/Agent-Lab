#include <gtest/gtest.h>

#include "geometry_core/plane_coords.hpp"
#include "geometry_core/plane_fit.hpp"

using geometry_core::build_plane_basis_deterministic;
using geometry_core::lift_point_from_plane_2d;
using geometry_core::lift_points_from_plane_2d;
using geometry_core::Plane;
using geometry_core::project_points_to_plane_2d;

TEST(PlaneCoords, DeterministicBasisMatchesWorkedExample) {
  // Worked example from the design spec: normal=(0,0,-1), offset=2
  // -> origin=(0,0,2), axis_u=(0,-1,0), axis_v=(-1,0,0).
  Plane plane{Eigen::Vector3d(0.0, 0.0, -1.0), 2.0, 1.0, 100};
  auto basis = build_plane_basis_deterministic(plane);
  EXPECT_NEAR(basis.origin_3d.x(), 0.0, 1e-9);
  EXPECT_NEAR(basis.origin_3d.y(), 0.0, 1e-9);
  EXPECT_NEAR(basis.origin_3d.z(), 2.0, 1e-9);
  EXPECT_NEAR(basis.axis_u.x(), 0.0, 1e-9);
  EXPECT_NEAR(basis.axis_u.y(), -1.0, 1e-9);
  EXPECT_NEAR(basis.axis_u.z(), 0.0, 1e-9);
  EXPECT_NEAR(basis.axis_v.x(), -1.0, 1e-9);
  EXPECT_NEAR(basis.axis_v.y(), 0.0, 1e-9);
  EXPECT_NEAR(basis.axis_v.z(), 0.0, 1e-9);
}

TEST(PlaneCoords, ProjectAndLiftRoundTrip) {
  Plane plane{Eigen::Vector3d(0.0, 0.0, -1.0), 2.0, 1.0, 100};
  auto basis = build_plane_basis_deterministic(plane);
  Eigen::MatrixXd pts3d(3, 3);
  pts3d << 0.1, 0.2, 2.0,
          -0.3, 0.05, 2.0,
           0.0, 0.0, 2.0;
  Eigen::MatrixXd pts2d = project_points_to_plane_2d(pts3d, basis);
  Eigen::MatrixXd back3d = lift_points_from_plane_2d(pts2d, basis);
  for (int i = 0; i < 3; ++i) {
    EXPECT_NEAR(back3d(i, 0), pts3d(i, 0), 1e-9);
    EXPECT_NEAR(back3d(i, 1), pts3d(i, 1), 1e-9);
    EXPECT_NEAR(back3d(i, 2), pts3d(i, 2), 1e-9);
  }
}

TEST(PlaneCoords, LiftSinglePointMatchesBatchRow) {
  Plane plane{Eigen::Vector3d(0.0, 0.0, -1.0), 2.0, 1.0, 100};
  auto basis = build_plane_basis_deterministic(plane);
  Eigen::Vector2d p2d(0.15, -0.05);
  Eigen::Vector3d single = lift_point_from_plane_2d(p2d, basis);
  Eigen::MatrixXd batch(1, 2);
  batch(0, 0) = p2d.x();
  batch(0, 1) = p2d.y();
  Eigen::MatrixXd batch_out = lift_points_from_plane_2d(batch, basis);
  EXPECT_NEAR(single.x(), batch_out(0, 0), 1e-12);
  EXPECT_NEAR(single.y(), batch_out(0, 1), 1e-12);
  EXPECT_NEAR(single.z(), batch_out(0, 2), 1e-12);
}

TEST(PlaneCoords, UpHintNearlyParallelToNormalFallsBackToXAxis) {
  // normal close to (0,-1,0): default up_hint (0,-1,0) is nearly parallel
  // (|dot| > 0.95), so the implementation must fall back to (1,0,0).
  Plane plane{Eigen::Vector3d(0.0, -0.999, -0.0447), 1.0, 1.0, 100};
  auto basis = build_plane_basis_deterministic(plane);
  // axis_u must still be unit length and orthogonal to normal.
  EXPECT_NEAR(basis.axis_u.norm(), 1.0, 1e-9);
  EXPECT_NEAR(basis.axis_u.dot(basis.normal), 0.0, 1e-9);
}
