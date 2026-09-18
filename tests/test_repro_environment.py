#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools import repro_environment


ROOT = Path(__file__).resolve().parents[1]


class ReproEnvironmentTests(unittest.TestCase):
    def test_repository_contract_is_self_consistent(self) -> None:
        self.assertEqual([], repro_environment.validate_contract(ROOT))

    def test_lock_versions_are_exact_and_expected(self) -> None:
        lock = json.loads(
            (ROOT / "reproducibility" / "environment.lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual("3.11.9", lock["python"]["version"])
        self.assertEqual("22.14.0", lock["node"]["version"])
        self.assertEqual("1.55.0", lock["playwright"]["python_package_version"])
        self.assertEqual("140.0.7339.16", lock["playwright"]["chromium_version"])
        self.assertFalse(lock["scope"]["workflows_wired"])

    def test_contract_detects_runtime_file_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for relative in (
                ".python-version",
                ".node-version",
                "requirements.in",
                "requirements.lock.txt",
                "package.json",
                "package-lock.json",
                "reproducibility/environment.lock.json",
            ):
                source = ROOT / relative
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())

            (root / ".node-version").write_text("99.0.0\n", encoding="utf-8")
            errors = repro_environment.validate_contract(root)
            self.assertIn(".node-version differs from environment.lock.json", errors)


if __name__ == "__main__":
    unittest.main()
