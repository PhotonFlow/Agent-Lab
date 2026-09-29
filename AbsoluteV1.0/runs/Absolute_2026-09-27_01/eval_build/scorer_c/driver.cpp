#include <chrono>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <optional>
#include <random>

#include "geometry_core/pipeline_v3_2.hpp"

int main() {
  using geometry_core::EstimatePoseParams;
  using geometry_core::PinholeIntrinsics;
  using geometry_core::RgbDepthCameraConfig;
  using geometry_core::Stage2Config;
  using geometry_core::estimate_pose_chamfer_v3_2;

  RgbDepthCameraConfig camera_cfg;
  camera_cfg.rgb = PinholeIntrinsics{900.0, 900.0, 640.0, 480.0, 1280, 960};
  camera_cfg.depth = PinholeIntrinsics{450.0, 450.0, 320.0, 240.0, 640, 480};
  camera_cfg.R_dr = Eigen::Matrix3d::Identity();
  camera_cfg.t_dr = Eigen::Vector3d::Zero();
  camera_cfg.depth_scale = 0.001;

  Stage2Config cfg;
  cfg.min_face_points = 100;
  EstimatePoseParams params;

  const Eigen::Vector4d bbox(340.0, 440.0, 940.0, 520.0);
  const double depths[3] = {1.5, 2.0, 2.5};

  double err_sum = 0.0;
  double ms_sum = 0.0;
  for (double z : depths) {
    cv::Mat depth(480, 640, CV_32FC1);
    depth.setTo(static_cast<float>(z));
    std::mt19937_64 rng(0);

    const auto t0 = std::chrono::steady_clock::now();
    const auto outcome = estimate_pose_chamfer_v3_2(
        bbox, depth, camera_cfg, cfg, params, std::nullopt, rng);
    const auto t1 = std::chrono::steady_clock::now();

    if (!outcome.ok) {
      std::cerr << outcome.failure.failure_reason << std::endl;
      return 1;
    }

    const double dtx = outcome.pose.tx;
    const double dty = outcome.pose.ty;
    const double dtz = outcome.pose.tz - z;
    err_sum += std::sqrt(dtx * dtx + dty * dty + dtz * dtz);
    ms_sum += std::chrono::duration<double, std::milli>(t1 - t0).count();
  }

  const double pose_error_m = err_sum / 3.0;
  const double latency_ms = ms_sum / 3.0;
  std::cout << std::setprecision(17) << pose_error_m << " " << latency_ms << "\n";
  return 0;
}
