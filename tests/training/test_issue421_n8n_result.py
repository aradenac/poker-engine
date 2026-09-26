#!/usr/bin/env python3
"""#421 -- the n8n output block (``N8N_TASK_RESULT``).

``analysis/issue421_generalized_response/N8N_TASK_RESULT.json`` is the *output*
of the #421 cycle: a strict, read-only projection of the already-persisted,
content-addressed terminal evidence.  Nothing here re-opens VALIDATION or TEST
and nothing is re-scored: every value is a published row of

* ``DECISION.json`` (terminal decision, candidate identity, boundaries),
* ``VALIDATION_RESULT.json`` (coverage, LIMPER_VS_ISO coverage, abstention),
* ``RAISE_SIZING_MODEL_REPORT.json`` against the ``FROZEN_VALIDATION_PROTOCOL``
  sizing criteria (``SIZING_NOT_INFERIOR_TO_FROZEN_TRAIN_EVIDENCE``),
* ``ISSUE367_PREFLIGHT.json`` (the #367 preflight gate and its boundaries),
* ``ARTIFACTS.json`` (evidence integrity),

The ticket block is exactly fourteen fields: ``issue``, ``status``,
``decision``, ``candidate_id``, ``candidate_sha256``, ``validation_coverage``,
``limper_vs_iso_coverage``, ``ood_abstain_rate``, ``raise_sizing_gate_passed``,
``issue367_preflight_passed``, ``validation_consumed``, ``test_consumed``,
``active_pointer_mutated`` and ``next_issue``.

The guard re-derives the whole block from those persisted artifacts and fails
closed on any drift, so the block can never silently disagree with the decision
it summarizes.  It also pins the two non-negotiable boundaries
(``test_consumed=false``, ``active_pointer_mutated=false``), the successor
(``next_issue=367``) and the fact that #367 was *not* executed in this run.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BUNDLE = ROOT / "analysis/issue421_generalized_response"
N8N_PATH = BUNDLE / "N8N_TASK_RESULT.json"
DECISION_PATH = BUNDLE / "DECISION.json"
VALIDATION_RESULT_PATH = BUNDLE / "VALIDATION_RESULT.json"
PROTOCOL_PATH = BUNDLE / "FROZEN_VALIDATION_PROTOCOL.json"
MANIFEST_PATH = BUNDLE / "CANDIDATE_MANIFEST.json"
RAISE_SIZING_REPORT_PATH = BUNDLE / "RAISE_SIZING_MODEL_REPORT.json"
PREFLIGHT_PATH = BUNDLE / "ISSUE367_PREFLIGHT.json"
ARTIFACTS_PATH = BUNDLE / "ARTIFACTS.json"

ISSUE = 421
NEXT_ISSUE = 367

#: The exact terminal vocabulary the ticket pins.
STATUS_READY = "READY_FOR_INTEGRATION"
STATUS_BLOCKED = "BLOCKED_SCIENTIFIC"
STATUS_NEEDS_FIXES = "NEEDS_FIXES"
DECISION_ADMIT = "ADMIT_GENERALIZED_RESPONSE_MODEL"
DECISION_RETAIN = "RETAIN_REFERENCE_GENERALIZATION_INSUFFICIENT"

#: The exact field set of the ticket block -- no more, no less.
FIELDS = (
    "issue",
    "status",
    "decision",
    "candidate_id",
    "candidate_sha256",
    "validation_coverage",
    "limper_vs_iso_coverage",
    "ood_abstain_rate",
    "raise_sizing_gate_passed",
    "issue367_preflight_passed",
    "validation_consumed",
    "test_consumed",
    "active_pointer_mutated",
    "next_issue",
)

SIZING_CRITERIA_ID = "SIZING_NOT_INFERIOR_TO_FROZEN_TRAIN_EVIDENCE"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sizing_gate_passed(report: dict, protocol: dict) -> bool:
    """The frozen raise-sizing criterion, read off published rows only.

    ``SIZING_NOT_INFERIOR_TO_FROZEN_TRAIN_EVIDENCE`` is a conjunction of five
    thresholds (CRPS, illegal-generated rate, NLL per sizing, PIT calibration
    and NLL gain vs uniform) frozen in the protocol and measured in the sizing
    report.  The gate passes only when every one of them holds.
    """
    criteria = protocol["sizing_criteria"]
    if criteria["criteria_id"] != SIZING_CRITERIA_ID:
        raise ValueError(
            f"the frozen protocol no longer pins the raise-sizing criterion: {criteria['criteria_id']!r}"
        )
    metrics = report["metrics"]
    return all(
        (
            metrics["crps_bb"] <= criteria["maximum_crps_bb"],
            metrics["illegal_generated_rate"] <= criteria["maximum_illegal_generated_rate"],
            metrics["nll_bits_per_sizing"] <= criteria["maximum_nll_bits_per_sizing"],
            metrics["calibration"]["pit_max_abs_bin_error"]
            <= criteria["maximum_pit_abs_bin_error"],
            metrics["nll_gain_vs_uniform_bits"] >= criteria["minimum_nll_gain_vs_uniform_bits"],
        )
    )


def derive_block() -> dict:
    """Re-derive the whole n8n block from the persisted, content-addressed evidence."""
    decision = load(DECISION_PATH)
    validation = load(VALIDATION_RESULT_PATH)
    protocol = load(PROTOCOL_PATH)
    manifest = load(MANIFEST_PATH)
    sizing = load(RAISE_SIZING_REPORT_PATH)
    preflight = load(PREFLIGHT_PATH)
    artifacts = load(ARTIFACTS_PATH)

    coverage = validation["metrics"]["coverage"]
    integrity_ok = artifacts["digest_verification"]["all_recomputed_digests_match_persisted"] is True
    admitted = decision["decision"] == DECISION_ADMIT and decision["issue367_authorized"] is True
    if admitted:
        status = STATUS_READY
    elif integrity_ok:
        status = STATUS_BLOCKED
    else:
        status = STATUS_NEEDS_FIXES

    return {
        "issue": decision["issue"],
        "status": status,
        "decision": decision["decision"],
        "candidate_id": decision["candidate"]["candidate_id"],
        "candidate_sha256": decision["candidate"]["canonical_payload_sha256"],
        "validation_coverage": coverage["coverage"],
        "limper_vs_iso_coverage": coverage["limiters_vs_iso"]["coverage"],
        "ood_abstain_rate": coverage["abstain_rate"],
        "raise_sizing_gate_passed": sizing_gate_passed(sizing, protocol),
        "issue367_preflight_passed": preflight["admission"]["authorized"] is True,
        "validation_consumed": decision["validation_consumed"],
        "test_consumed": decision["test_consumed"],
        "active_pointer_mutated": decision["active_pointer_mutated"],
        "next_issue": NEXT_ISSUE,
    }


class Issue421N8nResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.block = load(N8N_PATH)
        cls.derived = derive_block()
        cls.decision = load(DECISION_PATH)
        cls.validation = load(VALIDATION_RESULT_PATH)
        cls.protocol = load(PROTOCOL_PATH)
        cls.manifest = load(MANIFEST_PATH)
        cls.sizing = load(RAISE_SIZING_REPORT_PATH)
        cls.preflight = load(PREFLIGHT_PATH)
        cls.artifacts = load(ARTIFACTS_PATH)

    # ------------------------------------------------------------- shape
    def test_block_is_the_exact_ticket_field_set(self):
        self.assertTrue(N8N_PATH.is_file(), f"{N8N_PATH} is missing")
        self.assertEqual(set(self.block), set(FIELDS), "the block is not exactly the ticket field set")
        for key, value in self.block.items():
            with self.subTest(field=key):
                self.assertIn(type(value), (bool, int, float, str))
        self.assertIsInstance(self.block["issue"], int)
        self.assertIsInstance(self.block["next_issue"], int)
        self.assertIsInstance(self.block["raise_sizing_gate_passed"], bool)
        self.assertIsInstance(self.block["issue367_preflight_passed"], bool)
        self.assertIsInstance(self.block["validation_consumed"], bool)
        self.assertIsInstance(self.block["test_consumed"], bool)
        self.assertIsInstance(self.block["active_pointer_mutated"], bool)
        self.assertIsInstance(self.block["validation_coverage"], float)
        self.assertIsInstance(self.block["limper_vs_iso_coverage"], float)
        self.assertIsInstance(self.block["ood_abstain_rate"], float)

    def test_block_is_the_derived_projection_of_the_persisted_artifacts(self):
        """No field may disagree with the evidence it summarizes."""
        self.assertEqual(self.derived, self.block)

    # ------------------------------------------------------------- identity
    def test_issue_decision_and_candidate_identity(self):
        self.assertEqual(self.block["issue"], ISSUE)
        self.assertEqual(self.block["issue"], self.decision["issue"])
        self.assertEqual(self.block["issue"], self.validation["issue"])
        self.assertEqual(self.block["issue"], self.preflight["issue"])

        self.assertEqual(self.block["decision"], DECISION_RETAIN)
        self.assertEqual(self.block["decision"], self.decision["decision"])
        self.assertEqual(self.block["decision"], self.validation["decision"])
        self.assertEqual(self.block["decision"], self.preflight["admission"]["admission_decision"])
        self.assertEqual(
            self.validation["outcome"],
            "RETAIN_ACTIVE_REFERENCE" if self.block["decision"] == DECISION_RETAIN else "ADMIT_CANDIDATE",
        )
        self.assertIn(
            self.block["decision"],
            {DECISION_ADMIT, DECISION_RETAIN},
            "the decision must be one of the two ticket values",
        )

        candidate_id = self.block["candidate_id"]
        candidate_sha = self.block["candidate_sha256"]
        self.assertEqual(candidate_id, "generalized-adverse-response-candidate-v1")
        self.assertEqual(candidate_id, self.decision["candidate"]["candidate_id"])
        self.assertEqual(candidate_id, self.manifest["candidate"]["candidate_id"])
        self.assertEqual(candidate_id, self.preflight["provider"]["candidate_id"])
        self.assertEqual(candidate_id, self.preflight["provider"]["audit"]["candidate_id"])
        self.assertEqual(candidate_sha, self.decision["candidate"]["canonical_payload_sha256"])
        self.assertEqual(candidate_sha, self.manifest["candidate"]["canonical_payload_sha256"])
        self.assertEqual(candidate_sha, self.preflight["provider"]["candidate_canonical_payload_sha256"])
        # The frozen #367 rule names the candidate by this exact digest.
        rule = self.protocol["issue367_rule"]
        self.assertTrue(
            any(candidate_sha in clause for clause in rule["authorized_when"]),
            "the #367 consumption rule must name the candidate digest the block reports",
        )

    def test_status_is_coherent_with_the_terminal_decision_and_integrity(self):
        self.assertIn(
            self.block["status"],
            {STATUS_READY, STATUS_BLOCKED, STATUS_NEEDS_FIXES},
            "the status must be one of the three ticket values",
        )
        self.assertEqual(
            self.artifacts["digest_verification"]["all_recomputed_digests_match_persisted"], True
        )
        # Not admitted + every recomputed digest matching => no integrity blocker.
        self.assertNotEqual(self.block["decision"], DECISION_ADMIT)
        self.assertFalse(self.decision["issue367_authorized"])
        self.assertEqual(self.block["status"], STATUS_BLOCKED)
        self.assertNotEqual(self.block["status"], STATUS_READY)
        self.assertEqual(self.block["status"], self.derived["status"])

    # ------------------------------------------------------------- coverage
    def test_coverage_fields_match_validation_result(self):
        coverage = self.validation["metrics"]["coverage"]
        self.assertEqual(self.block["validation_coverage"], coverage["coverage"])
        self.assertEqual(self.block["limper_vs_iso_coverage"], coverage["limiters_vs_iso"]["coverage"])
        self.assertEqual(self.block["ood_abstain_rate"], coverage["abstain_rate"])
        # Cross-artifact coherence with the terminal decision's own projection.
        decision_coverage = self.decision["metrics"]["coverage"]
        self.assertEqual(self.block["validation_coverage"], decision_coverage["total"])
        self.assertEqual(
            self.block["limper_vs_iso_coverage"], decision_coverage["limiters_vs_iso"]["coverage"]
        )
        self.assertEqual(self.block["ood_abstain_rate"], decision_coverage["abstain_rate"])
        # The abstention is the frozen OOD gate's fail-closed share, not a re-score.
        self.assertEqual(coverage["universe_rows"], coverage["answered_decisions"])
        self.assertEqual(coverage["ood_status_counts"]["MODEL_OOD_ABSTAIN"], 0)
        self.assertEqual(self.block["ood_abstain_rate"], 0.0)

    # ------------------------------------------------------------- gates
    def test_raise_sizing_gate_is_derived_from_the_frozen_criterion(self):
        self.assertEqual(self.protocol["sizing_criteria"]["criteria_id"], SIZING_CRITERIA_ID)
        self.assertEqual(
            self.block["raise_sizing_gate_passed"], sizing_gate_passed(self.sizing, self.protocol)
        )
        self.assertIs(self.block["raise_sizing_gate_passed"], True)
        # Tree-side coherence: the frozen frontiers close with zero fail-closed sizing.
        self.assertEqual(self.sizing["guarantees"]["frontiers_fail_closed"], 0)
        self.assertEqual(self.sizing["guarantees"]["frontiers_resolved"], 7)
        self.assertEqual(self.sizing["metrics"]["illegal_generated_rate"], 0.0)
        audit = self.preflight["direct_evaluation_audit"]
        self.assertEqual(audit["frontier_raise_sizing_resolved"], audit["frontiers_visited"])

    def test_issue367_preflight_gate_is_coherent_with_the_preflight(self):
        admission = self.preflight["admission"]
        expected = admission["authorized"] is True
        self.assertEqual(self.block["issue367_preflight_passed"], expected)
        self.assertEqual(
            admission["outcome"], "ADMITTED" if expected else "ABSTAIN_BLOCKED_ADMISSION"
        )
        self.assertIs(self.block["issue367_preflight_passed"], False)
        self.assertEqual(admission["consumption"], "FORBIDDEN")
        self.assertEqual(admission["validation_outcome"], self.validation["outcome"])
        self.assertEqual(admission["criteria_passed"], self.decision["criteria_passed"])
        self.assertEqual(admission["failed_gates"], self.decision["failed_gates"])

    # ------------------------------------------------------------- boundaries
    def test_boundaries_and_successor_are_pinned(self):
        self.assertIs(self.block["test_consumed"], False)
        self.assertIs(self.block["active_pointer_mutated"], False)
        self.assertEqual(self.block["next_issue"], NEXT_ISSUE)

        # VALIDATION was consumed exactly once by the frozen read; TEST was never opened.
        self.assertIs(self.block["validation_consumed"], True)
        self.assertIs(self.decision["validation_consumed"], True)
        self.assertIs(self.validation["test_consumed"], False)
        self.assertIs(self.validation["split_opened"], True)
        self.assertEqual(self.validation["validation_reads"], 1)

        self.assertIs(self.decision["test_consumed"], False)
        self.assertIs(self.decision["test_authorized"], False)
        self.assertIs(self.decision["active_pointer_mutated"], False)
        self.assertIs(self.decision["active_model_pointer_mutation"], False)
        self.assertIs(self.artifacts["boundary"]["test_consumed"], False)
        self.assertIs(self.artifacts["boundary"]["active_pointer_mutated"], False)
        self.assertIs(self.artifacts["boundary"]["issue367_executed"], False)

    def test_issue367_was_not_executed_in_this_run(self):
        boundary = self.preflight["boundary"]
        self.assertIs(boundary["issue367_executed"], False)
        self.assertIs(boundary["hero_ev_executed"], False)
        self.assertIs(boundary["hero_ev_runner_imported"], False)
        self.assertEqual(boundary["rollouts_executed"], 0)
        self.assertEqual(boundary["ev_values_computed"], 0)
        self.assertIs(boundary["recommendation_computed"], False)
        self.assertIs(boundary["test_consumed"], False)
        self.assertIs(boundary["active_model_pointer_mutated"], False)
        # The block announces #367 as the successor without authorizing it.
        self.assertEqual(self.block["next_issue"], NEXT_ISSUE)
        self.assertIs(self.block["issue367_preflight_passed"], False)


if __name__ == "__main__":
    unittest.main()
