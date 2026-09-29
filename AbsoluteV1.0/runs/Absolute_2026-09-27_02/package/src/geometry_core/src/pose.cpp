#include "geometry_core/pose.hpp"

#include <cmath>

namespace geometry_core {

double yaw_from_normal_camera(const Eigen::Vector3d& n_toward_cam) {
  return std::atan2(n_toward_cam.x(), -n_toward_cam.z());
}

}  // namespace geometry_core
