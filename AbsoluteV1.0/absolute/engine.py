"""Decisions the script owns. The model does not get to mark a keep."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable

from absolute.package import hash_tree, message_fields, validation_ready

LATENCY_BUDGET_MS = 1.0
TERMINAL_STOPS = {
    "target",
    "nothing_new",
    "outputs_covered",
    "oracle_saturated",
    "uncovered_outputs",
    "scenario_uncovered",
}
from absolute.store import append_journal, load_run, read_journal, save_run


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def validate_charter(charter: dict[str, Any]) -> None:
    if "protected" in charter:
        raise ValueError("protected metrics belong under metrics.protected")
    primary = charter.get("metrics", {}).get("primary")
    if not isinstance(primary, dict):
        raise ValueError("charter.metrics.primary is required")
    for key in ("name", "direction", "noise"):
        if key not in primary:
            raise ValueError(f"charter.metrics.primary.{key} is required")
    if primary["direction"] not in ("maximize", "minimize"):
        raise ValueError("primary.direction must be maximize or minimize")
    if isinstance(primary["noise"], bool) or not math.isfinite(float(primary["noise"])) or float(primary["noise"]) < 0:
        raise ValueError("primary.noise must be finite and nonnegative")
    command = charter.get("eval_command")
    if command is not None and (not isinstance(command, list) or not command):
        raise ValueError("eval_command must be a non-empty list of strings, or null")
    catalog = charter.get("feature_catalog")
    if not isinstance(catalog, list):
        raise ValueError("charter.feature_catalog must be a list")
    seen: set[str] = set()
    for entry in catalog:
        if (
            not isinstance(entry, dict)
            or not str(entry.get("id", "")).strip()
            or not str(entry.get("summary", "")).strip()
        ):
            raise ValueError("each catalog entry needs an id and a summary")
        if entry["id"] in seen:
            raise ValueError(f"duplicate catalog id {entry['id']}")
        seen.add(entry["id"])
    mutable = charter.get("mutable", [])
    immutable = charter.get("immutable", [])
    if not isinstance(mutable, list) or not isinstance(immutable, list):
        raise ValueError("mutable and immutable must be lists")
    if "loop" in charter and charter["loop"] not in ("until_target", "continuous"):
        raise ValueError("loop must be until_target or continuous")
    if charter.get("loop") in ("until_target", "continuous"):
        if charter.get("edit_policy") != "except_immutable":
            raise ValueError("until_target requires edit_policy except_immutable")
        if not command:
            raise ValueError("until_target requires an eval command")
        if primary.get("target") is None and charter["loop"] == "until_target":
            raise ValueError("until_target requires metrics.primary.target")
        if primary.get("target") is not None and (isinstance(primary["target"], bool) or not math.isfinite(float(primary["target"]))):
            raise ValueError("primary.target must be finite")
    if command and charter.get("edit_policy") != "except_immutable":
        if not mutable:
            raise ValueError("a charter with an eval command requires a non-empty mutable list")
        if not immutable:
            raise ValueError("a charter with an eval command requires a non-empty immutable list")
    for item in charter.get("metrics", {}).get("protected", []):
        if item.get("direction") not in ("maximize", "minimize"):
            raise ValueError("protected metric direction must be maximize or minimize")
        budget = item["max_regression"]
        if isinstance(budget, bool) or not math.isfinite(float(budget)) or float(budget) < 0:
            raise ValueError("protected max_regression must be finite and nonnegative")


def protected_metrics(charter: dict[str, Any]) -> list[dict[str, Any]]:
    return list(charter.get("metrics", {}).get("protected", []))


def _better(direction: str, baseline: float, current: float, margin: float) -> bool:
    if direction == "maximize":
        return current - baseline > margin
    return baseline - current > margin


def _within_budget(direction: str, baseline: float, current: float, budget: float) -> bool:
    if direction == "minimize":
        return current <= baseline + budget
    return current >= baseline - budget


def required_output_specs(charter: dict[str, Any]) -> list[dict[str, Any]]:
    outputs = charter.get("required_outputs")
    if isinstance(outputs, list) and outputs:
        return list(outputs)
    primary = charter["metrics"]["primary"]
    return [
        {
            "direction": primary["direction"],
            "id": primary["name"],
            "metric": primary["name"],
            "noise": primary["noise"],
            "target": primary.get("target"),
        }
    ]


def outputs_at_target(charter: dict[str, Any], metrics: dict[str, Any]) -> bool:
    for spec in required_output_specs(charter):
        metric = spec["metric"]
        if spec.get("target") is None or metric not in metrics:
            return False
        if not target_hit({"direction": spec["direction"], "target": spec["target"]}, metrics[metric]):
            return False
    return True


def protected_targets_met(charter: dict[str, Any], metrics: dict[str, Any]) -> bool:
    for item in protected_metrics(charter):
        if item.get("target") is None:
            continue
        metric = item["name"]
        if metric not in metrics or not target_hit(item, metrics[metric]):
            return False
    return True


def measurements_at_target(charter: dict[str, Any], metrics: dict[str, Any]) -> bool:
    return outputs_at_target(charter, metrics) and protected_targets_met(charter, metrics)


def accuracy_keep_reason(charter: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> str | None:
    """None means the implementation edit may be kept."""
    for spec in required_output_specs(charter):
        metric = spec["metric"]
        if metric not in after or metric not in before:
            return f"eval JSON missing {metric}"
    for item in protected_metrics(charter):
        metric = item["name"]
        if metric not in after or metric not in before:
            return f"eval JSON missing protected metric {metric}"
        if not _within_budget(
            item["direction"],
            float(before[metric]),
            float(after[metric]),
            float(item["max_regression"]),
        ):
            return f"protected metric {metric} regressed"
        if item.get("target") is not None and not target_hit(item, after[metric]):
            return f"protected metric {metric} missed its target"
    if measurements_at_target(charter, before):
        return "oracle saturated"
    improved = False
    for spec in required_output_specs(charter):
        metric = spec["metric"]
        noise = float(spec["noise"])
        if _better(spec["direction"], float(before[metric]), float(after[metric]), noise):
            improved = True
        elif not _within_budget(spec["direction"], float(before[metric]), float(after[metric]), noise):
            return f"accuracy metric {metric} regressed"
    if improved:
        return None
    latency = next((item for item in protected_metrics(charter) if item["name"] == "latency_ms"), None)
    if (
        latency
        and "latency_ms" in before
        and "latency_ms" in after
        and _better(
            "minimize",
            float(before["latency_ms"]),
            float(after["latency_ms"]),
            float(latency["max_regression"]),
        )
    ):
        return "latency-only"
    return "accuracy did not improve"


def search_metric_specs(charter: dict[str, Any]) -> list[dict[str, Any]]:
    specs = [dict(spec) for spec in required_output_specs(charter)]
    names = {spec["metric"] for spec in specs}
    specs.extend(
        {**item, "metric": item["name"], "direction": item["direction"],
         "noise": item.get("noise", item["max_regression"]),
         "target": item.get("target"), "max_regression": item["max_regression"],
         "aggregation": item.get("aggregation", "worst"),
         "hard_limit": item.get("hard_limit", item.get("target"))}
        for item in protected_metrics(charter) if item["name"] not in names
    )
    return specs


def aggregate_metric(spec: dict[str, Any], values: list[float]) -> float:
    policy = "worst" if spec.get("hard_limit") is not None else spec.get("aggregation", "median")
    if policy == "worst":
        return max(values) if spec["direction"] == "minimize" else min(values)
    if policy == "mean":
        return mean(values)
    if policy == "median":
        return median(values)
    raise ValueError(f"unknown aggregation {policy}")


def search_keep_reason(
    charter: dict[str, Any], before: dict[str, Any], after: dict[str, Any],
    baseline: dict[str, Any],
) -> str | None:
    improved = False
    for spec in search_metric_specs(charter):
        name = spec["metric"]
        values = [sample.get(name) for sample in (before, after, baseline)]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
            return f"eval JSON missing finite metric {name}"
        previous, candidate, original = map(float, values)
        noise = float(spec["noise"])
        margin = max(noise, float(spec.get("min_effect", noise)))
        budget = float(spec.get("max_regression", noise))
        if not all(math.isfinite(value) and value >= 0 for value in (noise, margin, budget)):
            return f"metric {name} has invalid tolerances"
        hard_limit = spec.get("hard_limit")
        if hard_limit is not None and not target_hit({"direction": spec["direction"], "target": hard_limit}, candidate):
            return f"metric {name} violated its hard limit"
        if not _within_budget(spec["direction"], previous, candidate, budget):
            return f"metric {name} regressed"
        if not _within_budget(spec["direction"], original, candidate, budget):
            return f"metric {name} exceeded baseline regression budget"
        if spec.get("target") is not None and target_hit(spec, previous) and not target_hit(spec, candidate):
            return f"metric {name} lost its achieved target"
        improved |= _better(spec["direction"], previous, candidate, margin)
    return None if improved else "no metric improved beyond noise"


def status_text(run_dir: Path) -> str:
    from absolute.store import read_json

    run = load_run(run_dir)
    scoreboard = read_json(run_dir / "scoreboard.json") if (run_dir / "scoreboard.json").exists() else {}
    lines = [
        f"Absolute | {run['id']} | {run['status']} | {run.get('stage') or '-'}",
        f"Cycles: {scoreboard.get('cycles', 0)}  Keeps: {scoreboard.get('keeps', 0)}  "
        f"No-gain streak: {scoreboard.get('no_keep_streak', 0)}  Stop: {run.get('stop_reason') or '-'}",
        "Metric                        Baseline         Best       Target   Progress",
    ]
    if scoreboard and (run_dir / "charter.json").exists():
        charter = read_json(run_dir / "charter.json")
        for spec in search_metric_specs(charter):
            name = spec["metric"]
            original = scoreboard.get("baseline", {}).get(name)
            current = scoreboard.get("best", {}).get(name)
            target = spec.get("target")
            numbers = [f"{value:.6g}" if isinstance(value, (int, float)) else "-" for value in (original, current, target)]
            progress = "[----------]"
            if all(isinstance(value, (int, float)) for value in (original, current, target)):
                if target_hit(spec, current):
                    filled = 10
                elif target != original:
                    filled = int(10 * max(0, min(1, (current - original) / (target - original))))
                else:
                    filled = 0
                progress = "[" + "#" * filled + "." * (10 - filled) + "]"
            lines.append(f"{name[:28]:28} {numbers[0]:>12} {numbers[1]:>12} {numbers[2]:>12}   {progress}")
    gaps = run.get("uncovered_behaviors") or []
    lines.append(f"Unmeasured scenario behaviors: {len(gaps)} | SOTA: unverified | Robot validation: pending")
    lines.extend(f"  Gap: {str(gap)[:200]}" for gap in gaps[:5])
    return "\n".join(lines)


def missing_message_fields(package: Path, expected: list[str]) -> list[str]:
    current = set(message_fields(package))
    return [name for name in expected if name not in current]


def citations_are_external(citations: Any, package: Path) -> bool:
    if not isinstance(citations, list) or not citations:
        return False
    root = str(package.resolve()).replace("\\", "/").lower()
    for item in citations:
        text = str(item).strip()
        if not (text.startswith("https://") or text.startswith("http://")):
            return False
        if root and root in text.replace("\\", "/").lower():
            return False
    return True


def citations_fetch(citations: list[str], timeout: float = 10) -> bool:
    for url in citations:
        request = urllib.request.Request(url, method="GET", headers={"User-Agent": "Absolute"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if int(getattr(response, "status", 200)) >= 400:
                    return False
        except (OSError, urllib.error.URLError, TimeoutError, ValueError):
            return False
    return True


def judge(charter: dict[str, Any], baseline: dict[str, float], current: dict[str, float]) -> str:
    primary = charter["metrics"]["primary"]
    name = primary["name"]
    if name not in current or name not in baseline:
        raise KeyError(f"eval JSON missing primary metric {name}")
    improved = _better(
        primary["direction"],
        float(baseline[name]),
        float(current[name]),
        float(primary["noise"]),
    )
    for item in protected_metrics(charter):
        metric = item["name"]
        if metric not in current or metric not in baseline:
            raise KeyError(f"eval JSON missing protected metric {metric}")
        if not _within_budget(
            item["direction"],
            float(baseline[metric]),
            float(current[metric]),
            float(item["max_regression"]),
        ):
            return "revert"
    return "keep" if improved else "revert"


_RUNNER_ARMED = False


def _until_target(charter: dict[str, Any]) -> bool:
    return charter.get("loop") in ("until_target", "continuous")


def target_hit(primary: dict[str, Any], value: Any) -> bool:
    target = primary.get("target")
    if target is None:
        return False
    if primary["direction"] == "maximize":
        return float(value) >= float(target)
    return float(value) <= float(target)


def _runner_only(charter: dict[str, Any]) -> None:
    if _until_target(charter) and not _RUNNER_ARMED:
        raise RuntimeError("only the runner may admit or score")


@contextmanager
def runner_authority():
    """Arm admit and cycle. Worker processes do not inherit this flag."""
    global _RUNNER_ARMED
    previous = _RUNNER_ARMED
    _RUNNER_ARMED = True
    try:
        yield
    finally:
        _RUNNER_ARMED = previous


class EvalFailure(RuntimeError):
    def __init__(self, message: str, stdout: str, stderr: str) -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


def run_eval(command: list[str], cwd: Path, timeout_sec: float) -> dict[str, Any]:
    from absolute.launch import run_process

    try:
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["ABSOLUTE_PACKAGE"] = str(cwd)
        completed = run_process(command, cwd, timeout_sec, env=env)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        raise EvalFailure("eval timed out", stdout, stderr) from exc
    if completed.returncode != 0:
        raise EvalFailure(
            completed.stderr.strip() or f"eval exit {completed.returncode}",
            completed.stdout,
            completed.stderr,
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise EvalFailure("eval stdout is not one JSON object", completed.stdout, completed.stderr) from exc
    if not isinstance(payload, dict):
        raise EvalFailure("eval JSON must be an object", completed.stdout, completed.stderr)
    return payload


def measure_search(run_dir: Path, charter: dict[str, Any], label: str) -> dict[str, float]:
    from absolute.contract import load_contract, resolve_pointer
    from absolute.launch import report
    from absolute.store import atomic_write
    from absolute.evaluation import check_case_evidence, verify_benchmark

    run = load_run(run_dir)
    benchmark = verify_benchmark(run_dir)
    if benchmark and charter["eval_command"] != benchmark["eval_command"]:
        raise RuntimeError("benchmark evaluator command changed")
    repeats = int(run.get("search", {}).get("eval_repeats", 3))
    document = load_contract(run_dir)
    paths = {row["id"]: row["path"] for row in document["metrics"]} if document else {}
    samples = []
    for index in range(repeats):
        report(run_dir, "evaluation", label=label, sample=index + 1, total=repeats)
        payload = run_eval(list(charter["eval_command"]), Path(run["package_copy"]), float(charter.get("eval_timeout_sec", 60)))
        if benchmark:
            check_case_evidence(benchmark, payload)
        sample = {}
        for spec in search_metric_specs(charter):
            name = spec["metric"]
            value = resolve_pointer(payload, paths[name]) if name in paths else payload.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise EvalFailure(f"eval JSON missing finite metric {name}", "", "")
            sample[name] = float(value)
        samples.append(sample)
    metrics = {
        spec["metric"]: aggregate_metric(spec, [sample[spec["metric"]] for sample in samples])
        for spec in search_metric_specs(charter)
    }
    atomic_write(run_dir / "eval" / f"{label}.json", {"metrics": metrics, "samples": samples})
    verify_benchmark(run_dir)
    return metrics


def _git(cwd: Path, args: list[str]) -> None:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "Absolute")
    env.setdefault("GIT_AUTHOR_EMAIL", "absolute@local")
    env.setdefault("GIT_COMMITTER_NAME", "Absolute")
    env.setdefault("GIT_COMMITTER_EMAIL", "absolute@local")
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env)


def ensure_copy_repo(package_copy: Path) -> None:
    if (package_copy / ".git").exists():
        return
    _git(package_copy, ["init"])
    _git(package_copy, ["add", "-A"])
    _git(package_copy, ["commit", "-m", "absolute: baseline copy"])


def capture_patch(package_copy: Path, destination: Path) -> None:
    _git(package_copy, ["add", "-A"])
    diff = subprocess.run(
        ["git", "diff", "--cached"],
        cwd=package_copy,
        check=True,
        capture_output=True,
        text=True,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(diff.stdout, encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_handoff(run_dir: Path) -> None:
    run = load_run(run_dir)
    journal = read_journal(run_dir, limit=20 if run.get("search") else None)
    tail = journal[-5:]
    scoreboard: dict[str, Any] = {}
    scoreboard_path = run_dir / "scoreboard.json"
    if scoreboard_path.exists():
        from absolute.store import read_json

        scoreboard = read_json(scoreboard_path)
    attempts = (
        [Path(entry["patch"]).name for entry in journal if entry.get("patch")]
        if run.get("search") else
        sorted(path.name for path in (run_dir / "attempts").glob("*")) if (run_dir / "attempts").exists() else []
    )
    lines = [
        "# Absolute handoff",
        "",
        f"status: {run.get('status')}",
        f"stop_reason: {run.get('stop_reason', '')}",
        *( [f"success: {run.get('success')}"] if "success" in run else [] ),
        *(
            ["uncovered_behaviors:", *[f"- {item}" for item in run["uncovered_behaviors"]]]
            if run.get("uncovered_behaviors")
            else []
        ),
        f"run: {run_dir}",
        f"source_package: {run.get('source_package')}",
        f"package_copy: {run.get('package_copy')}",
        f"baseline: {json.dumps(scoreboard.get('baseline'))}",
        f"best: {json.dumps(scoreboard.get('best'))}",
        f"cycles: {scoreboard.get('cycles', 0)} keeps: {scoreboard.get('keeps', 0)}",
        "",
        "attempts:",
        *([f"- attempts/{name}" for name in attempts] or ["- none"]),
        "",
        "journal_tail:",
        *[json.dumps(entry) for entry in tail],
        "",
        "limitations:",
        *([f"- {line}" for line in _limitation_lines(journal)] or ["- none"]),
        "",
        f"immutable_hashes: {json.dumps(run.get('immutable_hashes') or {})}",
        "robot_validated: false",
        "",
        _handoff_instruction(run_dir),
        "",
    ]
    write_text(run_dir / "handoff.md", "\n".join(lines))


def reset_copy(package_copy: Path) -> None:
    _git(package_copy, ["reset", "--hard", "HEAD"])
    _git(package_copy, ["clean", "-fd"])


def head_sha(package_copy: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=package_copy,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def reset_to(package_copy: Path, sha: str) -> None:
    _git(package_copy, ["reset", "--hard", sha])
    _git(package_copy, ["clean", "-fd"])


def changed_paths(package_copy: Path, base_sha: str) -> list[str]:
    _git(package_copy, ["add", "-A"])
    completed = subprocess.run(
        ["git", "diff", "--name-only", "--cached", base_sha],
        cwd=package_copy,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]


def commit_from(package_copy: Path, base_sha: str, message: str) -> str:
    _git(package_copy, ["add", "-A"])
    _git(package_copy, ["reset", "--soft", base_sha])
    _git(package_copy, ["commit", "-m", message])
    return head_sha(package_copy)


def capture_patch_from(package_copy: Path, destination: Path, base_sha: str) -> None:
    _git(package_copy, ["add", "-A"])
    diff = subprocess.run(
        ["git", "diff", "--cached", base_sha],
        cwd=package_copy,
        check=True,
        capture_output=True,
        text=True,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(diff.stdout, encoding="utf-8")


def commit_copy(package_copy: Path, message: str) -> str:
    _git(package_copy, ["add", "-A"])
    _git(package_copy, ["commit", "-m", message])
    return head_sha(package_copy)


def check_immutable(run_dir: Path, package_copy: Path) -> None:
    run = load_run(run_dir)
    expected = run.get("immutable_hashes") or {}
    if not expected:
        return
    current = hash_tree(package_copy, list(expected))
    changed = [name for name, digest in expected.items() if current[name] != digest]
    if changed:
        raise RuntimeError("immutable files changed: " + ", ".join(changed))


def record_baseline(run_dir: Path, metrics: dict[str, Any]) -> None:
    run = load_run(run_dir)
    scoreboard = {
        "baseline": metrics,
        "best": metrics,
        "cycles": 0,
        "keeps": 0,
        "no_keep_streak": 0,
        "implementation_keep_streak": 0,
    }
    from absolute.store import atomic_write

    atomic_write(run_dir / "scoreboard.json", scoreboard)
    append_journal(
        run_dir,
        {"at": now(), "cycle": 0, "hypothesis": "baseline", "metrics": metrics, "outcome": "baseline"},
    )
    run["status"] = "awaiting_gate_b"
    save_run(run_dir, run)
    write_handoff(run_dir)


def _handoff_instruction(run_dir: Path) -> str:
    if load_run(run_dir).get("search"):
        return (
            "Continuous search: resume this folder with python -m absolute evolve --run <folder>. "
            "Recent attempts are summarized here; full history is in journal.jsonl. "
            "Targets and plateau do not imply SOTA. This is not a state-of-the-art claim. "
            "Do not mark a keep. robot_validated: false."
        )
    charter_path = run_dir / "charter.json"
    if charter_path.is_file():
        from absolute.store import read_json

        charter = read_json(charter_path)
        if _until_target(charter):
            run = load_run(run_dir)
            if run.get("status") == "stopped" and run.get("stop_reason") == "outputs_covered":
                return (
                    "This run stopped because every required output is at its target and the proposal round admitted nothing new. "
                    "Every proposal was a feature already kept or a feature the panel already rejected. "
                    "robot_validated: false. Do not open a new run."
                )
            if run.get("status") == "stopped" and run.get("stop_reason") == "scenario_uncovered":
                return (
                    "This run stopped because the sealed metrics are already at their targets and the scenario still names a behavior the package does not measure. "
                    "This is not success and not a state-of-the-art claim. "
                    "robot_validated: false. Do not open a new run."
                )
            if run.get("status") == "stopped" and run.get("stop_reason") == "oracle_saturated":
                return (
                    "This run stopped because every required accuracy metric was already at its target at baseline. "
                    "The suite cannot see a further change. This is not a state-of-the-art claim. "
                    "robot_validated: false. Do not open a new run."
                )
            if run.get("status") == "stopped" and run.get("stop_reason") == "uncovered_outputs":
                return (
                    "This run stopped because a required output is still off target after the proposal rounds were exhausted. "
                    "This is not a state-of-the-art claim. robot_validated: false. Do not open a new run."
                )
            if run.get("status") == "stopped" and run.get("stop_reason") == "nothing_new":
                return (
                    "This run stopped because the proposal round admitted nothing new. "
                    "Every proposal was a feature already kept or a feature the panel already rejected. "
                    "robot_validated: false. Do not open a new run."
                )
            if run.get("status") == "stopped":
                return "This run is stopped. Do not open a new run."
            return (
                "If status is running, continue this folder. "
                "A finished cycle starts the next feature-proposal group. "
                "The run stops when every proposal is a feature already kept or a feature the panel already rejected. "
                "A revert, a failed eval, and a bad edit retry that same stage. "
                "Plateau and max_cycles do not stop it. Do not mark a keep. Do not open a new run."
            )
    return (
        "If status is running, continue this folder. If status is needs_human, fix the copy or the charter, "
        "then resume this same folder. If status is stopped, do not create a new run unless asked."
    )


def apply_stops(run_dir: Path, charter: dict[str, Any], scoreboard: dict[str, Any]) -> None:
    run = load_run(run_dir)
    primary = charter["metrics"]["primary"]
    best = scoreboard["best"][primary["name"]]
    if _until_target(charter):
        return
    target = primary.get("target")
    stops = charter.get("stops", {})
    reason = None
    if target is not None:
        hit = target_hit(primary, best)
        if hit:
            reason = "target"
    if scoreboard["no_keep_streak"] >= int(stops.get("plateau", 5)):
        reason = "plateau"
    if scoreboard["cycles"] >= int(stops.get("max_cycles", 20)):
        reason = "max_cycles"
    if reason:
        run["status"] = "stopped"
        run["stop_reason"] = reason
        save_run(run_dir, run)


def _require_measured(charter: dict[str, Any]) -> list[str]:
    command = charter.get("eval_command")
    if not command:
        raise ValueError("eval command is null")
    return list(command)


def _tree_matches_script(run: dict[str, Any], package_copy: Path) -> bool:
    script_head = run.get("script_head")
    if not script_head or head_sha(package_copy) != script_head:
        return False
    return not _dirty_paths(package_copy)


def _stop_human(run_dir: Path, package_copy: Path, reason: str, restore_sha: str, hypothesis: str) -> None:
    attempt = run_dir / "attempts" / "error.patch"
    try:
        capture_patch_from(package_copy, attempt, restore_sha)
    except subprocess.CalledProcessError:
        pass
    reset_to(package_copy, restore_sha)
    run = load_run(run_dir)
    run["status"] = "needs_human"
    run["stop_reason"] = reason
    run["open_admit"] = None
    save_run(run_dir, run)
    append_journal(
        run_dir,
        {
            "at": now(),
            "cycle": None,
            "hypothesis": hypothesis,
            "metrics": None,
            "outcome": "error",
            "error": reason,
        },
    )
    write_handoff(run_dir)
    raise RuntimeError(reason)


def admit(
    run_dir: Path,
    charter: dict[str, Any],
    tag: str,
    hypothesis: str,
    feature_id: str | None,
    *,
    summary: str | None = None,
) -> dict[str, Any]:
    _runner_only(charter)
    run = load_run(run_dir)
    if run.get("status") != "running":
        raise RuntimeError(f"admit requires status running, found {run.get('status')}")
    _require_measured(charter)
    if run.get("open_admit"):
        raise ValueError("an admit is already open")
    package_copy = Path(run["package_copy"])
    if not _tree_matches_script(run, package_copy):
        raise ValueError("admit requires a clean copy at the last script commit")
    if tag not in ("implementation", "tech-stack", "feature"):
        raise ValueError("tag must be implementation, tech-stack, or feature")
    from absolute.store import read_json

    scoreboard_path = run_dir / "scoreboard.json"
    streak = 0
    if scoreboard_path.exists():
        streak = int(read_json(scoreboard_path).get("implementation_keep_streak", 0))
    if tag == "implementation" and streak >= 3:
        raise ValueError("three implementation keeps in a row; admit tech-stack or feature")
    catalog = list(charter.get("feature_catalog", []))
    catalog_ids = {entry["id"] for entry in catalog}
    if tag == "feature":
        if not feature_id or feature_id not in catalog_ids:
            if _until_target(charter) and feature_id and str(summary or "").strip():
                if feature_id not in catalog_ids:
                    catalog.append({"id": feature_id, "summary": str(summary).strip()})
                    charter["feature_catalog"] = catalog
                    from absolute.store import atomic_write

                    atomic_write(run_dir / "charter.json", charter)
            else:
                _stop_human(
                    run_dir,
                    package_copy,
                    f"feature id is not in the catalog: {feature_id}",
                    run["script_head"],
                    hypothesis,
                )
    elif feature_id:
        raise ValueError("feature id is only valid for a feature tag")
    run["open_admit"] = {
        "feature_id": feature_id,
        "hypothesis": hypothesis,
        "sha": run["script_head"],
        "tag": tag,
    }
    save_run(run_dir, run)
    return run["open_admit"]


def _repair_attempt(
    run_dir: Path,
    charter: dict[str, Any],
    package_copy: Path,
    reason: str,
    restore_sha: str,
    hypothesis: str,
    outcome: str,
    tag: str,
    feature_id: str | None,
) -> dict[str, Any]:
    from absolute.store import atomic_write, read_json

    scoreboard = read_json(run_dir / "scoreboard.json")
    scoreboard["cycles"] = int(scoreboard.get("cycles", 0)) + 1
    scoreboard["no_keep_streak"] = int(scoreboard.get("no_keep_streak", 0)) + 1
    attempt = run_dir / "attempts" / f"{scoreboard['cycles']:03d}.patch"
    try:
        capture_patch_from(package_copy, attempt, restore_sha)
    except subprocess.CalledProcessError:
        pass
    reset_to(package_copy, restore_sha)
    entry: dict[str, Any] = {
        "admit_sha": restore_sha,
        "at": now(),
        "cycle": scoreboard["cycles"],
        "error": reason,
        "feature_id": feature_id,
        "hypothesis": hypothesis,
        "metrics": None,
        "outcome": outcome,
        "tag": tag,
    }
    if attempt.exists():
        entry["patch"] = str(attempt.relative_to(run_dir)).replace("\\", "/")
    run = load_run(run_dir)
    run["open_admit"] = None
    run["script_head"] = restore_sha
    run["status"] = "running"
    run["stop_reason"] = ""
    save_run(run_dir, run)
    atomic_write(run_dir / "scoreboard.json", scoreboard)
    append_journal(run_dir, entry)
    apply_stops(run_dir, charter, scoreboard)
    write_handoff(run_dir)
    return entry


def behavior_command_rejection(
    command: Any,
    eval_command: list[str],
    immutable: list[str],
) -> str | None:
    if not isinstance(command, list) or not command or not all(isinstance(part, str) and part.strip() for part in command):
        return "missing behavior test"
    if [str(part) for part in command] == [str(part) for part in eval_command]:
        return "behavior test is the eval command"
    names = {Path(path).name for path in immutable}
    paths = {path.replace("\\", "/") for path in immutable}
    for token in command:
        norm = str(token).replace("\\", "/")
        if Path(norm).name in names or norm in paths:
            return "behavior test names the scorer"
    return None


def _record_stage(
    run_dir: Path,
    package_copy: Path,
    *,
    outcome: str,
    reason: str,
    base_sha: str,
    hypothesis: str,
    stage: str,
    cycle_n: int,
    metrics: dict[str, Any] | None,
    feature_id: str | None,
    keep_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from absolute.store import atomic_write, read_json

    scoreboard = read_json(run_dir / "scoreboard.json")
    scoreboard["edit_attempts"] = int(scoreboard.get("edit_attempts", 0)) + 1
    attempt = run_dir / "attempts" / f"{scoreboard['edit_attempts']:03d}.patch"
    try:
        capture_patch_from(package_copy, attempt, base_sha)
    except subprocess.CalledProcessError:
        pass
    entry: dict[str, Any] = {
        "admit_sha": base_sha,
        "attempt": scoreboard["edit_attempts"],
        "at": now(),
        "cycle": cycle_n,
        "error": reason,
        "feature_id": feature_id,
        "hypothesis": hypothesis,
        "metrics": metrics,
        "outcome": outcome,
        "stage": stage,
    }
    if attempt.exists():
        entry["patch"] = str(attempt.relative_to(run_dir)).replace("\\", "/")
    run = load_run(run_dir)
    if outcome == "keep" and keep_metrics is not None:
        if changed_paths(package_copy, base_sha):
            sha = commit_from(package_copy, base_sha, f"absolute: {hypothesis}")
        else:
            sha = base_sha
        entry["commit"] = sha
        run["script_head"] = sha
        scoreboard["best"] = keep_metrics
        scoreboard["keeps"] = int(scoreboard.get("keeps", 0)) + 1
        scoreboard["no_keep_streak"] = 0
    else:
        reset_to(package_copy, base_sha)
        run["script_head"] = base_sha
        scoreboard["no_keep_streak"] = int(scoreboard.get("no_keep_streak", 0)) + 1
    run["status"] = "running"
    run["stop_reason"] = ""
    if outcome == "keep" and stage == "feature_edit" and feature_id:
        summary = ""
        admitted = run.get("admitted_feature") or {}
        if isinstance(admitted, dict) and str(admitted.get("feature_id") or "") == str(feature_id):
            summary = str(admitted.get("summary") or "")
        _append_listed_feature(run, "kept_features", str(feature_id), summary)
    from absolute.store import commit_stage

    commit_stage(run_dir, run, scoreboard, entry)
    write_handoff(run_dir)
    return entry


def _referenced_test_files(package: Path, command: list[str]) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for token in command:
        raw = str(token).replace("\\", "/")
        candidates = [Path(raw)]
        if not raw.endswith(".py"):
            candidates.append(Path(raw + ".py"))
            candidates.append(Path(raw.replace(".", "/") + ".py"))
        for relative in candidates:
            if relative.is_absolute() or ".." in relative.parts:
                continue
            path = package / relative
            if path.is_file():
                found[relative.as_posix()] = path.read_bytes()
    return found


def _behavior_fails_then_passes(package: Path, command: list[str], timeout: float, base_sha: str) -> str | None:
    """The new test must fail on the pre-edit code and pass after. None means it did."""
    files = _referenced_test_files(package, command)
    if not files:
        return "behavior test is not a file in the package"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".patch")
    patch = Path(handle.name)
    handle.close()
    try:
        capture_patch_from(package, patch, base_sha)
        reset_to(package, base_sha)
        for relative, data in files.items():
            destination = package / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        try:
            before = subprocess.run(
                command,
                cwd=package,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            before = None
        reset_to(package, base_sha)
        if patch.stat().st_size:
            applied = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", str(patch)],
                cwd=package,
                check=False,
                capture_output=True,
                text=True,
            )
            if applied.returncode != 0:
                return applied.stderr.strip() or "could not restore the edit"
        try:
            after = subprocess.run(
                command,
                cwd=package,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            after = None
    finally:
        patch.unlink(missing_ok=True)
    if before is not None and before.returncode == 0:
        return "behavior test passed before the edit"
    if before is None or after is None or after.returncode != 0:
        return "behavior test failed"
    return None


def score_stage(
    run_dir: Path,
    charter: dict[str, Any],
    *,
    stage: str,
    cycle_n: int,
    hypothesis: str,
    base_sha: str,
    behavior_test: Any,
    pre_metrics: dict[str, Any],
    feature_id: str | None = None,
    integrity_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    _runner_only(charter)
    run = load_run(run_dir)
    if run.get("status") != "running":
        raise RuntimeError(f"stage gate requires status running, found {run.get('status')}")
    from absolute.contract import ContractTamper, enforce_sealed_contract

    try:
        charter = enforce_sealed_contract(run_dir, charter)
    except ContractTamper as exc:
        return _record_stage(
            run_dir,
            Path(run["package_copy"]),
            outcome="bad_edit",
            reason=str(exc),
            base_sha=base_sha,
            hypothesis=hypothesis,
            stage=stage,
            cycle_n=cycle_n,
            metrics=None,
            feature_id=feature_id,
        )
    package_copy = Path(run["package_copy"])
    command = list(charter["eval_command"])
    rejected = behavior_command_rejection(behavior_test, command, list(charter.get("immutable") or []))
    if rejected:
        return _record_stage(
            run_dir,
            package_copy,
            outcome="bad_edit",
            reason=rejected,
            base_sha=base_sha,
            hypothesis=hypothesis,
            stage=stage,
            cycle_n=cycle_n,
            metrics=None,
            feature_id=feature_id,
        )
    if stage == "search_edit":
        from absolute.launch import report, run_process
        from absolute.evaluation import run_validation, validate_command, verify_benchmark

        try:
            check_immutable(run_dir, package_copy)
            benchmark = verify_benchmark(run_dir)
            if benchmark:
                run_validation(run_dir, benchmark["validation_commands"], package_copy, float(charter.get("eval_timeout_sec", 60)), f"cycle-{cycle_n:06d}")
                validate_command(behavior_test)
            report(run_dir, "behavior_test", cycle=cycle_n)
            result = run_process(list(behavior_test), package_copy, float(charter.get("eval_timeout_sec", 60)), env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            test_output = result.stdout + "\n" + result.stderr
            write_text(run_dir / "eval" / f"cycle-{cycle_n:06d}-test.log", test_output)
            behavior_error = None if result.returncode == 0 else "behavior test failed: " + test_output[-2000:]
            verify_benchmark(run_dir)
        except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError) as exc:
            behavior_error = str(exc)
    else:
        behavior_error = _behavior_fails_then_passes(
            package_copy,
            list(behavior_test),
            float(charter.get("eval_timeout_sec", 60)),
            base_sha,
        )
    if integrity_check is not None and not integrity_check():
        behavior_error = "behavior test changed runner-owned files or scorer"
    if behavior_error:
        return _record_stage(
            run_dir,
            package_copy,
            outcome="bad_edit",
            reason=behavior_error,
            base_sha=base_sha,
            hypothesis=hypothesis,
            stage=stage,
            cycle_n=cycle_n,
            metrics=None,
            feature_id=feature_id,
        )
    removed = missing_message_fields(package_copy, list(run.get("message_fields") or []))
    if not removed and run.get("message_schema"):
        from absolute.package import message_schema

        current_schema = message_schema(package_copy)
        removed = [name for name, schema in run["message_schema"].items() if current_schema.get(name) != schema]
    if removed:
        return _record_stage(
            run_dir,
            package_copy,
            outcome="bad_edit",
            reason="edit removed a public message field: " + ", ".join(removed),
            base_sha=base_sha,
            hypothesis=hypothesis,
            stage=stage,
            cycle_n=cycle_n,
            metrics=None,
            feature_id=feature_id,
        )
    try:
        check_immutable(run_dir, package_copy)
        if stage == "search_edit" and not changed_paths(package_copy, base_sha):
            raise RuntimeError("candidate contains no changes")
        metrics = (
            measure_search(run_dir, charter, f"cycle-{cycle_n:06d}-candidate")
            if stage == "search_edit"
            else run_eval(command, package_copy, float(charter.get("eval_timeout_sec", 60)))
        )
        check_immutable(run_dir, package_copy)
    except Exception as exc:
        if integrity_check is not None:
            integrity_check()
        outcome = "eval_failed" if isinstance(exc, EvalFailure) or isinstance(exc, KeyError) else "bad_edit"
        if isinstance(exc, RuntimeError) and "immutable" in str(exc):
            outcome = "bad_edit"
        return _record_stage(
            run_dir,
            package_copy,
            outcome=outcome,
            reason=str(exc),
            base_sha=base_sha,
            hypothesis=hypothesis,
            stage=stage,
            cycle_n=cycle_n,
            metrics=None,
            feature_id=feature_id,
        )
    if integrity_check is not None and not integrity_check():
        return _record_stage(
            run_dir, package_copy, outcome="bad_edit", reason="evaluation changed runner-owned files or scorer",
            base_sha=base_sha, hypothesis=hypothesis, stage=stage, cycle_n=cycle_n,
            metrics=None, feature_id=feature_id,
        )
    primary = charter["metrics"]["primary"]
    name = primary["name"]
    if name not in metrics or name not in pre_metrics:
        return _record_stage(
            run_dir,
            package_copy,
            outcome="eval_failed",
            reason=f"eval JSON missing primary metric {name}",
            base_sha=base_sha,
            hypothesis=hypothesis,
            stage=stage,
            cycle_n=cycle_n,
            metrics=None,
            feature_id=feature_id,
        )
    if stage == "search_edit":
        from absolute.store import read_json

        scoreboard = read_json(run_dir / "scoreboard.json")
        reason = search_keep_reason(charter, pre_metrics, metrics, scoreboard["baseline"])
        if reason is None:
            reason = search_keep_reason(charter, scoreboard["best"], metrics, scoreboard["baseline"])
    else:
        reason = accuracy_keep_reason(charter, pre_metrics, metrics)
    if reason and reason.startswith("eval JSON missing"):
        return _record_stage(
            run_dir,
            package_copy,
            outcome="eval_failed",
            reason=reason,
            base_sha=base_sha,
            hypothesis=hypothesis,
            stage=stage,
            cycle_n=cycle_n,
            metrics=None,
            feature_id=feature_id,
        )
    keep = reason is None
    return _record_stage(
        run_dir,
        package_copy,
        outcome="keep" if keep else "revert",
        reason="" if keep else str(reason),
        base_sha=base_sha,
        hypothesis=hypothesis,
        stage=stage,
        cycle_n=cycle_n,
        metrics=metrics,
        feature_id=feature_id,
        keep_metrics=metrics if keep else None,
    )


def complete_cycle(run_dir: Path, charter: dict[str, Any], *, method_satisfied: bool) -> None:
    _runner_only(charter)
    from absolute.store import atomic_write, read_json

    del method_satisfied
    scoreboard = read_json(run_dir / "scoreboard.json")
    scoreboard["cycles"] = int(scoreboard.get("cycles", 0)) + 1
    atomic_write(run_dir / "scoreboard.json", scoreboard)
    run = load_run(run_dir)
    feature = run.get("admitted_feature") or {}
    verdict = run.get("method_verdict") or {}
    feature_id = str(feature.get("feature_id") or "").strip() if isinstance(feature, dict) else ""
    if feature_id:
        method = str(verdict.get("verdict") or "").strip() if isinstance(verdict, dict) else ""
        kept_ids = {
            str(item.get("id") or "")
            for item in (run.get("kept_features") or [])
            if isinstance(item, dict)
        }
        if feature_id in kept_ids:
            run["board_note"] = f"{feature_id} kept; method {method}" if method else f"{feature_id} kept"
        else:
            run["board_note"] = f"{feature_id} not kept"
    run["admitted_feature"] = None
    run["status"] = "running"
    run["stop_reason"] = ""
    run["stage"] = "search" if run.get("search") else "application"
    save_run(run_dir, run)
    write_handoff(run_dir)


def unique_proposals(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in proposals:
        feature_id = str(item.get("feature_id") or "")
        if not feature_id or feature_id in seen:
            continue
        seen.add(feature_id)
        unique.append(item)
    return unique


def known_feature_ids(run: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for key in ("kept_features", "rejected_features"):
        for entry in run.get(key) or []:
            if isinstance(entry, dict) and entry.get("id"):
                found.add(str(entry["id"]))
    return found


def round_is_nothing_new(proposals: list[dict[str, Any]], run: dict[str, Any]) -> bool:
    unique = unique_proposals(proposals)
    if not unique:
        return False
    known = known_feature_ids(run)
    return all(str(item.get("feature_id") or "") in known for item in unique)


def _append_listed_feature(run: dict[str, Any], key: str, feature_id: str, summary: str) -> None:
    items = [item for item in (run.get(key) or []) if isinstance(item, dict)]
    if any(str(item.get("id") or "") == feature_id for item in items):
        run[key] = items
        return
    items.append({"id": feature_id, "summary": summary})
    run[key] = items


def record_rejections(run_dir: Path, proposals: list[dict[str, Any]]) -> None:
    from absolute.store import load_run, save_run

    run = load_run(run_dir)
    for item in proposals:
        feature_id = str(item.get("feature_id") or "")
        if not feature_id or feature_id in known_feature_ids(run):
            continue
        _append_listed_feature(run, "rejected_features", feature_id, str(item.get("summary") or ""))
    save_run(run_dir, run)


def _limitation_lines(journal: list[dict[str, Any]]) -> list[str]:
    lines = []
    for entry in journal:
        if entry.get("outcome") not in ("revert", "bad_edit", "eval_failed"):
            continue
        stage = entry.get("stage") or entry.get("tag") or "cycle"
        detail = entry.get("error") or entry.get("hypothesis") or entry.get("outcome")
        lines.append(f"{stage}: {entry.get('outcome')} {detail}")
    return lines[-10:]


def stop_run(run_dir: Path, reason: str) -> None:
    from absolute.store import read_json

    charter = read_json(run_dir / "charter.json")
    _runner_only(charter)
    run = load_run(run_dir)
    run["status"] = "stopped"
    run["stop_reason"] = reason
    run["stage"] = ""
    save_run(run_dir, run)
    write_handoff(run_dir)


def stop_nothing_new(run_dir: Path) -> None:
    stop_run(run_dir, "nothing_new")


def cycle(run_dir: Path, charter: dict[str, Any]) -> dict[str, Any]:
    _runner_only(charter)
    run = load_run(run_dir)
    command = charter.get("eval_command")
    if not command:
        raise ValueError("eval command is null")
    if run.get("status") != "running":
        raise RuntimeError(f"cycle requires status running, found {run.get('status')}")
    package_copy = Path(run["package_copy"])
    admit_record = run.get("open_admit")
    if not admit_record:
        if not _tree_matches_script(run, package_copy):
            restore = run.get("script_head") or head_sha(package_copy)
            if _until_target(charter):
                return _repair_attempt(
                    run_dir,
                    charter,
                    package_copy,
                    "package copy changed without an admit",
                    restore,
                    "",
                    "bad_edit",
                    "",
                    None,
                )
            _stop_human(
                run_dir,
                package_copy,
                "package copy changed without an admit",
                restore,
                "",
            )
        raise ValueError("cycle requires an open admit")
    hypothesis = str(admit_record["hypothesis"])
    base = str(admit_record["sha"])
    tag = str(admit_record["tag"])
    feature_id = admit_record.get("feature_id")

    def fail_open(outcome: str, reason: str) -> dict[str, Any]:
        if _until_target(charter):
            return _repair_attempt(
                run_dir,
                charter,
                package_copy,
                reason,
                base,
                hypothesis,
                outcome,
                tag,
                feature_id,
            )
        _stop_human(run_dir, package_copy, reason, base, hypothesis)
        raise RuntimeError(reason)

    paths = changed_paths(package_copy, base)
    if charter.get("edit_policy") == "except_immutable":
        immutable_paths = set(charter.get("immutable") or [])
        blocked = [path for path in paths if path in immutable_paths]
        blocked_reason = "edit changed an immutable file: " + ", ".join(blocked)
    else:
        mutable = set(charter.get("mutable", []))
        blocked = [path for path in paths if path not in mutable]
        blocked_reason = "edit outside mutable paths: " + ", ".join(blocked)
    if blocked:
        return fail_open("bad_edit", blocked_reason)
    try:
        check_immutable(run_dir, package_copy)
        metrics = run_eval(list(command), package_copy, float(charter.get("eval_timeout_sec", 60)))
    except Exception as exc:
        if isinstance(exc, EvalFailure):
            write_text(run_dir / "eval" / "error.stdout.txt", exc.stdout)
            write_text(run_dir / "eval" / "error.stderr.txt", exc.stderr)
            return fail_open("eval_failed", str(exc))
        return fail_open("bad_edit", str(exc))

    from absolute.store import atomic_write, read_json

    scoreboard = read_json(run_dir / "scoreboard.json")
    try:
        outcome = judge(charter, scoreboard["best"], metrics)
    except KeyError as exc:
        return fail_open("eval_failed", str(exc))
    scoreboard["cycles"] += 1
    entry: dict[str, Any] = {
        "admit_sha": base,
        "at": now(),
        "cycle": scoreboard["cycles"],
        "feature_id": admit_record.get("feature_id"),
        "hypothesis": hypothesis,
        "metrics": metrics,
        "outcome": outcome,
        "tag": admit_record["tag"],
    }
    attempt = run_dir / "attempts" / f"{scoreboard['cycles']:03d}.patch"
    capture_patch_from(package_copy, attempt, base)
    entry["patch"] = str(attempt.relative_to(run_dir)).replace("\\", "/")
    run = load_run(run_dir)
    if outcome == "keep":
        sha = commit_from(package_copy, base, f"absolute: {hypothesis}")
        entry["commit"] = sha
        run["script_head"] = sha
        scoreboard["best"] = metrics
        scoreboard["keeps"] += 1
        scoreboard["no_keep_streak"] = 0
        if admit_record["tag"] == "implementation":
            scoreboard["implementation_keep_streak"] = int(scoreboard.get("implementation_keep_streak", 0)) + 1
        else:
            scoreboard["implementation_keep_streak"] = 0
    else:
        reset_to(package_copy, base)
        scoreboard["no_keep_streak"] += 1
    run["open_admit"] = None
    save_run(run_dir, run)
    atomic_write(run_dir / "scoreboard.json", scoreboard)
    append_journal(run_dir, entry)
    apply_stops(run_dir, charter, scoreboard)
    write_handoff(run_dir)
    return entry


def install_eval(run_dir: Path, charter: dict[str, Any], candidate: Path, dest_rel: str) -> dict[str, Any]:
    if (run_dir / "scoreboard.json").exists():
        raise ValueError("install-eval refuses after baseline")
    run = load_run(run_dir)
    if run.get("status") not in ("surveying", "awaiting_gate_b"):
        raise ValueError("install-eval requires a captured package and no baseline")
    if charter.get("eval_command"):
        raise ValueError("eval command is already set")
    if not run.get("package_copy"):
        raise ValueError("capture a package before install-eval")
    try:
        candidate.resolve().relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError("candidate must live under the run folder") from exc
    relative = Path(dest_rel.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("dest must be a package-relative path")
    package_copy = Path(run["package_copy"])
    dest = package_copy / relative
    existed = dest.is_file()
    previous = dest.read_bytes() if existed else None
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate, dest)
    command = [sys.executable, relative.as_posix()]
    try:
        metrics = run_eval(command, package_copy, float(charter.get("eval_timeout_sec", 60)))
        primary = charter["metrics"]["primary"]["name"]
        missing = [primary] if primary not in metrics else []
        missing.extend(item["name"] for item in protected_metrics(charter) if item["name"] not in metrics)
        if missing:
            raise ValueError("eval JSON missing " + ", ".join(missing))
    except Exception:
        if existed and previous is not None:
            dest.write_bytes(previous)
        elif dest.exists():
            dest.unlink()
        raise
    dest_key = relative.as_posix()
    immutable = list(charter.get("immutable") or [])
    if dest_key not in immutable:
        immutable.append(dest_key)
    charter["immutable"] = immutable
    charter["eval_command"] = command
    from absolute.store import atomic_write

    atomic_write(run_dir / "charter.json", charter)
    sha = commit_copy(package_copy, "absolute: install eval")
    run = load_run(run_dir)
    run["script_head"] = sha
    save_run(run_dir, run)
    return metrics


def resume(run_dir: Path, charter: dict[str, Any]) -> None:
    run = load_run(run_dir)
    if run.get("status") != "needs_human":
        raise ValueError(f"resume requires status needs_human, found {run.get('status')}")
    package_copy = Path(run["package_copy"])
    if _dirty_paths(package_copy):
        raise ValueError("resume requires a clean package copy")
    expected = run.get("immutable_hashes") or {}
    if expected:
        current = hash_tree(package_copy, list(expected))
        if current != expected:
            raise ValueError("immutable files differ from the last baseline")
    baseline_command = run.get("baseline_eval_command")
    if baseline_command is not None and list(charter.get("eval_command") or []) != list(baseline_command):
        raise ValueError("eval command differs from the last baseline")
    run["status"] = "running"
    run["open_admit"] = None
    run["stop_reason"] = ""
    save_run(run_dir, run)
    write_handoff(run_dir)


def _dirty_paths(package_copy: Path) -> list[str]:
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=package_copy,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = []
    for line in status.stdout.splitlines():
        if line.strip():
            paths.append(line[3:].strip().replace("\\", "/"))
    return paths


def _assert_clean(package_copy: Path) -> None:
    dirty = _dirty_paths(package_copy)
    unexpected = [path for path in dirty if Path(path).name != "VALIDATION.md"]
    if unexpected:
        raise RuntimeError("measured promotion has edits outside VALIDATION.md: " + ", ".join(unexpected))
    if dirty:
        commit_copy(package_copy, "absolute: validation procedure")


def has_measured_keep(run_dir: Path) -> bool:
    return any(entry.get("outcome") == "keep" for entry in read_journal(run_dir))


def ballots_allow_field_test(ballots: dict[str, Any]) -> None:
    experts = ballots.get("experts", [])
    if len(experts) < 3:
        raise ValueError("field-test promotion needs at least 3 expert ballots")
    for expert in experts:
        vote = expert.get("vote")
        if vote == "definitely":
            raise ValueError("experts cannot vote definitely; use field-test or reject")
        if vote == "reject":
            raise ValueError("a reject vote blocks field-test promotion")
        if vote != "field-test":
            raise ValueError("vote must be field-test or reject")
        if not str(expert.get("could_be_worse_if", "")).strip():
            raise ValueError("each field-test vote must say how the change could be worse")


def promote_package(
    run_dir: Path,
    source_package: Path,
    package_copy: Path,
    basis: str,
) -> Path:
    if basis not in ("measured", "field-test"):
        raise ValueError("basis must be measured or field-test")
    if basis == "measured" and not has_measured_keep(run_dir):
        raise ValueError("measured promotion requires a kept cycle")
    if basis == "field-test":
        if has_measured_keep(run_dir):
            raise ValueError("a measured keep must be promoted with --basis measured")
        ballot_path = run_dir / "ballots.json"
        if not ballot_path.exists():
            raise ValueError("field-test promotion requires ballots.json")
        ballots_allow_field_test(json.loads(ballot_path.read_text(encoding="utf-8")))
    validation_ready(package_copy)
    if basis == "measured":
        _assert_clean(package_copy)
    else:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=package_copy,
            check=True,
            capture_output=True,
            text=True,
        )
        if status.stdout.strip():
            commit_copy(package_copy, "absolute: field-test candidate")
    from absolute.naming import next_package_name
    from absolute.package import copy_package
    from absolute.store import atomic_write

    destination = source_package.parent / next_package_name(source_package.name)
    copy_package(package_copy, destination)
    atomic_write(
        destination / "ABSOLUTE_STATUS.json",
        {
            "basis": basis,
            "framework": "Absolute",
            "promoted_at": now(),
            "robot_validated": False,
            "run": run_dir.name,
            "version": "1.0",
        },
    )
    return destination
