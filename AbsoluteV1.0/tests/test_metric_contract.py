import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from absolute.cli import build_parser, main
from absolute.contract import accept_discovered_metrics, bind_metrics, contract_changes, normalize_metric, obligation_sentences
from absolute.engine import aggregate_metric, runner_authority, score_stage, search_keep_reason, search_metric_specs
from absolute.loop import evolve_package, metric_discovery_queries, metric_followup_queries
from absolute.store import load_run, read_json

FORBIDDEN = ("pose_error_m", "dimension_error_m", "selection_error", "scenario_error")
HEADER = (
    "import json, sys\n"
    "from pathlib import Path\n"
    "sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
    "import algo\n"
)


def _metric(ident, direction, target, role, description):
    return {
        "description": description,
        "direction": direction,
        "id": ident,
        "noise": 0.0,
        "path": f"/{ident}",
        "role": role,
        "target": target,
        "witnesses": [],
    }


class Discover:
    def __init__(self):
        self.briefs = []

    def __call__(self, brief):
        self.briefs.append(brief)
        if brief["role"] != "metric_discover":
            raise RuntimeError(brief["role"])
        source = Path(brief["package_copy"], "evaluate.py").read_text(encoding="utf-8")
        metrics = []
        if brief.get("discovery_round") == 1:
            if "residual_l2" in source:
                metrics.append(_metric("residual_l2", "minimize", 1e-8, "objective", "L2 residual of the linear solve."))
            if "path_length" in source:
                metrics.append(_metric("path_length", "minimize", 10, "objective", "Length of the returned path."))
            if "collision_count" in source:
                metrics.append(_metric("collision_count", "minimize", 0, "protected", "Collisions against obstacles."))
        elif "iterations" in source:
            metrics.append(_metric("iterations", "minimize", 0, "objective", "Iterations used by the solve."))
        destination = Path(brief["output"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps({"metrics": metrics, "query": brief["query"]}), encoding="utf-8")


def _package(root, name, algo, evaluate):
    package = root / name
    package.mkdir(parents=True)
    (package / "algo.py").write_text(algo, encoding="utf-8")
    (package / "evaluate.py").write_text(HEADER + evaluate, encoding="utf-8")
    return package


def _ids(contract, role):
    return [item["id"] for item in contract["metrics"] if item["role"] == role]


class EvaluationAssetsTests(unittest.TestCase):
    def test_module_entrypoint_is_protected(self):
        from absolute.evaluation import command_files

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evaluate.py").write_text("pass\n", encoding="utf-8")
            self.assertIn(root / "evaluate.py", command_files([sys.executable, "-m", "evaluate"], root))

    def test_inline_regression_commands_are_rejected(self):
        from absolute.evaluation import validate_command

        with self.assertRaisesRegex(ValueError, "inline"):
            validate_command([sys.executable, "-c", "pass"])

    def test_manifest_detects_evaluator_and_dataset_changes(self):
        from absolute.evaluation import MANIFEST, verify_benchmark
        from absolute.package import file_hash
        from absolute.store import atomic_write, save_run

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evaluate.py").write_text("pass\n", encoding="utf-8")
            (root / "test_api.py").write_text("pass\n", encoding="utf-8")
            data = root / "cases.csv"
            data.write_text("input,answer\n1,2\n", encoding="utf-8")
            atomic_write(root / MANIFEST, {"hashes": {str(data): file_hash(data)}})
            save_run(root, {"id": "test", "benchmark_sha256": file_hash(root / MANIFEST)})
            self.assertIsNotNone(verify_benchmark(root))
            data.write_text("input,answer\n1,3\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "asset changed"):
                verify_benchmark(root)

    def test_required_cases_must_be_reported(self):
        from absolute.evaluation import check_case_evidence

        with self.assertRaisesRegex(ValueError, "required benchmark cases"):
            check_case_evidence({"cases": [{"id": "roundtrip"}]}, {"quality": 1})
        check_case_evidence({"cases": [{"id": "roundtrip"}]}, {"quality": 1, "_cases": ["roundtrip"]})


class EvaluationPreparationTests(unittest.TestCase):
    def test_module_entrypoint_is_discovered_without_importing_it(self):
        from absolute.evaluation import command_files, inventory

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evaluate.py").write_text("raise RuntimeError('must not import')", encoding="utf-8")
            self.assertEqual(command_files([sys.executable, "-m", "evaluate"], root)[-1], (root / "evaluate.py").resolve())
            self.assertEqual(inventory(root)["evaluators"], ["evaluate.py"])

    def test_inline_and_empty_regression_commands_are_rejected(self):
        from absolute.evaluation import validate_command

        for command in ([], [sys.executable, "-c", "pass"], ["pytest", "--collect-only"], ["echo", "ok"]):
            with self.subTest(command=command), self.assertRaises(ValueError):
                validate_command(command)


class EvaluationBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.package = self.root / "candidate"
        shutil.copytree(ROOT / "examples" / "toy_stack" / "algo_v1.1", self.package)
        self.scenario = self.root / "scenario.md"
        self.scenario.write_text("Improve the returned score.\nAvoid invalid outputs.\n", encoding="utf-8")
        self.roles = []
        self.missing = False
        self.fake = False

    def tearDown(self):
        self.temp.cleanup()

    def launcher(self, brief):
        self.roles.append(brief["role"])
        if brief["role"] == "evaluation_plan":
            self.assertFalse((Path(brief["run"]) / "eval" / "baseline.json").exists())
            payload = {"metrics": [_metric("score", "maximize", None, "objective", "Returned score")],
                       "requirements": [{"text": "Improve the returned score.", "metrics": ["score"], "validation_needed": "Independent representative workload"}]}
        elif self.missing:
            payload = {"missing_evidence": ["Provide labeled recordings for accuracy validation."]}
        else:
            folder = Path(brief["benchmark_dir"])
            evaluator = folder / "measure.py"
            expression = "1" if self.fake else "algo.VALUE"
            evaluator.write_text(
                "import json, sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path.cwd()))\nimport algo\n"
                f"print(json.dumps({{'score': {expression}, '_cases': ['nonnegative']}}))\n", encoding="utf-8",
            )
            guard = folder / "guard.py"
            guard.write_text(
                "import sys, unittest\nfrom pathlib import Path\nsys.path.insert(0, str(Path.cwd()))\nimport algo\n"
                "class Guard(unittest.TestCase):\n    def test_valid(self):\n        self.assertGreaterEqual(algo.VALUE, 0)\n"
                "unittest.main()\n", encoding="utf-8",
            )
            payload = {
                "eval_command": [sys.executable, str(evaluator)], "validation_commands": [[sys.executable, str(guard)]],
                "files": [str(evaluator), str(guard)], "oracle": "Toy domain exposes a numeric objective; guard checks a necessary invariant.",
                "limitations": ["Toy fixture only; not domain validation."], "cases": [{"id": "nonnegative"}],
                "negative_controls": [{"metric": "score", "path": "algo.py", "replacement": "VALUE = 0\nLATENCY_MS = 10\n"}],
            }
        destination = Path(brief["output"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload), encoding="utf-8")

    def evolve(self, **kwargs):
        return evolve_package(package=self.package, scenario=self.scenario, launcher=self.launcher,
                              runs_root=self.root / "runs", completed_cycle_limit=0, eval_repeats=1, **kwargs)

    def test_plan_precedes_reusing_an_existing_evaluator(self):
        run = self.evolve()
        self.assertEqual(self.roles, ["evaluation_plan"])
        self.assertEqual(load_run(run)["evaluation_scope"], "discovered")
        self.assertTrue(load_run(run)["setup_complete"])
        self.assertIsNone(read_json(run / "charter.json")["metrics"]["primary"]["target"])
        coverage = read_json(run / "eval" / "coverage.json")["requirements"]
        self.assertEqual([item["status"] for item in coverage], ["measured_proxy", "unmeasured"])

    def test_builder_qualifies_generated_benchmark_with_a_negative_control(self):
        (self.package / "evaluate.py").unlink()
        run = self.evolve()
        self.assertEqual(self.roles, ["evaluation_plan", "benchmark_build"])
        self.assertTrue(load_run(run)["setup_complete"])
        self.assertEqual(load_run(run)["evaluation_scope"], "generated")
        self.assertIn("VALUE = 1", (self.package / "algo.py").read_text())

    def test_constant_generated_scorer_is_blocked(self):
        (self.package / "evaluate.py").unlink()
        self.fake = True
        run = self.evolve()
        self.assertFalse(load_run(run)["setup_complete"])
        self.assertIn("did not worsen", load_run(run)["stop_reason"])
        self.assertFalse((run / "scoreboard.json").exists())
        from absolute.loop import continue_package

        self.fake = False
        continue_package(run, self.launcher, completed_cycle_limit=0)
        self.assertTrue(load_run(run)["setup_complete"])

    def test_missing_optional_objective_remains_an_explicit_gap(self):
        original_launcher = self.launcher

        def launcher(brief):
            original_launcher(brief)
            if brief["role"] == "evaluation_plan":
                path = Path(brief["output"])
                payload = read_json(path)
                payload["metrics"].append(_metric("robustness", "maximize", None, "objective", "Unmeasured robustness"))
                payload["requirements"].append({"text": "Avoid invalid outputs.", "metrics": ["robustness"]})
                path.write_text(json.dumps(payload), encoding="utf-8")

        self.launcher = launcher
        run = self.evolve()
        self.assertTrue(load_run(run)["setup_complete"])
        self.assertNotIn("robustness", read_json(run / "scoreboard.json")["best"])
        self.assertIn("robustness", (run / "eval" / "coverage.md").read_text())

    def test_missing_protected_metric_blocks_optimization(self):
        original_launcher = self.launcher

        def launcher(brief):
            original_launcher(brief)
            if brief["role"] == "evaluation_plan":
                path = Path(brief["output"])
                payload = read_json(path)
                payload["metrics"].append(_metric("failures", "minimize", 0, "protected", "Failure count"))
                path.write_text(json.dumps(payload), encoding="utf-8")

        self.launcher = launcher
        run = self.evolve()
        self.assertFalse(load_run(run)["setup_complete"])
        self.assertIn("required measurement is unavailable", load_run(run)["stop_reason"])

    def test_missing_evidence_pauses_and_can_resume_same_folder(self):
        from absolute.loop import continue_package

        (self.package / "evaluate.py").unlink()
        self.missing = True
        run = self.evolve()
        self.assertEqual(load_run(run)["status"], "paused")
        self.assertIn("labeled recordings", (run / "eval" / "coverage.md").read_text())
        self.missing = False
        continue_package(run, self.launcher, completed_cycle_limit=0)
        self.assertTrue(load_run(run)["setup_complete"])
        self.assertEqual(self.roles.count("evaluation_plan"), 1)


class MetricPolicyTests(unittest.TestCase):
    def test_intermittent_constraint_failures_cannot_hide_in_a_median(self):
        charter = {}
        bind_metrics(charter, [
            _metric("quality", "maximize", None, "objective", "quality"),
            _metric("failures", "minimize", 0, "protected", "failures"),
        ])
        spec = next(item for item in search_metric_specs(charter) if item["metric"] == "failures")
        self.assertEqual(aggregate_metric(spec, [0, 1, 0]), 1)
        before = {"quality": 1, "failures": 0}
        self.assertIn("hard limit", search_keep_reason(charter, before, {"quality": 2, "failures": 1}, before))
        self.assertEqual(aggregate_metric({"direction": "minimize", "aggregation": "mean"}, [1, 2, 3]), 2)

    def test_latency_keeps_its_declared_role_target_and_noise(self):
        metric = _metric("latency_ms", "minimize", 50, "objective", "runtime")
        metric["noise"] = 0.5
        rows = accept_discovered_metrics([{"metrics": [metric]}], {"latency_ms": 100}, "")
        self.assertEqual(rows, [metric])
        again = accept_discovered_metrics([{"metrics": [metric]}], {"latency_ms": 90}, "", sealed=rows)
        self.assertEqual(again, rows)

    def test_targetless_objectives_can_be_bound(self):
        metric = _metric("quality", "maximize", None, "objective", "quality")
        rows = accept_discovered_metrics([{"metrics": [metric]}], {"quality": 1}, "")
        charter = {}
        bind_metrics(charter, rows)
        self.assertIsNone(charter["metrics"]["primary"]["target"])
        self.assertEqual(len(charter["required_outputs"]), 1)

    def test_invalid_numeric_policy_is_rejected(self):
        for key in ("noise", "min_effect", "max_regression"):
            for value in (-1, float("nan"), float("inf"), True):
                with self.subTest(key=key, value=value):
                    metric = _metric("quality", "maximize", None, "objective", "quality")
                    metric[key] = value
                    with self.assertRaises(ValueError):
                        normalize_metric(metric, "")

    def test_policy_fields_are_sealed_and_distinct(self):
        metric = _metric("runtime", "minimize", None, "protected", "runtime")
        metric.update(noise=0.2, min_effect=0.5, max_regression=0, hard_limit=50, aggregation="worst", units="ms")
        normalized = normalize_metric(metric, "")
        charter = {}
        bind_metrics(charter, [_metric("quality", "maximize", None, "objective", "quality"), normalized])
        protected = charter["metrics"]["protected"][0]
        self.assertEqual(protected["noise"], 0.2)
        self.assertEqual(protected["max_regression"], 0)
        changed = dict(normalized, aggregation="median")
        self.assertIn("aggregation runtime", contract_changes([normalized], [changed]))


class MetricContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.runs = self.tmp / "runs"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def evolve(self, package, scenario, launcher):
        return evolve_package(
            package=package,
            scenario=scenario,
            eval_command=[sys.executable, "evaluate.py"],
            launcher=launcher,
            runs_root=self.runs,
            timeout_sec=30,
            completed_cycle_limit=0,
            continuous=False,
        )

    def test_queries_are_disjoint(self):
        first = metric_discovery_queries("solver_toy")
        second = metric_followup_queries("planner_toy")
        self.assertEqual(len(first), 3)
        self.assertEqual(len(first), len(set(first)))
        self.assertEqual(len(second), len(set(second)))
        self.assertTrue(set(first).isdisjoint(second))

    def test_framework_has_no_pallet_metric_names(self):
        files = list((ROOT / "absolute").rglob("*.py"))
        files.extend([ROOT / "SKILL.md", ROOT / "README.md"])
        for path in files:
            text = path.read_text(encoding="utf-8")
            for name in FORBIDDEN:
                self.assertNotIn(name, text, f"{name} in {path.name}")

    def test_cli_omits_metric_flags(self):
        args = build_parser().parse_args(
            ["evolve", "--package", "pkg", "--scenario", "scenario.md", "--eval", sys.executable, "evaluate.py"]
        )
        self.assertIsNone(args.metric)
        with self.assertRaises(SystemExit) as caught:
            main(["evolve", "--until-target", "--package", "pkg", "--scenario", "scenario.md", "--runs-root", str(self.runs)])
        self.assertIn("eval", str(caught.exception))
        self.assertFalse(self.runs.exists())
        with self.assertRaises(SystemExit) as partial:
            main(
                [
                    "evolve",
                    "--package",
                    "pkg",
                    "--scenario",
                    "scenario.md",
                    "--metric",
                    "score",
                    "--eval",
                    sys.executable,
                    "evaluate.py",
                ]
            )
        self.assertIn("omit all four", str(partial.exception))

    def test_contract_changes_name_drop_and_relax(self):
        before = [_metric("residual_l2", "minimize", 1e-8, "objective", "residual")]
        self.assertIn("dropped residual_l2", contract_changes(before, []))
        flipped = [_metric("residual_l2", "maximize", 1e-8, "objective", "residual")]
        self.assertIn("direction residual_l2", contract_changes(before, flipped))
        loosened = [_metric("residual_l2", "minimize", 1e-2, "objective", "residual")]
        self.assertIn("target residual_l2", contract_changes(before, loosened))
        noisy = _metric("residual_l2", "minimize", 1e-8, "objective", "residual")
        noisy["noise"] = 1.0
        self.assertIn("noise residual_l2", contract_changes(before, [noisy]))

    def test_two_packages_discover_different_metrics(self):
        solver = _package(
            self.tmp,
            "solver_toy",
            "RESIDUAL = 1.0e-4\nLATENCY_MS = 2\n",
            'json.dump({"latency_ms": algo.LATENCY_MS, "residual_l2": algo.RESIDUAL}, sys.stdout)\n',
        )
        planner = _package(
            self.tmp,
            "planner_toy",
            "PATH = 14.0\nCOLLISIONS = 2\nLATENCY_MS = 3\n",
            'json.dump({"collision_count": algo.COLLISIONS, "latency_ms": algo.LATENCY_MS, "path_length": algo.PATH}, sys.stdout)\n',
        )
        solver_scenario = self.tmp / "solver.md"
        planner_scenario = self.tmp / "planner.md"
        solver_scenario.write_text(
            "A numerical solver must reduce residual_l2 on the frozen system.\n",
            encoding="utf-8",
        )
        planner_scenario.write_text(
            "A planner must shorten path_length.\nThe planner must keep collision_count at zero.\n",
            encoding="utf-8",
        )
        solver_launcher = Discover()
        planner_launcher = Discover()
        solver_run = self.evolve(solver, solver_scenario, solver_launcher)
        planner_run = self.evolve(planner, planner_scenario, planner_launcher)
        solver_contract = read_json(solver_run / "eval" / "contract.json")
        planner_contract = read_json(planner_run / "eval" / "contract.json")
        self.assertEqual(_ids(solver_contract, "objective"), ["residual_l2"])
        self.assertEqual(_ids(planner_contract, "objective"), ["path_length"])
        self.assertIn("collision_count", _ids(planner_contract, "protected"))
        self.assertNotIn("path_length", [item["id"] for item in solver_contract["metrics"]])
        self.assertNotIn("collision_count", [item["id"] for item in solver_contract["metrics"]])
        self.assertNotIn("residual_l2", [item["id"] for item in planner_contract["metrics"]])
        self.assertEqual(solver_contract["edits"], "reject")
        self.assertEqual(planner_contract["edits"], "reject")
        for launcher in (solver_launcher, planner_launcher):
            self.assertEqual({brief["role"] for brief in launcher.briefs}, {"metric_discover"})
            self.assertEqual(len(launcher.briefs), 3)
            for brief in launcher.briefs:
                self.assertNotIn("eval_command", brief)
                self.assertEqual(brief["model"], "grok-4.7-xhigh")
                self.assertIn("grok-4.7-xhigh", brief["prompt"])
                self.assertNotIn("eval_command", brief["prompt"])
                self.assertNotIn(sys.executable, brief["prompt"])
        self.assertEqual(load_run(solver_run)["status"], "running")
        self.assertFalse((Path(load_run(solver_run)["package_copy"]) / "eval" / "contract.json").exists())
        digest = hashlib.sha256((solver_run / "eval" / "contract.json").read_bytes()).hexdigest()
        self.assertEqual(digest, load_run(solver_run)["contract_sha256"])

    def test_saturated_metrics_do_not_hide_an_unmeasured_behavior(self):
        package = _package(
            self.tmp,
            "solver_toy",
            "RESIDUAL = 0\nLATENCY_MS = 1\n",
            'json.dump({"latency_ms": algo.LATENCY_MS, "residual_l2": algo.RESIDUAL}, sys.stdout)\n',
        )
        scenario = self.tmp / "scenario.md"
        scenario.write_text(
            "The solver must reduce residual_l2.\n"
            "The solver must also report how many iterations it used.\n",
            encoding="utf-8",
        )
        launcher = Discover()
        run = self.evolve(package, scenario, launcher)
        state = load_run(run)
        self.assertEqual(state["stop_reason"], "scenario_uncovered")
        self.assertFalse(state["success"])
        self.assertTrue(state["proxy_saturated"])
        self.assertTrue(any("iterations" in item for item in state["uncovered_behaviors"]))
        self.assertIn("not success", (run / "handoff.md").read_text(encoding="utf-8"))
        contract = read_json(run / "eval" / "contract.json")
        self.assertEqual(_ids(contract, "objective"), ["residual_l2"])
        self.assertEqual(len(launcher.briefs), 6)
        self.assertNotIn("edit", {brief["role"] for brief in launcher.briefs})
        sentences = obligation_sentences(scenario.read_text(encoding="utf-8"))
        self.assertEqual(len(sentences), 2)

    def test_a_second_discovery_round_can_add_but_not_replace(self):
        package = _package(
            self.tmp,
            "solver_toy",
            "RESIDUAL = 0\nITERATIONS = 4\nLATENCY_MS = 1\n",
            'json.dump({"iterations": algo.ITERATIONS, "latency_ms": algo.LATENCY_MS, "residual_l2": algo.RESIDUAL}, sys.stdout)\n',
        )
        scenario = self.tmp / "scenario.md"
        scenario.write_text(
            "The solver must reduce residual_l2.\n"
            "The solver must also report how many iterations it used.\n",
            encoding="utf-8",
        )
        run = self.evolve(package, scenario, Discover())
        self.assertEqual(load_run(run)["status"], "running")
        self.assertEqual(load_run(run)["discovery_round"], 2)
        contract = read_json(run / "eval" / "contract.json")
        self.assertEqual(_ids(contract, "objective"), ["iterations", "residual_l2"])
        residual = next(item for item in contract["metrics"] if item["id"] == "residual_l2")
        self.assertEqual(residual["direction"], "minimize")
        self.assertEqual(float(residual["target"]), 1e-8)

    def test_a_loosened_charter_cannot_keep_a_protected_regression(self):
        package = _package(
            self.tmp,
            "planner_toy",
            "PATH = 14.0\nCOLLISIONS = 0\nLATENCY_MS = 3\n",
            'json.dump({"collision_count": algo.COLLISIONS, "latency_ms": algo.LATENCY_MS, "path_length": algo.PATH}, sys.stdout)\n',
        )
        scenario = self.tmp / "planner.md"
        scenario.write_text(
            "A planner must shorten path_length.\nThe planner must keep collision_count at zero.\n",
            encoding="utf-8",
        )
        run = self.evolve(package, scenario, Discover())
        charter = read_json(run / "charter.json")
        for item in charter["metrics"]["protected"]:
            if item["name"] == "collision_count":
                item["max_regression"] = 100
                item.pop("target", None)
        copy = Path(load_run(run)["package_copy"])
        (copy / "algo.py").write_text("PATH = 10.0\nCOLLISIONS = 5\nLATENCY_MS = 3\n", encoding="utf-8")
        (copy / "test_behavior.py").write_text(
            "import unittest\nimport algo\n\n"
            "class Behavior(unittest.TestCase):\n"
            "    def test_holds(self):\n"
            "        self.assertEqual(algo.PATH, 10.0)\n"
            "        self.assertEqual(algo.COLLISIONS, 5)\n",
            encoding="utf-8",
        )
        with runner_authority():
            entry = score_stage(
                run,
                charter,
                stage="feature_edit",
                cycle_n=1,
                hypothesis="shorten the path",
                base_sha=load_run(run)["script_head"],
                behavior_test=[sys.executable, "-m", "unittest", "test_behavior"],
                pre_metrics=read_json(run / "scoreboard.json")["best"],
            )
        self.assertEqual(entry["outcome"], "revert")
        self.assertIn("collision_count", entry["error"])
        self.assertIn("PATH = 14.0", (copy / "algo.py").read_text(encoding="utf-8"))

    def test_a_rewritten_contract_file_is_not_scored(self):
        package = _package(
            self.tmp,
            "solver_toy",
            "RESIDUAL = 1.0e-4\nLATENCY_MS = 2\n",
            'json.dump({"latency_ms": algo.LATENCY_MS, "residual_l2": algo.RESIDUAL}, sys.stdout)\n',
        )
        scenario = self.tmp / "solver.md"
        scenario.write_text("A numerical solver must reduce residual_l2 on the frozen system.\n", encoding="utf-8")
        run = self.evolve(package, scenario, Discover())
        (run / "eval" / "contract.json").write_text('{"edits": "allow"}\n', encoding="utf-8")
        with runner_authority():
            entry = score_stage(
                run,
                read_json(run / "charter.json"),
                stage="feature_edit",
                cycle_n=1,
                hypothesis="rewrite the seal",
                base_sha=load_run(run)["script_head"],
                behavior_test=[sys.executable, "-m", "unittest", "test_behavior"],
                pre_metrics={"residual_l2": 1e-4},
            )
        self.assertEqual(entry["outcome"], "bad_edit")
        self.assertIn("metric contract", entry["error"])


if __name__ == "__main__":
    unittest.main()
