#pragma once

#include <Eigen/Dense>
#include <opencv2/core.hpp>

#include "geometry_core/camera_config.hpp"
#include "geometry_core/plane_fit.hpp"
#include "geometry_core/schemas.hpp"

namespace geometry_core {

// Outputs of sample_face_points. rgb_uv_lookup from the Python version is
// intentionally not ported (dead output for pipelinev3_2's call site); see
// Task 12 Interfaces note in the plan.
struct FaceSamples {
  Eigen::MatrixXd points_depth_frame;  // (N, 3), depth-camera frame, metres
  cv::Mat depth_face_mask;             // (Hd, Wd) CV_8UC1, 0/1
};

// Vectorised (well, fully materialised) back-projection of a depth image
// into a flattened (H*W, 3) point grid, row-major (row*W + col) order,
// matching numpy's default C-order flatten of an (H, W, 3) array. Provided
// for unit-test parity with the Python function; sample_face_points below
// uses an equivalent per-pixel fused loop instead for memory locality.
Eigen::MatrixXd backproject_depth_grid(const cv::Mat& depth_m,
                                        const Eigen::Matrix3d& K_depth_inv);

FaceSamples sample_face_points(const cv::Mat& depth_m, const cv::Mat& mask_rgb,
                                const RgbDepthCameraConfig& camera_cfg,
                                const Stage2Config& cfg);

Eigen::Vector3d ray_plane_intersect_cross_camera(const Eigen::Vector2d& rgb_uv,
                                                  const RgbDepthCameraConfig& camera_cfg,
                                                  const Plane& plane_in_depth_frame);

}  // namespace geometry_core
