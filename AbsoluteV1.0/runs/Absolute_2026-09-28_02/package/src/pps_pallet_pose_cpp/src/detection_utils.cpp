#include "pps_pallet_pose_cpp/detection_utils.hpp"

#include <algorithm>
#include <stdexcept>

namespace pps_pallet_pose_cpp {

namespace {

Eigen::Vector4d bbox_to_xyxy(const vision_msgs::msg::BoundingBox2D& bbox) {
  const double cx = bbox.center.position.x;
  const double cy = bbox.center.position.y;
  const double half_w = 0.5 * bbox.size_x;
  const double half_h = 0.5 * bbox.size_y;
  return Eigen::Vector4d(cx - half_w, cy - half_h, cx + half_w, cy + half_h);
}

bool less_highest_confidence(const DetectionCandidate& a, const DetectionCandidate& b) {
  if (a.score != b.score) {
    return a.score < b.score;
  }
  return a.area_px < b.area_px;
}

bool less_largest_area(const DetectionCandidate& a, const DetectionCandidate& b) {
  if (a.area_px != b.area_px) {
    return a.area_px < b.area_px;
  }
  return a.score < b.score;
}

}  // namespace

std::vector<DetectionCandidate> extract_detection_candidates(
    const vision_msgs::msg::Detection2DArray& detections, const std::string& target_class_id) {
  std::vector<DetectionCandidate> candidates;
  for (size_t idx = 0; idx < detections.detections.size(); ++idx) {
    const auto& detection = detections.detections[idx];
    if (detection.results.empty()) {
      continue;
    }
    const auto* best = &detection.results.front();
    for (const auto& r : detection.results) {
      if (r.hypothesis.score > best->hypothesis.score) {
        best = &r;
      }
    }
    const std::string class_id = best->hypothesis.class_id;
    if (!target_class_id.empty() && class_id != target_class_id) {
      continue;
    }
    const Eigen::Vector4d bbox_xyxy = bbox_to_xyxy(detection.bbox);
    const double width = std::max(0.0, bbox_xyxy(2) - bbox_xyxy(0));
    const double height = std::max(0.0, bbox_xyxy(3) - bbox_xyxy(1));
    DetectionCandidate candidate;
    candidate.bbox_xyxy = bbox_xyxy;
    candidate.score = best->hypothesis.score;
    candidate.class_id = class_id;
    candidate.area_px = width * height;
    candidate.source_index = static_cast<int>(idx);
    candidates.push_back(candidate);
  }
  return candidates;
}

std::optional<DetectionCandidate> select_detection(
    const std::vector<DetectionCandidate>& candidates, const std::string& strategy) {
  if (candidates.empty()) {
    return std::nullopt;
  }
  if (strategy == "highest_confidence") {
    return *std::max_element(candidates.begin(), candidates.end(), less_highest_confidence);
  }
  if (strategy == "largest_area") {
    return *std::max_element(candidates.begin(), candidates.end(), less_largest_area);
  }
  throw std::invalid_argument("Unknown detection selection strategy: " + strategy);
}

Stage2Admission select_stage2_subset(
    const std::vector<DetectionCandidate>& candidates, const std::string& strategy, int count) {
  Stage2Admission admission;
  if (candidates.empty()) {
    return admission;
  }
  const bool highest = strategy == "highest_confidence";
  const bool largest = strategy == "largest_area";
  if (!highest && !largest) {
    throw std::invalid_argument("Unknown detection selection strategy: " + strategy);
  }
  const auto less = highest ? less_highest_confidence : less_largest_area;
  std::vector<unsigned char> chosen(candidates.size(), 0);
  const int admit_limit = count > 0 ? count : 0;
  for (int admitted_n = 0; admitted_n < admit_limit; ++admitted_n) {
    std::vector<std::size_t> open;
    open.reserve(candidates.size());
    for (std::size_t index = 0; index < candidates.size(); ++index) {
      if (!chosen[index]) {
        open.push_back(index);
      }
    }
    if (open.empty()) {
      break;
    }
    const auto best = std::max_element(
        open.begin(), open.end(),
        [&](std::size_t left, std::size_t right) {
          return less(candidates[left], candidates[right]);
        });
    chosen[*best] = 1;
    admission.admitted.push_back(candidates[*best]);
  }
  for (std::size_t index = 0; index < candidates.size(); ++index) {
    if (!chosen[index]) {
      admission.deferred.push_back(candidates[index]);
    }
  }
  return admission;
}

std::string deferred_source_indices_text(const std::vector<DetectionCandidate>& deferred) {
  std::string text;
  for (std::size_t index = 0; index < deferred.size(); ++index) {
    if (index != 0) {
      text.push_back(',');
    }
    text += std::to_string(deferred[index].source_index);
  }
  return text;
}

}  // namespace pps_pallet_pose_cpp
