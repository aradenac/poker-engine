#!/usr/bin/env python3
"""Deterministic synthetic benchmark for #198 preparatory paired/adaptive EV search.

This intentionally does not consume certified HH, VALIDATION, TEST, #107/#108
artifacts, or the frozen scientific engine. It isolates Monte Carlo mechanics:
historical candidate-dependent seeds versus CRN pairing and deterministic
adaptive elimination.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.paired_adaptive_preflop_ev import (
    AdaptiveBudget,
    run_fixed_historical,
    run_paired_search,
)

CANDIDATES = {
    "A": {"true_ev": 0.300, "sensitivity": 0.00},
    "B": {"true_ev": 0.295, "sensitivity": 0.08},
    "C": {"true_ev": 0.050, "sensitivity": 0.20},
    "D": {"true_ev": -0.400, "sensitivity": 0.30},
}


def world_factory(public_context, decision_id, sample_index, seed):
    del public_context, decision_id
    rng = random.Random(seed)
    return {
        "sample_index": sample_index,
        "common_shock": rng.gauss(0.0, 1.2),
        "response_tilt": rng.gauss(0.0, 0.5),
    }


def paired_ev(world, candidate_id, payload):
    del candidate_id
    return (
        payload["true_ev"]
        + world["common_shock"]
        + payload["sensitivity"] * world["response_tilt"]
    )


def legacy_ev(candidate_id, payload, sample_index, seed):
    del candidate_id, sample_index
    rng = random.Random(seed)
    return (
        payload["true_ev"]
        + rng.gauss(0.0, 1.2)
        + payload["sensitivity"] * rng.gauss(0.0, 0.5)
    )


def summarize(reports):
    selected = [report["selected_id"] for report in reports]
    rollouts = [report["search"]["rollout_budget_used"] for report in reports]
    delta_variances = [
        report["pairwise_deltas"]["A__minus__B"]["variance_bb2"] for report in reports
    ]
    return {
        "replicates": len(reports),
        "true_best_id": "A",
        "true_best_selection_rate": sum(item == "A" for item in selected) / len(selected),
        "mean_rollouts": statistics.fmean(rollouts),
        "min_rollouts": min(rollouts),
        "max_rollouts": max(rollouts),
        "mean_A_minus_B_sample_variance_bb2": statistics.fmean(delta_variances),
    }


def benchmark(replicates: int = 64) -> dict:
    fixed = []
    paired = []
    adaptive = []
    for replicate in range(replicates):
        base_seed = f"synthetic-{replicate}"
        decision_id = f"synthetic:{replicate}"
        fixed.append(
            run_fixed_historical(
                CANDIDATES,
                evaluator=legacy_ev,
                base_seed=base_seed,
                samples_per_alternative=32,
            )
        )
        paired.append(
            run_paired_search(
                CANDIDATES,
                decision_id=decision_id,
                public_context={"position": "BTN", "known_board": []},
                world_factory=world_factory,
                evaluator=paired_ev,
                base_seed=base_seed,
                budget=AdaptiveBudget(
                    initial_samples_per_alternative=8,
                    max_samples_per_alternative=32,
                    batch_size=8,
                    max_total_rollouts=128,
                ),
                adaptive=False,
            )
        )
        adaptive.append(
            run_paired_search(
                CANDIDATES,
                decision_id=decision_id,
                public_context={"position": "BTN", "known_board": []},
                world_factory=world_factory,
                evaluator=paired_ev,
                base_seed=base_seed,
                budget=AdaptiveBudget(
                    initial_samples_per_alternative=8,
                    max_samples_per_alternative=32,
                    batch_size=8,
                    max_total_rollouts=128,
                ),
                adaptive=True,
            )
        )
    result = {
        "schema": "paired-adaptive-preflop-ev-synthetic-benchmark/v1",
        "scientific_effect": "NONE_PREPARATORY",
        "corpus": "synthetic/local",
        "replicates": replicates,
        "candidate_truth_bb": {
            candidate_id: payload["true_ev"] for candidate_id, payload in CANDIDATES.items()
        },
        "configuration": {
            "fixed_samples_per_alternative": 32,
            "paired_initial_samples_per_alternative": 8,
            "paired_max_samples_per_alternative": 32,
            "paired_batch_size": 8,
            "paired_max_total_rollouts": 128,
            "selection_stability_metric": "fraction selecting known synthetic optimum A",
            "delta_variance_metric": "sample variance of index-matched A-B delta; CRN only in paired modes",
        },
        "modes": {
            "fixed_historical": summarize(fixed),
            "paired_fixed": summarize(paired),
            "paired_adaptive": summarize(adaptive),
        },
    }
    result["comparisons"] = {
        "paired_fixed_vs_fixed": {
            "rollout_ratio": result["modes"]["paired_fixed"]["mean_rollouts"]
            / result["modes"]["fixed_historical"]["mean_rollouts"],
            "delta_variance_ratio": result["modes"]["paired_fixed"][
                "mean_A_minus_B_sample_variance_bb2"
            ]
            / result["modes"]["fixed_historical"]["mean_A_minus_B_sample_variance_bb2"],
        },
        "paired_adaptive_vs_fixed": {
            "rollout_ratio": result["modes"]["paired_adaptive"]["mean_rollouts"]
            / result["modes"]["fixed_historical"]["mean_rollouts"],
            "delta_variance_ratio": result["modes"]["paired_adaptive"][
                "mean_A_minus_B_sample_variance_bb2"
            ]
            / result["modes"]["fixed_historical"]["mean_A_minus_B_sample_variance_bb2"],
        },
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replicates", type=int, default=64)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.replicates <= 0:
        raise SystemExit("--replicates must be positive")
    result = benchmark(args.replicates)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
