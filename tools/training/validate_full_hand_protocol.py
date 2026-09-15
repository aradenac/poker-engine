#!/usr/bin/env python3
"""Validate the frozen full-hand/preflop evaluation protocol against repository state.

This validator intentionally checks protocol *definition*, not experiment results.  It
prevents a later candidate run from silently changing the target population, split
budget, statistical selection rule, Model-B guardrails or protected TEST generation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL = ROOT / "training/full_hand/FULL_HAND_EVALUATION_PROTOCOL_20260915.json"
DEFAULT_LEDGER = ROOT / "training/full_hand/TEST_HOLDOUT_LEDGER.json"
DEFAULT_REGISTRY = ROOT / "training/populations/registry.json"
DEFAULT_CERTIFICATION = ROOT / "training/datasets/NLHE_100-200/population_certification.json"
DEFAULT_PROMOTION_CONTRACT = ROOT / "training/PROMOTION_GATE_CONTRACT.json"


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


def validate(
    protocol: dict[str, Any],
    ledger: dict[str, Any],
    registry: dict[str, Any],
    certification: dict[str, Any],
    promotion_contract: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []

    require(errors, protocol.get("schema") == "poker-full-hand-evaluation-protocol/v1", "unsupported protocol schema")
    require(errors, protocol.get("status") == "FROZEN_BEFORE_EXPERIMENT", "protocol must be frozen before experiment")
    require(errors, protocol.get("related_issue") == 99, "protocol must remain tied to issue #99")
    require(errors, bool(protocol.get("created_from_main_commit")), "protocol must record its pre-experiment main commit")

    scope = protocol.get("scope") or {}
    population_id = scope.get("population_id")
    populations = registry.get("populations") or {}
    population = populations.get(population_id) if population_id else None
    require(errors, population is not None, "protocol population_id must exist in population registry")
    if isinstance(population, dict):
        identity = population.get("identity") or {}
        require(errors, identity.get("platform") == "PokerStars", "target platform must remain PokerStars")
        require(errors, identity.get("variant") == "NLHE", "target variant must remain NLHE")
        require(errors, identity.get("stake") == "100/200", "target stake must remain 100/200")
        require(errors, identity.get("money") == "play", "target money kind must remain play")
        require(errors, identity.get("format") == "ZOOM", "target format must remain ZOOM")
        require(errors, identity.get("max_seats") == 6, "target table size must remain 6-max")
        require(errors, nested(population, "data", "source_certification") == scope.get("population_certification"), "protocol certification path must match population registry")

    admissible = nested(certification, "status", "ADMISSIBLE") or {}
    cert_fingerprint = admissible.get("fingerprint_sha256")
    cert_count = admissible.get("unique_hands")
    cert_splits = admissible.get("split_counts") or {}
    require(errors, scope.get("admissible_hand_ids_sha256") == cert_fingerprint, "protocol population fingerprint must match certification")
    require(errors, scope.get("certified_unique_hands") == cert_count, "protocol unique-hand count must match certification")
    require(errors, scope.get("split_counts") == cert_splits, "protocol TRAIN/VALIDATION/TEST counts must match certification")
    require(errors, sum(int(v) for v in cert_splits.values()) == int(cert_count or 0), "certified split counts must sum to admissible unique hands")

    holdout = protocol.get("holdout_policy") or {}
    require(errors, holdout.get("split_disjointness_required") is True, "split disjointness must be mandatory")
    require(errors, holdout.get("future_information_forbidden") is True, "future information must be forbidden")
    require(errors, holdout.get("test_consumption_ledger") == "training/full_hand/TEST_HOLDOUT_LEDGER.json", "protocol must point at the protected TEST ledger")
    require(errors, "frozen" in str(holdout.get("TEST", "")).lower(), "TEST rule must restrict use to a frozen finalist")

    budgets = protocol.get("budgets") or {}
    require(errors, budgets.get("promotion_validation_hands") == "ALL_CERTIFIED_VALIDATION_HANDS", "promotion VALIDATION must use the full certified holdout")
    require(errors, budgets.get("promotion_test_hands") == "ALL_CERTIFIED_TEST_HANDS", "promotion TEST must use the full certified holdout")
    require(errors, budgets.get("current_validation_hand_count") == cert_splits.get("VALIDATION"), "VALIDATION budget must match certification")
    require(errors, budgets.get("current_test_hand_count") == cert_splits.get("TEST"), "TEST budget must match certification")
    require(errors, int(budgets.get("full_hand_rollouts_per_base_hand", 0)) >= 1, "full-hand rollout budget must be positive")
    require(errors, int(budgets.get("analyser_trials_per_decision", 0)) >= 1, "analyser trial budget must be positive")
    require(errors, "never promotion-eligible" in str(budgets.get("reduced_budget_runs", "")).lower(), "reduced-budget runs must be barred from promotion")

    statistics = protocol.get("statistics") or {}
    require(errors, float(statistics.get("confidence_level", 0.0)) == 0.95, "confidence level must remain 95%")
    require(errors, statistics.get("strategy_cluster_unit") == "hand_id", "strategy uncertainty must cluster by independent hand_id")
    require(errors, statistics.get("paired_comparisons_required") is True, "strategy comparisons must be paired")
    require(errors, statistics.get("selection_reads_test") is False, "candidate selection must never read TEST")

    for street in ("preflop", "postflop"):
        model = nested(protocol, "model_a", street) or {}
        diagnostics = set(model.get("required_diagnostics") or [])
        require(errors, model.get("primary_metric") == "multiclass_log_loss", f"Model A {street} primary metric must remain multiclass_log_loss")
        require(errors, "95% CI upper bound <= 0" in str(model.get("promotion_rule", "")), f"Model A {street} promotion rule must require paired non-regression")
        require(errors, "expected_calibration_error" in diagnostics, f"Model A {street} must report calibration")
        require(errors, "support_count" in diagnostics, f"Model A {street} must report support")
        require(errors, model.get("runtime_parity_required") is True, f"Model A {street} runtime parity must be mandatory")

    protocol_b = protocol.get("model_b") or {}
    contract_b = promotion_contract.get("model_b") or {}
    require(errors, protocol_b.get("independent_from_model_a_required") is True, "Model B must remain independent from Model A")
    require(errors, protocol_b.get("selection_split") == "VALIDATION", "Model B selection must use VALIDATION")
    expected_pair = contract_b.get("candidate_vs_incumbent") or {}
    pair = protocol_b.get("paired_candidate_vs_incumbent") or {}
    require(errors, pair.get("action_log_loss_delta_ci95_upper_at_most") == expected_pair.get("action_log_loss_delta_candidate_minus_incumbent_ci95_upper_at_most"), "Model B action-log-loss threshold drifted from unified gate")
    require(errors, pair.get("range_log_loss_delta_ci95_upper_at_most") == expected_pair.get("range_log_loss_delta_candidate_minus_incumbent_ci95_upper_at_most"), "Model B range-log-loss threshold drifted from unified gate")
    require(errors, protocol_b.get("absolute_guardrails") == contract_b.get("absolute_guardrails"), "Model B absolute guardrails must reuse the unified promotion contract")

    strategy = protocol.get("hero_strategy") or {}
    require(errors, strategy.get("primary_metric") == "bb_per_100_full_hands", "Hero primary metric must be full-hand BB/100")
    require(errors, nested(strategy, "validation_selection_rule", "required_ci95_lower_bound_bb_per_100") == 0.0, "VALIDATION strategy CI lower bound must be >= 0")
    require(errors, nested(strategy, "test_confirmation_rule", "required_ci95_lower_bound_bb_per_100") == 0.0, "TEST strategy CI lower bound must be >= 0")
    require(errors, nested(strategy, "test_confirmation_rule", "test_may_select_alternative") is False, "TEST must not select an alternate Hero candidate")
    require(errors, nested(strategy, "test_confirmation_rule", "test_may_retune") is False, "TEST must not retune Hero strategy")
    breakdowns = set(strategy.get("required_breakdowns") or [])
    for required_breakdown in ("position", "preflop_family", "players_to_flop", "stack_depth_bucket"):
        require(errors, required_breakdown in breakdowns, f"Hero strategy must report {required_breakdown} breakdown")
    require(errors, int(nested(strategy, "environment_sensitivity", "minimum_total_plausible_model_b_environments") or 0) >= 3, "Hero promotion must be tested against nominal plus at least two plausible Model B variants")

    publication = protocol.get("publication") or {}
    require(errors, publication.get("inconclusive_is") == "RETAIN_BASELINE", "inconclusive evidence must retain the baseline")
    require(errors, publication.get("registry_update_requires_all_applicable_gates_pass") is True, "registry updates must require all applicable gates")
    require(errors, publication.get("rejected_candidate_must_be_persisted") is True, "rejected candidates must remain reproducible")

    require(errors, ledger.get("schema") == "poker-test-holdout-ledger/v1", "unsupported TEST ledger schema")
    require(errors, ledger.get("population_id") == population_id, "TEST ledger population must match protocol population")
    generations = ledger.get("generations") or []
    generation_ids = [g.get("generation_id") for g in generations if isinstance(g, dict)]
    require(errors, len(generation_ids) == len(set(generation_ids)), "TEST generation IDs must be unique")
    current = [g for g in generations if isinstance(g, dict) and g.get("status") == "UNCONSUMED"]
    require(errors, len(current) == 1, "exactly one current UNCONSUMED TEST generation is required before first full-hand experiment")
    if len(current) == 1:
        generation = current[0]
        require(errors, generation.get("source_population_fingerprint_sha256") == cert_fingerprint, "current TEST generation fingerprint must match certified population")
        require(errors, generation.get("split") == "TEST", "current protected generation must be TEST")
        require(errors, generation.get("unique_hands") == cert_splits.get("TEST"), "current TEST generation size must match certification")
        require(errors, generation.get("consumed_by_cycle") is None, "UNCONSUMED TEST generation cannot name a consuming cycle")
        require(errors, generation.get("consumed_by_frozen_finalist") is None, "UNCONSUMED TEST generation cannot name a finalist")

    return {
        "schema": "poker-full-hand-protocol-validation/v1",
        "protocol_version": protocol.get("protocol_version"),
        "population_id": population_id,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "certified_split_counts": cert_splits,
        "protected_test_generation": current[0].get("generation_id") if len(current) == 1 else None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--certification", default=str(DEFAULT_CERTIFICATION))
    parser.add_argument("--promotion-contract", default=str(DEFAULT_PROMOTION_CONTRACT))
    parser.add_argument("--out", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = validate(
        load_json(Path(args.protocol)),
        load_json(Path(args.ledger)),
        load_json(Path(args.registry)),
        load_json(Path(args.certification)),
        load_json(Path(args.promotion_contract)),
    )
    text = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    print(text, end="")
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
