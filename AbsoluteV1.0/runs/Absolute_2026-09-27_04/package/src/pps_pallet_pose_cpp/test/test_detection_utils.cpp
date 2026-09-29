#include <gtest/gtest.h>

#include <vision_msgs/msg/detection2_d_array.hpp>

#include "pps_pallet_pose_cpp/detection_utils.hpp"

namespace {

using pps_pallet_pose_cpp::DetectionCandidate;
using vision_msgs::msg::Detection2D;
using vision_msgs::msg::Detection2DArray;
using vision_msgs::msg::ObjectHypothesisWithPose;

Detection2D make_detection(double cx, double cy, double w, double h, const std::string& class_id,
                            double score) {
  Detection2D d;
  d.bbox.center.position.x = cx;
  d.bbox.center.position.y = cy;
  d.bbox.size_x = w;
  d.bbox.size_y = h;
  ObjectHypothesisWithPose hyp;
  hyp.hypothesis.class_id = class_id;
  hyp.hypothesis.score = score;
  d.results.push_back(hyp);
  return d;
}

}  // namespace

TEST(DetectionUtils, ExtractComputesXyxyFromCenterSize) {
  Detection2DArray arr;
  arr.detections.push_back(make_detection(10.0, 20.0, 4.0, 6.0, "pallet", 0.9));
  auto candidates = pps_pallet_pose_cpp::extract_detection_candidates(arr, "");
  ASSERT_EQ(candidates.size(), 1u);
  EXPECT_DOUBLE_EQ(candidates[0].bbox_xyxy(0), 8.0);
  EXPECT_DOUBLE_EQ(candidates[0].bbox_xyxy(1), 17.0);
  EXPECT_DOUBLE_EQ(candidates[0].bbox_xyxy(2), 12.0);
  EXPECT_DOUBLE_EQ(candidates[0].bbox_xyxy(3), 23.0);
  EXPECT_DOUBLE_EQ(candidates[0].area_px, 24.0);
  EXPECT_EQ(candidates[0].source_index, 0);
}

TEST(DetectionUtils, ExtractFiltersByTargetClassId) {
  Detection2DArray arr;
  arr.detections.push_back(make_detection(0, 0, 1, 1, "forklift", 0.99));
  arr.detections.push_back(make_detection(0, 0, 1, 1, "pallet", 0.5));
  auto candidates = pps_pallet_pose_cpp::extract_detection_candidates(arr, "pallet");
  ASSERT_EQ(candidates.size(), 1u);
  EXPECT_EQ(candidates[0].class_id, "pallet");
  EXPECT_EQ(candidates[0].source_index, 1);
}

TEST(DetectionUtils, ExtractSkipsDetectionsWithNoResults) {
  Detection2DArray arr;
  Detection2D empty;
  empty.bbox.size_x = 1;
  empty.bbox.size_y = 1;
  arr.detections.push_back(empty);
  auto candidates = pps_pallet_pose_cpp::extract_detection_candidates(arr, "");
  EXPECT_TRUE(candidates.empty());
}

TEST(DetectionUtils, ExtractPicksHighestScoringHypothesisPerDetection) {
  Detection2DArray arr;
  Detection2D d = make_detection(0, 0, 1, 1, "low", 0.1);
  ObjectHypothesisWithPose better;
  better.hypothesis.class_id = "high";
  better.hypothesis.score = 0.8;
  d.results.push_back(better);
  arr.detections.push_back(d);
  auto candidates = pps_pallet_pose_cpp::extract_detection_candidates(arr, "");
  ASSERT_EQ(candidates.size(), 1u);
  EXPECT_EQ(candidates[0].class_id, "high");
  EXPECT_DOUBLE_EQ(candidates[0].score, 0.8);
}

TEST(DetectionUtils, SelectHighestConfidencePicksHighestScore) {
  std::vector<DetectionCandidate> candidates = {
      {Eigen::Vector4d(0, 0, 1, 1), 0.5, "pallet", 1.0, 0},
      {Eigen::Vector4d(0, 0, 1, 1), 0.9, "pallet", 1.0, 1},
  };
  auto chosen = pps_pallet_pose_cpp::select_detection(candidates, "highest_confidence");
  ASSERT_TRUE(chosen.has_value());
  EXPECT_EQ(chosen->source_index, 1);
}

TEST(DetectionUtils, SelectLargestAreaPicksLargestArea) {
  std::vector<DetectionCandidate> candidates = {
      {Eigen::Vector4d(0, 0, 1, 1), 0.9, "pallet", 5.0, 0},
      {Eigen::Vector4d(0, 0, 1, 1), 0.5, "pallet", 50.0, 1},
  };
  auto chosen = pps_pallet_pose_cpp::select_detection(candidates, "largest_area");
  ASSERT_TRUE(chosen.has_value());
  EXPECT_EQ(chosen->source_index, 1);
}

TEST(DetectionUtils, SelectOnEmptyCandidatesReturnsNullopt) {
  std::vector<DetectionCandidate> candidates;
  auto chosen = pps_pallet_pose_cpp::select_detection(candidates, "highest_confidence");
  EXPECT_FALSE(chosen.has_value());
}

TEST(DetectionUtils, SelectUnknownStrategyThrows) {
  std::vector<DetectionCandidate> candidates = {{Eigen::Vector4d(0, 0, 1, 1), 0.9, "pallet", 1.0, 0}};
  EXPECT_THROW(pps_pallet_pose_cpp::select_detection(candidates, "bogus"), std::invalid_argument);
}

TEST(DetectionUtils, Stage2LargestAreaAdmitsTopTwoAndDefersTheRest) {
  const double scores[5] = {0.99, 0.70, 0.60, 0.50, 0.40};
  const double areas[5] = {2000.0, 50000.0, 40000.0, 30000.0, 1000.0};
  std::vector<DetectionCandidate> candidates;
  candidates.reserve(5);
  for (int i = 0; i < 5; ++i) {
    DetectionCandidate c;
    c.bbox_xyxy = Eigen::Vector4d(0.0, 0.0, 10.0, 10.0);
    c.score = scores[i];
    c.class_id = "pallet";
    c.area_px = areas[i];
    c.source_index = i;
    candidates.push_back(c);
  }

  const auto admission = pps_pallet_pose_cpp::select_stage2_subset(
      candidates, "largest_area", static_cast<std::size_t>(2));

  ASSERT_EQ(admission.admitted.size(), 2u);
  EXPECT_EQ(admission.admitted[0].source_index, 1);
  EXPECT_EQ(admission.admitted[1].source_index, 2);
  ASSERT_EQ(admission.deferred.size(), 3u);
  EXPECT_EQ(admission.deferred[0].source_index, 0);
  EXPECT_EQ(admission.deferred[1].source_index, 3);
  EXPECT_EQ(admission.deferred[2].source_index, 4);
}
