#include "geometry_core/chamfer_prior.hpp"

#include <cmath>
#include <vector>

#include "chamfer_internal.hpp"

namespace geometry_core {

double chamfer_cost_v2_with_prior(
    const Eigen::Ref<const Eigen::MatrixXd>& proto_points_2d,
    const PrototypePose2D& pose, const cv::Mat& dist_img_m, const GridMeta& meta,
    const Eigen::Vector2d& anchor_xy, double prior_lambda, double trim_fraction,
    const double* outside_penalty_m) {
  const double data = chamfer_cost_v2(proto_points_2d, pose, dist_img_m, meta,
                                       trim_fraction, outside_penalty_m);
  const double dx = pose.tx - anchor_xy.x();
  const double dy = pose.ty - anchor_xy.y();
  return data + prior_lambda * (dx * dx + dy * dy);
}

std::pair<PrototypePose2D, double> coarse_chamfer_search_v2_with_prior(
    const Eigen::Ref<const Eigen::MatrixXd>& proto_points_2d,
    const PrototypePose2D& init_pose, const cv::Mat& dist_img_m, const GridMeta& meta,
    const Eigen::Vector2d& anchor_xy, double prior_lambda, double search_dx_m,
    double search_dy_m, double search_dtheta_rad, double step_dx_m, double step_dy_m,
    double step_dtheta_rad, double trim_fraction, const double* outside_penalty_m) {
  std::vector<double> dx_values;
  dx_values.reserve(
      static_cast<size_t>(std::floor((2.0 * search_dx_m) / step_dx_m)) + 2);
  for (double v = -search_dx_m; v <= search_dx_m + 0.5 * step_dx_m; v += step_dx_m) {
    dx_values.push_back(v);
  }
  std::vector<double> dy_values;
  dy_values.reserve(
      static_cast<size_t>(std::floor((2.0 * search_dy_m) / step_dy_m)) + 2);
  for (double v = -search_dy_m; v <= search_dy_m + 0.5 * step_dy_m; v += step_dy_m) {
    dy_values.push_back(v);
  }
  std::vector<double> dtheta_values;
  dtheta_values.reserve(
      static_cast<size_t>(std::floor((2.0 * search_dtheta_rad) / step_dtheta_rad)) + 2);
  for (double v = -search_dtheta_rad; v <= search_dtheta_rad + 0.5 * step_dtheta_rad;
       v += step_dtheta_rad) {
    dtheta_values.push_back(v);
  }

  PrototypePose2D best_pose = init_pose;
  double best_cost = chamfer_cost_v2_with_prior(proto_points_2d, init_pose, dist_img_m,
                                                 meta, anchor_xy, prior_lambda,
                                                 trim_fraction, outside_penalty_m);

  const long n_theta = static_cast<long>(dtheta_values.size());
  const long n_y = static_cast<long>(dy_values.size());
  const long n_x = static_cast<long>(dx_values.size());
  const long total = n_theta * n_y * n_x;

  PrototypePose2D global_best_pose = best_pose;
  double global_best_cost = best_cost;
  long global_best_index = -1;

#pragma omp parallel
  {
    PrototypePose2D local_best_pose = best_pose;
    double local_best_cost = best_cost;
    long local_best_index = -1;

    // Thread-local scratch shared with the fused cost path; with
    // schedule(static) each thread gets a contiguous flat range so theta
    // changes infrequently (rotate once per theta). Force a recompute on this
    // thread's first iteration by invalidating any cached rotation left over
    // from a prior search call.
    chamfer_detail::ChamferTls& tls = chamfer_detail::chamfer_tls();
    chamfer_detail::ensure_tls_size(tls, proto_points_2d.rows());
    tls.cached_theta_i = -1;

#pragma omp for schedule(static)
    for (long flat = 0; flat < total; ++flat) {
      const long theta_i = flat / (n_y * n_x);
      const long rem = flat % (n_y * n_x);
      const long y_i = rem / n_x;
      const long x_i = rem % n_x;

      if (tls.cached_theta_i != theta_i) {
        const double theta = init_pose.theta_rad + dtheta_values[theta_i];
        chamfer_detail::rotate_proto_into(proto_points_2d, theta, tls.rotated);
        tls.cached_theta_i = theta_i;
        tls.cached_theta_rad = theta;
      }
      const double tx = init_pose.tx + dx_values[x_i];
      const double ty = init_pose.ty + dy_values[y_i];
      const double data = chamfer_detail::chamfer_cost_from_rotated(
          tls.rotated, tx, ty, dist_img_m, meta, trim_fraction, outside_penalty_m, tls);
      const double px = tx - anchor_xy.x();
      const double py = ty - anchor_xy.y();
      const double cost = data + prior_lambda * (px * px + py * py);
      if (local_best_index < 0 || cost < local_best_cost) {
        local_best_cost = cost;
        local_best_pose = PrototypePose2D{tls.cached_theta_rad, tx, ty};
        local_best_index = flat;
      }
    }

#pragma omp critical
    {
      if (local_best_index >= 0 &&
          (global_best_index < 0 || local_best_cost < global_best_cost ||
           (local_best_cost == global_best_cost && local_best_index < global_best_index))) {
        global_best_cost = local_best_cost;
        global_best_pose = local_best_pose;
        global_best_index = local_best_index;
      }
    }
  }

  return {global_best_pose, global_best_cost};
}

std::pair<PrototypePose2D, double> two_stage_chamfer_search_v2_with_prior(
    const Eigen::Ref<const Eigen::MatrixXd>& proto_points_2d,
    const PrototypePose2D& init_pose, const cv::Mat& dist_img_m, const GridMeta& meta,
    const Eigen::Vector2d& anchor_xy, double prior_lambda, double coarse_dx_m,
    double coarse_dy_m, double coarse_dtheta_rad, double coarse_step_dx_m,
    double coarse_step_dy_m, double coarse_step_dtheta_rad, double fine_dx_m,
    double fine_dy_m, double fine_dtheta_rad, double fine_step_dx_m,
    double fine_step_dy_m, double fine_step_dtheta_rad, double trim_fraction,
    const double* outside_penalty_m) {
  auto [coarse_pose, coarse_cost] = coarse_chamfer_search_v2_with_prior(
      proto_points_2d, init_pose, dist_img_m, meta, anchor_xy, prior_lambda,
      coarse_dx_m, coarse_dy_m, coarse_dtheta_rad, coarse_step_dx_m, coarse_step_dy_m,
      coarse_step_dtheta_rad, trim_fraction, outside_penalty_m);
  (void)coarse_cost;
  return coarse_chamfer_search_v2_with_prior(
      proto_points_2d, coarse_pose, dist_img_m, meta, anchor_xy, prior_lambda, fine_dx_m,
      fine_dy_m, fine_dtheta_rad, fine_step_dx_m, fine_step_dy_m, fine_step_dtheta_rad,
      trim_fraction, outside_penalty_m);
}

}  // namespace geometry_core
