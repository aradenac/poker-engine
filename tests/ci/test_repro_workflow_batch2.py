#!/usr/bin/env python3
"""Issue #366 static migration contract; standard library only.

Undo ONLY the approved migration and compare the entire historical file hash.
This deliberately freezes triggers, permissions, job/step gates, shell commands,
inputs, assertions, artifacts and tokens, including their ordering and whitespace.
Historical hashes are captured from BASE_SHA, independently of the evidence JSON.
No Git history or YAML dependency is needed to check the workflow contract.
"""
from pathlib import Path
import hashlib
import json
import unittest
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import audit_repro_composite_factorization as transition

BASE_SHA = 'b2fa125bc5da885d30e15f36a8bb17072f46ca18'
BASELINES = {'.github/workflows/full-hand-arena.yml': {'sha256': '3635255ff3de95e3cf734d15e0db7cf59a37d5664707f23ba6e95d6d6083d665',
                                           'setups': 2,
                                           'paths_blocks': 1},
 '.github/workflows/model-b-card-aware-runtime.yml': {'sha256': 'd297c71f5bbaf087ff14f15e9b461d54a06446d396f5eb37e3bd9c1d115ae1a2',
                                                      'setups': 1,
                                                      'paths_blocks': 2}}
PROTECTED = {'.github/workflows/trainer-smoke.yml': 'df5c3226c697515daace3cd4c5484195ba5b85f3111e36061b5220d2df8d0b1d',
 '.github/workflows/hero-range-editor.yml': '8f47e3b352b2b6c98d3ae6e48afb4feb5ee45dd426fd857316510b64259ba2d2',
 '.github/workflows/hero-range-compliance.yml': '30285d84a72f4a9e985ecbc935955229905010e461b28e01ab31bfe8faf78e5d',
 '.github/workflows/project-state-consistency.yml': '16afa5bb9009d075665077c659410e44c7b96390edbadc0e49d398c095299e92'}
REPRO_PATHS = ('tools/repro_ci_environment.py',
 'tools/repro_environment_identity.py',
 'tools/repro_container.py',
 'tools/repro_hardening.py',
 'tools/repro_environment.py',
 '.python-version',
 '.node-version',
 'requirements.lock.txt',
 'package-lock.json',
 'reproducibility/environment.lock.json',
 'reproducibility/os-base.lock.json',
 'reproducibility/container-base.lock.json',
 'reproducibility/Dockerfile.science',
 'reproducibility/system-packages.apt.txt',
 'reproducibility/apt-snapshot.lock.json',
 'reproducibility/system-packages.resolution.lock.json',
 'reproducibility/browser-identity.lock.json',
 'reproducibility/ubuntu-snapshot.sources')
OLD_SETUP = "      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.11'\n"
LOCKED_SETUP = "      - uses: actions/setup-python@v5\n        with:\n          python-version-file: '.python-version'\n      - name: Verify locked REPRO environment\n        run: python3 tools/repro_ci_environment.py verify\n"


def check_workflow(case, path, text):
    try:
        text = transition.historical_text(path, text)
    except transition.AuditError as exc:
        case.fail(str(exc))
    baseline = BASELINES[path]
    case.assertEqual(text.count("uses: actions/setup-python@"), baseline["setups"])
    case.assertEqual(text.count(LOCKED_SETUP), baseline["setups"],
                     "Every Python setup must immediately run the unconditional verifier")
    case.assertEqual(text.count("python3 tools/repro_ci_environment.py verify"),
                     baseline["setups"])
    case.assertNotRegex(text, r"continue-on-error|\|\|\s*true|repro_ci_browser\.py")
    paths_block = "    paths:\n" + "".join(f"      - '{p}'\n" for p in REPRO_PATHS)
    case.assertEqual(text.count(paths_block), baseline["paths_blocks"])
    restored = text.replace(LOCKED_SETUP, OLD_SETUP).replace(paths_block, "    paths:\n")
    case.assertEqual(hashlib.sha256(restored.encode()).hexdigest(), baseline["sha256"],
                     "Historical workflow changed beyond the approved REPRO migration")


class ReproWorkflowBatch2Tests(unittest.TestCase):
    def test_only_target_workflows_and_complete_contract(self):
        self.assertEqual(set(BASELINES), {
            ".github/workflows/full-hand-arena.yml",
            ".github/workflows/model-b-card-aware-runtime.yml",
        })
        for path in BASELINES:
            with self.subTest(path=path):
                check_workflow(self, path, (ROOT / path).read_text())

    def test_exact_python_identity(self):
        version = (ROOT / ".python-version").read_text().strip()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        lock = json.loads((ROOT / "reproducibility/environment.lock.json").read_text())
        self.assertEqual(version, lock["python"]["version"])
        self.assertIn(lock["python"]["requirements"], REPRO_PATHS)
        self.assertIn(lock["node"]["package_lock"], REPRO_PATHS)
        for path in REPRO_PATHS:
            self.assertTrue((ROOT / path).is_file(), path)

    def test_protected_workflows_unchanged(self):
        # Issue-scoped baseline guard for the explicitly excluded #361/#346 files.
        for path, digest in PROTECTED.items():
            with self.subTest(path=path):
                self.assertEqual(hashlib.sha256(transition.historical_text(path, (ROOT / path).read_text()).encode()).hexdigest(), digest)

    def test_fail_closed_against_gate_and_command_mutations(self):
        path = ".github/workflows/full-hand-arena.yml"
        original = transition.baseline(path)
        mutations = [
            original.replace("        run: python3 tools/repro_ci_environment.py verify\n", "", 1),
            original.replace("verify\n", "verify || true\n", 1),
            original.replace("      - name: Verify locked", "        continue-on-error: true\n      - name: Verify locked", 1),
            original.replace("        run: python3 tools/repro_ci_environment.py verify", "        if: false\n        run: python3 tools/repro_ci_environment.py verify", 1),
            original.replace("          python-version-file: '.python-version'", "          python-version: '3.11'", 1),
            original.replace("          assert report['summary']['simulated_hands'] == 4\n", ""),
            original.replace("          PYTHONPATH=. python3 tests/simulation/test_full_hand_arena.py\n", ""),
            original.replace("  actions: read\n", ""),
            original.replace("  workflow_dispatch:\n", ""),
            original.replace("      - 'requirements.lock.txt'\n", "", 1),
        ]
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=index):
                self.assertNotEqual(original, mutation)
                with self.assertRaises(AssertionError):
                    check_workflow(self, path, mutation)


if __name__ == "__main__":
    unittest.main()
