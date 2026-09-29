#include <algorithm>
#include <cmath>
#include <vector>

#include <gtest/gtest.h>

#include "geometry_core/pca_init.hpp"

using geometry_core::choose_pi_ambiguous_pose;
using geometry_core::close_mask;
using geometry_core::compute_distance_transform_v2;
using geometry_core::estimate_pca_long_axis;
using geometry_core::extract_boundary_mask;
using geometry_core::make_pca_init_pose;
using geometry_core::PrototypePose2D;
using geometry_core::rasterize_points_to_mask;

namespace {
// See test_chamfer.cpp for why a 4-corner-only wireframe is too sparse for
// close_mask's keep_largest step (collapses to a single corner). Densely
// sample each edge instead.
Eigen::MatrixXd dense_rectangle_contour(double half_w, double half_h, double spacing_m) {
  Eigen::Matrix<double, 4, 2> corners;
  corners << -half_w, -half_h,
              half_w, -half_h,
              half_w,  half_h,
             -half_w,  half_h;
  std::vector<Eigen::Vector2d> pts;
  for (int i = 0; i < 4; ++i) {
    const Eigen::Vector2d p0 = corners.row(i).transpose();
    const Eigen::Vector2d p1 = corners.row((i + 1) % 4).transpose();
    const double length = (p1 - p0).norm();
    const int n = std::max(2, static_cast<int>(std::ceil(length / spacing_m)));
    for (int k = 0; k < n; ++k) {
      const double t = static_cast<double>(k) / static_cast<double>(n);
      pts.push_back(p0 + t * (p1 - p0));
    }
  }
  Eigen::MatrixXd out(static_cast<long>(pts.size()), 2);
  for (long i = 0; i < out.rows(); ++i) {
    out.row(i) = pts[static_cast<size_t>(i)].transpose();
  }
  return out;
}

// A plain rectangle (and even the real, pocket-aware pallet prototype -- its
// two pockets are identically sized and symmetrically placed) is exactly
// 180-degree rotationally symmetric, so theta and theta+pi always produce
// IDENTICAL chamfer cost and choose_pi_ambiguous_pose's comparison is always
// a tie (in production, disambiguation relies on asymmetry in the *observed*
// points, e.g. occlusion, not on the prototype's own shape). Append a small
// one-sided tab so this unit test has a genuine, non-tied signal to
// disambiguate on.
Eigen::MatrixXd add_asymmetric_tab(const Eigen::MatrixXd& base, double half_h,
                                    double spacing_m, double bump_m = 0.02) {
  const int n = std::max(2, static_cast<int>(std::ceil(bump_m / spacing_m)));
  std::vector<Eigen::Vector2d> tab;
  for (int k = 0; k <= n; ++k) {
    const double t = static_cast<double>(k) / static_cast<double>(n);
    tab.push_back(Eigen::Vector2d(0.0, half_h + t * bump_m));
  }
  Eigen::MatrixXd out(base.rows() + static_cast<long>(tab.size()), 2);
  out.topRows(base.rows()) = base;
  for (size_t i = 0; i < tab.size(); ++i) {
    out.row(base.rows() + static_cast<long>(i)) = tab[i].transpose();
  }
  return out;
}
}  // namespace

TEST(PcaInit, LongAxisAlignedWithXGivesZeroTheta) {
  // Points spread far more along x than y -> principal axis ~ (1, 0).
  Eigen::MatrixXd pts(6, 2);
  pts << -0.5, -0.01,
         -0.3,  0.01,
         -0.1, -0.01,
          0.1,  0.01,
          0.3, -0.01,
          0.5,  0.01;
  auto result = estimate_pca_long_axis(pts);
  EXPECT_NEAR(std::abs(result.theta_rad), 0.0, 0.05);
  EXPECT_GE(result.principal_axis.x(), 0.0);  // deterministic sign convention
}

TEST(PcaInit, SignConventionIsDeterministicForYDominantAxis) {
  // Points spread mostly along y -> principal_axis dominant component is y,
  // and by the Python convention must have non-negative y.
  Eigen::MatrixXd pts(6, 2);
  pts << -0.01, -0.5,
          0.01, -0.3,
         -0.01, -0.1,
          0.01,  0.1,
         -0.01,  0.3,
          0.01,  0.5;
  auto result = estimate_pca_long_axis(pts);
  EXPECT_GE(result.principal_axis.y(), 0.0);
}

TEST(PcaInit, MakePcaInitPoseUsesGivenCentre) {
  Eigen::MatrixXd pts(4, 2);
  pts << -0.5, 0.0, -0.2, 0.0, 0.2, 0.0, 0.5, 0.0;
  Eigen::Vector2d centre(0.1, 0.2);
  PrototypePose2D pose = make_pca_init_pose(centre, pts);
  EXPECT_DOUBLE_EQ(pose.tx, 0.1);
  EXPECT_DOUBLE_EQ(pose.ty, 0.2);
}

TEST(PcaInit, ChoosePiAmbiguousPosePicksLowerCostOrientation) {
  Eigen::MatrixXd proto =
      add_asymmetric_tab(dense_rectangle_contour(0.1, 0.02, 0.005), 0.02, 0.005);
  // Ground truth pose is theta=0; base_pose is theta=pi (the wrong branch),
  // so choose_pi_ambiguous_pose must flip back to theta ~ 0 (mod 2pi).
  Eigen::MatrixXd observed = proto;  // identity transform
  auto [mask, meta] = rasterize_points_to_mask(observed, 0.005, 0.05);
  cv::Mat filled = close_mask(mask, 2, true);
  cv::Mat boundary = extract_boundary_mask(filled);
  cv::Mat dist = compute_distance_transform_v2(boundary, meta.resolution_m);

  PrototypePose2D base_pose{M_PI, 0.0, 0.0};  // wrong branch
  auto [best_pose, best_cost] =
      choose_pi_ambiguous_pose(proto, base_pose, dist, meta, /*trim_fraction=*/0.0);
  // best_pose.theta_rad should be base_pose.theta_rad + pi == 2*pi ~ 0 (mod
  // 2pi); check via cos/sin rather than raw angle equality.
  EXPECT_NEAR(std::cos(best_pose.theta_rad), 1.0, 1e-6);
  EXPECT_LT(best_cost, 0.002);
}
