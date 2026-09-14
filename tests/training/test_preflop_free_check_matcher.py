#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.audit_preflop_key_runtime_parity import canonical_from_context  # noqa: E402
from tools.training.evaluate_preflop_free_check_matcher import runtime_exact_strict  # noqa: E402
from tools.training.explain_preflop_key_runtime_mismatches import (  # noqa: E402
    explain,
    history_pairs_from_context,
    history_pairs_from_key,
)


def ctx(*, free=False):
    return {
        "table_size": 6,
        "actor_position": "CO",
        "family": "VS_LIMPERS",
        "raise_level": 0,
        "free_check": free,
        "live_positions": ["LJ", "HJ", "CO", "BTN", "SB", "BB"],
        "all_in_positions": [],
        "history": [
            {"position": "LJ", "action": "LIMP"},
            {"position": "HJ", "action": "LIMP"},
        ],
    }


def node(node_id, context, key, support):
    return {
        "id": node_id,
        "canonical_key": key,
        "context": context,
        "coverage": {"population_decisions": support},
        "population_model": {
            "legal_actions": ["FOLD", "RAISE", "JAM"],
            "frequencies": {"FOLD": 0.5, "RAISE": 0.45, "JAM": 0.05},
        },
    }


def test_legacy_comma_history_is_token_equivalent_to_current_separator():
    c = ctx()
    assert history_pairs_from_key("LJ:LIMP,HJ:LIMP") == history_pairs_from_context(c)
    assert history_pairs_from_key("LJ:LIMP>HJ:LIMP") == history_pairs_from_context(c)


def test_explainer_attributes_key_mismatch_and_runtime_collision():
    false_ctx = ctx(free=False)
    true_ctx = ctx(free=True)
    legacy_key = canonical_from_context(false_ctx).replace("LJ:LIMP>HJ:LIMP", "LJ:LIMP,HJ:LIMP")
    model = {
        "model_version": "fixture",
        "nodes": [
            node("false", false_ctx, legacy_key, 100),
            node("true", true_ctx, canonical_from_context(true_ctx), 10),
        ],
    }
    result = explain(model)
    mismatch = result["canonical_key_mismatch"]
    collisions = result["runtime_collisions"]
    assert mismatch["nodes"] == 1
    assert mismatch["explanation_distribution"] == {"LEGACY_COMMA_DELIMITER_ONLY": 1}
    assert mismatch["all_mismatches_explained"] is True
    assert collisions["classes"] == 1
    assert collisions["class_cause_distribution"] == {"free_check": 1}
    assert collisions["all_collisions_free_check_only"] is True


def test_strict_exact_distinguishes_free_check():
    decision = dict(ctx(free=True))
    assert runtime_exact_strict(ctx(free=True), decision) is True
    assert runtime_exact_strict(ctx(free=False), decision) is False


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"preflop free-check matcher tests: {len(tests)} passed")
