#pragma once

#include <utility>

#include <Eigen/Dense>
#include <opencv2/core.hpp>

#include "geometry_core/chamfer.hpp"

namespace geometry_core {

// Dominant in-plane orientation estimated from observed 2D points. Mirrors
// pallet_pose_estimation/geometry/pca_init.py::PcaInitResult.
struct PcaInitResult {
  double theta_rad = 0.0;
  Eigen::Vector2d principal_axis = Eigen::Vector2d::Zero();
  Eigen::Vector2d centroid_2d = Eigen::Vector2d::Zero();
  Eigen::Vector2d eigvals = Eigen::Vector2d::Zero();  // descending
  double anisotropy_ratio = 0.0;
};

PcaInitResult estimate_pca_long_axis(const Eigen::Ref<const Eigen::MatrixXd>& points_2d);

PrototypePose2D make_pca_init_pose(const Eigen::Vector2d& centre_2d,
                                    const Eigen::Ref<const Eigen::MatrixXd>& obs_points_2d);

std::pair<PrototypePose2D, double> choose_pi_ambiguous_pose(
    const Eigen::Ref<const Eigen::MatrixXd>& proto_points_2d,
    const PrototypePose2D& base_pose, const cv::Mat& dist_img_m, const GridMeta& meta,
    double trim_fraction = 0.10, const double* outside_penalty_m = nullptr);

}  // namespace geometry_core
