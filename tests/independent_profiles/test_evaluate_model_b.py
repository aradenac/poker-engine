#!/usr/bin/env python3
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.independent_profiles.evaluate_model_b import (  # noqa: E402
    action_probabilities,
    choose_node,
    range_probability,
)


class ModelBEvaluationContractTest(unittest.TestCase):
    def test_action_probability_normalizes_legal_mode_labels(self):
        mixed = {
            "n": 100,
            "counts": {"CHECK": 40, "BET": 10, "FOLD": 20, "CALL": 25, "RAISE": 5},
        }
        free = action_probabilities(mixed, ["CHECK", "BET"], 1.0)
        facing = action_probabilities(mixed, ["FOLD", "CALL", "RAISE"], 1.0)
        self.assertAlmostEqual(sum(free.values()), 1.0)
        self.assertAlmostEqual(sum(facing.values()), 1.0)
        self.assertAlmostEqual(free["CHECK"], 41 / 52)
        self.assertAlmostEqual(facing["CALL"], 26 / 53)

    def test_choose_node_uses_finest_sufficient_then_fallback(self):
        levels = [
            {"cols": ["profile", "street"], "data": {"1|flop": {"n": 5, "counts": {"BET": 5}}}},
            {"cols": ["street"], "data": {"flop": {"n": 50, "counts": {"BET": 20, "CHECK": 30}}}},
            {"cols": [], "data": {"ALL": {"n": 100, "counts": {"BET": 40, "CHECK": 60}}}},
        ]
        node, level, key = choose_node(levels, {"profile": 1, "street": "flop"}, 20)
        self.assertEqual(level, 1)
        self.assertEqual(key, "flop")
        self.assertEqual(node["n"], 50)
        node, level, key = choose_node(levels, {"profile": 2, "street": "turn"}, 20)
        self.assertEqual(level, 2)
        self.assertEqual(key, "ALL")
        self.assertEqual(node["n"], 100)

    def test_range_probability_uses_combinatorial_prior(self):
        multiplicity = {"AA": 6, "AKs": 4, "AKo": 12}
        node = {"n": 0, "counts": {}}
        aa = range_probability(node, "AA", multiplicity, 50.0)
        aks = range_probability(node, "AKs", multiplicity, 50.0)
        ako = range_probability(node, "AKo", multiplicity, 50.0)
        self.assertAlmostEqual(aa, 6 / 1326)
        self.assertAlmostEqual(aks, 4 / 1326)
        self.assertAlmostEqual(ako, 12 / 1326)
        self.assertTrue(all(math.isfinite(x) and x > 0 for x in (aa, aks, ako)))


if __name__ == "__main__":
    unittest.main()
