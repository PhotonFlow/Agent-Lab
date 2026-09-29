import hashlib
import json
import math
import shlex
import subprocess
import sys
import time
from pathlib import Path

BUDGET_SEC = 120.0

DRIVER_CPP = r"""#include <chrono>
#include <cmath>
#include <iostream>
#include <optional>
#include <random>

#include <Eigen/Dense>
#include <opencv2/core.hpp>

#include "geometry_core/pipeline_v3_2.hpp"

int main() {
  geometry_core::RgbDepthCameraConfig camera_cfg;
  camera_cfg.rgb = geometry_core::PinholeIntrinsics{900.0, 900.0, 640.0, 480.0, 1280, 960};
  camera_cfg.depth = geometry_core::PinholeIntrinsics{450.0, 450.0, 320.0, 240.0, 640, 480};
  camera_cfg.R_dr = Eigen::Matrix3d::Identity();
  camera_cfg.t_dr = Eigen::Vector3d::Zero();
  camera_cfg.depth_scale = 0.001;

  cv::Mat depth(480, 640, CV_32FC1, cv::Scalar(2.0f));
  Eigen::Vector4d bbox(340.0, 440.0, 940.0, 520.0);

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
  const double pose_error_m = std::sqrt(tx * tx + ty * ty + (tz - 2.0) * (tz - 2.0));
  std::cout << pose_error_m << " " << latency_ms << "\n";
  return 0;
}
"""


def windows_to_wsl(path: Path) -> str:
    resolved = path.resolve()
    text = str(resolved)
    if len(text) >= 2 and text[1] == ":":
        drive = text[0].lower()
        rest = text[2:].replace("\\", "/").lstrip("/")
        return f"/mnt/{drive}/{rest}"
    return resolved.as_posix()


def fail(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def remaining(t0: float) -> float:
    left = BUDGET_SEC - (time.monotonic() - t0)
    if left <= 0:
        fail("eval timeout budget exhausted")
    return left


def wsl_run(argv, timeout_sec: float) -> subprocess.CompletedProcess:
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


def fingerprint(package: Path, driver_text: str) -> str:
    digest = hashlib.sha256()
    paths = sorted(package.joinpath("src").glob("*.cpp"))
    paths.extend(sorted(package.joinpath("include").rglob("*.hpp")))
    for path in paths:
        digest.update(path.relative_to(package).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    digest.update(b"DRIVER\0")
    digest.update(driver_text.encode("utf-8"))
    return digest.hexdigest()


def parse_driver_stdout(raw: str) -> tuple[float, float]:
    for line in reversed(raw.splitlines()):
        parts = line.strip().split()
        if len(parts) != 2:
            continue
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            continue
    fail("driver stdout missing pose_error_m latency_ms line")


def main() -> None:
    t0 = time.monotonic()
    package = Path.cwd()
    cache = package.parents[1] / "eval_build" / "scorer_a"
    cache.mkdir(parents=True, exist_ok=True)

    driver_src = cache / "driver.cpp"
    driver_bin = cache / "driver"
    hash_path = cache / "inputs.sha256"
    current_hash = fingerprint(package, DRIVER_CPP)

    need_rebuild = True
    if driver_bin.is_file() and hash_path.is_file():
        try:
            need_rebuild = hash_path.read_text(encoding="utf-8").strip() != current_hash
        except OSError:
            need_rebuild = True

    if need_rebuild:
        driver_src.write_text(DRIVER_CPP, encoding="utf-8")
        sources = [windows_to_wsl(p) for p in sorted(package.joinpath("src").glob("*.cpp"))]
        compile_cmd = [
            "/usr/bin/g++",
            "-std=c++17",
            "-O2",
            "-DNDEBUG",
            "-fopenmp",
            "-I" + windows_to_wsl(package / "include"),
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
        if stderr_text:
            print(stderr_text, file=sys.stderr)
        fail("estimator did not return ok")

    pose_error_m, latency_ms = parse_driver_stdout(stdout_text)
    if not math.isfinite(pose_error_m) or not math.isfinite(latency_ms):
        fail("non-finite pose_error_m or latency_ms")

    sys.stdout.write(
        json.dumps(
            {"pose_error_m": pose_error_m, "latency_ms": latency_ms},
            separators=(",", ":"),
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
