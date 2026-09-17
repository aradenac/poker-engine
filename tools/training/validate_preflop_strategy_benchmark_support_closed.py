#!/usr/bin/env python3
"""Validate the immutable support-closed replacement contract for issue #108."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from tools.training.validate_preflop_strategy_benchmark_v2 import validate_run_manifest

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "training/full_hand/PREFLOP_STRATEGY_BENCHMARK_CONTRACT_20260917_SUPPORT_CLOSED.json"
DEFAULT_BASE = ROOT / "training/full_hand/FULL_HAND_EVALUATION_PROTOCOL_20260915.json"
DEFAULT_REFERENCE = ROOT / "training/full_hand/HERO_REFERENCE_POLICY_20260917_SUPPORT_CLOSED.json"
DEFAULT_SENSITIVITY = ROOT / "training/full_hand/MODEL_B_SENSITIVITY_ENVIRONMENTS_20260917.json"
DEFAULT_BLOCKED = ROOT / "training/runs/20260917_preflop_strategy_validation_v2_blocked/RESULT.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_contract(
    contract: Mapping[str, Any],
    base: Mapping[str, Any],
    reference: Mapping[str, Any],
    sensitivity: Mapping[str, Any],
    blocked: Mapping[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []

    def need(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    need(contract.get("schema") == "poker-preflop-strategy-benchmark-contract/v2", "contract schema drifted")
    need(contract.get("contract_version") == "2026-09-17.2", "replacement contract version drifted")
    need(contract.get("status") == "FROZEN_BEFORE_REPLACEMENT_VALIDATION_RESULTS", "replacement contract is not frozen")
    need(contract.get("related_issue") == 108, "replacement contract must remain tied to #108")
    need(str(contract.get("supersedes_for_future_execution") or "").endswith("PREFLOP_STRATEGY_BENCHMARK_CONTRACT_20260917.json"), "replacement must supersede immutable v2 execution contract")
    need("missing postflop" in str(contract.get("supersession_reason") or "").lower(), "supersession reason must identify exact postflop support failure")
    need("never edit" in str(contract.get("change_policy") or "").lower(), "replacement change policy must remain immutable")

    need(blocked.get("schema") == "poker-preflop-strategy-validation-blocked/v1", "blocked predecessor evidence schema mismatch")
    need(blocked.get("status") == "BLOCKED", "predecessor must remain BLOCKED")
    boundary = blocked.get("selection_boundary") or {}
    need(boundary.get("environment_report_persisted") is False, "replacement may only follow a predecessor with no environment report")
    need(boundary.get("selection_performed") is False, "replacement may only follow a predecessor with no strategy selection")
    need(boundary.get("test_consumed") is False, "TEST must remain untouched")
    need(boundary.get("promotion_authorized") is False, "blocked predecessor must not authorize promotion")

    population = contract.get("population") or {}
    need(population.get("population_id") == (base.get("scope") or {}).get("population_id"), "population mismatch")
    need(population.get("population_fingerprint_sha256") == (base.get("scope") or {}).get("admissible_hand_ids_sha256"), "population fingerprint drifted")
    need(population.get("cross_population_generalization_forbidden") is True, "cross-population use must remain forbidden")

    ref_contract = contract.get("reference_policy") or {}
    need(ref_contract.get("kind") == "POPULATION_DERIVED_REFERENCE_WITH_SHARED_SUPPORT_CLOSURE", "reference kind drifted")
    need(ref_contract.get("postflop_shared_with_candidate") is True, "candidate/reference continuation must remain shared")
    need(ref_contract.get("nearest_context_substitution_forbidden") is True, "nearest-context substitution must remain forbidden")
    need(ref_contract.get("support_closure_must_be_reported") is True, "support closure must be reported")
    need(ref_contract.get("exact_context_missing") == "CHECK_THEN_CALL_THEN_FOLD_SHARED_AND_COUNTED", "support closure contract drifted")
    need(ref_contract.get("v83_autonomous_preflop_claim") is False, "replacement must not relabel v83")

    need(reference.get("schema") == "poker-hero-reference-policy/v1", "reference descriptor schema mismatch")
    need(reference.get("version") == "2026-09-17.2", "reference descriptor version mismatch")
    need(reference.get("status") == "FROZEN_BEFORE_REPLACEMENT_VALIDATION_RESULTS", "reference descriptor is not frozen")
    need(reference.get("population_id") == population.get("population_id"), "reference population mismatch")
    runtime = reference.get("runtime") or {}
    need(runtime.get("class") == "SupportClosedModelAReferencePolicy", "replacement runtime class drifted")
    need(runtime.get("delegate_class") == "ModelAContinuationPolicy", "replacement must preserve Model A exact delegate")
    need(runtime.get("unsupported_context_policy") == "CHECK_THEN_CALL_THEN_FOLD_V1", "reference fallback contract drifted")
    need(runtime.get("nearest_context_substitution") is False, "reference must not nearest-match contexts")
    closure = reference.get("support_closure") or {}
    need(closure.get("trigger") == "ModelAUnsupportedContext only", "support closure trigger drifted")
    need(closure.get("action_priority") == ["CHECK", "CALL", "FOLD"], "support closure action order drifted")
    need(closure.get("shared_by_reference_and_candidate") is True, "support closure must be common to both arms")
    need(closure.get("count_every_use") is True and closure.get("report_by_street") is True, "support closure accounting must remain mandatory")
    need((reference.get("selection_provenance") or {}).get("test_consumed_for_reference_selection") is False, "reference must not consume TEST")

    artifacts = reference.get("artifacts") or {}
    for key in ("preflop_model", "postflop_baseline", "postflop_selected_overlay"):
        row = artifacts.get(key) or {}
        path = ROOT / str(row.get("path") or "")
        need(path.is_file(), f"reference artifact {key} missing")
        if path.is_file():
            need(sha256(path) == row.get("sha256"), f"reference artifact {key} hash drifted")

    candidate = contract.get("candidate_policy") or {}
    need(candidate.get("source_issue") == 107, "candidate source drifted")
    need(candidate.get("exact_context_and_hand_match_required") is True, "candidate exact PFC/hand matching must remain required")
    need(candidate.get("nearest_context_substitution_forbidden") is True, "candidate nearest-context substitution must remain forbidden")
    need(candidate.get("out_of_support_behavior") == "FALL_BACK_TO_FROZEN_REFERENCE_AND_COUNT_OUT_OF_SUPPORT", "candidate fallback semantics drifted")

    scenarios = contract.get("scenarios") or {}
    budgets = base.get("budgets") or {}
    need(scenarios.get("validation_base_hands") == budgets.get("promotion_validation_hands"), "VALIDATION sample changed")
    need(scenarios.get("test_base_hands") == budgets.get("promotion_test_hands"), "TEST sample changed")
    need(scenarios.get("rollouts_per_base_hand") == budgets.get("full_hand_rollouts_per_base_hand"), "rollout budget changed")
    need(scenarios.get("paired_across_hero_policies") is True, "Hero pairing must remain enabled")
    need(scenarios.get("same_scenarios_across_model_b_environments") is True, "environment scenarios must remain identical")

    sens_contract = contract.get("environment_sensitivity") or {}
    need(sensitivity.get("schema") == "poker-model-b-sensitivity-set/v1", "sensitivity schema mismatch")
    need(sensitivity.get("status") == "FROZEN_BEFORE_STRATEGY_RESULTS", "sensitivity set changed after results")
    ids = [str(row.get("environment_id")) for row in sensitivity.get("environments", [])]
    roles = {str(row.get("role")) for row in sensitivity.get("environments", [])}
    need(roles == set(sens_contract.get("required_roles") or []), "sensitivity roles drifted")
    need(len(ids) >= 3 and len(ids) == len(set(ids)), "sensitivity ids invalid")
    need((sensitivity.get("base_reference") or {}).get("artifact_sha256") == sens_contract.get("base_artifact_sha256"), "Model B base artifact changed")

    stats = contract.get("statistics") or {}
    need(stats.get("paired_delta") == "candidate_minus_reference", "delta direction changed")
    need(stats.get("cluster_unit") == "hand_id", "cluster unit changed")
    need(int(stats.get("bootstrap_samples") or 0) == 5000, "bootstrap budget changed")
    validation = contract.get("validation_selection") or {}
    need(validation.get("split") == "VALIDATION" and validation.get("test_data_visible") is False, "VALIDATION/TEST boundary drifted")
    need(float(validation.get("required_ci95_lower_bound_bb_per_100")) == 0.0, "VALIDATION threshold changed")
    need(validation.get("minimum_environment_gate_rule") == "PASS_ALL_PREDECLARED_ENVIRONMENTS", "environment gate changed")
    need(validation.get("reference_support_closure_must_be_reported") is True, "closure reporting must remain required")

    return {
        "schema": "poker-preflop-strategy-support-closed-contract-validation/v1",
        "contract_version": contract.get("contract_version"),
        "model_b_environment_ids": ids,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--sensitivity", type=Path, default=DEFAULT_SENSITIVITY)
    parser.add_argument("--blocked", type=Path, default=DEFAULT_BLOCKED)
    parser.add_argument("--run-manifest", type=Path)
    args = parser.parse_args()
    contract = load(args.contract)
    sensitivity = load(args.sensitivity)
    result = validate_contract(contract, load(args.base), load(args.reference), sensitivity, load(args.blocked))
    if result["status"] == "PASS" and args.run_manifest:
        run_check = validate_run_manifest(contract, sensitivity, load(args.run_manifest))
        result["run_manifest"] = run_check
        if run_check["status"] != "PASS":
            result["status"] = "FAIL"
            result["errors"].extend(run_check["errors"])
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
