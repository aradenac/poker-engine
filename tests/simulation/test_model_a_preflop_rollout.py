#!/usr/bin/env python3
from __future__ import annotations

import unittest

from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.model_a_continuation import ModelAContinuationPolicy
from tools.simulation.model_a_preflop_rollout import ModelAPreflopContinuationRollout


def node(
    *,
    node_id,
    actor,
    table_size,
    family,
    live,
    all_in,
    history,
    raise_level,
    frequencies,
):
    return {
        "id": node_id,
        "context": {
            "actor_position": actor,
            "table_size": table_size,
            "raise_level": raise_level,
            "family": family,
            "live_positions": list(live),
            "all_in_positions": list(all_in),
            "history": list(history),
        },
        "coverage": {"population_decisions": 100},
        "population_model": {
            "legal_actions": list(frequencies),
            "frequencies": dict(frequencies),
        },
    }


def hu_call_policy() -> ModelAContinuationPolicy:
    preflop = {
        "nodes": [
            node(
                node_id="HU_BB_VS_JAM",
                actor="BB",
                table_size=2,
                family="VS_RFI",
                live=["BB"],
                all_in=["SB_BTN"],
                history=[{"position": "SB_BTN", "action": "JAM"}],
                raise_level=1,
                frequencies={"CALL": 1.0},
            )
        ]
    }
    return ModelAContinuationPolicy(preflop, {"nodes": []})


def three_way_call_policy() -> ModelAContinuationPolicy:
    preflop = {
        "nodes": [
            node(
                node_id="SB_VS_BTN_JAM",
                actor="SB",
                table_size=3,
                family="VS_RFI",
                live=["SB", "BB"],
                all_in=["BTN"],
                history=[{"position": "BTN", "action": "JAM"}],
                raise_level=1,
                frequencies={"CALL": 1.0},
            ),
            node(
                node_id="BB_VS_BTN_JAM_SB_CALL",
                actor="BB",
                table_size=3,
                family="VS_RFI_CALLERS",
                live=["BB"],
                all_in=["BTN", "SB"],
                history=[
                    {"position": "BTN", "action": "JAM"},
                    {"position": "SB", "action": "CALL"},
                ],
                raise_level=1,
                frequencies={"CALL": 1.0},
            ),
        ]
    }
    return ModelAContinuationPolicy(preflop, {"nodes": []})


class ModelAPreflopRolloutTests(unittest.TestCase):
    def test_heads_up_shove_rollout_is_reproducible_and_settles_with_rake(self):
        state = NoLimitHoldemState(
            seats=["Hero", "Villain"],
            button="Hero",
            stacks_bb={"Hero": 10, "Villain": 10},
        )
        state.apply_action("Hero", "RAISE", target_total_bb=10)
        rollout = ModelAPreflopContinuationRollout(
            opponent_policy=hu_call_policy(),
            hero_hole_cards=["As", "Ah"],
            hero_continuation_policy=None,
        )
        kwargs = {
            "actor": "Hero",
            "seed": 12345,
            "sample_index": 0,
            "candidate": {"id": "SHOVE"},
        }
        first = rollout(NoLimitHoldemState.from_snapshot(state.to_snapshot()), **kwargs)
        second = rollout(NoLimitHoldemState.from_snapshot(state.to_snapshot()), **kwargs)
        self.assertTrue(first["supported"])
        self.assertEqual(first, second)
        self.assertEqual(first["terminal"], "showdown")
        self.assertEqual(first["pot_layers"], 1)
        self.assertGreater(first["rake_bb"], 0)
        self.assertEqual(len(first["board"]), 5)
        self.assertEqual(len(set(first["board"] + ["As", "Ah"])), 7)

    def test_three_way_short_call_creates_side_pot_through_shared_core(self):
        state = NoLimitHoldemState(
            seats=["Hero", "Short", "BB"],
            button="Hero",
            stacks_bb={"Hero": 10, "Short": 5, "BB": 10},
        )
        state.apply_action("Hero", "RAISE", target_total_bb=10)
        rollout = ModelAPreflopContinuationRollout(
            opponent_policy=three_way_call_policy(),
            hero_hole_cards=["Ks", "Kh"],
            hero_continuation_policy=None,
        )
        result = rollout(
            state,
            actor="Hero",
            seed=991,
            sample_index=0,
            candidate={"id": "SHOVE"},
        )
        self.assertTrue(result["supported"], result.get("reason"))
        self.assertEqual(result["terminal"], "showdown")
        self.assertEqual(result["pot_layers"], 2)
        self.assertGreater(result["rake_bb"], 0)

    def test_missing_exact_response_marks_candidate_unsupported(self):
        state = NoLimitHoldemState(
            seats=["Hero", "Villain"],
            button="Hero",
            stacks_bb={"Hero": 10, "Villain": 10},
        )
        state.apply_action("Hero", "RAISE", target_total_bb=10)
        rollout = ModelAPreflopContinuationRollout(
            opponent_policy=ModelAContinuationPolicy({"nodes": []}, {"nodes": []}),
            hero_hole_cards=["Qs", "Qh"],
            hero_continuation_policy=None,
        )
        result = rollout(
            state,
            actor="Hero",
            seed=7,
            sample_index=0,
            candidate={"id": "SHOVE"},
        )
        self.assertFalse(result["supported"])
        self.assertIn("missing exact preflop", result["reason"])


if __name__ == "__main__":
    unittest.main()
