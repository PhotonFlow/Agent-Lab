# Rich stage-2 pallet pose result for the AGV controller.
# The pose is expressed in the camera RGB optical frame (header.frame_id).
std_msgs/Header header

# Full 6-DoF pose. orientation encodes yaw about the optical up axis (-Y);
# yaw_rad below is the authoritative scalar yaw.
geometry_msgs/Pose pose

# Yaw of the pallet face under the REP-103 / right-hand-rule convention
# (see pose.py: yaw = atan2(n_x, -n_z)). Radians.
float64 yaw_rad

# Face normal (pointing toward the camera) in the RGB frame.
float64[3] face_normal_rgb

# Plane-fit quality and observation statistics.
float64 plane_inlier_ratio
int32 n_face_points
float64 chamfer_cost_m

# Quality-gate verdict. When accepted is false, quality_reasons lists the
# tripped gates and the controller should treat the pose as low-confidence.
bool accepted
string[] quality_reasons

# Non-empty only on hard failure (no pose produced).
string failure_reason

# Provenance.
string geometry_source
string preset_id

# Capture-time stamps of the exact synchronized RGB (via its detection
# message, which forwards the RGB image's header verbatim) and depth frames
# that produced this pose -- i.e. the inputs message_filters ApproximateTime
# actually paired, not the time this message was published (header.stamp
# above is the publish time).
builtin_interfaces/Time input_rgb_stamp
builtin_interfaces/Time input_depth_stamp

# Detection2DArray slot admitted to stage 2 for this capture. 0 is a real slot.
# Slots not admitted stay deferred, in candidate-list order.
int32 admitted_source_index
int32[] deferred_source_indices
