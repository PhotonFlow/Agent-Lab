import hashlib
import json
import math
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

BUDGET_SEC = 150.0

STUB_HEADER = """#pragma once

#include <string>
#include <vector>

namespace vision_msgs {
namespace msg {

struct Point2 {
  double x = 0.0;
  double y = 0.0;
};

struct Pose2D {
  Point2 position;
};

struct BoundingBox2D {
  Pose2D center;
  double size_x = 0.0;
  double size_y = 0.0;
};

struct ObjectHypothesis {
  std::string class_id;
  double score = 0.0;
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

POSE_AND_SEL_PREFIX = r"""#include <chrono>
#include <cmath>
#include <iostream>
#include <optional>
#include <random>
#include <string>
#include <vector>

#include <Eigen/Dense>
#include <opencv2/core.hpp>

#include "geometry_core/pipeline_v3_2.hpp"
#include "pps_pallet_pose_cpp/detection_utils.hpp"

namespace {

bool is_must_defer(int source_index) {
  return source_index == 0 || source_index == 3 || source_index == 4;
}

std::vector<pps_pallet_pose_cpp::DetectionCandidate> make_candidates() {
  const double scores[5] = {0.99, 0.70, 0.60, 0.50, 0.40};
  const double areas[5] = {2000.0, 50000.0, 40000.0, 30000.0, 1000.0};
  std::vector<pps_pallet_pose_cpp::DetectionCandidate> candidates;
  candidates.reserve(5);
  for (int i = 0; i < 5; ++i) {
    pps_pallet_pose_cpp::DetectionCandidate c;
    c.bbox_xyxy = Eigen::Vector4d(0.0, 0.0, 10.0, 10.0);
    c.score = scores[i];
    c.class_id = "pallet";
    c.area_px = areas[i];
    c.source_index = i;
    candidates.push_back(c);
  }
  return candidates;
}

double selection_error_from(const std::vector<int>& admitted,
                            const std::vector<int>& deferred) {
  int bad_admitted = 0;
  for (int idx : admitted) {
    if (is_must_defer(idx)) {
      ++bad_admitted;
    }
  }
  int missing_deferred = 0;
  const int must_defer[3] = {0, 3, 4};
  for (int want : must_defer) {
    bool found = false;
    for (int idx : deferred) {
      if (idx == want) {
        found = true;
        break;
      }
    }
    if (!found) {
      ++missing_deferred;
    }
  }
  return static_cast<double>(bad_admitted) + 0.25 * static_cast<double>(missing_deferred);
}

}  // namespace

int main() {
  geometry_core::RgbDepthCameraConfig camera_cfg;
  camera_cfg.rgb = geometry_core::PinholeIntrinsics{900.0, 900.0, 640.0, 480.0, 1280, 960};
  camera_cfg.depth = geometry_core::PinholeIntrinsics{450.0, 450.0, 320.0, 240.0, 640, 480};
  camera_cfg.R_dr = Eigen::Matrix3d::Identity();
  camera_cfg.t_dr = Eigen::Vector3d::Zero();
  camera_cfg.depth_scale = 0.001;

  cv::Mat depth(480, 640, CV_32FC1, cv::Scalar(2.0f));
  const Eigen::Vector4d bbox(340.0, 440.0, 940.0, 520.0);

  geometry_core::Stage2Config cfg;
  cfg.min_face_points = 100;
  geometry_core::EstimatePoseParams params;
  std::mt19937_64 rng(0);

  const auto t0 = std::chrono::steady_clock::now();
  const auto outcome = geometry_core::estimate_pose_chamfer_v3_2(
      bbox, depth, camera_cfg, cfg, params, std::nullopt, rng);
  const auto t1 = std::chrono::steady_clock::now();
  const double latency_ms =
      std::chrono::duration<double, std::milli>(t1 - t0).count();

  if (!outcome.ok) {
    std::cerr << outcome.failure.failure_reason << std::endl;
    return 1;
  }

  const double tx = outcome.pose.tx;
  const double ty = outcome.pose.ty;
  const double tz = outcome.pose.tz;
  const double pose_error_m =
      std::sqrt(tx * tx + ty * ty + (tz - 2.0) * (tz - 2.0));
"""

DIM_BLOCK = r"""
  double dimension_error_m = 3.0;
  {
    geometry_core::RgbDepthCameraConfig dim_cam;
    dim_cam.rgb = geometry_core::PinholeIntrinsics{450.0, 450.0, 320.0, 240.0, 640, 480};
    dim_cam.depth = geometry_core::PinholeIntrinsics{450.0, 450.0, 320.0, 240.0, 640, 480};
    dim_cam.R_dr = Eigen::Matrix3d::Identity();
    dim_cam.t_dr = Eigen::Vector3d::Zero();
    dim_cam.depth_scale = 0.001;

    const int u0 = 230;
    const int u1 = 410;
    const int v0 = 168;
    const int v1 = 312;
    const double z_face = 2.5;
    cv::Mat dim_depth = cv::Mat::zeros(480, 640, CV_32FC1);
    for (int v = v0; v <= v1; ++v) {
      for (int u = u0; u <= u1; ++u) {
        dim_depth.at<float>(v, u) = static_cast<float>(z_face);
      }
    }
    const Eigen::Vector4d dim_bbox(224.0, 162.0, 416.0, 318.0);
    geometry_core::Stage2Config dim_cfg;
    dim_cfg.min_face_points = 100;
    geometry_core::EstimatePoseParams dim_params;
    std::mt19937_64 dim_rng(0);
    const auto dim_out = geometry_core::estimate_pose_chamfer_v3_2(
        dim_bbox, dim_depth, dim_cam, dim_cfg, dim_params, std::nullopt, dim_rng);
    if (dim_out.has_dimensions && std::isfinite(dim_out.width_m) &&
        std::isfinite(dim_out.height_m) && std::isfinite(dim_out.depth_m)) {
      const double fx = 450.0;
      const double fy = 450.0;
      const double cx = 320.0;
      const double cy = 240.0;
      const double x0 = ((static_cast<double>(u0) + 0.5) - cx) / fx * z_face;
      const double x1 = ((static_cast<double>(u1) + 0.5) - cx) / fx * z_face;
      const double y0 = ((static_cast<double>(v0) + 0.5) - cy) / fy * z_face;
      const double y1 = ((static_cast<double>(v1) + 0.5) - cy) / fy * z_face;
      const double gt_w = x1 - x0;
      const double gt_h = y1 - y0;
      const double gt_d = z_face;
      dimension_error_m = std::abs(dim_out.width_m - gt_w) +
                          std::abs(dim_out.height_m - gt_h) +
                          std::abs(dim_out.depth_m - gt_d);
    } else {
      dimension_error_m = 3.0;
    }
  }
"""

DIM_FALLBACK = r"""
  const double dimension_error_m = 3.0;
"""

SEL_STAGE2 = r"""
  const auto candidates = make_candidates();
  const auto admission = pps_pallet_pose_cpp::select_stage2_subset(
      candidates, "largest_area", static_cast<std::size_t>(2));
  std::vector<int> admitted;
  std::vector<int> deferred;
  admitted.reserve(admission.admitted.size());
  deferred.reserve(admission.deferred.size());
  for (const auto& c : admission.admitted) {
    admitted.push_back(c.source_index);
  }
  for (const auto& c : admission.deferred) {
    deferred.push_back(c.source_index);
  }
  const double selection_error = selection_error_from(admitted, deferred);
"""

SEL_LEGACY = r"""
  const auto candidates = make_candidates();
  const auto chosen =
      pps_pallet_pose_cpp::select_detection(candidates, "highest_confidence");
  if (!chosen.has_value()) {
    std::cerr << "select_detection returned empty" << std::endl;
    return 1;
  }
  const std::vector<int> admitted{chosen->source_index};
  const std::vector<int> deferred;
  const double selection_error = selection_error_from(admitted, deferred);
"""

DRIVER_SUFFIX = r"""
  if (!std::isfinite(pose_error_m) || !std::isfinite(latency_ms) ||
      !std::isfinite(dimension_error_m) || !std::isfinite(selection_error)) {
    std::cerr << "non-finite metric" << std::endl;
    return 1;
  }

  std::cout.precision(17);
  std::cout << pose_error_m << " " << latency_ms << " " << dimension_error_m << " "
            << selection_error << "\n";
  return 0;
}
"""


def fail(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*?$", "", text, flags=re.M)
    return text


def extract_struct(text: str, name: str) -> str | None:
    match = re.search(r"struct\s+" + re.escape(name) + r"\s*\{", text)
    if match is None:
        return None
    start = match.end() - 1
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def has_ident(text: str, name: str) -> bool:
    return re.search(r"\b" + re.escape(name) + r"\b", text) is not None


def outcome_has_dimension_members(header: str) -> bool:
    body = extract_struct(header, "EstimatePoseOutcome")
    if body is None:
        return False
    return all(
        has_ident(body, field)
        for field in ("has_dimensions", "width_m", "height_m", "depth_m")
    )


def selection_uses_stage2(header: str) -> bool:
    if not has_ident(header, "select_stage2_subset"):
        return False
    body = extract_struct(header, "Stage2Admission")
    if body is None:
        fail("select_stage2_subset is declared but Stage2Admission is missing")
    if not has_ident(body, "admitted") or not has_ident(body, "deferred"):
        fail("Stage2Admission must have vectors named admitted and deferred")
    return True


def make_driver(has_dims: bool, use_stage2: bool) -> str:
    dim = DIM_BLOCK if has_dims else DIM_FALLBACK
    sel = SEL_STAGE2 if use_stage2 else SEL_LEGACY
    return POSE_AND_SEL_PREFIX + dim + sel + DRIVER_SUFFIX


def windows_to_wsl(path: Path) -> str:
    resolved = path.resolve()
    text = str(resolved)
    if len(text) >= 2 and text[1] == ":":
        drive = text[0].lower()
        rest = text[2:].replace("\\", "/").lstrip("/")
        return f"/mnt/{drive}/{rest}"
    return resolved.as_posix()


def remaining(t0: float) -> float:
    left = BUDGET_SEC - (time.monotonic() - t0)
    if left <= 1.0:
        fail("eval timeout budget exhausted")
    return left


def wsl_run(argv: list[str], timeout_sec: float) -> subprocess.CompletedProcess:
    cmdline = " ".join(shlex.quote(part) for part in argv)
    try:
        return subprocess.run(
            ["wsl.exe", "-d", "Ubuntu", "-e", "bash", "-lc", cmdline],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_sec,
            check=False,
        )
    except FileNotFoundError:
        fail("wsl.exe not found")
    except subprocess.TimeoutExpired:
        fail("eval timeout budget exhausted")


def decode(blob: bytes) -> str:
    return blob.decode("utf-8", errors="replace")


def fingerprint(paths: list[Path], driver_text: str) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    digest.update(b"DRIVER\0")
    digest.update(driver_text.encode("utf-8"))
    return digest.hexdigest()


def parse_driver_stdout(raw: str) -> tuple[float, float, float, float]:
    for line in reversed(raw.splitlines()):
        parts = line.strip().split()
        if len(parts) != 4:
            continue
        try:
            values = tuple(float(p) for p in parts)
        except ValueError:
            continue
        if all(math.isfinite(v) for v in values):
            return values  # type: ignore[return-value]
    fail("driver stdout missing pose latency dimension selection line")


def main() -> None:
    t0 = time.monotonic()
    src = Path.cwd()
    pipeline_hpp = src / "geometry_core" / "include" / "geometry_core" / "pipeline_v3_2.hpp"
    detection_hpp = (
        src / "pps_pallet_pose_cpp" / "include" / "pps_pallet_pose_cpp" / "detection_utils.hpp"
    )
    detection_cpp = src / "pps_pallet_pose_cpp" / "src" / "detection_utils.cpp"
    geo_cpp = sorted((src / "geometry_core" / "src").glob("*.cpp"))
    if not pipeline_hpp.is_file() or not detection_hpp.is_file() or not geo_cpp:
        fail("expected geometry_core and pps_pallet_pose_cpp under cwd")
    if not detection_cpp.is_file():
        fail("missing pps_pallet_pose_cpp/src/detection_utils.cpp")

    pipeline_text = strip_comments(pipeline_hpp.read_text(encoding="utf-8"))
    detection_text = strip_comments(detection_hpp.read_text(encoding="utf-8"))
    has_dims = outcome_has_dimension_members(pipeline_text)
    use_stage2 = selection_uses_stage2(detection_text)
    driver_text = make_driver(has_dims, use_stage2)

    cache = src.resolve().parent.parent / "eval_build" / "scorer_a"
    cache.mkdir(parents=True, exist_ok=True)
    stub_dir = cache / "stub"
    stub_header = stub_dir / "vision_msgs" / "msg" / "detection2_d_array.hpp"
    stub_header.parent.mkdir(parents=True, exist_ok=True)
    stub_header.write_text(STUB_HEADER, encoding="utf-8")

    driver_src = cache / "driver.cpp"
    driver_bin = cache / "driver"
    hash_path = cache / "inputs.sha256"

    hash_inputs = list(geo_cpp) + [pipeline_hpp, detection_cpp, detection_hpp]
    current_hash = fingerprint(hash_inputs, driver_text)

    need_rebuild = True
    if driver_bin.is_file() and hash_path.is_file():
        try:
            need_rebuild = hash_path.read_text(encoding="utf-8").strip() != current_hash
        except OSError:
            need_rebuild = True

    if need_rebuild:
        driver_src.write_text(driver_text, encoding="utf-8")
        sources = [windows_to_wsl(p) for p in geo_cpp]
        sources.append(windows_to_wsl(detection_cpp))
        compile_cmd = [
            "/usr/bin/g++",
            "-std=c++17",
            "-O2",
            "-DNDEBUG",
            "-fopenmp",
            "-I" + windows_to_wsl(src / "geometry_core" / "include"),
            "-I" + windows_to_wsl(src / "pps_pallet_pose_cpp" / "include"),
            "-I" + windows_to_wsl(stub_dir),
            "-I/usr/include/eigen3",
            "-I/usr/include/opencv4",
            *sources,
            windows_to_wsl(driver_src),
            "-lopencv_core",
            "-lopencv_imgproc",
            "-lyaml-cpp",
            "-lgomp",
            "-pthread",
            "-o",
            windows_to_wsl(driver_bin),
        ]
        compiled = wsl_run(compile_cmd, remaining(t0))
        if compiled.returncode != 0:
            err = decode(compiled.stderr).strip() or decode(compiled.stdout).strip()
            fail(err or "g++ failed")
        hash_path.write_text(current_hash + "\n", encoding="utf-8")

    ran = wsl_run([windows_to_wsl(driver_bin)], remaining(t0))
    stdout_text = decode(ran.stdout)
    stderr_text = decode(ran.stderr).strip()
    if ran.returncode != 0:
        fail(stderr_text or "estimator did not return ok")

    pose_error_m, latency_ms, dimension_error_m, selection_error = parse_driver_stdout(
        stdout_text
    )
    scenario_error = pose_error_m + dimension_error_m + selection_error
    payload = {
        "scenario_error": scenario_error,
        "pose_error_m": pose_error_m,
        "latency_ms": latency_ms,
        "dimension_error_m": dimension_error_m,
        "selection_error": selection_error,
    }
    if not all(math.isfinite(v) for v in payload.values()):
        fail("non-finite metric")
    sys.stdout.write(json.dumps(payload) + "\n")


if __name__ == "__main__":
    main()
