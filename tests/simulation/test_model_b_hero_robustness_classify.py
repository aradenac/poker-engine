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
    CI95_WIDTH_TOLERANCE_BB,
    DEFAULT_POLICY,
    MAX_CI95_WIDTH_BB,
    REASON_CODES,
    REQUIRED_ALTERNATIVE_FIELDS,
    REQUIRED_HERO_ENTRY_FIELDS,
    SENSITIVE_DELTA_BB,
    STATUS_PRECEDENCE,
    STATUSES,
    TOO_CLOSE_DELTA_BB,
    RobustnessClassifyError,
    RobustnessPolicy,
    Status,
    classify,
)

FIXTURES = ROOT / "tests/fixtures/model_b_hero_robustness"
MODULE_PATH = ROOT / "tools/simulation/model_b_hero_robustness_classify.py"

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


class UncertaintySemanticsTests(unittest.TestCase):
    """Regressions for the CI95 width semantics (task ``backlog-wxq``).

    The width used by the classifier is always the one *derived from the
    ``ci95`` bounds*; a declared ``width_bb`` is a claim that must agree with
    those bounds within :data:`CI95_WIDTH_TOLERANCE_BB`. An incoherent envelope
    is never a support claim, and the Hero entry is not privileged: every
    compared alternative is verified as strictly.
    """

    def _mismatch_envelope(self) -> dict:
        return {"ci95": [-10.0, 10.0], "width_bb": 0.06, "source": "s"}

    def test_declared_width_contradicting_the_bounds_cannot_be_consistent(self) -> None:
        entry = _entry(uncertainty=self._mismatch_envelope())
        result = classify(entry)
        self.assertEqual(result["status"], "INSUFFICIENT_SUPPORT")
        self.assertIn("UNCERTAINTY_WIDTH_MISMATCH", result["reason_codes"])
        self.assertNotIn("CONSISTENT_WITHIN_POLICY", result["reason_codes"])

    def test_alternative_width_contradicting_the_bounds_cannot_be_consistent(self) -> None:
        entry = _entry(
            alternatives=[_alternative(ev=0.5, uncertainty=self._mismatch_envelope())]
        )
        result = classify(entry)
        self.assertEqual(result["status"], "INSUFFICIENT_SUPPORT")
        self.assertIn("UNCERTAINTY_WIDTH_MISMATCH", result["reason_codes"])

    def test_reversed_bounds_are_insufficient(self) -> None:
        entry = _entry(uncertainty={"ci95": [1.0, 0.5], "width_bb": 0.5, "source": "s"})
        result = classify(entry)
        self.assertEqual(result["status"], "INSUFFICIENT_SUPPORT")
        self.assertIn("UNCERTAINTY_INVALID", result["reason_codes"])

    def test_non_finite_or_malformed_bounds_are_insufficient(self) -> None:
        probes = (
            [float("nan"), 1.0],
            [0.0, float("inf")],
            [0.0, float("-inf")],
            [0.5],
            ["0.0", 1.0],
            [None, 1.0],
            "0.0,1.0",
        )
        for ci95 in probes:
            with self.subTest(ci95=ci95):
                entry = _entry(
                    uncertainty={"ci95": ci95, "width_bb": 0.06, "source": "s"}
                )
                result = classify(entry)
                self.assertEqual(result["status"], "INSUFFICIENT_SUPPORT")
                self.assertIn("UNCERTAINTY_INVALID", result["reason_codes"])

    def test_invalid_declared_width_is_insufficient(self) -> None:
        for declared in (-0.06, float("nan"), float("inf"), "0.06", None, True):
            with self.subTest(width_bb=declared):
                entry = _entry(
                    uncertainty={"ci95": [0.97, 1.03], "width_bb": declared, "source": "s"}
                )
                result = classify(entry)
                self.assertEqual(result["status"], "INSUFFICIENT_SUPPORT")
                self.assertIn("UNCERTAINTY_INVALID", result["reason_codes"])

    def test_missing_declared_width_is_insufficient(self) -> None:
        entry = _entry(uncertainty={"ci95": [0.97, 1.03], "source": "s"})
        result = classify(entry)
        self.assertEqual(result["status"], "INSUFFICIENT_SUPPORT")
        self.assertIn("UNCERTAINTY_INVALID", result["reason_codes"])

    def test_coherent_width_above_the_policy_is_insufficient(self) -> None:
        entry = _entry(uncertainty={"ci95": [0.0, 6.0], "width_bb": 6.0, "source": "s"})
        result = classify(entry)
        self.assertEqual(result["status"], "INSUFFICIENT_SUPPORT")
        self.assertIn("CI95_WIDTH_EXCEEDS_POLICY", result["reason_codes"])
        self.assertNotIn("UNCERTAINTY_WIDTH_MISMATCH", result["reason_codes"])
        self.assertGreater(6.0, MAX_CI95_WIDTH_BB)

    def test_coherent_width_at_the_policy_boundary_is_accepted(self) -> None:
        entry = _entry(
            uncertainty={
                "ci95": [1.0, 1.0 + MAX_CI95_WIDTH_BB],
                "width_bb": MAX_CI95_WIDTH_BB,
                "source": "s",
            }
        )
        self.assertEqual(classify(entry)["status"], "CONSISTENT")

    def test_float_rounding_of_a_coherent_interval_is_tolerated(self) -> None:
        # ``1.45 - 1.39 == 0.06000000000000005`` in binary floating point.
        noisy = 1.45 - 1.39
        self.assertNotEqual(noisy, 0.06)
        self.assertLessEqual(abs(noisy - 0.06), CI95_WIDTH_TOLERANCE_BB)
        for declared in (0.06, noisy):
            with self.subTest(width_bb=declared):
                entry = _entry(
                    uncertainty={"ci95": [1.39, 1.45], "width_bb": declared, "source": "s"}
                )
                self.assertEqual(classify(entry)["status"], "CONSISTENT")
        self.assertGreater(CI95_WIDTH_TOLERANCE_BB, 0.0)

    def test_secondary_alternative_without_uncertainty_forbids_consistent(self) -> None:
        entry = _entry(
            alternatives=[
                _alternative(alternative_id="BEST", ev=0.5),
                _alternative(alternative_id="SECOND", ev=0.2, uncertainty=None),
            ]
        )
        result = classify(entry)
        self.assertEqual(result["status"], "INSUFFICIENT_SUPPORT")
        self.assertIn("UNCERTAINTY_MISSING", result["reason_codes"])

    def test_secondary_alternative_with_malformed_uncertainty_forbids_consistent(self) -> None:
        entry = _entry(
            alternatives=[
                _alternative(alternative_id="BEST", ev=0.5),
                _alternative(
                    alternative_id="SECOND",
                    ev=0.2,
                    uncertainty={"ci95": [0.1], "width_bb": 0.06, "source": "s"},
                ),
            ]
        )
        result = classify(entry)
        self.assertEqual(result["status"], "INSUFFICIENT_SUPPORT")
        self.assertIn("UNCERTAINTY_INVALID", result["reason_codes"])

    def test_secondary_alternative_with_excessive_uncertainty_forbids_consistent(self) -> None:
        entry = _entry(
            alternatives=[
                _alternative(alternative_id="BEST", ev=0.5),
                _alternative(
                    alternative_id="SECOND",
                    ev=0.2,
                    uncertainty={"ci95": [-4.0, 4.0], "width_bb": 8.0, "source": "s"},
                ),
            ]
        )
        result = classify(entry)
        self.assertEqual(result["status"], "INSUFFICIENT_SUPPORT")
        self.assertIn("CI95_WIDTH_EXCEEDS_POLICY", result["reason_codes"])

    def test_ood_precedence_survives_an_incoherent_envelope(self) -> None:
        entry = _entry(
            support={"status": "OOD_UNTESTABLE", "tier": "UNKNOWN", "ood": True},
            uncertainty=self._mismatch_envelope(),
        )
        self.assertEqual(classify(entry)["status"], "OOD_UNTESTABLE")

    def test_alternative_order_does_not_change_a_broken_uncertainty_verdict(self) -> None:
        alternatives = [
            _alternative(alternative_id="BEST", ev=0.5),
            _alternative(
                alternative_id="MISMATCH", ev=0.2, uncertainty=self._mismatch_envelope()
            ),
            _alternative(alternative_id="MISSING", ev=0.1, uncertainty=None),
            _alternative(
                alternative_id="WIDE",
                ev=0.05,
                uncertainty={"ci95": [-4.0, 4.0], "width_bb": 8.0, "source": "s"},
            ),
        ]
        entry = _entry(alternatives=copy.deepcopy(alternatives))
        flipped = _entry(alternatives=list(reversed(copy.deepcopy(alternatives))))
        first = classify(entry)
        second = classify(flipped)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "INSUFFICIENT_SUPPORT")
        self.assertEqual(
            set(first["reason_codes"]),
            {
                "UNCERTAINTY_MISSING",
                "UNCERTAINTY_WIDTH_MISMATCH",
                "CI95_WIDTH_EXCEEDS_POLICY",
            },
        )
        self.assertTrue(set(first["reason_codes"]) <= REASON_CODES)


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


class ConsolidationTests(unittest.TestCase):
    """Guarantees migrated from the removed #425 status/consumer chain.

    The single canonical classifier is now the only active classification
    implementation: the incompatible ``model_b_hero_robustness_status`` module
    (and its ``classify_robustness`` entry point) is gone, so a second verdict
    vocabulary can never be selected by accident.
    """

    def test_single_classification_implementation_is_active(self) -> None:
        simulation = ROOT / "tools/simulation"
        self.assertFalse((simulation / "model_b_hero_robustness_status.py").exists())
        for path in simulation.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("def classify_robustness", source, path.name)

    def test_module_never_reads_model_a_or_synthesizes_environment_weight(self) -> None:
        lowered = MODULE_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("model_a", lowered)
        self.assertNotIn("probability", lowered)
        self.assertNotIn("weight", lowered)

    def test_output_never_exposes_environment_shares_or_model_a(self) -> None:
        for fixture in FIXTURE_STATUSES:
            result = classify(_load(fixture))
            self.assertEqual(set(result), {"status", "reason_codes"})
            rendered = json.dumps(result).lower()
            self.assertNotIn("model_a", rendered)
            self.assertNotIn("hero_ev", rendered)
            self.assertNotIn("share", rendered)

    def test_reason_codes_are_non_empty_uppercase_strings(self) -> None:
        for fixture in FIXTURE_STATUSES:
            result = classify(_load(fixture))
            self.assertTrue(result["reason_codes"], fixture)
            for code in result["reason_codes"]:
                self.assertIsInstance(code, str)
                self.assertTrue(code)
                self.assertEqual(code, code.upper())

    def test_classifier_never_mutates_its_input(self) -> None:
        document = _load("multi_sizing.json")
        snapshot = copy.deepcopy(document)
        classify(document)
        self.assertEqual(document, snapshot)

    def test_equal_ev_alternatives_are_order_independent(self) -> None:
        entry = _entry(
            alternatives=[
                _alternative(alternative_id="B", ev=0.5),
                _alternative(alternative_id="A", ev=0.5),
            ]
        )
        flipped = copy.deepcopy(entry)
        flipped["alternatives"] = list(reversed(flipped["alternatives"]))
        self.assertEqual(classify(entry), classify(flipped))

    def test_policy_is_a_pure_input_with_named_defaults(self) -> None:
        entry = _entry(alternatives=[_alternative(ev=0.94, paired_delta=-0.06)])
        default = classify(entry)
        self.assertEqual(default["status"], "SENSITIVE")
        loose = classify(entry, policy={"too_close_delta_bb": 0.10})
        self.assertEqual(loose["status"], "TOO_CLOSE")
        self.assertEqual(classify(entry, policy=RobustnessPolicy(too_close_delta_bb=0.10)), loose)
        self.assertEqual(DEFAULT_POLICY.too_close_delta_bb, TOO_CLOSE_DELTA_BB)
        self.assertEqual(DEFAULT_POLICY.sensitive_delta_bb, SENSITIVE_DELTA_BB)
        self.assertEqual(DEFAULT_POLICY.max_ci95_width_bb, MAX_CI95_WIDTH_BB)


if __name__ == "__main__":  # pragma: no cover - manual entry point
    unittest.main()
