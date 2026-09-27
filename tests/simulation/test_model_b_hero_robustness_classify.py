#!/usr/bin/env python3
"""Regression tests for the Hero robustness status classifier (``backlog-nhg``)."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.model_b_hero_robustness_classify import (  # noqa: E402
    MAX_CI95_WIDTH_BB,
    REASON_CODES,
    REQUIRED_ALTERNATIVE_FIELDS,
    REQUIRED_HERO_ENTRY_FIELDS,
    SENSITIVE_DELTA_BB,
    STATUS_PRECEDENCE,
    STATUSES,
    TOO_CLOSE_DELTA_BB,
    RobustnessClassifyError,
    Status,
    classify,
)

FIXTURES = ROOT / "tests/fixtures/model_b_hero_robustness"

FIXTURE_STATUSES = {
    "robust_consistent.json": "CONSISTENT",
    "too_close.json": "TOO_CLOSE",
    "sparse_high_uncertainty.json": "INSUFFICIENT_SUPPORT",
    "ood_unsupported.json": "OOD_UNTESTABLE",
    "multi_sizing.json": "SENSITIVE",
}


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _entry(**overrides) -> dict:
    entry = {
        "action": "ISO",
        "sizing": 5.0,
        "ev": 1.0,
        "uncertainty": {"ci95": [0.97, 1.03], "width_bb": 0.06, "source": "s"},
        "paired_delta": 0.0,
        "route_source": "route_iso_5",
        "support": {"status": "CONSISTENT", "tier": "HIGH", "ood": False},
        "posterior_refs": None,
        "alternatives": [_alternative()],
    }
    entry.update(overrides)
    return entry


def _alternative(**overrides) -> dict:
    alternative = {
        "alternative_id": "ISO@4",
        "action": "ISO",
        "sizing": 4.0,
        "ev": 0.5,
        "uncertainty": {"ci95": [0.47, 0.53], "width_bb": 0.06, "source": "s"},
        "paired_delta": -0.5,
        "route_source": "route_iso_4",
        "support": {"status": "CONSISTENT", "tier": "HIGH", "ood": False},
        "posterior_refs": None,
    }
    alternative.update(overrides)
    return alternative


class VocabularyTests(unittest.TestCase):
    def test_statuses_are_the_exact_closed_vocabulary(self) -> None:
        self.assertEqual(
            STATUSES,
            {
                "CONSISTENT",
                "SENSITIVE",
                "TOO_CLOSE",
                "INSUFFICIENT_SUPPORT",
                "OOD_UNTESTABLE",
            },
        )
        self.assertEqual({member.value for member in Status}, set(STATUSES))
        self.assertEqual(set(STATUS_PRECEDENCE), set(STATUSES))
        self.assertEqual(len(STATUS_PRECEDENCE), 5)

    def test_precedence_is_the_documented_severity_order(self) -> None:
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

    def test_thresholds_are_named_ordered_constants(self) -> None:
        self.assertGreater(SENSITIVE_DELTA_BB, TOO_CLOSE_DELTA_BB)
        self.assertGreater(MAX_CI95_WIDTH_BB, 0.0)

    def test_every_emitted_reason_code_is_declared(self) -> None:
        for fixture in FIXTURE_STATUSES:
            result = classify(_load(fixture))
            self.assertTrue(set(result["reason_codes"]) <= REASON_CODES, result)


class FixtureTests(unittest.TestCase):
    def test_each_fixture_maps_to_its_expected_status(self) -> None:
        for fixture, expected in FIXTURE_STATUSES.items():
            with self.subTest(fixture=fixture):
                result = classify(_load(fixture))
                self.assertEqual(result["status"], expected)
                self.assertIn(result["status"], STATUSES)

    def test_full_document_and_bare_entry_agree(self) -> None:
        for fixture in FIXTURE_STATUSES:
            document = _load(fixture)
            self.assertEqual(classify(document), classify(document["hero_entry"]))

    def test_result_shape_is_exactly_status_and_reason_codes(self) -> None:
        for fixture in FIXTURE_STATUSES:
            result = classify(_load(fixture))
            self.assertEqual(set(result), {"status", "reason_codes"})
            self.assertEqual(result["reason_codes"], sorted(set(result["reason_codes"])))


class DeterminismTests(unittest.TestCase):
    def test_repeated_calls_are_identical(self) -> None:
        for fixture in FIXTURE_STATUSES:
            entry = _load(fixture)["hero_entry"]
            first = classify(copy.deepcopy(entry))
            second = classify(copy.deepcopy(entry))
            self.assertEqual(first, second)

    def test_alternative_order_does_not_change_the_verdict(self) -> None:
        entry = _load("multi_sizing.json")["hero_entry"]
        reversed_entry = copy.deepcopy(entry)
        reversed_entry["alternatives"] = list(reversed(reversed_entry["alternatives"]))
        self.assertEqual(classify(entry), classify(reversed_entry))


class PrecedenceTests(unittest.TestCase):
    def test_ood_wins_over_everything(self) -> None:
        entry = _entry(support={"status": "OOD_UNTESTABLE", "tier": "UNKNOWN", "ood": True})
        self.assertEqual(classify(entry)["status"], "OOD_UNTESTABLE")

    def test_declared_ood_flag_wins(self) -> None:
        entry = _entry(support={"status": "CONSISTENT", "tier": "HIGH", "ood": True})
        self.assertEqual(classify(entry)["status"], "OOD_UNTESTABLE")

    def test_unknown_support_status_is_ood(self) -> None:
        entry = _entry(support={"status": "MOSTLY_FINE", "tier": "HIGH", "ood": False})
        self.assertEqual(classify(entry)["status"], "OOD_UNTESTABLE")

    def test_null_support_fails_closed_to_ood(self) -> None:
        entry = _entry(support=None)
        result = classify(entry)
        self.assertEqual(result["status"], "OOD_UNTESTABLE")
        self.assertEqual(result["reason_codes"], ["SUPPORT_MISSING"])

    def test_sparse_support_is_insufficient(self) -> None:
        entry = _entry(
            support={"status": "INSUFFICIENT_SUPPORT", "tier": "LOW", "ood": False}
        )
        self.assertEqual(classify(entry)["status"], "INSUFFICIENT_SUPPORT")

    def test_high_uncertainty_is_insufficient(self) -> None:
        entry = _entry(
            uncertainty={"ci95": [-2.0, 4.0], "width_bb": 6.0, "source": "s"}
        )
        result = classify(entry)
        self.assertEqual(result["status"], "INSUFFICIENT_SUPPORT")
        self.assertIn("CI95_WIDTH_EXCEEDS_POLICY", result["reason_codes"])

    def test_sparse_tier_is_insufficient(self) -> None:
        entry = _entry(support={"status": "CONSISTENT", "tier": "LOW", "ood": False})
        self.assertEqual(classify(entry)["status"], "INSUFFICIENT_SUPPORT")

    def test_too_close_is_preserved_over_sensitive(self) -> None:
        entry = _entry(
            support={"status": "SENSITIVE", "tier": "HIGH", "ood": False},
            alternatives=[_alternative(ev=0.99, paired_delta=-0.01)],
        )
        result = classify(entry)
        self.assertEqual(result["status"], "TOO_CLOSE")
        self.assertIn("ADVANTAGE_WITHIN_TOLERANCE", result["reason_codes"])

    def test_too_close_is_preserved_over_consistent(self) -> None:
        entry = _entry(alternatives=[_alternative(ev=0.98, paired_delta=-0.02)])
        self.assertEqual(classify(entry)["status"], "TOO_CLOSE")

    def test_sizing_variation_inside_sensitivity_band_is_sensitive(self) -> None:
        entry = _entry(alternatives=[_alternative(ev=0.85, paired_delta=-0.15)])
        result = classify(entry)
        self.assertEqual(result["status"], "SENSITIVE")
        self.assertIn("SIZING_VARIATION_WITHIN_SENSITIVITY_BAND", result["reason_codes"])

    def test_settled_standing_is_consistent(self) -> None:
        entry = _entry(alternatives=[_alternative(ev=0.5, paired_delta=-0.5)])
        self.assertEqual(classify(entry)["status"], "CONSISTENT")

    def test_paired_ci_including_zero_is_too_close(self) -> None:
        alternative = _alternative(ev=0.5, paired_delta=-0.5)
        alternative["paired_delta_ci95"] = [-0.2, 0.2]
        entry = _entry(alternatives=[alternative])
        result = classify(entry)
        self.assertEqual(result["status"], "TOO_CLOSE")
        self.assertIn("PAIRED_CI_INCLUDES_ZERO", result["reason_codes"])

    def test_every_returned_status_is_in_the_closed_vocabulary(self) -> None:
        probes = [
            _entry(),
            _entry(support=None),
            _entry(support={"status": "SENSITIVE", "tier": "LOW", "ood": False}),
            _entry(alternatives=[_alternative(ev=0.99, paired_delta=0.0)]),
            _entry(alternatives=None),
        ]
        for probe in probes:
            self.assertIn(classify(probe)["status"], STATUSES)


class FailClosedTests(unittest.TestCase):
    def test_non_mapping_input_raises(self) -> None:
        with self.assertRaises(RobustnessClassifyError):
            classify("not-a-mapping")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            classify(None)  # type: ignore[arg-type]

    def test_missing_hero_entry_field_raises(self) -> None:
        for field in REQUIRED_HERO_ENTRY_FIELDS:
            entry = _entry()
            del entry[field]
            with self.subTest(field=field):
                with self.assertRaises(RobustnessClassifyError) as ctx:
                    classify(entry)
                self.assertIn(field, str(ctx.exception))

    def test_missing_alternative_field_raises(self) -> None:
        for field in REQUIRED_ALTERNATIVE_FIELDS:
            alternative = _alternative()
            del alternative[field]
            with self.subTest(field=field):
                with self.assertRaises(RobustnessClassifyError) as ctx:
                    classify(_entry(alternatives=[alternative]))
                self.assertIn(field, str(ctx.exception))

    def test_missing_field_never_defaults_to_a_status(self) -> None:
        entry = _entry()
        del entry["support"]
        with self.assertRaises(RobustnessClassifyError):
            classify(entry)

    def test_null_alternatives_are_insufficient_not_consistent(self) -> None:
        result = classify(_entry(alternatives=None))
        self.assertEqual(result["status"], "INSUFFICIENT_SUPPORT")
        self.assertIn("NO_COMPARISON_SET", result["reason_codes"])

    def test_null_hero_ev_is_insufficient(self) -> None:
        result = classify(_entry(ev=None))
        self.assertEqual(result["status"], "INSUFFICIENT_SUPPORT")
        self.assertIn("EV_MISSING", result["reason_codes"])


if __name__ == "__main__":  # pragma: no cover - manual entry point
    unittest.main()
