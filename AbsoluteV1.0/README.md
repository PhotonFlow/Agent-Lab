# Absolute v1.1 Pre-Development

Continuous, evaluator-guided optimization of a software stack. A Python coordinator owns the state, measurements, and keep/revert decisions. Fresh Cursor workers modify a private package copy; the original stack is not changed or deployed.

## Run

Requires Python 3.10+, Git, and an authenticated Cursor Agent CLI. No Python dependencies. From this directory:

```bash
python -m absolute evolve --package <path> --scenario <file> --model <available-model-id> --eval <command> <args>
python -m absolute evolve --run <run-folder>
python -m absolute status --run <run-folder> --dashboard
python -m unittest discover -s tests -v
```

Choose a model ID from `agent models`. Without `--model`, `ABSOLUTE_MODEL` or the previous `grok-4.7-xhigh` default is used; that default must be available to your account. `--eval` must be last, runs from the package copy, and must print one JSON object. Use an absolute interpreter path when `python` is not on PATH.

Metric discovery runs once before editing, with an optional follow-up to identify coverage gaps. Passing `--metric`, `--direction`, `--noise`, and `--target` together instead seals an explicit objective. Discovery can protect additional measured objectives and constraints. A declared target is a milestone, not a continuous-search stop. Unmeasured scenario behaviors remain visible as gaps.

## Search

Each experiment remeasures the incumbent, launches **one optimizer worker**, tests its change, and measures the candidate. The scheduler rotates across all sealed metrics and four search directions: local improvement, algorithm replacement, robustness, and simplification. Research and code inspection happen inside that worker when relevant, not in a mandatory committee.

A keep requires an improvement beyond the declared noise on at least one metric, no regression beyond any metric's budget, no loss of an achieved target, and no cumulative budget violation against the original baseline. Quality-preserving latency or memory improvements are eligible, including after a quality target is reached. Existing passing tests are allowed for behavior-preserving optimizations; behavior changes should add regression tests. Public message fields and immutable scorer files stay protected.

By default each measurement uses three evaluator samples and their per-metric median. `--eval-repeats N` selects 1-100 samples at run creation. Parent and candidate samples are saved separately. Repeats reduce sensitivity to outliers but are **not statistical significance tests**. Set noise tolerances from repeated runs on representative hardware and control seeds, workloads, warmup, and system load in the evaluator.

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

## Evaluation And Safety

The framework generalizes through the stack's evaluator and native build/test commands, not through robotics-specific algorithm code. Include task quality, failure rate, tail latency, peak memory, and applicable safety constraints in the sealed suite. Use varied environments, sensor conditions, perturbations, fixed development seeds, and independent held-out scenarios. A metric name or a quoted scenario sentence does not prove the evaluator actually measures that behavior.

**Measured improvements are not a SOTA certificate.** Establish domain SOTA separately using current baselines under identical hardware/data/budget conditions, confidence intervals, and a final independent test set not exposed to adaptive search. No search over arbitrary stacks can guarantee exhaustive coverage or eventual improvement. The runner never sets `sota_verified` true.

Workers and evaluator programs execute with your user permissions. Scorer hashes, snapshots, and prompts are accidental-tampering guards, **not a security sandbox**. Use an isolated container/VM with no robot actuation, production credentials, or sensitive mounts. External scorers should depend only on immutable code/data outside the editable package. A holdout accessible to the editing agent is not secret.

Promotion remains explicit and requires the existing validation procedure. `robot_validated` stays false until hardware validation is performed by a person. Do not deploy optimized robotics code directly from a search run.

## Compatibility

Existing v1.0 folders retain their original workflow and stop semantics. `--until-target` creates a run using that legacy feature-board workflow. The historical runs contain machine-specific absolute paths and are evidence, not portable executable fixtures. They are not rewritten or silently migrated.

See [the evidence and design notes](docs/plans/2026-09-29-001-continuous-search-v1.1.md) and [agent instructions](SKILL.md).
