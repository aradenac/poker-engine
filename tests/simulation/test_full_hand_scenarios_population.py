#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import split_for
from tools.simulation.full_hand_scenarios import build_full_hand_scenario_manifest
from tools.simulation.model_b_runtime import ModelBEnvironment

LEGACY = "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1"


class PopulationFullHandScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = ModelBEnvironment.from_population(LEGACY, ROOT)
        cls.a = build_full_hand_scenario_manifest(
            population_id=LEGACY,
            env=cls.env,
            count=2,
            reps=2,
            master_seed=20260915,
            split="TEST",
            root=ROOT,
        )
        cls.b = build_full_hand_scenario_manifest(
            population_id=LEGACY,
            env=cls.env,
            count=2,
            reps=2,
            master_seed=20260915,
            split="TEST",
            root=ROOT,
        )

    def test_manifest_is_reproducible_and_population_scoped(self):
        self.assertEqual(self.a["scenario_fingerprint_sha256"], self.b["scenario_fingerprint_sha256"])
        self.assertEqual(self.a["population_id"], LEGACY)
        self.assertEqual(self.a["split"], "TEST")
        self.assertEqual(self.a["selected_independent_templates"], 2)
        self.assertEqual(len(self.a["scenarios"]), 4)
        self.assertEqual(self.a["source"]["selection_contract"], "predeal-table-geometry-only")
        self.assertGreater(self.a["eligible_templates"], 2)

    def test_fresh_deals_cover_complete_table_and_do_not_alias_between_reps(self):
        by_cluster = {}
        for row in self.a["scenarios"]:
            self.assertEqual(split_for(row["source_hand_id"]), "TEST")
            self.assertGreaterEqual(len(row["seats"]), 2)
            self.assertLessEqual(len(row["seats"]), 6)
            self.assertEqual(set(row["hole_cards"]), set(row["seats"]))
            self.assertEqual(set(row["stacks_bb"]), set(row["seats"]))
            self.assertEqual(len(row["board"]), 5)
            dealt = [card for player in row["seats"] for card in row["hole_cards"][player]] + row["board"]
            self.assertEqual(len(dealt), len(set(dealt)))
            self.assertIsNone(row["profiles"][row["hero"]])
            for player in row["seats"]:
                if player != row["hero"]:
                    self.assertIn(row["profiles"][player], self.env.profile_ids)
            by_cluster.setdefault(row["cluster_id"], []).append(row)
        self.assertEqual(len(by_cluster), 2)
        for rows in by_cluster.values():
            self.assertEqual(len(rows), 2)
            self.assertNotEqual(rows[0]["scenario_id"], rows[1]["scenario_id"])
            self.assertNotEqual(rows[0]["component_seeds"]["deck"], rows[1]["component_seeds"]["deck"])

    def test_randomness_namespaces_are_explicit(self):
        self.assertEqual(
            set(self.a["randomness_contract"]),
            {"deck", "opponent_actions", "hero_policy", "monte_carlo"},
        )
        for row in self.a["scenarios"]:
            self.assertEqual(
                set(row["component_seeds"]),
                {"deck", "opponent_actions", "hero_policy", "monte_carlo"},
            )


if __name__ == "__main__":
    unittest.main()
