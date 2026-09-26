#!/usr/bin/env python3
"""#421 -> #367 preflight regressions (no Hero EV, no TEST, no nearest lookup).

The preflight walks the 38 required nodes of the scenario #321 response tree
plus its 7 frozen raise-sizing frontiers, queries the #421 generalized
adverse-response runtime provider *directly* at each node's exact public context
and records the action distribution, the frozen OOD status, the uncertainty, the
provenance and the conditional raise sizing.

These tests pin the contract: every visited node is either direct-evaluated or
explicitly abstained, no nearest price/context or representative price is ever
substituted, no Hero EV / #367 run / recommendation is computed, TEST stays
unconsumed, the active pointer is untouched, the result is conditioned on the
frozen admission decision (and, when the candidate is not admitted, states the
blocking abstention and quotes the frozen rule), and the whole document is
byte-reproducible.
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

from tools.preflop import generalized_response_model as model  # noqa: E402
from tools.preflop import generalized_response_runtime as runtime_provider  # noqa: E402
from tools.simulation import issue421_issue367_preflight as preflight_tool  # noqa: E402


class Issue421Issue367PreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = preflight_tool.OUTPUT_DIR
        cls.document, cls.summary = preflight_tool.build()
        if not (cls.output / preflight_tool.NAME).is_file():
            preflight_tool.persist(cls.document)
        cls.persisted = json.loads((cls.output / preflight_tool.NAME).read_text())
        cls.tree = json.loads(preflight_tool.REQUIRED_TREE_PATH.read_text())
        cls.tree_nodes = {str(node["id"]): node for node in cls.tree["nodes"]}
        cls.frontiers = model.load_raise_sizing_frontiers()

    # ------------------------------------------------------------- artifact
    def test_persisted_preflight_is_content_addressed_and_check_passes(self):
        payload = (self.output / preflight_tool.NAME).read_bytes()
        self.assertEqual(payload, preflight_tool.serialize(self.persisted))
        sidecar = (self.output / preflight_tool.SIDECAR_NAME).read_text().splitlines()
        self.assertEqual(sidecar[0], f"{hashlib.sha256(payload).hexdigest()}  {preflight_tool.NAME}")
        self.assertEqual(
            sidecar[1],
            f"# canonical_payload_sha256 {preflight_tool.canonical_sha256(self.persisted)}",
        )
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(preflight_tool.check(), 0)
        self.assertEqual(json.loads(stream.getvalue())["check"], "PASS")

    def test_document_identity_and_scenario_binding(self):
        self.assertEqual(self.document["schema"], preflight_tool.SCHEMA)
        self.assertEqual(self.document["kind"], "ISSUE367_PREFLIGHT")
        self.assertEqual(self.document["issue"], 421)
        self.assertEqual(self.document["source_issue"], 367)
        self.assertEqual(self.document["scenario_issue"], 321)
        self.assertEqual(self.document["scenario_id"], preflight_tool.SCENARIO_ID)
        scenario = self.document["scenario"]
        self.assertEqual(scenario["root_path"], ["SB:ISO@5"])
        self.assertEqual(scenario["required_node_count"], 38)
        self.assertEqual(scenario["unresolved_sizing_frontier_count"], 7)
        self.assertEqual(scenario["fixture_sha256"], preflight_tool.sha256_file(preflight_tool.FIXTURE_PATH))
        bindings = self.document["evidence_bindings"]
        for key, path in (
            ("preflight_tool_sha256", preflight_tool.SOURCE_PATH),
            ("runtime_module_sha256", preflight_tool.RUNTIME_MODULE_PATH),
            ("protocol_byte_sha256", preflight_tool.PROTOCOL_PATH),
            ("candidate_manifest_sha256", preflight_tool.MANIFEST_PATH),
            ("decision_sha256", preflight_tool.DECISION_PATH),
            ("validation_result_sha256", preflight_tool.VALIDATION_RESULT_PATH),
            ("required_tree_sha256", preflight_tool.REQUIRED_TREE_PATH),
        ):
            with self.subTest(binding=key):
                self.assertEqual(bindings[key], preflight_tool.sha256_file(path))
        self.assertEqual(
            bindings["candidate_canonical_payload_sha256"], preflight_tool.CANDIDATE_CANONICAL_SHA256
        )
        self.assertEqual(bindings["candidate_byte_sha256"], preflight_tool.CANDIDATE_BYTE_SHA256)

    # ------------------------------------------------------------- admission
    def test_result_is_conditioned_on_the_frozen_decision_and_frozen_rule(self):
        admission = self.document["admission"]
        decision = json.loads(preflight_tool.DECISION_PATH.read_text())
        validation = json.loads(preflight_tool.VALIDATION_RESULT_PATH.read_text())
        protocol = json.loads(preflight_tool.PROTOCOL_PATH.read_text())
        frozen_rule = protocol["issue367_rule"]
        self.assertEqual(admission["rule_id"], preflight_tool.ISSUE367_RULE_ID)
        self.assertEqual(frozen_rule["rule_id"], preflight_tool.ISSUE367_RULE_ID)
        self.assertFalse(frozen_rule["authorized_at_freeze"])
        self.assertEqual(admission["validation_outcome"], validation["outcome"])
        self.assertEqual(admission["admission_decision"], validation["decision"])
        self.assertEqual(admission["declared_issue367_authorized"], decision["issue367_authorized"])
        self.assertEqual(admission["failed_gates"], decision["failed_gates"])
        self.assertEqual(admission["criteria_passed"], decision["criteria_passed"])
        self.assertEqual(admission["criteria_total"], decision["criteria_total"])
        # The frozen rule is quoted verbatim, not paraphrased.
        self.assertEqual(admission["authorized_when"], frozen_rule["authorized_when"])
        self.assertEqual(admission["forbidden_while"], frozen_rule["forbidden_while"])
        self.assertEqual(
            admission["consequence_when_forbidden"], frozen_rule["consequence_when_forbidden"]
        )
        self.assertEqual(
            admission["currently_admitted_model_a_for_367"],
            frozen_rule["currently_admitted_model_a_for_367"],
        )
        self.assertEqual(
            admission["currently_admitted_model_a_for_367"]["candidate_id"],
            "model-a-preflop-sizing-aware-candidate-v2",
        )

    def test_unadmitted_candidate_yields_a_blocking_abstention(self):
        admission = self.document["admission"]
        validation = json.loads(preflight_tool.VALIDATION_RESULT_PATH.read_text())
        if validation["outcome"] == preflight_tool.ISSUE367_AUTHORIZING_OUTCOME:
            self.skipTest("this workspace carries an admitted candidate, not a retention")
        self.assertFalse(admission["authorized"])
        self.assertEqual(admission["consumption"], "FORBIDDEN")
        self.assertEqual(admission["outcome"], "ABSTAIN_BLOCKED_ADMISSION")
        self.assertIn(
            "VALIDATION outcome is RETAIN_ACTIVE_REFERENCE", admission["blocking_reasons"]
        )
        for gate in admission["failed_gates"]:
            self.assertIn(f"failed frozen gate: {gate}", admission["blocking_reasons"])
        self.assertIn(
            "no ADMIT_CANDIDATE VALIDATION result exists for this candidate",
            admission["blocking_reasons"],
        )
        abstention = admission["abstention"]
        self.assertEqual(abstention["code"], "ISSUE367_ADMISSION_NOT_GRANTED")
        self.assertEqual(abstention["frozen_rule_id"], preflight_tool.ISSUE367_RULE_ID)
        for flag in (
            "hero_ev_consumed",
            "model_b_consumed",
            "test_consumed",
            "active_model_pointer_mutation",
            "promotion_performed",
        ):
            self.assertFalse(abstention[flag], flag)

    def test_admission_branch_tracks_the_frozen_decision(self):
        """Both branches are reachable; the artifact follows the frozen decision."""
        protocol = preflight_tool.load_frozen_protocol()
        manifest = preflight_tool.load_candidate_manifest(protocol)
        decision = preflight_tool.load_terminal_decision(protocol)
        honest = preflight_tool.issue367_admission(protocol, manifest, decision)
        self.assertEqual(honest, self.document["admission"])

        admitted = json.loads(json.dumps(decision))
        admitted["validation_result"]["outcome"] = preflight_tool.ISSUE367_AUTHORIZING_OUTCOME
        admitted["document"]["issue367_authorized"] = True
        admitted["document"]["failed_gates"] = []
        branch = preflight_tool.issue367_admission(protocol, manifest, admitted)
        self.assertTrue(branch["authorized"])
        self.assertEqual(branch["outcome"], "ADMITTED")
        self.assertEqual(branch["consumption"], "AUTHORIZED")
        self.assertIsNone(branch["abstention"])
        self.assertEqual(branch["blocking_reasons"], [])

    def test_decision_cannot_authorize_consumption_without_an_admission_outcome(self):
        protocol = preflight_tool.load_frozen_protocol()
        manifest = preflight_tool.load_candidate_manifest(protocol)
        decision = preflight_tool.load_terminal_decision(protocol)
        tampered = json.loads(json.dumps(decision))
        tampered["document"]["issue367_authorized"] = True
        with self.assertRaises(preflight_tool.PreflightError):
            preflight_tool.issue367_admission(protocol, manifest, tampered)

    def test_an_admission_with_a_failed_gate_is_refused(self):
        protocol = preflight_tool.load_frozen_protocol()
        manifest = preflight_tool.load_candidate_manifest(protocol)
        decision = preflight_tool.load_terminal_decision(protocol)
        tampered = json.loads(json.dumps(decision))
        tampered["validation_result"]["outcome"] = preflight_tool.ISSUE367_AUTHORIZING_OUTCOME
        tampered["document"]["issue367_authorized"] = True
        with self.assertRaises(preflight_tool.PreflightError):
            preflight_tool.issue367_admission(protocol, manifest, tampered)

    def test_frozen_evidence_drift_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            sidecar = Path(tmp) / "decision.sha256"
            sidecar.write_text("0" * 64 + "  DECISION.json\n", encoding="utf-8")
            with mock.patch.object(preflight_tool, "DECISION_SIDECAR", sidecar):
                with self.assertRaises(preflight_tool.PreflightError):
                    preflight_tool.load_terminal_decision(
                        preflight_tool.load_frozen_protocol()
                    )
            with mock.patch.object(preflight_tool, "CANDIDATE_CANONICAL_SHA256", "0" * 64):
                with self.assertRaises(preflight_tool.PreflightError):
                    preflight_tool.load_candidate_manifest(
                        preflight_tool.load_frozen_protocol()
                    )

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
                self.assertIn(record["decision_class"], ("DIRECT_EVAL", "EXPLICIT_ABSTAIN"))
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

    def test_every_visited_node_is_direct_eval_or_explicit_abstain(self):
        audit = self.document["direct_evaluation_audit"]
        self.assertEqual(audit["rule"], "EVERY_VISITED_NODE_IS_DIRECT_EVAL_OR_EXPLICIT_ABSTAIN")
        self.assertTrue(audit["every_visited_node_classified"])
        self.assertEqual(
            audit["direct_eval_nodes"] + audit["explicit_abstain_nodes"], audit["nodes_visited"]
        )
        for record in self.document["nodes"]:
            with self.subTest(node=record["node_identity"]["path"]):
                if record["decision_class"] == "DIRECT_EVAL":
                    self.assertIsNone(record["abstention"])
                    model_view = record["model"]
                    self.assertTrue(model_view["usable"])
                    self.assertFalse(model_view["abstain"])
                    self.assertEqual(model_view["fail_closed_reason"], None)
                    distribution = model_view["action_distribution"]
                    self.assertEqual(distribution["illegal_mass"], 0.0)
                    self.assertEqual(
                        sorted(distribution["probabilities"]), sorted(preflight_tool.model.ACTIONS)
                    )
                    self.assertAlmostEqual(
                        sum(distribution["probabilities"].values()), 1.0, places=9
                    )
                    self.assertIsNotNone(model_view["uncertainty"])
                    self.assertEqual(
                        model_view["provenance"]["candidate"]["candidate_id"],
                        preflight_tool.CANDIDATE_ID,
                    )
                else:
                    self.assertIsNotNone(record["abstention"])
                    self.assertIsNone(record["abstention"]["selected_action"])
                    self.assertIsNone(record["abstention"]["sizing"])

    def test_ood_gate_abstention_wiring_is_real(self):
        probe = self.document["direct_evaluation_audit"]["ood_abstention_probe"]
        self.assertTrue(probe["passed"])
        self.assertEqual(probe["status"], "OOD_ABSTAIN")
        self.assertIn("UNSEEN_CATEGORY", probe["hard_reasons"])
        self.assertIsNone(probe["selected_action"])
        self.assertIsNone(probe["selected_sizing_bb"])

    def test_raise_simulations_report_the_conditional_sizing_or_fail_closed(self):
        audit = self.document["direct_evaluation_audit"]
        attempted = audit["raise_simulations_attempted"]
        resolved = audit["raise_simulation_states"].get("RAISE_SIZING_RESOLVED", 0)
        failed = audit["raise_simulation_states"].get("RAISE_SIZING_FAIL_CLOSED", 0)
        self.assertEqual(attempted, resolved + failed)
        self.assertTrue(audit["raise_sizing_abstentions_are_explicit"])
        for reason, count in audit["raise_sizing_fail_closed_reasons"].items():
            self.assertTrue(reason)
            self.assertGreater(count, 0)
        for record in self.document["nodes"]:
            simulation = record["raise_simulation"]
            with self.subTest(node=record["node_identity"]["path"], state=simulation["state"]):
                if simulation["state"] == "RAISE_SIZING_RESOLVED":
                    sizing = simulation["sizing"]
                    self.assertEqual(sizing["status"], "RESOLVED")
                    self.assertEqual(sizing["illegal_count"], 0)
                    self.assertFalse(sizing["nearest_price_substituted"])
                    self.assertFalse(sizing["nearest_context_substituted"])
                    self.assertTrue(sizing["generated_sizings_bb"])
                    self.assertIsNotNone(simulation["selected_sizing_bb"])
                elif simulation["state"] == "RAISE_SIZING_FAIL_CLOSED":
                    self.assertTrue(simulation["reason"])
                    self.assertEqual(simulation["sizing"]["status"], "FAIL_CLOSED")
                    self.assertEqual(simulation["sizing"]["generated_sizings_bb"], [])
                    self.assertIsNone(simulation["selected_sizing_bb"])
                elif simulation["state"] == "NO_RAISE_ACTION":
                    self.assertIsNone(simulation["sizing"])
                    self.assertIsNone(simulation["requested_action"])
                else:
                    self.fail(f"unexpected raise simulation state {simulation['state']!r}")

    def test_frontier_raise_sizing_resolves_on_the_frozen_engine_interval(self):
        for record in self.document["sizing_frontiers"]:
            with self.subTest(frontier=record["path"]):
                context = record["requested_context"]
                self.assertIsNone(context["target_total_bb"])
                self.assertEqual(
                    context["legal_target_interval_bb"], record["legal_target_interval_bb"]
                )
                simulation = record["raise_simulation"]
                self.assertEqual(simulation["state"], "RAISE_SIZING_RESOLVED")
                sizing = simulation["sizing"]
                self.assertEqual(sizing["illegal_count"], 0)
                self.assertEqual(
                    sizing["legal_window"]["bounds_source"]["max"], "engine_max_raise_to"
                )
                self.assertTrue(record["derived_window_matches_frozen_interval"])
                self.assertEqual(
                    sizing["legal_window"]["floor_bb"], record["legal_target_interval_bb"][0]
                )
                self.assertEqual(
                    sizing["legal_window"]["cap_bb"], record["legal_target_interval_bb"][1]
                )
                self.assertIsNotNone(record["model"]["uncertainty"]["model_node_support"])
                check = record["structural_context_cross_check"]
                for field in (
                    "family_agrees",
                    "actor_position_agrees",
                    "table_size_agrees",
                    "raise_level_agrees",
                    "live_position_set_agrees",
                    "history_agrees",
                ):
                    self.assertTrue(check[field], field)

    # ------------------------------------------------------- nearest lookups
    def test_no_nearest_price_or_context_substitution_is_applied(self):
        audit = self.document["nearest_lookup_audit"]
        self.assertEqual(
            audit["substitution_classes_refused"], list(preflight_tool.SUBSTITUTION_CLASSES)
        )
        self.assertTrue(audit["probes_passed"])
        self.assertEqual(len(audit["probes"]), 3)
        for probe in audit["probes"]:
            with self.subTest(probe=probe["probe"]):
                self.assertTrue(probe["passed"])
                self.assertTrue(probe["decision_changed"])
        self.assertFalse(audit["nearest_price_substituted"])
        self.assertFalse(audit["nearest_context_substituted"])
        guarantees = audit["runtime_declared_flags"]["metadata_guarantees"]
        self.assertFalse(guarantees["nearest_price_substituted"])
        self.assertFalse(guarantees["nearest_context_substituted"])
        self.assertTrue(guarantees["direct_price_sizing_evaluation"])
        runtime_audit = audit["runtime_declared_flags"]["runtime_audit"]
        self.assertFalse(runtime_audit["nearest_price"])
        self.assertFalse(runtime_audit["nearest_context"])
        self.assertTrue(audit["stack_bucket_reconstruction"]["all_nodes_bucket_invariant"])
        for record in self.document["nodes"]:
            flags = record["model"]["provenance"]["identity_flags"]
            self.assertFalse(flags["nearest_price_substituted"])
            self.assertFalse(flags["nearest_context_substituted"])
            self.assertEqual(
                record["model"]["request"]["evaluation"], "direct_recomputation"
            )
            self.assertEqual(
                record["model"]["request"]["interpolation"],
                "linear_spline_partition_of_unity",
            )

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
                self.assertNotEqual(
                    reconstruction["representative_bb"], reconstruction["alternate_bb"]
                )
                self.assertTrue(reconstruction["ood_feature_key_invariant"])
                self.assertEqual(
                    reconstruction["representative_context_key"],
                    reconstruction["alternate_context_key"],
                )
        context = preflight_tool.node_request_context(
            self.tree_nodes[str(self.tree["root_id"])]
        )
        self.assertIsNone(context["target_total_bb"])
        self.assertEqual(context["faced_target_total_bb"], 5.0)
        self.assertEqual(context["current_bet_bb"], 5.0)
        self.assertEqual(context["actor_contribution_bb"], 1.0)
        self.assertNotIn("effective_stack_bucket", context)

    def test_faced_price_is_never_passed_as_a_queried_sizing(self):
        guard = self.document["nearest_lookup_audit"]["faced_price_mapping_guard"]
        self.assertEqual(
            guard["rule"], "THE_FACED_RAISE_TO_IS_NEVER_PASSED_AS_A_QUERIED_SIZING"
        )
        self.assertTrue(guard["misreading_is_not_used"])
        self.assertIsNone(guard["mapping_used"]["queried_sizing"])
        self.assertEqual(guard["mapping_used"]["faced_raise_to"], "faced_target_total_bb")
        # The frozen #421 dataset contract is the authority for the field meaning.
        contract = json.loads(preflight_tool.DATASET_CONTRACT_PATH.read_text())
        descriptions = json.dumps(contract)
        self.assertIn("after the action for RAISE/JAM", descriptions)
        self.assertEqual(
            self.document["evidence_bindings"]["dataset_contract_sha256"],
            preflight_tool.sha256_file(preflight_tool.DATASET_CONTRACT_PATH),
        )
        misread_paths = {tuple(row["path"]) for row in guard["misreading_would_abstain_nodes"]}
        self.assertEqual(guard["misreading_would_abstain_count"], len(misread_paths))
        self.assertTrue(misread_paths)
        # Every misread path is refused, and the refusal is *declared*: either the
        # frozen OOD gate abstained (the misread target also leaves the calibrated
        # domain) or the legal-window declaration failed closed because the misread
        # target is not a legal raise target of that actor.
        codes: dict[str, int] = {}
        for row in guard["misreading_would_abstain_nodes"]:
            codes[row["code"]] = codes.get(row["code"], 0) + 1
            if row["code"] == runtime_provider.OOD_ABSTAIN_REASON:
                self.assertIn("EXTRAPOLATION_SIZING", row["hard_reasons"])
            else:
                self.assertEqual(row["code"], runtime_provider.FAIL_CLOSED_ILLEGAL_SIZING)
                self.assertEqual(row["hard_reasons"], [])
        self.assertEqual(codes, guard["misreading_refusal_codes"])
        self.assertEqual(sum(codes.values()), guard["misreading_would_abstain_count"])
        self.assertIn(runtime_provider.FAIL_CLOSED_ILLEGAL_SIZING, codes)
        self.assertIn(runtime_provider.OOD_ABSTAIN_REASON, codes)
        by_path = {
            tuple(record["node_identity"]["path"]): record for record in self.document["nodes"]
        }
        for path in misread_paths:
            with self.subTest(path=path):
                self.assertEqual(by_path[path]["decision_class"], "DIRECT_EVAL")
                self.assertTrue(by_path[path]["model"]["usable"])

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
        self.assertEqual(scan["runner_module_imported_by_preflight"], False)
        self.assertEqual(scan["forbidden_modules_imported_during_build"], [])
        self.assertNotIn(
            "tools.simulation.run_issue367_real_iso_ev",
            preflight_tool.hero_ev_modules_present(),
        )
        self.assertNotIn(
            "tools.simulation.admitted_model_a_iso_provider",
            preflight_tool.hero_ev_modules_present(),
        )
        self.assertEqual(preflight_tool.verify_no_hero_ev_execution()["result"], "PASS")
        self.assertEqual(preflight_tool.verify_no_holdout_access()["result"], "PASS")

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

    def test_hand_history_tripwire_classifies_data_files(self):
        self.assertTrue(preflight_tool._is_hand_history_path("training/datasets/x.jsonl"))
        self.assertTrue(preflight_tool._is_hand_history_path("anywhere/archive.zip"))
        self.assertTrue(preflight_tool._is_hand_history_path("anywhere/other.snapshots.json"))
        self.assertTrue(
            preflight_tool._is_hand_history_path(
                ROOT / "training" / "datasets" / "populations" / "any.json"
            )
        )
        # The canonical #321 scenario fixture is declared frozen evidence, not hand history.
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
