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
    REASON_CODES_BY_STATUS,
    REQUIRED_ALTERNATIVE_FIELDS,
    REQUIRED_HERO_ENTRY_FIELDS,
    ORDERING_SUPPORT_STATUS_BUCKETS,
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
    "best_alternative_clearly_superior.json": "SENSITIVE",
}


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _entry(**overrides) -> dict:
    entry = {
        "action": "ISO",
        "sizing": 5.0,
        "ev": 1.0,
        "uncertainty": {"ci95": [0.97, 1.03], "width_bb": 0.06, "source": "s"},
        # `hero_entry.paired_delta` is Hero versus the *best* alternative, so the
        # coherent default is the Hero advantage over `_alternative()`'s 0.5 EV.
        "paired_delta": 0.5,
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
        # An alternative's `paired_delta` compares it with the best alternative,
        # so the only alternative of the default entry is trivially tied with
        # itself. The classifier never reads this value as Hero evidence.
        "paired_delta": 0.0,
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
            paired_delta=0.01,
            alternatives=[_alternative(ev=0.99)],
        )
        result = classify(entry)
        self.assertEqual(result["status"], "TOO_CLOSE")
        self.assertIn("ADVANTAGE_WITHIN_TOLERANCE", result["reason_codes"])

    def test_too_close_is_preserved_over_consistent(self) -> None:
        entry = _entry(paired_delta=0.02, alternatives=[_alternative(ev=0.98)])
        self.assertEqual(classify(entry)["status"], "TOO_CLOSE")

    def test_sizing_variation_inside_sensitivity_band_is_sensitive(self) -> None:
        entry = _entry(paired_delta=0.15, alternatives=[_alternative(ev=0.85)])
        result = classify(entry)
        self.assertEqual(result["status"], "SENSITIVE")
        self.assertIn("SIZING_VARIATION_WITHIN_SENSITIVITY_BAND", result["reason_codes"])

    def test_settled_standing_is_consistent(self) -> None:
        entry = _entry(paired_delta=0.5, alternatives=[_alternative(ev=0.5)])
        self.assertEqual(classify(entry)["status"], "CONSISTENT")

    def test_paired_ci_including_zero_is_too_close(self) -> None:
        # A Hero-versus-best paired CI covering zero is a quasi-equality, even
        # when the paired point estimate sits outside the close band. Only the
        # Hero entry's own paired comparison speaks about this standing, and an
        # explicit no-ordering pair is never promoted to a sensitivity claim.
        entry = _entry(
            ev=0.5,
            uncertainty={"ci95": [0.47, 0.53], "width_bb": 0.06, "source": "s"},
            paired_delta=-0.4,
            alternatives=[
                _alternative(
                    ev=0.9,
                    uncertainty={
                        "ci95": [0.87, 0.93],
                        "width_bb": 0.06,
                        "source": "s",
                    },
                )
            ],
        )
        entry["paired_delta_ci95"] = [-0.9, 0.6]
        result = classify(entry)
        self.assertEqual(result["status"], "TOO_CLOSE")
        self.assertIn("PAIRED_CI_INCLUDES_ZERO", result["reason_codes"])
        self.assertNotIn("PAIRED_DELTA_WITHIN_TOLERANCE", result["reason_codes"])

    def test_every_returned_status_is_in_the_closed_vocabulary(self) -> None:
        probes = [
            _entry(),
            _entry(support=None),
            _entry(support={"status": "SENSITIVE", "tier": "LOW", "ood": False}),
            _entry(paired_delta=0.01, alternatives=[_alternative(ev=0.99)]),
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


class CloseBandSemanticsTests(unittest.TestCase):
    """Quasi-equality vs clearly-superior alternative (task ``backlog-lgc``).

    The numeric ``TOO_CLOSE`` test is reserved for an *absolute* gap inside
    :data:`TOO_CLOSE_DELTA_BB`: a gap that merely points downwards is a
    quasi-equality only while it stays in that band. Beyond it the best
    alternative is clearly superior to Hero and the verdict is an explicit
    ``SENSITIVE`` carrying ``BEST_ALTERNATIVE_CLEARLY_SUPERIOR`` -- never
    ``TOO_CLOSE``, and never a sizing selection or a recommendation.

    The two schema ``paired_delta`` fields are not interchangeable (task
    ``backlog-kuh``): ``hero_entry.paired_delta`` compares Hero with the best
    alternative and is the only paired signal about this standing, while
    ``alternatives[].paired_delta`` compares that alternative with the best
    alternative -- for the best-ranked one it is a self-comparison, ~0 by
    construction, and can never prove that Hero is tied with the best.
    """

    def _hero_below_best(
        self, *, best_ev: float, hero_paired_delta: float = -4.0
    ) -> dict:
        """A coherent Hero entry at EV -5.0 whose best alternative is far above.

        ``hero_paired_delta`` is the Hero-versus-best paired delta, coherent
        with the ``-5.0`` versus ``-1.0`` point estimates by default. The best
        alternative declares its own (auto-relative) paired delta of ``0.0``,
        exactly as the schema defines it.
        """

        return _entry(
            ev=-5.0,
            paired_delta=hero_paired_delta,
            alternatives=[
                _alternative(
                    alternative_id="BEST",
                    ev=best_ev,
                    paired_delta=0.0,
                    # Same sizing as Hero: the corrected case must not hinge on a
                    # sizing variation reason.
                    sizing=5.0,
                )
            ],
        )

    def test_clearly_better_alternative_is_sensitive_not_too_close(self) -> None:
        entry = self._hero_below_best(best_ev=-1.0, hero_paired_delta=-4.0)
        result = classify(entry)
        self.assertEqual(result["status"], "SENSITIVE")
        self.assertNotEqual(result["status"], "TOO_CLOSE")
        self.assertEqual(result["reason_codes"], ["BEST_ALTERNATIVE_CLEARLY_SUPERIOR"])
        self.assertTrue(set(result["reason_codes"]) <= REASON_CODES)
        self.assertTrue(
            set(result["reason_codes"])
            <= set(REASON_CODES_BY_STATUS["SENSITIVE"])
        )
        # No reason code of the close band may survive the correction.
        self.assertFalse(
            set(result["reason_codes"]) & set(REASON_CODES_BY_STATUS["TOO_CLOSE"])
        )

    def test_fixture_with_self_paired_delta_on_the_superior_alternative_is_sensitive(
        self,
    ) -> None:
        """The committed fixture of the ``paired_delta`` alignment (task ``backlog-kuh``).

        The best alternative is clearly superior to Hero in EV and declares its
        own ``paired_delta`` of ``0.0`` -- the schema's auto-comparison of the
        best alternative with itself. That trivially zero number must never be
        read as "Hero is tied with the best": the verdict is the explicit
        ``SENSITIVE``/``BEST_ALTERNATIVE_CLEARLY_SUPERIOR``, never ``TOO_CLOSE``
        and never a close-band reason.
        """

        document = _load("best_alternative_clearly_superior.json")
        entry = document["hero_entry"]
        best = entry["alternatives"][0]

        # The fixture really carries the ambiguous shape: the best alternative
        # is clearly above Hero while declaring a zero auto-relative delta.
        self.assertEqual(best["paired_delta"], 0.0)
        self.assertLess(entry["ev"] - best["ev"], -TOO_CLOSE_DELTA_BB)
        # The Hero-side paired delta is *not* near zero, so the zero it must not
        # inherit can only come from the alternative's auto-comparison.
        self.assertGreater(
            abs(float(entry["paired_delta"])), TOO_CLOSE_DELTA_BB
        )

        result = classify(document)
        self.assertEqual(result["status"], "SENSITIVE")
        self.assertNotEqual(result["status"], "TOO_CLOSE")
        self.assertEqual(result["reason_codes"], ["BEST_ALTERNATIVE_CLEARLY_SUPERIOR"])
        self.assertNotIn("PAIRED_DELTA_WITHIN_TOLERANCE", result["reason_codes"])
        self.assertFalse(
            set(result["reason_codes"]) & set(REASON_CODES_BY_STATUS["TOO_CLOSE"])
        )
        # A full document and its bare ``hero_entry`` block agree.
        self.assertEqual(classify(document), classify(document["hero_entry"]))

        # The best alternative's own paired signal cannot move the verdict at
        # all -- it is not Hero evidence, whatever value (or paired CI) it
        # declares.
        bribed = copy.deepcopy(document)
        bribed_best = bribed["hero_entry"]["alternatives"][0]
        bribed_best["paired_delta"] = 3.0
        bribed_best["paired_delta_ci95"] = [-0.1, 0.1]
        self.assertEqual(classify(bribed), result)

    def test_corrected_case_never_selects_or_recommends_a_sizing(self) -> None:
        # Only the standing is reported: exactly one status, one dedicated
        # reason, and no sizing/selection wording anywhere in the output.
        entry = self._hero_below_best(best_ev=-1.0)
        result = classify(entry)
        self.assertEqual(set(result), {"status", "reason_codes"})
        self.assertEqual(result["reason_codes"], ["BEST_ALTERNATIVE_CLEARLY_SUPERIOR"])
        rendered = json.dumps(result)
        for forbidden in ("sizing", "SIZING", "recommend", "RECOMMEND", "selected"):
            self.assertNotIn(forbidden, rendered)

    def test_gap_inside_the_band_is_too_close_in_both_directions(self) -> None:
        # Hero ahead by exactly the tolerance: quasi ex-aequo, no ordering.
        ahead = classify(
            _entry(
                ev=1.0,
                # Hero-versus-best, coherent with the point estimates below.
                paired_delta=TOO_CLOSE_DELTA_BB,
                alternatives=[
                    _alternative(ev=1.0 - TOO_CLOSE_DELTA_BB)
                ],
            )
        )
        self.assertEqual(ahead["status"], "TOO_CLOSE")
        self.assertIn("ADVANTAGE_WITHIN_TOLERANCE", ahead["reason_codes"])
        self.assertNotIn("BEST_ALTERNATIVE_CLEARLY_SUPERIOR", ahead["reason_codes"])

        # Hero behind by exactly the tolerance: still a quasi-equality.
        behind = classify(
            _entry(
                ev=1.0,
                paired_delta=-TOO_CLOSE_DELTA_BB,
                alternatives=[
                    _alternative(ev=1.0 + TOO_CLOSE_DELTA_BB)
                ],
            )
        )
        self.assertEqual(behind["status"], "TOO_CLOSE")
        self.assertIn("ADVANTAGE_WITHIN_TOLERANCE", behind["reason_codes"])
        self.assertIn("ALTERNATIVE_MATCHES_OR_EXCEEDS_HERO", behind["reason_codes"])
        self.assertNotIn("BEST_ALTERNATIVE_CLEARLY_SUPERIOR", behind["reason_codes"])

    def test_near_zero_gaps_in_both_directions_are_too_close(self) -> None:
        for gap in (1e-9, -1e-9, 0.0):
            with self.subTest(gap=gap):
                entry = _entry(
                    ev=1.0,
                    paired_delta=gap,
                    alternatives=[_alternative(ev=1.0 - gap)],
                )
                result = classify(entry)
                self.assertEqual(result["status"], "TOO_CLOSE", result)
                self.assertIn("ADVANTAGE_WITHIN_TOLERANCE", result["reason_codes"])
                self.assertNotIn(
                    "BEST_ALTERNATIVE_CLEARLY_SUPERIOR", result["reason_codes"]
                )

    def test_gap_just_outside_the_band_is_sensitive(self) -> None:
        outside = TOO_CLOSE_DELTA_BB + 1e-6

        # Just outside on the downward side: the alternative is clearly better.
        below = classify(
            _entry(
                ev=1.0,
                paired_delta=-outside,
                alternatives=[_alternative(ev=1.0 + outside)],
            )
        )
        self.assertEqual(below["status"], "SENSITIVE", below)
        self.assertIn("BEST_ALTERNATIVE_CLEARLY_SUPERIOR", below["reason_codes"])
        self.assertNotIn("ADVANTAGE_WITHIN_TOLERANCE", below["reason_codes"])

        # Just outside on the upward side: the standing only holds inside the
        # wider sensitivity band.
        above = classify(
            _entry(
                ev=1.0,
                paired_delta=outside,
                alternatives=[_alternative(ev=1.0 - outside)],
            )
        )
        self.assertEqual(above["status"], "SENSITIVE", above)
        self.assertIn("ADVANTAGE_WITHIN_SENSITIVITY_BAND", above["reason_codes"])
        self.assertNotIn("BEST_ALTERNATIVE_CLEARLY_SUPERIOR", above["reason_codes"])

    def test_clearly_superior_beyond_the_sensitivity_band_is_sensitive(self) -> None:
        entry = self._hero_below_best(
            best_ev=-1.0, hero_paired_delta=-SENSITIVE_DELTA_BB * 4.0
        )
        result = classify(entry)
        self.assertEqual(result["status"], "SENSITIVE", result)
        self.assertEqual(result["reason_codes"], ["BEST_ALTERNATIVE_CLEARLY_SUPERIOR"])

    def test_unrelated_paired_delta_does_not_mask_the_corrected_case(self) -> None:
        # A lower-ranked alternative declares its own (auto-relative) paired
        # delta: that speaks about *its* standing versus the best alternative,
        # not about the Hero-versus-best comparison, so the corrected case
        # stands. Alternative-level paired deltas are never Hero evidence.
        unrelated = _alternative(alternative_id="TIED", ev=-5.0, paired_delta=-4.0)
        entry = _entry(
            ev=-5.0,
            paired_delta=-4.0,
            alternatives=[
                _alternative(alternative_id="BEST", ev=-1.0, sizing=5.0),
                unrelated,
            ],
        )
        result = classify(entry)
        self.assertEqual(result["status"], "SENSITIVE", result)
        self.assertEqual(result["reason_codes"], ["BEST_ALTERNATIVE_CLEARLY_SUPERIOR"])

    def test_unrelated_support_status_does_not_mask_the_corrected_case(self) -> None:
        # Same rule for the declared support signal of an unrelated alternative.
        entry = _entry(
            ev=-5.0,
            paired_delta=-4.0,
            alternatives=[
                _alternative(alternative_id="BEST", ev=-1.0, sizing=5.0),
                _alternative(
                    alternative_id="TIED",
                    ev=-5.0,
                    paired_delta=-4.0,
                    support={"status": "TOO_CLOSE", "tier": "MEDIUM", "ood": False},
                ),
            ],
        )
        result = classify(entry)
        self.assertEqual(result["status"], "SENSITIVE", result)
        self.assertEqual(result["reason_codes"], ["BEST_ALTERNATIVE_CLEARLY_SUPERIOR"])
        self.assertNotIn("SUPPORT_STATUS_TOO_CLOSE", result["reason_codes"])

    def test_contradictory_hero_paired_delta_keeps_too_close(self) -> None:
        # Contradictory signals *about the relevant comparison*: the EV gap says
        # "clearly superior" while the Hero entry's own paired delta (Hero versus
        # the best alternative) declares a tie. The conservative no-claim verdict
        # and the documented precedence win -- an explicit pair never promotes a
        # sensitivity claim.
        entry = self._hero_below_best(best_ev=-1.0, hero_paired_delta=-0.01)
        result = classify(entry)
        self.assertEqual(result["status"], "TOO_CLOSE", result)
        self.assertIn("PAIRED_DELTA_WITHIN_TOLERANCE", result["reason_codes"])
        self.assertNotIn("BEST_ALTERNATIVE_CLEARLY_SUPERIOR", result["reason_codes"])

    def test_contradictory_support_status_on_the_best_alternative_keeps_too_close(self) -> None:
        entry = _entry(
            ev=-5.0,
            paired_delta=-4.0,
            alternatives=[
                _alternative(
                    alternative_id="BEST",
                    ev=-1.0,
                    support={"status": "TOO_CLOSE", "tier": "MEDIUM", "ood": False},
                )
            ],
        )
        result = classify(entry)
        self.assertEqual(result["status"], "TOO_CLOSE", result)
        self.assertIn("SUPPORT_STATUS_TOO_CLOSE", result["reason_codes"])

    def test_clearly_superior_case_still_fails_closed_on_ood(self) -> None:
        entry = self._hero_below_best(best_ev=-1.0)
        entry["support"] = {"status": "OOD_UNTESTABLE", "tier": "UNKNOWN", "ood": True}
        self.assertEqual(classify(entry)["status"], "OOD_UNTESTABLE")

    def test_clearly_superior_case_still_fails_closed_on_sparse_support(self) -> None:
        entry = self._hero_below_best(best_ev=-1.0)
        entry["support"] = {"status": "INSUFFICIENT_SUPPORT", "tier": "LOW", "ood": False}
        result = classify(entry)
        self.assertEqual(result["status"], "INSUFFICIENT_SUPPORT", result)
        self.assertIn("SUPPORT_STATUS_INSUFFICIENT", result["reason_codes"])

    def test_clearly_superior_case_still_fails_closed_on_wide_uncertainty(self) -> None:
        entry = self._hero_below_best(best_ev=-1.0)
        entry["alternatives"][0]["uncertainty"] = {
            "ci95": [-4.0, 4.0],
            "width_bb": 8.0,
            "source": "s",
        }
        result = classify(entry)
        self.assertEqual(result["status"], "INSUFFICIENT_SUPPORT", result)
        self.assertIn("CI95_WIDTH_EXCEEDS_POLICY", result["reason_codes"])

    def test_clearly_superior_verdict_is_order_independent(self) -> None:
        alternatives = [
            _alternative(alternative_id="BEST", ev=-1.0, sizing=5.0),
            _alternative(alternative_id="TIED", ev=-5.0, paired_delta=-4.0),
            _alternative(alternative_id="WORSE", ev=-7.0, paired_delta=-6.0),
        ]
        first = classify(
            _entry(ev=-5.0, paired_delta=-4.0, alternatives=copy.deepcopy(alternatives))
        )
        flipped = classify(
            _entry(
                ev=-5.0,
                paired_delta=-4.0,
                alternatives=list(reversed(copy.deepcopy(alternatives))),
            )
        )
        self.assertEqual(first, flipped)
        self.assertEqual(first["status"], "SENSITIVE")
        self.assertEqual(first["reason_codes"], ["BEST_ALTERNATIVE_CLEARLY_SUPERIOR"])

    def test_reason_code_catalogue_names_the_corrected_case(self) -> None:
        self.assertIn("BEST_ALTERNATIVE_CLEARLY_SUPERIOR", REASON_CODES)
        self.assertIn(
            "BEST_ALTERNATIVE_CLEARLY_SUPERIOR",
            REASON_CODES_BY_STATUS["SENSITIVE"],
        )
        self.assertNotIn(
            "BEST_ALTERNATIVE_CLEARLY_SUPERIOR",
            REASON_CODES_BY_STATUS["TOO_CLOSE"],
        )

    def test_ordering_support_statuses_are_the_two_ordering_claims(self) -> None:
        # Only TOO_CLOSE/SENSITIVE carry an ordering claim; the evidence-level
        # statuses are not part of the relevance-filtered signal set.
        self.assertEqual(
            ORDERING_SUPPORT_STATUS_BUCKETS,
            {"TOO_CLOSE": "TOO_CLOSE", "SENSITIVE": "SENSITIVE"},
        )


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
