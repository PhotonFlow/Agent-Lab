"""Run-folder names and package version bumps."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

RUN_RE = re.compile(r"^Absolute_(?P<day>\d{4}-\d{2}-\d{2})_(?P<index>\d+)$")
VERSION_RE = re.compile(r"^(?P<stem>.*)_v(?P<ver>\d+(?:\.\d+)*)$")


def run_id(day: date, index: int) -> str:
    if index < 1:
        raise ValueError("run index starts at 1")
    return f"Absolute_{day.isoformat()}_{index:02d}"


def allocate_run_id(runs_root: Path, day: date | None = None) -> str:
    day = day or date.today()
    runs_root.mkdir(parents=True, exist_ok=True)
    taken = []
    for child in runs_root.iterdir():
        match = RUN_RE.match(child.name)
        if match and match.group("day") == day.isoformat():
            taken.append(int(match.group("index")))
    nxt = max(taken, default=0) + 1
    return run_id(day, nxt)


def next_package_name(package_name: str) -> str:
    """algo_v1.1 -> algo_v1.2. A name with no _v suffix becomes <name>_v1.1."""
    match = VERSION_RE.match(package_name)
    if not match:
        return f"{package_name}_v1.1"
    parts = match.group("ver").split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return f"{match.group('stem')}_v{'.'.join(parts)}"
