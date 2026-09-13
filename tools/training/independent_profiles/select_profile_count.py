#!/usr/bin/env python3
"""Compare Model B profile counts using VALIDATION only.

TEST is intentionally not touched here. Selection first applies explicit structural
VALIDATION constraints (range signal, profile balance, profile stability), then
maximizes action log-loss improvement inside the feasible set. This prevents a tiny
action-only gain from selecting unstable or undersupported micro-profiles.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path

from tools.datasets.build_hand_history_increment import split_for
from tools.training.independent_profiles.build_player_features import merge_archives
from tools.training.independent_profiles.build_model_b import build_behavior_tables, fit_profiles
from tools.training.independent_profiles.evaluate_model_b import evaluate_split, load

SCHEMA = "independent-opponent-model-b-profile-count-selection/v1"


def choose_candidate(
    candidates: list[dict],
    *,
    min_profile_weight: float = 0.0,
    min_weighted_stability: float = 0.0,
) -> tuple[dict, list[dict]]:
    """Return selected candidate and the structurally feasible subset.

    The constraints are evaluated on VALIDATION-only quantities. If no candidate
    satisfies every requested constraint, selection fails instead of silently
    relaxing a promotion guard.
    """
    feasible = []
    for c in candidates:
        stability = c.get("profile_stability_weighted")
        if c["range_log_loss_improvement"] < 0:
            continue
        if c["minimum_profile_weight"] < min_profile_weight:
            continue
        if stability is None or stability < min_weighted_stability:
            continue
        feasible.append(c)
    if not feasible:
        raise ValueError(
            "no profile-count candidate satisfies VALIDATION structural constraints: "
            f"min_profile_weight={min_profile_weight}, "
            f"min_weighted_stability={min_weighted_stability}"
        )
    selected = max(
        feasible,
        key=lambda c: (
            c["action_log_loss_improvement"],
            c["range_log_loss_improvement"],
            c["profile_stability_weighted"],
            -c["k"],
        ),
    )
    return selected, feasible


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--stake", action="append", default=["100/200"])
    parser.add_argument("--exclude-player", action="append", default=[])
    parser.add_argument("--k", type=int, action="append", required=True)
    parser.add_argument("--action-alpha", type=float, default=1.0)
    parser.add_argument("--range-prior-strength", type=float, default=50.0)
    parser.add_argument("--min-profile-weight", type=float, default=0.0)
    parser.add_argument("--min-weighted-stability", type=float, default=0.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    feature_doc = load(args.features)
    by_id, provenance = merge_archives(args.archive, set(args.stake))
    records = list(by_id.values())
    train_records = [r for r in records if split_for(r.hand_id) == "TRAIN"]
    excluded = set(args.exclude_player)

    candidates = []
    for k in sorted(set(args.k)):
        profiles = fit_profiles(feature_doc, k)
        ranges, actions, sizings, audit = build_behavior_tables(
            train_records, profiles["player_profile"], excluded
        )
        validation = evaluate_split(
            records,
            "VALIDATION",
            feature_doc,
            profiles,
            ranges,
            actions,
            sizings,
            excluded,
            args.action_alpha,
            args.range_prior_strength,
        )
        candidates.append({
            "k": k,
            "profile_weights": {str(p["profile"]): p["appearance_weight"] for p in profiles["profiles"]},
            "minimum_profile_weight": min(p["appearance_weight"] for p in profiles["profiles"]),
            "action_n": validation["actions"]["n"],
            "action_log_loss": validation["actions"]["log_loss"],
            "action_fallback_log_loss": validation["actions"]["street_mode_fallback_log_loss"],
            "action_log_loss_improvement": validation["actions"]["log_loss_improvement"],
            "action_ece": validation["actions"]["ece_confidence"],
            "range_n": validation["range"]["n"],
            "range_log_loss": validation["range"]["log_loss"],
            "range_prior_log_loss": validation["range"]["combinatorial_prior_log_loss"],
            "range_log_loss_improvement": validation["range"]["log_loss_improvement"],
            "profile_stability_players": validation["profile_stability"]["players_evaluated"],
            "profile_stability": validation["profile_stability"]["stable_fraction"],
            "profile_stability_weighted": validation["profile_stability"]["appearance_weighted_stable_fraction"],
            "train_audit": audit,
        })
        del profiles, ranges, actions, sizings, validation
        gc.collect()

    selected, feasible = choose_candidate(
        candidates,
        min_profile_weight=args.min_profile_weight,
        min_weighted_stability=args.min_weighted_stability,
    )
    feasible_ks = {c["k"] for c in feasible}
    for candidate in candidates:
        candidate["structurally_feasible"] = candidate["k"] in feasible_ks

    result = {
        "schema": SCHEMA,
        "selection_split": "VALIDATION",
        "test_used_for_selection": False,
        "selection_rule": "filter by non-negative range improvement, minimum profile weight and minimum weighted profile stability; maximize action log-loss improvement among feasible candidates; tie-break by range improvement, stability, then smaller K",
        "selection_constraints": {
            "range_log_loss_improvement_min": 0.0,
            "minimum_profile_weight": args.min_profile_weight,
            "minimum_weighted_profile_stability": args.min_weighted_stability,
        },
        "dataset": provenance,
        "candidates": candidates,
        "selected_k": selected["k"],
        "selected_candidate": selected,
        "feasible_k": sorted(feasible_ks),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
