#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import repro_lock_update as update


class LockUpdateProcedureTests(unittest.TestCase):
    def candidate(self, tmp: str) -> Path:
        root = Path(tmp) / "candidate"
        root.mkdir()
        policy = update.load_policy(ROOT)
        for rel in policy["managed_files"]:
            src = ROOT / rel
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return root

    def add_synthetic_system_package(self, root: Path) -> None:
        packages = root / "reproducibility/system-packages.apt.txt"
        text = packages.read_text(encoding="utf-8").rstrip() + "\nzz-test-package\n"
        packages.write_text(text, encoding="utf-8")
        lock = root / "reproducibility/system-packages.resolution.lock.json"
        data = json.loads(lock.read_text(encoding="utf-8"))
        data["entries"].append({
            "requested_package": "zz-test-package",
            "resolved_version": None,
            "source": "ubuntu-official-snapshot",
            "snapshot_status": f"PINNED_{data['snapshot_id']}",
            "verification_status": "RESOLVE_AND_COMPARE_AT_BUILD_OR_VERIFY",
        })
        lock.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def test_no_change_is_deterministic_and_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self.candidate(tmp)
            before = {
                rel: update._sha(ROOT / rel)
                for rel in update.load_policy(ROOT)["managed_files"]
            }
            first = update.build_plan(ROOT, candidate)
            second = update.build_plan(ROOT, candidate)
            after = {
                rel: update._sha(ROOT / rel)
                for rel in update.load_policy(ROOT)["managed_files"]
            }
            self.assertEqual(first, second)
            self.assertRegex(first["plan_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual("NO_CHANGE", first["status"])
            self.assertEqual([], first["violations"])
            self.assertFalse(first["identity_changed"])
            self.assertEqual(before, after)

    def test_coupled_system_package_update_passes_and_changes_identities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self.candidate(tmp)
            self.add_synthetic_system_package(candidate)
            plan = update.build_plan(
                ROOT,
                candidate,
                expected_components=["system_packages"],
            )
            self.assertEqual("PASS", plan["status"])
            self.assertEqual(["system_packages"], plan["changed_components"])
            self.assertEqual([], plan["violations"])
            self.assertTrue(plan["identity_changed"])
            self.assertNotEqual(
                plan["identities"]["old"]["container_manifest_sha256"],
                plan["identities"]["new"]["container_manifest_sha256"],
            )
            self.assertNotEqual(
                plan["identities"]["old"]["environment_identity_sha256"],
                plan["identities"]["new"]["environment_identity_sha256"],
            )

    def test_partial_system_package_update_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self.candidate(tmp)
            path = candidate / "reproducibility/system-packages.apt.txt"
            path.write_text(
                path.read_text(encoding="utf-8").rstrip() + "\nzz-test-package\n",
                encoding="utf-8",
            )
            plan = update.build_plan(ROOT, candidate)
            self.assertEqual("FAIL", plan["status"])
            rules = {row["rule"] for row in plan["violations"]}
            self.assertIn("PARTIAL_COMPONENT_UPDATE", rules)
            self.assertIn("CANDIDATE_CONTRACT_INVALID", rules)

    def test_partial_playwright_update_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self.candidate(tmp)
            path = candidate / "requirements.in"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "playwright==1.55.0",
                    "playwright==1.56.0",
                ),
                encoding="utf-8",
            )
            plan = update.build_plan(ROOT, candidate)
            self.assertEqual("FAIL", plan["status"])
            partial = [
                row
                for row in plan["violations"]
                if row["rule"] == "PARTIAL_COMPONENT_UPDATE"
            ]
            by_component = {row["component"]: row for row in partial}
            self.assertEqual(
                {"python_dependencies", "playwright_runtime"},
                set(by_component),
            )
            self.assertIn(
                "requirements.lock.txt",
                by_component["python_dependencies"]["missing_required_changed_files"],
            )
            self.assertIn(
                "reproducibility/browser-identity.lock.json",
                by_component["playwright_runtime"]["missing_required_changed_files"],
            )

    def test_partial_python_runtime_update_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self.candidate(tmp)
            (candidate / ".python-version").write_text(
                "3.11.10\n",
                encoding="utf-8",
            )
            plan = update.build_plan(ROOT, candidate)
            self.assertEqual("FAIL", plan["status"])
            partial = {
                row["component"]: row
                for row in plan["violations"]
                if row["rule"] == "PARTIAL_COMPONENT_UPDATE"
            }
            self.assertIn("python_runtime", partial)
            self.assertIn(
                "reproducibility/environment.lock.json",
                partial["python_runtime"]["missing_required_changed_files"],
            )
            self.assertIn(
                "CANDIDATE_CONTRACT_INVALID",
                {row["rule"] for row in plan["violations"]},
            )

    def test_partial_node_runtime_update_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self.candidate(tmp)
            (candidate / ".node-version").write_text(
                "22.14.1\n",
                encoding="utf-8",
            )
            plan = update.build_plan(ROOT, candidate)
            self.assertEqual("FAIL", plan["status"])
            partial = {
                row["component"]: row
                for row in plan["violations"]
                if row["rule"] == "PARTIAL_COMPONENT_UPDATE"
            }
            self.assertIn("node_runtime", partial)
            self.assertIn(
                "package-lock.json",
                partial["node_runtime"]["missing_required_changed_files"],
            )
            self.assertIn(
                "CANDIDATE_CONTRACT_INVALID",
                {row["rule"] for row in plan["violations"]},
            )

    def test_partial_apt_snapshot_update_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self.candidate(tmp)
            path = candidate / "reproducibility/apt-snapshot.lock.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["snapshot_id"] = "20260919T000000Z"
            path.write_text(
                json.dumps(data, indent=2) + "\n",
                encoding="utf-8",
            )
            plan = update.build_plan(ROOT, candidate)
            self.assertEqual("FAIL", plan["status"])
            partial = {
                row["component"]: row
                for row in plan["violations"]
                if row["rule"] == "PARTIAL_COMPONENT_UPDATE"
            }
            self.assertIn("apt_snapshot", partial)
            self.assertIn(
                "reproducibility/ubuntu-snapshot.sources",
                partial["apt_snapshot"]["missing_required_changed_files"],
            )
            self.assertIn(
                "CANDIDATE_CONTRACT_INVALID",
                {row["rule"] for row in plan["violations"]},
            )

    def test_partial_container_digest_update_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self.candidate(tmp)
            path = candidate / "reproducibility/container-base.lock.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["image"]["manifest_digest"] = "sha256:" + "1" * 64
            path.write_text(
                json.dumps(data, indent=2) + "\n",
                encoding="utf-8",
            )
            plan = update.build_plan(ROOT, candidate)
            self.assertEqual("FAIL", plan["status"])
            rules = {row["rule"] for row in plan["violations"]}
            self.assertIn("PARTIAL_COMPONENT_UPDATE", rules)
            self.assertIn("CANDIDATE_CONTRACT_INVALID", rules)

    def test_missing_candidate_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self.candidate(tmp)
            (candidate / "reproducibility/browser-identity.lock.json").unlink()
            plan = update.build_plan(ROOT, candidate)
            self.assertEqual("FAIL", plan["status"])
            self.assertIn(
                "MISSING_CANDIDATE_FILE",
                {row["rule"] for row in plan["violations"]},
            )

    def test_expected_component_set_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self.candidate(tmp)
            self.add_synthetic_system_package(candidate)
            plan = update.build_plan(
                ROOT,
                candidate,
                expected_components=["apt_snapshot"],
            )
            self.assertEqual("FAIL", plan["status"])
            self.assertIn(
                "EXPECTED_COMPONENT_SET_MISMATCH",
                {row["rule"] for row in plan["violations"]},
            )

    def test_non_regression_matrix_is_component_aware(self) -> None:
        policy = update.load_policy(ROOT)
        commands = update._required_tests(
            policy,
            ["playwright_runtime", "container_base"],
        )
        self.assertTrue(any("test_repro_lock_update.py" in x for x in commands))
        self.assertTrue(any("test_repro_ci_helpers.py" in x for x in commands))
        self.assertTrue(any("repro_container.py validate" in x for x in commands))
        self.assertEqual(len(commands), len(set(commands)))

    def test_policy_has_all_authorized_update_components(self) -> None:
        components = set(update.load_policy(ROOT)["components"])
        self.assertEqual({
            "python_runtime",
            "python_dependencies",
            "node_runtime",
            "node_dependencies",
            "playwright_runtime",
            "chromium_runtime",
            "os_base",
            "container_base",
            "apt_snapshot",
            "system_packages",
        }, components)


if __name__ == "__main__":
    unittest.main()
