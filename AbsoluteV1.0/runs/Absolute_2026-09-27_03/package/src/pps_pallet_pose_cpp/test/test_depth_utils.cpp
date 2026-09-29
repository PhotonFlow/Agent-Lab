#include <gtest/gtest.h>

#include <cstring>
#include <vector>

#include <sensor_msgs/msg/image.hpp>

#include "pps_pallet_pose_cpp/depth_utils.hpp"

namespace {

sensor_msgs::msg::Image make_16uc1_image(int height, int width, const std::vector<uint16_t>& pixels) {
  sensor_msgs::msg::Image msg;
  msg.height = static_cast<uint32_t>(height);
  msg.width = static_cast<uint32_t>(width);
  msg.encoding = "16UC1";
  msg.is_bigendian = 0;
  msg.step = static_cast<uint32_t>(width) * 2;
  msg.data.resize(static_cast<size_t>(height) * msg.step);
  std::memcpy(msg.data.data(), pixels.data(), pixels.size() * sizeof(uint16_t));
  return msg;
}

sensor_msgs::msg::Image make_32fc1_image(int height, int width, const std::vector<float>& pixels) {
  sensor_msgs::msg::Image msg;
  msg.height = static_cast<uint32_t>(height);
  msg.width = static_cast<uint32_t>(width);
  msg.encoding = "32FC1";
  msg.is_bigendian = 0;
  msg.step = static_cast<uint32_t>(width) * 4;
  msg.data.resize(static_cast<size_t>(height) * msg.step);
  std::memcpy(msg.data.data(), pixels.data(), pixels.size() * sizeof(float));
  return msg;
}

}  // namespace

TEST(DepthUtils, Uint16MillimetresScaledToMetres) {
  auto msg = make_16uc1_image(1, 2, {1000, 2500});
  cv::Mat out = pps_pallet_pose_cpp::depth_image_to_meters(msg, 0.001);
  ASSERT_EQ(out.rows, 1);
  ASSERT_EQ(out.cols, 2);
  EXPECT_NEAR(out.at<float>(0, 0), 1.0f, 1e-6f);
  EXPECT_NEAR(out.at<float>(0, 1), 2.5f, 1e-6f);
}

TEST(DepthUtils, Float32PassthroughIgnoresDepthScale) {
  auto msg = make_32fc1_image(1, 2, {0.75f, 1.25f});
  cv::Mat out = pps_pallet_pose_cpp::depth_image_to_meters(msg, 0.001);
  EXPECT_NEAR(out.at<float>(0, 0), 0.75f, 1e-6f);
  EXPECT_NEAR(out.at<float>(0, 1), 1.25f, 1e-6f);
}

TEST(DepthUtils, ZeroPixelPreservedAsZeroNotFiltered) {
  auto msg = make_16uc1_image(1, 1, {0});
  cv::Mat out = pps_pallet_pose_cpp::depth_image_to_meters(msg, 0.001);
  EXPECT_NEAR(out.at<float>(0, 0), 0.0f, 1e-6f);
}

TEST(DepthUtils, RespectsRowStrideLargerThanTightWidth) {
  sensor_msgs::msg::Image msg;
  msg.height = 1;
  msg.width = 2;
  msg.encoding = "16UC1";
  msg.is_bigendian = 0;
  msg.step = 8;  // padded stride, tight row would be 4 bytes
  msg.data.assign(8, 0);
  uint16_t row[2] = {3000, 4000};
  std::memcpy(msg.data.data(), row, sizeof(row));
  cv::Mat out = pps_pallet_pose_cpp::depth_image_to_meters(msg, 0.001);
  EXPECT_NEAR(out.at<float>(0, 0), 3.0f, 1e-6f);
  EXPECT_NEAR(out.at<float>(0, 1), 4.0f, 1e-6f);
}

TEST(DepthUtils, UnsupportedEncodingThrows) {
  sensor_msgs::msg::Image msg;
  msg.height = 1;
  msg.width = 1;
  msg.encoding = "rgb8";
  msg.step = 3;
  msg.data.assign(3, 0);
  EXPECT_THROW(pps_pallet_pose_cpp::depth_image_to_meters(msg, 0.001), std::invalid_argument);
}

TEST(DepthUtils, UndersizedBufferThrows) {
  sensor_msgs::msg::Image msg;
  msg.height = 2;
  msg.width = 2;
  msg.encoding = "16UC1";
  msg.step = 4;
  msg.data.assign(4, 0);  // only 1 row's worth of data, height=2 expected
  EXPECT_THROW(pps_pallet_pose_cpp::depth_image_to_meters(msg, 0.001), std::invalid_argument);
}
