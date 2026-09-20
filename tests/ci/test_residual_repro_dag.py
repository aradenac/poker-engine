#!/usr/bin/env python3
"""Mutation tests for issue #382; no workflow or scientific command is executed."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import audit_repro_composite_factorization as transition
from tools import audit_active_workflow_dag as dag
from tools import audit_residual_repro_dag as audit


class ResidualReproDagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.before = {path: audit.baseline(path) for path in audit.DISPOSITIONS}
        cls.after = {path: transition.baseline(path) for path in audit.DISPOSITIONS}

    def test_current_consumers_chain_to_historical_after(self):
        for path in self.after:
            with self.subTest(path=path):
                text = (ROOT / path).read_text()
                audit.check_workflow(path, self.before[path], text)
                if path in transition.WORKFLOWS:
                    transition.check_workflow(path, transition.baseline(path), text)

    def reject(self, path: str, old: str, new: str) -> None:
        source = self.after[path]
        self.assertIn(old, source, f"mutation token absent in {path}: {old!r}")
        mutated = source.replace(old, new, 1)
        self.assertNotEqual(source, mutated)
        with self.assertRaises(audit.AuditError):
            audit.check_workflow(path, self.before[path], mutated)

    def test_ten_explicit_dispositions_and_exact_migrations(self) -> None:
        self.assertEqual(len(audit.DISPOSITIONS), 10)
        self.assertEqual(len(audit.MIGRATED), 5)
        self.assertEqual(len(audit.STRONG), 5)
        for path in audit.DISPOSITIONS:
            with self.subTest(path=path):
                audit.check_workflow(path, self.before[path], self.after[path])

    def test_commands_split_seed_dataset_and_scientific_boundaries_are_frozen(self) -> None:
        path = ".github/workflows/model-b-reveal-aware.yml"
        for old, new in (("--seed 20260915", "--seed 20260916"),
                         ("--split VALIDATION", "--split TEST"),
                         ("NLHE 100-200.zip", "OTHER.zip"),
                         ("Paired VALIDATION only", "Paired TEST only")):
            with self.subTest(token=old):
                self.reject(path, old, new)
        path = ".github/workflows/postflop-response-refit.yml"
        self.reject(path, "--epochs 60", "--epochs 61")
        self.reject(path, "'TEST': 2449", "'TEST': 2450")

    def test_artifact_identity_is_frozen(self) -> None:
        path = ".github/workflows/hero-calculated-range-export.yml"
        for old, new in (("name: issue-107-real-generation-smoke-${{ github.sha }}", "name: changed"),
                         ("/tmp/issue-107-aa-run.json", "/tmp/other.json"),
                         ("retention-days: 14", "retention-days: 1")):
            with self.subTest(token=old):
                self.reject(path, old, new)

    def test_job_needs_if_env_matrix_timeout_permissions_concurrency_are_frozen(self) -> None:
        mutations = (
            (".github/workflows/postflop-response-refit.yml", "  refit:", "  renamed:"),
            (".github/workflows/postflop-response-refit.yml", "    timeout-minutes: 90", "    timeout-minutes: 91"),
            (".github/workflows/postflop-response-refit.yml", "      PYTHONPATH: '.'", "      PYTHONPATH: './other'"),
            (".github/workflows/postflop-response-refit.yml", "    steps:", "    strategy:\n      matrix:\n        seed: [1, 2]\n    steps:"),
            (".github/workflows/ingest-artifacts.yml", "contents: write", "contents: read"),
            (".github/workflows/ingest-artifacts.yml", "cancel-in-progress: false", "cancel-in-progress: true"),
            (".github/workflows/materialize-certified-population.yml", "needs: [repro-environment, contract]", "needs: contract"),
            (".github/workflows/materialize-certified-population.yml", "if: github.event_name == 'push'", "if: true"),
        )
        for path, old, new in mutations:
            with self.subTest(path=path, token=old):
                self.reject(path, old, new)

    def test_historical_trigger_and_write_boundary_are_frozen(self) -> None:
        self.reject(".github/workflows/ingest-artifacts.yml", "      - 'artifacts/inbox/*.json'\n", "")
        self.reject(".github/workflows/ingest-artifacts.yml", "on:\n  push:", "on:\n  pull_request:\n  push:")
        self.reject(".github/workflows/ingest-artifacts.yml", "git push", "git push --force")

    def test_runtime_verify_node_necessity_and_bypasses(self) -> None:
        for path in audit.MIGRATED:
            self.reject(path, audit.PYTHON, audit.OLD_PYTHON_311)
            self.reject(path, audit.verify_step(path), "")
            self.reject(path, audit.VERIFY, audit.VERIFY + " || true")
            self.reject(path, "      - name: Verify locked REPRO environment",
                        "      - name: Verify locked REPRO environment\n        continue-on-error: true")
            self.reject(path, "      - name: Verify locked REPRO environment",
                        "      - name: Verify locked REPRO environment\n        if: false")
        for path in audit.NODE:
            self.reject(path, audit.NODE_SETUP, audit.OLD_NODE_22)
            self.reject(path, "verify --require-node", "verify")
        python_only = next(path for path in audit.MIGRATED if path not in audit.NODE)
        self.reject(python_only, audit.PYTHON, audit.PYTHON + audit.NODE_SETUP)

    def test_scope_rejects_every_workflow_outside_migrated_five(self) -> None:
        audit.check_scope(list(audit.ALLOWLIST))
        for forbidden in (".github/workflows/game-core.yml",
                          ".github/workflows/dataset-integrity.yml",
                          ".github/workflows/finalize-training-cycle.yml",
                          "training/models/preflop_population_model_v5.json"):
            with self.subTest(path=forbidden), self.assertRaises(audit.AuditError):
                audit.check_scope([*audit.ALLOWLIST, forbidden])
        # The historical allowlist applies to its recorded commit, not later issues.
        # Current scope is enforced independently by the #384 authoritative audit.
        historical = __import__('json').loads(transition.baseline(audit.EVIDENCE))
        audit.check_scope(historical['files_changed'])

    def test_dag_is_complete_and_unknown_is_never_safe(self) -> None:
        data = dag.build()
        inventory = json.loads(audit.baseline(audit.INVENTORY))
        current = {row["path"] for row in inventory["workflows"] if row["lifecycle"] == "current"}
        dag.validate_data(data, current)
        omitted = copy.deepcopy(data)
        omitted["workflows"].pop()
        with self.assertRaises(dag.AuditError):
            dag.validate_data(omitted, current)
        unknown = next(row for row in data["workflows"] if row["side_effect_class"] == "UNKNOWN")
        unknown["concurrency_recommendation"]["safe_candidate_for_future_cancellation_change"] = True
        with self.assertRaises(dag.AuditError):
            dag.validate_data(data, current)

    def test_twelve_before_after_scenarios_and_repro_trigger_delta(self) -> None:
        data = dag.build()
        self.assertEqual(data["representative_scenario_count"], 14)
        self.assertTrue(all("before" in row and "after" in row
                            for row in data["representative_scenarios"]))
        helper = next(row for row in data["representative_scenarios"]
                      if row["scenario"] == "repro_helper")
        self.assertGreater(helper["after"]["workflow_count"], helper["before"]["workflow_count"])
        historical = next(row for row in data["representative_scenarios"]
                          if row["scenario"] == "historical_manual_workflow")
        self.assertEqual(historical["after"]["workflow_count"], 0)


if __name__ == "__main__":
    unittest.main()
