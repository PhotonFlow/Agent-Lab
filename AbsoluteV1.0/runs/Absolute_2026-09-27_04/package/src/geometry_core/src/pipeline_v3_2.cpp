#include "geometry_core/pipeline_v3_2.hpp"

#include <algorithm>
#include <cmath>

#include "geometry_core/backproject.hpp"
#include "geometry_core/chamfer.hpp"
#include "geometry_core/chamfer_prior.hpp"
#include "geometry_core/face_mask.hpp"
#include "geometry_core/pca_init.hpp"
#include "geometry_core/plane_coords.hpp"
#include "geometry_core/plane_fit.hpp"
#include "geometry_core/pose.hpp"
#include "geometry_core/prototype.hpp"
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

// Keyed cache: rebuilds the prototype only when the shape parameters change
// (they are fixed per-config in practice), avoiding a rebuild every frame.
const Prototype2D& cached_prototype(double width_m, double height_m, double pocket_width_m,
                                     double pocket_height_m, double pocket_centre_offset_m,
                                     double contour_spacing_m) {
  struct Key {
    double width_m = 0.0, height_m = 0.0, pocket_width_m = 0.0, pocket_height_m = 0.0,
           pocket_centre_offset_m = 0.0, contour_spacing_m = 0.0;
  };
  static Key key{};
  static Prototype2D proto{};
  static bool have = false;
  if (!have || key.width_m != width_m || key.height_m != height_m ||
      key.pocket_width_m != pocket_width_m || key.pocket_height_m != pocket_height_m ||
      key.pocket_centre_offset_m != pocket_centre_offset_m ||
      key.contour_spacing_m != contour_spacing_m) {
    proto = build_default_pallet_prototype(width_m, height_m, pocket_width_m, pocket_height_m,
                                            pocket_centre_offset_m, contour_spacing_m);
    key = Key{width_m, height_m, pocket_width_m, pocket_height_m, pocket_centre_offset_m,
              contour_spacing_m};
    have = true;
  }
  return proto;
}
}  // namespace

EstimatePoseOutcome estimate_pose_chamfer_v3_2(const Eigen::Vector4d& bbox_xyxy,
                                                const cv::Mat& depth_m,
                                                const RgbDepthCameraConfig& camera_cfg,
                                                const Stage2Config& cfg,
                                                const EstimatePoseParams& params,
                                                std::optional<int> instance_id,
                                                std::mt19937_64& rng) {
  const double* outside_penalty_ptr =
      params.has_outside_penalty_m ? &params.outside_penalty_m : nullptr;

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

  // 4. Deterministic plane-local 2D coordinates.
  PlaneBasis basis = build_plane_basis_deterministic(plane_d);
  Eigen::MatrixXd obs_points_2d = project_points_to_plane_2d(plane_points_3d, basis);

  // 5. Rasterise -> close -> edge -> exact distance transform.
  auto [obs_mask, grid_meta] =
      rasterize_points_to_mask(obs_points_2d, params.resolution_m, params.padding_m);
  cv::Mat obs_filled = close_mask(obs_mask, params.close_radius_px, /*keep_largest=*/true);
  cv::Mat obs_edge = extract_boundary_mask(obs_filled);
  cv::Mat dist_img_m = compute_distance_transform_v2(obs_edge, grid_meta.resolution_m);

  // 6. Prototype (pocket-aware), cached across calls with identical shape params.
  const Prototype2D& proto = cached_prototype(
      params.pallet_width_m, params.pallet_height_m, params.pocket_width_m,
      params.pocket_height_m, params.pocket_centre_offset_m, params.contour_spacing_m);

  // 7. Initial pose from bbox centre projected to plane.
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
  Eigen::MatrixXd centre_d_row(1, 3);
  centre_d_row.row(0) = centre_d_init.transpose();
  Eigen::Vector2d centre_2d_init = project_points_to_plane_2d(centre_d_row, basis).row(0);
  PrototypePose2D init_pose = make_pca_init_pose(centre_2d_init, obs_points_2d);

  auto [init_pose_resolved, init_cost] =
      choose_pi_ambiguous_pose(proto.contour_points, init_pose, dist_img_m, grid_meta,
                                params.trim_fraction, outside_penalty_ptr);
  (void)init_cost;
  init_pose = init_pose_resolved;

  const Eigen::Vector2d anchor_xy(init_pose.tx, init_pose.ty);

  // 8a. FREE (unconstrained, no-prior) two-stage bilinear chamfer search.
  auto [free_pose, free_cost] = two_stage_chamfer_search_v2(
      proto.contour_points, init_pose, dist_img_m, grid_meta, params.coarse_dx_m,
      params.coarse_dy_m, params.coarse_dtheta_rad, params.coarse_step_dx_m,
      params.coarse_step_dy_m, params.coarse_step_dtheta_rad, params.fine_dx_m,
      params.fine_dy_m, params.fine_dtheta_rad, params.fine_step_dx_m,
      params.fine_step_dy_m, params.fine_step_dtheta_rad, params.trim_fraction,
      outside_penalty_ptr);

  // 8b. Confidence gate.
  const double lo = params.cost_reliable_lo_m;
  const double hi = params.cost_reliable_hi_m;
  double confidence = hi > lo ? (hi - free_cost) / (hi - lo) : 1.0;
  confidence = std::clamp(confidence, 0.0, 1.0);
  const double lambda_eff = params.prior_lambda * (1.0 - confidence);

  bool used_prior_fallback = false;
  PrototypePose2D anchor_pose_same_theta{free_pose.theta_rad, anchor_xy.x(), anchor_xy.y()};
  const double anchor_cost =
      chamfer_cost_v2(proto.contour_points, anchor_pose_same_theta, dist_img_m, grid_meta,
                       params.trim_fraction, outside_penalty_ptr);

  PrototypePose2D best_pose;
  double prior_data_cost = 0.0;
  if (lambda_eff <= params.lambda_floor) {
    best_pose = free_pose;
  } else {
    auto [prior_pose, prior_search_cost] = two_stage_chamfer_search_v2_with_prior(
        proto.contour_points, init_pose, dist_img_m, grid_meta, anchor_xy, lambda_eff,
        params.prior_coarse_dx_m, params.prior_coarse_dy_m, params.coarse_dtheta_rad,
        params.coarse_step_dx_m, params.coarse_step_dy_m, params.coarse_step_dtheta_rad,
        params.fine_dx_m, params.fine_dy_m, params.fine_dtheta_rad, params.fine_step_dx_m,
        params.fine_step_dy_m, params.fine_step_dtheta_rad, params.trim_fraction,
        outside_penalty_ptr);
    (void)prior_search_cost;
    prior_data_cost = chamfer_cost_v2(proto.contour_points, prior_pose, dist_img_m, grid_meta,
                                       params.trim_fraction, outside_penalty_ptr);

    auto combined_cost = [&](const PrototypePose2D& pose, double data_cost) {
      const double dx = pose.tx - anchor_xy.x();
      const double dy = pose.ty - anchor_xy.y();
      return data_cost + lambda_eff * (dx * dx + dy * dy);
    };

    if (combined_cost(prior_pose, prior_data_cost) <= combined_cost(free_pose, free_cost)) {
      best_pose = prior_pose;
      used_prior_fallback = true;
    } else {
      best_pose = free_pose;
    }
  }

  double best_cost = free_cost;
  if (used_prior_fallback) {
    best_cost = prior_data_cost;
  }

  // 9. Publish the bbox-centre ray-plane hit in the RGB frame. The chamfer
  // search still selects best_pose for debug, but that refined lift is not
  // the reported translation.
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
  outcome.debug.chamfer_theta_rad = best_pose.theta_rad;
  outcome.debug.chamfer_cost_m = best_cost;
  outcome.debug.n_plane_inliers = n_plane_inliers;
  outcome.debug.raster_h = grid_meta.height;
  outcome.debug.raster_w = grid_meta.width;
  outcome.debug.free_cost_m = free_cost;
  outcome.debug.anchor_cost_m = anchor_cost;
  outcome.debug.confidence = confidence;
  outcome.debug.prior_lambda_eff = lambda_eff;
  outcome.debug.used_prior_fallback = used_prior_fallback;

  const Eigen::MatrixXd face_cam =
      apply_se3_batch(camera_cfg.R_dr, camera_cfg.t_dr, samples.points_depth_frame);
  outcome.has_dimensions = true;
  outcome.width_m = face_cam.col(0).maxCoeff() - face_cam.col(0).minCoeff();
  outcome.height_m = face_cam.col(1).maxCoeff() - face_cam.col(1).minCoeff();
  outcome.depth_m = face_cam.col(2).mean();

  return outcome;
}

}  // namespace geometry_core
