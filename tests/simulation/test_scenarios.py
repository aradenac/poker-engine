#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEGACY = "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1"
CANDIDATE = ROOT / "training/runs/20260913_model_b_response_v3/selected_candidate/model"
sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import split_for  # noqa: E402
from tools.simulation.model_b_conditioned_runtime import ConditionedModelBEnvironment  # noqa: E402
from tools.simulation.model_b_runtime import ModelBEnvironment  # noqa: E402
from tools.simulation.retarget_scenario_manifest import retarget_manifest  # noqa: E402
from tools.simulation.scenarios import build_scenario_manifest  # noqa: E402


class ScenarioIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = ModelBEnvironment.from_population(LEGACY, ROOT)
        cls.a = build_scenario_manifest(
            population_id=LEGACY,
            env=cls.env,
            count=3,
            reps=2,
            master_seed=20260912,
            split="TEST",
            root=ROOT,
        )
        cls.b = build_scenario_manifest(
            population_id=LEGACY,
            env=cls.env,
            count=3,
            reps=2,
            master_seed=20260912,
            split="TEST",
            root=ROOT,
        )

    def test_manifest_is_deterministic(self):
        self.assertEqual(self.a["scenario_fingerprint_sha256"], self.b["scenario_fingerprint_sha256"])
        compact_a = [
            (x["scenario_id"], x["hand_id"], x["rep"], x["profile"], x["opponent_cards"], x["runout"])
            for x in self.a["scenarios"]
        ]
        compact_b = [
            (x["scenario_id"], x["hand_id"], x["rep"], x["profile"], x["opponent_cards"], x["runout"])
            for x in self.b["scenarios"]
        ]
        self.assertEqual(compact_a, compact_b)

    def test_requested_shape_and_test_split(self):
        self.assertEqual(len(self.a["scenarios"]), 6)
        self.assertEqual(self.a["split"], "TEST")
        self.assertEqual(self.a["population_id"], LEGACY)
        self.assertEqual(self.a["cache_namespace"], LEGACY)
        self.assertGreater(self.a["eligible_hands"], 0)
        for scenario in self.a["scenarios"]:
            self.assertEqual(split_for(scenario["hand_id"]), "TEST")
            self.assertEqual(len(scenario["flop"]), 3)
            self.assertEqual(len(scenario["runout"]), 2)
            self.assertEqual(len(scenario["opponent_cards"]), 2)
            self.assertEqual(len(scenario["postflop_order"]), 2)
            self.assertEqual(set(scenario["postflop_order"]), {scenario["hero"], scenario["opponent"]})
            self.assertNotEqual(scenario["hero"], scenario["opponent"])
            self.assertGreater(scenario["flop_pot_bb"], 0)

    def test_model_b_population_mismatch_is_rejected(self):
        wrong = ModelBEnvironment(self.env.model_dir, alias="fixture", population_id="other_population")
        with self.assertRaisesRegex(ValueError, "Model B population mismatch"):
            build_scenario_manifest(
                population_id=LEGACY, env=wrong, count=1, reps=1, master_seed=1, split="TEST", root=ROOT
            )

    def test_retarget_preserves_population_and_scenario_identity(self):
        target = ConditionedModelBEnvironment(CANDIDATE, population_id=LEGACY)
        out = retarget_manifest(self.a, self.env, target)
        self.assertEqual(out["population_id"], LEGACY)
        self.assertEqual(out["cache_namespace"], LEGACY)
        self.assertEqual(out["scenario_fingerprint_sha256"], self.a["scenario_fingerprint_sha256"])
        self.assertEqual(out["scenarios"], self.a["scenarios"])
        self.assertEqual(out["scenario_materialization_provenance"]["population_id"], LEGACY)
        self.assertTrue(out["scenario_materialization_provenance"]["scenario_fingerprint_unchanged"])

    def test_retarget_cross_population_model_is_rejected(self):
        wrong_target = ConditionedModelBEnvironment(CANDIDATE, population_id="other_population")
        with self.assertRaisesRegex(ValueError, "target Model B population mismatch"):
            retarget_manifest(self.a, self.env, wrong_target)

    def test_cards_are_unique(self):
        for scenario in self.a["scenarios"]:
            cards = scenario["hero_cards"] + scenario["opponent_cards"] + scenario["flop"] + scenario["runout"]
            self.assertEqual(len(cards), len(set(cards)))

    def test_profile_is_from_promoted_model(self):
        valid = set(self.env.profile_ids)
        for scenario in self.a["scenarios"]:
            self.assertIn(scenario["profile"], valid)


if __name__ == "__main__":
    unittest.main()
