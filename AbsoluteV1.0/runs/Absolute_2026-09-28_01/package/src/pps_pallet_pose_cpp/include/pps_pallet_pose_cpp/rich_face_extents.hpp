#pragma once

namespace pps_pallet_pose_cpp {

// Extents carried on /pps/pallet_pose_rich with the pose from the same
// stage-2 estimate. Width is the camera-x span of the inlier face, height
// is the camera-y span, and depth is the mean range, all in metres.
// Present only when that estimate produced the inlier face.
template <typename RichMsg>
void assign_rich_face_extents(RichMsg& rich, bool estimate_produced_extents, double width_m,
                              double height_m, double depth_m) {
  if (!estimate_produced_extents) {
    rich.has_dimensions = false;
    rich.width_m = 0.0;
    rich.height_m = 0.0;
    rich.depth_m = 0.0;
    return;
  }
  rich.has_dimensions = true;
  rich.width_m = width_m;
  rich.height_m = height_m;
  rich.depth_m = depth_m;
}

}  // namespace pps_pallet_pose_cpp
