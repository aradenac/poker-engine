#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from tools import repro_container
from tools import repro_environment
from tools import repro_environment_identity as environment_identity
from tools import repro_hardening


def clone_sources(destination: Path) -> Path:
    for relative in (
        ".python-version",
        ".node-version",
        "requirements.lock.txt",
        "package-lock.json",
        "reproducibility/environment.lock.json",
        "reproducibility/os-base.lock.json",
        "reproducibility/container-base.lock.json",
        "reproducibility/system-packages.apt.txt",
        "reproducibility/apt-snapshot.lock.json",
        "reproducibility/system-packages.resolution.lock.json",
        "reproducibility/browser-identity.lock.json",
        "reproducibility/ubuntu-snapshot.sources",
        "reproducibility/Dockerfile.science",
    ):
        source = ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return destination


def valid_core_runtime() -> dict:
    return repro_environment.attach_payload_sha256({
        "matches": {
            "python": True,
            "node": True,
            "playwright": True,
            "chromium": True,
            "os": True,
        }
    })


def valid_observation(root: Path = ROOT) -> dict:
    expected = repro_hardening.expected_identity(root)
    packages = {
        name: {
            "installed_version": "1.0-test",
            "candidate_version": "1.0-test",
            "candidate_source_verified": True,
            "architecture": "amd64",
        }
        for name in repro_hardening.load_contract(root)["packages"]
    }
    return {
        "architecture": "amd64",
        "snapshot_id": expected["apt_snapshot_identity"]["snapshot_id"],
        "sources_sha256": expected["apt_snapshot_identity"]["sources_sha256"],
        "packages": packages,
        "browser": {
            "playwright_version": "1.55.0",
            "version": "140.0.7339.16",
            "revision": "1187",
            "executable_path": "/ms-playwright/chromium-1187/chrome-linux/chrome",
            "binary_sha256": "a" * 64,
            "archive_sha256": None,
        },
        "core_runtime": valid_core_runtime(),
        "base_image_digest": None,
    }


def rules(report: dict) -> set[str]:
    return {item["rule"] for item in report["violations"]}


class ReproHardeningTests(unittest.TestCase):
    def test_exact_package_resolution_passes_with_explicit_limit_warnings(self) -> None:
        report = repro_hardening.verify_observation(valid_observation(), ROOT)
        self.assertEqual("WARN", report["status"])
        self.assertEqual([], report["violations"])
        self.assertIn(
            "SYSTEM_PACKAGE_VERSIONS_NOT_PREEXPANDED",
            {item["rule"] for item in report["warnings"]},
        )

    def test_wrong_package_version_fails(self) -> None:
        observation = valid_observation()
        name = sorted(observation["packages"])[0]
        observation["packages"][name]["installed_version"] = "wrong-version"
        report = repro_hardening.verify_observation(observation, ROOT)
        self.assertIn("PACKAGE_RESOLUTION_DIFFERENT", rules(report))

    def test_missing_package_fails(self) -> None:
        observation = valid_observation()
        observation["packages"].pop(sorted(observation["packages"])[0])
        report = repro_hardening.verify_observation(observation, ROOT)
        self.assertIn("PACKAGE_MISSING", rules(report))

    def test_architecture_mismatch_fails(self) -> None:
        observation = valid_observation()
        observation["architecture"] = "arm64"
        report = repro_hardening.verify_observation(observation, ROOT)
        self.assertIn("APT_ARCHITECTURE_MISMATCH", rules(report))

    def test_snapshot_mismatch_fails(self) -> None:
        observation = valid_observation()
        observation["snapshot_id"] = "20260917T000000Z"
        report = repro_hardening.verify_observation(observation, ROOT)
        self.assertIn("APT_SNAPSHOT_MISMATCH", rules(report))

    def test_source_repository_identity_mismatch_fails(self) -> None:
        observation = valid_observation()
        observation["sources_sha256"] = "0" * 64
        report = repro_hardening.verify_observation(observation, ROOT)
        self.assertIn("APT_SOURCE_MISMATCH", rules(report))

    def test_package_repository_snapshot_mismatch_fails(self) -> None:
        observation = valid_observation()
        name = sorted(observation["packages"])[0]
        observation["packages"][name]["candidate_source_verified"] = False
        report = repro_hardening.verify_observation(observation, ROOT)
        self.assertIn("PACKAGE_REPOSITORY_SNAPSHOT_UNEXPECTED", rules(report))

    def test_browser_version_mismatch_fails(self) -> None:
        observation = valid_observation()
        observation["browser"]["version"] = "140.0.7339.99"
        report = repro_hardening.verify_observation(observation, ROOT)
        self.assertIn("BROWSER_VERSION_MISMATCH", rules(report))

    def test_archive_hash_mismatch_fails_when_hash_is_available(self) -> None:
        expected = copy.deepcopy(repro_hardening.expected_identity(ROOT))
        expected["browser_archive_identity"]["sha_pinned"] = True
        expected["browser_archive_identity"]["sha256"] = "b" * 64
        observation = valid_observation()
        observation["browser"]["archive_sha256"] = "c" * 64
        violations, _ = repro_hardening._browser_violations(expected, observation)
        self.assertIn(
            "BROWSER_ARCHIVE_SHA256_MISMATCH",
            {item["rule"] for item in violations},
        )

    def test_installed_binary_mismatch_fails_when_expected_hash_is_available(self) -> None:
        expected = copy.deepcopy(repro_hardening.expected_identity(ROOT))
        expected["browser_binary_identity"]["expected_sha256"] = "b" * 64
        expected["browser_binary_identity"]["sha_pinned"] = True
        observation = valid_observation()
        observation["browser"]["binary_sha256"] = "c" * 64
        violations, _ = repro_hardening._browser_violations(expected, observation)
        self.assertIn(
            "BROWSER_BINARY_SHA256_MISMATCH",
            {item["rule"] for item in violations},
        )

    def test_same_inputs_produce_same_container_and_environment_identity(self) -> None:
        self.assertEqual(
            repro_container.materialize_manifest(ROOT),
            repro_container.materialize_manifest(ROOT),
        )
        self.assertEqual(
            environment_identity.materialize_identity(ROOT),
            environment_identity.materialize_identity(ROOT),
        )

    def test_system_resolution_lock_change_changes_both_identities(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = clone_sources(Path(temp_dir))
            before_container = repro_container.materialize_manifest(root)
            before_environment = environment_identity.materialize_identity(root)
            path = root / "reproducibility/system-packages.resolution.lock.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["review_note"] = "synthetic lock change"
            path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            after_container = repro_container.materialize_manifest(root)
            after_environment = environment_identity.materialize_identity(root)
            self.assertNotEqual(before_container["manifest_sha256"], after_container["manifest_sha256"])
            self.assertNotEqual(before_environment["identity_sha256"], after_environment["identity_sha256"])

    def test_browser_identity_change_changes_both_identities(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = clone_sources(Path(temp_dir))
            before_container = repro_container.materialize_manifest(root)
            before_environment = environment_identity.materialize_identity(root)
            path = root / "reproducibility/browser-identity.lock.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["provenance"]["review_note"] = "synthetic provenance change"
            path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            after_container = repro_container.materialize_manifest(root)
            after_environment = environment_identity.materialize_identity(root)
            self.assertNotEqual(before_container["manifest_sha256"], after_container["manifest_sha256"])
            self.assertNotEqual(before_environment["identity_sha256"], after_environment["identity_sha256"])

    def test_no_archive_hash_or_package_version_is_invented(self) -> None:
        hardening = repro_hardening.expected_identity(ROOT)
        self.assertFalse(hardening["apt_snapshot_identity"]["fully_pinned"])
        self.assertIsNone(hardening["browser_archive_identity"]["sha256"])
        self.assertFalse(hardening["browser_archive_identity"]["sha_pinned"])
        resolution = json.loads(
            (ROOT / "reproducibility/system-packages.resolution.lock.json").read_text(encoding="utf-8")
        )
        self.assertTrue(all(row["resolved_version"] is None for row in resolution["entries"]))

    def test_hermeticity_is_derived_conservatively(self) -> None:
        self.assertEqual(
            "BASE_IMAGE_PINNED",
            repro_hardening.expected_identity(ROOT)["hermeticity_level"],
        )
        self.assertEqual(
            "BASE_SYSTEM_BROWSER_PINNED",
            repro_hardening.derive_hermeticity(
                base_image_pinned=True,
                system_packages_fully_pinned=True,
                browser_archive_sha_pinned=True,
            ),
        )

    def test_historical_grandfathering_is_unchanged(self) -> None:
        historical = {"schema": "historical-run/v1"}
        self.assertTrue(
            environment_identity.validate_run_manifest(
                historical, ROOT, grandfather_historical=False
            )
        )
        self.assertEqual(
            [],
            environment_identity.validate_run_manifest(
                historical, ROOT, grandfather_historical=True
            ),
        )


if __name__ == "__main__":
    unittest.main()
