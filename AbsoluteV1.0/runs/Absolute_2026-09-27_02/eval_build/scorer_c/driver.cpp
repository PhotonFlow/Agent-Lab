#include <chrono>
#include <iomanip>
#include <cmath>
#include <cstddef>
#include <iostream>
#include <optional>
#include <random>
#include <string>
#include <vector>

#include <Eigen/Dense>
#include <opencv2/core.hpp>

#include "geometry_core/pipeline_v3_2.hpp"
#include "pps_pallet_pose_cpp/detection_utils.hpp"

int main() {
  geometry_core::RgbDepthCameraConfig cam;
  cam.rgb = geometry_core::PinholeIntrinsics(900.0, 900.0, 640.0, 480.0, 1280, 960);
  cam.depth = geometry_core::PinholeIntrinsics(450.0, 450.0, 320.0, 240.0, 640, 480);
  cam.R_dr = Eigen::Matrix3d::Identity();
  cam.t_dr = Eigen::Vector3d::Zero();
  cam.depth_scale = 0.001;

  cv::Mat depth(480, 640, CV_32FC1, cv::Scalar(2.0f));
  Eigen::Vector4d bbox(340.0, 440.0, 940.0, 520.0);
  geometry_core::Stage2Config cfg;
  cfg.min_face_points = 100;
  geometry_core::EstimatePoseParams params;
  std::mt19937_64 rng(0);

  const auto t0 = std::chrono::steady_clock::now();
  auto outcome = geometry_core::estimate_pose_chamfer_v3_2(
      bbox, depth, cam, cfg, params, std::nullopt, rng);
  const auto t1 = std::chrono::steady_clock::now();
  const double latency_ms =
      std::chrono::duration<double, std::milli>(t1 - t0).count();

  if (!outcome.ok) {
    std::cerr << "estimate_pose_chamfer_v3_2 failed: " << outcome.failure.failure_reason
              << "\n";
    return 1;
  }
  const double tx = outcome.pose.tx;
  const double ty = outcome.pose.ty;
  const double tz = outcome.pose.tz;
  if (!std::isfinite(tx) || !std::isfinite(ty) || !std::isfinite(tz) ||
      !std::isfinite(latency_ms)) {
    std::cerr << "non-finite pose or latency\n";
    return 1;
  }
  std::cout.setf(std::ios::fmtflags(0), std::ios::floatfield);
  std::cout << std::setprecision(17);
  std::cout << "tx " << tx << "\n";
  std::cout << "ty " << ty << "\n";
  std::cout << "tz " << tz << "\n";
  std::cout << "latency_ms " << latency_ms << "\n";
  std::cout << "has_dimensions skip\n";

  std::vector<pps_pallet_pose_cpp::DetectionCandidate> cands(5);
  const double scores[5] = {0.99, 0.70, 0.60, 0.50, 0.40};
  const double areas[5] = {2000.0, 50000.0, 40000.0, 30000.0, 1000.0};
  for (int i = 0; i < 5; ++i) {
    cands[static_cast<std::size_t>(i)].bbox_xyxy = Eigen::Vector4d(0.0, 0.0, 1.0, 1.0);
    cands[static_cast<std::size_t>(i)].score = scores[i];
    cands[static_cast<std::size_t>(i)].class_id = "pallet";
    cands[static_cast<std::size_t>(i)].area_px = areas[i];
    cands[static_cast<std::size_t>(i)].source_index = i;
  }

  {
    auto chosen = pps_pallet_pose_cpp::select_detection(cands, "highest_confidence");
    if (!chosen.has_value()) {
      std::cerr << "select_detection returned empty\n";
      return 1;
    }
    std::cout << "admitted " << chosen->source_index << "\n";
    std::cout << "deferred\n";
  }

  return 0;
}
