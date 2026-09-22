#!/usr/bin/env python3
"""Byte-mirror + exhaustive-code contract for the shared analysis-state mapper (#393 T2).

Pins two independent invariants:

1. ``src/analytics/analysis-state.js`` and ``site/analytics/analysis-state.js``
   are byte-identical, so the served bundle can never drift from the edit source.
2. The exported ``REASON_CODE_MAP`` exhaustively covers every code family the
   taxonomy must absorb: the frozen adapter's ``COVERAGE_STATES`` /
   ``FAIL_CLOSED_STATES`` (#370), the canonical schema catalog and the explicit
   Review/Inbox/Replayer codes, and every code resolves to one of the six
   canonical states.

The mapper is required through Node so the enumeration is taken from the actual
runtime export rather than by re-parsing the source.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "analytics" / "analysis-state.js"
MIRROR = ROOT / "site" / "analytics" / "analysis-state.js"
SCHEMA_PATH = ROOT / "contracts" / "analytics" / "analysis-state.schema.json"

NODE = shutil.which("node")

EXPECTED_STATES = [
    "ANALYSE_DISPONIBLE",
    "ANALYSE_PARTIELLE",
    "CALCUL_EN_COURS",
    "DONNEES_INSUFFISANTES",
    "SPOT_NON_SUPPORTE",
    "ERREUR_CALCUL",
]

REQUIRED_CODES = {
    # coverage_state
    "COVERED",
    "LOW_SUPPORT",
    "UNSUPPORTED",
    "NON_COMPARABLE",
    "ANALYSIS_MISSING",
    "UNCOVERED",
    # frozen adapter fail-closed states (#370)
    "NO_ADMISSIBLE_STRATEGY",
    "EXACT_CONTEXT_ABSENT",
    "EXACT_CONTEXT_MISMATCH",
    "POPULATION_MISMATCH",
    "STRATEGY_MISMATCH",
    "ARTIFACT_IDENTITY_MISMATCH",
    "NON_COMPARABLE_ALTERNATIVES",
    "INVALID_GUIDANCE",
    # trainer / replayer
    "SPOT_NON_COUVERT",
    "ACTIVE_REFERENCE_SCOPE_UNSUPPORTED",
    "PLAYED_ALTERNATIVE_NOT_EVALUATED",
    # Review
    "MISSING_COMPARABLE_EV",
    "NO_COMPARABLE_REVIEW_DETAIL",
    # Inbox
    "MISSING_HH_SOURCE",
    "MISSING_REVIEW_SCORE",
    "REVIEW_SCORE_INCOMPLETE",
    "UNFINISHED_DECISIONS",
    "NO_DECISION_EVENTS",
    "UNSUPPORTED_DECISIONS",
    "NON_COMPARABLE_DECISIONS",
    # Replayer / dashboard EMPTY_STATES
    "NO_HANDS",
    "ANALYSIS_PENDING",
    "ANALYSIS_INCOMPLETE",
    "NO_SIGNIFICANT_LOSS",
    "READY",
}

CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _runtime_enumeration() -> dict:
    if NODE is None:
        raise RuntimeError("node runtime is required for the analysis-state mirror contract")
    script = (
        "const State=require('./src/analytics/analysis-state.js');"
        "const Adapter=require('./src/training/preflop-decision-adapter.js');"
        "process.stdout.write(JSON.stringify({"
        "schema:State.SCHEMA,"
        "states:Object.keys(State.ANALYSIS_STATES),"
        "code_map:State.REASON_CODE_MAP,"
        "coverage:Adapter.COVERAGE_STATES,"
        "fail_closed:Adapter.FAIL_CLOSED_STATES"
        "}));"
    )
    completed = subprocess.run(
        [NODE, "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


RUNTIME = _runtime_enumeration()
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
SCHEMA_CODES = set(SCHEMA["$defs"]["reason_code"]["enum"])


class AnalysisStateMirrorContract(unittest.TestCase):
    # --------------------------------------------------------------- mirror
    def test_source_and_site_copy_are_byte_identical(self):
        self.assertTrue(SOURCE.is_file(), "missing src/analytics/analysis-state.js")
        self.assertTrue(MIRROR.is_file(), "missing site/analytics/analysis-state.js")
        self.assertEqual(SOURCE.read_bytes(), MIRROR.read_bytes())

    # ---------------------------------------------------------- enumeration
    def test_schema_and_six_states(self):
        self.assertEqual(RUNTIME["schema"], "poker-analysis-state/v1")
        self.assertEqual(RUNTIME["states"], EXPECTED_STATES)
        self.assertEqual(len(set(RUNTIME["states"])), 6)

    def test_every_code_resolves_to_exactly_one_canonical_state(self):
        code_map = RUNTIME["code_map"]
        self.assertTrue(code_map)
        states = set(RUNTIME["states"])
        for code, state in code_map.items():
            self.assertRegex(code, CODE_PATTERN, code)
            self.assertIn(
                state,
                states,
                f"code {code} maps to a non-canonical state {state}",
            )

    def test_covers_frozen_adapter_enums(self):
        code_map = RUNTIME["code_map"]
        for code in RUNTIME["coverage"]:
            self.assertIn(code, code_map, f"adapter coverage code not mapped: {code}")
        for code in RUNTIME["fail_closed"]:
            self.assertIn(code, code_map, f"adapter fail-closed code not mapped: {code}")
        # The adapter enum itself must stay the canonical taxonomy source.
        self.assertEqual(
            set(RUNTIME["coverage"]),
            {"COVERED", "LOW_SUPPORT", "UNSUPPORTED", "NON_COMPARABLE", "ANALYSIS_MISSING", "UNCOVERED"},
        )
        self.assertEqual(
            set(RUNTIME["fail_closed"]),
            {
                "NO_ADMISSIBLE_STRATEGY",
                "EXACT_CONTEXT_ABSENT",
                "EXACT_CONTEXT_MISMATCH",
                "POPULATION_MISMATCH",
                "STRATEGY_MISMATCH",
                "ARTIFACT_IDENTITY_MISMATCH",
                "LOW_SUPPORT",
                "UNCOVERED",
                "NON_COMPARABLE_ALTERNATIVES",
                "INVALID_GUIDANCE",
            },
        )

    def test_covers_schema_catalog_and_required_review_inbox_replayer_codes(self):
        code_map = set(RUNTIME["code_map"])
        missing_schema = SCHEMA_CODES - code_map
        self.assertEqual(missing_schema, set(), f"schema codes not mapped: {sorted(missing_schema)}")
        missing_required = REQUIRED_CODES - code_map
        self.assertEqual(missing_required, set(), f"required codes not mapped: {sorted(missing_required)}")


if __name__ == "__main__":
    unittest.main()
