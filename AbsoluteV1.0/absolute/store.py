"""JSON files inside one Absolute run folder. The run folder is the only memory."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run_path(run_dir: Path, name: str) -> Path:
    return run_dir / name


def load_run(run_dir: Path) -> dict[str, Any]:
    return read_json(run_dir / "run.json")


def save_run(run_dir: Path, run: dict[str, Any]) -> None:
    atomic_write(run_dir / "run.json", run)


def append_journal(run_dir: Path, entry: dict[str, Any]) -> None:
    path = run_dir / "journal.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def read_journal(run_dir: Path, limit: int | None = None) -> list[dict[str, Any]]:
    path = run_dir / "journal.jsonl"
    if not path.exists():
        return []
    if limit is not None:
        with path.open("rb") as handle:
            offset = max(0, path.stat().st_size - 131072)
            handle.seek(offset)
            if offset:
                handle.readline()
            lines = handle.read().decode("utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()][-limit:]
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


@contextmanager
def run_lock(run_dir: Path):
    with (run_dir / ".runner.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("another runner owns this run folder") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
