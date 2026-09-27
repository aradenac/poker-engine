#!/usr/bin/env python3
"""Acceptance tests for the #425 adapter/runner (task ``backlog-m59``).

The suite covers the ticket acceptance points end to end, on synthetic
fixtures only:

* the runner emits a report conforming to
  ``contracts/training/hero-model-b-robustness-consumer-report.schema.json``
  (``hero-model-b-hero-robustness-consumer-report/v1``), and it runs on
  synthetic fixtures only;
* the report carries ``input_schema_ref``, a ``status`` drawn from the closed
  five-value vocabulary, its ``reason_codes``, an all-false
  ``information_boundary``, synthetic ``provenance`` references and the two
  content hashes ``harness_request_sha256`` / ``harness_report_sha256``;
* two executions over the same fixture are byte-identical and carry the same
  sha256 values, including across distinct ``PYTHONHASHSEED`` values;
* the real ``#367`` ISO EV run is never consumed and #344/#199/#423 are reused,
  never modified;
* an invalid fixture fails closed with an explicit ``reason_code`` and produces
  no report and no status.

Run it with::

    PYTHONPATH=. python3 tests/simulation/test_model_b_hero_robustness_adapter.py
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.simulation import model_b_hero_robustness_adapter as adapter  # noqa: E402
from tools.simulation import model_b_preflop_sensitivity_harness as harness  # noqa: E402

FIXTURES = ROOT / "tests/fixtures/model_b_hero_robustness"
CONTEXT_PATH = (
    ROOT / "tests/fixtures/model_b_preflop_sensitivity/synthetic_sb_two_limpers_context.json"
)
ADAPTER_PATH = ROOT / "tools/simulation/model_b_hero_robustness_adapter.py"
REPORT_SCHEMA_PATH = (
    ROOT / "contracts/training/hero-model-b-robustness-consumer-report.schema.json"
)
HARNESS_PATH = ROOT / "tools/simulation/model_b_preflop_sensitivity_harness.py"
SOURCE_340 = ROOT / "training/runs/20260919_model_b_preflop_response_to_price_2a"
FORBIDDEN_367_RUN = ROOT / "training/runs/20260919_issue367_real_iso_ev_v1"

#: Fixture -> expected #425 verdict.
FIXTURE_STATUSES = {
    "robust_consistent.json": "CONSISTENT",
    "multi_sizing.json": "SENSITIVE",
    "too_close.json": "TOO_CLOSE",
    "sparse_high_uncertainty.json": "INSUFFICIENT_SUPPORT",
    "ood_unsupported.json": "OOD_UNTESTABLE",
}
INVALID_FIXTURE = "schema_mismatch.json"

#: Assembled so this guard does not itself hard-code the forbidden run name.
FORBIDDEN_RUN_MARKER = "real" + "_iso" + "_ev"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture(name: str) -> dict:
    return load_json(FIXTURES / name)


def context() -> dict:
    return load_json(CONTEXT_PATH)


def docs_340() -> dict:
    cache = getattr(docs_340, "_cache", None)
    if cache is None:
        cache = adapter.load_source_340_docs()
        docs_340._cache = cache  # type: ignore[attr-defined]
    return cache


def report_for(name: str) -> dict:
    cache = getattr(report_for, "_cache", None)
    if cache is None:
        cache = {}
        report_for._cache = cache  # type: ignore[attr-defined]
    if name not in cache:
        cache[name] = adapter.build_report(
            fixture(name), context=context(), **docs_340()
        )
    return copy.deepcopy(cache[name])


def cli(
    fixture_path: Path,
    out_path: Path | None = None,
    extra_env: dict | None = None,
) -> "subprocess.CompletedProcess[str]":
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    if extra_env:
        env.update(extra_env)
    command = [sys.executable, str(ADAPTER_PATH), "--fixture", str(fixture_path)]
    if out_path is not None:
        command += ["--out", str(out_path)]
    return subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, text=True)


def independent_chain(name: str) -> dict:
    """Recompute the #425 -> #344 chain without going through the adapter."""
    from tools.simulation import model_b_hero_robustness_contract as contract

    document = contract.load_robustness_input(FIXTURES / name)
    request = contract.project_to_harness_request(document, context())
    report = harness.run_harness(request, **docs_340())
    return {
        "request_sha256": harness.canonical_sha256(request),
        "report_sha256": report["report_sha256"],
        "harness_input_request_sha256": report["input_request_sha256"],
    }


class ReportContractTest(unittest.TestCase):
    def test_report_schema_is_fail_closed_and_declares_its_fields(self) -> None:
        schema = load_json(REPORT_SCHEMA_PATH)
        self.assertEqual(schema["$id"], adapter.ADAPTER_REPORT_SCHEMA)
        self.assertIs(schema["additionalProperties"], False)
        self.assertIs(
            schema["properties"]["information_boundary"]["additionalProperties"], False
        )
        self.assertIs(
            schema["properties"]["provenance"]["additionalProperties"], False
        )
        self.assertEqual(
            set(schema["required"]),
            {
                "schema",
                "input_schema_ref",
                "status",
                "reason_codes",
                "information_boundary",
                "provenance",
                "harness_request_sha256",
                "harness_report_sha256",
            },
        )
        self.assertEqual(
            set(schema["properties"]["status"]["enum"]), set(adapter.STATUSES)
        )
        self.assertEqual(
            len(schema["properties"]["status"]["enum"]), 5,
        )

    def test_every_fixture_yields_a_conforming_report(self) -> None:
        expected_keys = {
            "schema",
            "input_schema_ref",
            "status",
            "reason_codes",
            "information_boundary",
            "provenance",
            "harness_request_sha256",
            "harness_report_sha256",
        }
        for name, expected in FIXTURE_STATUSES.items():
            with self.subTest(fixture=name):
                report = report_for(name)
                self.assertEqual(set(report), expected_keys)
                self.assertEqual(report["schema"], adapter.ADAPTER_REPORT_SCHEMA)
                self.assertEqual(
                    report["input_schema_ref"], "hero-model-b-robustness-input/v1"
                )
                self.assertEqual(report["status"], expected)
                self.assertIn(report["status"], tuple(adapter.STATUS_VOCABULARY))
                self.assertIn(report["status"], adapter.STATUSES)
                self.assertTrue(report["reason_codes"])
                self.assertEqual(
                    sorted(report["reason_codes"]), report["reason_codes"]
                )
                self.assertEqual(
                    len(set(report["reason_codes"])), len(report["reason_codes"])
                )
                for code in report["reason_codes"]:
                    self.assertIsInstance(code, str)
                    self.assertTrue(code)
                self.assertEqual(
                    report["information_boundary"],
                    {flag: False for flag in adapter.REPORT_INFORMATION_BOUNDARY_FLAGS},
                )
                self.assertTrue(
                    all(
                        value is False
                        for value in report["information_boundary"].values()
                    )
                )
                self.assertEqual(report["provenance"], adapter.REPORT_PROVENANCE)
                self.assertIs(report["provenance"]["synthetic_fixture"], True)
                for flag in (
                    "real_issue_367_consumed",
                    "real_issue_314_consumed",
                    "validation_consumed",
                    "test_consumed",
                ):
                    self.assertIs(report["provenance"][flag], False)
                for key in ("harness_request_sha256", "harness_report_sha256"):
                    self.assertRegex(report[key], r"^[a-f0-9]{64}$")

    def test_report_passes_the_shipped_schema_and_the_builtin_walker(self) -> None:
        for name in FIXTURE_STATUSES:
            with self.subTest(fixture=name):
                report = report_for(name)
                self.assertIs(adapter.validate_report(report), report)
        try:
            import jsonschema  # type: ignore
        except ImportError:  # pragma: no cover - jsonschema is not a locked dependency
            self.skipTest("jsonschema absent; the built-in walker already validated")
        validator = jsonschema.Draft202012Validator(load_json(REPORT_SCHEMA_PATH))
        for name in FIXTURE_STATUSES:
            with self.subTest(fixture=name):
                errors = sorted(
                    validator.iter_errors(report_for(name)), key=lambda e: list(e.path)
                )
                self.assertEqual([error.message for error in errors], [])

    def test_report_boundary_and_provenance_consts_are_pinned(self) -> None:
        bad = report_for("robust_consistent.json")
        bad["information_boundary"]["model_a_consumed"] = True
        with self.assertRaises(adapter.AdapterError) as raised:
            adapter.validate_report(bad)
        self.assertEqual(raised.exception.reason_code, "REPORT_SCHEMA_VIOLATION")

        bad = report_for("robust_consistent.json")
        bad["provenance"]["real_issue_367_consumed"] = True
        with self.assertRaises(adapter.AdapterError):
            adapter.validate_report(bad)

        bad = report_for("robust_consistent.json")
        bad["status"] = "ROBUST"
        with self.assertRaises(adapter.AdapterError):
            adapter.validate_report(bad)

        bad = report_for("robust_consistent.json")
        bad["extra"] = 1
        with self.assertRaises(adapter.AdapterError) as raised:
            adapter.validate_report(bad)
        self.assertEqual(raised.exception.reason_code, "REPORT_SCHEMA_VIOLATION")

    def test_report_hashes_bind_the_projected_request_and_harness_report(self) -> None:
        chain = independent_chain("robust_consistent.json")
        report = report_for("robust_consistent.json")
        self.assertEqual(report["harness_request_sha256"], chain["request_sha256"])
        self.assertEqual(report["harness_report_sha256"], chain["report_sha256"])
        self.assertEqual(
            report["harness_request_sha256"], chain["harness_input_request_sha256"]
        )


class DeterminismTest(unittest.TestCase):
    def test_two_in_process_runs_are_identical(self) -> None:
        for name in FIXTURE_STATUSES:
            with self.subTest(fixture=name):
                first = adapter.build_report(
                    fixture(name), context=context(), **docs_340()
                )
                second = adapter.build_report(
                    fixture(name), context=context(), **docs_340()
                )
                self.assertEqual(first, second)
                self.assertEqual(
                    adapter.render_report(first), adapter.render_report(second)
                )
                self.assertEqual(
                    first["harness_request_sha256"], second["harness_request_sha256"]
                )
                self.assertEqual(
                    first["harness_report_sha256"], second["harness_report_sha256"]
                )

    def test_cli_output_is_byte_identical_across_hash_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.json"
            second = Path(tmp) / "second.json"
            run_a = cli(
                FIXTURES / "robust_consistent.json", first, {"PYTHONHASHSEED": "0"}
            )
            run_b = cli(
                FIXTURES / "robust_consistent.json", second, {"PYTHONHASHSEED": "12345"}
            )
            self.assertEqual(run_a.returncode, 0, run_a.stderr)
            self.assertEqual(run_b.returncode, 0, run_b.stderr)
            first_text = first.read_text(encoding="utf-8")
            self.assertEqual(first_text, second.read_text(encoding="utf-8"))
            self.assertEqual(run_a.stdout, run_b.stdout)
            self.assertEqual(run_a.stdout, first_text)
            self.assertEqual(json.loads(first_text)["status"], "CONSISTENT")

    def test_cli_writes_every_fixture_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for name, expected in FIXTURE_STATUSES.items():
                with self.subTest(fixture=name):
                    first = Path(tmp) / f"{name}.a.json"
                    second = Path(tmp) / f"{name}.b.json"
                    self.assertEqual(cli(FIXTURES / name, first).returncode, 0)
                    self.assertEqual(cli(FIXTURES / name, second).returncode, 0)
                    self.assertEqual(
                        first.read_text(encoding="utf-8"),
                        second.read_text(encoding="utf-8"),
                    )
                    written = json.loads(first.read_text(encoding="utf-8"))
                    self.assertEqual(written["status"], expected)
                    self.assertEqual(written, report_for(name))
                    adapter.validate_report(written)

    def test_report_is_independent_of_the_fixture_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "copied-fixture.json"
            copied.write_text(
                json.dumps(fixture("robust_consistent.json")), encoding="utf-8"
            )
            out = Path(tmp) / "report.json"
            run = cli(copied, out)
            self.assertEqual(run.returncode, 0, run.stderr)
            rendered = out.read_text(encoding="utf-8")
            self.assertEqual(json.loads(rendered), report_for("robust_consistent.json"))
            self.assertNotIn(tmp, rendered)
            self.assertNotIn("captured-at", rendered)


class FailClosedTest(unittest.TestCase):
    def test_schema_mismatch_produces_no_report_and_no_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "never.json"
            run = cli(FIXTURES / INVALID_FIXTURE, out)
            self.assertEqual(run.returncode, 2)
            self.assertFalse(out.exists(), "a fail-closed run must not write a report")
            payload = json.loads(run.stderr)
            self.assertEqual(payload["schema"], adapter.ADAPTER_ERROR_SCHEMA)
            self.assertEqual(payload["outcome"], "FAIL_CLOSED")
            self.assertEqual(payload["reason_code"], "SCHEMA_MISMATCH")
            self.assertNotIn("status", payload)

    def test_invalid_mutations_fail_closed_with_an_explicit_reason_code(self) -> None:
        base = fixture("robust_consistent.json")
        cases = (
            (lambda doc: doc.pop("provenance"), "MISSING_PROVENANCE"),
            (
                lambda doc: doc["provenance"].pop("validation_consumed"),
                "MISSING_PROVENANCE",
            ),
            (
                lambda doc: doc["provenance"].__setitem__(
                    "real_issue_367_consumed", True
                ),
                "MISSING_PROVENANCE",
            ),
            (
                lambda doc: doc["information_boundary"].__setitem__(
                    "hero_ev_consumed", True
                ),
                "INFORMATION_BOUNDARY_VIOLATION",
            ),
            (lambda doc: doc.__setitem__("extra", 1), "UNKNOWN_FIELD"),
            (lambda doc: doc["hero_entry"].pop("support"), "MISSING_SUPPORT"),
            (
                lambda doc: doc["provenance"].__setitem__("synthetic_fixture", False),
                "MISSING_PROVENANCE",
            ),
            (
                lambda doc: doc.__setitem__("source_kind", "REAL_EVIDENCE"),
                "SOURCE_KIND_MISMATCH",
            ),
        )
        for mutate, expected in cases:
            with self.subTest(reason_code=expected):
                bad = copy.deepcopy(base)
                mutate(bad)
                with self.assertRaises(adapter.AdapterError) as raised:
                    adapter.build_report(bad, context=context(), **docs_340())
                self.assertEqual(raised.exception.reason_code, expected)
                payload = raised.exception.to_dict()
                self.assertEqual(payload["outcome"], "FAIL_CLOSED")
                self.assertNotIn("status", payload)

    def test_non_synthetic_fixture_on_disk_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mutation = fixture("robust_consistent.json")
            mutation["provenance"]["synthetic_fixture"] = False
            path = Path(tmp) / "not-synthetic.json"
            path.write_text(json.dumps(mutation), encoding="utf-8")
            out = Path(tmp) / "never.json"
            run = cli(path, out)
            self.assertEqual(run.returncode, 2)
            self.assertFalse(out.exists())
            self.assertEqual(json.loads(run.stderr)["outcome"], "FAIL_CLOSED")

    def test_unreadable_fixture_fails_closed(self) -> None:
        with self.assertRaises(adapter.AdapterError) as raised:
            adapter.run_fixture(
                FIXTURES / "does-not-exist.json"
            )
        self.assertEqual(raised.exception.reason_code, "ROBUSTNESS_FIXTURE_MISSING")

    def test_missing_340_artifact_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(adapter.AdapterError) as raised:
                adapter.run_fixture(
                    FIXTURES / "robust_consistent.json",
                    candidate=Path(tmp) / "absent.json",
                )
        self.assertEqual(
            raised.exception.reason_code, "SOURCE_340_CANDIDATE_DOC_MISSING"
        )


class BoundaryTest(unittest.TestCase):
    def test_the_real_iso_ev_run_is_refused_before_it_is_opened(self) -> None:
        with self.assertRaises(adapter.AdapterError) as raised:
            adapter.assert_source_path_allowed(FORBIDDEN_367_RUN / "RESULT.json")
        self.assertEqual(raised.exception.reason_code, "FORBIDDEN_UPSTREAM_ARTIFACT")
        with self.assertRaises(adapter.AdapterError):
            adapter.load_source_340_docs(run_dir=FORBIDDEN_367_RUN)
        with self.assertRaises(adapter.AdapterError):
            adapter.run_fixture(
                FIXTURES / "robust_consistent.json",
                candidate=FORBIDDEN_367_RUN / "RESULT.json",
            )

    def test_adapter_module_never_hardcodes_the_forbidden_run(self) -> None:
        source = ADAPTER_PATH.read_text(encoding="utf-8")
        self.assertNotIn(FORBIDDEN_RUN_MARKER, source)
        self.assertNotIn("issue367", source)
        self.assertNotIn("20260919_issue367", source)

    def test_default_source_run_is_the_340_run(self) -> None:
        self.assertEqual(adapter.DEFAULT_SOURCE_340_DIR, SOURCE_340)
        self.assertNotIn(FORBIDDEN_RUN_MARKER, str(adapter.DEFAULT_SOURCE_340_DIR))
        self.assertTrue(SOURCE_340.is_dir())
        self.assertTrue(FORBIDDEN_367_RUN.is_dir())

    def test_adapter_reuses_344_without_editing_it(self) -> None:
        source = ADAPTER_PATH.read_text(encoding="utf-8")
        self.assertIn("run_harness", source)
        self.assertIn("project_to_harness_request", source)
        self.assertIn("model_b_hero_robustness_classify", source)
        # #199 and #423 stay untouched: the adapter never imports or points at them.
        self.assertNotIn("model_b_robustness.py", source)
        self.assertNotIn("contracts/analytics", source)
        harness_source = HARNESS_PATH.read_text(encoding="utf-8")
        self.assertIn("def run_harness", harness_source)
        self.assertNotIn("model_b_hero_robustness_adapter", harness_source)

    def test_report_never_claims_validation_or_test_consumption(self) -> None:
        for name in FIXTURE_STATUSES:
            with self.subTest(fixture=name):
                report = report_for(name)
                self.assertIs(report["provenance"]["validation_consumed"], False)
                self.assertIs(report["provenance"]["test_consumed"], False)
                self.assertEqual(report["provenance"]["parent_issue"], "425")
                self.assertEqual(report["provenance"]["harness_issue"], "344")


if __name__ == "__main__":
    unittest.main()
