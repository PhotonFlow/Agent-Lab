# Absolute v1.0

General optimization loop for a real-time robotics package. The package under test is copied into a run folder. The original is left alone until a sibling version is promoted.

```text
runs/Absolute_2026-09-24_01/
  run.json
  charter.json
  scoreboard.json
  journal.jsonl
  package/<original-name>/
```

A measured keep of `algo_v1.1` is promoted beside it as `algo_v1.2`. A package with no benchmark can install a scorer first. If no scorer runs, promotion requires three experts to vote `field-test` and `VALIDATION.md` to have a human procedure. `ABSOLUTE_STATUS.json` stays `robot_validated: false` until a person runs that procedure.

From this directory:

```bash
python -m absolute evolve --package <path> --scenario <file> --eval <command> <args>
python -m unittest discover -s tests
```

The process keeps starting the next feature-proposal group after each finished cycle. Before the first edit it discovers a metric contract from the package and the scenario, seals that contract, and keeps or reverts later edits only against the seal. It stops when every required output is at its target, when the baseline oracle is already saturated, when a sealed metric is at its target while the scenario still names an unmeasured behavior, or when an off-target output stays uncovered. Agent instructions are in `SKILL.md`.
