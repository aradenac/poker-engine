#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.full_hand_arena import compare_paired, run_full_hand, summarize_results
from tools.simulation.full_hand_scenarios import materialize_full_hand_scenario


CARDS = {
    "BTN": ["As", "Kd"],
    "SB": ["Qh", "Qc"],
    "BB": ["Js", "Td"],
    "UTG": ["9h", "9c"],
}
BOARD = ["2c", "3d", "4h", "5s", "6c"]


def scenario(*, seats, hero, button, stacks, scenario_id="scenario-1", cluster_id="cluster-1"):
    return {
        "schema": "full-hand-arena-scenario/v1",
        "scenario_id": scenario_id,
        "cluster_id": cluster_id,
        "population_id": "fixture-population",
        "source_hand_id": cluster_id,
        "hero": hero,
        "seats": list(seats),
        "button": button,
        "positions": {name: name for name in seats},
        "stacks_bb": {name: float(stacks[name]) for name in seats},
        "hole_cards": {name: list(CARDS[name]) for name in seats},
        "board": list(BOARD),
        "profiles": {name: (None if name == hero else 0) for name in seats},
        "component_seeds": {"deck": 1, "opponent_actions": 2, "hero_policy": 3, "monte_carlo": 4},
    }


class PassivePolicy:
    def decide(self, state, *, seed_parts, **context):
        legal = state.legal_view(context["actor"])["legal_actions"]
        if "CHECK" in legal:
            return {"action": "CHECK"}
        if "CALL" in legal:
            return {"action": "CALL"}
        return {"action": "FOLD"}


class ScriptThenPassivePolicy(PassivePolicy):
    def __init__(self, script):
        self.script = {actor: list(rows) for actor, rows in script.items()}
        self.index = {actor: 0 for actor in self.script}

    def decide(self, state, *, seed_parts, **context):
        actor = context["actor"]
        rows = self.script.get(actor, [])
        index = self.index.get(actor, 0)
        if index < len(rows):
            self.index[actor] = index + 1
            return dict(rows[index])
        return super().decide(state, seed_parts=seed_parts, **context)


class AuditPolicy(PassivePolicy):
    def __init__(self):
        self.observations = []

    def decide(self, state, *, seed_parts, **context):
        self.observations.append({
            "snapshot": state.to_snapshot(),
            "actor": context["actor"],
            "actor_cards": list(context["hole_cards"]),
            "context_keys": sorted(context),
        })
        return super().decide(state, seed_parts=seed_parts, **context)


class FullHandScenarioTests(unittest.TestCase):
    def test_materialization_is_deterministic_fresh_and_multiway(self):
        template = {
            "population_id": "fixture-population",
            "source_hand_id": "123",
            "big_blind_chips": 200,
            "hero": "BTN",
            "seats": ["BTN", "SB", "BB", "UTG"],
            "button": "BTN",
            "positions": {"BTN": "BTN", "SB": "SB", "BB": "BB", "UTG": "CO"},
            "stacks_bb": {"BTN": 100, "SB": 80, "BB": 40, "UTG": 120},
        }
        kwargs = dict(
            profile_ids=[0, 1],
            profile_weights=[0.7, 0.3],
            player_profiles={"SB": 1},
            master_seed=20260915,
            rep=0,
        )
        a = materialize_full_hand_scenario(template, **kwargs)
        b = materialize_full_hand_scenario(template, **kwargs)
        self.assertEqual(a, b)
        self.assertEqual(a["profiles"]["BTN"], None)
        self.assertEqual(a["profiles"]["SB"], 1)
        dealt = [card for player in a["seats"] for card in a["hole_cards"][player]] + a["board"]
        self.assertEqual(len(dealt), 13)
        self.assertEqual(len(dealt), len(set(dealt)))
        c = materialize_full_hand_scenario(template, **{**kwargs, "rep": 1})
        self.assertNotEqual(a["scenario_id"], c["scenario_id"])
        self.assertNotEqual(a["component_seeds"]["deck"], c["component_seeds"]["deck"])


class FullHandArenaTests(unittest.TestCase):
    def test_preflop_fold_can_end_without_flop(self):
        s = scenario(
            seats=["BTN", "BB"], hero="BTN", button="BTN",
            stacks={"BTN": 100, "BB": 100},
        )
        hero = ScriptThenPassivePolicy({"BTN": [{"action": "FOLD"}]})
        result = run_full_hand(s, hero_policy=hero, opponent_policy=PassivePolicy())
        self.assertEqual(result["settlement"]["terminal"], "fold")
        self.assertEqual(result["coverage"]["terminal_street"], "preflop")
        self.assertFalse(result["coverage"]["reached_flop"])
        self.assertEqual(result["hero_net_bb"], -0.5)
        self.assertEqual(len(result["trace"]), 1)

    def test_multiway_limps_reach_flop_and_complete_hand(self):
        s = scenario(
            seats=["BTN", "SB", "BB"], hero="BTN", button="BTN",
            stacks={"BTN": 100, "SB": 100, "BB": 100},
        )
        result = run_full_hand(s, hero_policy=PassivePolicy(), opponent_policy=PassivePolicy())
        self.assertEqual(result["settlement"]["terminal"], "showdown")
        self.assertTrue(result["coverage"]["multiway_flop"])
        self.assertEqual(result["coverage"]["players_to_flop"], 3)
        self.assertEqual(result["coverage"]["preflop_raises"], 0)
        self.assertEqual(result["coverage"]["preflop_raise_bucket"], "NONE")

    def test_threebet_path_is_exercised(self):
        s = scenario(
            seats=["BTN", "SB", "BB"], hero="BTN", button="BTN",
            stacks={"BTN": 100, "SB": 100, "BB": 100},
        )
        hero = ScriptThenPassivePolicy({
            "BTN": [
                {"action": "RAISE", "target_total_bb": 2.5},
                {"action": "CALL"},
            ]
        })
        opponents = ScriptThenPassivePolicy({
            "SB": [{"action": "RAISE", "target_total_bb": 8.0}],
            "BB": [{"action": "FOLD"}],
        })
        result = run_full_hand(s, hero_policy=hero, opponent_policy=opponents)
        self.assertEqual(result["coverage"]["preflop_raises"], 2)
        self.assertEqual(result["coverage"]["preflop_raise_bucket"], "3BET")
        self.assertEqual(result["coverage"]["players_to_flop"], 2)
        preflop = [(row["actor"], row["action"], row["target_total_bb"]) for row in result["trace"] if row["street"] == "preflop"]
        self.assertEqual(preflop[:4], [
            ("BTN", "RAISE", 2.5),
            ("SB", "RAISE", 8.0),
            ("BB", "FOLD", None),
            ("BTN", "CALL", None),
        ])

    def test_preflop_allins_create_multiway_side_pots(self):
        s = scenario(
            seats=["BTN", "SB", "BB", "UTG"], hero="UTG", button="BTN",
            stacks={"BTN": 20, "SB": 8, "BB": 4, "UTG": 20},
        )
        hero = ScriptThenPassivePolicy({"UTG": [{"action": "ALL_IN"}]})
        result = run_full_hand(s, hero_policy=hero, opponent_policy=PassivePolicy())
        self.assertTrue(result["coverage"]["all_in"])
        self.assertTrue(result["coverage"]["side_pot"])
        self.assertEqual(result["coverage"]["pot_layers"], 3)
        self.assertEqual(result["coverage"]["players_to_flop"], 4)
        self.assertEqual(result["settlement"]["gross_pot_bb"], 52.0)

    def test_policy_receives_no_opponent_cards_or_future_board(self):
        s = scenario(
            seats=["BTN", "SB", "BB"], hero="BTN", button="BTN",
            stacks={"BTN": 100, "SB": 100, "BB": 100},
        )
        hero = AuditPolicy()
        opponents = AuditPolicy()
        run_full_hand(s, hero_policy=hero, opponent_policy=opponents)
        observations = hero.observations + opponents.observations
        self.assertTrue(observations)
        for obs in observations:
            snap = obs["snapshot"]
            serialized = json.dumps(snap, sort_keys=True)
            self.assertNotIn("hole", serialized.lower())
            self.assertEqual(obs["context_keys"], [
                "actor", "hole_cards", "pot_type", "preflop_role", "profile", "relative_position"
            ])
            actor = obs["actor"]
            self.assertEqual(obs["actor_cards"], s["hole_cards"][actor])
            for other in s["seats"]:
                if other == actor:
                    continue
                for card in s["hole_cards"][other]:
                    self.assertNotIn(card, serialized)
            expected_board_len = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[snap["street"]]
            self.assertEqual(len(snap["board"]), expected_board_len)
            for card in s["board"][expected_board_len:]:
                self.assertNotIn(card, serialized)

    def test_replay_is_exact_for_same_scenario_and_stateless_policies(self):
        s = scenario(
            seats=["BTN", "SB", "BB"], hero="BTN", button="BTN",
            stacks={"BTN": 100, "SB": 100, "BB": 100},
        )
        a = run_full_hand(s, hero_policy=PassivePolicy(), opponent_policy=PassivePolicy())
        b = run_full_hand(s, hero_policy=PassivePolicy(), opponent_policy=PassivePolicy())
        self.assertEqual(a, b)

    def test_report_uses_clustered_independent_hand_uncertainty(self):
        rows = []
        for sid, cluster, value, flags in [
            ("a0", "a", 1.0, {"reached_flop": True, "multiway_flop": True, "all_in": False, "side_pot": False, "uncalled_refund": False}),
            ("a1", "a", 3.0, {"reached_flop": True, "multiway_flop": True, "all_in": False, "side_pot": False, "uncalled_refund": False}),
            ("b0", "b", -2.0, {"reached_flop": False, "multiway_flop": False, "all_in": True, "side_pot": True, "uncalled_refund": True}),
            ("b1", "b", 0.0, {"reached_flop": False, "multiway_flop": False, "all_in": True, "side_pot": True, "uncalled_refund": True}),
        ]:
            rows.append({
                "scenario_id": sid,
                "cluster_id": cluster,
                "hero": "Hero",
                "hero_net_bb": value,
                "coverage": {
                    **flags,
                    "table_players": 3,
                    "preflop_raise_bucket": "NONE",
                    "terminal_street": "river" if flags["reached_flop"] else "preflop",
                    "terminal": "showdown" if flags["reached_flop"] else "fold",
                },
            })
        report = summarize_results(rows)
        self.assertEqual(report["simulated_hands"], 4)
        self.assertEqual(report["independent_hands"], 2)
        self.assertEqual(report["bb_per_100_simulated_hands"], 50.0)
        self.assertIsNotNone(report["clustered_se_bb_per_100"])
        self.assertIn("not an observed", report["interpretation"])
        self.assertEqual(report["coverage_counts"]["side_pot"], 2)

        baseline = [{**row, "hero_net_bb": row["hero_net_bb"] - 0.25} for row in rows]
        paired = compare_paired(rows, baseline)
        self.assertEqual(paired["matched_scenarios"], 4)
        self.assertEqual(paired["independent_hands"], 2)
        self.assertAlmostEqual(paired["delta_bb_per_100"], 25.0)


if __name__ == "__main__":
    unittest.main()
