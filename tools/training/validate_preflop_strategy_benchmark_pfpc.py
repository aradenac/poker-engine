#!/usr/bin/env python3
"""Validate the immutable PFPC replacement benchmark contract for issue #108.

The previous 2026-09-17.2 support-closed contract remains immutable.  This
validator permits exactly the representation change required after the
zero-exposure run: candidate matching moves from exact PFC to exact frozen PFPC
plus an explicit content-addressed PFPC -> source-PFC binding.  Population,
reference/support closure, scenarios, Model-B sensitivity, budgets, statistics
and thresholds must remain unchanged.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Mapping

from tools.training.validate_preflop_strategy_benchmark_support_closed import (
    DEFAULT_BASE,
    DEFAULT_BLOCKED,
    DEFAULT_REFERENCE,
    DEFAULT_SENSITIVITY,
    load,
    validate_contract as validate_support_closed_contract,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "training/full_hand/PREFLOP_STRATEGY_BENCHMARK_CONTRACT_20260918_PFPC.json"
DEFAULT_PREVIOUS = ROOT / "training/full_hand/PREFLOP_STRATEGY_BENCHMARK_CONTRACT_20260917_SUPPORT_CLOSED.json"
DEFAULT_ZERO_EXPOSURE = ROOT / "training/runs/20260917_preflop_strategy_validation_support_closed_zero_exposure/RESULT.json"


def validate_contract(
    contract: Mapping[str, Any],
    previous: Mapping[str, Any],
    base: Mapping[str, Any],
    reference: Mapping[str, Any],
    sensitivity: Mapping[str, Any],
    zero_exposure: Mapping[str, Any],
    *,
    blocked: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []

    def need(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    # First prove the immutable predecessor is still valid under its own
    # validator.  The PFPC contract may supersede it for future execution but
    # may not rewrite its scientific meaning.
    predecessor = validate_support_closed_contract(
        previous,
        base,
        reference,
        sensitivity,
        load(DEFAULT_BLOCKED) if blocked is None else blocked,
    )
    need(predecessor.get("status") == "PASS", "support-closed predecessor contract no longer validates")

    need(contract.get("schema") == "poker-preflop-strategy-benchmark-contract/v2", "PFPC contract schema drifted")
    need(contract.get("contract_version") == "2026-09-18.3", "PFPC contract version drifted")
    need(contract.get("status") == "FROZEN_BEFORE_PFPC_VALIDATION_RESULTS", "PFPC contract must freeze before results")
    need(contract.get("related_issue") == 108, "PFPC contract must remain tied to #108")
    need(
        str(contract.get("supersedes_for_future_execution") or "").endswith(
            "PREFLOP_STRATEGY_BENCHMARK_CONTRACT_20260917_SUPPORT_CLOSED.json"
        ),
        "PFPC contract must explicitly supersede 2026-09-17.2 for future execution",
    )
    reason = str(contract.get("supersession_reason") or "").lower()
    need("zero candidate exposure" in reason, "PFPC supersession reason must preserve zero-exposure cause")
    need("poker-preflop-policy-context/v1" in reason, "PFPC supersession reason must identify policy-context contract")
    need("never edit" in str(contract.get("change_policy") or "").lower(), "PFPC change policy must remain immutable")

    need(
        zero_exposure.get("schema") == "poker-preflop-strategy-validation-execution-result/v1",
        "zero-exposure predecessor evidence schema mismatch",
    )
    need(zero_exposure.get("decision") == "BLOCKED_ZERO_CANDIDATE_EXPOSURE", "predecessor must remain blocked for zero exposure")
    boundary = zero_exposure.get("selection_boundary") or {}
    need(boundary.get("test_consumed") is False, "PFPC replacement requires untouched TEST")
    need(boundary.get("promotion_authorized") is False, "zero-exposure predecessor must not authorize promotion")
    need(boundary.get("performance_gate_interpretable") is False, "zero-exposure predecessor must remain non-interpretable")
    completed = zero_exposure.get("completed_environments") or {}
    need(bool(completed), "zero-exposure predecessor must preserve completed environment evidence")
    for environment_id, row in completed.items():
        need(int((row or {}).get("supported_decisions", -1)) == 0, f"{environment_id}: predecessor exposure is not zero")

    # Everything unrelated to candidate representation stays byte-semantic
    # equivalent to the immutable predecessor.
    for field in ("population", "reference_policy", "scenarios", "environment_sensitivity", "statistics", "test_confirmation"):
        need(contract.get(field) == previous.get(field), f"PFPC replacement changed frozen {field}")

    old_validation = dict(previous.get("validation_selection") or {})
    new_validation = dict(contract.get("validation_selection") or {})
    for field, value in old_validation.items():
        need(new_validation.get(field) == value, f"PFPC replacement changed validation rule {field}")
    need(new_validation.get("candidate_exposure_must_be_positive") is True, "PFPC validation must require positive candidate exposure")
    need(
        new_validation.get("zero_candidate_exposure_outcome") == "BLOCKED_NOT_A_PERFORMANCE_RESULT",
        "PFPC zero-exposure outcome drifted",
    )

    candidate = contract.get("candidate_policy") or {}
    expected_candidate = {
        "source_issue": 107,
        "artifact_kind": "poker-hero-range-repository/v1",
        "policy_binding_kind": "poker-hero-policy-context-binding/v1",
        "immutable_artifact_sha256_required": True,
        "immutable_binding_sha256_required": True,
        "source_commit_required": True,
        "decision_contract": "poker-preflop-decision/v1",
        "source_audit_context_contract": "poker-preflop-context/v1",
        "policy_context_contract": "poker-preflop-policy-context/v1",
        "matching": "EXACT_PFPC_AND_169_HAND_CLASS_ONLY",
        "exact_policy_context_and_hand_match_required": True,
        "binding_source_pfc_must_exist_in_repository": True,
        "out_of_support_behavior": "FALL_BACK_TO_FROZEN_REFERENCE_AND_COUNT_OUT_OF_SUPPORT",
        "nearest_context_substitution_forbidden": True,
        "policy_context_bucketing_frozen_before_validation": True,
        "must_be_frozen_before_validation_rollout": True,
        "same_cycle_mutation_after_validation_starts_forbidden": True,
    }
    need(candidate == expected_candidate, "PFPC candidate policy contract drifted")

    required = set(contract.get("required_breakdowns") or [])
    need(set(previous.get("required_breakdowns") or []).issubset(required), "PFPC contract removed predecessor breakdowns")
    need({"policy_context", "candidate_support_by_policy_context"}.issubset(required), "PFPC coverage breakdowns are missing")

    old_req = set((previous.get("run_manifest_requirements") or {}).get("required_before_any_promotion_eligible_rollout") or [])
    new_req = set((contract.get("run_manifest_requirements") or {}).get("required_before_any_promotion_eligible_rollout") or [])
    need(old_req.issubset(new_req), "PFPC contract removed predecessor run identities")
    need({"candidate_binding_sha256", "candidate_binding_schema"}.issubset(new_req), "PFPC run must freeze binding SHA/schema")
    need(
        (contract.get("run_manifest_requirements") or {}).get("missing_required_identity_status") == "BLOCKED",
        "missing PFPC identity must remain BLOCKED",
    )

    return {
        "schema": "poker-preflop-strategy-pfpc-contract-validation/v1",
        "contract_version": contract.get("contract_version"),
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--previous", type=Path, default=DEFAULT_PREVIOUS)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--sensitivity", type=Path, default=DEFAULT_SENSITIVITY)
    parser.add_argument("--zero-exposure", type=Path, default=DEFAULT_ZERO_EXPOSURE)
    args = parser.parse_args()
    result = validate_contract(
        load(args.contract),
        load(args.previous),
        load(args.base),
        load(args.reference),
        load(args.sensitivity),
        load(args.zero_exposure),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
