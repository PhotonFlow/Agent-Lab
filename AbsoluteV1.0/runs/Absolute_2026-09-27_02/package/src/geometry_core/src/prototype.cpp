#include "geometry_core/prototype.hpp"

#include <algorithm>
#include <cmath>
#include <vector>

namespace geometry_core {

namespace {

Eigen::MatrixXd sample_segment(const Eigen::Vector2d& p0, const Eigen::Vector2d& p1,
                                double spacing_m) {
  const double length = (p1 - p0).norm();
  const int n = std::max(2, static_cast<int>(std::ceil(length / spacing_m)) + 1);
  Eigen::MatrixXd out(n, 2);
  for (int i = 0; i < n; ++i) {
    const double t = static_cast<double>(i) / static_cast<double>(n);  // endpoint=False
    out.row(i) = (p0 + t * (p1 - p0)).transpose();
  }
  return out;
}

Eigen::MatrixXd sample_rect_contour(double width_m, double height_m, double cx,
                                     double cy, double contour_spacing_m) {
  const double half_w = 0.5 * width_m;
  const double half_h = 0.5 * height_m;
  Eigen::Matrix<double, 4, 2> corners;
  corners << cx - half_w, cy - half_h,
             cx + half_w, cy - half_h,
             cx + half_w, cy + half_h,
             cx - half_w, cy + half_h;

  std::vector<Eigen::MatrixXd> parts;
  int total_rows = 0;
  for (int i = 0; i < 4; ++i) {
    Eigen::MatrixXd seg = sample_segment(corners.row(i).transpose(),
                                          corners.row((i + 1) % 4).transpose(),
                                          contour_spacing_m);
    total_rows += static_cast<int>(seg.rows());
    parts.push_back(std::move(seg));
  }
  Eigen::MatrixXd out(total_rows, 2);
  int row = 0;
  for (const auto& part : parts) {
    out.block(row, 0, part.rows(), 2) = part;
    row += static_cast<int>(part.rows());
  }
  return out;
}

}  // namespace

Prototype2D build_default_pallet_prototype(double width_m, double height_m,
                                            double pocket_width_m,
                                            double pocket_height_m,
                                            double pocket_centre_offset_m,
                                            double contour_spacing_m) {
  Eigen::MatrixXd outer =
      sample_rect_contour(width_m, height_m, 0.0, 0.0, contour_spacing_m);
  Eigen::MatrixXd hole_l = sample_rect_contour(
      pocket_width_m, pocket_height_m, -pocket_centre_offset_m, 0.0, contour_spacing_m);
  Eigen::MatrixXd hole_r = sample_rect_contour(
      pocket_width_m, pocket_height_m, pocket_centre_offset_m, 0.0, contour_spacing_m);

  const int total = static_cast<int>(outer.rows() + hole_l.rows() + hole_r.rows());
  Eigen::MatrixXd contour(total, 2);
  contour.block(0, 0, outer.rows(), 2) = outer;
  contour.block(outer.rows(), 0, hole_l.rows(), 2) = hole_l;
  contour.block(outer.rows() + hole_l.rows(), 0, hole_r.rows(), 2) = hole_r;

  Prototype2D proto;
  proto.contour_points = contour;
  proto.origin_xy = Eigen::Vector2d::Zero();
  return proto;
}

}  // namespace geometry_core
