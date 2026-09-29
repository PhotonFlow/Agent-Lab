#pragma once

#include <vector>

#include "geometry_core/chamfer.hpp"

namespace geometry_core {
namespace chamfer_detail {

// Thread-local scratch buffers reused across cost evaluations to avoid
// per-call heap allocations. Shared by the public chamfer_cost_v2, the fused
// free-search inner loop, and the prior-regularized search inner loop. Buffer
// contents are overwritten on every evaluation, so no state leaks between
// logically independent cost calls.
struct ChamferTls {
  Eigen::MatrixXd rotated;     // N x 2, proto rotated by theta (no translation)
  Eigen::MatrixXd translated;  // N x 2, rotated + (tx, ty)
  Eigen::ArrayXd distances;    // per-point sampled distances
  std::vector<double> sorted;  // sortable copy of distances for trimmed mean
  long cached_theta_i = -1;    // grid theta index currently held in `rotated`
  double cached_theta_rad = 0.0;
};

ChamferTls& chamfer_tls();

void ensure_tls_size(ChamferTls& tls, long n);

// Rotation half of transform_points_2d: out = proto * R(theta)^T. Kept
// operation-order identical to the public transform so results are bit-exact.
void rotate_proto_into(const Eigen::Ref<const Eigen::MatrixXd>& proto,
                       double theta_rad, Eigen::MatrixXd& out);

// Cost from an already-rotated prototype: apply translation, sample, trim.
// Equivalent to chamfer_cost_v2 minus the rotation (which the caller amortizes).
double chamfer_cost_from_rotated(const Eigen::MatrixXd& rotated, double tx, double ty,
                                 const cv::Mat& dist_img_m, const GridMeta& meta,
                                 double trim_fraction, const double* outside_penalty_m,
                                 ChamferTls& tls);

}  // namespace chamfer_detail
}  // namespace geometry_core
