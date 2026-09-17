#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.select_preflop_strategy_validation import select_with_exposure_guard  # noqa: E402

ENVIRONMENTS = [
    "model-b-public-reference-nominal-v1",
    "model-b-public-reference-lower-aggression-v1",
    "model-b-public-reference-higher-aggression-v1",
]


def run_manifest():
    return {
        "contract_version": "2026-09-17.2",
        "identities": {"candidate_id": "candidate-1", "model_b_environment_ids": ENVIRONMENTS},
    }


def report(environment_id: str, *, supported: int, unsupported: int, passed: bool = True):
    total = supported + unsupported
    return {
        "environment": {"environment_id": environment_id},
        "candidate_id": "candidate-1",
        "gate": {"pass": passed},
        "paired": {"observed_delta_bb_per_100": 1.0, "ci95_bb_per_100": [0.1, 1.9]},
        "candidate_coverage": {
            "hero_preflop_decisions": total,
            "supported_decisions": supported,
            "out_of_support_decisions": unsupported,
            "supported_decision_rate": None if total == 0 else supported / total,
            "out_of_support_decision_rate": None if total == 0 else unsupported / total,
        },
        "reference_support_closure": {"support_closure_rate": 0.03, "support_closure_by_street": {}},
        "candidate_reference_support_closure": {"support_closure_rate": 0.03, "support_closure_by_street": {}},
    }


def test_zero_exposure_blocks_without_waiting_for_missing_environment() -> None:
    reports = [
        report(ENVIRONMENTS[0], supported=0, unsupported=4993),
        report(ENVIRONMENTS[2], supported=0, unsupported=5051),
    ]
    selection = select_with_exposure_guard(reports, run_manifest())
    assert selection["outcome"] == "BLOCKED_ZERO_CANDIDATE_EXPOSURE"
    assert selection["performance_gate_interpretable"] is False
    assert selection["test_authorized"] is False
    assert selection["test_consumed"] is False
    assert selection["promotion_authorized"] is False
    validity = selection["candidate_exposure_validity"]
    assert validity["blocked_environments"] == [ENVIRONMENTS[0], ENVIRONMENTS[2]]
    assert validity["missing_environments"] == [ENVIRONMENTS[1]]


def test_positive_exposure_delegates_to_frozen_performance_gate() -> None:
    reports = [report(env, supported=20, unsupported=80, passed=True) for env in ENVIRONMENTS]
    selection = select_with_exposure_guard(reports, run_manifest())
    assert selection["outcome"] == "FREEZE_FINALIST"
    assert selection["test_authorized"] is True
    assert selection["test_consumed"] is False
    assert selection["candidate_exposure_validity"]["status"] == "PASS"


def test_positive_exposure_still_respects_environment_failure() -> None:
    reports = [
        report(ENVIRONMENTS[0], supported=20, unsupported=80, passed=True),
        report(ENVIRONMENTS[1], supported=20, unsupported=80, passed=False),
        report(ENVIRONMENTS[2], supported=20, unsupported=80, passed=True),
    ]
    selection = select_with_exposure_guard(reports, run_manifest())
    assert selection["outcome"] == "RETAIN_REFERENCE"
    assert selection["test_authorized"] is False


def test_missing_environment_without_blocking_exposure_fails_closed() -> None:
    try:
        select_with_exposure_guard(
            [report(ENVIRONMENTS[0], supported=20, unsupported=80)],
            run_manifest(),
        )
    except ValueError as exc:
        assert "incomplete" in str(exc)
    else:
        raise AssertionError("missing Model-B environment must fail closed")


def test_incomplete_coverage_accounting_is_rejected() -> None:
    broken = report(ENVIRONMENTS[0], supported=1, unsupported=1)
    broken["candidate_coverage"]["hero_preflop_decisions"] = 3
    try:
        select_with_exposure_guard([broken], run_manifest())
    except ValueError as exc:
        assert "accounting" in str(exc)
    else:
        raise AssertionError("incomplete candidate coverage must be rejected")


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"Preflop strategy exposure guard tests: {len(tests)} passed")


if __name__ == "__main__":
    main()
