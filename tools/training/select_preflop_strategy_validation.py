#!/usr/bin/env python3
"""Apply the frozen #108 VALIDATION selection only when the candidate was exercised.

The performance gate in the frozen benchmark remains unchanged.  This wrapper
adds a separate validity boundary: a report that executed zero candidate
decisions cannot establish performance, even if candidate/reference deltas are
numerically zero.  A zero-exposure report is sufficient to block the run before
all Model-B environments finish because the all-environment benchmark can no
longer be interpreted as a comparison of the candidate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.simulation.preflop_strategy_benchmark_support_closed import select_validation
from tools.simulation.preflop_strategy_benchmark_v2 import load_json, write_json

SELECTION_SCHEMA = "poker-preflop-strategy-validation-selection/v2"


def _environment_id(report: Mapping[str, Any]) -> str:
    return str((report.get("environment") or {}).get("environment_id") or "")


def _coverage(report: Mapping[str, Any]) -> dict[str, Any]:
    raw = dict(report.get("candidate_coverage") or {})
    hero = int(raw.get("hero_preflop_decisions", 0) or 0)
    supported = int(raw.get("supported_decisions", 0) or 0)
    unsupported = int(raw.get("out_of_support_decisions", 0) or 0)
    if supported < 0 or unsupported < 0 or hero < 0:
        raise ValueError("candidate coverage counts must be non-negative")
    if supported + unsupported != hero:
        raise ValueError("candidate coverage accounting is incomplete")
    return {
        "hero_preflop_decisions": hero,
        "supported_decisions": supported,
        "out_of_support_decisions": unsupported,
        "supported_decision_rate": None if hero == 0 else supported / hero,
        "out_of_support_decision_rate": None if hero == 0 else unsupported / hero,
    }


def select_with_exposure_guard(
    reports: Sequence[Mapping[str, Any]],
    run_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    expected = [str(value) for value in run_manifest["identities"]["model_b_environment_ids"]]
    candidate_id = str(run_manifest["identities"]["candidate_id"])
    by_id: dict[str, Mapping[str, Any]] = {}
    for report in reports:
        environment_id = _environment_id(report)
        if not environment_id or environment_id not in expected:
            raise ValueError(f"unexpected environment report {environment_id!r}")
        if environment_id in by_id:
            raise ValueError(f"duplicate environment report {environment_id}")
        if str(report.get("candidate_id") or "") != candidate_id:
            raise ValueError("environment reports compare different candidates")
        by_id[environment_id] = report

    coverage = {environment_id: _coverage(report) for environment_id, report in by_id.items()}
    blocked = [
        environment_id
        for environment_id, row in coverage.items()
        if row["hero_preflop_decisions"] <= 0 or row["supported_decisions"] <= 0
    ]
    missing = [environment_id for environment_id in expected if environment_id not in by_id]

    if blocked:
        contract_version = str(run_manifest.get("contract_version") or "")
        zero_exposure_outcome = (
            "BLOCKED_NOT_A_PERFORMANCE_RESULT"
            if contract_version == "2026-09-18.3"
            else "BLOCKED_ZERO_CANDIDATE_EXPOSURE"
        )
        performance_pass = {
            environment_id: bool(by_id[environment_id].get("gate", {}).get("pass"))
            for environment_id in by_id
        }
        return {
            "schema": SELECTION_SCHEMA,
            "phase": "VALIDATION",
            "contract_version": run_manifest["contract_version"],
            "candidate_id": candidate_id,
            "environment_gate_rule": "PASS_ALL_PREDECLARED_ENVIRONMENTS_AND_NONZERO_CANDIDATE_EXPOSURE",
            "outcome": zero_exposure_outcome,
            "frozen_finalist": None,
            "test_authorized": False,
            "test_used_for_selection": False,
            "test_consumed": False,
            "promotion_authorized": False,
            "performance_gate_interpretable": False,
            "performance_gate_pass_on_completed_reports": performance_pass,
            "candidate_exposure_validity": {
                "rule": "EACH_COMPLETED_ENVIRONMENT_MUST_EXECUTE_AT_LEAST_ONE_CANDIDATE_DECISION",
                "blocked_environments": blocked,
                "missing_environments": missing,
                "coverage": coverage,
            },
            "interpretation": (
                "Benchmark blocked before strategy selection: at least one completed environment never executed "
                "the frozen candidate, so candidate/reference equality cannot be interpreted as performance evidence."
            ),
            "interpretation_limits": [
                "The frozen performance threshold is unchanged; this is a validity gate, not a post-hoc EV threshold.",
                "A zero-exposure environment compares the reference policy with itself through candidate fallback.",
                "TEST remains unconsumed and active strategy pointers must remain unchanged.",
            ],
        }

    if missing:
        raise ValueError(f"environment report set incomplete: missing {missing}")

    selection = select_validation([by_id[environment_id] for environment_id in expected], run_manifest)
    selection["candidate_exposure_validity"] = {
        "rule": "EACH_COMPLETED_ENVIRONMENT_MUST_EXECUTE_AT_LEAST_ONE_CANDIDATE_DECISION",
        "status": "PASS",
        "coverage": coverage,
    }
    return selection


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    selection = select_with_exposure_guard(
        [load_json(path) for path in args.report],
        load_json(args.run_manifest),
    )
    write_json(args.output, selection)
    print(json.dumps(selection, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
