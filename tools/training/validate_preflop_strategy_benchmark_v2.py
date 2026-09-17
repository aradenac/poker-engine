#!/usr/bin/env python3
"""Validate the immutable executable #108 benchmark v2 and run identities.

The 2026-09-15 v1 contract remains untouched for auditability.  This validator
covers only the versioned v2 experiment that replaces the unavailable autonomous
v83 preflop incumbent with the frozen native Model-A reference descriptor.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "training/full_hand/PREFLOP_STRATEGY_BENCHMARK_CONTRACT_20260917.json"
DEFAULT_BASE = ROOT / "training/full_hand/FULL_HAND_EVALUATION_PROTOCOL_20260915.json"
DEFAULT_REFERENCE = ROOT / "training/full_hand/HERO_REFERENCE_POLICY_20260917.json"
DEFAULT_SENSITIVITY = ROOT / "training/full_hand/MODEL_B_SENSITIVITY_ENVIRONMENTS_20260917.json"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def valid_sha(value: Any, regex: re.Pattern[str]) -> bool:
    return isinstance(value, str) and bool(regex.fullmatch(value.lower()))


def validate_contract(
    contract: Mapping[str, Any],
    base: Mapping[str, Any],
    reference: Mapping[str, Any],
    sensitivity: Mapping[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    require(errors, contract.get("schema") == "poker-preflop-strategy-benchmark-contract/v2", "unsupported v2 contract schema")
    require(errors, contract.get("status") == "FROZEN_BEFORE_CANDIDATE_RESULTS", "v2 contract must be frozen before candidate results")
    require(errors, contract.get("related_issue") == 108, "v2 contract must remain tied to #108")
    require(errors, bool(contract.get("supersedes_for_future_execution")), "v2 must preserve explicit v1 supersession provenance")
    reason = str(contract.get("supersession_reason") or "").lower()
    require(errors, "v83" in reason and "no #108 validation or test" in reason, "v2 must document why v1 became non-executable before result consumption")
    require(errors, "never edit" in str(contract.get("change_policy") or "").lower(), "v2 change policy must forbid post-result edits")

    population = contract.get("population") or {}
    population_id = str(population.get("population_id") or "")
    require(errors, population_id == str((base.get("scope") or {}).get("population_id") or ""), "v2 population must match base full-hand protocol")
    require(errors, population.get("population_fingerprint_sha256") == (base.get("scope") or {}).get("admissible_hand_ids_sha256"), "v2 population fingerprint drifted")
    require(errors, population.get("cross_population_generalization_forbidden") is True, "cross-population generalization must remain forbidden")

    ref = contract.get("reference_policy") or {}
    require(errors, ref.get("kind") == "POPULATION_DERIVED_REFERENCE_NOT_PRODUCTION_INCUMBENT", "reference must be explicitly non-production")
    require(errors, ref.get("v83_autonomous_preflop_claim") is False, "v2 must not claim v83 is an autonomous preflop policy")
    require(errors, ref.get("postflop_shared_with_candidate") is True, "candidate/reference must share postflop continuation")
    require(errors, ref.get("exact_context_missing") == "BLOCKED_FOR_REFERENCE_DECISION", "reference exact-context misses must fail closed")
    require(errors, reference.get("schema") == "poker-hero-reference-policy/v1", "reference descriptor schema mismatch")
    require(errors, reference.get("status") == "FROZEN_BEFORE_STRATEGY_RESULTS", "reference descriptor must be frozen")
    require(errors, reference.get("population_id") == population_id, "reference population mismatch")
    require(errors, (reference.get("selection_provenance") or {}).get("test_consumed_for_reference_selection") is False, "reference selection must not consume TEST")
    runtime = reference.get("runtime") or {}
    require(errors, runtime.get("class") == "ModelAContinuationPolicy", "reference runtime must remain native ModelAContinuationPolicy")
    require(errors, runtime.get("exact_context_policy") == "FAIL_CLOSED_ON_MISSING_EXACT_NODE", "reference runtime must fail closed on unsupported exact nodes")
    artifacts = reference.get("artifacts") or {}
    for key in ("preflop_model", "postflop_baseline", "postflop_selected_overlay"):
        row = artifacts.get(key) or {}
        require(errors, bool(row.get("path")) and valid_sha(row.get("sha256"), HEX64), f"reference artifact {key} must be content-addressed")

    candidate = contract.get("candidate_policy") or {}
    require(errors, candidate.get("source_issue") == 107, "candidate source must remain #107")
    require(errors, candidate.get("decision_contract") == "poker-preflop-decision/v1", "candidate must preserve canonical decision contract")
    require(errors, candidate.get("canonical_context_contract") == "poker-preflop-context/v1", "candidate must use canonical preflop context identity")
    require(errors, candidate.get("exact_context_and_hand_match_required") is True, "candidate must match exact context and hand")
    require(errors, candidate.get("nearest_context_substitution_forbidden") is True, "candidate nearest-context substitution must remain forbidden")
    require(errors, candidate.get("out_of_support_behavior") == "FALL_BACK_TO_FROZEN_REFERENCE_AND_COUNT_OUT_OF_SUPPORT", "candidate out-of-support behavior drifted")
    require(errors, candidate.get("must_be_frozen_before_validation_rollout") is True, "candidate must freeze before VALIDATION")

    scenarios = contract.get("scenarios") or {}
    budgets = base.get("budgets") or {}
    require(errors, scenarios.get("validation_base_hands") == budgets.get("promotion_validation_hands"), "VALIDATION budget must inherit base protocol")
    require(errors, scenarios.get("test_base_hands") == budgets.get("promotion_test_hands"), "TEST budget must inherit base protocol")
    require(errors, scenarios.get("rollouts_per_base_hand") == budgets.get("full_hand_rollouts_per_base_hand"), "rollout budget must inherit base protocol")
    require(errors, scenarios.get("paired_across_hero_policies") is True, "Hero policies must be paired")
    require(errors, scenarios.get("same_scenarios_across_model_b_environments") is True, "Model B environments must share scenarios")
    streams = list(scenarios.get("rng_streams_must_be_separate") or [])
    require(errors, len(streams) >= 4 and len(streams) == len(set(streams)), "scenario RNG streams must remain separate")

    sens = contract.get("environment_sensitivity") or {}
    require(errors, sensitivity.get("schema") == "poker-model-b-sensitivity-set/v1", "sensitivity descriptor schema mismatch")
    require(errors, sensitivity.get("status") == "FROZEN_BEFORE_STRATEGY_RESULTS", "sensitivity descriptor must be frozen")
    require(errors, sensitivity.get("population_id") == population_id, "sensitivity population mismatch")
    required_roles = set(sens.get("required_roles") or [])
    rows = list(sensitivity.get("environments") or [])
    roles = [str(row.get("role") or "") for row in rows]
    ids = [str(row.get("environment_id") or "") for row in rows]
    require(errors, len(rows) >= int(sens.get("minimum_environments") or 0) >= 3, "at least three frozen Model B environments are required")
    require(errors, required_roles == set(roles), "sensitivity roles drifted from v2 contract")
    require(errors, len(ids) == len(set(ids)) and all(ids), "sensitivity environment ids must be unique")
    base_ref = sensitivity.get("base_reference") or {}
    require(errors, base_ref.get("source_issue") == 104, "sensitivity base must remain selected #104 Model B")
    require(errors, base_ref.get("test_consumed_by_issue_104") is False, "sensitivity base selection must not consume TEST")
    require(errors, base_ref.get("artifact_sha256") == sens.get("base_artifact_sha256"), "sensitivity base artifact hash drifted")
    by_role = {str(row.get("role")): row for row in rows}
    if {"lower_aggression", "higher_aggression"}.issubset(by_role):
        low, high = by_role["lower_aggression"], by_role["higher_aggression"]
        require(errors, abs(float(low["raise_odds_multiplier"]) * float(high["raise_odds_multiplier"]) - 1.0) < 1e-12, "RAISE-odds stress must remain reciprocal")
        require(errors, abs(float(low["raise_sizing_multiplier"]) * float(high["raise_sizing_multiplier"]) - 1.0) < 1e-12, "RAISE-sizing stress must remain reciprocal")

    stats = contract.get("statistics") or {}
    require(errors, stats.get("primary_metric") == "bb_per_100_full_hands", "primary metric must remain full-hand BB/100")
    require(errors, stats.get("paired_delta") == "candidate_minus_reference", "paired delta direction must remain candidate-minus-reference")
    require(errors, float(stats.get("confidence_level") or 0.0) == 0.95, "confidence level must remain 95%")
    require(errors, stats.get("cluster_unit") == "hand_id", "uncertainty must cluster by hand_id")
    require(errors, int(stats.get("bootstrap_samples") or 0) >= 1000, "bootstrap budget is too small")

    validation = contract.get("validation_selection") or {}
    require(errors, validation.get("split") == "VALIDATION" and validation.get("test_data_visible") is False, "VALIDATION must not see TEST")
    require(errors, float(validation.get("required_ci95_lower_bound_bb_per_100")) == 0.0, "VALIDATION CI threshold drifted")
    require(errors, validation.get("minimum_environment_gate_rule") == "PASS_ALL_PREDECLARED_ENVIRONMENTS", "VALIDATION must pass every environment")
    require(errors, validation.get("if_no_candidate_passes") == "RETAIN_REFERENCE", "failed VALIDATION must retain reference")
    require(errors, validation.get("freeze_at_most_one_finalist") is True, "VALIDATION may freeze at most one finalist")

    test = contract.get("test_confirmation") or {}
    require(errors, test.get("split") == "TEST", "confirmation split must remain TEST")
    require(errors, test.get("authorized_only_for_frozen_validation_finalist") is True, "TEST requires frozen finalist")
    require(errors, test.get("test_may_select_alternative") is False and test.get("test_may_retune_candidate") is False and test.get("test_may_change_thresholds") is False, "TEST must not select/retune/change thresholds")
    require(errors, float(test.get("required_ci95_lower_bound_bb_per_100")) == 0.0, "TEST CI threshold drifted")
    require(errors, test.get("failure_or_inconclusive_outcome") == "RETAIN_REFERENCE", "failed TEST must retain reference")

    return {
        "schema": "poker-preflop-strategy-benchmark-contract-v2-validation/v1",
        "contract_version": contract.get("contract_version"),
        "population_id": population_id,
        "model_b_environment_ids": ids,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }


def validate_run_manifest(
    contract: Mapping[str, Any],
    sensitivity: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    require(errors, manifest.get("schema") == "poker-preflop-strategy-benchmark-run/v2", "unsupported v2 run manifest schema")
    require(errors, manifest.get("contract_version") == contract.get("contract_version"), "run contract version mismatch")
    phase = str(manifest.get("phase") or "").upper()
    require(errors, phase in {"VALIDATION", "TEST"}, "run phase must be VALIDATION or TEST")
    require(errors, manifest.get("results_inspected") is False, "run identities must freeze before results inspection")

    identities = manifest.get("identities") or {}
    require(errors, valid_sha(identities.get("code_commit_sha"), HEX40), "run must freeze code commit SHA")
    require(errors, identities.get("dataset_population_fingerprint_sha256") == (contract.get("population") or {}).get("population_fingerprint_sha256"), "run population fingerprint drifted")
    for field in ("scenario_manifest_sha256", "reference_descriptor_sha256", "candidate_artifact_sha256", "model_b_sensitivity_descriptor_sha256"):
        require(errors, valid_sha(identities.get(field), HEX64), f"run must freeze {field}")
    require(errors, bool(identities.get("candidate_id")), "run must freeze candidate_id")
    require(errors, valid_sha(identities.get("candidate_source_commit_sha"), HEX40), "run must freeze candidate source commit")
    require(errors, identities.get("model_b_base_artifact_sha256") == (contract.get("environment_sensitivity") or {}).get("base_artifact_sha256"), "run Model B base artifact drifted")
    expected_ids = [str(row["environment_id"]) for row in sensitivity.get("environments", [])]
    require(errors, list(identities.get("model_b_environment_ids") or []) == expected_ids, "run Model B environment identities/order drifted")

    budgets = manifest.get("budgets") or {}
    require(errors, isinstance(budgets.get("master_seed"), int), "run must freeze integer master_seed")
    require(errors, budgets.get("rollouts_per_base_hand") == (contract.get("scenarios") or {}).get("rollouts_per_base_hand"), "run rollout budget drifted")
    require(errors, budgets.get("bootstrap_samples") == (contract.get("statistics") or {}).get("bootstrap_samples"), "run bootstrap budget drifted")

    thresholds = manifest.get("thresholds") or {}
    require(errors, thresholds.get("validation_ci95_lower_bb_per_100") == (contract.get("validation_selection") or {}).get("required_ci95_lower_bound_bb_per_100"), "run VALIDATION threshold drifted")
    require(errors, thresholds.get("test_ci95_lower_bb_per_100") == (contract.get("test_confirmation") or {}).get("required_ci95_lower_bound_bb_per_100"), "run TEST threshold drifted")
    require(errors, thresholds.get("environment_gate_rule") == "PASS_ALL_PREDECLARED_ENVIRONMENTS", "run environment gate drifted")

    test_read = bool(manifest.get("test_data_read"))
    if phase == "VALIDATION":
        require(errors, not test_read, "VALIDATION run must prove TEST was not read")
        require(errors, "validation_selection" not in manifest, "pre-result VALIDATION manifest must not contain finalist selection")
    else:
        require(errors, test_read, "TEST manifest must explicitly record TEST read")
        selection = manifest.get("validation_selection") or {}
        require(errors, selection.get("outcome") == "FREEZE_FINALIST", "TEST requires a frozen VALIDATION finalist")
        require(errors, selection.get("frozen_finalist") == identities.get("candidate_id"), "TEST finalist must equal candidate_id")
        require(errors, selection.get("test_used_for_selection") is False, "TEST must not be used for selection")
        require(errors, bool(manifest.get("test_holdout_generation_id")), "TEST run must freeze holdout generation id")

    return {
        "schema": "poker-preflop-strategy-benchmark-run-v2-validation/v1",
        "phase": phase,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--sensitivity", type=Path, default=DEFAULT_SENSITIVITY)
    parser.add_argument("--run-manifest", type=Path)
    args = parser.parse_args()
    contract = load_json(args.contract)
    sensitivity = load_json(args.sensitivity)
    result = validate_contract(contract, load_json(args.base), load_json(args.reference), sensitivity)
    if result["status"] != "PASS":
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    if args.run_manifest:
        run = validate_run_manifest(contract, sensitivity, load_json(args.run_manifest))
        print(json.dumps(run, indent=2, sort_keys=True))
        return 0 if run["status"] == "PASS" else 2
    print(json.dumps({
        **result,
        "reference_descriptor_sha256": sha256_file(args.reference),
        "model_b_sensitivity_descriptor_sha256": sha256_file(args.sensitivity),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
