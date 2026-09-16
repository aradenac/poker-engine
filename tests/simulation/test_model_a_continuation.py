#!/usr/bin/env python3
from __future__ import annotations

import unittest

from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.model_a_continuation import (
    ModelAContinuationPolicy,
    ModelAUnsupportedContext,
)


def preflop_node(*, actor, family, live, history, raise_level, frequencies, support=100):
    return {
        "id": f"PF_{actor}_{family}_{raise_level}_{len(history)}",
        "context": {
            "actor_position": actor,
            "table_size": 3,
            "raise_level": raise_level,
            "family": family,
            "live_positions": list(live),
            "all_in_positions": [],
            "history": list(history),
        },
        "coverage": {"population_decisions": support},
        "population_model": {
            "frequencies": dict(frequencies),
            "legal_actions": list(frequencies),
        },
    }


def postflop_node(key, frequencies, *, own_size_pot=None, support=100):
    node = {
        "id": "PO_" + key.replace("|", "_"),
        "canonical_key": key,
        "coverage": {"population_decisions": support},
        "population_model": {
            "frequencies": dict(frequencies),
            "legal_actions": list(frequencies),
        },
    }
    if own_size_pot is not None:
        node["continuous"] = {"own_size_pot": {"n": support, "median": own_size_pot, "mean": own_size_pot}}
    return node


def srp_state() -> NoLimitHoldemState:
    state = NoLimitHoldemState(
        seats=["BTN", "SB", "BB"],
        button="BTN",
        stacks_bb={"BTN": 100, "SB": 100, "BB": 100},
    )
    state.apply_action("BTN", "RAISE", target_total_bb=2.5)
    state.apply_action("SB", "FOLD")
    return state


def models():
    btn_open = preflop_node(
        actor="BTN",
        family="UNOPENED",
        live=["BTN", "SB", "BB"],
        history=[],
        raise_level=0,
        frequencies={"RAISE": 1.0},
    )
    bb_vs_open = preflop_node(
        actor="BB",
        family="VS_RFI",
        live=["BTN", "BB"],
        history=[{"position": "BTN", "action": "RAISE"}],
        raise_level=1,
        frequencies={"FOLD": 0.2, "CALL": 0.8},
    )
    post = {
        "nodes": [
            postflop_node("flop|2|2|OOP|SRP|CALLER|", {"BET": 1.0}, own_size_pot=0.5),
            postflop_node("flop|2|2|IP|SRP|PFA|BET", {"RAISE": 1.0}, own_size_pot=0.5),
        ],
        "response_models": {},
        "combo_policy_models": {},
        "hand_policy_prior": {},
    }
    return {"nodes": [btn_open, bb_vs_open]}, post


class ModelAContinuationTests(unittest.TestCase):
    def test_preflop_exact_context_reconstructs_fold_and_call_after_open(self):
        preflop, postflop = models()
        policy = ModelAContinuationPolicy(preflop, postflop)
        state = srp_state()
        info = policy.action_probabilities(state, actor="BB", hole_cards=["Ah", "Kd"])
        self.assertEqual(info["source"], "EXACT_NODE_MARGINAL_FALLBACK")
        self.assertEqual(info["semantic_context"]["actor_position"], "BB")
        self.assertEqual(info["semantic_context"]["family"], "VS_RFI")
        self.assertEqual(info["semantic_context"]["live_positions"], ["BTN", "BB"])
        self.assertEqual(info["semantic_context"]["history"], [{"position": "BTN", "action": "RAISE"}])
        self.assertAlmostEqual(info["probabilities"]["FOLD"], 0.2)
        self.assertAlmostEqual(info["probabilities"]["CALL"], 0.8)
        self.assertNotIn("LIMP", info["probabilities"])

    def test_missing_exact_preflop_context_fails_closed(self):
        policy = ModelAContinuationPolicy({"nodes": []}, {"nodes": []})
        state = NoLimitHoldemState(
            seats=["BTN", "SB", "BB"],
            button="BTN",
            stacks_bb={"BTN": 100, "SB": 100, "BB": 100},
        )
        with self.assertRaisesRegex(ModelAUnsupportedContext, "missing exact preflop"):
            policy.action_probabilities(state, actor="BTN", hole_cards=["Ah", "Kd"])

    def test_postflop_exact_key_and_empirical_bet_sizing_are_runtime_compatible(self):
        preflop, postflop = models()
        policy = ModelAContinuationPolicy(preflop, postflop)
        state = srp_state()
        state.apply_action("BB", "CALL")
        state.advance_street(["As", "7d", "2c"])
        self.assertEqual(state.next_actor, "BB")
        result = policy.decide(
            state,
            actor="BB",
            hole_cards=["Kh", "Qh"],
            seed_parts=("fixture", 1),
        )
        self.assertEqual(result["semantic_context"]["canonical_key"], "flop|2|2|OOP|SRP|CALLER|")
        self.assertEqual(result["semantic_action"], "BET")
        self.assertEqual(result["action"], "RAISE")
        self.assertEqual(result["sizing_source"], "EXACT_NODE_OWN_SIZE_POT")
        self.assertAlmostEqual(result["target_total_bb"], 2.75)

    def test_postflop_facing_bet_keeps_raise_semantics(self):
        preflop, postflop = models()
        policy = ModelAContinuationPolicy(preflop, postflop)
        state = srp_state()
        state.apply_action("BB", "CALL")
        state.advance_street(["As", "7d", "2c"])
        state.apply_action("BB", "RAISE", target_total_bb=2.75)
        self.assertEqual(state.next_actor, "BTN")
        info = policy.action_probabilities(state, actor="BTN", hole_cards=["Ad", "Qc"])
        self.assertEqual(info["semantic_context"]["canonical_key"], "flop|2|2|IP|SRP|PFA|BET")
        self.assertEqual(info["probabilities"], {"RAISE": 1.0})


if __name__ == "__main__":
    unittest.main()
