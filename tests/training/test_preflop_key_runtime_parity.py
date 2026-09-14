#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.audit_preflop_key_runtime_parity import (  # noqa: E402
    audit,
    canonical_diff_fields,
    canonical_from_context,
    classify_hist_mismatch,
    runtime_signature,
)


def ctx(*, hist=None, free=False, actor="CO"):
    return {
        "table_size": 6,
        "actor_position": actor,
        "family": "VS_LIMPERS",
        "raise_level": 0,
        "free_check": free,
        "live_positions": ["LJ", "CO", "BTN", "SB", "BB"],
        "all_in_positions": [],
        "history": hist or [],
    }


def node(node_id, context, key, support=10, actions=None):
    return {
        "id": node_id,
        "canonical_key": key,
        "context": context,
        "coverage": {"population_decisions": support},
        "population_model": {"legal_actions": actions or ["FOLD", "LIMP", "RAISE"]},
    }


def test_context_key_round_trip():
    c = ctx(hist=[{"position": "LJ", "action": "LIMP"}])
    key = canonical_from_context(c)
    assert key == "6|CO|family=VS_LIMPERS|rl=0|free=0|live=LJ,CO,BTN,SB,BB|allin=|hist=LJ:LIMP"
    assert canonical_diff_fields(key, c) == []


def test_hist_mismatch_classification():
    c = ctx(hist=[{"position": "LJ", "action": "LIMP"}, {"position": "HJ", "action": "LIMP"}])
    assert classify_hist_mismatch("LJ:LIMP", c) == "CANONICAL_PREFIX_OF_CONTEXT"
    assert classify_hist_mismatch("LJ:LIMP>HJ:LIMP>CO:LIMP", c) == "CONTEXT_PREFIX_OF_CANONICAL"
    assert classify_hist_mismatch("LJ:RAISE>HJ:LIMP", c) == "ACTION_ONLY_DIFFERENCE"


def test_runtime_signature_intentionally_ignores_free_check():
    a = ctx(free=False)
    b = ctx(free=True)
    assert canonical_from_context(a) != canonical_from_context(b)
    assert runtime_signature(a) == runtime_signature(b)


def test_audit_reports_hist_mismatch_and_action_collision():
    history = [{"position": "LJ", "action": "LIMP"}, {"position": "HJ", "action": "LIMP"}]
    c1 = ctx(hist=history, free=False)
    c2 = ctx(hist=history, free=True)
    good = canonical_from_context(c1)
    stale = good.rsplit("hist=", 1)[0] + "hist=LJ:LIMP"
    model = {
        "schema": "fixture",
        "nodes": [
            node("A", c1, stale, support=100),
            node("B", c2, canonical_from_context(c2), support=20),
        ],
    }
    result = audit(model)
    parity = result["canonical_context_parity"]
    runtime = result["runtime_equivalence"]
    assert parity["mismatch_nodes"] == 1
    assert parity["diff_field_distribution"] == {"hist": 1}
    assert parity["hist_mismatch_pattern_distribution"] == {"CANONICAL_PREFIX_OF_CONTEXT": 1}
    assert runtime["collision_classes"] == 1
    assert runtime["nodes_in_collision_classes"] == 2
    assert runtime["action_level_collisions"] == 3
    assert runtime["shadowed_support_sum_by_action"] == 60


def test_disjoint_legal_actions_are_not_runtime_selection_collision():
    c = ctx()
    model = {
        "nodes": [
            node("A", c, canonical_from_context(c), support=100, actions=["FOLD"]),
            node("B", c, canonical_from_context(c), support=20, actions=["RAISE"]),
        ]
    }
    result = audit(model)
    assert result["runtime_equivalence"]["collision_classes"] == 0
    assert result["runtime_equivalence"]["action_level_collisions"] == 0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"preflop key/runtime parity tests: {len(tests)} passed")
