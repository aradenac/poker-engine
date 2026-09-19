#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import repro_ci_browser
from tools import repro_ci_environment


class ReproCiEnvironmentHelperTests(unittest.TestCase):
    def test_contract_and_plan_are_deterministic(self) -> None:
        first = repro_ci_environment.plan(
            ROOT, install_python_deps=True, install_node_deps=True
        )
        second = repro_ci_environment.plan(
            ROOT, install_python_deps=True, install_node_deps=True
        )
        self.assertEqual(first, second)
        self.assertEqual(
            "poker-repro-ci-environment-helper/v1", first["schema"]
        )
        self.assertEqual("3.11.9", first["expected"]["python"])
        self.assertEqual("22.14.0", first["expected"]["node"])
        self.assertEqual(2, len(first["commands"]))
        self.assertIn("requirements.lock.txt", first["commands"][0])
        self.assertEqual(["npm", "ci", "--ignore-scripts"], first["commands"][1])

    def test_exact_runtime_versions_pass(self) -> None:
        report = repro_ci_environment.verify(
            ROOT,
            require_node=True,
            observed_python="3.11.9",
            observed_node="22.14.0",
        )
        self.assertEqual("PASS", report["status"])
        self.assertEqual([], report["violations"])
        self.assertRegex(report["environment_identity_sha256"], r"^[0-9a-f]{64}$")

    def test_runtime_version_mismatch_fails_closed(self) -> None:
        report = repro_ci_environment.verify(
            ROOT,
            require_node=True,
            observed_python="3.11.8",
            observed_node="22.13.0",
        )
        self.assertEqual("FAIL", report["status"])
        rules = {row["rule"] for row in report["violations"]}
        self.assertEqual(
            {"PYTHON_VERSION_MISMATCH", "NODE_VERSION_MISMATCH"}, rules
        )


class ReproCiBrowserHelperTests(unittest.TestCase):
    def _matching_observation(self) -> dict:
        return {
            "playwright": "1.55.0",
            "chromium": "140.0.7339.16",
            "revision": "1187",
            "executable_path": (
                "/ms-playwright/chromium-1187/chrome-linux/chrome"
            ),
            "binary_sha256": "a" * 64,
        }

    def test_plan_preserves_existing_with_deps_behavior(self) -> None:
        with_deps = repro_ci_browser.plan(ROOT, with_system_deps=True)
        without_deps = repro_ci_browser.plan(ROOT, with_system_deps=False)
        self.assertEqual(with_deps, repro_ci_browser.plan(ROOT, with_system_deps=True))
        self.assertIn("--with-deps", with_deps["commands"][0])
        self.assertNotIn("--with-deps", without_deps["commands"][0])
        self.assertEqual("chromium", with_deps["commands"][0][-1])

    def test_matching_browser_identity_is_warn_only_for_known_archive_gap(self) -> None:
        report = repro_ci_browser.verify(ROOT, self._matching_observation())
        self.assertEqual("WARN", report["status"])
        self.assertEqual([], report["violations"])
        self.assertFalse(report["archive_sha_pinned"])
        self.assertEqual(
            {"BROWSER_ARCHIVE_SHA256_UNPINNED"},
            {row["rule"] for row in report["warnings"]},
        )

    def test_browser_version_mismatch_fails(self) -> None:
        observed = self._matching_observation()
        observed["chromium"] = "140.0.7339.99"
        report = repro_ci_browser.verify(ROOT, observed)
        self.assertEqual("FAIL", report["status"])
        self.assertIn(
            "CHROMIUM_VERSION_MISMATCH",
            {row["rule"] for row in report["violations"]},
        )

    def test_browser_binary_fingerprint_is_required(self) -> None:
        observed = self._matching_observation()
        observed["binary_sha256"] = None
        report = repro_ci_browser.verify(ROOT, observed)
        self.assertEqual("FAIL", report["status"])
        self.assertIn(
            "CHROMIUM_BINARY_SHA256_MISSING",
            {row["rule"] for row in report["violations"]},
        )


class HelperConsumerEvidenceTests(unittest.TestCase):
    def test_every_helper_has_at_least_two_real_future_consumers(self) -> None:
        evidence = json.loads(
            (ROOT / "analysis/workflow_audit/helper_consumers.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("poker-workflow-helper-consumers/v1", evidence["schema"])
        self.assertFalse(evidence["workflow_files_modified"])
        self.assertGreaterEqual(len(evidence["helpers"]), 2)
        for helper in evidence["helpers"]:
            self.assertGreaterEqual(len(helper["consumers"]), 2, helper["helper"])
            for consumer in helper["consumers"]:
                self.assertTrue(consumer["workflow"].startswith(".github/workflows/"))
                self.assertRegex(consumer["workflow_blob_sha"], r"^[0-9a-f]{40}$")

    def test_consumer_evidence_records_measured_inline_sequences(self) -> None:
        evidence = json.loads(
            (ROOT / "analysis/workflow_audit/helper_consumers.json").read_text(
                encoding="utf-8"
            )
        )
        seen = set()
        for helper in evidence["helpers"]:
            for consumer in helper["consumers"]:
                key = (helper["helper"], consumer["workflow"])
                self.assertNotIn(key, seen)
                seen.add(key)
                measured = consumer["evidence"]
                self.assertTrue(measured)
                self.assertTrue(
                    all(isinstance(v, int) and v >= 0 for v in measured.values())
                )
                self.assertGreater(sum(measured.values()), 0)


if __name__ == "__main__":
    unittest.main()
