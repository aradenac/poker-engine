#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.validate_preflop_strategy_benchmark import (  # noqa: E402
    validate_contract,
    validate_run_manifest,
)

CONTRACT = json.loads(
    (ROOT / "training/full_hand/PREFLOP_STRATEGY_BENCHMARK_CONTRACT_20260915.json").read_text(encoding="utf-8")
)
BASE = json.loads(
    (ROOT / "training/full_hand/FULL_HAND_EVALUATION_PROTOCOL_20260915.json").read_text(encoding="utf-8")
)


def assert_fails_with(result: dict, fragment: str) -> None:
    assert result["status"] == "FAIL", result
    assert any(fragment.lower() in error.lower() for error in result["errors"]), result


def valid_manifest(phase: str = "VALIDATION") -> dict:
    roles = CONTRACT["environment_sensitivity"]["required_roles"]
    manifest = {
        "schema": "poker-preflop-strategy-benchmark-run/v1",
        "contract_version": CONTRACT["contract_version"],
        "phase": phase,
        "results_inspected": False,
        "test_data_read": False,
        "identities": {
            "code_commit_sha": "a" * 40,
            "dataset_population_fingerprint_sha256": "b" * 64,
            "scenario_manifest_sha256": "c" * 64,
            "incumbent_artifact_sha256": "d" * 64,
            "candidate_id": "hero-preflop-candidate-synthetic",
            "candidate_artifact_sha256": "e" * 64,
            "candidate_source_commit_sha": "f" * 40,
            "model_b_environments_with_artifact_sha256": [
                {
                    "role": role,
                    "environment_id": f"model-b-{index}",
                    "artifact_sha256": (str(index + 1) * 64)[:64],
                }
                for index, role in enumerate(roles)
            ],
        },
        "budgets": {
            "master_seed": 20260915,
            "rollouts_per_base_hand": CONTRACT["scenarios"]["rollouts_per_base_hand"],
            "bootstrap_samples": CONTRACT["statistics"]["bootstrap_samples"],
        },
        "thresholds": {
            "validation_ci95_lower_bb_per_100": CONTRACT["validation_selection"]["required_ci95_lower_bound_bb_per_100"],
            "test_ci95_lower_bb_per_100": CONTRACT["test_confirmation"]["required_ci95_lower_bound_bb_per_100"],
            "environment_gate_rule": "PASS_ALL_PREDECLARED_ENVIRONMENTS",
        },
        "scenario_policy": {
            "paired_across_hero_policies": True,
            "same_scenarios_across_model_b_environments": True,
            "rng_streams": CONTRACT["scenarios"]["rng_streams_must_be_separate"],
        },
    }
    if phase == "TEST":
        manifest["test_data_read"] = True
        manifest["validation_selection"] = {
            "outcome": "FREEZE_FINALIST",
            "frozen_finalist": manifest["identities"]["candidate_id"],
            "test_used_for_selection": False,
        }
        manifest["test_holdout_generation_id"] = "zoom_100-200_play_20260915_g1"
    return manifest


def test_frozen_contract_is_valid_against_base_protocol() -> None:
    result = validate_contract(CONTRACT, BASE)
    assert result["status"] == "PASS", result
    assert result["population_id"] == "pokerstars_nlhe_100-200_zoom_play_6max_v1"


def test_incumbent_fallback_must_fail_closed() -> None:
    contract = copy.deepcopy(CONTRACT)
    contract["reference_policy"]["preflop_rule"] = "Use nearest available action."
    assert_fails_with(validate_contract(contract, BASE), "fallback")


def test_validation_must_not_see_test() -> None:
    contract = copy.deepcopy(CONTRACT)
    contract["validation_selection"]["test_data_visible"] = True
    assert_fails_with(validate_contract(contract, BASE), "TEST must remain invisible")


def test_model_b_sensitivity_requires_three_frozen_environments() -> None:
    contract = copy.deepcopy(CONTRACT)
    contract["environment_sensitivity"]["minimum_environments"] = 1
    assert_fails_with(validate_contract(contract, BASE), "at least two plausible Model B")


def test_promotion_eligible_validation_manifest_freezes_every_identity() -> None:
    result = validate_run_manifest(CONTRACT, valid_manifest())
    assert result["status"] == "PASS", result
    assert result["phase"] == "VALIDATION"
    assert set(result["model_b_environment_roles"]) == set(CONTRACT["environment_sensitivity"]["required_roles"])


def test_missing_candidate_artifact_hash_fails_closed() -> None:
    manifest = valid_manifest()
    manifest["identities"]["candidate_artifact_sha256"] = None
    assert_fails_with(validate_run_manifest(CONTRACT, manifest), "candidate artifact")


def test_validation_manifest_cannot_read_test_or_embed_finalist_selection() -> None:
    manifest = valid_manifest()
    manifest["test_data_read"] = True
    manifest["validation_selection"] = {"outcome": "FREEZE_FINALIST"}
    result = validate_run_manifest(CONTRACT, manifest)
    assert_fails_with(result, "TEST was not read")
    assert any("must not contain" in error for error in result["errors"]), result


def test_test_manifest_requires_exact_frozen_validation_finalist() -> None:
    manifest = valid_manifest("TEST")
    manifest["validation_selection"]["frozen_finalist"] = "other-candidate"
    assert_fails_with(validate_run_manifest(CONTRACT, manifest), "must equal")


def test_test_manifest_passes_only_for_frozen_finalist() -> None:
    result = validate_run_manifest(CONTRACT, valid_manifest("TEST"))
    assert result["status"] == "PASS", result
    assert result["phase"] == "TEST"


def test_environment_or_threshold_drift_is_rejected() -> None:
    manifest = valid_manifest()
    manifest["identities"]["model_b_environments_with_artifact_sha256"].pop()
    manifest["thresholds"]["validation_ci95_lower_bb_per_100"] = -1.0
    result = validate_run_manifest(CONTRACT, manifest)
    assert_fails_with(result, "Model B sensitivity environments")
    assert any("threshold drifted" in error for error in result["errors"]), result


if __name__ == "__main__":
    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"preflop strategy benchmark contract tests: {len(tests)} passed")
