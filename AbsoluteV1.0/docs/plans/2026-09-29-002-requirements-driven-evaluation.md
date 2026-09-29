# Requirements-Driven Evaluation: Research And Implementation

Research reviewed on 2026-09-29, before implementation. This is a targeted primary-source investigation, not a claim to have surveyed every current framework.

## Findings From Sources

| Source | Evidence | Design consequence |
| --- | --- | --- |
| [AlphaEvolve, sections 2.1, 2.4 and 3.3](https://arxiv.org/html/2506.13131v1) | User-specified executable evaluators, staged evaluation, multiple metrics, unseen workloads, and reference-based correctness checks underpin the reported improvements. | Separate desired outcomes from evaluator construction. Preserve independent regression gates and use benchmark-specific aggregation. The paper does not establish autonomous oracle construction for arbitrary robotics tasks. |
| [Darwin Godel Machine, March 2026 revision](https://arxiv.org/abs/2505.22954) | Empirical benchmark validation and a diverse archive support open-ended improvement; experiments use isolation and oversight. | Retain evidence and checkpoints. Do not confuse role prompts or benchmark gains with isolation or robot safety. Population search is a later optimization, not a substitute for valid measurements. |
| [Generalization in Adaptive Data Analysis and Holdout Reuse](https://arxiv.org/abs/1506.02629) | Repeated adaptive reuse can overfit a holdout. Its reusable-holdout guarantees require a specific algorithm, not merely a file named test. | Search data is development data. Independent final validation remains outside adaptive feedback. We do not claim to implement the paper's statistical guarantees. |
| [The Ladder](https://arxiv.org/abs/1502.04585) | Sequential feedback can compromise leaderboard accuracy. | Repeated medians are not significance tests; disclose adaptive overfitting and retain raw measurements. |
| [Concrete Problems in AI Safety](https://arxiv.org/abs/1606.06565) | Wrong objectives, reward hacking, side effects, and distribution shift are distinct failure modes. | Freeze the judge, test trivial/broken implementations, and fail closed where required evidence is absent. |
| [NIST response-robot test methods](https://www.nist.gov/el/intelligent-systems-division-73500/standard-test-methods-response-robots) | Requirements drive capability metrics, controlled test apparatuses, and deployment-relevant comparisons. | Record tested conditions and unmeasured capabilities. Synthetic inputs cannot establish deployment performance. |
| [Hypothesis documentation](https://hypothesis.readthedocs.io/en/latest/tutorial/introduction.html) | Property testing supplements unit tests using specified invariants, round trips, or trusted references. | Builders may use an existing property-testing library when appropriate; generated inputs do not supply an oracle. Do not invent a bespoke fuzzing engine. |
| [SQLite atomic commit](https://www.sqlite.org/atomiccommit.html) and [Python sqlite3](https://docs.python.org/3/library/sqlite3.html) | Transactions provide recoverable multi-record updates, subject to storage/OS guarantees. | Use standard-library transactional storage for experiment recovery rather than claiming independent JSON replacements are a transaction. |

Some publisher and corporate pages were unavailable through the network proxy. Only retrieved sources above are used as evidence; inaccessible or unrelated results were excluded.

## Chosen Scope

First repair metric semantics, checkpoint identity, mandatory validation, scorer manifests, and recovery. Then introduce one evaluation-planning role and, only when needed, one benchmark-building role. No mandatory committee, generic simulator, downloaded dataset, or installed service.

The planned order is requirements and desired metrics, asset inventory, reuse/adaptation/construction, executable qualification, immutable benchmark version, baseline, and continuous optimization. Unknown requirements remain explicit gaps. Objectives need not have fabricated targets. Measurement noise, useful effect size, allowed regression, aggregation, and hard bounds are separate fields.

Generated evaluation must remain outside the editable candidate. It needs a runnable regression gate, declared evaluator/data files, a documented oracle, and negative-control evidence. Qualification checks execution and sensitivity; it does not prove semantic correctness or certify domain SOTA. Missing assets produce an actionable blocked report, not invented labels or a successful optimization claim.

Versioned benchmarks cannot be silently rewritten during candidate search. Changes require requalification and remeasurement; original-run artifacts remain immutable evidence. Independent held-out validation and physical robot validation remain external responsibilities.

## Verification Criteria

- Reproduce and prevent discarded latency policy, invalid tolerances, hidden intermittent failures, and targetless-objective rejection.
- Tie kept measurements to the correct Git tree; verify recovery after interrupted state publication.
- Require frozen regression commands and files; reject evaluator mutation and no-op replacement gates.
- Exercise supplied evaluator, discovered assets, generated benchmark, missing evidence, failed qualification, and setup resume with offline fixtures.
- Keep legacy bounded runs readable and run the full existing test suite alongside the new regressions.

## Implemented Boundary

Requirements-first setup, optional evaluator input, local asset routing, one builder, frozen manifests, negative-control qualification, partial coverage reports, independent regression gates, metric-specific aggregation, and resumable setup are implemented. Existing workflows are not silently migrated. Generated sensitivity controls have their own recorded measurements. SQLite supports replay of interrupted decision publication; legacy JSON artifacts remain readable exports.

Automatic benchmark expansion, population search, formal oracle validation, container provisioning, adaptive-statistics guarantees, and independent held-out/hardware validation are not implemented. Benchmark changes require a new run; cross-version claims require original/incumbent remeasurement by the operator. This bounded scope avoids letting code and its judge change together without comparable evidence.