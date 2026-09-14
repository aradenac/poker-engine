#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.evaluate_preflop_topology_candidate import (  # noqa: E402
    build_target_specs,
    candidate_nodes,
    find_closest,
    read_rows,
    runtime_exact,
)


def context(*, free=False, family="VS_LIMPERS"):
    return {
        "table_size": 6,
        "actor_position": "CO",
        "family": family,
        "raise_level": 0,
        "free_check": free,
        "live_positions": ["LJ", "HJ", "CO", "BTN", "SB", "BB"],
        "all_in_positions": [],
        "history": [{"position": "LJ", "action": "LIMP"}, {"position": "HJ", "action": "LIMP"}],
    }


def node(node_id, *, support=100, free=False, legal=None, freqs=None):
    return {
        "id": node_id,
        "canonical_key": node_id,
        "context": context(free=free),
        "coverage": {"population_decisions": support},
        "continuous_population": {},
        "population_model": {
            "legal_actions": legal or ["FOLD", "LIMP", "RAISE", "JAM"],
            "frequencies": freqs or {"FOLD": 0.5, "LIMP": 0.35, "RAISE": 0.14, "JAM": 0.01},
        },
    }


def decision(*, action="FOLD", free=True):
    return {
        **context(free=free),
        "action": action,
        "pot_before_bb": 2.5,
        "actor_start_stack_bb": 100.0,
        "action_add_bb": 0.0,
    }


def test_runtime_exact_mirrors_browser_free_check_quirk() -> None:
    assert runtime_exact(context(free=False), decision(free=True)) is True


def test_runtime_exact_prefers_highest_support() -> None:
    low = node("low", support=20)
    high = node("high", support=200)
    match = find_closest({"CO": [low, high]}, decision(action="FOLD"))
    assert match and match["exact"] is True
    assert match["node"]["id"] == "high"


def test_action_legal_filter_matches_browser() -> None:
    fold_only = node("fold", support=500, legal=["FOLD"], freqs={"FOLD": 1.0})
    raise_node = node("raise", support=10, legal=["RAISE"], freqs={"RAISE": 1.0})
    match = find_closest({"CO": [fold_only, raise_node]}, decision(action="RAISE"))
    assert match and match["node"]["id"] == "raise"


def test_target_materialization_is_train_support_gated_and_smoothed() -> None:
    baseline = {"nodes": [node("existing-key")]}
    unseen_key = "6|CO|family=VS_LIMPERS|rl=0|free=1|live=LJ,HJ,CO,BTN,SB,BB|allin=|hist=LJ:LIMP>HJ:LIMP"
    sparse_key = unseen_key.replace("CO|family", "BTN|family")
    overlay = {"preflop_nodes": [
        {"id": "u", "canonical_key": unseen_key, "context": context(free=True), "n_delta": 20, "actions": {"FOLD": 12, "LIMP": 8}},
        {"id": "s", "canonical_key": sparse_key, "context": {**context(free=True), "actor_position": "BTN"}, "n_delta": 19, "actions": {"FOLD": 10, "LIMP": 9}},
    ]}
    rows = []
    for i in range(20):
        rows.append({
            **decision(action="FOLD" if i < 12 else "LIMP", free=True),
            "v4_canonical_key": unseen_key,
            "pot_before_bb": 2.5,
            "actor_start_stack_bb": 100.0,
            "action_add_bb": 0.0,
        })
    specs = build_target_specs(baseline, overlay, {unseen_key: rows, sparse_key: []}, 20)
    assert len(specs) == 1
    assert specs[0]["support"] == 20
    materialized = candidate_nodes(specs, 40.0)
    assert len(materialized) == 1
    f = materialized[0]["population_model"]["frequencies"]
    assert abs(sum(f.values()) - 1.0) < 1e-12
    assert f["FOLD"] > 0 and f["LIMP"] > 0


def test_validation_reader_never_scores_test_rows() -> None:
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "decisions.jsonl"
        base = {
            "street": "preflop", "is_hero": False, "hand_id": "1",
            "actor_position": "CO", "action": "FOLD", "table_size": 6,
            "raise_level": 0, "family": "VS_LIMPERS", "live_positions": [],
            "all_in_positions": [], "history": [], "free_check": False,
            "v4_canonical_key": "k",
        }
        lines = [
            {**base, "hand_id": "1", "split": "TRAIN"},
            {**base, "hand_id": "2", "split": "VALIDATION"},
            {**base, "hand_id": "3", "split": "TEST"},
        ]
        path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
        scored, train = read_rows(path, "VALIDATION")
        assert [x["hand_id"] for x in scored] == ["2"]
        assert [x["hand_id"] for x in train["k"]] == ["1"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"preflop topology candidate tests: {len(tests)} passed")
