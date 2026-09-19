#!/usr/bin/env python3
from __future__ import annotations

import base64
import copy
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.ranges.model_a_posterior_runtime import ModelAPosteriorRuntime
from src.ranges.posterior_range import validate_posterior_range
from tools.repro_preflop_fixture import load_verified_reference
from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.model_a_continuation import (
    ModelAContinuationPolicy,
    _preflop_decision,
    _semantic_action,
    _semantic_trace,
)
from tools.training.model_a_latent_ranges import matrix_notations


def clone_state(state: NoLimitHoldemState) -> NoLimitHoldemState:
    return NoLimitHoldemState.from_snapshot(state.to_snapshot(include_log=True))


def reference_states():
    fixture = load_verified_reference(ROOT)
    scenario = fixture["scenario"]
    points = scenario["snapshot_points"]
    before = {}
    after = {}
    for point in points:
        if "before_action" in point:
            before.setdefault(point["before_action"], []).append(point["id"])
        if "after_action" in point:
            after.setdefault(point["after_action"], []).append(point["id"])
    stored = {row["id"]: row for row in fixture["snapshots"]}

    state = NoLimitHoldemState(
        seats=scenario["seats"],
        button=scenario["button"],
        stacks_bb=scenario["starting_stacks_bb"],
        small_blind_bb=scenario["blinds_bb"]["small"],
        big_blind_bb=scenario["blinds_bb"]["big"],
    )
    states = {}
    decisions = []
    for action in scenario["actions"]:
        action_id = action["id"]
        for snapshot_id in before.get(action_id, []):
            states[snapshot_id] = clone_state(state)

        trace, _, preflop_history, _, _ = _semantic_trace(state)
        del trace
        player = action["player"]
        semantic = _semantic_action(state, action, preflop_history)
        decision = _preflop_decision(state, player, preflop_history)
        decisions.append((action_id, player, semantic, copy.deepcopy(decision)))

        if action["action"] == "RAISE":
            state.apply_action(player, "RAISE", target_total_bb=action["target_total_bb"])
        else:
            state.apply_action(player, action["action"])
        for snapshot_id in after.get(action_id, []):
            states[snapshot_id] = clone_state(state)

    before_co_limp = NoLimitHoldemState(
        seats=scenario["seats"],
        button=scenario["button"],
        stacks_bb=scenario["starting_stacks_bb"],
        small_blind_bb=scenario["blinds_bb"]["small"],
        big_blind_bb=scenario["blinds_bb"]["big"],
    )
    before_co_limp.apply_action("UTG", "FOLD")
    before_co_limp.apply_action("HJ", "FOLD")
    states["before_co_limp_unstored"] = before_co_limp

    state.advance_street(scenario["flop_cards"])
    states["flop_entry_runtime"] = clone_state(state)
    return fixture, stored, states, decisions


def encoded_policy(semantic: str) -> dict:
    hands = matrix_notations()
    actions = ["FOLD", semantic]
    values = []
    for action in actions:
        for hand in hands:
            if action == semantic:
                values.append(900 if hand == "AA" else 100)
            else:
                values.append(100 if hand == "AA" else 900)
    raw = struct.pack("<" + "H" * len(values), *values)
    return {
        "hand_order": hands,
        "actions": actions,
        "shape": [len(actions), len(hands)],
        "scale": 1000,
        "dtype": "uint16-le",
        "data": base64.b64encode(raw).decode("ascii"),
    }


def informative_policy(decisions, *, drop_action_id=None, zero_support_action_id=None):
    nodes = []
    wanted = {"co_limp", "btn_limp", "bb_call_iso", "co_call_iso", "btn_call_iso"}
    for action_id, player, semantic, decision in decisions:
        if action_id not in wanted or action_id == drop_action_id:
            continue
        support = 0 if action_id == zero_support_action_id else 100 + len(nodes)
        nodes.append(
            {
                "id": f"PF_{action_id}",
                "context": {
                    "actor_position": decision["actor_position"],
                    "table_size": decision["table_size"],
                    "raise_level": decision["raise_level"],
                    "family": decision["family"],
                    "live_positions": list(decision["live_positions"]),
                    "all_in_positions": list(decision["all_in_positions"]),
                    "history": copy.deepcopy(decision["history"]),
                },
                "coverage": {"population_decisions": support},
                "population_model": {
                    "legal_actions": ["FOLD", semantic],
                    "policy169_q_b64": encoded_policy(semantic),
                },
            }
        )
    return ModelAContinuationPolicy(
        {"hand_grid": {"classes": matrix_notations()}, "nodes": nodes},
        {"nodes": [], "response_models": {}, "combo_policy_models": {}, "hand_policy_prior": {}},
        identity={
            "preflop_sha256": "synthetic-preflop",
            "postflop_baseline_sha256": "synthetic-postflop",
            "continuation_overlay_sha256": "synthetic-overlay",
            "stage_b_decision": "SYNTHETIC_TEST_ONLY",
        },
    )


def adapter(policy):
    return ModelAPosteriorRuntime(
        policy,
        population_id="synthetic-kts-population",
        model_id="model-a-existing-continuation",
        model_version="fixture-v1",
        source_id="synthetic:#321",
    )


def fingerprint(stored, snapshot_id):
    return stored[snapshot_id]["public_fingerprint_sha256"]


def test_kts_co_and_btn_ranges_change_after_limp():
    fixture, stored, states, decisions = reference_states()
    runtime = adapter(informative_policy(decisions))

    co_before = runtime.posterior_record(
        states["before_co_limp_unstored"],
        player="CO",
        moment="BEFORE_ACTION",
        hand_id=fixture["scenario_id"],
        step_id="co_limp:before",
    )
    co_after = runtime.posterior_record(
        states["after_co_limp"],
        player="CO",
        moment="AFTER_ACTION",
        hand_id=fixture["scenario_id"],
        step_id="co_limp:after",
        public_state_fingerprint=fingerprint(stored, "after_co_limp"),
    )
    assert co_before["status"] == co_after["status"] == "AVAILABLE"
    assert co_before["distribution_fingerprint"] != co_after["distribution_fingerprint"]
    assert co_after["projection_169"]["classes"]["AA"] > co_before["projection_169"]["classes"]["AA"]

    btn_before = runtime.posterior_record(
        states["after_co_limp"],
        player="BTN",
        moment="BEFORE_ACTION",
        hand_id=fixture["scenario_id"],
        step_id="btn_limp:before",
        public_state_fingerprint=fingerprint(stored, "after_co_limp"),
    )
    btn_after = runtime.posterior_record(
        states["after_btn_limp"],
        player="BTN",
        moment="AFTER_ACTION",
        hand_id=fixture["scenario_id"],
        step_id="btn_limp:after",
        public_state_fingerprint=fingerprint(stored, "after_btn_limp"),
    )
    assert btn_before["status"] == btn_after["status"] == "AVAILABLE"
    assert btn_before["distribution_fingerprint"] != btn_after["distribution_fingerprint"]
    assert btn_after["projection_169"]["classes"]["AA"] > btn_before["projection_169"]["classes"]["AA"]


def test_kts_bb_before_after_call_and_limpers_after_second_call():
    fixture, stored, states, decisions = reference_states()
    runtime = adapter(informative_policy(decisions))

    bb_before = runtime.posterior_record(
        states["before_bb_call"],
        player="BB",
        moment="BEFORE_ACTION",
        hand_id=fixture["scenario_id"],
        step_id="bb_call:before",
        public_state_fingerprint=fingerprint(stored, "before_bb_call"),
    )
    bb_after = runtime.posterior_record(
        states["after_bb_call"],
        player="BB",
        moment="AFTER_ACTION",
        hand_id=fixture["scenario_id"],
        step_id="bb_call:after",
        public_state_fingerprint=fingerprint(stored, "after_bb_call"),
    )
    assert bb_before["status"] == bb_after["status"] == "AVAILABLE"
    assert bb_before["distribution_fingerprint"] != bb_after["distribution_fingerprint"]

    co_limp = runtime.posterior_record(
        states["after_co_limp"],
        player="CO",
        moment="AFTER_ACTION",
        hand_id=fixture["scenario_id"],
        step_id="co_limp:after",
    )
    co_call = runtime.posterior_record(
        states["after_co_call"],
        player="CO",
        moment="AFTER_ACTION",
        hand_id=fixture["scenario_id"],
        step_id="co_call:after",
        public_state_fingerprint=fingerprint(stored, "after_co_call"),
    )
    assert co_limp["status"] == co_call["status"] == "AVAILABLE"
    assert co_limp["distribution_fingerprint"] != co_call["distribution_fingerprint"]

    btn_limp = runtime.posterior_record(
        states["after_btn_limp"],
        player="BTN",
        moment="AFTER_ACTION",
        hand_id=fixture["scenario_id"],
        step_id="btn_limp:after",
    )
    btn_call = runtime.posterior_record(
        states["after_btn_call_preflop"],
        player="BTN",
        moment="AFTER_ACTION",
        hand_id=fixture["scenario_id"],
        step_id="btn_call:after",
        public_state_fingerprint=fingerprint(stored, "after_btn_call_preflop"),
    )
    assert btn_limp["status"] == btn_call["status"] == "AVAILABLE"
    assert btn_limp["distribution_fingerprint"] != btn_call["distribution_fingerprint"]


def test_contract_identity_support_projection_and_call_sizing_are_validated():
    fixture, stored, states, decisions = reference_states()
    runtime = adapter(informative_policy(decisions))
    record = runtime.posterior_record(
        states["after_bb_call"],
        player="BB",
        moment="AFTER_ACTION",
        hand_id=fixture["scenario_id"],
        step_id="bb_call_iso",
        public_state_fingerprint=fingerprint(stored, "after_bb_call"),
    )
    assert record["status"] == "AVAILABLE"
    assert validate_posterior_range(record) == []
    assert record["schema"] == "poker-opponent-posterior-range/v1"
    assert record["identity"] == {
        "population_id": "synthetic-kts-population",
        "model_id": "model-a-existing-continuation",
        "model_version": "fixture-v1",
        "source_id": "synthetic:#321",
    }
    assert record["support"]["source_observations"] > 0
    assert record["support"]["backoff"]["level"] == "EXACT_NODE_HISTORY"
    assert "PF_bb_call_iso" in record["provenance"]["source_artifact"]
    assert record["probability_mass"] == 1.0
    assert len(record["projection_169"]["classes"]) == 169
    assert record["public_action"]["action"] == "CALL"
    assert record["public_action"]["sizing"]["semantic"] == "INCREMENTAL_COST_BB"
    assert record["public_action"]["sizing"]["observed_size_bb"] == 3.0
    assert record["public_action"]["sizing"]["target_total_bb"] == 4.0
    assert record["public_action"]["sizing"]["pot_before_bb"] == 7.0
    assert record["public_action"]["sizing"]["pot_fraction"] == 3.0 / 7.0


def test_before_action_has_no_target_action_and_unconditioned_prior_is_not_all_100():
    fixture, stored, states, decisions = reference_states()
    runtime = adapter(informative_policy(decisions))
    record = runtime.posterior_record(
        states["before_bb_call"],
        player="BB",
        moment="BEFORE_ACTION",
        hand_id=fixture["scenario_id"],
        step_id="bb_call_iso:before",
        public_state_fingerprint=fingerprint(stored, "before_bb_call"),
    )
    assert record["status"] == "AVAILABLE"
    assert record["public_action"] is None
    assert record["support"]["source_observations"] == 0
    assert record["support"]["backoff"]["level"] == "UNCONDITIONED_COMBO_PRIOR"
    values = list(record["projection_169"]["classes"].values())
    assert abs(sum(values) - 1.0) < 1e-9
    assert not all(value == 1.0 for value in values)
    assert record["projection_169"]["classes"]["AKo"] > record["projection_169"]["classes"]["AKs"]


def test_missing_exact_node_fails_closed_without_uniform_grid():
    fixture, stored, states, decisions = reference_states()
    runtime = adapter(informative_policy(decisions, drop_action_id="co_call_iso"))
    record = runtime.posterior_record(
        states["after_co_call"],
        player="CO",
        moment="AFTER_ACTION",
        hand_id=fixture["scenario_id"],
        step_id="co_call:after",
        public_state_fingerprint=fingerprint(stored, "after_co_call"),
    )
    assert record["status"] == "UNSUPPORTED"
    assert record["probability_mass"] == 0.0
    assert record["exact_combo_weights"] == []
    assert set(record["projection_169"]["classes"].values()) == {0.0}
    assert validate_posterior_range(record) == []


def test_zero_exact_node_support_fails_closed():
    fixture, stored, states, decisions = reference_states()
    runtime = adapter(informative_policy(decisions, zero_support_action_id="bb_call_iso"))
    record = runtime.posterior_record(
        states["after_bb_call"],
        player="BB",
        moment="AFTER_ACTION",
        hand_id=fixture["scenario_id"],
        step_id="bb_call:after",
        public_state_fingerprint=fingerprint(stored, "after_bb_call"),
    )
    assert record["status"] == "UNSUPPORTED"
    assert "no positive population support" in record["reason"]
    assert record["probability_mass"] == 0.0


def test_public_only_boundary_rejects_flop_state_in_preflop_adapter():
    fixture, _, states, decisions = reference_states()
    runtime = adapter(informative_policy(decisions))
    record = runtime.posterior_record(
        states["flop_entry_runtime"],
        player="BB",
        moment="BEFORE_ACTION",
        hand_id=fixture["scenario_id"],
        step_id="flop-entry",
    )
    assert record["status"] == "INVALID"
    assert "preflop-only" in record["reason"]
    assert record["probability_mass"] == 0.0
    assert record["exact_combo_weights"] == []
    assert validate_posterior_range(record) == []


def test_after_action_requires_immediately_preceding_action_from_target_player():
    fixture, stored, states, decisions = reference_states()
    runtime = adapter(informative_policy(decisions))
    record = runtime.posterior_record(
        states["after_hero_raise"],
        player="CO",
        moment="AFTER_ACTION",
        hand_id=fixture["scenario_id"],
        step_id="invalid-co-after-hero",
        public_state_fingerprint=fingerprint(stored, "after_hero_raise"),
    )
    assert record["status"] == "INVALID"
    assert record["moment"] == "BEFORE_ACTION"
    assert record["probability_mass"] == 0.0
    assert "immediately preceding public action" in record["reason"]


def test_all_kts_acceptance_records_validate_with_320_contract():
    fixture, stored, states, decisions = reference_states()
    runtime = adapter(informative_policy(decisions))
    cases = [
        ("after_co_limp", "CO", "AFTER_ACTION"),
        ("after_btn_limp", "BTN", "AFTER_ACTION"),
        ("before_bb_call", "BB", "BEFORE_ACTION"),
        ("after_bb_call", "BB", "AFTER_ACTION"),
        ("before_co_call", "CO", "BEFORE_ACTION"),
        ("after_co_call", "CO", "AFTER_ACTION"),
        ("before_btn_call", "BTN", "BEFORE_ACTION"),
        ("after_btn_call_preflop", "BTN", "AFTER_ACTION"),
    ]
    for snapshot_id, player, moment in cases:
        record = runtime.posterior_record(
            states[snapshot_id],
            player=player,
            moment=moment,
            hand_id=fixture["scenario_id"],
            step_id=snapshot_id,
            public_state_fingerprint=fingerprint(stored, snapshot_id),
        )
        assert record["status"] == "AVAILABLE", (snapshot_id, record["reason"])
        assert validate_posterior_range(record) == [], snapshot_id
        assert record["public_state_fingerprint"] == fingerprint(stored, snapshot_id)


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"model-a posterior runtime tests: {len(tests)} passed")


if __name__ == "__main__":
    main()
