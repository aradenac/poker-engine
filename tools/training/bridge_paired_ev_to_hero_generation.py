#!/usr/bin/env python3
"""Bridge paired/adaptive EV output to one #196 Hero preflop strategy cell.

Issue #297 integration-contract only. This module does not run rollouts, consume
VALIDATION/TEST, select a real strategy, or touch #108. It maps an already
computed paired result plus an explicit exact decision binding into the existing
#196 strategy-cell contract, fail-closed.

Zero-rollout exact values are deliberately NOT coerced into MEASURED cells.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from tools.training.validate_hero_preflop_generation import (
    CANONICAL_HAND_SET,
    ContractError,
    canonical_json_bytes,
    load_json,
    sha256_path,
)

REQUEST_SCHEMA = "poker-paired-ev-generation-bridge-request/v1"
RESULT_SCHEMA = "poker-paired-ev-generation-bridge/v1"
PAIRED_SCHEMA = "paired-adaptive-preflop-ev/v1"
PLAN_SCHEMA = "poker-hero-preflop-generation-plan/v1"
PAIRING_CONTRACT = "DECISION_SAMPLE_COMMON_RANDOM_NUMBERS_V1"
MEASURED_COMPATIBLE = "MEASURED_COMPATIBLE"
EXACT_ZERO_ROLLOUT = "EXACT_ZERO_ROLLOUT_NON_MATERIALIZABLE"
EXACT_DETERMINISTIC_COMPATIBLE = "EXACT_DETERMINISTIC_COMPATIBLE"
EXACT_LOOKUP = "EXACT_CONTEXT_ONLY"

_CANONICAL_ACTIONS = {"FOLD", "CHECK", "CALL", "BET", "RAISE", "SHOVE"}
_PASSIVE_ACTIONS = {"FOLD", "CHECK", "CALL"}
_AGGRESSIVE_ACTIONS = {"BET", "RAISE"}
_ALLOWED_SIZING_KINDS = {"NONE", "FIXED_BB", "POT_FRACTION", "ALL_IN"}


class BridgeError(ContractError):
    """Fail-closed #297 adapter error."""


def fail(code: str, message: str) -> None:
    raise BridgeError(code, message)


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        fail("INVALID_NUMBER", f"{name} must be numeric, not boolean")
    try:
        number = float(value)
    except (TypeError, ValueError):
        fail("INVALID_NUMBER", f"{name}={value!r}")
    if not math.isfinite(number):
        fail("INVALID_NUMBER", f"{name} must be finite")
    return number


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        fail("INVALID_COUNT", f"{name} must be a non-negative integer")
    return value


def _sha256_value(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _plan_context_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "family": row["family"],
        "hero_position": row["hero_position"],
        "opener_position": row["opener_position"],
        "last_aggressor_position": row["last_aggressor_position"],
        "caller_count": int(row["caller_count"]),
        "limper_count": int(row["limper_count"]),
        "jam_state": bool(row["jam_state"]),
        "stack_bucket": row["effective_stack_bucket"],
    }


def _validate_action_sizing(spec: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    action = str(spec.get("action") or "")
    if action not in _CANONICAL_ACTIONS:
        fail("UNREPRESENTABLE_ACTION", action or "<empty>")

    sizing = spec.get("sizing")
    if not isinstance(sizing, Mapping):
        fail("UNREPRESENTABLE_SIZING", f"{action}: sizing must be an object")
    kind = str(sizing.get("kind") or "")
    if kind not in _ALLOWED_SIZING_KINDS:
        fail("UNREPRESENTABLE_SIZING", f"{action}: kind={kind!r}")
    unit = sizing.get("unit")
    value = sizing.get("value")

    if action in _PASSIVE_ACTIONS:
        if kind != "NONE" or unit is not None or value is not None:
            fail("UNREPRESENTABLE_SIZING", f"{action} requires NONE/null/null")
    elif action == "SHOVE":
        if kind != "ALL_IN" or unit is not None or value is not None:
            fail("UNREPRESENTABLE_SIZING", "SHOVE requires ALL_IN/null/null")
    elif action in _AGGRESSIVE_ACTIONS:
        if kind == "FIXED_BB":
            if unit != "BB" or _finite(value, f"{action}.sizing.value") <= 0:
                fail("UNREPRESENTABLE_SIZING", f"{action} FIXED_BB requires positive BB value")
        elif kind == "POT_FRACTION":
            if unit != "POT_FRACTION" or _finite(value, f"{action}.sizing.value") <= 0:
                fail("UNREPRESENTABLE_SIZING", f"{action} POT_FRACTION requires positive fraction")
        else:
            fail(
                "UNREPRESENTABLE_SIZING",
                f"{action} requires FIXED_BB or POT_FRACTION; use SHOVE for all-in",
            )

    normalized = {
        "kind": kind,
        "value": None if value is None else _finite(value, f"{action}.sizing.value"),
        "unit": unit,
    }
    return action, normalized


def _validate_identity(identity: Mapping[str, Any], plan: Mapping[str, Any], plan_sha256: str) -> dict[str, Any]:
    required = (
        "population_id",
        "generation_id",
        "candidate_id",
        "source_plan_sha256",
        "source_train_audit_sha256",
        "generator_version",
        "code_sha",
        "environment_identity_slot",
        "generation_parameters_slot",
        "scientific_effect",
    )
    missing = [name for name in required if not identity.get(name)]
    if missing:
        fail("IDENTITY_INCOMPLETE", f"missing {missing}")

    normalized = {name: str(identity[name]) for name in required}
    if normalized["source_plan_sha256"] != plan_sha256:
        fail("SOURCE_PLAN_HASH_MISMATCH", "artifact identity does not bind exact source-plan bytes")
    if normalized["population_id"] != str(plan.get("population_id") or ""):
        fail("POPULATION_MISMATCH", "artifact population differs from source plan")
    source = plan.get("source") or {}
    if normalized["source_train_audit_sha256"] != str(source.get("sha256") or ""):
        fail("SOURCE_AUDIT_HASH_MISMATCH", "artifact TRAIN audit differs from source plan")
    if len(normalized["code_sha"]) != 40 or any(c not in "0123456789abcdef" for c in normalized["code_sha"]):
        fail("IDENTITY_INVALID", "code_sha must be lowercase 40-hex")
    for key in ("source_plan_sha256", "source_train_audit_sha256"):
        value = normalized[key]
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            fail("IDENTITY_INVALID", f"{key} must be lowercase 64-hex")
    return normalized


def bridge_request(
    request: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    plan_sha256: str,
) -> dict[str, Any]:
    if request.get("schema") != REQUEST_SCHEMA:
        fail("REQUEST_SCHEMA_MISMATCH", str(request.get("schema")))
    if plan.get("schema") != PLAN_SCHEMA:
        fail("PLAN_SCHEMA_MISMATCH", str(plan.get("schema")))

    identity_raw = request.get("artifact_identity")
    if not isinstance(identity_raw, Mapping):
        fail("IDENTITY_INCOMPLETE", "artifact_identity must be an object")
    identity = _validate_identity(identity_raw, plan, plan_sha256)

    paired = request.get("paired_result")
    if not isinstance(paired, Mapping) or paired.get("schema") != PAIRED_SCHEMA:
        fail("PAIRED_SCHEMA_MISMATCH", str(paired.get("schema") if isinstance(paired, Mapping) else type(paired)))
    if paired.get("mode") not in {"paired_adaptive", "paired_fixed"}:
        fail("UNSUPPORTED_PAIRED_MODE", str(paired.get("mode")))

    search = paired.get("search")
    if not isinstance(search, Mapping):
        fail("PAIRED_RESULT_INVALID", "search must be an object")
    if search.get("pairing_contract") != PAIRING_CONTRACT:
        fail("PAIRING_CONTRACT_MISMATCH", str(search.get("pairing_contract")))
    if abs(_finite(search.get("confidence_z"), "search.confidence_z") - 1.96) > 1e-12:
        fail("UNSUPPORTED_CONFIDENCE_LEVEL", "current #196 cell names require a 95% CI (z=1.96)")

    binding = request.get("decision_binding")
    if not isinstance(binding, Mapping):
        fail("DECISION_BINDING_INVALID", "decision_binding must be an object")
    decision_id = str(binding.get("decision_id") or "")
    if not decision_id or decision_id != str(search.get("decision_id") or ""):
        fail("DECISION_ID_MISMATCH", "decision_binding must exactly match paired search decision_id")

    context_id = str(binding.get("context_id") or "")
    hand_class = str(binding.get("hand_class") or "")
    if hand_class not in CANONICAL_HAND_SET:
        fail("INVALID_HAND_CLASS", hand_class or "<empty>")

    plan_by_id = {str(row.get("context_id") or ""): row for row in plan.get("contexts") or []}
    plan_context = plan_by_id.get(context_id)
    if plan_context is None:
        fail("EXACT_CONTEXT_UNAVAILABLE", context_id or "<empty>")
    if plan_context.get("readiness") != "READY_FOR_GENERATION":
        fail("EXACT_CONTEXT_NOT_READY", context_id)
    if plan_context.get("nearest_context_allowed") is not False:
        fail("NEAREST_CONTEXT_FORBIDDEN", context_id)

    selected_id = str(paired.get("selected_id") or "")
    alternatives_result = paired.get("alternatives")
    if not selected_id or not isinstance(alternatives_result, Mapping) or selected_id not in alternatives_result:
        fail("SELECTED_ALTERNATIVE_MISSING", selected_id or "<empty>")
    alternative_specs = request.get("alternatives")
    if not isinstance(alternative_specs, Mapping) or selected_id not in alternative_specs:
        fail("ALTERNATIVE_SPEC_MISSING", selected_id)
    if selected_id == identity["candidate_id"]:
        fail(
            "IDENTITY_NAMESPACE_COLLISION",
            "alternative_id and artifact candidate_id are distinct namespaces and must differ",
        )

    action, sizing = _validate_action_sizing(alternative_specs[selected_id])
    selected = alternatives_result[selected_id]
    if not isinstance(selected, Mapping):
        fail("PAIRED_RESULT_INVALID", f"alternative {selected_id} must be an object")

    ev_bb = _finite(selected.get("ev_bb"), f"alternatives[{selected_id}].ev_bb")
    samples = _nonnegative_int(selected.get("samples"), f"alternatives[{selected_id}].samples")
    rollouts = _nonnegative_int(selected.get("rollouts"), f"alternatives[{selected_id}].rollouts")
    std_error = _finite(selected.get("standard_error_bb"), f"alternatives[{selected_id}].standard_error_bb")
    ci_low = _finite(selected.get("ci_lower_bb"), f"alternatives[{selected_id}].ci_lower_bb")
    ci_high = _finite(selected.get("ci_upper_bb"), f"alternatives[{selected_id}].ci_upper_bb")
    if std_error < 0 or ci_low > ci_high or not (ci_low <= ev_bb <= ci_high):
        fail("UNCERTAINTY_INVALID", f"{selected_id}: EV/SE/CI are inconsistent")
    worlds_materialized = _nonnegative_int(search.get("worlds_materialized"), "search.worlds_materialized")
    rollout_budget_used = _nonnegative_int(search.get("rollout_budget_used"), "search.rollout_budget_used")
    if rollouts > samples or rollouts > worlds_materialized or rollouts > rollout_budget_used:
        fail("ROLLOUT_ACCOUNTING_INVALID", selected_id)

    dimensions = _plan_context_fields(plan_context)
    support = {
        "train_observations": int(plan_context["train_observations"]),
        "distinct_hands": int(plan_context["distinct_hands"]),
        "support_tier": plan_context["support_tier"],
        "source_plan_context_id": context_id,
    }
    evidence = {
        "source_schema": PAIRED_SCHEMA,
        "source_result_sha256": _sha256_value(paired),
        "mode": paired["mode"],
        "pairing_contract": PAIRING_CONTRACT,
        "ev_bb": ev_bb,
        "samples": samples,
        "rollouts": rollouts,
        "worlds_materialized": worlds_materialized,
        "rollout_budget_used": rollout_budget_used,
        "standard_error_bb": std_error,
        "ci95_low_bb": ci_low,
        "ci95_high_bb": ci_high,
    }

    cell = None
    if rollouts == 0:
        if samples <= 0:
            fail("EXACT_VALUE_EVIDENCE_INVALID", "zero-rollout exact value must still expose sampled/report evidence")
        exact_fold = (
            action == "FOLD"
            and sizing == {"kind": "NONE", "value": None, "unit": None}
            and abs(ev_bb) <= 1e-12
            and abs(std_error) <= 1e-12
            and abs(ci_low) <= 1e-12
            and abs(ci_high) <= 1e-12
        )
        if exact_fold:
            bridge_state = EXACT_DETERMINISTIC_COMPATIBLE
            cell = {
                "population_id": identity["population_id"],
                "generation_id": identity["generation_id"],
                "candidate_id": identity["candidate_id"],
                "context_id": context_id,
                **dimensions,
                "hand_class": hand_class,
                "action": {"status": "EXACT_DETERMINISTIC", "value": "FOLD"},
                "sizing": {"status": "EXACT_DETERMINISTIC", "kind": "NONE", "value": None, "unit": None},
                "ev": {
                    "status": "EXACT_DETERMINISTIC",
                    "estimate_bb": 0.0,
                    "uncertainty": {
                        "method": "EXACT_DETERMINISTIC_ZERO",
                        "std_error_bb": 0.0,
                        "ci95_low_bb": 0.0,
                        "ci95_high_bb": 0.0,
                    },
                },
                "rollout": {
                    "status": "EXACT_DETERMINISTIC",
                    "sample_count": samples,
                    "world_count": 0,
                },
                "support": support,
                "provenance": {
                    "source_plan_sha256": identity["source_plan_sha256"],
                    "source_train_audit_sha256": identity["source_train_audit_sha256"],
                    "generator_version": identity["generator_version"],
                    "code_sha": identity["code_sha"],
                    "environment_identity_slot": identity["environment_identity_slot"],
                    "generation_parameters_slot": identity["generation_parameters_slot"],
                    "scientific_effect": identity["scientific_effect"],
                },
            }
        else:
            bridge_state = EXACT_ZERO_ROLLOUT
    else:
        if samples != rollouts:
            fail(
                "ROLLOUT_ACCOUNTING_INVALID",
                "MEASURED materialization requires selected samples == selected rollouts",
            )
        bridge_state = MEASURED_COMPATIBLE
        cell = {
            "population_id": identity["population_id"],
            "generation_id": identity["generation_id"],
            "candidate_id": identity["candidate_id"],
            "context_id": context_id,
            **dimensions,
            "hand_class": hand_class,
            "action": {"status": "MEASURED", "value": action},
            "sizing": {
                "status": "MEASURED",
                "kind": sizing["kind"],
                "value": sizing["value"],
                "unit": sizing["unit"],
            },
            "ev": {
                "status": "MEASURED",
                "estimate_bb": ev_bb,
                "uncertainty": {
                    "method": "PAIRED_CRN_CI95",
                    "std_error_bb": std_error,
                    "ci95_low_bb": ci_low,
                    "ci95_high_bb": ci_high,
                },
            },
            "rollout": {
                "status": "MEASURED",
                "sample_count": samples,
                "world_count": rollouts,
            },
            "support": support,
            "provenance": {
                "source_plan_sha256": identity["source_plan_sha256"],
                "source_train_audit_sha256": identity["source_train_audit_sha256"],
                "generator_version": identity["generator_version"],
                "code_sha": identity["code_sha"],
                "environment_identity_slot": identity["environment_identity_slot"],
                "generation_parameters_slot": identity["generation_parameters_slot"],
                "scientific_effect": identity["scientific_effect"],
            },
        }

    result_without_hash = {
        "schema": RESULT_SCHEMA,
        "bridge_state": bridge_state,
        "scientific_effect": "NONE_INTEGRATION_CONTRACT_ONLY",
        "exact_lookup": EXACT_LOOKUP,
        "nearest_context_allowed": False,
        "decision_id": decision_id,
        "context_id": context_id,
        "hand_class": hand_class,
        "alternative_id": selected_id,
        "population_id": identity["population_id"],
        "generation_id": identity["generation_id"],
        "candidate_id": identity["candidate_id"],
        "source_plan_sha256": identity["source_plan_sha256"],
        "source_train_audit_sha256": identity["source_train_audit_sha256"],
        "generator_version": identity["generator_version"],
        "code_sha": identity["code_sha"],
        "environment_identity_slot": identity["environment_identity_slot"],
        "generation_parameters_slot": identity["generation_parameters_slot"],
        "exact_context": {"context_id": context_id, **dimensions},
        "selected_alternative": {
            "action": action,
            "sizing": sizing,
        },
        "evidence": evidence,
        "strategy_cell": cell,
    }
    return {
        **result_without_hash,
        "output_sha256": _sha256_value(result_without_hash),
    }


def bridge_file(request_path: Path, plan_path: Path) -> dict[str, Any]:
    request = load_json(request_path)
    plan = load_json(plan_path)
    return bridge_request(request, plan, plan_sha256=sha256_path(plan_path))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = bridge_file(args.request, args.plan)
    except ContractError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": exc.message}}, indent=2, sort_keys=True))
        return 1

    payload = canonical_json_bytes(result)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(payload)
    print(payload.decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
