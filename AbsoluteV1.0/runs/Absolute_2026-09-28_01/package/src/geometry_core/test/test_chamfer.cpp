#include <algorithm>
#include <cmath>
#include <vector>

#include <gtest/gtest.h>

#include "geometry_core/chamfer.hpp"

using geometry_core::chamfer_cost_v2;
using geometry_core::close_mask;
using geometry_core::compute_distance_transform_v2;
using geometry_core::coarse_chamfer_search_v2;
using geometry_core::extract_boundary_mask;
using geometry_core::GridMeta;
using geometry_core::PrototypePose2D;
using geometry_core::rasterize_points_to_mask;
using geometry_core::sample_distance_bilinear;
using geometry_core::transform_points_2d;
using geometry_core::two_stage_chamfer_search_v2;

namespace {
// A wireframe of just the 4 rectangle corners is too sparse for
// close_mask's morphological closing (radius 2) to bridge into a single
// connected loop: with corners tens of pixels apart, closing leaves 4
// isolated single-pixel blobs and keep_largest then collapses the mask down
// to just ONE of them (verified against the Python reference implementation
// pallet_pose_estimation.geometry.chamfer, which produces the exact same
// collapse -- 0.1309... cost -- for this input; this is a test-fixture
// issue, not a port bug). Densely sample each edge instead, matching how
// real face-point observations / prototype contours look in production.
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

TEST(Chamfer, TransformPoints2dRotatesAndTranslates) {
  Eigen::MatrixXd pts(1, 2);
  pts << 1.0, 0.0;
  PrototypePose2D pose{M_PI / 2.0, 5.0, -5.0};  // 90 deg CCW then shift
  Eigen::MatrixXd out = transform_points_2d(pts, pose);
  EXPECT_NEAR(out(0, 0), 5.0, 1e-9);
  EXPECT_NEAR(out(0, 1), -4.0, 1e-9);
}

TEST(Chamfer, RasterizeThenBoundaryThenEdtRoundTrip) {
  // A 0.2 x 0.1 rectangle contour sampled coarsely.
  Eigen::MatrixXd pts(4, 2);
  pts << -0.1, -0.05,
          0.1, -0.05,
          0.1,  0.05,
         -0.1,  0.05;
  auto [mask, meta] = rasterize_points_to_mask(pts, /*resolution_m=*/0.01, /*padding_m=*/0.05);
  EXPECT_GT(cv::countNonZero(mask), 0);
  cv::Mat filled = close_mask(mask, /*close_radius_px=*/2, /*keep_largest=*/true);
  cv::Mat boundary = extract_boundary_mask(filled);
  cv::Mat dist = compute_distance_transform_v2(boundary, meta.resolution_m);
  EXPECT_EQ(dist.rows, meta.height);
  EXPECT_EQ(dist.cols, meta.width);
  // Distance at a boundary pixel must be exactly 0.
  double min_val, max_val;
  cv::minMaxLoc(dist, &min_val, &max_val);
  EXPECT_NEAR(min_val, 0.0, 1e-6);
}

TEST(Chamfer, ChamferCostV2IsZeroWhenPoseMatchesObservation) {
  Eigen::MatrixXd pts = dense_rectangle_contour(0.1, 0.05, 0.005);
  auto [mask, meta] = rasterize_points_to_mask(pts, 0.005, 0.05);
  cv::Mat filled = close_mask(mask, 2, true);
  cv::Mat boundary = extract_boundary_mask(filled);
  cv::Mat dist = compute_distance_transform_v2(boundary, meta.resolution_m);

  PrototypePose2D identity_pose{0.0, 0.0, 0.0};
  double cost = chamfer_cost_v2(pts, identity_pose, dist, meta, /*trim_fraction=*/0.0);
  EXPECT_LT(cost, meta.resolution_m);  // sub-pixel: contour matches itself
}

TEST(Chamfer, CoarseSearchFindsKnownOffsetPose) {
  // Build an observation that is a 0.02m x-shifted, 0.05 rad rotated version
  // of the prototype contour; the search should recover that offset.
  Eigen::MatrixXd proto = dense_rectangle_contour(0.1, 0.05, 0.005);
  const double true_theta = 0.05;
  const double true_tx = 0.02;
  const double true_ty = -0.01;
  PrototypePose2D true_pose{true_theta, true_tx, true_ty};
  Eigen::MatrixXd observed = transform_points_2d(proto, true_pose);

  auto [mask, meta] = rasterize_points_to_mask(observed, 0.005, 0.08);
  cv::Mat filled = close_mask(mask, 2, true);
  cv::Mat boundary = extract_boundary_mask(filled);
  cv::Mat dist = compute_distance_transform_v2(boundary, meta.resolution_m);

  PrototypePose2D init_pose{0.0, 0.0, 0.0};
  auto [best_pose, best_cost] = coarse_chamfer_search_v2(
      proto, init_pose, dist, meta,
      /*search_dx_m=*/0.05, /*search_dy_m=*/0.05, /*search_dtheta_rad=*/0.15,
      /*step_dx_m=*/0.005, /*step_dy_m=*/0.005, /*step_dtheta_rad=*/0.01,
      /*trim_fraction=*/0.0, nullptr);

  EXPECT_NEAR(best_pose.tx, true_tx, 0.006);
  EXPECT_NEAR(best_pose.ty, true_ty, 0.006);
  EXPECT_NEAR(best_pose.theta_rad, true_theta, 0.011);
  EXPECT_LT(best_cost, 0.003);
}

TEST(Chamfer, TwoStageSearchRefinesBeyondCoarseGrid) {
  Eigen::MatrixXd proto = dense_rectangle_contour(0.1, 0.05, 0.003);
  PrototypePose2D true_pose{0.03, 0.013, -0.007};
  Eigen::MatrixXd observed = transform_points_2d(proto, true_pose);

  auto [mask, meta] = rasterize_points_to_mask(observed, 0.003, 0.08);
  cv::Mat filled = close_mask(mask, 2, true);
  cv::Mat boundary = extract_boundary_mask(filled);
  cv::Mat dist = compute_distance_transform_v2(boundary, meta.resolution_m);

  PrototypePose2D init_pose{0.0, 0.0, 0.0};
  auto [best_pose, best_cost] = two_stage_chamfer_search_v2(
      proto, init_pose, dist, meta,
      /*coarse_dx_m=*/0.05, /*coarse_dy_m=*/0.05, /*coarse_dtheta_rad=*/0.15,
      /*coarse_step_dx_m=*/0.01, /*coarse_step_dy_m=*/0.01, /*coarse_step_dtheta_rad=*/0.02,
      /*fine_dx_m=*/0.012, /*fine_dy_m=*/0.012, /*fine_dtheta_rad=*/0.03,
      /*fine_step_dx_m=*/0.001, /*fine_step_dy_m=*/0.001, /*fine_step_dtheta_rad=*/0.003,
      /*trim_fraction=*/0.0, nullptr);

  EXPECT_NEAR(best_pose.tx, 0.013, 0.0015);
  EXPECT_NEAR(best_pose.ty, -0.007, 0.0015);
  EXPECT_NEAR(best_pose.theta_rad, 0.03, 0.004);
}

namespace {
Eigen::ArrayXd sample_distance_bilinear_at_oracle(
    const Eigen::Ref<const Eigen::MatrixXd>& points_2d, const cv::Mat& dist_img_m,
    const GridMeta& meta, double outside_penalty_m) {
  const int H = dist_img_m.rows;
  const int W = dist_img_m.cols;
  Eigen::ArrayXd out = Eigen::ArrayXd::Constant(points_2d.rows(), outside_penalty_m);
  for (long i = 0; i < points_2d.rows(); ++i) {
    const double col_f = (points_2d(i, 0) - meta.min_xy.x()) / meta.resolution_m;
    const double row_f = (points_2d(i, 1) - meta.min_xy.y()) / meta.resolution_m;
    const long c0 = static_cast<long>(std::floor(col_f));
    const long r0 = static_cast<long>(std::floor(row_f));
    const double dx = col_f - static_cast<double>(c0);
    const double dy = row_f - static_cast<double>(r0);
    if (r0 >= 0 && r0 + 1 < H && c0 >= 0 && c0 + 1 < W) {
      const double d00 = dist_img_m.at<float>(static_cast<int>(r0), static_cast<int>(c0));
      const double d01 = dist_img_m.at<float>(static_cast<int>(r0), static_cast<int>(c0 + 1));
      const double d10 = dist_img_m.at<float>(static_cast<int>(r0 + 1), static_cast<int>(c0));
      const double d11 = dist_img_m.at<float>(static_cast<int>(r0 + 1), static_cast<int>(c0 + 1));
      out(i) = (1.0 - dx) * (1.0 - dy) * d00 + dx * (1.0 - dy) * d01 +
               (1.0 - dx) * dy * d10 + dx * dy * d11;
    }
  }
  return out;
}
}  // namespace

TEST(Chamfer, SampleDistanceBilinearMatchesAtOracleBitExact) {
  Eigen::MatrixXd pts = dense_rectangle_contour(0.1, 0.05, 0.01);
  auto [mask, meta] = rasterize_points_to_mask(pts, 0.005, 0.05);
  cv::Mat filled = close_mask(mask, 2, true);
  cv::Mat boundary = extract_boundary_mask(filled);
  cv::Mat dist = compute_distance_transform_v2(boundary, meta.resolution_m);

  PrototypePose2D pose{0.1, 0.01, -0.02};
  Eigen::MatrixXd transformed = transform_points_2d(pts, pose);
  const double penalty = 50.0 * meta.resolution_m;
  Eigen::ArrayXd got = sample_distance_bilinear(transformed, dist, meta, penalty);
  Eigen::ArrayXd exp = sample_distance_bilinear_at_oracle(transformed, dist, meta, penalty);
  ASSERT_EQ(got.size(), exp.size());
  for (long i = 0; i < got.size(); ++i) {
    EXPECT_EQ(got(i), exp(i)) << "i=" << i;
  }
}

TEST(Chamfer, CoarseSearchMatchesExhaustiveChamferCostBitExact) {
  Eigen::MatrixXd proto = dense_rectangle_contour(0.08, 0.04, 0.02);
  PrototypePose2D true_pose{0.04, 0.01, -0.01};
  Eigen::MatrixXd observed = transform_points_2d(proto, true_pose);
  auto [mask, meta] = rasterize_points_to_mask(observed, 0.01, 0.06);
  cv::Mat filled = close_mask(mask, 2, true);
  cv::Mat boundary = extract_boundary_mask(filled);
  cv::Mat dist = compute_distance_transform_v2(boundary, meta.resolution_m);

  PrototypePose2D init{0.0, 0.0, 0.0};
  const double search_dx = 0.03, search_dy = 0.03, search_dtheta = 0.08;
  const double step_dx = 0.01, step_dy = 0.01, step_dtheta = 0.02;
  const double trim = 0.10;

  std::vector<double> dx_values, dy_values, dtheta_values;
  for (double v = -search_dx; v <= search_dx + 0.5 * step_dx; v += step_dx) dx_values.push_back(v);
  for (double v = -search_dy; v <= search_dy + 0.5 * step_dy; v += step_dy) dy_values.push_back(v);
  for (double v = -search_dtheta; v <= search_dtheta + 0.5 * step_dtheta; v += step_dtheta)
    dtheta_values.push_back(v);

  // Mirror production init seed: cost at init_pose, index -1.
  PrototypePose2D best = init;
  double best_cost = chamfer_cost_v2(proto, init, dist, meta, trim, nullptr);
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
    const double cost = chamfer_cost_v2(proto, pose, dist, meta, trim, nullptr);
    // Match coarse_chamfer_search_v2 local update + global reduce semantics
    // for a single thread: update when cost < best_cost (dead second clause omitted).
    if (cost < best_cost) {
      best_cost = cost;
      best = pose;
      best_index = flat;
    }
    (void)best_index;
  }

  auto [got_pose, got_cost] = coarse_chamfer_search_v2(
      proto, init, dist, meta, search_dx, search_dy, search_dtheta, step_dx, step_dy,
      step_dtheta, trim, nullptr);

  EXPECT_EQ(got_cost, best_cost);
  EXPECT_EQ(got_pose.theta_rad, best.theta_rad);
  EXPECT_EQ(got_pose.tx, best.tx);
  EXPECT_EQ(got_pose.ty, best.ty);
}
