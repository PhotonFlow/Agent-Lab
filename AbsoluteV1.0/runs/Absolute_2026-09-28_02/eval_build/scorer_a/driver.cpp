#include <chrono>
#include <cmath>
#include <iostream>
#include <optional>
#include <random>
#include <string>
#include <vector>

#include <Eigen/Dense>
#include <opencv2/core.hpp>

#include "geometry_core/pipeline_v3_2.hpp"
#include "pps_pallet_pose_cpp/detection_utils.hpp"

namespace {

bool is_must_defer(int source_index) {
  return source_index == 0 || source_index == 3 || source_index == 4;
}

std::vector<pps_pallet_pose_cpp::DetectionCandidate> make_candidates() {
  const double scores[5] = {0.99, 0.70, 0.60, 0.50, 0.40};
  const double areas[5] = {2000.0, 50000.0, 40000.0, 30000.0, 1000.0};
  std::vector<pps_pallet_pose_cpp::DetectionCandidate> candidates;
  candidates.reserve(5);
  for (int i = 0; i < 5; ++i) {
    pps_pallet_pose_cpp::DetectionCandidate c;
    c.bbox_xyxy = Eigen::Vector4d(0.0, 0.0, 10.0, 10.0);
    c.score = scores[i];
    c.class_id = "pallet";
    c.area_px = areas[i];
    c.source_index = i;
    candidates.push_back(c);
  }
  return candidates;
}

double selection_error_from(const std::vector<int>& admitted,
                            const std::vector<int>& deferred) {
  int bad_admitted = 0;
  for (int idx : admitted) {
    if (is_must_defer(idx)) {
      ++bad_admitted;
    }
  }
  int missing_deferred = 0;
  const int must_defer[3] = {0, 3, 4};
  for (int want : must_defer) {
    bool found = false;
    for (int idx : deferred) {
      if (idx == want) {
        found = true;
        break;
      }
    }
    if (!found) {
      ++missing_deferred;
    }
  }
  return static_cast<double>(bad_admitted) + 0.25 * static_cast<double>(missing_deferred);
}

}  // namespace

int main() {
  geometry_core::RgbDepthCameraConfig camera_cfg;
  camera_cfg.rgb = geometry_core::PinholeIntrinsics{900.0, 900.0, 640.0, 480.0, 1280, 960};
  camera_cfg.depth = geometry_core::PinholeIntrinsics{450.0, 450.0, 320.0, 240.0, 640, 480};
  camera_cfg.R_dr = Eigen::Matrix3d::Identity();
  camera_cfg.t_dr = Eigen::Vector3d::Zero();
  camera_cfg.depth_scale = 0.001;

  cv::Mat depth(480, 640, CV_32FC1, cv::Scalar(2.0f));
  const Eigen::Vector4d bbox(340.0, 440.0, 940.0, 520.0);

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
  const double pose_error_m =
      std::sqrt(tx * tx + ty * ty + (tz - 2.0) * (tz - 2.0));

  const double dimension_error_m = 3.0;

  const auto candidates = make_candidates();
  const auto admission = pps_pallet_pose_cpp::select_stage2_subset(
      candidates, "largest_area", static_cast<std::size_t>(2));
  std::vector<int> admitted;
  std::vector<int> deferred;
  admitted.reserve(admission.admitted.size());
  deferred.reserve(admission.deferred.size());
  for (const auto& c : admission.admitted) {
    admitted.push_back(c.source_index);
  }
  for (const auto& c : admission.deferred) {
    deferred.push_back(c.source_index);
  }
  const double selection_error = selection_error_from(admitted, deferred);

  if (!std::isfinite(pose_error_m) || !std::isfinite(latency_ms) ||
      !std::isfinite(dimension_error_m) || !std::isfinite(selection_error)) {
    std::cerr << "non-finite metric" << std::endl;
    return 1;
  }

  std::cout.precision(17);
  std::cout << pose_error_m << " " << latency_ms << " " << dimension_error_m << " "
            << selection_error << "\n";
  return 0;
}
