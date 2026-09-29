#!/usr/bin/env python3
"""Absolute scorer candidate B. cwd must be the package src tree."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

BUILD_DIR = Path(__file__).resolve().parent.parent / "eval_build" / "scorer_b"
STUB_ROOT = BUILD_DIR / "stub"
STUB_HDR = STUB_ROOT / "vision_msgs" / "msg" / "detection2_d_array.hpp"
DRIVER_SRC = BUILD_DIR / "driver.cpp"
DRIVER_BIN = BUILD_DIR / "driver"
HASH_PATH = BUILD_DIR / "input.sha256"

PIPELINE_HDR = Path("geometry_core/include/geometry_core/pipeline_v3_2.hpp")
DET_HDR = Path("pps_pallet_pose_cpp/include/pps_pallet_pose_cpp/detection_utils.hpp")
DET_SRC = Path("pps_pallet_pose_cpp/src/detection_utils.cpp")
GEO_SRC_DIR = Path("geometry_core/src")

# Dimension-fixture rectangle written into the depth image (integer pixel centres).
DIM_FX = 450.0
DIM_FY = 450.0
DIM_CX = 320.0
DIM_CY = 240.0
DIM_Z = 2.5
DIM_U0, DIM_U1 = 230, 410
DIM_V0, DIM_V1 = 168, 312
DIM_PAD = 8
DEFER_IDX = frozenset((0, 3, 4))

STUB_TEXT = """\
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
"""


def fail(msg: str, code: int = 1) -> None:
    sys.stderr.write(msg.rstrip() + "\n")
    raise SystemExit(code)


def to_wsl(path: Path) -> str:
    resolved = path.resolve()
    text = str(resolved)
    if len(text) >= 2 and text[1] == ":":
        return "/mnt/" + text[0].lower() + text[2:].replace("\\", "/")
    return text.replace("\\", "/")


def extract_struct_body(source: str, name: str) -> str | None:
    match = re.search(r"\bstruct\s+" + re.escape(name) + r"\b", source)
    if not match:
        return None
    brace = source.find("{", match.end())
    if brace < 0:
        return None
    depth = 0
    for idx in range(brace, len(source)):
        ch = source[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1 : idx]
    return None


def has_ident(body: str, name: str) -> bool:
    return re.search(r"\b" + re.escape(name) + r"\b", body) is not None


def inspect_headers() -> tuple[bool, bool]:
    if not PIPELINE_HDR.is_file():
        fail("missing " + PIPELINE_HDR.as_posix())
    if not DET_HDR.is_file():
        fail("missing " + DET_HDR.as_posix())
    pipeline = PIPELINE_HDR.read_text(encoding="utf-8")
    det = DET_HDR.read_text(encoding="utf-8")

    outcome_body = extract_struct_body(pipeline, "EstimatePoseOutcome")
    if outcome_body is None:
        fail("EstimatePoseOutcome not declared in pipeline_v3_2.hpp")
    has_dims = all(
        has_ident(outcome_body, name)
        for name in ("has_dimensions", "width_m", "height_m", "depth_m")
    )

    has_select = re.search(r"\bselect_stage2_subset\s*\(", det) is not None
    if has_select:
        adm_body = extract_struct_body(det, "Stage2Admission")
        if adm_body is None:
            fail(
                "select_stage2_subset is declared but Stage2Admission is missing; "
                "cannot score admitted/deferred"
            )
        if not (has_ident(adm_body, "admitted") and has_ident(adm_body, "deferred")):
            fail(
                "select_stage2_subset is declared but Stage2Admission lacks "
                "vectors named admitted and deferred"
            )
    return has_dims, has_select


def dim_ground_truth() -> tuple[float, float, float]:
    gt_w = (DIM_U1 - DIM_U0) * DIM_Z / DIM_FX
    gt_h = (DIM_V1 - DIM_V0) * DIM_Z / DIM_FY
    return gt_w, gt_h, DIM_Z


def generate_driver(has_dims: bool, has_select: bool) -> str:
    dim_block = ""
    if has_dims:
        dim_block = f"""
  geometry_core::RgbDepthCameraConfig dcam;
  dcam.rgb = geometry_core::PinholeIntrinsics({DIM_FX}, {DIM_FY}, {DIM_CX}, {DIM_CY}, 640, 480);
  dcam.depth = geometry_core::PinholeIntrinsics({DIM_FX}, {DIM_FY}, {DIM_CX}, {DIM_CY}, 640, 480);
  dcam.R_dr = Eigen::Matrix3d::Identity();
  dcam.t_dr = Eigen::Vector3d::Zero();
  dcam.depth_scale = 0.001;

  cv::Mat dim_depth = cv::Mat::zeros(480, 640, CV_32FC1);
  for (int v = {DIM_V0}; v <= {DIM_V1}; ++v) {{
    for (int u = {DIM_U0}; u <= {DIM_U1}; ++u) {{
      dim_depth.at<float>(v, u) = {DIM_Z}f;
    }}
  }}
  const Eigen::Vector4d dim_bbox(
      {DIM_U0 - DIM_PAD}.0, {DIM_V0 - DIM_PAD}.0,
      {DIM_U1 + DIM_PAD}.0, {DIM_V1 + DIM_PAD}.0);
  geometry_core::Stage2Config dcfg;
  dcfg.min_face_points = 100;
  geometry_core::EstimatePoseParams dparams;
  std::mt19937_64 drng(0);
  const auto dim_out = geometry_core::estimate_pose_chamfer_v3_2(
      dim_bbox, dim_depth, dcam, dcfg, dparams, std::nullopt, drng);
  std::printf("DIM_RAN=1\\n");
  std::printf("HAS_DIMENSIONS=%d\\n", dim_out.has_dimensions ? 1 : 0);
  std::printf("WIDTH_M=%.17g\\n", dim_out.width_m);
  std::printf("HEIGHT_M=%.17g\\n", dim_out.height_m);
  std::printf("DEPTH_M=%.17g\\n", dim_out.depth_m);
"""
    else:
        dim_block = """
  std::printf("DIM_RAN=0\\n");
  std::printf("HAS_DIMENSIONS=0\\n");
  std::printf("WIDTH_M=nan\\n");
  std::printf("HEIGHT_M=nan\\n");
  std::printf("DEPTH_M=nan\\n");
"""

    if has_select:
        sel_block = """
  const auto admission = pps_pallet_pose_cpp::select_stage2_subset(
      candidates, "largest_area", static_cast<std::size_t>(2));
  std::printf("ADMITTED=");
  for (std::size_t i = 0; i < admission.admitted.size(); ++i) {
    if (i) std::printf(",");
    std::printf("%d", admission.admitted[i].source_index);
  }
  std::printf("\\nDEFERRED=");
  for (std::size_t i = 0; i < admission.deferred.size(); ++i) {
    if (i) std::printf(",");
    std::printf("%d", admission.deferred[i].source_index);
  }
  std::printf("\\n");
"""
    else:
        sel_block = """
  const auto chosen = pps_pallet_pose_cpp::select_detection(candidates, "highest_confidence");
  if (!chosen.has_value()) {
    std::fprintf(stderr, "select_detection returned empty\\n");
    return 2;
  }
  std::printf("ADMITTED=%d\\n", chosen->source_index);
  std::printf("DEFERRED=\\n");
"""

    return f"""\
#include <chrono>
#include <cmath>
#include <cstdio>
#include <optional>
#include <random>
#include <string>
#include <vector>

#include <Eigen/Dense>
#include <opencv2/core.hpp>

#include "geometry_core/camera_config.hpp"
#include "geometry_core/pipeline_v3_2.hpp"
#include "geometry_core/schemas.hpp"
#include "pps_pallet_pose_cpp/detection_utils.hpp"

int main() {{
  geometry_core::RgbDepthCameraConfig camera;
  camera.rgb = geometry_core::PinholeIntrinsics(900.0, 900.0, 640.0, 480.0, 1280, 960);
  camera.depth = geometry_core::PinholeIntrinsics(450.0, 450.0, 320.0, 240.0, 640, 480);
  camera.R_dr = Eigen::Matrix3d::Identity();
  camera.t_dr = Eigen::Vector3d::Zero();
  camera.depth_scale = 0.001;

  cv::Mat depth(480, 640, CV_32FC1, cv::Scalar(2.0f));
  const Eigen::Vector4d bbox(340.0, 440.0, 940.0, 520.0);
  geometry_core::Stage2Config cfg;
  cfg.min_face_points = 100;
  geometry_core::EstimatePoseParams params;
  std::mt19937_64 rng(0);

  const auto t0 = std::chrono::steady_clock::now();
  const auto outcome = geometry_core::estimate_pose_chamfer_v3_2(
      bbox, depth, camera, cfg, params, std::nullopt, rng);
  const auto t1 = std::chrono::steady_clock::now();
  const double latency_ms =
      std::chrono::duration<double, std::milli>(t1 - t0).count();

  if (!outcome.ok) {{
    std::fprintf(stderr, "estimate_pose_chamfer_v3_2 failed: %s\\n",
                 outcome.failure.failure_reason.c_str());
    return 2;
  }}

  std::printf("POSE_OK=1\\n");
  std::printf("TX=%.17g\\n", outcome.pose.tx);
  std::printf("TY=%.17g\\n", outcome.pose.ty);
  std::printf("TZ=%.17g\\n", outcome.pose.tz);
  std::printf("LATENCY_MS=%.17g\\n", latency_ms);
{dim_block}
  std::vector<pps_pallet_pose_cpp::DetectionCandidate> candidates(5);
  const double scores[5] = {{0.99, 0.70, 0.60, 0.50, 0.40}};
  const double areas[5] = {{2000.0, 50000.0, 40000.0, 30000.0, 1000.0}};
  for (int i = 0; i < 5; ++i) {{
    candidates[i].bbox_xyxy = Eigen::Vector4d(0.0, 0.0, 1.0, 1.0);
    candidates[i].score = scores[i];
    candidates[i].class_id = "pallet";
    candidates[i].area_px = areas[i];
    candidates[i].source_index = i;
  }}
{sel_block}
  return 0;
}}
"""


def input_hash(driver_text: str) -> str:
    digest = hashlib.sha256()
    if not GEO_SRC_DIR.is_dir():
        fail("missing " + GEO_SRC_DIR.as_posix())
    srcs = sorted(p for p in GEO_SRC_DIR.glob("*.cpp") if p.is_file())
    if not srcs:
        fail("no geometry_core/src/*.cpp files")
    for path in srcs:
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    for path in (PIPELINE_HDR, DET_SRC, DET_HDR):
        if not path.is_file():
            fail("missing " + path.as_posix())
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    digest.update(b"DRIVER\0")
    digest.update(driver_text.encode("utf-8"))
    return digest.hexdigest()


def ensure_stub() -> None:
    STUB_HDR.parent.mkdir(parents=True, exist_ok=True)
    STUB_HDR.write_text(STUB_TEXT, encoding="utf-8")


def compile_driver(driver_text: str, digest: str) -> None:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    ensure_stub()
    DRIVER_SRC.write_text(driver_text, encoding="utf-8")
    cached = HASH_PATH.is_file() and DRIVER_BIN.is_file()
    if cached and HASH_PATH.read_text(encoding="utf-8").strip() == digest:
        return

    geo_srcs = sorted(p for p in GEO_SRC_DIR.glob("*.cpp") if p.is_file())
    cwd = Path.cwd()
    includes = [
        "-I/usr/include/eigen3",
        "-I/usr/include/opencv4",
        "-I" + to_wsl(cwd / "geometry_core" / "include"),
        "-I" + to_wsl(cwd / "geometry_core" / "src"),
        "-I" + to_wsl(cwd / "pps_pallet_pose_cpp" / "include"),
        "-I" + to_wsl(STUB_ROOT),
    ]
    sources = [to_wsl(p) for p in geo_srcs]
    sources.append(to_wsl(DET_SRC))
    sources.append(to_wsl(DRIVER_SRC))
    cmd_parts = [
        "/usr/bin/g++",
        "-std=c++17",
        "-O2",
        "-DNDEBUG",
        "-fopenmp",
        *includes,
        *sources,
        "-o",
        to_wsl(DRIVER_BIN),
        "-lopencv_core",
        "-lopencv_imgproc",
        "-lyaml-cpp",
        "-lgomp",
        "-pthread",
    ]
    compile_cmd = " ".join(cmd_parts)
    try:
        proc = subprocess.run(
            ["wsl.exe", "-d", "Ubuntu", "-e", "bash", "-lc", compile_cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        fail("g++ compile timed out")
    if proc.returncode != 0:
        err = (proc.stderr or "") + (proc.stdout or "")
        fail("g++ failed:\n" + err)
    HASH_PATH.write_text(digest + "\n", encoding="utf-8")


def run_driver() -> str:
    try:
        proc = subprocess.run(
            ["wsl.exe", "-d", "Ubuntu", "-e", "bash", "-lc", to_wsl(DRIVER_BIN)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        fail("driver timed out")
    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or "driver exited non-zero"
        fail(err)
    return proc.stdout


def parse_kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key] = value
    return out


def parse_index_list(raw: str) -> list[int]:
    raw = (raw or "").strip()
    if not raw:
        return []
    return [int(part) for part in raw.split(",") if part != ""]


def require_finite(name: str, value: float) -> float:
    if not math.isfinite(value):
        fail(name + " is not a finite float")
    return float(value)


def main() -> int:
    has_dims, has_select = inspect_headers()
    driver_text = generate_driver(has_dims, has_select)
    digest = input_hash(driver_text)
    compile_driver(driver_text, digest)
    parsed = parse_kv(run_driver())

    if parsed.get("POSE_OK") != "1":
        fail("pose fixture did not report POSE_OK")
    try:
        tx = float(parsed["TX"])
        ty = float(parsed["TY"])
        tz = float(parsed["TZ"])
        latency_ms = float(parsed["LATENCY_MS"])
    except (KeyError, ValueError) as exc:
        fail("pose fixture parse error: " + str(exc))

    pose_error_m = math.sqrt(tx * tx + ty * ty + (tz - 2.0) * (tz - 2.0))
    require_finite("pose_error_m", pose_error_m)
    require_finite("latency_ms", latency_ms)

    if has_dims and parsed.get("DIM_RAN") == "1":
        try:
            has_dim_flag = int(parsed["HAS_DIMENSIONS"])
            width_m = float(parsed["WIDTH_M"])
            height_m = float(parsed["HEIGHT_M"])
            depth_m = float(parsed["DEPTH_M"])
        except (KeyError, ValueError) as exc:
            fail("dimension fixture parse error: " + str(exc))
        if has_dim_flag and all(math.isfinite(v) for v in (width_m, height_m, depth_m)):
            gt_w, gt_h, gt_d = dim_ground_truth()
            dimension_error_m = (
                abs(width_m - gt_w) + abs(height_m - gt_h) + abs(depth_m - gt_d)
            )
        else:
            dimension_error_m = 3.0
    else:
        dimension_error_m = 3.0
    require_finite("dimension_error_m", dimension_error_m)

    try:
        admitted = parse_index_list(parsed.get("ADMITTED", ""))
        deferred = parse_index_list(parsed.get("DEFERRED", ""))
    except ValueError as exc:
        fail("selection fixture parse error: " + str(exc))
    deferred_set = set(deferred)
    bad_admitted = sum(1 for idx in admitted if idx in DEFER_IDX)
    missing_deferred = sum(1 for idx in DEFER_IDX if idx not in deferred_set)
    selection_error = float(bad_admitted) + 0.25 * float(missing_deferred)
    require_finite("selection_error", selection_error)

    scenario_error = pose_error_m + dimension_error_m + selection_error
    require_finite("scenario_error", scenario_error)

    payload = {
        "scenario_error": scenario_error,
        "pose_error_m": pose_error_m,
        "latency_ms": latency_ms,
        "dimension_error_m": dimension_error_m,
        "selection_error": selection_error,
    }
    sys.stdout.write(json.dumps(payload, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        fail(str(exc))
