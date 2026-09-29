"""JSON files inside one Absolute run folder. The run folder is the only memory."""

from __future__ import annotations

import json
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


def read_journal(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "journal.jsonl"
    if not path.exists():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]
