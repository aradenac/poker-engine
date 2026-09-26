#!/usr/bin/env python3
"""Normative exact-context runtime contract: the doc must match the artifacts.

``docs/hierarchical-exact-context-runtime-contract.md`` states the normative
meaning of the three hierarchical statuses, the strict identity/pooling
separation, the disposition of ``RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE`` and the
precise #367 tree-closure conditions. This guard re-derives every quoted value
from the machine-readable sources of truth so the text cannot drift from the
spec, the candidate contract, the preflight, the raise-sizing frontiers or the
terminal decision.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "analysis/issue419_hierarchical_tree"

SPEC = json.loads((BUNDLE / "HIERARCHICAL_MODEL_SPEC.json").read_text(encoding="utf-8"))
CONTRACT = json.loads((BUNDLE / "contract/CANDIDATE_CONTRACT.json").read_text(encoding="utf-8"))
PREFLIGHT = json.loads(
    (BUNDLE / "exact_tree_preflight/EXACT_TREE_PREFLIGHT.json").read_text(encoding="utf-8")
)
FRONTIERS = json.loads(
    (BUNDLE / "raise_sizing_frontiers/RAISE_SIZING_FRONTIER_RESOLUTION.json").read_text(
        encoding="utf-8"
    )
)
DECISION = json.loads((BUNDLE / "terminal_decision/DECISION.json").read_text(encoding="utf-8"))
VALIDATION = json.loads((BUNDLE / "validation/VALIDATION_RESULT.json").read_text(encoding="utf-8"))
DOC_RAW = (ROOT / "docs/hierarchical-exact-context-runtime-contract.md").read_text(
    encoding="utf-8"
)
# Collapse markdown line wrapping so phrase assertions are stable.
DOC = " ".join(DOC_RAW.split())


class HierarchicalExactContextContractDocTests(unittest.TestCase):
    def test_reason_codes_and_thresholds_match_the_spec(self):
        reason_codes = SPEC["runtime_support_contract"]["reason_codes"]
        self.assertEqual(
            sorted(reason_codes),
            ["EXACT_EMPIRICAL_STRONG", "EXACT_HIERARCHICAL_ESTIMATE", "EXACT_UNRESOLVED"],
        )
        for code in reason_codes:
            with self.subTest(reason_code=code):
                self.assertIn(code, DOC)
                self.assertTrue(reason_codes[code]["condition"])

        thresholds = SPEC["decision_thresholds"]
        self.assertTrue(thresholds["thresholds_frozen"])
        self.assertIn(f"{thresholds['minimum_marginal_observations']} marginal observations", DOC)
        self.assertIn(f"{thresholds['minimum_distinct_hands']} distinct hands", DOC)
        self.assertIn("L0_EXACT_KEY", DOC)
        self.assertIn(thresholds["exact_claim_requires"].split(" meeting")[0], DOC)

        shrinkage = SPEC["hierarchy_prior_shrinkage"]
        self.assertIn(f"kappa0 = {shrinkage['hierarchical_strength_kappa0']:g}", DOC)
        self.assertIn(
            f"alpha = {shrinkage['base_prior']['alpha_per_legal_marginal_action']}", DOC
        )
        for level in shrinkage["levels"]:
            with self.subTest(level=level["level"]):
                self.assertIn(level["level"], DOC)

    def test_support_isolation_and_pooling_separation_are_normative(self):
        rule = SPEC["support_isolation_rule"]
        self.assertEqual(rule["rule_id"], "SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT")
        self.assertEqual(rule["runtime_invariant"], "support.source_key == requested_key")
        self.assertEqual(rule["violation_reason_code"], "COARSE_KEY_SUPPORT_LAUNDERING")
        for anchor in (rule["rule_id"], rule["runtime_invariant"], rule["violation_reason_code"]):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, DOC)

        axes = SPEC["parameter_pooling"]["axes"]
        for axis in axes["never_mutualizable"]:
            with self.subTest(never_mutualizable=axis):
                self.assertIn(axis, DOC)

    def test_coarse_merge_risk_is_documented_as_contained_not_resolved(self):
        decision = SPEC["granularity_decision"]
        self.assertEqual(
            decision["decision_id"], "EXACT_KEY_IDENTITY_IS_FINER_THAN_RUNTIME_PROVIDER_KEY"
        )
        self.assertEqual(decision["risk_addressed"], "RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE")
        self.assertEqual(decision["status"], "OPEN_FOR_367_SPEC_DOES_NOT_CHANGE_PROVIDER")
        self.assertFalse(decision["provider_change_performed_here"])
        for anchor in (decision["decision_id"], decision["risk_addressed"], decision["status"]):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, DOC)

        evidence = decision["evidence"]
        self.assertIn(f"{evidence['nodes_total']} fine keys", DOC)
        self.assertIn(f"{evidence['distinct_runtime_support_context_keys']} coarse", DOC)
        self.assertIn(f"{evidence['runtime_keys_merging_audit_states']} collision groups", DOC)
        self.assertEqual(evidence["runtime_keys_merging_audit_states"], 8)
        self.assertEqual(evidence["runtime_qualified_nodes"], 3)
        self.assertEqual(evidence["audit_exact_qualified_nodes"], 0)
        self.assertIn(f"{evidence['runtime_qualified_nodes']} of the 38 required nodes", DOC)
        self.assertIn(f"{evidence['audit_exact_qualified_nodes']} qualify at the audit-exact", DOC)

        bb = evidence["canonical_bb_facing_sb_iso5"]
        co = evidence["canonical_co_after_bb_fold"]
        self.assertIn(
            f"{bb['runtime_observations']} observations / {bb['runtime_distinct_hands']} "
            "distinct hands",
            DOC,
        )
        self.assertIn(
            f"{bb['audit_exact_observations']} / {bb['audit_exact_distinct_hands']} at `L0`", DOC
        )
        self.assertIn(
            f"{co['runtime_observations']} / {co['runtime_distinct_hands']} at `L3`", DOC
        )
        self.assertIn(
            f"{co['audit_exact_observations']} / {co['audit_exact_distinct_hands']} at `L0`", DOC
        )
        self.assertIn(decision["prerequisite_for_exact_claims"], DOC)

    def test_tree_closure_conditions_match_the_preflight(self):
        conditions = PREFLIGHT["admissibility"]["conditions"]
        self.assertEqual(PREFLIGHT["schema"], "poker-issue419-exact-tree-preflight/v1")
        self.assertFalse(PREFLIGHT["required_tree_complete"])
        self.assertIn("required_tree_complete = false", DOC)
        for name, condition in conditions.items():
            with self.subTest(condition=name):
                self.assertIn(name, DOC)
                self.assertIsInstance(condition["satisfied"], bool)

        self.assertFalse(conditions["every_required_node_has_an_admissible_exact_answer"]["satisfied"])
        self.assertFalse(conditions["no_unresolved_raise_sizing_frontier"]["satisfied"])
        self.assertFalse(conditions["required_tree_fully_enumerated"]["satisfied"])
        self.assertTrue(conditions["no_nearest_or_borrowed_substitution_applied"]["satisfied"])
        self.assertTrue(conditions["no_hero_ev_or_recommendation_computed"]["satisfied"])

        counts = PREFLIGHT["admissibility"]["unresolved_reason_counts"]
        for reason, count in counts.items():
            with self.subTest(unresolved_reason=reason):
                self.assertIn(reason, DOC)
                self.assertIn(f"{count}", DOC)

        self.assertEqual(FRONTIERS["unresolved_count"], 7)
        self.assertEqual(FRONTIERS["resolved_count"], 0)
        self.assertIn(f"{FRONTIERS['unresolved_count']} unresolved frontiers", DOC)

    def test_terminal_decision_and_admission_rule_are_pinned(self):
        self.assertEqual(DECISION["schema"], "poker-hierarchical-exact-tree-terminal-decision/v1")
        self.assertFalse(DECISION["admitted"])
        self.assertFalse(DECISION["required_tree_complete"])
        self.assertFalse(DECISION["issue367_authorized"])
        for anchor in (DECISION["decision"], DECISION["status"], "admitted = false"):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, DOC)
        self.assertIn(f"next_issue` is `{DECISION['next_issue']}", DOC)
        self.assertIn(DECISION["decision_rule"]["rule_id"], DOC)
        self.assertIn(DECISION["support_isolation_rule"], DOC)

        validation_blocker = next(
            blocker for blocker in DECISION["blockers"] if blocker["code"] == "VALIDATION_GATES_FAILED"
        )
        self.assertEqual(VALIDATION["outcome"], DECISION["validation_outcome"])
        self.assertIn(VALIDATION["outcome"], DOC)
        for gate in validation_blocker["failing_gates"]:
            with self.subTest(failing_gate=gate):
                self.assertIn(gate, DOC)
        self.assertEqual(
            sorted(validation_blocker["failing_gates"]), ["calibration_absolute", "coverage_floor"]
        )

    def test_candidate_statuses_and_reference_surfaces(self):
        statuses = CONTRACT["statuses"]
        self.assertEqual(
            sorted(statuses),
            ["EXACT_EMPIRICAL_STRONG", "EXACT_HIERARCHICAL_ESTIMATE", "EXACT_UNRESOLVED"],
        )
        self.assertEqual(
            CONTRACT["candidate_id"], "model-a-preflop-sizing-hierarchical-candidate-v1"
        )
        self.assertIn(DECISION["candidate_sha256"], DOC)
        self.assertIn(DECISION["candidate_id"], DOC)
        for status in statuses:
            with self.subTest(status=status):
                self.assertIn(status, DOC)
        for surface in (
            "docs/model-a-posterior-runtime.md",
            "docs/reviewer-preflop-iso-analysis.md",
        ):
            with self.subTest(surface=surface):
                self.assertIn(surface, DOC)


if __name__ == "__main__":
    unittest.main()
