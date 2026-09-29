#include <chrono>
#include <cmath>
#include <cstdio>
#include <optional>
#include <random>
#include <string>
#include <vector>

#include <Eigen/Dense>
#include <opencv2/core.hpp>

#include "geometry_core/camera_config.hpp"
#include "geometry_core/pipeline_v3_2.hpp"
#include "geometry_core/schemas.hpp"
#include "pps_pallet_pose_cpp/detection_utils.hpp"

int main() {
  geometry_core::RgbDepthCameraConfig camera;
  camera.rgb = geometry_core::PinholeIntrinsics(900.0, 900.0, 640.0, 480.0, 1280, 960);
  camera.depth = geometry_core::PinholeIntrinsics(450.0, 450.0, 320.0, 240.0, 640, 480);
  camera.R_dr = Eigen::Matrix3d::Identity();
  camera.t_dr = Eigen::Vector3d::Zero();
  camera.depth_scale = 0.001;

  cv::Mat depth(480, 640, CV_32FC1, cv::Scalar(2.0f));
  const Eigen::Vector4d bbox(340.0, 440.0, 940.0, 520.0);
  geometry_core::Stage2Config cfg;
  cfg.min_face_points = 100;
  geometry_core::EstimatePoseParams params;
  std::mt19937_64 rng(0);

  const auto t0 = std::chrono::steady_clock::now();
  const auto outcome = geometry_core::estimate_pose_chamfer_v3_2(
      bbox, depth, camera, cfg, params, std::nullopt, rng);
  const auto t1 = std::chrono::steady_clock::now();
  const double latency_ms =
      std::chrono::duration<double, std::milli>(t1 - t0).count();

  if (!outcome.ok) {
    std::fprintf(stderr, "estimate_pose_chamfer_v3_2 failed: %s\n",
                 outcome.failure.failure_reason.c_str());
    return 2;
  }

  std::printf("POSE_OK=1\n");
  std::printf("TX=%.17g\n", outcome.pose.tx);
  std::printf("TY=%.17g\n", outcome.pose.ty);
  std::printf("TZ=%.17g\n", outcome.pose.tz);
  std::printf("LATENCY_MS=%.17g\n", latency_ms);

  std::printf("DIM_RAN=0\n");
  std::printf("HAS_DIMENSIONS=0\n");
  std::printf("WIDTH_M=nan\n");
  std::printf("HEIGHT_M=nan\n");
  std::printf("DEPTH_M=nan\n");

  std::vector<pps_pallet_pose_cpp::DetectionCandidate> candidates(5);
  const double scores[5] = {0.99, 0.70, 0.60, 0.50, 0.40};
  const double areas[5] = {2000.0, 50000.0, 40000.0, 30000.0, 1000.0};
  for (int i = 0; i < 5; ++i) {
    candidates[i].bbox_xyxy = Eigen::Vector4d(0.0, 0.0, 1.0, 1.0);
    candidates[i].score = scores[i];
    candidates[i].class_id = "pallet";
    candidates[i].area_px = areas[i];
    candidates[i].source_index = i;
  }

  const auto chosen = pps_pallet_pose_cpp::select_detection(candidates, "highest_confidence");
  if (!chosen.has_value()) {
    std::fprintf(stderr, "select_detection returned empty\n");
    return 2;
  }
  std::printf("ADMITTED=%d\n", chosen->source_index);
  std::printf("DEFERRED=\n");

  return 0;
}
