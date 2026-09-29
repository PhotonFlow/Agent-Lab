#pragma once

#include <optional>
#include <string>

#include <Eigen/Dense>

namespace geometry_core {

inline constexpr const char* kYawSignConvention =
    "rep103_right_hand_rule_about_world_up";

// Knobs for the stage-2 geometry pipeline. Mirrors
// pallet_pose_estimation/schemas.py::Stage2Config exactly.
struct Stage2Config {
  int erode_px = 2;
  double depth_min_m = 0.3;
  double depth_max_m = 5.0;
  double plane_inlier_threshold_m = 0.005;
  int ransac_iters = 100;
  double ransac_min_inlier_ratio_early_stop = 0.85;
  int min_face_points = 100;
  int rgb_clip_margin_px = 0;
};

// End-to-end stage-2 result for one pallet detection. Mirrors
// pallet_pose_estimation/schemas.py::PoseResult (bbox-only fields; the
// pocket-keypoint fields from the Python dataclass are not used by v3.2 and
// are intentionally omitted here since geometry_source is always
// "bbox_chamfer_v3_2").
struct PoseResult {
  double yaw_rad = 0.0;
  double tx = 0.0;
  double ty = 0.0;
  double tz = 0.0;

  Eigen::Vector3d face_normal_rgb = Eigen::Vector3d::Zero();
  Eigen::Vector3d face_normal_depth = Eigen::Vector3d::Zero();
  double plane_offset_depth_m = 0.0;

  double plane_inlier_ratio = 0.0;
  int n_face_points = 0;

  std::optional<int> instance_id;
  std::string geometry_source = "bbox_chamfer_v3_2";
  std::string yaw_sign_convention = kYawSignConvention;
};

// Returned when stage 2 cannot produce a pose for a detection. Mirrors
// pallet_pose_estimation/schemas.py::FailureResult.
struct FailureResult {
  std::optional<int> instance_id;
  std::string failure_reason;
  int n_face_points = 0;
};

}  // namespace geometry_core
