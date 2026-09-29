"""Process stand-in the runner launches when proving the loop.

The first feature edit moves the measured value the wrong way. The retry,
the method edit, and the inference edit then finish the cycle.
A Cursor agent follows the brief instead of this schedule.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _write(path: str, payload: dict) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _bump(run: str, key: str) -> int:
    path = Path(run) / "fixture-schedule.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data[key] = int(data.get(key, 0)) + 1
    path.write_text(json.dumps(data), encoding="utf-8")
    return int(data[key])


def _behavior(package: Path, value: int, latency: int) -> None:
    (package / "test_behavior.py").write_text(
        "import unittest\n"
        "import algo\n\n"
        "class Behavior(unittest.TestCase):\n"
        "    def test_holds(self):\n"
        f"        self.assertEqual(algo.VALUE, {value})\n"
        f"        self.assertEqual(algo.LATENCY_MS, {latency})\n",
        encoding="utf-8",
    )


def _algo(package: Path, value: int, latency: int) -> None:
    (package / "algo.py").write_text(f"VALUE = {value}\nLATENCY_MS = {latency}\n", encoding="utf-8")


def do_application(brief: dict) -> None:
    _write(
        brief["output"],
        {
            "outputs": "a score and a latency",
            "purpose": "toy stack for the evolve demonstration",
            "users": "the test harness",
        },
    )


def do_feature_propose(brief: dict) -> None:
    index = int(brief.get("index") or 1)
    if index == 1:
        payload = {"feature_id": "restated", "hypothesis": "say the metric name", "summary": "score"}
    elif index == 2:
        payload = {"feature_id": "extra", "hypothesis": "an unused idea", "summary": "count the calls"}
    else:
        payload = {
            "feature_id": "raise-value",
            "hypothesis": "raise the toy score",
            "summary": "raise the toy score the package exposes",
        }
    _write(brief["output"], payload)


def do_feature_review(brief: dict) -> None:
    _write(brief["output"], {"judgments": [{"concern": brief["role"], "feature_id": "raise-value"}]})


def do_feature_admit(brief: dict) -> None:
    decisions = []
    for path in brief.get("proposals") or []:
        proposal = json.loads(Path(path).read_text(encoding="utf-8"))
        accept = proposal.get("feature_id") == "raise-value"
        decisions.append(
            {
                "decision": "accept" if accept else "reject",
                "feature_id": proposal.get("feature_id"),
                "reason": "admitted feature" if accept else "not the one feature",
            }
        )
    _write(brief["output"], {"decisions": decisions})


def do_literature(brief: dict) -> None:
    _write(
        brief["output"],
        {"citations": ["fixture"], "findings": [brief["query"] + " finding"], "query": brief["query"]},
    )


def do_literature_chair(brief: dict) -> None:
    verdict = os.environ.get("ABSOLUTE_FIXTURE_VERDICT", "adopt")
    if verdict not in ("adopt", "stands"):
        verdict = "adopt"
    _write(
        brief["output"],
        {
            "citations": ["fixture method note"],
            "method": "direct assignment",
            "verdict": verdict,
        },
    )


def do_survey(brief: dict) -> None:
    _write(brief["output"], {"points": ["algo.py assignment is the latency hot path"]})


def do_survey_review(brief: dict) -> None:
    _write(brief["output"], {"points": ["algo.py assignment is the latency hot path"]})


def do_edit(brief: dict) -> None:
    package = Path(brief["package_copy"])
    stage = str(brief.get("stage"))
    attempt = _bump(str(brief["run"]), stage)
    if stage == "feature_edit" and attempt == 1:
        _algo(package, 0, 10)
        _behavior(package, 0, 10)
    elif stage == "inference_edit":
        _algo(package, 5, 4)
        _behavior(package, 5, 4)
    else:
        _algo(package, 5, 10)
        _behavior(package, 5, 10)
        if stage == "method_gate":
            (package / "method_note.py").write_text("METHOD = True\n", encoding="utf-8")
    _write(brief["result"], {"behavior_test": [sys.executable, "-m", "unittest", "test_behavior"]})


def do_optimize(brief: dict) -> None:
    package = Path(brief["package_copy"])
    latency = 8 if brief["cycle"] == 1 else 4
    _algo(package, 5, latency)
    _behavior(package, 5, latency)
    _write(brief["result"], {
        "hypothesis": "improve score then latency",
        "behavior_test": [sys.executable, "-B", "-m", "unittest", "test_behavior"],
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True)
    parser.add_argument("--brief", required=True)
    args = parser.parse_args()
    brief = json.loads(Path(args.brief).read_text(encoding="utf-8"))
    if args.role != brief["role"]:
        raise SystemExit("role mismatch")
    Path(args.brief).with_suffix(".pid").write_text(str(os.getpid()), encoding="utf-8")
    handlers = {
        "application": do_application,
        "feature_propose": do_feature_propose,
        "feature_review_scenario": do_feature_review,
        "feature_review_feasibility": do_feature_review,
        "feature_review_restatement": do_feature_review,
        "feature_admit": do_feature_admit,
        "literature": do_literature,
        "literature_chair": do_literature_chair,
        "survey": do_survey,
        "survey_review": do_survey_review,
        "edit": do_edit,
        "optimize": do_optimize,
    }
    if args.role not in handlers:
        raise SystemExit(f"unknown role {args.role}")
    handlers[args.role](brief)


if __name__ == "__main__":
    main()
