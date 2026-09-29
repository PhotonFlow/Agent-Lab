#pragma once

#include <utility>

#include <Eigen/Dense>
#include <opencv2/core.hpp>

#include "geometry_core/chamfer.hpp"

namespace geometry_core {

// Levenberg-Marquardt registration of the prototype onto the chamfer distance
// transform (Fitzgibbon, BMVC 2001 / IVC 2003). Replaces the exhaustive
// translation-rotation grid. The returned cost is the trimmed-mean chamfer
// data term, without the optional anchor prior.
//
// `anchor_xy` and `prior_lambda` add the same quadratic translation prior as
// chamfer_cost_v2_with_prior. Pass a null anchor to search the data term only.
// The pose stays inside the axis-aligned window around `init_pose`.
std::pair<PrototypePose2D, double> lm_chamfer_search(
    const Eigen::Ref<const Eigen::MatrixXd>& proto_points_2d,
    const PrototypePose2D& init_pose, const cv::Mat& dist_img_m, const GridMeta& meta,
    double max_dx_m, double max_dy_m, double max_dtheta_rad, double trim_fraction = 0.10,
    const double* outside_penalty_m = nullptr, const Eigen::Vector2d* anchor_xy = nullptr,
    double prior_lambda = 0.0);

}  // namespace geometry_core
