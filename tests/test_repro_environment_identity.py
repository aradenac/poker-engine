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

from tools import repro_environment_identity as identity
from tools import audit_scientific_run_environment as audit_runs

FIXTURES = ROOT / "tests/fixtures/repro"


def clone_repro_sources(destination: Path) -> Path:
    for relative in (
        ".python-version",
        ".node-version",
        "requirements.lock.txt",
        "package-lock.json",
        "reproducibility/environment.lock.json",
        "reproducibility/os-base.lock.json",
        "reproducibility/container-base.lock.json",
        "reproducibility/system-packages.apt.txt",
        "reproducibility/Dockerfile.science",
    ):
        source = ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return destination


class EnvironmentIdentityTests(unittest.TestCase):
    def test_generation_is_stable_and_content_addressed(self) -> None:
        first = identity.materialize_identity(ROOT)
        second = identity.materialize_identity(ROOT)
        self.assertEqual(first, second)
        self.assertEqual(first["identity_sha256"], second["identity_sha256"])
        self.assertEqual(first["identity_sha256"], identity.canonical_sha256(first))
        self.assertEqual([], identity.validate_identity(first, ROOT))

    def test_lock_change_changes_identity_sha(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = clone_repro_sources(Path(temp_dir))
            before = identity.materialize_identity(root)
            lock = root / "requirements.lock.txt"
            lock.write_text(lock.read_text(encoding="utf-8") + "# synthetic lock metadata change\n", encoding="utf-8")
            after = identity.materialize_identity(root)
            self.assertNotEqual(before["identity_sha256"], after["identity_sha256"])
            before_hash = next(x["sha256"] for x in before["locks"] if x["role"] == "requirements_lock")
            after_hash = next(x["sha256"] for x in after["locks"] if x["role"] == "requirements_lock")
            self.assertNotEqual(before_hash, after_hash)

    def test_version_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = clone_repro_sources(Path(temp_dir))
            (root / ".node-version").write_text("99.0.0\n", encoding="utf-8")
            with self.assertRaises(identity.IdentityError):
                identity.materialize_identity(root)

    def test_bad_hash_and_noncanonical_identity_are_rejected(self) -> None:
        valid = identity.materialize_identity(ROOT)
        bad_hash = copy.deepcopy(valid)
        bad_hash["identity_sha256"] = "0" * 64
        self.assertIn("identity_sha256 mismatch", identity.validate_identity(bad_hash, ROOT))
        noncanonical = copy.deepcopy(valid)
        noncanonical["unexpected"] = True
        errors = identity.validate_identity(noncanonical, ROOT)
        self.assertTrue(any("non-canonical fields" in error for error in errors))

    def test_future_run_injection_and_missing_identity_fail_closed(self) -> None:
        future = json.loads((FIXTURES / "future_run_base.json").read_text(encoding="utf-8"))
        self.assertTrue(identity.validate_run_manifest(future, ROOT))
        self.assertTrue(identity.validate_run_manifest(future, ROOT, grandfather_historical=True))
        injected = identity.inject_manifest(future, ROOT)
        self.assertEqual([], identity.validate_run_manifest(injected, ROOT))
        self.assertEqual(identity.materialize_identity(ROOT), injected["environment_identity"])

    def test_grandfather_is_explicit_only(self) -> None:
        historical = json.loads((FIXTURES / "historical_run_grandfathered.json").read_text(encoding="utf-8"))
        self.assertTrue(identity.validate_run_manifest(historical, ROOT, grandfather_historical=False))
        self.assertEqual([], identity.validate_run_manifest(historical, ROOT, grandfather_historical=True))

    def test_missing_lock_and_missing_critical_version_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = clone_repro_sources(Path(temp_dir))
            (root / "package-lock.json").unlink()
            with self.assertRaises(identity.IdentityError):
                identity.materialize_identity(root)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = clone_repro_sources(Path(temp_dir))
            env_path = root / "reproducibility/environment.lock.json"
            env = json.loads(env_path.read_text(encoding="utf-8"))
            env["playwright"]["chromium_version"] = ""
            env_path.write_text(json.dumps(env, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(identity.IdentityError):
                identity.materialize_identity(root)

    def test_scientific_run_audit_is_deterministic_and_grandfathered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for target in audit_runs.TARGETS:
                path = root / target["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
            first = audit_runs.build_audit(root)
            second = audit_runs.build_audit(root)
            self.assertEqual(first, second)
            self.assertEqual(0, first["summary"]["with_environment_identity"])
            self.assertEqual(len(audit_runs.TARGETS), first["summary"]["without_environment_identity"])
            self.assertEqual([], first["summary"]["missing_representatives"])
            historical = [row for row in first["targets"] if row["historical_policy"].startswith("GRANDFATHERED")]
            self.assertTrue(historical)


if __name__ == "__main__":
    unittest.main()
