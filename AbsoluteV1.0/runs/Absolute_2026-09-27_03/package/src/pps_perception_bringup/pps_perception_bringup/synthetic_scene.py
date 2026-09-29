"""Synthetic pallet scene for mock end-to-end testing (ROS-free).

Renders a frontal planar pallet face (with two pocket holes punched out) into a
depth image, and computes the matching RGB bounding box, both derived from the
same metric 3D geometry so the depth observation and the (mock) detector bbox
are mutually consistent. Used by ``scene_publisher`` and the launch test.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import yaml

# Canonical pallet face geometry (EU pallet face), placed frontally at TZ_M.
TZ_M = 2.0
HALF_W = 0.55
HALF_H = 0.40
POCKET_HALF_W = 0.15
POCKET_HALF_H = 0.05
POCKET_OFFSET = 0.30


@dataclass(frozen=True)
class _Intr:
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int


@dataclass(frozen=True)
class CameraModel:
    rgb: _Intr
    depth: _Intr
    R_dr: np.ndarray
    t_dr: np.ndarray
    depth_scale: float


def load_camera(yaml_path: str) -> CameraModel:
    with open(yaml_path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    def intr(block: dict) -> _Intr:
        return _Intr(
            fx=float(block["fx"]),
            fy=float(block["fy"]),
            cx=float(block["cx"]),
            cy=float(block["cy"]),
            width=int(block.get("width", 0)),
            height=int(block.get("height", 0)),
        )

    extr = data["depth_to_rgb_extrinsic"]
    R_dr = np.array(extr["rotation"], dtype=np.float64)
    t_mm = extr["translation_mm"]
    t_dr = np.array([t_mm["x"], t_mm["y"], t_mm["z"]], dtype=np.float64) * 1e-3
    return CameraModel(
        rgb=intr(data["rgb_camera"]),
        depth=intr(data["depth_camera"]),
        R_dr=R_dr,
        t_dr=t_dr,
        depth_scale=float(data.get("depth_scale", 0.001)),
    )


def render_depth_mm(cam: CameraModel, *, tz: float = TZ_M) -> np.ndarray:
    """Return an ``(Hd, Wd) uint16`` depth image in millimetres (0 = invalid)."""
    d = cam.depth
    uu, vv = np.meshgrid(np.arange(d.width), np.arange(d.height))
    x = (uu - d.cx) / d.fx * tz
    y = (vv - d.cy) / d.fy * tz
    on_face = (np.abs(x) <= HALF_W) & (np.abs(y) <= HALF_H)
    in_pocket = (np.abs(y) <= POCKET_HALF_H) & (
        (np.abs(x - POCKET_OFFSET) <= POCKET_HALF_W)
        | (np.abs(x + POCKET_OFFSET) <= POCKET_HALF_W)
    )
    valid = on_face & ~in_pocket
    depth_mm = np.where(valid, np.uint16(round(tz * 1000.0)), np.uint16(0))
    return depth_mm.astype(np.uint16)


def face_bbox_rgb(cam: CameraModel, *, tz: float = TZ_M) -> list[float]:
    """Project the 4 face corners into the RGB frame; return ``[x1,y1,x2,y2]``."""
    corners_d = np.array(
        [
            [-HALF_W, -HALF_H, tz],
            [HALF_W, -HALF_H, tz],
            [HALF_W, HALF_H, tz],
            [-HALF_W, HALF_H, tz],
        ],
        dtype=np.float64,
    )
    corners_r = corners_d @ cam.R_dr.T + cam.t_dr.reshape(1, 3)
    u = cam.rgb.fx * corners_r[:, 0] / corners_r[:, 2] + cam.rgb.cx
    v = cam.rgb.fy * corners_r[:, 1] / corners_r[:, 2] + cam.rgb.cy
    return [float(u.min()), float(v.min()), float(u.max()), float(v.max())]


def make_rgb(cam: CameraModel) -> np.ndarray:
    """A neutral-grey RGB image (content is irrelevant for the mock backend)."""
    return np.full((cam.rgb.height, cam.rgb.width, 3), 128, dtype=np.uint8)


def face_bbox_rgb_from_yaml(yaml_path: str, *, tz: float = TZ_M) -> list[float]:
    return face_bbox_rgb(load_camera(yaml_path), tz=tz)
