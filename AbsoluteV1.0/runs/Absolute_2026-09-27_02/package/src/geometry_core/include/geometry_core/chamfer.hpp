#pragma once

#include <utility>

#include <Eigen/Dense>
#include <opencv2/core.hpp>

namespace geometry_core {

struct GridMeta {
  Eigen::Vector2d min_xy = Eigen::Vector2d::Zero();  // metres
  double resolution_m = 0.005;                       // metres / pixel
  int height = 0;
  int width = 0;
};

// 2D rigid transform of prototype into observed plane-local frame. Mirrors
// pallet_pose_estimation/geometry/chamfer.py::PrototypePose2D.
struct PrototypePose2D {
  double theta_rad = 0.0;
  double tx = 0.0;
  double ty = 0.0;
};

Eigen::MatrixXd transform_points_2d(const Eigen::Ref<const Eigen::MatrixXd>& points_2d,
                                    const PrototypePose2D& pose);

std::pair<cv::Mat, GridMeta> rasterize_points_to_mask(
    const Eigen::Ref<const Eigen::MatrixXd>& points_2d, double resolution_m,
    double padding_m);

cv::Mat close_mask(const cv::Mat& mask, int close_radius_px = 2,
                    bool keep_largest = true);

cv::Mat extract_boundary_mask(const cv::Mat& mask);

// CV_32FC1, metres, exact L2 (cv::DIST_MASK_PRECISE) distance-to-edge image.
cv::Mat compute_distance_transform_v2(const cv::Mat& edge_mask, double resolution_m);

Eigen::ArrayXd sample_distance_bilinear(
    const Eigen::Ref<const Eigen::MatrixXd>& points_2d, const cv::Mat& dist_img_m,
    const GridMeta& meta, double outside_penalty_m);

double chamfer_cost_v2(const Eigen::Ref<const Eigen::MatrixXd>& proto_points_2d,
                        const PrototypePose2D& pose, const cv::Mat& dist_img_m,
                        const GridMeta& meta, double trim_fraction = 0.10,
                        const double* outside_penalty_m = nullptr);

std::pair<PrototypePose2D, double> coarse_chamfer_search_v2(
    const Eigen::Ref<const Eigen::MatrixXd>& proto_points_2d,
    const PrototypePose2D& init_pose, const cv::Mat& dist_img_m, const GridMeta& meta,
    double search_dx_m, double search_dy_m, double search_dtheta_rad, double step_dx_m,
    double step_dy_m, double step_dtheta_rad, double trim_fraction = 0.10,
    const double* outside_penalty_m = nullptr);

std::pair<PrototypePose2D, double> two_stage_chamfer_search_v2(
    const Eigen::Ref<const Eigen::MatrixXd>& proto_points_2d,
    const PrototypePose2D& init_pose, const cv::Mat& dist_img_m, const GridMeta& meta,
    double coarse_dx_m, double coarse_dy_m, double coarse_dtheta_rad,
    double coarse_step_dx_m, double coarse_step_dy_m, double coarse_step_dtheta_rad,
    double fine_dx_m, double fine_dy_m, double fine_dtheta_rad, double fine_step_dx_m,
    double fine_step_dy_m, double fine_step_dtheta_rad, double trim_fraction = 0.10,
    const double* outside_penalty_m = nullptr);

}  // namespace geometry_core
