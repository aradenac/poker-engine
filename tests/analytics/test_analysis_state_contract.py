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


if __name__ == "__main__":
    unittest.main()
