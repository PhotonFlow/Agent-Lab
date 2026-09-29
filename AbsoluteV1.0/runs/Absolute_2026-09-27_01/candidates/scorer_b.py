import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

TIMEOUT_SEC = 120.0

DRIVER_SRC = r"""#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <optional>
#include <random>
#include <vector>

#include "geometry_core/pipeline_v3_2.hpp"

namespace {

double pose_error_m(const geometry_core::PoseResult& pose) {
  const double dtx = pose.tx;
  const double dty = pose.ty;
  const double dtz = pose.tz - 2.0;
  const double dyaw = 0.6 * pose.yaw_rad;
  return std::sqrt(dtx * dtx + dty * dty + dtz * dtz + dyaw * dyaw);
}

double median5(std::vector<double> values) {
  std::sort(values.begin(), values.end());
  return values[2];
}

}  // namespace

int main() {
  geometry_core::RgbDepthCameraConfig camera_cfg;
  camera_cfg.rgb =
      geometry_core::PinholeIntrinsics{900.0, 900.0, 640.0, 480.0, 1280, 960};
  camera_cfg.depth =
      geometry_core::PinholeIntrinsics{450.0, 450.0, 320.0, 240.0, 640, 480};
  camera_cfg.R_dr = Eigen::Matrix3d::Identity();
  camera_cfg.t_dr = Eigen::Vector3d::Zero();
  camera_cfg.depth_scale = 0.001;

  cv::Mat depth(480, 640, CV_32FC1, cv::Scalar(2.0f));
  const Eigen::Vector4d bbox(340.0, 440.0, 940.0, 520.0);

  geometry_core::Stage2Config cfg;
  cfg.min_face_points = 100;

  geometry_core::EstimatePoseParams params;

  const auto call_once = [&]() {
    std::mt19937_64 rng(0);
    return geometry_core::estimate_pose_chamfer_v3_2(
        bbox, depth, camera_cfg, cfg, params, std::nullopt, rng);
  };

  {
    const auto warmup = call_once();
    if (!warmup.ok) {
      std::cerr << warmup.failure.failure_reason << std::endl;
      return 1;
    }
  }

  std::vector<double> errors;
  std::vector<double> latencies;
  errors.reserve(5);
  latencies.reserve(5);

  for (int i = 0; i < 5; ++i) {
    const auto t0 = std::chrono::steady_clock::now();
    const auto outcome = call_once();
    const auto t1 = std::chrono::steady_clock::now();
    if (!outcome.ok) {
      std::cerr << outcome.failure.failure_reason << std::endl;
      return 1;
    }
    const double ms =
        std::chrono::duration<double, std::milli>(t1 - t0).count();
    errors.push_back(pose_error_m(outcome.pose));
    latencies.push_back(ms);
  }

  const double pose_error = median5(errors);
  const double latency = median5(latencies);
  if (!std::isfinite(pose_error) || !std::isfinite(latency)) {
    std::cerr << "non-finite metric" << std::endl;
    return 1;
  }

  std::cout.precision(17);
  std::cout << pose_error << " " << latency << "\n";
  return 0;
}
"""


def die(message: str, code: int = 1) -> None:
    sys.stderr.write(message if message.endswith("\n") else message + "\n")
    raise SystemExit(code)


def to_wsl(path: Path) -> str:
    resolved = path.resolve()
    text = str(resolved)
    if len(text) >= 2 and text[1] == ":":
        drive = text[0].lower()
        rest = text[2:].replace("\\", "/")
        if not rest.startswith("/"):
            rest = "/" + rest
        return f"/mnt/{drive}{rest}"
    return text.replace("\\", "/")


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def hashed_inputs(package: Path, driver_src: str) -> bytes:
    digest = hashlib.sha256()
    tracked = []
    tracked.extend(sorted(package.glob("src/*.cpp")))
    tracked.extend(sorted(package.glob("include/**/*.hpp")))
    for item in tracked:
        rel = item.relative_to(package).as_posix().encode("utf-8")
        digest.update(rel)
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    digest.update(b"driver.cpp\0")
    digest.update(driver_src.encode("utf-8"))
    return digest.digest()


def run_wsl(command: str, timeout: float) -> subprocess.CompletedProcess:
    try:
        completed = subprocess.run(
            ["wsl", "-e", "bash", "-lc", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except FileNotFoundError:
        die("wsl is not available")
    except subprocess.TimeoutExpired:
        die("eval timed out")
    if completed.stderr:
        sys.stderr.buffer.write(completed.stderr)
        if not completed.stderr.endswith(b"\n"):
            sys.stderr.buffer.write(b"\n")
        sys.stderr.buffer.flush()
    return completed


def main() -> None:
    package = Path.cwd()
    cache = package.parents[1] / "eval_build" / "scorer_b"
    cache.mkdir(parents=True, exist_ok=True)

    driver_cpp = cache / "driver.cpp"
    driver_bin = cache / "driver"
    driver_out = cache / "driver.stdout"
    hash_path = cache / "source.sha256"
    expected = hashed_inputs(package, DRIVER_SRC).hex()
    have_hash = hash_path.is_file() and hash_path.read_text(encoding="utf-8").strip() == expected
    need_rebuild = (not driver_bin.is_file()) or (not have_hash)

    deadline = TIMEOUT_SEC
    import time

    started = time.monotonic()

    if need_rebuild:
        driver_cpp.write_text(DRIVER_SRC, encoding="utf-8", newline="\n")
        sources = sorted(package.glob("src/*.cpp"))
        if not sources:
            die("no package src/*.cpp files")
        compile_cmd = " ".join(
            [
                "g++",
                "-std=c++17",
                "-O2",
                "-DNDEBUG",
                "-fopenmp",
                "-I" + to_wsl(package / "include"),
                "-I/usr/include/eigen3",
                "-I/usr/include/opencv4",
            ]
            + [sh_quote(to_wsl(src)) for src in sources]
            + [
                sh_quote(to_wsl(driver_cpp)),
                "-lopencv_core",
                "-lopencv_imgproc",
                "-lyaml-cpp",
                "-lgomp",
                "-pthread",
                "-o",
                sh_quote(to_wsl(driver_bin)),
            ]
        )
        remaining = deadline - (time.monotonic() - started)
        if remaining <= 1.0:
            die("eval timed out")
        compiled = run_wsl(compile_cmd, remaining)
        if compiled.returncode != 0:
            die("g++ failed", compiled.returncode if compiled.returncode else 1)
        hash_path.write_text(expected + "\n", encoding="utf-8")

    remaining = deadline - (time.monotonic() - started)
    if remaining <= 1.0:
        die("eval timed out")

    run_cmd = (
        sh_quote(to_wsl(driver_bin))
        + " > "
        + sh_quote(to_wsl(driver_out))
    )
    ran = run_wsl(run_cmd, remaining)
    if ran.returncode != 0:
        die("driver failed", ran.returncode if ran.returncode else 1)

    try:
        raw = driver_out.read_text(encoding="utf-8")
    except OSError as exc:
        die(f"missing driver stdout: {exc}")

    line = None
    for candidate in raw.splitlines():
        stripped = candidate.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) != 2:
            continue
        try:
            pose_error_m = float(parts[0])
            latency_ms = float(parts[1])
        except ValueError:
            continue
        line = (pose_error_m, latency_ms)

    if line is None:
        die("driver stdout was not 'pose_error_m latency_ms'")

    pose_error_m, latency_ms = line
    if not math.isfinite(pose_error_m) or not math.isfinite(latency_ms):
        die("non-finite metric")

    sys.stdout.write(
        json.dumps(
            {"pose_error_m": pose_error_m, "latency_ms": latency_ms},
            separators=(",", ":"),
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
