#include <iostream>
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
  const Eigen::Vector4d bbox(340.0, 440.0, 940.0, 520.0);
  geometry_core::Stage2Config cfg;
  cfg.min_face_points = 100;
  geometry_core::EstimatePoseParams params;
  std::mt19937_64 rng(0);
  const auto outcome = geometry_core::estimate_pose_chamfer_v3_2(
      bbox, depth, camera_cfg, cfg, params, std::nullopt, rng);
  if (!outcome.ok) {
    std::cerr << outcome.failure.failure_reason << "\n";
    return 1;
  }
  std::cout.precision(17);
  std::cout << outcome.pose.tx << " " << outcome.pose.ty << " " << outcome.pose.tz << " "
            << outcome.pose.plane_offset_depth_m << "\n";
  return 0;
}
