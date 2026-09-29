// pps_v3.3_ros/src/pps_pallet_pose_cpp/src/pallet_pose_node.cpp
#include "pps_pallet_pose_cpp/pallet_pose_node.hpp"

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <sstream>
#include <stdexcept>

#ifdef _OPENMP
#include <omp.h>
#endif

#include "pps_pallet_pose_cpp/depth_utils.hpp"
#include "pps_pallet_pose_cpp/detection_utils.hpp"
#include "pps_pallet_pose_cpp/rich_face_extents.hpp"

namespace pps_pallet_pose_cpp {

namespace {

// "<sec>.<nanosec, zero-padded to 9 digits>", e.g. 1720000000.123456789.
std::string stamp_to_string(const builtin_interfaces::msg::Time& stamp) {
  std::ostringstream oss;
  oss << stamp.sec << '.' << std::setw(9) << std::setfill('0') << stamp.nanosec;
  return oss.str();
}

}  // namespace

namespace {

// Mirrors pps_pallet_pose/node.py::yaw_to_quaternion_optical exactly: yaw
// about the optical-frame up axis (-Y). Message-encoding logic, not
// algorithm, so it is re-derived here rather than calling into geometry_core.
void yaw_to_quaternion_optical(double yaw_rad, double& qx, double& qy, double& qz, double& qw) {
  const double half = 0.5 * yaw_rad;
  qx = 0.0;
  qy = -std::sin(half);
  qz = 0.0;
  qw = std::cos(half);
}

}  // namespace

PalletPoseNode::PalletPoseNode() : rclcpp::Node("pallet_pose_cpp_node") {
  this->declare_parameter<std::string>("camera_yaml_path", "");
  this->declare_parameter<std::string>("target_class_id", "pallet");
  this->declare_parameter<std::string>("detection_selection", "highest_confidence");
  this->declare_parameter<double>("sync_slop_s", 0.10);
  this->declare_parameter<int>("sync_queue_size", 10);
  this->declare_parameter<std::string>("depth_topic", "/camera/depth/image_raw");
  this->declare_parameter<std::string>("detections_topic", "/pps/detections");
  this->declare_parameter<std::string>("pose_topic", "/pps/pallet_pose");
  this->declare_parameter<std::string>("pallet_pose_topic", "/pps/pallet_pose_rich");
  this->declare_parameter<std::string>("diagnostics_topic", "/pps/pallet_pose_diagnostics");
  this->declare_parameter<std::string>("camera_frame_id", "camera_rgb_optical_frame");
  this->declare_parameter<int>("max_stage2", 2);

  const std::string camera_yaml_path = this->get_parameter("camera_yaml_path").as_string();
  if (camera_yaml_path.empty()) {
    throw std::invalid_argument("camera_yaml_path parameter is required");
  }
  camera_cfg_ = geometry_core::RgbDepthCameraConfig::from_yaml(camera_yaml_path);
  // stage2_cfg_ and params_ are left at geometry_core's built-in defaults
  // (the validated "production" configuration) — no overrides in this
  // thin wrapper, per the no-algorithm-changes constraint.

  target_class_id_ = this->get_parameter("target_class_id").as_string();
  detection_selection_ = this->get_parameter("detection_selection").as_string();
  camera_frame_id_ = this->get_parameter("camera_frame_id").as_string();
  const int max_stage2_param = static_cast<int>(this->get_parameter("max_stage2").as_int());
  max_stage2_ = static_cast<std::size_t>(std::max(0, max_stage2_param));

  pose_pub_ = this->create_publisher<geometry_msgs::msg::PoseStamped>(
      this->get_parameter("pose_topic").as_string(), 10);
  rich_pub_ = this->create_publisher<pps_perception_msgs::msg::PalletPoseStamped>(
      this->get_parameter("pallet_pose_topic").as_string(), 10);
  diag_pub_ = this->create_publisher<diagnostic_msgs::msg::DiagnosticArray>(
      this->get_parameter("diagnostics_topic").as_string(), 10);

  depth_sub_ = std::make_unique<message_filters::Subscriber<sensor_msgs::msg::Image>>(
      this, this->get_parameter("depth_topic").as_string());
  det_sub_ = std::make_unique<message_filters::Subscriber<vision_msgs::msg::Detection2DArray>>(
      this, this->get_parameter("detections_topic").as_string());

  const int queue_size = static_cast<int>(this->get_parameter("sync_queue_size").as_int());
  sync_ = std::make_unique<message_filters::Synchronizer<SyncPolicy>>(
      SyncPolicy(queue_size), *depth_sub_, *det_sub_);
  sync_->setMaxIntervalDuration(
      rclcpp::Duration::from_seconds(this->get_parameter("sync_slop_s").as_double()));
  sync_->registerCallback(std::bind(&PalletPoseNode::on_pair, this, std::placeholders::_1,
                                     std::placeholders::_2));

  RCLCPP_INFO(this->get_logger(), "pallet_pose_cpp_node up: camera_yaml=%s",
              camera_yaml_path.c_str());
#ifdef _OPENMP
  RCLCPP_INFO(this->get_logger(), "OpenMP max threads: %d", omp_get_max_threads());
#else
  RCLCPP_WARN(this->get_logger(), "OpenMP not enabled at compile time");
#endif
}

void PalletPoseNode::on_pair(const sensor_msgs::msg::Image::ConstSharedPtr& depth_msg,
                              const vision_msgs::msg::Detection2DArray::ConstSharedPtr& det_msg) {
  auto candidates = extract_detection_candidates(*det_msg, target_class_id_);
  Stage2Admission admission;
  try {
    admission = select_stage2_subset(candidates, detection_selection_, max_stage2_);
  } catch (const std::invalid_argument& exc) {
    RCLCPP_WARN(this->get_logger(), "%s", exc.what());
    return;
  }

  const std::string frame_id = det_msg->header.frame_id.empty() ? camera_frame_id_
                                                                  : det_msg->header.frame_id;
  const auto& input_rgb_stamp = det_msg->header.stamp;
  const auto& input_depth_stamp = depth_msg->header.stamp;
  if (!admission.deferred.empty()) {
    publish_deferred(admission.deferred, input_rgb_stamp, input_depth_stamp);
  }
  if (admission.admitted.empty()) {
    return;
  }

  cv::Mat depth_m;
  try {
    depth_m = depth_image_to_meters(*depth_msg, camera_cfg_.depth_scale);
  } catch (const std::exception& exc) {
    RCLCPP_WARN(this->get_logger(), "%s", exc.what());
    return;
  }

  for (const auto& candidate : admission.admitted) {
    auto outcome = geometry_core::estimate_pose_chamfer_v3_2(
        candidate.bbox_xyxy, depth_m, camera_cfg_, stage2_cfg_, params_, candidate.source_index,
        rng_);
    if (!outcome.ok) {
      publish_failure_diagnostics(outcome.failure, input_rgb_stamp, input_depth_stamp);
      continue;
    }
    publish_ok_diagnostics(outcome.pose, outcome, input_rgb_stamp, input_depth_stamp);
    publish_pose(outcome.pose, outcome, frame_id, input_rgb_stamp, input_depth_stamp);
  }
}

void PalletPoseNode::publish_pose(const geometry_core::PoseResult& pose,
                                   const geometry_core::EstimatePoseOutcome& outcome,
                                   const std::string& frame_id,
                                   const builtin_interfaces::msg::Time& input_rgb_stamp,
                                   const builtin_interfaces::msg::Time& input_depth_stamp) {
  double qx, qy, qz, qw;
  yaw_to_quaternion_optical(pose.yaw_rad, qx, qy, qz, qw);
  const auto stamp = this->get_clock()->now();

  geometry_msgs::msg::PoseStamped ps;
  ps.header.frame_id = frame_id;
  ps.header.stamp = stamp;
  ps.pose.position.x = pose.tx;
  ps.pose.position.y = pose.ty;
  ps.pose.position.z = pose.tz;
  ps.pose.orientation.x = qx;
  ps.pose.orientation.y = qy;
  ps.pose.orientation.z = qz;
  ps.pose.orientation.w = qw;
  pose_pub_->publish(ps);

  pps_perception_msgs::msg::PalletPoseStamped rich;
  rich.header = ps.header;
  rich.pose = ps.pose;
  rich.yaw_rad = pose.yaw_rad;
  rich.face_normal_rgb = {pose.face_normal_rgb.x(), pose.face_normal_rgb.y(),
                           pose.face_normal_rgb.z()};
  rich.plane_inlier_ratio = pose.plane_inlier_ratio;
  rich.n_face_points = pose.n_face_points;
  rich.chamfer_cost_m = outcome.has_debug ? outcome.debug.chamfer_cost_m : 0.0;
  // No quality-gate concept in geometry_core: every successfully-estimated
  // pose is reported accepted with no rejection reasons.
  rich.accepted = true;
  rich.failure_reason = "";
  rich.geometry_source = pose.geometry_source;
  rich.preset_id = "geometry_core_default";
  rich.input_rgb_stamp = input_rgb_stamp;
  rich.input_depth_stamp = input_depth_stamp;
  assign_rich_face_extents(rich, outcome.has_dimensions, outcome.width_m, outcome.height_m,
                           outcome.depth_m);
  rich_pub_->publish(rich);
}

void PalletPoseNode::publish_failure_diagnostics(const geometry_core::FailureResult& failure,
                                                   const builtin_interfaces::msg::Time& input_rgb_stamp,
                                                   const builtin_interfaces::msg::Time& input_depth_stamp) {
  diagnostic_msgs::msg::DiagnosticArray diag;
  diag.header.stamp = this->get_clock()->now();
  diagnostic_msgs::msg::DiagnosticStatus status;
  status.name = "pps_pallet_pose_cpp";
  status.hardware_id = "dynamic_handling_ros_v1";
  status.level = diagnostic_msgs::msg::DiagnosticStatus::WARN;
  status.message = failure.failure_reason;
  diagnostic_msgs::msg::KeyValue kv;
  kv.key = "failure_reason";
  kv.value = failure.failure_reason;
  status.values.push_back(kv);
  diagnostic_msgs::msg::KeyValue rgb_kv;
  rgb_kv.key = "input_rgb_stamp";
  rgb_kv.value = stamp_to_string(input_rgb_stamp);
  status.values.push_back(rgb_kv);
  diagnostic_msgs::msg::KeyValue depth_kv;
  depth_kv.key = "input_depth_stamp";
  depth_kv.value = stamp_to_string(input_depth_stamp);
  status.values.push_back(depth_kv);
  diag.status.push_back(status);
  diag_pub_->publish(diag);
}

void PalletPoseNode::publish_ok_diagnostics(const geometry_core::PoseResult& pose,
                                             const geometry_core::EstimatePoseOutcome& outcome,
                                             const builtin_interfaces::msg::Time& input_rgb_stamp,
                                             const builtin_interfaces::msg::Time& input_depth_stamp) {
  diagnostic_msgs::msg::DiagnosticArray diag;
  diag.header.stamp = this->get_clock()->now();
  diagnostic_msgs::msg::DiagnosticStatus status;
  status.name = "pps_pallet_pose_cpp";
  status.hardware_id = "dynamic_handling_ros_v1";
  status.level = diagnostic_msgs::msg::DiagnosticStatus::OK;
  status.message = "pose_estimated";
  auto add = [&status](const std::string& key, const std::string& value) {
    diagnostic_msgs::msg::KeyValue kv;
    kv.key = key;
    kv.value = value;
    status.values.push_back(kv);
  };
  add("chamfer_cost_m", outcome.has_debug ? std::to_string(outcome.debug.chamfer_cost_m) : "");
  add("plane_inlier_ratio", std::to_string(pose.plane_inlier_ratio));
  add("n_face_points", std::to_string(pose.n_face_points));
  add("input_rgb_stamp", stamp_to_string(input_rgb_stamp));
  add("input_depth_stamp", stamp_to_string(input_depth_stamp));
  diag.status.push_back(status);
  diag_pub_->publish(diag);
}

void PalletPoseNode::publish_deferred(const std::vector<DetectionCandidate>& deferred,
                                       const builtin_interfaces::msg::Time& input_rgb_stamp,
                                       const builtin_interfaces::msg::Time& input_depth_stamp) {
  diagnostic_msgs::msg::DiagnosticArray diag;
  diag.header.stamp = this->get_clock()->now();
  diagnostic_msgs::msg::DiagnosticStatus status;
  status.name = "pps_pallet_pose_cpp";
  status.hardware_id = "dynamic_handling_ros_v1";
  status.level = diagnostic_msgs::msg::DiagnosticStatus::OK;
  status.message = "pallet_deferred";
  std::ostringstream indices;
  for (std::size_t i = 0; i < deferred.size(); ++i) {
    if (i != 0) {
      indices << ',';
    }
    indices << deferred[i].source_index;
  }
  diagnostic_msgs::msg::KeyValue kv;
  kv.key = "deferred_source_index";
  kv.value = indices.str();
  status.values.push_back(kv);
  diagnostic_msgs::msg::KeyValue rgb_kv;
  rgb_kv.key = "input_rgb_stamp";
  rgb_kv.value = stamp_to_string(input_rgb_stamp);
  status.values.push_back(rgb_kv);
  diagnostic_msgs::msg::KeyValue depth_kv;
  depth_kv.key = "input_depth_stamp";
  depth_kv.value = stamp_to_string(input_depth_stamp);
  status.values.push_back(depth_kv);
  diag.status.push_back(status);
  diag_pub_->publish(diag);
}

}  // namespace pps_pallet_pose_cpp
