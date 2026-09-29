#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <optional>
#include <random>
#include <vector>

#include "geometry_core/pipeline_v3_2.hpp"

namespace {

double pose_error_m(const geometry_core::PoseResult& pose) {
  const double dtx = pose.tx;
  const double dty = pose.ty;
  const double dtz = pose.tz - 2.0;
  const double dyaw = 0.6 * pose.yaw_rad;
  return std::sqrt(dtx * dtx + dty * dty + dtz * dtz + dyaw * dyaw);
}

double median5(std::vector<double> values) {
  std::sort(values.begin(), values.end());
  return values[2];
}

}  // namespace

int main() {
  geometry_core::RgbDepthCameraConfig camera_cfg;
  camera_cfg.rgb =
      geometry_core::PinholeIntrinsics{900.0, 900.0, 640.0, 480.0, 1280, 960};
  camera_cfg.depth =
      geometry_core::PinholeIntrinsics{450.0, 450.0, 320.0, 240.0, 640, 480};
  camera_cfg.R_dr = Eigen::Matrix3d::Identity();
  camera_cfg.t_dr = Eigen::Vector3d::Zero();
  camera_cfg.depth_scale = 0.001;

  cv::Mat depth(480, 640, CV_32FC1, cv::Scalar(2.0f));
  const Eigen::Vector4d bbox(340.0, 440.0, 940.0, 520.0);

  geometry_core::Stage2Config cfg;
  cfg.min_face_points = 100;

  geometry_core::EstimatePoseParams params;

  const auto call_once = [&]() {
    std::mt19937_64 rng(0);
    return geometry_core::estimate_pose_chamfer_v3_2(
        bbox, depth, camera_cfg, cfg, params, std::nullopt, rng);
  };

  {
    const auto warmup = call_once();
    if (!warmup.ok) {
      std::cerr << warmup.failure.failure_reason << std::endl;
      return 1;
    }
  }

  std::vector<double> errors;
  std::vector<double> latencies;
  errors.reserve(5);
  latencies.reserve(5);

  for (int i = 0; i < 5; ++i) {
    const auto t0 = std::chrono::steady_clock::now();
    const auto outcome = call_once();
    const auto t1 = std::chrono::steady_clock::now();
    if (!outcome.ok) {
      std::cerr << outcome.failure.failure_reason << std::endl;
      return 1;
    }
    const double ms =
        std::chrono::duration<double, std::milli>(t1 - t0).count();
    errors.push_back(pose_error_m(outcome.pose));
    latencies.push_back(ms);
  }

  const double pose_error = median5(errors);
  const double latency = median5(latencies);
  if (!std::isfinite(pose_error) || !std::isfinite(latency)) {
    std::cerr << "non-finite metric" << std::endl;
    return 1;
  }

  std::cout.precision(17);
  std::cout << pose_error << " " << latency << "\n";
  return 0;
}
