#pragma once

#include <Eigen/Dense>

#include "geometry_core/plane_fit.hpp"

namespace geometry_core {

// 2D plane-local basis frame. Mirrors
// pallet_pose_estimation/geometry/plane_coords.py::PlaneBasis.
struct PlaneBasis {
  Eigen::Vector3d origin_3d = Eigen::Vector3d::Zero();
  Eigen::Vector3d axis_u = Eigen::Vector3d::Zero();
  Eigen::Vector3d axis_v = Eigen::Vector3d::Zero();
  Eigen::Vector3d normal = Eigen::Vector3d::Zero();
};

// Deterministic plane-local basis depending only on the plane (and a fixed
// up hint). If up_hint is null, defaults to (0, -1, 0) (matches Python
// default). Mirrors build_plane_basis_deterministic exactly, including the
// |up_hint . normal| > 0.95 fallback to (1, 0, 0) and the axis_u.x() < 0
// sign-flip convention.
PlaneBasis build_plane_basis_deterministic(const Plane& plane,
                                            const Eigen::Vector3d* up_hint = nullptr);

Eigen::MatrixXd project_points_to_plane_2d(
    const Eigen::Ref<const Eigen::MatrixXd>& points_3d, const PlaneBasis& basis);

Eigen::Vector3d lift_point_from_plane_2d(const Eigen::Vector2d& point_2d,
                                          const PlaneBasis& basis);

Eigen::MatrixXd lift_points_from_plane_2d(
    const Eigen::Ref<const Eigen::MatrixXd>& points_2d, const PlaneBasis& basis);

}  // namespace geometry_core
