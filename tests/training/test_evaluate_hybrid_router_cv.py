#!/usr/bin/env python3
"""#423 T4 guard: cross-fitted TRAIN-only hybrid router comparison + derivation.

Covers every acceptance criterion of the task:

* the harness reuses the #421 hand-grouped folds and proves, by assertion, that
  no hand sits on both sides of a split;
* VALIDATION and TEST are refused fail-closed at the loader, at the guard and
  in a static scan of the module source, and the loader never requests them;
* the comparison carries log loss, Brier, ECE, coverage and abstain rate for
  the three channels, per stratum and on a separate ``LIMPER_VS_ISO`` surface;
* the OOD stratum is measured with synthetic probes on which the router fails
  closed;
* the paired-by-hand bootstrap publishes its dispersion, its confidence
  intervals and the effectifs every stratum contributed;
* two runs are byte-identical and the persisted derivation is pinned by its
  ``.sha256`` sidecar.

``pytest`` is not a declared dependency of this repository; the suite is a
plain ``unittest`` module, run with ``python3 -m unittest`` like its siblings.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_model as model  # noqa: E402
from tools.training import evaluate_generalized_response_cv as cv  # noqa: E402
from tools.training import evaluate_hybrid_router_cv as harness  # noqa: E402

MODULE_PATH = ROOT / "tools/training/evaluate_hybrid_router_cv.py"
HARNESS_PATH = ROOT / "tools/training/evaluate_generalized_response_cv.py"
DERIVATION_PATH = ROOT / "analysis/issue423_hybrid_router/derivation/CV_DERIVATION.json"
DATASET = model.DEFAULT_DATASET

#: The two splits the harness must never require or read.
FORBIDDEN_SPLITS = ("VALIDATION", "TEST")

#: ``POKER_HYBRID_ROUTER_CV_FULL=1`` refits the persisted derivation (~minutes).
FULL = os.environ.get("POKER_HYBRID_ROUTER_CV_FULL", "") == "1"


def synthetic_rows(count: int = 900, hands: int = 90) -> list[dict]:
    rows = []
    for index, row in enumerate(model.synthetic_rows(count, 423)):
        rows.append(dict(row, hand_id=f"hyb-hand-{index % hands:04d}"))
    return rows


def fast_run(rows: list[dict] | None = None) -> dict:
    """Small end-to-end run: three folds, short probes, few bootstrap samples."""
    return harness.run_cross_validation(
        rows if rows is not None else synthetic_rows(),
        folds=3,
        seed=cv.CV_SEED,
        config=model.make_config(tuning_max_rows=300),
        fit_max_rows=1500,
        probe_limit=3,
        samples=120,
    )


def fast_artifact(stride: int = 400) -> dict:
    return harness.build_derivation(
        DATASET,
        folds=3,
        seed=cv.CV_SEED,
        stride=stride,
        probe_limit=2,
        samples=64,
        fit_max_rows=1500,
    )


# ---------------------------------------------------------------------------
# fail-closed split guards
# ---------------------------------------------------------------------------


class TrainOnlyGuardTests(unittest.TestCase):
    def test_the_module_consumes_train_only(self) -> None:
        self.assertEqual(harness.CONSUMED_SPLITS, ("TRAIN",))
        self.assertEqual(harness.MAIN_SPLIT, "TRAIN")
        for split in FORBIDDEN_SPLITS:
            self.assertIn(split, harness.REFUSED_SPLITS)

    def test_a_validation_row_is_refused(self) -> None:
        row = dict(model.synthetic_rows(1, 1)[0], split="VALIDATION")
        with self.assertRaises(harness.HybridRouterCvError):
            harness.assert_train_only([row], context="test")

    def test_a_test_row_is_refused(self) -> None:
        row = dict(model.synthetic_rows(1, 1)[0], split="TEST")
        with self.assertRaises(harness.HybridRouterCvError):
            harness.assert_train_only([row], context="test")

    def test_a_row_without_an_explicit_train_split_is_refused(self) -> None:
        row = dict(model.synthetic_rows(1, 1)[0])
        row.pop("split")
        with self.assertRaises(harness.HybridRouterCvError):
            harness.assert_train_only([row], context="test")

    def test_a_refused_split_is_also_refused_when_requested(self) -> None:
        for split in FORBIDDEN_SPLITS:
            with self.assertRaises(harness.HybridRouterCvError):
                harness.assert_consumed_splits(("TRAIN", split), context="test")
        self.assertEqual(harness.assert_consumed_splits(("train",), context="test"), ["TRAIN"])

    def test_the_cross_validation_refuses_a_holdout_row(self) -> None:
        rows = synthetic_rows(300, 30)
        for split in FORBIDDEN_SPLITS:
            poisoned = [dict(row) for row in rows]
            poisoned[0]["split"] = split
            with self.assertRaises(harness.HybridRouterCvError):
                harness.run_cross_validation(
                    poisoned, folds=3, config=model.make_config(tuning_max_rows=200)
                )

    def test_the_loader_never_requests_a_holdout_split(self) -> None:
        recorded: list[tuple[str, ...]] = []
        original = model.read_dataset_rows

        def spy(path, *, splits=model.TRAIN_SPLITS):  # type: ignore[no-untyped-def]
            recorded.append(tuple(str(split) for split in splits))
            return original(path, splits=splits)

        with mock.patch.object(model, "read_dataset_rows", side_effect=spy):
            rows = harness.read_train_rows(DATASET, stride=400)
        self.assertTrue(rows)
        self.assertTrue(recorded, "the harness did not read the dataset through the loader")
        for splits in recorded:
            self.assertNotIn("VALIDATION", splits)
            self.assertNotIn("TEST", splits)

    def test_a_dataset_carrying_a_validation_row_yields_train_rows_only(self) -> None:
        """A holdout row present in the file is never selected by the loader."""
        rows = model.synthetic_rows(6, 11)
        rows[3] = dict(rows[3], hand_id="holdout-hand", split="VALIDATION")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "poisoned.jsonl"
            path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
            )
            selected = harness.read_train_rows(path)
            self.assertEqual(len(selected), len(rows) - 1)
            self.assertEqual(harness.assert_train_only(selected, context="test"), len(selected))
            self.assertNotIn("holdout-hand", {row["hand_id"] for row in selected})

    def test_static_scan_proves_the_module_names_no_holdout_loader(self) -> None:
        scan = harness.verify_no_holdout_access()
        self.assertEqual(scan["result"], "PASS", scan["hits"])
        self.assertEqual(scan["hits"], [])
        planted = (
            "def f(tool):\n"
            "    tool.load_holdout()\n"
            "    tool.read_dataset_rows(path, splits=('VALIDATION',))\n"
        )
        broken = harness.verify_no_holdout_access(planted)
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
# hand-grouped folds
# ---------------------------------------------------------------------------


class NoLeakTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cv_run = fast_run()

    def test_no_hand_is_on_both_sides_of_a_split(self) -> None:
        proof = self.cv_run["protocol"]["no_leak"]
        self.assertEqual(proof["group_key"], "hand_id")
        self.assertTrue(proof["checked_at_runtime"])
        self.assertTrue(proof["hands_assigned_to_exactly_one_fold"])
        self.assertTrue(proof["holdout_hands_pairwise_disjoint"])
        self.assertEqual(proof["max_hand_overlap_between_fit_and_holdout"], 0)
        for fold in self.cv_run["folds"]:
            self.assertEqual(fold["hand_overlap_with_fit"], 0)
            self.assertEqual(fold["holdout_hands"], len(
                {record["hand_id"] for record in self.cv_run["records"] if record["fold"] == fold["fold"]}
            ))

    def test_every_hand_is_assigned_to_exactly_one_fold(self) -> None:
        seen: dict[str, set[int]] = {}
        for record in self.cv_run["records"]:
            seen.setdefault(record["hand_id"], set()).add(record["fold"])
        for hand, folds in seen.items():
            self.assertEqual(len(folds), 1, f"hand {hand} appeared in two holdout folds")
        self.assertEqual(len(seen), self.cv_run["protocol"]["no_leak"]["hands"])
        self.assertEqual(
            sum(fold["holdout_rows"] for fold in self.cv_run["folds"]), len(self.cv_run["records"])
        )

    def test_the_folds_are_the_harness_folds(self) -> None:
        rows = synthetic_rows()
        split = cv.grouped_folds(rows, folds=3, seed=cv.CV_SEED)
        self.assertEqual(
            [fold.summary()["holdout_hands"] for fold in split],
            [fold["holdout_hands"] for fold in self.cv_run["folds"]],
        )

    def test_rows_without_hand_id_are_refused(self) -> None:
        rows = synthetic_rows(120, 20)
        rows[0].pop("hand_id")
        with self.assertRaises(cv.TrainCrossValidationError):
            harness.run_cross_validation(rows, folds=3, config=model.make_config(tuning_max_rows=200))

    def test_at_least_two_folds_are_required(self) -> None:
        with self.assertRaises(cv.TrainCrossValidationError):
            harness.run_cross_validation(
                synthetic_rows(), folds=1, config=model.make_config(tuning_max_rows=200)
            )


# ---------------------------------------------------------------------------
# channels, strata and metrics
# ---------------------------------------------------------------------------


class MetricSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = fast_artifact()

    def test_the_three_channels_are_compared(self) -> None:
        self.assertEqual(
            sorted(self.artifact["models"]),
            ["active_model_a", "generalized_calibrated", "hybrid_router"],
        )

    def test_every_required_metric_is_present_per_stratum(self) -> None:
        required = (
            "log_loss_bits_per_decision",
            "brier_score",
            "expected_calibration_error",
            "accuracy",
        )
        for stratum in (
            model.OOD_STRATUM_FREQUENT_EXACT,
            model.OOD_STRATUM_RARE_EXACT,
            model.OOD_STRATUM_EXACT_ABSENT_IN_DOMAIN,
            model.OOD_STRATUM_EXACT_ABSENT_OUT_OF_DOMAIN,
        ):
            block = self.artifact["per_stratum"][stratum]
            for channel in harness.CHANNELS:
                coverage = block["models"][channel]["coverage"]
                for key in ("n", "answered", "coverage", "abstain_rate"):
                    self.assertIn(key, coverage)
                if coverage["n"]:
                    self.assertAlmostEqual(
                        coverage["coverage"] + coverage["abstain_rate"], 1.0, places=9
                    )
                metrics = block["models"][channel]["metrics"]
                for key in required:
                    self.assertIn(key, metrics)

    def test_the_strata_partition_the_held_out_decisions(self) -> None:
        counts = self.artifact["strata"]["counts"]
        self.assertEqual(
            sorted(counts), sorted([*harness.ADMISSION_STRATA, harness.OOD_STRATUM])
        )
        self.assertEqual(sum(counts.values()), self.artifact["scope"]["cross_validated_rows"])
        self.assertEqual(self.artifact["strata"]["rows"], self.artifact["scope"]["cross_validated_rows"])

    def test_limper_vs_iso_has_its_own_metric_surface(self) -> None:
        for channel in harness.CHANNELS:
            block = self.artifact["models"][channel]["limper_vs_iso"]
            self.assertEqual(block["family"], harness.LIMPER_VS_ISO_FAMILY)
            self.assertIn("coverage", block["scope"])
            self.assertIn("log_loss_bits_per_decision", block["metrics"])
        counts = self.artifact["strata"]["counts"]
        limper = self.artifact["models"][harness.CHANNEL_HYBRID]["limper_vs_iso"]["scope"]["n"]
        self.assertLessEqual(limper, sum(counts.values()))

    def test_the_hybrid_answers_through_the_routed_channel(self) -> None:
        rows = synthetic_rows()
        run = fast_run(rows)
        for record in run["records"]:
            hybrid = record["channels"][harness.CHANNEL_HYBRID]
            if record["route_source"] == harness.router.ROUTE_SOURCE_ACTIVE:
                self.assertEqual(
                    hybrid["probabilities"], record["channels"][harness.CHANNEL_ACTIVE]["probabilities"]
                )
            elif record["route_source"] == harness.router.ROUTE_SOURCE_SPARSE:
                self.assertEqual(
                    hybrid["probabilities"],
                    record["channels"][harness.CHANNEL_GENERALIZED]["probabilities"],
                )
            else:
                self.assertFalse(hybrid["answered"])
                self.assertIsNone(hybrid["probabilities"])

    def test_the_router_abstains_on_every_ood_probe(self) -> None:
        probes = self.artifact["ood_synthetic_probes"]
        self.assertTrue(probes["assertions"]["router_abstains_on_every_probe"])
        self.assertTrue(probes["assertions"]["every_probe_carries_its_hard_reason"])
        self.assertTrue(probes["assertions"]["unseen_category_probes_are_the_ood_stratum"])
        self.assertEqual(probes["abstain_rate"], 1.0)
        self.assertEqual(probes["coverage"], 0.0)
        for kind in harness.PROBE_KINDS:
            self.assertEqual(probes["by_kind"][kind]["abstain_rate"], 1.0)
            self.assertTrue(probes["by_kind"][kind]["expected_reason_present"])

    def test_the_ood_stratum_is_measured_with_the_synthetic_probes(self) -> None:
        block = self.artifact["per_stratum"][harness.OOD_STRATUM]
        self.assertEqual(block["source"], "synthetic_probes:unseen_category")
        self.assertGreater(block["n"], 0)
        self.assertEqual(
            block["models"][harness.CHANNEL_HYBRID]["coverage"]["coverage"], 0.0
        )
        self.assertEqual(
            block["models"][harness.CHANNEL_HYBRID]["coverage"]["abstain_rate"], 1.0
        )
        self.assertIn("real_holdout_decisions", block)

    def test_every_channel_distribution_is_legal(self) -> None:
        for channel in harness.CHANNELS:
            metrics = self.artifact["models"][channel]["metrics"]
            if metrics["n"]:
                self.assertEqual(metrics["illegal_mass_max"], 0.0)
                self.assertLessEqual(metrics["probability_sum_max_abs_error"], 1e-9)


# ---------------------------------------------------------------------------
# paired bootstrap
# ---------------------------------------------------------------------------


class PairedBootstrapTests(unittest.TestCase):
    def test_the_resample_unit_is_the_hand(self) -> None:
        pairs = [
            {"hand_id": "h1", "delta_nll": 1.0},
            {"hand_id": "h1", "delta_nll": 3.0},
            {"hand_id": "h2", "delta_nll": -1.0},
            {"hand_id": "h2", "delta_nll": -1.0},
        ]
        block = harness.paired_bootstrap(pairs, samples=200, seed=7)
        self.assertEqual(block["hands"], 2)
        self.assertEqual(block["rows"], 4)
        self.assertAlmostEqual(block["point_estimate_bits_per_decision"], 0.5)
        # Every draw is the mean of two drawn hand means: {-1, 0.5, 2}.
        for level in ("0.025", "0.5", "0.975"):
            self.assertIn(round(block["quantiles"][level], 9), (-1.0, 0.5, 2.0))

    def test_the_dispersion_and_the_intervals_are_published(self) -> None:
        rng = __import__("random").Random(11)
        pairs = []
        for hand in range(60):
            for _ in range(3):
                pairs.append({"hand_id": f"h{hand:03d}", "delta_nll": rng.gauss(0.05, 0.4)})
        block = harness.paired_bootstrap(pairs, samples=400, seed=harness.BOOTSTRAP_SEED)
        self.assertIsNotNone(block["bootstrap_stddev_bits_per_decision"])
        self.assertGreater(block["bootstrap_stddev_bits_per_decision"], 0.0)
        self.assertEqual(len(block["ci95"]), 2)
        self.assertEqual(len(block["ci90"]), 2)
        self.assertLess(block["ci95"][0], block["ci95"][1])
        self.assertEqual(
            block["upper_quantile_bits_per_decision"], block["quantiles"]["0.95"]
        )
        self.assertIsNotNone(block["analytic"]["standard_error_bits_per_decision"])
        self.assertIsNotNone(block["analytic"]["margin_analytic_bits_per_decision"])

    def test_the_bootstrap_is_deterministic_and_seed_sensitive(self) -> None:
        pairs = [
            {"hand_id": f"h{index % 20:03d}", "delta_nll": ((index * 37) % 11) / 25.0}
            for index in range(120)
        ]
        first = harness.paired_bootstrap(pairs, samples=200, seed=3)
        second = harness.paired_bootstrap(pairs, samples=200, seed=3)
        third = harness.paired_bootstrap(pairs, samples=200, seed=4)
        self.assertEqual(first, second)
        self.assertNotEqual(first["quantiles"]["0.5"], third["quantiles"]["0.5"])

    def test_the_analytic_cross_check_matches_the_clustered_bootstrap(self) -> None:
        rng = __import__("random").Random(5)
        pairs = []
        for hand in range(400):
            size = rng.choice([1, 1, 2, 3, 8, 15])
            effect = rng.gauss(0.02, 0.3)
            for _ in range(size):
                pairs.append({"hand_id": f"h{hand:04d}", "delta_nll": rng.gauss(effect, 0.5)})
        block = harness.paired_bootstrap(pairs, samples=3000, seed=harness.BOOTSTRAP_SEED)
        analytic = block["analytic"]
        self.assertAlmostEqual(
            analytic["standard_error_bits_per_decision"],
            block["bootstrap_stddev_bits_per_decision"],
            delta=0.1 * block["bootstrap_stddev_bits_per_decision"],
        )
        self.assertAlmostEqual(
            analytic["margin_analytic_bits_per_decision"],
            block["quantiles"]["0.95"],
            delta=0.02 * abs(block["quantiles"]["0.95"]),
        )

    def test_the_paired_comparison_is_per_hand_and_excludes_abstentions(self) -> None:
        records = [
            {
                "hand_id": "h1",
                "observed": "CALL",
                "stratum": model.OOD_STRATUM_FREQUENT_EXACT,
                "family": "UNOPENED",
                "channels": {
                    "left": {"answered": True, "probabilities": {"FOLD": 0.1, "CALL": 0.6, "RAISE": 0.2, "JAM": 0.1}},
                    "right": {"answered": True, "probabilities": {"FOLD": 0.2, "CALL": 0.5, "RAISE": 0.2, "JAM": 0.1}},
                },
            },
            {
                "hand_id": "h2",
                "observed": "FOLD",
                "stratum": model.OOD_STRATUM_FREQUENT_EXACT,
                "family": "UNOPENED",
                "channels": {
                    "left": {"answered": False, "probabilities": None},
                    "right": {"answered": True, "probabilities": {"FOLD": 0.4, "CALL": 0.3, "RAISE": 0.2, "JAM": 0.1}},
                },
            },
        ]
        block = harness.paired_comparison(records, "left", "right", samples=50, seed=1)
        self.assertEqual(block["rows"], 1)
        self.assertEqual(block["hands"], 1)
        self.assertEqual(block["excluded_decisions"], 1)
        self.assertLess(block["point_estimate_bits_per_decision"], 0.0)


# ---------------------------------------------------------------------------
# the frozen active reference
# ---------------------------------------------------------------------------


class ActiveReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reference = harness.load_active_reference()
        cls.rows = harness.read_train_rows(DATASET, stride=311)

    def test_the_reference_is_pinned_by_its_digest(self) -> None:
        self.assertEqual(self.reference["sha256"], harness.ACTIVE_MODEL_SHA256)
        self.assertEqual(
            harness.sha256_file(harness.ACTIVE_MODEL_PATH), harness.ACTIVE_MODEL_SHA256
        )

    def test_the_replication_reproduces_the_frozen_comparator(self) -> None:
        from tools.training import validate_generalized_response as frozen

        comparators = frozen.build_comparators()
        seen_non_empty = False
        for row in self.rows:
            mine = harness.active_public_distribution(self.reference, row)
            theirs = frozen.active_public_distribution(comparators, row)
            self.assertEqual(mine["available"], theirs["available"])
            if mine["available"]:
                self.assertEqual(mine["probabilities"], theirs["probabilities"])
                seen_non_empty = True
            else:
                self.assertEqual(mine["reason"], theirs["reason"])
        self.assertTrue(seen_non_empty)

    def test_the_memo_reproduces_the_uncached_search(self) -> None:
        cached_reference = dict(self.reference, match_cache={})
        rows = [row for row in self.rows[:20] for _ in range(5)]
        calls: list[tuple] = []
        original = harness.find_closest

        def counting(index, decision):  # type: ignore[no-untyped-def]
            calls.append((index.get("x"), decision.get("hand_id")))
            return original(index, decision)

        with mock.patch.object(harness, "find_closest", side_effect=counting):
            first = [dict(harness.active_public_distribution(cached_reference, row)) for row in rows]
            second = [dict(harness.active_public_distribution(cached_reference, row)) for row in rows]
        self.assertEqual(first, second)
        self.assertLessEqual(len(calls), 20, "the memo did not reuse the repeated keys")
        self.assertEqual(len(cached_reference["match_cache"]), len(calls))


# ---------------------------------------------------------------------------
# the persisted derivation
# ---------------------------------------------------------------------------


class PersistedDerivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fast = fast_artifact()

    def test_the_derivation_is_present_and_self_consistent(self) -> None:
        self.assertTrue(DERIVATION_PATH.exists(), "the derivation run is missing")
        artifact = json.loads(DERIVATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(artifact["schema"], harness.DERIVATION_SCHEMA)
        self.assertEqual(artifact["module_sha256"], harness.sha256_file(MODULE_PATH))
        self.assertEqual(harness.check(DERIVATION_PATH), [])
        self.assertEqual(artifact["scope"]["split"], "TRAIN")
        self.assertEqual(artifact["scope"]["consumed_splits"], ["TRAIN"])
        self.assertFalse(artifact["scope"]["validation_consumed"])
        self.assertFalse(artifact["scope"]["test_consumed"])
        self.assertTrue(artifact["guards"]["no_holdout_loader"])
        self.assertTrue(artifact["guards"]["hands_never_on_both_sides_of_a_fold"])
        self.assertEqual(artifact["protocol"]["no_leak"]["max_hand_overlap_between_fit_and_holdout"], 0)
        for fold in artifact["folds"]:
            self.assertEqual(fold["hand_overlap_with_fit"], 0)
        self.assertEqual(
            sum(artifact["strata"]["counts"].values()), artifact["scope"]["cross_validated_rows"]
        )
        self.assertEqual(artifact["protocol"]["no_leak"]["hands"], artifact["scope"]["hands"])
        self.assertTrue(artifact["assertions"]["router_abstains_on_every_ood_probe"])
        for channel in harness.CHANNELS:
            self.assertIn(channel, artifact["models"])
        for stratum in (*harness.ADMISSION_STRATA, harness.OOD_STRATUM):
            self.assertIn(stratum, artifact["strata"]["counts"])

    def test_the_margin_inputs_are_derived_from_train_only(self) -> None:
        artifact = json.loads(DERIVATION_PATH.read_text(encoding="utf-8"))
        margin = artifact["margin_derivation"]
        self.assertIs(margin["terminal_evaluation_derived"], False)
        self.assertEqual(margin["admission_strata"], list(harness.ADMISSION_STRATA))
        self.assertIsNotNone(margin["bootstrap_stddev_bits_per_decision"])
        self.assertIsNotNone(margin["margin_global_bootstrap_bits_per_decision"])
        self.assertIsNotNone(margin["margin_global_analytic_bits_per_decision"])
        self.assertIn("0.95", margin["quantiles"])
        self.assertGreaterEqual(margin["hands"], 1)
        self.assertGreaterEqual(margin["rows"], margin["hands"])
        self.assertGreater(margin["rows"], 0)
        for name, block in artifact["paired"].items():
            self.assertEqual(block["paired_unit"], "hand_id")
            self.assertIsNotNone(block["global"]["bootstrap_stddev_bits_per_decision"])
            for stratum in (*harness.ADMISSION_STRATA, harness.OOD_STRATUM):
                self.assertIn(stratum, block["by_stratum"])
                self.assertIn("rows", block["by_stratum"][stratum])
                self.assertIn("hands", block["by_stratum"][stratum])
            self.assertIn("limper_vs_iso", block)

    def test_the_derivation_sidecar_pins_the_bytes(self) -> None:
        sidecar = DERIVATION_PATH.with_suffix(".sha256").read_text(encoding="utf-8").splitlines()
        self.assertTrue(sidecar)
        self.assertEqual(sidecar[0].split()[0], harness.sha256_bytes(DERIVATION_PATH.read_bytes()))
        self.assertIn("TRAIN_ONLY_NO_VALIDATION_NO_TEST", sidecar[2])

    def test_the_artifact_is_written_byte_reproducibly(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = harness.write_artifact(self.fast, Path(first_dir) / "derivation.json")
            second = harness.write_artifact(self.fast, Path(second_dir) / "derivation.json")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(
                first.with_suffix(".sha256").read_bytes(),
                second.with_suffix(".sha256").read_bytes(),
            )

    def test_two_fresh_runs_agree_byte_for_byte(self) -> None:
        self.assertEqual(
            harness.persisted_artifact_text(self.fast),
            harness.persisted_artifact_text(harness.build_derivation(
                DATASET, folds=3, seed=cv.CV_SEED, stride=400, probe_limit=2, samples=64, fit_max_rows=1500
            )),
        )

    def test_cli_print_only_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "derivation.json"
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                exit_code = harness.main(
                    [
                        "--print",
                        "--stride",
                        "400",
                        "--folds",
                        "3",
                        "--bootstrap-samples",
                        "32",
                        "--probe-limit",
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
            self.assertEqual(printed["schema"], harness.DERIVATION_SCHEMA)
            self.assertEqual(printed["scope"]["row_stride"], 400)

    def test_the_self_check_cli_reports_the_comparison(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exit_code = harness.main(["--self-check", "--seed", "421"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["static_scan"], "PASS")
        self.assertFalse(payload["validation_consumed"])
        self.assertFalse(payload["test_consumed"])
        self.assertEqual(payload["no_leak"]["max_hand_overlap_between_fit_and_holdout"], 0)
        self.assertEqual(sorted(payload["channels"]), sorted(harness.CHANNELS))

    def test_check_reports_a_corrupted_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "derivation.json"
            harness.write_artifact(self.fast, target)
            self.assertEqual(harness.check(target), [])
            target.write_text(target.read_text(encoding="utf-8").replace("TRAIN", "TRAIN "), encoding="utf-8")
            problems = harness.check(target)
            self.assertTrue(problems)

    def test_full_derivation_recomputes_identically(self) -> None:
        if not FULL:
            self.skipTest("set POKER_HYBRID_ROUTER_CV_FULL=1 to refit the full derivation")
        persisted = json.loads(DERIVATION_PATH.read_text(encoding="utf-8"))
        scope = persisted["scope"]
        protocol = persisted["protocol"]
        recomputed = harness.build_derivation(
            scope["dataset"],
            folds=protocol["folds"],
            seed=protocol["seed"],
            rule=protocol["route_rule"]["id"],
            architecture=protocol["architecture"],
            method=protocol["calibration_method"],
            stride=scope["row_stride"],
            probe_limit=protocol["ood_probes"]["limit_per_kind_per_fold"],
        )
        self.assertEqual(
            harness.persisted_artifact_text(recomputed),
            harness.persisted_artifact_text(persisted),
        )


class DependencySurfaceTests(unittest.TestCase):
    def test_module_depends_on_the_standard_library_only(self) -> None:
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
