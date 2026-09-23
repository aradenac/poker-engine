#!/usr/bin/env python3
"""Structure contract for the versioned analysis-state taxonomy (#393 T1).

This pins the canonical `poker-analysis-state/v1` object and its normative
documentation:

- the schema declares exactly the six user-facing states;
- all seven technical dimensions are declared strictly separately;
- `statistical_support` keeps observations/distinct_hands, `error` keeps
  type/retryable;
- the doc forbids ``couverture`` as a primary label and states the seven
  required distinctions plus the D5/D6 rules.

It is a contract/structure test only: it changes no engine or model behavior and
does not depend on a JSON-Schema runtime.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "contracts" / "analytics" / "analysis-state.schema.json"
DOC_PATH = ROOT / "docs" / "analysis-state-contract.md"

EXPECTED_STATES = [
    "ANALYSE_DISPONIBLE",
    "ANALYSE_PARTIELLE",
    "CALCUL_EN_COURS",
    "DONNEES_INSUFFISANTES",
    "SPOT_NON_SUPPORTE",
    "ERREUR_CALCUL",
]

EXPECTED_DIMENSIONS = [
    "computational_status",
    "model_support_status",
    "statistical_support",
    "ev_comparability",
    "recommendation_admissibility",
    "posterior_availability",
    "error",
]

# One canonical machine-readable code per required distinction (schema catalog).
DISTINCTION_CODES = {
    "calcul non terminé": "CALCULATION_PENDING",
    "absence de node": "NODE_ABSENT",
    "support insuffisant": "INSUFFICIENT_SUPPORT",
    "contexte non supporté": "CONTEXT_UNSUPPORTED",
    "recommandation non admise": "RECOMMENDATION_NOT_ADMISSIBLE",
    "erreur worker": "WORKER_ERROR",
    "analyse partielle": "PARTIAL_ANALYSIS",
}

DOC_SECTIONS = [
    "## états de premier niveau",
    "## interdiction de couverture comme libellé principal",
    "## dimensions strictement séparées",
    "## les sept distinctions",
    "## règle d5",
    "## règle d6",
]

POSTERIOR_STATES = {"conditioned", "prior_uninformative", "source_prior_unconditioned", "degenerate"}


def normalize(text: str) -> str:
    """Lowercase and collapse markdown wrapping/quotes for stable phrase checks."""
    lowered = text.lower()
    for char in ("«", "»", "’", "\u2019"):
        lowered = lowered.replace(char, " ")
    return " ".join(lowered.split())


SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
DOC = DOC_PATH.read_text(encoding="utf-8")
DOC_FLAT = normalize(DOC)


class AnalysisStateContract(unittest.TestCase):
    # ---------------------------------------------------------------- schema
    def test_schema_is_versioned_json_object(self):
        self.assertEqual(SCHEMA["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertTrue(SCHEMA["$id"].endswith("contracts/analytics/analysis-state.schema.json"))
        self.assertTrue(SCHEMA["title"])
        self.assertEqual(SCHEMA["type"], "object")
        self.assertIs(SCHEMA.get("additionalProperties"), False)
        self.assertEqual(SCHEMA["properties"]["schema"]["const"], "poker-analysis-state/v1")

    def test_required_set_is_state_plus_all_separated_dimensions(self):
        required = set(SCHEMA["required"])
        expected = {"schema", "state", "reason_codes", *EXPECTED_DIMENSIONS}
        self.assertEqual(required, expected)
        for dimension in EXPECTED_DIMENSIONS:
            self.assertIn(dimension, SCHEMA["properties"], dimension)
        self.assertIn("reason_codes", SCHEMA["properties"])

    def test_declares_exactly_six_top_level_states(self):
        state_enum = SCHEMA["properties"]["state"]["enum"]
        self.assertEqual(state_enum, EXPECTED_STATES)
        self.assertEqual(len(state_enum), 6)
        self.assertEqual(len(set(state_enum)), 6)

    def test_reason_codes_are_machine_readable(self):
        reason_codes = SCHEMA["properties"]["reason_codes"]
        self.assertEqual(reason_codes["type"], "array")
        self.assertEqual(reason_codes["items"]["type"], "string")
        self.assertIs(reason_codes.get("uniqueItems"), True)
        catalog = SCHEMA["$defs"]["reason_code"]["enum"]
        self.assertIn("CALCULATION_PENDING", catalog)
        for code in catalog:
            self.assertRegex(code, r"^[A-Z][A-Z0-9_]*$", code)
        for distinction, code in DISTINCTION_CODES.items():
            self.assertIn(code, catalog, distinction)

    def test_statistical_support_shape(self):
        support = SCHEMA["properties"]["statistical_support"]
        self.assertEqual(support["type"], "object")
        self.assertIs(support.get("additionalProperties"), False)
        self.assertEqual(set(support["required"]), {"observations", "distinct_hands"})
        for field in ("observations", "distinct_hands"):
            self.assertEqual(support["properties"][field]["type"], "integer")
            self.assertEqual(support["properties"][field]["minimum"], 0)

    def test_ev_comparability_and_recommendation_admissibility_are_separate(self):
        ev = SCHEMA["properties"]["ev_comparability"]
        self.assertEqual(set(ev["required"]), {"comparable", "reason"})
        self.assertEqual(ev["properties"]["comparable"]["type"], "boolean")

        admissibility = SCHEMA["properties"]["recommendation_admissibility"]
        self.assertIn("admissible", admissibility["required"])
        self.assertEqual(admissibility["properties"]["admissible"]["type"], "boolean")

    def test_posterior_availability_and_error_shapes(self):
        posterior = SCHEMA["properties"]["posterior_availability"]["enum"]
        self.assertTrue(POSTERIOR_STATES.issubset(set(posterior)), posterior)
        self.assertIn("unavailable", posterior)

        error = SCHEMA["properties"]["error"]
        self.assertEqual(set(error["required"]), {"type", "retryable"})
        self.assertIn("null", error["properties"]["type"]["type"])
        self.assertEqual(error["properties"]["retryable"]["type"], "boolean")

    def test_missing_dimensions_are_explicitly_fail_safe(self):
        # The contract must be able to represent a dimension the producer did
        # not supply, instead of fabricating an optimistic positive value.
        computational = SCHEMA["properties"]["computational_status"]["enum"]
        self.assertIn("NOT_EVALUATED", computational, computational)
        self.assertIn("COMPLETE", computational, computational)
        self.assertIn(
            "NOT_EVALUATED",
            SCHEMA["properties"]["model_support_status"]["enum"],
        )
        # The fail-safe semantics are normative documentation, not just code.
        self.assertIn("fail-safe", DOC_FLAT)
        self.assertIn("not_evaluated", DOC_FLAT)
        self.assertIn("évidence positive explicite", DOC_FLAT)
        self.assertIn("absence de blocker", DOC_FLAT)
        # A concrete fail-safe example documents the missing-dimension shape.
        fail_safe = [
            example
            for example in SCHEMA["examples"]
            if example["computational_status"] == "NOT_EVALUATED"
        ]
        self.assertTrue(fail_safe, "schema must document a fail-safe example")
        self.assertNotEqual(fail_safe[0]["state"], "ANALYSE_DISPONIBLE")
        self.assertNotEqual(fail_safe[0]["posterior_availability"], "conditioned")
        self.assertFalse(fail_safe[0]["recommendation_admissibility"]["admissible"])
        self.assertFalse(fail_safe[0]["ev_comparability"]["comparable"])

    def test_canonical_example_is_consistent(self):
        examples = SCHEMA["examples"]
        self.assertTrue(examples)
        example = examples[0]
        self.assertEqual(set(example), set(SCHEMA["required"]))
        self.assertEqual(example["schema"], "poker-analysis-state/v1")
        self.assertIn(example["state"], EXPECTED_STATES)
        self.assertEqual(
            set(example["statistical_support"]),
            {"observations", "distinct_hands"},
        )

    # ------------------------------------------------------------------- doc
    def test_doc_references_versioned_schema(self):
        self.assertIn("contracts/analytics/analysis-state.schema.json", DOC)
        self.assertIn("poker-analysis-state/v1", DOC)
        for state in EXPECTED_STATES:
            self.assertIn(state, DOC, state)
        for dimension in EXPECTED_DIMENSIONS:
            self.assertIn(dimension, DOC, dimension)

    def test_doc_has_mandatory_sections(self):
        for section in DOC_SECTIONS:
            self.assertIn(section, DOC_FLAT, section)

    def test_doc_forbids_couverture_as_a_primary_label(self):
        self.assertIn("couverture", DOC_FLAT)
        self.assertIn("jamais un libellé principal", DOC_FLAT)
        # The generic fallback must be explicitly rejected.
        self.assertIn("aucune analyse disponible", DOC_FLAT)

    def test_doc_states_the_seven_distinctions(self):
        for distinction in DISTINCTION_CODES:
            self.assertIn(distinction, DOC_FLAT, distinction)

    def test_doc_states_d5_and_d6(self):
        self.assertIn("d5", DOC_FLAT)
        self.assertIn("action observée", DOC_FLAT)
        self.assertIn("range avant/après", DOC_FLAT)
        self.assertIn("alternative ev optimale", DOC_FLAT)

        self.assertIn("d6", DOC_FLAT)
        self.assertIn("recommendation_admissibility.admissible", DOC_FLAT)
        self.assertIn("ev_comparability.comparable", DOC_FLAT)


NODE = shutil.which("node")


def map_state(expression: str) -> dict:
    """Run the real mapper through Node and return the mapped object."""
    script = (
        "const S=require('./src/analytics/analysis-state.js');"
        "process.stdout.write(JSON.stringify(S.mapAnalysisState(" + expression + ")));"
    )
    completed = subprocess.run(
        [NODE, "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


class AnalysisStateFailSafe(unittest.TestCase):
    """Behavioral regression for review #408 blocker 1 (fail-safe mapper).

    These run the real Node mapper so the required cases below are exercised by
    the trainer CI, not only by the JS unit file.
    """

    @classmethod
    def setUpClass(cls):
        if NODE is None:
            raise unittest.SkipTest("node runtime is required for the fail-safe regression")

    def test_empty_input_is_not_available_and_fabricates_nothing(self):
        empty = map_state("{}")
        self.assertNotEqual(empty["state"], "ANALYSE_DISPONIBLE")
        self.assertEqual(empty["state"], "DONNEES_INSUFFISANTES")
        self.assertFalse(empty["recommendation_admissibility"]["admissible"])
        self.assertFalse(empty["ev_comparability"]["comparable"])
        self.assertNotEqual(empty["posterior_availability"], "conditioned")
        self.assertEqual(empty["computational_status"], "NOT_EVALUATED")
        self.assertEqual(empty["model_support_status"], "NOT_EVALUATED")
        self.assertEqual(empty["ev_comparability"]["reason"], "NOT_EVALUATED")
        self.assertEqual(empty["recommendation_admissibility"]["status"], "NOT_EVALUATED")
        # Valid + idempotent against the canonical contract.
        validation = subprocess.run(
            [
                NODE,
                "-e",
                "const S=require('./src/analytics/analysis-state.js');"
                "const a=S.mapAnalysisState({});"
                "process.stdout.write(JSON.stringify({valid:S.validateAnalysisState(a).valid,"
                "idempotent:JSON.stringify(S.mapAnalysisState(a))===JSON.stringify(a)}));",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        flags = json.loads(validation.stdout)
        self.assertTrue(flags["valid"], flags)
        self.assertTrue(flags["idempotent"], flags)

    def test_partial_input_only_promotes_the_proven_dimension(self):
        mapped = map_state("{ev_comparability:{comparable:true,reason:null}}")
        self.assertTrue(mapped["ev_comparability"]["comparable"])
        self.assertFalse(mapped["recommendation_admissibility"]["admissible"])
        self.assertEqual(mapped["recommendation_admissibility"]["status"], "NOT_EVALUATED")
        self.assertNotEqual(mapped["posterior_availability"], "conditioned")
        self.assertEqual(mapped["model_support_status"], "NOT_EVALUATED")

    def test_explicit_positive_evidence_maps_to_available(self):
        covered = map_state("{coverage_state:'COVERED'}")
        self.assertEqual(covered["state"], "ANALYSE_DISPONIBLE")
        self.assertEqual(covered["model_support_status"], "SUPPORTED")

        weak = map_state("{model_support_status:'SUPPORTED'}")
        self.assertNotEqual(weak["state"], "ANALYSE_DISPONIBLE")

    def test_unknown_codes_are_preserved_and_stay_safe(self):
        mapped = map_state("{reason_codes:['FUTURE_TAXONOMY_CODE']}")
        self.assertNotEqual(mapped["state"], "ANALYSE_DISPONIBLE")
        self.assertEqual(mapped["state"], "DONNEES_INSUFFISANTES")
        self.assertIn("FUTURE_TAXONOMY_CODE", mapped["reason_codes"])


if __name__ == "__main__":
    unittest.main()
