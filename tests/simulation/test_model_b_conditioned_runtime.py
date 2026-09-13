#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.model_b_conditioned_runtime import (  # noqa: E402
    ConditionedModelBEnvironment,
    price_bucket,
)


CANDIDATE = ROOT / "training/runs/20260913_model_b_response_v3/selected_candidate/model"
INCUMBENT = ROOT / "training/runs/20260912_independent_profiles_v2/model"


class PriceBucketTests(unittest.TestCase):
    def test_boundaries_match_training_contract(self):
        self.assertEqual(price_bucket(0.25), "P00_25")
        self.assertEqual(price_bucket(0.50), "P25_50")
        self.assertEqual(price_bucket(0.75), "P50_75")
        self.assertEqual(price_bucket(1.00), "P75_100")
        self.assertEqual(price_bucket(1.50), "P100_150")
        self.assertEqual(price_bucket(1.51), "P150_PLUS")
        self.assertEqual(price_bucket(None), "UNKNOWN")


class ConditionedRuntimeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candidate = ConditionedModelBEnvironment(CANDIDATE)
        cls.incumbent = ConditionedModelBEnvironment(INCUMBENT, alias="independent_model_b_v2")

    def _context(self):
        return dict(
            profile=0,
            street="flop",
            mode="FACING",
            relative_position="OOP",
            pot_type="SRP",
            preflop_role="PFA",
        )

    def test_candidate_loads_v3_contract(self):
        self.assertEqual(self.candidate.actions["schema"], "independent-postflop-actions/v3-conditioned")
        self.assertEqual(self.candidate.sizing["schema"], "independent-postflop-sizing/v3-conditioned")
        self.assertEqual(self.candidate.contract["schema"], "independent-opponent-model-b-prediction-contract/v2")
        self.assertEqual(self.candidate.actions["conditioning_dimensions"], ["price_bucket"])

    def test_price_changes_candidate_response(self):
        ctx = self._context()
        probes = [0.20, 0.40, 0.60, 0.90, 1.25, 1.75]
        folds = [self.candidate.action_probabilities(**ctx, facing_price_to_pot=x)["FOLD"] for x in probes]
        self.assertGreater(max(folds) - min(folds), 1e-4, folds)
        for x in probes:
            probs = self.candidate.action_probabilities(**ctx, facing_price_to_pot=x)
            self.assertAlmostEqual(sum(probs.values()), 1.0, places=12)

    def test_incumbent_adapter_remains_price_invariant(self):
        ctx = self._context()
        low = self.incumbent.action_probabilities(**ctx, facing_price_to_pot=0.20)
        high = self.incumbent.action_probabilities(**ctx, facing_price_to_pot=1.75)
        self.assertEqual(low, high)

    def test_candidate_sizing_uses_same_price_contract(self):
        values = self.candidate.sizing_values(
            profile=0,
            street="flop",
            mode="FACING",
            action="RAISE",
            pot_type="SRP",
            facing_price_to_pot=0.50,
        )
        self.assertTrue(values)
        self.assertTrue(all(x > 0 for x in values))


if __name__ == "__main__":
    unittest.main()
