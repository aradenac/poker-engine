#!/usr/bin/env python3
"""#423 -- the n8n output block (``N8N_TASK_RESULT``).

``analysis/issue423_hybrid_router/N8N_TASK_RESULT.json`` is the *output* of the
#423 cycle: a strict, read-only projection of the already-persisted,
content-addressed terminal evidence.  Nothing here re-opens VALIDATION or TEST
and nothing is re-scored: every value is a published row of

* ``DECISION.json`` (the terminal outcome, its global deltas, the OOD gate and
  the frozen boundaries),
* ``TRAIN_CV_ROUTER_REPORT.json`` (the cross-fitted TRAIN log-loss deltas, the
  sparse pooled delta, the calibrated sparse ECE and the OOD abstention rate),
* ``SPARSE_STRATA_COMPARISON.json`` (the sparse pooled ECE and the routed
  system identity),
* ``ROUTER_MANIFEST.json`` (the frozen router definition digest),
* ``ISSUE367_PREFLIGHT.json`` (the #367 admission gate and its boundaries),
* ``ARTIFACTS.json`` (evidence integrity and the boundary block).

The ticket block is exactly fourteen fields: ``issue``, ``status``,
``decision``, ``router_id``, ``router_sha256``, ``global_cv_delta_log_loss``,
``sparse_cv_delta_log_loss``, ``sparse_calibration_ece``, ``ood_abstain_rate``,
``issue367_preflight_passed``, ``validation_reopened``, ``test_consumed``,
``active_pointer_mutated`` and ``next_issue``.

The guard re-derives the whole block from those persisted artifacts and fails
closed on any drift, so the block can never silently disagree with the decision
it summarizes.  It also pins the three non-negotiable boundaries
(``test_consumed=false``, ``active_pointer_mutated=false``,
``validation_reopened=false``), the successor (``next_issue=367``) and the fact
that #367 was *not* executed in this run.

Identity convention (mirrors the #419/#421 blocks).  ``router_id`` is the
routed system's own identifier as published in the evidence -- the hybrid
channel's ``model_id`` (``TRAIN_CV_ROUTER_REPORT.json::models.hybrid_router`` and
``SPARSE_STRATA_COMPARISON.json::by_stratum[*].models.hybrid_router``) -- and
``router_sha256`` is the byte SHA256 of that router's *frozen definition*, the
frozen spec ``HYBRID_ROUTER_SPEC.json``, which the manifest, the terminal
report and the terminal decision all pin to the same digest.  No field is
recomputed outside the persisted evidence; the only derived value is ``status``,
which is folded from the terminal outcome and the bundle's digest integrity.

``pytest`` is not a declared dependency of this repository; the suite is a plain
``unittest`` module, run with ``python3 -m unittest`` like its siblings.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BUNDLE = ROOT / "analysis/issue423_hybrid_router"
N8N_PATH = BUNDLE / "N8N_TASK_RESULT.json"
DECISION_PATH = BUNDLE / "DECISION.json"
REPORT_PATH = BUNDLE / "TRAIN_CV_ROUTER_REPORT.json"
SPARSE_PATH = BUNDLE / "SPARSE_STRATA_COMPARISON.json"
MANIFEST_PATH = BUNDLE / "ROUTER_MANIFEST.json"
PREFLIGHT_PATH = BUNDLE / "ISSUE367_PREFLIGHT.json"
ARTIFACTS_PATH = BUNDLE / "ARTIFACTS.json"

ISSUE = 423
NEXT_ISSUE = 367

#: The exact terminal vocabulary the ticket pins.
STATUS_READY = "READY_FOR_INTEGRATION"
STATUS_BLOCKED = "BLOCKED_SCIENTIFIC"
STATUS_NEEDS_FIXES = "NEEDS_FIXES"
DECISION_ADMIT = "ADMIT_HYBRID_ROUTER_FOR_ANALYSIS"
DECISION_RETAIN = "RETAIN_REFERENCE_HYBRID_INSUFFICIENT"
DECISION_VALUES = (DECISION_ADMIT, DECISION_RETAIN)

#: The exact field set of the ticket block -- no more, no less.
FIELDS = (
    "issue",
    "status",
    "decision",
    "router_id",
    "router_sha256",
    "global_cv_delta_log_loss",
    "sparse_cv_delta_log_loss",
    "sparse_calibration_ece",
    "ood_abstain_rate",
    "issue367_preflight_passed",
    "validation_reopened",
    "test_consumed",
    "active_pointer_mutated",
    "next_issue",
)

#: The global non-inferiority delta the block reports: the routed system minus
#: the retained active Model A reference, by ``hand_id``.
GLOBAL_DELTA_KEY = "hybrid_router_minus_active_model_a"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def classify_status(decision: dict, artifacts: dict) -> str:
    """Fold the terminal outcome and the bundle integrity into the ticket status.

    ``READY_FOR_INTEGRATION`` only when the terminal outcome admits the router
    for analysis; otherwise ``BLOCKED_SCIENTIFIC`` when every persisted digest
    still matches, and ``NEEDS_FIXES`` when the bundle itself is corrupt.
    """
    integrity_ok = (
        artifacts["digest_verification"]["all_recomputed_digests_match_persisted"] is True
    )
    admitted = (
        decision["decision"] == DECISION_ADMIT
        and decision["issue367"]["authorized"] is True
    )
    if admitted:
        return STATUS_READY
    return STATUS_BLOCKED if integrity_ok else STATUS_NEEDS_FIXES


def derive_block() -> dict:
    """Re-derive the whole n8n block from the persisted, content-addressed evidence."""
    decision = load(DECISION_PATH)
    report = load(REPORT_PATH)
    sparse = load(SPARSE_PATH)
    manifest = load(MANIFEST_PATH)
    preflight = load(PREFLIGHT_PATH)
    artifacts = load(ARTIFACTS_PATH)

    return {
        "issue": decision["issue"],
        "status": classify_status(decision, artifacts),
        "decision": decision["decision"],
        "router_id": report["models"]["hybrid_router"]["model_id"],
        "router_sha256": manifest["frozen_spec"]["sha256"],
        "global_cv_delta_log_loss": decision["global_deltas"][GLOBAL_DELTA_KEY],
        "sparse_cv_delta_log_loss": report["deltas"]["sparse_log_loss_bits_per_decision"][
            "paired_hybrid_minus_active"
        ],
        "sparse_calibration_ece": sparse["pooled"]["hybrid_ece"],
        "ood_abstain_rate": decision["ood_gate"]["synthetic_probes"]["abstain_rate"],
        "issue367_preflight_passed": preflight["issue367_preflight_passed"],
        "validation_reopened": decision["boundaries"]["validation_reopened"],
        "test_consumed": decision["boundaries"]["test_consumed"],
        "active_pointer_mutated": decision["boundaries"]["active_pointer_mutated"],
        "next_issue": NEXT_ISSUE,
    }


class Issue423N8nResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.block = load(N8N_PATH)
        cls.derived = derive_block()
        cls.decision = load(DECISION_PATH)
        cls.report = load(REPORT_PATH)
        cls.sparse = load(SPARSE_PATH)
        cls.manifest = load(MANIFEST_PATH)
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
        self.assertIsInstance(self.block["status"], str)
        self.assertIsInstance(self.block["decision"], str)
        self.assertIsInstance(self.block["router_id"], str)
        self.assertIsInstance(self.block["router_sha256"], str)
        self.assertIsInstance(self.block["issue367_preflight_passed"], bool)
        self.assertIsInstance(self.block["validation_reopened"], bool)
        self.assertIsInstance(self.block["test_consumed"], bool)
        self.assertIsInstance(self.block["active_pointer_mutated"], bool)
        self.assertIsInstance(self.block["global_cv_delta_log_loss"], float)
        self.assertIsInstance(self.block["sparse_cv_delta_log_loss"], float)
        self.assertIsInstance(self.block["sparse_calibration_ece"], float)
        self.assertIsInstance(self.block["ood_abstain_rate"], float)
        # The router digest is a bare lowercase SHA256, never a canonical-payload tag.
        self.assertEqual(len(self.block["router_sha256"]), 64)
        self.assertEqual(self.block["router_sha256"], self.block["router_sha256"].lower())
        int(self.block["router_sha256"], 16)

    def test_block_is_the_derived_projection_of_the_persisted_artifacts(self):
        """No field may disagree with the evidence it summarizes."""
        self.assertEqual(self.derived, self.block)

    # ------------------------------------------------------------- identity
    def test_issue_and_decision_identity(self):
        self.assertEqual(self.block["issue"], ISSUE)
        self.assertEqual(self.block["issue"], self.decision["issue"])
        self.assertEqual(self.block["issue"], self.report["issue"])
        self.assertEqual(self.block["issue"], self.sparse["issue"])
        self.assertEqual(self.block["issue"], self.manifest["issue"])
        self.assertEqual(self.block["issue"], self.preflight["issue"])
        self.assertEqual(self.block["issue"], self.artifacts["issue"])

        self.assertEqual(self.block["decision"], DECISION_RETAIN)
        self.assertIn(self.block["decision"], DECISION_VALUES, "the decision must be one of the two ticket values")
        self.assertEqual(self.block["decision"], self.decision["decision"])
        self.assertEqual(self.block["decision"], self.decision["protocol_outcome"])
        self.assertEqual(self.block["decision"], self.decision["issue367"]["terminal_outcome"])
        self.assertEqual(self.block["decision"], self.report["outcome"])
        self.assertEqual(self.block["decision"], self.report["criteria_evaluation"]["outcome"])
        self.assertEqual(self.block["decision"], self.sparse["outcome"])
        self.assertEqual(self.block["decision"], self.preflight["admission"]["terminal_outcome"])
        self.assertEqual(self.block["decision"], self.artifacts["terminal_decision"]["decision"])
        self.assertEqual(self.artifacts["terminal_decision"]["actual_terminal_outcome"], self.block["decision"])

    def test_router_identity_is_pinned_across_the_evidence(self):
        router_id = self.block["router_id"]
        router_sha = self.block["router_sha256"]

        # The routed system's own identifier: the hybrid channel's model_id.
        self.assertEqual(router_id, "hybrid_router")
        self.assertEqual(router_id, self.report["models"]["hybrid_router"]["model_id"])
        self.assertEqual(router_id, self.decision["channels"][-1])
        self.assertIn(router_id, self.decision["channels"])
        for stratum, block in self.sparse["by_stratum"].items():
            with self.subTest(stratum=stratum):
                self.assertEqual(router_id, block["models"]["hybrid_router"]["model_id"])
        # The routed channel is published under that identity in the terminal
        # report across its four frozen strata.
        self.assertEqual(
            sorted(self.report["models"]["hybrid_router"]["by_stratum"]),
            ["exact_absent_in_domain", "exact_absent_out_of_domain", "frequent_exact", "rare_exact"],
        )

        # The frozen definition digest: the frozen router spec, bound identically
        # in the manifest, the terminal report and the terminal decision.
        spec_path = "analysis/issue423_hybrid_router/HYBRID_ROUTER_SPEC.json"
        self.assertEqual(self.manifest["frozen_spec"]["path"], spec_path)
        self.assertEqual(self.manifest["frozen_spec"]["sha256"], router_sha)
        self.assertEqual(self.report["frozen_spec"]["path"], spec_path)
        self.assertEqual(self.report["frozen_spec"]["sha256"], router_sha)
        self.assertEqual(self.decision["frozen_criteria"]["spec_path"], spec_path)
        self.assertEqual(self.decision["frozen_criteria"]["spec_sha256"], router_sha)
        self.assertEqual(self.preflight["provider"]["spec"]["sha256"], router_sha)
        self.assertEqual(self.preflight["evidence_bindings"]["spec_byte_sha256"], router_sha)
        self.assertEqual(
            self.artifacts["artifacts"]["HYBRID_ROUTER_SPEC.json"]["sha256"], router_sha
        )
        self.assertEqual(
            self.artifacts["evidence_bindings"]["HYBRID_ROUTER_SPEC.json"]["sha256"], router_sha
        )
        # The manifest is the criteria manifest for that same frozen spec.
        self.assertEqual(
            self.manifest["frozen_criteria"]["procedure_reference"]["spec"], spec_path
        )
        self.assertEqual(self.manifest["frozen_spec"]["canonical_payload_sha256"], self.report["frozen_spec"]["canonical_payload_sha256"])

    # ------------------------------------------------------------- deltas
    def test_global_cv_delta_matches_the_terminal_report_and_decision(self):
        # The block never recomputes the delta: it is the persisted global
        # non-inferiority point estimate, router minus active Model A.
        persisted = self.decision["global_deltas"][GLOBAL_DELTA_KEY]
        self.assertEqual(self.report["deltas"]["global_log_loss_bits_per_decision"][GLOBAL_DELTA_KEY], persisted)
        self.assertEqual(self.block["global_cv_delta_log_loss"], persisted)
        self.assertEqual(self.block["global_cv_delta_log_loss"], -0.004301)
        # The paired comparison mirrors the same point estimate.
        paired = self.decision["paired"][GLOBAL_DELTA_KEY]
        self.assertEqual(paired["left"], "hybrid_router")
        self.assertEqual(paired["right"], "active_model_a")
        self.assertEqual(paired["global"]["point_estimate_bits_per_decision"], persisted)

    def test_sparse_cv_delta_and_ece_match_the_sparse_comparison_and_report(self):
        # Sparse delta: the pooled paired log-loss delta of the hybrid channel
        # against the active reference, over the two sparse strata.
        sparse_delta = self.report["deltas"]["sparse_log_loss_bits_per_decision"][
            "paired_hybrid_minus_active"
        ]
        self.assertEqual(self.block["sparse_cv_delta_log_loss"], sparse_delta)
        self.assertEqual(self.block["sparse_cv_delta_log_loss"], -0.031234)
        self.assertEqual(
            self.report["deltas"]["sparse_log_loss_bits_per_decision"]["strata"],
            ["rare_exact", "exact_absent_in_domain"],
        )
        self.assertEqual(
            sorted(self.sparse["by_stratum"]),
            ["exact_absent_in_domain", "rare_exact"],
        )

        # Sparse calibration ECE: the support-weighted pooled hybrid ECE the
        # frozen SPARSE_ECE_CEILING criterion reads.
        pooled_ece = self.sparse["pooled"]["hybrid_ece"]
        self.assertEqual(self.block["sparse_calibration_ece"], pooled_ece)
        self.assertEqual(
            self.report["deltas"]["sparse_log_loss_bits_per_decision"]["hybrid_ece"], pooled_ece
        )
        self.assertEqual(self.block["sparse_calibration_ece"], 0.027507)
        # It is the hybrid ECE, not the active reference's, and the ceiling it
        # misses is the frozen one -- the single failed criterion.
        self.assertEqual(self.sparse["pooled"]["active_ece"], 0.042629)
        self.assertNotEqual(self.block["sparse_calibration_ece"], self.sparse["pooled"]["active_ece"])
        ceiling = self.sparse["pooled"]["criteria"]["SPARSE_ECE_CEILING"]
        self.assertEqual(ceiling["id"], "SPARSE_ECE_CEILING")
        self.assertEqual(ceiling["threshold"], 0.02)
        self.assertIs(ceiling["passed"], False)
        self.assertGreater(self.block["sparse_calibration_ece"], ceiling["threshold"])
        self.assertEqual(self.decision["failed_criteria"], ["SPARSE_ECE_CEILING"])

    def test_ood_abstain_rate_is_the_frozen_gate_rate(self):
        rate = self.block["ood_abstain_rate"]
        self.assertEqual(rate, 1.0)
        self.assertEqual(rate, self.decision["ood_gate"]["synthetic_probes"]["abstain_rate"])
        self.assertEqual(rate, self.report["ood"]["abstain_rate"])
        self.assertEqual(rate, self.report["ood_synthetic_probes"]["abstain_rate"])
        self.assertEqual(
            rate, self.decision["ood_gate"]["channel_abstention_on_probes"]["hybrid_router"]["abstain_rate"]
        )
        # The gate fails closed on the synthetic probe surface: complete abstention.
        self.assertEqual(rate, self.decision["ood_gate"]["required_abstention_rate_on_synthetic_ood_probes"])
        self.assertEqual(self.report["ood"]["coverage"], 0.0)
        self.assertEqual(
            self.report["ood_synthetic_probes"]["router_abstained"],
            self.report["ood_synthetic_probes"]["n"],
        )
        self.assertIs(self.report["ood_synthetic_probes"]["assertions"]["router_abstains_on_every_probe"], True)

    # ------------------------------------------------------------- status
    def test_status_is_coherent_with_the_terminal_decision_and_integrity(self):
        self.assertIn(
            self.block["status"],
            {STATUS_READY, STATUS_BLOCKED, STATUS_NEEDS_FIXES},
            "the status must be one of the three ticket values",
        )
        self.assertIs(
            self.artifacts["digest_verification"]["all_recomputed_digests_match_persisted"], True
        )
        # Not admitted + every recomputed digest matching => no integrity blocker.
        self.assertNotEqual(self.block["decision"], DECISION_ADMIT)
        self.assertIs(self.decision["issue367"]["authorized"], False)
        self.assertEqual(self.block["status"], STATUS_BLOCKED)
        self.assertNotEqual(self.block["status"], STATUS_READY)
        self.assertEqual(self.block["status"], classify_status(self.decision, self.artifacts))
        self.assertEqual(self.block["status"], self.derived["status"])

    # ------------------------------------------------------------- gates
    def test_issue367_preflight_gate_is_coherent_with_the_preflight(self):
        admission = self.preflight["admission"]
        expected = admission["issue367_authorized"] is True
        self.assertEqual(self.block["issue367_preflight_passed"], expected)
        self.assertEqual(self.block["issue367_preflight_passed"], self.preflight["issue367_preflight_passed"])
        self.assertEqual(
            self.block["issue367_preflight_passed"],
            self.preflight["issue367_preflight_passed_derivation"]["issue367_preflight_passed"],
        )
        self.assertEqual(self.block["issue367_preflight_passed"], self.decision["issue367"]["preflight_passed"])
        self.assertIs(self.block["issue367_preflight_passed"], False)
        self.assertEqual(
            admission["outcome"], "ADMITTED" if expected else "ABSTAIN_BLOCKED_ADMISSION"
        )
        self.assertEqual(admission["consumption"], "FORBIDDEN")
        self.assertEqual(admission["criteria_passed"], self.decision["criteria_passed"])
        self.assertEqual(admission["criteria_total"], self.decision["criteria_total"])
        self.assertEqual(admission["criteria_failed"], self.decision["failed_criteria"])
        # The preflight walkthrough itself passed; the *admission* gate did not,
        # because the terminal outcome retains the reference.
        self.assertIs(self.preflight["walkthrough"]["preflight_passed"], True)
        self.assertIs(
            self.preflight["issue367_preflight_passed_derivation"]["terms"]["terminal_outcome_admits"],
            False,
        )

    # ------------------------------------------------------------- boundaries
    def test_boundaries_and_successor_are_pinned(self):
        self.assertIs(self.block["test_consumed"], False)
        self.assertIs(self.block["active_pointer_mutated"], False)
        self.assertIs(self.block["validation_reopened"], False)
        self.assertEqual(self.block["next_issue"], NEXT_ISSUE)

        # The sources back every pinned boundary; a flipped bound fails here.
        self.assertIs(self.decision["boundaries"]["test_consumed"], False)
        self.assertIs(self.decision["boundaries"]["test_authorized"], False)
        self.assertIs(self.decision["boundaries"]["active_pointer_mutated"], False)
        self.assertIs(self.decision["boundaries"]["active_model_pointer_mutation"], False)
        self.assertIs(self.decision["boundaries"]["validation_reopened"], False)
        self.assertIs(self.decision["boundaries"]["validation_consumed"], False)
        self.assertEqual(self.decision["boundaries"]["split"], "TRAIN")
        self.assertEqual(self.decision["boundaries"]["consumed_splits"], ["TRAIN"])
        self.assertEqual(self.decision["boundaries"]["refused_splits"], ["VALIDATION", "TEST"])

        self.assertIs(self.artifacts["boundary"]["test_consumed"], False)
        self.assertIs(self.artifacts["boundary"]["active_pointer_mutated"], False)
        self.assertIs(self.artifacts["boundary"]["validation_reopened"], False)
        self.assertIs(self.artifacts["boundary"]["issue367_executed"], False)
        self.assertEqual(self.artifacts["boundary"]["next_issue"], NEXT_ISSUE)
        self.assertEqual(self.decision["next_issue"], NEXT_ISSUE)
        self.assertEqual(self.artifacts["terminal_decision"]["next_issue"], NEXT_ISSUE)

        # The frozen report consumed no holdout either.
        self.assertIs(self.report["assertions"]["test_never_read"], True)
        self.assertIs(self.report["assertions"]["validation_never_read"], True)
        self.assertIs(self.report["guards"]["test_consumed"], False)
        self.assertIs(self.report["guards"]["validation_consumed"], False)
        self.assertEqual(self.report["scope"]["split"], "TRAIN")

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
        self.assertIs(boundary["validation_split_consumed"], False)
        # The block announces #367 as the successor without authorizing it.
        self.assertEqual(self.block["next_issue"], NEXT_ISSUE)
        self.assertEqual(self.decision["next_issue_status"], "NOT_EXECUTED")
        self.assertIs(self.block["issue367_preflight_passed"], False)
        self.assertIs(self.artifacts["boundary"]["issue367_executed"], False)


if __name__ == "__main__":
    unittest.main()
