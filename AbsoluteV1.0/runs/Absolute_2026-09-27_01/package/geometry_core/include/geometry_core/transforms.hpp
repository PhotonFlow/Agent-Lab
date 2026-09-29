#pragma once

#include <Eigen/Dense>

namespace geometry_core {

Eigen::Vector3d apply_se3(const Eigen::Matrix3d& R, const Eigen::Vector3d& t,
                           const Eigen::Vector3d& point);

Eigen::MatrixXd apply_se3_batch(const Eigen::Matrix3d& R,
                                 const Eigen::Vector3d& t,
                                 const Eigen::Ref<const Eigen::MatrixXd>& points_n3);

void invert_se3(const Eigen::Matrix3d& R, const Eigen::Vector3d& t,
                 Eigen::Matrix3d& R_inv, Eigen::Vector3d& t_inv);

// Returns (NaN, NaN) if point_cam.z() <= 0.
Eigen::Vector2d project_pinhole(const Eigen::Vector3d& point_cam,
                                 const Eigen::Matrix3d& K);

// Rows with z <= 0 are (NaN, NaN).
Eigen::MatrixXd project_pinhole_batch(
    const Eigen::Ref<const Eigen::MatrixXd>& points_cam_n3,
    const Eigen::Matrix3d& K);

Eigen::Vector3d pixel_ray(const Eigen::Vector2d& uv,
                           const Eigen::Matrix3d& K_inv);

}  // namespace geometry_core
