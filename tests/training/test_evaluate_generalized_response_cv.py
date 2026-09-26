#!/usr/bin/env python3
"""#421 T4 guard: TRAIN-only hand-grouped cross-validation of the T3 architectures.

Covers every acceptance criterion of the task:

* the internal CV split is grouped by ``hand_id`` and the no-leak property is
  *proved by assertion* (no hand ever lands on both sides of a split);
* every requested metric is present: multiclass log loss, Brier, ECE,
  coverage after the provisional OOD gate, and per position / family /
  sizing-bucket breakdowns;
* the three decision strata -- frequent exacts, rare exacts, and exact
  combination absent although every feature value is in-domain -- are explicit
  and partition the held-out rows;
* the architecture is selected on out-of-fold evidence by the preregistered
  criteria and the report declares ``validation_consumed=false`` and
  ``test_consumed=false``;
* the tool fails closed on TEST and its persisted report is byte-reproducible.

The fast path cross-validates a deterministic stride sample of the real TRAIN
rows; the full 5-fold recomputation of the persisted report is opt-in via
``POKER_GENERALIZED_RESPONSE_CV_FULL=1`` (it refits both architectures ten
times, ~3 minutes).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_model as model  # noqa: E402
from tools.training import evaluate_generalized_response_cv as cv  # noqa: E402

DATASET = ROOT / "analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.jsonl"
REPORT_PATH = ROOT / "analysis/issue421_generalized_response/TRAIN_CV_REPORT.json"
MODULE_PATH = ROOT / "tools/training/evaluate_generalized_response_cv.py"
MODEL_MODULE_PATH = ROOT / "tools/preflop/generalized_response_model.py"

FULL = os.environ.get("POKER_GENERALIZED_RESPONSE_CV_FULL") == "1"

#: Deterministic stride + fold count that keep the real-data tests fast while
#: still exercising the persisted TRAIN rows end to end.
STRIDE = 12
FAST_FOLDS = 3
FAST_CONFIG = model.make_config(tuning_max_rows=1000)


_CACHE: dict[str, object] = {}


def fast_report() -> dict:
    """Cross-validated report over a stride sample of the real TRAIN rows."""
    if "report" not in _CACHE:
        rows = cv.read_train_rows(DATASET, stride=STRIDE)
        _CACHE["report"] = cv.run_cross_validation(
            rows, folds=FAST_FOLDS, seed=cv.CV_SEED, config=FAST_CONFIG
        )
        _CACHE["rows"] = rows
    return _CACHE["report"]  # type: ignore[return-value]


def fast_rows() -> list[dict]:
    fast_report()
    return _CACHE["rows"]  # type: ignore[return-value]


def grouped_rows(count: int = 60, hands: int = 12, actions_per_hand: int = 5) -> list[dict]:
    """Deterministic synthetic TRAIN rows with several decisions per hand."""
    base = model.synthetic_rows(count, cv.CV_SEED)
    rows = []
    for index, row in enumerate(base):
        rows.append(dict(row, hand_id=f"g{index % hands:03d}"))
    return rows[: hands * actions_per_hand]


def controlled_absent_row() -> tuple[list[dict], dict]:
    """(fit rows, held-out row) where every feature value is seen but not the mix."""
    def row(position: str, stack: float, action: str = "FOLD") -> dict:
        return {
            "hand_id": "unused",
            "split": "TRAIN",
            "table_size": 6,
            "family": "UNOPENED",
            "actor_position": position,
            "aggressor_position": None,
            "limper_count": 0,
            "caller_count": 0,
            "live_positions": ["LJ", "HJ", "CO", "BTN", "SB", "BB"],
            "raise_level": 0,
            "to_call_bb": 1.0,
            "pot_before_bb": 1.5,
            "pot_odds": 0.4,
            "price_to_pot": 0.666667,
            "effective_stack_bb": stack,
            "target_total_bb": None,
            "observed_sizing_bb": None,
            "action": action,
        }

    # Each actor position and each stack bucket is seen; the (CO, 100bb) mix is not.
    # SB@100bb is seen 20 times (frequent), HJ@100bb once (rare), BTN@100bb 30 times.
    fit_rows = [dict(row("CO", 10.0), hand_id=f"f-co-{index}") for index in range(30)]
    fit_rows += [dict(row("BTN", 100.0), hand_id=f"f-btn-{index}") for index in range(30)]
    fit_rows += [dict(row("SB", 100.0), hand_id=f"f-sb-{index}") for index in range(20)]
    fit_rows += [dict(row("HJ", 100.0), hand_id="f-hj-0")]
    holdout = dict(row("CO", 100.0), hand_id="holdout-hand")
    return fit_rows, holdout


# ---------------------------------------------------------------------------
# split: hand grouping and the no-leak assertion
# ---------------------------------------------------------------------------


class SplitTests(unittest.TestCase):
    def test_folds_are_grouped_by_hand_and_leak_free(self) -> None:
        rows = grouped_rows()
        folds = cv.grouped_folds(rows, folds=3, seed=cv.CV_SEED)
        hand_fold: dict[str, set[int]] = {}
        for fold in folds:
            for row in fold.holdout_rows:
                hand_fold.setdefault(str(row["hand_id"]), set()).add(fold.index)
        self.assertTrue(hand_fold, "the split produced no held-out hand")
        for hand_id, assigned in hand_fold.items():
            self.assertEqual(len(assigned), 1, f"hand {hand_id} spans several folds: {assigned}")
        for fold in folds:
            self.assertEqual(fold.train_hands & fold.holdout_hands, set())
            self.assertEqual(fold.summary()["hand_overlap_with_fit"], 0)
        union = set().union(*(fold.holdout_hands for fold in folds))
        self.assertEqual(union, {str(row["hand_id"]) for row in rows})
        self.assertEqual(sum(len(fold.holdout_hands) for fold in folds), len(union))

    def test_no_leak_proof_is_consistent_with_the_split(self) -> None:
        folds = cv.grouped_folds(grouped_rows(), folds=4, seed=cv.CV_SEED)
        proof = cv.no_leak_proof(folds)
        self.assertEqual(proof["group_key"], "hand_id")
        self.assertEqual(proof["folds"], 4)
        self.assertTrue(proof["hands_assigned_to_exactly_one_fold"])
        self.assertTrue(proof["holdout_hands_pairwise_disjoint"])
        self.assertEqual(proof["max_hand_overlap_between_fit_and_holdout"], 0)
        self.assertTrue(proof["checked_at_runtime"])
        self.assertEqual(proof["holdout_hands_per_fold"], [len(fold.holdout_hands) for fold in folds])

    def test_fold_assignment_is_deterministic(self) -> None:
        for hand_id in ("261672888042", "hand-0007", "g003"):
            self.assertEqual(
                cv.fold_of(hand_id, cv.CV_SEED, 5), cv.fold_of(hand_id, cv.CV_SEED, 5)
            )
        self.assertEqual(
            cv.grouped_folds(grouped_rows(), folds=3, seed=cv.CV_SEED)[0].holdout_hands,
            cv.grouped_folds(grouped_rows(), folds=3, seed=cv.CV_SEED)[0].holdout_hands,
        )

    def test_rows_without_hand_id_are_refused(self) -> None:
        rows = grouped_rows(count=20, hands=4, actions_per_hand=5)
        rows[0] = dict(rows[0], hand_id="")
        with self.assertRaises(cv.TrainCrossValidationError):
            cv.grouped_folds(rows, folds=2, seed=cv.CV_SEED)

    def test_at_least_two_folds_are_required(self) -> None:
        with self.assertRaises(cv.TrainCrossValidationError):
            cv.grouped_folds(grouped_rows(), folds=1, seed=cv.CV_SEED)
        with self.assertRaises(cv.TrainCrossValidationError):
            cv.fold_of("hand", cv.CV_SEED, 1)

    def test_test_split_is_refused_everywhere(self) -> None:
        self.assertEqual(cv.CONSUMED_SPLITS, ("TRAIN",))
        with self.assertRaises(model.GeneralizedResponseModelError):
            model.read_dataset_rows(DATASET, splits=("TEST",))
        self.assertTrue(all(row["split"] == "TRAIN" for row in fast_rows()))
        row = dict(grouped_rows(count=10, hands=2, actions_per_hand=5)[0], split="TEST")
        with self.assertRaises(model.GeneralizedResponseModelError):
            cv.run_cross_validation([row] * 4, folds=2, seed=cv.CV_SEED)

    def test_empty_architecture_list_is_refused(self) -> None:
        with self.assertRaises(cv.TrainCrossValidationError):
            cv.run_cross_validation(grouped_rows(), folds=2, seed=cv.CV_SEED, architectures=[])


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


class MetricsTests(unittest.TestCase):
    def test_all_requested_metrics_are_present(self) -> None:
        report = fast_report()
        self.assertEqual(report["protocol"]["kind"], "hand_grouped_k_fold_cross_validation")
        self.assertEqual(report["protocol"]["group_key"], "hand_id")
        self.assertEqual(
            sorted(report["protocol"]["model_config"]), sorted(model.make_config())
        )
        self.assertEqual(report["protocol"]["model_config_source"], "explicit")
        for architecture in model.ARCHITECTURES:
            block = report["architectures"][architecture]
            out_of_fold = block["out_of_fold"]
            self.assertGreater(out_of_fold["n"], 0)
            for key in (
                "log_loss_bits_per_decision",
                "baseline_log_loss_bits_per_decision",
                "gain_bits_per_decision",
                "brier_score",
                "accuracy",
            ):
                self.assertIsInstance(out_of_fold[key], float, f"{architecture}.{key}")
            self.assertIsInstance(out_of_fold["expected_calibration_error"]["ece"], float)
            calibration = out_of_fold["expected_calibration_error"]
            self.assertEqual(calibration["bins_per_action_class"], cv.CALIBRATION_BINS)
            self.assertEqual(sorted(calibration["per_action_class"]), sorted(model.ACTIONS))
            for breakdown in ("by_actor_position", "by_aggressor_position", "by_family", "by_sizing_bucket"):
                groups = block[breakdown]
                self.assertTrue(groups, breakdown)
                for label, metrics in groups.items():
                    self.assertGreater(metrics["n"], 0, f"{architecture}.{breakdown}.{label}")
                    self.assertIn("log_loss_bits_per_decision", metrics)
                    self.assertIn("brier_score", metrics)
                    self.assertIn("share", metrics)
            gate = block["coverage_after_provisional_ood_gate"]
            self.assertIsInstance(gate["coverage"], float)
            self.assertEqual(gate["accepted"] + gate["rejected"], gate["n"])
            self.assertEqual(gate["n"], out_of_fold["n"])
            self.assertTrue(gate["threshold_sensitivity"])
            self.assertEqual(block["runtime"]["complexity_rank"], cv.RUNTIME_COMPLEXITY_RANK[architecture])
            self.assertEqual(len(block["by_fold"]), report["protocol"]["folds"])
            self.assertIn("fold_log_loss_stddev", block["stability"])

    def test_breakdown_groups_cover_every_held_out_row(self) -> None:
        report = fast_report()
        for architecture in model.ARCHITECTURES:
            block = report["architectures"][architecture]
            total = block["out_of_fold"]["n"]
            for breakdown in ("by_actor_position", "by_family", "by_sizing_bucket"):
                self.assertEqual(
                    sum(metrics["n"] for metrics in block[breakdown].values()),
                    total,
                    f"{architecture}.{breakdown} does not cover every row",
                )

    def test_by_position_and_sizing_buckets_are_labelled(self) -> None:
        block = fast_report()["architectures"][model.ARCH_REGULARIZED]
        self.assertTrue(set(block["by_actor_position"]) <= {"LJ", "HJ", "CO", "BTN", "SB", "BB"})
        self.assertIn(cv.NO_OBSERVED_SIZING, block["by_sizing_bucket"])
        self.assertTrue(
            set(block["by_sizing_bucket"]) <= set(cv.SIZING_BUCKET_LABELS) | {cv.NO_OBSERVED_SIZING}
        )

    def test_expected_calibration_error_matches_the_frozen_definition(self) -> None:
        records = [
            {"observed": "FOLD", "probabilities": {"FOLD": 0.9, "CALL": 0.05, "RAISE": 0.03, "JAM": 0.02}},
            {"observed": "CALL", "probabilities": {"FOLD": 0.2, "CALL": 0.6, "RAISE": 0.1, "JAM": 0.1}},
            {"observed": "FOLD", "probabilities": {"FOLD": 0.4, "CALL": 0.4, "RAISE": 0.1, "JAM": 0.1}},
            {"observed": "RAISE", "probabilities": {"FOLD": 0.1, "CALL": 0.2, "RAISE": 0.6, "JAM": 0.1}},
        ]
        result = cv.expected_calibration_error(records, bins=2, minimum_bin_support=1)
        # Hand-derived FOLD class: order by P(FOLD) -> rows (0.1, RAISE), (0.2, CALL),
        # (0.4, FOLD), (0.9, FOLD); two equal-count bins of two rows each:
        #   bin 1: |(0.1+0.2)/2 - (0+0)/2| = 0.15   -> weight 0.5 -> 0.075
        #   bin 2: |(0.4+0.9)/2 - (1+1)/2| = 0.35   -> weight 0.5 -> 0.175
        self.assertAlmostEqual(result["per_action_class"]["FOLD"], 0.25, places=9)
        self.assertAlmostEqual(
            result["ece"],
            sum(result["per_action_class"].values()) / len(model.ACTIONS),
            places=9,
        )
        self.assertEqual(result["bins_meeting_minimum_support"], 8)
        self.assertTrue(result["claim_supportable"])
        # An all-correct, perfectly confident record set is perfectly calibrated.
        confident = [
            {"observed": action, "probabilities": {a: (1.0 if a == action else 0.0) for a in model.ACTIONS}}
            for action in model.ACTIONS
        ]
        self.assertAlmostEqual(
            cv.expected_calibration_error(confident, bins=2, minimum_bin_support=1)["ece"], 0.0, places=9
        )
        self.assertIsNone(cv.expected_calibration_error([])["ece"])

    def test_strata_partition_the_holdout_and_are_explicit(self) -> None:
        report = fast_report()
        for architecture in model.ARCHITECTURES:
            block = report["architectures"][architecture]
            counts = block["strata"]["counts"]
            self.assertEqual(sorted(counts), sorted(cv.STRATA))
            for name in (
                cv.STRATUM_FREQUENT_EXACT,
                cv.STRATUM_RARE_EXACT,
                cv.STRATUM_EXACT_ABSENT_IN_DOMAIN,
            ):
                self.assertIn(name, counts, f"{architecture} is missing stratum {name}")
            self.assertEqual(sum(counts.values()), block["out_of_fold"]["n"])
            self.assertAlmostEqual(sum(block["strata"]["share"].values()), 1.0, places=6)
            self.assertEqual(block["strata"]["minimum_support_frequent"], cv.FREQUENT_EXACT_MIN_SUPPORT)
            for name in counts:
                metrics = block["strata"]["metrics"][name]
                if counts[name]:
                    self.assertEqual(metrics["n"], counts[name])
                    self.assertIn("log_loss_bits_per_decision", metrics)
                    self.assertIn("brier_score", metrics)

    def test_exact_absent_in_domain_stratum_is_detected(self) -> None:
        fit_rows, holdout = controlled_absent_row()
        index = cv.FoldIndex()
        for row in fit_rows:
            index.add(row)
        classification = cv.classify_row(holdout, index)
        self.assertEqual(classification["exact_support_in_fit_fold"], 0)
        self.assertTrue(classification["feature_in_domain"])
        self.assertEqual(classification["unseen_features"], [])
        self.assertEqual(classification["stratum"], cv.STRATUM_EXACT_ABSENT_IN_DOMAIN)
        self.assertFalse(classification["gate_accepted"])

        def variant(**overrides: object) -> dict:
            return dict(holdout, **overrides)

        rare = cv.classify_row(variant(actor_position="HJ"), index)
        self.assertEqual(rare["exact_support_in_fit_fold"], 1)
        self.assertEqual(rare["stratum"], cv.STRATUM_RARE_EXACT)
        frequent = cv.classify_row(variant(actor_position="SB"), index)
        self.assertEqual(frequent["exact_support_in_fit_fold"], cv.FREQUENT_EXACT_MIN_SUPPORT)
        self.assertEqual(frequent["stratum"], cv.STRATUM_FREQUENT_EXACT)
        outside = variant(actor_position="UTG")
        self.assertEqual(
            cv.classify_row(outside, index)["stratum"], cv.STRATUM_EXACT_ABSENT_OUT_OF_DOMAIN
        )
        self.assertEqual(cv.classify_row(outside, index)["unseen_features"], ["actor_position"])

    def test_provisional_gate_accepts_supported_exact_contexts(self) -> None:
        fit_rows, holdout = controlled_absent_row()
        index = cv.FoldIndex()
        for row in fit_rows:
            index.add(row)
        supported = dict(holdout, actor_position="BTN")
        accepted = cv.classify_row(supported, index)
        self.assertEqual(accepted["exact_support_in_fit_fold"], 30)
        self.assertTrue(accepted["gate_accepted"])

    def test_sizing_bucket_reads_the_observed_raise_target(self) -> None:
        passive = {"target_total_bb": None, "pot_before_bb": 1.5, "to_call_bb": 1.0}
        self.assertEqual(cv.sizing_bucket(passive), cv.NO_OBSERVED_SIZING)
        base = {"pot_before_bb": 1.5, "to_call_bb": 1.0}
        self.assertEqual(cv.sizing_bucket(dict(base, target_total_bb=1.0)), "R<=0.5")
        self.assertEqual(cv.sizing_bucket(dict(base, target_total_bb=2.0)), "R0.5-1")
        self.assertEqual(cv.sizing_bucket(dict(base, target_total_bb=3.0)), "R1-2")
        self.assertEqual(cv.sizing_bucket(dict(base, target_total_bb=7.0)), "R2-4")
        self.assertEqual(cv.sizing_bucket(dict(base, target_total_bb=30.0)), "R>4")


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------


class SelectionTests(unittest.TestCase):
    def test_selection_is_out_of_fold_and_leaves_validation_and_test_unconsumed(self) -> None:
        report = fast_report()
        selection = report["selection"]
        self.assertIn(selection["selected"], model.ARCHITECTURES)
        self.assertEqual(selection["evidence_basis"], "out_of_fold_holdout_only")
        self.assertEqual(selection["consumed_splits"], ["TRAIN"])
        self.assertFalse(selection["validation_consumed"])
        self.assertFalse(selection["test_consumed"])
        self.assertTrue(selection["criteria"]["preregistered"])
        self.assertTrue(selection["criteria"]["registered_before_evaluation"])
        self.assertEqual(selection["ranking"][0], selection["selected"])
        for architecture in model.ARCHITECTURES:
            evidence = selection["evidence"][architecture]
            self.assertEqual(
                evidence["out_of_fold_log_loss_bits_per_decision"],
                report["architectures"][architecture]["out_of_fold"]["log_loss_bits_per_decision"],
            )
            self.assertIn("runtime_complexity_rank", evidence)
        self.assertTrue(selection["trace"])
        self.assertIn("validation_consumed=false", selection["justification"])

    def test_lower_calibration_wins_inside_the_log_loss_tolerance(self) -> None:
        criteria = cv.PREREGISTERED_SELECTION_CRITERIA
        tolerance = criteria["steps"][0]["tolerance"]
        blocks = {
            "a": _fake_block(log_loss=1.20, ece=0.08, brier=0.50, stddev=0.01, rank=1),
            "b": _fake_block(log_loss=1.20 + tolerance / 2, ece=0.02, brier=0.50, stddev=0.01, rank=2),
        }
        selection = cv.select_architecture(blocks)
        self.assertEqual(selection["selected"], "b")
        self.assertEqual(selection["trace"][0]["kept"], ["a", "b"])
        self.assertEqual(selection["trace"][1]["criterion"], "calibration")

    def test_log_loss_outside_the_tolerance_dominates_calibration(self) -> None:
        tolerance = cv.PREREGISTERED_SELECTION_CRITERIA["steps"][0]["tolerance"]
        blocks = {
            "a": _fake_block(log_loss=1.20, ece=0.30, brier=0.90, stddev=0.09, rank=2),
            "b": _fake_block(log_loss=1.20 + tolerance * 3, ece=0.01, brier=0.10, stddev=0.01, rank=1),
        }
        selection = cv.select_architecture(blocks)
        self.assertEqual(selection["selected"], "a")
        self.assertEqual(selection["trace"][0]["eliminated"], ["b"])

    def test_runtime_simplicity_breaks_a_full_tie(self) -> None:
        blocks = {
            "a": _fake_block(log_loss=1.2, ece=0.02, brier=0.5, stddev=0.01, rank=2),
            "b": _fake_block(log_loss=1.2, ece=0.02, brier=0.5, stddev=0.01, rank=1),
        }
        selection = cv.select_architecture(blocks)
        self.assertEqual(selection["selected"], "b")
        self.assertEqual(selection["trace"][-1]["criterion"], "runtime_simplicity")

    def test_preregistered_criteria_are_pinned_in_the_module(self) -> None:
        criteria = cv.PREREGISTERED_SELECTION_CRITERIA
        self.assertEqual(criteria["evidence_basis"], "out_of_fold_holdout_only")
        self.assertFalse(criteria["validation_consumed"])
        self.assertFalse(criteria["test_consumed"])
        metrics = [step["metric"] for step in criteria["steps"]]
        self.assertEqual(metrics[0], "out_of_fold.log_loss_bits_per_decision")
        self.assertTrue(any(item.startswith("out_of_fold.expected_calibration_error") for item in metrics))
        self.assertIn("stability.fold_log_loss_stddev", metrics)
        self.assertIn("runtime.complexity_rank", metrics)
        self.assertEqual(criteria["runtime_complexity_rank"], cv.RUNTIME_COMPLEXITY_RANK)


def _fake_block(*, log_loss: float, ece: float, brier: float, stddev: float, rank: int) -> dict:
    return {
        "out_of_fold": {"log_loss_bits_per_decision": log_loss, "expected_calibration_error": {"ece": ece},
                        "brier_score": brier, "baseline_log_loss_bits_per_decision": 1.33,
                        "gain_bits_per_decision": 1.33 - log_loss},
        "stability": {"fold_log_loss_stddev": stddev},
        "runtime": {"complexity_rank": rank, "node_cells": 100},
        "coverage_after_provisional_ood_gate": {"coverage": 0.9},
    }


# ---------------------------------------------------------------------------
# persistence and the persisted TRAIN report
# ---------------------------------------------------------------------------


class PersistenceTests(unittest.TestCase):
    def test_report_is_written_byte_reproducibly(self) -> None:
        report = fast_report()
        with tempfile.TemporaryDirectory() as directory:
            first = cv.write_report(report, Path(directory) / "a.json")
            second = cv.write_report(report, Path(directory) / "b.json")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(json.loads(first.read_text(encoding="utf-8")), json.loads(
                cv.persisted_report_text(report)
            ))

    def test_persisted_report_is_present_and_self_consistent(self) -> None:
        self.assertTrue(REPORT_PATH.exists(), "the TRAIN CV report is missing")
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(report["schema"], cv.SCHEMA)
        self.assertEqual(report["module_sha256"], cv.sha256_file(MODULE_PATH))
        self.assertEqual(report["model_module"]["sha256"], cv.sha256_file(MODEL_MODULE_PATH))
        self.assertEqual(report["model_module"]["architectures"], list(model.ARCHITECTURES))
        self.assertEqual(report["scope"]["split"], "TRAIN")
        self.assertEqual(report["scope"]["dataset_sha256"], cv.sha256_file(DATASET))
        self.assertFalse(report["scope"]["validation_consumed"])
        self.assertFalse(report["scope"]["test_consumed"])
        self.assertEqual(report["protocol"]["consumed_splits"], ["TRAIN"])
        self.assertEqual(report["protocol"]["forbidden_splits"], ["TEST"])
        proof = report["protocol"]["no_leak"]
        self.assertEqual(proof["group_key"], "hand_id")
        self.assertEqual(proof["max_hand_overlap_between_fit_and_holdout"], 0)
        self.assertTrue(proof["hands_assigned_to_exactly_one_fold"])
        for fold in report["folds"]:
            self.assertEqual(fold["hand_overlap_with_fit"], 0)
        self.assertEqual(
            sum(fold["holdout_rows"] for fold in report["folds"]), report["scope"]["rows"]
        )
        self.assertIn(report["selection"]["selected"], model.ARCHITECTURES)
        for architecture in model.ARCHITECTURES:
            block = report["architectures"][architecture]
            self.assertIsInstance(block["out_of_fold"]["expected_calibration_error"]["ece"], float)
            self.assertIn("coverage", block["coverage_after_provisional_ood_gate"])
            self.assertEqual(
                sum(block["strata"]["counts"].values()), block["out_of_fold"]["n"]
            )
            for name in (
                cv.STRATUM_FREQUENT_EXACT,
                cv.STRATUM_RARE_EXACT,
                cv.STRATUM_EXACT_ABSENT_IN_DOMAIN,
            ):
                self.assertIn(name, block["strata"]["counts"])
            self.assertIn(cv.NO_OBSERVED_SIZING, block["by_sizing_bucket"])

    def test_full_report_recomputes_identically(self) -> None:
        if not FULL:
            self.skipTest("set POKER_GENERALIZED_RESPONSE_CV_FULL=1 to refit the full report")
        recomputed = cv.build_report(DATASET)
        persisted = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(cv.persisted_report_text(recomputed), cv.persisted_report_text(persisted))

    def test_self_check_cli_reports_both_architectures(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exit_code = cv.main(["--self-check", "--seed", "5"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(sorted(payload["ranking"]), sorted(model.ARCHITECTURES))
        self.assertEqual(payload["no_leak"]["max_hand_overlap_between_fit_and_holdout"], 0)
        self.assertFalse(payload["validation_consumed"])
        self.assertFalse(payload["test_consumed"])

    def test_cli_print_only_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.json"
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                exit_code = cv.main(
                    [
                        "--print",
                        "--stride",
                        "40",
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
            self.assertEqual(printed["schema"], cv.SCHEMA)
            self.assertEqual(printed["scope"]["row_stride"], 40)


class DependencySurfaceTests(unittest.TestCase):
    def test_module_depends_on_the_standard_library_only(self) -> None:
        import ast

        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
        allowed_third_party = {"tools"}
        import sys as _sys

        stdlib = set(_sys.stdlib_module_names)
        for module in modules:
            if module in allowed_third_party:
                continue
            self.assertIn(module, stdlib, f"{module} is not in the standard library")


if __name__ == "__main__":
    unittest.main(verbosity=2)
