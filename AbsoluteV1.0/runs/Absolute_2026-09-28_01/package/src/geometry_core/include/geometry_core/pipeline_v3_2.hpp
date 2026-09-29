#pragma once

#include <cmath>
#include <optional>
#include <random>

#include <Eigen/Dense>
#include <opencv2/core.hpp>

#include "geometry_core/camera_config.hpp"
#include "geometry_core/schemas.hpp"

namespace geometry_core {

struct ChamferDebugV3_2 {
  double chamfer_theta_rad = 0.0;
  double chamfer_cost_m = 0.0;
  int n_plane_inliers = 0;
  int raster_h = 0;
  int raster_w = 0;
  double free_cost_m = 0.0;
  double anchor_cost_m = 0.0;
  double confidence = 0.0;
  double prior_lambda_eff = 0.0;
  bool used_prior_fallback = false;
};

// All defaults copied verbatim from
// pallet_pose_estimation/pipelinev3_2.py::estimate_pose_chamfer_v3_2's
// keyword-argument defaults. Do not change any value here without updating
// the Python reference and re-running the validation sweep (Task 15).
struct EstimatePoseParams {
  double pallet_width_m = 1.20;
  double pallet_height_m = 0.14;
  double pocket_width_m = 0.47;
  double pocket_height_m = 0.10;
  double pocket_centre_offset_m = 0.28;
  double contour_spacing_m = 0.03;

  double resolution_m = 0.005;
  double padding_m = 0.80;
  int close_radius_px = 2;

  double coarse_dx_m = 0.15;
  double coarse_dy_m = 0.15;
  double coarse_dtheta_rad = 10.0 * M_PI / 180.0;
  double coarse_step_dx_m = 0.01;
  double coarse_step_dy_m = 0.01;
  double coarse_step_dtheta_rad = 1.0 * M_PI / 180.0;

  double fine_dx_m = 0.012;
  double fine_dy_m = 0.012;
  double fine_dtheta_rad = 1.2 * M_PI / 180.0;
  double fine_step_dx_m = 0.001;
  double fine_step_dy_m = 0.001;
  double fine_step_dtheta_rad = 0.2 * M_PI / 180.0;

  double trim_fraction = 0.10;
  bool has_outside_penalty_m = false;
  double outside_penalty_m = 0.0;  // only used if has_outside_penalty_m

  double prior_lambda = 3.0;
  double cost_reliable_lo_m = 0.006;
  double cost_reliable_hi_m = 0.020;
  double lambda_floor = 0.05;

  double prior_coarse_dx_m = 0.10;
  double prior_coarse_dy_m = 0.10;
};

struct EstimatePoseOutcome {
  bool ok = false;
  PoseResult pose;
  FailureResult failure{std::nullopt, "", 0};
  ChamferDebugV3_2 debug;
  bool has_debug = false;
  // Metric extents of the inlier face used for the pose. width is the
  // camera-x span, height the camera-y span, depth the mean range.
  bool has_dimensions = false;
  double width_m = 0.0;
  double height_m = 0.0;
  double depth_m = 0.0;
};

EstimatePoseOutcome estimate_pose_chamfer_v3_2(const Eigen::Vector4d& bbox_xyxy,
                                                const cv::Mat& depth_m,
                                                const RgbDepthCameraConfig& camera_cfg,
                                                const Stage2Config& cfg,
                                                const EstimatePoseParams& params,
                                                std::optional<int> instance_id,
                                                std::mt19937_64& rng);

}  // namespace geometry_core
