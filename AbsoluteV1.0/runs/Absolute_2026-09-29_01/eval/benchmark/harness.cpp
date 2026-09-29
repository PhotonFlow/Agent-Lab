// Runs estimate_pose_chamfer_v3_2 on the analytical scene in bench_scene.hpp.
// Prints raw pose and one warm-cache timing. The Python oracle turns those
// numbers into pose_error_m. This file does not embed an expected score.

#include "bench_scene.hpp"

#include <chrono>
#include <iostream>
#include <random>

#include <opencv2/core.hpp>

#include "geometry_core/pipeline_v3_2.hpp"

namespace {

geometry_core::RgbDepthCameraConfig make_camera() {
  geometry_core::RgbDepthCameraConfig camera;
  camera.rgb = geometry_core::PinholeIntrinsics{
      bench_scene::kRgbFx, bench_scene::kRgbFy, bench_scene::kRgbCx,
      bench_scene::kRgbCy, bench_scene::kRgbWidth, bench_scene::kRgbHeight};
  camera.depth = geometry_core::PinholeIntrinsics{
      bench_scene::kDepthFx, bench_scene::kDepthFy, bench_scene::kDepthCx,
      bench_scene::kDepthCy, bench_scene::kDepthWidth, bench_scene::kDepthHeight};
  camera.R_dr = Eigen::Matrix3d::Identity();
  camera.t_dr = Eigen::Vector3d::Zero();
  camera.depth_scale = 0.001;
  return camera;
}

}  // namespace

int main() {
  const geometry_core::RgbDepthCameraConfig camera = make_camera();
  const cv::Mat depth(bench_scene::kDepthHeight, bench_scene::kDepthWidth, CV_32FC1,
                      cv::Scalar(static_cast<float>(bench_scene::kPlaneZM)));
  const Eigen::Vector4d bbox(
      bench_scene::kRgbCx - bench_scene::kBboxHalfWidthPx,
      bench_scene::kRgbCy - bench_scene::kBboxHalfHeightPx,
      bench_scene::kRgbCx + bench_scene::kBboxHalfWidthPx,
      bench_scene::kRgbCy + bench_scene::kBboxHalfHeightPx);
  const geometry_core::Stage2Config cfg;
  const geometry_core::EstimatePoseParams params;

  {
    std::mt19937_64 warmup(1);
    (void)geometry_core::estimate_pose_chamfer_v3_2(bbox, depth, camera, cfg, params,
                                                     std::nullopt, warmup);
  }

  std::mt19937_64 rng(0);
  const auto t0 = std::chrono::steady_clock::now();
  const geometry_core::EstimatePoseOutcome outcome =
      geometry_core::estimate_pose_chamfer_v3_2(bbox, depth, camera, cfg, params,
                                                 std::nullopt, rng);
  const auto t1 = std::chrono::steady_clock::now();
  const double latency_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();

  std::cout.setf(std::ios::fmtflags(0), std::ios::floatfield);
  std::cout.precision(17);
  std::cout << "ok " << (outcome.ok ? 1 : 0) << "\n";
  std::cout << "tx " << outcome.pose.tx << "\n";
  std::cout << "ty " << outcome.pose.ty << "\n";
  std::cout << "tz " << outcome.pose.tz << "\n";
  std::cout << "yaw " << outcome.pose.yaw_rad << "\n";
  std::cout << "latency_ms " << latency_ms << "\n";
  return 0;
}
