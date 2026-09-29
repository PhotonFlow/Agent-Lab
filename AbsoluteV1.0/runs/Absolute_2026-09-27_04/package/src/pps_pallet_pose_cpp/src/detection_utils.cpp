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
    return *std::max_element(
        candidates.begin(), candidates.end(), [](const DetectionCandidate& a, const DetectionCandidate& b) {
          if (a.score != b.score) return a.score < b.score;
          return a.area_px < b.area_px;
        });
  }
  if (strategy == "largest_area") {
    return *std::max_element(
        candidates.begin(), candidates.end(), [](const DetectionCandidate& a, const DetectionCandidate& b) {
          if (a.area_px != b.area_px) return a.area_px < b.area_px;
          return a.score < b.score;
        });
  }
  throw std::invalid_argument("Unknown detection selection strategy: " + strategy);
}

Stage2Admission select_stage2_subset(
    const std::vector<DetectionCandidate>& candidates, const std::string& strategy, std::size_t k) {
  if (strategy != "largest_area") {
    throw std::invalid_argument("Unknown detection selection strategy: " + strategy);
  }
  std::vector<std::size_t> ranked(candidates.size());
  for (std::size_t i = 0; i < ranked.size(); ++i) {
    ranked[i] = i;
  }
  std::sort(ranked.begin(), ranked.end(), [&](std::size_t ia, std::size_t ib) {
    const DetectionCandidate& a = candidates[ia];
    const DetectionCandidate& b = candidates[ib];
    if (a.area_px != b.area_px) {
      return a.area_px > b.area_px;
    }
    if (a.score != b.score) {
      return a.score > b.score;
    }
    return ia < ib;
  });

  const std::size_t admit_n = std::min(k, candidates.size());
  Stage2Admission admission;
  admission.admitted.reserve(admit_n);
  std::vector<char> is_admitted(candidates.size(), 0);
  for (std::size_t i = 0; i < admit_n; ++i) {
    is_admitted[ranked[i]] = 1;
    admission.admitted.push_back(candidates[ranked[i]]);
  }
  admission.deferred.reserve(candidates.size() - admit_n);
  for (std::size_t i = 0; i < candidates.size(); ++i) {
    if (is_admitted[i] == 0) {
      admission.deferred.push_back(candidates[i]);
    }
  }
  return admission;
}

}  // namespace pps_pallet_pose_cpp
