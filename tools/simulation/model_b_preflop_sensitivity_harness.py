#!/usr/bin/env python3
"""Synthetic-only Model B preflop sensitivity harness for issue #344."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.simulation.model_b_preflop_response_to_price import (
    ACTIONS,
    EmpiricalPreflopResponseToPriceModel,
    artifact_sha256,
)

SCHEMA = "model-b-preflop-sensitivity-harness-request/v1"
REPORT_SCHEMA = "model-b-preflop-sensitivity-harness-report/v1"
CANONICAL_DECISION_SCHEMA = "poker-preflop-decision/v1"
SOURCE_KIND = "SYNTHETIC_HARNESS_ONLY"
FORBIDDEN_MODEL_FEATURES = {
    "ev_bb", "uncertainty", "confidence", "recommended_action",
    "recommended_sizing", "recommendation", "model_a", "model_a_ev",
    "model_a_policy", "model_a_recommendation", "hero_ev",
    "hero_recommendation",
}
SUPPORTED_HERO_ACTIONS = {"FOLD", "OVERLIMP", "ISO"}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def canonical_sha256(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _finite(value: Any, *, name: str, nonnegative: bool = True) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(x) or (nonnegative and x < 0):
        raise ValueError(f"{name} must be finite" + (" and non-negative" if nonnegative else ""))
    return x


def _forbidden_keys(value: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered in FORBIDDEN_MODEL_FEATURES or lowered.startswith("model_a"):
                found.append(f"{path}.{key}")
            found.extend(_forbidden_keys(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_forbidden_keys(child, f"{path}[{index}]"))
    return found


def project_canonical_decision(
    decision: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Project #314 canonical alternatives to public action+sizing fields only."""
    if decision.get("schema") != CANONICAL_DECISION_SCHEMA:
        raise ValueError(f"expected {CANONICAL_DECISION_SCHEMA}")
    alternatives = decision.get("alternatives")
    if not isinstance(alternatives, list) or not alternatives:
        raise ValueError("canonical decision alternatives are required")

    projected = []
    seen = set()
    for raw in alternatives:
        if not isinstance(raw, Mapping):
            raise ValueError("canonical alternative must be an object")
        alternative_id = str(raw.get("id") or raw.get("alternative_id") or "")
        if not alternative_id or alternative_id in seen:
            raise ValueError("canonical alternative id missing or duplicate")
        seen.add(alternative_id)
        action = str(raw.get("action") or "").upper()
        if action not in SUPPORTED_HERO_ACTIONS:
            raise ValueError(f"unsupported Hero action for sensitivity harness: {action!r}")
        target = raw.get("target_total_bb")
        incremental = raw.get("incremental_cost_bb")
        if action == "FOLD":
            if target is not None or _finite(incremental, name=f"{alternative_id}.incremental_cost_bb") != 0:
                raise ValueError("FOLD must have null target_total_bb and zero incremental cost")
        else:
            target = _finite(target, name=f"{alternative_id}.target_total_bb")
            incremental = _finite(incremental, name=f"{alternative_id}.incremental_cost_bb")
        projected.append({
            "alternative_id": alternative_id,
            "action": action,
            "target_total_bb": target,
            "incremental_cost_bb": float(incremental),
        })

    request = {
        "schema": SCHEMA,
        "source_kind": SOURCE_KIND,
        "synthetic_fixture": bool(context.get("synthetic_fixture")),
        "decision_ref": {
            "canonical_schema": CANONICAL_DECISION_SCHEMA,
            "decision_id": decision.get("decision_id"),
            "context_id": decision.get("context_id"),
        },
        "public_context": copy.deepcopy(dict(context)),
        "alternatives": projected,
        "information_boundary": {
            "hero_ev_consumed": False,
            "model_a_consumed": False,
            "recommendation_consumed": False,
            "future_cards_consumed": False,
            "opponent_hole_cards_consumed": False,
        },
    }
    validate_request(request)
    return request


def validate_request(request: Mapping[str, Any]) -> None:
    if request.get("schema") != SCHEMA:
        raise ValueError(f"expected request schema {SCHEMA}")
    if request.get("source_kind") != SOURCE_KIND or request.get("synthetic_fixture") is not True:
        raise ValueError("issue #344 accepts synthetic harness inputs only")
    boundary = request.get("information_boundary") or {}
    for key in (
        "hero_ev_consumed", "model_a_consumed", "recommendation_consumed",
        "future_cards_consumed", "opponent_hole_cards_consumed",
    ):
        if boundary.get(key) is not False:
            raise ValueError("information boundary must explicitly forbid EV/Model-A/private information")

    decision_ref = request.get("decision_ref") or {}
    if decision_ref.get("canonical_schema") != CANONICAL_DECISION_SCHEMA:
        raise ValueError("request must bind the canonical preflop decision contract")
    if not decision_ref.get("context_id"):
        raise ValueError("decision_ref.context_id is required")

    context = request.get("public_context")
    if not isinstance(context, Mapping):
        raise ValueError("public_context is required")
    required = (
        "hero_position", "hero_contribution_before_bb", "pot_before_hero_action_bb",
        "initial_sequence", "limper_count", "responders",
    )
    missing = [key for key in required if context.get(key) is None]
    if missing:
        raise ValueError(f"missing public sensitivity context: {missing}")
    if context.get("synthetic_fixture") is not True:
        raise ValueError("public context must be synthetic_fixture=true")
    if not str(context["hero_position"]).upper():
        raise ValueError("hero_position is required")
    hero_before = _finite(context["hero_contribution_before_bb"], name="hero_contribution_before_bb")
    _finite(context["pot_before_hero_action_bb"], name="pot_before_hero_action_bb")
    if int(context["limper_count"]) < 0:
        raise ValueError("limper_count must be non-negative")
    if not isinstance(context["initial_sequence"], list):
        raise ValueError("initial_sequence must be an array")

    responders = context["responders"]
    if not isinstance(responders, list) or not responders:
        raise ValueError("at least one responder is required")
    positions = set()
    for index, responder in enumerate(responders):
        if not isinstance(responder, Mapping):
            raise ValueError("responder must be an object")
        position = str(responder.get("position") or "").upper()
        if not position or position in positions:
            raise ValueError("responder position missing or duplicate")
        positions.add(position)
        for key in ("profile", "contribution_bb", "effective_stack_bb", "family_no_callers", "family_with_callers"):
            if responder.get(key) is None:
                raise ValueError(f"responder[{index}].{key} is required")
        _finite(responder["contribution_bb"], name=f"responder[{index}].contribution_bb")
        _finite(responder["effective_stack_bb"], name=f"responder[{index}].effective_stack_bb")

    alternatives = request.get("alternatives")
    if not isinstance(alternatives, list) or not alternatives:
        raise ValueError("alternatives are required")
    seen = set()
    for raw in alternatives:
        alternative_id = str(raw.get("alternative_id") or "")
        if not alternative_id or alternative_id in seen:
            raise ValueError("alternative id missing or duplicate")
        seen.add(alternative_id)
        action = str(raw.get("action") or "").upper()
        if action not in SUPPORTED_HERO_ACTIONS:
            raise ValueError(f"unsupported alternative action: {action!r}")
        if action in {"ISO", "OVERLIMP"}:
            target = _finite(raw.get("target_total_bb"), name=f"{alternative_id}.target_total_bb")
            incremental = _finite(raw.get("incremental_cost_bb"), name=f"{alternative_id}.incremental_cost_bb")
            if abs((target - hero_before) - incremental) > 1e-9:
                raise ValueError(f"{alternative_id} incremental cost does not match exact target sizing")
        else:
            if raw.get("target_total_bb") is not None or float(raw.get("incremental_cost_bb", -1)) != 0:
                raise ValueError(f"{alternative_id} FOLD sizing contract invalid")

    forbidden = _forbidden_keys(request)
    if forbidden:
        raise ValueError(f"forbidden Model A/EV/recommendation feature injected: {forbidden}")


def verify_issue_340_identity(
    *,
    candidate_doc: Mapping[str, Any],
    reference_doc: Mapping[str, Any],
    summary: Mapping[str, Any],
    result: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    if summary.get("schema") != "model-b-preflop-response-to-price-2a-summary/v1":
        raise ValueError("unexpected #340 summary schema")
    if result.get("schema") != "model-b-preflop-response-to-price-2a-result/v1":
        raise ValueError("unexpected #340 result schema")
    if result.get("status") != "COMPLETE":
        raise ValueError("#340 result is not complete")
    if result.get("test_consumed") is not False or result.get("production_effect") != "NONE":
        raise ValueError("#340 evidence violates TEST/production boundary")
    if result.get("automatic_promotion") is not False or result.get("active_model_b_changed") is not False:
        raise ValueError("#340 must not have promoted/activated the candidate")
    if provenance.get("schema") != "model-b-preflop-response-to-price-2a-run-provenance/v1":
        raise ValueError("unexpected #340 provenance schema")
    sci = provenance.get("scientific_identity") or {}
    candidate_hash = artifact_sha256(candidate_doc)
    reference_hash = artifact_sha256(reference_doc)
    if candidate_hash != summary.get("candidate_artifact_sha256") or candidate_hash != sci.get("candidate_artifact_sha256"):
        raise ValueError("#340 candidate identity/hash mismatch")
    if reference_hash != summary.get("reference_artifact_sha256") or reference_hash != sci.get("reference_artifact_sha256"):
        raise ValueError("#340 reference identity/hash mismatch")
    report_hash = str(summary.get("source_issue_319_report_hash") or "")
    if not report_hash or report_hash != sci.get("source_issue_319_report_hash"):
        raise ValueError("#340 source #319 provenance mismatch")
    if candidate_doc.get("source_issue_319_report_hash") != report_hash:
        raise ValueError("#340 candidate does not bind the expected #319 report")
    if reference_doc.get("source_issue_319_report_hash") != report_hash:
        raise ValueError("#340 reference does not bind the expected #319 report")
    if candidate_doc.get("reference_mode") is not False or reference_doc.get("reference_mode") is not True:
        raise ValueError("#340 candidate/reference roles are inconsistent")
    return {
        "source_issue": 340,
        "candidate_artifact_sha256": candidate_hash,
        "reference_artifact_sha256": reference_hash,
        "source_issue_319_report_hash": report_hash,
        "workflow_run_id": provenance.get("workflow_run_id"),
        "upstream_validation_evidence_referenced": True,
        "validation_data_consumed_by_this_harness": False,
        "test_consumed_by_this_harness": False,
        "production_effect": "NONE",
    }


def _prediction_input(
    *,
    responder: Mapping[str, Any],
    hero_position: str,
    sequence: Sequence[Mapping[str, str]],
    limper_count: int,
    caller_count: int,
    target_total_bb: float,
    pot_before_response_bb: float,
) -> dict[str, Any]:
    contribution = _finite(responder["contribution_bb"], name="responder.contribution_bb")
    to_call = max(0.0, target_total_bb - contribution)
    if pot_before_response_bb <= 0:
        raise ValueError("pot_before_response_bb must be positive")
    family = (
        str(responder["family_with_callers"])
        if caller_count > 0
        else str(responder["family_no_callers"])
    )
    return {
        "profile": responder["profile"],
        "family": family,
        "responder_position": str(responder["position"]).upper(),
        "raiser_position": hero_position,
        "sequence": ">".join(f"{x['position']}:{x['action']}" for x in sequence),
        "limper_count": int(limper_count),
        "caller_count": int(caller_count),
        "target_total_bb": float(target_total_bb),
        "facing_price_to_pot": float(to_call / pot_before_response_bb),
        "effective_stack_bb": _finite(responder["effective_stack_bb"], name="responder.effective_stack_bb"),
    }


def _aggregate_responder(rows: list[tuple[float, Mapping[str, Any]]], *, reach: float) -> dict[str, Any]:
    if reach <= 0:
        return {
            "reach_probability": 0.0,
            "conditional_action_probabilities": {action: None for action in ACTIONS},
            "unconditional_action_event_probabilities": {action: 0.0 for action in ACTIONS},
            "support_state_probability": {},
            "selected_level_probability": {},
            "non_identifiability": "NOT_REACHED",
        }
    action_weight = {action: 0.0 for action in ACTIONS}
    support_weight: dict[str, float] = {}
    level_weight: dict[str, float] = {}
    for state_weight, pred in rows:
        for action in ACTIONS:
            action_weight[action] += state_weight * float(pred["probabilities"][action])
        support = str(pred["support_state"])
        support_weight[support] = support_weight.get(support, 0.0) + state_weight
        level = str(pred["selected_level"]["index"])
        level_weight[level] = level_weight.get(level, 0.0) + state_weight
    conditional = {action: action_weight[action] / reach for action in ACTIONS}
    return {
        "reach_probability": reach,
        "conditional_action_probabilities": conditional,
        "unconditional_action_event_probabilities": action_weight,
        "support_state_probability": {key: value / reach for key, value in sorted(support_weight.items())},
        "selected_level_probability": {
            key: value / reach
            for key, value in sorted(level_weight.items(), key=lambda item: int(item[0]))
        },
        "non_identifiability": (
            "EXACT_IDENTIFIABLE"
            if set(support_weight) == {"EXACT_SUPPORTED"}
            else "DECLARED_BACKOFF_OR_BINNED_SUPPORT"
        ),
    }


def evaluate_iso_alternative(
    *,
    alternative: Mapping[str, Any],
    context: Mapping[str, Any],
    model: EmpiricalPreflopResponseToPriceModel,
) -> dict[str, Any]:
    target = _finite(alternative["target_total_bb"], name="target_total_bb")
    hero_position = str(context["hero_position"]).upper()
    hero_before = _finite(context["hero_contribution_before_bb"], name="hero_contribution_before_bb")
    starting_pot = _finite(context["pot_before_hero_action_bb"], name="pot_before_hero_action_bb")
    hero_add = target - hero_before
    if hero_add <= 0:
        raise ValueError("ISO target_total_bb must exceed Hero current contribution")

    initial_sequence = [
        {"position": str(x["position"]).upper(), "action": str(x["action"]).upper()}
        for x in context["initial_sequence"]
    ] + [{"position": hero_position, "action": "RAISE"}]
    states = [{
        "weight": 1.0,
        "pot_bb": starting_pot + hero_add,
        "caller_count": 0,
        "callers": 0,
        "continuers": 0,
        "aggressive": False,
        "sequence": initial_sequence,
        "terminal": False,
    }]
    per_responder = []

    for responder in context["responders"]:
        reach = sum(state["weight"] for state in states if not state["terminal"])
        prediction_rows: list[tuple[float, Mapping[str, Any]]] = []
        next_states = []
        unsupported = None
        for state in states:
            if state["terminal"]:
                next_states.append(state)
                continue
            raw = _prediction_input(
                responder=responder,
                hero_position=hero_position,
                sequence=state["sequence"],
                limper_count=int(context["limper_count"]),
                caller_count=int(state["caller_count"]),
                target_total_bb=target,
                pot_before_response_bb=float(state["pot_bb"]),
            )
            forbidden = _forbidden_keys(raw)
            if forbidden:
                raise ValueError(f"forbidden feature reached Model B prediction input: {forbidden}")
            try:
                pred = model.predict(**raw)
            except KeyError as exc:
                unsupported = str(exc)
                break
            prediction_rows.append((state["weight"], pred))
            contribution = _finite(responder["contribution_bb"], name="responder.contribution_bb")
            call_cost = max(0.0, target - contribution)
            for action in ACTIONS:
                branch_weight = state["weight"] * float(pred["probabilities"][action])
                if branch_weight <= 0:
                    continue
                branch = copy.deepcopy(state)
                branch["weight"] = branch_weight
                branch["sequence"] = list(branch["sequence"]) + [{
                    "position": str(responder["position"]).upper(),
                    "action": action,
                }]
                if action == "CALL":
                    branch["pot_bb"] = float(branch["pot_bb"]) + call_cost
                    branch["caller_count"] = int(branch["caller_count"]) + 1
                    branch["callers"] = int(branch["callers"]) + 1
                    branch["continuers"] = int(branch["continuers"]) + 1
                elif action in {"RAISE", "JAM"}:
                    branch["aggressive"] = True
                    branch["continuers"] = int(branch["continuers"]) + 1
                    branch["terminal"] = True
                next_states.append(branch)
        if unsupported is not None:
            return {
                "status": "UNSUPPORTED",
                "alternative_id": alternative["alternative_id"],
                "action": "ISO",
                "target_total_bb": target,
                "reason": "NO_DECLARED_SUPPORTED_MODEL_B_CONTEXT",
                "detail": unsupported,
            }
        per_responder.append({
            "position": str(responder["position"]).upper(),
            **_aggregate_responder(prediction_rows, reach=reach),
        })
        states = next_states

    mass = sum(float(state["weight"]) for state in states)
    if abs(mass - 1.0) > 1e-9:
        raise AssertionError(f"branch probability mass drift: {mass}")
    p_all_fold = sum(
        state["weight"] for state in states
        if int(state["continuers"]) == 0 and not state["aggressive"]
    )
    p_3bet_or_jam = sum(state["weight"] for state in states if state["aggressive"])
    expected_continuers = sum(state["weight"] * int(state["continuers"]) for state in states)
    caller_partition = {
        "all_fold": sum(state["weight"] for state in states if int(state["callers"]) == 0 and not state["aggressive"]),
        "exactly_1_caller": sum(state["weight"] for state in states if int(state["callers"]) == 1 and not state["aggressive"]),
        "exactly_2_callers": sum(state["weight"] for state in states if int(state["callers"]) == 2 and not state["aggressive"]),
        "three_plus_callers": sum(state["weight"] for state in states if int(state["callers"]) >= 3 and not state["aggressive"]),
        "aggressive_terminal": p_3bet_or_jam,
    }
    backoff_states = sorted({
        key
        for responder in per_responder
        for key in responder["support_state_probability"]
        if key != "EXACT_SUPPORTED"
    })
    return {
        "status": "AVAILABLE",
        "alternative_id": alternative["alternative_id"],
        "action": "ISO",
        "target_total_bb": target,
        "incremental_cost_bb": float(alternative["incremental_cost_bb"]),
        "responder_probabilities": per_responder,
        "aggregate": {
            "p_all_fold": p_all_fold,
            "expected_continuers": expected_continuers,
            "p_3bet_or_jam": p_3bet_or_jam,
            "caller_partition_with_aggressive_terminal": caller_partition,
        },
        "support": {
            "non_identifiability": (
                "EXACT_IDENTIFIABLE" if not backoff_states
                else "DECLARED_BACKOFF_OR_BINNED_SUPPORT"
            ),
            "backoff_states_observed": backoff_states,
            "nearest_price_substitution": False,
            "family_never_dropped": True,
        },
        "modeling_boundary": {
            "aggressive_response_is_terminal": True,
            "reason": "#340 response-to-price covers the facing response; later response-to-3bet is intentionally not invented",
        },
    }


def _non_iso(alternative: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "NOT_APPLICABLE",
        "alternative_id": alternative["alternative_id"],
        "action": str(alternative["action"]).upper(),
        "target_total_bb": alternative.get("target_total_bb"),
        "incremental_cost_bb": float(alternative["incremental_cost_bb"]),
        "reason": "MODEL_B_RESPONSE_TO_PRICE_REQUIRES_HERO_AGGRESSION",
        "responder_probabilities": None,
        "aggregate": None,
        "support": {
            "non_identifiability": "NOT_APPLICABLE",
            "nearest_price_substitution": False,
        },
    }


def _delta(low: Mapping[str, Any], high: Mapping[str, Any]) -> dict[str, Any]:
    if low.get("status") != "AVAILABLE" or high.get("status") != "AVAILABLE":
        return {
            "status": "UNAVAILABLE",
            "low_alternative_id": low["alternative_id"],
            "high_alternative_id": high["alternative_id"],
        }
    aggregate = {
        key: float(high["aggregate"][key]) - float(low["aggregate"][key])
        for key in ("p_all_fold", "expected_continuers", "p_3bet_or_jam")
    }
    by_low = {row["position"]: row for row in low["responder_probabilities"]}
    by_high = {row["position"]: row for row in high["responder_probabilities"]}
    responders = []
    for position in sorted(set(by_low) & set(by_high)):
        a, b = by_low[position], by_high[position]
        if a["reach_probability"] <= 0 or b["reach_probability"] <= 0:
            continue
        responders.append({
            "position": position,
            "high_minus_low_conditional_action_probability": {
                action: (
                    float(b["conditional_action_probabilities"][action])
                    - float(a["conditional_action_probabilities"][action])
                )
                for action in ACTIONS
            },
            "high_minus_low_reach_probability": (
                float(b["reach_probability"]) - float(a["reach_probability"])
            ),
        })
    return {
        "status": "AVAILABLE",
        "low_alternative_id": low["alternative_id"],
        "high_alternative_id": high["alternative_id"],
        "low_target_total_bb": low["target_total_bb"],
        "high_target_total_bb": high["target_total_bb"],
        "high_minus_low": {"aggregate": aggregate, "responders": responders},
    }


def run_harness(
    request: Mapping[str, Any],
    *,
    candidate_doc: Mapping[str, Any],
    reference_doc: Mapping[str, Any],
    summary: Mapping[str, Any],
    result: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    validate_request(request)
    identity = verify_issue_340_identity(
        candidate_doc=candidate_doc,
        reference_doc=reference_doc,
        summary=summary,
        result=result,
        provenance=provenance,
    )
    candidate = EmpiricalPreflopResponseToPriceModel(candidate_doc)
    reference = EmpiricalPreflopResponseToPriceModel(reference_doc)

    candidate_rows = []
    reference_rows = []
    for alternative in request["alternatives"]:
        if alternative["action"] != "ISO":
            candidate_rows.append(_non_iso(alternative))
            reference_rows.append(_non_iso(alternative))
        else:
            candidate_rows.append(evaluate_iso_alternative(
                alternative=alternative, context=request["public_context"], model=candidate
            ))
            reference_rows.append(evaluate_iso_alternative(
                alternative=alternative, context=request["public_context"], model=reference
            ))

    candidate_by = {row["alternative_id"]: row for row in candidate_rows}
    reference_by = {row["alternative_id"]: row for row in reference_rows}
    iso_ids = [alt["alternative_id"] for alt in request["alternatives"] if alt["action"] == "ISO"]
    pairwise_candidate = []
    pairwise_reference = []
    for i in range(len(iso_ids)):
        for j in range(i + 1, len(iso_ids)):
            pairwise_candidate.append(_delta(candidate_by[iso_ids[i]], candidate_by[iso_ids[j]]))
            pairwise_reference.append(_delta(reference_by[iso_ids[i]], reference_by[iso_ids[j]]))

    report = {
        "schema": REPORT_SCHEMA,
        "source_kind": SOURCE_KIND,
        "status": "SYNTHETIC_HARNESS_ONLY",
        "decision_ref": copy.deepcopy(request["decision_ref"]),
        "input_request_sha256": canonical_sha256(request),
        "issue_340_identity": identity,
        "scope": {
            "real_issue_314_consumed": False,
            "hero_ev_consumed": False,
            "model_a_consumed": False,
            "recommendation_consumed": False,
            "train_consumed": False,
            "validation_consumed": False,
            "test_consumed": False,
            "active_model_b_changed": False,
            "automatic_promotion": False,
            "production_effect": "NONE",
            "ui_modified": False,
        },
        "candidate": {
            "identity": candidate.identity,
            "alternatives": candidate_rows,
            "pairwise_sizing_deltas": pairwise_candidate,
        },
        "reference_control": {
            "identity": reference.identity,
            "alternatives": reference_rows,
            "pairwise_sizing_deltas": pairwise_reference,
            "role": "price-agnostic #340 control; not an active-pointer mutation",
        },
        "future_issue_314_contract": {
            "canonical_schema": CANONICAL_DECISION_SCHEMA,
            "projection_function": "project_canonical_decision",
            "consumed_fields_per_alternative": [
                "id/alternative_id", "action", "target_total_bb", "incremental_cost_bb"
            ],
            "explicitly_not_consumed": [
                "ev_bb", "uncertainty", "confidence", "support", "selected_id",
                "recommendations", "Model A fields",
            ],
        },
    }
    report["report_sha256"] = canonical_sha256(report)
    return report


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--request-output", type=Path)
    args = parser.parse_args()

    decision = load_json(args.decision)
    context = load_json(args.context)
    request = project_canonical_decision(decision, context=context)
    report = run_harness(
        request,
        candidate_doc=load_json(args.candidate),
        reference_doc=load_json(args.reference),
        summary=load_json(args.summary),
        result=load_json(args.result),
        provenance=load_json(args.provenance),
    )
    if args.request_output:
        write_report(args.request_output, request)
    write_report(args.output, report)
    print(json.dumps({
        "schema": report["schema"],
        "status": report["status"],
        "report_sha256": report["report_sha256"],
        "issue_340_identity": report["issue_340_identity"],
        "candidate_alternatives": [
            {
                "alternative_id": row["alternative_id"],
                "status": row["status"],
                "target_total_bb": row.get("target_total_bb"),
                "aggregate": row.get("aggregate"),
                "support": row.get("support"),
            }
            for row in report["candidate"]["alternatives"]
        ],
        "scope": report["scope"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
