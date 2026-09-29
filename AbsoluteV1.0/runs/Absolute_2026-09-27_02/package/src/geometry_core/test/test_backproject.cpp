#include <gtest/gtest.h>

#include "geometry_core/backproject.hpp"

using geometry_core::backproject_depth_grid;
using geometry_core::FaceSamples;
using geometry_core::Plane;
using geometry_core::RgbDepthCameraConfig;
using geometry_core::sample_face_points;
using geometry_core::ray_plane_intersect_cross_camera;
using geometry_core::Stage2Config;

namespace {
RgbDepthCameraConfig make_identity_camera(int w, int h, double f) {
  RgbDepthCameraConfig cfg;
  cfg.rgb.width = w;
  cfg.rgb.height = h;
  cfg.rgb.fx = f;
  cfg.rgb.fy = f;
  cfg.rgb.cx = w / 2.0;
  cfg.rgb.cy = h / 2.0;
  cfg.depth = cfg.rgb;  // identical cameras, coincident (identity extrinsic)
  cfg.R_dr = Eigen::Matrix3d::Identity();
  cfg.t_dr = Eigen::Vector3d::Zero();
  cfg.depth_scale = 0.001;
  return cfg;
}
}  // namespace

TEST(Backproject, BackprojectDepthGridKnownPoint) {
  Eigen::Matrix3d K;
  K << 100.0, 0.0, 50.0, 0.0, 100.0, 50.0, 0.0, 0.0, 1.0;
  cv::Mat depth = cv::Mat::zeros(4, 4, CV_32FC1);
  depth.at<float>(2, 2) = 2.0f;  // row=2 (v), col=2 (u), z=2.0
  Eigen::MatrixXd pts = backproject_depth_grid(depth, K.inverse());
  const int idx = 2 * 4 + 2;  // row-major (H,W) flatten: row*W + col
  EXPECT_NEAR(pts(idx, 2), 2.0, 1e-9);
}

TEST(Backproject, SampleFacePointsAcceptsOnlyMaskedPixels) {
  RgbDepthCameraConfig cfg = make_identity_camera(20, 20, 50.0);
  cv::Mat depth = cv::Mat::ones(20, 20, CV_32FC1) * 1.0f;  // 1m everywhere
  cv::Mat mask = cv::Mat::zeros(20, 20, CV_8UC1);
  mask(cv::Rect(5, 5, 5, 5)).setTo(1);  // 25-pixel face region

  Stage2Config s2cfg;
  s2cfg.depth_min_m = 0.3;
  s2cfg.depth_max_m = 5.0;
  s2cfg.rgb_clip_margin_px = 0;

  FaceSamples samples = sample_face_points(depth, mask, cfg, s2cfg);
  EXPECT_EQ(samples.points_depth_frame.rows(), 25);
  for (int i = 0; i < samples.points_depth_frame.rows(); ++i) {
    EXPECT_NEAR(samples.points_depth_frame(i, 2), 1.0, 1e-6);
  }
}

TEST(Backproject, SampleFacePointsRejectsOutOfRangeDepth) {
  RgbDepthCameraConfig cfg = make_identity_camera(10, 10, 50.0);
  cv::Mat depth = cv::Mat::ones(10, 10, CV_32FC1) * 10.0f;  // beyond depth_max_m
  cv::Mat mask = cv::Mat::ones(10, 10, CV_8UC1);
  Stage2Config s2cfg;
  s2cfg.depth_min_m = 0.3;
  s2cfg.depth_max_m = 5.0;
  FaceSamples samples = sample_face_points(depth, mask, cfg, s2cfg);
  EXPECT_EQ(samples.points_depth_frame.rows(), 0);
}

TEST(Backproject, RayPlaneIntersectCrossCameraFindsPointOnPlane) {
  RgbDepthCameraConfig cfg = make_identity_camera(20, 20, 50.0);
  // Plane z = 2.0 in depth frame, normal toward camera => normal=(0,0,-1), offset=2.0
  Plane plane{Eigen::Vector3d(0.0, 0.0, -1.0), 2.0, 1.0, 100};
  Eigen::Vector2d uv(10.0, 10.0);  // principal point -> ray along +z
  Eigen::Vector3d p = ray_plane_intersect_cross_camera(uv, cfg, plane);
  EXPECT_NEAR(p.x(), 0.0, 1e-9);
  EXPECT_NEAR(p.y(), 0.0, 1e-9);
  EXPECT_NEAR(p.z(), 2.0, 1e-9);
}
