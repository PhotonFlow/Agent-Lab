#include <cmath>

#include <gtest/gtest.h>

#include "geometry_core/transforms.hpp"

using geometry_core::apply_se3;
using geometry_core::apply_se3_batch;
using geometry_core::invert_se3;
using geometry_core::pixel_ray;
using geometry_core::project_pinhole;
using geometry_core::project_pinhole_batch;

TEST(Transforms, ApplySe3IdentityRotation) {
  Eigen::Matrix3d R = Eigen::Matrix3d::Identity();
  Eigen::Vector3d t(1.0, 2.0, 3.0);
  Eigen::Vector3d p(0.0, 0.0, 0.0);
  Eigen::Vector3d out = apply_se3(R, t, p);
  EXPECT_NEAR(out.x(), 1.0, 1e-12);
  EXPECT_NEAR(out.y(), 2.0, 1e-12);
  EXPECT_NEAR(out.z(), 3.0, 1e-12);
}

TEST(Transforms, ApplySe3BatchMatchesSingle) {
  Eigen::Matrix3d R;
  R << 0, -1, 0,
       1,  0, 0,
       0,  0, 1;  // 90 deg about z
  Eigen::Vector3d t(0.5, -0.5, 1.0);
  Eigen::MatrixXd pts(2, 3);
  pts << 1.0, 0.0, 0.0,
         0.0, 1.0, 0.0;
  Eigen::MatrixXd out = apply_se3_batch(R, t, pts);
  Eigen::Vector3d single0 = apply_se3(R, t, Eigen::Vector3d(1.0, 0.0, 0.0));
  Eigen::Vector3d single1 = apply_se3(R, t, Eigen::Vector3d(0.0, 1.0, 0.0));
  EXPECT_NEAR(out(0, 0), single0.x(), 1e-12);
  EXPECT_NEAR(out(0, 1), single0.y(), 1e-12);
  EXPECT_NEAR(out(0, 2), single0.z(), 1e-12);
  EXPECT_NEAR(out(1, 0), single1.x(), 1e-12);
  EXPECT_NEAR(out(1, 1), single1.y(), 1e-12);
  EXPECT_NEAR(out(1, 2), single1.z(), 1e-12);
}

TEST(Transforms, InvertSe3RoundTrips) {
  Eigen::Matrix3d R;
  R << 0, -1, 0,
       1,  0, 0,
       0,  0, 1;
  Eigen::Vector3d t(0.5, -0.5, 1.0);
  Eigen::Matrix3d R_inv;
  Eigen::Vector3d t_inv;
  invert_se3(R, t, R_inv, t_inv);
  Eigen::Vector3d p(1.0, 2.0, 3.0);
  Eigen::Vector3d transformed = apply_se3(R, t, p);
  Eigen::Vector3d back = apply_se3(R_inv, t_inv, transformed);
  EXPECT_NEAR(back.x(), p.x(), 1e-9);
  EXPECT_NEAR(back.y(), p.y(), 1e-9);
  EXPECT_NEAR(back.z(), p.z(), 1e-9);
}

TEST(Transforms, ProjectPinholeKnownPoint) {
  Eigen::Matrix3d K;
  K << 100.0, 0.0, 50.0,
       0.0, 100.0, 50.0,
       0.0, 0.0, 1.0;
  Eigen::Vector3d p(1.0, 2.0, 10.0);
  Eigen::Vector2d uv = project_pinhole(p, K);
  EXPECT_NEAR(uv.x(), 60.0, 1e-9);   // 100*1/10 + 50
  EXPECT_NEAR(uv.y(), 70.0, 1e-9);   // 100*2/10 + 50
}

TEST(Transforms, ProjectPinholeNonPositiveDepthIsNan) {
  Eigen::Matrix3d K = Eigen::Matrix3d::Identity();
  Eigen::Vector2d uv = project_pinhole(Eigen::Vector3d(1.0, 1.0, 0.0), K);
  EXPECT_TRUE(std::isnan(uv.x()));
  EXPECT_TRUE(std::isnan(uv.y()));
}

TEST(Transforms, ProjectPinholeBatchMasksInvalidRows) {
  Eigen::Matrix3d K;
  K << 100.0, 0.0, 50.0,
       0.0, 100.0, 50.0,
       0.0, 0.0, 1.0;
  Eigen::MatrixXd pts(2, 3);
  pts << 1.0, 2.0, 10.0,
         1.0, 1.0, -1.0;  // invalid: z <= 0
  Eigen::MatrixXd uv = project_pinhole_batch(pts, K);
  EXPECT_NEAR(uv(0, 0), 60.0, 1e-9);
  EXPECT_NEAR(uv(0, 1), 70.0, 1e-9);
  EXPECT_TRUE(std::isnan(uv(1, 0)));
  EXPECT_TRUE(std::isnan(uv(1, 1)));
}

TEST(Transforms, PixelRayInverseOfProjectAtUnitDepth) {
  Eigen::Matrix3d K;
  K << 100.0, 0.0, 50.0,
       0.0, 100.0, 50.0,
       0.0, 0.0, 1.0;
  Eigen::Matrix3d K_inv = K.inverse();
  Eigen::Vector2d uv(60.0, 70.0);
  Eigen::Vector3d ray = pixel_ray(uv, K_inv);
  // ray * z should reproject to the same uv for any z > 0.
  Eigen::Vector3d p3d = ray * 4.2;
  Eigen::Vector2d back = project_pinhole(p3d, K);
  EXPECT_NEAR(back.x(), uv.x(), 1e-9);
  EXPECT_NEAR(back.y(), uv.y(), 1e-9);
}
