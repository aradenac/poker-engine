#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools import repro_bootstrap, repro_environment

ROOT = Path(__file__).resolve().parents[1]


class ReproBootstrapTests(unittest.TestCase):
    def test_plan_uses_locked_install_and_single_verify_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = repro_bootstrap.bootstrap_plan(
                root=root,
                venv=root / ".venv",
                manifest_dir=root / "manifests",
                install_os_deps=False,
            )
            flat = [" ".join(command) for command in plan]
            self.assertIn("--no-deps", flat[1])
            self.assertEqual("npm ci --ignore-scripts", flat[2])
            self.assertIn("playwright install chromium", flat[3])
            self.assertIn("repro_bootstrap.py verify --manifest-dir", flat[4])

    def test_verify_fails_closed_before_manifest_write(self) -> None:
        manifest = repro_environment.attach_payload_sha256({
            "schema": repro_environment.MANIFEST_SCHEMA,
            "expected": {}, "observed": {},
            "matches": {"python": True, "node": True, "playwright": True, "chromium": False, "os": True},
        })
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "manifests"
            with self.assertRaises(repro_bootstrap.BootstrapError):
                repro_bootstrap.verify_environment(ROOT, target, manifest)
            self.assertFalse(target.exists())

    def test_verify_writes_content_addressed_manifest_when_all_match(self) -> None:
        manifest = repro_environment.attach_payload_sha256({
            "schema": repro_environment.MANIFEST_SCHEMA,
            "expected": {}, "observed": {},
            "matches": {"python": True, "node": True, "playwright": True, "chromium": True, "os": True},
        })
        with tempfile.TemporaryDirectory() as temp_dir:
            path = repro_bootstrap.verify_environment(ROOT, Path(temp_dir), manifest)
            self.assertTrue(path.exists())
            self.assertIn(manifest["payload_sha256"], path.name)


if __name__ == "__main__":
    unittest.main()
