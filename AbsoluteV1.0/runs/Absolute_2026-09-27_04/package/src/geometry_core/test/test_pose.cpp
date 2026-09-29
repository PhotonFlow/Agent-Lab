#include <cmath>

#include <gtest/gtest.h>

#include "geometry_core/pose.hpp"

using geometry_core::yaw_from_normal_camera;

TEST(Pose, FrontalFaceYawIsZero) {
  Eigen::Vector3d n(0.0, 0.0, -1.0);
  EXPECT_NEAR(yaw_from_normal_camera(n), 0.0, 1e-12);
}

TEST(Pose, PositiveXComponentGivesPositiveYaw) {
  Eigen::Vector3d n(std::sin(0.3), 0.0, -std::cos(0.3));
  EXPECT_NEAR(yaw_from_normal_camera(n), 0.3, 1e-9);
}

TEST(Pose, NegativeXComponentGivesNegativeYaw) {
  Eigen::Vector3d n(-std::sin(0.3), 0.0, -std::cos(0.3));
  EXPECT_NEAR(yaw_from_normal_camera(n), -0.3, 1e-9);
}
