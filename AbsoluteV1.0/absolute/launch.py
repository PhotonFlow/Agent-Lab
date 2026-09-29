"""Launch one fresh worker process. The parent keeps the scorer authority."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
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
    tool_args = ["-p", "--force", "--model", WORKER_MODEL, prompt]
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


def _run_command(cmd: list[str], brief: dict, cwd: str) -> None:
    log_path = Path(brief["brief_path"]).with_suffix(".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        code = proc.wait()
        pid = proc.pid
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
    if code != 0:
        text = log_path.read_text(encoding="utf-8", errors="replace").strip()
        raise LaunchError(text or f"worker exit {code}")


def make_subprocess_launcher(prefix: list[str]) -> Callable[[dict], None]:
    def launch(brief: dict) -> None:
        cmd = [*prefix, "--role", brief["role"], "--brief", brief["brief_path"]]
        _run_command(cmd, brief, brief["framework_root"])

    return launch


def make_cursor_launcher() -> Callable[[dict], None]:
    def launch(brief: dict) -> None:
        cmd = agent_argv(brief["brief_path"], brief["role"])
        _run_command(cmd, brief, brief["framework_root"])

    return launch
