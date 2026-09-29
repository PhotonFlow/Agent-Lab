"""Score the candidate stage-2 pose on the analytical fronto-parallel scene.

Working directory is the candidate package root (the directory that contains
geometry_core). Stdout is one JSON object.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import oracle

KEYS = ("ok", "tx", "ty", "tz", "yaw", "latency_ms")
CACHE = Path(tempfile.gettempdir()) / "absolute-pose-bench-cache"


def wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive[0].lower()
    tail = resolved.as_posix()[2:]
    return f"/mnt/{drive}{tail}"


def parse_fields(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[0] in KEYS and parts[0] not in found:
            found[parts[0]] = parts[1].strip()
    missing = [key for key in KEYS if key not in found]
    if missing:
        raise RuntimeError(f"harness stdout missing {missing}: {text[-1500:]}")
    return found


def main() -> int:
    package = Path.cwd()
    geom = package / "geometry_core"
    if not (geom / "src" / "pipeline_v3_2.cpp").is_file():
        print("geometry_core sources not found in the working directory", file=sys.stderr)
        return 1

    here = Path(__file__).resolve().parent
    header_dir = CACHE / "header"
    header_dir.mkdir(parents=True, exist_ok=True)
    (header_dir / "bench_scene.hpp").write_text(oracle.scene_header(), encoding="utf-8", newline="\n")

    command = [
        "wsl.exe",
        "-e",
        "bash",
        wsl_path(here / "build_and_run.sh"),
        wsl_path(geom),
        wsl_path(here / "harness.cpp"),
        wsl_path(CACHE),
        wsl_path(header_dir),
    ]
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        command, capture_output=True, env=env, encoding="utf-8", errors="replace"
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr or "")
        sys.stderr.write(completed.stdout or "")
        return completed.returncode or 1

    fields = parse_fields(completed.stdout or "")
    ok = fields["ok"] == "1"
    error = oracle.pose_error_m(
        float(fields["tx"]),
        float(fields["ty"]),
        float(fields["tz"]),
        float(fields["yaw"]),
        ok,
    )
    latency_ms = float(fields["latency_ms"])
    if latency_ms < 0.0:
        print("negative latency", file=sys.stderr)
        return 1
    payload = {
        "pose_error_m": error,
        "latency_ms": latency_ms,
        "_cases": [oracle.CASE_ID],
    }
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - surface the compile or parse failure
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
