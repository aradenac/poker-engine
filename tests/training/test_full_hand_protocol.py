#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.validate_full_hand_protocol import validate  # noqa: E402

PROTOCOL = json.loads((ROOT / "training/full_hand/FULL_HAND_EVALUATION_PROTOCOL_20260915.json").read_text(encoding="utf-8"))
LEDGER = json.loads((ROOT / "training/full_hand/TEST_HOLDOUT_LEDGER.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((ROOT / "training/populations/registry.json").read_text(encoding="utf-8"))
CERTIFICATION = json.loads((ROOT / "training/datasets/NLHE_100-200/population_certification.json").read_text(encoding="utf-8"))
PROMOTION_CONTRACT = json.loads((ROOT / "training/PROMOTION_GATE_CONTRACT.json").read_text(encoding="utf-8"))


def report(protocol=None, ledger=None, registry=None, certification=None, promotion_contract=None) -> dict:
    return validate(
        protocol or PROTOCOL,
        ledger or LEDGER,
        registry or REGISTRY,
        certification or CERTIFICATION,
        promotion_contract or PROMOTION_CONTRACT,
    )


def assert_fails_with(result: dict, fragment: str) -> None:
    assert result["status"] == "FAIL", result
    assert any(fragment in error for error in result["errors"]), result


def test_frozen_protocol_matches_certified_repository_state() -> None:
    result = report()
    assert result["status"] == "PASS", result
    assert result["certified_split_counts"] == {"TRAIN": 19016, "VALIDATION": 2324, "TEST": 2449}
    assert result["protected_test_generation"] == "zoom_100-200_play_20260915_g1"


def test_population_fingerprint_drift_is_rejected() -> None:
    protocol = copy.deepcopy(PROTOCOL)
    protocol["scope"]["admissible_hand_ids_sha256"] = "0" * 64
    assert_fails_with(report(protocol=protocol), "fingerprint")


def test_holdout_budget_must_cover_full_certified_split() -> None:
    protocol = copy.deepcopy(PROTOCOL)
    protocol["budgets"]["promotion_validation_hands"] = 96
    assert_fails_with(report(protocol=protocol), "full certified holdout")


def test_model_b_guardrails_cannot_drift_from_unified_gate() -> None:
    protocol = copy.deepcopy(PROTOCOL)
    protocol["model_b"]["absolute_guardrails"]["max_action_ece"] = 0.10
    assert_fails_with(report(protocol=protocol), "guardrails")


def test_test_generation_cannot_be_marked_consumed_without_replacement() -> None:
    ledger = copy.deepcopy(LEDGER)
    generation = ledger["generations"][0]
    generation["status"] = "CONSUMED"
    generation["consumed_by_cycle"] = "synthetic-cycle"
    generation["consumed_by_frozen_finalist"] = "candidate-x"
    assert_fails_with(report(ledger=ledger), "UNCONSUMED")


def test_strategy_requires_model_b_sensitivity_not_single_environment() -> None:
    protocol = copy.deepcopy(PROTOCOL)
    protocol["hero_strategy"]["environment_sensitivity"]["minimum_total_plausible_model_b_environments"] = 1
    assert_fails_with(report(protocol=protocol), "Model B variants")


def test_test_cannot_select_alternative_candidate() -> None:
    protocol = copy.deepcopy(PROTOCOL)
    protocol["hero_strategy"]["test_confirmation_rule"]["test_may_select_alternative"] = True
    assert_fails_with(report(protocol=protocol), "alternate Hero candidate")


if __name__ == "__main__":
    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"full-hand protocol tests: {len(tests)} passed")
