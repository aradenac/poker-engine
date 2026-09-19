#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.model_b_price_response import HIERARCHY
from tools.training.independent_profiles.evaluate_support_aware_backoff_v1 import select_split


class Record:
    def __init__(self, hand_id):
        self.hand_id = hand_id


class ProtocolTests(unittest.TestCase):
    def test_protocol_and_graph_are_frozen_before_validation(self):
        root = ROOT / "training/runs/20260919_model_b_support_aware_backoff_v1"
        protocol = json.loads((root / "PROTOCOL.json").read_text())
        graph = json.loads((root / "BACKOFF_GRAPH.json").read_text())
        self.assertEqual(protocol["status"], "FROZEN_BEFORE_VALIDATION")
        self.assertEqual(protocol["split_contract"]["fit"], ["TRAIN"])
        self.assertEqual(protocol["split_contract"]["evaluate"], ["VALIDATION"])
        self.assertEqual(protocol["split_contract"]["forbidden"], ["TEST"])
        self.assertFalse(protocol["split_contract"]["test_consumed"])
        self.assertFalse(protocol["scientific_constraints"]["hyperparameters_selected_on_validation"])
        self.assertEqual(protocol["scientific_constraints"]["production_effect"], "NONE")
        self.assertFalse(protocol["scientific_constraints"]["automatic_promotion"])
        self.assertEqual([x["dimensions"] for x in graph["levels"]], [list(x) for x in HIERARCHY])
        self.assertTrue(graph["frozen_before_validation"])
        self.assertFalse(graph["nearest_context_heuristic"])

    def test_thresholds_match_protocol_and_graph(self):
        root = ROOT / "training/runs/20260919_model_b_support_aware_backoff_v1"
        protocol = json.loads((root / "PROTOCOL.json").read_text())
        graph = json.loads((root / "BACKOFF_GRAPH.json").read_text())
        self.assertEqual(protocol["method"]["action_min_observations"], graph["action_support"]["min_observations"])
        self.assertEqual(protocol["method"]["action_min_distinct_hands"], graph["action_support"]["min_distinct_hands"])
        self.assertEqual(protocol["method"]["sizing_min_raises"], graph["sizing_support"]["min_raises"])
        self.assertEqual(protocol["method"]["sizing_min_distinct_hands"], graph["sizing_support"]["min_distinct_hands"])

    def test_select_split_fail_closed_for_test(self):
        records = [Record("a")]
        with self.assertRaisesRegex(ValueError, "only TRAIN and VALIDATION"):
            select_split(records, "TEST")

    def test_source_197_and_272_are_test_unconsumed(self):
        r197 = json.loads((ROOT / "training/runs/20260919_model_b_response_to_price_v1/RESULT.json").read_text())
        p272 = json.loads((ROOT / "training/runs/20260919_model_b_observed_vs_simulated_calibration_v1/PROTOCOL.json").read_text())
        self.assertFalse(r197["test_consumed"])
        self.assertFalse(p272["split_contract"]["test_consumed"])

    def test_no_model_a_or_production_features_in_protocol(self):
        protocol = json.loads((ROOT / "training/runs/20260919_model_b_support_aware_backoff_v1/PROTOCOL.json").read_text())
        self.assertFalse(protocol["scientific_constraints"]["model_a_features_allowed"])
        self.assertFalse(protocol["scientific_constraints"]["active_model_b_change_allowed"])
        self.assertEqual(protocol["scientific_constraints"]["production_effect"], "NONE")


if __name__ == "__main__":
    unittest.main()
