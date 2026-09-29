---
name: absolute
description: >-
  Run Absolute v1.0. One command, python -m absolute evolve, keeps evolving
  a package copy. Each finished cycle starts the next feature-proposal group.
  The run stops when every required output is at its target, when the
  baseline oracle is saturated, when a sealed metric is at its target
  while the scenario still names an unmeasured behavior, or when an
  output stays uncovered.
  Use when the user asks to
  start Absolute, evolve a stack, or optimize an algorithm until a goal.
---

# Absolute v1.0

The framework root is the directory that contains this file. Run every command from that directory.

One command starts the loop. The process keeps cycling. After a cycle finishes, the next feature-proposal group starts. The success stop is `outputs_covered`: every required output is at its target and that group admits nothing new, because every proposal is a feature already kept or a feature the panel already rejected. A baseline where every required accuracy metric is already at its target stops as `oracle_saturated`. That stop is not a state-of-the-art claim. If those metrics are already at their targets and the scenario still names a behavior the package does not measure, the run stops as `scenario_uncovered`. That stop is not success and not a state-of-the-art claim. A chair that accepts nothing while an output is still off target retries, then stops as `uncovered_outputs`. That stop is not a state-of-the-art claim either. Closing the chat does not stop it. Do not ask the person to approve a gate, a feature, or an edit.

```bash
python -m absolute evolve --package <path> --scenario <file> --eval <command> <args>
```

`--scenario` is a file that describes the application. Before the first edit, three agents read the package copy and that description and propose the metrics. The runner checks each proposed metric against the eval output, seals the set, and keeps or reverts later edits only against that seal. A human does not name the metrics. Passing `--metric`, `--direction`, `--noise`, and `--target` together seals that explicit metric instead. Omit all four to discover. `--eval` is last. Its working directory is the package copy. It prints one JSON object and nothing else. Workers do not receive the eval command. When the object contains `latency_ms`, latency is protected. When discovery does not set a tighter latency budget, that budget is 1 millisecond.

The runner copies the package into the run folder. `build`, `install`, and `log` are not copied. The original tree is not edited. The scorer is immutable. Agents that brainstorm, review, research, or edit do not read or write it, and they do not receive the eval path.

## What the process does

`evolve` owns the folder, the launches, and the score. A session that was asked to evolve a package runs that command and lets it run. It does not admit, edit, or score by hand, and it does not open a second run while this one is still short of the stop.

Each cycle, in order, each stage a fresh process:

1. Application, on the first cycle and again only when the scenario file content changes. The agent reads the package copy and the scenario text and writes what the software is for, who uses it, and which outputs matter.
2. Feature board. Several agents propose features from that application, including features the user did not name. They receive the features already kept, the features the panel already rejected, and any short note from the previous cycle. Three reviewers then judge the proposals independently. One lens is the scenario, including features the user did not name. One lens is feasibility in this package. One lens rejects a proposal that only restates a named metric penalty. One admission chair reads those reviews. When the chair accepts a feature, it accepts exactly one, and that feature is not already kept or rejected. A well-formed verdict that accepts none retries while a required output is off target, and it stops the run when every required output is already at its target. A review does not score, does not mark a keep, and does not stop the next cycle.
3. Literature research for that feature. Six to eight agents use disjoint queries covering candidate methods, evidence those methods are current, integration constraints, and measured cost. One chair merges them and drops duplicates. The verdict is adopt this method, the current method stands, or insufficient evidence. Adopt and stands are valid only when every justifying citation is an http or https URL outside the package and the runner can fetch it. A package path cannot justify the verdict. Another agent is launched only with a new disjoint query.
4. Code survey, every cycle, separate from literature. Several agents name hot paths, algorithmic complexity, extra copies, and dependencies that dominate inference. A short review keeps the points that affect the admitted feature or the measured latency.
5. One implementation edit, then one inference attempt. Each edit process follows test-driven development and verification-before-completion. Do not commit. Do not open a git worktree. Do not ask a person to sign the design. Do not run finishing-a-development-branch. Do not merge.
   - Implementation edit. When literature said adopt, this edit applies that method. Otherwise it implements the admitted feature. The behavior test must fail on the pre-edit tree and pass after. A required accuracy metric must improve by more than its own noise, and every protected budget must hold. A latency-only change is reverted. While every accuracy metric is already at its target, no implementation edit is kept.
   - Inference attempt. This runs once. It is kept only under the same accuracy rule. A failure to shave latency does not block the cycle.

The script runs the eval and keeps or reverts. Workers do not mark a keep. A failed eval, a bad edit, or a revert retries that stage until its attempt cap, then the cycle continues. The implementation edit and the inference attempt both finish before the cycle is done. Finishing that cycle starts the next feature-proposal group. A metric at its target, a verdict that the current method stands, or a kept feature does not cancel that group.

Stop when the required outputs are covered (`outputs_covered`), when the baseline oracle is saturated (`oracle_saturated`), when the sealed metrics are at their targets but a scenario behavior is still unmeasured (`scenario_uncovered`), or when an off-target output is still uncovered after the proposal cap (`uncovered_outputs`). Do not stop on `needs_human` for a revert. Plateau and `max_cycles` do not end the run. `robot_validated` stays false.

Workers are pinned to `grok-4.7-xhigh`. Each worker is a new process. Metric discovery, application, proposal, the three feature reviewers, the admission chair, literature, literature chair, survey, survey review, and edit are different processes. The edit worker does not score, and the scorer is not the editor. The feature reviewers, the admission chair, and the discovery workers do not score.

If the process exits before the stop, the run status stays `running`. Continue that same folder. Do not allocate a new `Absolute_YYYY-MM-DD_NN`.

```bash
python -m absolute evolve --run <run-folder>
```

## If you were launched with a worker brief

Do only the role in the brief. Write the output file the brief names, or make the one edit, then stop. Do not start `evolve`. Do not admit. Do not score. Do not mark a keep. Do not read or write the scorer or any immutable file.

## Promotion

`evolve` does not promote. After the stop, a measured sibling is still `promote --basis measured` once `VALIDATION.md` in the package copy has at least five numbered steps a person can run. `ABSOLUTE_STATUS.json` stays `robot_validated: false` until that person finishes the procedure. The original package stays in place.
