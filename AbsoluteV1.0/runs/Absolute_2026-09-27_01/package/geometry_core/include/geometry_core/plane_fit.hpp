#pragma once

#include <random>

#include <Eigen/Dense>

namespace geometry_core {

// A 3D plane n.X + d = 0 with unit normal n. Mirrors
// pallet_pose_estimation/geometry/plane_fit.py::Plane.
struct Plane {
  Eigen::Vector3d normal = Eigen::Vector3d::Zero();
  double offset = 0.0;
  double inlier_ratio = 0.0;
  int n_inliers = 0;
};

// Least-squares plane fit via SVD (smallest right-singular vector of the
// centred point cloud). Throws std::invalid_argument if points_n3 has fewer
// than 3 rows or is degenerate.
Plane svd_plane_refit(const Eigen::Ref<const Eigen::MatrixXd>& points_n3);

// 3-point RANSAC + SVD refit on the winning inlier set. `rng` provides
// statistically-equivalent (not bit-exact-vs-NumPy) sampling; see plan
// Task 4 interfaces note. Falls back to a global svd_plane_refit over all
// points if no 3-point sample yields >=3 inliers within max_iters.
Plane ransac_plane_fit(const Eigen::Ref<const Eigen::MatrixXd>& points_n3,
                        double inlier_threshold_m, int max_iters,
                        double early_stop_inlier_ratio, std::mt19937_64& rng);

// Flip normal (and offset) so normal.z() <= 0.
Plane orient_normal_toward_camera(const Plane& plane);

// Signed point-to-plane distance: points_n3 * normal + offset (row-wise dot).
Eigen::ArrayXd point_to_plane_distance(
    const Plane& plane, const Eigen::Ref<const Eigen::MatrixXd>& points_n3);

Eigen::Array<bool, Eigen::Dynamic, 1> plane_inlier_mask(
    const Eigen::Ref<const Eigen::MatrixXd>& points_n3, const Plane& plane,
    double threshold_m);

}  // namespace geometry_core
