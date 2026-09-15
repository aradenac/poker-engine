#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.full_hand_arena import compare_paired


def row(sid: str, cluster: str = "c", hero: str = "Hero", net: float = 0.0) -> dict:
    return {"scenario_id": sid, "cluster_id": cluster, "hero": hero, "hero_net_bb": net}


class StrictPairedComparisonTests(unittest.TestCase):
    def test_requires_exact_scenario_set(self):
        with self.assertRaisesRegex(ValueError, "identical scenario_id sets"):
            compare_paired([row("a"), row("b")], [row("a")])
        with self.assertRaisesRegex(ValueError, "identical scenario_id sets"):
            compare_paired([row("a")], [row("a"), row("b")])

    def test_rejects_duplicate_ids_on_either_side(self):
        with self.assertRaisesRegex(ValueError, "candidate contains duplicate"):
            compare_paired([row("a"), row("a")], [row("a")])
        with self.assertRaisesRegex(ValueError, "baseline contains duplicate"):
            compare_paired([row("a")], [row("a"), row("a")])

    def test_requires_same_scenario_identity(self):
        with self.assertRaisesRegex(ValueError, "cluster_id mismatch"):
            compare_paired([row("a", cluster="x")], [row("a", cluster="y")])
        with self.assertRaisesRegex(ValueError, "hero mismatch"):
            compare_paired([row("a", hero="Hero")], [row("a", hero="Other")])

    def test_exact_pairing_reports_all_rows(self):
        candidate = [row("a", "x", net=1.0), row("b", "y", net=2.0)]
        baseline = [row("b", "y", net=1.5), row("a", "x", net=0.5)]
        report = compare_paired(candidate, baseline)
        self.assertEqual(report["matched_scenarios"], 2)
        self.assertEqual(report["independent_hands"], 2)
        self.assertAlmostEqual(report["delta_bb_per_100"], 50.0)


if __name__ == "__main__":
    unittest.main()
