#include <random>

#include <gtest/gtest.h>

#include "geometry_core/plane_fit.hpp"

using geometry_core::orient_normal_toward_camera;
using geometry_core::plane_inlier_mask;
using geometry_core::Plane;
using geometry_core::ransac_plane_fit;
using geometry_core::svd_plane_refit;

namespace {
// z = 2.0 plane, 200 points on a 10x10 cm grid with 8 outliers spiked in z.
Eigen::MatrixXd make_noisy_plane_points() {
  const int grid = 14;  // 196 inlier points
  Eigen::MatrixXd pts(grid * grid + 4, 3);
  int row = 0;
  for (int i = 0; i < grid; ++i) {
    for (int j = 0; j < grid; ++j) {
      pts(row, 0) = -0.065 + 0.01 * i;
      pts(row, 1) = -0.065 + 0.01 * j;
      pts(row, 2) = 2.0;
      ++row;
    }
  }
  // Gross outliers, far from the z=2.0 plane.
  const double outlier_z[4] = {2.5, 1.5, 2.8, 1.2};
  for (int k = 0; k < 4; ++k) {
    pts(row, 0) = 0.0;
    pts(row, 1) = 0.0;
    pts(row, 2) = outlier_z[k];
    ++row;
  }
  return pts;
}
}  // namespace

TEST(PlaneFit, SvdRefitRecoversFlatPlane) {
  Eigen::MatrixXd pts(4, 3);
  pts << -0.1, -0.1, 2.0,
          0.1, -0.1, 2.0,
          0.1,  0.1, 2.0,
         -0.1,  0.1, 2.0;
  Plane plane = svd_plane_refit(pts);
  // Normal must be parallel to +/-z; offset must satisfy n.z*2.0 + offset == 0.
  EXPECT_NEAR(std::abs(plane.normal.z()), 1.0, 1e-9);
  EXPECT_NEAR(plane.normal.z() * 2.0 + plane.offset, 0.0, 1e-9);
}

TEST(PlaneFit, RansacRecoversPlaneDespiteOutliers) {
  Eigen::MatrixXd pts = make_noisy_plane_points();
  std::mt19937_64 rng(0);
  Plane plane = ransac_plane_fit(pts, /*inlier_threshold_m=*/0.005,
                                  /*max_iters=*/100,
                                  /*early_stop_inlier_ratio=*/0.85, rng);
  EXPECT_GE(plane.n_inliers, 190);
  EXPECT_NEAR(std::abs(plane.normal.z()), 1.0, 1e-6);
  EXPECT_NEAR(std::abs(plane.normal.z() * 2.0 + plane.offset), 0.0, 1e-6);
}

TEST(PlaneFit, OrientNormalTowardCameraFlipsPositiveZ) {
  Plane plane{Eigen::Vector3d(0.0, 0.0, 1.0), -2.0, 1.0, 100};
  Plane oriented = orient_normal_toward_camera(plane);
  EXPECT_NEAR(oriented.normal.z(), -1.0, 1e-12);
  EXPECT_NEAR(oriented.offset, 2.0, 1e-12);
}

TEST(PlaneFit, OrientNormalTowardCameraKeepsNegativeZ) {
  Plane plane{Eigen::Vector3d(0.0, 0.0, -1.0), 2.0, 1.0, 100};
  Plane oriented = orient_normal_toward_camera(plane);
  EXPECT_NEAR(oriented.normal.z(), -1.0, 1e-12);
  EXPECT_NEAR(oriented.offset, 2.0, 1e-12);
}

TEST(PlaneFit, PlaneInlierMaskFlagsOutliers) {
  Eigen::MatrixXd pts = make_noisy_plane_points();
  Plane plane{Eigen::Vector3d(0.0, 0.0, -1.0), 2.0, 1.0, 0};
  auto mask = plane_inlier_mask(pts, plane, 0.005);
  EXPECT_EQ(mask.size(), pts.rows());
  for (int i = 0; i < mask.size() - 4; ++i) {
    EXPECT_TRUE(mask(i));
  }
  for (int i = mask.size() - 4; i < mask.size(); ++i) {
    EXPECT_FALSE(mask(i));
  }
}
