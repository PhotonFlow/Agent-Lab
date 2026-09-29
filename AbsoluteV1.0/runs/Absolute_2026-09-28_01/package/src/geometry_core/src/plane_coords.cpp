#include "geometry_core/plane_coords.hpp"

#include <cmath>
#include <stdexcept>

namespace geometry_core {

namespace {
Eigen::Vector3d normalize_or_throw(const Eigen::Vector3d& v) {
  const double norm = v.norm();
  if (norm < 1e-12) {
    throw std::invalid_argument("normalize: vector is too small");
  }
  return v / norm;
}
}  // namespace

PlaneBasis build_plane_basis_deterministic(const Plane& plane,
                                            const Eigen::Vector3d* up_hint) {
  const Eigen::Vector3d n = normalize_or_throw(plane.normal);
  const Eigen::Vector3d origin_3d = -plane.offset * n;

  Eigen::Vector3d e_up = up_hint != nullptr ? normalize_or_throw(*up_hint)
                                             : Eigen::Vector3d(0.0, -1.0, 0.0);
  if (std::abs(e_up.dot(n)) > 0.95) {
    e_up = Eigen::Vector3d(1.0, 0.0, 0.0);
  }

  Eigen::Vector3d u = e_up - e_up.dot(n) * n;
  Eigen::Vector3d axis_u = normalize_or_throw(u);
  if (axis_u.x() < 0.0) {
    axis_u = -axis_u;
  }
  Eigen::Vector3d axis_v = normalize_or_throw(n.cross(axis_u));

  PlaneBasis basis;
  basis.origin_3d = origin_3d;
  basis.axis_u = axis_u;
  basis.axis_v = axis_v;
  basis.normal = n;
  return basis;
}

Eigen::MatrixXd project_points_to_plane_2d(
    const Eigen::Ref<const Eigen::MatrixXd>& points_3d, const PlaneBasis& basis) {
  Eigen::MatrixXd rel = points_3d.rowwise() - basis.origin_3d.transpose();
  Eigen::MatrixXd out(points_3d.rows(), 2);
  out.col(0) = rel * basis.axis_u;
  out.col(1) = rel * basis.axis_v;
  return out;
}

Eigen::Vector3d lift_point_from_plane_2d(const Eigen::Vector2d& point_2d,
                                          const PlaneBasis& basis) {
  return basis.origin_3d + point_2d.x() * basis.axis_u + point_2d.y() * basis.axis_v;
}

Eigen::MatrixXd lift_points_from_plane_2d(
    const Eigen::Ref<const Eigen::MatrixXd>& points_2d, const PlaneBasis& basis) {
  Eigen::MatrixXd out(points_2d.rows(), 3);
  for (long i = 0; i < points_2d.rows(); ++i) {
    out.row(i) = lift_point_from_plane_2d(points_2d.row(i), basis).transpose();
  }
  return out;
}

}  // namespace geometry_core
