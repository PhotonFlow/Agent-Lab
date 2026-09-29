#include "geometry_core/pca_init.hpp"

#include <cmath>
#include <stdexcept>

namespace geometry_core {

PcaInitResult estimate_pca_long_axis(const Eigen::Ref<const Eigen::MatrixXd>& points_2d) {
  if (points_2d.cols() != 2 || points_2d.rows() < 3) {
    throw std::invalid_argument("points_2d must have shape (N>=3, 2)");
  }
  const Eigen::RowVector2d centroid = points_2d.colwise().mean();
  Eigen::MatrixXd centred = points_2d.rowwise() - centroid;
  Eigen::Matrix2d cov = (centred.transpose() * centred) / static_cast<double>(points_2d.rows());

  Eigen::SelfAdjointEigenSolver<Eigen::Matrix2d> solver(cov);
  // Eigen returns ascending eigenvalues; reverse to descending (matches
  // np.linalg.eigh + np.argsort(...)[::-1]).
  Eigen::Vector2d eigvals_desc(solver.eigenvalues()(1), solver.eigenvalues()(0));
  Eigen::Vector2d principal_axis = solver.eigenvectors().col(1);  // largest eigenvalue

  if (std::abs(principal_axis.x()) >= std::abs(principal_axis.y())) {
    if (principal_axis.x() < 0.0) {
      principal_axis = -principal_axis;
    }
  } else {
    if (principal_axis.y() < 0.0) {
      principal_axis = -principal_axis;
    }
  }

  PcaInitResult result;
  result.theta_rad = std::atan2(principal_axis.y(), principal_axis.x());
  result.principal_axis = principal_axis;
  result.centroid_2d = centroid.transpose();
  result.eigvals = eigvals_desc;
  result.anisotropy_ratio = eigvals_desc(1) / std::max(eigvals_desc(0), 1e-18);
  return result;
}

PrototypePose2D make_pca_init_pose(const Eigen::Vector2d& centre_2d,
                                    const Eigen::Ref<const Eigen::MatrixXd>& obs_points_2d) {
  PcaInitResult pca = estimate_pca_long_axis(obs_points_2d);
  PrototypePose2D pose;
  pose.theta_rad = pca.theta_rad;
  pose.tx = centre_2d.x();
  pose.ty = centre_2d.y();
  return pose;
}

std::pair<PrototypePose2D, double> choose_pi_ambiguous_pose(
    const Eigen::Ref<const Eigen::MatrixXd>& proto_points_2d,
    const PrototypePose2D& base_pose, const cv::Mat& dist_img_m, const GridMeta& meta,
    double trim_fraction, const double* outside_penalty_m) {
  PrototypePose2D pose_a = base_pose;
  PrototypePose2D pose_b{base_pose.theta_rad + M_PI, base_pose.tx, base_pose.ty};

  const double cost_a =
      chamfer_cost_v2(proto_points_2d, pose_a, dist_img_m, meta, trim_fraction, outside_penalty_m);
  const double cost_b =
      chamfer_cost_v2(proto_points_2d, pose_b, dist_img_m, meta, trim_fraction, outside_penalty_m);

  if (cost_a <= cost_b) {
    return {pose_a, cost_a};
  }
  return {pose_b, cost_b};
}

}  // namespace geometry_core
