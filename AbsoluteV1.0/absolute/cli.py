"""Command line for Absolute v1.0. Bookkeeping stays here; the model edits the copy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from absolute import __version__
from absolute.engine import (
    admit,
    ballots_allow_field_test,
    check_immutable,
    cycle,
    ensure_copy_repo,
    head_sha,
    install_eval,
    now,
    promote_package,
    record_baseline,
    resume,
    run_eval,
    validate_charter,
)
from absolute.loop import continue_package, evolve_package, launcher_from_worker
from absolute.naming import allocate_run_id
from absolute.package import copy_package, hash_tree
from absolute.store import atomic_write, load_run, read_json, save_run

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]


def _run_dir(value: str) -> Path:
    path = Path(value).resolve()
    if not (path / "run.json").is_file():
        raise SystemExit(f"not an Absolute run: {path}")
    return path


def _charter(run_dir: Path) -> dict:
    path = run_dir / "charter.json"
    if not path.is_file():
        raise SystemExit("charter.json is missing")
    return read_json(path)


def cmd_new(args: argparse.Namespace) -> None:
    root = Path(args.runs_root).resolve() if args.runs_root else FRAMEWORK_ROOT / "runs"
    run_name = allocate_run_id(root)
    run_dir = root / run_name
    run_dir.mkdir()
    (run_dir / "ideas").mkdir()
    (run_dir / "sota").mkdir()
    (run_dir / "eval").mkdir()
    save_run(
        run_dir,
        {
            "created_at": now(),
            "framework": "Absolute",
            "id": run_name,
            "package_copy": None,
            "source_package": None,
            "status": "starting",
            "task": args.task,
            "version": __version__,
        },
    )
    print(run_dir)


def cmd_set_charter(args: argparse.Namespace) -> None:
    run_dir = _run_dir(args.run)
    charter = json.loads(Path(args.file).read_text(encoding="utf-8"))
    validate_charter(charter)
    atomic_write(run_dir / "charter.json", charter)
    run = load_run(run_dir)
    run["status"] = "awaiting_gate_a"
    save_run(run_dir, run)
    print(run["status"])


def cmd_accept(args: argparse.Namespace) -> None:
    run_dir = _run_dir(args.run)
    run = load_run(run_dir)
    expected = {"a": "awaiting_gate_a", "b": "awaiting_gate_b"}[args.gate]
    if run["status"] != expected:
        raise SystemExit(f"gate {args.gate} requires status {expected}, found {run['status']}")
    run["status"] = "surveying" if args.gate == "a" else "running"
    save_run(run_dir, run)
    print(run["status"])


def cmd_capture(args: argparse.Namespace) -> None:
    run_dir = _run_dir(args.run)
    run = load_run(run_dir)
    if run["status"] not in ("surveying", "awaiting_gate_b", "running"):
        raise SystemExit("capture requires gate A to be accepted")
    source = Path(args.package).resolve()
    destination = run_dir / "package" / source.name
    copy_package(source, destination)
    ensure_copy_repo(destination)
    run["source_package"] = str(source)
    run["package_copy"] = str(destination)
    run["script_head"] = head_sha(destination)
    save_run(run_dir, run)
    print(destination)


def cmd_baseline(args: argparse.Namespace) -> None:
    run_dir = _run_dir(args.run)
    run = load_run(run_dir)
    charter = _charter(run_dir)
    if not run.get("package_copy"):
        raise SystemExit("capture a package before baseline")
    package_copy = Path(run["package_copy"])
    command = charter.get("eval_command")
    if not command:
        run["status"] = "awaiting_gate_b"
        run["eval_mode"] = "unavailable"
        save_run(run_dir, run)
        print("eval_unavailable")
        return
    metrics = run_eval(command, package_copy, float(charter.get("eval_timeout_sec", 60)))
    immutable = list(charter.get("immutable", []))
    run["immutable_hashes"] = hash_tree(package_copy, immutable) if immutable else {}
    run["baseline_eval_command"] = list(command)
    run["eval_mode"] = "measured"
    save_run(run_dir, run)
    record_baseline(run_dir, metrics)
    atomic_write(run_dir / "eval" / "baseline.json", metrics)
    print(json.dumps(metrics))


def cmd_cycle(args: argparse.Namespace) -> None:
    run_dir = _run_dir(args.run)
    entry = cycle(run_dir, _charter(run_dir))
    print(json.dumps(entry))


def cmd_admit(args: argparse.Namespace) -> None:
    run_dir = _run_dir(args.run)
    record = admit(run_dir, _charter(run_dir), args.tag, args.hypothesis, args.feature_id)
    print(json.dumps(record))


def cmd_install_eval(args: argparse.Namespace) -> None:
    run_dir = _run_dir(args.run)
    metrics = install_eval(run_dir, _charter(run_dir), Path(args.candidate), args.dest)
    print(json.dumps(metrics))


def cmd_resume(args: argparse.Namespace) -> None:
    run_dir = _run_dir(args.run)
    resume(run_dir, _charter(run_dir))
    print("running")


def cmd_ballot(args: argparse.Namespace) -> None:
    run_dir = _run_dir(args.run)
    if args.vote == "definitely":
        raise SystemExit("vote definitely is not a ballot; use field-test or reject")
    path = run_dir / "ballots.json"
    payload = read_json(path) if path.exists() else {"experts": []}
    payload["experts"].append(
        {
            "could_be_worse_if": args.risk,
            "expert": args.expert,
            "vote": args.vote,
        }
    )
    try:
        ballots_allow_field_test(payload)
        ready = True
    except ValueError:
        ready = False
    atomic_write(path, payload)
    print("ready" if ready else "incomplete")


def cmd_promote(args: argparse.Namespace) -> None:
    run_dir = _run_dir(args.run)
    run = load_run(run_dir)
    if not run.get("package_copy") or not run.get("source_package"):
        raise SystemExit("capture a package before promote")
    check_immutable(run_dir, Path(run["package_copy"]))
    destination = promote_package(
        run_dir,
        Path(run["source_package"]),
        Path(run["package_copy"]),
        args.basis,
    )
    run["status"] = "stopped"
    run["stop_reason"] = f"promoted:{args.basis}"
    run["promoted_to"] = str(destination)
    save_run(run_dir, run)
    print(destination)


def cmd_status(args: argparse.Namespace) -> None:
    print(json.dumps(load_run(_run_dir(args.run)), indent=2))


def cmd_evolve(args: argparse.Namespace) -> None:
    launcher = launcher_from_worker(args.worker)
    if args.run:
        if any(
            value is not None
            for value in (args.package, args.scenario, args.metric, args.direction, args.noise, args.target, args.task)
        ) or args.eval:
            raise SystemExit("evolve --run continues a folder; do not pass a package or a goal")
        continue_package(Path(args.run), launcher)
        return
    if args.package is None or args.scenario is None:
        raise SystemExit("evolve requires --package and --scenario")
    if not args.eval:
        raise SystemExit("evolve requires --eval COMMAND as the last argument")
    named = (args.metric, args.direction, args.noise, args.target)
    if any(value is not None for value in named) and not all(value is not None for value in named):
        raise SystemExit("pass --metric, --direction, --noise, and --target together, or omit all four")
    evolve_package(
        package=Path(args.package),
        scenario=Path(args.scenario),
        metric=args.metric,
        direction=args.direction,
        noise=args.noise,
        target=args.target,
        eval_command=list(args.eval),
        launcher=launcher,
        runs_root=Path(args.runs_root) if args.runs_root else None,
        timeout_sec=args.timeout,
        task=args.task,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="absolute")
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new")
    new.add_argument("--task", required=True)
    new.add_argument("--runs-root")
    new.set_defaults(func=cmd_new)

    charter = sub.add_parser("set-charter")
    charter.add_argument("--run", required=True)
    charter.add_argument("--file", required=True)
    charter.set_defaults(func=cmd_set_charter)

    accept = sub.add_parser("accept")
    accept.add_argument("--run", required=True)
    accept.add_argument("--gate", choices=("a", "b"), required=True)
    accept.set_defaults(func=cmd_accept)

    capture = sub.add_parser("capture")
    capture.add_argument("--run", required=True)
    capture.add_argument("--package", required=True)
    capture.set_defaults(func=cmd_capture)

    baseline = sub.add_parser("baseline")
    baseline.add_argument("--run", required=True)
    baseline.set_defaults(func=cmd_baseline)

    cycle_cmd = sub.add_parser("cycle")
    cycle_cmd.add_argument("--run", required=True)
    cycle_cmd.set_defaults(func=cmd_cycle)

    admit_cmd = sub.add_parser("admit")
    admit_cmd.add_argument("--run", required=True)
    admit_cmd.add_argument("--tag", choices=("implementation", "tech-stack", "feature"), required=True)
    admit_cmd.add_argument("--hypothesis", required=True)
    admit_cmd.add_argument("--feature-id")
    admit_cmd.set_defaults(func=cmd_admit)

    install = sub.add_parser("install-eval")
    install.add_argument("--run", required=True)
    install.add_argument("--candidate", required=True)
    install.add_argument("--dest", required=True)
    install.set_defaults(func=cmd_install_eval)

    resume_cmd = sub.add_parser("resume")
    resume_cmd.add_argument("--run", required=True)
    resume_cmd.set_defaults(func=cmd_resume)

    ballot = sub.add_parser("ballot")
    ballot.add_argument("--run", required=True)
    ballot.add_argument("--expert", required=True)
    ballot.add_argument("--vote", choices=("field-test", "reject", "definitely"), required=True)
    ballot.add_argument("--risk", default="")
    ballot.set_defaults(func=cmd_ballot)

    promote = sub.add_parser("promote")
    promote.add_argument("--run", required=True)
    promote.add_argument("--basis", choices=("measured", "field-test"), required=True)
    promote.set_defaults(func=cmd_promote)

    status = sub.add_parser("status")
    status.add_argument("--run", required=True)
    status.set_defaults(func=cmd_status)

    evolve = sub.add_parser("evolve")
    evolve.add_argument("--package")
    evolve.add_argument("--scenario")
    evolve.add_argument("--run")
    evolve.add_argument("--metric")
    evolve.add_argument("--direction", choices=("minimize", "maximize"))
    evolve.add_argument("--noise", type=float, default=None)
    evolve.add_argument("--target", type=float, default=None)
    evolve.add_argument("--timeout", type=float, default=60)
    evolve.add_argument("--runs-root")
    evolve.add_argument("--worker", default=None)
    evolve.add_argument("--task", default=None)
    evolve.add_argument("--eval", nargs=argparse.REMAINDER)
    evolve.set_defaults(func=cmd_evolve)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (RuntimeError, ValueError, FileExistsError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
