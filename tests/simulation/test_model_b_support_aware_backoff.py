#!/usr/bin/env python3
from __future__ import annotations

import copy
import unittest

from tools.simulation.model_b_price_response import HIERARCHY
from tools.simulation.model_b_support_aware_backoff import (
    SupportAwareBackoffModel,
    artifact_sha256,
    build_artifact,
)


def graph():
    return {
        "schema": "model-b-support-aware-backoff-graph/v1",
        "version": "2026-09-19.1",
        "source_split": "TRAIN",
        "frozen_before_validation": True,
        "action_support": {"min_observations": 30, "min_distinct_hands": 20},
        "sizing_support": {"min_raises": 12, "min_distinct_hands": 8},
        "levels": [
            {"index": i, "dimensions": list(level)}
            for i, level in enumerate(HIERARCHY)
        ],
    }


def obs(i, *, sequence="BET", pos="IP", action="CALL", sizing=None):
    row = {
        "hand_id": f"h{i}",
        "source_split": "TRAIN",
        "profile": 0,
        "street": "flop",
        "relative_position": pos,
        "pot_type": "SRP",
        "sequence": sequence,
        "facing_price_to_pot": 0.5,
        "spr": 3.0,
        "action": action,
    }
    if sizing is not None:
        row["raise_sizing_ratio"] = sizing
    return row


class ArtifactTests(unittest.TestCase):
    def test_artifact_is_deterministic_and_train_only(self):
        rows = [obs(i, action=("FOLD","CALL","RAISE")[i % 3], sizing=1.0 if i % 3 == 2 else None) for i in range(60)]
        a = build_artifact(rows, graph=graph())
        b = build_artifact(copy.deepcopy(rows), graph=graph())
        self.assertEqual(artifact_sha256(a), artifact_sha256(b))
        self.assertEqual(a["fit_split"], "TRAIN")
        self.assertFalse(a["test_consumed"])
        self.assertEqual(a["production_effect"], "NONE")

    def test_non_train_input_is_rejected(self):
        row = obs(1)
        row["source_split"] = "VALIDATION"
        with self.assertRaisesRegex(ValueError, "TRAIN observations only"):
            build_artifact([row], graph=graph())


class SelectionTests(unittest.TestCase):
    def test_exact_context_used_when_observations_and_hands_supported(self):
        rows = [obs(i, action=("FOLD","CALL","RAISE")[i % 3], sizing=1.0 if i % 3 == 2 else None) for i in range(60)]
        model = SupportAwareBackoffModel(build_artifact(rows, graph=graph()))
        p = model.predict(**obs(999))
        self.assertEqual(p["selected_level"]["index"], 0)
        self.assertEqual(p["fallback_reason"], "EXACT_CONTEXT_SUPPORTED")
        self.assertGreaterEqual(p["effective_support"]["observations"], 30)
        self.assertGreaterEqual(p["effective_support"]["distinct_hands"], 20)
        self.assertEqual(p["effective_support"]["source_split"], "TRAIN")

    def test_distinct_hands_guard_forces_backoff(self):
        rows = []
        # Exact node has many observations but only 5 distinct hands.
        for i in range(40):
            row = obs(i % 5, sequence="RARE")
            rows.append(row)
        # Broader street/price/global nodes gain distinct-hand support from other contexts.
        rows.extend(obs(100+i, sequence="COMMON", pos="OOP") for i in range(40))
        model = SupportAwareBackoffModel(build_artifact(rows, graph=graph()))
        p = model.predict(**obs(999, sequence="RARE"))
        self.assertGreater(p["selected_level"]["index"], 0)
        self.assertTrue(any(x["reason"] == "INSUFFICIENT_TRAIN_SUPPORT" for x in p["failed_finer_levels"]))
        self.assertNotEqual(p["fallback_reason"], "EXACT_CONTEXT_SUPPORTED")

    def test_no_nearest_context_heuristic_only_declared_levels(self):
        rows = [obs(i, sequence="KNOWN", action="CALL") for i in range(40)]
        model = SupportAwareBackoffModel(build_artifact(rows, graph=graph()))
        probe = obs(999, sequence="UNKNOWN", pos="OOP")
        p = model.predict(**probe)
        self.assertIn(p["selected_level"]["index"], range(len(HIERARCHY)))
        self.assertTrue(all("level" in x for x in p["failed_finer_levels"]))
        self.assertFalse(model.document["feature_contract"]["nearest_context_heuristic"])

    def test_sizing_support_and_tail_diagnostics_are_explicit(self):
        rows = []
        for i in range(36):
            rows.append(obs(i, action="RAISE", sizing=2.0 if i % 2 else 4.0))
        model = SupportAwareBackoffModel(build_artifact(rows, graph=graph()))
        p = model.predict(**obs(999, action="CALL"))
        self.assertEqual(p["sizing_selected_level"]["index"], 0)
        self.assertGreaterEqual(p["sizing_effective_support"]["raise_observations"], 12)
        self.assertIsNotNone(p["sizing"]["median"])
        self.assertIsNotNone(p["tail_diagnostics"]["overbet_conditional_on_raise"])
        self.assertIsNotNone(p["tail_diagnostics"]["jam_like_conditional_on_raise"])

    def test_prediction_contract_contains_required_provenance(self):
        rows = [obs(i, action=("FOLD","CALL","RAISE")[i % 3], sizing=0.75 if i % 3 == 2 else None) for i in range(60)]
        model = SupportAwareBackoffModel(build_artifact(rows, graph=graph()))
        p = model.predict(**obs(999))
        for key in ("exact_context","selected_level","effective_support","fallback_reason","probabilities","sizing","tail_diagnostics"):
            self.assertIn(key, p)
        self.assertAlmostEqual(sum(p["probabilities"].values()), 1.0, places=12)


if __name__ == "__main__":
    unittest.main()
