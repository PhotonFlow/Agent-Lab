#include "geometry_core/backproject.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <vector>

#include "geometry_core/transforms.hpp"

#ifdef _OPENMP
#include <omp.h>
#endif

namespace geometry_core {

Eigen::MatrixXd backproject_depth_grid(const cv::Mat& depth_m,
                                        const Eigen::Matrix3d& K_depth_inv) {
  const int H = depth_m.rows;
  const int W = depth_m.cols;
  Eigen::MatrixXd out(static_cast<long>(H) * W, 3);
  for (int v = 0; v < H; ++v) {
    for (int u = 0; u < W; ++u) {
      const double z = static_cast<double>(depth_m.at<float>(v, u));
      Eigen::Vector3d ray = K_depth_inv * Eigen::Vector3d(u, v, 1.0);
      const long idx = static_cast<long>(v) * W + u;
      out.row(idx) = (ray * z).transpose();
    }
  }
  return out;
}

FaceSamples sample_face_points(const cv::Mat& depth_m, const cv::Mat& mask_rgb,
                                const RgbDepthCameraConfig& camera_cfg,
                                const Stage2Config& cfg) {
  const Eigen::Matrix3d K_depth_inv = camera_cfg.depth.K_inv();
  const Eigen::Matrix3d K_rgb = camera_cfg.rgb.K();
  const Eigen::Matrix3d& R_dr = camera_cfg.R_dr;
  const Eigen::Vector3d& t_dr = camera_cfg.t_dr;

  const int Hd = depth_m.rows;
  const int Wd = depth_m.cols;
  const int Hr = camera_cfg.rgb.height;
  const int Wr = camera_cfg.rgb.width;
  const int margin = cfg.rgb_clip_margin_px;

  // OpenMP-parallel per-pixel scan: each thread accumulates its own
  // contiguous slice of rows into a private bucket. Buckets are concatenated
  // in thread-index order below, which reproduces the exact serial
  // (v ascending, u ascending) acceptance order for any thread count --
  // including the OpenMP-disabled/1-thread case. Preserving that order (not
  // just the final point set) matters: downstream ransac_plane_fit draws
  // array indices into these points via a shared, long-lived rng, so
  // reordering them would silently change RANSAC's result even though the
  // point set itself is unchanged.
#ifdef _OPENMP
  const int max_threads = std::max(1, omp_get_max_threads());
#else
  const int max_threads = 1;
#endif
  std::vector<std::vector<Eigen::Vector3d>> thread_accepted(static_cast<size_t>(max_threads));
  for (auto& bucket : thread_accepted) {
    // Same total-reservation heuristic as the serial version (face is a
    // fraction of frame), split evenly across buckets.
    bucket.reserve(static_cast<size_t>(Hd) * static_cast<size_t>(Wd) /
                    (4 * static_cast<size_t>(max_threads)));
  }

#pragma omp parallel
  {
#ifdef _OPENMP
    const int tid = omp_get_thread_num();
#else
    const int tid = 0;
#endif
    std::vector<Eigen::Vector3d>& local = thread_accepted[static_cast<size_t>(tid)];

#pragma omp for schedule(static)
    for (int v = 0; v < Hd; ++v) {
      for (int u = 0; u < Wd; ++u) {
        const double z_d = static_cast<double>(depth_m.at<float>(v, u));
        if (!std::isfinite(z_d) || z_d < cfg.depth_min_m || z_d > cfg.depth_max_m) {
          continue;
        }
        const Eigen::Vector3d ray = K_depth_inv * Eigen::Vector3d(u, v, 1.0);
        const Eigen::Vector3d p_d = ray * z_d;
        const Eigen::Vector3d p_r = apply_se3(R_dr, t_dr, p_d);
        const double z_r = p_r.z();
        if (!std::isfinite(z_r) || z_r <= 0.0) {
          continue;
        }
        const Eigen::Vector2d uv_r = project_pinhole(p_r, K_rgb);
        if (!std::isfinite(uv_r.x()) || !std::isfinite(uv_r.y())) {
          continue;
        }
        const long u_int = std::lround(uv_r.x());
        const long v_int = std::lround(uv_r.y());
        if (u_int < margin || u_int >= Wr - margin || v_int < margin || v_int >= Hr - margin) {
          continue;
        }
        if (mask_rgb.at<uint8_t>(static_cast<int>(v_int), static_cast<int>(u_int)) == 0) {
          continue;
        }
        local.push_back(p_d);
      }
    }
  }

  size_t total_accepted = 0;
  for (const auto& bucket : thread_accepted) {
    total_accepted += bucket.size();
  }
  Eigen::MatrixXd points(static_cast<long>(total_accepted), 3);
  long row = 0;
  for (const auto& bucket : thread_accepted) {
    for (const auto& p : bucket) {
      points.row(row++) = p.transpose();
    }
  }

  FaceSamples samples;
  samples.points_depth_frame = points;
  return samples;
}

Eigen::Vector3d ray_plane_intersect_cross_camera(const Eigen::Vector2d& rgb_uv,
                                                  const RgbDepthCameraConfig& camera_cfg,
                                                  const Plane& plane_in_depth_frame) {
  const Eigen::Matrix3d K_rgb_inv = camera_cfg.rgb.K_inv();
  const Eigen::Vector3d ray_r_dir = pixel_ray(rgb_uv, K_rgb_inv);

  Eigen::Matrix3d R_rd;
  Eigen::Vector3d t_rd;
  invert_se3(camera_cfg.R_dr, camera_cfg.t_dr, R_rd, t_rd);

  const Eigen::Vector3d origin_d = t_rd;
  const Eigen::Vector3d dir_d = R_rd * ray_r_dir;

  const Eigen::Vector3d& n = plane_in_depth_frame.normal;
  const double d_plane = plane_in_depth_frame.offset;
  const double denom = n.dot(dir_d);
  if (std::abs(denom) < 1e-9) {
    throw std::invalid_argument("ray is parallel to the plane (denominator near zero)");
  }
  const double t = -(n.dot(origin_d) + d_plane) / denom;
  return origin_d + t * dir_d;
}

}  // namespace geometry_core
