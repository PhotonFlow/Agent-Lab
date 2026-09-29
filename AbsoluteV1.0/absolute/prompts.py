"""Worker prompts. One role per fresh process. The runner scores; workers do not."""

from __future__ import annotations


def research_prompt(brief: dict) -> str:
    return "\n".join(
        [
            "ROLE: research",
            "You are one fresh research agent for this Absolute cycle. You are not the runner.",
            f"Model: {brief.get('model', 'grok-4.7-xhigh')}",
            f"Your query, and no other query: {brief['query']}",
            "The other research agents have disjoint queries. Do not answer a different query.",
            f"Write only this JSON file: {brief['output']}",
            'Schema: {"query": "<the query above, unchanged>", "findings": ["short finding"]}',
            "Read the handoff field in this brief and the package copy. Keep findings short.",
            "Do not edit the package. Do not edit the scorer. Do not admit. Do not score. Do not mark a keep.",
            "Do not start python -m absolute evolve.",
        ]
    )


def proposal_prompt(brief: dict) -> str:
    blocked = ", ".join(brief.get("blocked_levels") or []) or "none"
    return "\n".join(
        [
            "ROLE: propose",
            "You are one fresh member of the decision cluster. You are not the runner and not the editor.",
            f"Read the research matrix at {brief['matrix']} and the handoff field in this brief.",
            f"Write one proposal JSON object to {brief['output']}.",
            "Levels are implementation, tech-stack, or feature. Propose exactly one change, not a list.",
            "A feature the user did not name is allowed. Give it a feature_id and a summary.",
            f"Blocked levels: {blocked}",
            "Do not edit the package. Do not edit the scorer. Do not admit. Do not score. Do not mark a keep.",
        ]
    )


def chair_prompt(brief: dict) -> str:
    blocked = ", ".join(brief.get("blocked_levels") or []) or "none"
    proposals = "\n".join(f"- {path}" for path in brief.get("proposals") or [])
    return "\n".join(
        [
            "ROLE: chair",
            "You are the chair of the decision cluster. You choose exactly one next change.",
            f"Read the research matrix at {brief['matrix']} and these proposals:",
            proposals,
            f"Write one JSON object to {brief['output']}. Not a list. Not three changes.",
            "Keys: level (implementation, tech-stack, or feature), hypothesis (one sentence).",
            "A feature level also needs feature_id and summary. You may name a feature the user did not.",
            "implementation and tech-stack must not include a feature_id.",
            f"Blocked levels: {blocked}",
            "Do not edit the package. Do not edit the scorer. Do not admit. Do not score. Do not mark a keep.",
        ]
    )


def _forbid_scorer() -> list[str]:
    return [
        "Do not read or write the scorer.",
        "Do not open an immutable file.",
        "Do not admit. Do not score. Do not mark a keep.",
        "Do not start python -m absolute evolve.",
    ]


def application_prompt(brief: dict) -> str:
    return "\n".join(
        [
            "ROLE: application",
            "You are one fresh process. Read the package copy and the scenario text in this brief.",
            "Write what the software is for, who uses it, and which outputs matter.",
            f"Write only this JSON file: {brief['output']}",
            'Schema: {"purpose": "...", "users": "...", "outputs": "..."}',
            *_forbid_scorer(),
        ]
    )


def feature_propose_prompt(brief: dict) -> str:
    return "\n".join(
        [
            "ROLE: feature_propose",
            "Propose one feature from the application, including a feature the user did not name.",
            f"Application: {brief['application']}",
            f"Kept features: {brief.get('kept_features') or []}",
            f"Rejected features: {brief.get('rejected_features') or []}",
            f"Note from the previous cycle: {brief.get('prior_note') or ''}",
            "Do not propose a feature id that is already kept or already rejected.",
            f"Write only this JSON file: {brief['output']}",
            'Schema: {"feature_id": "...", "summary": "...", "hypothesis": "..."}',
            "Do not restate a named metric penalty as the whole proposal.",
            f"Named penalties: {', '.join(brief.get('named_penalties') or [])}",
            *_forbid_scorer(),
        ]
    )


def _review_prompt(brief: dict, role: str, lens: str) -> str:
    proposals = "\n".join(f"- {path}" for path in brief.get("proposals") or [])
    return "\n".join(
        [
            f"ROLE: {role}",
            lens,
            "Judge each proposal. Do not admit a feature. Do not mark a keep. Do not stop the run.",
            f"Kept features: {brief.get('kept_features') or []}",
            f"Rejected features: {brief.get('rejected_features') or []}",
            f"Named penalties: {', '.join(brief.get('named_penalties') or [])}",
            proposals,
            f"Write only this JSON file: {brief['output']}",
            'Schema: {"judgments": [{"feature_id": "...", "concern": "..."}]}',
            *_forbid_scorer(),
        ]
    )


def feature_review_scenario_prompt(brief: dict) -> str:
    return _review_prompt(
        brief,
        "feature_review_scenario",
        "Lens: the scenario, including features the user did not name.",
    )


def feature_review_feasibility_prompt(brief: dict) -> str:
    return _review_prompt(
        brief,
        "feature_review_feasibility",
        "Lens: feasibility in this package.",
    )


def feature_review_restatement_prompt(brief: dict) -> str:
    return _review_prompt(
        brief,
        "feature_review_restatement",
        "Lens: reject a proposal that only restates a named metric penalty.",
    )


def feature_admit_prompt(brief: dict) -> str:
    proposals = "\n".join(f"- {path}" for path in brief.get("proposals") or [])
    reviews = "\n".join(f"- {path}" for path in brief.get("reviews") or [])
    return "\n".join(
        [
            "ROLE: feature_admit",
            "Read the three reviews. Accept or reject each proposal in writing.",
            "When you accept a feature, accept exactly one, and do not accept a feature that is already kept or rejected.",
            "Reject a proposal that only restates a named penalty.",
            "If none of the new proposals should be admitted, reject each one and accept none.",
            "Do not mark a keep. Do not score. Do not stop the run.",
            f"Kept features: {brief.get('kept_features') or []}",
            f"Rejected features: {brief.get('rejected_features') or []}",
            f"Named penalties: {', '.join(brief.get('named_penalties') or [])}",
            reviews,
            proposals,
            f"Write only this JSON file: {brief['output']}",
            'Schema: {"decisions": [{"feature_id": "...", "decision": "accept|reject", "reason": "..."}]}',
            *_forbid_scorer(),
        ]
    )


def literature_prompt(brief: dict) -> str:
    return "\n".join(
        [
            "ROLE: literature",
            f"Your query, and no other query: {brief['query']}",
            "Do not answer a different query.",
            f"Write only this JSON file: {brief['output']}",
            'Schema: {"query": "<the query above, unchanged>", "findings": ["short finding"], "citations": ["source"]}',
            *_forbid_scorer(),
        ]
    )


def literature_chair_prompt(brief: dict) -> str:
    reports = "\n".join(f"- {path}" for path in brief.get("reports") or [])
    return "\n".join(
        [
            "ROLE: literature_chair",
            "Merge the reports, drop duplicates, and write one verdict with citations.",
            reports,
            f"Feature: {brief.get('feature')}",
            f"Write only this JSON file: {brief['output']}",
            'Schema: {"verdict": "adopt|stands|insufficient-evidence", "method": "...", "citations": ["https://..."]}',
            "Every citation that justifies adopt or stands must be an http or https URL outside this package.",
            "A package path cannot justify the verdict. insufficient-evidence means the current method is not endorsed.",
            "verdict adopt means adopt this method. verdict stands means retrieved evidence shows the current method is competitive.",
            *_forbid_scorer(),
        ]
    )


def survey_prompt(brief: dict) -> str:
    return "\n".join(
        [
            "ROLE: survey",
            "Read the package copy. Name hot paths, algorithmic complexity, extra copies, and dependencies that dominate inference.",
            f"Write only this JSON file: {brief['output']}",
            'Schema: {"points": ["one implementation point"]}',
            *_forbid_scorer(),
        ]
    )


def survey_review_prompt(brief: dict) -> str:
    reports = "\n".join(f"- {path}" for path in brief.get("reports") or [])
    return "\n".join(
        [
            "ROLE: survey_review",
            "Keep the points that affect the admitted feature or the measured latency.",
            f"Feature: {brief.get('feature')}",
            reports,
            f"Write only this JSON file: {brief['output']}",
            'Schema: {"points": ["kept point"]}',
            *_forbid_scorer(),
        ]
    )


def metric_discover_prompt(brief: dict) -> str:
    sealed = ", ".join(brief.get("sealed_metric_ids") or []) or "none"
    gaps = ", ".join(brief.get("uncovered_behaviors") or []) or "none"
    return "\n".join(
        [
            "ROLE: metric_discover",
            "You are one fresh process. You are not the runner and not the editor.",
            f"Model: {brief.get('model', 'grok-4.7-xhigh')}",
            f"Your query, and no other query: {brief['query']}",
            "Read the package copy and the scenario text in this brief.",
            "Propose the numeric metrics this package already computes that later edits should be judged on.",
            "Do not invent a metric the package does not already compute.",
            f"Sealed metric ids: {sealed}",
            f"Uncovered scenario behaviors: {gaps}",
            "You may add a metric. You may not rename, drop, retarget, or relax a sealed metric.",
            f"Write only this JSON file: {brief['output']}",
            'Schema: {"query": "<the query above, unchanged>", "metrics": [{"id": "...", "description": "...", "direction": "minimize|maximize", "target": 0, "role": "objective|protected", "path": "/id", "noise": 0, "witnesses": ["exact scenario substring"]}]}',
            "You do not receive the eval command. Do not score. Do not edit the package. Do not edit the scorer. Do not mark a keep.",
            "Do not start python -m absolute evolve.",
        ]
    )


def edit_prompt(brief: dict) -> str:
    return "\n".join(
        [
            "ROLE: edit",
            f"Stage: {brief.get('stage')}",
            f"Hypothesis: {brief.get('hypothesis')}",
            f"Feature: {brief.get('feature')}",
            f"Method: {brief.get('method')}",
            f"Survey points: {brief.get('survey_points')}",
            f"Package copy: {brief['package_copy']}",
            f"Prior patches, with no scores attached: {brief.get('prior_patches') or []}",
            "Do not repeat a prior patch.",
            f"Write the behavior-test command to {brief['result']}",
            'Schema: {"behavior_test": ["executable", "args"]}',
            "Follow Superpowers test-driven development on the package copy: write a failing test, watch it fail, then make the smallest change that passes.",
            "Follow Superpowers verification-before-completion: run that test and read its output before you stop.",
            "Do not commit.",
            "Do not open a git worktree.",
            "Do not ask a person to sign the design.",
            "Do not run finishing-a-development-branch.",
            "Do not merge.",
            *_forbid_scorer(),
            "Do not mark a keep. The runner's script decides keep or revert.",
        ]
    )


def optimize_prompt(brief: dict) -> str:
    return "\n".join([
        "ROLE: optimize. Perform one evidence-driven experiment, then exit.",
        f"Package copy: {brief['package_copy']}",
        "Read the structured fields of this brief, including scenario_text, metrics, measured, and feedback.",
        f"Focus: {brief['focus']['metric']}. Search strategy: {brief['strategy']}.",
        "Inspect the owning code and nearby tests; identify a falsifiable hypothesis before editing.",
        "Use recent measured failures and successful patches as evidence; do not repeat an unchanged failed experiment.",
        "Implementation, algorithm, dependency, and application-feature changes are all allowed when justified.",
        "For an algorithm replacement, retrieve relevant primary literature or official implementations when tools permit.",
        "Do not invent citations or claim SOTA. A paper or a target reached is not a benchmark comparison.",
        "Address measured quality, tail latency, memory, reliability, and scenario diversity where the sealed metrics cover them.",
        "Uncovered behaviors are evaluation gaps, not evidence of success. Do not change the contract to hide them.",
        "Preserve public interfaces and existing tests. For behavior changes, add a discriminating regression test.",
        "For behavior-preserving performance edits, existing passing tests are valid; do not invent a failing assertion about implementation details.",
        "Run the relevant build and tests. This supports Python, C++, ROS, and other stacks through their own commands.",
        f"Write JSON to {brief['result']}: "
        '{"hypothesis": "short causal explanation", "behavior_test": ["executable", "args"]}.',
        "The parent independently measures every sealed metric and decides keep or revert.",
        "Read only relevant source and recent feedback. The brief is capped at 64KB; reserve context for tools and edits.",
        "The declared 500K context window is a planning ceiling, not a CLI guarantee of model capacity.",
        "Do not read old raw worker logs or the entire journal. Inspect a referenced patch only when relevant.",
        "Do not change files outside the package copy and the result file. Do not modify runner state or existing tests to weaken them.",
        "Do not commit. Do not create worktrees. Do not deploy or control a robot.",
        *_forbid_scorer(),
    ])


def render_prompt(brief: dict) -> str:
    role = brief["role"]
    prompts = {
        "research": research_prompt,
        "propose": proposal_prompt,
        "chair": chair_prompt,
        "application": application_prompt,
        "feature_propose": feature_propose_prompt,
        "feature_review_scenario": feature_review_scenario_prompt,
        "feature_review_feasibility": feature_review_feasibility_prompt,
        "feature_review_restatement": feature_review_restatement_prompt,
        "feature_admit": feature_admit_prompt,
        "literature": literature_prompt,
        "literature_chair": literature_chair_prompt,
        "survey": survey_prompt,
        "survey_review": survey_review_prompt,
        "metric_discover": metric_discover_prompt,
        "edit": edit_prompt,
        "optimize": optimize_prompt,
    }
    if role not in prompts:
        raise ValueError(f"unknown worker role {role}")
    return prompts[role](brief)
