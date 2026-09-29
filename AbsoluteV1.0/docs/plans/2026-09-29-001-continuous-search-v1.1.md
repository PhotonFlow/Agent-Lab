# Continuous Search v1.1: Evidence And Scope

## Local Evidence

The archived `runs/Absolute_2026-09-28_02/run.json` reports `uncovered_outputs`, not successful domain optimization. Its launch log records 129 completed worker launches: 110 non-edit workers and 19 editors. This does not measure token cost or prove those roles never help, but it establishes substantial orchestration overhead for that run.

The v1.0 acceptance gate rejects latency-only changes and changes after the measured target is reached. The feature board excludes previously proposed feature IDs, even though a different implementation of the same feature could be useful. All prior patches are supplied without measurements, and the handoff expands with the entire attempt history. Workers have no deadline and redirect output without live progress.

## Research Basis

Sources inspected on 2026-09-29:

- [AlphaEvolve, 2025](https://arxiv.org/abs/2506.13131): code evolution driven by one or more evaluators. Supports direct measured search and evaluator feedback, not a guarantee on tasks with incomplete evaluators.
- [Darwin Godel Machine, revised March 2026](https://arxiv.org/abs/2505.22954): empirical self-improvement with a diverse archive and open-ended exploration. Supports learning from retained experiments. Its reported coding-benchmark gains do not establish robotics safety or universal generalization.
- [Multi-Agent System Search, ICLR 2026](https://arxiv.org/abs/2502.02533): prompts and collaboration topology materially affect outcomes. Supports treating topology as a design decision, not assuming more workers are always better. It does not establish that one worker is universally optimal.
- [Cursor CLI parameters](https://cursor.com/docs/cli/reference/parameters): documents model selection and streaming output, but no context-window allocation flag.

This is a targeted primary-source review, not an exhaustive survey of every 2026 framework. AlphaEvolve/DGM results are not reproduced here.

## Implemented Decisions

1. Default to one-worker experiments, reusing the existing sealed contract and Git-backed score/rollback engine. Retain old runs and the legacy mode rather than silently changing their semantics.
2. Rotate across sealed metrics and local, algorithmic, robustness, and simplification strategies. Accept improvements on any metric under conservative regression constraints. Allow passing native regression suites for behavior-preserving optimization.
3. Remeasure incumbent and candidate with repeated samples, retain raw samples, and compare their medians. Also compare candidates to the recorded best and the original baseline to reduce acceptance of measurement drift and cumulative budget erosion.
4. Persist measured outcomes and patches, feed bounded recent feedback into fresh workers, and cap serialized optimization briefs at 64KB. A 500K planning ceiling is metadata, not a provider context entitlement or runtime token meter.
5. Continue past targets and plateaus. Add backoff, worker deadlines, graceful pause/resume, and an OS-held runner lock. Broken infrastructure pauses instead of spending indefinitely on a failing launcher.
6. Emit timestamped events, worker heartbeat/log locations, evaluation phases, rejection reasons, and an ASCII metric dashboard. Keep full history on disk without growing every worker prompt.

## Limits And Required Evidence

The reduced default topology is supported by local overhead and tested control flow, not by a controlled LLM-quality comparison. Run equal-budget ablations on representative perception, planning, control, and estimation tasks before claiming better optimization efficiency. Record wall time, model tokens/cost, valid experiments, held-out improvement, and regression rate over multiple seeds.

This is incumbent-based multi-metric search, not population-based evolution, a Pareto archive, an exhaustive enumerator, or framework self-modification. A Git/patch history retains evidence but does not automatically explore every historical parent. Non-improving intermediate candidates are retained as patches but not promoted. These deliberate limits keep the first upgrade understandable and testable.

Development evaluators must measure actual output behavior on representative inputs, with isolated immutable dependencies. Repeated adaptive search can overfit any visible suite. Establish claims on a final independently held-out test set with current domain baselines, comparable compute budgets, statistical uncertainty, and hardware/software versions. Unit tests of the coordinator do not substitute for that experiment.

Scenario-witness matching is a coverage aid, not semantic proof. A metric may have the right name and still be a poor proxy. Missing measurements remain visible; the optimizer cannot independently certify all-round domain coverage. Robot validation and deployment stay outside autonomous search. Same-user processes and file snapshots are not a sandbox.