#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.strategy_candidate_report import build


def result(sid: str, hand: str, utility: float, label: str = "CHECK") -> dict:
    return {
        "scenario_id": sid,
        "hand_id": hand,
        "policy": "current",
        "utility_bb": utility,
        "terminal": "showdown",
        "hero_actions": [{"street": "flop", "label": label, "executed_kind": label, "executed_cost_bb": 0.0}],
    }


def arena(engine_sha: str, values: list[float]) -> dict:
    return {
        "schema": "sequential-independent-arena/v2",
        "metadata": {
            "scenario_fingerprint_sha256": "same",
            "scenario_split": "VALIDATION",
            "master_seed": 20260912,
            "trials": 1200,
            "policies": ["current"],
            "engine": {"path": "engine.html", "sha256": engine_sha},
            "model_a": {"preflop": {"sha256": "pre"}, "postflop": {"sha256": "post"}},
            "model_b": {"alias": "v3", "artifact_sha256": {"profiles.json": "p", "preflop_ranges.json": "r", "postflop_actions.json": "a", "sizing.json": "s", "prediction_contract.json": "c"}},
        },
        "results": [result("s1", "h1", values[0]), result("s2", "h2", values[1])],
    }


def contract() -> dict:
    return {"strategy": {
        "metric": "conditional_postflop_utility_bb",
        "interpretation": "fixture",
        "promotion_requires_validation_ci95_lower_at_least": 0.0,
        "promotion_requires_test_ci95_lower_at_least": 0.0,
    }}


def test_clear_validation_win_advances():
    report = build(arena("v83", [0.0, 0.0]), arena("v84", [2.0, 2.0]), contract(), "VALIDATION", 7)
    assert report["decision"] == "ADVANCE_TO_TEST"
    assert report["gate_pass"] is True
    assert report["paired_base_hands"] == 2


def test_validation_loss_rejects_without_test():
    report = build(arena("v83", [2.0, 2.0]), arena("v84", [0.0, 0.0]), contract(), "VALIDATION", 7)
    assert report["decision"] == "RETAIN_V83"
    assert report["gate_pass"] is False
    assert report["test_used_for_selection"] is False


def test_fixed_environment_is_required():
    base = arena("v83", [0.0, 0.0])
    candidate = copy.deepcopy(arena("v84", [1.0, 1.0]))
    candidate["metadata"]["model_b"]["artifact_sha256"]["sizing.json"] = "changed"
    try:
        build(base, candidate, contract(), "VALIDATION", 7)
    except ValueError:
        pass
    else:
        raise AssertionError("strategy gate accepted a changed environment")


if __name__ == "__main__":
    test_clear_validation_win_advances()
    test_validation_loss_rejects_without_test()
    test_fixed_environment_is_required()
    print("ok")
