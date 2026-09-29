#include "geometry_core/chamfer.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <vector>

#include <opencv2/imgproc.hpp>

#ifdef _OPENMP
#include <omp.h>
#endif

#include "chamfer_internal.hpp"

namespace geometry_core {

Eigen::MatrixXd transform_points_2d(const Eigen::Ref<const Eigen::MatrixXd>& points_2d,
                                    const PrototypePose2D& pose) {
  const double c = std::cos(pose.theta_rad);
  const double s = std::sin(pose.theta_rad);
  Eigen::Matrix2d R;
  R << c, -s,
       s,  c;
  Eigen::MatrixXd out = points_2d * R.transpose();
  out.col(0).array() += pose.tx;
  out.col(1).array() += pose.ty;
  return out;
}

std::pair<cv::Mat, GridMeta> rasterize_points_to_mask(
    const Eigen::Ref<const Eigen::MatrixXd>& points_2d, double resolution_m,
    double padding_m) {
  if (points_2d.rows() == 0) {
    throw std::invalid_argument("points_2d must have at least one row");
  }
  const Eigen::Vector2d min_xy = points_2d.colwise().minCoeff().transpose().array() - padding_m;
  const Eigen::Vector2d max_xy = points_2d.colwise().maxCoeff().transpose().array() + padding_m;

  const int width = static_cast<int>(std::ceil((max_xy.x() - min_xy.x()) / resolution_m)) + 1;
  const int height = static_cast<int>(std::ceil((max_xy.y() - min_xy.y()) / resolution_m)) + 1;

  cv::Mat mask = cv::Mat::zeros(height, width, CV_8UC1);
  for (long i = 0; i < points_2d.rows(); ++i) {
    const long col = std::lround((points_2d(i, 0) - min_xy.x()) / resolution_m);
    const long row = std::lround((points_2d(i, 1) - min_xy.y()) / resolution_m);
    if (row >= 0 && row < height && col >= 0 && col < width) {
      mask.at<uint8_t>(static_cast<int>(row), static_cast<int>(col)) = 1;
    }
  }

  GridMeta meta;
  meta.min_xy = min_xy;
  meta.resolution_m = resolution_m;
  meta.height = height;
  meta.width = width;
  return {mask, meta};
}

cv::Mat close_mask(const cv::Mat& mask, int close_radius_px, bool keep_largest) {
  cv::Mat src = mask.clone();
  if (close_radius_px > 0) {
    const int k = 2 * close_radius_px + 1;
    cv::Mat kernel = cv::getStructuringElement(cv::MORPH_ELLIPSE, cv::Size(k, k));
    cv::morphologyEx(src, src, cv::MORPH_CLOSE, kernel);
  }
  if (keep_largest) {
    cv::Mat labels, stats, centroids;
    const int n = cv::connectedComponentsWithStats(src, labels, stats, centroids, 8);
    if (n > 1) {
      int largest_label = 1;
      int largest_area = stats.at<int>(1, cv::CC_STAT_AREA);
      for (int label = 2; label < n; ++label) {
        const int area = stats.at<int>(label, cv::CC_STAT_AREA);
        if (area > largest_area) {
          largest_area = area;
          largest_label = label;
        }
      }
      cv::Mat out = cv::Mat::zeros(src.size(), CV_8UC1);
      out.setTo(1, labels == largest_label);
      src = out;
    }
  }
  return src;
}

cv::Mat extract_boundary_mask(const cv::Mat& mask) {
  cv::Mat kernel = cv::Mat::ones(3, 3, CV_8UC1);
  cv::Mat eroded;
  cv::erode(mask, eroded, kernel, cv::Point(-1, -1), 1);
  cv::Mat edge;
  cv::bitwise_not(eroded, eroded);  // ~eroded (still 0/1-valued after erode of 0/1 mask)
  cv::bitwise_and(mask, eroded, edge);
  return edge;
}

cv::Mat compute_distance_transform_v2(const cv::Mat& edge_mask, double resolution_m) {
  cv::Mat src;
  // edge pixels (value 1) -> 0 (distanceTransform measures distance to zero
  // pixels); non-edge (value 0) -> 1.
  cv::compare(edge_mask, 0, src, cv::CMP_EQ);  // 255 where edge_mask==0, else 0
  src.setTo(1, src == 255);
  src.setTo(0, edge_mask != 0);
  cv::Mat dist_px;
  cv::distanceTransform(src, dist_px, cv::DIST_L2, cv::DIST_MASK_PRECISE);
  cv::Mat dist_m;
  dist_px.convertTo(dist_m, CV_32FC1, resolution_m);
  return dist_m;
}

namespace {

// Same body as the public sample_distance_bilinear, but writes into a
// caller-owned buffer instead of allocating. `out` is assumed pre-sized to
// points rows. Both entry points share this body so there is a single source
// of truth for the bilinear sampling arithmetic.
void sample_bilinear_into(const Eigen::Ref<const Eigen::MatrixXd>& points_2d,
                          const cv::Mat& dist_img_m, const GridMeta& meta,
                          double outside_penalty_m, Eigen::ArrayXd& out) {
  const int H = dist_img_m.rows;
  const int W = dist_img_m.cols;
  const size_t step = static_cast<size_t>(dist_img_m.step1());  // floats per row
  const float* base = dist_img_m.ptr<float>(0);
  out.setConstant(outside_penalty_m);

  for (long i = 0; i < points_2d.rows(); ++i) {
    const double col_f = (points_2d(i, 0) - meta.min_xy.x()) / meta.resolution_m;
    const double row_f = (points_2d(i, 1) - meta.min_xy.y()) / meta.resolution_m;
    const long c0 = static_cast<long>(std::floor(col_f));
    const long r0 = static_cast<long>(std::floor(row_f));
    const double dx = col_f - static_cast<double>(c0);
    const double dy = row_f - static_cast<double>(r0);

    if (r0 >= 0 && r0 + 1 < H && c0 >= 0 && c0 + 1 < W) {
      const float* row0 = base + static_cast<size_t>(r0) * step;
      const float* row1 = base + static_cast<size_t>(r0 + 1) * step;
      const double d00 = static_cast<double>(row0[c0]);
      const double d01 = static_cast<double>(row0[c0 + 1]);
      const double d10 = static_cast<double>(row1[c0]);
      const double d11 = static_cast<double>(row1[c0 + 1]);
      out(i) = (1.0 - dx) * (1.0 - dy) * d00 + dx * (1.0 - dy) * d01 +
               (1.0 - dx) * dy * d10 + dx * dy * d11;
    }
  }
}

// Trimmed mean over `distances`, using `sorted` as scratch. Keeps the full
// std::sort + ascending prefix-sum ordering identical to chamfer_cost_v2.
double trimmed_mean_from_distances(Eigen::ArrayXd& distances, double trim_fraction,
                                   std::vector<double>& sorted) {
  const long n = distances.size();
  sorted.assign(distances.data(), distances.data() + n);
  std::sort(sorted.begin(), sorted.end());
  long keep = n;
  if (trim_fraction > 0.0) {
    keep = std::max<long>(
        1, static_cast<long>(std::ceil((1.0 - trim_fraction) * static_cast<double>(n))));
  }
  double sum = 0.0;
  for (long i = 0; i < keep; ++i) {
    sum += sorted[static_cast<size_t>(i)];
  }
  return sum / static_cast<double>(keep);
}

}  // namespace

Eigen::ArrayXd sample_distance_bilinear(
    const Eigen::Ref<const Eigen::MatrixXd>& points_2d, const cv::Mat& dist_img_m,
    const GridMeta& meta, double outside_penalty_m) {
  Eigen::ArrayXd out(points_2d.rows());
  sample_bilinear_into(points_2d, dist_img_m, meta, outside_penalty_m, out);
  return out;
}

namespace chamfer_detail {

ChamferTls& chamfer_tls() {
  thread_local ChamferTls tls;
  return tls;
}

void ensure_tls_size(ChamferTls& tls, long n) {
  if (tls.rotated.rows() != n) {
    tls.rotated.resize(n, 2);
    tls.translated.resize(n, 2);
    tls.distances.resize(n);
    tls.sorted.resize(static_cast<size_t>(n));
    tls.cached_theta_i = -1;
  }
}

void rotate_proto_into(const Eigen::Ref<const Eigen::MatrixXd>& proto,
                       double theta_rad, Eigen::MatrixXd& out) {
  const double c = std::cos(theta_rad);
  const double s = std::sin(theta_rad);
  Eigen::Matrix2d R;
  R << c, -s,
       s,  c;
  out = proto * R.transpose();
}

double chamfer_cost_from_rotated(const Eigen::MatrixXd& rotated, double tx, double ty,
                                 const cv::Mat& dist_img_m, const GridMeta& meta,
                                 double trim_fraction, const double* outside_penalty_m,
                                 ChamferTls& tls) {
  const double penalty = outside_penalty_m != nullptr ? *outside_penalty_m
                                                      : 50.0 * meta.resolution_m;
  tls.translated = rotated;
  tls.translated.col(0).array() += tx;
  tls.translated.col(1).array() += ty;
  sample_bilinear_into(tls.translated, dist_img_m, meta, penalty, tls.distances);
  return trimmed_mean_from_distances(tls.distances, trim_fraction, tls.sorted);
}

}  // namespace chamfer_detail

double chamfer_cost_v2(const Eigen::Ref<const Eigen::MatrixXd>& proto_points_2d,
                        const PrototypePose2D& pose, const cv::Mat& dist_img_m,
                        const GridMeta& meta, double trim_fraction,
                        const double* outside_penalty_m) {
  chamfer_detail::ChamferTls& tls = chamfer_detail::chamfer_tls();
  chamfer_detail::ensure_tls_size(tls, proto_points_2d.rows());
  chamfer_detail::rotate_proto_into(proto_points_2d, pose.theta_rad, tls.rotated);
  return chamfer_detail::chamfer_cost_from_rotated(tls.rotated, pose.tx, pose.ty,
                                                    dist_img_m, meta, trim_fraction,
                                                    outside_penalty_m, tls);
}

std::pair<PrototypePose2D, double> coarse_chamfer_search_v2(
    const Eigen::Ref<const Eigen::MatrixXd>& proto_points_2d,
    const PrototypePose2D& init_pose, const cv::Mat& dist_img_m, const GridMeta& meta,
    double search_dx_m, double search_dy_m, double search_dtheta_rad, double step_dx_m,
    double step_dy_m, double step_dtheta_rad, double trim_fraction,
    const double* outside_penalty_m) {
  std::vector<double> dx_values;
  dx_values.reserve(
      static_cast<size_t>(std::floor((2.0 * search_dx_m) / step_dx_m)) + 2);
  for (double v = -search_dx_m; v <= search_dx_m + 0.5 * step_dx_m; v += step_dx_m) {
    dx_values.push_back(v);
  }
  std::vector<double> dy_values;
  dy_values.reserve(
      static_cast<size_t>(std::floor((2.0 * search_dy_m) / step_dy_m)) + 2);
  for (double v = -search_dy_m; v <= search_dy_m + 0.5 * step_dy_m; v += step_dy_m) {
    dy_values.push_back(v);
  }
  std::vector<double> dtheta_values;
  dtheta_values.reserve(
      static_cast<size_t>(std::floor((2.0 * search_dtheta_rad) / step_dtheta_rad)) + 2);
  for (double v = -search_dtheta_rad; v <= search_dtheta_rad + 0.5 * step_dtheta_rad;
       v += step_dtheta_rad) {
    dtheta_values.push_back(v);
  }

  PrototypePose2D best_pose = init_pose;
  double best_cost = chamfer_cost_v2(proto_points_2d, init_pose, dist_img_m, meta,
                                      trim_fraction, outside_penalty_m);

  const long n_theta = static_cast<long>(dtheta_values.size());
  const long n_y = static_cast<long>(dy_values.size());
  const long n_x = static_cast<long>(dx_values.size());
  const long total = n_theta * n_y * n_x;

  // OpenMP-parallel brute-force search: each thread keeps a private
  // best (pose, cost), reduced across threads at the end. Order of
  // evaluation does not affect the argmin result (ties resolved by
  // whichever candidate is found first in flattened (theta, y, x) order,
  // matching the Python nested-loop tie-break exactly since we resolve ties
  // by flattened index, not by thread completion order).
  PrototypePose2D global_best_pose = best_pose;
  double global_best_cost = best_cost;
  long global_best_index = -1;

#pragma omp parallel
  {
    PrototypePose2D local_best_pose = best_pose;
    double local_best_cost = best_cost;
    long local_best_index = -1;

    // Thread-local scratch; with schedule(static) each thread gets a
    // contiguous flat range so theta changes infrequently (H1: rotate once
    // per theta). Force a recompute on this thread's first iteration by
    // invalidating any cached rotation left over from a prior search call.
    chamfer_detail::ChamferTls& tls = chamfer_detail::chamfer_tls();
    chamfer_detail::ensure_tls_size(tls, proto_points_2d.rows());
    tls.cached_theta_i = -1;

#pragma omp for schedule(static)
    for (long flat = 0; flat < total; ++flat) {
      const long theta_i = flat / (n_y * n_x);
      const long rem = flat % (n_y * n_x);
      const long y_i = rem / n_x;
      const long x_i = rem % n_x;

      if (tls.cached_theta_i != theta_i) {
        const double theta = init_pose.theta_rad + dtheta_values[theta_i];
        chamfer_detail::rotate_proto_into(proto_points_2d, theta, tls.rotated);
        tls.cached_theta_i = theta_i;
        tls.cached_theta_rad = theta;
      }
      const double tx = init_pose.tx + dx_values[x_i];
      const double ty = init_pose.ty + dy_values[y_i];
      const double cost = chamfer_detail::chamfer_cost_from_rotated(
          tls.rotated, tx, ty, dist_img_m, meta, trim_fraction, outside_penalty_m, tls);
      if (cost < local_best_cost ||
          (local_best_index < 0 && cost < local_best_cost)) {
        local_best_cost = cost;
        local_best_pose = PrototypePose2D{tls.cached_theta_rad, tx, ty};
        local_best_index = flat;
      }
    }

#pragma omp critical
    {
      if (local_best_index >= 0 &&
          (local_best_cost < global_best_cost ||
           (local_best_cost == global_best_cost &&
            (global_best_index < 0 || local_best_index < global_best_index)))) {
        global_best_cost = local_best_cost;
        global_best_pose = local_best_pose;
        global_best_index = local_best_index;
      }
    }
  }

  return {global_best_pose, global_best_cost};
}

std::pair<PrototypePose2D, double> two_stage_chamfer_search_v2(
    const Eigen::Ref<const Eigen::MatrixXd>& proto_points_2d,
    const PrototypePose2D& init_pose, const cv::Mat& dist_img_m, const GridMeta& meta,
    double coarse_dx_m, double coarse_dy_m, double coarse_dtheta_rad,
    double coarse_step_dx_m, double coarse_step_dy_m, double coarse_step_dtheta_rad,
    double fine_dx_m, double fine_dy_m, double fine_dtheta_rad, double fine_step_dx_m,
    double fine_step_dy_m, double fine_step_dtheta_rad, double trim_fraction,
    const double* outside_penalty_m) {
  auto [coarse_pose, coarse_cost] = coarse_chamfer_search_v2(
      proto_points_2d, init_pose, dist_img_m, meta, coarse_dx_m, coarse_dy_m,
      coarse_dtheta_rad, coarse_step_dx_m, coarse_step_dy_m, coarse_step_dtheta_rad,
      trim_fraction, outside_penalty_m);
  (void)coarse_cost;
  return coarse_chamfer_search_v2(proto_points_2d, coarse_pose, dist_img_m, meta,
                                   fine_dx_m, fine_dy_m, fine_dtheta_rad, fine_step_dx_m,
                                   fine_step_dy_m, fine_step_dtheta_rad, trim_fraction,
                                   outside_penalty_m);
}

}  // namespace geometry_core
