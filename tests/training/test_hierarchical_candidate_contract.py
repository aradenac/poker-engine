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
from tools.training import audit_hierarchical_candidate_contract as tool  # noqa: E402

RESPONSE_REF = {"$ref": "#/$defs/response"}


class HierarchicalCandidateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = tool.OUTPUT
        cls.index = json.loads((cls.output / "ARTIFACTS.json").read_text(encoding="utf-8"))
        cls.contract = json.loads(
            (cls.output / tool.CONTRACT_NAME).read_text(encoding="utf-8")
        )
        cls.hierarchical_schema, cls.exact_schema = tool.load_schemas()

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


if __name__ == "__main__":
    unittest.main()
