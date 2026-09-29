"""Analytical pose oracle for one synthetic fronto-parallel pallet.

The scene matches geometry_core/test/test_pipeline_v3_2.cpp
RecoversFrontoParallelPoseOnSyntheticScene: a flat depth plane at z = 2 m,
coincident pinhole cameras, and an RGB box centred on the principal point.
Ground truth is that construction, not a recorded estimator output.

Yaw is converted to metres by the horizontal half-extent of that box at the
true depth. Yaw is a rotation about the camera's vertical axis, so that
half-extent is the arc-length lever arm. The scenario states pose error in
metres and names yaw, but it does not give a separate angular weight.
"""

from __future__ import annotations

import math

# Identical RGB and depth pinhole models from the synthetic test.
RGB_FX = 900.0
RGB_FY = 900.0
RGB_CX = 640.0
RGB_CY = 480.0
RGB_WIDTH = 1280
RGB_HEIGHT = 960
DEPTH_FX = 450.0
DEPTH_FY = 450.0
DEPTH_CX = 320.0
DEPTH_CY = 240.0
DEPTH_WIDTH = 640
DEPTH_HEIGHT = 480

# Plane distance and box half-size in pixels: (cx ± 300, cy ± 40).
PLANE_Z_M = 2.0
BBOX_HALF_WIDTH_PX = 300.0
BBOX_HALF_HEIGHT_PX = 40.0

GT_TX_M = 0.0
GT_TY_M = 0.0
GT_TZ_M = PLANE_Z_M
GT_YAW_RAD = 0.0

# Stage2Config::depth_max_m. A rejected pose is scored at the far gate of the
# estimator's own valid depth range, which is worse than any in-range residual
# this scene can produce (the plane is at 2 m and the search window is 0.15 m).
FAILURE_PENALTY_M = 5.0

CASE_ID = "synthetic_fronto_parallel"


def yaw_lever_arm_m() -> float:
    """Metres of arc at the true plane for one radian of yaw."""
    return BBOX_HALF_WIDTH_PX / RGB_FX * PLANE_Z_M


def wrap_rad(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def pose_error_m(tx: float, ty: float, tz: float, yaw_rad: float, ok: bool) -> float:
    if not ok:
        return FAILURE_PENALTY_M
    for value in (tx, ty, tz, yaw_rad):
        if not math.isfinite(value):
            return FAILURE_PENALTY_M
    lever = yaw_lever_arm_m()
    dyaw = wrap_rad(yaw_rad - GT_YAW_RAD)
    return math.sqrt(
        (tx - GT_TX_M) ** 2
        + (ty - GT_TY_M) ** 2
        + (tz - GT_TZ_M) ** 2
        + (dyaw * lever) ** 2
    )


def scene_header() -> str:
    """C++ constants consumed by the harness. Generated on each run."""
    return f"""#pragma once
namespace bench_scene {{
constexpr double kRgbFx = {RGB_FX:.17g};
constexpr double kRgbFy = {RGB_FY:.17g};
constexpr double kRgbCx = {RGB_CX:.17g};
constexpr double kRgbCy = {RGB_CY:.17g};
constexpr int kRgbWidth = {RGB_WIDTH};
constexpr int kRgbHeight = {RGB_HEIGHT};
constexpr double kDepthFx = {DEPTH_FX:.17g};
constexpr double kDepthFy = {DEPTH_FY:.17g};
constexpr double kDepthCx = {DEPTH_CX:.17g};
constexpr double kDepthCy = {DEPTH_CY:.17g};
constexpr int kDepthWidth = {DEPTH_WIDTH};
constexpr int kDepthHeight = {DEPTH_HEIGHT};
constexpr double kPlaneZM = {PLANE_Z_M:.17g};
constexpr double kBboxHalfWidthPx = {BBOX_HALF_WIDTH_PX:.17g};
constexpr double kBboxHalfHeightPx = {BBOX_HALF_HEIGHT_PX:.17g};
}}
"""
