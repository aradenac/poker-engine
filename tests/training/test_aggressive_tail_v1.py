#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))

from tools.simulation.model_b_price_response import HIERARCHY
from tools.training.independent_profiles.evaluate_aggressive_tail_v1 import select_split


class Record:
    def __init__(self,hand_id):
        self.hand_id=hand_id


class ProtocolTests(unittest.TestCase):
    def test_protocol_is_frozen_before_validation(self):
        root=ROOT/"training/runs/20260919_model_b_aggressive_tail_v1"
        p=json.loads((root/"PROTOCOL.json").read_text())
        g=json.loads((root/"TAIL_GRAPH.json").read_text())
        self.assertEqual(p["status"],"FROZEN_BEFORE_VALIDATION")
        self.assertEqual(p["split_contract"]["fit"],["TRAIN"])
        self.assertEqual(p["split_contract"]["evaluate"],["VALIDATION"])
        self.assertEqual(p["split_contract"]["forbidden"],["TEST"])
        self.assertFalse(p["split_contract"]["test_consumed"])
        self.assertFalse(p["scientific_constraints"]["hyperparameters_selected_on_validation"])
        self.assertEqual(p["scientific_constraints"]["production_effect"],"NONE")
        self.assertFalse(p["scientific_constraints"]["automatic_promotion"])
        self.assertFalse(p["scientific_constraints"]["active_model_b_change_allowed"])
        self.assertEqual([x["dimensions"] for x in g["levels"]],[list(x) for x in HIERARCHY])
        self.assertTrue(g["frozen_before_validation"])
        self.assertFalse(g["nearest_context_heuristic"])
        self.assertFalse(g["silent_pooling"])

    def test_tail_thresholds_are_inherited_and_frozen(self):
        root=ROOT/"training/runs/20260919_model_b_aggressive_tail_v1"
        p=json.loads((root/"PROTOCOL.json").read_text())
        g=json.loads((root/"TAIL_GRAPH.json").read_text())
        self.assertEqual(p["method"]["tail_min_raises"],12)
        self.assertEqual(p["method"]["tail_min_distinct_hands"],8)
        self.assertEqual(p["method"]["tail_min_raises"],g["tail_support"]["min_raises"])
        self.assertEqual(p["method"]["tail_min_distinct_hands"],g["tail_support"]["min_distinct_hands"])
        self.assertEqual(p["method"]["alpha_per_tail_class"],0.5)

    def test_action_and_sizing_are_declared_unchanged_from_286(self):
        p=json.loads((ROOT/"training/runs/20260919_model_b_aggressive_tail_v1/PROTOCOL.json").read_text())
        self.assertEqual(p["representation"]["action_distribution"],"DELEGATE_UNCHANGED_TO_ISSUE_286")
        self.assertEqual(p["representation"]["sizing_distribution"],"DELEGATE_UNCHANGED_TO_ISSUE_286")

    def test_select_split_rejects_test(self):
        with self.assertRaisesRegex(ValueError,"only TRAIN and VALIDATION"):
            select_split([Record("x")],"TEST")

    def test_upstream_science_is_test_unconsumed(self):
        r197=json.loads((ROOT/"training/runs/20260919_model_b_response_to_price_v1/RESULT.json").read_text())
        r286=json.loads((ROOT/"training/runs/20260919_model_b_support_aware_backoff_v1/RESULT.json").read_text())
        self.assertFalse(r197["test_consumed"])
        self.assertFalse(r286["test_consumed"])
        self.assertFalse(r286["active_model_b_changed"])

    def test_no_model_a_hero_ev_or_108_scope(self):
        p=json.loads((ROOT/"training/runs/20260919_model_b_aggressive_tail_v1/PROTOCOL.json").read_text())
        s=p["scientific_constraints"]
        self.assertFalse(s["model_a_features_allowed"])
        self.assertFalse(s["hero_or_ev_features_allowed"])
        self.assertFalse(s["issue_108_files_modified"])


if __name__=="__main__":
    unittest.main()
