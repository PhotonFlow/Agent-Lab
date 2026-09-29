"""Frontal pallet centre: bbox ray beats a sub-pixel chamfer shift.

The default prototype, matched to an identity-extrinsic render of the synthetic
face, has a chamfer minimum 2 mm off the true centre. That shift is inside the
depth-pixel quantization radius, so pipeline_v3_2 keeps the bbox-ray centre.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pps_perception_bringup"))

from pps_perception_bringup.synthetic_scene import (  # noqa: E402
    TZ_M,
    face_bbox_rgb,
    load_camera,
    render_depth_mm,
)

CAM_YAML = ROOT / "pps_perception_bringup" / "config" / "camera.yaml"
PIPELINE = ROOT / "geometry_core" / "src" / "pipeline_v3_2.cpp"


def _sample_segment(p0, p1, spacing):
    length = float(np.linalg.norm(p1 - p0))
    n = max(2, int(math.ceil(length / spacing)) + 1)
    t = np.arange(n, dtype=np.float64) / n
    return p0 + t[:, None] * (p1 - p0)


def _sample_rect(width, height, cx, cy, spacing):
    hw, hh = 0.5 * width, 0.5 * height
    corners = np.array(
        [[cx - hw, cy - hh], [cx + hw, cy - hh], [cx + hw, cy + hh], [cx - hw, cy + hh]],
        dtype=np.float64,
    )
    return np.vstack([_sample_segment(corners[i], corners[(i + 1) % 4], spacing) for i in range(4)])


def _default_prototype():
    outer = _sample_rect(1.20, 0.14, 0.0, 0.0, 0.03)
    hole_l = _sample_rect(0.47, 0.10, -0.28, 0.0, 0.03)
    hole_r = _sample_rect(0.47, 0.10, 0.28, 0.0, 0.03)
    return np.vstack([outer, hole_l, hole_r])


def _sample_points(depth_m, mask_rgb, cam):
    k_d_inv = np.linalg.inv(
        np.array(
            [[cam.depth.fx, 0, cam.depth.cx], [0, cam.depth.fy, cam.depth.cy], [0, 0, 1]],
            dtype=np.float64,
        )
    )
    k_r = np.array(
        [[cam.rgb.fx, 0, cam.rgb.cx], [0, cam.rgb.fy, cam.rgb.cy], [0, 0, 1]],
        dtype=np.float64,
    )
    vs, us = np.mgrid[0 : depth_m.shape[0], 0 : depth_m.shape[1]]
    z = depth_m.astype(np.float64)
    valid = np.isfinite(z) & (z >= 0.3) & (z <= 5.0)
    rays = np.stack([us, vs, np.ones_like(us)], axis=-1).reshape(-1, 3) @ k_d_inv.T
    p_d = rays * z.reshape(-1, 1)
    p_r = p_d @ cam.R_dr.T + cam.t_dr
    valid = valid.reshape(-1) & (p_r[:, 2] > 0)
    uv = np.stack(
        [
            k_r[0, 0] * p_r[:, 0] / np.maximum(p_r[:, 2], 1e-12) + k_r[0, 2],
            k_r[1, 1] * p_r[:, 1] / np.maximum(p_r[:, 2], 1e-12) + k_r[1, 2],
        ],
        axis=1,
    )
    ui = np.rint(uv[:, 0]).astype(np.int64)
    vi = np.rint(uv[:, 1]).astype(np.int64)
    inside = (ui >= 0) & (ui < cam.rgb.width) & (vi >= 0) & (vi < cam.rgb.height)
    valid &= inside
    ui_v, vi_v = ui[valid], vi[valid]
    valid_idx = np.flatnonzero(valid)
    keep = mask_rgb[vi_v, ui_v] != 0
    return p_d[valid_idx[keep]]


def _plane_frame(points):
    centroid = points.mean(axis=0)
    _, _, vt = np.linalg.svd(points - centroid, full_matrices=False)
    normal = vt[-1].copy()
    if normal[2] > 0:
        normal = -normal
    offset = -float(normal @ centroid)
    origin = -offset * normal
    e_up = np.array([0.0, -1.0, 0.0])
    if abs(float(e_up @ normal)) > 0.95:
        e_up = np.array([1.0, 0.0, 0.0])
    axis_u = e_up - float(e_up @ normal) * normal
    axis_u = axis_u / np.linalg.norm(axis_u)
    if axis_u[0] < 0:
        axis_u = -axis_u
    axis_v = np.cross(normal, axis_u)
    axis_v = axis_v / np.linalg.norm(axis_v)
    return normal, offset, origin, axis_u, axis_v


def _project(points, origin, axis_u, axis_v):
    rel = points - origin
    return np.column_stack([rel @ axis_u, rel @ axis_v])


def _distance_image(obs, resolution=0.005, padding=0.80):
    min_xy = obs.min(axis=0) - padding
    max_xy = obs.max(axis=0) + padding
    width = int(math.ceil((max_xy[0] - min_xy[0]) / resolution)) + 1
    height = int(math.ceil((max_xy[1] - min_xy[1]) / resolution)) + 1
    mask = np.zeros((height, width), np.uint8)
    cols = np.rint((obs[:, 0] - min_xy[0]) / resolution).astype(np.int64)
    rows = np.rint((obs[:, 1] - min_xy[1]) / resolution).astype(np.int64)
    ok = (rows >= 0) & (rows < height) & (cols >= 0) & (cols < width)
    mask[rows[ok], cols[ok]] = 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(closed, 8)
    if n > 1:
        largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        closed = (labels == largest).astype(np.uint8)
    eroded = cv2.erode(closed, np.ones((3, 3), np.uint8), iterations=1)
    edge = cv2.bitwise_and(closed, cv2.bitwise_not(eroded))
    src = np.where(edge != 0, 0, 1).astype(np.uint8)
    dist = cv2.distanceTransform(src, cv2.DIST_L2, cv2.DIST_MASK_PRECISE).astype(np.float32)
    return dist * resolution, min_xy, resolution


def _chamfer(proto, theta, tx, ty, dist, min_xy, resolution):
    c, s = math.cos(theta), math.sin(theta)
    pts = proto @ np.array([[c, s], [-s, c]])
    pts = pts + np.array([tx, ty])
    col_f = (pts[:, 0] - min_xy[0]) / resolution
    row_f = (pts[:, 1] - min_xy[1]) / resolution
    c0 = np.floor(col_f).astype(np.int64)
    r0 = np.floor(row_f).astype(np.int64)
    dx = col_f - c0
    dy = row_f - r0
    penalty = 50.0 * resolution
    out = np.full(pts.shape[0], penalty)
    h, w = dist.shape
    ok = (r0 >= 0) & (r0 + 1 < h) & (c0 >= 0) & (c0 + 1 < w)
    r0o, c0o, dxo, dyo = r0[ok], c0[ok], dx[ok], dy[ok]
    out[ok] = (
        (1 - dxo) * (1 - dyo) * dist[r0o, c0o]
        + dxo * (1 - dyo) * dist[r0o, c0o + 1]
        + (1 - dxo) * dyo * dist[r0o + 1, c0o]
        + dxo * dyo * dist[r0o + 1, c0o + 1]
    )
    ordered = np.sort(out)
    keep = max(1, int(math.ceil(0.9 * ordered.size)))
    return float(ordered[:keep].mean())


def _ray_plane(uv, cam, normal, offset):
    k_r_inv = np.linalg.inv(
        np.array(
            [[cam.rgb.fx, 0, cam.rgb.cx], [0, cam.rgb.fy, cam.rgb.cy], [0, 0, 1]],
            dtype=np.float64,
        )
    )
    ray_r = k_r_inv @ np.array([uv[0], uv[1], 1.0])
    r_rd = cam.R_dr.T
    origin = -r_rd @ cam.t_dr
    direction = r_rd @ ray_r
    denom = float(normal @ direction)
    t = -(float(normal @ origin) + offset) / denom
    return origin + t * direction


class FrontalCentreBiasTest(unittest.TestCase):
    def test_pipeline_keeps_bbox_ray_inside_silhouette_quantization(self):
        source = PIPELINE.read_text(encoding="utf-8")
        self.assertIn("silhouette", source)
        self.assertIn("quant_radius", source)

    def test_chamfer_shift_is_quantization_and_bbox_ray_is_closer(self):
        cam = load_camera(str(CAM_YAML))
        cam = type(cam)(
            rgb=cam.rgb,
            depth=cam.depth,
            R_dr=np.eye(3),
            t_dr=np.zeros(3),
            depth_scale=cam.depth_scale,
        )
        depth_mm = render_depth_mm(cam, tz=TZ_M)
        depth_m = np.zeros(depth_mm.shape, np.float32)
        np.divide(depth_mm, 1000.0, out=depth_m, where=depth_mm > 0)
        bbox = face_bbox_rgb(cam, tz=TZ_M)
        x1, y1, x2, y2 = bbox
        x1i, y1i = max(0, int(round(min(x1, x2)))), max(0, int(round(min(y1, y2))))
        x2i = min(cam.rgb.width, int(round(max(x1, x2))))
        y2i = min(cam.rgb.height, int(round(max(y1, y2))))
        mask = np.zeros((cam.rgb.height, cam.rgb.width), np.uint8)
        mask[y1i:y2i, x1i:x2i] = 1
        mask = cv2.erode(mask, np.ones((3, 3), np.uint8), iterations=2)

        points = _sample_points(depth_m, mask, cam)
        normal, offset, origin, axis_u, axis_v = _plane_frame(points)
        obs = _project(points, origin, axis_u, axis_v)
        dist, min_xy, resolution = _distance_image(obs)
        proto = _default_prototype()

        centre_uv = np.array([0.5 * (bbox[0] + bbox[2]), 0.5 * (bbox[1] + bbox[3])])
        centre_d = _ray_plane(centre_uv, cam, normal, offset)
        centre_2d = _project(centre_d.reshape(1, 3), origin, axis_u, axis_v)[0]
        true_d = np.array([0.0, 0.0, TZ_M])

        def pose_err(tx, ty):
            point = origin + tx * axis_u + ty * axis_v
            return float(np.linalg.norm(point - true_d))

        best = None
        for deg in (89.8, 90.0, 90.2, -90.2, -90.0, -89.8):
            theta = math.radians(deg)
            for iy in range(-6, 7):
                ty = centre_2d[1] + iy * 0.001
                for ix in range(-6, 7):
                    tx = centre_2d[0] + ix * 0.001
                    cost = _chamfer(proto, theta, tx, ty, dist, min_xy, resolution)
                    if best is None or cost < best[0]:
                        best = (cost, tx, ty)
        shift = math.hypot(best[1] - centre_2d[0], best[2] - centre_2d[1])
        z_abs = abs(float(centre_d[2]))
        quant_radius = 0.5 * math.hypot(z_abs / cam.depth.fx, z_abs / cam.depth.fy)
        bbox_err = pose_err(centre_2d[0], centre_2d[1])
        chamfer_err = pose_err(best[1], best[2])

        self.assertLess(bbox_err, 0.0005)
        self.assertGreater(chamfer_err, 0.0015)
        self.assertGreater(shift, 0.001)
        self.assertLessEqual(shift, quant_radius)
        self.assertLess(bbox_err, chamfer_err - 0.001)


if __name__ == "__main__":
    unittest.main()
