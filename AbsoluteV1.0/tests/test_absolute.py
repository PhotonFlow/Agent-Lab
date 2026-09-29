import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from absolute.cli import main
from absolute.engine import validate_charter
from absolute.naming import next_package_name
from absolute.store import load_run, read_journal, read_json

TOY = ROOT / "examples" / "toy_stack" / "algo_v1.1"


def validation_text() -> str:
    return "\n".join(f"{i}. Observe result {i} and record it." for i in range(1, 6)) + "\n"


def git_commit(copy: Path, message: str) -> None:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Absolute"
    env["GIT_AUTHOR_EMAIL"] = "absolute@local"
    env["GIT_COMMITTER_NAME"] = "Absolute"
    env["GIT_COMMITTER_EMAIL"] = "absolute@local"
    subprocess.run(["git", "add", "-A"], cwd=copy, check=True, env=env)
    subprocess.run(["git", "commit", "-m", message], cwd=copy, check=True, env=env)


def head_sha(copy: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=copy,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


class CharterTests(unittest.TestCase):
    def payload(self, **overrides):
        charter = {
            "eval_command": [sys.executable, "evaluate.py"],
            "feature_catalog": [],
            "immutable": ["evaluate.py"],
            "metrics": {
                "primary": {"direction": "maximize", "name": "score", "noise": 0.1},
                "protected": [
                    {"direction": "minimize", "max_regression": 2, "name": "latency_ms"}
                ],
            },
            "mutable": ["algo.py"],
        }
        charter.update(overrides)
        return charter

    def test_measured_charter_requires_mutable_and_immutable(self):
        with self.assertRaises(ValueError):
            validate_charter(self.payload(mutable=[]))
        with self.assertRaises(ValueError):
            validate_charter(self.payload(immutable=[]))

    def test_null_eval_allows_empty_immutable(self):
        validate_charter(self.payload(eval_command=None, immutable=[], feature_catalog=[]))

    def test_top_level_protected_is_rejected(self):
        charter = self.payload()
        charter["protected"] = charter["metrics"]["protected"]
        with self.assertRaises(ValueError):
            validate_charter(charter)

    def test_catalog_entry_needs_id_and_summary(self):
        with self.assertRaises(ValueError):
            validate_charter(self.payload(feature_catalog=[{"id": "dimension"}]))


class NamingTests(unittest.TestCase):
    def test_bumps_last_component(self):
        self.assertEqual(next_package_name("algo_v1.1"), "algo_v1.2")
        self.assertEqual(next_package_name("algo_v1.1.3"), "algo_v1.1.4")
        self.assertEqual(next_package_name("algo"), "algo_v1.1")


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.stack = self.tmp / "stack"
        self.stack.mkdir()
        shutil.copytree(TOY, self.stack / "algo_v1.1")
        self.runs = self.tmp / "runs"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, argv: list[str]) -> None:
        main(argv)

    def new_run(self) -> Path:
        from io import StringIO
        from contextlib import redirect_stdout

        buf = StringIO()
        with redirect_stdout(buf):
            self.run_cli(["new", "--task", "toy", "--runs-root", str(self.runs)])
        return Path(buf.getvalue().strip())

    def charter(self, run: Path, eval_command: list[str] | None, plateau: int = 5) -> None:
        payload = {
            "eval_command": eval_command,
            "eval_timeout_sec": 30,
            "feature_catalog": [{"id": "dimension", "summary": "estimate object size"}],
            "immutable": ["evaluate.py"] if eval_command else [],
            "metrics": {
                "primary": {"direction": "maximize", "name": "score", "noise": 0.1, "target": 10},
                "protected": [
                    {"direction": "minimize", "max_regression": 2, "name": "latency_ms"}
                ],
            },
            "mutable": ["algo.py"],
            "stops": {"max_cycles": 20, "plateau": plateau},
            "task": "toy",
        }
        path = self.tmp / "charter.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.run_cli(["set-charter", "--run", str(run), "--file", str(path)])

    def test_measured_keep_revert_and_promote(self):
        run = self.new_run()
        self.charter(run, [sys.executable, "evaluate.py"])
        self.run_cli(["accept", "--run", str(run), "--gate", "a"])
        self.run_cli(["capture", "--run", str(run), "--package", str(self.stack / "algo_v1.1")])
        self.run_cli(["baseline", "--run", str(run)])
        self.run_cli(["accept", "--run", str(run), "--gate", "b"])
        copy = Path(load_run(run)["package_copy"])
        self.run_cli(
            ["admit", "--run", str(run), "--tag", "implementation", "--hypothesis", "raise score"]
        )
        (copy / "algo.py").write_text("VALUE = 5\n", encoding="utf-8")
        self.run_cli(["cycle", "--run", str(run)])
        self.assertEqual((copy / "algo.py").read_text(encoding="utf-8"), "VALUE = 5\n")
        self.run_cli(
            ["admit", "--run", str(run), "--tag", "implementation", "--hypothesis", "worse score"]
        )
        (copy / "algo.py").write_text("VALUE = 0\n", encoding="utf-8")
        self.run_cli(["cycle", "--run", str(run)])
        self.assertEqual((copy / "algo.py").read_text(encoding="utf-8"), "VALUE = 5\n")
        self.assertIn("VALUE = 0", (run / "attempts" / "002.patch").read_text(encoding="utf-8"))
        reverted = [entry for entry in read_journal(run) if entry.get("cycle") == 2][0]
        self.assertEqual(reverted["metrics"]["score"], 0)
        self.assertIn("status:", (run / "handoff.md").read_text(encoding="utf-8"))
        (copy / "VALIDATION.md").write_text(validation_text(), encoding="utf-8")
        self.run_cli(["promote", "--run", str(run), "--basis", "measured"])
        promoted = self.stack / "algo_v1.2"
        self.assertTrue(promoted.is_dir())
        self.assertIn("VALUE = 5", (promoted / "algo.py").read_text(encoding="utf-8"))
        self.assertEqual((self.stack / "algo_v1.1" / "algo.py").read_text(encoding="utf-8"), "VALUE = 1\nLATENCY_MS = 10\n")
        status = read_json(promoted / "ABSOLUTE_STATUS.json")
        self.assertEqual(status["basis"], "measured")
        self.assertFalse(status["robot_validated"])
        self.assertEqual(load_run(run)["status"], "stopped")

    def test_field_test_requires_unanimous_ballots(self):
        run = self.new_run()
        self.charter(run, None)
        self.run_cli(["accept", "--run", str(run), "--gate", "a"])
        self.run_cli(["capture", "--run", str(run), "--package", str(self.stack / "algo_v1.1")])
        self.run_cli(["baseline", "--run", str(run)])
        self.run_cli(["accept", "--run", str(run), "--gate", "b"])
        copy = Path(load_run(run)["package_copy"])
        (copy / "algo.py").write_text("VALUE = 3\n", encoding="utf-8")
        (copy / "VALIDATION.md").write_text(validation_text(), encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_cli(["promote", "--run", str(run), "--basis", "field-test"])
        for index in range(2):
            self.run_cli(
                [
                    "ballot",
                    "--run",
                    str(run),
                    "--expert",
                    f"e{index}",
                    "--vote",
                    "field-test",
                    "--risk",
                    "latency could grow on the robot",
                ]
            )
        with self.assertRaises(SystemExit):
            self.run_cli(["promote", "--run", str(run), "--basis", "field-test"])
        self.run_cli(
            [
                "ballot",
                "--run",
                str(run),
                "--expert",
                "e2",
                "--vote",
                "reject",
                "--risk",
                "score may be a proxy",
            ]
        )
        with self.assertRaises(SystemExit):
            self.run_cli(["promote", "--run", str(run), "--basis", "field-test"])

    def test_field_test_promotes_when_unanimous(self):
        run = self.new_run()
        self.charter(run, None)
        self.run_cli(["accept", "--run", str(run), "--gate", "a"])
        self.run_cli(["capture", "--run", str(run), "--package", str(self.stack / "algo_v1.1")])
        self.run_cli(["baseline", "--run", str(run)])
        self.run_cli(["accept", "--run", str(run), "--gate", "b"])
        copy = Path(load_run(run)["package_copy"])
        (copy / "algo.py").write_text("VALUE = 3\n", encoding="utf-8")
        (copy / "VALIDATION.md").write_text(validation_text(), encoding="utf-8")
        for index in range(3):
            self.run_cli(
                [
                    "ballot",
                    "--run",
                    str(run),
                    "--expert",
                    f"e{index}",
                    "--vote",
                    "field-test",
                    "--risk",
                    "the robot may show a failure the desk run cannot see",
                ]
            )
        self.run_cli(["promote", "--run", str(run), "--basis", "field-test"])
        status = read_json(self.stack / "algo_v1.2" / "ABSOLUTE_STATUS.json")
        self.assertEqual(status["basis"], "field-test")
        self.assertFalse(status["robot_validated"])
        self.assertIn("VALUE = 1", (self.stack / "algo_v1.1" / "algo.py").read_text(encoding="utf-8"))

    def measured_ready(self) -> tuple[Path, Path]:
        run = self.new_run()
        self.charter(run, [sys.executable, "evaluate.py"])
        self.run_cli(["accept", "--run", str(run), "--gate", "a"])
        self.run_cli(["capture", "--run", str(run), "--package", str(self.stack / "algo_v1.1")])
        self.run_cli(["baseline", "--run", str(run)])
        self.run_cli(["accept", "--run", str(run), "--gate", "b"])
        return run, Path(load_run(run)["package_copy"])

    def admit(self, run: Path, tag: str, hypothesis: str, feature_id: str | None = None) -> None:
        argv = ["admit", "--run", str(run), "--tag", tag, "--hypothesis", hypothesis]
        if feature_id:
            argv.extend(["--feature-id", feature_id])
        self.run_cli(argv)

    def test_unknown_feature_stops_without_an_admit(self):
        run = self.new_run()
        self.charter(run, [sys.executable, "evaluate.py"])
        charter_path = self.tmp / "charter.json"
        payload = json.loads(charter_path.read_text(encoding="utf-8"))
        payload["feature_catalog"] = []
        charter_path.write_text(json.dumps(payload), encoding="utf-8")
        self.run_cli(["set-charter", "--run", str(run), "--file", str(charter_path)])
        self.run_cli(["accept", "--run", str(run), "--gate", "a"])
        self.run_cli(["capture", "--run", str(run), "--package", str(self.stack / "algo_v1.1")])
        self.run_cli(["baseline", "--run", str(run)])
        self.run_cli(["accept", "--run", str(run), "--gate", "b"])
        with self.assertRaises(SystemExit):
            self.admit(run, "feature", "add dimension", "dimension")
        state = load_run(run)
        self.assertEqual(state["status"], "needs_human")
        self.assertIsNone(state.get("open_admit"))

    def test_admit_refuses_a_commit_the_script_did_not_make(self):
        run, copy = self.measured_ready()
        (copy / "algo.py").write_text("VALUE = 4\n", encoding="utf-8")
        git_commit(copy, "worker")
        with self.assertRaises(SystemExit):
            self.admit(run, "implementation", "already committed")
        self.assertEqual(load_run(run)["status"], "running")
        self.assertIsNone(load_run(run).get("open_admit"))

    def test_worker_commit_revert_restores_admit_sha(self):
        run, copy = self.measured_ready()
        self.admit(run, "implementation", "commit then revert")
        base = load_run(run)["open_admit"]["sha"]
        (copy / "algo.py").write_text("VALUE = 0\n", encoding="utf-8")
        git_commit(copy, "worker")
        self.run_cli(["cycle", "--run", str(run)])
        self.assertEqual((copy / "algo.py").read_text(encoding="utf-8"), "VALUE = 1\nLATENCY_MS = 10\n")
        self.assertEqual(head_sha(copy), base)
        self.assertEqual(load_run(run)["status"], "running")

    def test_committed_extra_file_does_not_keep(self):
        run, copy = self.measured_ready()
        self.admit(run, "implementation", "extra file")
        base = load_run(run)["open_admit"]["sha"]
        (copy / "algo.py").write_text("VALUE = 9\n", encoding="utf-8")
        (copy / "extra.txt").write_text("nope\n", encoding="utf-8")
        git_commit(copy, "worker")
        with self.assertRaises(SystemExit):
            self.run_cli(["cycle", "--run", str(run)])
        self.assertEqual(load_run(run)["status"], "needs_human")
        self.assertEqual((copy / "algo.py").read_text(encoding="utf-8"), "VALUE = 1\nLATENCY_MS = 10\n")
        self.assertFalse((copy / "extra.txt").exists())
        self.assertEqual(head_sha(copy), base)

    def test_legal_worker_commit_keep_parents_the_admit_sha(self):
        run, copy = self.measured_ready()
        self.admit(run, "implementation", "commit then keep")
        base = load_run(run)["open_admit"]["sha"]
        (copy / "algo.py").write_text("VALUE = 6\n", encoding="utf-8")
        git_commit(copy, "worker")
        self.run_cli(["cycle", "--run", str(run)])
        self.assertEqual((copy / "algo.py").read_text(encoding="utf-8"), "VALUE = 6\n")
        parent = subprocess.run(
            ["git", "rev-parse", "HEAD^"],
            cwd=copy,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(parent, base)

    def test_null_eval_cycle_does_not_stop_the_run(self):
        run = self.new_run()
        self.charter(run, None)
        self.run_cli(["accept", "--run", str(run), "--gate", "a"])
        self.run_cli(["capture", "--run", str(run), "--package", str(self.stack / "algo_v1.1")])
        self.run_cli(["baseline", "--run", str(run)])
        self.run_cli(["accept", "--run", str(run), "--gate", "b"])
        copy = Path(load_run(run)["package_copy"])
        (copy / "algo.py").write_text("VALUE = 3\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_cli(["cycle", "--run", str(run)])
        self.assertEqual(load_run(run)["status"], "running")
        self.assertEqual((copy / "algo.py").read_text(encoding="utf-8"), "VALUE = 3\n")

    def test_three_implementation_keeps_block_a_fourth(self):
        run, copy = self.measured_ready()
        for value in (2, 3, 4):
            self.admit(run, "implementation", f"to {value}")
            (copy / "algo.py").write_text(f"VALUE = {value}\n", encoding="utf-8")
            self.run_cli(["cycle", "--run", str(run)])
        with self.assertRaises(SystemExit):
            self.admit(run, "implementation", "fourth")
        self.assertEqual(load_run(run)["status"], "running")
        self.admit(run, "tech-stack", "reset streak")
        (copy / "algo.py").write_text("VALUE = 5\n", encoding="utf-8")
        self.run_cli(["cycle", "--run", str(run)])
        self.admit(run, "implementation", "allowed again")

    def test_install_eval_freezes_a_running_scorer(self):
        run = self.new_run()
        self.charter(run, None)
        self.run_cli(["accept", "--run", str(run), "--gate", "a"])
        self.run_cli(["capture", "--run", str(run), "--package", str(self.stack / "algo_v1.1")])
        candidate = run / "candidates" / "scorer.py"
        candidate.parent.mkdir()
        candidate.write_text(
            'import json\njson.dump({"score": 1, "latency_ms": 10}, __import__("sys").stdout)\n',
            encoding="utf-8",
        )
        bad = run / "candidates" / "bad.py"
        bad.write_text("print('nope')\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_cli(
                ["install-eval", "--run", str(run), "--candidate", str(bad), "--dest", "evaluate.py"]
            )
        self.assertIsNone(read_json(run / "charter.json")["eval_command"])
        self.run_cli(
            ["install-eval", "--run", str(run), "--candidate", str(candidate), "--dest", "evaluate.py"]
        )
        charter = read_json(run / "charter.json")
        self.assertEqual(charter["eval_command"][1], "evaluate.py")
        self.assertIn("evaluate.py", charter["immutable"])
        self.run_cli(["baseline", "--run", str(run)])
        with self.assertRaises(SystemExit):
            self.run_cli(
                [
                    "install-eval",
                    "--run",
                    str(run),
                    "--candidate",
                    str(candidate),
                    "--dest",
                    "evaluate.py",
                ]
            )
        self.run_cli(["accept", "--run", str(run), "--gate", "b"])
        copy = Path(load_run(run)["package_copy"])
        self.admit(run, "implementation", "touch scorer")
        base = load_run(run)["open_admit"]["sha"]
        (copy / "evaluate.py").write_text("print('broken')\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_cli(["cycle", "--run", str(run)])
        self.assertEqual(load_run(run)["status"], "needs_human")
        self.assertEqual(head_sha(copy), base)

    def test_resume_refuses_a_changed_scorer_hash(self):
        run, copy = self.measured_ready()
        self.admit(run, "implementation", "break eval")
        (copy / "evaluate.py").write_text("print('broken')\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_cli(["cycle", "--run", str(run)])
        self.assertEqual(load_run(run)["status"], "needs_human")
        (copy / "evaluate.py").write_text("print('still broken')\n", encoding="utf-8")
        git_commit(copy, "rewrite scorer")
        with self.assertRaises(SystemExit):
            self.run_cli(["resume", "--run", str(run)])
        self.assertEqual(load_run(run)["status"], "needs_human")

    def test_resume_continues_the_same_run(self):
        run, copy = self.measured_ready()
        self.admit(run, "implementation", "extra file")
        (copy / "extra.txt").write_text("nope\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_cli(["cycle", "--run", str(run)])
        self.run_cli(["resume", "--run", str(run)])
        self.assertEqual(load_run(run)["status"], "running")
        self.assertIsNone(load_run(run).get("open_admit"))
        self.admit(run, "implementation", "after resume")
