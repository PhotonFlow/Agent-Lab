#include "geometry_core/camera_config.hpp"

#include <cmath>
#include <stdexcept>

#include <yaml-cpp/yaml.h>

namespace geometry_core {

void PinholeIntrinsics::ensure_cached() const {
  if (cached_) {
    return;
  }
  K_cached_ << fx, 0.0, cx,
               0.0, fy, cy,
               0.0, 0.0, 1.0;
  K_inv_cached_ = K_cached_.inverse();
  cached_ = true;
}

Eigen::Matrix3d PinholeIntrinsics::K() const {
  ensure_cached();
  return K_cached_;
}

Eigen::Matrix3d PinholeIntrinsics::K_inv() const {
  ensure_cached();
  return K_inv_cached_;
}

namespace {

void check_zero_distortion(const YAML::Node& block, const std::string& label) {
  const YAML::Node distortion = block["distortion"];
  if (!distortion) {
    return;
  }
  for (const char* key : {"k1", "k2", "p1", "p2", "k3"}) {
    if (distortion[key]) {
      const double value = distortion[key].as<double>();
      if (std::abs(value) > 1e-9) {
        throw std::invalid_argument(label + ".distortion." + key + "=" +
                                     std::to_string(value) +
                                     " is non-zero; pinhole-only model assumed");
      }
    }
  }
}

PinholeIntrinsics parse_intrinsics(const YAML::Node& block, int default_w,
                                    int default_h, const std::string& label) {
  check_zero_distortion(block, label);
  PinholeIntrinsics intr;
  intr.width = block["width"] ? block["width"].as<int>() : default_w;
  intr.height = block["height"] ? block["height"].as<int>() : default_h;
  intr.fx = block["fx"].as<double>();
  intr.fy = block["fy"].as<double>();
  intr.cx = block["cx"].as<double>();
  intr.cy = block["cy"].as<double>();
  return intr;
}

bool is_rotation(const Eigen::Matrix3d& r, double atol = 1e-4) {
  const Eigen::Matrix3d should_be_identity = r * r.transpose();
  if (!should_be_identity.isApprox(Eigen::Matrix3d::Identity(), atol)) {
    return false;
  }
  return std::abs(r.determinant() - 1.0) < atol;
}

}  // namespace

RgbDepthCameraConfig RgbDepthCameraConfig::from_yaml(const std::string& path) {
  const YAML::Node data = YAML::LoadFile(path);

  RgbDepthCameraConfig cfg;
  cfg.rgb = parse_intrinsics(data["rgb_camera"], 1280, 960, "rgb_camera");
  cfg.depth = parse_intrinsics(data["depth_camera"], 640, 480, "depth_camera");

  const YAML::Node extr = data["depth_to_rgb_extrinsic"];
  const YAML::Node rot = extr["rotation"];
  if (rot.size() != 3) {
    throw std::invalid_argument("expected 3x3 rotation");
  }
  Eigen::Matrix3d R_dr;
  for (int i = 0; i < 3; ++i) {
    if (rot[i].size() != 3) {
      throw std::invalid_argument("expected 3x3 rotation");
    }
    for (int j = 0; j < 3; ++j) {
      R_dr(i, j) = rot[i][j].as<double>();
    }
  }
  if (!is_rotation(R_dr)) {
    throw std::invalid_argument(
        "depth_to_rgb_extrinsic.rotation is not a proper rotation "
        "(R^T R != I or det != 1)");
  }
  cfg.R_dr = R_dr;

  if (extr["translation_mm"]) {
    const YAML::Node t = extr["translation_mm"];
    cfg.t_dr = Eigen::Vector3d(t["x"].as<double>(), t["y"].as<double>(),
                                t["z"].as<double>()) *
               1e-3;
  } else if (extr["translation_m"]) {
    const YAML::Node t = extr["translation_m"];
    cfg.t_dr = Eigen::Vector3d(t["x"].as<double>(), t["y"].as<double>(),
                                t["z"].as<double>());
  } else {
    throw std::invalid_argument(
        "depth_to_rgb_extrinsic must contain 'translation_mm' or 'translation_m'");
  }

  cfg.depth_scale = data["depth_scale"] ? data["depth_scale"].as<double>() : 0.001;
  return cfg;
}

}  // namespace geometry_core
