#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from tools.training.bridge_paired_ev_to_hero_generation import (
    EXACT_ZERO_ROLLOUT,
    MEASURED_COMPATIBLE,
    REQUEST_SCHEMA,
    RESULT_SCHEMA,
    BridgeError,
    bridge_request,
)
from tools.training.validate_hero_preflop_generation import (
    CANONICAL_HAND_CLASSES,
    canonical_json_bytes,
    sha256_path,
    validate_generation,
)

PLAN_PATH = ROOT / "analysis/hero_preflop_generation_plan.json"
SCHEMA_PATH = ROOT / "contracts/training/paired-ev-generation-bridge.schema.json"
MEASURED_FIXTURE = ROOT / "tests/fixtures/paired_ev_generation_bridge/valid_measured.json"
EXACT_FIXTURE = ROOT / "tests/fixtures/paired_ev_generation_bridge/zero_rollout_exact.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


PLAN = load(PLAN_PATH)
PLAN_SHA = sha256_path(PLAN_PATH)


def bridged(request: dict) -> dict:
    return bridge_request(request, PLAN, plan_sha256=PLAN_SHA)


def expect_error(request: dict, code: str) -> None:
    try:
        bridged(request)
    except BridgeError as exc:
        assert exc.code == code, (exc.code, exc.message)
    else:
        raise AssertionError(f"expected {code}")


def measured_request() -> dict:
    return load(MEASURED_FIXTURE)


def exact_request() -> dict:
    return load(EXACT_FIXTURE)


def test_versioned_contract_and_measured_cell_mapping() -> None:
    schema = load(SCHEMA_PATH)
    defs = schema["$defs"]
    assert defs["request"]["properties"]["schema"]["const"] == REQUEST_SCHEMA
    assert defs["result"]["properties"]["schema"]["const"] == RESULT_SCHEMA

    result = bridged(measured_request())
    assert result["schema"] == RESULT_SCHEMA
    assert result["bridge_state"] == MEASURED_COMPATIBLE
    assert result["scientific_effect"] == "NONE_INTEGRATION_CONTRACT_ONLY"
    assert result["exact_lookup"] == "EXACT_CONTEXT_ONLY"
    assert result["nearest_context_allowed"] is False
    cell = result["strategy_cell"]
    assert cell["action"] == {"status": "MEASURED", "value": "FOLD"}
    assert cell["sizing"] == {"status": "MEASURED", "kind": "NONE", "value": None, "unit": None}
    assert cell["ev"]["estimate_bb"] == 0.125
    assert cell["ev"]["uncertainty"] == {
        "method": "PAIRED_CRN_CI95",
        "std_error_bb": 0.01,
        "ci95_low_bb": 0.1054,
        "ci95_high_bb": 0.1446,
    }
    assert cell["rollout"] == {"status": "MEASURED", "sample_count": 8, "world_count": 8}


def test_alternative_id_is_distinct_from_artifact_candidate_id() -> None:
    request = measured_request()
    result = bridged(request)
    assert result["alternative_id"] == "ALT_FOLD_SYNTHETIC"
    assert result["candidate_id"] == "SYNTHETIC_ARTIFACT_CANDIDATE_V1"
    assert result["alternative_id"] != result["candidate_id"]

    collision = measured_request()
    old = collision["paired_result"]["selected_id"]
    candidate = collision["artifact_identity"]["candidate_id"]
    collision["paired_result"]["selected_id"] = candidate
    collision["paired_result"]["alternatives"][candidate] = collision["paired_result"]["alternatives"].pop(old)
    collision["alternatives"][candidate] = collision["alternatives"].pop(old)
    expect_error(collision, "IDENTITY_NAMESPACE_COLLISION")


def test_exact_context_and_hand_class_only() -> None:
    result = bridged(measured_request())
    cell = result["strategy_cell"]
    assert cell["context_id"] == measured_request()["decision_binding"]["context_id"]
    assert cell["hand_class"] == "AA"
    assert cell["support"]["source_plan_context_id"] == cell["context_id"]

    wrong_context = measured_request()
    wrong_context["decision_binding"]["context_id"] += ":nearest"
    expect_error(wrong_context, "EXACT_CONTEXT_UNAVAILABLE")

    wrong_hand = measured_request()
    wrong_hand["decision_binding"]["hand_class"] = "AXs"
    expect_error(wrong_hand, "INVALID_HAND_CLASS")

    wrong_decision = measured_request()
    wrong_decision["decision_binding"]["decision_id"] += ":other"
    expect_error(wrong_decision, "DECISION_ID_MISMATCH")


def test_non_representable_action_or_sizing_fails_closed() -> None:
    bad = measured_request()
    bad["alternatives"]["ALT_FOLD_SYNTHETIC"] = {
        "action": "FOLD",
        "sizing": {"kind": "FIXED_BB", "value": 2.5, "unit": "BB"},
    }
    expect_error(bad, "UNREPRESENTABLE_SIZING")

    bad = measured_request()
    bad["alternatives"]["ALT_FOLD_SYNTHETIC"] = {
        "action": "RAISE",
        "sizing": {"kind": "NONE", "value": None, "unit": None},
    }
    expect_error(bad, "UNREPRESENTABLE_SIZING")

    bad = measured_request()
    bad["alternatives"]["ALT_FOLD_SYNTHETIC"] = {
        "action": "JAM",
        "sizing": {"kind": "ALL_IN", "value": None, "unit": None},
    }
    expect_error(bad, "UNREPRESENTABLE_ACTION")


def test_zero_rollout_exact_value_is_explicit_and_never_measured() -> None:
    result = bridged(exact_request())
    assert result["bridge_state"] == EXACT_ZERO_ROLLOUT
    assert result["evidence"]["rollouts"] == 0
    assert result["evidence"]["ev_bb"] == 0.125
    assert result["strategy_cell"] is None


def test_rollout_and_uncertainty_accounting_fail_closed() -> None:
    bad = measured_request()
    alt = bad["paired_result"]["alternatives"]["ALT_FOLD_SYNTHETIC"]
    alt["rollouts"] = 7
    expect_error(bad, "ROLLOUT_ACCOUNTING_INVALID")

    bad = measured_request()
    bad["paired_result"]["search"]["confidence_z"] = 1.645
    expect_error(bad, "UNSUPPORTED_CONFIDENCE_LEVEL")

    bad = measured_request()
    bad["paired_result"]["alternatives"]["ALT_FOLD_SYNTHETIC"]["ci_lower_bb"] = 0.2
    expect_error(bad, "UNCERTAINTY_INVALID")


def test_identity_is_preserved_and_source_plan_is_content_bound() -> None:
    request = measured_request()
    result = bridged(request)
    identity = request["artifact_identity"]
    for key in (
        "population_id",
        "generation_id",
        "candidate_id",
        "source_plan_sha256",
        "source_train_audit_sha256",
        "generator_version",
        "code_sha",
        "environment_identity_slot",
        "generation_parameters_slot",
    ):
        assert result[key] == identity[key]
    cell = result["strategy_cell"]
    assert cell["provenance"]["source_plan_sha256"] == identity["source_plan_sha256"]
    assert cell["provenance"]["source_train_audit_sha256"] == identity["source_train_audit_sha256"]
    assert cell["provenance"]["environment_identity_slot"] == identity["environment_identity_slot"]
    assert cell["provenance"]["generation_parameters_slot"] == identity["generation_parameters_slot"]
    assert cell["provenance"]["code_sha"] == identity["code_sha"]

    bad = measured_request()
    bad["artifact_identity"]["source_plan_sha256"] = "0" * 64
    expect_error(bad, "SOURCE_PLAN_HASH_MISMATCH")


def test_deterministic_output_and_hash() -> None:
    a = bridged(measured_request())
    b = bridged(measured_request())
    assert a == b
    assert canonical_json_bytes(a) == canonical_json_bytes(b)
    payload = copy.deepcopy(a)
    digest = payload.pop("output_sha256")
    import hashlib
    assert hashlib.sha256(canonical_json_bytes(payload)).hexdigest() == digest


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _make_measured_request(context_id: str, hand_class: str, identity: dict) -> dict:
    decision_id = f"{context_id}|{hand_class}"
    return {
        "schema": REQUEST_SCHEMA,
        "paired_result": {
            "schema": "paired-adaptive-preflop-ev/v1",
            "mode": "paired_fixed",
            "selected_id": "ALT_FOLD_SYNTHETIC_VALIDATOR",
            "alternatives": {
                "ALT_FOLD_SYNTHETIC_VALIDATOR": {
                    "ev_bb": 0.0,
                    "samples": 2,
                    "rollouts": 2,
                    "standard_error_bb": 0.0,
                    "ci_lower_bb": 0.0,
                    "ci_upper_bb": 0.0,
                    "paired_delta_vs_selected": {
                        "samples": 2,
                        "delta_ev_bb": 0.0,
                        "variance_bb2": 0.0,
                        "standard_error_bb": 0.0,
                        "ci_lower_bb": 0.0,
                        "ci_upper_bb": 0.0,
                    },
                    "status": "SELECTED",
                    "eliminated_after_samples": None,
                }
            },
            "pairwise_deltas": {},
            "search": {
                "pairing_contract": "DECISION_SAMPLE_COMMON_RANDOM_NUMBERS_V1",
                "base_seed": "synthetic-validator-compat",
                "decision_id": decision_id,
                "initial_samples_per_alternative": 2,
                "max_samples_per_alternative": 2,
                "batch_size": 1,
                "max_total_rollouts": 2,
                "confidence_z": 1.96,
                "elimination_margin_bb": 0.0,
                "adaptive": False,
                "rollout_budget_used": 2,
                "worlds_materialized": 2,
                "world_fingerprints_sha256": {},
            },
        },
        "decision_binding": {
            "decision_id": decision_id,
            "context_id": context_id,
            "hand_class": hand_class,
        },
        "artifact_identity": identity,
        "alternatives": {
            "ALT_FOLD_SYNTHETIC_VALIDATOR": {
                "action": "FOLD",
                "sizing": {"kind": "NONE", "value": None, "unit": None},
            }
        },
    }


def test_bridge_cells_are_accepted_by_existing_196_generation_validator() -> None:
    """Build a temporary full READY plan using only deterministic synthetic worlds.

    The temporary manifest is production-shaped solely so the existing #196 validator
    exercises its MEASURED branch. Nothing is persisted and no poker claim is made.
    """
    generation_id = "SYNTHETIC_BRIDGE_VALIDATOR_COMPAT_V1"
    candidate_id = "SYNTHETIC_ARTIFACT_CANDIDATE_VALIDATOR_V1"
    identity = {
        "population_id": PLAN["population_id"],
        "generation_id": generation_id,
        "candidate_id": candidate_id,
        "source_plan_sha256": PLAN_SHA,
        "source_train_audit_sha256": PLAN["source"]["sha256"],
        "generator_version": "paired-ev-generation-bridge-validator-fixture/1",
        "code_sha": "8447ba28b30dab3d22fe975bd9eb4a6b3ecfd202",
        "environment_identity_slot": "env:SYNTHETIC_BRIDGE_VALIDATOR_V1",
        "generation_parameters_slot": "params:SYNTHETIC_BRIDGE_VALIDATOR_V1",
        "scientific_effect": "NONE_INTEGRATION_CONTRACT_ONLY",
    }

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        env = {
            "schema": "synthetic-environment-identity/v1",
            "slot_id": identity["environment_identity_slot"],
            "scientific_effect": "NONE_INTEGRATION_CONTRACT_ONLY",
            "note": "ephemeral #297 validator compatibility fixture only",
        }
        params = {
            "schema": "synthetic-paired-bridge-generation-parameters/v1",
            "slot_id": identity["generation_parameters_slot"],
            "rollouts_per_cell": 2,
            "worlds": "synthetic deterministic fixture only",
            "scientific_effect": "NONE_INTEGRATION_CONTRACT_ONLY",
        }
        _write_json(root / "environment_identity.json", env)
        _write_json(root / "generation_parameters.json", params)

        plan_by_id = {row["context_id"]: row for row in PLAN["contexts"]}
        artifacts = [
            {
                "role": "ENVIRONMENT_IDENTITY",
                "path": "environment_identity.json",
                "sha256": sha256_path(root / "environment_identity.json"),
                "shard_id": None,
                "context_ids": [],
                "cell_count": 0,
            },
            {
                "role": "GENERATION_PARAMETERS",
                "path": "generation_parameters.json",
                "sha256": sha256_path(root / "generation_parameters.json"),
                "shard_id": None,
                "context_ids": [],
                "cell_count": 0,
            },
        ]
        binding_rows = []

        for shard_plan in PLAN["shard_plan"]["shards"]:
            cells = []
            for context_id in shard_plan["context_ids"]:
                for hand_class in CANONICAL_HAND_CLASSES:
                    result = bridge_request(
                        _make_measured_request(context_id, hand_class, identity),
                        PLAN,
                        plan_sha256=PLAN_SHA,
                    )
                    assert result["bridge_state"] == MEASURED_COMPATIBLE
                    cells.append(result["strategy_cell"])
            shard = {
                "schema": "poker-hero-preflop-strategy-shard/v1",
                "population_id": PLAN["population_id"],
                "generation_id": generation_id,
                "candidate_id": candidate_id,
                "shard_id": shard_plan["shard_id"],
                "synthetic_fixture": False,
                "cells": cells,
            }
            rel = f"shards/{shard_plan['shard_id']}.json"
            _write_json(root / rel, shard)
            digest = sha256_path(root / rel)
            artifacts.append({
                "role": "STRATEGY_SHARD",
                "path": rel,
                "sha256": digest,
                "shard_id": shard_plan["shard_id"],
                "context_ids": shard_plan["context_ids"],
                "cell_count": len(cells),
            })
            for context_id in shard_plan["context_ids"]:
                binding_rows.append({
                    "context_id": context_id,
                    "population_id": PLAN["population_id"],
                    "generation_id": generation_id,
                    "candidate_id": candidate_id,
                    "stack_bucket": plan_by_id[context_id]["effective_stack_bucket"],
                    "shard_id": shard_plan["shard_id"],
                    "artifact_path": rel,
                    "artifact_sha256": digest,
                })

        binding = {
            "schema": "poker-hero-preflop-generation-binding/v1",
            "population_id": PLAN["population_id"],
            "generation_id": generation_id,
            "candidate_id": candidate_id,
            "lookup_policy": {
                "mode": "EXACT_CONTEXT_ONLY",
                "nearest_context_allowed": False,
                "fallback_states": ["EXACT_GENERATED", "EXACT_INCUMBENT_FALLBACK", "EXACT_UNAVAILABLE"],
            },
            "bindings": binding_rows,
        }
        _write_json(root / "binding.json", binding)
        artifacts.append({
            "role": "BINDING",
            "path": "binding.json",
            "sha256": sha256_path(root / "binding.json"),
            "shard_id": None,
            "context_ids": PLAN["generation_order"],
            "cell_count": 0,
        })

        manifest = {
            "schema": "poker-hero-preflop-generation-manifest/v1",
            "population_id": PLAN["population_id"],
            "generation_id": generation_id,
            "candidate_id": candidate_id,
            "generator_version": identity["generator_version"],
            "source_plan_sha256": PLAN_SHA,
            "source_train_audit_sha256": PLAN["source"]["sha256"],
            "code_sha": identity["code_sha"],
            "environment_identity": {
                "slot_id": identity["environment_identity_slot"],
                "path": "environment_identity.json",
                "sha256": sha256_path(root / "environment_identity.json"),
            },
            "generation_parameters": {
                "slot_id": identity["generation_parameters_slot"],
                "path": "generation_parameters.json",
                "sha256": sha256_path(root / "generation_parameters.json"),
            },
            "generation_scope": "FULL_READY_PLAN",
            "synthetic_fixture": False,
            "context_count": len(PLAN["generation_order"]),
            "expected_hand_classes_per_context": 169,
            "shard_count": len(PLAN["shard_plan"]["shards"]),
            "hand_class_order_id": "poker-hand-class-169-matrix-row-major-v1",
            "plan_projection": {
                "ready_context_count": len(PLAN["generation_order"]),
                "expected_hand_classes_per_context": 169,
                "ready_cell_count": PLAN["structural_compute_estimator"]["ready_hand_class_cells"],
                "planned_shard_count": PLAN["structural_compute_estimator"]["planned_shards"],
            },
            "expected_context_ids": PLAN["generation_order"],
            "artifacts": artifacts,
            "completeness": {
                "state": "COMPLETE",
                "expected_context_count": 44,
                "actual_context_count": 44,
                "expected_cells": 7436,
                "actual_cells": 7436,
                "expected_shard_count": 6,
                "actual_shard_count": 6,
            },
            "fallback_contract": {
                "states": ["EXACT_GENERATED", "EXACT_INCUMBENT_FALLBACK", "EXACT_UNAVAILABLE"],
                "resolution_order": ["EXACT_GENERATED", "EXACT_INCUMBENT_FALLBACK", "EXACT_UNAVAILABLE"],
                "lookup": "EXACT_CONTEXT_ONLY",
                "nearest_context_allowed": False,
                "forbidden_substitutions": [
                    "NEAREST_STACK",
                    "NEAREST_POSITION",
                    "NEAREST_OPENER",
                    "NEAREST_FAMILY",
                    "CALLER_COUNT_BACKOFF",
                    "LIMPER_COUNT_BACKOFF",
                    "JAM_STATE_BACKOFF",
                ],
            },
            "immutability": {
                "content_addressed": True,
                "hash_algorithm": "sha256",
                "in_place_modification_allowed": False,
                "correction_policy": "NEW_GENERATION_ID",
                "finalized_state": "FINALIZED",
            },
        }
        _write_json(root / "manifest.json", manifest)

        report = validate_generation(root, PLAN_PATH, allow_synthetic=False)
        assert report["valid"] is True
        assert report["contexts"] == 44
        assert report["cells"] == 7436
        assert report["shards"] == 6
        assert report["synthetic_fixture"] is False


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"paired EV -> Hero generation bridge tests: {len(tests)} passed")
