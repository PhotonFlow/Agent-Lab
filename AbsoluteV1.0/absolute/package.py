"""Copy a package into a run, and promote a sibling version beside the original."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

IGNORE_DIRS = {
    "build",
    "install",
    "log",
    "devel",
    "__pycache__",
    ".git",
    ".colcon",
}
IGNORE_SUFFIXES = {".pyc", ".pyo"}


def ignore_runtime(_dir: str, names: list[str]) -> set[str]:
    skipped = set()
    for name in names:
        if name in IGNORE_DIRS or Path(name).suffix in IGNORE_SUFFIXES:
            skipped.add(name)
    return skipped


def copy_package(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"package directory not found: {source}")
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite {destination}")
    shutil.copytree(source, destination, ignore=ignore_runtime)


def message_fields(root: Path) -> list[str]:
    """Public field names in ROS message definitions. Internal symbols are not included."""
    found: list[str] = []
    if not root.is_dir():
        return found
    for path in sorted(root.rglob("*.msg")):
        relative = path.relative_to(root).as_posix()
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("["):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            name = parts[1].split("=", 1)[0].strip()
            if name:
                found.append(f"{relative}:{name}")
    return found


def message_schema(root: Path) -> dict[str, list[str]]:
    return {
        path.relative_to(root).as_posix(): [
            " ".join(line.split())
            for raw in path.read_text(encoding="utf-8").splitlines()
            if (line := raw.split("#", 1)[0].strip())
        ]
        for pattern in ("*.msg", "*.srv", "*.action")
        for path in sorted(root.rglob(pattern))
    }


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_tree(root: Path, relative_paths: list[str]) -> dict[str, str]:
    hashes = {}
    for relative in relative_paths:
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"immutable file missing in package copy: {relative}")
        hashes[relative] = file_hash(path)
    return hashes


def validation_ready(package_dir: Path, minimum_steps: int = 5) -> None:
    path = package_dir / "VALIDATION.md"
    if not path.is_file():
        raise ValueError("promoted package requires VALIDATION.md")
    steps = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.lstrip()[:1].isdigit() and ". " in line
    ]
    if len(steps) < minimum_steps:
        raise ValueError(
            f"VALIDATION.md needs at least {minimum_steps} numbered steps, found {len(steps)}"
        )
