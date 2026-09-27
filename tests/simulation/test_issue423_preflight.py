#!/usr/bin/env python3
"""#423 -> #367 preflight regressions (no Hero EV, no TEST, no nearest lookup).

The preflight walks the 38 required nodes of the scenario #321 response tree
plus its 7 frozen raise-sizing frontiers, queries the #423 T7 hybrid runtime
provider *directly* at each decision's exact public context and records the
router's chosen source, the requested context, the distribution, the support,
the uncertainty, the frozen OOD status and the declared sizing source.

These tests pin the contract:

* the preflight runs even when the admission is refused and states, explicitly,
  that no Hero EV was computed and that #367 was not launched;
* every visited decision is either ``DIRECT_EVAL`` or ``EXPLICIT_ABSTAIN``, and
  a negative test proves a neighbour substitution is refused with the stable
  code ``NEAREST_NEIGHBOUR_SUBSTITUTION_REFUSED``;
* ``issue367_preflight_passed`` is derived mechanically from the terminal
  outcome and the frozen OOD rule -- true only when the terminal outcome admits
  the router, the walkthrough is analysis-admissible and the structural
  preflight passed;
* a significant OOD branch stays blocking: it carries ``analysis_admissible``
  false, no distribution and no sizing, and is never rescued by a neighbour;
* TEST stays unconsumed, the active pointer is untouched and the whole document
  is byte-reproducible.

``pytest`` is not a declared dependency of this repository; the suite is a plain
``unittest`` module, run with ``python3 -m unittest`` like its siblings.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop import hybrid_response_router as router  # noqa: E402
from tools.preflop import hybrid_response_runtime as runtime_provider  # noqa: E402
from tools.simulation import issue423_issue367_preflight as preflight_tool  # noqa: E402

#: The #421 candidate identity the calibrated channel answers with.  The router
#: reports it with underscores in ``model_id`` and as the frozen candidate id
#: (dashes) in the channel cell; both name the same candidate.
CANDIDATE_ID = "generalized-adverse-response-candidate-v1"


class Issue423Issue367PreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = preflight_tool.OUTPUT_DIR
        cls.document, cls.summary = preflight_tool.build()
        if not (cls.output / preflight_tool.NAME).is_file():
            preflight_tool.persist(cls.document)
        cls.persisted = json.loads((cls.output / preflight_tool.NAME).read_text())
        cls.tree = json.loads(preflight_tool.REQUIRED_TREE_PATH.read_text())
        cls.tree_nodes = {str(node["id"]): node for node in cls.tree["nodes"]}
        cls.frontiers = json.loads(
            preflight_tool.model.FRONTIER_RESOLUTION_PATH.read_text()
        )
        cls.terminal = json.loads(preflight_tool.TERMINAL_REPORT_PATH.read_text())

    # ------------------------------------------------------------- artifact
    def test_persisted_preflight_is_content_addressed_and_check_passes(self):
        payload = (self.output / preflight_tool.NAME).read_bytes()
        self.assertEqual(payload, preflight_tool.serialize(self.persisted))
        sidecar = (self.output / preflight_tool.SIDECAR_NAME).read_text().splitlines()
        self.assertEqual(
            sidecar[0], f"{hashlib.sha256(payload).hexdigest()}  {preflight_tool.NAME}"
        )
        self.assertEqual(
            sidecar[1],
            f"# canonical_payload_sha256 {preflight_tool.canonical_sha256(self.persisted)}",
        )
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(preflight_tool.check(), 0)
        self.assertEqual(json.loads(stream.getvalue())["check"], "PASS")

    def test_check_detects_drift_in_the_persisted_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)
            with mock.patch.object(preflight_tool, "OUTPUT_DIR", scratch):
                preflight_tool.persist(self.document)
                stream = io.StringIO()
                with contextlib.redirect_stdout(stream):
                    self.assertEqual(preflight_tool.check(), 0)
                tampered = json.loads((scratch / preflight_tool.NAME).read_text())
                tampered["issue367_preflight_passed"] = True
                (scratch / preflight_tool.NAME).write_text(
                    json.dumps(tampered, sort_keys=True, indent=2) + "\n", encoding="utf-8"
                )
                stream = io.StringIO()
                with contextlib.redirect_stderr(stream):
                    self.assertEqual(preflight_tool.check(), 1)
                self.assertIn("differs from a fresh preflight", stream.getvalue())
            # The committed artifact was never touched.
            self.assertEqual(
                (self.output / preflight_tool.NAME).read_bytes(),
                preflight_tool.serialize(self.persisted),
            )

    def test_document_identity_and_scenario_binding(self):
        self.assertEqual(self.document["schema"], preflight_tool.SCHEMA)
        self.assertEqual(self.document["kind"], "ISSUE367_PREFLIGHT")
        self.assertEqual(self.document["issue"], 423)
        self.assertEqual(self.document["source_issue"], 367)
        self.assertEqual(self.document["scenario_issue"], 321)
        self.assertEqual(self.document["scenario_id"], preflight_tool.SCENARIO_ID)
        scenario = self.document["scenario"]
        self.assertEqual(scenario["root_path"], ["SB:ISO@5"])
        self.assertEqual(scenario["required_node_count"], 38)
        self.assertEqual(scenario["unresolved_sizing_frontier_count"], 7)
        self.assertEqual(
            scenario["fixture_sha256"], preflight_tool.sha256_file(preflight_tool.FIXTURE_PATH)
        )
        bindings = self.document["evidence_bindings"]
        for key, path in (
            ("preflight_tool_sha256", preflight_tool.SOURCE_PATH),
            ("runtime_module_sha256", preflight_tool.RUNTIME_MODULE_PATH),
            ("router_module_sha256", preflight_tool.ROUTER_MODULE_PATH),
            ("spec_byte_sha256", preflight_tool.SPEC_PATH),
            ("manifest_byte_sha256", preflight_tool.MANIFEST_PATH),
            ("calibration_report_sha256", preflight_tool.CALIBRATION_REPORT_PATH),
            ("terminal_report_sha256", preflight_tool.TERMINAL_REPORT_PATH),
            ("required_tree_sha256", preflight_tool.REQUIRED_TREE_PATH),
            ("fixture_sha256", preflight_tool.FIXTURE_PATH),
            (
                "frontier_resolution_sha256",
                preflight_tool.model.FRONTIER_RESOLUTION_PATH,
            ),
        ):
            with self.subTest(binding=key):
                self.assertEqual(bindings[key], preflight_tool.sha256_file(path))

    # ------------------------------------------------------------- admission
    def test_preflight_runs_even_when_the_admission_is_refused(self):
        admission = self.document["admission"]
        evaluation = self.terminal["criteria_evaluation"]
        # The walkthrough is executed regardless of the admission outcome.
        self.assertEqual(self.document["nodes_queried"], 38)
        self.assertEqual(self.document["sizing_frontiers_queried"], 7)
        self.assertEqual(self.document["walkthrough"]["decisions_visited"], 45)
        # The frozen terminal report is read as evidence, never re-derived.
        self.assertEqual(admission["terminal_outcome"], self.terminal["outcome"])
        self.assertEqual(admission["outcome_rule"], evaluation["outcome_rule"])
        self.assertEqual(admission["criteria_failed"], list(evaluation["failed"]))
        self.assertEqual(
            admission["issue367_authorized"],
            preflight_tool.terminal_outcome_admits(
                preflight_tool.load_terminal_report(preflight_tool.load_frozen_spec())
            ),
        )
        if admission["issue367_authorized"]:
            self.assertEqual(admission["consumption"], "AUTHORIZED")
            self.assertIsNone(admission["abstention"])
            self.assertEqual(admission["blocking_reasons"], [])
        else:
            self.assertFalse(admission["issue367_authorized"])
            self.assertEqual(admission["consumption"], "FORBIDDEN")
            self.assertEqual(admission["outcome"], "ABSTAIN_BLOCKED_ADMISSION")
            self.assertIn(
                f"terminal router outcome is {self.terminal['outcome']}",
                admission["blocking_reasons"],
            )
            for name in evaluation["failed"]:
                self.assertIn(f"failed frozen criterion: {name}", admission["blocking_reasons"])
            abstention = admission["abstention"]
            self.assertEqual(abstention["code"], "ISSUE367_ADMISSION_NOT_GRANTED")
            self.assertEqual(abstention["rule_id"], preflight_tool.ISSUE367_RULE_ID)
            for flag in ("hero_ev_consumed", "test_consumed", "active_model_pointer_mutation",
                         "promotion_performed"):
                self.assertFalse(abstention[flag], flag)
        # This workspace carries a retention, and the artifact says so.
        self.assertEqual(self.terminal["outcome"], preflight_tool.RETAINING_OUTCOME)
        self.assertFalse(self.document["issue367_preflight_passed"])
        self.assertIn(preflight_tool.ADMITTING_OUTCOME, admission["outcome_rule_verbatim"])

    def test_terminal_outcome_admits_only_a_fully_passing_admit(self):
        report = preflight_tool.load_terminal_report(preflight_tool.load_frozen_spec())
        self.assertFalse(preflight_tool.terminal_outcome_admits(report))
        admitted = json.loads(json.dumps(report))
        admitted["outcome"] = preflight_tool.ADMITTING_OUTCOME
        admitted["document"]["criteria_evaluation"]["all_passed"] = True
        admitted["document"]["criteria_evaluation"]["failed"] = []
        self.assertTrue(preflight_tool.terminal_outcome_admits(admitted))
        # An outcome that disagrees with the frozen criteria is refused.
        refused = json.loads(json.dumps(admitted))
        refused["outcome"] = preflight_tool.RETAINING_OUTCOME
        self.assertFalse(preflight_tool.terminal_outcome_admits(refused))
        # An outcome that contradicts the persisted criteria is refused on load,
        # and a stale sidecar is refused before the document is even parsed.
        spec = preflight_tool.load_frozen_spec()
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)
            inconsistent = scratch / "TRAIN_CV_ROUTER_REPORT.json"
            payload = json.loads(preflight_tool.TERMINAL_REPORT_PATH.read_text())
            payload["outcome"] = preflight_tool.ADMITTING_OUTCOME
            inconsistent.write_text(json.dumps(payload), encoding="utf-8")
            good_sidecar = scratch / "good.sha256"
            good_sidecar.write_text(
                f"{preflight_tool.sha256_file(inconsistent)}  TRAIN_CV_ROUTER_REPORT.json\n",
                encoding="utf-8",
            )
            with mock.patch.object(preflight_tool, "TERMINAL_REPORT_PATH", inconsistent), \
                    mock.patch.object(preflight_tool, "TERMINAL_REPORT_SIDECAR", good_sidecar):
                with self.assertRaises(preflight_tool.PreflightError):
                    preflight_tool.load_terminal_report(spec)
            stale_sidecar = scratch / "stale.sha256"
            stale_sidecar.write_text("0" * 64 + "  TRAIN_CV_ROUTER_REPORT.json\n", encoding="utf-8")
            with mock.patch.object(preflight_tool, "TERMINAL_REPORT_PATH", inconsistent), \
                    mock.patch.object(preflight_tool, "TERMINAL_REPORT_SIDECAR", stale_sidecar):
                with self.assertRaises(preflight_tool.PreflightError):
                    preflight_tool.load_terminal_report(spec)

    # ------------------------------------------------------------ walkthrough
    def test_walks_every_required_node_and_sizing_frontier(self):
        nodes = self.document["nodes"]
        self.assertEqual(self.document["nodes_queried"], 38)
        self.assertEqual(len(nodes), 38)
        self.assertEqual(self.document["sizing_frontiers_queried"], 7)
        self.assertEqual(len(self.document["sizing_frontiers"]), 7)
        seen_paths = set()
        for index, record in enumerate(nodes):
            identity = record["node_identity"]
            source = self.tree_nodes[identity["node_id"]]
            with self.subTest(node=identity["node_id"]):
                self.assertEqual(record["index"], index)
                self.assertEqual(identity["path"], list(source["path"]))
                self.assertEqual(identity["audit_exact_key"], source["audit_exact_key"])
                self.assertEqual(
                    identity["runtime_support_context_key"], source["runtime_support_context_key"]
                )
                self.assertEqual(
                    identity["runtime_exact_preflop_node_key"],
                    source["runtime_exact_preflop_node_key"],
                )
                self.assertEqual(record["requested_context"], source["context"])
                self.assertIn(
                    record["decision_class"], preflight_tool.DECISION_CLASSES
                )
                seen_paths.add(tuple(identity["path"]))
        self.assertEqual(len(seen_paths), 38)
        frontier_ids = {str(frontier["node_id"]) for frontier in self.frontiers["frontiers"]}
        for record in self.document["sizing_frontiers"]:
            with self.subTest(frontier=record["node_id"]):
                self.assertIn(record["node_id"], frontier_ids)
                self.assertEqual(record["action"], "RAISE")
                self.assertEqual(record["resolution_state"], "UNRESOLVED")
                self.assertEqual(record["exact_tree_status"], "UNRESOLVED")
                self.assertFalse(record["exact_tree_satisfied"])
                self.assertEqual(record["legal_target_interval_bb"], [9.0, 100.0])

    def test_every_visited_decision_is_direct_eval_or_explicit_abstain(self):
        walkthrough = self.document["walkthrough"]
        self.assertEqual(
            walkthrough["rule"], "EVERY_VISITED_DECISION_IS_DIRECT_EVAL_OR_EXPLICIT_ABSTAIN"
        )
        self.assertTrue(walkthrough["every_visited_decision_classified"])
        self.assertEqual(walkthrough["unclassified_decisions"], [])
        self.assertEqual(
            walkthrough["direct_eval_decisions"] + walkthrough["explicit_abstain_decisions"],
            walkthrough["decisions_visited"],
        )
        for record in self.document["nodes"] + self.document["sizing_frontiers"]:
            with self.subTest(path=record.get("path")):
                if record["decision_class"] == preflight_tool.DIRECT_EVAL:
                    self.assertIsNone(record["abstention"])
                    decision = record["decision"]
                    self.assertTrue(decision["analysis_admissible"])
                    self.assertFalse(decision["abstain"])
                    self.assertEqual(decision["fail_closed_reason"], None)
                    distribution = record["distribution"]
                    self.assertEqual(distribution["illegal_mass"], 0.0)
                    self.assertEqual(
                        sorted(distribution["probabilities"]),
                        sorted(preflight_tool.model.ACTIONS),
                    )
                    self.assertAlmostEqual(
                        sum(distribution["probabilities"].values()), 1.0, places=9
                    )
                    self.assertIsNotNone(record["uncertainty"])
                    self.assertIsNotNone(record["support"])
                    self.assertIsNotNone(record["ood_status"])
                    self.assertIsNotNone(record["sizing_source"])
                else:
                    self.assertIsNotNone(record["abstention"])
                    self.assertIsNone(record["abstention"]["selected_action"])
                    self.assertIsNone(record["abstention"]["sizing"])
                    self.assertFalse(record["ood_status"]["analysis_admissible"])

    def test_direct_eval_decisions_carry_the_router_source_and_a_sizing_source(self):
        for record in self.document["nodes"] + self.document["sizing_frontiers"]:
            if record["decision_class"] != preflight_tool.DIRECT_EVAL:
                continue
            with self.subTest(path=record.get("path")):
                self.assertIn(record["route_source"], router.ROUTE_SOURCES)
                self.assertNotEqual(record["route_source"], router.ROUTE_SOURCE_ABSTAIN)
                sizing = record["sizing_source"]
                self.assertFalse(sizing["nearest_price_substituted"])
                self.assertFalse(sizing["legal_minimum_fallback_substituted"])
                self.assertFalse(sizing["representative_price_substituted"])
                self.assertEqual(sizing["sizing_channel"], "calibrated_generalized_raise_sizing")
                conditional = sizing["conditional_raise"]
                self.assertTrue(conditional["available"])
                declaration = conditional["declaration"]
                self.assertEqual(
                    declaration["sizing_channel"], "calibrated_generalized_raise_sizing"
                )
                self.assertFalse(declaration["nearest_price_substituted"])
                self.assertFalse(declaration["nearest_context_substituted"])
        counts = self.document["walkthrough"]
        self.assertEqual(
            counts["route_source_counts"],
            {router.ROUTE_SOURCE_SPARSE: counts["direct_eval_decisions"]},
        )
        self.assertEqual(
            counts["support_state_counts"],
            {router.SUPPORT_STATE_SPARSE: counts["direct_eval_decisions"]},
        )
        self.assertEqual(
            sum(counts["uncertainty_counts"].values()), counts["direct_eval_decisions"]
        )
        self.assertEqual(
            counts["sizing_source_counts_conditional_raise_channel"],
            {"calibrated_generalized_raise_sizing": counts["decisions_visited"]},
        )

    def test_sparse_in_domain_branches_are_evaluated_through_the_generalized_channel(self):
        runtime = runtime_provider.load_runtime(None, None, None, None)
        sparse = [
            record
            for record in self.document["nodes"]
            if record["route_source"] == router.ROUTE_SOURCE_SPARSE
        ]
        self.assertEqual(len(sparse), self.document["nodes_queried"] - 1)
        for record in sparse[:5]:
            with self.subTest(path=record["node_identity"]["path"]):
                self.assertEqual(record["decision"]["model_id"], runtime_provider.GENERALIZED_MODEL_ID)
                self.assertEqual(record["decision"]["support_state"], router.SUPPORT_STATE_SPARSE)
                cell = record["support"]["channel_cell"]
                self.assertEqual(cell["candidate_id"], CANDIDATE_ID)
                self.assertEqual(
                    cell["candidate_id"].replace("-", "_"),
                    runtime_provider.GENERALIZED_MODEL_ID,
                )
                self.assertIn(
                    record["decision"]["status"],
                    (
                        runtime_provider.runtime.STATUS_RESOLVED,
                        runtime_provider.runtime.STATUS_HIGH_UNCERTAINTY,
                    ),
                )
        # The generalized channel is the #421 runtime the router delegates to.
        self.assertIsInstance(runtime.generalized, runtime_provider.runtime.GeneralizedResponseRuntime)

    def test_the_active_branch_requires_an_exact_active_cell(self):
        probe = self.document["nearest_lookup_audit"]["active_exact_cell_probe"]
        self.assertTrue(probe["passed"])
        self.assertEqual(probe["routed_source"], router.ROUTE_SOURCE_ACTIVE)
        self.assertFalse(probe["exact_active_cell_present"])
        self.assertTrue(probe["abstained"])
        self.assertEqual(
            probe["fail_closed_reason"], runtime_provider.FAIL_CLOSED_ACTIVE_CELL_UNAVAILABLE
        )
        self.assertTrue(probe["nearest_active_node_not_read"])
        blocking = {
            (row["kind"], row["code"]) for row in self.document["walkthrough"]["blocking_branches"]
        }
        self.assertIn(("node", runtime_provider.FAIL_CLOSED_ACTIVE_CELL_UNAVAILABLE), blocking)

    # ---------------------------------------------------------- substitutions
    def test_a_neighbour_substitution_request_is_refused(self):
        runtime = runtime_provider.load_runtime(None, None, None, None)
        root = self.tree_nodes[str(self.tree["root_id"])]
        context = preflight_tool.node_request_context(root)
        for key in ("allow_nearest_price", "allow_nearest_context", "allow_nearest_neighbour"):
            probe = dict(context)
            probe[key] = True
            with self.subTest(request_key=key):
                with self.assertRaises(runtime_provider.HybridResponseRuntimeError) as caught:
                    runtime.resolve(probe, strict=False)
                self.assertEqual(
                    caught.exception.code, runtime_provider.FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION
                )
        recorded = self.document["nearest_lookup_audit"]["request_refusal_probe"]
        self.assertTrue(recorded["passed"])
        self.assertEqual(
            recorded["expected_code"], runtime_provider.FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION
        )
        self.assertEqual(recorded["neighbours_refused"], len(recorded["attempts"]))
        for row in recorded["attempts"]:
            self.assertTrue(row["refused"])
            self.assertEqual(row["code"], runtime_provider.FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION)
            self.assertTrue(row["refused_before_any_decision"])

    def test_no_nearest_price_or_context_is_ever_substituted_in_the_document(self):
        audit = self.document["nearest_lookup_audit"]
        self.assertFalse(audit["nearest_price_substituted"])
        self.assertFalse(audit["nearest_context_substituted"])
        self.assertEqual(
            audit["substitution_classes_refused"], list(preflight_tool.SUBSTITUTION_CLASSES)
        )
        for probe in audit["probes"]:
            with self.subTest(probe=probe["probe"]):
                self.assertTrue(probe["passed"])
        self.assertEqual(
            audit["probes_passed"], all(probe["passed"] for probe in audit["probes"])
        )
        boundary = self.document["boundary"]
        self.assertFalse(boundary["nearest_price_substituted"])
        self.assertFalse(boundary["nearest_context_substituted"])
        for record in self.document["nodes"] + self.document["sizing_frontiers"]:
            if record["decision"] is None:
                continue
            with self.subTest(path=record.get("path")):
                decision = record["decision"]
                self.assertTrue(decision["no_nearest_price_substitution"])
                self.assertTrue(decision["no_nearest_context_substitution"])
                self.assertFalse(decision["nearest_price_substituted"])
                self.assertFalse(decision["nearest_context_substituted"])
        # The faced raise-to is never passed as a queried sizing: every misread
        # is refused by the runtime's own declared fail-closed vocabulary.
        guard = audit["faced_price_mapping_guard"]
        self.assertTrue(guard["misreading_is_not_used"])
        self.assertEqual(guard["misreading_would_answer_count"], 0)
        allowed_codes = {
            runtime_provider.FAIL_CLOSED_ACTIVE_CELL_UNAVAILABLE,
            runtime_provider.FAIL_CLOSED_ILLEGAL_SIZING_TARGET,
            runtime_provider.runtime.OOD_ABSTAIN_REASON,
        }
        for code, count in guard["misreading_refusal_codes"].items():
            with self.subTest(code=code):
                self.assertIn(code, allowed_codes)
                self.assertGreater(count, 0)
        self.assertEqual(
            sum(guard["misreading_refusal_codes"].values()),
            guard["misreading_would_abstain_count"],
        )

    def test_a_perturbed_request_is_recomputed_not_snapped_to_a_neighbour(self):
        runtime = runtime_provider.load_runtime(None, None, None, None)
        root = self.tree_nodes[str(self.tree["root_id"])]
        base = preflight_tool.node_request_context(root)
        exact = runtime.resolve(base, strict=False)
        shifted = dict(base)
        shifted["to_call_bb"] = float(base["to_call_bb"]) + 0.2
        perturbed = runtime.resolve(shifted, strict=False)
        self.assertNotEqual(
            exact["decision_canonical_sha256"], perturbed["decision_canonical_sha256"]
        )
        other = dict(base)
        other["family"] = "LIMPER_VS_ISO"
        other_document = runtime.resolve(other, strict=False)
        self.assertNotEqual(exact["context_key"], other_document["context_key"])
        self.assertNotEqual(
            exact["decision_canonical_sha256"], other_document["decision_canonical_sha256"]
        )

    # ------------------------------------------------------------ the OOD rule
    def test_ood_rule_is_quoted_verbatim_from_the_frozen_manifest(self):
        manifest = json.loads(preflight_tool.MANIFEST_PATH.read_text())
        rule = self.document["ood_rule"]
        row = next(
            item
            for item in manifest["frozen_criteria"]["criteria"]
            if item["id"] == preflight_tool.OOD_CRITERION_ID
        )
        self.assertEqual(rule["rule_id"], preflight_tool.OOD_CRITERION_ID)
        self.assertEqual(rule["criterion_verbatim"], row["criterion"])
        self.assertEqual(rule["derivation_rule_verbatim"], row["derivation_rule"])
        self.assertEqual(
            rule["required_abstention_rate_on_synthetic_ood_probes"], float(row["value"])
        )
        self.assertEqual(
            rule["mechanised_predicate"],
            "abstain(c) iff reasons(c) intersect OOD_HARD_REASONS is not empty",
        )
        self.assertTrue(rule["abstains_on_hard_reasons_only"])
        self.assertTrue(rule["hard_reason_codes_are_decisive"])
        self.assertTrue(rule["soft_reasons_may_only_raise_uncertainty"])
        self.assertEqual(
            rule["hard_reason_codes"], list(preflight_tool.model.OOD_HARD_REASONS)
        )
        self.assertIn("route_source != OOD_ABSTAIN", rule["analysis_admissibility_rule"])

    def test_a_significant_ood_branch_stays_blocking(self):
        guard = self.document["walkthrough"]
        self.assertTrue(guard["ood_branch_guard_passed"])
        self.assertTrue(guard["significant_ood_branch_is_blocking"])
        self.assertEqual(guard["significant_ood_branch_count"], 0)
        self.assertIn("OOD_ABSTENTION_CRITERION", self.document["ood_rule"]["rule_id"])
        probes = self._ood_probes()
        for row in probes["probes"]:
            with self.subTest(kind=row["kind"]):
                self.assertTrue(row["abstained"])
                self.assertFalse(row["analysis_admissible"])
                self.assertFalse(row["distribution_present"])
                self.assertIsNone(row["selected_action"])
                self.assertFalse(row["sizing_present"])
                self.assertTrue(row["expected_reason_present"])
                self.assertEqual(row["route_source"], router.ROUTE_SOURCE_ABSTAIN)
                self.assertFalse(row["nearest_price_substituted"])
                self.assertFalse(row["nearest_context_substituted"])
        # A visited branch flagged as a hard-reason OOD branch is blocking.
        synthetic_node = {
            "decision_class": preflight_tool.EXPLICIT_ABSTAIN,
            "node_identity": {"node_id": "x", "path": ["SB:ISO@5", "PROBE"]},
            "abstention": {
                "class": preflight_tool.OOD_BRANCH,
                "code": preflight_tool.OOD_CRITERION_ID,
                "hard_reasons": ["UNSEEN_CATEGORY"],
                "soft_reasons": [],
            },
            "decision": None,
        }
        synthetic_frontier = {
            "decision_class": preflight_tool.DIRECT_EVAL,
            "node_id": "y",
            "path": ["SB:ISO@5", "PROBE2"],
            "abstention": None,
            "decision": {"analysis_admissible": True},
        }
        rollup = preflight_tool.walkthrough_rollup(
            [synthetic_node],
            [synthetic_frontier],
            {"probes_passed": True, "active_exact_cell_probe": {"passed": True}},
            {"passed": True},
        )
        self.assertEqual(rollup["significant_ood_branch_count"], 1)
        self.assertEqual(rollup["blocking_branch_count"], 1)
        self.assertFalse(rollup["analysis_admissible"])
        self.assertTrue(rollup["blocking_branches"][0]["blocks_analysis"])
        self.assertFalse(rollup["blocking_branches"][0]["substituted"])

    def _ood_probes(self) -> dict:
        runtime = runtime_provider.load_runtime(None, None, None, None)
        rule = preflight_tool.ood_rule_record(
            preflight_tool.load_frozen_spec(), preflight_tool.load_frozen_manifest(
                preflight_tool.load_frozen_spec()
            )
        )
        return preflight_tool.ood_branch_guard(runtime, rule)

    # -------------------------------------------------- the mechanical gate
    def test_issue367_preflight_passed_is_derived_mechanically(self):
        derivation = self.document["issue367_preflight_passed_derivation"]
        self.assertEqual(
            derivation["formula"],
            "issue367_preflight_passed = terminal_outcome_admits and analysis_admissible "
            "and preflight_passed",
        )
        recomputed = preflight_tool.derive_issue367_preflight_passed(
            self.document["admission"], self.document["walkthrough"]
        )
        self.assertEqual(recomputed, derivation)
        self.assertIs(
            self.document["issue367_preflight_passed"],
            derivation["issue367_preflight_passed"],
        )
        # The gate is exactly the conjunction of the three terms.
        for admitted in (True, False):
            for admissible in (True, False):
                for preflight_passed in (True, False):
                    with self.subTest(
                        admitted=admitted, admissible=admissible, passed=preflight_passed
                    ):
                        result = preflight_tool.derive_issue367_preflight_passed(
                            {"issue367_authorized": admitted, "terminal_outcome": "X"},
                            {
                                "analysis_admissible": admissible,
                                "preflight_passed": preflight_passed,
                            },
                        )
                        self.assertIs(
                            result["issue367_preflight_passed"],
                            admitted and admissible and preflight_passed,
                        )

    def test_the_gate_is_false_here_because_the_terminal_outcome_retains_the_reference(self):
        derivation = self.document["issue367_preflight_passed_derivation"]
        self.assertFalse(derivation["terms"]["terminal_outcome_admits"])
        self.assertFalse(self.document["issue367_preflight_passed"])
        # The gate also refuses when a visited decision is not analysis-admissible.
        walkthrough = dict(self.document["walkthrough"])
        walkthrough["analysis_admissible"] = False
        admission = dict(self.document["admission"])
        admission["issue367_authorized"] = True
        result = preflight_tool.derive_issue367_preflight_passed(admission, walkthrough)
        self.assertFalse(result["issue367_preflight_passed"])
        self.assertTrue(result["terms"]["terminal_outcome_admits"])
        self.assertFalse(result["terms"]["analysis_admissible"])

    def test_an_analysis_inadmissible_walkthrough_keeps_the_gate_false(self):
        admission = dict(self.document["admission"])
        admission["issue367_authorized"] = True
        walkthrough = dict(self.document["walkthrough"])
        walkthrough["analysis_admissible"] = True
        walkthrough["preflight_passed"] = False
        result = preflight_tool.derive_issue367_preflight_passed(admission, walkthrough)
        self.assertFalse(result["issue367_preflight_passed"])
        self.assertTrue(result["terms"]["analysis_admissible"])
        self.assertFalse(result["terms"]["preflight_passed"])

    # -------------------------------------------------------------- boundary
    def test_no_hero_ev_no_367_run_and_no_recommendation(self):
        boundary = self.document["boundary"]
        self.assertFalse(boundary["issue367_executed"])
        self.assertFalse(boundary["hero_ev_executed"])
        self.assertFalse(boundary["recommendation_computed"])
        self.assertFalse(boundary["hero_ev_runner_imported"])
        self.assertEqual(boundary["rollouts_executed"], 0)
        self.assertEqual(boundary["ev_values_computed"], 0)
        scan = self.document["self_scans"]["hero_ev_scan"]
        self.assertEqual(scan["result"], "PASS")
        self.assertFalse(scan["hero_ev_executed"])
        self.assertFalse(scan["recommendation_computed"])
        self.assertEqual(scan["rollouts_executed"], 0)
        self.assertEqual(scan["ev_values_computed"], 0)
        self.assertEqual(scan["runner_module_imported_by_preflight"], False)
        self.assertEqual(scan["forbidden_modules_imported_during_build"], [])
        self.assertNotIn(
            "tools.simulation.run_issue367_real_iso_ev",
            preflight_tool.hero_ev_modules_present(),
        )
        self.assertEqual(preflight_tool.verify_no_hero_ev_execution()["result"], "PASS")
        self.assertEqual(preflight_tool.verify_no_holdout_access()["result"], "PASS")
        self.assertIn(
            "no Hero EV is computed and #367 is not launched",
            self.document["admission"]["consequence_when_forbidden"],
        )

    def test_no_test_consumption_and_no_active_pointer_mutation(self):
        boundary = self.document["boundary"]
        self.assertFalse(boundary["test_consumed"])
        self.assertFalse(boundary["test_split_authorized"])
        self.assertFalse(boundary["validation_split_consumed"])
        self.assertFalse(boundary["active_model_pointer_mutated"])
        self.assertTrue(boundary["protected_files_unchanged"])
        self.assertEqual(boundary["hand_history_files_opened"], 0)
        self.assertTrue(boundary["reads_stayed_inside_the_declared_frozen_evidence"])
        self.assertEqual(
            self.document["protected_files"], preflight_tool.protected_hashes()
        )
        self.assertEqual(
            boundary["declared_evidence_paths"], list(preflight_tool.ALLOWED_EVIDENCE_PATHS)
        )
        for path in boundary["declared_evidence_paths"]:
            self.assertNotIn("GENERALIZED_RESPONSE_DATASET.jsonl", path)
            self.assertNotIn("/datasets/", path)
            self.assertTrue((ROOT / path).is_file(), path)
        self.assertEqual(self.document["self_scans"]["holdout_scan"]["result"], "PASS")
        self.assertEqual(
            self.document["self_scans"]["holdout_scan"]["holdout_looking_imports"], []
        )
        guard = self.document["nearest_lookup_audit"]["faced_price_mapping_guard"]
        self.assertTrue(guard["misreading_is_not_used"])
        self.assertIsNone(guard["mapping_used"]["queried_sizing"])
        self.assertEqual(guard["mapping_used"]["faced_raise_to"], "faced_target_total_bb")

    def test_stack_bucket_reconstruction_is_public_and_key_invariant(self):
        for record in self.document["nodes"]:
            reconstruction = record["stack_reconstruction"]
            node = self.tree_nodes[record["node_identity"]["node_id"]]
            with self.subTest(node=record["node_identity"]["path"]):
                bucket = node["context"]["effective_stack_bucket"]
                self.assertEqual(reconstruction["bucket"], bucket)
                self.assertEqual(
                    reconstruction["representative_bb"],
                    preflight_tool.STACK_BUCKET_REPRESENTATIVE[bucket],
                )
                self.assertEqual(
                    reconstruction["alternate_bb"],
                    preflight_tool.STACK_BUCKET_ALTERNATES[bucket],
                )
                self.assertTrue(reconstruction["ood_feature_key_invariant"])
                self.assertEqual(
                    reconstruction["representative_context_key"],
                    reconstruction["alternate_context_key"],
                )
        context = preflight_tool.node_request_context(self.tree_nodes[str(self.tree["root_id"])])
        self.assertIsNone(context["target_total_bb"])
        self.assertEqual(context["faced_target_total_bb"], 5.0)
        self.assertEqual(context["current_bet_bb"], 5.0)
        self.assertEqual(context["actor_contribution_bb"], 1.0)
        self.assertNotIn("effective_stack_bucket", context)

    def test_frontier_window_uses_the_frozen_engine_interval(self):
        for record in self.document["sizing_frontiers"]:
            with self.subTest(frontier=record["path"]):
                context = record["requested_context"]
                self.assertIsNone(context["target_total_bb"])
                self.assertEqual(
                    context["legal_target_interval_bb"], record["legal_target_interval_bb"]
                )
                self.assertTrue(record["derived_window_matches_frozen_interval"])
                self.assertEqual(
                    record["derived_window_bb"], record["legal_target_interval_bb"]
                )
                cross_check = record["structural_context_cross_check"]
                for flag in (
                    "family_agrees",
                    "actor_position_agrees",
                    "table_size_agrees",
                    "raise_level_agrees",
                    "live_position_set_agrees",
                    "history_agrees",
                    "all_in_position_set_agrees",
                ):
                    self.assertTrue(cross_check[flag], flag)
                frozen = record["frozen_sizing_source"]
                self.assertEqual(
                    frozen["blocker_reason_code"], "RAISE_SIZING_UNRESOLVED_NO_NEAREST_PRICE"
                )
                for flag in (
                    "nearest_price_substituted",
                    "nearest_context_substituted",
                    "representative_price_substituted",
                    "legal_minimum_fallback_substituted",
                ):
                    self.assertFalse(frozen[flag], flag)

    def test_hand_history_tripwire_classifies_data_files(self):
        self.assertTrue(preflight_tool._is_hand_history_path("training/datasets/x.jsonl"))
        self.assertTrue(preflight_tool._is_hand_history_path("anywhere/archive.zip"))
        self.assertTrue(preflight_tool._is_hand_history_path("anywhere/other.snapshots.json"))
        self.assertTrue(
            preflight_tool._is_hand_history_path(
                ROOT / "training" / "datasets" / "populations" / "any.json"
            )
        )
        self.assertFalse(preflight_tool._is_hand_history_path(preflight_tool.FIXTURE_PATH))
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "probe.json"
            with mock.patch.object(preflight_tool, "DATASET_ROOT", Path(tmp)):
                with self.assertRaises(preflight_tool.PreflightError):
                    with preflight_tool.hand_history_tripwire():
                        probe.open("w").close()
            self.assertFalse(probe.exists())

    def test_self_scans_reject_forbidden_symbols_injected_into_the_source(self):
        with self.assertRaises(preflight_tool.PreflightError):
            preflight_tool.verify_no_hero_ev_execution(
                "import tools.simulation.run_issue367_real_iso_ev as runner\n"
            )
        with self.assertRaises(preflight_tool.PreflightError):
            preflight_tool.verify_no_holdout_access("rows = load_validation_records()\n")
        with self.assertRaises(preflight_tool.PreflightError):
            preflight_tool.verify_no_holdout_access(
                "import tools.training.load_holdout as holdout\n"
            )

    def test_build_is_deterministic_and_reproducible(self):
        first, _ = preflight_tool.build()
        second, _ = preflight_tool.build()
        self.assertEqual(preflight_tool.serialize(first), preflight_tool.serialize(second))
        self.assertEqual(
            preflight_tool.serialize(first), (self.output / preflight_tool.NAME).read_bytes()
        )
        self.assertEqual(first, self.persisted)


if __name__ == "__main__":
    unittest.main()
