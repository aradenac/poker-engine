#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.environment_drift_report import build
from tools.simulation.retarget_scenario_manifest import retarget_manifest


class FakeEnv:
    def __init__(self, alias: str, actions: str, sizing: str):
        self.alias = alias
        self.population_id = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
        self.model_dir = Path(f"/tmp/{alias}")
        self._fp = {
            "profiles.json": "profiles",
            "preflop_ranges.json": "ranges",
            "postflop_actions.json": actions,
            "sizing.json": sizing,
            "prediction_contract.json": "contract-" + alias,
        }

    def artifact_fingerprints(self):
        return dict(self._fp)


def scenario(sid: str, hand: str, rep: int, profile: int):
    return {
        "scenario_id": sid,
        "hand_id": hand,
        "rep": rep,
        "hero": "Hero",
        "opponent": "Villain",
        "positions": {"Hero": "BTN", "Villain": "BB"},
        "pot_type": "SRP",
        "stacks_bb": {"Hero": 100.0, "Villain": 100.0},
        "preflop_contributions_bb": {"Hero": 2.5, "Villain": 2.5},
        "flop_pot_bb": 5.0,
    }


def result(sid: str, hand: str, profile: int, policy: str, utility: float, label: str):
    return {
        "scenario_id": sid,
        "hand_id": hand,
        "rep": 0,
        "profile": profile,
        "policy": policy,
        "utility_bb": utility,
        "hero_decisions": 1,
        "terminal": "showdown",
        "hero_actions": [{"street": "flop", "label": label, "executed_kind": label, "executed_cost_bb": 0.0}],
    }


def arena(model_actions: str, results: list[dict]):
    scenarios = [scenario("s1", "h1", 0, 0), scenario("s2", "h2", 0, 1)]
    return {
        "schema": "sequential-independent-arena/v2",
        "metadata": {
            "scenario_fingerprint_sha256": "same-scenarios",
            "scenario_split": "VALIDATION",
            "master_seed": 20260912,
            "trials": 1200,
            "policies": ["current", "no_jam"],
            "engine": {"path": "site/index.html", "sha256": "engine"},
            "model_a": {"preflop": {"sha256": "pre"}, "postflop": {"sha256": "post"}},
            "model_b": {"alias": model_actions, "artifact_sha256": {
                "profiles.json": "profiles",
                "preflop_ranges.json": "ranges",
                "postflop_actions.json": model_actions,
                "sizing.json": model_actions + "-size",
                "prediction_contract.json": model_actions + "-contract",
            }},
        },
        "scenario_manifest": {"scenarios": scenarios},
        "results": results,
    }


def test_retarget_keeps_scenario_identity_only_when_dependencies_match():
    src = FakeEnv("v2", "a2", "s2")
    dst = FakeEnv("v3", "a3", "s3")
    manifest = {
        "schema": "sequential-arena-scenario-manifest/v2",
        "population_id": src.population_id,
        "scenario_fingerprint_sha256": "fingerprint",
        "model_b": {"artifact_sha256": src.artifact_fingerprints()},
        "scenarios": [{"scenario_id": "x"}],
    }
    out = retarget_manifest(manifest, src, dst)
    assert out["scenario_fingerprint_sha256"] == "fingerprint"
    assert out["scenarios"] == manifest["scenarios"]
    assert out["model_b"]["artifact_sha256"]["postflop_actions.json"] == "a3"
    bad = FakeEnv("bad", "a4", "s4")
    bad._fp["preflop_ranges.json"] = "different"
    try:
        retarget_manifest(manifest, src, bad)
    except ValueError:
        pass
    else:
        raise AssertionError("retarget accepted changed scenario dependencies")


def test_environment_drift_separates_fixed_strategy_from_environment():
    incumbent_results = [
        result("s1", "h1", 0, "current", 1.0, "CHECK"),
        result("s2", "h2", 1, "current", -1.0, "CALL"),
        result("s1", "h1", 0, "no_jam", 0.5, "CHECK"),
        result("s2", "h2", 1, "no_jam", -0.5, "CALL"),
    ]
    candidate_results = copy.deepcopy(incumbent_results)
    candidate_results[0]["utility_bb"] = 2.0
    candidate_results[1]["utility_bb"] = 0.0
    candidate_results[2]["utility_bb"] = 1.0
    candidate_results[3]["utility_bb"] = 0.25
    report = build(arena("v2", incumbent_results), arena("v3", candidate_results), 20260913)
    overall = report["current_policy"]["overall"]
    assert overall["paired_scenarios"] == 2
    assert overall["mean_delta_candidate_minus_incumbent_bb"] == 1.0
    assert report["provenance"]["strategy_changed"] is False
    assert report["provenance"]["model_a_changed"] is False
    assert report["policy_sensitivity"]["available"] is True
    assert "no_jam" in report["policy_sensitivity"]["difference_in_difference"]


if __name__ == "__main__":
    test_retarget_keeps_scenario_identity_only_when_dependencies_match()
    test_environment_drift_separates_fixed_strategy_from_environment()
    print("ok")
