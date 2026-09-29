"""Requirements-first evaluator preparation and frozen benchmark validation."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from absolute.contract import normalize_metric, resolve_pointer
from absolute.launch import WORKER_MODEL, report, run_process
from absolute.package import copy_package, file_hash
from absolute.prompts import render_prompt
from absolute.store import atomic_write, load_run, read_json, save_run

MANIFEST = "eval/benchmark.json"
SKIP = {".git", ".venv", "venv", "build", "install", "log", "__pycache__", "node_modules"}


class EvaluationBlocked(RuntimeError):
    pass


def inventory(package: Path) -> dict[str, Any]:
    assets: dict[str, Any] = {"evaluators": [], "tests": [], "data": [], "build": [], "truncated": False}
    count = 0
    for folder, directories, files in os.walk(package):
        directories[:] = sorted(name for name in directories if name not in SKIP and not name.startswith("."))
        for name in sorted(files):
            count += 1
            if count > 20000:
                assets["truncated"] = True
                return assets
            relative = (Path(folder) / name).relative_to(package).as_posix()
            lower = name.lower()
            category = None
            if lower in ("absolute-evaluation.json", "evaluate.py", "benchmark.py", "eval.py"):
                category = "evaluators"
            elif lower.startswith("test_") or lower.endswith(("_test.py", "_test.cpp")):
                category = "tests"
            elif lower.endswith((".bag", ".mcap", ".csv", ".npz", ".npy", ".parquet")):
                category = "data"
            elif lower in ("cmakelists.txt", "package.xml", "pyproject.toml", "package.json", "makefile"):
                category = "build"
            if category and len(assets[category]) < 100:
                assets[category].append(relative)
    return assets


def command_files(command: list[str], package: Path) -> list[Path]:
    found = []
    for index, argument in enumerate(command):
        candidate = Path(argument)
        if index and command[index - 1] == "-m":
            module = package.joinpath(*argument.split("."))
            for path in (module.with_suffix(".py"), module / "__main__.py", module / "__init__.py"):
                if path.is_file():
                    found.append(path.resolve())
            continue
        path = candidate if candidate.is_absolute() else package / candidate
        if path.is_file():
            found.append(path.resolve())
    return list(dict.fromkeys(found))


def validate_command(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(part, str) and part.strip() for part in value):
        raise ValueError("a command must be a nonempty string array")
    if any(part in ("-c", "-e", "--eval", "-Command", "/c", "/C", "--collect-only") for part in value) or Path(value[0]).stem.lower() in ("true", "echo"):
        raise ValueError("inline or collection-only commands are not regression gates")
    return list(value)


def _launch(run_dir: Path, launcher: Callable, role: str, **fields) -> dict:
    from absolute.engine import _tree_matches_script, reset_to

    run = load_run(run_dir)
    folder = run_dir / "workers" / "setup"
    output = folder / f"{role}-result.json"
    output.unlink(missing_ok=True)
    brief = {
        "role": role, "cycle": 0, "run": str(run_dir), "package_copy": run["package_copy"],
        "framework_root": str(Path(__file__).resolve().parents[1]),
        "model": os.environ.get("ABSOLUTE_MODEL") or WORKER_MODEL,
        "brief_path": str(folder / f"{role}.json"), "output": str(output), **fields,
    }
    brief["prompt"] = render_prompt(brief)
    if len(json.dumps(brief).encode("utf-8")) > 64000:
        raise EvaluationBlocked("setup brief exceeds 64KB; narrow the scenario or asset inventory")
    atomic_write(Path(brief["brief_path"]), brief)
    report(run_dir, "setup_worker", role=role)
    package = Path(run["package_copy"])
    protected = [run_dir / "run.json", Path(run["scenario_path"]), run_dir / "eval" / "plan.json"]
    snapshot = {path: path.read_bytes() if path.is_file() else None for path in protected}
    try:
        if launcher is None:
            raise EvaluationBlocked("evaluation setup needs a worker launcher")
        launcher(brief)
    finally:
        tampered = False
        for path, original in snapshot.items():
            current = path.read_bytes() if path.is_file() else None
            if current != original:
                tampered = True
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(original)
        if not _tree_matches_script(run, package):
            reset_to(package, run["script_head"])
            tampered = True
        if tampered:
            raise EvaluationBlocked("setup worker changed the candidate or runner-owned files")
    payload = read_json(output)
    if not isinstance(payload, dict):
        raise ValueError(f"{role} must return one object")
    return payload


def _coverage(run_dir: Path, plan: dict, measured_ids: set[str], limitations: list[str]) -> None:
    requirements = []
    for item in plan["requirements"]:
        present = sorted(set(item.get("metrics") or []) & measured_ids)
        requirements.append({
            "text": item["text"], "metrics": present,
            "status": "measured_proxy" if present else "unmeasured",
            "validation_needed": item.get("validation_needed") or "Independent representative data and validation are still required.",
        })
    document = {"requirements": requirements, "limitations": limitations, "sota_verified": False, "robot_validated": False}
    atomic_write(run_dir / "eval" / "coverage.json", document)
    lines = ["# Evaluation coverage", "", "Measured proxies are not verified domain coverage.", ""]
    for item in requirements:
        lines.extend([f"- {item['status']}: {item['text']}", f"  Needed: {item['validation_needed']}"])
    lines.extend(["", "## Limitations", *[f"- {item}" for item in limitations]])
    (run_dir / "eval" / "coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def plan_evaluation(run_dir: Path, launcher: Callable, explicit_metrics: list[dict] | None) -> dict:
    run = load_run(run_dir)
    package = Path(run["package_copy"])
    scenario = Path(run["scenario_path"]).read_text(encoding="utf-8")
    path = run_dir / "eval" / "plan.json"
    if path.is_file():
        plan = read_json(path)
        if plan["scenario_hash"] != file_hash(Path(run["scenario_path"])):
            raise EvaluationBlocked("scenario changed; start a new benchmark version in a new run")
        return plan
    assets = inventory(package)
    atomic_write(run_dir / "eval" / "assets.json", assets)
    if explicit_metrics:
        plan = {"metrics": explicit_metrics, "requirements": []}
    else:
        plan = _launch(run_dir, launcher, "evaluation_plan", scenario_text=scenario, assets=assets)
    metrics = [normalize_metric(item, scenario) for item in plan.get("metrics", [])]
    if not metrics or not any(item["role"] == "objective" for item in metrics):
        raise EvaluationBlocked("evaluation plan needs at least one application objective")
    if len({item["id"] for item in metrics}) != len(metrics):
        raise EvaluationBlocked("evaluation plan contains duplicate metric IDs")
    for metric in metrics:
        metric.setdefault("aggregation", "worst" if metric["role"] == "protected" else "median")
        metric.setdefault("max_regression", 0.0)
        metric.setdefault("min_effect", metric["noise"])
        if metric["role"] == "protected" and metric["target"] is not None:
            metric.setdefault("hard_limit", metric["target"])
    requirements = plan.get("requirements") or []
    if not isinstance(requirements, list) or any(not isinstance(item, dict) or not str(item.get("text") or "").strip() for item in requirements):
        raise EvaluationBlocked("requirements must contain nonempty text")
    texts = {item["text"] for item in requirements}
    for line in scenario.splitlines():
        text = line.strip()
        if text and not text.startswith("#") and text not in texts:
            requirements.append({"text": text, "metrics": [], "validation_needed": "Confirm executable evidence for this scenario statement."})
    plan = {"metrics": metrics, "requirements": requirements, "scenario_hash": file_hash(Path(run["scenario_path"]))}
    atomic_write(path, plan)
    _coverage(run_dir, plan, set(), ["Benchmark qualification has not completed."])
    return plan


def _auto_validation(package: Path, assets: dict) -> list[list[str]]:
    tests = [path for path in assets["tests"] if path.endswith(".py")]
    if tests and all("unittest" in (package / path).read_text(encoding="utf-8") for path in tests):
        folders = sorted({str(Path(path).parent) for path in tests})
        return [[sys.executable, "-B", "-m", "unittest", "discover", "-s", folder] for folder in folders]
    return []


def _manifest_files(payload: dict, package: Path) -> list[Path]:
    declared = payload.get("files") or []
    if not isinstance(declared, list) or not all(isinstance(item, str) for item in declared):
        raise ValueError("benchmark files must be a list of paths")
    paths = []
    payload["directories"] = {}
    for name in declared:
        path = Path(name)
        path = path if path.is_absolute() else package / path
        if path.is_dir():
            files = sorted(item.resolve() for item in path.rglob("*") if item.is_file() and "__pycache__" not in item.parts)
            payload["directories"][str(path.resolve())] = [str(item) for item in files]
            paths.extend(files)
        elif path.is_file():
            paths.append(path.resolve())
        else:
            raise EvaluationBlocked(f"missing benchmark asset: {path}")
    paths.extend(command_files(payload["eval_command"], package))
    for command in payload["validation_commands"]:
        paths.extend(command_files(command, package))
    return list(dict.fromkeys(paths))


def run_validation(run_dir: Path, commands: list[list[str]], package: Path, timeout: float, label: str) -> None:
    for index, command in enumerate(commands, start=1):
        report(run_dir, "regression_test", label=label, index=index)
        result = run_process(command, package, timeout, env=dict(os.environ, ABSOLUTE_PACKAGE=str(package), PYTHONDONTWRITEBYTECODE="1"))
        output = result.stdout + "\n" + result.stderr
        (run_dir / "eval" / f"{label}-test-{index}.log").write_text(output, encoding="utf-8")
        if result.returncode or re.search(r"Ran 0 tests|no tests ran|0 tests? (?:found|collected)", output, re.I):
            raise EvaluationBlocked(f"regression gate failed: {command}; {output[-1500:]}")


def verify_benchmark(run_dir: Path) -> dict | None:
    run = load_run(run_dir)
    expected = run.get("benchmark_sha256")
    if not expected:
        return None
    path = run_dir / MANIFEST
    if not path.is_file() or file_hash(path) != expected:
        raise EvaluationBlocked("benchmark manifest changed; create a new benchmark version")
    manifest = read_json(path)
    for name, digest in manifest["hashes"].items():
        path = Path(name)
        if not path.is_file() or file_hash(path) != digest:
            raise EvaluationBlocked(f"benchmark asset changed: {name}")
    for name, expected in manifest.get("directories", {}).items():
        actual = sorted(str(item.resolve()) for item in Path(name).rglob("*") if item.is_file() and "__pycache__" not in item.parts)
        if actual != expected:
            raise EvaluationBlocked(f"benchmark directory changed: {name}")
    charter_path = run_dir / "charter.json"
    if charter_path.is_file() and read_json(charter_path)["eval_command"] != manifest["eval_command"]:
        raise EvaluationBlocked("benchmark evaluator command changed")
    return manifest


def ensure_evaluation(run_dir: Path, launcher: Callable, command: list[str] | None, plan: dict) -> dict:
    from absolute.engine import _tree_matches_script, reset_to, run_eval

    run = load_run(run_dir)
    package = Path(run["package_copy"])
    if run.get("benchmark_sha256"):
        return verify_benchmark(run_dir)
    assets = read_json(run_dir / "eval" / "assets.json")
    discovered = False
    if not command:
        candidates = [name for name in assets["evaluators"] if name.endswith(".py")]
        if len(candidates) == 1:
            command = [sys.executable, candidates[0]]
            discovered = True
    saved = run_dir / "eval" / "proposal.json"
    if saved.is_file():
        payload = read_json(saved)
    elif (package / "absolute-evaluation.json").is_file():
        payload = read_json(package / "absolute-evaluation.json")
        payload["origin"] = "declared"
    elif command and _auto_validation(package, assets):
        payload = {
            "eval_command": command, "validation_commands": _auto_validation(package, assets),
            "files": assets["tests"] + assets["data"], "origin": "discovered" if discovered else "supplied",
            "oracle": "User-supplied evaluator; semantic validity is not independently established.",
            "limitations": ["No independent held-out evaluation or hardware validation has been performed."],
        }
    else:
        folder = run_dir / "eval" / "benchmark"
        folder.mkdir(parents=True, exist_ok=True)
        payload = _launch(
            run_dir, launcher, "benchmark_build", plan=plan, assets=assets,
            eval_command=command, benchmark_dir=str(folder), python=sys.executable,
        )
        payload["origin"] = "generated"
        if not _tree_matches_script(run, package):
            reset_to(package, run["script_head"])
            raise EvaluationBlocked("benchmark builder changed the candidate package")
    missing = payload.get("missing_evidence")
    if missing:
        _coverage(run_dir, plan, set(), [str(item) for item in missing])
        raise EvaluationBlocked("additional evaluation evidence required: " + "; ".join(map(str, missing)))
    payload["eval_command"] = validate_command(command or payload.get("eval_command"))
    commands = payload.get("validation_commands")
    if not isinstance(commands, list) or not commands:
        raise EvaluationBlocked("a benchmark needs an independent regression command")
    payload["validation_commands"] = [validate_command(item) for item in commands]
    if payload["eval_command"] in payload["validation_commands"]:
        raise EvaluationBlocked("the evaluator cannot be its own regression gate")
    if not str(payload.get("oracle") or "").strip():
        raise EvaluationBlocked("benchmark must document its oracle")
    paths = _manifest_files(payload, package)
    paths.extend(package / name for name in assets["tests"])
    paths.extend([Path(run["scenario_path"]), run_dir / "eval" / "plan.json"])
    hashes = {str(path.resolve()): file_hash(path) for path in paths}
    atomic_write(saved, payload)
    timeout = float(run["setup"]["timeout_sec"])
    run_validation(run_dir, payload["validation_commands"], package, timeout, "qualification")
    measured = run_eval(payload["eval_command"], package, timeout)
    check_case_evidence(payload, measured)
    from absolute.contract import _require_number

    metrics = []
    unavailable = []
    for metric in plan["metrics"]:
        try:
            value = resolve_pointer(measured, metric["path"])
        except KeyError:
            if metric["role"] == "protected" or metric.get("hard_limit") is not None or run["setup"].get("metric") == metric["id"]:
                raise EvaluationBlocked(f"required measurement is unavailable: {metric['id']}") from None
            unavailable.append(metric["id"])
            continue
        _require_number(value, metric["id"])
        metrics.append(metric)
    if not any(metric["role"] == "objective" for metric in metrics):
        raise EvaluationBlocked("no planned objective can be measured")
    controls = payload.get("negative_controls") or []
    if payload["origin"] == "generated":
        required = {item["id"] for item in metrics if item["role"] == "objective"}
        witnessed = set()
        for index, control in enumerate(controls[:8]):
            metric = next((item for item in metrics if item["id"] == control.get("metric")), None)
            relative = Path(str(control.get("path") or ""))
            if metric is None or relative.is_absolute() or ".." in relative.parts or not (package / relative).is_file():
                raise EvaluationBlocked("negative control must name an existing candidate file and planned metric")
            if str((package / relative).resolve()) in hashes:
                raise EvaluationBlocked("negative control cannot change benchmark assets")
            with tempfile.TemporaryDirectory() as directory:
                probe = Path(directory) / "candidate"
                copy_package(package, probe)
                (probe / relative).write_text(str(control["replacement"]), encoding="utf-8")
                probe_command = []
                for argument in payload["eval_command"]:
                    try:
                        mapped = Path(argument).resolve().relative_to(package.resolve()) if Path(argument).is_absolute() else None
                    except ValueError:
                        mapped = None
                    probe_command.append(str(probe / mapped) if mapped is not None else argument)
                report(run_dir, "negative_control", index=index + 1, metric=metric["id"])
                bad = run_eval(probe_command, probe, timeout)
                before = float(resolve_pointer(measured, metric["path"]))
                after = float(resolve_pointer(bad, metric["path"]))
                loss = after - before if metric["direction"] == "minimize" else before - after
                if not math.isfinite(after) or loss <= metric["noise"]:
                    raise EvaluationBlocked(f"negative control did not worsen {metric['id']}")
                atomic_write(run_dir / "eval" / f"negative-control-{index + 1:03d}.json", {
                    "metric": metric["id"], "baseline": before, "control": after, "loss": loss,
                    "candidate_file": relative.as_posix(), "status": "sensitive",
                })
                witnessed.add(metric["id"])
        if not required <= witnessed:
            raise EvaluationBlocked("generated benchmark needs a sensitivity control for each objective")
    if not _tree_matches_script(run, package):
        reset_to(package, run["script_head"])
        raise EvaluationBlocked("benchmark qualification changed the candidate package")
    for name, digest in hashes.items():
        if not Path(name).is_file() or file_hash(Path(name)) != digest:
            raise EvaluationBlocked(f"qualification changed benchmark asset: {name}")
    limitations = [str(item) for item in payload.get("limitations") or []]
    if unavailable:
        limitations.append("Additional measurements required: " + ", ".join(unavailable))
    limitations.append("Sensitivity checks do not prove oracle correctness, domain completeness, or SOTA.")
    manifest = {**payload, "hashes": hashes, "version": 1, "qualification": "executable", "limitations": limitations}
    manifest["available_metrics"] = sorted(measured)
    manifest["measured_metric_ids"] = [metric["id"] for metric in metrics]
    atomic_write(run_dir / MANIFEST, manifest)
    run = load_run(run_dir)
    run["benchmark_sha256"] = file_hash(run_dir / MANIFEST)
    run["evaluation_scope"] = payload["origin"]
    save_run(run_dir, run)
    _coverage(run_dir, plan, {metric["id"] for metric in metrics}, limitations)
    return manifest


def check_case_evidence(document: dict[str, Any], payload: dict[str, Any]) -> None:
    expected = {item["id"] for item in document.get("cases") or []}
    actual = payload.get("_cases", [])
    if not isinstance(actual, list) or not all(isinstance(item, str) for item in actual):
        raise ValueError("evaluator _cases must be a list of executed case IDs")
    if expected - set(actual):
        raise ValueError("evaluator did not execute required benchmark cases: " + ", ".join(sorted(expected - set(actual))))