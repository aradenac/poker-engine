#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.simulation.model_b_preflop_price_diagnostics import (
    build_from_fixture,
    counterfactual_report,
    expand_fixture,
)
from tools.simulation.model_b_preflop_response_to_price import (
    ACTIONS,
    HIERARCHY,
    PreflopResponseToPriceModel,
    artifact_sha256,
    build_synthetic_artifact,
    price_bucket,
    raise_size_bucket,
)

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/"training/runs/20260919_model_b_preflop_response_to_price_scaffold_v1"
FIXTURE=ROOT/"tests/fixtures/model_b_preflop_response_to_price/scenario_4bb_vs_6bb.json"


def load(path):
    return json.loads(path.read_text())


def base_row(i, *, family="ISO_OVER_LIMPERS", pos="BB", size=4.0, price=0.55, action="CALL"):
    return {
        "source_kind":"SYNTHETIC_FIXTURE",
        "hand_id":f"h{i}",
        "profile":"P0",
        "family":family,
        "responder_position":pos,
        "raiser_position":"SB",
        "sequence":"CO_LIMP>BTN_LIMP>SB_ISO",
        "limper_count":2,
        "hero_raise_size_bb":size,
        "facing_price_to_pot":price,
        "effective_stack_bb":100,
        "action":action,
    }


class ContractTests(unittest.TestCase):
    def test_4bb_and_6bb_have_distinct_public_price_buckets(self):
        self.assertNotEqual(raise_size_bucket(4),raise_size_bucket(6))
        self.assertNotEqual(price_bucket(0.55),price_bucket(0.85))

    def test_graph_matches_runtime_hierarchy_and_never_drops_family(self):
        graph=load(RUN/"BACKOFF_GRAPH.json")
        self.assertEqual([tuple(x["dimensions"]) for x in graph["levels"]],list(HIERARCHY))
        self.assertTrue(all("family" in level for level in HIERARCHY))
        self.assertTrue(graph["no_cross_family_pooling"])
        self.assertFalse(graph["nearest_context_heuristic"])

    def test_feature_contract_forbids_model_a_ev_recommendations(self):
        c=load(RUN/"FEATURE_CONTRACT.json")
        forbidden=set(c["forbidden_features"])
        self.assertIn("model_a_ev",forbidden)
        self.assertIn("model_a_recommendation",forbidden)
        self.assertIn("hero_ev",forbidden)
        self.assertFalse(c["source_policy"]["validation_allowed"])
        self.assertFalse(c["source_policy"]["test_allowed"])
        self.assertFalse(c["source_policy"]["real_train_fit_allowed"])


class BuilderRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.graph=load(RUN/"BACKOFF_GRAPH.json")
        self.fixture=load(FIXTURE)
        self.rows=expand_fixture(self.fixture)
        self.doc=build_from_fixture(self.fixture,self.graph)
        self.model=PreflopResponseToPriceModel(self.doc)

    def test_fixture_artifact_is_deterministic_and_synthetic_only(self):
        a=build_from_fixture(self.fixture,self.graph)
        b=build_from_fixture(copy.deepcopy(self.fixture),self.graph)
        self.assertEqual(artifact_sha256(a),artifact_sha256(b))
        self.assertEqual(a["source_kind"],"SYNTHETIC_FIXTURE")
        self.assertEqual(a["fit_status"],"NOT_FINAL_BEFORE_319")
        self.assertFalse(a["validation_consumed"])
        self.assertFalse(a["test_consumed"])
        self.assertFalse(a["performance_claim_allowed"])
        self.assertEqual(a["production_effect"],"NONE")

    def test_builder_rejects_real_or_dataset_split_inputs(self):
        bad=base_row(1)
        bad["source_kind"]="TRAIN"
        with self.assertRaisesRegex(ValueError,"SYNTHETIC_FIXTURE only"):
            build_synthetic_artifact([bad],graph=self.graph)
        bad=base_row(2)
        bad["dataset_split"]="VALIDATION"
        with self.assertRaisesRegex(ValueError,"dataset splits are forbidden"):
            build_synthetic_artifact([bad],graph=self.graph)
        bad=base_row(3)
        bad["dataset_split"]="TEST"
        with self.assertRaisesRegex(ValueError,"dataset splits are forbidden"):
            build_synthetic_artifact([bad],graph=self.graph)

    def test_runtime_rejects_model_a_ev_and_recommendation_features(self):
        probe={k:v for k,v in self.rows[0].items() if k not in {"action","hand_id","source_kind","variant_id"}}
        with self.assertRaisesRegex(ValueError,"forbidden"):
            self.model.predict(**probe,model_a_ev=1.0)
        with self.assertRaisesRegex(ValueError,"forbidden"):
            self.model.predict(**probe,recommended_action="RAISE")

    def test_probabilities_include_fold_call_raise_jam_and_sum_to_one(self):
        probe={k:v for k,v in self.rows[0].items() if k not in {"action","hand_id","source_kind","variant_id"}}
        p=self.model.predict(**probe)
        self.assertEqual(tuple(p["probabilities"]),ACTIONS)
        self.assertAlmostEqual(sum(p["probabilities"].values()),1.0,places=12)
        self.assertEqual(p["effective_support"]["source_kind"],"SYNTHETIC_FIXTURE")
        self.assertEqual(p["production_effect"],"NONE")

    def test_explicit_backoff_uses_support_and_stays_within_family(self):
        rows=[]
        for i in range(10):
            rows.append(base_row(i,pos="BB",action="CALL"))
        for i in range(15):
            rows.append(base_row(100+i,pos="CO",action="FOLD"))
        doc=build_synthetic_artifact(rows,graph=self.graph)
        model=PreflopResponseToPriceModel(doc)
        p=model.predict(**{k:v for k,v in base_row(999,pos="BB").items() if k not in {"action","hand_id","source_kind"}})
        self.assertGreater(p["selected_level"]["index"],0)
        self.assertEqual(p["fallback_reason"],"DECLARED_SYNTHETIC_BACKOFF")
        self.assertTrue(any(x["reason"]=="INSUFFICIENT_SYNTHETIC_SUPPORT" for x in p["failed_finer_levels"]))
        missing={k:v for k,v in base_row(1000,family="VS_RFI").items() if k not in {"action","hand_id","source_kind"}}
        with self.assertRaises(KeyError):
            model.predict(**missing)

    def test_fixture_exact_contexts_have_explicit_support(self):
        report=counterfactual_report(self.model,self.fixture)
        for variant in report["variants"].values():
            for responder in variant["responders"]:
                self.assertEqual(responder["selected_level"]["index"],0)
                self.assertEqual(responder["fallback_reason"],"EXACT_SYNTHETIC_CONTEXT_SUPPORTED")
                self.assertGreaterEqual(responder["effective_support"]["observations"],20)
                self.assertGreaterEqual(responder["effective_support"]["distinct_hands"],12)


class CounterfactualTests(unittest.TestCase):
    def test_6bb_synthetic_fixture_increases_fold_and_reduces_continuers(self):
        fixture=load(FIXTURE)
        graph=load(RUN/"BACKOFF_GRAPH.json")
        model=PreflopResponseToPriceModel(build_from_fixture(fixture,graph))
        report=counterfactual_report(model,fixture)
        self.assertFalse(report["validation_consumed"])
        self.assertFalse(report["test_consumed"])
        self.assertFalse(report["performance_claim_allowed"])
        self.assertEqual(report["production_effect"],"NONE")
        for delta in report["responder_deltas"]:
            self.assertGreater(delta["high_minus_low"]["probabilities"]["FOLD"],0)
            self.assertLess(delta["high_minus_low"]["probabilities"]["CALL"],0)
            self.assertLess(delta["high_minus_low"]["continue_probability"],0)
        agg=report["aggregate_high_minus_low"]
        self.assertLess(agg["synthetic_expected_continuers"],0)
        self.assertGreater(agg["synthetic_all_fold_probability"],0)


if __name__=="__main__":
    unittest.main()
