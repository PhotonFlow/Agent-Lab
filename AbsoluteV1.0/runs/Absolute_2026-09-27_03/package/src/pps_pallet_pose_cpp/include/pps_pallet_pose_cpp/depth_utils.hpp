#pragma once

#include <opencv2/core.hpp>
#include <sensor_msgs/msg/image.hpp>

namespace pps_pallet_pose_cpp {

// Converts a sensor_msgs/Image depth frame (16UC1 millimetres scaled by
// depth_scale, or 32FC1 already in metres) into a CV_32FC1 cv::Mat in metres.
// Mirrors pps_pallet_pose/depth_conversions.py::depth_image_to_meters.
// Throws std::invalid_argument on an unsupported encoding or an undersized
// data buffer.
cv::Mat depth_image_to_meters(const sensor_msgs::msg::Image& msg, double depth_scale);

}  // namespace pps_pallet_pose_cpp
