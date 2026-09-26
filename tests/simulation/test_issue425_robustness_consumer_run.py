#!/usr/bin/env python3
"""Acceptance tests for the versioned #425 robustness consumer run (task backlog-k9w).

``training/runs/20260926_issue425_model_b_robustness_consumer_v1/`` is the
persisted, versioned evidence of the synthetic ``#425`` chain. The ticket asks
for five artifacts and four properties:

1. ``PROVENANCE.json``, ``FIXTURE_OUTPUTS.json`` (one consumer report per
   fixture), ``INDEPENDENCE_PROOF.json`` (``forbidden_hits = []``,
   ``information_boundary_all_false = true`` and the projected-request hashes),
   ``RESULT.json`` and ``SUMMARY.md`` exist and are readable;
2. ``RESULT.json`` carries the non-consumption flags
   (``real_hero_results_consumed``, ``validation_consumed``, ``test_consumed``,
   ``parent_closed`` all ``false``) and ``next_issue = 315``;
3. the (re)generation command is deterministic: two independent regenerations
   produce byte-identical artifacts with identical sha256;
4. ``SUMMARY.md`` states that ``#315`` remains open and that no real sensitivity
   was executed.

The suite is synthetic and hermetic: it reads only the committed synthetic
fixtures, the public sensitivity context and the persisted ``#340`` evidence. It
never opens the real ``#367`` run, never reads a VALIDATION/TEST hand and never
performs network I/O. Any failure makes the script exit non-zero.

Run it with::

    PYTHONPATH=. python3 tests/simulation/test_issue425_robustness_consumer_run.py
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.simulation import build_issue425_robustness_consumer_run as builder  # noqa: E402
from tools.simulation.model_b_hero_robustness_consumer import consume_batch  # noqa: E402
from tools.simulation.model_b_hero_robustness_status import REASON_CODES  # noqa: E402

RUN_DIR = builder.RUN_DIR
ARTIFACT_NAMES = builder.ARTIFACT_NAMES
EXPECTED_FIXTURE_STATUSES = builder.EXPECTED_FIXTURE_STATUSES
STATUS_VOCABULARY = builder.RUN_STATUSES

#: Assembled so this guard does not itself hard-code the forbidden run name.
FORBIDDEN_RUN_MARKER = "real" + "_iso" + "_ev"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = load(RUN_DIR / "RESULT.json")
        cls.provenance = load(RUN_DIR / "PROVENANCE.json")
        cls.fixture_outputs = load(RUN_DIR / "FIXTURE_OUTPUTS.json")
        cls.independence = load(RUN_DIR / "INDEPENDENCE_PROOF.json")
        cls.summary = (RUN_DIR / "SUMMARY.md").read_text(encoding="utf-8")

    # --- (1) artifacts present and valid ------------------------------------
    def test_all_five_artifacts_exist(self):
        for name in ARTIFACT_NAMES:
            with self.subTest(name=name):
                self.assertTrue((RUN_DIR / name).is_file(), name)

    def test_json_artifacts_are_readable_objects(self):
        for name in ("PROVENANCE.json", "FIXTURE_OUTPUTS.json", "INDEPENDENCE_PROOF.json", "RESULT.json"):
            with self.subTest(name=name):
                value = load(RUN_DIR / name)
                self.assertIsInstance(value, dict)
                self.assertTrue(value.get("schema"))

    def test_summary_is_non_empty_markdown(self):
        self.assertTrue(self.summary.startswith("# Run"))
        self.assertIn("## Deterministic (re)generation", self.summary)

    # --- (2) RESULT flags and next_issue ------------------------------------
    def test_result_flags_are_pinned_false(self):
        for flag in (
            "real_hero_results_consumed",
            "validation_consumed",
            "test_consumed",
            "parent_closed",
            "real_sensitivity_executed",
            "real_issue_314_consumed",
            "real_issue_367_consumed",
            "model_a_consumed",
            "hero_ev_consumed",
            "recommendation_consumed",
            "automatic_promotion",
            "active_model_b_changed",
        ):
            with self.subTest(flag=flag):
                self.assertIs(self.result[flag], False, flag)

    def test_result_next_issue_is_315(self):
        self.assertEqual(self.result["next_issue"], 315)
        self.assertEqual(self.result["parent_issue"], 315)
        self.assertEqual(self.result["production_effect"], "NONE")

    def test_result_status_is_in_vocabulary(self):
        self.assertIn(self.result["status"], STATUS_VOCABULARY)
        self.assertEqual(list(self.result["status_vocabulary"]), list(STATUS_VOCABULARY))

    def test_result_is_ready_for_integration(self):
        self.assertEqual(self.result["status"], builder.STATUS_READY)
        self.assertTrue(self.result["expectations"]["all_match"])
        self.assertEqual(self.result["expectations"]["missing_expectation"], [])
        self.assertEqual(self.result["expectations"]["missing_fixture"], [])
        self.assertTrue(all(self.result["dod"].values()))

    def test_result_statuses_match_observations(self):
        self.assertEqual(self.result["statuses"], self.fixture_outputs["statuses"])
        self.assertEqual(self.result["observed_statuses"], self.result["expected_statuses"])
        for name, status in EXPECTED_FIXTURE_STATUSES.items():
            self.assertEqual(self.result["observed_statuses"][name], status, name)

    # --- (1) one consumer report per fixture --------------------------------
    def test_fixture_outputs_has_one_report_per_fixture(self):
        reports = self.fixture_outputs["reports"]
        self.assertEqual(
            [entry["fixture"] for entry in reports], sorted(EXPECTED_FIXTURE_STATUSES)
        )
        self.assertEqual(self.fixture_outputs["fixture_count"], len(reports))
        for entry in reports:
            report = entry["report"]
            self.assertEqual(
                report["schema"], "hero-model-b-robustness-consumer-report/v1", entry["fixture"]
            )
            self.assertEqual(report["status"], EXPECTED_FIXTURE_STATUSES[entry["fixture"]])
            self.assertTrue(report["reason_codes"], entry["fixture"])
            self.assertTrue(set(report["reason_codes"]).issubset(REASON_CODES), entry["fixture"])
            self.assertEqual(sorted(report["reason_codes"]), list(report["reason_codes"]))

    def test_fixture_outputs_match_the_consumer_library(self):
        batch = consume_batch()
        persisted = {entry["fixture"]: entry["report"] for entry in self.fixture_outputs["reports"]}
        for entry, report in zip(batch["fixtures"], batch["reports"]):
            self.assertEqual(persisted[entry["fixture"]], report, entry["fixture"])

    # --- (1) independence proof ---------------------------------------------
    def test_independence_proof_is_clean(self):
        self.assertEqual(self.independence["forbidden_hits"], [])
        self.assertIs(self.independence["information_boundary_all_false"], True)
        self.assertIs(self.independence["independence_clean"], True)
        self.assertTrue(self.independence["forbidden_hits_by_fixture"])
        for name, hits in self.independence["forbidden_hits_by_fixture"].items():
            self.assertEqual(hits, [], name)
        for name, flag in self.independence["information_boundary_all_false_by_fixture"].items():
            self.assertIs(flag, True, name)

    def test_independence_proof_pins_every_projected_request_hash(self):
        hashes = self.independence["projected_request_sha256"]
        self.assertEqual(sorted(hashes), sorted(EXPECTED_FIXTURE_STATUSES))
        for name, digest in hashes.items():
            with self.subTest(name=name):
                self.assertEqual(len(digest), 64)
                int(digest, 16)
        persisted = {entry["fixture"]: entry["report"] for entry in self.fixture_outputs["reports"]}
        for name, report in persisted.items():
            self.assertEqual(
                hashes[name], report["sensitivity"]["request_sha256"], name
            )

    def test_result_manifest_digests_match_the_persisted_bytes(self):
        for name, digest in self.result["artifacts"].items():
            with self.subTest(name=name):
                self.assertEqual(sha256_bytes((RUN_DIR / name).read_bytes()), digest)

    # --- (4) SUMMARY states the boundaries ----------------------------------
    def test_summary_states_315_remains_open(self):
        lowered = self.summary.lower()
        self.assertIn("#315", lowered)
        self.assertIn("remains open", lowered)

    def test_summary_states_no_real_sensitivity_was_executed(self):
        lowered = self.summary.lower()
        self.assertIn("no real sensitivity", lowered)
        self.assertIn("not run the real model b sensitivity evaluation", lowered)

    def test_summary_and_result_document_the_determinism_command(self):
        self.assertIn(builder.BUILDER_REL, self.summary)
        self.assertIn("--verify-determinism", self.summary)
        self.assertEqual(
            self.result["determinism"]["regeneration_command"],
            builder.regeneration_command(RUN_DIR),
        )


class DeterminismTests(unittest.TestCase):
    @classmethod
    def _fresh(cls) -> dict[str, bytes]:
        """One shared fresh build: the CLI subprocess is the slow part."""
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
        for name in ARTIFACT_NAMES:
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
            for name in ARTIFACT_NAMES:
                shutil.copy2(RUN_DIR / name, Path(tmp) / name)
            summary = Path(tmp) / "SUMMARY.md"
            summary.write_text(summary.read_text(encoding="utf-8") + "\ntampered\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                code = builder.main(["--check", "--out-dir", tmp])
            self.assertEqual(code, 1)

    def test_verify_determinism_cli_succeeds(self):
        with redirect_stdout(io.StringIO()):
            code = builder.main(["--verify-determinism"])
        self.assertEqual(code, 0)

    def test_forbidden_upstream_run_is_refused(self):
        fake_run = Path("/synthetic/forbidden") / f"{FORBIDDEN_RUN_MARKER}_v1"
        inputs = builder.RunInputs(model_b_run=fake_run)
        with self.assertRaises(Exception) as caught:
            inputs.source_340_path("candidate_doc")
        self.assertEqual(getattr(caught.exception, "reason_code", None), "FORBIDDEN_UPSTREAM_ARTIFACT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
