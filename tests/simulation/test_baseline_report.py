#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.baseline_report import build_report  # noqa: E402


def scenario(sid: str, hand_id: str, rep: int, profile: int, position: str, pot_type: str, hero_cards: list[str], flop: list[str], runout: list[str], pot: float, effective: float) -> dict:
    return {
        "scenario_id": sid,
        "hand_id": hand_id,
        "rep": rep,
        "profile": profile,
        "hero": "Hero",
        "opponent": "Villain",
        "hero_cards": hero_cards,
        "opponent_cards": ["2c", "3d"],
        "flop": flop,
        "runout": runout,
        "positions": {"Hero": position, "Villain": "BB"},
        "pot_type": pot_type,
        "stacks_bb": {"Hero": effective + 3.0, "Villain": effective + 3.0},
        "preflop_contributions_bb": {"Hero": 3.0, "Villain": 3.0},
        "flop_pot_bb": pot,
    }


def row(sid: str, hand_id: str, rep: int, profile: int, policy: str, utility: float, label: str, street: str = "flop", ratio: float | None = None) -> dict:
    return {
        "scenario_id": sid,
        "hand_id": hand_id,
        "rep": rep,
        "profile": profile,
        "policy": policy,
        "utility_bb": utility,
        "hero_decisions": 2,
        "terminal": "showdown",
        "hero_actions": [
            {
                "street": street,
                "label": label,
                "pot_bb": 10.0,
                "to_call_bb": 0.0,
                "ev_final_bb": 1.2,
                "ev_model_bb": 1.0,
                "cost_bb": 10.0 * ratio if ratio is not None else None,
                "size_ratio": ratio,
                "response_observation_floor": 25,
                "continue_range_quality": 0.8,
                "p_all_fold": 0.2,
            }
        ],
    }


def synthetic_arena() -> dict:
    scenarios = [
        scenario("s1", "h1", 0, 0, "BTN", "SRP", ["As", "Ah"], ["Ac", "7d", "2h"], ["9s", "Kd"], 10.0, 15.0),
        scenario("s2", "h1", 1, 1, "BTN", "SRP", ["As", "Ah"], ["Ac", "7d", "2h"], ["Ts", "Kd"], 10.0, 15.0),
        scenario("s3", "h2", 0, 1, "CO", "3BP", ["Ks", "Qs"], ["Js", "Ts", "2d"], ["9s", "3c"], 12.0, 60.0),
        scenario("s4", "h2", 1, 2, "CO", "3BP", ["Ks", "Qs"], ["Js", "Ts", "2d"], ["8s", "3c"], 12.0, 60.0),
    ]
    results = [
        row("s1", "h1", 0, 0, "current", 2.0, "125% pot", ratio=1.25),
        row("s2", "h1", 1, 1, "current", 4.0, "jam", ratio=3.0),
        row("s3", "h2", 0, 1, "current", -2.0, "CHECK"),
        row("s4", "h2", 1, 2, "current", 0.0, "all-in effectif", ratio=2.5),
        row("s1", "h1", 0, 0, "no_jam", 1.0, "100% pot", ratio=1.0),
        row("s2", "h1", 1, 1, "no_jam", 3.0, "100% pot", ratio=1.0),
        row("s3", "h2", 0, 1, "no_jam", -1.0, "CHECK"),
        row("s4", "h2", 1, 2, "no_jam", 1.0, "100% pot", ratio=1.0),
    ]
    return {
        "schema": "sequential-independent-arena/v2",
        "metadata": {
            "code_commit": "abc123",
            "engine": {"path": "site/index.html", "sha256": "engine"},
            "model_a": {"preflop": {"sha256": "a"}, "postflop": {"sha256": "b"}},
            "model_b": {"alias": "independent_model_b_v2", "artifact_sha256": {"profiles.json": "c"}},
            "scenario_fingerprint_sha256": "scenario-fp",
            "scenario_split": "VALIDATION",
            "master_seed": 20260912,
            "trials": 1200,
            "observed_monte_carlo_trials": [1200],
            "policies": ["current", "no_jam"],
            "simulation_source_sha256": {"sequential_postflop.py": "source"},
        },
        "scenario_manifest": {
            "schema": "sequential-arena-scenario-manifest/v1",
            "master_seed": 20260912,
            "split": "VALIDATION",
            "eligible_hands": 100,
            "requested_hands": 2,
            "reps": 2,
            "scenarios": scenarios,
        },
        "summary": {},
        "results": results,
    }


def test_clustered_utility_and_regret() -> None:
    report = build_report(synthetic_arena())
    current = report["policies"]["current"]
    assert current["overall"]["base_hands"] == 2
    assert current["overall"]["rollouts"] == 4
    assert current["overall"]["mean_utility_bb"] == 1.0
    assert current["overall"]["realized_utility_per_hero_decision_bb"] == 0.5
    assert current["overall"]["utility_ci95_cluster_bootstrap"] is not None
    paired = report["paired_policy_comparisons_vs_current"]["no_jam"]
    assert paired["paired_scenarios"] == 4
    assert paired["mean_delta_utility_bb"] == 0.0
    regret = report["diagnostic_policy_set_regret"]
    assert regret is not None
    assert regret["mean_regret_bb"] == 0.5
    assert "not exhaustive" in regret["definition"]


def test_decision_style_and_context_breakdowns() -> None:
    report = build_report(synthetic_arena())
    current = report["policies"]["current"]
    decisions = current["decisions"]
    assert decisions["true_jam_count"] == 1
    assert decisions["effective_allin_count"] == 1
    assert decisions["overbet_count"] == 3
    assert current["decision_breakdowns"]["hero_position"]["BTN"]["decisions"] == 2
    assert current["decision_breakdowns"]["initial_spr_bucket"]["<2"]["decisions"] == 2
    assert current["decision_breakdowns"]["hand_strength"]["trips"]["decisions"] == 2
    assert current["decision_breakdowns"]["hand_strength"]["straight"]["decisions"] == 2
    flagged = current["suspicious_decisions"]
    assert any(x["family"] == "JAM" for x in flagged)
    assert any("sizing_above_2x_pot" in x["reasons"] for x in flagged)


def test_scope_and_provenance_are_explicit() -> None:
    report = build_report(synthetic_arena())
    assert report["schema"] == "sequential-v83-baseline-report/v1"
    assert report["scope"]["heads_up_postflop"] is True
    assert report["scope"]["preflop_strategy"] is False
    assert report["scope"]["multiway_strategy"] is False
    assert report["statistical_contract"]["cluster_unit"] == "base_hand_id"
    assert report["provenance"]["scenario_fingerprint_sha256"] == "scenario-fp"
    assert report["provenance"]["model_b"]["alias"] == "independent_model_b_v2"
    assert len(report["environment_limitations"]) >= 3


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"baseline report tests: {len(tests)} passed")
