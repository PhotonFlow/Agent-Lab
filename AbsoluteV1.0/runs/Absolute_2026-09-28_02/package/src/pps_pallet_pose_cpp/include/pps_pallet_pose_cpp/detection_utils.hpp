#pragma once

#include <optional>
#include <string>
#include <vector>

#include <Eigen/Dense>
#include <vision_msgs/msg/detection2_d_array.hpp>

namespace pps_pallet_pose_cpp {

struct DetectionCandidate {
  Eigen::Vector4d bbox_xyxy;
  double score = 0.0;
  std::string class_id;
  double area_px = 0.0;
  int source_index = -1;
};

// Mirrors pps_pallet_pose/detections.py::extract_detection_candidates.
// target_class_id == "" disables class filtering (matches Python's
// target_class_id=None). Only the highest-scoring hypothesis per detection
// is kept, mirroring the Python `max(results, key=score)` behaviour.
std::vector<DetectionCandidate> extract_detection_candidates(
    const vision_msgs::msg::Detection2DArray& detections, const std::string& target_class_id);

// Mirrors pps_pallet_pose/detections.py::select_detection. Throws
// std::invalid_argument for an unknown strategy (matching Python's
// ValueError). Returns std::nullopt for an empty candidate list.
std::optional<DetectionCandidate> select_detection(
    const std::vector<DetectionCandidate>& candidates, const std::string& strategy);

// First-maximum admission of one capture's class-matched candidates.
// An empty list returns both vectors empty before the strategy is checked.
// An unknown strategy throws std::invalid_argument. admitted is rank order,
// at most count. deferred keeps candidate-list order. Each copy keeps source_index.
struct Stage2Admission {
  std::vector<DetectionCandidate> admitted;
  std::vector<DetectionCandidate> deferred;
};

Stage2Admission select_stage2_subset(
    const std::vector<DetectionCandidate>& candidates, const std::string& strategy, int count);

// One diagnostic value. An empty deferred list is an empty string.
std::string deferred_source_indices_text(const std::vector<DetectionCandidate>& deferred);

}  // namespace pps_pallet_pose_cpp
