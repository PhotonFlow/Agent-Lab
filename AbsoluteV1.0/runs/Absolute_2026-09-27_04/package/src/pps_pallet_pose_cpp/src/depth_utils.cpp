#include "pps_pallet_pose_cpp/depth_utils.hpp"

#include <stdexcept>

namespace pps_pallet_pose_cpp {

cv::Mat depth_image_to_meters(const sensor_msgs::msg::Image& msg, double depth_scale) {
  const int height = static_cast<int>(msg.height);
  const int width = static_cast<int>(msg.width);
  const int step = static_cast<int>(msg.step);

  int bytes_per_pixel = 0;
  int cv_type = 0;
  float scale = 1.0f;
  if (msg.encoding == "16UC1") {
    bytes_per_pixel = 2;
    cv_type = CV_16UC1;
    scale = static_cast<float>(depth_scale);
  } else if (msg.encoding == "32FC1") {
    bytes_per_pixel = 4;
    cv_type = CV_32FC1;
    scale = 1.0f;
  } else {
    throw std::invalid_argument("Unsupported depth encoding: " + msg.encoding);
  }

  const int row_bytes = width * bytes_per_pixel;
  const size_t required = static_cast<size_t>(height) * static_cast<size_t>(step);
  if (step < row_bytes || msg.data.size() < required) {
    throw std::invalid_argument(
        "depth buffer too small: size=" + std::to_string(msg.data.size()) +
        ", height=" + std::to_string(height) + ", step=" + std::to_string(step) +
        ", row_bytes=" + std::to_string(row_bytes));
  }

  // msg.is_bigendian is not honoured: every depth sensor this node targets
  // (RealSense/RGB-D over ROS2) publishes little-endian, matching x86/ARM
  // host byte order, exactly as the Python reference assumes in practice.
  cv::Mat strided(height, width, cv_type, const_cast<uint8_t*>(msg.data.data()), step);
  cv::Mat out;
  strided.convertTo(out, CV_32FC1, scale);
  return out;
}

}  // namespace pps_pallet_pose_cpp
