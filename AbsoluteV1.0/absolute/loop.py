"""Durable optimization coordinator with fresh, bounded-context workers."""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from absolute import __version__
from absolute.contract import (
    accept_discovered_metrics,
    bind_metrics,
    compose_contract,
    live_obligations,
    load_contract,
    obligation_sentences,
    store_contract,
    uncovered_obligations,
)
from absolute.engine import (
    LATENCY_BUDGET_MS,
    TERMINAL_STOPS,
    _repair_attempt,
    _tree_matches_script,
    citations_are_external,
    citations_fetch,
    complete_cycle,
    ensure_copy_repo,
    head_sha,
    measurements_at_target,
    measure_search,
    now,
    record_baseline,
    record_rejections,
    reset_to,
    round_is_nothing_new,
    run_eval,
    runner_authority,
    score_stage,
    search_metric_specs,
    stop_run,
    status_text,
    unique_proposals,
    validate_charter,
    write_handoff,
)
from absolute.naming import allocate_run_id
from absolute.package import copy_package, file_hash, hash_tree, message_fields, message_schema
from absolute.prompts import render_prompt
from absolute.launch import LaunchError, WORKER_MODEL, report
from absolute.store import atomic_write, checkpoint_cycle, load_run, read_journal, read_json, recover_checkpoint, repair_journal, run_lock, save_run

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
STAGE_ATTEMPTS = 5
BOARD_ATTEMPTS = 2
Launcher = Callable[[dict], None]


class BoardRetry(Exception):
    """The proposal round did not admit a feature while a required output is still off target."""


def metric_discovery_queries(package_name: str) -> list[str]:
    subject = package_name.strip() or "package"
    return [
        f"numeric results {subject} already computes that later edits should improve",
        f"numeric results {subject} must not regress while another result improves",
        f"scenario sentences for {subject} that no current numeric result witnesses",
    ]


def metric_followup_queries(package_name: str) -> list[str]:
    subject = package_name.strip() or "package"
    return [
        f"new numeric results {subject} can add without changing a sealed metric",
        f"sealed results for {subject} that must stay unchanged",
        f"unwitnessed scenario sentences for {subject} that a new numeric result could witness",
    ]


def research_queries(metric: str, direction: str, package_name: str, noise: float) -> list[str]:
    return [
        f"methods that {direction} {metric} on a stack like {package_name}",
        f"defects in {package_name} that keep {metric} away from its target",
        f"measurement noise around {noise} for {metric} and edits that must not touch the scorer",
    ]


def literature_queries(feature: str, package_name: str) -> list[str]:
    subject = feature.strip() or package_name
    return [
        f"candidate methods for {subject} on {package_name}",
        f"other candidate methods for {subject} that are not the first list",
        f"evidence that methods for {subject} are current",
        f"evidence that older methods for {subject} have been superseded",
        f"integration constraints for {subject} in {package_name}",
        f"interfaces in {package_name} that a {subject} change must keep working",
        f"measured cost of methods for {subject}",
        f"measured latency cost of methods for {subject} on {package_name}",
    ]


def literature_backups(feature: str, package_name: str) -> list[str]:
    subject = feature.strip() or package_name
    return [
        f"additional candidate methods for {subject} beyond the assigned pair",
        f"additional current-evidence sources for {subject}",
        f"additional integration constraints for {subject} in {package_name}",
        f"additional measured-cost reports for {subject}",
    ]


def parse_decision(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("decision must be one object")
    if "changes" in payload:
        raise ValueError("decision must be exactly one change")
    level = payload.get("level")
    if level not in ("implementation", "tech-stack", "feature"):
        raise ValueError("decision level must be implementation, tech-stack, or feature")
    hypothesis = str(payload.get("hypothesis") or "").strip()
    if not hypothesis:
        raise ValueError("decision needs a hypothesis")
    feature_id = payload.get("feature_id")
    summary = payload.get("summary")
    if level == "feature":
        if not str(feature_id or "").strip() or not str(summary or "").strip():
            raise ValueError("a feature decision needs a feature id and a summary")
        feature_id = str(feature_id).strip()
        summary = str(summary).strip()
    else:
        if feature_id:
            raise ValueError("feature id is only valid for a feature change")
        feature_id = None
        summary = None
    return {
        "feature_id": feature_id,
        "hypothesis": hypothesis,
        "level": level,
        "summary": summary,
    }


def immutable_in_package(command: list[str], package: Path) -> list[str]:
    from absolute.evaluation import command_files

    found: list[str] = []
    root = package.resolve()
    for path in command_files(command, package):
        try:
            found.append(path.relative_to(root).as_posix())
        except ValueError:
            continue
    return found


def external_scorer_files(command: list[str], package: Path) -> list[Path]:
    from absolute.evaluation import command_files

    files: list[Path] = []
    root = package.resolve()
    for resolved in command_files(command, package):
        try:
            resolved.relative_to(root)
        except ValueError:
            files.append(resolved)
    return files


def build_charter(
    *,
    metric: str,
    direction: str,
    noise: float,
    target: float,
    eval_command: list[str],
    immutable: list[str],
    task: str,
    timeout: float,
) -> dict[str, Any]:
    return {
        "edit_policy": "except_immutable",
        "eval_command": list(eval_command),
        "eval_timeout_sec": timeout,
        "feature_catalog": [],
        "immutable": list(immutable),
        "loop": "until_target",
        "metrics": {
            "primary": {
                "direction": direction,
                "name": metric,
                "noise": noise,
                "target": target,
            },
            "protected": [],
        },
        "mutable": [],
        "stops": {"max_cycles": 1, "plateau": 1},
        "task": task,
    }


def _snapshot(paths: list[Path]) -> dict[str, bytes | None]:
    snap: dict[str, bytes | None] = {}
    for path in paths:
        snap[str(path)] = path.read_bytes() if path.is_file() else None
    return snap


def _tampered(snap: dict[str, bytes | None]) -> bool:
    for name, data in snap.items():
        path = Path(name)
        current = path.read_bytes() if path.is_file() else None
        if current != data:
            return True
    return False


def _restore(snap: dict[str, bytes | None]) -> None:
    for name, data in snap.items():
        path = Path(name)
        if data is None:
            if path.exists():
                path.unlink()
        elif not path.is_file() or path.read_bytes() != data:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)


def _materialize(brief: dict) -> dict:
    ready = dict(brief)
    ready["prompt"] = render_prompt(ready)
    if ready.get("role") == "optimize" and len(json.dumps(ready).encode("utf-8")) > 64000:
        raise RuntimeError("optimizer brief exceeds 64KB; shorten the scenario or metric descriptions")
    path = Path(ready["brief_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    if ready.get("output"):
        Path(ready["output"]).parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, ready)
    return ready


def _launch_one(launcher: Launcher, brief: dict) -> None:
    launcher(_materialize(brief))


def _launch_all(launcher: Launcher, briefs: list[dict]) -> None:
    ready = [_materialize(brief) for brief in briefs]
    if len(ready) == 1:
        launcher(ready[0])
        return
    with ThreadPoolExecutor(max_workers=len(ready)) as pool:
        list(pool.map(launcher, ready))


def _retry(stage: str, fn):
    last: Exception | None = None
    for _ in range(STAGE_ATTEMPTS):
        try:
            return fn()
        except Exception as exc:
            last = exc
    raise RuntimeError(f"{stage} failed") from last


def _merge_matrix(cycle_n: int, queries: list[str], outputs: list[Path]) -> dict[str, Any]:
    agents = []
    for query, path in zip(queries, outputs):
        if not path.is_file():
            raise ValueError(f"missing research output {path.name}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("query") != query:
            raise ValueError("research worker changed the query")
        findings = payload.get("findings")
        if not isinstance(findings, list) or not findings or not all(str(item).strip() for item in findings):
            raise ValueError("research findings are empty")
        agents.append({"findings": [str(item) for item in findings], "query": query})
    got = [agent["query"] for agent in agents]
    if len(set(got)) != len(got):
        raise ValueError("research queries overlap")
    if set(got) != set(queries):
        raise ValueError("research queries do not match the assigned set")
    return {"agents": agents, "cycle": cycle_n}


def _base_brief(
    run_dir: Path,
    cycle_n: int,
    handoff: str,
    package: Path,
    charter: dict[str, Any],
    scoreboard: dict[str, Any],
) -> dict[str, Any]:
    primary = charter["metrics"]["primary"]
    return {
        "cycle": cycle_n,
        "framework_root": str(FRAMEWORK_ROOT),
        "goal": {
            "direction": primary["direction"],
            "metric": primary["name"],
            "noise": primary["noise"],
            "target": primary["target"],
        },
        "handoff": handoff,
        "immutable": list(charter.get("immutable") or []),
        "measurement": {"baseline": scoreboard.get("baseline"), "best": scoreboard.get("best")},
        "model": os.environ.get("ABSOLUTE_MODEL") or WORKER_MODEL,
        "package_copy": str(package),
        "run": str(run_dir),
        "skill": str(FRAMEWORK_ROOT / "SKILL.md"),
    }


def _read_discovery(outputs: list[Path], queries: list[str]) -> list[dict[str, Any]]:
    payloads = []
    for path, query in zip(outputs, queries):
        payload = _read_json(path)
        if payload.get("query") != query:
            raise ValueError("discovery worker changed the query")
        payloads.append(payload)
    return payloads


def _launch_discovery(
    run_dir: Path,
    launcher: Launcher,
    package: Path,
    scenario_text: str,
    queries: list[str],
    round_n: int,
    sealed_ids: list[str],
    gaps: list[str],
) -> list[dict[str, Any]]:
    folder = run_dir / "workers" / "discovery" / f"round-{round_n}"
    briefs = []
    outputs: list[Path] = []
    for index, query in enumerate(queries, start=1):
        output = folder / f"proposal-{index}.json"
        briefs.append(
            {
                "brief_path": str(folder / f"proposal-{index}-brief.json"),
                "cycle": 0,
                "discovery_round": round_n,
                "framework_root": str(FRAMEWORK_ROOT),
                "model": "grok-4.7-xhigh",
                "output": str(output),
                "package_copy": str(package),
                "query": query,
                "role": "metric_discover",
                "run": str(run_dir),
                "scenario_text": scenario_text,
                "sealed_metric_ids": list(sealed_ids),
                "skill": str(FRAMEWORK_ROOT / "SKILL.md"),
                "uncovered_behaviors": list(gaps),
            }
        )
        outputs.append(output)
    _launch_all(launcher, briefs)
    return _read_discovery(outputs, queries)


def _discover_metrics(
    run_dir: Path,
    launcher: Launcher,
    package: Path,
    scenario_text: str,
    eval_payload: dict[str, Any],
    round_n: int,
    sealed: list[dict[str, Any]] | None,
    gaps: list[str],
) -> list[dict[str, Any]]:
    queries = metric_discovery_queries(package.name) if round_n == 1 else metric_followup_queries(package.name)

    def once() -> list[dict[str, Any]]:
        payloads = _launch_discovery(
            run_dir,
            launcher,
            package,
            scenario_text,
            queries,
            round_n,
            [metric["id"] for metric in sealed or [] if metric["id"] != "latency_ms"],
            gaps,
        )
        return accept_discovered_metrics(
            payloads,
            eval_payload,
            scenario_text,
            sealed=sealed,
            gaps=gaps,
            latency_budget=0.0 if load_run(run_dir).get("search") else LATENCY_BUDGET_MS,
        )

    return _retry("metric discovery", once)


def _explicit_metrics(
    metric: str,
    direction: str,
    noise: float,
    target: float | None,
    protected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = [
        {
            "description": metric,
            "direction": direction,
            "id": metric,
            "noise": float(noise),
            "path": f"/{metric}",
            "role": "objective",
            "target": None if target is None else float(target),
            "witnesses": [],
        }
    ]
    for item in protected:
        if item["name"] == metric:
            continue
        row = {
            "description": item["name"],
            "direction": item["direction"],
            "id": item["name"],
            "noise": float(item["max_regression"]),
            "path": f"/{item['name']}",
            "role": "protected",
            "target": None if item.get("target") is None else float(item["target"]),
            "witnesses": [],
        }
        rows.append(row)
    return rows


def _write_sealed(
    run_dir: Path,
    charter: dict[str, Any],
    metrics: list[dict[str, Any]],
    scenario_text: str,
    obligations: list[str],
    round_n: int,
) -> None:
    bind_metrics(charter, metrics)
    validate_charter(charter)
    atomic_write(run_dir / "charter.json", charter)
    document = compose_contract(metrics, obligations, scenario_text, now())
    run = load_run(run_dir)
    run["contract_sha256"] = store_contract(run_dir, document)
    run["discovery_round"] = round_n
    run["uncovered_behaviors"] = uncovered_obligations(obligations, metrics, scenario_text)
    primary = charter["metrics"]["primary"]
    run["goal"] = {
        "direction": primary["direction"],
        "metric": primary["name"],
        "noise": primary["noise"],
        "target": primary["target"],
    }
    run["task"] = charter["task"]
    save_run(run_dir, run)


def _refresh_scoreboard(run_dir: Path, metrics: dict[str, Any]) -> None:
    path = run_dir / "scoreboard.json"
    if not path.is_file():
        return
    scoreboard = read_json(path)
    for key in ("baseline", "best"):
        current = scoreboard.get(key)
        if not isinstance(current, dict):
            continue
        for name, value in metrics.items():
            if name not in current:
                current[name] = value
    atomic_write(path, scoreboard)


def _extend_contract(run_dir: Path, launcher: Launcher, eval_payload: dict[str, Any]) -> dict[str, Any]:
    charter = read_json(run_dir / "charter.json")
    run = load_run(run_dir)
    if int(run.get("discovery_round") or 1) >= 2 or launcher is None:
        return charter
    document = load_contract(run_dir)
    if document is None:
        return charter
    scenario_text = Path(run["scenario_path"]).read_text(encoding="utf-8")
    obligations = live_obligations(scenario_text, list(document.get("obligations") or []))
    gaps = uncovered_obligations(obligations, document["metrics"], scenario_text)
    if not gaps:
        return charter
    package = Path(run["package_copy"])
    metrics = _discover_metrics(
        run_dir,
        launcher,
        package,
        scenario_text,
        eval_payload,
        2,
        document["metrics"],
        gaps,
    )
    _write_sealed(run_dir, charter, metrics, scenario_text, obligations, 2)
    _refresh_scoreboard(run_dir, eval_payload)
    return read_json(run_dir / "charter.json")


def _finish_gate(run_dir: Path, charter: dict[str, Any], eval_metrics: dict[str, Any]) -> None:
    run = load_run(run_dir)
    scenario_text = Path(run["scenario_path"]).read_text(encoding="utf-8")
    document = load_contract(run_dir)
    obligations = live_obligations(
        scenario_text,
        list(document.get("obligations") or []) if document else obligation_sentences(scenario_text),
    )
    metric_rows = list(document["metrics"]) if document else []
    gaps = uncovered_obligations(obligations, metric_rows, scenario_text)
    at_target = measurements_at_target(charter, eval_metrics)
    run["uncovered_behaviors"] = gaps
    run["proxy_saturated"] = at_target
    if run.get("search"):
        run["status"] = "running"
        run["stop_reason"] = ""
        run["success"] = False
        run["sota_verified"] = False
        run["stage"] = "search"
    elif at_target and gaps:
        run["success"] = False
        run["status"] = "stopped"
        run["stop_reason"] = "scenario_uncovered"
        run["stage"] = ""
    elif at_target:
        run["status"] = "stopped"
        run["stop_reason"] = "oracle_saturated"
        run["stage"] = ""
    else:
        run["status"] = "running"
        run["stop_reason"] = ""
    save_run(run_dir, run)
    write_handoff(run_dir)


def prepare_run(
    *,
    package: Path,
    scenario: Path,
    metric: str | None = None,
    direction: str | None = None,
    noise: float | None = None,
    target: float | None = None,
    eval_command: list[str] | None = None,
    runs_root: Path | None = None,
    timeout_sec: float = 60,
    task: str | None = None,
    launcher: Launcher | None = None,
    continuous: bool = False,
    eval_repeats: int = 3,
) -> Path:
    if not 1 <= eval_repeats <= 100:
        raise ValueError("eval_repeats must be between 1 and 100")
    explicit = metric is not None
    if explicit and (direction is None or noise is None or (target is None and not continuous)):
        raise ValueError("an explicit metric needs a direction, noise, and target")
    if not continuous and not eval_command:
        raise ValueError("legacy runs require an eval command")
    if not explicit and launcher is None:
        raise RuntimeError("metric discovery needs the worker launcher")
    scenario_path = scenario.resolve()
    if not scenario_path.is_file():
        raise FileNotFoundError(f"scenario file not found: {scenario_path}")
    scenario_text = scenario_path.read_text(encoding="utf-8")
    scenario_digest = file_hash(scenario_path)
    source = package.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"package directory not found: {source}")
    root = runs_root.resolve() if runs_root else FRAMEWORK_ROOT / "runs"
    run_name = allocate_run_id(root)
    run_dir = root / run_name
    run_dir.mkdir()
    for name in ("ideas", "sota", "eval", "attempts", "workers", "decisions"):
        (run_dir / name).mkdir()
    destination = run_dir / "package" / source.name
    copy_package(source, destination)
    ensure_copy_repo(destination)
    immutable = immutable_in_package(eval_command or [], destination)
    save_run(
        run_dir,
        {
            "created_at": now(),
            "discovery_round": 1,
            "entry": "evolve",
            "external_scorer": [str(path) for path in external_scorer_files(eval_command or [], destination)],
            "framework": "Absolute",
            "id": run_name,
            "package_copy": str(destination),
            "application_hash": "",
            "scenario_hash": scenario_digest,
            "scenario_path": str(scenario_path),
            "script_head": head_sha(destination),
            "source_package": str(source),
            "stage": "application",
            "status": "starting",
            "version": __version__,
            **({
                "search": {"eval_repeats": eval_repeats, "context_window_tokens": 500000},
                "setup_complete": False,
                "setup": {"eval_command": eval_command, "metric": metric, "direction": direction,
                          "noise": noise, "target": target, "timeout_sec": timeout_sec, "task": task},
            } if continuous else {}),
        },
    )
    if continuous:
        with run_lock(run_dir):
            _prepare_search_evaluation(run_dir, launcher)
        return run_dir
    report(run_dir, "baseline_started", package=str(destination))
    eval_metrics = run_eval(list(eval_command), destination, timeout_sec)
    if explicit:
        assert direction is not None and noise is not None and target is not None
        charter = build_charter(
            direction=direction,
            eval_command=list(eval_command),
            immutable=immutable,
            metric=metric,
            noise=noise,
            target=target,
            task=task or f"evolve {source.name} until {metric} {direction} reaches {target}",
            timeout=timeout_sec,
        )
        protected: list[dict[str, Any]] = []
        if "latency_ms" in eval_metrics and metric != "latency_ms":
            protected.append(
            {"direction": "minimize", "max_regression": 0.0 if continuous else LATENCY_BUDGET_MS, "name": "latency_ms"}
            )
        metric_rows = _explicit_metrics(metric, direction, noise, target, protected)
        missing = [row["id"] for row in metric_rows if row["id"] not in eval_metrics]
        if missing:
            raise RuntimeError("eval JSON missing " + ", ".join(missing))
    else:
        assert launcher is not None
        metric_rows = _discover_metrics(
            run_dir,
            launcher,
            destination,
            scenario_text,
            eval_metrics,
            1,
            None,
            [],
        )
        primary = next(row for row in metric_rows if row["role"] == "objective" and row["target"] is not None)
        charter = build_charter(
            direction=primary["direction"],
            eval_command=list(eval_command),
            immutable=immutable,
            metric=primary["id"],
            noise=primary["noise"],
            target=primary["target"],
            task=task or f"evolve {source.name} against its sealed metrics",
            timeout=timeout_sec,
        )
    obligations = obligation_sentences(scenario_text)
    _write_sealed(run_dir, charter, metric_rows, scenario_text, obligations, 1)
    charter = read_json(run_dir / "charter.json")
    if measurements_at_target(charter, eval_metrics) and _current_gaps(run_dir, scenario_text) and launcher is not None:
        charter = _extend_contract(run_dir, launcher, eval_metrics)
    run = load_run(run_dir)
    run["baseline_eval_command"] = list(eval_command)
    run["eval_mode"] = "measured"
    run["immutable_hashes"] = hash_tree(destination, immutable) if immutable else {}
    run["message_fields"] = message_fields(destination)
    run["message_schema"] = message_schema(destination)
    save_run(run_dir, run)
    if continuous:
        eval_metrics = measure_search(run_dir, read_json(run_dir / "charter.json"), "baseline-samples")
    record_baseline(run_dir, eval_metrics)
    atomic_write(run_dir / "eval" / "baseline.json", eval_metrics)
    _finish_gate(run_dir, read_json(run_dir / "charter.json"), eval_metrics)
    report(run_dir, "baseline_finished", metrics=eval_metrics, status=load_run(run_dir)["status"])
    return run_dir


def _prepare_search_evaluation(run_dir: Path, launcher: Launcher | None) -> bool:
    from absolute.evaluation import ensure_evaluation, plan_evaluation

    run = load_run(run_dir)
    settings = run["setup"]
    package = Path(run["package_copy"])
    run.update(status="starting", stage="evaluation_setup", stop_reason="")
    save_run(run_dir, run)
    try:
        if not _tree_matches_script(run, package):
            reset_to(package, run["script_head"])
        explicit = None
        if settings["metric"] is not None:
            explicit = _explicit_metrics(settings["metric"], settings["direction"], settings["noise"], settings["target"], [])
        plan = plan_evaluation(run_dir, launcher, explicit)
        manifest = ensure_evaluation(run_dir, launcher, settings["eval_command"], plan)
        rows = [metric for metric in plan["metrics"] if metric["id"] in manifest["measured_metric_ids"]]
        if explicit and "latency_ms" in manifest.get("available_metrics", []) and settings["metric"] != "latency_ms":
            rows.extend(_explicit_metrics("latency_ms", "minimize", 0, None, []))
            rows[-1].update(role="protected", aggregation="worst", max_regression=0)
        primary = next(item for item in rows if item["role"] == "objective")
        command = manifest["eval_command"]
        immutable = []
        for name in manifest["hashes"]:
            try:
                immutable.append(Path(name).relative_to(package).as_posix())
            except ValueError:
                pass
        charter = build_charter(
            metric=primary["id"], direction=primary["direction"], noise=primary["noise"], target=primary["target"],
            eval_command=command, immutable=immutable, task=settings["task"] or f"evolve {package.name} against qualified measurements",
            timeout=settings["timeout_sec"],
        )
        charter["loop"] = "continuous"
        scenario_text = Path(run["scenario_path"]).read_text(encoding="utf-8")
        _write_sealed(run_dir, charter, rows, scenario_text, [item["text"] for item in plan["requirements"]], 1)
        charter = read_json(run_dir / "charter.json")
        metrics = measure_search(run_dir, charter, "baseline-samples")
        run = load_run(run_dir)
        run.update(
            baseline_eval_command=command, eval_mode="measured", immutable_hashes=hash_tree(package, immutable),
            message_fields=message_fields(package), message_schema=message_schema(package),
        )
        save_run(run_dir, run)
        record_baseline(run_dir, metrics)
        atomic_write(run_dir / "eval" / "baseline.json", metrics)
        run = load_run(run_dir)
        run.update(setup_complete=True, status="running", stage="search", stop_reason="", success=False, sota_verified=False)
        run["uncovered_behaviors"] = _current_gaps(run_dir, scenario_text)
        save_run(run_dir, run)
        write_handoff(run_dir)
        report(run_dir, "evaluation_ready", scope=run.get("evaluation_scope"), metrics=metrics)
        return True
    except (Exception, KeyboardInterrupt) as exc:
        from absolute.evaluation import _coverage

        run = load_run(run_dir)
        reset_to(package, run["script_head"])
        run.update(status="paused", stage="evaluation_setup", stop_reason=f"evaluation_setup: {str(exc)[:1500]}")
        save_run(run_dir, run)
        proposal = run_dir / "eval" / "proposal.json"
        if not run.get("benchmark_sha256") and proposal.is_file() and read_json(proposal).get("origin") == "generated":
            proposal.replace(run_dir / "eval" / "failed-proposal.json")
        if (run_dir / "eval" / "plan.json").is_file():
            _coverage(run_dir, read_json(run_dir / "eval" / "plan.json"), set(), [run["stop_reason"]])
        report(run_dir, "evaluation_blocked", reason=run["stop_reason"], report=str(run_dir / "eval" / "coverage.md"))
        return False


def _current_gaps(run_dir: Path, scenario_text: str) -> list[str]:
    coverage = run_dir / "eval" / "coverage.json"
    if coverage.is_file():
        return [item["text"] for item in read_json(coverage)["requirements"] if item["status"] == "unmeasured"]
    document = load_contract(run_dir)
    if document is None:
        return []
    obligations = live_obligations(scenario_text, list(document.get("obligations") or []))
    return uncovered_obligations(obligations, document["metrics"], scenario_text)


def _ensure_continuable(run_dir: Path) -> bool:
    charter = read_json(run_dir / "charter.json")
    if charter.get("loop") != "until_target":
        raise RuntimeError("this folder is not an evolve run")
    run = load_run(run_dir)
    if run.get("status") == "stopped" and run.get("stop_reason") in TERMINAL_STOPS:
        return False
    package = Path(run["package_copy"])
    if run.get("status") == "needs_human" or run.get("open_admit"):
        restore = run["open_admit"]["sha"] if run.get("open_admit") else run.get("script_head")
        reset_to(package, str(restore))
        run["open_admit"] = None
        run["script_head"] = str(restore)
        run["status"] = "running"
        run["stop_reason"] = ""
        save_run(run_dir, run)
    elif run.get("status") == "awaiting_gate_b":
        run["status"] = "running"
        run["stop_reason"] = ""
        save_run(run_dir, run)
    elif run.get("status") != "running":
        raise RuntimeError(f"cannot continue status {run.get('status')}")
    elif not _tree_matches_script(run, package):
        reset_to(package, run["script_head"])
    write_handoff(run_dir)
    return True


def _set_stage(run_dir: Path, stage: str) -> None:
    run = load_run(run_dir)
    run["stage"] = stage
    save_run(run_dir, run)
    report(run_dir, "stage", stage=stage)


def _worker_brief(run_dir: Path, cycle_n: int, package: Path, charter: dict[str, Any]) -> dict[str, Any]:
    primary = charter["metrics"]["primary"]
    names = [primary["name"]]
    names.extend(item["name"] for item in charter.get("metrics", {}).get("protected") or [])
    return {
        "cycle": cycle_n,
        "framework_root": str(FRAMEWORK_ROOT),
        "model": os.environ.get("ABSOLUTE_MODEL") or WORKER_MODEL,
        "named_penalties": names,
        "package_copy": str(package),
        "run": str(run_dir),
        "skill": str(FRAMEWORK_ROOT / "SKILL.md"),
    }


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise ValueError(f"missing {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _until_ok(fn, attempts: int = STAGE_ATTEMPTS):
    last: Exception | None = None
    for _ in range(attempts):
        try:
            return fn()
        except (ValueError, json.JSONDecodeError) as exc:
            last = exc
    raise RuntimeError("stage artifact failed") from last


def _stop_for_coverage(run_dir: Path, proposals: list[dict[str, Any]], launcher: Launcher) -> None:
    charter = read_json(run_dir / "charter.json")
    best = read_json(run_dir / "scoreboard.json").get("best") or {}
    if not measurements_at_target(charter, best):
        raise BoardRetry()
    scenario_text = Path(load_run(run_dir)["scenario_path"]).read_text(encoding="utf-8")
    if _current_gaps(run_dir, scenario_text) and int(load_run(run_dir).get("discovery_round") or 1) < 2:
        fresh = run_eval(
            list(charter["eval_command"]),
            Path(load_run(run_dir)["package_copy"]),
            float(charter.get("eval_timeout_sec", 60)),
        )
        charter = _extend_contract(run_dir, launcher, fresh)
        best = read_json(run_dir / "scoreboard.json").get("best") or {}
        if not measurements_at_target(charter, best):
            raise BoardRetry()
    if _current_gaps(run_dir, scenario_text):
        with runner_authority():
            record_rejections(run_dir, proposals)
            run = load_run(run_dir)
            run["success"] = False
            run["proxy_saturated"] = True
            run["uncovered_behaviors"] = _current_gaps(run_dir, scenario_text)
            save_run(run_dir, run)
            stop_run(run_dir, "scenario_uncovered")
        return
    with runner_authority():
        record_rejections(run_dir, proposals)
        stop_run(run_dir, "outputs_covered")


def one_cycle(run_dir: Path, launcher: Launcher) -> dict[str, Any]:
    charter = read_json(run_dir / "charter.json")
    run = load_run(run_dir)
    scoreboard = read_json(run_dir / "scoreboard.json")
    cycle_n = int(scoreboard.get("cycles", 0)) + 1
    package = Path(run["package_copy"])
    stage = run.get("stage") or "application"
    workers = run_dir / "workers" / f"cycle-{cycle_n:03d}"
    primary_name = charter["metrics"]["primary"]["name"]

    def brief_for(role: str, name: str, output: Path | None) -> dict[str, Any]:
        ready = _worker_brief(run_dir, cycle_n, package, read_json(run_dir / "charter.json"))
        ready.update(
            {
                "brief_path": str(workers / f"{name}.json"),
                "role": role,
            }
        )
        if output is not None:
            ready["output"] = str(output)
        return ready

    def run_application() -> None:
        _set_stage(run_dir, "application")
        scenario = Path(load_run(run_dir)["scenario_path"])
        digest = file_hash(scenario)
        current = load_run(run_dir)
        current["scenario_hash"] = digest
        save_run(run_dir, current)
        if current.get("application_hash") == digest and (run_dir / "application" / "application.json").is_file():
            return
        output = run_dir / "application" / "application.json"
        ready = brief_for("application", "application", output)
        ready["scenario_text"] = scenario.read_text(encoding="utf-8")
        _launch_one(launcher, ready)
        payload = _read_json(output)
        if not all(_nonempty(payload.get(key)) for key in ("purpose", "users", "outputs")):
            raise ValueError("application artifact is incomplete")
        current = load_run(run_dir)
        current["application_hash"] = digest
        save_run(run_dir, current)

    def _board_fields() -> dict[str, Any]:
        current = load_run(run_dir)
        return {
            "kept_features": list(current.get("kept_features") or []),
            "prior_note": current.get("board_note") or "",
            "rejected_features": list(current.get("rejected_features") or []),
        }

    def gather_proposals() -> list[dict[str, Any]]:
        _set_stage(run_dir, "feature_board")
        application = _read_json(run_dir / "application" / "application.json")
        proposal_paths: list[Path] = []
        briefs = []
        for index in range(1, 4):
            output = run_dir / "decisions" / f"cycle-{cycle_n:03d}" / f"proposal-{index}.json"
            ready = brief_for("feature_propose", f"proposal-{index}", output)
            ready.update(_board_fields())
            ready["application"] = application
            ready["index"] = index
            briefs.append(ready)
            proposal_paths.append(output)
        _launch_all(launcher, briefs)
        proposals = []
        for path in proposal_paths:
            payload = _read_json(path)
            if not _nonempty(payload.get("feature_id")) or not _nonempty(payload.get("summary")):
                raise ValueError(f"incomplete proposal {path.name}")
            proposals.append(payload)
        return proposals

    def admit_from(proposals: list[dict[str, Any]]) -> dict[str, Any] | None:
        unique = unique_proposals(proposals)
        if round_is_nothing_new(unique, load_run(run_dir)):
            _stop_for_coverage(run_dir, unique, launcher)
            return None
        cycle_dir = run_dir / "decisions" / f"cycle-{cycle_n:03d}"
        review_specs = (
            ("feature_review_scenario", "review-scenario"),
            ("feature_review_feasibility", "review-feasibility"),
            ("feature_review_restatement", "review-restatement"),
        )
        review_paths: list[Path] = []
        review_briefs = []
        proposal_paths = [str(cycle_dir / f"proposal-{index}.json") for index in range(1, 4)]
        for role, name in review_specs:
            output = cycle_dir / f"{name}.json"
            ready = brief_for(role, name, output)
            ready.update(_board_fields())
            ready["proposals"] = proposal_paths
            review_briefs.append(ready)
            review_paths.append(output)
        _launch_all(launcher, review_briefs)
        for path in review_paths:
            payload = _read_json(path)
            if not isinstance(payload.get("judgments"), list):
                raise ValueError(f"review judgments are missing in {path.name}")
        admission_path = cycle_dir / "admission.json"
        chair = brief_for("feature_admit", "admission", admission_path)
        chair.update(_board_fields())
        chair["proposals"] = proposal_paths
        chair["reviews"] = [str(path) for path in review_paths]
        _launch_one(launcher, chair)
        decisions = _read_json(admission_path).get("decisions")
        if not isinstance(decisions, list):
            raise ValueError("admission decisions are missing")
        by_id: dict[str, dict[str, Any]] = {}
        for item in decisions:
            if not isinstance(item, dict):
                raise ValueError("admission decision is malformed")
            feature_id = str(item.get("feature_id") or "")
            if feature_id in by_id or item.get("decision") not in ("accept", "reject"):
                raise ValueError("admission decision is malformed")
            if not _nonempty(item.get("reason")):
                raise ValueError("admission decision needs a reason")
            by_id[feature_id] = item
        if set(by_id) != {str(item["feature_id"]) for item in unique}:
            raise ValueError("admission decisions do not cover the proposals")
        accepted = [item for item in by_id.values() if item["decision"] == "accept"]
        if len(accepted) > 1:
            raise ValueError("admission accepted more than one feature")
        if not accepted:
            _stop_for_coverage(run_dir, unique, launcher)
            return None
        feature_id = str(accepted[0]["feature_id"])
        match = [item for item in unique if str(item["feature_id"]) == feature_id]
        if len(match) != 1:
            raise ValueError("accepted feature is not a proposal")
        known = {
            str(entry.get("id"))
            for key in ("kept_features", "rejected_features")
            for entry in (load_run(run_dir).get(key) or [])
            if isinstance(entry, dict)
        }
        if feature_id in known or match[0]["summary"].strip() == primary_name:
            raise ValueError("accepted feature is not new")
        rejected = [item for item in unique if str(item["feature_id"]) != feature_id]
        with runner_authority():
            record_rejections(run_dir, rejected)
        current = load_run(run_dir)
        current["admitted_feature"] = match[0]
        current["stage"] = "literature"
        save_run(run_dir, current)
        charter_path = run_dir / "charter.json"
        charter_body = read_json(charter_path)
        catalog = list(charter_body.get("feature_catalog") or [])
        if feature_id not in {entry.get("id") for entry in catalog}:
            catalog.append({"id": feature_id, "summary": match[0]["summary"]})
            charter_body["feature_catalog"] = catalog
            atomic_write(charter_path, charter_body)
        return match[0]

    def _check_literature(path: Path, query: str) -> None:
        payload = _read_json(path)
        if payload.get("query") != query:
            raise ValueError("literature worker changed the query")
        findings = payload.get("findings")
        if not isinstance(findings, list) or not findings:
            raise ValueError("literature findings are empty")

    def run_literature(feature: dict[str, Any]) -> dict[str, Any]:
        _set_stage(run_dir, "literature")
        queries = literature_queries(str(feature["summary"]), package.name)
        backups = [item for item in literature_backups(str(feature["summary"]), package.name) if item not in queries]
        outputs: list[Path] = []
        briefs = []
        for index, query in enumerate(queries, start=1):
            output = run_dir / "sota" / f"cycle-{cycle_n:03d}" / f"literature-{index}.json"
            ready = brief_for("literature", f"literature-{index}", output)
            ready["index"] = index
            ready["query"] = query
            briefs.append(ready)
            outputs.append(output)
        _launch_all(launcher, briefs)
        used = set(queries)
        for index, (query, path) in enumerate(zip(queries, outputs), start=1):
            try:
                _check_literature(path, query)
            except (ValueError, json.JSONDecodeError):
                if not backups:
                    raise ValueError("literature artifact is unusable") from None
                replacement = backups.pop(0)
                used.add(replacement)
                output = path
                ready = brief_for("literature", f"literature-{index}-retry", output)
                ready["index"] = index
                ready["query"] = replacement
                _launch_one(launcher, ready)
                _check_literature(output, replacement)
        verdict_path = run_dir / "sota" / f"cycle-{cycle_n:03d}" / "verdict.json"
        chair = brief_for("literature_chair", "literature-chair", verdict_path)
        chair["feature"] = feature
        chair["reports"] = [str(path) for path in outputs]
        _launch_one(launcher, chair)
        verdict = _read_json(verdict_path)
        if verdict.get("verdict") not in ("adopt", "stands", "insufficient-evidence"):
            raise ValueError("literature verdict is missing")
        citations = verdict.get("citations")
        if verdict.get("verdict") in ("adopt", "stands") and not (
            citations_are_external(citations, package) and citations_fetch([str(item) for item in citations])
        ):
            verdict = {
                "citations": citations if isinstance(citations, list) else [],
                "method": str(verdict.get("method") or "").strip(),
                "verdict": "insufficient-evidence",
            }
        citations = verdict.get("citations")
        if not isinstance(citations, list) or not citations or not all(_nonempty(item) for item in citations):
            raise ValueError("literature verdict needs citations")
        if not _nonempty(verdict.get("method")):
            raise ValueError("literature verdict needs a method")
        current = load_run(run_dir)
        current["method_verdict"] = {
            "citations": [str(item) for item in citations],
            "method": str(verdict["method"]).strip(),
            "verdict": verdict["verdict"],
        }
        save_run(run_dir, current)
        return current["method_verdict"]

    def run_survey(feature: dict[str, Any]) -> list[str]:
        _set_stage(run_dir, "code_survey")
        report_paths: list[Path] = []
        briefs = []
        for index in range(1, 4):
            output = run_dir / "sota" / f"cycle-{cycle_n:03d}" / f"survey-{index}.json"
            ready = brief_for("survey", f"survey-{index}", output)
            ready["index"] = index
            briefs.append(ready)
            report_paths.append(output)
        _launch_all(launcher, briefs)
        for path in report_paths:
            payload = _read_json(path)
            points = payload.get("points")
            if not isinstance(points, list) or not points:
                raise ValueError(f"empty survey {path.name}")
        review_path = run_dir / "sota" / f"cycle-{cycle_n:03d}" / "survey-review.json"
        review = brief_for("survey_review", "survey-review", review_path)
        review["feature"] = feature
        review["reports"] = [str(path) for path in report_paths]
        _launch_one(launcher, review)
        kept = _read_json(review_path).get("points")
        if not isinstance(kept, list):
            raise ValueError("survey review is missing")
        points = [str(item) for item in kept if _nonempty(item)]
        current = load_run(run_dir)
        current["survey_points"] = points
        save_run(run_dir, current)
        return points

    def run_edit(stage_name: str, hypothesis: str, feature: dict[str, Any], method: str, points: list[str]) -> dict[str, Any]:
        from absolute.engine import _record_stage

        limit = 1 if stage_name == "inference_edit" else STAGE_ATTEMPTS
        entry: dict[str, Any] = {"outcome": "revert"}
        for _ in range(limit):
            _set_stage(run_dir, stage_name)
            current = load_run(run_dir)
            base_sha = str(current["script_head"])
            pre = read_json(run_dir / "scoreboard.json")["best"]
            result = workers / f"edit-result-{stage_name}.json"
            ready = brief_for("edit", f"edit-{stage_name}", None)
            ready.update(
                {
                    "feature": feature,
                    "hypothesis": hypothesis,
                    "method": method,
                    "prior_patches": [str(path) for path in sorted((run_dir / "attempts").glob("*.patch"))],
                    "result": str(result),
                    "stage": stage_name,
                    "survey_points": points,
                }
            )
            external_snap = _snapshot(external_scorer_files(list(charter["eval_command"]), package))
            contract_files = [
                run_dir / "eval" / "contract.json",
                run_dir / "charter.json",
                run_dir / "run.json",
            ]
            contract_snap = _snapshot(contract_files)
            expected_hash = load_run(run_dir).get("contract_sha256")
            try:
                _launch_one(launcher, ready)
            except Exception:
                _restore(external_snap)
                _restore(contract_snap)
                raise
            if _tampered(external_snap):
                _restore(external_snap)
                _restore(contract_snap)
                with runner_authority():
                    entry = _record_stage(
                        run_dir,
                        package,
                        outcome="bad_edit",
                        reason="edit worker wrote the scorer",
                        base_sha=base_sha,
                        hypothesis=hypothesis,
                        stage=stage_name,
                        cycle_n=cycle_n,
                        metrics=None,
                        feature_id=feature.get("feature_id"),
                    )
                continue
            hash_moved = load_run(run_dir).get("contract_sha256") != expected_hash
            if _tampered(contract_snap) or hash_moved:
                _restore(contract_snap)
                with runner_authority():
                    entry = _record_stage(
                        run_dir,
                        package,
                        outcome="bad_edit",
                        reason="edit worker rewrote the metric contract",
                        base_sha=base_sha,
                        hypothesis=hypothesis,
                        stage=stage_name,
                        cycle_n=cycle_n,
                        metrics=None,
                        feature_id=feature.get("feature_id"),
                    )
                continue
            behavior = None
            if result.is_file():
                try:
                    behavior = _read_json(result).get("behavior_test")
                except (ValueError, json.JSONDecodeError):
                    behavior = None
            with runner_authority():
                entry = score_stage(
                    run_dir,
                    read_json(run_dir / "charter.json"),
                    stage=stage_name,
                    cycle_n=cycle_n,
                    hypothesis=hypothesis,
                    base_sha=base_sha,
                    behavior_test=behavior,
                    pre_metrics=pre,
                    feature_id=feature.get("feature_id"),
                )
            if entry["outcome"] == "keep":
                return entry
        return entry

    if stage == "application":
        _until_ok(run_application)
        stage = "feature_board"
    feature = load_run(run_dir).get("admitted_feature")
    if stage == "feature_board":
        if not feature:
            for _ in range(BOARD_ATTEMPTS):
                try:
                    proposals = _until_ok(gather_proposals)
                    feature = _until_ok(lambda: admit_from(proposals))
                    break
                except BoardRetry:
                    feature = None
            else:
                with runner_authority():
                    stop_run(run_dir, "uncovered_outputs")
                return {"cycle": cycle_n, "metrics": None, "outcome": "uncovered_outputs"}
            if feature is None:
                reason = load_run(run_dir).get("stop_reason") or "outputs_covered"
                return {"cycle": cycle_n, "metrics": None, "outcome": reason}
        stage = "literature"
    if stage == "literature":
        _until_ok(lambda: run_literature(feature))
        stage = "code_survey"
    verdict = load_run(run_dir).get("method_verdict") or {}
    if stage == "code_survey":
        _until_ok(lambda: run_survey(feature))
        stage = "feature_edit"
    points = list(load_run(run_dir).get("survey_points") or [])
    last: dict[str, Any] = {"outcome": "keep"}
    if stage == "feature_edit":
        verdict = load_run(run_dir).get("method_verdict") or verdict
        method = str(verdict.get("method") or "") if verdict.get("verdict") == "adopt" else ""
        last = run_edit(
            "feature_edit",
            str(feature.get("hypothesis") or feature.get("summary")),
            feature,
            method,
            points,
        )
        stage = "inference_edit"
    if stage == "method_gate":
        stage = "inference_edit"
    if stage == "inference_edit":
        verdict = load_run(run_dir).get("method_verdict") or verdict
        last = run_edit("inference_edit", "lower measured latency", feature, str(verdict.get("method") or ""), points)
    with runner_authority():
        complete_cycle(
            run_dir,
            read_json(run_dir / "charter.json"),
            method_satisfied=True,
        )
    return last



def _search_cycle(run_dir: Path, launcher: Launcher) -> dict[str, Any]:
    from absolute.engine import _record_stage
    from absolute.evaluation import MANIFEST, verify_benchmark

    benchmark = verify_benchmark(run_dir)
    run = load_run(run_dir)
    charter = read_json(run_dir / "charter.json")
    scoreboard = read_json(run_dir / "scoreboard.json")
    cycle_n = int(scoreboard.get("cycles", 0)) + 1
    package = Path(run["package_copy"])
    base_sha = run["script_head"]
    specs = search_metric_specs(charter)
    focus = specs[(cycle_n - 1) % len(specs)]
    strategies = ("local improvement", "algorithm replacement", "robustness and edge cases", "simplification and resource use")
    strategy = strategies[((cycle_n - 1) // len(specs)) % len(strategies)]
    scenario_text = Path(run["scenario_path"]).read_text(encoding="utf-8")
    gaps = _current_gaps(run_dir, scenario_text)
    run.update(stage="search", uncovered_behaviors=gaps, success=False, sota_verified=False)
    save_run(run_dir, run)
    report(run_dir, "cycle_started", cycle=cycle_n, focus=focus["metric"], strategy=strategy, uncovered=len(gaps))
    before = measure_search(run_dir, charter, f"cycle-{cycle_n:06d}-parent")
    workers = run_dir / "workers" / f"cycle-{cycle_n:06d}"
    result = workers / "result.json"
    result.unlink(missing_ok=True)
    feedback = [
        {key: (str(entry[key])[:1500] if key in ("hypothesis", "error") else entry[key])
         for key in ("cycle", "hypothesis", "outcome", "error", "metrics", "patch", "commit") if key in entry}
        for entry in read_journal(run_dir, limit=12)
    ]
    brief = _worker_brief(run_dir, cycle_n, package, charter)
    brief.update(
        role="optimize", brief_path=str(workers / "optimize.json"), result=str(result),
        scenario_text=scenario_text, focus=focus, strategy=strategy, metrics=specs,
        measured=before, best=scoreboard["best"], feedback=feedback,
        uncovered_behaviors=gaps, context_window_tokens=500000,
        immutable=list(charter.get("immutable") or []),
    )
    protected = [run_dir / name for name in ("run.json", "charter.json", "scoreboard.json", "eval/contract.json", "recovery.sqlite3")]
    protected.extend(external_scorer_files(list(charter["eval_command"]), package))
    protected.append(Path(run["scenario_path"]))
    if benchmark:
        protected.append(run_dir / MANIFEST)
        protected.extend(Path(name) for name in benchmark["hashes"] if Path(name).is_relative_to(run_dir / "eval"))
    snapshot = _snapshot(protected)
    hypothesis = f"{strategy}: {focus['metric']}"

    def integrity_check() -> bool:
        changed = _tampered(snapshot)
        if changed:
            _restore(snapshot)
        return not changed

    def reject(outcome: str, reason: str) -> dict[str, Any]:
        with runner_authority():
            return _record_stage(
                run_dir, package, outcome=outcome, reason=reason[:2000], base_sha=base_sha,
                hypothesis=hypothesis, stage="search_edit", cycle_n=cycle_n, metrics=None, feature_id=None,
            )

    try:
        _launch_one(launcher, brief)
        if _tampered(snapshot):
            _restore(snapshot)
            entry = reject("bad_edit", "worker changed runner-owned files or scorer")
        else:
            payload = _read_json(result)
            if not isinstance(payload, dict) or not _nonempty(payload.get("hypothesis")):
                raise ValueError("optimizer result needs a hypothesis and behavior_test")
            hypothesis = str(payload["hypothesis"])[:1500]
            report(run_dir, "candidate_ready", cycle=cycle_n, hypothesis=hypothesis)
            with runner_authority():
                entry = score_stage(
                    run_dir, charter, stage="search_edit", cycle_n=cycle_n, hypothesis=hypothesis,
                    base_sha=base_sha, behavior_test=payload.get("behavior_test"), pre_metrics=before,
                    integrity_check=integrity_check,
                )
    except (LaunchError, OSError, ValueError) as exc:
        _restore(snapshot)
        entry = reject("worker_failed" if isinstance(exc, (LaunchError, OSError)) else "bad_edit", str(exc))
    except BaseException:
        if checkpoint_cycle(run_dir) == cycle_n:
            recover_checkpoint(run_dir, force=True)
            raise
        _restore(snapshot)
        reset_to(package, base_sha)
        raise
    with runner_authority():
        complete_cycle(run_dir, charter, method_satisfied=True)
    report(run_dir, "cycle_finished", cycle=cycle_n, outcome=entry["outcome"], reason=entry.get("error", ""), metrics=entry.get("metrics"))
    print(status_text(run_dir), flush=True)
    return entry


def _pause(run_dir: Path, reason: str) -> None:
    recover_checkpoint(run_dir)
    run = load_run(run_dir)
    run.update(status="paused", stop_reason=reason)
    save_run(run_dir, run)
    try:
        write_handoff(run_dir)
    except (ValueError, KeyError):
        pass
    report(run_dir, "paused", reason=reason)


def _cooldown(run_dir: Path, seconds: float) -> None:
    report(run_dir, "cooldown", seconds=seconds)
    remaining = seconds
    while remaining > 0 and not (run_dir / "STOP").exists():
        interval = min(1.0, remaining)
        threading.Event().wait(interval)
        remaining -= interval


def run_cycles(run_dir: Path, launcher: Launcher, completed_cycle_limit: int | None = None) -> None:
    with run_lock(run_dir):
        recover_checkpoint(run_dir)
        repair_journal(run_dir)
        state = load_run(run_dir)
        if state.get("setup") and not state.get("setup_complete"):
            if not _prepare_search_evaluation(run_dir, launcher):
                return
        if not load_run(run_dir).get("search"):
            _run_legacy_cycles(run_dir, launcher, completed_cycle_limit)
            return
        run = load_run(run_dir)
        if run.get("status") not in ("running", "paused"):
            raise RuntimeError(f"cannot continue status {run.get('status')}")
        run.update(status="running", stop_reason="")
        save_run(run_dir, run)
        package = Path(run["package_copy"])
        if not _tree_matches_script(run, package):
            reset_to(package, run["script_head"])
        recent = read_journal(run_dir, limit=1)
        scoreboard = read_json(run_dir / "scoreboard.json")
        scoreboard["cycles"] = max(int(scoreboard.get("cycles", 0)), int(recent[-1].get("cycle") or 0) if recent else 0)
        atomic_write(run_dir / "scoreboard.json", scoreboard)
        print(status_text(run_dir), flush=True)
        failures = 0
        try:
            while True:
                if (run_dir / "STOP").exists():
                    _pause(run_dir, "stop_requested")
                    return
                scoreboard = read_json(run_dir / "scoreboard.json")
                if completed_cycle_limit is not None and int(scoreboard.get("cycles", 0)) >= completed_cycle_limit:
                    _pause(run_dir, "cycle_budget")
                    return
                entry = _search_cycle(run_dir, launcher)
                failures = failures + 1 if entry["outcome"] == "worker_failed" else 0
                if failures >= 5:
                    _pause(run_dir, "worker_failures")
                    return
                streak = int(read_json(run_dir / "scoreboard.json").get("no_keep_streak", 0))
                completed = int(read_json(run_dir / "scoreboard.json").get("cycles", 0))
                if streak and (completed_cycle_limit is None or completed < completed_cycle_limit):
                    _cooldown(run_dir, min(300, 2 ** min(streak, 9)))
        except KeyboardInterrupt:
            _pause(run_dir, "interrupted")
        except Exception as exc:
            _pause(run_dir, f"error: {str(exc)[:1000]}")
            raise


def _run_legacy_cycles(run_dir: Path, launcher: Launcher, completed_cycle_limit: int | None = None) -> None:
    while True:
        if not _ensure_continuable(run_dir):
            print(load_run(run_dir).get("stop_reason") or "", flush=True)
            return
        if completed_cycle_limit is not None:
            completed = int(read_json(run_dir / "scoreboard.json").get("cycles", 0))
            if completed >= completed_cycle_limit:
                return
        entry = one_cycle(run_dir, launcher)
        print(
            json.dumps(
                {"cycle": entry.get("cycle"), "metrics": entry.get("metrics"), "outcome": entry.get("outcome")}
            ),
            flush=True,
        )
        run = load_run(run_dir)
        if run.get("status") == "stopped" and run.get("stop_reason") in TERMINAL_STOPS:
            print(run.get("stop_reason") or "", flush=True)
            return


def evolve_package(
    *,
    package: Path,
    scenario: Path,
    eval_command: list[str] | None = None,
    launcher: Launcher,
    metric: str | None = None,
    direction: str | None = None,
    noise: float | None = None,
    target: float | None = None,
    runs_root: Path | None = None,
    timeout_sec: float = 60,
    task: str | None = None,
    completed_cycle_limit: int | None = None,
    continuous: bool = True,
    eval_repeats: int = 3,
) -> Path:
    run_dir = prepare_run(
        package=package,
        scenario=scenario,
        metric=metric,
        direction=direction,
        noise=noise,
        target=target,
        eval_command=eval_command,
        launcher=launcher,
        runs_root=runs_root,
        timeout_sec=timeout_sec,
        task=task,
        continuous=continuous,
        eval_repeats=eval_repeats,
    )
    print(run_dir, flush=True)
    if continuous and not load_run(run_dir).get("setup_complete"):
        return run_dir
    run_cycles(run_dir, launcher, completed_cycle_limit)
    return run_dir


def continue_package(run_dir: Path, launcher: Launcher, completed_cycle_limit: int | None = None) -> Path:
    run_dir = run_dir.resolve()
    print(run_dir, flush=True)
    run_cycles(run_dir, launcher, completed_cycle_limit)
    return run_dir


def launcher_from_worker(worker: str | None) -> Launcher:
    import sys

    from absolute.launch import make_cursor_launcher, make_subprocess_launcher

    if worker:
        return make_subprocess_launcher([sys.executable, str(Path(worker).resolve())])
    return make_cursor_launcher()
