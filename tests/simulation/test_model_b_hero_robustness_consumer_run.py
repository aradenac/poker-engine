#!/usr/bin/env python3
"""Acceptance tests for the versioned robustness consumer run (task backlog-o7k).

``training/runs/20260927_model_b_hero_robustness_consumer_v1/`` is the
persisted, versioned evidence of the synthetic ``#425`` chain. The ticket asks
for one run directory holding:

1. ``INPUT_SCHEMA_REF.json`` -- the reference to the T1 schema
   (``contracts/training/model-b-hero-robustness-input.schema.json``,
   ``hero-model-b-robustness-input/v1``);
2. one report per synthetic fixture, emitted *by the T5 runner*
   (``tools/simulation/model_b_hero_robustness_adapter.py``) -- never
   hand-written and never derived from the RESULT.json of the real ``#367`` ISO
   EV run;
3. ``INDEPENDENCE_PROOF.json`` -- the forbidden features are enumerated, none of
   them is present in the projected ``#344`` request and
   ``information_boundary = false``;
4. ``RUN_PROVENANCE.json`` -- ``real_issue_367_consumed = false``,
   ``validation_consumed = false``, ``test_consumed = false``,
   ``active_model_b_changed = false``, ``automatic_promotion = false`` and
   ``production_effect = "NONE"``;
5. ``SUMMARY.json`` -- a stable, reproducible sha256 per report; regenerating
   yields the same hashes.

The suite is synthetic and hermetic: it reads only the committed synthetic
fixtures, the public sensitivity context, the T1 contract and the persisted
``#340`` evidence. It never opens the real ``#367`` run, never reads a
VALIDATION/TEST hand and never performs network I/O. Any failure makes the
script exit non-zero.

Run it with::

    PYTHONPATH=. python3 tests/simulation/test_model_b_hero_robustness_consumer_run.py
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.simulation import build_model_b_hero_robustness_consumer_run as builder  # noqa: E402
from tools.simulation.model_b_hero_robustness_adapter import (  # noqa: E402
    ADAPTER_REPORT_SCHEMA,
    INPUT_SCHEMA_REF,
    REPORT_SCHEMA_PATH,
    run_fixture,
)
from tools.simulation.model_b_hero_robustness_contract import (  # noqa: E402
    CONTRACT_PATH,
    project_to_harness_request,
)
from tools.simulation.model_b_preflop_sensitivity_harness import (  # noqa: E402
    FORBIDDEN_ALTERNATIVE_LEAK_FIELDS,
    FORBIDDEN_MODEL_FEATURES,
    canonical_sha256,
    load_json,
)

RUN_DIR = builder.RUN_DIR
FIXED_ARTIFACT_NAMES = builder.FIXED_ARTIFACT_NAMES
EXPECTED_FIXTURE_STATUSES = builder.EXPECTED_FIXTURE_STATUSES
INVALID_FIXTURES = builder.INVALID_FIXTURES
FIXTURES_DIR = builder.DEFAULT_FIXTURES_DIR
CONTEXT_PATH = builder.DEFAULT_CONTEXT_PATH

#: Assembled so this guard does not itself hard-code the forbidden run name.
FORBIDDEN_RUN_TOKEN = "issue367_" + "real_iso_ev_v1"


def load(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def iter_keys(value: Any, path: str = "$"):
    """Yield ``(path, key)`` for every mapping key found anywhere in ``value``."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield f"{path}.{key}", str(key)
            yield from iter_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_keys(child, f"{path}[{index}]")


def leaked_feature_paths(request: Mapping[str, Any]) -> list[str]:
    """Independent forbidden-feature walk over a projected request."""
    tokens = set(FORBIDDEN_MODEL_FEATURES) | set(FORBIDDEN_ALTERNATIVE_LEAK_FIELDS)
    scannable = {key: value for key, value in request.items() if key != "information_boundary"}
    hits: list[str] = []
    for path, key in iter_keys(scannable):
        lowered = key.lower()
        if lowered in tokens or lowered.startswith("model_a"):
            hits.append(path)
    return sorted(set(hits))


class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.input_schema_ref = load(RUN_DIR / "INPUT_SCHEMA_REF.json")
        cls.independence = load(RUN_DIR / "INDEPENDENCE_PROOF.json")
        cls.provenance = load(RUN_DIR / "RUN_PROVENANCE.json")
        cls.summary = load(RUN_DIR / "SUMMARY.json")

    # --- (1) artifacts present and valid ------------------------------------
    def test_all_artifacts_exist(self):
        for name in builder.artifact_names(sorted(EXPECTED_FIXTURE_STATUSES)):
            with self.subTest(name=name):
                self.assertTrue((RUN_DIR / name).is_file(), name)

    def test_fixed_artifacts_are_readable_objects(self):
        for name in FIXED_ARTIFACT_NAMES:
            with self.subTest(name=name):
                value = load(RUN_DIR / name)
                self.assertIsInstance(value, dict)
                self.assertTrue(value.get("schema"))

    def test_no_report_for_the_invalid_fixture(self):
        for name in INVALID_FIXTURES:
            with self.subTest(name=name):
                self.assertFalse((RUN_DIR / builder.report_name(name)).exists(), name)

    # --- (1) INPUT_SCHEMA_REF references the T1 contract ---------------------
    def test_input_schema_ref_points_at_the_t1_contract(self):
        contract = load(CONTRACT_PATH)
        self.assertEqual(self.input_schema_ref["input_schema"], INPUT_SCHEMA_REF)
        self.assertEqual(self.input_schema_ref["contract"]["id"], INPUT_SCHEMA_REF)
        self.assertEqual(contract["$id"], INPUT_SCHEMA_REF)
        self.assertEqual(
            self.input_schema_ref["contract"]["sha256"],
            sha256_bytes(CONTRACT_PATH.read_bytes()),
        )
        self.assertEqual(
            self.input_schema_ref["contract"]["path"],
            "contracts/training/model-b-hero-robustness-input.schema.json",
        )

    def test_input_schema_ref_pins_every_consumed_input(self):
        manifest = self.input_schema_ref["inputs"]
        self.assertEqual(manifest["fixtures_dir"], "tests/fixtures/model_b_hero_robustness")
        for entry in manifest["fixtures"]:
            with self.subTest(fixture=entry["fixture"]):
                self.assertEqual(
                    entry["sha256"],
                    sha256_bytes((FIXTURES_DIR / entry["fixture"]).read_bytes()),
                )
        self.assertEqual(
            manifest["context"]["sha256"], sha256_bytes(CONTEXT_PATH.read_bytes())
        )

    # --- (2) one report per fixture, produced by the T5 runner --------------
    def test_one_report_per_fixture_with_expected_status(self):
        self.assertEqual(self.summary["fixture_count"], len(EXPECTED_FIXTURE_STATUSES))
        self.assertEqual(sorted(self.summary["reports"]), sorted(
            builder.report_name(name) for name in EXPECTED_FIXTURE_STATUSES
        ))
        for fixture, expected_status in EXPECTED_FIXTURE_STATUSES.items():
            with self.subTest(fixture=fixture):
                report = load(RUN_DIR / builder.report_name(fixture))
                self.assertEqual(report["schema"], ADAPTER_REPORT_SCHEMA)
                self.assertEqual(report["status"], expected_status)
                self.assertEqual(report["input_schema_ref"], INPUT_SCHEMA_REF)
                self.assertTrue(report["reason_codes"])
                self.assertEqual(
                    sorted(report["reason_codes"]), list(report["reason_codes"])
                )

    def test_reports_come_from_the_t5_runner(self):
        """The persisted bytes must be exactly what the T5 runner emits."""
        context = load(CONTEXT_PATH)
        for fixture in sorted(EXPECTED_FIXTURE_STATUSES):
            with self.subTest(fixture=fixture):
                fresh = run_fixture(
                    FIXTURES_DIR / fixture, context_path=CONTEXT_PATH
                )
                rendered = (
                    json.dumps(fresh, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
                ).encode("utf-8")
                self.assertEqual(
                    (RUN_DIR / builder.report_name(fixture)).read_bytes(), rendered
                )
                self.assertEqual(fresh["schema"], ADAPTER_REPORT_SCHEMA)
        self.assertTrue(isinstance(context, Mapping))

    def test_reports_match_the_harness_request_hashes(self):
        context = load(CONTEXT_PATH)
        for fixture in sorted(EXPECTED_FIXTURE_STATUSES):
            with self.subTest(fixture=fixture):
                document = load(FIXTURES_DIR / fixture)
                request = project_to_harness_request(document, context)
                report = load(RUN_DIR / builder.report_name(fixture))
                self.assertEqual(
                    report["harness_request_sha256"], canonical_sha256(request)
                )

    def test_invalid_fixture_is_documented_and_failed_closed(self):
        rejected = self.provenance["rejected_fixtures"]
        self.assertEqual(sorted(rejected), sorted(INVALID_FIXTURES))
        for name, expected_code in INVALID_FIXTURES.items():
            with self.subTest(name=name):
                self.assertEqual(rejected[name]["reason_code"], expected_code)

    # --- (3) independence proof ---------------------------------------------
    def test_independence_proof_enumerates_forbidden_features(self):
        self.assertEqual(
            self.independence["forbidden_features"], sorted(FORBIDDEN_MODEL_FEATURES)
        )
        self.assertEqual(
            self.independence["forbidden_alternative_leak_fields"],
            sorted(FORBIDDEN_ALTERNATIVE_LEAK_FIELDS),
        )

    def test_independence_proof_is_clean(self):
        self.assertEqual(self.independence["forbidden_hits"], [])
        self.assertIs(self.independence["information_boundary"], False)
        self.assertIs(self.independence["information_boundary_all_false"], True)
        self.assertIs(self.independence["independence_clean"], True)
        for name, hits in self.independence["forbidden_hits_by_fixture"].items():
            with self.subTest(name=name):
                self.assertEqual(hits, [])
        for name, flag in self.independence["information_boundary_all_false_by_fixture"].items():
            with self.subTest(name=name):
                self.assertIs(flag, True)
        for name, boundary in self.independence["information_boundary_by_fixture"].items():
            with self.subTest(name=name):
                self.assertTrue(boundary)
                self.assertTrue(all(value is False for value in boundary.values()))

    def test_independence_proof_pins_every_projected_request(self):
        hashes = self.independence["projected_request_sha256"]
        self.assertEqual(sorted(hashes), sorted(EXPECTED_FIXTURE_STATUSES))
        for name, digest in hashes.items():
            with self.subTest(name=name):
                self.assertEqual(len(digest), 64)
                int(digest, 16)
                report = load(RUN_DIR / builder.report_name(name))
                self.assertEqual(digest, report["harness_request_sha256"])

    def test_projected_requests_are_independently_leak_free(self):
        context = load(CONTEXT_PATH)
        for fixture in sorted(EXPECTED_FIXTURE_STATUSES):
            with self.subTest(fixture=fixture):
                document = load(FIXTURES_DIR / fixture)
                request = project_to_harness_request(document, context)
                self.assertEqual(leaked_feature_paths(request), [])
                boundary = request["information_boundary"]
                self.assertTrue(boundary)
                self.assertTrue(all(value is False for value in boundary.values()))

    # --- (4) run provenance flags -------------------------------------------
    def test_run_provenance_required_flags(self):
        self.assertIs(self.provenance["real_issue_367_consumed"], False)
        self.assertIs(self.provenance["validation_consumed"], False)
        self.assertIs(self.provenance["test_consumed"], False)
        self.assertIs(self.provenance["active_model_b_changed"], False)
        self.assertIs(self.provenance["automatic_promotion"], False)
        self.assertEqual(self.provenance["production_effect"], "NONE")

    def test_run_provenance_never_closes_the_parent(self):
        for flag in (
            "real_issue_314_consumed",
            "real_hero_results_consumed",
            "real_sensitivity_executed",
            "parent_closed",
        ):
            with self.subTest(flag=flag):
                self.assertIs(self.provenance[flag], False, flag)
        self.assertEqual(self.provenance["parent_issue"], 315)
        self.assertEqual(self.provenance["next_issue"], 315)

    def test_run_provenance_names_the_t5_runner(self):
        self.assertEqual(
            self.provenance["report_generator"],
            "tools/simulation/model_b_hero_robustness_adapter.py",
        )
        self.assertEqual(self.provenance["report_schema"], ADAPTER_REPORT_SCHEMA)

    # --- (5) SUMMARY.json hashes --------------------------------------------
    def test_summary_sha256_matches_the_persisted_reports(self):
        self.assertTrue(self.summary["reports"])
        for name, entry in self.summary["reports"].items():
            with self.subTest(name=name):
                self.assertEqual(len(entry["sha256"]), 64)
                int(entry["sha256"], 16)
                self.assertEqual(
                    entry["sha256"],
                    sha256_bytes((RUN_DIR / name).read_bytes()),
                )
                self.assertEqual(entry["status"], EXPECTED_FIXTURE_STATUSES[entry["fixture"]])

    def test_summary_artifacts_match_the_persisted_bytes(self):
        for name, digest in self.summary["artifacts"].items():
            with self.subTest(name=name):
                self.assertEqual(sha256_bytes((RUN_DIR / name).read_bytes()), digest)

    def test_summary_is_ready_for_integration(self):
        self.assertEqual(self.summary["status"], "READY_FOR_INTEGRATION")
        self.assertTrue(self.summary["expectations"]["all_match"])
        self.assertEqual(self.summary["statuses"], self._expected_histogram())

    def _expected_histogram(self) -> dict[str, int]:
        histogram: dict[str, int] = {}
        for status in EXPECTED_FIXTURE_STATUSES.values():
            histogram[status] = histogram.get(status, 0) + 1
        return dict(sorted(histogram.items()))

    # --- (6) no real #367 evidence ------------------------------------------
    def test_no_artifact_references_the_real_iso_ev_run(self):
        for path in sorted(RUN_DIR.iterdir()):
            if not path.is_file():
                continue
            with self.subTest(name=path.name):
                lowered = path.read_text(encoding="utf-8").lower()
                self.assertNotIn(FORBIDDEN_RUN_TOKEN, lowered)

    def test_report_contract_exists_and_is_the_emitted_schema(self):
        self.assertTrue(REPORT_SCHEMA_PATH.is_file())
        self.assertEqual(load(REPORT_SCHEMA_PATH)["$id"], ADAPTER_REPORT_SCHEMA)


class DeterminismTests(unittest.TestCase):
    @classmethod
    def _fresh(cls) -> dict[str, bytes]:
        """One shared fresh build: the runner subprocesses are the slow part."""
        cache = getattr(cls, "_fresh_cache", None)
        if cache is None:
            cache = builder.build_run_artifacts()
            cls._fresh_cache = cache
        return cache

    def test_two_regenerations_produce_identical_sha256(self):
        first = builder.build_run_artifacts()
        second = builder.build_run_artifacts()
        self.assertEqual(sorted(first), sorted(second))
        for name in sorted(first):
            with self.subTest(name=name):
                self.assertEqual(sha256_bytes(first[name]), sha256_bytes(second[name]))

    def test_persisted_run_matches_a_fresh_regeneration(self):
        fresh = self._fresh()
        for name in builder.artifact_names(sorted(EXPECTED_FIXTURE_STATUSES)):
            with self.subTest(name=name):
                self.assertEqual(
                    sha256_bytes((RUN_DIR / name).read_bytes()),
                    sha256_bytes(fresh[name]),
                    name,
                )

    def test_no_host_path_is_embedded_in_any_artifact(self):
        fresh = self._fresh()
        for name, data in fresh.items():
            text = data.decode("utf-8")
            with self.subTest(name=name):
                self.assertNotIn(str(ROOT), text)
                self.assertNotIn("/tmp/", text)

    def test_check_mode_passes_on_the_persisted_run(self):
        with redirect_stdout(io.StringIO()):
            code = builder.main(["--check", "--out-dir", str(RUN_DIR)])
        self.assertEqual(code, 0)

    def test_check_mode_detects_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in builder.artifact_names(sorted(EXPECTED_FIXTURE_STATUSES)):
                shutil.copy2(RUN_DIR / name, Path(tmp) / name)
            target = Path(tmp) / builder.report_name("too_close.json")
            report = load(target)
            report["status"] = "CONSISTENT"
            target.write_text(
                json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                code = builder.main(["--check", "--out-dir", tmp])
            self.assertEqual(code, 1)

    def test_verify_determinism_cli_succeeds(self):
        with redirect_stdout(io.StringIO()):
            code = builder.main(["--verify-determinism"])
        self.assertEqual(code, 0)

    def test_forbidden_upstream_run_is_refused(self):
        fake_run = Path("/synthetic/forbidden") / FORBIDDEN_RUN_TOKEN
        inputs = builder.RunInputs(model_b_run=fake_run)
        with self.assertRaises(Exception) as caught:
            inputs.source_340_path("candidate_doc")
        self.assertEqual(
            getattr(caught.exception, "reason_code", None), "FORBIDDEN_UPSTREAM_ARTIFACT"
        )

    def test_runner_cli_is_importable_as_a_script(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / builder.CLI_REL), "--help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            env={**dict(os.environ), "PYTHONPATH": str(ROOT)},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
