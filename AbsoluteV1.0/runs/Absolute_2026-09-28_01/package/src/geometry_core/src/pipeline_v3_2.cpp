#include "geometry_core/pipeline_v3_2.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

#include "geometry_core/backproject.hpp"
#include "geometry_core/face_mask.hpp"
#include "geometry_core/plane_fit.hpp"
#include "geometry_core/pose.hpp"
#include "geometry_core/transforms.hpp"

namespace geometry_core {

namespace {
EstimatePoseOutcome make_failure(std::optional<int> instance_id, std::string reason,
                                  int n_face_points) {
  EstimatePoseOutcome outcome;
  outcome.ok = false;
  outcome.failure = FailureResult{instance_id, std::move(reason), n_face_points};
  return outcome;
}
}  // namespace

EstimatePoseOutcome estimate_pose_chamfer_v3_2(const Eigen::Vector4d& bbox_xyxy,
                                                const cv::Mat& depth_m,
                                                const RgbDepthCameraConfig& camera_cfg,
                                                const Stage2Config& cfg,
                                                const EstimatePoseParams& params,
                                                std::optional<int> instance_id,
                                                std::mt19937_64& rng) {
  // Prototype-grid parameters are not inputs to the pose or the inlier-face
  // extents. The estimate does not run that grid.
  (void)params;

  // 1. RGB bbox mask + cross-camera face point sampling.
  const int Hr = camera_cfg.rgb.height;
  const int Wr = camera_cfg.rgb.width;
  cv::Mat mask_rgb = build_bbox_mask(bbox_xyxy, Hr, Wr, cfg.erode_px);
  if (cv::countNonZero(mask_rgb) == 0) {
    return make_failure(instance_id, "bbox empty after erosion", 0);
  }
  FaceSamples samples = sample_face_points(depth_m, mask_rgb, camera_cfg, cfg);
  const int n_face_points = static_cast<int>(samples.points_depth_frame.rows());
  if (n_face_points < cfg.min_face_points) {
    return make_failure(instance_id, "too few face points: " + std::to_string(n_face_points),
                         n_face_points);
  }

  // 2. RANSAC + SVD plane.
  Plane plane_d;
  try {
    plane_d = ransac_plane_fit(samples.points_depth_frame, cfg.plane_inlier_threshold_m,
                                cfg.ransac_iters, cfg.ransac_min_inlier_ratio_early_stop, rng);
  } catch (const std::exception& exc) {
    return make_failure(instance_id, std::string("plane fit failed: ") + exc.what(),
                         n_face_points);
  }
  plane_d = orient_normal_toward_camera(plane_d);

  // 3. Plane inliers.
  auto inlier_mask = plane_inlier_mask(samples.points_depth_frame, plane_d,
                                        cfg.plane_inlier_threshold_m);
  const int n_plane_inliers = static_cast<int>(inlier_mask.count());
  if (n_plane_inliers < cfg.min_face_points) {
    return make_failure(instance_id,
                         "too few plane inliers: " + std::to_string(n_plane_inliers),
                         n_face_points);
  }
  Eigen::MatrixXd plane_points_3d(n_plane_inliers, 3);
  {
    int row = 0;
    for (long i = 0; i < samples.points_depth_frame.rows(); ++i) {
      if (inlier_mask(i)) {
        plane_points_3d.row(row++) = samples.points_depth_frame.row(i);
      }
    }
  }

  // Translation is the bbox-centre ray-plane hit. Yaw is the plane normal.
  const Eigen::Vector2d bbox_centre_uv(0.5 * (bbox_xyxy(0) + bbox_xyxy(2)),
                                        0.5 * (bbox_xyxy(1) + bbox_xyxy(3)));
  Eigen::Vector3d centre_d_init;
  try {
    centre_d_init = ray_plane_intersect_cross_camera(bbox_centre_uv, camera_cfg, plane_d);
  } catch (const std::exception& exc) {
    return make_failure(
        instance_id, std::string("bbox-centre back-projection failed: ") + exc.what(),
        n_face_points);
  }
  Eigen::Vector3d centre_r = apply_se3(camera_cfg.R_dr, camera_cfg.t_dr, centre_d_init);
  Eigen::Vector3d n_r = camera_cfg.R_dr * plane_d.normal;
  n_r /= (n_r.norm() + 1e-12);
  const double yaw = yaw_from_normal_camera(n_r);

  EstimatePoseOutcome outcome;
  outcome.ok = true;
  outcome.pose.yaw_rad = yaw;
  outcome.pose.tx = centre_r.x();
  outcome.pose.ty = centre_r.y();
  outcome.pose.tz = centre_r.z();
  outcome.pose.face_normal_rgb = n_r;
  outcome.pose.face_normal_depth = plane_d.normal;
  outcome.pose.plane_offset_depth_m = plane_d.offset;
  outcome.pose.plane_inlier_ratio = plane_d.inlier_ratio;
  outcome.pose.n_face_points = n_face_points;
  outcome.pose.instance_id = instance_id;
  outcome.pose.geometry_source = "bbox_chamfer_v3_2";
  outcome.pose.yaw_sign_convention = kYawSignConvention;

  outcome.has_debug = true;
  outcome.debug.n_plane_inliers = n_plane_inliers;

  if (plane_points_3d.rows() > 0) {
    double min_x = std::numeric_limits<double>::infinity();
    double max_x = -std::numeric_limits<double>::infinity();
    double min_y = std::numeric_limits<double>::infinity();
    double max_y = -std::numeric_limits<double>::infinity();
    double sum_z = 0.0;
    const Eigen::Index n = plane_points_3d.rows();
    for (Eigen::Index i = 0; i < n; ++i) {
      const double x = plane_points_3d(i, 0);
      const double y = plane_points_3d(i, 1);
      const double z = plane_points_3d(i, 2);
      min_x = std::min(min_x, x);
      max_x = std::max(max_x, x);
      min_y = std::min(min_y, y);
      max_y = std::max(max_y, y);
      sum_z += z;
    }
    outcome.has_dimensions = true;
    outcome.width_m = max_x - min_x;
    outcome.height_m = max_y - min_y;
    outcome.depth_m = sum_z / static_cast<double>(n);
  }

  return outcome;
}

}  // namespace geometry_core
