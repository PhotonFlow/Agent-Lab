#pragma once

#include <string>
#include <vector>

namespace vision_msgs {
namespace msg {

struct Point2D {
  double x = 0.0;
  double y = 0.0;
};

struct Pose2D {
  Point2D position;
};

struct BoundingBox2D {
  Pose2D center;
  double size_x = 0.0;
  double size_y = 0.0;
};

struct ObjectHypothesis {
  double score = 0.0;
  std::string class_id;
};

struct ObjectHypothesisWithPose {
  ObjectHypothesis hypothesis;
};

struct Detection2D {
  std::vector<ObjectHypothesisWithPose> results;
  BoundingBox2D bbox;
};

struct Detection2DArray {
  std::vector<Detection2D> detections;
};

}  // namespace msg
}  // namespace vision_msgs
