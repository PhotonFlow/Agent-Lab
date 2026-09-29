#include <chrono>
#include <cmath>
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
  geometry_core::EstimatePoseParams params;
  std::mt19937_64 rng(0);

  const auto t0 = std::chrono::steady_clock::now();
  const auto outcome = geometry_core::estimate_pose_chamfer_v3_2(
      bbox, depth, camera_cfg, cfg, params, std::nullopt, rng);
  const auto t1 = std::chrono::steady_clock::now();
  const double latency_ms =
      std::chrono::duration<double, std::milli>(t1 - t0).count();

  if (!outcome.ok) {
    std::cerr << outcome.failure.failure_reason << std::endl;
    return 1;
  }

  const double tx = outcome.pose.tx;
  const double ty = outcome.pose.ty;
  const double tz = outcome.pose.tz;
  const double pose_error_m = std::sqrt(tx * tx + ty * ty + (tz - 2.0) * (tz - 2.0));
  std::cout << pose_error_m << " " << latency_ms << "\n";
  return 0;
}
