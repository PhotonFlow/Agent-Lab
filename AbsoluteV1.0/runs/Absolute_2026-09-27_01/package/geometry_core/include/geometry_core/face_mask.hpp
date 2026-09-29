#pragma once

#include <Eigen/Dense>
#include <opencv2/core.hpp>

namespace geometry_core {

// Rasterise an axis-aligned bbox as a CV_8UC1 mask (values 0/1, not 0/255),
// then apply erode_px iterations of 3x3 binary erosion. Mirrors
// pallet_pose_estimation/geometry/face_mask.py::build_bbox_mask.
cv::Mat build_bbox_mask(const Eigen::Vector4d& bbox_xyxy, int height, int width,
                         int erode_px = 2);

}  // namespace geometry_core
