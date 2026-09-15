#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.full_hand_arena import run_full_hand


class CapturePassivePolicy:
    def __init__(self):
        self.calls = []

    def decide(self, state, *, seed_parts, **context):
        self.calls.append((context["actor"], tuple(seed_parts)))
        legal = state.legal_view(context["actor"])["legal_actions"]
        if "CHECK" in legal:
            return {"action": "CHECK"}
        if "CALL" in legal:
            return {"action": "CALL"}
        return {"action": "FOLD"}


class FullHandArenaSeedContractTests(unittest.TestCase):
    def scenario(self):
        return {
            "schema": "full-hand-arena-scenario/v1",
            "scenario_id": "seed-contract-scenario",
            "cluster_id": "seed-contract-cluster",
            "population_id": "fixture-population",
            "hero": "BTN",
            "seats": ["BTN", "SB", "BB"],
            "button": "BTN",
            "positions": {"BTN": "BTN", "SB": "SB", "BB": "BB"},
            "stacks_bb": {"BTN": 100.0, "SB": 100.0, "BB": 100.0},
            "hole_cards": {
                "BTN": ["As", "Kd"],
                "SB": ["Qh", "Qc"],
                "BB": ["Js", "Td"],
            },
            "board": ["2c", "3d", "4h", "5s", "6c"],
            "profiles": {"BTN": None, "SB": 0, "BB": 1},
            "component_seeds": {
                "deck": 1001,
                "opponent_actions": 2002,
                "hero_policy": 3003,
                "monte_carlo": 4004,
            },
        }

    def test_hero_and_opponents_receive_their_persisted_seed_namespace(self):
        scenario = self.scenario()
        hero = CapturePassivePolicy()
        opponents = CapturePassivePolicy()
        result = run_full_hand(scenario, hero_policy=hero, opponent_policy=opponents)

        self.assertTrue(hero.calls)
        self.assertTrue(opponents.calls)
        for actor, seed_parts in hero.calls:
            self.assertEqual(actor, "BTN")
            self.assertEqual(seed_parts[0], scenario["scenario_id"])
            self.assertEqual(seed_parts[1], scenario["component_seeds"]["hero_policy"])
            self.assertEqual(seed_parts[2], "hero")
        for actor, seed_parts in opponents.calls:
            self.assertNotEqual(actor, "BTN")
            self.assertEqual(seed_parts[0], scenario["scenario_id"])
            self.assertEqual(seed_parts[1], scenario["component_seeds"]["opponent_actions"])
            self.assertEqual(seed_parts[2], "opponent")

        for row in result["trace"]:
            expected_key = "hero_policy" if row["actor"] == "BTN" else "opponent_actions"
            self.assertEqual(row["decision_seed_namespace"], expected_key)
            self.assertEqual(row["seed_parts"][1], scenario["component_seeds"][expected_key])

    def test_missing_or_extra_seed_namespace_is_rejected(self):
        scenario = self.scenario()
        del scenario["component_seeds"]["monte_carlo"]
        with self.assertRaisesRegex(ValueError, "component_seeds"):
            run_full_hand(scenario, hero_policy=CapturePassivePolicy(), opponent_policy=CapturePassivePolicy())

        scenario = self.scenario()
        scenario["component_seeds"]["unexpected"] = 5
        with self.assertRaisesRegex(ValueError, "component_seeds"):
            run_full_hand(scenario, hero_policy=CapturePassivePolicy(), opponent_policy=CapturePassivePolicy())


if __name__ == "__main__":
    unittest.main()
