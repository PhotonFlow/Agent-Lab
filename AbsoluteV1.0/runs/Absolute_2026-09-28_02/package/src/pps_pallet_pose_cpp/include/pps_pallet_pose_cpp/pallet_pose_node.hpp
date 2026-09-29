// pps_v3.3_ros/src/pps_pallet_pose_cpp/include/pps_pallet_pose_cpp/pallet_pose_node.hpp
#pragma once

#include <memory>
#include <optional>
#include <random>
#include <string>

#include <diagnostic_msgs/msg/diagnostic_array.hpp>
#include <geometry_msgs/msg/pose_stamped.hpp>
#include <builtin_interfaces/msg/time.hpp>
#include <message_filters/subscriber.h>
#include <message_filters/sync_policies/approximate_time.h>
#include <message_filters/synchronizer.h>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <vision_msgs/msg/detection2_d_array.hpp>

#include <geometry_core/camera_config.hpp>
#include <geometry_core/pipeline_v3_2.hpp>
#include <pps_perception_msgs/msg/pallet_pose_stamped.hpp>

#include "pps_pallet_pose_cpp/detection_utils.hpp"

namespace pps_pallet_pose_cpp {

class PalletPoseNode : public rclcpp::Node {
 public:
  PalletPoseNode();

 private:
  using SyncPolicy = message_filters::sync_policies::ApproximateTime<
      sensor_msgs::msg::Image, vision_msgs::msg::Detection2DArray>;

  void on_pair(const sensor_msgs::msg::Image::ConstSharedPtr& depth_msg,
               const vision_msgs::msg::Detection2DArray::ConstSharedPtr& det_msg);
  void publish_pose(const geometry_core::PoseResult& pose,
                     const geometry_core::EstimatePoseOutcome& outcome, const std::string& frame_id,
                     const builtin_interfaces::msg::Time& input_rgb_stamp,
                     const builtin_interfaces::msg::Time& input_depth_stamp,
                     const Stage2Admission& admission);
  void publish_failure_diagnostics(const geometry_core::FailureResult& failure,
                                     const builtin_interfaces::msg::Time& input_rgb_stamp,
                                     const builtin_interfaces::msg::Time& input_depth_stamp,
                                     const Stage2Admission& admission);
  void publish_ok_diagnostics(const geometry_core::PoseResult& pose,
                               const geometry_core::EstimatePoseOutcome& outcome,
                               const builtin_interfaces::msg::Time& input_rgb_stamp,
                               const builtin_interfaces::msg::Time& input_depth_stamp);

  geometry_core::RgbDepthCameraConfig camera_cfg_;
  geometry_core::Stage2Config stage2_cfg_;
  geometry_core::EstimatePoseParams params_;
  std::mt19937_64 rng_{0};

  rclcpp::Publisher<geometry_msgs::msg::PoseStamped>::SharedPtr pose_pub_;
  rclcpp::Publisher<pps_perception_msgs::msg::PalletPoseStamped>::SharedPtr rich_pub_;
  rclcpp::Publisher<diagnostic_msgs::msg::DiagnosticArray>::SharedPtr diag_pub_;

  std::unique_ptr<message_filters::Subscriber<sensor_msgs::msg::Image>> depth_sub_;
  std::unique_ptr<message_filters::Subscriber<vision_msgs::msg::Detection2DArray>> det_sub_;
  std::unique_ptr<message_filters::Synchronizer<SyncPolicy>> sync_;

  std::string target_class_id_;
  std::string detection_selection_;
  std::string camera_frame_id_;
};

}  // namespace pps_pallet_pose_cpp
