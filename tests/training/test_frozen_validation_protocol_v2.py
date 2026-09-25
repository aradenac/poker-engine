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
            with self.subTest(artifact=name):
                data = (tool.OUT / name).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"])
                self.assertEqual(data, (tool.OUT / entry["object"]).read_bytes())
        self.assertEqual(
            {p.name for p in (tool.OUT / "sha256").iterdir()},
            {Path(entry["object"]).name for entry in self.index.values()},
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
        self.assertFalse(layer["counts_as_a_closed_exact_tree_node"])
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
        gates = layer["admissibility_gates"]
        self.assertEqual(sorted(gates), ["calibration", "pooling", "sizing"])
        self.assertEqual(gates["calibration"]["maximum_absolute_ece"], 0.05)
        self.assertEqual(gates["calibration"]["maximum_ece_delta_vs_active"], 0.02)
        self.assertTrue(gates["pooling"]["support_source_key_equals_requested_key"])
        self.assertEqual(gates["sizing"]["policy"], "exact-support-only")
        self.assertIn("representative raise price", gates["sizing"]["forbidden"])

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
        self.assertIn("required_tree_complete", rule["tree_closure"])
        self.assertEqual(
            rule["issue367_consumption"]["rule_id"],
            "ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE",
        )
        self.assertFalse(rule["issue367_consumption"]["authorized_at_this_revision"])
        self.assertTrue(
            rule["issue367_consumption"]["not_authorized_by_a_single_admissible_node"]
        )

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


if __name__ == "__main__":
    unittest.main()
