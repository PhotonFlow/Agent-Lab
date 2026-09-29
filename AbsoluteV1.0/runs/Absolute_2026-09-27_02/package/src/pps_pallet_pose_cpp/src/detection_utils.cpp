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

Stage2Admission select_stage2_subset(const std::vector<DetectionCandidate>& candidates,
                                      const std::string& strategy, std::size_t max_stage2) {
  Stage2Admission admission;
  if (candidates.empty() || max_stage2 == 0) {
    admission.deferred = candidates;
    return admission;
  }

  std::vector<DetectionCandidate> ranked = candidates;
  if (strategy == "highest_confidence") {
    std::sort(ranked.begin(), ranked.end(), [](const DetectionCandidate& a, const DetectionCandidate& b) {
      if (a.score != b.score) return a.score > b.score;
      if (a.area_px != b.area_px) return a.area_px > b.area_px;
      return a.source_index < b.source_index;
    });
  } else if (strategy == "largest_area") {
    std::sort(ranked.begin(), ranked.end(), [](const DetectionCandidate& a, const DetectionCandidate& b) {
      if (a.area_px != b.area_px) return a.area_px > b.area_px;
      if (a.score != b.score) return a.score > b.score;
      return a.source_index < b.source_index;
    });
  } else {
    throw std::invalid_argument("Unknown detection selection strategy: " + strategy);
  }

  const std::size_t n_admit = std::min(max_stage2, ranked.size());
  admission.admitted.assign(ranked.begin(), ranked.begin() + static_cast<std::ptrdiff_t>(n_admit));
  admission.deferred.assign(ranked.begin() + static_cast<std::ptrdiff_t>(n_admit), ranked.end());
  return admission;
}

}  // namespace pps_pallet_pose_cpp
