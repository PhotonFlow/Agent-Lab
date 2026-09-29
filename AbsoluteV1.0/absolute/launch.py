"""Launch one fresh worker process. The parent keeps the scorer authority."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

WORKER_MODEL = "grok-4.7-xhigh"


class LaunchError(RuntimeError):
    pass


def agent_argv(brief_path: str, role: str, which: Callable[[str], str | None] | None = None) -> list[str]:
    """Command line for one Cursor agent. The brief file holds the role prompt."""
    finder = which or shutil.which
    prompt = (
        f"Read the Absolute worker brief at {brief_path} and do only the {role} role. "
        "Follow the prompt field in that brief. Do not start another evolve command. Do not score the run."
    )
    tool_args = [
        "-p", "--force", "--model", os.environ.get("ABSOLUTE_MODEL") or WORKER_MODEL,
        "--output-format", "stream-json", "--stream-partial-output", prompt,
    ]
    agent = finder("agent")
    if agent:
        return [agent, *tool_args]
    cursor = finder("cursor") or finder("cursor.cmd")
    if not cursor:
        raise LaunchError("Cursor agent CLI is not installed")
    return [cursor, "agent", *tool_args]


_LOG_LOCK = threading.Lock()


def _append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")


def report(run_dir: Path, event: str, **fields) -> None:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {"time": timestamp, "event": event, **fields}
    _append_jsonl(run_dir / "events.jsonl", payload)
    detail = " ".join(f"{key}={value}" for key, value in fields.items())
    with _LOG_LOCK:
        print(f"[{timestamp}] {event} {detail}", file=sys.stderr, flush=True)


def _positive_setting(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError as exc:
        raise LaunchError(f"{name} must be finite and positive") from exc
    if not math.isfinite(value) or value <= 0:
        raise LaunchError(f"{name} must be finite and positive")
    return value


def _terminate(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        except OSError:
            pass
    else:
        import signal

        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.poll() is None:
        proc.kill()
    proc.wait()


def run_process(command: list[str], cwd: Path, timeout: float, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(
        command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except BaseException:
        _terminate(proc)
        raise
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


def _run_command(cmd: list[str], brief: dict, cwd: str) -> None:
    log_path = Path(brief["brief_path"]).with_suffix(".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    run_dir = Path(brief["run"])
    timeout = _positive_setting("ABSOLUTE_WORKER_TIMEOUT_SEC", 1800)
    heartbeat = _positive_setting("ABSOLUTE_HEARTBEAT_SEC", 30)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    identity = {"cycle": brief.get("cycle"), "role": brief["role"], "index": brief.get("index")}
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )
        pid = proc.pid
        try:
            report(run_dir, "worker_started", **identity, pid=pid, log=str(log_path))
            while True:
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    report(run_dir, "worker_timeout", **identity, pid=pid, timeout_sec=timeout)
                    raise LaunchError(f"{brief['role']} exceeded {timeout:g}s; see {log_path}")
                try:
                    code = proc.wait(timeout=min(heartbeat, remaining))
                    break
                except subprocess.TimeoutExpired:
                    report(
                        run_dir, "worker_heartbeat", **identity, pid=pid,
                        elapsed_sec=round(time.monotonic() - started, 1),
                        log_bytes=log_path.stat().st_size,
                    )
        except BaseException:
            _terminate(proc)
            raise
    _append_jsonl(
        Path(brief["run"]) / "launch_log.jsonl",
        {
            "cycle": brief.get("cycle"),
            "index": brief.get("index"),
            "pid": pid,
            "returncode": code,
            "role": brief["role"],
        },
    )
    report(
        run_dir, "worker_finished", **identity, pid=pid, returncode=code,
        elapsed_sec=round(time.monotonic() - started, 1), log=str(log_path),
    )
    if code != 0:
        with log_path.open("rb") as log:
            log.seek(max(0, log_path.stat().st_size - 4096))
            text = log.read().decode("utf-8", errors="replace").strip()
        raise LaunchError(text or f"worker exit {code}")


def make_subprocess_launcher(prefix: list[str]) -> Callable[[dict], None]:
    def launch(brief: dict) -> None:
        cmd = [*prefix, "--role", brief["role"], "--brief", brief["brief_path"]]
        _run_command(cmd, brief, brief["framework_root"])

    return launch


def make_cursor_launcher() -> Callable[[dict], None]:
    def launch(brief: dict) -> None:
        cmd = agent_argv(brief["brief_path"], brief["role"])
        cmd = [*cmd[:-1], "--workspace", brief["package_copy"], cmd[-1]]
        _run_command(cmd, brief, brief["framework_root"])

    return launch
