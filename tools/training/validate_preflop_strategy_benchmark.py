#!/usr/bin/env python3
"""Validate the frozen #108 preflop/full-hand benchmark contract and run manifests.

This module is deliberately result-blind. It checks that the experimental design,
policy identities, paired scenario identity, Model-B sensitivity environments and
VALIDATION/TEST boundaries are frozen before any promotion-eligible rollout. A
missing identity is BLOCKED/FAIL evidence, never an implicit fallback.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "training/full_hand/PREFLOP_STRATEGY_BENCHMARK_CONTRACT_20260915.json"
DEFAULT_BASE_PROTOCOL = ROOT / "training/full_hand/FULL_HAND_EVALUATION_PROTOCOL_20260915.json"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def nested(data: dict[str, Any], *keys: str) -> Any:
    value: Any = data
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _valid_sha(value: Any, regex: re.Pattern[str]) -> bool:
    return isinstance(value, str) and bool(regex.fullmatch(value.lower()))


def _equals_float(value: Any, expected: float) -> bool:
    """Compare an explicitly present numeric value without treating 0.0 as missing."""
    if value is None:
        return False
    try:
        return float(value) == expected
    except (TypeError, ValueError):
        return False


def validate_contract(contract: dict[str, Any], base_protocol: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    require(errors, contract.get("schema") == "poker-preflop-strategy-benchmark-contract/v1", "unsupported #108 benchmark contract schema")
    require(errors, contract.get("status") == "FROZEN_BEFORE_CANDIDATE_RESULTS", "#108 benchmark contract must be frozen before candidate results")
    require(errors, contract.get("related_issue") == 108, "benchmark contract must remain tied to issue #108")
    require(errors, contract.get("extends_protocol") == "training/full_hand/FULL_HAND_EVALUATION_PROTOCOL_20260915.json", "benchmark contract must extend the frozen #99 full-hand protocol")
    require(errors, "never edit" in str(contract.get("change_policy", "")).lower(), "contract change policy must forbid post-result edits")

    population_id = nested(contract, "population", "population_id")
    require(errors, population_id == nested(base_protocol, "scope", "population_id"), "#108 population must match the frozen full-hand protocol")
    require(errors, nested(contract, "population", "cross_population_generalization_forbidden") is True, "cross-population generalization must be forbidden")

    dependencies = contract.get("dependencies") or {}
    require(errors, dependencies.get("full_hand_arena_issue") == 105, "#108 full-hand dependency must remain #105")
    require(errors, dependencies.get("hero_candidate_issue") == 107, "#108 Hero candidate dependency must remain #107")
    require(errors, dependencies.get("must_be_complete_before_promotion_eligible_execution") is True, "#105/#107 must complete before promotion-eligible execution")
    require(errors, dependencies.get("partial_or_pilot_execution_status") == "BLOCKED", "partial dependency state must be BLOCKED")

    reference = contract.get("reference_policy") or {}
    require(errors, reference.get("name") == "promoted_engine_v83", "incumbent identity must remain promoted engine v83")
    require(errors, reference.get("engine_release_artifact") == "user/releases/poker_range_equity_offline_multiway_v83.html", "incumbent artifact path drifted")
    preflop_rule = str(reference.get("preflop_rule", "")).lower()
    require(errors, "blocked" in preflop_rule and "do not drop" in preflop_rule and "fabricate" in preflop_rule, "incumbent preflop fallback must fail closed rather than drop/fabricate scenarios")
    require(errors, reference.get("identity_must_be_frozen_in_run_manifest") is True, "incumbent identity must be frozen in each run manifest")

    candidate = contract.get("candidate_policy") or {}
    require(errors, candidate.get("source_issue") == 107, "candidate source must remain issue #107")
    require(errors, candidate.get("decision_contract") == "poker-preflop-decision/v1", "candidate must preserve the canonical preflop decision contract")
    require(errors, candidate.get("immutable_artifact_sha256_required") is True, "candidate artifact hash must be mandatory")
    require(errors, candidate.get("must_be_frozen_before_validation_rollout") is True, "candidate must be frozen before VALIDATION")
    require(errors, candidate.get("same_cycle_mutation_after_validation_starts_forbidden") is True, "same-cycle candidate mutation must be forbidden")

    scenarios = contract.get("scenarios") or {}
    base_budgets = base_protocol.get("budgets") or {}
    require(errors, scenarios.get("source_issue") == 105, "paired scenario source must remain issue #105")
    require(errors, scenarios.get("scenario_manifest_required") is True and scenarios.get("scenario_manifest_sha256_required") is True, "scenario manifest identity must be mandatory")
    require(errors, scenarios.get("validation_base_hands") == base_budgets.get("promotion_validation_hands"), "VALIDATION hand budget must inherit the frozen full-hand protocol")
    require(errors, scenarios.get("test_base_hands") == base_budgets.get("promotion_test_hands"), "TEST hand budget must inherit the frozen full-hand protocol")
    require(errors, scenarios.get("rollouts_per_base_hand") == base_budgets.get("full_hand_rollouts_per_base_hand"), "rollout budget must inherit the frozen full-hand protocol")
    require(errors, scenarios.get("paired_across_hero_policies") is True, "Hero policies must use paired scenarios")
    paired = set(scenarios.get("paired_fields") or [])
    for field in ("hand_id", "hole_cards_and_deck", "starting_stacks", "opponent_profiles", "opponent_random_streams"):
        require(errors, field in paired, f"paired scenario identity must include {field}")
    streams = list(scenarios.get("rng_streams_must_be_separate") or [])
    require(errors, len(streams) >= 3 and len(streams) == len(set(streams)), "deck/opponent/Hero Monte-Carlo RNG streams must be distinct")
    coverage = set(scenarios.get("required_terminal_coverage") or [])
    for terminal in ("preflop_fold", "uncontested_pot", "limped_multiway", "three_bet_or_higher", "preflop_all_in", "postflop_showdown"):
        require(errors, terminal in coverage, f"full-hand coverage must include {terminal}")

    sensitivity = contract.get("environment_sensitivity") or {}
    roles = list(sensitivity.get("required_roles") or [])
    minimum_envs = int(sensitivity.get("minimum_environments") or 0)
    require(errors, minimum_envs >= 3, "strategy benchmark requires nominal plus at least two plausible Model B environments")
    require(errors, len(roles) >= minimum_envs and len(roles) == len(set(roles)), "Model B environment roles must be unique and satisfy the minimum")
    require(errors, "nominal" in roles, "Model B sensitivity must include a nominal environment")
    require(errors, sensitivity.get("each_environment_requires_model_b_artifact_sha256") is True, "every Model B environment must be content-addressed")
    require(errors, sensitivity.get("environment_identities_frozen_before_validation") is True, "Model B environments must be frozen before VALIDATION")
    require(errors, sensitivity.get("same_paired_scenarios_in_every_environment") is True, "environment sensitivity must reuse the paired scenarios")
    require(errors, sensitivity.get("automatic_promotion_requires_gate_pass_in_every_predeclared_environment") is True, "automatic promotion must not rely on one Model B environment")

    statistics = contract.get("statistics") or {}
    require(errors, statistics.get("primary_metric") == "bb_per_100_full_hands", "primary strategy metric must be full-hand BB/100")
    require(errors, statistics.get("paired_delta") == "candidate_minus_incumbent", "paired delta direction must be candidate-minus-incumbent")
    require(errors, _equals_float(statistics.get("confidence_level"), 0.95), "confidence level must remain 95%")
    require(errors, statistics.get("cluster_unit") == "hand_id", "uncertainty must cluster by independent hand_id")
    require(errors, statistics.get("repeated_rollouts_clustered_by") == "hand_id", "repeat rollouts must be clustered by hand_id")
    require(errors, int(statistics.get("bootstrap_samples") or 0) >= 1000, "paired bootstrap budget is too small")
    require(errors, statistics.get("paired_comparison_required") is True, "paired comparison must be mandatory")
    require(errors, statistics.get("point_estimate_alone_never_authorizes_promotion") is True, "point estimates alone must never authorize promotion")

    validation = contract.get("validation_selection") or {}
    require(errors, validation.get("split") == "VALIDATION", "candidate selection must use VALIDATION")
    require(errors, validation.get("test_data_visible") is False, "TEST must remain invisible during candidate selection")
    require(errors, _equals_float(validation.get("required_ci95_lower_bound_bb_per_100"), 0.0), "VALIDATION CI lower-bound gate must remain >= 0")
    require(errors, validation.get("minimum_environment_gate_rule") == "PASS_ALL_PREDECLARED_ENVIRONMENTS", "VALIDATION must pass every predeclared Model B environment")
    require(errors, validation.get("if_no_candidate_passes") == "RETAIN_BASELINE", "failed/inconclusive VALIDATION must retain baseline")
    require(errors, validation.get("freeze_at_most_one_finalist") is True, "VALIDATION may freeze at most one finalist")

    test = contract.get("test_confirmation") or {}
    require(errors, test.get("split") == "TEST", "final confirmation split must be TEST")
    require(errors, test.get("authorized_only_for_frozen_validation_finalist") is True, "TEST requires a frozen VALIDATION finalist")
    require(errors, test.get("test_may_select_alternative") is False, "TEST must not select an alternative")
    require(errors, test.get("test_may_retune_candidate") is False and test.get("test_may_change_thresholds") is False, "TEST must not retune candidate or thresholds")
    require(errors, _equals_float(test.get("required_ci95_lower_bound_bb_per_100"), 0.0), "TEST CI lower-bound gate must remain >= 0")
    require(errors, test.get("minimum_environment_gate_rule") == "PASS_ALL_PREDECLARED_ENVIRONMENTS", "TEST must pass every predeclared Model B environment")
    require(errors, test.get("failure_or_inconclusive_outcome") == "RETAIN_BASELINE", "failed/inconclusive TEST must retain baseline")
    require(errors, test.get("consumption_must_be_recorded_in") == "training/full_hand/TEST_HOLDOUT_LEDGER.json", "TEST consumption must use the protected ledger")

    breakdowns = set(contract.get("required_breakdowns") or [])
    for item in ("position", "preflop_family", "limper_count", "caller_count", "players_to_flop", "stack_depth_bucket", "all_in_preflop", "won_without_flop", "jam_frequency", "side_pot_frequency", "out_of_support_decision_rate"):
        require(errors, item in breakdowns, f"benchmark report must include {item}")

    manifest_fields = set(nested(contract, "run_manifest_requirements", "required_before_any_promotion_eligible_rollout") or [])
    for field in ("code_commit_sha", "dataset_population_fingerprint_sha256", "scenario_manifest_sha256", "incumbent_artifact_sha256", "candidate_id", "candidate_artifact_sha256", "candidate_source_commit_sha", "model_b_environments_with_artifact_sha256", "master_seed", "rollouts_per_base_hand", "bootstrap_samples", "validation_thresholds", "test_thresholds"):
        require(errors, field in manifest_fields, f"run manifest must freeze {field}")
    require(errors, nested(contract, "run_manifest_requirements", "missing_required_identity_status") == "BLOCKED", "missing run identity must fail closed as BLOCKED")

    return {
        "schema": "poker-preflop-strategy-benchmark-contract-validation/v1",
        "contract_version": contract.get("contract_version"),
        "population_id": population_id,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }


def validate_run_manifest(contract: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    require(errors, manifest.get("schema") == "poker-preflop-strategy-benchmark-run/v1", "unsupported #108 run manifest schema")
    require(errors, manifest.get("contract_version") == contract.get("contract_version"), "run manifest contract version mismatch")
    phase = str(manifest.get("phase") or "").upper()
    require(errors, phase in {"VALIDATION", "TEST"}, "run phase must be VALIDATION or TEST")
    require(errors, manifest.get("results_inspected") is False, "run identities must be frozen before results are inspected")

    identities = manifest.get("identities") or {}
    require(errors, _valid_sha(identities.get("code_commit_sha"), HEX40), "run must freeze a 40-hex code commit SHA")
    require(errors, _valid_sha(identities.get("dataset_population_fingerprint_sha256"), HEX64), "run must freeze the population fingerprint")
    require(errors, _valid_sha(identities.get("scenario_manifest_sha256"), HEX64), "run must freeze the scenario manifest SHA-256")
    require(errors, _valid_sha(identities.get("incumbent_artifact_sha256"), HEX64), "run must freeze the incumbent artifact SHA-256")
    require(errors, bool(identities.get("candidate_id")), "run must freeze candidate_id")
    require(errors, _valid_sha(identities.get("candidate_artifact_sha256"), HEX64), "run must freeze the candidate artifact SHA-256")
    require(errors, _valid_sha(identities.get("candidate_source_commit_sha"), HEX40), "run must freeze the candidate source commit SHA")

    environments = identities.get("model_b_environments_with_artifact_sha256") or []
    required_roles = set(nested(contract, "environment_sensitivity", "required_roles") or [])
    minimum = int(nested(contract, "environment_sensitivity", "minimum_environments") or 0)
    roles = [str(row.get("role")) for row in environments if isinstance(row, dict)]
    require(errors, len(environments) >= minimum, "run must freeze all required Model B sensitivity environments")
    require(errors, len(roles) == len(set(roles)), "Model B environment roles must be unique")
    require(errors, required_roles.issubset(set(roles)), "run is missing a predeclared Model B environment role")
    for row in environments:
        require(errors, isinstance(row, dict) and bool(row.get("environment_id")), "each Model B environment needs an environment_id")
        require(errors, isinstance(row, dict) and _valid_sha(row.get("artifact_sha256"), HEX64), "each Model B environment needs a SHA-256 artifact identity")

    budgets = manifest.get("budgets") or {}
    require(errors, isinstance(budgets.get("master_seed"), int), "run must freeze an integer master_seed")
    require(errors, budgets.get("rollouts_per_base_hand") == nested(contract, "scenarios", "rollouts_per_base_hand"), "run rollout budget drifted from contract")
    require(errors, budgets.get("bootstrap_samples") == nested(contract, "statistics", "bootstrap_samples"), "run bootstrap budget drifted from contract")

    thresholds = manifest.get("thresholds") or {}
    expected_validation = nested(contract, "validation_selection", "required_ci95_lower_bound_bb_per_100")
    expected_test = nested(contract, "test_confirmation", "required_ci95_lower_bound_bb_per_100")
    require(errors, thresholds.get("validation_ci95_lower_bb_per_100") == expected_validation, "run VALIDATION threshold drifted from contract")
    require(errors, thresholds.get("test_ci95_lower_bb_per_100") == expected_test, "run TEST threshold drifted from contract")
    require(errors, thresholds.get("environment_gate_rule") == "PASS_ALL_PREDECLARED_ENVIRONMENTS", "run must preserve the all-environment gate")

    scenario = manifest.get("scenario_policy") or {}
    require(errors, scenario.get("paired_across_hero_policies") is True, "run scenarios must remain paired across Hero policies")
    require(errors, scenario.get("same_scenarios_across_model_b_environments") is True, "run must reuse paired scenarios across Model B environments")
    require(errors, set(scenario.get("rng_streams") or []) == set(nested(contract, "scenarios", "rng_streams_must_be_separate") or []), "run RNG stream partition drifted from contract")

    if phase == "VALIDATION":
        require(errors, manifest.get("test_data_read") is False, "VALIDATION manifest must state that TEST was not read")
        require(errors, not manifest.get("validation_selection"), "VALIDATION run must not contain a prior TEST/finalist selection object")
    elif phase == "TEST":
        selection = manifest.get("validation_selection") or {}
        require(errors, selection.get("outcome") == "FREEZE_FINALIST", "TEST requires a frozen VALIDATION finalist")
        require(errors, selection.get("frozen_finalist") == identities.get("candidate_id"), "TEST candidate must equal the frozen VALIDATION finalist")
        require(errors, selection.get("test_used_for_selection") is False, "VALIDATION selection must not have used TEST")
        require(errors, bool(manifest.get("test_holdout_generation_id")), "TEST run must identify the protected holdout generation")

    return {
        "schema": "poker-preflop-strategy-benchmark-run-validation/v1",
        "contract_version": contract.get("contract_version"),
        "phase": phase or None,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "candidate_id": identities.get("candidate_id"),
        "model_b_environment_roles": roles,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--base-protocol", default=str(DEFAULT_BASE_PROTOCOL))
    parser.add_argument("--run-manifest", default="")
    parser.add_argument("--out", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = load_json(Path(args.contract))
    base = load_json(Path(args.base_protocol))
    report = validate_contract(contract, base)
    if report["status"] == "PASS" and args.run_manifest:
        report = validate_run_manifest(contract, load_json(Path(args.run_manifest)))
    text = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    print(text, end="")
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
