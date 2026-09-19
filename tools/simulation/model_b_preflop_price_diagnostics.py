#!/usr/bin/env python3
"""Synthetic counterfactual diagnostics for #315 tranche 1."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

from tools.simulation.model_b_preflop_response_to_price import (
    ACTIONS,
    PreflopResponseToPriceModel,
    artifact_sha256,
    build_synthetic_artifact,
)


def expand_fixture(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    if document.get("schema") != "model-b-preflop-response-to-price-synthetic-fixture/v1":
        raise ValueError("unsupported synthetic preflop fixture")
    if document.get("source_kind") != "SYNTHETIC_FIXTURE":
        raise ValueError("fixture must be synthetic")
    common = dict(document["common"])
    rows = []
    for variant in document["variants"]:
        for responder in variant["responders"]:
            counts = responder["action_counts"]
            for action in ACTIONS:
                count = int(counts.get(action, 0))
                if count < 0:
                    raise ValueError("synthetic action count must be non-negative")
                for index in range(count):
                    rows.append({
                        **common,
                        "source_kind": "SYNTHETIC_FIXTURE",
                        "hand_id": (
                            f"{document['fixture_id']}:{variant['variant_id']}:"
                            f"{responder['responder_position']}:{action}:{index}"
                        ),
                        "variant_id": variant["variant_id"],
                        "hero_raise_size_bb": float(variant["hero_raise_size_bb"]),
                        "responder_position": responder["responder_position"],
                        "facing_price_to_pot": float(responder["facing_price_to_pot"]),
                        "action": action,
                    })
    return rows


def build_from_fixture(fixture: Mapping[str, Any], graph: Mapping[str, Any]) -> dict[str, Any]:
    return build_synthetic_artifact(expand_fixture(fixture), graph=graph)


def _variant_contexts(fixture: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    common = dict(fixture["common"])
    result = {}
    for variant in fixture["variants"]:
        rows = []
        for responder in variant["responders"]:
            rows.append({
                **common,
                "hero_raise_size_bb": float(variant["hero_raise_size_bb"]),
                "responder_position": responder["responder_position"],
                "facing_price_to_pot": float(responder["facing_price_to_pot"]),
            })
        result[str(variant["variant_id"])] = rows
    return result


def counterfactual_report(
    model: PreflopResponseToPriceModel,
    fixture: Mapping[str, Any],
    *,
    low_variant: str = "4BB",
    high_variant: str = "6BB",
) -> dict[str, Any]:
    contexts = _variant_contexts(fixture)
    if low_variant not in contexts or high_variant not in contexts:
        raise ValueError("requested counterfactual variants missing from fixture")

    variants = {}
    for variant_id, rows in contexts.items():
        responders = []
        expected_continuers = 0.0
        all_fold_probability = 1.0
        for row in rows:
            pred = model.predict(**row)
            p = pred["probabilities"]
            expected_continuers += 1.0 - p["FOLD"]
            all_fold_probability *= p["FOLD"]
            responders.append({
                "responder_position": row["responder_position"],
                "hero_raise_size_bb": row["hero_raise_size_bb"],
                "facing_price_to_pot": row["facing_price_to_pot"],
                "selected_level": pred["selected_level"],
                "effective_support": pred["effective_support"],
                "fallback_reason": pred["fallback_reason"],
                "probabilities": p,
                "derived": pred["derived"],
            })
        variants[variant_id] = {
            "responders": responders,
            "synthetic_expected_continuers": expected_continuers,
            "synthetic_all_fold_probability": all_fold_probability,
        }

    by_pos = {
        variant: {row["responder_position"]: row for row in payload["responders"]}
        for variant, payload in variants.items()
    }
    positions = sorted(set(by_pos[low_variant]).intersection(by_pos[high_variant]))
    deltas = []
    for pos in positions:
        low = by_pos[low_variant][pos]
        high = by_pos[high_variant][pos]
        deltas.append({
            "responder_position": pos,
            "high_minus_low": {
                "hero_raise_size_bb": high["hero_raise_size_bb"] - low["hero_raise_size_bb"],
                "facing_price_to_pot": high["facing_price_to_pot"] - low["facing_price_to_pot"],
                "probabilities": {
                    action: high["probabilities"][action] - low["probabilities"][action]
                    for action in ACTIONS
                },
                "continue_probability": (
                    high["derived"]["continue_probability"] - low["derived"]["continue_probability"]
                ),
                "aggressive_continue_probability": (
                    high["derived"]["aggressive_continue_probability"]
                    - low["derived"]["aggressive_continue_probability"]
                ),
            },
        })

    return {
        "schema": "model-b-preflop-response-to-price-synthetic-counterfactual/v1",
        "issue": 315,
        "tranche": 1,
        "fixture_id": fixture["fixture_id"],
        "source_kind": "SYNTHETIC_FIXTURE",
        "model_identity": model.identity,
        "comparison": {"low_variant": low_variant, "high_variant": high_variant},
        "variants": variants,
        "responder_deltas": deltas,
        "aggregate_high_minus_low": {
            "synthetic_expected_continuers": (
                variants[high_variant]["synthetic_expected_continuers"]
                - variants[low_variant]["synthetic_expected_continuers"]
            ),
            "synthetic_all_fold_probability": (
                variants[high_variant]["synthetic_all_fold_probability"]
                - variants[low_variant]["synthetic_all_fold_probability"]
            ),
        },
        "interpretation_guard": (
            "Synthetic scaffold diagnostic only. These probabilities are fixture-driven and "
            "must not be interpreted as empirical performance or a Hero recommendation."
        ),
        "validation_consumed": False,
        "test_consumed": False,
        "performance_claim_allowed": False,
        "production_effect": "NONE",
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_fixture(*, fixture_path: Path, graph_path: Path, output_dir: Path) -> dict[str, Any]:
    fixture = load_json(fixture_path)
    graph = load_json(graph_path)
    artifact = build_from_fixture(fixture, graph)
    model = PreflopResponseToPriceModel(artifact)
    report = counterfactual_report(model, fixture)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "model" / "preflop_response_to_price.json", artifact)
    write_json(output_dir / "SYNTHETIC_COUNTERFACTUAL.json", report)
    result = {
        "schema": "model-b-preflop-response-to-price-scaffold-result/v1",
        "issue": 315,
        "tranche": 1,
        "status": "SCAFFOLD_COMPLETE",
        "candidate_artifact_sha256": artifact_sha256(artifact),
        "source_kind": "SYNTHETIC_FIXTURE",
        "fit_status": "NOT_FINAL_BEFORE_319",
        "validation_consumed": False,
        "test_consumed": False,
        "performance_claim_allowed": False,
        "production_effect": "NONE",
        "active_model_b_changed": False,
        "automatic_promotion": False,
        "dod": {
            "feature_contract_defined": True,
            "independent_builder_runtime": True,
            "public_price_stack_position_sequence_profile_dimensions": True,
            "explicit_support_backoff": True,
            "synthetic_fixture_only": True,
            "model_a_ev_recommendation_features_forbidden": True,
            "counterfactual_4bb_vs_6bb_persisted": True,
            "no_validation_or_test": True,
            "no_final_fit_before_319": True,
            "no_promotion_or_pointer_change": True,
        },
    }
    write_json(output_dir / "RESULT.json", result)
    return result
