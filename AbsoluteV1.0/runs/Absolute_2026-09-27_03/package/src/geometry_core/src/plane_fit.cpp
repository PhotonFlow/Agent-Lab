#include "geometry_core/plane_fit.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <stdexcept>

namespace geometry_core {

namespace {

std::pair<Eigen::Vector3d, double> three_point_plane(const Eigen::Vector3d& p0,
                                                       const Eigen::Vector3d& p1,
                                                       const Eigen::Vector3d& p2,
                                                       bool* ok) {
  Eigen::Vector3d n = (p1 - p0).cross(p2 - p0);
  const double norm = n.norm();
  *ok = norm >= 1e-12;
  if (!*ok) {
    return {Eigen::Vector3d::Zero(), 0.0};
  }
  n /= norm;
  const double d = -n.dot(p0);
  return {n, d};
}

// Sample 3 distinct indices in [0, n) — statistically equivalent to
// np.random.Generator.choice(n, size=3, replace=False), not bit-exact.
std::array<long, 3> sample_three_distinct(long n, std::mt19937_64& rng) {
  std::uniform_int_distribution<long> dist(0, n - 1);
  std::array<long, 3> idx{-1, -1, -1};
  idx[0] = dist(rng);
  do {
    idx[1] = dist(rng);
  } while (idx[1] == idx[0]);
  do {
    idx[2] = dist(rng);
  } while (idx[2] == idx[0] || idx[2] == idx[1]);
  return idx;
}

}  // namespace

Plane svd_plane_refit(const Eigen::Ref<const Eigen::MatrixXd>& points_n3) {
  if (points_n3.rows() < 3) {
    throw std::invalid_argument("need at least 3 points for SVD refit");
  }
  const Eigen::RowVector3d centroid = points_n3.colwise().mean();
  Eigen::MatrixXd centred = points_n3.rowwise() - centroid;
  Eigen::JacobiSVD<Eigen::MatrixXd> svd(centred, Eigen::ComputeThinV);
  // V's last column (smallest singular value) is the plane normal.
  Eigen::Vector3d normal = svd.matrixV().col(2);
  const double norm_len = normal.norm();
  if (norm_len < 1e-12) {
    throw std::invalid_argument("degenerate point set: SVD produced zero normal");
  }
  normal /= norm_len;
  const double offset = -normal.dot(centroid.transpose());

  Plane plane;
  plane.normal = normal;
  plane.offset = offset;
  plane.inlier_ratio = 0.0;
  plane.n_inliers = 0;
  return plane;
}

Plane ransac_plane_fit(const Eigen::Ref<const Eigen::MatrixXd>& points_n3,
                        double inlier_threshold_m, int max_iters,
                        double early_stop_inlier_ratio, std::mt19937_64& rng) {
  const long n_points = points_n3.rows();
  if (points_n3.cols() != 3) {
    throw std::invalid_argument("points_n3 must have 3 columns");
  }
  if (n_points < 3) {
    throw std::invalid_argument("need at least 3 points");
  }

  int best_inlier_count = -1;
  Eigen::Array<bool, Eigen::Dynamic, 1> best_mask;
  Eigen::Vector3d best_normal = Eigen::Vector3d::Zero();
  double best_offset = 0.0;
  bool have_candidate = false;

  const int early_stop_count =
      static_cast<int>(std::ceil(early_stop_inlier_ratio * static_cast<double>(n_points)));

  for (int iter = 0; iter < max_iters; ++iter) {
    const std::array<long, 3> idx = sample_three_distinct(n_points, rng);
    bool ok = false;
    auto [n, d] = three_point_plane(points_n3.row(idx[0]), points_n3.row(idx[1]),
                                     points_n3.row(idx[2]), &ok);
    if (!ok) {
      continue;
    }
    Eigen::ArrayXd residuals = (points_n3 * n).array() + d;
    Eigen::Array<bool, Eigen::Dynamic, 1> mask = residuals.abs() <= inlier_threshold_m;
    const int count = static_cast<int>(mask.count());
    if (count > best_inlier_count) {
      best_inlier_count = count;
      best_mask = mask;
      best_normal = n;
      best_offset = d;
      have_candidate = true;
      if (count >= early_stop_count) {
        break;
      }
    }
  }

  if (!have_candidate || best_inlier_count < 3) {
    Plane fallback = svd_plane_refit(points_n3);
    Eigen::ArrayXd residuals = (points_n3 * fallback.normal).array() + fallback.offset;
    Eigen::Array<bool, Eigen::Dynamic, 1> mask = residuals.abs() <= inlier_threshold_m;
    fallback.inlier_ratio = static_cast<double>(mask.count()) / static_cast<double>(n_points);
    fallback.n_inliers = static_cast<int>(mask.count());
    return fallback;
  }

  Eigen::MatrixXd inlier_pts(best_inlier_count, 3);
  int row = 0;
  for (long i = 0; i < n_points; ++i) {
    if (best_mask(i)) {
      inlier_pts.row(row++) = points_n3.row(i);
    }
  }
  Plane refit = svd_plane_refit(inlier_pts);
  Eigen::ArrayXd residuals_refit = (points_n3 * refit.normal).array() + refit.offset;
  Eigen::Array<bool, Eigen::Dynamic, 1> mask_refit = residuals_refit.abs() <= inlier_threshold_m;
  refit.inlier_ratio = static_cast<double>(mask_refit.count()) / static_cast<double>(n_points);
  refit.n_inliers = static_cast<int>(mask_refit.count());
  return refit;
}

Plane orient_normal_toward_camera(const Plane& plane) {
  if (plane.normal.z() > 0.0) {
    Plane flipped = plane;
    flipped.normal = -plane.normal;
    flipped.offset = -plane.offset;
    return flipped;
  }
  return plane;
}

Eigen::ArrayXd point_to_plane_distance(
    const Plane& plane, const Eigen::Ref<const Eigen::MatrixXd>& points_n3) {
  return (points_n3 * plane.normal).array() + plane.offset;
}

Eigen::Array<bool, Eigen::Dynamic, 1> plane_inlier_mask(
    const Eigen::Ref<const Eigen::MatrixXd>& points_n3, const Plane& plane,
    double threshold_m) {
  Eigen::ArrayXd residuals = point_to_plane_distance(plane, points_n3).abs();
  return residuals <= threshold_m;
}

}  // namespace geometry_core
