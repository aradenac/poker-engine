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

ROOT = Path(__file__).resolve().parents[2]
BASE_SHA = '001a21a8969098adf3e57bfbcaa6a6ddbd038009'
BASELINES = {'.github/workflows/full-hand-arena.yml': {'sha256': '3635255ff3de95e3cf734d15e0db7cf59a37d5664707f23ba6e95d6d6083d665',
                                           'setups': 2,
                                           'paths_blocks': 1},
 '.github/workflows/model-b-card-aware-runtime.yml': {'sha256': 'd297c71f5bbaf087ff14f15e9b461d54a06446d396f5eb37e3bd9c1d115ae1a2',
                                                      'setups': 1,
                                                      'paths_blocks': 2}}
PROTECTED = {'.github/workflows/trainer-smoke.yml': '89bb574b39e5119ac80eddcba68f32939a2cd9633f0eeb4c0f3cf8362c4edac8',
 '.github/workflows/hero-range-editor.yml': '1825295ec7bf5263af6213b26302c87b6864defa804e61c31a134b341b387a0a',
 '.github/workflows/hero-range-compliance.yml': '132d3d211c68ecf16538ed17a90dc1b5e37b694a2838112c8bbf957ada2f5f8a',
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
                self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest)

    def test_fail_closed_against_gate_and_command_mutations(self):
        path = ".github/workflows/full-hand-arena.yml"
        original = (ROOT / path).read_text()
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
