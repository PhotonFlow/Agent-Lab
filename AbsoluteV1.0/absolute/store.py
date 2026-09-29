"""JSON files inside one Absolute run folder. The run folder is the only memory."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing, contextmanager
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
    repair_journal(run_dir)
    path = run_dir / "journal.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


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
            data = handle.read()
            if data and not data.endswith(b"\n"):
                data = data[:data.rfind(b"\n") + 1]
            lines = data.decode("utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()][-limit:]
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        data = data[:data.rfind(b"\n") + 1]
    lines = [line for line in data.decode("utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def repair_journal(run_dir: Path) -> None:
    path = run_dir / "journal.jsonl"
    if not path.exists():
        return
    with path.open("r+b") as handle:
        end = handle.seek(0, os.SEEK_END)
        if not end:
            return
        handle.seek(end - 1)
        if handle.read(1) == b"\n":
            return
        while end:
            start = max(0, end - 65536)
            handle.seek(start)
            chunk = handle.read(end - start)
            boundary = chunk.rfind(b"\n")
            if boundary >= 0:
                handle.truncate(start + boundary + 1)
                break
            end = start
        else:
            handle.truncate(0)
        handle.flush()
        os.fsync(handle.fileno())


class CheckpointError(RuntimeError):
    pass


def checkpoint_cycle(run_dir: Path) -> int | None:
    path = run_dir / "recovery.sqlite3"
    if not path.is_file():
        return None
    with closing(sqlite3.connect(path)) as connection:
        try:
            row = connection.execute("SELECT payload FROM checkpoint WHERE id=1").fetchone()
        except sqlite3.OperationalError:
            return None
    return int(json.loads(row[0])["entry"]["cycle"]) if row else None


def commit_stage(run_dir: Path, run: dict, scoreboard: dict, entry: dict) -> None:
    payload = json.dumps({"run": run, "scoreboard": scoreboard, "entry": entry}, allow_nan=False)
    try:
        with closing(sqlite3.connect(run_dir / "recovery.sqlite3")) as connection, connection:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("CREATE TABLE IF NOT EXISTS checkpoint (id INTEGER PRIMARY KEY, payload TEXT NOT NULL, published INTEGER NOT NULL)")
            connection.execute("INSERT OR REPLACE INTO checkpoint VALUES (1, ?, 0)", (payload,))
        recover_checkpoint(run_dir)
    except (OSError, sqlite3.Error) as exc:
        raise CheckpointError("decision publication interrupted; resume this run to recover") from exc


def recover_checkpoint(run_dir: Path, *, force: bool = False) -> bool:
    path = run_dir / "recovery.sqlite3"
    if not path.is_file():
        return False
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS checkpoint (id INTEGER PRIMARY KEY, payload TEXT NOT NULL, published INTEGER NOT NULL)")
        row = connection.execute("SELECT payload, published FROM checkpoint WHERE id=1").fetchone()
        if not row or (row[1] and not force):
            return False
        payload = json.loads(row[0])
        repair_journal(run_dir)
        atomic_write(run_dir / "run.json", payload["run"])
        atomic_write(run_dir / "scoreboard.json", payload["scoreboard"])
        recent = read_journal(run_dir, limit=1)
        if not recent or recent[-1] != payload["entry"]:
            append_journal(run_dir, payload["entry"])
        with connection:
            connection.execute("UPDATE checkpoint SET published=1 WHERE id=1")
        return True
    finally:
        connection.close()


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
