#include <cstdio>
#include <fstream>
#include <stdexcept>

#include <gtest/gtest.h>

#include "geometry_core/camera_config.hpp"

using geometry_core::RgbDepthCameraConfig;

namespace {
std::string write_temp_yaml(const std::string& contents) {
  const std::string path = std::tmpnam(nullptr);
  std::ofstream out(path);
  out << contents;
  out.close();
  return path;
}

constexpr const char* kValidYaml = R"YAML(
rgb_camera:
  width: 1280
  height: 960
  fx: 900.0
  fy: 900.0
  cx: 640.0
  cy: 480.0
  distortion: {k1: 0.0, k2: 0.0, p1: 0.0, p2: 0.0, k3: 0.0}
depth_camera:
  width: 640
  height: 480
  fx: 450.0
  fy: 450.0
  cx: 320.0
  cy: 240.0
  distortion: {k1: 0.0, k2: 0.0, p1: 0.0, p2: 0.0, k3: 0.0}
depth_to_rgb_extrinsic:
  rotation: [[1,0,0],[0,1,0],[0,0,1]]
  translation_mm: {x: 25.0, y: 0.0, z: 0.0}
depth_scale: 0.001
)YAML";
}  // namespace

TEST(CameraConfig, LoadsValidYamlAndConvertsMmToMetres) {
  const std::string path = write_temp_yaml(kValidYaml);
  RgbDepthCameraConfig cfg = RgbDepthCameraConfig::from_yaml(path);
  std::remove(path.c_str());

  EXPECT_EQ(cfg.rgb.width, 1280);
  EXPECT_EQ(cfg.rgb.height, 960);
  EXPECT_DOUBLE_EQ(cfg.rgb.fx, 900.0);
  EXPECT_DOUBLE_EQ(cfg.depth.fx, 450.0);
  EXPECT_NEAR(cfg.t_dr.x(), 0.025, 1e-12);  // 25mm -> 0.025m
  EXPECT_NEAR(cfg.depth_scale, 0.001, 1e-12);
  EXPECT_TRUE(cfg.R_dr.isApprox(Eigen::Matrix3d::Identity()));
}

TEST(CameraConfig, KMatrixIsPinhole) {
  const std::string path = write_temp_yaml(kValidYaml);
  RgbDepthCameraConfig cfg = RgbDepthCameraConfig::from_yaml(path);
  std::remove(path.c_str());
  Eigen::Matrix3d K = cfg.rgb.K();
  EXPECT_DOUBLE_EQ(K(0, 0), 900.0);
  EXPECT_DOUBLE_EQ(K(1, 1), 900.0);
  EXPECT_DOUBLE_EQ(K(0, 2), 640.0);
  EXPECT_DOUBLE_EQ(K(1, 2), 480.0);
  Eigen::Matrix3d K_inv = cfg.rgb.K_inv();
  EXPECT_TRUE((K * K_inv).isApprox(Eigen::Matrix3d::Identity(), 1e-9));
}

TEST(CameraConfig, NonZeroDistortionThrows) {
  std::string bad_yaml = std::string(kValidYaml);
  const auto pos = bad_yaml.find("k1: 0.0, k2: 0.0, p1: 0.0, p2: 0.0, k3: 0.0}\ndepth_camera");
  bad_yaml.replace(pos, std::string("k1: 0.0, k2: 0.0, p1: 0.0, p2: 0.0, k3: 0.0}").size(),
                    "k1: 0.1, k2: 0.0, p1: 0.0, p2: 0.0, k3: 0.0}");
  const std::string path = write_temp_yaml(bad_yaml);
  EXPECT_THROW(RgbDepthCameraConfig::from_yaml(path), std::invalid_argument);
  std::remove(path.c_str());
}
