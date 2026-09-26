#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.model_b_hero_robustness_status import (  # noqa: E402
    DEFAULT_POLICY,
    REASON_CODES,
    STATUSES,
    STATUS_PRECEDENCE,
    RobustnessPolicy,
    classify_robustness,
)

FIXTURES = ROOT / "tests/fixtures/model_b_robustness_consumer"
MODULE_PATH = ROOT / "tools/simulation/model_b_hero_robustness_status.py"

FIXTURE_STATUSES = {
    "robust_recommendation.json": "CONSISTENT",
    "too_close.json": "TOO_CLOSE",
    "sparse_high_uncertainty.json": "INSUFFICIENT_SUPPORT",
    "ood_unsupported.json": "OOD_UNTESTABLE",
    "multiple_sizings.json": "SENSITIVE",
}


def _provenance() -> dict:
    return {
        "parent_issue": 314,
        "upstream_result_schema": "poker-issue367-real-iso-ev-result/v1",
        "synthetic_fixture": True,
        "real_issue_367_consumed": False,
        "real_issue_314_consumed": False,
        "validation_consumed": False,
        "test_consumed": False,
    }


def _boundary() -> dict:
    return {
        "hero_ev_consumed": False,
        "model_a_consumed": False,
        "recommendation_consumed": False,
        "route_as_predictive_target": False,
        "future_cards_consumed": False,
        "opponent_hole_cards_consumed": False,
    }


def alternative(
    alternative_id: str,
    *,
    ev: float | None = 1.0,
    delta: float | None = -0.1,
    width: float | None = 0.06,
    status: str = "CONSISTENT",
    ood: bool = False,
    uncertainty: bool = True,
) -> dict:
    row = {
        "alternative_id": alternative_id,
        "action": "ISO",
        "sizing": 5.0,
        "route": f"route_{alternative_id}",
        "source": "synthetic_monte_carlo_paired_v1",
        "ev_bb": ev,
        "uncertainty": None,
        "paired_delta_vs_best_bb": delta,
        "support": {"status": status, "tier": "MEDIUM", "ood": ood},
        "posterior_refs": None,
    }
    if uncertainty and width is not None:
        row["uncertainty"] = {
            "ci95": [0.0, width],
            "width_bb": width,
            "source": "synthetic_paired_ci95_v1",
        }
    return row


def document(
    alternatives: list,
    *,
    provenance: dict | None = None,
    boundary: dict | None = None,
    stability: dict | None = None,
) -> dict:
    doc = {
        "schema": "hero-model-b-robustness-input/v1",
        "source_kind": "SYNTHETIC_ROBUSTNESS_SHAPED",
        "synthetic_fixture": True,
        "decision": {
            "decision_id": "d1",
            "context_id": "c1",
            "hero_position": "SB",
            "action": "ISO",
            "sizing": 5.0,
        },
        "alternatives": alternatives,
        "provenance": _provenance() if provenance is None else provenance,
        "information_boundary": _boundary() if boundary is None else boundary,
    }
    if stability is not None:
        doc["stability"] = stability
    return doc


class StatusVocabularyTests(unittest.TestCase):
    def test_statuses_is_exactly_the_five_admissible_verdicts(self):
        self.assertEqual(
            set(STATUSES),
            {
                "CONSISTENT",
                "SENSITIVE",
                "TOO_CLOSE",
                "INSUFFICIENT_SUPPORT",
                "OOD_UNTESTABLE",
            },
        )

    def test_precedence_is_fixed_and_ordered(self):
        self.assertEqual(
            STATUS_PRECEDENCE,
            (
                "OOD_UNTESTABLE",
                "INSUFFICIENT_SUPPORT",
                "TOO_CLOSE",
                "SENSITIVE",
                "CONSISTENT",
            ),
        )
        self.assertEqual(set(STATUS_PRECEDENCE), set(STATUSES))

    def test_reason_codes_are_explicit_non_empty_strings(self):
        self.assertTrue(REASON_CODES)
        for code in REASON_CODES:
            self.assertIsInstance(code, str)
            self.assertTrue(code)
            self.assertEqual(code, code.upper())

    def test_every_fixture_maps_to_its_expected_status(self):
        for name, expected in FIXTURE_STATUSES.items():
            with self.subTest(fixture=name):
                payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
                result = classify_robustness(payload)
                self.assertEqual(result["status"], expected)
                self.assertTrue(set(result["reason_codes"]) <= REASON_CODES)
                self.assertEqual(set(result), {"status", "reason_codes", "evidence"})
                self.assertEqual(result["evidence"]["environment_aggregation"], "ENVELOPE_ONLY")


class PrecedenceTests(unittest.TestCase):
    def test_ood_beats_insufficient_support(self):
        doc = document(
            [alternative("A", ev=1.0), alternative("B", ev=0.9, status="OOD_UNTESTABLE", ood=True)],
            provenance={},  # missing provenance alone would be INSUFFICIENT_SUPPORT
        )
        result = classify_robustness(doc)
        self.assertEqual(result["status"], "OOD_UNTESTABLE")
        self.assertIn("SUPPORT_OOD", result["reason_codes"])
        self.assertIn("PROVENANCE_MISSING", result["evidence"]["reason_codes_by_status"]["INSUFFICIENT_SUPPORT"])

    def test_unknown_declared_status_is_untestable(self):
        doc = document([alternative("A", status="MAYBE_FINE")])
        result = classify_robustness(doc)
        self.assertEqual(result["status"], "OOD_UNTESTABLE")
        self.assertIn("SUPPORT_STATUS_UNKNOWN", result["reason_codes"])

    def test_alternative_level_ood_flag_is_untestable(self):
        row = alternative("A")
        row["ood"] = True
        result = classify_robustness(document([row]))
        self.assertEqual(result["status"], "OOD_UNTESTABLE")
        self.assertIn("SUPPORT_OOD", result["reason_codes"])

    def test_missing_support_block_is_untestable(self):
        row = alternative("A")
        del row["support"]
        result = classify_robustness(document([row]))
        self.assertEqual(result["status"], "OOD_UNTESTABLE")
        self.assertIn("SUPPORT_MISSING", result["reason_codes"])

    def test_insufficient_beats_too_close(self):
        doc = document(
            [alternative("A", ev=1.00, delta=0.0), alternative("B", ev=0.99, delta=-0.01)],
            provenance={},
        )
        result = classify_robustness(doc)
        self.assertEqual(result["status"], "INSUFFICIENT_SUPPORT")
        self.assertIn("PROVENANCE_MISSING", result["reason_codes"])
        self.assertIn("ADVANTAGE_WITHIN_TOLERANCE", result["evidence"]["reason_codes_by_status"]["TOO_CLOSE"])

    def test_too_close_beats_sensitive(self):
        doc = document(
            [
                alternative("A", ev=1.00, delta=0.0, status="SENSITIVE"),
                alternative("B", ev=0.99, delta=-0.01, status="SENSITIVE"),
            ]
        )
        result = classify_robustness(doc)
        self.assertEqual(result["status"], "TOO_CLOSE")
        self.assertIn("SUPPORT_STATUS_SENSITIVE", result["evidence"]["reason_codes_by_status"]["SENSITIVE"])

    def test_sensitive_beats_consistent(self):
        doc = document(
            [alternative("A", ev=1.0, delta=0.0), alternative("B", ev=0.5, delta=-0.5, status="SENSITIVE")]
        )
        result = classify_robustness(doc)
        self.assertEqual(result["status"], "SENSITIVE")
        self.assertIn("SUPPORT_STATUS_SENSITIVE", result["reason_codes"])

    def test_stability_block_can_declare_instability(self):
        doc = document(
            [alternative("A", ev=1.0, delta=0.0), alternative("B", ev=0.5, delta=-0.5)],
            stability={"action": False, "sizing": True, "ranking": None},
        )
        result = classify_robustness(doc)
        self.assertEqual(result["status"], "SENSITIVE")
        self.assertEqual(result["reason_codes"], ["UNSTABLE_ACTION"])

    def test_consistent_when_nothing_triggers(self):
        doc = document([alternative("A", ev=1.4, delta=0.0), alternative("B", ev=1.0, delta=-0.4)])
        result = classify_robustness(doc)
        self.assertEqual(result["status"], "CONSISTENT")
        self.assertEqual(result["reason_codes"], ["CONSISTENT_ACROSS_ENVIRONMENTS"])

    def test_every_emitted_status_is_in_the_vocabulary(self):
        samples = [
            document([alternative("A")]),
            document([]),
            {},
            "not-a-mapping",
            None,
            document([alternative("A", ev=None)]),
            document([alternative("A", uncertainty=False)]),
            document([alternative("A", width=999.0)]),
            document([alternative("A", status="TOO_CLOSE")]),
        ]
        for sample in samples:
            with self.subTest(sample=repr(sample)[:40]):
                result = classify_robustness(sample)
                self.assertIn(result["status"], STATUSES)
                self.assertTrue(set(result["reason_codes"]) <= REASON_CODES)


class DeterminismTests(unittest.TestCase):
    def test_same_input_yields_identical_output(self):
        doc = json.loads((FIXTURES / "multiple_sizings.json").read_text(encoding="utf-8"))
        snapshot = copy.deepcopy(doc)
        first = classify_robustness(doc)
        second = classify_robustness(copy.deepcopy(doc))
        self.assertEqual(first, second)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertEqual(doc, snapshot)  # the classifier never mutates its input

    def test_reordering_alternatives_does_not_change_the_result(self):
        doc = json.loads((FIXTURES / "robust_recommendation.json").read_text(encoding="utf-8"))
        reversed_doc = copy.deepcopy(doc)
        reversed_doc["alternatives"] = list(reversed(reversed_doc["alternatives"]))
        self.assertEqual(classify_robustness(doc), classify_robustness(reversed_doc))

    def test_reason_codes_and_evidence_lists_are_sorted(self):
        doc = json.loads((FIXTURES / "ood_unsupported.json").read_text(encoding="utf-8"))
        result = classify_robustness(doc)
        self.assertEqual(result["reason_codes"], sorted(result["reason_codes"]))
        self.assertEqual(result["evidence"]["ood_alternatives"], sorted(result["evidence"]["ood_alternatives"]))
        for codes in result["evidence"]["reason_codes_by_status"].values():
            self.assertEqual(codes, sorted(codes))

    def test_ranking_ties_break_lexically_on_alternative_id(self):
        doc = document(
            [alternative("B", ev=1.0, delta=-0.5), alternative("A", ev=1.0, delta=-0.5)]
        )
        result = classify_robustness(doc)
        self.assertEqual(result["evidence"]["best_alternative_id"], "A")
        self.assertEqual(result["evidence"]["second_best_alternative_id"], "B")

    def test_policy_is_a_pure_input(self):
        doc = document([alternative("A", ev=1.00, delta=0.0), alternative("B", ev=0.94, delta=-0.06)])
        default = classify_robustness(doc)
        self.assertEqual(default["status"], "CONSISTENT")
        loose = classify_robustness(doc, policy=RobustnessPolicy(too_close_tolerance_bb=0.10))
        self.assertEqual(loose["status"], "TOO_CLOSE")
        self.assertEqual(DEFAULT_POLICY.too_close_tolerance_bb, 0.05)
        self.assertEqual(default["evidence"]["policy"]["too_close_tolerance_bb"], 0.05)


class SourceGuardTests(unittest.TestCase):
    def test_module_never_reads_model_a_or_hero_ev(self):
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("model_a", text)
        self.assertNotIn("hero_ev", text)
        lower = text.lower()
        self.assertNotIn("probability", lower)
        self.assertNotIn("weight", lower)

    def test_output_never_exposes_environment_shares_or_model_a(self):
        doc = json.loads((FIXTURES / "robust_recommendation.json").read_text(encoding="utf-8"))
        result = classify_robustness(doc)
        rendered = json.dumps(result).lower()
        self.assertNotIn("model_a", rendered)
        self.assertNotIn("hero_ev", rendered)


if __name__ == "__main__":
    unittest.main()
