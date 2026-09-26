#!/usr/bin/env python3
"""#423 T6 guard: terminal score judged by the frozen admission criteria.

Covers every acceptance criterion of the task:

* the terminal run refuses to start when the spec is not frozen, when the
  frozen criteria are absent or not the preregistered five, and when the spec
  digest has drifted from its sidecar or from the criteria manifest;
* the persisted report carries the direct per-stratum comparison of the active
  Model A reference, the calibrated generalized channel and the hybrid router,
  the global log-loss delta, the sparse delta, the sparse ECE, the OOD
  abstention rate, a separate ``LIMPER_VS_ISO`` surface and the paired-by-hand
  bootstrap;
* the outcome is derived mechanically from the frozen criteria -- no margin is
  reinvented in the report -- and a single failing criterion flips it;
* the report and its companion are digest-pinned, byte-stable and bound to the
  frozen spec digest.

``pytest`` is not a declared dependency of this repository; the suite is a
plain ``unittest`` module, run with ``python3 -m unittest`` like its siblings.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_model as model  # noqa: E402
from tools.training import evaluate_generalized_response_cv as cv  # noqa: E402
from tools.training import evaluate_hybrid_router_cv as harness  # noqa: E402
from tools.training import freeze_hybrid_router_criteria as freeze  # noqa: E402

HERE = ROOT / "analysis/issue423_hybrid_router"
REPORT_PATH = HERE / "TRAIN_CV_ROUTER_REPORT.json"
SPARSE_PATH = HERE / "SPARSE_STRATA_COMPARISON.json"
SPEC_PATH = HERE / "HYBRID_ROUTER_SPEC.json"
SPEC_DIGEST_PATH = HERE / "HYBRID_ROUTER_SPEC.sha256"
MANIFEST_PATH = HERE / "ROUTER_MANIFEST.json"
MODULE_PATH = ROOT / "tools/training/evaluate_hybrid_router_cv.py"

#: ``POKER_HYBRID_ROUTER_CV_FULL=1`` re-runs the full terminal score (~minutes).
FULL = os.environ.get("POKER_HYBRID_ROUTER_CV_FULL", "") == "1"


def persisted_report() -> dict:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def persisted_sparse() -> dict:
    return json.loads(SPARSE_PATH.read_text(encoding="utf-8"))


def synthetic_dataset(path: Path, *, rows: int = 900, hands: int = 90) -> Path:
    payload = "".join(
        json.dumps(dict(row, hand_id=f"hyb-hand-{index % hands:04d}"), sort_keys=True) + "\n"
        for index, row in enumerate(model.synthetic_rows(rows, cv.CV_SEED))
    )
    path.write_text(payload, encoding="utf-8")
    return path


def fast_core() -> tuple[dict, list[dict]]:
    rows = [
        dict(row, hand_id=f"hyb-hand-{index % 90:04d}")
        for index, row in enumerate(model.synthetic_rows(900, cv.CV_SEED))
    ]
    core = harness.run_cross_validation(
        rows,
        folds=3,
        seed=cv.CV_SEED,
        config=model.make_config(tuning_max_rows=300),
        fit_max_rows=1500,
        probe_limit=3,
        samples=120,
    )
    return core, rows


def force_all_criteria_to_pass(report: dict) -> dict:
    """Rewrite only the measured statistics so every frozen criterion passes."""
    for stratum in harness.SPARSE_STRATA:
        for channel in harness.CHANNELS:
            metrics = report["models"][channel]["by_stratum"][stratum]["metrics"]
            metrics["n"] = max(1, int(metrics.get("n") or 0))
            metrics["gain_bits_per_decision"] = 1.0
            metrics["expected_calibration_error"] = 0.0
    margin = report["paired"][harness.PAIRED_HYBRID_MINUS_ACTIVE]["admission_support"]
    margin["upper_quantile_bits_per_decision"] = 0.0
    frequent = report["per_stratum"][harness.FREQUENT_EXACT_STRATUM]["paired"][
        harness.PAIRED_HYBRID_MINUS_ACTIVE
    ]
    frequent["point_estimate_bits_per_decision"] = 0.0
    frequent["ci95"] = [0.0, 0.0]
    report["ood_synthetic_probes"]["abstain_rate"] = 1.0
    report["ood_synthetic_probes"]["coverage"] = 0.0
    return report


@contextlib.contextmanager
def frozen_layout(tmp: Path):
    """A writable copy of the persisted freeze the tests may tamper with."""
    spec_path = tmp / "HYBRID_ROUTER_SPEC.json"
    digest_path = tmp / "HYBRID_ROUTER_SPEC.sha256"
    manifest_path = tmp / "ROUTER_MANIFEST.json"
    shutil.copyfile(SPEC_PATH, spec_path)
    shutil.copyfile(SPEC_DIGEST_PATH, digest_path)
    shutil.copyfile(MANIFEST_PATH, manifest_path)
    yield {
        "spec": spec_path,
        "digest": digest_path,
        "manifest": manifest_path,
    }


def repin(entry: dict) -> None:
    """Re-pin the sidecar to the bytes currently on disk."""
    digest = harness.sha256_file(entry["spec"])
    entry["digest"].write_text(f"{digest}  {entry['spec'].name}\n", encoding="utf-8")


def load(entry: dict) -> dict:
    return harness.load_frozen_criteria(
        entry["spec"], digest_path=entry["digest"], manifest_path=entry["manifest"]
    )


# ---------------------------------------------------------------------------
# the frozen-first gate
# ---------------------------------------------------------------------------


class FrozenSpecGateTests(unittest.TestCase):
    def test_the_persisted_report_binds_the_frozen_spec(self) -> None:
        report = persisted_report()
        frozen = harness.load_frozen_criteria()
        self.assertEqual(report["frozen_spec"]["sha256"], frozen["sha256"])
        self.assertEqual(report["frozen_spec"]["criteria_sha256"], frozen["criteria_sha256"])
        self.assertEqual(report["frozen_criteria"], frozen["criteria"])

    def test_a_missing_spec_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(harness.HybridRouterTerminalError) as caught:
                harness.load_frozen_criteria(Path(directory) / "absent.json")
            self.assertIn("missing", str(caught.exception))

    def test_an_unfrozen_spec_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with frozen_layout(Path(directory)) as entry:
                spec = json.loads(entry["spec"].read_text(encoding="utf-8"))
                spec["frozen"] = False
                entry["spec"].write_text(json.dumps(spec, sort_keys=True), encoding="utf-8")
                repin(entry)
                with self.assertRaises(harness.HybridRouterTerminalError) as caught:
                    load(entry)
                self.assertIn("not frozen", str(caught.exception))

    def test_a_spec_without_numeric_criteria_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with frozen_layout(Path(directory)) as entry:
                spec = json.loads(entry["spec"].read_text(encoding="utf-8"))
                spec.pop("frozen_criteria")
                entry["spec"].write_text(json.dumps(spec, sort_keys=True), encoding="utf-8")
                repin(entry)
                with self.assertRaises(harness.HybridRouterTerminalError) as caught:
                    load(entry)
                self.assertIn("no frozen numeric criteria", str(caught.exception))

    def test_a_missing_sidecar_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with frozen_layout(Path(directory)) as entry:
                entry["digest"].unlink()
                with self.assertRaises(harness.HybridRouterTerminalError) as caught:
                    load(entry)
                self.assertIn("digest-pinned", str(caught.exception))

    def test_a_drifted_spec_digest_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with frozen_layout(Path(directory)) as entry:
                entry["spec"].write_text(
                    entry["spec"].read_text(encoding="utf-8") + " ", encoding="utf-8"
                )
                with self.assertRaises(harness.HybridRouterTerminalError) as caught:
                    load(entry)
                self.assertIn("diverged", str(caught.exception))

    def test_a_drifted_criteria_digest_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with frozen_layout(Path(directory)) as entry:
                spec = json.loads(entry["spec"].read_text(encoding="utf-8"))
                spec["frozen_criteria"]["criteria"][0]["value"] = 0.5
                entry["spec"].write_text(json.dumps(spec, sort_keys=True), encoding="utf-8")
                repin(entry)
                with self.assertRaises(harness.HybridRouterTerminalError) as caught:
                    load(entry)
                self.assertIn("criteria digest", str(caught.exception))

    def test_a_freeze_that_is_not_the_preregistered_five_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with frozen_layout(Path(directory)) as entry:
                spec = json.loads(entry["spec"].read_text(encoding="utf-8"))
                dropped = spec["frozen_criteria"]["criteria"].pop()
                spec["frozen_criteria"]["criteria_sha256"] = model.stable_hash(
                    harness._finalize(harness._criteria_payload(spec["frozen_criteria"]))
                )
                entry["spec"].write_text(json.dumps(spec, sort_keys=True), encoding="utf-8")
                repin(entry)
                with self.assertRaises(harness.HybridRouterTerminalError) as caught:
                    load(entry)
                self.assertIn("preregistered five", str(caught.exception))
                self.assertEqual(dropped["id"], harness.CRITERION_OOD)

    def test_a_missing_criteria_manifest_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with frozen_layout(Path(directory)) as entry:
                entry["manifest"].unlink()
                with self.assertRaises(harness.HybridRouterTerminalError) as caught:
                    load(entry)
                self.assertIn("manifest", str(caught.exception))

    def test_a_manifest_that_disagrees_with_the_spec_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with frozen_layout(Path(directory)) as entry:
                manifest = json.loads(entry["manifest"].read_text(encoding="utf-8"))
                manifest["frozen_criteria"]["criteria"][0]["value"] = 0.5
                entry["manifest"].write_text(
                    json.dumps(manifest, sort_keys=True), encoding="utf-8"
                )
                with self.assertRaises(harness.HybridRouterTerminalError) as caught:
                    load(entry)
                self.assertIn("criteria manifest", str(caught.exception))

    def test_a_manifest_pinning_a_different_spec_digest_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with frozen_layout(Path(directory)) as entry:
                manifest = json.loads(entry["manifest"].read_text(encoding="utf-8"))
                manifest["frozen_spec"]["sha256"] = "0" * 64
                entry["manifest"].write_text(
                    json.dumps(manifest, sort_keys=True), encoding="utf-8"
                )
                with self.assertRaises(harness.HybridRouterTerminalError) as caught:
                    load(entry)
                self.assertIn("diverged from the criteria manifest", str(caught.exception))


# ---------------------------------------------------------------------------
# mechanical application of the frozen criteria
# ---------------------------------------------------------------------------


class CriteriaApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.core, cls.rows = fast_core()
        cls.frozen = harness.load_frozen_criteria()
        cls.report = harness._assemble_terminal_report(
            cls.core,
            frozen=cls.frozen,
            scope={"split": "TRAIN", "rows": len(cls.rows), "row_stride": 1},
            samples=120,
            bootstrap_seed=harness.BOOTSTRAP_SEED,
        )

    def evaluate(self, report: dict) -> dict:
        return harness.evaluate_frozen_criteria(report, self.frozen["criteria"])

    def test_every_frozen_criterion_is_applied_in_order(self) -> None:
        evaluation = self.evaluate(force_all_criteria_to_pass(json.loads(json.dumps(self.report))))
        self.assertEqual(evaluation["criteria_order"], list(harness.TERMINAL_CRITERIA_ORDER))
        self.assertEqual(
            [record["id"] for record in evaluation["criteria"]],
            list(harness.TERMINAL_CRITERIA_ORDER),
        )
        frozen_values = {
            entry["id"]: entry["value"] for entry in self.frozen["criteria"]["criteria"]
        }
        frozen_text = {
            entry["id"]: entry["criterion"] for entry in self.frozen["criteria"]["criteria"]
        }
        for record in evaluation["criteria"]:
            self.assertEqual(record["threshold"], frozen_values[record["id"]])
            self.assertEqual(record["frozen_criterion"], frozen_text[record["id"]])

    def test_the_outcome_is_derived_from_the_criteria_and_nothing_else(self) -> None:
        passing = self.evaluate(force_all_criteria_to_pass(json.loads(json.dumps(self.report))))
        self.assertTrue(passing["all_passed"])
        self.assertEqual(passing["outcome"], harness.OUTCOME_ADMIT)
        self.assertEqual(passing["failed"], [])

        failing = json.loads(json.dumps(self.report))
        force_all_criteria_to_pass(failing)
        failing["models"][harness.CHANNEL_HYBRID]["by_stratum"][
            harness.SPARSE_STRATA[0]
        ]["metrics"]["expected_calibration_error"] = 1.0
        evaluation = self.evaluate(failing)
        self.assertFalse(evaluation["all_passed"])
        self.assertEqual(evaluation["outcome"], harness.OUTCOME_RETAIN)
        self.assertEqual(evaluation["failed"], [harness.CRITERION_SPARSE_ECE])

    def test_the_frozen_margin_is_not_reinvented_here(self) -> None:
        evaluation = self.evaluate(force_all_criteria_to_pass(json.loads(json.dumps(self.report))))
        margin = evaluation["criteria"][0]
        frozen_value = self.frozen["criteria"]["criteria"][0]["value"]
        self.assertEqual(margin["id"], harness.CRITERION_MARGIN)
        self.assertEqual(margin["threshold"], frozen_value)
        self.assertEqual(margin["observed"], 0.0)
        self.assertEqual(evaluation["thresholds_source"], "frozen_hybrid_router_criteria")
        self.assertIs(evaluation["margins_reinvented_here"], False)

    def test_a_missing_statistic_fails_closed(self) -> None:
        report = json.loads(json.dumps(self.report))
        for stratum in harness.SPARSE_STRATA:
            for channel in harness.CHANNELS:
                metrics = report["models"][channel]["by_stratum"][stratum]["metrics"]
                metrics["n"] = 0
                metrics["gain_bits_per_decision"] = None
                metrics["expected_calibration_error"] = None
        evaluation = self.evaluate(report)
        failed = set(evaluation["failed"])
        self.assertIn(harness.CRITERION_SPARSE_GAIN, failed)
        self.assertIn(harness.CRITERION_SPARSE_ECE, failed)
        self.assertEqual(evaluation["outcome"], harness.OUTCOME_RETAIN)

    def test_the_minimum_sparse_support_is_enforced(self) -> None:
        report = force_all_criteria_to_pass(json.loads(json.dumps(self.report)))
        for stratum in harness.SPARSE_STRATA:
            report["models"][harness.CHANNEL_HYBRID]["by_stratum"][stratum]["metrics"]["n"] = 5
        evaluation = self.evaluate(report)
        gain = evaluation["criteria"][1]
        self.assertEqual(gain["id"], harness.CRITERION_SPARSE_GAIN)
        self.assertFalse(gain["inputs"]["minimum_sparse_support_satisfied"])
        self.assertFalse(gain["passed"])

    def test_a_partial_freeze_is_refused(self) -> None:
        criteria = json.loads(json.dumps(self.frozen["criteria"]))
        criteria["criteria"] = criteria["criteria"][:-1]
        with self.assertRaises(harness.HybridRouterTerminalError) as caught:
            harness.evaluate_frozen_criteria(self.report, criteria)
        self.assertIn("omit", str(caught.exception))

    def test_an_unknown_criterion_is_refused(self) -> None:
        criteria = json.loads(json.dumps(self.frozen["criteria"]))
        extra = dict(criteria["criteria"][0])
        extra["id"] = "INVENTED_MARGIN"
        criteria["criteria"].append(extra)
        with self.assertRaises(harness.HybridRouterTerminalError) as caught:
            harness.evaluate_frozen_criteria(self.report, criteria)
        self.assertIn("outside the preregistered procedure", str(caught.exception))


# ---------------------------------------------------------------------------
# the persisted terminal report
# ---------------------------------------------------------------------------


class TerminalReportContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = persisted_report()
        cls.sparse = persisted_sparse()

    def test_the_three_channels_are_compared_per_stratum(self) -> None:
        for stratum in (*harness.ADMISSION_STRATA, harness.OOD_STRATUM):
            for channel in harness.CHANNELS:
                block = self.report["models"][channel]["by_stratum"][stratum]
                self.assertIn("metrics", block)
                self.assertIn("scope", block)
            surface = self.report["per_stratum"][stratum]
            for channel in harness.CHANNELS:
                self.assertIn(channel, surface["models"])

    def test_every_required_metric_is_present_per_stratum(self) -> None:
        for channel in harness.CHANNELS:
            block = self.report["models"][channel]["by_stratum"]
            for stratum in (*harness.ADMISSION_STRATA, harness.OOD_STRATUM):
                metrics = block[stratum]["metrics"]
                for key in (
                    "log_loss_bits_per_decision",
                    "brier_score",
                    "expected_calibration_error",
                    "accuracy",
                ):
                    self.assertIn(key, metrics)
                self.assertIn("coverage", block[stratum]["scope"])
                self.assertIn("abstain_rate", block[stratum]["scope"])

    def test_the_global_log_loss_delta_is_present(self) -> None:
        delta = self.report["deltas"]["global_log_loss_bits_per_decision"]
        self.assertIn(harness.PAIRED_HYBRID_MINUS_ACTIVE, delta)
        self.assertIsNotNone(delta[harness.PAIRED_HYBRID_MINUS_ACTIVE])
        self.assertEqual(self.report["deltas"]["paired_unit"], "hand_id")

    def test_the_sparse_delta_and_ece_are_present(self) -> None:
        sparse = self.report["deltas"]["sparse_log_loss_bits_per_decision"]
        self.assertEqual(sparse["strata"], list(harness.SPARSE_STRATA))
        self.assertIsNotNone(sparse["paired_hybrid_minus_active"])
        self.assertIsNotNone(sparse["hybrid_ece"])
        self.assertIsNotNone(sparse["hybrid_gain_bits_per_decision"])
        self.assertEqual(self.report["sparse"]["strata"], list(harness.SPARSE_STRATA))
        for stratum in harness.SPARSE_STRATA:
            self.assertIn(stratum, self.sparse["by_stratum"])

    def test_the_ood_abstention_rate_is_present(self) -> None:
        self.assertEqual(self.report["ood"]["abstain_rate"], 1.0)
        self.assertEqual(self.report["ood"]["coverage"], 0.0)
        self.assertEqual(self.report["ood"]["stratum"], harness.OOD_STRATUM)
        self.assertGreater(self.report["ood"]["n"], 0)
        self.assertTrue(self.report["assertions"]["router_abstains_on_every_ood_probe"])

    def test_limper_vs_iso_is_reported_separately(self) -> None:
        limper = self.report["limper_vs_iso"]
        self.assertEqual(limper["family"], harness.LIMPER_VS_ISO_FAMILY)
        for channel in harness.CHANNELS:
            self.assertIn(channel, limper["models"])
            self.assertIn("log_loss_bits_per_decision", limper["models"][channel]["metrics"])
        self.assertIn(harness.PAIRED_HYBRID_MINUS_ACTIVE, limper["paired"])

    def test_the_paired_bootstrap_is_by_hand_id(self) -> None:
        for comparison in (harness.PAIRED_HYBRID_MINUS_ACTIVE, harness.PAIRED_HYBRID_MINUS_GENERALIZED):
            block = self.report["paired"][comparison]
            self.assertEqual(block["paired_unit"], "hand_id")
            for label in ("global", "admission_support", "limper_vs_iso"):
                sub = block[label]
                self.assertGreaterEqual(sub["hands"], 1)
                self.assertGreaterEqual(sub["rows"], sub["hands"])
                self.assertIn("ci95", sub)
                self.assertIn("quantiles", sub)
        self.assertGreater(self.report["paired"][harness.PAIRED_HYBRID_MINUS_ACTIVE]["global"]["rows"], 0)

    def test_the_report_embeds_the_frozen_spec_digest_and_criteria(self) -> None:
        frozen = harness.load_frozen_criteria()
        self.assertEqual(self.report["frozen_spec"]["sha256"], frozen["sha256"])
        self.assertEqual(self.report["frozen_spec"]["criteria_sha256"], frozen["criteria_sha256"])
        self.assertEqual(self.report["frozen_spec"]["criteria_order"], list(harness.TERMINAL_CRITERIA_ORDER))
        self.assertEqual(self.sparse["frozen_spec"]["sha256"], frozen["sha256"])

    def test_the_outcome_is_one_of_the_two_terminal_verdicts(self) -> None:
        self.assertIn(self.report["outcome"], harness.TERMINAL_OUTCOMES)
        evaluation = self.report["criteria_evaluation"]
        self.assertEqual(evaluation["all_passed"], report_all_passed(self.report))
        self.assertEqual(
            self.report["outcome"],
            harness.OUTCOME_ADMIT if evaluation["all_passed"] else harness.OUTCOME_RETAIN,
        )


def report_all_passed(report: dict) -> bool:
    return all(record["passed"] for record in report["criteria_evaluation"]["criteria"])


class PersistedTerminalArtifactTests(unittest.TestCase):
    def test_the_terminal_artifacts_verify(self) -> None:
        self.assertTrue(REPORT_PATH.is_file(), "the terminal report is missing")
        self.assertTrue(SPARSE_PATH.is_file(), "the sparse strata comparison is missing")
        self.assertEqual(harness.verify_terminal_artifacts(), [])

    def test_full_terminal_score_recomputes_identically(self) -> None:
        if not FULL:
            self.skipTest("set POKER_HYBRID_ROUTER_CV_FULL=1 to re-score the full terminal run")
        report = persisted_report()
        scope = report["scope"]
        protocol = report["protocol"]
        recomputed = harness.build_terminal_report(
            scope["dataset"],
            folds=protocol["folds"],
            seed=protocol["seed"],
            rule=protocol["route_rule"]["id"],
            architecture=protocol["architecture"],
            method=protocol["calibration_method"],
            stride=scope["row_stride"],
            fit_max_rows=protocol["calibration_fit_max_rows"],
            probe_limit=protocol["ood_probes"]["limit_per_kind_per_fold"],
            samples=protocol["paired_bootstrap"]["samples"],
            bootstrap_seed=protocol["paired_bootstrap"]["seed"],
        )
        self.assertEqual(
            harness.persisted_artifact_text(recomputed),
            REPORT_PATH.read_bytes().decode("utf-8"),
        )
        self.assertEqual(
            harness.persisted_artifact_text(recomputed["sparse_strata_comparison"]),
            SPARSE_PATH.read_bytes().decode("utf-8"),
        )
        self.assertEqual(recomputed["outcome"], report["outcome"])
        self.assertEqual(
            recomputed["criteria_evaluation"]["failed"],
            report["criteria_evaluation"]["failed"],
        )

    def test_the_report_sidecar_pins_the_bytes(self) -> None:
        sidecar = REPORT_PATH.with_suffix(".sha256").read_text(encoding="utf-8").splitlines()
        self.assertTrue(sidecar)
        self.assertEqual(sidecar[0].split()[0], harness.sha256_bytes(REPORT_PATH.read_bytes()))
        self.assertIn("TRAIN_ONLY_NO_VALIDATION_NO_TEST", sidecar[2])
        self.assertIn("outcome", sidecar[3])

    def test_the_sparse_comparison_is_bound_and_pinned(self) -> None:
        binding = persisted_report()["sparse_strata_comparison_binding"]
        self.assertEqual(binding["name"], SPARSE_PATH.name)
        self.assertEqual(
            binding["sha256"], harness.sha256_bytes(SPARSE_PATH.read_bytes())
        )
        sidecar = SPARSE_PATH.with_suffix(".sha256").read_text(encoding="utf-8").splitlines()
        self.assertEqual(sidecar[0].split()[0], harness.sha256_bytes(SPARSE_PATH.read_bytes()))

    def test_the_report_declares_a_train_only_scope(self) -> None:
        scope = persisted_report()["scope"]
        self.assertEqual(scope["split"], "TRAIN")
        self.assertEqual(scope["consumed_splits"], ["TRAIN"])
        self.assertFalse(scope["validation_consumed"])
        self.assertFalse(scope["test_consumed"])
        guards = persisted_report()["guards"]
        self.assertTrue(guards["frozen_spec_verified_before_scoring"])
        self.assertTrue(guards["hands_never_on_both_sides_of_a_fold"])
        self.assertTrue(guards["no_holdout_loader"])

    def test_a_corrupted_report_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / REPORT_PATH.name
            shutil.copyfile(REPORT_PATH, target)
            shutil.copyfile(REPORT_PATH.with_suffix(".sha256"), target.with_suffix(".sha256"))
            companion = Path(directory) / SPARSE_PATH.name
            shutil.copyfile(SPARSE_PATH, companion)
            shutil.copyfile(SPARSE_PATH.with_suffix(".sha256"), companion.with_suffix(".sha256"))
            self.assertEqual(harness.verify_terminal_artifacts(target), [])
            target.write_text(
                target.read_text(encoding="utf-8").replace(
                    harness.OUTCOME_ADMIT, harness.OUTCOME_RETAIN
                ),
                encoding="utf-8",
            )
            problems = harness.verify_terminal_artifacts(target)
            self.assertTrue(problems)

    def test_an_outcome_that_does_not_follow_the_criteria_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / REPORT_PATH.name
            report = persisted_report()
            report["outcome"] = (
                harness.OUTCOME_RETAIN
                if report["outcome"] == harness.OUTCOME_ADMIT
                else harness.OUTCOME_ADMIT
            )
            report["canonical_payload_sha256"] = model.stable_hash(
                harness._canonical_payload(harness._finalize(report))
            )
            target.write_text(harness.persisted_artifact_text(report), encoding="utf-8")
            target.with_suffix(".sha256").write_text(
                harness.terminal_sidecar_text(report, name=target.name), encoding="utf-8"
            )
            companion = Path(directory) / SPARSE_PATH.name
            shutil.copyfile(SPARSE_PATH, companion)
            shutil.copyfile(SPARSE_PATH.with_suffix(".sha256"), companion.with_suffix(".sha256"))
            problems = harness.verify_terminal_artifacts(target)
            self.assertTrue(
                any("outcome is not the one the frozen criteria derive" in item for item in problems),
                problems,
            )


# ---------------------------------------------------------------------------
# the T5 ordering guard, seen from the terminal side
# ---------------------------------------------------------------------------


class OrderingGuardTests(unittest.TestCase):
    def test_the_frozen_criteria_still_verify_with_the_report_present(self) -> None:
        self.assertTrue(REPORT_PATH.is_file())
        self.assertEqual(freeze.check(), [])
        self.assertEqual(freeze.check_spec_reproducible(), [])

    def test_the_ordering_guard_resolves_to_bound(self) -> None:
        state = freeze.terminal_order_state()
        self.assertEqual(state["state"], "BOUND")
        self.assertEqual(freeze.terminal_absence_problems(), [])
        self.assertTrue(state["bound"])
        self.assertEqual(state["unbound"], [])

    def test_a_report_that_binds_nothing_leaves_the_ordering_unprovable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "TRAIN_CV_ROUTER_REPORT.json"
            target.write_text("{}", encoding="utf-8")
            problems = freeze.terminal_absence_problems((target,))
            self.assertTrue(problems)
            self.assertIn("without binding the frozen spec digest", problems[0])

    def test_a_report_binding_a_stale_digest_leaves_the_ordering_unprovable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "TRAIN_CV_ROUTER_REPORT.json"
            target.write_text(
                json.dumps({"frozen_spec": {"sha256": "0" * 64}}), encoding="utf-8"
            )
            problems = freeze.terminal_absence_problems((target,))
            self.assertTrue(problems)


# ---------------------------------------------------------------------------
# the command line and byte stability
# ---------------------------------------------------------------------------


class TerminalCliTests(unittest.TestCase):
    def test_check_terminal_cli_passes(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            exit_code = harness.main(["--check-terminal"])
        self.assertEqual(exit_code, 0, buffer.getvalue())

    def test_terminal_self_check_reports_the_outcome(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exit_code = harness.main(["--terminal-self-check", "--seed", "423"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["schema"], harness.TERMINAL_SELF_CHECK_SCHEMA)
        self.assertEqual(payload["criteria_order"], list(harness.TERMINAL_CRITERIA_ORDER))
        self.assertIn(payload["outcome"], harness.TERMINAL_OUTCOMES)
        self.assertEqual(payload["required_surface_problems"], [])
        self.assertEqual(payload["frozen_spec_sha256"], harness.load_frozen_criteria()["sha256"])

    def test_terminal_print_does_not_write_and_is_byte_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dataset = synthetic_dataset(Path(directory) / "synthetic.jsonl")
            target = Path(directory) / "report.json"
            arguments = [
                "--terminal",
                "--print",
                "--dataset",
                str(dataset),
                "--folds",
                "3",
                "--probe-limit",
                "2",
                "--bootstrap-samples",
                "32",
                "--tuning-max-rows",
                "200",
                "--seed",
                str(cv.CV_SEED),
                "--terminal-out",
                str(target),
            ]
            first = io.StringIO()
            with contextlib.redirect_stdout(first):
                self.assertEqual(harness.main(arguments), 0)
            second = io.StringIO()
            with contextlib.redirect_stdout(second):
                self.assertEqual(harness.main(arguments), 0)
            self.assertFalse(target.exists(), "the CLI wrote despite --print")
            self.assertEqual(first.getvalue(), second.getvalue())
            payload = json.loads(first.getvalue())
            self.assertEqual(payload["schema"], harness.TERMINAL_SCHEMA)
            self.assertIn(payload["outcome"], harness.TERMINAL_OUTCOMES)

    def test_the_terminal_run_refuses_a_drifted_spec(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dataset = synthetic_dataset(Path(directory) / "synthetic.jsonl", rows=300, hands=30)
            with frozen_layout(Path(directory)) as entry:
                entry["spec"].write_text(
                    entry["spec"].read_text(encoding="utf-8") + "\n", encoding="utf-8"
                )
                with self.assertRaises(harness.HybridRouterTerminalError):
                    harness.build_terminal_report(
                        dataset,
                        folds=3,
                        probe_limit=1,
                        samples=16,
                        fit_max_rows=500,
                        config=model.make_config(tuning_max_rows=200),
                        spec_path=entry["spec"],
                        spec_digest_path=entry["digest"],
                        manifest_path=entry["manifest"],
                    )

    def test_two_terminal_runs_agree_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dataset = synthetic_dataset(Path(directory) / "synthetic.jsonl")
            kwargs = {
                "folds": 3,
                "probe_limit": 2,
                "samples": 32,
                "fit_max_rows": 800,
                "config": model.make_config(tuning_max_rows=200),
            }
            first = harness.build_terminal_report(dataset, **kwargs)
            second = harness.build_terminal_report(dataset, **kwargs)
            self.assertEqual(
                harness.persisted_artifact_text(first),
                harness.persisted_artifact_text(second),
            )
            self.assertEqual(first["outcome"], second["outcome"])

    def test_the_module_is_stdlib_only_and_names_no_holdout_loader(self) -> None:
        self.assertEqual(harness.verify_no_holdout_access()["result"], "PASS")
        self.assertIn("evaluate_hybrid_router_cv.py", str(MODULE_PATH))


if __name__ == "__main__":
    unittest.main(verbosity=2)
