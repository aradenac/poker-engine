#!/usr/bin/env python3
"""Contract tests for the fail-closed Hero -> Model B robustness consumer (#425)."""
from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.model_b_hero_robustness_consumer import (  # noqa: E402
    BATCH_REPORT_SCHEMA,
    CONSUMER_REPORT_SCHEMA,
    ConsumerError,
    assert_source_artifact_allowed,
    build_consumer_report,
    consume_batch,
    consume_fixture,
    independence_guard,
    load_source_340_docs,
    main,
    scan_forbidden_features,
    validate_fixture,
)
from tools.simulation.model_b_hero_robustness_status import STATUSES  # noqa: E402
from tools.simulation.model_b_preflop_sensitivity_harness import (  # noqa: E402
    canonical_sha256,
    load_json,
    project_robustness_input,
)

FIXTURES = ROOT / "tests/fixtures/model_b_robustness_consumer"
CONTEXT = ROOT / "tests/fixtures/model_b_preflop_sensitivity/synthetic_sb_two_limpers_context.json"
MODULE_PATH = ROOT / "tools/simulation/model_b_hero_robustness_consumer.py"

FIXTURE_STATUSES = {
    "robust_recommendation.json": "CONSISTENT",
    "too_close.json": "TOO_CLOSE",
    "sparse_high_uncertainty.json": "INSUFFICIENT_SUPPORT",
    "ood_unsupported.json": "OOD_UNTESTABLE",
    "multiple_sizings.json": "SENSITIVE",
}


def source_340() -> dict:
    return load_source_340_docs()


class FixtureReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = source_340()

    def report(self, name: str) -> dict:
        return consume_fixture(FIXTURES / name, source_340=self.docs)

    def test_report_schema_and_status_for_every_t2_fixture(self):
        present = {p.name for p in FIXTURES.glob("*.json")}
        self.assertTrue(set(FIXTURE_STATUSES).issubset(present), present)
        for name, expected in FIXTURE_STATUSES.items():
            report = self.report(name)
            self.assertEqual(report["schema"], CONSUMER_REPORT_SCHEMA)
            self.assertEqual(
                sorted(report),
                [
                    "classification_evidence",
                    "decision_id",
                    "independence",
                    "reason_codes",
                    "schema",
                    "sensitivity",
                    "status",
                ],
            )
            self.assertEqual(report["status"], expected)
            self.assertIn(report["status"], STATUSES)
            self.assertTrue(report["reason_codes"])
            self.assertEqual(sorted(report["reason_codes"]), list(report["reason_codes"]))
            self.assertTrue(report["decision_id"].startswith("synthetic-robustness-"))

    def test_independence_guard_flags_are_pinned(self):
        for name in FIXTURE_STATUSES:
            independence = self.report(name)["independence"]
            self.assertIs(independence["request_has_forbidden_features"], False)
            self.assertEqual(independence["forbidden_hits"], [])
            self.assertIs(independence["information_boundary_all_false"], True)

    def test_multiple_sizings_status_is_at_least_sensitive(self):
        report = self.report("multiple_sizings.json")
        self.assertIn(report["status"], {"SENSITIVE", "INSUFFICIENT_SUPPORT", "OOD_UNTESTABLE"})

    def test_sensitivity_block_binds_issue_340_identity_and_hashes(self):
        report = self.report("robust_recommendation.json")
        sensitivity = report["sensitivity"]
        self.assertEqual(
            sensitivity["issue_340_identity"]["candidate_artifact_sha256"],
            "87736a611a0000a8bc30b142a3c1db0ac2086368c6fa18441cdc211bd17f3a06",
        )
        self.assertEqual(sensitivity["issue_340_identity"]["production_effect"], "NONE")
        self.assertIs(sensitivity["issue_340_identity"]["test_consumed_by_this_harness"], False)
        self.assertEqual(len(sensitivity["request_sha256"]), 64)
        self.assertEqual(len(sensitivity["report_sha256"]), 64)

    def test_classification_evidence_is_exposed(self):
        report = self.report("too_close.json")
        evidence = report["classification_evidence"]
        self.assertEqual(evidence["schema"], "model-b-hero-robustness-status/v1")
        self.assertEqual(evidence["input_schema"], "hero-model-b-robustness-input/v1")
        self.assertIs(evidence["provenance_present"], True)
        self.assertIs(evidence["information_boundary_present"], True)
        self.assertEqual(evidence["boundary_violations"], [])

    def test_report_is_deterministic(self):
        first = self.report("sparse_high_uncertainty.json")
        second = self.report("sparse_high_uncertainty.json")
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertEqual(
            canonical_sha256(first["sensitivity"]),
            canonical_sha256(second["sensitivity"]),
        )


class FailClosedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = load_json(FIXTURES / "too_close.json")
        cls.docs = source_340()
        cls.context = load_json(CONTEXT)

    def expect(self, reason_code: str, mutate) -> None:
        bad = copy.deepcopy(self.doc)
        mutate(bad)
        with self.assertRaises(ConsumerError) as caught:
            validate_fixture(bad)
        self.assertEqual(caught.exception.reason_code, reason_code)
        self.assertIn(reason_code, str(caught.exception))
        self.assertEqual(caught.exception.to_dict()["status"], "FAIL_CLOSED")

    def test_schema_mismatch_fails_closed(self):
        self.expect("SCHEMA_MISMATCH", lambda d: d.__setitem__("schema", "hero-model-b/v2"))

    def test_source_kind_mismatch_fails_closed(self):
        self.expect("SOURCE_KIND_MISMATCH", lambda d: d.__setitem__("source_kind", "REAL_ISSUE_314"))

    def test_missing_provenance_fails_closed(self):
        self.expect("PROVENANCE_MISSING", lambda d: d.pop("provenance"))

    def test_incomplete_provenance_fails_closed(self):
        self.expect("PROVENANCE_INCOMPLETE", lambda d: d["provenance"].pop("parent_issue"))

    def test_missing_support_fails_closed(self):
        self.expect("SUPPORT_MISSING", lambda d: d["alternatives"][0].pop("support"))

    def test_missing_decision_fails_closed(self):
        self.expect("DECISION_MISSING", lambda d: d.pop("decision"))

    def test_missing_information_boundary_fails_closed(self):
        self.expect("INFORMATION_BOUNDARY_MISSING", lambda d: d.pop("information_boundary"))

    def test_unknown_field_fails_closed(self):
        self.expect("INPUT_SCHEMA_VIOLATION", lambda d: d.__setitem__("extra", 1))

    def test_string_ev_is_not_accepted_as_a_number(self):
        self.expect("INPUT_SCHEMA_VIOLATION", lambda d: d["alternatives"][0].__setitem__("ev_bb", "1.0"))

    def test_truthy_information_boundary_fails_closed(self):
        bad = copy.deepcopy(self.doc)
        bad["information_boundary"]["hero_ev_consumed"] = True
        with self.assertRaises(ConsumerError) as caught:
            build_consumer_report(bad, context=self.context, **self.docs)
        self.assertEqual(caught.exception.reason_code, "INFORMATION_BOUNDARY_VIOLATION")

    def test_provenance_consuming_real_evidence_fails_closed(self):
        bad = copy.deepcopy(self.doc)
        bad["provenance"]["real_issue_314_consumed"] = True
        with self.assertRaises(ConsumerError) as caught:
            validate_fixture(bad)
        self.assertEqual(caught.exception.reason_code, "INPUT_SCHEMA_VIOLATION")

    def test_fold_with_non_null_sizing_fails_closed_on_projection(self):
        bad = copy.deepcopy(self.doc)
        bad["alternatives"].append(
            {
                "alternative_id": "FOLD",
                "action": "FOLD",
                "sizing": 2.0,
                "route": "synthetic_robustness_route_fold",
                "source": "synthetic_monte_carlo_paired_v1",
                "ev_bb": -0.1,
                "uncertainty": {
                    "ci95": [-0.2, 0.0],
                    "width_bb": 0.2,
                    "source": "synthetic_paired_ci95_v1",
                },
                "paired_delta_vs_best_bb": -1.0,
                "support": {"status": "CONSISTENT", "tier": "HIGH", "ood": False},
                "posterior_refs": None,
            }
        )
        with self.assertRaises(ConsumerError) as caught:
            build_consumer_report(bad, context=self.context, **self.docs)
        self.assertEqual(caught.exception.reason_code, "PROJECTION_REJECTED")

    def test_public_context_mismatch_fails_closed(self):
        bad = copy.deepcopy(self.doc)
        bad["decision"]["hero_position"] = "BTN"
        with self.assertRaises(ConsumerError) as caught:
            build_consumer_report(bad, context=self.context, **self.docs)
        self.assertEqual(caught.exception.reason_code, "PROJECTION_REJECTED")


class IndependenceGuardTests(unittest.TestCase):
    def test_projected_request_has_no_forbidden_hits(self):
        context = load_json(CONTEXT)
        request = project_robustness_input(load_json(FIXTURES / "too_close.json"), context=context)
        self.assertEqual(scan_forbidden_features(request), [])
        self.assertEqual(
            independence_guard(request),
            {
                "request_has_forbidden_features": False,
                "forbidden_hits": [],
                "information_boundary_all_false": True,
            },
        )

    def test_feature_leak_is_refused(self):
        context = load_json(CONTEXT)
        request = project_robustness_input(load_json(FIXTURES / "too_close.json"), context=context)
        leaks = {
            "ev_bb": 1.0,
            "uncertainty": {"ci95": [0.0, 1.0], "width_bb": 1.0, "source": "x"},
            "route": "leaked",
            "source": "leaked",
            "support": {"status": "CONSISTENT", "tier": "HIGH", "ood": False},
            "posterior_refs": ["x"],
            "paired_delta_vs_best_bb": 0.0,
            "recommendation": "ISO@5",
        }
        for key, value in leaks.items():
            bad = copy.deepcopy(request)
            bad["alternatives"][0][key] = value
            hits = scan_forbidden_features(bad)
            self.assertTrue(any(hit.endswith(key) for hit in hits), (key, hits))
            with self.assertRaises(ConsumerError) as caught:
                independence_guard(bad)
            self.assertEqual(caught.exception.reason_code, "INDEPENDENCE_LEAK")

    def test_truthy_boundary_flag_is_refused(self):
        context = load_json(CONTEXT)
        request = project_robustness_input(load_json(FIXTURES / "too_close.json"), context=context)
        bad = copy.deepcopy(request)
        bad["information_boundary"]["future_cards_consumed"] = True
        with self.assertRaises(ConsumerError) as caught:
            independence_guard(bad)
        self.assertEqual(caught.exception.reason_code, "INFORMATION_BOUNDARY_VIOLATION")


class SourceGuardTests(unittest.TestCase):
    def test_module_never_references_real_iso_ev_or_model_features(self):
        text = MODULE_PATH.read_text(encoding="utf-8").lower()
        for token in ("real_iso_ev", "issue367", "model_a", "hero_ev"):
            self.assertNotIn(token, text)

    def test_real_iso_ev_run_artifacts_are_refused_before_being_opened(self):
        runs = [
            path
            for path in (ROOT / "training/runs").iterdir()
            if "real_iso_ev" in path.name
        ]
        self.assertTrue(runs, "expected the real ISO EV run to exist for the guard test")
        for run in runs:
            for artifact in ("RESULT.json", "SUMMARY.json"):
                with self.assertRaises(ConsumerError) as caught:
                    assert_source_artifact_allowed(run / artifact)
                self.assertEqual(caught.exception.reason_code, "FORBIDDEN_UPSTREAM_ARTIFACT")

    def test_issue_340_artifacts_are_allowed(self):
        path = ROOT / "training/runs/20260919_model_b_preflop_response_to_price_2a/RESULT.json"
        self.assertEqual(assert_source_artifact_allowed(path), path)


class BatchModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = source_340()

    def test_batch_covers_every_fixture(self):
        batch = consume_batch(source_340=self.docs)
        self.assertEqual(batch["schema"], BATCH_REPORT_SCHEMA)
        self.assertEqual(batch["fixture_count"], len(batch["fixtures"]))
        by_name = {entry["fixture"]: entry["status"] for entry in batch["fixtures"]}
        for name, expected in FIXTURE_STATUSES.items():
            self.assertEqual(by_name.get(name), expected)
        self.assertEqual(sum(batch["statuses"].values()), len(batch["fixtures"]))
        self.assertEqual(
            [entry["fixture"] for entry in batch["fixtures"]],
            sorted(by_name),
        )

    def test_cli_batch_writes_one_report_per_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                code = main(["--batch", "--out-dir", tmp])
            self.assertEqual(code, 0)
            out = Path(tmp)
            for name in FIXTURE_STATUSES:
                report = json.loads((out / name).read_text(encoding="utf-8"))
                self.assertEqual(report["schema"], CONSUMER_REPORT_SCHEMA)
                self.assertEqual(report["status"], FIXTURE_STATUSES[name])
            summary = json.loads((out / "BATCH_SUMMARY.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["schema"], BATCH_REPORT_SCHEMA)
            self.assertNotIn("reports", summary)

    def test_cli_single_mode_writes_a_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            with redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "--fixture",
                        str(FIXTURES / "robust_recommendation.json"),
                        "--out",
                        str(out),
                    ]
                )
            self.assertEqual(code, 0)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "CONSISTENT")
            self.assertIs(report["independence"]["information_boundary_all_false"], True)

    def test_cli_fails_closed_with_reason_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "bad.json"
            bad = load_json(FIXTURES / "too_close.json")
            bad["provenance"].pop("synthetic_fixture")
            fixture.write_text(json.dumps(bad) + "\n", encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                code = main(["--fixture", str(fixture), "--out", str(Path(tmp) / "out.json")])
            self.assertEqual(code, 2)
            payload = json.loads(stderr.getvalue())
            self.assertEqual(payload["status"], "FAIL_CLOSED")
            self.assertEqual(payload["reason_code"], "PROVENANCE_INCOMPLETE")
            self.assertFalse((Path(tmp) / "out.json").exists())

    def test_cli_accepts_the_fixture_folder_as_fixture_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                code = main(["--fixture", str(FIXTURES), "--out", tmp])
            self.assertEqual(code, 0)
            for name in FIXTURE_STATUSES:
                self.assertTrue((Path(tmp) / name).is_file())

    def test_cli_reports_an_unreadable_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                code = main(
                    [
                        "--fixture",
                        str(Path(tmp) / "nope.json"),
                        "--out",
                        str(Path(tmp) / "out.json"),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(stderr.getvalue())["reason_code"], "FIXTURE_UNREADABLE")


if __name__ == "__main__":
    unittest.main()
