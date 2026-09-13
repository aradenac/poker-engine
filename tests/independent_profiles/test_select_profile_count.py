#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.independent_profiles.select_profile_count import choose_candidate  # noqa: E402


def candidate(k, *, action, range_gain, min_weight, stability):
    return {
        "k": k,
        "action_log_loss_improvement": action,
        "range_log_loss_improvement": range_gain,
        "minimum_profile_weight": min_weight,
        "profile_stability_weighted": stability,
    }


class ProfileCountSelectionTest(unittest.TestCase):
    def test_structural_gates_precede_action_optimization(self):
        rows = [
            candidate(3, action=0.028, range_gain=0.10, min_weight=0.21, stability=0.72),
            candidate(4, action=0.029, range_gain=0.06, min_weight=0.10, stability=0.49),
            candidate(5, action=0.030, range_gain=0.04, min_weight=0.02, stability=0.47),
        ]
        selected, feasible = choose_candidate(
            rows, min_profile_weight=0.05, min_weighted_stability=0.55
        )
        self.assertEqual(selected["k"], 3)
        self.assertEqual([x["k"] for x in feasible], [3])

    def test_fails_when_no_candidate_satisfies_contract(self):
        rows = [candidate(4, action=0.03, range_gain=0.05, min_weight=0.10, stability=0.40)]
        with self.assertRaises(ValueError):
            choose_candidate(rows, min_profile_weight=0.05, min_weighted_stability=0.55)


if __name__ == "__main__":
    unittest.main()
