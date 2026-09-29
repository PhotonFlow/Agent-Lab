#pragma once

#include <utility>

#include <Eigen/Dense>
#include <opencv2/core.hpp>

#include "geometry_core/chamfer.hpp"

namespace geometry_core {

double chamfer_cost_v2_with_prior(
    const Eigen::Ref<const Eigen::MatrixXd>& proto_points_2d,
    const PrototypePose2D& pose, const cv::Mat& dist_img_m, const GridMeta& meta,
    const Eigen::Vector2d& anchor_xy, double prior_lambda, double trim_fraction = 0.10,
    const double* outside_penalty_m = nullptr);

std::pair<PrototypePose2D, double> coarse_chamfer_search_v2_with_prior(
    const Eigen::Ref<const Eigen::MatrixXd>& proto_points_2d,
    const PrototypePose2D& init_pose, const cv::Mat& dist_img_m, const GridMeta& meta,
    const Eigen::Vector2d& anchor_xy, double prior_lambda, double search_dx_m,
    double search_dy_m, double search_dtheta_rad, double step_dx_m, double step_dy_m,
    double step_dtheta_rad, double trim_fraction = 0.10,
    const double* outside_penalty_m = nullptr);

std::pair<PrototypePose2D, double> two_stage_chamfer_search_v2_with_prior(
    const Eigen::Ref<const Eigen::MatrixXd>& proto_points_2d,
    const PrototypePose2D& init_pose, const cv::Mat& dist_img_m, const GridMeta& meta,
    const Eigen::Vector2d& anchor_xy, double prior_lambda, double coarse_dx_m,
    double coarse_dy_m, double coarse_dtheta_rad, double coarse_step_dx_m,
    double coarse_step_dy_m, double coarse_step_dtheta_rad, double fine_dx_m,
    double fine_dy_m, double fine_dtheta_rad, double fine_step_dx_m,
    double fine_step_dy_m, double fine_step_dtheta_rad, double trim_fraction = 0.10,
    const double* outside_penalty_m = nullptr);

}  // namespace geometry_core
