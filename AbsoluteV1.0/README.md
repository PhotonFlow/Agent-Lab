# Absolute v1.1 Pre-Development

Continuous, evaluator-guided optimization of a software stack. A Python coordinator owns the state, measurements, and keep/revert decisions. Fresh Cursor workers modify a private package copy; the original stack is not changed or deployed.

## Run

Requires Python 3.10+, Git, and an authenticated Cursor Agent CLI. No Python dependencies. From this directory:

```bash
python -m absolute evolve --package <path> --scenario <file> --model <available-model-id>
python -m absolute evolve --package <path> --scenario <file> --model <available-model-id> --eval <command> <args>
python -m absolute evolve --run <run-folder>
python -m absolute status --run <run-folder> --dashboard
python -m unittest discover -s tests -v
```

Choose a model ID from `agent models`. Without `--model`, `ABSOLUTE_MODEL` or the previous `grok-4.7-xhigh` default is used; that default must be available to your account. `--eval` must be last, runs from the package copy, and must print one JSON object. Use an absolute interpreter path when `python` is not on PATH.

The evaluator is optional for new continuous runs. Requirements and intended metrics are planned before running a benchmark. Passing `--metric`, `--direction`, and `--noise` supplies an explicit objective; `--target` is optional. Targets are milestones, not continuous-search stops. Legacy `--until-target` still requires an evaluator and all four goal flags when specifying a goal.

## Evaluation Setup

1. Inspect the scenario and candidate interfaces, and inventory available evaluators, tests, data, and build files. One planning worker defines intended metrics and missing validation, without seeing benchmark results.
2. Reuse a supplied evaluator or a single discovered Python evaluator when compatible unittest tests are present. A package-local `absolute-evaluation.json` can explicitly declare native commands, dependencies, and an oracle. Otherwise one benchmark-building worker adapts or constructs evaluation outside the editable package.
3. Run the independent regression gate and evaluator. A generated benchmark also needs a runnable negative control for every measurable objective: changing candidate code in a disposable copy must worsen the score. Crashes and constant scores do not qualify.
4. Freeze the manifest, declared evaluator/test/data files, scenario, and plan. Then seal measurable metric policies and record the baseline. Missing protected measurements block setup; missing optional objectives remain explicit gaps.

Setup is bounded to one planning/building attempt per invocation, with the worker deadline. Missing assets or failed qualification pause the same run with an actionable reason. Resume with `evolve --run`; a rejected generated proposal is retained and the builder can retry. The framework does not automatically download data, install dependencies, operate hardware, or invent labels.

For native projects, a descriptor can contain:

```json
{
	"eval_command": ["./benchmark", "cases.csv"],
	"validation_commands": [["ctest", "--test-dir", "test-build", "--output-on-failure"]],
	"files": ["benchmark", "cases.csv", "test-build/CTestTestfile.cmake"],
	"oracle": "Describe the trusted reference or labels and the conditions they cover.",
	"limitations": ["Independent held-out and hardware validation still required."]
}
```

Commands run from the candidate directory; generated scripts also receive `ABSOLUTE_PACKAGE`. Explicit `files` may include directories. Declare **all** scorer, test, configuration, and dataset dependencies, including imported helpers and native test binaries. Automatic discovery only identifies direct entry points and visible assets; it cannot prove an arbitrary program's dependency closure. Test build artifacts must exist or be produced by a declared build command. Do not list editable candidate implementations as frozen scorer dependencies.

Coverage reports distinguish `measured_proxy` from `unmeasured`, and state what additional evidence is needed. Neither an agent's scenario quote nor a negative-control pass proves domain coverage. Supplied/discovered benchmarks are executable-checked, not independently certified; generated benchmarks are sensitivity-checked, not oracle-certified.

## Search

Each experiment remeasures the incumbent, launches **one optimizer worker**, tests its change, and measures the candidate. The scheduler rotates across all sealed metrics and four search directions: local improvement, algorithm replacement, robustness, and simplification. Research and code inspection happen inside that worker when relevant, not in a mandatory committee.

A keep requires an improvement beyond the declared noise on at least one metric, no regression beyond any metric's budget, no loss of an achieved target, and no cumulative budget violation against the original baseline. Quality-preserving latency or memory improvements are eligible, including after a quality target is reached. Existing passing tests are allowed for behavior-preserving optimizations; behavior changes should add regression tests. Public message fields and immutable scorer files stay protected.

By default each measurement uses three evaluator samples. Objectives use their declared aggregation (`median`, `mean`, or `worst`); protected metrics default to worst-case, and hard bounds always use worst-case so an intermittent violation cannot disappear in a median. `noise`, `min_effect`, `max_regression`, and `hard_limit` are separate finite policy values. `--eval-repeats N` selects 1-100 samples. Repeats are **not statistical significance tests**. Calibrate noise on representative hardware and control seeds, workloads, warmup, and system load in the evaluator.

Every candidate must pass the frozen regression commands before measurement. Worker-suggested tests are additional checks, not replacements. Existing regression files and ROS message/service/action schemas are protected. A kept score is recorded against the actual Git tree, including when a worker unexpectedly committed its edits.

Every attempt retains its patch, hypothesis, measurements, and outcome; kept implementations are Git checkpoints. Workers receive recent measured successes and failures instead of unbounded transcripts. This is conservative incumbent-based search, not a full population or Pareto-front algorithm. Improvements that require temporary measured regressions are not automatically accepted.

## Continuous Operation

- No default cycle limit. Targets, rejected experiments, and plateaus do not stop new runs.
- `--max-cycles N` pauses at a total lifetime cycle count, including on resume. Increase it or omit it to continue.
- Ctrl+C cancels the active worker and restores the incumbent. Creating a file named `STOP` in the run folder pauses at an experiment boundary; remove it before resuming.
- Failed workers are rolled back and retried with bounded backoff. Five consecutive worker-process failures pause for inspection. Broken baseline evaluation or corrupted state also pauses with an error.
- Workers have a 30-minute default deadline and 30-second heartbeat. Configure positive seconds with `ABSOLUTE_WORKER_TIMEOUT_SEC` and `ABSOLUTE_HEARTBEAT_SEC`.
- An OS-released per-run lock prevents concurrent coordinators. Resume the same folder after a crash. Do not manually edit its package copy between experiments; resume restores the last script-owned checkpoint.
- Keep the coordinator terminal/process alive. Closing a parent terminal may terminate it; this is not an installed OS service. Use your platform's process supervisor for unattended restarts.

## Context And Visibility

The coordinator is ordinary Python and does not consume an accumulating LLM conversation. Each experiment uses a fresh worker, a bounded recent-history reader, and a **64KB maximum serialized brief**. Full logs, samples, and patches remain on disk. Oversized briefs are rejected visibly rather than silently truncating requirements.

The worker brief declares a **500,000-token planning ceiling**, leaving room for code inspection and tool output. This does not provision a model context window or measure the tokens used by Cursor tools. Cursor's documented CLI has no context-size flag; select a model/account that actually supports your desired capacity. The framework cannot enlarge the context of the agent that launches it.

The terminal shows worker PIDs, phase, objective, strategy, heartbeats, elapsed time, log size, evaluation samples, rejection reasons, and a baseline/best/target table. Durable artifacts:

| Artifact | Contents |
| --- | --- |
| `events.jsonl` | Timestamped live coordinator and worker lifecycle events |
| `workers/cycle-*/optimize.log` | Cursor stream-JSON output, including partial output |
| `journal.jsonl`, `attempts/` | Full measured experiment history and patches |
| `eval/*-parent.json`, `eval/*-candidate.json` | Individual samples and aggregate measurements |
| `scoreboard.json`, `handoff.md` | Incumbent metrics and bounded restart summary |
| `eval/plan.json`, `eval/assets.json` | Intended outcomes and discovered local assets |
| `eval/benchmark.json` | Frozen benchmark version, commands, oracle, asset hashes and limitations |
| `eval/coverage.json`, `eval/coverage.md` | Measured proxies, gaps, and required additional validation |
| `eval/negative-control-*.json` | Recorded generated-benchmark sensitivity checks |
| `recovery.sqlite3` | Transactional decision record used to recover interrupted JSON/journal publication |

## Evaluation And Safety

The framework generalizes through the stack's evaluator and native build/test commands, not through robotics-specific algorithm code. Include task quality, failure rate, tail latency, peak memory, and applicable safety constraints in the sealed suite. Use varied environments, sensor conditions, perturbations, fixed development seeds, and independent held-out scenarios. A metric name or a quoted scenario sentence does not prove the evaluator actually measures that behavior.

**Measured improvements are not a SOTA certificate.** Establish domain SOTA separately using current baselines under identical hardware/data/budget conditions, confidence intervals, and a final independent test set not exposed to adaptive search. No search over arbitrary stacks can guarantee exhaustive coverage or eventual improvement. The runner never sets `sota_verified` true.

Workers and evaluator programs execute with your user permissions. Scorer hashes, snapshots, and prompts are accidental-tampering guards, **not a security sandbox**. Use an isolated container/VM with no robot actuation, production credentials, or sensitive mounts. External scorers should depend only on immutable code/data outside the editable package. A holdout accessible to the editing agent is not secret.

Promotion remains explicit and requires the existing validation procedure. `robot_validated` stays false until hardware validation is performed by a person. Do not deploy optimized robotics code directly from a search run.

## Compatibility

Existing folders retain their workflow and are not silently migrated to the new setup. Start a new run to obtain the requirements-first plan and frozen regression manifest. `--until-target` creates the legacy feature-board workflow. Historical runs contain machine-specific absolute paths and are evidence, not portable executable fixtures.

Automatic mid-run benchmark expansion is deliberately deferred. A frozen benchmark cannot be rewritten to justify a candidate. Changing its data, scenario or measurement semantics requires a new run, with requalification and baseline measurement; compare original and incumbent implementations under the same new benchmark before making cross-version claims. No in-place upgrade or automatic cross-version SOTA comparison is implemented.

See [the evidence and design notes](docs/plans/2026-09-29-001-continuous-search-v1.1.md) and [agent instructions](SKILL.md).
The [requirements-driven evaluation research](docs/plans/2026-09-29-002-requirements-driven-evaluation.md) records the primary sources, design decisions, and remaining limits.
