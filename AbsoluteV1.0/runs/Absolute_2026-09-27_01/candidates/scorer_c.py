#!/usr/bin/env python3
"""Absolute candidate C scorer: mean translation error over three depths."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

DRIVER_SRC = r"""#include <chrono>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <optional>
#include <random>

#include "geometry_core/pipeline_v3_2.hpp"

int main() {
  using geometry_core::EstimatePoseParams;
  using geometry_core::PinholeIntrinsics;
  using geometry_core::RgbDepthCameraConfig;
  using geometry_core::Stage2Config;
  using geometry_core::estimate_pose_chamfer_v3_2;

  RgbDepthCameraConfig camera_cfg;
  camera_cfg.rgb = PinholeIntrinsics{900.0, 900.0, 640.0, 480.0, 1280, 960};
  camera_cfg.depth = PinholeIntrinsics{450.0, 450.0, 320.0, 240.0, 640, 480};
  camera_cfg.R_dr = Eigen::Matrix3d::Identity();
  camera_cfg.t_dr = Eigen::Vector3d::Zero();
  camera_cfg.depth_scale = 0.001;

  Stage2Config cfg;
  cfg.min_face_points = 100;
  EstimatePoseParams params;

  const Eigen::Vector4d bbox(340.0, 440.0, 940.0, 520.0);
  const double depths[3] = {1.5, 2.0, 2.5};

  double err_sum = 0.0;
  double ms_sum = 0.0;
  for (double z : depths) {
    cv::Mat depth(480, 640, CV_32FC1);
    depth.setTo(static_cast<float>(z));
    std::mt19937_64 rng(0);

    const auto t0 = std::chrono::steady_clock::now();
    const auto outcome = estimate_pose_chamfer_v3_2(
        bbox, depth, camera_cfg, cfg, params, std::nullopt, rng);
    const auto t1 = std::chrono::steady_clock::now();

    if (!outcome.ok) {
      std::cerr << outcome.failure.failure_reason << std::endl;
      return 1;
    }

    const double dtx = outcome.pose.tx;
    const double dty = outcome.pose.ty;
    const double dtz = outcome.pose.tz - z;
    err_sum += std::sqrt(dtx * dtx + dty * dty + dtz * dtz);
    ms_sum += std::chrono::duration<double, std::milli>(t1 - t0).count();
  }

  const double pose_error_m = err_sum / 3.0;
  const double latency_ms = ms_sum / 3.0;
  std::cout << std::setprecision(17) << pose_error_m << " " << latency_ms << "\n";
  return 0;
}
"""


def _die(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def to_wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive
    if len(drive) == 2 and drive[1] == ":":
        rest = resolved.as_posix()[2:]
        if not rest.startswith("/"):
            rest = "/" + rest
        return f"/mnt/{drive[0].lower()}{rest}"
    return resolved.as_posix()


def source_hash(package: Path, driver_src: str) -> str:
    digest = hashlib.sha256()
    files = sorted(package.joinpath("src").glob("*.cpp"))
    files.extend(sorted(package.joinpath("include").rglob("*.hpp")))
    for item in files:
        rel = item.relative_to(package).as_posix().encode("utf-8")
        digest.update(rel)
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    digest.update(b"DRIVER\0")
    digest.update(driver_src.encode("utf-8"))
    return digest.hexdigest()


def remaining_timeout(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0.0:
        _die("eval timeout")
    return left


def run_wsl(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        _die("eval timeout")
    except FileNotFoundError:
        _die("wsl is not available")


def parse_driver_stdout(text: str) -> tuple[float, float]:
    parsed: tuple[float, float] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("wsl:"):
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            parsed = (float(parts[0]), float(parts[1]))
        except ValueError:
            continue
    if parsed is None:
        _die("driver stdout missing pose_error_m latency_ms")
    return parsed


def main() -> None:
    deadline = time.monotonic() + 120.0
    package = Path.cwd()
    cache = package.parents[1] / "eval_build" / "scorer_c"
    cache.mkdir(parents=True, exist_ok=True)

    sources = sorted(package.joinpath("src").glob("*.cpp"))
    if not sources:
        _die("no package src/*.cpp files")

    digest = source_hash(package, DRIVER_SRC)
    driver_cpp = cache / "driver.cpp"
    binary = cache / "driver"
    hash_path = cache / "source.sha256"
    driver_cpp.write_text(DRIVER_SRC, encoding="utf-8", newline="\n")

    need_rebuild = (
        not binary.is_file()
        or not hash_path.is_file()
        or hash_path.read_text(encoding="utf-8").strip() != digest
    )
    if need_rebuild:
        compile_cmd = [
            "wsl",
            "-e",
            "/usr/bin/g++",
            "-std=c++17",
            "-O2",
            "-DNDEBUG",
            "-fopenmp",
            f"-I{to_wsl_path(package / 'include')}",
            "-I/usr/include/eigen3",
            "-I/usr/include/opencv4",
            *[to_wsl_path(src) for src in sources],
            to_wsl_path(driver_cpp),
            "-lopencv_core",
            "-lopencv_imgproc",
            "-lyaml-cpp",
            "-lgomp",
            "-pthread",
            "-o",
            to_wsl_path(binary),
        ]
        compiled = run_wsl(compile_cmd, remaining_timeout(deadline))
        if compiled.stderr:
            print(compiled.stderr, file=sys.stderr, end="")
        if compiled.returncode != 0:
            if compiled.stdout:
                print(compiled.stdout, file=sys.stderr, end="")
            _die("g++ failed")
        chmod = run_wsl(
            ["wsl", "-e", "/bin/chmod", "+x", to_wsl_path(binary)],
            remaining_timeout(deadline),
        )
        if chmod.returncode != 0:
            _die("chmod failed")
        hash_path.write_text(digest + "\n", encoding="utf-8", newline="\n")

    ran = run_wsl(["wsl", "-e", to_wsl_path(binary)], remaining_timeout(deadline))
    if ran.stderr:
        print(ran.stderr, file=sys.stderr, end="")
    if ran.returncode != 0:
        _die("estimator call failed" if not ran.stderr.strip() else "driver failed")

    pose_error_m, latency_ms = parse_driver_stdout(ran.stdout)
    if not (math.isfinite(pose_error_m) and math.isfinite(latency_ms)):
        _die("non-finite metric")

    payload = json.dumps(
        {"pose_error_m": pose_error_m, "latency_ms": latency_ms},
        separators=(",", ":"),
    )
    sys.stdout.buffer.write(payload.encode("ascii") + b"\n")
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
