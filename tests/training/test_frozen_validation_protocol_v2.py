#!/usr/bin/env python3
"""#419 revision v2 of the frozen hierarchical VALIDATION protocol.

The v2 revision is an explicitly versioned, content-addressed artifact that
splits the protocol into an exact empirical support layer and an exact-context
estimate admissibility layer. These tests pin the split, the unchanged 20/20
thresholds, the unchanged ``EXACT_EMPIRICAL_STRONG`` label, the v1->v2
traceability, the node consumption rule, and — most importantly — the
immutability of every frozen v1 surface (protocol bytes, digest sidecar, the
consumed VALIDATION history, the T8 preflight and the terminal decision).
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training import write_frozen_validation_protocol as v1_tool  # noqa: E402
from tools.training import write_frozen_validation_protocol_v2 as tool  # noqa: E402
from tools.training.audit_preflop_sizing_support import stable_hash  # noqa: E402


class FrozenValidationProtocolV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol_bytes = (tool.OUT / tool.NAME).read_bytes()
        cls.protocol = json.loads(cls.protocol_bytes)
        cls.index = json.loads((tool.OUT / tool.INDEX_NAME).read_text())
        cls.digest = hashlib.sha256(cls.protocol_bytes).hexdigest()
        cls.v1_bytes = v1_tool.PROTOCOL_PATH.read_bytes()
        cls.v1 = json.loads(cls.v1_bytes)

    # ------------------------------------------------------------- artifact
    def test_v2_is_content_addressed_and_byte_identical(self):
        self.assertEqual(self.digest, self.index[tool.NAME]["sha256"])
        self.assertEqual(
            self.index[tool.NAME]["canonical_payload_sha256"], stable_hash(self.protocol)
        )
        self.assertEqual(self.protocol_bytes, (tool.OUT / tool.NAME).read_bytes())
        self.assertEqual(
            self.protocol_bytes,
            (tool.OUT / self.index[tool.NAME]["object"]).read_bytes(),
        )
        for name, entry in self.index.items():
            if name == tool.HISTORY_KEY:
                continue
            with self.subTest(artifact=name):
                data = (tool.OUT / name).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"])
                self.assertEqual(data, (tool.OUT / entry["object"]).read_bytes())
        self.assertEqual(
            {p.name for p in (tool.OUT / "sha256").iterdir()},
            {
                Path(entry["object"]).name
                for name, entry in self.index.items()
                if name != tool.HISTORY_KEY
            },
        )
        sidecar = (tool.OUT / tool.DIGEST_NAME).read_text().splitlines()
        self.assertEqual(sidecar[0].split(), [self.digest, tool.NAME])
        self.assertEqual(
            sidecar[1].split(),
            ["#", "canonical_payload_sha256", stable_hash(self.protocol)],
        )
        self.assertEqual(sidecar[2].split(), ["#", "revision_of", tool.V1_BYTE_SHA256])

    def test_schema_name_and_revision_are_distinct_from_v1(self):
        self.assertEqual(self.protocol["schema"], tool.SCHEMA)
        self.assertEqual(self.protocol["schema"], "poker-hierarchical-frozen-validation-protocol/v2")
        self.assertEqual(self.protocol["kind"], tool.KIND)
        self.assertEqual(self.protocol["revision"], 2)
        self.assertEqual(self.protocol["revision_of"], "poker-hierarchical-frozen-validation-protocol/v1")
        self.assertEqual(self.protocol["issue"], 419)
        self.assertEqual(self.protocol["parent_issue"], 314)
        self.assertEqual(self.protocol["status"], tool.STATUS)
        self.assertNotEqual(self.protocol["schema"], self.v1["schema"])
        self.assertNotEqual(self.protocol["name"], self.v1["protocol_name"])
        self.assertEqual(self.index[tool.NAME]["revision_of"], tool.V1_BYTE_SHA256)

    def test_v2_references_the_v1_digests(self):
        provenance = self.protocol["v1_provenance"]
        self.assertEqual(provenance["schema"], self.v1["schema"])
        self.assertEqual(provenance["byte_sha256"], tool.V1_BYTE_SHA256)
        self.assertEqual(provenance["byte_sha256"], hashlib.sha256(self.v1_bytes).hexdigest())
        self.assertEqual(provenance["canonical_payload_sha256"], tool.V1_CANONICAL_SHA256)
        self.assertEqual(provenance["canonical_payload_sha256"], stable_hash(self.v1))
        self.assertEqual(provenance["status"], self.v1["status"])
        self.assertEqual(provenance["frozen_at"], self.v1["frozen_at"])
        self.assertEqual(provenance["protocol_generator"]["path"], tool.V1_GENERATOR_PATH)
        self.assertEqual(provenance["protocol_generator"]["sha256"], tool.V1_GENERATOR_SHA256)
        self.assertEqual(provenance["thresholds_sha256"], stable_hash(self.v1["thresholds"]))
        self.assertEqual(
            provenance["pooling_limits_sha256"], stable_hash(self.v1["pooling_limits"])
        )
        self.assertEqual(
            provenance["admission_gates_sha256"],
            stable_hash(self.v1["calibration_and_admission"]["admission_gates"]),
        )

    # ------------------------------------------------------- v1 immutability
    def test_v1_bytes_and_history_are_still_byte_identical(self):
        custody = self.protocol["v1_custody"]
        self.assertTrue(custody["v1_bytes_unchanged"])
        self.assertTrue(custody["v1_immutability_is_re_derived_not_asserted"])
        rows = custody["v1_surfaces"] + custody["bound_identities"]
        paths = {row["path"] for row in rows}
        for required in (
            "analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.json",
            "analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.sha256",
            "analysis/issue419_hierarchical_tree/validation/VALIDATION_RESULT.json",
            "analysis/issue419_hierarchical_tree/exact_tree_preflight/EXACT_TREE_PREFLIGHT.json",
            "analysis/issue419_hierarchical_tree/terminal_decision/DECISION.json",
        ):
            with self.subTest(required=required):
                self.assertIn(required, paths)
        for row in rows:
            with self.subTest(path=row["path"]):
                self.assertEqual(tool.sha256_file(ROOT / row["path"]), row["sha256"])
        # The v2 payload is not the authority: the pinned v1 pins are re-derived
        # from the very bytes the v1 protocol froze.
        self.assertEqual(
            tool.sha256_file(v1_tool.PROTOCOL_PATH), self.protocol["v1_provenance"]["byte_sha256"]
        )
        self.assertEqual(
            tool.sha256_file(ROOT / v1_tool.SOURCE_PATH.relative_to(ROOT)),
            tool.V1_GENERATOR_SHA256,
        )
        self.assertEqual(
            self.v1["code"]["protocol_generator_sha256"], tool.V1_GENERATOR_SHA256
        )
        self.assertEqual(
            (v1_tool.BUNDLE / v1_tool.NAME).read_bytes(), self.v1_bytes
        )
        self.assertEqual(
            self.protocol["v1_custody"]["validation_history_sha256"],
            tool.sha256_file(ROOT / "analysis/issue419_hierarchical_tree/validation/VALIDATION_RESULT.json"),
        )
        # The immutability check fails closed when a frozen v1 byte drifts.
        with self.assertRaises(tool.ProtocolV2Error):
            tool._surface_rows(((
                "analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.json",
                "FROZEN_V1_PROTOCOL_PAYLOAD",
                "0" * 64,
            ),))

    # --------------------------------------------------------------- layers
    def test_layer_a_is_the_unchanged_exact_empirical_support_definition(self):
        layer = self.protocol["layers"]["layer_a_exact_empirical_support"]
        self.assertEqual(layer["layer_id"], "EXACT_EMPIRICAL_SUPPORT")
        self.assertEqual(layer["status_label"], "EXACT_EMPIRICAL_STRONG")
        self.assertFalse(layer["status_label_changed_by_this_revision"])
        self.assertFalse(layer["relabelled_from_pooled_support_allowed"])
        self.assertEqual(layer["support_level"], "L0_EXACT_KEY")
        self.assertEqual(layer["thresholds"]["minimum_marginal_observations"], 20)
        self.assertEqual(layer["thresholds"]["minimum_distinct_hands"], 20)
        self.assertTrue(layer["thresholds"]["inherited_verbatim_from_v1"])
        self.assertFalse(layer["thresholds"]["modified_by_this_revision"])
        self.assertTrue(layer["support_never_borrowed"])
        self.assertFalse(layer["counts_from_other_levels_allowed"])
        self.assertEqual(layer["support_isolation_rule"], "SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT")
        self.assertEqual(layer["runtime_invariant"], "support.source_key == requested_key")
        self.assertEqual(
            self.protocol["thresholds"]["minimum_marginal_observations"],
            int(self.v1["thresholds"]["minimum_marginal_observations"]),
        )
        self.assertEqual(
            self.protocol["thresholds"]["minimum_distinct_hands"],
            int(self.v1["thresholds"]["minimum_distinct_hands"]),
        )

    def test_layer_b_is_the_exact_context_estimate_admissibility_layer(self):
        layer = self.protocol["layers"]["layer_b_exact_context_estimate_admissibility"]
        self.assertEqual(layer["layer_id"], "EXACT_CONTEXT_ESTIMATE_ADMISSIBILITY")
        self.assertEqual(layer["status_label"], "EXACT_HIERARCHICAL_ESTIMATE")
        self.assertTrue(layer["identity_preserved"])
        self.assertEqual(layer["identity_granularity"], "hierarchical_exact_key")
        self.assertEqual(layer["runtime_invariant"], "support.source_key == requested_key")
        self.assertFalse(layer["support_counted_from_pooled_levels"])
        self.assertFalse(layer["counts_as_exact_support"])
        closure = layer["counts_as_a_closed_exact_tree_node"]
        self.assertEqual(closure["value"], "CONDITIONAL")
        self.assertTrue(closure["conditionally_closes"])
        self.assertFalse(closure["unconditionally_closes"])
        self.assertTrue(closure["true_iff_all_layer_b_gates_pass"])
        self.assertTrue(closure["false_if_any_layer_b_gate_fails"])
        self.assertFalse(closure["default_when_a_gate_is_unevaluated"])
        self.assertEqual(layer["pooling"]["mechanism"], "STRICTLY_PARAMETRIC")
        self.assertTrue(layer["pooling"]["parent_prior_only"])
        self.assertFalse(layer["pooling"]["counts_smoothed_across_levels"])
        self.assertEqual(layer["pooling"]["support_source_levels"], ["L0_EXACT_KEY"])
        self.assertEqual(
            layer["pooling"]["maximum_parameter_pooling_level"], "L4_POSITION_PRICE_PRIOR"
        )
        self.assertEqual(layer["pooling"]["kappa0"], self.protocol["pooling_limits"]["kappa0"])
        self.assertEqual(layer["pooling"]["kappa0"], 16.0)
        self.assertEqual(layer["pooling"]["alpha_per_legal_marginal_action"], 0.5)
        self.assertEqual(
            layer["identity_axes_retained_at_every_level"],
            ["requested_key_identity", "actor_position", "aggressor_position",
             "target_total_bb", "to_call_bb"],
        )

    def test_layer_b_requires_ess_uncertainty_and_provenance(self):
        layer = self.protocol["layers"]["layer_b_exact_context_estimate_admissibility"]
        mandatory = layer["mandatory_reported_fields"]
        ess = {row["field"] for row in mandatory["effective_sample_size"]}
        self.assertEqual(
            ess, {"support.effective_sample_size", "pooling.source_effective_sample_size"}
        )
        uncertainty = {row["field"] for row in mandatory["uncertainty"]}
        self.assertEqual(uncertainty, {"uncertainty", "posterior"})
        provenance = {row["field"] for row in mandatory["provenance"]}
        for field in (
            "requested_key",
            "support.observations",
            "support.distinct_hands",
            "support.source_key",
            "support.borrowed_from_other_keys",
            "pooling.level",
            "pooling.source_key",
            "pooling.source_observations",
            "pooling.source_distinct_hands",
            "pooling.retained_axes",
            "pooling.pooled_axes",
        ):
            with self.subTest(field=field):
                self.assertIn(field, provenance)
        gates = {row["gate_id"]: row for row in layer["admissibility_gates"]}
        self.assertEqual(
            [row["gate_id"] for row in layer["admissibility_gates"]],
            [
                "EXACT_KEY_IDENTITY",
                "POOLING_PROVENANCE",
                "POOLING_LEVEL",
                "EFFECTIVE_SAMPLE_SIZE",
                "UNCERTAINTY",
                "CALIBRATION",
                "RAISE_SIZING_FRONTIER",
            ],
        )
        self.assertEqual(
            [row["reason_code"] for row in layer["admissibility_gates"]],
            list(tool.GATE_REASON_CODES),
        )
        by_dimension = layer["admissibility_gates_by_dimension"]
        self.assertEqual(by_dimension["calibration"]["maximum_absolute_ece"], 0.05)
        self.assertEqual(by_dimension["calibration"]["maximum_ece_delta_vs_active"], 0.02)
        self.assertEqual(
            by_dimension["calibration"]["minimum_bin_support_for_a_calibration_claim"], 20
        )
        self.assertTrue(by_dimension["identity"]["support_source_key_equals_requested_key"])
        self.assertEqual(by_dimension["raise_sizing"]["policy"], "exact-support-only")
        self.assertIn("representative raise price", by_dimension["raise_sizing"]["forbidden"])
        self.assertEqual(gates["CALIBRATION"]["reason_code"], "REFUSED_CALIBRATION")
        self.assertEqual(
            gates["RAISE_SIZING_FRONTIER"]["reason_code"], "REFUSED_RAISE_SIZING_FRONTIER"
        )

    def test_thresholds_and_pooling_are_inherited_and_never_weakened(self):
        self.assertTrue(self.protocol["thresholds"]["inherited_verbatim_from_v1"])
        self.assertFalse(self.protocol["thresholds"]["modified_by_this_revision"])
        self.assertFalse(self.protocol["thresholds"]["re_selected_after_reading_validation"])
        self.assertTrue(self.protocol["pooling_limits"]["inherited_verbatim_from_v1"])
        self.assertFalse(self.protocol["pooling_limits"]["modified_by_this_revision"])
        self.assertEqual(
            self.protocol["pooling_limits"]["rule_id"],
            "SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT",
        )
        self.assertEqual(self.protocol["pooling_limits"]["only_support_source_level"], "L0_EXACT_KEY")
        frozen = self.protocol["gates"]["frozen_admission_gates"]
        v1_gates = self.v1["calibration_and_admission"]["admission_gates"]
        self.assertEqual([row["gate"] for row in frozen], [row["gate"] for row in v1_gates])
        for row, source in zip(frozen, v1_gates):
            with self.subTest(gate=row["gate"]):
                self.assertEqual(row["rule"], source["rule"])
                self.assertTrue(row["carried_from_v1"])
                self.assertFalse(row["modified"])
        self.assertFalse(self.protocol["gates"]["gates_modified_by_this_revision"])
        self.assertEqual(self.protocol["gates"]["gates_sha256"], stable_hash(v1_gates))
        self.assertEqual(
            self.protocol["gates"]["outcome_rule"],
            self.v1["calibration_and_admission"]["outcome_rule"],
        )

    # ----------------------------------------------------- statuses/consumption
    def test_three_statuses_and_the_admissible_node_consumption_rule(self):
        statuses = {row["status"]: row for row in self.protocol["statuses"]["values"]}
        self.assertEqual(
            sorted(statuses),
            ["EXACT_EMPIRICAL_STRONG", "EXACT_HIERARCHICAL_ESTIMATE", "EXACT_UNRESOLVED"],
        )
        self.assertTrue(self.protocol["statuses"]["closed_enum"])
        self.assertTrue(statuses["EXACT_EMPIRICAL_STRONG"]["consumable"])
        self.assertTrue(statuses["EXACT_HIERARCHICAL_ESTIMATE"]["consumable"])
        self.assertFalse(statuses["EXACT_UNRESOLVED"]["consumable"])
        self.assertEqual(
            statuses["EXACT_EMPIRICAL_STRONG"]["layer"], "EXACT_EMPIRICAL_SUPPORT"
        )
        self.assertEqual(
            statuses["EXACT_HIERARCHICAL_ESTIMATE"]["layer"],
            "EXACT_CONTEXT_ESTIMATE_ADMISSIBILITY",
        )
        rule = self.protocol["admissible_node_consumption_rule"]
        self.assertEqual(rule["rule_id"], "CONSUME_ONLY_AN_ADMISSIBLE_NODE_ANSWER")
        self.assertIn("EXACT_HIERARCHICAL_ESTIMATE", rule["consumption_by_status"])
        estimate = rule["consumption_by_status"]["EXACT_HIERARCHICAL_ESTIMATE"]
        self.assertTrue(estimate["consumable"])
        self.assertIn("never displayed or counted as exact support", estimate["obligations"])
        unresolved = rule["consumption_by_status"]["EXACT_UNRESOLVED"]
        self.assertFalse(unresolved["consumable"])
        self.assertIn(
            "the pooling level actually used is visible wherever an estimate is shown",
            rule["downstream_requirements"],
        )
        closure = rule["tree_closure"]
        self.assertEqual(closure["rule_id"], tool.NODE_CLOSURE_RULE_ID)
        self.assertIn("required_tree_complete_requires", closure)
        self.assertIn("every required node to be closed", closure["required_tree_complete_requires"])
        self.assertEqual(
            closure["closes_the_node_by_status"]["EXACT_HIERARCHICAL_ESTIMATE"],
            "CONDITIONAL: true if and only if every layer-B gate passes, false otherwise",
        )
        self.assertFalse(closure["closes_the_node_by_status"]["EXACT_UNRESOLVED"].startswith("true"))
        self.assertEqual(closure["gate_ids"], [
            "EXACT_KEY_IDENTITY",
            "POOLING_PROVENANCE",
            "POOLING_LEVEL",
            "EFFECTIVE_SAMPLE_SIZE",
            "UNCERTAINTY",
            "CALIBRATION",
            "RAISE_SIZING_FRONTIER",
        ])
        self.assertEqual(list(closure["refusal_reason_codes"]), list(tool.GATE_REASON_CODES))
        self.assertTrue(closure["not_authorized_by_a_single_admissible_node"])
        self.assertIn(
            "every required node is closed under the conjunction of the frozen layer-B gates",
            closure["authorizes_issue367_consumption_iff"],
        )
        for reason in (
            "any required node is open because a layer-B gate failed",
            "any layer-B gate is unevaluated for a required node",
            "the node answer is EXACT_UNRESOLVED",
            "a raise-sizing frontier stays unresolved",
        ):
            with self.subTest(forbidden=reason):
                self.assertIn(reason, closure["forbids_issue367_consumption_when"])
        self.assertEqual(
            rule["issue367_consumption"]["rule_id"],
            "ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE",
        )
        self.assertFalse(rule["issue367_consumption"]["authorized_at_this_revision"])
        self.assertTrue(
            rule["issue367_consumption"]["not_authorized_by_a_single_admissible_node"]
        )
        self.assertEqual(rule["issue367_consumption"]["node_closure_rule_id"], tool.NODE_CLOSURE_RULE_ID)

    def test_revision_admits_nothing_and_leaves_the_holdout_closed(self):
        self.assertEqual(self.protocol["publication"]["production_effect"], "NONE")
        self.assertEqual(self.protocol["publication"]["active_reference_mutation"], "FORBIDDEN")
        self.assertEqual(self.protocol["publication"]["automatic_promotion"], "FORBIDDEN")
        self.assertFalse(self.protocol["publication"]["admits_anything"])
        relation = self.protocol["relationship_to_v1"]
        self.assertEqual(relation["kind"], "ADDITIVE_INTERPRETATION_ONLY")
        self.assertTrue(relation["v1_gates_and_thresholds_remain_the_source_of_record"])
        self.assertFalse(relation["v1_re_frozen_by_this_revision"])
        self.assertFalse(relation["v1_bytes_rewritten"])
        self.assertFalse(relation["changes_admission_rule"])
        holdout = self.protocol["holdout_boundary"]
        self.assertTrue(holdout["revision_authored_after_validation_read"])
        self.assertFalse(holdout["thresholds_selected_after_reading_the_holdout"])
        self.assertFalse(holdout["holdout_reopened_by_this_revision"])
        self.assertFalse(holdout["validation_consumed_by_this_revision"])
        self.assertFalse(holdout["test_consumed"])
        self.assertFalse(holdout["test_authorized"])
        self.assertEqual(holdout["validation_outcome"], "RETAIN_ACTIVE_REFERENCE")
        self.assertTrue(holdout["validation_outcome_is_for_this_candidate"])
        self.assertEqual(
            holdout["issue367_currently_admitted_model"]["candidate_id"],
            "model-a-preflop-sizing-aware-candidate-v2",
        )
        self.assertFalse(
            holdout["issue367_currently_admitted_model"][
                "reference_to_the_hierarchical_candidate_authorized"
            ]
        )
        self.assertEqual(
            holdout["validation_result_sha256"],
            tool.sha256_file(
                ROOT / "analysis/issue419_hierarchical_tree/validation/VALIDATION_RESULT.json"
            ),
        )

    # ------------------------------------------------------------ determinism
    def test_layer_b_gates_are_machine_readable_with_reason_codes(self):
        layer = self.protocol["layers"]["layer_b_exact_context_estimate_admissibility"]
        gates = layer["admissibility_gates"]
        self.assertEqual(len(gates), 7)
        reason_codes = [row["reason_code"] for row in gates]
        self.assertEqual(reason_codes, list(tool.GATE_REASON_CODES))
        self.assertEqual(layer["admissibility_gate_reason_codes"], list(tool.GATE_REASON_CODES))
        self.assertEqual(layer["admissibility_gate_ids"], [row["gate_id"] for row in gates])
        for order, gate in enumerate(gates, start=1):
            with self.subTest(gate=gate["gate_id"]):
                self.assertEqual(gate["order"], order)
                self.assertTrue(gate["reason_code"].startswith("REFUSED_"))
                self.assertTrue(gate["requirement"])
                self.assertTrue(gate["enforced_fields"])
                self.assertTrue(gate["applies_to"])
                for status in gate["applies_to"]:
                    self.assertIn(
                        status,
                        ["EXACT_EMPIRICAL_STRONG", "EXACT_HIERARCHICAL_ESTIMATE",
                         "EXACT_UNRESOLVED"],
                    )
                self.assertTrue(gate["closes_the_node_when_satisfied"])
                self.assertFalse(gate["more_permissive_than_v1"])
                self.assertTrue(gate["inherited_from_v1"])
                self.assertFalse(gate["modified_by_this_revision"])
                self.assertFalse(gate["on_failure"]["node_closed"])
                self.assertEqual(gate["on_failure"]["issue367_consumption"], "REFUSED")
                self.assertEqual(gate["on_failure"]["reason_code"], gate["reason_code"])

    def test_layer_b_gate_values_are_never_more_permissive_than_v1(self):
        layer = self.protocol["layers"]["layer_b_exact_context_estimate_admissibility"]
        block = layer["non_loosening_vs_v1"]
        comparisons = block["comparisons"]
        self.assertEqual(block["comparisons_checked"], len(comparisons))
        self.assertTrue(block["all_not_more_permissive"])
        self.assertFalse(block["any_comparison_more_permissive"])
        self.assertTrue(comparisons)
        v1_pooling = self.v1["pooling_limits"]
        v1_thresholds = self.v1["thresholds"]
        v1_calibration = self.v1["calibration_and_admission"]["calibration"]
        for row in comparisons:
            with self.subTest(gate=row["gate_id"], field=row["field"]):
                self.assertTrue(
                    row["not_more_permissive_than_v1"],
                    msg=f"{row['gate_id']}.{row['field']} is more permissive than v1",
                )
                self.assertIn(
                    row["monotonicity"], {"exact", "non_increasing", "non_decreasing", "superset"}
                )
                recomputed = tool._not_more_permissive(
                    value=row["value"],
                    v1_value=row["v1_value"],
                    monotonicity=row["monotonicity"],
                )
                self.assertTrue(recomputed)
        # A comparative guard against the persisted v1 values, re-derived here
        # rather than trusted from the payload.
        ece = next(
            row for row in comparisons
            if row["gate_id"] == "CALIBRATION" and row["field"] == "maximum_absolute_ece"
        )
        self.assertEqual(ece["value"], v1_thresholds["maximum_absolute_ece"])
        self.assertLessEqual(ece["value"], v1_thresholds["maximum_absolute_ece"])
        delta = next(
            row for row in comparisons
            if row["gate_id"] == "CALIBRATION" and row["field"] == "maximum_ece_delta_vs_active"
        )
        self.assertLessEqual(delta["value"], v1_thresholds["maximum_ece_delta_vs_active"])
        bin_support = next(
            row for row in comparisons
            if row["gate_id"] == "CALIBRATION"
            and row["field"] == "minimum_bin_support_for_a_calibration_claim"
        )
        self.assertGreaterEqual(
            bin_support["value"], v1_calibration["minimum_bin_support_for_a_calibration_claim"]
        )
        min_hands = next(
            row for row in comparisons
            if row["gate_id"] == "EFFECTIVE_SAMPLE_SIZE" and row["field"] == "minimum_distinct_hands"
        )
        self.assertGreaterEqual(min_hands["value"], v1_thresholds["minimum_distinct_hands"])
        max_level = next(
            row for row in comparisons
            if row["gate_id"] == "POOLING_LEVEL"
            and row["field"] == "maximum_level_for_a_reported_estimate"
        )
        self.assertEqual(
            max_level["value"], v1_pooling["maximum_pooling_level_for_a_reported_estimate"]
        )
        # A loosening is reported as a false comparison, not silently accepted.
        self.assertFalse(
            tool._not_more_permissive(value=0.10, v1_value=0.05, monotonicity="non_increasing")
        )

    def test_node_closure_is_conditional_on_the_layer_b_gate_conjunction(self):
        layer = self.protocol["layers"]["layer_b_exact_context_estimate_admissibility"]
        closure = layer["node_closure"]
        self.assertEqual(closure["rule_id"], tool.NODE_CLOSURE_RULE_ID)
        self.assertEqual(closure["rule_id"], "NODE_CLOSES_IFF_ALL_FROZEN_LAYER_B_GATES_PASS")
        self.assertEqual(
            closure["gate_ids"], layer["admissibility_gate_ids"]
        )
        self.assertEqual(list(closure["refusal_reason_codes"]), list(tool.GATE_REASON_CODES))
        self.assertTrue(closure["no_threshold_moved"])
        self.assertTrue(closure["no_gate_value_moved"])
        self.assertFalse(closure["unresolved_node_closure"])
        estimate = closure["closes_the_node_by_status"]["EXACT_HIERARCHICAL_ESTIMATE"]
        self.assertIn("if and only if every layer-B gate passes", estimate)
        self.assertIn("every gate", closure["closed_iff"])
        self.assertIn("stays open when any gate fails", closure["closed_iff"])
        self.assertTrue(layer["counts_as_a_closed_exact_tree_node"]["true_iff_all_layer_b_gates_pass"])
        self.assertTrue(layer["counts_as_a_closed_exact_tree_node"]["false_if_any_layer_b_gate_fails"])
        # Closing the tree still needs every node closed and no sizing frontier.
        rule = self.protocol["admissible_node_consumption_rule"]["tree_closure"]
        self.assertIn("unresolved raise-sizing frontier", rule["required_tree_complete_requires"])

    def test_superseded_v2_bytes_are_preserved_and_cited_by_the_amendment(self):
        history = self.protocol["v1_custody"]["superseded_v2_history"]
        self.assertEqual(history["byte_sha256"], tool.SUPERSEDED_V2_BYTE_SHA256)
        self.assertEqual(history["canonical_payload_sha256"], tool.SUPERSEDED_V2_CANONICAL_SHA256)
        self.assertEqual(history["object"], tool.HISTORY_OBJECT)
        self.assertEqual(history["digest_sidecar"], tool.HISTORY_DIGEST_SIDECAR)
        self.assertEqual(history["cited_by_amendment_id"], tool.AMENDMENT_ID)
        # The bytes are on disk and hash back to the cited digest.
        history_bytes = (tool.OUT / tool.HISTORY_OBJECT).read_bytes()
        self.assertEqual(
            hashlib.sha256(history_bytes).hexdigest(), tool.SUPERSEDED_V2_BYTE_SHA256
        )
        superseded = json.loads(history_bytes)
        self.assertEqual(superseded["schema"], tool.SCHEMA)
        self.assertEqual(superseded["revision"], 2)
        self.assertEqual(stable_hash(superseded), tool.SUPERSEDED_V2_CANONICAL_SHA256)
        self.assertFalse(
            superseded["layers"]["layer_b_exact_context_estimate_admissibility"][
                "counts_as_a_closed_exact_tree_node"
            ]
        )
        sidecar = (tool.OUT / tool.HISTORY_DIGEST_SIDECAR).read_text().splitlines()
        self.assertEqual(sidecar[0].split(), [tool.SUPERSEDED_V2_BYTE_SHA256, tool.NAME])
        index_row = self.index[tool.HISTORY_KEY]
        self.assertEqual(index_row["sha256"], tool.SUPERSEDED_V2_BYTE_SHA256)
        self.assertEqual(index_row["object"], tool.HISTORY_OBJECT)
        # The amendment block cites the superseded digest and records what moved.
        amendments = self.protocol["amendments"]
        self.assertEqual(amendments["superseded_digest"], tool.SUPERSEDED_V2_BYTE_SHA256)
        self.assertEqual(amendments["current_amendment_id"], tool.AMENDMENT_ID)
        self.assertTrue(amendments["no_threshold_moved"])
        self.assertTrue(amendments["no_gate_value_moved"])
        item = amendments["items"][0]
        self.assertFalse(item["change_before"]["counts_as_a_closed_exact_tree_node"])
        self.assertEqual(item["change_after"]["counts_as_a_closed_exact_tree_node"], "CONDITIONAL")
        self.assertFalse(item["threshold_change"])
        self.assertFalse(item["gate_value_change"])
        self.assertFalse(item["admits_anything"])
        self.assertFalse(item["changes_admission_rule"])
        self.assertEqual(list(item["reason_codes_added"]), list(tool.GATE_REASON_CODES))
        revision_history = self.protocol["revision_history"]
        superseded_entries = [
            row for row in revision_history["entries"] if row["status"] == "SUPERSEDED"
        ]
        self.assertEqual(len(superseded_entries), 1)
        self.assertEqual(superseded_entries[0]["byte_sha256"], tool.SUPERSEDED_V2_BYTE_SHA256)
        self.assertEqual(superseded_entries[0]["object"], tool.HISTORY_OBJECT)
        current = [
            row for row in revision_history["entries"] if row["status"] == "CURRENT"
        ]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["node_closure_value"], "CONDITIONAL")

    def test_conditional_closure_blocks_consumption_on_any_failing_gate(self):
        gates = self.protocol["layers"]["layer_b_exact_context_estimate_admissibility"][
            "admissibility_gates"
        ]
        # A synthetic node answer that satisfies every gate closes; failing any
        # single gate leaves the node open with that gate's reason code.
        satisfied = {
            "support_source_key_equals_requested_key": True,
            "support_borrowed_from_other_keys": False,
            "report_pooling_level_always": True,
            "support.effective_sample_size": 20,
            "support.distinct_hands": 20,
            "pooling.level": "L1_STACK_POOL",
            "uncertainty": {"ci": [0.1, 0.2]},
            "maximum_absolute_ece": 0.05,
            "maximum_ece_delta_vs_active": 0.02,
            "unresolved_frontier": False,
        }

        def evaluate(answer):
            failing = []
            if not answer["support_source_key_equals_requested_key"] or answer[
                "support_borrowed_from_other_keys"
            ]:
                failing.append("REFUSED_EXACT_KEY_IDENTITY")
            if not answer["report_pooling_level_always"]:
                failing.append("REFUSED_POOLING_PROVENANCE")
            if answer["pooling.level"] not in {"L0_EXACT_KEY", "L1_STACK_POOL", "L2_POT_POOL",
                                               "L3_RUNTIME_SUPPORT_CONTEXT",
                                               "L4_POSITION_PRICE_PRIOR"}:
                failing.append("REFUSED_POOLING_LEVEL")
            if (
                answer["support.effective_sample_size"] != answer["support.distinct_hands"]
                or answer["support.distinct_hands"] < 20
            ):
                failing.append("REFUSED_EFFECTIVE_SAMPLE_SIZE")
            if not answer["uncertainty"]:
                failing.append("REFUSED_UNCERTAINTY")
            if (
                answer["maximum_absolute_ece"] > 0.05
                or answer["maximum_ece_delta_vs_active"] > 0.02
            ):
                failing.append("REFUSED_CALIBRATION")
            if answer["unresolved_frontier"]:
                failing.append("REFUSED_RAISE_SIZING_FRONTIER")
            return failing

        self.assertEqual(evaluate(dict(satisfied)), [])
        self.assertEqual(len(gates), 7)
        for key, value, expected in (
            ("support_source_key_equals_requested_key", False, "REFUSED_EXACT_KEY_IDENTITY"),
            ("report_pooling_level_always", False, "REFUSED_POOLING_PROVENANCE"),
            ("pooling.level", "L9_UNKNOWN", "REFUSED_POOLING_LEVEL"),
            ("support.distinct_hands", 5, "REFUSED_EFFECTIVE_SAMPLE_SIZE"),
            ("uncertainty", {}, "REFUSED_UNCERTAINTY"),
            ("maximum_absolute_ece", 0.5, "REFUSED_CALIBRATION"),
            ("unresolved_frontier", True, "REFUSED_RAISE_SIZING_FRONTIER"),
        ):
            with self.subTest(failing_gate=expected):
                broken = dict(satisfied)
                broken[key] = value
                self.assertIn(expected, evaluate(broken))
        reason_codes = {row["reason_code"] for row in gates}
        for code in (
            "REFUSED_EXACT_KEY_IDENTITY",
            "REFUSED_POOLING_PROVENANCE",
            "REFUSED_POOLING_LEVEL",
            "REFUSED_EFFECTIVE_SAMPLE_SIZE",
            "REFUSED_UNCERTAINTY",
            "REFUSED_CALIBRATION",
            "REFUSED_RAISE_SIZING_FRONTIER",
        ):
            self.assertIn(code, reason_codes)

    def test_deterministic_regeneration_matches_the_persisted_revision(self):
        rebuilt = tool.build(authored_at=self.protocol["authored_at"])
        self.assertEqual(tool.serialize(rebuilt), self.protocol_bytes)
        self.assertEqual(
            stable_hash(rebuilt), self.index[tool.NAME]["canonical_payload_sha256"]
        )

    def test_check_mode_passes_on_the_persisted_revision(self):
        self.assertEqual(tool.check(), 0)

    def test_docs_pin_the_v2_identity_and_the_v1_traceability(self):
        canonical = self.index[tool.NAME]["canonical_payload_sha256"]
        for relative in (
            "docs/hierarchical-exact-context-validation-protocol.md",
            "docs/hierarchical-exact-context-runtime-contract.md",
            "docs/hierarchical-exact-context-model.md",
        ):
            with self.subTest(doc=relative):
                doc = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("FROZEN_VALIDATION_PROTOCOL_V2.json", doc)
                self.assertIn("poker-hierarchical-frozen-validation-protocol/v2", doc)
                self.assertIn("write_frozen_validation_protocol_v2.py", doc)
                self.assertIn(tool.SUPPORT_ISOLATION_RULE, doc)
                self.assertIn(tool.NODE_CLOSURE_RULE_ID, doc)
                self.assertIn(tool.AMENDMENT_ID, doc)
                for status in ("EXACT_EMPIRICAL_STRONG", "EXACT_HIERARCHICAL_ESTIMATE",
                               "EXACT_UNRESOLVED"):
                    self.assertIn(status, doc)
        for relative in (
            "docs/hierarchical-exact-context-validation-protocol.md",
            "docs/hierarchical-exact-context-runtime-contract.md",
        ):
            with self.subTest(doc=relative):
                doc = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn(self.digest, doc)
                self.assertIn(canonical, doc)
                self.assertIn(tool.V1_BYTE_SHA256, doc)
                self.assertIn(tool.V1_CANONICAL_SHA256, doc)
                self.assertIn(tool.SUPERSEDED_V2_BYTE_SHA256, doc)
                self.assertIn(tool.SUPERSEDED_V2_CANONICAL_SHA256, doc)
                self.assertIn("CONDITIONAL", doc)
                for reason_code in tool.GATE_REASON_CODES:
                    with self.subTest(reason_code=reason_code):
                        self.assertIn(reason_code, doc)


if __name__ == "__main__":
    unittest.main()
