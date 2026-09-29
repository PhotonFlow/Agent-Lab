#include "geometry_core/face_mask.hpp"

#include <algorithm>
#include <cmath>

#include <opencv2/imgproc.hpp>

namespace geometry_core {

cv::Mat build_bbox_mask(const Eigen::Vector4d& bbox_xyxy, int height, int width,
                         int erode_px) {
  const double x1 = bbox_xyxy(0);
  const double y1 = bbox_xyxy(1);
  const double x2 = bbox_xyxy(2);
  const double y2 = bbox_xyxy(3);

  const int x1i = std::max(0, static_cast<int>(std::lround(std::min(x1, x2))));
  const int y1i = std::max(0, static_cast<int>(std::lround(std::min(y1, y2))));
  const int x2i = std::min(width, static_cast<int>(std::lround(std::max(x1, x2))));
  const int y2i = std::min(height, static_cast<int>(std::lround(std::max(y1, y2))));

  cv::Mat mask = cv::Mat::zeros(height, width, CV_8UC1);
  if (x2i <= x1i || y2i <= y1i) {
    return mask;
  }
  mask(cv::Rect(x1i, y1i, x2i - x1i, y2i - y1i)).setTo(1);

  if (erode_px > 0) {
    cv::Mat kernel = cv::Mat::ones(3, 3, CV_8UC1);
    cv::erode(mask, mask, kernel, cv::Point(-1, -1), erode_px);
  }
  return mask;
}

}  // namespace geometry_core
