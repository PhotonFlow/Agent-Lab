#include <algorithm>
#include <cmath>
#include <vector>

#include <gtest/gtest.h>

#include "geometry_core/chamfer_prior.hpp"
#include "geometry_core/chamfer.hpp"

using geometry_core::chamfer_cost_v2;
using geometry_core::chamfer_cost_v2_with_prior;
using geometry_core::close_mask;
using geometry_core::coarse_chamfer_search_v2_with_prior;
using geometry_core::compute_distance_transform_v2;
using geometry_core::extract_boundary_mask;
using geometry_core::GridMeta;
using geometry_core::PrototypePose2D;
using geometry_core::rasterize_points_to_mask;
using geometry_core::transform_points_2d;
using geometry_core::two_stage_chamfer_search_v2_with_prior;

namespace {
// Densely sample a rectangle contour, matching test_chamfer.cpp's fixture so
// close_mask's morphological closing bridges the edges into one connected loop.
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
}  // namespace

TEST(ChamferPrior, CostIncludesQuadraticPenalty) {
  Eigen::MatrixXd proto(4, 2);
  proto << -0.1, -0.02, 0.1, -0.02, 0.1, 0.02, -0.1, 0.02;
  auto [mask, meta] = rasterize_points_to_mask(proto, 0.005, 0.05);
  cv::Mat filled = close_mask(mask, 2, true);
  cv::Mat boundary = extract_boundary_mask(filled);
  cv::Mat dist = compute_distance_transform_v2(boundary, meta.resolution_m);

  PrototypePose2D pose{0.0, 0.05, 0.0};  // offset from anchor by 0.05 in x
  Eigen::Vector2d anchor(0.0, 0.0);
  double cost_no_prior_equivalent =
      chamfer_cost_v2_with_prior(proto, pose, dist, meta, anchor, /*prior_lambda=*/0.0);
  double cost_with_prior =
      chamfer_cost_v2_with_prior(proto, pose, dist, meta, anchor, /*prior_lambda=*/10.0);
  const double expected_penalty = 10.0 * (0.05 * 0.05);
  EXPECT_NEAR(cost_with_prior - cost_no_prior_equivalent, expected_penalty, 1e-9);
}

TEST(ChamferPrior, HighLambdaPullsSearchTowardAnchorOverFarBetterFreeFit) {
  Eigen::MatrixXd proto(4, 2);
  proto << -0.1, -0.02, 0.1, -0.02, 0.1, 0.02, -0.1, 0.02;
  // Observation is proto shifted by +0.04 in x from the origin.
  PrototypePose2D true_pose{0.0, 0.04, 0.0};
  Eigen::MatrixXd observed = transform_points_2d(proto, true_pose);
  auto [mask, meta] = rasterize_points_to_mask(observed, 0.003, 0.08);
  cv::Mat filled = close_mask(mask, 2, true);
  cv::Mat boundary = extract_boundary_mask(filled);
  cv::Mat dist = compute_distance_transform_v2(boundary, meta.resolution_m);

  PrototypePose2D init_pose{0.0, 0.0, 0.0};
  Eigen::Vector2d anchor(0.0, 0.0);  // anchor at the ORIGIN, away from the true 0.04 offset
  auto [best_pose, best_cost] = two_stage_chamfer_search_v2_with_prior(
      proto, init_pose, dist, meta, anchor, /*prior_lambda=*/1000.0,
      /*coarse_dx_m=*/0.05, /*coarse_dy_m=*/0.05, /*coarse_dtheta_rad=*/0.05,
      /*coarse_step_dx_m=*/0.005, /*coarse_step_dy_m=*/0.005, /*coarse_step_dtheta_rad=*/0.02,
      /*fine_dx_m=*/0.005, /*fine_dy_m=*/0.005, /*fine_dtheta_rad=*/0.01,
      /*fine_step_dx_m=*/0.001, /*fine_step_dy_m=*/0.001, /*fine_step_dtheta_rad=*/0.005,
      /*trim_fraction=*/0.0, nullptr);
  // With an overwhelming prior_lambda, the search must stay very close to
  // the anchor (0,0) rather than moving to the true 0.04 offset.
  EXPECT_LT(std::abs(best_pose.tx), 0.006);
  (void)best_cost;
}

TEST(ChamferPrior, CoarseSearchMatchesExhaustivePriorCostBitExact) {
  Eigen::MatrixXd proto = dense_rectangle_contour(0.08, 0.04, 0.02);
  PrototypePose2D true_pose{0.04, 0.01, -0.01};
  Eigen::MatrixXd observed = transform_points_2d(proto, true_pose);
  auto [mask, meta] = rasterize_points_to_mask(observed, 0.01, 0.06);
  cv::Mat filled = close_mask(mask, 2, true);
  cv::Mat boundary = extract_boundary_mask(filled);
  cv::Mat dist = compute_distance_transform_v2(boundary, meta.resolution_m);

  PrototypePose2D init{0.0, 0.0, 0.0};
  Eigen::Vector2d anchor(0.005, -0.005);  // anchor offset from init/grid centre
  const double prior_lambda = 25.0;
  const double search_dx = 0.03, search_dy = 0.03, search_dtheta = 0.08;
  const double step_dx = 0.01, step_dy = 0.01, step_dtheta = 0.02;
  const double trim = 0.10;

  std::vector<double> dx_values, dy_values, dtheta_values;
  for (double v = -search_dx; v <= search_dx + 0.5 * step_dx; v += step_dx) dx_values.push_back(v);
  for (double v = -search_dy; v <= search_dy + 0.5 * step_dy; v += step_dy) dy_values.push_back(v);
  for (double v = -search_dtheta; v <= search_dtheta + 0.5 * step_dtheta; v += step_dtheta)
    dtheta_values.push_back(v);

  // Mirror production init seed: prior cost at init_pose, index -1.
  PrototypePose2D best = init;
  double best_cost = chamfer_cost_v2_with_prior(proto, init, dist, meta, anchor,
                                                prior_lambda, trim, nullptr);
  long best_index = -1;
  const long n_theta = static_cast<long>(dtheta_values.size());
  const long n_y = static_cast<long>(dy_values.size());
  const long n_x = static_cast<long>(dx_values.size());
  for (long flat = 0; flat < n_theta * n_y * n_x; ++flat) {
    const long theta_i = flat / (n_y * n_x);
    const long rem = flat % (n_y * n_x);
    const long y_i = rem / n_x;
    const long x_i = rem % n_x;
    PrototypePose2D pose;
    pose.theta_rad = init.theta_rad + dtheta_values[theta_i];
    pose.tx = init.tx + dx_values[x_i];
    pose.ty = init.ty + dy_values[y_i];
    const double data = chamfer_cost_v2(proto, pose, dist, meta, trim, nullptr);
    const double dx = pose.tx - anchor.x();
    const double dy = pose.ty - anchor.y();
    const double cost = data + prior_lambda * (dx * dx + dy * dy);
    // Match coarse_chamfer_search_v2_with_prior local update semantics for a
    // single thread: prior's condition is (index < 0 || cost < best_cost).
    if (best_index < 0 || cost < best_cost) {
      best_cost = cost;
      best = pose;
      best_index = flat;
    }
  }
  (void)best_index;

  auto [got_pose, got_cost] = coarse_chamfer_search_v2_with_prior(
      proto, init, dist, meta, anchor, prior_lambda, search_dx, search_dy, search_dtheta,
      step_dx, step_dy, step_dtheta, trim, nullptr);

  EXPECT_EQ(got_cost, best_cost);
  EXPECT_EQ(got_pose.theta_rad, best.theta_rad);
  EXPECT_EQ(got_pose.tx, best.tx);
  EXPECT_EQ(got_pose.ty, best.ty);
}
