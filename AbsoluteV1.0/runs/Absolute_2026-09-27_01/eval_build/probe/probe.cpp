#include <iostream>
#include <optional>
#include <random>

#include <Eigen/Dense>
#include <opencv2/core.hpp>

#include "geometry_core/pipeline_v3_2.hpp"

int main() {
  geometry_core::RgbDepthCameraConfig camera_cfg;
  camera_cfg.rgb = geometry_core::PinholeIntrinsics{900.0, 900.0, 640.0, 480.0, 1280, 960};
  camera_cfg.depth = geometry_core::PinholeIntrinsics{450.0, 450.0, 320.0, 240.0, 640, 480};
  camera_cfg.R_dr = Eigen::Matrix3d::Identity();
  camera_cfg.t_dr = Eigen::Vector3d::Zero();
  camera_cfg.depth_scale = 0.001;

  cv::Mat depth(480, 640, CV_32FC1, cv::Scalar(2.0f));
  Eigen::Vector4d bbox(340.0, 440.0, 940.0, 520.0);

  geometry_core::Stage2Config cfg;
  cfg.min_face_points = 100;

  auto run = [&](const char* name, geometry_core::EstimatePoseParams params) {
    std::mt19937_64 rng(0);
    const auto outcome = geometry_core::estimate_pose_chamfer_v3_2(
        bbox, depth, camera_cfg, cfg, params, std::nullopt, rng);
    if (!outcome.ok) {
      std::cout << name << " FAIL " << outcome.failure.failure_reason << "\n";
      return;
    }
    const auto& p = outcome.pose;
    std::cout << name << " tx " << p.tx << " ty " << p.ty << " tz " << p.tz
              << " yaw " << p.yaw_rad << " theta " << outcome.debug.chamfer_theta_rad
              << " cost " << outcome.debug.chamfer_cost_m
              << " prior " << outcome.debug.used_prior_fallback << "\n";
  };

  run("snapped", geometry_core::EstimatePoseParams{});
  return 0;
}
