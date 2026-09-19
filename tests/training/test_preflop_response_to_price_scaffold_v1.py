#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/"training/runs/20260919_model_b_preflop_response_to_price_scaffold_v1"


class ScaffoldScienceContractTests(unittest.TestCase):
    def test_tranche_one_is_synthetic_only_and_has_no_dataset_split(self):
        feature=json.loads((RUN/"FEATURE_CONTRACT.json").read_text())
        graph=json.loads((RUN/"BACKOFF_GRAPH.json").read_text())
        self.assertEqual(feature["status"],"SCAFFOLD_SYNTHETIC_ONLY")
        self.assertEqual(feature["source_policy"]["builder_allowed_source_kind"],"SYNTHETIC_FIXTURE")
        self.assertFalse(feature["source_policy"]["real_train_fit_allowed"])
        self.assertFalse(feature["source_policy"]["validation_allowed"])
        self.assertFalse(feature["source_policy"]["test_allowed"])
        self.assertEqual(graph["fit_status"],"NOT_FINAL_BEFORE_319")
        self.assertFalse(graph["validation_consumed"])
        self.assertFalse(graph["test_consumed"])

    def test_no_promotion_active_pointer_or_108(self):
        feature=json.loads((RUN/"FEATURE_CONTRACT.json").read_text())
        science=feature["scientific_constraints"]
        self.assertFalse(science["performance_claim_allowed"])
        self.assertFalse(science["active_model_b_change_allowed"])
        self.assertFalse(science["automatic_promotion"])
        self.assertEqual(science["production_effect"],"NONE")
        self.assertFalse(science["issue_108_files_modified"])

    def test_fold_call_raise_jam_are_explicit_actions(self):
        feature=json.loads((RUN/"FEATURE_CONTRACT.json").read_text())
        self.assertEqual(feature["actions"],["FOLD","CALL","RAISE","JAM"])

    def test_public_dimension_contract_covers_requested_inputs(self):
        feature=json.loads((RUN/"FEATURE_CONTRACT.json").read_text())
        allowed=set(feature["allowed_input_features"])
        for field in (
            "profile","family","responder_position","raiser_position","sequence",
            "limper_count","hero_raise_size_bb","facing_price_to_pot","effective_stack_bb",
        ):
            self.assertIn(field,allowed)


if __name__=="__main__":
    unittest.main()
