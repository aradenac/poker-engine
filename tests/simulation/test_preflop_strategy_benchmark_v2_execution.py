#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.preflop_strategy_benchmark_v2 import (  # noqa: E402
    ENV_REPORT_SCHEMA,
    paired_cluster_bootstrap,
    select_validation,
    summarize_environment_rows,
)


def rows():
    out = []
    deltas = {"h1": [1.0, 3.0], "h2": [-1.0, 1.0]}
    for hand, values in deltas.items():
        for rep, delta in enumerate(values):
            out.append(
                {
                    "scenario_id": f"{hand}-{rep}",
                    "hand_id": hand,
                    "rep": rep,
                    "hero_position": "BTN",
                    "preflop_family": "UNOPENED",
                    "limper_count": 0,
                    "caller_count": 0,
                    "stack_depth_bucket": "GT75_LE125",
                    "delta_bb": delta,
                    "candidate_audit": {
                        "hero_preflop_decisions": 1,
                        "candidate_supported_decisions": 1 if hand == "h1" else 0,
                        "candidate_out_of_support_decisions": 0 if hand == "h1" else 1,
                    },
                    "reference_outcome": {
                        "players_to_flop": 2,
                        "won_without_flop": False,
                        "all_in_preflop": False,
                        "hero_jam_preflop": False,
                        "side_pot": False,
                    },
                    "candidate_outcome": {
                        "players_to_flop": 3,
                        "won_without_flop": False,
                        "all_in_preflop": hand == "h1",
                        "hero_jam_preflop": hand == "h1",
                        "side_pot": False,
                    },
                }
            )
    return out


def report(environment_id: str, passed: bool = True):
    return {
        "schema": ENV_REPORT_SCHEMA,
        "candidate_id": "candidate-1",
        "environment": {"environment_id": environment_id},
        "gate": {"pass": passed},
        "paired": {
            "observed_delta_bb_per_100": 25.0,
            "ci95_bb_per_100": [1.0 if passed else -1.0, 50.0],
        },
        "candidate_coverage": {
            "supported_decision_rate": 0.5,
            "out_of_support_decision_rate": 0.5,
        },
    }


def run_manifest():
    return {
        "contract_version": "fixture",
        "identities": {
            "candidate_id": "candidate-1",
            "model_b_environment_ids": ["nominal", "low", "high"],
        },
    }


def test_paired_bootstrap_clusters_repetitions_by_hand() -> None:
    stats = paired_cluster_bootstrap(rows(), samples=200, seed=7)
    # Cluster means are h1=2bb and h2=0bb, so paired estimate is 1bb/hand.
    assert stats["independent_hands"] == 2
    assert stats["observations"] == 4
    assert stats["repetitions_per_hand"] == 2
    assert stats["observed_delta_bb_per_100"] == 100.0
    assert stats["ci95_bb_per_100"][0] <= 100.0 <= stats["ci95_bb_per_100"][1]


def test_environment_summary_reports_support_and_required_breakdowns() -> None:
    summary = summarize_environment_rows(
        rows(),
        environment={"environment_id": "nominal", "role": "nominal"},
        candidate_id="candidate-1",
        bootstrap_samples=200,
        bootstrap_seed=9,
        threshold=-1000.0,
    )
    assert summary["gate"]["pass"] is True
    assert summary["candidate_coverage"]["hero_preflop_decisions"] == 4
    assert summary["candidate_coverage"]["supported_decisions"] == 2
    assert summary["candidate_coverage"]["out_of_support_decisions"] == 2
    assert summary["candidate_coverage"]["out_of_support_decision_rate"] == 0.5
    assert set(summary["breakdowns"]) == {
        "position",
        "preflop_family",
        "limper_count",
        "caller_count",
        "stack_depth_bucket",
        "reference_outcomes",
        "candidate_outcomes",
    }
    assert summary["breakdowns"]["candidate_outcomes"]["jam_frequency"] == 0.5


def test_validation_selection_requires_every_frozen_environment() -> None:
    selected = select_validation(
        [report("nominal"), report("low"), report("high")],
        run_manifest(),
    )
    assert selected["outcome"] == "FREEZE_FINALIST"
    assert selected["frozen_finalist"] == "candidate-1"
    assert selected["test_authorized"] is True
    assert selected["test_consumed"] is False
    assert selected["promotion_authorized"] is False

    retained = select_validation(
        [report("nominal"), report("low", passed=False), report("high")],
        run_manifest(),
    )
    assert retained["outcome"] == "RETAIN_REFERENCE"
    assert retained["frozen_finalist"] is None
    assert retained["test_authorized"] is False
    assert retained["test_consumed"] is False


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"Preflop strategy benchmark v2 execution tests: {len(tests)} passed")


if __name__ == "__main__":
    main()
