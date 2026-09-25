#!/usr/bin/env python3
"""Fail-closed mutation tests for the issue #204 trigger/concurrency consolidation decision.

No workflow file is modified and no scientific command is executed: every assertion runs against the
static DAG model in tools/audit_active_workflow_dag.py and its versioned decision artifact.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import audit_active_workflow_dag as dag


class ConsolidationDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = dag.build()
        cls.decision = dag.build_decision(cls.data)
        cls.stored = json.loads((ROOT / dag.DECISION).read_text())

    def mutate(self, mutate) -> None:
        candidate = copy.deepcopy(self.decision)
        mutate(candidate)
        with self.assertRaises(dag.AuditError):
            dag.validate_decision(candidate)

    def row(self, candidate: dict, path: str) -> dict:
        return next(row for row in candidate["workflows"] if row["path"] == path)

    def test_versioned_decision_artifact_matches_the_generator(self) -> None:
        self.assertEqual(self.stored, self.decision)
        self.assertEqual(dag.DECISION_SCHEMA, self.decision["schema"])
        self.assertEqual("NO_FURTHER_CONSOLIDATION_JUSTIFIED", self.decision["decision"])
        self.assertIn(self.decision["decision"], dag.DECISION_VALUES)
        self.assertEqual([], self.decision["recommendations"]["applied"])
        # The decision tranche changes no workflow: the frozen DAG evidence stays byte-identical.
        self.assertEqual(json.dumps(self.data, indent=2, sort_keys=True) + "\n",
                         (ROOT / dag.OUTPUT).read_text())
        self.assertEqual(self.decision["inventory_sha256"],
                         json.loads((ROOT / dag.OUTPUT).read_text())["inventory_sha256"])

    def test_every_recommendation_carries_an_explicit_fail_closed_status(self) -> None:
        active = {row["path"] for row in self.data["workflows"]}
        rows = self.decision["workflows"]
        self.assertEqual(active, {row["path"] for row in rows})
        for row in rows:
            with self.subTest(path=row["path"]):
                self.assertIsInstance(row["fail_closed_safe"], bool)
                if row["side_effect_class"] in dag.UNSAFE_SIDE_EFFECT_CLASSES:
                    self.assertFalse(row["fail_closed_safe"])
                if row["fail_closed_safe"]:
                    self.assertIn(row["side_effect_class"], dag.SAFE_SIDE_EFFECT_CLASSES)
                if row["recommendation_state"] == "ALREADY_CANCEL_IN_PROGRESS":
                    self.assertIs(True, row["cancel_in_progress"])
                else:
                    self.assertNotEqual(True, row["cancel_in_progress"])
                    self.assertTrue(row["blockers"])
                    self.assertLessEqual(set(row["blockers"]), set(self.decision["blocker_catalog"]))

    def test_unsafe_side_effects_are_never_marked_safe(self) -> None:
        path = ".github/workflows/population-pack.yml"
        self.assertEqual("PUBLICATION_CAPABLE", self.row(self.decision, path)["side_effect_class"])
        self.mutate(lambda candidate: self.row(candidate, path).update(fail_closed_safe=True))
        self.mutate(lambda candidate: self.row(candidate, path).update(side_effect_class="READ_ONLY"))
        unknown = ".github/workflows/game-core.yml"
        self.assertEqual("UNKNOWN", self.row(self.decision, unknown)["side_effect_class"])
        self.mutate(lambda candidate: self.row(candidate, unknown).update(fail_closed_safe=True))

    def test_unapplied_recommendations_keep_a_catalog_blocker(self) -> None:
        path = ".github/workflows/project-state-consistency.yml"
        self.assertIn("OUT_OF_SCOPE_CHANGE_SURFACE", self.row(self.decision, path)["blockers"])
        self.mutate(lambda candidate: self.row(candidate, path).update(blockers=[]))
        self.mutate(lambda candidate: self.row(candidate, path).update(blockers=["NOT_A_CATALOG_CODE"]))
        self.mutate(lambda candidate: self.row(candidate, path).update(
            recommendation_state="ALREADY_CANCEL_IN_PROGRESS"))

    def test_scope_mutation_of_the_change_surface_is_rejected(self) -> None:
        self.assertFalse(self.decision["change_surface"]["workflow_files_modified"])
        for key in ("workflow_files_modified", "repository_write_surface_expanded",
                    "publication_surface_expanded", "scientific_surface_expanded",
                    "cancellation_surface_changed", "project_state_consistency_modified"):
            self.mutate(lambda candidate, key=key: candidate["change_surface"].update({key: True}))
        self.mutate(lambda candidate: candidate["change_surface"].update(
            declared_change_scope=[".github/workflows/project-state-consistency.yml"]))
        self.mutate(lambda candidate: candidate["change_surface"].update(
            declared_workflow_changes=[".github/workflows/project-state-consistency.yml"]))

    def test_the_worktree_never_modifies_a_workflow_file(self) -> None:
        porcelain = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
        touched = {line[3:].strip() for line in porcelain.splitlines() if line.strip()}
        # This tranche is audit-only: no workflow definition that existed at the pinned base may be edited.
        # A workflow file added by a later issue does not exist at that base, so it is outside the #204
        # consolidation surface (it can never be a "modified" audited definition) and is tolerated here.
        touched_workflows = {path for path in touched if path.startswith(".github/workflows/")}
        pre_existing = {path for path in touched_workflows if self.exists_at_pinned_base(path)}
        self.assertEqual(set(), pre_existing)
        self.assertNotIn(".github/workflows/project-state-consistency.yml", touched_workflows)
        declared = self.decision["change_surface"]["declared_change_scope"]
        self.assertEqual([], [path for path in declared if path.startswith(".github/workflows/")])
        self.assertEqual([dag.OUTPUT], self.decision["change_surface"]["unchanged_frozen_evidence"])

    @staticmethod
    def exists_at_pinned_base(path: str) -> bool:
        """True when the path is part of the pinned #204 snapshot this decision audits."""
        try:
            subprocess.check_output(["git", "show", f"{dag.BASE_SHA}:{path}"], cwd=ROOT,
                                    text=True, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            return False
        return True

    def test_applying_a_change_under_a_no_change_decision_is_rejected(self) -> None:
        def apply_change(candidate: dict) -> None:
            candidate["recommendations"]["applied"] = [{
                "path": ".github/workflows/preflop-grid-evaluator.yml", "fail_closed_safe": True,
                "mutation_test": True, "job_and_artifact_names_preserved": True}]
        self.mutate(apply_change)

        def unsafe_apply(candidate: dict) -> None:
            candidate["decision"] = "MINIMAL_FAIL_CLOSED_CHANGE_APPLIED"
            candidate["recommendations"]["applied"] = [{
                "path": ".github/workflows/population-pack.yml", "fail_closed_safe": False,
                "mutation_test": True, "job_and_artifact_names_preserved": True}]
        self.mutate(unsafe_apply)

    def test_the_alternative_minimal_change_branch_is_also_fail_closed(self) -> None:
        """The unused branch stays well-defined and can only ever carry a read-only/artifact-only workflow."""
        path = ".github/workflows/preflop-grid-evaluator.yml"

        def minimal(candidate: dict) -> None:
            candidate["decision"] = "MINIMAL_FAIL_CLOSED_CHANGE_APPLIED"
            candidate["recommendations"]["applied"] = [{
                "path": path, "fail_closed_safe": True, "mutation_test": True,
                "job_and_artifact_names_preserved": True}]
            candidate["change_surface"]["workflow_files_modified"] = True
            candidate["change_surface"]["cancellation_surface_changed"] = True
            candidate["change_surface"]["declared_workflow_changes"] = [path]
            candidate["change_surface"]["declared_change_scope"] = [
                *candidate["change_surface"]["declared_change_scope"], path]
        accepted = copy.deepcopy(self.decision)
        minimal(accepted)
        dag.validate_decision(accepted)

        def mutate_minimal(change) -> None:
            candidate = copy.deepcopy(self.decision)
            minimal(candidate)
            change(candidate)
            with self.assertRaises(dag.AuditError):
                dag.validate_decision(candidate)

        mutate_minimal(lambda c: c["change_surface"].update(declared_workflow_changes=[
            ".github/workflows/population-pack.yml"]))
        mutate_minimal(lambda c: c["change_surface"].update(workflow_files_modified=False))
        mutate_minimal(lambda c: c["change_surface"].update(repository_write_surface_expanded=True))
        mutate_minimal(lambda c: c["recommendations"]["applied"][0].update(mutation_test=False))
        mutate_minimal(lambda c: c["recommendations"]["applied"][0].update(
            job_and_artifact_names_preserved=False))
        mutate_minimal(lambda c: c["recommendations"]["applied"][0].update(
            path=".github/workflows/project-state-consistency.yml"))

    def test_job_and_artifact_names_are_preserved_for_every_workflow(self) -> None:
        stored = self.stored
        self.assertEqual(dag._name_digest(self.data["workflows"]), stored["frozen_name_digest"])
        self.assertEqual(stored["frozen_name_digest"], self.decision["frozen_name_digest"])
        for row in stored["workflows"]:
            source = next(item for item in self.data["workflows"] if item["path"] == row["path"])
            with self.subTest(path=row["path"]):
                self.assertEqual([job["id"] for job in source["jobs"]], row["job_ids"])
                self.assertEqual([artifact["name"] for artifact in source["artifacts"]],
                                 row["artifact_names"])
        self.assertNotIn(".github/workflows/project-state-consistency.yml",
                         stored["recommendations"]["applied"])

    def test_fourteen_scenarios_are_measured_unbilled_before_and_after(self) -> None:
        scenarios = self.decision["scenarios"]
        self.assertEqual(14, self.decision["scenario_count"])
        self.assertEqual([s[0] for s in dag.SCENARIOS], [item["scenario"] for item in scenarios])
        for item in scenarios:
            with self.subTest(scenario=item["scenario"]):
                self.assertIs(False, item["billed"])
                self.assertEqual("static structural proxy", item["method"])
                self.assertEqual(item["before"], item["after"])
                self.assertEqual({"runs": 0, "jobs": 0, "cost_proxy": 0}, item["delta"])
        self.assertEqual(self.decision["totals"]["before"], self.decision["totals"]["after"])
        self.assertEqual({"runs": 0, "jobs": 0, "cost_proxy": 0}, self.decision["totals"]["delta"])
        self.assertIs(False, self.decision["measurement_method"]["billed"])
        self.mutate(lambda candidate: candidate["scenarios"][0]["after"].update(runs=999))
        self.mutate(lambda candidate: candidate["scenarios"][0].update(billed=True))
        self.mutate(lambda candidate: candidate.update(scenario_count=13))

    def test_counts_reconcile_with_the_active_dag(self) -> None:
        counts = self.decision["counts"]
        self.assertEqual(self.data["active_workflow_count"], counts["active_automatic_workflow_count"])
        self.assertEqual(self.data["manual_only_count"], counts["manual_only_count"])
        self.assertEqual(self.data["inventory_workflow_count"], counts["inventory_workflow_count"])
        self.assertEqual(
            counts["active_automatic_workflow_count"] + counts["manual_only_count"],
            counts["inventory_workflow_count"])
        self.assertEqual(
            counts["without_concurrency_count"] + counts["cancel_in_progress_true_count"]
            + counts["cancel_in_progress_false_count"],
            counts["active_automatic_workflow_count"])
        self.assertEqual(
            counts["safe_candidate_not_applied_count"] + counts["blocked_not_applied_count"],
            self.decision["recommendations"]["unapplied_count"])
        self.assertEqual(
            counts["safe_candidate_not_applied_count"] + counts["blocked_not_applied_count"]
            + counts["cancel_in_progress_true_count"],
            counts["active_automatic_workflow_count"])
        self.assertEqual(
            counts["duplicate_push_and_pull_request_exposure_count"],
            sum(1 for row in self.decision["workflows"]
                if row["duplicate_push_and_pull_request_exposure"]))
        self.mutate(lambda candidate: candidate["counts"].update(without_concurrency_count=99))

    def test_static_proxy_cannot_measure_a_concurrency_change(self) -> None:
        """Fail-closed evidence for the decision: the authorized method is blind to concurrency."""
        sensitivity = self.decision["method_sensitivity"]
        self.assertEqual(sorted(dag.COST_PATTERNS), sensitivity["proxy_inputs"])
        self.assertEqual([], sensitivity["concurrency_sensitive_inputs"])
        self.mutate(lambda candidate: candidate["method_sensitivity"].update(
            concurrency_sensitive_inputs=["cancel-in-progress"]))
        self.mutate(lambda candidate: candidate["method_sensitivity"].update(proxy_inputs=["jobs"]))
        candidates = [".github/workflows/model-b-card-aware-runtime.yml",
                      ".github/workflows/continuous-training-cycle.yml",
                      ".github/workflows/preflop-grid-evaluator.yml"]
        for path in candidates:
            row = self.row(self.decision, path)
            self.assertNotEqual("ALREADY_CANCEL_IN_PROGRESS", row["recommendation_state"])
            source = (ROOT / path).read_text()
            job_count = len(dag.parse_jobs(source.splitlines()))
            mutated = source if not row["has_concurrency"] else source.replace(
                "cancel-in-progress: false", "cancel-in-progress: true", 1)
            if not row["has_concurrency"]:
                mutated = source + "\nconcurrency:\n  group: hypothetical-${{ github.ref }}\n" \
                                   "  cancel-in-progress: true\n"
            with self.subTest(path=path):
                self.assertNotEqual(source, mutated)
                baseline = dag._cost(source, path, row["name"], dag.parse_jobs(source.splitlines()))
                hypothetical = dag._cost(mutated, path, row["name"], dag.parse_jobs(mutated.splitlines()))
                self.assertEqual(baseline, hypothetical)
                self.assertEqual(job_count, len(dag.parse_jobs(mutated.splitlines())))


if __name__ == "__main__":
    unittest.main()
