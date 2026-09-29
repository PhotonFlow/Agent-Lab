import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from contextlib import redirect_stderr
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from absolute.cli import main
from absolute.engine import (
    admit,
    round_is_nothing_new,
    runner_authority,
    score_stage,
    search_keep_reason,
    target_hit,
    unique_proposals,
    validate_charter,
)
from absolute.launch import LaunchError, _run_command, agent_argv
from absolute.loop import (
    STAGE_ATTEMPTS,
    continue_package,
    evolve_package,
    external_scorer_files,
    immutable_in_package,
    literature_queries,
    prepare_run,
)
from absolute.package import copy_package
from absolute.store import load_run, read_journal, read_json, run_lock

TOY = ROOT / "examples" / "toy_stack" / "algo_v1.1"
WORKER = ROOT / "tests" / "fixtures" / "scheduled_worker.py"


class CharterAndQueryTests(unittest.TestCase):
    def test_native_evaluator_entrypoint_and_data_are_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "package"
            package.mkdir()
            (package / "benchmark.bin").write_bytes(b"binary")
            (package / "dataset.yaml").write_text("cases: []", encoding="utf-8")
            self.assertEqual(immutable_in_package(["./benchmark.bin", "dataset.yaml"], package), ["benchmark.bin", "dataset.yaml"])
            scorer = root / "measure.sh"
            scorer.write_text("exit 0", encoding="utf-8")
            self.assertEqual(external_scorer_files([str(scorer)], package), [scorer.resolve()])

    def test_search_accepts_secondary_improvements_after_target(self):
        charter = {"metrics": {
            "primary": {"name": "score", "direction": "maximize", "noise": 0.1, "target": 5},
            "protected": [{"name": "memory_mb", "direction": "minimize", "max_regression": 1}],
        }}
        baseline = {"score": 5, "memory_mb": 10}
        self.assertIsNone(search_keep_reason(charter, baseline, {"score": 5, "memory_mb": 7}, baseline))
        self.assertIn("regressed", search_keep_reason(charter, baseline, {"score": 4, "memory_mb": 7}, baseline))
        self.assertIn("baseline", search_keep_reason(charter, {"score": 6, "memory_mb": 11}, {"score": 7, "memory_mb": 12}, baseline))
        self.assertIn("finite", search_keep_reason(charter, baseline, {"score": float("nan"), "memory_mb": 7}, baseline))
        self.assertIn("no metric", search_keep_reason(charter, baseline, baseline, baseline))

    def test_target_hit_uses_the_goal_and_not_the_noise_margin(self):
        self.assertTrue(target_hit({"direction": "maximize", "target": 1}, 1))
        self.assertFalse(target_hit({"direction": "maximize", "target": 1}, 0.9))
        self.assertTrue(target_hit({"direction": "minimize", "target": 0}, 0))
        self.assertFalse(target_hit({"direction": "minimize", "target": 0}, 0.05))
        self.assertFalse(target_hit({"direction": "minimize"}, 0))

    def test_literature_queries_are_disjoint(self):
        queries = literature_queries("raise the toy score", "algo_v1.1")
        self.assertEqual(len(queries), 8)
        self.assertEqual(len(set(queries)), 8)

    def test_until_target_charter_does_not_need_a_catalog_or_a_mutable_list(self):
        validate_charter(
            {
                "edit_policy": "except_immutable",
                "eval_command": [sys.executable, "evaluate.py"],
                "feature_catalog": [],
                "immutable": [],
                "loop": "until_target",
                "metrics": {
                    "primary": {"direction": "maximize", "name": "score", "noise": 0.1, "target": 5},
                    "protected": [],
                },
                "mutable": [],
            }
        )
        with self.assertRaises(ValueError):
            validate_charter(
                {
                    "eval_command": [sys.executable, "evaluate.py"],
                    "feature_catalog": [],
                    "immutable": ["evaluate.py"],
                    "metrics": {
                        "primary": {"direction": "maximize", "name": "score", "noise": 0.1},
                        "protected": [],
                    },
                    "mutable": [],
                }
            )

    def test_agent_command_pins_the_model(self):
        argv = agent_argv("C:/brief.json", "edit", which=lambda name: "C:/agent.exe" if name == "agent" else None)
        self.assertEqual(argv[0], "C:/agent.exe")
        self.assertIn("-p", argv)
        self.assertIn("grok-4.7-xhigh", argv)
        self.assertIn("C:/brief.json", argv[-1])
        cursor = agent_argv(
            "C:/brief.json",
            "research",
            which=lambda name: "C:/cursor.cmd" if name == "cursor.cmd" else None,
        )
        self.assertEqual(cursor[:2], ["C:/cursor.cmd", "agent"])
        with self.assertRaises(LaunchError):
            agent_argv("C:/brief.json", "edit", which=lambda _name: None)

    def test_skill_tells_a_later_session_the_loop(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "python -m absolute evolve",
            "--scenario",
            "test-driven development",
            "Do not commit",
            "worktree",
            "finishing-a-development-branch",
            "Do not mark a keep",
            "Plateau and `max_cycles`",
            "current method stands",
            "needs_human",
            "next feature-proposal group",
            "already kept",
            "already rejected",
        ):
            self.assertIn(phrase, text)
        self.assertNotIn("research cluster", text)
        self.assertNotIn("completed_cycle_limit", text)


class StateRecoveryTests(unittest.TestCase):
    def test_interrupted_publication_replays_without_duplicate_journal_entries(self):
        from absolute.store import CheckpointError, atomic_write, commit_stage, recover_checkpoint

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = {"id": "test", "script_head": "accepted", "status": "running"}
            board = {"best": {"score": 5}, "cycles": 1}
            entry = {"cycle": 1, "attempt": 1, "outcome": "keep", "commit": "accepted"}
            calls = []

            def interrupted(path, payload):
                calls.append(path)
                if len(calls) == 2:
                    raise OSError("simulated interrupted publication")
                atomic_write(path, payload)

            with patch("absolute.store.atomic_write", side_effect=interrupted), self.assertRaises(CheckpointError):
                commit_stage(root, run, board, entry)
            self.assertTrue(recover_checkpoint(root))
            self.assertEqual(load_run(root), run)
            self.assertEqual(read_json(root / "scoreboard.json"), board)
            self.assertEqual(read_journal(root), [entry])
            self.assertFalse(recover_checkpoint(root))
            recover_checkpoint(root, force=True)
            self.assertEqual(read_journal(root), [entry])

    def test_torn_tail_is_ignored_and_repaired_before_append(self):
        from absolute.store import append_journal

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "journal.jsonl").write_bytes(b'{"cycle": 1}\n{"cycle":')
            self.assertEqual(read_journal(root, limit=2), [{"cycle": 1}])
            append_journal(root, {"cycle": 2})
            self.assertEqual(read_journal(root), [{"cycle": 1}, {"cycle": 2}])


class LauncherProgressTests(unittest.TestCase):
    def test_only_one_runner_can_own_a_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            with run_lock(Path(directory)):
                with self.assertRaisesRegex(RuntimeError, "another runner"):
                    with run_lock(Path(directory)):
                        self.fail("second runner acquired lock")
            with run_lock(Path(directory)):
                pass

    def test_model_can_be_selected_without_a_fake_context_flag(self):
        with patch.dict("os.environ", {"ABSOLUTE_MODEL": "chosen-model"}):
            argv = agent_argv("brief.json", "optimize", which=lambda name: "agent")
        self.assertIn("chosen-model", argv)
        self.assertIn("stream-json", argv)
        self.assertNotIn("--context-window", argv)

    def test_worker_reports_progress_and_preserves_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            brief = {"run": directory, "brief_path": str(root / "worker.json"), "role": "edit", "cycle": 1}
            output = StringIO()
            with redirect_stderr(output):
                _run_command([sys.executable, "-c", "print('worker result')"], brief, directory)
            self.assertIn("worker_started", output.getvalue())
            self.assertIn("worker_finished", output.getvalue())
            self.assertIn("worker result", (root / "worker.log").read_text())
            events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
            self.assertEqual(events[-1]["returncode"], 0)

    def test_worker_timeout_is_bounded_and_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            brief = {"run": directory, "brief_path": str(root / "worker.json"), "role": "edit"}
            output = StringIO()
            with patch.dict("os.environ", {"ABSOLUTE_WORKER_TIMEOUT_SEC": "0.2", "ABSOLUTE_HEARTBEAT_SEC": "0.05"}):
                with redirect_stderr(output), self.assertRaisesRegex(LaunchError, "exceeded"):
                    _run_command([sys.executable, "-c", "import threading; threading.Event().wait()"], brief, directory)
            self.assertIn("worker_heartbeat", output.getvalue())
            self.assertIn("worker_timeout", output.getvalue())


class CopyTests(unittest.TestCase):
    def test_capture_skips_build_install_and_log(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            source = tmp / "pkg"
            (source / "build").mkdir(parents=True)
            (source / "build" / "a.o").write_text("obj", encoding="utf-8")
            (source / "install").mkdir()
            (source / "log").mkdir()
            (source / "keep.txt").write_text("yes", encoding="utf-8")
            destination = tmp / "dest"
            copy_package(source, destination)
            self.assertFalse((destination / "build").exists())
            self.assertFalse((destination / "install").exists())
            self.assertFalse((destination / "log").exists())
            self.assertEqual((destination / "keep.txt").read_text(encoding="utf-8"), "yes")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _behavior_test(package: Path, value: int = 3, latency: int = 4) -> None:
    (package / "test_behavior.py").write_text(
        "import unittest\nimport algo\n\n"
        "class Behavior(unittest.TestCase):\n"
        "    def test_holds(self):\n"
        f"        self.assertEqual(algo.VALUE, {value})\n"
        f"        self.assertEqual(algo.LATENCY_MS, {latency})\n",
        encoding="utf-8",
    )


def _write_algo(package: Path, value: int, latency: int) -> None:
    (package / "algo.py").write_text(f"VALUE = {value}\nLATENCY_MS = {latency}\n", encoding="utf-8")


class ToyLauncher:
    def __init__(self, mode="revert-then-hit"):
        self.mode = mode
        self.roles: list[str] = []
        self.counts: dict[str, int] = {}
        self.die_on = None
        self.external: Path | None = None
        self.fail_literature = False
        self.literature_failures = 0
        self.verdict = "adopt"
        self.bad_review = False
        self.bad_admission = False
        self.reject_all = False

    def __call__(self, brief):
        role = brief["role"]
        self.roles.append(role)
        if self.die_on and role == "edit" and brief.get("stage") == self.die_on:
            raise RuntimeError("runner died")
        if role == "literature" and brief.get("index") == 1 and self.fail_literature:
            self.literature_failures += 1
            self.fail_literature = False
            raise RuntimeError("literature missing")
        if role == "application":
            self._write(brief["output"], {"outputs": "score", "purpose": "toy", "users": "tests"})
        elif role == "feature_propose":
            index = int(brief.get("index") or 1)
            if index == 1:
                payload = {"feature_id": "restated", "hypothesis": "name the metric", "summary": "score"}
            elif index == 2:
                payload = {"feature_id": "extra", "hypothesis": "unused", "summary": "count calls"}
            else:
                payload = {"feature_id": "raise-value", "hypothesis": "raise the toy score", "summary": "raise the toy score"}
            self._write(brief["output"], payload)
        elif role.startswith("feature_review_"):
            if self.bad_review:
                self.bad_review = False
                Path(brief["output"]).write_text("not json", encoding="utf-8")
            else:
                self._write(
                    brief["output"],
                    {"judgments": [{"concern": role, "feature_id": "raise-value"}]},
                )
        elif role == "feature_admit":
            decisions = []
            for path in brief["proposals"]:
                proposal = json.loads(Path(path).read_text(encoding="utf-8"))
                if self.bad_admission:
                    accept = proposal["feature_id"] == "restated"
                elif self.reject_all:
                    accept = False
                else:
                    accept = proposal["feature_id"] == "raise-value"
                decisions.append(
                    {
                        "decision": "accept" if accept else "reject",
                        "feature_id": proposal["feature_id"],
                        "reason": "one feature" if accept else "rejected",
                    }
                )
            if self.bad_admission:
                self.bad_admission = False
            self._write(brief["output"], {"decisions": decisions})
        elif role == "literature":
            self._write(brief["output"], {"citations": ["note"], "findings": [brief["query"]], "query": brief["query"]})
        elif role == "literature_chair":
            self._write(
                brief["output"],
                {"citations": ["note"], "method": "direct assignment", "verdict": self.verdict},
            )
        elif role == "survey":
            self._write(brief["output"], {"points": ["latency lives in algo.py"]})
        elif role == "survey_review":
            self._write(brief["output"], {"points": ["latency lives in algo.py"]})
        elif role == "edit":
            self._edit(brief)

    def _edit(self, brief):
        stage = brief["stage"]
        self.counts[stage] = self.counts.get(stage, 0) + 1
        attempt = self.counts[stage]
        package = Path(brief["package_copy"])
        cycle = int(brief["cycle"])
        if self.mode == "eval-fail" and stage == "feature_edit" and attempt == 1:
            (package / "algo.py").write_text("this is not python\n", encoding="utf-8")
            (package / "marker.txt").write_text("1", encoding="utf-8")
            (package / "test_behavior.py").write_text(
                "import unittest\nfrom pathlib import Path\n\n"
                "class Behavior(unittest.TestCase):\n"
                "    def test_holds(self):\n"
                "        self.assertTrue(Path('marker.txt').is_file())\n",
                encoding="utf-8",
            )
        elif self.mode == "bad-immutable" and stage == "feature_edit" and attempt == 1:
            (package / "evaluate.py").write_text("print('hijack')\n", encoding="utf-8")
            _behavior_test(package, 5, 10)
        elif self.mode == "external" and stage == "feature_edit" and attempt == 1 and self.external:
            self.external.write_text(
                "import json,sys\njson.dump({'score': 100, 'latency_ms': 1}, sys.stdout)\n",
                encoding="utf-8",
            )
            _write_algo(package, 5, 10)
            _behavior_test(package, 5, 10)
        elif stage == "feature_edit" and attempt == 1 and cycle == 1:
            _write_algo(package, 0, 10)
            _behavior_test(package, 0, 10)
        elif stage == "inference_edit":
            value = 9 if cycle > 1 else 5
            _write_algo(package, value, 4)
            _behavior_test(package, value, 4)
        else:
            value = 9 if cycle > 1 else 5
            _write_algo(package, value, 10)
            _behavior_test(package, value, 10)
            if stage == "method_gate":
                (package / "method_note.py").write_text("METHOD = True\n", encoding="utf-8")
        self._write(brief["result"], {"behavior_test": [sys.executable, "-m", "unittest", "test_behavior"]})

    @staticmethod
    def _write(path, payload):
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload), encoding="utf-8")


class EvolveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.stack = self.tmp / "stack"
        self.stack.mkdir()
        shutil.copytree(TOY, self.stack / "algo_v1.1")
        self.runs = self.tmp / "runs"
        self.scenario = self.tmp / "scenario.md"
        self.scenario.write_text("A toy number is scored.\n", encoding="utf-8")
        self._attempts = STAGE_ATTEMPTS

    def tearDown(self):
        import absolute.loop as loop_mod

        loop_mod.STAGE_ATTEMPTS = self._attempts
        shutil.rmtree(self.tmp, ignore_errors=True)

    def evolve(self, launcher, **kwargs):
        payload = {
            "package": self.stack / "algo_v1.1",
            "scenario": self.scenario,
            "metric": "score",
            "direction": "maximize",
            "noise": 0.1,
            "target": 5,
            "eval_command": [sys.executable, "evaluate.py"],
            "launcher": launcher,
            "runs_root": self.runs,
            "timeout_sec": 30,
            "continuous": False,
        }
        payload.update(kwargs)
        return evolve_package(**payload)

    def test_subprocess_evolve_reverts_then_keeps_three_edits(self):
        scenario = self.scenario
        main(
            [
                "evolve",
                "--until-target",
                "--package",
                str(self.stack / "algo_v1.1"),
                "--scenario",
                str(scenario),
                "--metric",
                "score",
                "--direction",
                "maximize",
                "--noise",
                "0.1",
                "--target",
                "5",
                "--runs-root",
                str(self.runs),
                "--worker",
                str(WORKER),
                "--eval",
                sys.executable,
                "evaluate.py",
            ]
        )
        run = next(self.runs.iterdir())
        state = load_run(run)
        self.assertEqual(state["status"], "stopped")
        self.assertEqual(state["stop_reason"], "outputs_covered")
        self.assertEqual(
            [entry["outcome"] for entry in read_journal(run)],
            ["baseline", "revert", "keep", "revert"],
        )
        self.assertEqual(read_json(run / "scoreboard.json")["cycles"], 1)
        self.assertEqual((self.stack / "algo_v1.1" / "algo.py").read_text(encoding="utf-8"), "VALUE = 1\nLATENCY_MS = 10\n")
        copy = Path(state["package_copy"])
        self.assertEqual((copy / "algo.py").read_text(encoding="utf-8"), "VALUE = 5\nLATENCY_MS = 10\n")
        self.assertEqual((copy / "evaluate.py").read_bytes(), (self.stack / "algo_v1.1" / "evaluate.py").read_bytes())
        self.assertEqual(read_json(run / "charter.json")["feature_catalog"][0]["id"], "raise-value")
        edit = read_json(run / "workers" / "cycle-001" / "edit-feature_edit.json")
        self.assertNotIn("eval_command", edit)
        self.assertIn("attempts", edit["prompt"])
        self.assertNotIn("latency_ms", edit["prompt"])
        for phrase in (
            "Do not commit",
            "git worktree",
            "sign the design",
            "finishing-a-development-branch",
            "test-driven development",
            "verification-before-completion",
            "Do not mark a keep",
        ):
            self.assertIn(phrase, edit["prompt"])
        self.assertNotIn("evaluate.py", edit["prompt"])
        roles = [
            json.loads(line)["role"]
            for line in (run / "launch_log.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertIn("feature_review_scenario", roles)
        self.assertIn("feature_review_feasibility", roles)
        self.assertIn("feature_review_restatement", roles)
        self.assertIn("feature_admit", roles)
        self.assertNotIn("feature_panel", roles)
        self.assertTrue((run / "decisions" / "cycle-002" / "proposal-1.json").is_file())
        self.assertFalse((run / "sota" / "cycle-002").exists())
        kept = state["kept_features"]
        self.assertEqual([item["id"] for item in kept], ["raise-value"])
        literature = [
            json.loads(line)
            for line in (run / "launch_log.jsonl").read_text(encoding="utf-8").splitlines()
            if json.loads(line)["role"] == "literature"
        ]
        self.assertGreaterEqual(len({item["pid"] for item in literature}), 8)
        self.assertNotIn("needs_human", (run / "run.json").read_text(encoding="utf-8"))

    def test_continuous_search_rotates_metrics_and_continues_past_target(self):
        briefs = []

        def launcher(brief):
            briefs.append(brief)
            package = Path(brief["package_copy"])
            _write_algo(package, 5, 8 if brief["cycle"] == 1 else 4)
            _behavior_test(package, 5, 8 if brief["cycle"] == 1 else 4)
            ToyLauncher._write(brief["result"], {"hypothesis": "improve score then latency", "behavior_test": [sys.executable, "-B", "-m", "unittest", "test_behavior"]})

        run = self.evolve(launcher, continuous=True, completed_cycle_limit=2, eval_repeats=1)
        self.assertEqual([brief["role"] for brief in briefs], ["optimize", "optimize"])
        self.assertEqual([brief["focus"]["metric"] for brief in briefs], ["score", "latency_ms"])
        self.assertEqual([entry["outcome"] for entry in read_journal(run)], ["baseline", "keep", "keep"])
        self.assertEqual(load_run(run)["stop_reason"], "cycle_budget")
        self.assertFalse(load_run(run)["sota_verified"])
        self.assertTrue(briefs[1]["feedback"])
        self.assertNotIn("eval_command", briefs[0])
        self.assertLess(len(json.dumps(briefs[1]).encode()), 64000)
        self.assertEqual((self.stack / "algo_v1.1" / "algo.py").read_text(), "VALUE = 1\nLATENCY_MS = 10\n")

    def test_continuous_stop_request_and_resume(self):
        run = self.evolve(lambda brief: self.fail("must not launch"), continuous=True, completed_cycle_limit=0, eval_repeats=1)
        (run / "STOP").touch()
        continue_package(run, lambda brief: self.fail("must not launch"))
        self.assertEqual(load_run(run)["stop_reason"], "stop_requested")
        (run / "STOP").unlink()
        continue_package(run, lambda brief: self.fail("must not launch"), completed_cycle_limit=0)
        self.assertEqual(load_run(run)["stop_reason"], "cycle_budget")

    def test_cli_defaults_to_continuous_search_with_visible_dashboard(self):
        main([
            "evolve", "--package", str(self.stack / "algo_v1.1"), "--scenario", str(self.scenario),
            "--metric", "score", "--direction", "maximize", "--noise", "0.1", "--target", "1",
            "--max-cycles", "2", "--eval-repeats", "1", "--runs-root", str(self.runs),
            "--worker", str(WORKER), "--eval", sys.executable, "evaluate.py",
        ])
        run = next(self.runs.iterdir())
        self.assertEqual(load_run(run)["stop_reason"], "cycle_budget")
        self.assertEqual(read_json(run / "scoreboard.json")["keeps"], 2)
        events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
        self.assertEqual(sum(entry["event"] == "worker_started" for entry in events), 2)
        from contextlib import redirect_stdout

        output = StringIO()
        with redirect_stdout(output):
            main(["status", "--run", str(run), "--dashboard"])
        self.assertIn("latency_ms", output.getvalue())
        self.assertIn("SOTA: unverified", output.getvalue())
        self.assertIn("[##########]", output.getvalue())

    def test_continuous_interrupt_restores_the_incumbent(self):
        def launcher(brief):
            _write_algo(Path(brief["package_copy"]), 999, 999)
            raise KeyboardInterrupt()

        run = self.evolve(launcher, continuous=True, eval_repeats=1)
        self.assertEqual(load_run(run)["stop_reason"], "interrupted")
        self.assertIn("VALUE = 1", (Path(load_run(run)["package_copy"]) / "algo.py").read_text())

    def test_continuous_behavior_test_cannot_rewrite_the_scoreboard(self):
        def launcher(brief):
            package = Path(brief["package_copy"])
            _write_algo(package, 5, 4)
            board = str(Path(brief["run"]) / "scoreboard.json")
            (package / "test_guard.py").write_text(
                f"from pathlib import Path\nPath({board!r}).write_text('{{}}')\n", encoding="utf-8",
            )
            ToyLauncher._write(brief["result"], {"hypothesis": "tamper during testing", "behavior_test": [sys.executable, "test_guard.py"]})

        run = self.evolve(launcher, continuous=True, eval_repeats=1, completed_cycle_limit=1)
        self.assertEqual(read_journal(run)[-1]["outcome"], "bad_edit")
        self.assertEqual(read_json(run / "scoreboard.json")["best"]["score"], 1)


    def test_continuous_worker_failure_rolls_back_and_retries(self):
        calls = []

        def launcher(brief):
            calls.append(brief)
            package = Path(brief["package_copy"])
            if len(calls) == 1:
                _write_algo(package, 999, 999)
                raise LaunchError("transient failure")
            self.assertIn("VALUE = 1", (package / "algo.py").read_text())
            _write_algo(package, 5, 4)
            _behavior_test(package, 5, 4)
            ToyLauncher._write(brief["result"], {"hypothesis": "recover", "behavior_test": [sys.executable, "-B", "-m", "unittest", "test_behavior"]})

        with patch("absolute.loop._cooldown"):
            run = self.evolve(launcher, continuous=True, completed_cycle_limit=2, eval_repeats=1)
        self.assertEqual([entry["outcome"] for entry in read_journal(run)], ["baseline", "worker_failed", "keep"])

    def test_worker_commit_keeps_the_actual_candidate_on_resume(self):
        from absolute.engine import _git, head_sha

        def launcher(brief):
            package = Path(brief["package_copy"])
            _write_algo(package, 5, 4)
            _behavior_test(package, 5, 4)
            _git(package, ["add", "-A"])
            _git(package, ["commit", "-m", "worker candidate"])
            ToyLauncher._write(brief["result"], {"hypothesis": "candidate commit", "behavior_test": [sys.executable, "-B", "-m", "unittest", "test_behavior"]})

        run = self.evolve(launcher, continuous=True, completed_cycle_limit=1, eval_repeats=1)
        package = Path(load_run(run)["package_copy"])
        self.assertEqual(load_run(run)["script_head"], head_sha(package))
        continue_package(run, lambda brief: self.fail("must not launch"), completed_cycle_limit=1)
        self.assertIn("VALUE = 5", (package / "algo.py").read_text())

    def test_noop_behavior_command_cannot_replace_frozen_regression_gate(self):
        def launcher(brief):
            _write_algo(Path(brief["package_copy"]), 5, 4)
            ToyLauncher._write(brief["result"], {"hypothesis": "skip testing", "behavior_test": [sys.executable, "-c", "pass"]})

        run = self.evolve(launcher, continuous=True, completed_cycle_limit=1, eval_repeats=1)
        self.assertEqual(read_journal(run)[-1]["outcome"], "bad_edit")
        self.assertIn("inline", read_journal(run)[-1]["error"])

    def test_frozen_regression_tests_cannot_be_weakened(self):
        def launcher(brief):
            package = Path(brief["package_copy"])
            _write_algo(package, 5, 4)
            (package / "test_algo.py").write_text("pass\n", encoding="utf-8")
            _behavior_test(package, 5, 4)
            ToyLauncher._write(brief["result"], {"hypothesis": "weaken tests", "behavior_test": [sys.executable, "-B", "-m", "unittest", "test_behavior"]})

        run = self.evolve(launcher, continuous=True, completed_cycle_limit=1, eval_repeats=1)
        self.assertEqual(read_journal(run)[-1]["outcome"], "bad_edit")
        self.assertIn("test_algo.py", read_journal(run)[-1]["error"])


    def test_message_schema_detects_type_and_order_changes(self):
        from absolute.package import message_schema

        path = self.tmp / "Pose.msg"
        path.write_text("float64 position\nbool valid\n", encoding="utf-8")
        before = message_schema(self.tmp)
        path.write_text("string position\nbool valid\n", encoding="utf-8")
        self.assertNotEqual(before, message_schema(self.tmp))

    def test_missing_scenario_does_not_copy_the_package(self):
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                main(
                    [
                        "evolve",
                        "--package",
                        str(self.stack / "algo_v1.1"),
                        "--metric",
                        "score",
                        "--direction",
                        "maximize",
                        "--noise",
                        "0.1",
                        "--target",
                        "5",
                        "--runs-root",
                        str(self.runs),
                        "--eval",
                        sys.executable,
                        "evaluate.py",
                    ]
                )
        self.assertFalse(self.runs.exists())

    def test_eval_failure_and_a_bad_edit_do_not_stop_the_run(self):
        run = self.evolve(ToyLauncher("eval-fail"))
        outcomes = [entry["outcome"] for entry in read_journal(run)]
        self.assertEqual(outcomes[0], "baseline")
        self.assertIn("eval_failed", outcomes)
        self.assertEqual(load_run(run)["stop_reason"], "outputs_covered")
        bad = ToyLauncher("bad-immutable")
        run = self.evolve(bad, runs_root=self.tmp / "runs-bad")
        journal = read_journal(run)
        self.assertEqual(journal[1]["outcome"], "bad_edit")
        self.assertEqual(load_run(run)["stop_reason"], "outputs_covered")
        copy = Path(load_run(run)["package_copy"])
        self.assertIn("algo.VALUE", (copy / "evaluate.py").read_text(encoding="utf-8"))
        self.assertNotIn("hijack", (copy / "evaluate.py").read_text(encoding="utf-8"))

    def test_an_external_scorer_written_by_the_editor_is_restored(self):
        script = self.tmp / "score.py"
        script.write_text(
            "import json, sys\nfrom pathlib import Path\n"
            "text = Path('algo.py').read_text(encoding='utf-8')\n"
            "value = int([line.split('=')[1] for line in text.splitlines() if line.startswith('VALUE')][0])\n"
            "latency = int([line.split('=')[1] for line in text.splitlines() if line.startswith('LATENCY')][0])\n"
            "json.dump({'latency_ms': latency, 'score': value}, sys.stdout)\n",
            encoding="utf-8",
        )
        original = script.read_bytes()
        launcher = ToyLauncher("external")
        launcher.external = script
        run = self.evolve(launcher, eval_command=[sys.executable, str(script)])
        self.assertEqual(script.read_bytes(), original)
        self.assertNotIn("100", script.read_text(encoding="utf-8"))
        journal = read_journal(run)
        self.assertEqual(journal[1]["outcome"], "bad_edit")
        self.assertEqual(load_run(run)["stop_reason"], "outputs_covered")

    def test_a_literature_failure_does_not_start_an_edit(self):
        launcher = ToyLauncher()
        launcher.fail_literature = True
        with self.assertRaises(RuntimeError):
            self.evolve(launcher)
        self.assertNotIn("edit", launcher.roles)
        self.assertEqual(load_run(next(self.runs.iterdir()))["status"], "running")

    def test_a_latency_only_edit_is_reverted(self):
        run = prepare_run(
            package=self.stack / "algo_v1.1",
            scenario=self.scenario,
            metric="score",
            direction="maximize",
            noise=0.1,
            target=5,
            eval_command=[sys.executable, "evaluate.py"],
            runs_root=self.runs,
            timeout_sec=30,
        )
        copy = Path(load_run(run)["package_copy"])
        _behavior_test(copy)
        _write_algo(copy, 3, 4)
        with runner_authority():
            entry = score_stage(
                run,
                read_json(run / "charter.json"),
                stage="inference_edit",
                cycle_n=1,
                hypothesis="lower measured latency",
                base_sha=load_run(run)["script_head"],
                behavior_test=[sys.executable, "-m", "unittest", "test_behavior"],
                pre_metrics={"score": 3, "latency_ms": 10},
            )
        self.assertEqual(entry["outcome"], "revert")
        self.assertEqual(entry["error"], "latency-only")
        self.assertEqual((copy / "algo.py").read_text(encoding="utf-8"), "VALUE = 1\nLATENCY_MS = 10\n")

    def test_search_stage_accepts_latency_only_with_existing_tests(self):
        run = prepare_run(
            package=self.stack / "algo_v1.1", scenario=self.scenario,
            metric="score", direction="maximize", noise=0.1, target=5,
            eval_command=[sys.executable, "evaluate.py"], runs_root=self.runs,
        )
        package = Path(load_run(run)["package_copy"])
        _write_algo(package, 1, 4)
        (package / "test_behavior.py").write_text(
            "import unittest, algo\nclass Behavior(unittest.TestCase):\n"
            "    def test_score(self):\n        self.assertEqual(algo.VALUE, 1)\n", encoding="utf-8",
        )
        with runner_authority():
            entry = score_stage(
                run, read_json(run / "charter.json"), stage="search_edit", cycle_n=1,
                hypothesis="preserve score and reduce latency", base_sha=load_run(run)["script_head"],
                behavior_test=[sys.executable, "-B", "-m", "unittest", "test_behavior"],
                pre_metrics={"score": 1, "latency_ms": 10},
            )
        self.assertEqual(entry["outcome"], "keep")
        samples = read_json(run / "eval" / "cycle-000001-candidate.json")["samples"]
        self.assertEqual(len(samples), 3)
        self.assertEqual(read_json(run / "scoreboard.json")["best"]["latency_ms"], 4)

    def test_removing_a_message_field_is_a_bad_edit(self):
        (self.stack / "algo_v1.1" / "Pose.msg").write_text("float64 width\nfloat64 height\n", encoding="utf-8")
        run = prepare_run(
            package=self.stack / "algo_v1.1",
            scenario=self.scenario,
            metric="score",
            direction="maximize",
            noise=0.1,
            target=5,
            eval_command=[sys.executable, "evaluate.py"],
            runs_root=self.runs,
            timeout_sec=30,
        )
        copy = Path(load_run(run)["package_copy"])
        (copy / "Pose.msg").write_text("float64 width\n", encoding="utf-8")
        _behavior_test(copy, 5, 10)
        _write_algo(copy, 5, 10)
        with runner_authority():
            entry = score_stage(
                run,
                read_json(run / "charter.json"),
                stage="feature_edit",
                cycle_n=1,
                hypothesis="drop height",
                base_sha=load_run(run)["script_head"],
                behavior_test=[sys.executable, "-m", "unittest", "test_behavior"],
                pre_metrics={"score": 1, "latency_ms": 10},
            )
        self.assertEqual(entry["outcome"], "bad_edit")
        self.assertIn("height", entry["error"])
        self.assertIn("float64 height", (copy / "Pose.msg").read_text(encoding="utf-8"))

    def test_a_behavior_test_that_names_the_scorer_is_not_run(self):
        run = prepare_run(
            package=self.stack / "algo_v1.1",
            scenario=self.scenario,
            metric="score",
            direction="maximize",
            noise=0.1,
            target=5,
            eval_command=[sys.executable, "evaluate.py"],
            runs_root=self.runs,
            timeout_sec=30,
        )
        copy = Path(load_run(run)["package_copy"])
        before = (copy / "evaluate.py").read_bytes()
        charter = read_json(run / "charter.json")
        with self.assertRaises(RuntimeError):
            score_stage(
                run,
                charter,
                stage="feature_edit",
                cycle_n=1,
                hypothesis="hijack",
                base_sha=load_run(run)["script_head"],
                behavior_test=[sys.executable, "evaluate.py"],
                pre_metrics={"score": 1, "latency_ms": 10},
            )
        with runner_authority():
            entry = score_stage(
                run,
                charter,
                stage="feature_edit",
                cycle_n=1,
                hypothesis="hijack",
                base_sha=load_run(run)["script_head"],
                behavior_test=[sys.executable, "evaluate.py", "--extra"],
                pre_metrics={"score": 1, "latency_ms": 10},
            )
        self.assertEqual(entry["outcome"], "bad_edit")
        self.assertEqual((copy / "evaluate.py").read_bytes(), before)
        self.assertIn("scorer", entry["error"])

    def test_the_cli_cannot_score_an_evolve_run(self):
        run = prepare_run(
            package=self.stack / "algo_v1.1",
            scenario=self.scenario,
            metric="score",
            direction="maximize",
            noise=0.1,
            target=5,
            eval_command=[sys.executable, "evaluate.py"],
            runs_root=self.runs,
            timeout_sec=30,
        )
        with self.assertRaises(RuntimeError):
            admit(run, read_json(run / "charter.json"), "implementation", "unarmed", None)
        self.assertIsNone(load_run(run).get("open_admit"))
        with runner_authority():
            admit(run, read_json(run / "charter.json"), "implementation", "armed", None)
        stderr = StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as caught:
                main(["cycle", "--run", str(run)])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("only the runner", stderr.getvalue())
        self.assertEqual(load_run(run)["status"], "running")
        self.assertIsNotNone(load_run(run).get("open_admit"))

    def test_one_cycle_keeps_three_stages_without_the_implementation_streak(self):
        run = self.evolve(ToyLauncher())
        stages = [entry.get("stage") for entry in read_journal(run) if entry.get("outcome") == "keep"]
        self.assertEqual(stages, ["feature_edit"])
        self.assertEqual(read_json(run / "scoreboard.json")["implementation_keep_streak"], 0)
        self.assertEqual(load_run(run)["stop_reason"], "outputs_covered")

    def test_baseline_at_the_target_still_launches_workers(self):
        launcher = ToyLauncher()
        run = self.evolve(launcher, target=1)
        self.assertNotIn("application", launcher.roles)
        self.assertEqual(load_run(run)["stop_reason"], "oracle_saturated")
        self.assertIn("not a state-of-the-art claim", (run / "handoff.md").read_text(encoding="utf-8"))

    def test_a_dead_runner_continues_the_same_folder(self):
        launcher = ToyLauncher()
        launcher.die_on = "inference_edit"
        with self.assertRaises(RuntimeError):
            self.evolve(launcher)
        run = next(self.runs.iterdir())
        self.assertEqual(load_run(run)["status"], "running")
        self.assertEqual(read_journal(run)[1]["outcome"], "revert")
        launcher.die_on = None
        continue_package(run, launcher)
        self.assertEqual(load_run(run)["stop_reason"], "outputs_covered")
        self.assertEqual(load_run(run)["id"], run.name)

    def test_unchanged_scenario_skips_application_on_the_next_cycle(self):
        launcher = ToyLauncher()
        run = self.evolve(launcher, target=9)
        self.assertEqual(launcher.roles.count("application"), 1)
        self.assertEqual(load_run(run)["stop_reason"], "uncovered_outputs")

    def test_known_ids_are_nothing_new_and_a_target_is_not_the_classifier(self):
        kept = [{"id": "raise-value", "summary": "raise the toy score"}]
        rejected = [{"id": "extra", "summary": "count calls"}]
        run = {"kept_features": kept, "rejected_features": rejected}
        known = [
            {"feature_id": "raise-value", "summary": "raise the toy score"},
            {"feature_id": "extra", "summary": "count calls"},
            {"feature_id": "extra", "summary": "count calls"},
        ]
        self.assertTrue(round_is_nothing_new(known, run))
        self.assertEqual(len(unique_proposals(known)), 2)
        fresh = [{"feature_id": "fresh", "summary": "a new idea"}, {"feature_id": "fresh", "summary": "a new idea"}]
        self.assertFalse(round_is_nothing_new(fresh, run))
        self.assertEqual(len(unique_proposals(fresh)), 1)
        self.assertFalse(round_is_nothing_new([], {"kept_features": [], "rejected_features": []}))

    def test_at_target_stands_still_launches_the_next_proposers(self):
        launcher = ToyLauncher()
        launcher.verdict = "stands"
        run = self.evolve(launcher, target=5)
        state = load_run(run)
        self.assertEqual(state["stop_reason"], "outputs_covered")
        self.assertEqual(read_json(run / "scoreboard.json")["cycles"], 1)
        self.assertEqual(launcher.roles.count("feature_propose"), 6)
        self.assertNotIn("method_gate", launcher.counts)
        self.assertIn("inference_edit", launcher.counts)
        self.assertEqual(launcher.roles.count("literature"), 8)
        self.assertTrue((run / "decisions" / "cycle-002" / "proposal-1.json").is_file())
        self.assertFalse((run / "sota" / "cycle-002").exists())
        brief = read_json(run / "workers" / "cycle-002" / "proposal-1.json")
        self.assertIn("prior_note", brief)
        self.assertIn("raise-value", brief["prior_note"])
        self.assertNotIn("eval_command", brief)
        review = read_json(run / "workers" / "cycle-001" / "review-scenario.json")
        self.assertNotIn("eval_command", review)
        self.assertIn("feature_review_scenario", launcher.roles)
        self.assertIn("feature_admit", launcher.roles)
        self.assertNotIn("feature_panel", launcher.roles)
        self.assertIn("admitted nothing new", (run / "handoff.md").read_text(encoding="utf-8"))
        self.assertEqual([item["id"] for item in state["kept_features"]], ["raise-value"])
        self.assertEqual(
            sorted(item["id"] for item in state["rejected_features"]),
            ["extra", "restated"],
        )

    def test_completed_cycle_limit_leaves_the_run_running(self):
        launcher = ToyLauncher()
        run = self.evolve(launcher, completed_cycle_limit=1)
        state = load_run(run)
        self.assertEqual(state["status"], "running")
        self.assertEqual(state["stop_reason"], "")
        self.assertEqual(read_json(run / "scoreboard.json")["cycles"], 1)
        self.assertFalse((run / "decisions" / "cycle-002").exists())
        self.assertIn("continue this folder", (run / "handoff.md").read_text(encoding="utf-8"))

    def test_a_reject_all_stops_before_literature(self):
        launcher = ToyLauncher()
        launcher.reject_all = True
        run = self.evolve(launcher)
        self.assertEqual(load_run(run)["stop_reason"], "uncovered_outputs")
        self.assertNotIn("literature", launcher.roles)
        self.assertEqual(read_json(run / "scoreboard.json")["cycles"], 0)
        self.assertEqual(launcher.roles.count("feature_propose"), 6)

    def test_a_bad_review_retries_the_panel_and_still_reaches_literature(self):
        launcher = ToyLauncher()
        launcher.bad_review = True
        run = self.evolve(launcher, completed_cycle_limit=1)
        self.assertGreaterEqual(launcher.roles.count("feature_review_scenario"), 2)
        self.assertIn("literature", launcher.roles)
        self.assertEqual(load_run(run)["status"], "running")

    def test_a_bad_admission_retries_and_does_not_stop(self):
        launcher = ToyLauncher()
        launcher.bad_admission = True
        run = self.evolve(launcher, completed_cycle_limit=1)
        self.assertEqual(launcher.roles.count("feature_admit"), 2)
        self.assertIn("literature", launcher.roles)
        self.assertEqual(load_run(run)["status"], "running")
        self.assertEqual(load_run(run)["kept_features"][0]["id"], "raise-value")

    def test_an_edit_that_rewrites_the_contract_is_restored(self):
        class Tamper(ToyLauncher):
            def __call__(self, brief):
                if (
                    brief["role"] == "edit"
                    and brief.get("stage") == "feature_edit"
                    and self.counts.get("feature_edit", 0) == 0
                ):
                    path = Path(brief["run"]) / "eval" / "contract.json"
                    path.write_text('{"edits": "allow"}\n', encoding="utf-8")
                super().__call__(brief)

        run = self.evolve(Tamper())
        journal = read_journal(run)
        self.assertIn("edit worker rewrote the metric contract", [entry.get("error") for entry in journal])
        contract = read_json(run / "eval" / "contract.json")
        score = next(item for item in contract["metrics"] if item["id"] == "score")
        self.assertEqual(float(score["target"]), 5.0)
        self.assertEqual(score["direction"], "maximize")
        digest = hashlib.sha256((run / "eval" / "contract.json").read_bytes()).hexdigest()
        self.assertEqual(digest, load_run(run)["contract_sha256"])
        self.assertEqual(load_run(run)["stop_reason"], "outputs_covered")


if __name__ == "__main__":
    unittest.main()

