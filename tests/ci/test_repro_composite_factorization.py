#!/usr/bin/env python3
"""Mutation tests for REPRO bootstrap factorization (#384).

Ensures that workflows are migrated to use `repro-runtime` or `repro-browser`
composite actions and that no banned inline bootstrap patterns persist.
"""

import unittest
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = (
    '.github/workflows/dataset-integrity.yml',
    '.github/workflows/full-hand-arena.yml',
    '.github/workflows/full-hand-protocol.yml',
    '.github/workflows/hero-calculated-range-export.yml',
    '.github/workflows/hero-range-compliance.yml',
    '.github/workflows/hero-range-editor.yml',
    '.github/workflows/model-b-card-aware-runtime.yml',
    '.github/workflows/model-b-reveal-aware.yml',
    '.github/workflows/population-pack-catalog.yml',
    '.github/workflows/postflop-response-refit.yml',
    '.github/workflows/preflop-grid-evaluator.yml',
    '.github/workflows/preflop-policy169.yml',
    '.github/workflows/preflop-search.yml',
    '.github/workflows/release-handoff-contract.yml',
    '.github/workflows/trainer-smoke.yml',
)

def check_workflow_content(case, path, content):
    case.assertTrue("uses: ./.github/actions/repro-runtime" in content or
                    "uses: ./.github/actions/repro-browser" in content,
                    f"{path} does not use the new composite actions")

    # Banned patterns
    case.assertFalse(re.search(r"uses: actions/setup-python@v5\s+with:\s+python-version:", content),
                     f"{path}: still using inline setup-python")
    case.assertFalse(re.search(r"uses: actions/setup-node@v4\s+with:\s+node-version:", content),
                     f"{path}: still using inline setup-node")

class TestReproCompositeFactorization(unittest.TestCase):
    def test_workflows_contract(self):
        for path in WORKFLOWS:
            with self.subTest(path=path):
                content = (ROOT / path).read_text()
                check_workflow_content(self, path, content)

    def test_mutation_fails(self):
        # Use full-hand-arena.yml as a test case for mutation
        path = WORKFLOWS[1]
        original = (ROOT / path).read_text()

        # Mutation: remove the composite action
        # The file has 6 spaces for indentation
        mutated = original.replace("      - uses: ./.github/actions/repro-runtime\n", "")

        with self.assertRaises(AssertionError):
            check_workflow_content(self, path, mutated)

if __name__ == "__main__":
    unittest.main()
