#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.preflop_strategy_benchmark_support_closed import (  # noqa: E402
    _aggregate_support_audits,
    select_validation,
)

ENVIRONMENTS = [
    "model-b-public-reference-nominal-v1",
    "model-b-public-reference-lower-aggression-v1",
    "model-b-public-reference-higher-aggression-v1",
]


def audit(hero: int, exact: int, fallback: int, *, flop: int = 0, turn: int = 0):
    return {
        "hero_decisions": hero,
        "exact_model_a_decisions": exact,
        "support_closure_decisions": fallback,
        "support_closure_by_street": {"preflop": 0, "flop": flop, "turn": turn, "river": 0},
        "support_closure_reasons": {"missing exact postflop Model-A node": fallback} if fallback else {},
    }


def test_support_audit_aggregation_is_complete_and_by_street() -> None:
    rows = [
        {"reference_support_audit": audit(3, 2, 1, flop=1)},
        {"reference_support_audit": audit(4, 3, 1, turn=1)},
    ]
    out = _aggregate_support_audits(rows, "reference_support_audit")
    assert out["hero_decisions"] == 7
    assert out["exact_model_a_decisions"] == 5
    assert out["support_closure_decisions"] == 2
    assert out["support_closure_rate"] == 2 / 7
    assert out["support_closure_by_street"]["flop"] == 1
    assert out["support_closure_by_street"]["turn"] == 1
    assert out["nearest_context_substitution"] is False


def report(environment_id: str, passed: bool):
    return {
        "environment": {"environment_id": environment_id},
        "candidate_id": "candidate-1",
        "gate": {"pass": passed},
        "paired": {"observed_delta_bb_per_100": 1.0, "ci95_bb_per_100": [0.1, 1.9]},
        "candidate_coverage": {"supported_decision_rate": 0.2, "out_of_support_decision_rate": 0.8},
        "reference_support_closure": {"support_closure_rate": 0.03, "support_closure_by_street": {"flop": 3}},
        "candidate_reference_support_closure": {"support_closure_rate": 0.04, "support_closure_by_street": {"flop": 4}},
    }


def run_manifest():
    return {
        "contract_version": "2026-09-17.2",
        "identities": {"candidate_id": "candidate-1", "model_b_environment_ids": ENVIRONMENTS},
    }


def test_selection_preserves_all_environment_gate_and_closure_disclosure() -> None:
    selection = select_validation([report(env, True) for env in ENVIRONMENTS], run_manifest())
    assert selection["outcome"] == "FREEZE_FINALIST"
    assert selection["test_authorized"] is True
    assert selection["test_consumed"] is False
    assert selection["promotion_authorized"] is False
    assert set(selection["reference_support_closure"]) == set(ENVIRONMENTS)
    assert selection["reference_support_closure"][ENVIRONMENTS[0]]["reference_rate"] == 0.03


def test_one_environment_failure_retains_reference() -> None:
    reports = [report(ENVIRONMENTS[0], True), report(ENVIRONMENTS[1], False), report(ENVIRONMENTS[2], True)]
    selection = select_validation(reports, run_manifest())
    assert selection["outcome"] == "RETAIN_REFERENCE"
    assert selection["test_authorized"] is False
    assert selection["test_consumed"] is False


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"Support-closed benchmark tests: {len(tests)} passed")


if __name__ == "__main__":
    main()
