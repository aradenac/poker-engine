#!/usr/bin/env python3
"""#419 contract guard: hierarchical candidate schema + active-pointer invariance.

Deterministic and offline.  It re-derives the contract from the provider code and
the two JSON-Schema files and asserts:

1. the persisted contract artifact is content-addressed and reproducible;
2. the new ``candidate_id`` and the mandatory hierarchical fields are declared by
   the schema at their required locations;
3. provider/schema parity: frozen provider constants equal their schema
   ``const``/``enum`` and real provider outputs validate at every status;
4. the active pointer is unchanged -- ``training/registry.json`` still promotes the
   pinned ``preflop_population_model_v5.json`` reference and never the candidate;
5. the exact-price v1/v2 contracts do not regress.

No VALIDATION/TEST hand, decision or label is ever read, and nothing is mutated.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop import model_a_sizing_hierarchical as H  # noqa: E402
from tools.simulation import issue419_exact_tree_preflight as preflight_tool  # noqa: E402
from tools.training import audit_hierarchical_candidate_contract as tool  # noqa: E402

RESPONSE_REF = {"$ref": "#/$defs/response"}
PREFLIGHT_PATH = (
    ROOT / "analysis/issue419_hierarchical_tree/exact_tree_preflight/EXACT_TREE_PREFLIGHT.json"
)
PREFLIGHT_V2_PATH = (
    ROOT
    / "analysis/issue419_hierarchical_tree/exact_tree_preflight_v2/EXACT_TREE_PREFLIGHT_V2.json"
)


class HierarchicalCandidateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = tool.OUTPUT
        cls.index = json.loads((cls.output / "ARTIFACTS.json").read_text(encoding="utf-8"))
        cls.contract = json.loads(
            (cls.output / tool.CONTRACT_NAME).read_text(encoding="utf-8")
        )
        cls.hierarchical_schema, cls.exact_schema = tool.load_schemas()
        cls.preflight = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))
        cls.preflight_v2 = json.loads(PREFLIGHT_V2_PATH.read_text(encoding="utf-8"))

    # 1. persisted, content-addressed contract artifact --------------------------
    def test_persisted_contract_is_content_addressed_and_reproducible(self):
        self.assertEqual(
            set(self.index), {tool.CONTRACT_NAME, tool.SUMMARY_NAME}
        )
        for name, entry in self.index.items():
            data = (self.output / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"], name)
            self.assertEqual(data, (self.output / entry["object"]).read_bytes(), name)
        self.assertEqual(
            {path.name for path in (self.output / "sha256").iterdir()},
            {Path(entry["object"]).name for entry in self.index.values()},
        )
        entry = self.index[tool.CONTRACT_NAME]
        self.assertEqual(entry["canonical_payload_sha256"], tool.stable_hash(self.contract))
        self.assertEqual(self.contract["schema"], tool.SCHEMA)
        self.assertEqual(self.contract["issue"], 419)
        self.assertEqual(self.contract["candidate_id"], H.CANDIDATE_ID)
        # The contract is byte-stable: rebuilding from the live provider matches.
        rebuilt = tool.build_contract()
        self.assertEqual(tool.stable_hash(rebuilt), tool.stable_hash(self.contract))
        self.assertEqual(rebuilt, self.contract)

    # 2. schema declares the new candidate_id and the mandatory fields -----------
    def test_schema_declares_candidate_id_and_required_hierarchical_fields(self):
        identity = self.hierarchical_schema["$defs"]["identity"]["properties"]
        self.assertEqual(identity["candidate_id"]["const"], H.CANDIDATE_ID)
        self.assertFalse(identity["active_model_replaced"]["const"])
        self.assertEqual(
            self.hierarchical_schema["$defs"]["status"]["enum"], list(H.STATUSES)
        )
        self.assertIn(
            H.STATUS_EXACT_HIERARCHICAL_ESTIMATE,
            self.hierarchical_schema["$defs"]["status"]["enum"],
        )
        for flag in (
            "nearest_price_fallback",
            "nearest_context_fallback",
            "representative_price_fallback",
        ):
            self.assertFalse(self.hierarchical_schema["properties"][flag]["const"], flag)
        required = tool.required_field_report(self.hierarchical_schema)
        self.assertTrue(required["all_present"])
        for field in (
            "status",
            "exact_empirical_observations",
            "effective_sample_size",
            "pooling_level",
            "pooling_source",
            "pooling_support_source",
            "uncertainty",
            "reason_code",
            "reason_codes",
        ):
            self.assertTrue(required[field]["present"], field)
        self.assertTrue(required["reason_codes"]["is_enum"])
        self.assertEqual(
            self.hierarchical_schema["$defs"]["reasonCode"]["enum"],
            list(tool.PROVIDER_REASON_CODES),
        )
        self.assertNotIn(
            H.SUPPORT_LAUNDERING_REASON,
            self.hierarchical_schema["$defs"]["reasonCode"]["enum"],
        )
        self.assertTrue(self.contract["required_hierarchical_fields"]["all_present"])
        # The exact-price identity list still registers the hierarchical candidate.
        enum = self.exact_schema["properties"]["identity"]["properties"]["candidate_id"]["enum"]
        self.assertIn(H.CANDIDATE_ID, enum)

    # 3. provider/schema parity + live validation --------------------------------
    def test_provider_constants_and_outputs_are_schema_parity_verified(self):
        parity = tool.provider_schema_parity(self.hierarchical_schema)
        self.assertTrue(parity["all_match"])
        self.assertEqual(parity["mismatches"], [])
        self.assertTrue(self.contract["provider_schema_parity"]["all_match"])

        scenarios = tool.build_provider_scenarios()
        self.assertEqual(
            sorted({scenario["status"] for scenario in scenarios.values()}),
            sorted(H.STATUSES),
        )
        for name, scenario in scenarios.items():
            with self.subTest(name=name):
                self.assertEqual(
                    tool.schema_errors(self.hierarchical_schema, scenario["candidate"]), []
                )
                self.assertEqual(
                    tool.schema_errors(
                        self.hierarchical_schema, scenario["response"], RESPONSE_REF
                    ),
                    [],
                )

        estimate = scenarios["hierarchical_estimate"]["response"]
        self.assertEqual(estimate["status"], H.STATUS_EXACT_HIERARCHICAL_ESTIMATE)
        self.assertIsNotNone(estimate["pooling"])
        self.assertEqual(estimate["pooling"]["level"], "L1_STACK_POOL")
        self.assertIsNotNone(estimate["uncertainty"])
        self.assertEqual(
            estimate["uncertainty"]["method"], "DIRICHLET_MARGINAL_BETA_CREDIBLE_INTERVAL"
        )
        self.assertGreater(estimate["support"]["effective_sample_size"], 0)

        strong = scenarios["exact_empirical_strong"]["response"]
        self.assertEqual(strong["status"], H.STATUS_EXACT_EMPIRICAL_STRONG)
        self.assertEqual(strong["pooling"]["level"], H.SUPPORT_LEVEL)
        self.assertGreater(strong["support"]["observations"], 0)
        self.assertEqual(strong["support"]["support_isolation_rule"], H.SUPPORT_ISOLATION_RULE)

        unresolved = scenarios["unresolved"]["response"]
        self.assertEqual(unresolved["status"], H.STATUS_EXACT_UNRESOLVED)
        self.assertIn(
            unresolved["unresolved_reason"],
            (
                H.REASON_NO_ADMISSIBLE_POOLING,
                H.REASON_NO_EXACT_SUPPORT_NO_CONTEXT,
                H.REASON_RAISE_SIZING_UNRESOLVED,
            ),
        )
        self.assertIsNone(unresolved["pooling"])

        reported = self.contract["provider_outputs"]
        self.assertTrue(reported["all_valid"])
        self.assertEqual(reported["statuses"], sorted(H.STATUSES))

    # 4. active pointer invariance ----------------------------------------------
    def test_active_pointer_is_unchanged_and_never_the_candidate(self):
        registry_text = tool.REGISTRY_PATH.read_text(encoding="utf-8")
        registry = json.loads(registry_text)
        pointer = tool.active_pointer_report(registry, registry_text)
        self.assertTrue(pointer["pointer_unchanged"])
        self.assertEqual(pointer["promoted_preflop"], tool.PINNED_PROMOTED_PREFLOP)
        self.assertEqual(pointer["promoted_postflop"], tool.PINNED_PROMOTED_POSTFLOP)
        self.assertTrue(pointer["reference_matches_pin"])
        self.assertEqual(pointer["reference_model_sha256"], tool.PINNED_REFERENCE_HASH)
        self.assertEqual(pointer["reference_model_path"], pointer["promoted_preflop"])
        self.assertEqual(pointer["promoted_run"], tool.PINNED_PROMOTED_RUN)
        self.assertFalse(pointer["candidate_mentioned_in_registry"])
        self.assertFalse(pointer["candidate_promoted"])

        recorded = self.contract["active_pointer"]
        self.assertTrue(recorded["pointer_unchanged"])
        self.assertEqual(recorded["promoted_preflop"], tool.PINNED_PROMOTED_PREFLOP)
        self.assertFalse(recorded["candidate_mentioned_in_registry"])
        self.assertFalse(recorded["candidate_promoted"])
        protected = self.contract["protected_files_before_after_sha256"]
        self.assertTrue(protected["unchanged"])
        self.assertEqual(protected["before"], protected["after"])
        self.assertEqual(
            recorded["registry_sha256"],
            protected["before"][str(tool.REGISTRY_PATH.relative_to(tool.ROOT))],
        )

    # 5. exact-price v1/v2 non-regression ---------------------------------------
    def test_exact_price_v1_v2_do_not_regress(self):
        enum = self.exact_schema["properties"]["identity"]["properties"]["candidate_id"]["enum"]
        self.assertIn(tool.exact_price.RUNTIME_CANDIDATE_ID, enum)
        self.assertIn(tool.exact_price.RUNTIME_CANDIDATE_V2_ID, enum)
        self.assertIn(H.CANDIDATE_ID, enum)
        report = tool.exact_price_non_regression(self.exact_schema)
        self.assertTrue(report["non_regressed"])
        self.assertTrue(report["all_valid"])
        self.assertTrue(report["v1_present"])
        self.assertTrue(report["v2_present"])
        self.assertTrue(report["backoff_policy_unchanged"])
        for label in ("v1", "v2"):
            self.assertEqual(report["candidates"][label]["schema_errors"], [], label)
            self.assertEqual(report["candidates"][label]["resolved_status"], "RESOLVED", label)
        recorded = self.contract["exact_price_non_regression"]
        self.assertTrue(recorded["non_regressed"])
        self.assertTrue(recorded["all_valid"])

    # 6. the schema gate is not vacuous -----------------------------------------
    def test_schema_validator_rejects_contract_mutations(self):
        scenario = tool.build_provider_scenarios()["hierarchical_estimate"]
        response = scenario["response"]
        self.assertEqual(
            tool.schema_errors(self.hierarchical_schema, response, RESPONSE_REF), []
        )

        missing_status = copy.deepcopy(response)
        del missing_status["status"]
        self.assertTrue(
            tool.schema_errors(self.hierarchical_schema, missing_status, RESPONSE_REF)
        )

        bad_status = copy.deepcopy(response)
        bad_status["status"] = "EXACT_BOGUS"
        self.assertTrue(
            tool.schema_errors(self.hierarchical_schema, bad_status, RESPONSE_REF)
        )

        bad_ess = copy.deepcopy(response)
        bad_ess["support"]["effective_sample_size"] = "not-a-number"
        self.assertTrue(tool.schema_errors(self.hierarchical_schema, bad_ess, RESPONSE_REF))

        extra_key = copy.deepcopy(response)
        extra_key["unexpected_field"] = 1
        self.assertTrue(tool.schema_errors(self.hierarchical_schema, extra_key, RESPONSE_REF))

        bad_identity = copy.deepcopy(scenario["candidate"])
        bad_identity["identity"]["candidate_id"] = "model-a-preflop-sizing-aware-candidate-v1"
        self.assertTrue(tool.schema_errors(self.hierarchical_schema, bad_identity))

        replacement = copy.deepcopy(scenario["candidate"])
        replacement["identity"]["active_model_replaced"] = True
        self.assertTrue(tool.schema_errors(self.hierarchical_schema, replacement))

    # 7. two-layer provider/schema/preflight parity -----------------------------
    def test_two_layer_fields_parity_provider_schema_preflight(self):
        scenarios = tool.build_provider_scenarios()
        self.assertEqual(
            sorted(scenarios),
            ["exact_empirical_strong", "hierarchical_estimate", "unresolved"],
        )
        for name, scenario in scenarios.items():
            response = scenario["response"]
            with self.subTest(scenario=name):
                # provider -> schema: the machine-readable response validates and
                # the frozen status/reason labels are the schema enum members.
                self.assertEqual(
                    tool.schema_errors(self.hierarchical_schema, response, RESPONSE_REF), []
                )
                self.assertIn(
                    response["status"], self.hierarchical_schema["$defs"]["status"]["enum"]
                )
                self.assertEqual(response["reason_code"], response["status"])

                # Layer A - empirical support. The preflight's `empirical_support`
                # projection is exactly the provider `support` layer, credited at
                # the hand level and never borrowed from another key.
                support = preflight_tool.support_record(response)
                self.assertEqual(support["observations"], response["support"]["observations"])
                self.assertEqual(support["distinct_hands"], response["support"]["distinct_hands"])
                self.assertEqual(
                    support["effective_sample_size"],
                    response["support"]["effective_sample_size"],
                )
                self.assertEqual(
                    response["support"]["effective_sample_size"],
                    float(response["support"]["distinct_hands"]),
                )
                self.assertEqual(support["source_key"], response["support"]["source_key"])
                self.assertEqual(support["source_key"], response["requested_key"])
                self.assertFalse(support["borrowed_from_other_keys"])
                self.assertEqual(support["support_isolation_rule"], H.SUPPORT_ISOLATION_RULE)
                self.assertEqual(
                    support["meets_observation_threshold"],
                    response["support"]["observations"] >= H.MIN_MARGINAL_OBSERVATIONS,
                )
                self.assertEqual(
                    support["meets_distinct_hand_threshold"],
                    response["support"]["distinct_hands"] >= H.MIN_DISTINCT_HANDS,
                )
                self.assertEqual(
                    support["qualifies_as_exact_support"],
                    support["meets_observation_threshold"]
                    and support["meets_distinct_hand_threshold"],
                )

                # Layer B - pooling provenance. The provider `pooling` layer and
                # the preflight `pooling_provenance` projection agree field for
                # field, and an exact-support answer is the only one that counts
                # as exact support.
                pooling = preflight_tool.pooling_record(response)
                if response["pooling"] is None:
                    self.assertIsNone(pooling)
                else:
                    for field in (
                        "level",
                        "source_key",
                        "source_observations",
                        "source_distinct_hands",
                        "source_effective_sample_size",
                        "retained_axes",
                        "pooled_axes",
                    ):
                        self.assertEqual(pooling[field], response["pooling"][field], field)
                    self.assertEqual(
                        pooling["counts_as_exact_support"],
                        response["pooling"]["level"] == H.SUPPORT_LEVEL,
                    )
                    self.assertEqual(
                        response["pooling"]["support_source_key"],
                        response["support"]["source_key"],
                    )

                # Uncertainty obligation (layer B): an answered decision reports
                # its band at the level actually used; an unresolved decision
                # emits none and the preflight reports none either.
                if response["status"] == H.STATUS_EXACT_UNRESOLVED:
                    self.assertIsNone(response["uncertainty"])
                    self.assertIsNone(preflight_tool.uncertainty_record(response))
                else:
                    self.assertIsNotNone(response["uncertainty"])
                    self.assertEqual(
                        response["uncertainty"]["method"],
                        self.hierarchical_schema["$defs"]["response"]["properties"][
                            "uncertainty"
                        ]["properties"]["method"]["const"],
                    )
                    self.assertEqual(
                        response["uncertainty"]["level_used"], response["pooling"]["level"]
                    )
                    self.assertGreater(response["uncertainty"]["effective_sample_size"], 0)
                    self.assertEqual(
                        set(response["uncertainty"]["actions"]), set(response["posterior"])
                    )

                # Admissibility / posterior identity / status: the preflight's
                # structured verdict names the same status and posterior, and
                # carries the layer-B gate vocabulary.
                closure = preflight_tool.admissibility(response)
                self.assertEqual(closure["status"], response["status"])
                self.assertEqual(closure["posterior_present"], response["posterior"] is not None)
                self.assertEqual(closure["rule_id"], preflight_tool.NODE_CLOSURE_RULE_ID)
                identity = preflight_tool.posterior_identity(response)
                self.assertEqual(identity["status"], response["status"])
                self.assertEqual(identity["reason_code"], response["reason_code"])
                self.assertEqual(identity["posterior"], response["posterior"])
                self.assertEqual(
                    identity["posterior_sha256"],
                    None
                    if response["posterior"] is None
                    else H.canonical_sha256(response["posterior"]),
                )

        # The persisted v2 preflight materializes the same two-layer families for
        # every required node, keyed by the exact identity.
        self.assertEqual(self.preflight_v2["schema"], "poker-issue419-exact-tree-preflight/v2")
        for node in self.preflight_v2["nodes"]:
            with self.subTest(node=node["index"]):
                self.assertEqual(
                    node["empirical_support"]["source_key"], node["exact_key"]
                )
                self.assertEqual(
                    node["empirical_support"]["support_isolation_rule"],
                    H.SUPPORT_ISOLATION_RULE,
                )
                self.assertIn(node["posterior_identity"]["status"], H.STATUSES)
                self.assertEqual(
                    node["admissibility_class"],
                    node["node_closure"]["admissibility_class"],
                )
                self.assertEqual(
                    node["node_closure"]["status"], node["posterior_identity"]["status"]
                )
                # A node that is not admissible exact support never claims it.
                if not node["counts_as_exact_support"]:
                    self.assertNotEqual(
                        node["admissibility_class"], H.STATUS_EXACT_EMPIRICAL_STRONG
                    )

    def test_pooled_estimate_is_never_relabelled_exact_empirical_strong(self):
        scenarios = tool.build_provider_scenarios()
        strong = scenarios["exact_empirical_strong"]["response"]
        estimate = scenarios["hierarchical_estimate"]["response"]

        # Layer A is genuinely L0/20-20 and closes as exact empirical support.
        self.assertEqual(strong["status"], H.STATUS_EXACT_EMPIRICAL_STRONG)
        self.assertEqual(strong["pooling"]["level"], H.SUPPORT_LEVEL)
        self.assertGreaterEqual(strong["support"]["observations"], H.MIN_MARGINAL_OBSERVATIONS)
        self.assertGreaterEqual(strong["support"]["distinct_hands"], H.MIN_DISTINCT_HANDS)
        strong_closure = preflight_tool.admissibility(strong)
        self.assertEqual(
            strong_closure["admissibility_class"], H.STATUS_EXACT_EMPIRICAL_STRONG
        )
        self.assertTrue(strong_closure["counts_as_exact_support"])

        # Layer B is a shrunk estimate over a parent level: it is never relabelled.
        self.assertEqual(estimate["status"], H.STATUS_EXACT_HIERARCHICAL_ESTIMATE)
        self.assertNotEqual(estimate["pooling"]["level"], H.SUPPORT_LEVEL)
        estimate_closure = preflight_tool.admissibility(estimate)
        self.assertNotEqual(
            estimate_closure["admissibility_class"], H.STATUS_EXACT_EMPIRICAL_STRONG
        )
        self.assertFalse(estimate_closure["counts_as_exact_support"])
        self.assertTrue(
            estimate_closure["layer_b_gates"]["EXACT_KEY_IDENTITY"]["applies_to_answer"]
        )

        # The provider refuses the relabelling outright: an EXACT_EMPIRICAL_STRONG
        # claim requires pooling.level == L0_EXACT_KEY, which a pooled estimate is
        # not, so validate_response fails closed.
        relabelled = copy.deepcopy(estimate)
        relabelled["status"] = H.STATUS_EXACT_EMPIRICAL_STRONG
        relabelled["reason_code"] = H.STATUS_EXACT_EMPIRICAL_STRONG
        with self.assertRaises(H.HierarchicalSizingError):
            H.validate_response(relabelled)
        relabelled_closure = preflight_tool.admissibility(relabelled)
        self.assertNotEqual(
            relabelled_closure["admissibility_class"], H.STATUS_EXACT_EMPIRICAL_STRONG
        )
        self.assertFalse(relabelled_closure["counts_as_exact_support"])

        # The two labels are distinct members of the frozen status enum.
        self.assertNotEqual(
            H.STATUS_EXACT_HIERARCHICAL_ESTIMATE, H.STATUS_EXACT_EMPIRICAL_STRONG
        )
        self.assertEqual(
            self.hierarchical_schema["$defs"]["status"]["enum"], list(H.STATUSES)
        )


if __name__ == "__main__":
    unittest.main()
