#include <cmath>

#include <gtest/gtest.h>

#include "geometry_core/pipeline_v3_2.hpp"

using geometry_core::EstimatePoseParams;
using geometry_core::estimate_pose_chamfer_v3_2;
using geometry_core::PinholeIntrinsics;
using geometry_core::RgbDepthCameraConfig;
using geometry_core::Stage2Config;

namespace {

// Build a synthetic scene: a fronto-parallel pallet face 2m from an
// identical, coincident RGB+depth camera pair (identity extrinsic), so the
// estimator should recover tx=ty=0 (image-centre projected), tz=2.0,
// yaw=0, within a few mm/degrees.
RgbDepthCameraConfig make_synthetic_camera() {
  RgbDepthCameraConfig cfg;
  cfg.rgb = PinholeIntrinsics{900.0, 900.0, 640.0, 480.0, 1280, 960};
  cfg.depth = PinholeIntrinsics{450.0, 450.0, 320.0, 240.0, 640, 480};
  cfg.R_dr = Eigen::Matrix3d::Identity();
  cfg.t_dr = Eigen::Vector3d::Zero();
  cfg.depth_scale = 0.001;
  return cfg;
}

// depth_m: a synthetic z=2.0 fronto-parallel plane visible everywhere the
// RGB bbox mask (after depth->rgb reprojection) would land, i.e. the whole
// depth image, since the plane is much larger than the bbox' footprint.
cv::Mat make_flat_plane_depth(int h, int w, double z) {
  return cv::Mat(h, w, CV_32FC1, cv::Scalar(static_cast<float>(z)));
}

}  // namespace

TEST(PipelineV3_2, PublishesBboxCentreRayHitAsTranslationOnUniformZ2Probe) {
  RgbDepthCameraConfig camera_cfg = make_synthetic_camera();
  cv::Mat depth = make_flat_plane_depth(480, 640, 2.0);
  // Centre is the RGB principal point (640, 480). On a uniform z=2 plane the
  // optical-axis ray hits (0, 0, 2), which is the published translation.
  Eigen::Vector4d bbox(340.0, 440.0, 940.0, 520.0);

  Stage2Config cfg;
  cfg.min_face_points = 100;
  EstimatePoseParams params;
  std::mt19937_64 rng(0);
  auto outcome = estimate_pose_chamfer_v3_2(bbox, depth, camera_cfg, cfg, params,
                                             std::nullopt, rng);
  ASSERT_TRUE(outcome.ok) << outcome.failure.failure_reason;
  EXPECT_NEAR(outcome.pose.tx, 0.0, 1e-12);
  EXPECT_NEAR(outcome.pose.ty, 0.0, 1e-12);
  EXPECT_NEAR(outcome.pose.tz, 2.0, 1e-12);
}

TEST(PipelineV3_2, RecoversFrontoParallelPoseOnSyntheticScene) {
  RgbDepthCameraConfig camera_cfg = make_synthetic_camera();
  cv::Mat depth = make_flat_plane_depth(480, 640, 2.0);

  // bbox centred on the RGB principal point, sized so its depth-frame
  // footprint (at z=2m) covers enough of the (flat, textureless) depth
  // plane to satisfy min_face_points.
  Eigen::Vector4d bbox(640.0 - 300.0, 480.0 - 40.0, 640.0 + 300.0, 480.0 + 40.0);

  Stage2Config cfg;
  cfg.min_face_points = 100;

  EstimatePoseParams params;  // all v3.2 defaults (see plan Global Constraints)

  std::mt19937_64 rng(0);
  auto outcome = estimate_pose_chamfer_v3_2(bbox, depth, camera_cfg, cfg, params,
                                             /*instance_id=*/std::nullopt, rng);
  ASSERT_TRUE(outcome.ok) << (outcome.ok ? "" : outcome.failure.failure_reason);
  EXPECT_NEAR(outcome.pose.tz, 2.0, 0.01);
  EXPECT_NEAR(outcome.pose.yaw_rad, 0.0, 0.05);
  EXPECT_GT(outcome.pose.plane_inlier_ratio, 0.9);
}

TEST(PipelineV3_2, ReportsCameraFrameExtentOfValidFacePoints) {
  RgbDepthCameraConfig camera_cfg;
  camera_cfg.rgb = PinholeIntrinsics{450.0, 450.0, 320.0, 240.0, 640, 480};
  camera_cfg.depth = camera_cfg.rgb;
  camera_cfg.R_dr = Eigen::Matrix3d::Identity();
  camera_cfg.t_dr = Eigen::Vector3d::Zero();
  camera_cfg.depth_scale = 0.001;

  // Filled rectangle whose integer-pixel back-projection at 2.5 m spans
  // 1.0 m in x and 0.8 m in y. The bbox is larger than that rectangle so
  // the default erosion still admits every valid depth pixel.
  const int u0 = 230;
  const int u1 = 410;
  const int v0 = 168;
  const int v1 = 312;
  const double z_face = 2.5;
  cv::Mat depth = cv::Mat::zeros(480, 640, CV_32FC1);
  for (int v = v0; v <= v1; ++v) {
    for (int u = u0; u <= u1; ++u) {
      depth.at<float>(v, u) = static_cast<float>(z_face);
    }
  }
  Eigen::Vector4d bbox(224.0, 162.0, 416.0, 318.0);

  Stage2Config cfg;
  cfg.min_face_points = 100;
  EstimatePoseParams params;
  std::mt19937_64 rng(0);
  auto outcome = estimate_pose_chamfer_v3_2(bbox, depth, camera_cfg, cfg, params,
                                             std::nullopt, rng);
  ASSERT_TRUE(outcome.ok) << outcome.failure.failure_reason;
  EXPECT_TRUE(outcome.has_dimensions);
  EXPECT_NEAR(outcome.width_m, 1.0, 1e-9);
  EXPECT_NEAR(outcome.height_m, 0.8, 1e-9);
  EXPECT_NEAR(outcome.depth_m, 2.5, 1e-9);
}

TEST(PipelineV3_2, EmptyBboxAfterErosionFails) {
  RgbDepthCameraConfig camera_cfg = make_synthetic_camera();
  cv::Mat depth = make_flat_plane_depth(480, 640, 2.0);
  Eigen::Vector4d degenerate_bbox(10.0, 10.0, 10.0, 10.0);  // zero area

  Stage2Config cfg;
  EstimatePoseParams params;
  std::mt19937_64 rng(0);
  auto outcome = estimate_pose_chamfer_v3_2(degenerate_bbox, depth, camera_cfg, cfg,
                                             params, std::nullopt, rng);
  EXPECT_FALSE(outcome.ok);
  EXPECT_EQ(outcome.failure.failure_reason, "bbox empty after erosion");
}
