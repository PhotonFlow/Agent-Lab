#!/usr/bin/env python3
"""Absolute scorer C: pose, dimensions, and stage-2 selection."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys


DIM_MEMBERS = ("has_dimensions", "width_m", "height_m", "depth_m")
MUST_DEFER = frozenset((0, 3, 4))

# Dimension-fixture face (pixel centers, identical 640x480 cameras, z=2.5).
DIM_Z = 2.5
DIM_FX = 450.0
DIM_FY = 450.0
DIM_CX = 320.0
DIM_CY = 240.0
DIM_U0, DIM_U1 = 230, 410
DIM_V0, DIM_V1 = 168, 312
DIM_BBOX_PAD = 8

VISION_STUB = """#pragma once

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
  BoundingBox2D bbox;
  std::vector<ObjectHypothesisWithPose> results;
};

struct Detection2DArray {
  std::vector<Detection2D> detections;
};

}  // namespace msg
}  // namespace vision_msgs
"""


def die(msg: str, code: int = 1) -> None:
    sys.stderr.write(msg.rstrip() + "\n")
    raise SystemExit(code)


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//.*?$", " ", text, flags=re.M)
    return text


def struct_body(text: str, name: str):
    cleaned = strip_comments(text)
    m = re.search(r"\bstruct\s+" + re.escape(name) + r"\b", cleaned)
    if not m:
        return None
    brace = cleaned.find("{", m.end())
    if brace < 0:
        return None
    depth = 0
    for i, ch in enumerate(cleaned[brace:], start=brace):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return cleaned[brace + 1 : i]
    return None


def has_member(body: str, name: str) -> bool:
    return re.search(r"\b" + re.escape(name) + r"\b", body) is not None


def win_to_wsl(path: str) -> str:
    abs_path = os.path.abspath(path)
    drive, rest = os.path.splitdrive(abs_path)
    rest = rest.replace("\\", "/")
    if drive:
        return "/mnt/" + drive[0].lower() + rest
    return rest


def sh_quote(path: str) -> str:
    return "'" + win_to_wsl(path).replace("'", "'\\''") + "'"


def wsl_run(command: str, timeout: int):
    return subprocess.run(
        ["wsl.exe", "-d", "Ubuntu", "-e", "bash", "-lc", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def file_sha(path: str) -> bytes:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.digest()


def dim_ground_truth():
    xs = [(u - DIM_CX) / DIM_FX * DIM_Z for u in range(DIM_U0, DIM_U1 + 1)]
    ys = [(v - DIM_CY) / DIM_FY * DIM_Z for v in range(DIM_V0, DIM_V1 + 1)]
    return max(xs) - min(xs), max(ys) - min(ys), DIM_Z


def parse_headers():
    with open(os.path.join("geometry_core", "include", "geometry_core", "pipeline_v3_2.hpp"), "r", encoding="utf-8") as f:
        pose_hdr = f.read()
    with open(
        os.path.join("pps_pallet_pose_cpp", "include", "pps_pallet_pose_cpp", "detection_utils.hpp"),
        "r",
        encoding="utf-8",
    ) as f:
        det_hdr = f.read()

    outcome = struct_body(pose_hdr, "EstimatePoseOutcome")
    if outcome is None:
        die("EstimatePoseOutcome not found in pipeline_v3_2.hpp")
    have_dims = all(has_member(outcome, m) for m in DIM_MEMBERS)

    cleaned = strip_comments(det_hdr)
    have_select = re.search(r"\bselect_stage2_subset\b", cleaned) is not None
    if have_select:
        admission = struct_body(det_hdr, "Stage2Admission")
        if admission is None:
            die("select_stage2_subset is declared but Stage2Admission is missing")
        if not has_member(admission, "admitted") or not has_member(admission, "deferred"):
            die(
                "Stage2Admission must declare vectors named admitted and deferred; "
                "refusing to score zero from missing members"
            )
    return have_dims, have_select


def generate_driver(have_dims: bool, have_select: bool) -> str:
    dim_block = ""
    if have_dims:
        x0 = float(DIM_U0 - DIM_BBOX_PAD)
        y0 = float(DIM_V0 - DIM_BBOX_PAD)
        x1 = float(DIM_U1 + DIM_BBOX_PAD)
        y1 = float(DIM_V1 + DIM_BBOX_PAD)
        dim_block = f"""
  {{
    geometry_core::RgbDepthCameraConfig cam;
    cam.rgb = geometry_core::PinholeIntrinsics({DIM_FX}, {DIM_FY}, {DIM_CX}, {DIM_CY}, 640, 480);
    cam.depth = geometry_core::PinholeIntrinsics({DIM_FX}, {DIM_FY}, {DIM_CX}, {DIM_CY}, 640, 480);
    cam.R_dr = Eigen::Matrix3d::Identity();
    cam.t_dr = Eigen::Vector3d::Zero();
    cam.depth_scale = 0.001;
    cv::Mat depth(480, 640, CV_32FC1, cv::Scalar(0.0f));
    for (int v = {DIM_V0}; v <= {DIM_V1}; ++v) {{
      for (int u = {DIM_U0}; u <= {DIM_U1}; ++u) {{
        depth.at<float>(v, u) = static_cast<float>({DIM_Z});
      }}
    }}
    Eigen::Vector4d bbox({x0}, {y0}, {x1}, {y1});
    geometry_core::Stage2Config cfg;
    cfg.min_face_points = 100;
    geometry_core::EstimatePoseParams params;
    std::mt19937_64 rng(0);
    auto outcome = geometry_core::estimate_pose_chamfer_v3_2(
        bbox, depth, cam, cfg, params, std::nullopt, rng);
    const int hd = outcome.has_dimensions ? 1 : 0;
    std::cout << "has_dimensions " << hd << "\\n";
    std::cout << "width_m " << outcome.width_m << "\\n";
    std::cout << "height_m " << outcome.height_m << "\\n";
    std::cout << "depth_m " << outcome.depth_m << "\\n";
  }}
"""
    else:
        dim_block = "  std::cout << \"has_dimensions skip\\n\";\n"

    if have_select:
        sel_block = """
  {
    auto admission = pps_pallet_pose_cpp::select_stage2_subset(cands, "largest_area",
                                                               static_cast<std::size_t>(2));
    std::cout << "admitted";
    for (const auto& c : admission.admitted) std::cout << " " << c.source_index;
    std::cout << "\\n";
    std::cout << "deferred";
    for (const auto& c : admission.deferred) std::cout << " " << c.source_index;
    std::cout << "\\n";
  }
"""
    else:
        sel_block = """
  {
    auto chosen = pps_pallet_pose_cpp::select_detection(cands, "highest_confidence");
    if (!chosen.has_value()) {
      std::cerr << "select_detection returned empty\\n";
      return 1;
    }
    std::cout << "admitted " << chosen->source_index << "\\n";
    std::cout << "deferred\\n";
  }
"""

    return f"""#include <chrono>
#include <cmath>
#include <cstddef>
#include <iostream>
#include <optional>
#include <random>
#include <string>
#include <vector>

#include <Eigen/Dense>
#include <opencv2/core.hpp>

#include "geometry_core/pipeline_v3_2.hpp"
#include "pps_pallet_pose_cpp/detection_utils.hpp"

int main() {{
  geometry_core::RgbDepthCameraConfig cam;
  cam.rgb = geometry_core::PinholeIntrinsics(900.0, 900.0, 640.0, 480.0, 1280, 960);
  cam.depth = geometry_core::PinholeIntrinsics(450.0, 450.0, 320.0, 240.0, 640, 480);
  cam.R_dr = Eigen::Matrix3d::Identity();
  cam.t_dr = Eigen::Vector3d::Zero();
  cam.depth_scale = 0.001;

  cv::Mat depth(480, 640, CV_32FC1, cv::Scalar(2.0f));
  Eigen::Vector4d bbox(340.0, 440.0, 940.0, 520.0);
  geometry_core::Stage2Config cfg;
  cfg.min_face_points = 100;
  geometry_core::EstimatePoseParams params;
  std::mt19937_64 rng(0);

  const auto t0 = std::chrono::steady_clock::now();
  auto outcome = geometry_core::estimate_pose_chamfer_v3_2(
      bbox, depth, cam, cfg, params, std::nullopt, rng);
  const auto t1 = std::chrono::steady_clock::now();
  const double latency_ms =
      std::chrono::duration<double, std::milli>(t1 - t0).count();

  if (!outcome.ok) {{
    std::cerr << "estimate_pose_chamfer_v3_2 failed: " << outcome.failure.failure_reason
              << "\\n";
    return 1;
  }}
  const double tx = outcome.pose.tx;
  const double ty = outcome.pose.ty;
  const double tz = outcome.pose.tz;
  if (!std::isfinite(tx) || !std::isfinite(ty) || !std::isfinite(tz) ||
      !std::isfinite(latency_ms)) {{
    std::cerr << "non-finite pose or latency\\n";
    return 1;
  }}
  std::cout.setf(std::ios::fmtflags(0), std::ios::floatfield);
  std::cout << std::setprecision(17);
  std::cout << "tx " << tx << "\\n";
  std::cout << "ty " << ty << "\\n";
  std::cout << "tz " << tz << "\\n";
  std::cout << "latency_ms " << latency_ms << "\\n";
{dim_block}
  std::vector<pps_pallet_pose_cpp::DetectionCandidate> cands(5);
  const double scores[5] = {{0.99, 0.70, 0.60, 0.50, 0.40}};
  const double areas[5] = {{2000.0, 50000.0, 40000.0, 30000.0, 1000.0}};
  for (int i = 0; i < 5; ++i) {{
    cands[static_cast<std::size_t>(i)].bbox_xyxy = Eigen::Vector4d(0.0, 0.0, 1.0, 1.0);
    cands[static_cast<std::size_t>(i)].score = scores[i];
    cands[static_cast<std::size_t>(i)].class_id = "pallet";
    cands[static_cast<std::size_t>(i)].area_px = areas[i];
    cands[static_cast<std::size_t>(i)].source_index = i;
  }}
{sel_block}
  return 0;
}}
"""


def ensure_iomanip(driver: str) -> str:
    if "#include <iomanip>" not in driver:
        driver = driver.replace("#include <chrono>\n", "#include <chrono>\n#include <iomanip>\n")
    return driver


def parse_kv_lines(text: str):
    data = {}
    lists = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        key = parts[0]
        if key in ("admitted", "deferred"):
            vals = []
            for p in parts[1:]:
                vals.append(int(p))
            lists[key] = vals
        elif key == "has_dimensions":
            data[key] = parts[1] if len(parts) > 1 else ""
        else:
            if len(parts) < 2:
                die("driver missing value for " + key)
            data[key] = parts[1]
    return data, lists


def compile_and_run(driver_text: str, build_dir: str) -> str:
    stub_path = os.path.join(build_dir, "stub", "vision_msgs", "msg", "detection2_d_array.hpp")
    os.makedirs(os.path.dirname(stub_path), exist_ok=True)
    with open(stub_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(VISION_STUB)

    driver_path = os.path.join(build_dir, "driver.cpp")
    with open(driver_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(driver_text)

    geo_src = os.path.join("geometry_core", "src")
    cpp_files = sorted(
        os.path.join(geo_src, name) for name in os.listdir(geo_src) if name.endswith(".cpp")
    )
    hashed_paths = list(cpp_files) + [
        os.path.join("geometry_core", "include", "geometry_core", "pipeline_v3_2.hpp"),
        os.path.join("pps_pallet_pose_cpp", "src", "detection_utils.cpp"),
        os.path.join("pps_pallet_pose_cpp", "include", "pps_pallet_pose_cpp", "detection_utils.hpp"),
    ]
    h = hashlib.sha256()
    for path in hashed_paths:
        h.update(path.encode("utf-8"))
        h.update(b"\0")
        h.update(file_sha(path))
    h.update(b"DRIVER\0")
    h.update(driver_text.encode("utf-8"))
    digest = h.hexdigest()

    hash_path = os.path.join(build_dir, "input.sha256")
    binary = os.path.join(build_dir, "scorer_c_bin")
    cached = False
    if os.path.isfile(hash_path) and os.path.isfile(binary):
        with open(hash_path, "r", encoding="utf-8") as f:
            cached = f.read().strip() == digest

    if not cached:
        includes = [
            "-I/usr/include/eigen3",
            "-I/usr/include/opencv4",
            "-I" + win_to_wsl(os.path.join("geometry_core", "include")),
            "-I" + win_to_wsl(os.path.join("pps_pallet_pose_cpp", "include")),
            "-I" + win_to_wsl(os.path.join(build_dir, "stub")),
            "-I" + win_to_wsl(geo_src),
        ]
        sources = [win_to_wsl(p) for p in cpp_files]
        sources.append(win_to_wsl(os.path.join("pps_pallet_pose_cpp", "src", "detection_utils.cpp")))
        sources.append(win_to_wsl(driver_path))
        cmd = " ".join(
            [
                "/usr/bin/g++",
                "-std=c++17",
                "-O2",
                "-DNDEBUG",
                "-fopenmp",
            ]
            + includes
            + sources
            + [
                "-lopencv_core",
                "-lopencv_imgproc",
                "-lyaml-cpp",
                "-lgomp",
                "-pthread",
                "-o",
                win_to_wsl(binary),
            ]
        )
        try:
            proc = wsl_run(cmd, timeout=150)
        except subprocess.TimeoutExpired:
            die("g++ timed out")
        if proc.returncode != 0:
            die("compile failed\n" + (proc.stderr or "") + (proc.stdout or ""))
        with open(hash_path, "w", encoding="utf-8") as f:
            f.write(digest + "\n")

    try:
        proc = wsl_run(sh_quote(binary), timeout=60)
    except subprocess.TimeoutExpired:
        die("driver timed out")
    if proc.returncode != 0:
        die("driver failed\n" + (proc.stderr or "") + (proc.stdout or ""))
    return proc.stdout


def finite_float(name: str, value) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        die(name + " is not a float")
    if not math.isfinite(out):
        die(name + " is not finite")
    return out


def main() -> None:
    have_dims, have_select = parse_headers()
    driver = ensure_iomanip(generate_driver(have_dims, have_select))
    build_dir = os.path.normpath(os.path.join(os.getcwd(), "..", "..", "eval_build", "scorer_c"))
    os.makedirs(build_dir, exist_ok=True)
    raw = compile_and_run(driver, build_dir)
    data, lists = parse_kv_lines(raw)

    if "tx" not in data or "ty" not in data or "tz" not in data:
        die("driver did not report a pose")
    tx = finite_float("tx", data["tx"])
    ty = finite_float("ty", data["ty"])
    tz = finite_float("tz", data["tz"])
    pose_error_m = math.sqrt(tx * tx + ty * ty + (tz - 2.0) ** 2)
    latency_ms = finite_float("latency_ms", data.get("latency_ms"))

    if have_dims:
        flag = data.get("has_dimensions", "")
        if flag == "skip":
            die("dimension members exist but driver skipped the fixture")
        has_dim = flag in ("1", "true", "True")
        try:
            width_m = float(data.get("width_m", "nan"))
            height_m = float(data.get("height_m", "nan"))
            depth_m = float(data.get("depth_m", "nan"))
        except ValueError:
            width_m = height_m = depth_m = float("nan")
        if (not has_dim) or not all(math.isfinite(v) for v in (width_m, height_m, depth_m)):
            dimension_error_m = 3.0
        else:
            gt_w, gt_h, gt_d = dim_ground_truth()
            dimension_error_m = abs(width_m - gt_w) + abs(height_m - gt_h) + abs(depth_m - gt_d)
    else:
        dimension_error_m = 3.0

    admitted = set(lists.get("admitted", []))
    deferred = set(lists.get("deferred", []))
    wrong_admitted = sum(1 for i in admitted if i in MUST_DEFER)
    missing_deferred = sum(1 for i in MUST_DEFER if i not in deferred)
    selection_error = float(wrong_admitted) + 0.25 * float(missing_deferred)

    pose_error_m = finite_float("pose_error_m", pose_error_m)
    latency_ms = finite_float("latency_ms", latency_ms)
    dimension_error_m = finite_float("dimension_error_m", dimension_error_m)
    selection_error = finite_float("selection_error", selection_error)
    scenario_error = finite_float(
        "scenario_error", pose_error_m + dimension_error_m + selection_error
    )

    payload = {
        "scenario_error": scenario_error,
        "pose_error_m": pose_error_m,
        "latency_ms": latency_ms,
        "dimension_error_m": dimension_error_m,
        "selection_error": selection_error,
    }
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
