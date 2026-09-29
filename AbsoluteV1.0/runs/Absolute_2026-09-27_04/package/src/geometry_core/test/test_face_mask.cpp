#include <gtest/gtest.h>

#include "geometry_core/face_mask.hpp"

using geometry_core::build_bbox_mask;

TEST(FaceMask, NoErosionFillsExactRectangle) {
  Eigen::Vector4d bbox(2.0, 3.0, 8.0, 9.0);  // x1,y1,x2,y2
  cv::Mat mask = build_bbox_mask(bbox, /*height=*/12, /*width=*/12, /*erode_px=*/0);
  ASSERT_EQ(mask.rows, 12);
  ASSERT_EQ(mask.cols, 12);
  EXPECT_EQ(mask.at<uint8_t>(3, 2), 1);
  EXPECT_EQ(mask.at<uint8_t>(8, 7), 1);
  EXPECT_EQ(mask.at<uint8_t>(9, 2), 0);   // row 9 is exclusive (y2=9)
  EXPECT_EQ(mask.at<uint8_t>(3, 8), 0);   // col 8 is exclusive (x2=8)
  EXPECT_EQ(mask.at<uint8_t>(0, 0), 0);
}

TEST(FaceMask, ErosionShrinksMaskInward) {
  Eigen::Vector4d bbox(2.0, 2.0, 10.0, 10.0);
  cv::Mat no_erode = build_bbox_mask(bbox, 14, 14, 0);
  cv::Mat eroded = build_bbox_mask(bbox, 14, 14, 2);
  const int no_erode_count = cv::countNonZero(no_erode);
  const int eroded_count = cv::countNonZero(eroded);
  EXPECT_LT(eroded_count, no_erode_count);
  // The centre pixel must survive erosion for a big-enough box.
  EXPECT_EQ(eroded.at<uint8_t>(6, 6), 1);
}

TEST(FaceMask, DegenerateBboxProducesEmptyMask) {
  Eigen::Vector4d bbox(5.0, 5.0, 5.0, 5.0);  // zero area
  cv::Mat mask = build_bbox_mask(bbox, 10, 10, 0);
  EXPECT_EQ(cv::countNonZero(mask), 0);
}

TEST(FaceMask, BboxIsClampedToImageBounds) {
  Eigen::Vector4d bbox(-5.0, -5.0, 100.0, 100.0);
  cv::Mat mask = build_bbox_mask(bbox, 10, 10, 0);
  EXPECT_EQ(cv::countNonZero(mask), 100);  // whole 10x10 image
}
