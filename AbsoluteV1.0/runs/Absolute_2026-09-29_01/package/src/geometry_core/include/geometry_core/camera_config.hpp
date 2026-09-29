#pragma once

#include <string>

#include <Eigen/Dense>

namespace geometry_core {

struct PinholeIntrinsics {
  double fx = 0.0;
  double fy = 0.0;
  double cx = 0.0;
  double cy = 0.0;
  int width = 0;
  int height = 0;

  PinholeIntrinsics() = default;
  PinholeIntrinsics(double fx_, double fy_, double cx_, double cy_, int width_,
                    int height_)
      : fx(fx_), fy(fy_), cx(cx_), cy(cy_), width(width_), height(height_) {}

  Eigen::Matrix3d K() const;
  Eigen::Matrix3d K_inv() const;

 private:
  // Cache assumes fx/fy/cx/cy are not mutated after the first K()/K_inv() call.
  mutable bool cached_ = false;
  mutable Eigen::Matrix3d K_cached_ = Eigen::Matrix3d::Identity();
  mutable Eigen::Matrix3d K_inv_cached_ = Eigen::Matrix3d::Identity();
  void ensure_cached() const;
};

struct RgbDepthCameraConfig {
  PinholeIntrinsics rgb;
  PinholeIntrinsics depth;
  Eigen::Matrix3d R_dr = Eigen::Matrix3d::Identity();  // depth -> rgb rotation
  Eigen::Vector3d t_dr = Eigen::Vector3d::Zero();       // depth -> rgb translation (m)
  double depth_scale = 0.001;

  static RgbDepthCameraConfig from_yaml(const std::string& path);
};

}  // namespace geometry_core
