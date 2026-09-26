#!/usr/bin/env python3
"""#423 T2 guard: in-fold fitted / out-of-fold evaluated response calibration.

Covers every acceptance criterion of the task:

* the report compares at least temperature scaling and vector scaling, names the
  retained method, and carries the ECE **before / after** of every stratum --
  all of it computed out-of-fold on TRAIN;
* isotonic is refused (documented fallback, or a hard failure in strict mode)
  when the preregistered support floor is not reached, with an explicit
  negative test;
* no calibration is fitted on VALIDATION and the refusal is *proved* by test
  rather than promised: the fitting surface raises on a VALIDATION or TEST
  record, the loader never requests a holdout split, and the static scan finds
  no holdout loader in the module;
* the calibration is fitted strictly in-fold (a spy proves the fitting routines
  only ever see ``provenance=in_fold_fit`` records, and refitting on a mutated
  held-out fold yields byte-identical parameters);
* the persisted report is byte-reproducible and pinned by its ``.sha256``
  sidecar.

The real-data tests run on a deterministic stride sample of the persisted TRAIN
rows and reuse the #421 harness fold protocol; the full artifact is regenerated
by ``python3 tools/preflop/generalized_response_calibration.py``.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_calibration as cal  # noqa: E402
from tools.preflop import generalized_response_model as model  # noqa: E402
from tools.training import evaluate_generalized_response_cv as harness  # noqa: E402

DATASET = ROOT / "analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.jsonl"
MODULE_PATH = ROOT / "tools/preflop/generalized_response_calibration.py"
HARNESS_PATH = ROOT / "tools/training/evaluate_generalized_response_cv.py"
REPORT_PATH = ROOT / "analysis/issue423_hybrid_router/GENERALIZED_CALIBRATION_REPORT.json"

#: Deterministic stride + fold count that keep the real-data tests fast while
#: still exercising the persisted TRAIN rows end to end.
STRIDE = 25
FAST_FOLDS = 3
FAST_CONFIG = model.make_config(tuning_max_rows=400)

_CACHE: dict[str, object] = {}


def fast_rows() -> list[dict]:
    if "rows" not in _CACHE:
        _CACHE["rows"] = cal.read_train_rows(DATASET, stride=STRIDE)
    return _CACHE["rows"]  # type: ignore[return-value]


def fast_run() -> dict:
    if "run" not in _CACHE:
        _CACHE["run"] = cal.run_calibration(
            fast_rows(), folds=FAST_FOLDS, seed=harness.CV_SEED, config=FAST_CONFIG
        )
    return _CACHE["run"]  # type: ignore[return-value]


def synthetic_rows(count: int = 600, hands: int = 60) -> list[dict]:
    """Deterministic synthetic TRAIN rows (several decisions per hand)."""
    rows = []
    for index, row in enumerate(model.synthetic_rows(count, 423)):
        rows.append(dict(row, hand_id=f"c{index % hands:04d}"))
    return rows


def _softmax(values: list[float]) -> list[float]:
    top = max(values)
    exponentials = [math.exp(value - top) for value in values]
    total = sum(exponentials)
    return [value / total for value in exponentials]


def miscalibrated_records(
    count: int = 4000,
    *,
    flat: float = 2.0,
    seed: int = 7,
    split: str = "TRAIN",
) -> list[dict]:
    """Records whose probabilities are a known flattening of the true law.

    The label is drawn from ``softmax(z)`` while the record carries
    ``softmax(z / flat)``; the inverse transform is therefore exactly a
    temperature of ``1 / flat`` and a vector scale of ``flat``.
    """
    import random

    generator = random.Random(seed)
    records: list[dict] = []
    for _ in range(count):
        logits = [generator.gauss(0.0, 1.6) for _ in model.ACTIONS]
        truth = _softmax(logits)
        draw = generator.random()
        cumulative = 0.0
        observed = model.ACTIONS[-1]
        for action, probability in zip(model.ACTIONS, truth):
            cumulative += probability
            if draw <= cumulative:
                observed = action
                break
        flattened = _softmax([value / flat for value in logits])
        records.append(
            {
                "split": split,
                "observed": observed,
                "probabilities": dict(zip(model.ACTIONS, flattened)),
                "masked_actions": [],
            }
        )
    return records


def ece(records: list[dict]) -> float:
    return harness.expected_calibration_error(records)["ece"]


PRIOR = {action: 0.25 for action in model.ACTIONS}


def calibrated(records: list[dict], fitted: dict) -> list[dict]:
    return [
        {
            "observed": record["observed"],
            "probabilities": cal.vector_to_probabilities(
                cal.apply_calibration(fitted, cal.probability_vector(record["probabilities"]))
            ),
        }
        for record in records
    ]


# ---------------------------------------------------------------------------
# split guards: TRAIN only
# ---------------------------------------------------------------------------


class SplitGuardTests(unittest.TestCase):
    def test_the_module_consumes_train_only(self) -> None:
        self.assertEqual(cal.CONSUMED_SPLITS, ("TRAIN",))
        self.assertEqual(cal.ALLOWED_SPLITS, ("TRAIN",))
        self.assertEqual(cal.REFUSED_SPLITS, ("VALIDATION", "TEST"))
        self.assertEqual(cal.FORBIDDEN_SPLITS, ("TEST",))

    def test_fitting_refuses_validation_and_test_records(self) -> None:
        records = miscalibrated_records(200)
        for split in ("VALIDATION", "TEST"):
            with self.subTest(split=split):
                poisoned = [dict(record, split=split) for record in records]
                with self.assertRaises(cal.CalibrationError):
                    cal.fit_temperature(poisoned)
                with self.assertRaises(cal.CalibrationError):
                    cal.fit_vector_scaling(poisoned)
                with self.assertRaises(cal.CalibrationError):
                    cal.fit_isotonic(poisoned)
                with self.assertRaises(cal.CalibrationError):
                    cal.calibrate_record(cal.fit_temperature(records), poisoned[0])

    def test_a_record_without_an_explicit_train_split_is_refused(self) -> None:
        records = miscalibrated_records(200)
        for record in records:
            record.pop("split")
        with self.assertRaises(cal.CalibrationError):
            cal.fit_temperature(records)

    def test_the_cross_validation_refuses_a_holdout_row(self) -> None:
        rows = synthetic_rows(200, 20)
        rows[0] = dict(rows[0], split="VALIDATION")
        with self.assertRaises(cal.CalibrationError):
            cal.run_calibration(
                rows, folds=2, seed=harness.CV_SEED, config=model.make_config(tuning_max_rows=100)
            )

    def test_the_loader_never_requests_a_holdout_split(self) -> None:
        recorded: list[tuple[str, ...]] = []
        original = model.read_dataset_rows

        def spy(path, *, splits=model.TRAIN_SPLITS):  # type: ignore[no-untyped-def]
            recorded.append(tuple(str(split) for split in splits))
            return original(path, splits=splits)

        with mock.patch.object(model, "read_dataset_rows", side_effect=spy):
            rows = cal.read_train_rows(DATASET, stride=500)
        self.assertTrue(rows)
        self.assertTrue(recorded, "the calibration did not read the dataset through the harness loader")
        for splits in recorded:
            self.assertNotIn("VALIDATION", splits)
            self.assertNotIn("TEST", splits)
        self.assertIn("tools/training/evaluate_generalized_response_cv.py", str(HARNESS_PATH))
        self.assertIn("read_train_rows", Path(HARNESS_PATH).read_text(encoding="utf-8"))

    def test_static_scan_proves_the_module_names_no_holdout_loader(self) -> None:
        scan = cal.verify_no_holdout_access()
        self.assertEqual(scan["result"], "PASS", scan["hits"])
        self.assertEqual(scan["hits"], [])
        planted = (
            "def f(tool):\n"
            "    tool.load_holdout()\n"
            "    tool.read_dataset_rows(path, splits=('VALIDATION',))\n"
        )
        broken = cal.verify_no_holdout_access(planted)
        self.assertEqual(broken["result"], "FAIL")
        self.assertTrue(broken["hits"])

    def test_module_reads_train_through_the_harness(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        calls = [
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        self.assertIn("read_train_rows", calls)
        self.assertNotIn("read_dataset_rows", calls)


# ---------------------------------------------------------------------------
# in-fold fitting
# ---------------------------------------------------------------------------


class InFoldFitTests(unittest.TestCase):
    def split_fold(self) -> harness.Fold:
        rows = synthetic_rows(500, 50)
        split = harness.grouped_folds(rows, folds=3, seed=harness.CV_SEED)
        return split[0]

    def test_the_fitting_surface_only_ever_sees_in_fold_records(self) -> None:
        split_fold = self.split_fold()
        seen: list[list[dict]] = []
        original = cal.fit_calibration

        def spy(method, records, **kwargs):  # type: ignore[no-untyped-def]
            seen.append([dict(record) for record in records])
            return original(method, records, **kwargs)

        with mock.patch.object(cal, "fit_calibration", side_effect=spy):
            result = cal.Fold(
                split_fold,
                model.ARCH_REGULARIZED,
                seed=harness.CV_SEED,
                config=model.make_config(tuning_max_rows=120),
                methods=cal.COMPARED_METHODS,
                strict_isotonic=False,
                fit_max_rows=cal.CALIBRATION_FIT_MAX_ROWS,
            )
        self.assertEqual(len(seen), len(cal.COMPARED_METHODS))
        for records in seen:
            self.assertTrue(records)
            self.assertTrue(all(record["provenance"] == "in_fold_fit" for record in records))
            hands = {record["hand_id"] for record in records}
            self.assertTrue(hands <= split_fold.train_hands)
            self.assertEqual(hands & split_fold.holdout_hands, set())
        self.assertTrue(result.out_of_fold_records)
        self.assertTrue(
            all(record["provenance"] == "out_of_fold_holdout" for record in result.out_of_fold_records)
        )
        self.assertTrue(
            {record["hand_id"] for record in result.out_of_fold_records} <= split_fold.holdout_hands
        )

    def test_the_fitted_parameters_never_depend_on_the_held_out_fold(self) -> None:
        split_fold = self.split_fold()
        flipped = [dict(row) for row in split_fold.holdout_rows]
        for row in flipped:
            row["action"] = "JAM" if row["action"] != "JAM" else "FOLD"
        mutated = harness.Fold(split_fold.index, list(split_fold.train_rows), flipped)
        kwargs = {
            "seed": harness.CV_SEED,
            "config": model.make_config(tuning_max_rows=120),
            "methods": cal.COMPARED_METHODS,
            "strict_isotonic": False,
            "fit_max_rows": cal.CALIBRATION_FIT_MAX_ROWS,
        }
        baseline = cal.Fold(split_fold, model.ARCH_REGULARIZED, **kwargs)
        perturbed = cal.Fold(mutated, model.ARCH_REGULARIZED, **kwargs)
        for method in cal.COMPARED_METHODS:
            with self.subTest(method=method):
                self.assertEqual(
                    baseline.fitted[method]["admitted"], perturbed.fitted[method]["admitted"]
                )
                self.assertEqual(baseline.fitted[method]["params"], perturbed.fitted[method]["params"])
        # ... while the out-of-fold surface does move: the held-out labels changed.
        self.assertNotEqual(
            baseline.metrics(cal.METHOD_UNCALIBRATED)["log_loss_bits_per_decision"],
            perturbed.metrics(cal.METHOD_UNCALIBRATED)["log_loss_bits_per_decision"],
        )


# ---------------------------------------------------------------------------
# isotonic: gated by a preregistered support floor
# ---------------------------------------------------------------------------


class IsotonicGateTests(unittest.TestCase):
    def test_isotonic_is_refused_below_the_preregistered_support_floor(self) -> None:
        records = miscalibrated_records(120)
        fitted = cal.fit_isotonic(records)
        self.assertFalse(fitted["admitted"])
        self.assertIsNone(fitted["params"])
        refusal = fitted["refusal"]
        self.assertEqual(refusal["reason"], "INSUFFICIENT_SUPPORT")
        self.assertTrue(refusal["gate"]["failures"])
        self.assertEqual(refusal["gate"]["minimum_support"], cal.ISOTONIC_MINIMUM_SUPPORT)
        self.assertIn("never applied and never scored", refusal["fallback"])
        # The refusal is harmless: applying it is the identity, never a map.
        probabilities = cal.probability_vector(records[0]["probabilities"])
        self.assertEqual(
            cal.apply_calibration(fitted, probabilities),
            cal.normalize_vector(probabilities, frozenset()),
        )

    def test_strict_mode_fails_closed_instead_of_falling_back(self) -> None:
        records = miscalibrated_records(120)
        with self.assertRaises(cal.CalibrationError):
            cal.fit_isotonic(records, strict=True)
        with self.assertRaises(cal.CalibrationError):
            cal.fit_calibration(cal.METHOD_ISOTONIC, records, strict_isotonic=True)

    def test_a_single_starved_class_refuses_the_whole_map(self) -> None:
        records = miscalibrated_records(4000, seed=3)
        support = cal.isotonic_support(records)
        gate = cal.evaluate_isotonic_gate(support)
        self.assertTrue(gate["admitted"])
        starved = [record for record in records if record["observed"] != model.ACTIONS[-1]]
        starved_support = cal.isotonic_support(starved)
        starved_gate = cal.evaluate_isotonic_gate(starved_support)
        self.assertFalse(starved_gate["admitted"])
        self.assertIn(
            model.ACTIONS[-1],
            [failure.get("action") for failure in starved_gate["failures"]],
        )

    def test_isotonic_is_admitted_above_the_floor_and_is_monotone(self) -> None:
        records = miscalibrated_records(4000, seed=5)
        fitted = cal.fit_isotonic(records)
        self.assertTrue(fitted["admitted"], fitted["refusal"])
        self.assertTrue(fitted["params_inlined"])
        for action in model.ACTIONS:
            knots = fitted["params"]["knots"][action]
            self.assertEqual(len(knots["x"]), len(knots["y"]))
            self.assertTrue(knots["x"], action)
            for left, right in zip(knots["x"], knots["x"][1:]):
                self.assertLessEqual(left, right)
            for left, right in zip(knots["y"], knots["y"][1:]):
                self.assertLessEqual(left, right)
            self.assertLessEqual(len(knots["x"]), cal.ISOTONIC_MAX_INLINE_KNOTS)

    def test_a_refused_isotonic_never_enters_the_selection(self) -> None:
        run = cal.run_calibration(
            synthetic_rows(400, 40),
            folds=3,
            seed=harness.CV_SEED,
            config=model.make_config(tuning_max_rows=120),
            fit_max_rows=800,
        )
        for architecture, block in run["architectures"].items():
            with self.subTest(architecture=architecture):
                isotonic = block["out_of_fold"][cal.METHOD_ISOTONIC]
                if block["selection"]["evidence"][cal.METHOD_ISOTONIC]["admissible"]:
                    continue
                self.assertFalse(isotonic["scored"])
                self.assertNotEqual(block["retained"]["method"], cal.METHOD_ISOTONIC)
                self.assertIn(
                    cal.METHOD_ISOTONIC,
                    block["selection"]["trace"][0]["eliminated"],
                )
                self.assertIn("fallback", block["selection"]["criteria"])

    def test_the_isotonic_map_interpolates_between_knots_and_is_anchored(self) -> None:
        # Regression guard: reading the pool-adjacent-violators knots as a step
        # map mapped every probability in [0.16, 0.30) to 0.0, which destroyed
        # the out-of-fold log loss of the decisions observed inside that band.
        xs = [0.16, 0.30, 0.62, 0.90]
        ys = [0.0, 0.10, 0.55, 1.0]
        self.assertEqual(cal.isotonic_lookup(xs, ys, 0.0), 0.0)
        self.assertEqual(cal.isotonic_lookup(xs, ys, 1.0), 1.0)
        inside = cal.isotonic_lookup(xs, ys, 0.20)
        self.assertGreater(inside, 0.0)
        self.assertLess(inside, 0.10)
        self.assertAlmostEqual(cal.isotonic_lookup(xs, ys, 0.30), 0.10, places=12)
        self.assertAlmostEqual(cal.isotonic_lookup(xs, ys, 0.62), 0.55, places=12)
        walk = [cal.isotonic_lookup(xs, ys, step / 50.0) for step in range(51)]
        for left, right in zip(walk, walk[1:]):
            self.assertLessEqual(left, right + 1e-12)
        # Outside the fitted range the map heads for the identity anchors rather
        # than clamping to the first / last knot frequency.
        xs_positive = [0.20, 0.80]
        ys_positive = [0.30, 0.70]
        self.assertAlmostEqual(cal.isotonic_lookup(xs_positive, ys_positive, 0.10), 0.15, places=12)
        self.assertAlmostEqual(cal.isotonic_lookup(xs_positive, ys_positive, 0.90), 0.85, places=12)
        self.assertEqual(cal.isotonic_lookup(xs_positive, ys_positive, 0.0), 0.0)
        self.assertEqual(cal.isotonic_lookup(xs_positive, ys_positive, 1.0), 1.0)
        # No knots at all: the identity is returned, never a fabricated extreme.
        self.assertAlmostEqual(cal.isotonic_lookup([], [], 0.37), 0.37, places=12)

    def test_isotonic_generalises_on_records_it_was_not_fitted_on(self) -> None:
        for flat in (1.5, 2.0, 3.0):
            with self.subTest(flat=flat):
                fitted = cal.fit_isotonic(miscalibrated_records(4000, flat=flat, seed=101))
                held_out = miscalibrated_records(3000, flat=flat, seed=202)
                self.assertTrue(fitted["admitted"], fitted["refusal"])
                before = harness.summary_metrics(held_out, PRIOR)
                after = harness.summary_metrics(calibrated(held_out, fitted), PRIOR)
                self.assertLessEqual(
                    after["log_loss_bits_per_decision"],
                    before["log_loss_bits_per_decision"] + 1e-9,
                )
                self.assertLess(
                    after["expected_calibration_error"]["ece"],
                    before["expected_calibration_error"]["ece"],
                )


# ---------------------------------------------------------------------------
# the comparison itself
# ---------------------------------------------------------------------------


class CalibrationFamilyTests(unittest.TestCase):
    def test_temperature_scaling_recovers_a_known_miscalibration(self) -> None:
        records = miscalibrated_records(4000, flat=2.0, seed=11)
        fitted = cal.fit_temperature(records)
        self.assertTrue(fitted["admitted"])
        self.assertAlmostEqual(fitted["params"]["temperature"], 0.5, delta=0.05)
        self.assertLess(
            fitted["in_fold_log_loss"]["fitted"], fitted["in_fold_log_loss"]["uncalibrated"]
        )
        self.assertLess(ece(calibrated(records, fitted)), ece(records))

    def test_vector_scaling_recovers_the_known_scale_and_never_degrades(self) -> None:
        records = miscalibrated_records(4000, flat=2.0, seed=13)
        fitted = cal.fit_vector_scaling(records)
        self.assertTrue(fitted["admitted"])
        scales = [fitted["params"]["scale"][action] for action in model.ACTIONS]
        self.assertAlmostEqual(sum(scales) / len(scales), 2.0, delta=0.35)
        before = harness.summary_metrics(records, {action: 0.25 for action in model.ACTIONS})
        after = harness.summary_metrics(
            calibrated(records, fitted), {action: 0.25 for action in model.ACTIONS}
        )
        self.assertLessEqual(
            after["log_loss_bits_per_decision"], before["log_loss_bits_per_decision"] + 1e-9
        )

    def test_every_calibrated_distribution_stays_legal(self) -> None:
        records = miscalibrated_records(4000, seed=17)
        records[0]["masked_actions"] = ["JAM", "RAISE"]
        for method in cal.COMPARED_METHODS:
            with self.subTest(method=method):
                fitted = cal.fit_calibration(method, records)
                for record in records[:200] + records[-1:]:
                    mask = cal.masked_actions(record)
                    values = cal.apply_calibration(
                        fitted, cal.probability_vector(record["probabilities"]), mask
                    )
                    self.assertAlmostEqual(sum(values), 1.0, places=12)
                    self.assertTrue(all(value >= 0.0 for value in values))
                    for index, action in enumerate(model.ACTIONS):
                        if action in mask:
                            self.assertEqual(values[index], 0.0)

    def test_the_comparison_lists_at_least_temperature_and_vector_scaling(self) -> None:
        run = fast_run()
        self.assertEqual(
            list(run["protocol"]["compared_methods"]),
            [cal.METHOD_TEMPERATURE, cal.METHOD_VECTOR, cal.METHOD_ISOTONIC],
        )
        for architecture, block in run["architectures"].items():
            with self.subTest(architecture=architecture):
                for method in (cal.METHOD_UNCALIBRATED, cal.METHOD_TEMPERATURE, cal.METHOD_VECTOR):
                    self.assertTrue(block["out_of_fold"][method]["scored"], method)
                    self.assertIsInstance(
                        block["out_of_fold"][method]["expected_calibration_error"]["ece"], float
                    )
                self.assertIn(block["retained"]["method"], cal.EVALUATED_METHODS)


# ---------------------------------------------------------------------------
# harness integration, metrics and the persisted report
# ---------------------------------------------------------------------------


class HarnessIntegrationTests(unittest.TestCase):
    def test_the_calibration_folds_are_the_harness_folds(self) -> None:
        run = fast_run()
        split = harness.grouped_folds(fast_rows(), folds=FAST_FOLDS, seed=harness.CV_SEED)
        self.assertEqual(run["protocol"]["no_leak"], harness.no_leak_proof(split))
        self.assertEqual(run["protocol"]["no_leak"]["max_hand_overlap_between_fit_and_holdout"], 0)
        self.assertEqual(run["protocol"]["no_leak"]["group_key"], "hand_id")
        self.assertEqual(run["protocol"]["folds"], FAST_FOLDS)
        self.assertEqual(run["folds"], [fold.summary() for fold in split])
        self.assertEqual(
            run["protocol"]["fold_assignment"],
            f"int(stable_hash('grm-cv/{harness.CV_SEED}/<hand_id>')[:8], 16) % {FAST_FOLDS}",
        )

    def test_the_before_column_reproduces_the_harness_out_of_fold_metrics(self) -> None:
        run = fast_run()
        reference = harness.run_cross_validation(
            fast_rows(),
            folds=FAST_FOLDS,
            seed=harness.CV_SEED,
            architectures=[model.ARCH_REGULARIZED],
            config=FAST_CONFIG,
        )["architectures"][model.ARCH_REGULARIZED]
        mine = run["architectures"][model.ARCH_REGULARIZED]["out_of_fold"][cal.METHOD_UNCALIBRATED]
        self.assertAlmostEqual(
            mine["log_loss_bits_per_decision"],
            reference["out_of_fold"]["log_loss_bits_per_decision"],
            places=9,
        )
        self.assertAlmostEqual(
            mine["expected_calibration_error"]["ece"],
            reference["out_of_fold"]["expected_calibration_error"]["ece"],
            places=9,
        )
        self.assertAlmostEqual(
            mine["brier_score"], reference["out_of_fold"]["brier_score"], places=9
        )
        for stratum in harness.STRATA:
            with self.subTest(stratum=stratum):
                self.assertAlmostEqual(
                    mine["by_stratum"][stratum]["expected_calibration_error"]["ece"] or 0.0,
                    reference["strata"]["metrics"][stratum]["expected_calibration_error"]["ece"] or 0.0,
                    places=9,
                )

    def test_the_report_carries_the_ece_before_and_after_of_every_stratum(self) -> None:
        run = fast_run()
        for architecture, block in run["architectures"].items():
            with self.subTest(architecture=architecture):
                table = block["ece_before_after_by_stratum"]
                self.assertEqual(sorted(table), sorted(harness.STRATA))
                retained = block["retained"]["method"]
                for stratum, row in table.items():
                    self.assertEqual(
                        row["n"],
                        block["out_of_fold"][cal.METHOD_UNCALIBRATED]["by_stratum"][stratum]["n"],
                    )
                    self.assertEqual(
                        row["ece_after"],
                        block["out_of_fold"][retained]["by_stratum"][stratum][
                            "expected_calibration_error"
                        ]["ece"],
                    )
                    self.assertEqual(
                        row["ece_before"],
                        block["out_of_fold"][cal.METHOD_UNCALIBRATED]["by_stratum"][stratum][
                            "expected_calibration_error"
                        ]["ece"],
                    )
                covered = [
                    name
                    for name in (harness.STRATUM_FREQUENT_EXACT, harness.STRATUM_RARE_EXACT)
                    if block["selection"]["evidence"][cal.METHOD_UNCALIBRATED]["admissible"]
                ]
                for name in covered:
                    self.assertGreater(table[name]["n"], 0, name)
                    self.assertIsInstance(table[name]["ece_before"], float)
                    self.assertIsInstance(table[name]["ece_after"], float)

    def test_the_retained_method_is_chosen_out_of_fold_only(self) -> None:
        run = fast_run()
        for architecture, block in run["architectures"].items():
            with self.subTest(architecture=architecture):
                selection = block["selection"]
                self.assertTrue(selection["criteria"]["preregistered"])
                self.assertEqual(selection["consumed_splits"], ["TRAIN"])
                self.assertFalse(selection["validation_consumed"])
                self.assertFalse(selection["test_consumed"])
                self.assertEqual(selection["evidence_basis"], "out_of_fold_holdout_only")
                self.assertIn(selection["retained"], selection["admissible_methods"])
                for evidence in selection["evidence"].values():
                    self.assertIn("out_of_fold_expected_calibration_error", evidence)
                self.assertIn("TRAIN out-of-fold evidence only", run["justification"][architecture])
        self.assertTrue(run["retained_method"] in cal.EVALUATED_METHODS)
        self.assertEqual(run["retained_architecture"], model.ARCH_REGULARIZED)

    def test_the_log_loss_guard_bounds_the_retained_method(self) -> None:
        run = fast_run()
        for architecture, block in run["architectures"].items():
            with self.subTest(architecture=architecture):
                steps = [step["metric"] for step in block["selection"]["criteria"]["steps"]]
                self.assertEqual(steps[1], "out_of_fold.log_loss_bits_per_decision")
                self.assertLess(
                    steps.index("out_of_fold.log_loss_bits_per_decision"),
                    steps.index("out_of_fold.expected_calibration_error.ece"),
                )
                evidence = block["selection"]["evidence"]
                retained = evidence[block["retained"]["method"]]
                baseline = evidence[cal.METHOD_UNCALIBRATED]
                self.assertLessEqual(
                    retained["out_of_fold_log_loss_bits_per_decision"],
                    baseline["out_of_fold_log_loss_bits_per_decision"]
                    + cal.SELECTION_LOGLOSS_TOLERANCE_BITS,
                )
                self.assertIsNotNone(retained["out_of_fold_expected_calibration_error"])

    def test_the_report_proves_that_validation_is_never_recalibrated(self) -> None:
        run = fast_run()
        guard = run["protocol"]["no_validation_recalibration"]
        self.assertEqual(guard["consumed_splits"], ["TRAIN"])
        self.assertEqual(guard["recalibrated_splits"], ["TRAIN"])
        self.assertEqual(guard["refused_splits"], ["VALIDATION", "TEST"])
        self.assertFalse(guard["validation_consumed"])
        self.assertFalse(guard["test_consumed"])
        self.assertEqual(guard["static_scan"]["result"], "PASS")
        self.assertIn("assert_train_only", guard["enforcement"])
        self.assertIn("CalibrationError", guard["enforcement"])
        for architecture, block in run["architectures"].items():
            with self.subTest(architecture=architecture):
                for fold in block["folds"]:
                    self.assertEqual(fold["hand_overlap_with_fit"], 0)
                    self.assertTrue(fold["fit_rows"] > 0)


class PersistenceTests(unittest.TestCase):
    def test_the_report_is_written_byte_reproducibly_with_a_digest_sidecar(self) -> None:
        report = cal.build_report(
            DATASET, folds=2, seed=harness.CV_SEED, stride=1000, config=FAST_CONFIG
        )
        second = cal.build_report(
            DATASET, folds=2, seed=harness.CV_SEED, stride=1000, config=FAST_CONFIG
        )
        self.assertEqual(cal.persisted_report_text(report), cal.persisted_report_text(second))
        with tempfile.TemporaryDirectory() as directory:
            first = cal.write_report(report, Path(directory) / "a.json")
            second_path = cal.write_report(second, Path(directory) / "b.json")
            self.assertEqual(first.read_bytes(), second_path.read_bytes())
            digest = json.dumps(
                cal._finalize(report), sort_keys=True, indent=2, ensure_ascii=True
            ).encode("utf-8") + b"\n"
            sidecar = (Path(directory) / "a.sha256").read_text(encoding="utf-8").splitlines()
            self.assertEqual(sidecar[0], f"{cal.sha256_bytes(digest)}  a.json")
            self.assertTrue(sidecar[1].startswith("# canonical_payload_sha256 "))
            self.assertIn("# scope TRAIN_ONLY_NO_VALIDATION_RECALIBRATION", sidecar)
            self.assertNotIn(b"/home/", first.read_bytes())

    def test_the_canonical_payload_pins_every_field_but_itself(self) -> None:
        report = cal.build_report(
            DATASET, folds=2, seed=harness.CV_SEED, stride=1000, config=FAST_CONFIG
        )
        self.assertEqual(
            report["canonical_payload_sha256"],
            model.stable_hash(cal._canonical_payload(cal._finalize(report))),
        )
        altered = dict(report, retained_method="temperature_scaling")
        self.assertNotEqual(
            model.stable_hash(cal._canonical_payload(cal._finalize(altered))),
            report["canonical_payload_sha256"],
        )

    def test_the_report_records_the_model_config_it_ran_with(self) -> None:
        report = cal.build_report(
            DATASET, folds=2, seed=harness.CV_SEED, stride=1000, config=FAST_CONFIG
        )
        self.assertEqual(report["protocol"]["model_config"], FAST_CONFIG)
        self.assertEqual(report["protocol"]["model_config_source"], "explicit")
        default = cal.build_report(DATASET, folds=2, seed=harness.CV_SEED, stride=2000)
        self.assertEqual(default["protocol"]["model_config"], model.make_config())
        self.assertEqual(default["protocol"]["model_config_source"], "library_default")

    def test_check_full_rebuilds_the_persisted_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.json"
            report = cal.build_report(
                DATASET,
                folds=2,
                seed=harness.CV_SEED,
                stride=800,
                config=FAST_CONFIG,
                fit_max_rows=2000,
            )
            cal.write_report(report, target)
            self.assertEqual(cal.verify_persisted(target), [])
            self.assertEqual(cal.check_full(target), [])
            # A drifted sidecar is caught before any rebuild.
            target.with_suffix(".sha256").write_text(
                f"{'0' * 64}  report.json\n", encoding="utf-8"
            )
            self.assertTrue(cal.verify_persisted(target))

    def test_the_persisted_report_is_present_and_self_consistent(self) -> None:
        if not REPORT_PATH.exists():
            self.skipTest("the persisted calibration report has not been generated yet")
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(report["schema"], cal.REPORT_SCHEMA)
        self.assertEqual(report["module_sha256"], cal.sha256_file(MODULE_PATH))
        self.assertEqual(report["harness"]["module_sha256"], cal.sha256_file(HARNESS_PATH))
        self.assertEqual(report["scope"]["split"], "TRAIN")
        self.assertEqual(report["scope"]["consumed_splits"], ["TRAIN"])
        self.assertEqual(report["scope"]["recalibrated_splits"], ["TRAIN"])
        self.assertFalse(report["scope"]["validation_consumed"])
        self.assertFalse(report["scope"]["test_consumed"])
        self.assertEqual(report["scope"]["rows"], report["scope"]["cross_validated_rows"])
        self.assertTrue(report["guards"]["validation_recalibration_refused"])
        self.assertTrue(report["guards"]["isotonic_support_gate_enforced"])
        self.assertTrue(report["guards"]["no_holdout_loader"])
        consistency = report["harness"]["train_cv_report_consistency"]
        self.assertTrue(consistency["checked"], consistency["reason"])
        self.assertTrue(consistency["within_tolerance"], consistency["architectures"])
        self.assertEqual(report["harness"]["selected_architecture"], model.ARCH_REGULARIZED)
        self.assertEqual(report["harness"]["headline_architecture"], report["retained_architecture"])
        for architecture, comparison in consistency["architectures"].items():
            with self.subTest(architecture=architecture):
                self.assertTrue(all(comparison["equal_at_published_precision"].values()), comparison)
                self.assertEqual(comparison["absolute_delta"]["expected_calibration_error"], 0.0)
        self.assertEqual(
            report["protocol"]["no_leak"]["max_hand_overlap_between_fit_and_holdout"], 0
        )
        self.assertIn(report["retained_method"], cal.EVALUATED_METHODS)
        for architecture, block in report["architectures"].items():
            with self.subTest(architecture=architecture):
                self.assertIn(
                    block["retained"]["method"], cal.EVALUATED_METHODS
                )
                for method in (cal.METHOD_TEMPERATURE, cal.METHOD_VECTOR):
                    self.assertTrue(block["out_of_fold"][method]["scored"])
                self.assertEqual(
                    sorted(block["ece_before_after_by_stratum"]), sorted(harness.STRATA)
                )
        self.assertEqual(cal.verify_persisted(REPORT_PATH), [])

    def test_the_self_check_cli_reports_the_comparison(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exit_code = cal.main(["--self-check", "--seed", "5"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["schema"], cal.SELF_CHECK_SCHEMA)
        self.assertEqual(payload["static_scan"], "PASS")
        self.assertFalse(payload["validation_consumed"])
        self.assertFalse(payload["test_consumed"])
        self.assertEqual(sorted(payload["retained_methods_by_architecture"]), sorted(model.ARCHITECTURES))
        self.assertEqual(
            list(payload["compared_methods"]), [cal.METHOD_TEMPERATURE, cal.METHOD_VECTOR, cal.METHOD_ISOTONIC]
        )

    def test_cli_print_only_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.json"
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                exit_code = cal.main(
                    [
                        "--print",
                        "--stride",
                        "2000",
                        "--folds",
                        "2",
                        "--dataset",
                        str(DATASET),
                        "--out",
                        str(target),
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertFalse(target.exists())
            printed = json.loads(buffer.getvalue())
            self.assertEqual(printed["schema"], cal.REPORT_SCHEMA)
            self.assertEqual(printed["scope"]["row_stride"], 2000)


class DependencySurfaceTests(unittest.TestCase):
    def test_the_module_depends_on_the_standard_library_only(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
        stdlib = set(sys.stdlib_module_names)
        for module in modules:
            if module == "tools":
                continue
            self.assertIn(module, stdlib, f"{module} is not in the standard library")


if __name__ == "__main__":
    unittest.main(verbosity=2)
