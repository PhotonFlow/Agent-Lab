"""Sealed metric contract. The editor cannot rename, drop, or relax it."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from absolute.store import atomic_write, load_run, read_json

SCHEMA_VERSION = "1"
CONTRACT_NAME = "eval/contract.json"
_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OBLIGATION = re.compile(r"\b(must|needs)\b")


class ContractTamper(RuntimeError):
    """The sealed contract on disk no longer matches the hash the runner stored."""


def obligation_sentences(text: str) -> list[str]:
    """Scenario behaviors the runner can see without a domain-specific metric name."""
    found: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("behavior:"):
            sentence = line.split(":", 1)[1].strip()
            if sentence:
                _add(found, sentence)
            continue
        if line.startswith("output:") or line.startswith("protected:"):
            continue
        for part in re.split(r"(?<=[.!?])\s+", line):
            sentence = part.strip()
            if len(sentence) >= 12 and _OBLIGATION.search(sentence):
                _add(found, sentence)
    return found


def canonical_bytes(document: dict[str, Any]) -> bytes:
    body = {key: value for key, value in document.items() if key != "seal"}
    return json.dumps(body, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")


def compose_contract(
    metrics: list[dict[str, Any]],
    obligations: list[str],
    scenario_text: str,
    created_at: str,
) -> dict[str, Any]:
    body = {
        "edits": "reject",
        "metrics": [_public_metric(metric) for metric in sorted(metrics, key=lambda item: item["id"])],
        "obligations": list(obligations),
        "schema_version": SCHEMA_VERSION,
    }
    document = dict(body)
    document["seal"] = {
        "contract_hash": hashlib.sha256(canonical_bytes(body)).hexdigest(),
        "created_at": created_at,
        "discovery_inputs_hash": hashlib.sha256(scenario_text.encode("utf-8")).hexdigest(),
        "schema_version": SCHEMA_VERSION,
    }
    verify_document(document)
    return document


def store_contract(run_dir: Path, document: dict[str, Any]) -> str:
    path = run_dir / CONTRACT_NAME
    atomic_write(path, document)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_document(document: dict[str, Any]) -> None:
    if not isinstance(document, dict):
        raise ContractTamper("metric contract changed")
    if document.get("schema_version") != SCHEMA_VERSION or document.get("edits") != "reject":
        raise ContractTamper("metric contract changed")
    seal = document.get("seal")
    if not isinstance(seal, dict) or seal.get("schema_version") != SCHEMA_VERSION:
        raise ContractTamper("metric contract changed")
    digest = hashlib.sha256(canonical_bytes(document)).hexdigest()
    if seal.get("contract_hash") != digest:
        raise ContractTamper("metric contract changed")
    if not isinstance(document.get("metrics"), list) or not document["metrics"]:
        raise ContractTamper("metric contract changed")
    if not isinstance(document.get("obligations"), list):
        raise ContractTamper("metric contract changed")


def contract_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[str]:
    """Rename, drop, and relax show up as changes. A new id is not a change to an old one."""
    old = {metric["id"]: metric for metric in before}
    new = {metric["id"]: metric for metric in after}
    reasons: list[str] = []
    for ident, metric in old.items():
        if ident not in new:
            reasons.append(f"dropped {ident}")
            continue
        other = new[ident]
        if other["direction"] != metric["direction"]:
            reasons.append(f"direction {ident}")
        if other["role"] != metric["role"]:
            reasons.append(f"role {ident}")
        if other["path"] != metric["path"]:
            reasons.append(f"path {ident}")
        if not _same_number(metric.get("target"), other.get("target")):
            reasons.append(f"target {ident}")
        if not _same_number(metric.get("noise"), other.get("noise")):
            reasons.append(f"noise {ident}")
    return reasons


def accept_discovered_metrics(
    payloads: list[dict[str, Any]],
    eval_payload: dict[str, Any],
    scenario_text: str,
    *,
    sealed: list[dict[str, Any]] | None = None,
    gaps: list[str] | None = None,
    latency_budget: float = 1.0,
) -> list[dict[str, Any]]:
    """Keep agent proposals only when they match the eval object and the sealed set."""
    proposed: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        metrics = payload.get("metrics", [])
        if not isinstance(metrics, list):
            raise ValueError("discovery metrics must be a list")
        for raw in metrics:
            metric = normalize_metric(raw, scenario_text)
            if metric["id"] == "latency_ms":
                continue
            prior = proposed.get(metric["id"])
            if prior is None:
                proposed[metric["id"]] = metric
                continue
            if contract_changes([prior], [metric]):
                raise ValueError(f"discovery agents disagree on {metric['id']}")
            prior["witnesses"] = _union(prior["witnesses"], metric["witnesses"])
            if len(metric["description"]) > len(prior["description"]):
                prior["description"] = metric["description"]
    if sealed is None:
        accepted = list(proposed.values())
    else:
        accepted = [_public_metric(metric) for metric in sealed if metric["id"] != "latency_ms"]
        known = {metric["id"] for metric in accepted}
        for metric in proposed.values():
            if metric["id"] in known:
                previous = next(item for item in accepted if item["id"] == metric["id"])
                if contract_changes([previous], [metric]):
                    raise ValueError(f"discovery tried to change {metric['id']}")
                continue
            if not _witnesses_gap(metric, gaps or [], scenario_text):
                raise ValueError(f"{metric['id']} does not witness an uncovered behavior")
            accepted.append(metric)
    accepted = _with_latency(accepted, eval_payload, latency_budget)
    for metric in accepted:
        _require_measured(eval_payload, metric)
    objectives = [metric for metric in accepted if metric["role"] == "objective"]
    if not objectives:
        raise ValueError("discovery produced no objective metric")
    if not any(metric["target"] is not None for metric in objectives):
        raise ValueError("an objective metric needs a target")
    return [_public_metric(metric) for metric in sorted(accepted, key=lambda item: item["id"])]


def normalize_metric(raw: Any, scenario_text: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("a metric must be an object")
    ident = str(raw.get("id") or "").strip()
    if not _ID.match(ident):
        raise ValueError("metric id must be an identifier")
    description = str(raw.get("description") or "").strip()
    if not description:
        raise ValueError(f"{ident} needs a description")
    direction = raw.get("direction")
    role = raw.get("role")
    if direction not in ("minimize", "maximize"):
        raise ValueError(f"{ident} direction must be minimize or maximize")
    if role not in ("objective", "protected"):
        raise ValueError(f"{ident} role must be objective or protected")
    path = str(raw.get("path") or "").strip()
    if _pointer_token(path) != ident:
        raise ValueError(f"metric path must name {ident}")
    if "target" not in raw:
        raise ValueError(f"{ident} needs a target")
    witnesses: list[str] = []
    raw_witnesses = raw.get("witnesses") or []
    if not isinstance(raw_witnesses, list):
        raise ValueError(f"{ident} witnesses must be a list")
    for item in raw_witnesses:
        text = str(item)
        if text and text in scenario_text:
            _add(witnesses, text)
    return {
        "description": description,
        "direction": direction,
        "id": ident,
        "noise": _number(raw.get("noise"), f"{ident} noise"),
        "path": path,
        "role": role,
        "target": None if raw.get("target") is None else _number(raw.get("target"), f"{ident} target"),
        "witnesses": witnesses,
    }


def bind_metrics(charter: dict[str, Any], metrics: list[dict[str, Any]]) -> None:
    objectives = [metric for metric in metrics if metric["role"] == "objective" and metric["target"] is not None]
    objectives.sort(key=lambda metric: metric["id"])
    if not objectives:
        raise ValueError("an objective metric needs a target")
    primary = objectives[0]
    protected = [metric for metric in metrics if metric["role"] == "protected"]
    charter["metrics"] = {
        "primary": {
            "direction": primary["direction"],
            "name": primary["id"],
            "noise": primary["noise"],
            "target": primary["target"],
        },
        "protected": [_protected_row(metric) for metric in protected],
    }
    charter["required_outputs"] = [_objective_row(metric) for metric in objectives]
    others = [metric for metric in metrics if metric["role"] == "objective" and metric["target"] is None]
    charter["required_outputs"].extend(_objective_row(metric) for metric in others)


def measurement_view(charter: dict[str, Any]) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for spec in charter.get("required_outputs") or []:
        rows.append(
            (
                "objective",
                spec["metric"],
                spec["direction"],
                None if spec.get("target") is None else float(spec["target"]),
                float(spec["noise"]),
            )
        )
    for item in charter.get("metrics", {}).get("protected", []):
        rows.append(
            (
                "protected",
                item["name"],
                item["direction"],
                None if item.get("target") is None else float(item["target"]),
                float(item["max_regression"]),
            )
        )
    return sorted(rows)


def enforce_sealed_contract(run_dir: Path, charter: dict[str, Any]) -> dict[str, Any]:
    path = run_dir / CONTRACT_NAME
    if not path.is_file():
        return charter
    raw = path.read_bytes()
    expected = load_run(run_dir).get("contract_sha256")
    if not expected or hashlib.sha256(raw).hexdigest() != expected:
        raise ContractTamper("metric contract changed")
    document = json.loads(raw.decode("utf-8"))
    verify_document(document)
    rebound = dict(charter)
    bind_metrics(rebound, document["metrics"])
    if measurement_view(rebound) != measurement_view(charter):
        atomic_write(run_dir / "charter.json", rebound)
    return rebound


def load_contract(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / CONTRACT_NAME
    if not path.is_file():
        return None
    document = read_json(path)
    verify_document(document)
    expected = load_run(run_dir).get("contract_sha256")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ContractTamper("metric contract changed")
    return document


def uncovered_obligations(
    obligations: list[str],
    metrics: list[dict[str, Any]],
    scenario_text: str,
) -> list[str]:
    gaps = []
    for sentence in obligations:
        if not _witnessed(sentence, metrics, scenario_text):
            gaps.append(sentence)
    return gaps


def live_obligations(scenario_text: str, sealed: list[str]) -> list[str]:
    found = list(sealed)
    for sentence in obligation_sentences(scenario_text):
        _add(found, sentence)
    return found


def resolve_pointer(document: dict[str, Any], pointer: str) -> Any:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise KeyError(pointer)
    current: Any = document
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise KeyError(pointer)
        current = current[part]
    return current


def _public_metric(metric: dict[str, Any]) -> dict[str, Any]:
    return {
        "description": metric["description"],
        "direction": metric["direction"],
        "id": metric["id"],
        "noise": metric["noise"],
        "path": metric["path"],
        "role": metric["role"],
        "target": metric["target"],
        "witnesses": list(metric.get("witnesses") or []),
    }


def _protected_row(metric: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "direction": metric["direction"],
        "max_regression": metric["noise"],
        "name": metric["id"],
    }
    if metric["target"] is not None:
        row["target"] = metric["target"]
    return row


def _objective_row(metric: dict[str, Any]) -> dict[str, Any]:
    return {
        "direction": metric["direction"],
        "id": metric["id"],
        "metric": metric["id"],
        "noise": metric["noise"],
        "target": metric["target"],
    }


def _with_latency(metrics: list[dict[str, Any]], eval_payload: dict[str, Any], budget: float) -> list[dict[str, Any]]:
    if "latency_ms" not in eval_payload:
        return metrics
    if any(metric["id"] == "latency_ms" for metric in metrics):
        return metrics
    _require_number(eval_payload["latency_ms"], "latency_ms")
    return metrics + [
        {
            "description": "Measured latency.",
            "direction": "minimize",
            "id": "latency_ms",
            "noise": float(budget),
            "path": "/latency_ms",
            "role": "protected",
            "target": None,
            "witnesses": [],
        }
    ]


def _require_measured(eval_payload: dict[str, Any], metric: dict[str, Any]) -> None:
    try:
        value = resolve_pointer(eval_payload, metric["path"])
    except KeyError as exc:
        raise ValueError(f"eval JSON missing {metric['id']}") from exc
    _require_number(value, metric["id"])


def _require_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"eval JSON missing {label}")
    return float(value)


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    return float(value)


def _same_number(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return float(left) == float(right)


def _pointer_token(pointer: str) -> str:
    if not pointer.startswith("/"):
        raise ValueError("metric path must be a JSON pointer")
    return pointer.split("/")[-1].replace("~1", "/").replace("~0", "~")


def _witnessed(sentence: str, metrics: list[dict[str, Any]], scenario_text: str) -> bool:
    for metric in metrics:
        if re.search(rf"\b{re.escape(metric['id'])}\b", sentence):
            return True
        for quote in metric.get("witnesses") or []:
            if quote and quote in scenario_text and (quote == sentence or quote in sentence or sentence in quote):
                return True
    return False


def _witnesses_gap(metric: dict[str, Any], gaps: list[str], scenario_text: str) -> bool:
    return any(_witnessed(gap, [metric], scenario_text) for gap in gaps)


def _union(left: list[str], right: list[str]) -> list[str]:
    found = list(left)
    for item in right:
        _add(found, item)
    return found


def _add(found: list[str], item: str) -> None:
    if item not in found:
        found.append(item)
