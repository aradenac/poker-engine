#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.validate_preflop_strategy_benchmark_v2 import (  # noqa: E402
    validate_contract,
    validate_run_manifest,
)

CONTRACT = json.loads((ROOT / "training/full_hand/PREFLOP_STRATEGY_BENCHMARK_CONTRACT_20260917.json").read_text())
BASE = json.loads((ROOT / "training/full_hand/FULL_HAND_EVALUATION_PROTOCOL_20260915.json").read_text())
REFERENCE = json.loads((ROOT / "training/full_hand/HERO_REFERENCE_POLICY_20260917.json").read_text())
SENSITIVITY = json.loads((ROOT / "training/full_hand/MODEL_B_SENSITIVITY_ENVIRONMENTS_20260917.json").read_text())


def assert_fails(result, fragment):
    assert result["status"] == "FAIL", result
    assert any(fragment.lower() in item.lower() for item in result["errors"]), result


def valid_manifest(phase="VALIDATION"):
    ids = [row["environment_id"] for row in SENSITIVITY["environments"]]
    out = {
        "schema": "poker-preflop-strategy-benchmark-run/v2",
        "contract_version": CONTRACT["contract_version"],
        "phase": phase,
        "results_inspected": False,
        "test_data_read": False,
        "identities": {
            "code_commit_sha": "a" * 40,
            "dataset_population_fingerprint_sha256": CONTRACT["population"]["population_fingerprint_sha256"],
            "scenario_manifest_sha256": "b" * 64,
            "reference_descriptor_sha256": "c" * 64,
            "candidate_id": "hero-preflop-candidate-fixture",
            "candidate_artifact_sha256": "d" * 64,
            "candidate_source_commit_sha": "e" * 40,
            "model_b_sensitivity_descriptor_sha256": "f" * 64,
            "model_b_base_artifact_sha256": CONTRACT["environment_sensitivity"]["base_artifact_sha256"],
            "model_b_environment_ids": ids,
        },
        "budgets": {
            "master_seed": 20260912,
            "rollouts_per_base_hand": CONTRACT["scenarios"]["rollouts_per_base_hand"],
            "bootstrap_samples": CONTRACT["statistics"]["bootstrap_samples"],
        },
        "thresholds": {
            "validation_ci95_lower_bb_per_100": CONTRACT["validation_selection"]["required_ci95_lower_bound_bb_per_100"],
            "test_ci95_lower_bb_per_100": CONTRACT["test_confirmation"]["required_ci95_lower_bound_bb_per_100"],
            "environment_gate_rule": "PASS_ALL_PREDECLARED_ENVIRONMENTS",
        },
    }
    if phase == "TEST":
        out["test_data_read"] = True
        out["validation_selection"] = {
            "outcome": "FREEZE_FINALIST",
            "frozen_finalist": out["identities"]["candidate_id"],
            "test_used_for_selection": False,
        }
        out["test_holdout_generation_id"] = "zoom_100-200_play-next-temporal-holdout"
    return out


def test_v2_contract_and_descriptors_pass() -> None:
    result = validate_contract(CONTRACT, BASE, REFERENCE, SENSITIVITY)
    assert result["status"] == "PASS", result
    assert set(result["model_b_environment_ids"]) == {
        "model-b-public-reference-nominal-v1",
        "model-b-public-reference-lower-aggression-v1",
        "model-b-public-reference-higher-aggression-v1",
    }


def test_v2_never_rebrands_reference_as_v83_incumbent() -> None:
    contract = copy.deepcopy(CONTRACT)
    contract["reference_policy"]["v83_autonomous_preflop_claim"] = True
    assert_fails(validate_contract(contract, BASE, REFERENCE, SENSITIVITY), "v83")


def test_candidate_nearest_context_fallback_is_forbidden() -> None:
    contract = copy.deepcopy(CONTRACT)
    contract["candidate_policy"]["nearest_context_substitution_forbidden"] = False
    assert_fails(validate_contract(contract, BASE, REFERENCE, SENSITIVITY), "nearest-context")


def test_sensitivity_variants_cannot_be_dropped() -> None:
    sensitivity = copy.deepcopy(SENSITIVITY)
    sensitivity["environments"].pop()
    assert_fails(validate_contract(CONTRACT, BASE, REFERENCE, sensitivity), "three frozen")


def test_validation_manifest_passes_without_test_access() -> None:
    result = validate_run_manifest(CONTRACT, SENSITIVITY, valid_manifest())
    assert result["status"] == "PASS", result


def test_validation_manifest_cannot_read_test() -> None:
    manifest = valid_manifest()
    manifest["test_data_read"] = True
    assert_fails(validate_run_manifest(CONTRACT, SENSITIVITY, manifest), "TEST was not read")


def test_run_environment_identity_order_is_frozen() -> None:
    manifest = valid_manifest()
    manifest["identities"]["model_b_environment_ids"].reverse()
    assert_fails(validate_run_manifest(CONTRACT, SENSITIVITY, manifest), "identities/order")


def test_test_requires_exact_validation_finalist() -> None:
    manifest = valid_manifest("TEST")
    manifest["validation_selection"]["frozen_finalist"] = "other"
    assert_fails(validate_run_manifest(CONTRACT, SENSITIVITY, manifest), "must equal")


def test_test_manifest_passes_only_when_finalist_is_frozen() -> None:
    result = validate_run_manifest(CONTRACT, SENSITIVITY, valid_manifest("TEST"))
    assert result["status"] == "PASS", result


def main():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"preflop strategy benchmark v2 tests: {len(tests)} passed")


if __name__ == "__main__":
    main()
