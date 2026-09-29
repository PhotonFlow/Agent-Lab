#include "geometry_core/transforms.hpp"

#include <limits>

namespace geometry_core {

namespace {
constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();
}

Eigen::Vector3d apply_se3(const Eigen::Matrix3d& R, const Eigen::Vector3d& t,
                           const Eigen::Vector3d& point) {
  return R * point + t;
}

Eigen::MatrixXd apply_se3_batch(const Eigen::Matrix3d& R,
                                 const Eigen::Vector3d& t,
                                 const Eigen::Ref<const Eigen::MatrixXd>& points_n3) {
  // points @ R.T + t, matching pallet_pose_estimation/geometry/transforms.py.
  Eigen::MatrixXd out = points_n3 * R.transpose();
  out.rowwise() += t.transpose();
  return out;
}

void invert_se3(const Eigen::Matrix3d& R, const Eigen::Vector3d& t,
                 Eigen::Matrix3d& R_inv, Eigen::Vector3d& t_inv) {
  R_inv = R.transpose();
  t_inv = -R_inv * t;
}

Eigen::Vector2d project_pinhole(const Eigen::Vector3d& point_cam,
                                 const Eigen::Matrix3d& K) {
  const double z = point_cam.z();
  if (z <= 0.0) {
    return Eigen::Vector2d(kNaN, kNaN);
  }
  return Eigen::Vector2d(K(0, 0) * point_cam.x() / z + K(0, 2),
                          K(1, 1) * point_cam.y() / z + K(1, 2));
}

Eigen::MatrixXd project_pinhole_batch(
    const Eigen::Ref<const Eigen::MatrixXd>& points_cam_n3,
    const Eigen::Matrix3d& K) {
  const long n = points_cam_n3.rows();
  Eigen::MatrixXd out = Eigen::MatrixXd::Constant(n, 2, kNaN);
  for (long i = 0; i < n; ++i) {
    const double z = points_cam_n3(i, 2);
    if (z > 0.0) {
      out(i, 0) = K(0, 0) * points_cam_n3(i, 0) / z + K(0, 2);
      out(i, 1) = K(1, 1) * points_cam_n3(i, 1) / z + K(1, 2);
    }
  }
  return out;
}

Eigen::Vector3d pixel_ray(const Eigen::Vector2d& uv,
                           const Eigen::Matrix3d& K_inv) {
  Eigen::Vector3d homog(uv.x(), uv.y(), 1.0);
  return K_inv * homog;
}

}  // namespace geometry_core
