#pragma once

#include <Eigen/Dense>

namespace geometry_core {

// Right-hand-rule yaw about world-up (ROS REP-103), matching
// pallet_pose_estimation/geometry/pose.py::yaw_from_normal_camera.
// n_toward_cam is the face normal oriented toward the camera
// (z-component negative for a pallet facing the lens).
double yaw_from_normal_camera(const Eigen::Vector3d& n_toward_cam);

}  // namespace geometry_core
