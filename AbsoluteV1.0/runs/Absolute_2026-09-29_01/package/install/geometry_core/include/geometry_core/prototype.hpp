#pragma once

#include <Eigen/Dense>

namespace geometry_core {

// Rectangle 2D prototype (outer face + two pocket holes). Mirrors
// pallet_pose_estimation/geometry/prototype.py::Prototype2D.
struct Prototype2D {
  Eigen::MatrixXd contour_points;  // (N, 2)
  Eigen::Vector2d origin_xy = Eigen::Vector2d::Zero();
};

// Outer rectangle plus two pocket rectangles, all sampled at
// contour_spacing_m, concatenated as [outer; hole_left; hole_right].
// Mirrors build_default_pallet_prototype exactly.
Prototype2D build_default_pallet_prototype(double width_m, double height_m,
                                            double pocket_width_m = 0.30,
                                            double pocket_height_m = 0.10,
                                            double pocket_centre_offset_m = 0.30,
                                            double contour_spacing_m = 0.01);

}  // namespace geometry_core
