#!/usr/bin/env python3
from __future__ import annotations

import math
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEGACY = "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1"
sys.path.insert(0, str(ROOT))

from tools.simulation.model_b_runtime import (  # noqa: E402
    ModelBEnvironment,
    best,
    cid,
    ccode,
    combo_class,
    hseed,
    legal_combos,
    rake_net,
)


class CardRuntimeTests(unittest.TestCase):
    def test_card_roundtrip(self):
        for card in ("2s", "Ah", "Tc", "Kd"):
            self.assertEqual(ccode(cid(card)), card[0].upper() + card[1].lower())

    def test_combo_class(self):
        self.assertEqual(combo_class(["As", "Ah"]), "AA")
        self.assertEqual(combo_class(["As", "Ks"]), "AKs")
        self.assertEqual(combo_class(["As", "Kh"]), "AKo")

    def test_legal_combo_count(self):
        combos = legal_combos(["As", "Kd"], ["2c", "3h", "4s"])
        self.assertEqual(len(combos), 1081)  # C(47,2)

    def test_hand_ranking(self):
        straight_flush = best(["As", "Ks", "Qs", "Js", "Ts", "2d", "3c"])
        quads = best(["Ah", "Ad", "Ac", "As", "Kd", "2c", "3c"])
        full_house = best(["Kh", "Kd", "Kc", "2s", "2d", "3c", "4c"])
        self.assertGreater(straight_flush, quads)
        self.assertGreater(quads, full_house)

    def test_rake_contract(self):
        self.assertAlmostEqual(rake_net(10), 9.45)
        self.assertAlmostEqual(rake_net(1000), 986.075)

    def test_hash_seed_is_deterministic(self):
        self.assertEqual(hseed("x", 1, 2), hseed("x", 1, 2))
        self.assertNotEqual(hseed("x", 1, 2), hseed("x", 1, 3))


class PromotedModelBIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = ModelBEnvironment.from_population(LEGACY, ROOT)

    def test_promoted_model_loads(self):
        self.assertEqual(self.env.alias, "independent_model_b_v2")
        self.assertEqual(self.env.population_id, LEGACY)
        self.assertEqual(len(self.env.profile_ids), 3)
        self.assertAlmostEqual(sum(self.env.profile_weights), 1.0, places=9)

    def test_implicit_global_registry_selection_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "population_id is required"):
            ModelBEnvironment.from_registry(ROOT)

    def test_action_probabilities_are_legal_and_normalized(self):
        free = self.env.action_probabilities(
            profile=0,
            street="flop",
            mode="FREE",
            relative_position="OOP",
            pot_type="SRP",
            preflop_role="PFA",
        )
        self.assertEqual(set(free), {"CHECK", "BET"})
        self.assertAlmostEqual(sum(free.values()), 1.0, places=12)

        facing = self.env.action_probabilities(
            profile=1,
            street="turn",
            mode="FACING",
            relative_position="IP",
            pot_type="LIMPED",
            preflop_role="LIMPER",
            can_raise=False,
        )
        self.assertEqual(set(facing), {"FOLD", "CALL", "RAISE"})
        self.assertEqual(facing["RAISE"], 0.0)
        self.assertAlmostEqual(sum(facing.values()), 1.0, places=12)

    def test_range_is_normalized_and_deterministic(self):
        combos, weights = self.env.range_combos(
            0, "BTN", "SRP", "PFA", ["As", "Kd"], ["2c", "7h", "Ts"]
        )
        self.assertEqual(len(combos), 1081)
        self.assertAlmostEqual(sum(weights), 1.0, places=12)
        self.assertTrue(all(math.isfinite(x) and x >= 0 for x in weights))
        a = self.env.sample_hole_cards(
            0, "BTN", "SRP", "PFA", ["As", "Kd"], ["2c", "7h", "Ts"], "fixture", 17
        )
        b = self.env.sample_hole_cards(
            0, "BTN", "SRP", "PFA", ["As", "Kd"], ["2c", "7h", "Ts"], "fixture", 17
        )
        self.assertEqual(a, b)

    def test_sizing_sampling_is_deterministic(self):
        context = dict(profile=0, street="flop", mode="FREE", action="BET", pot_type="SRP")
        a = self.env.sample_sizing(seed_parts=("size", 99), **context)
        b = self.env.sample_sizing(seed_parts=("size", 99), **context)
        self.assertEqual(a, b)
        self.assertGreater(a, 0)


class RobustnessBackendIntegrationTests(unittest.TestCase):
    def test_issue_199_robustness_unit_matrix(self):
        subprocess.run(
            [sys.executable, str(ROOT / "tests/simulation/test_model_b_robustness.py")],
            cwd=ROOT,
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
