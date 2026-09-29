// pps_v3.3_ros/src/pps_pallet_pose_cpp/src/pallet_pose_node_main.cpp
#include <rclcpp/rclcpp.hpp>

#include "pps_pallet_pose_cpp/pallet_pose_node.hpp"

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  auto node = std::make_shared<pps_pallet_pose_cpp::PalletPoseNode>();
  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
