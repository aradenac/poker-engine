#!/usr/bin/env python3
"""Compare Model B profile counts using VALIDATION only.

TEST is intentionally not touched here. The selected K maximizes validation action
log-loss improvement subject to non-negative range improvement; if no candidate
meets the range constraint, the best action improvement is selected and flagged.
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--stake", action="append", default=["100/200"])
    parser.add_argument("--exclude-player", action="append", default=[])
    parser.add_argument("--k", type=int, action="append", required=True)
    parser.add_argument("--action-alpha", type=float, default=1.0)
    parser.add_argument("--range-prior-strength", type=float, default=50.0)
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

    feasible = [c for c in candidates if c["range_log_loss_improvement"] >= 0]
    pool = feasible or candidates
    selected = max(
        pool,
        key=lambda c: (
            c["action_log_loss_improvement"],
            c["range_log_loss_improvement"],
            c["profile_stability_weighted"] if c["profile_stability_weighted"] is not None else -1,
            -c["k"],
        ),
    )
    result = {
        "schema": SCHEMA,
        "selection_split": "VALIDATION",
        "test_used_for_selection": False,
        "selection_rule": "maximize action log-loss improvement subject to non-negative range log-loss improvement; tie-break by range improvement, weighted profile stability, then smaller K",
        "dataset": provenance,
        "candidates": candidates,
        "selected_k": selected["k"],
        "selected_candidate": selected,
        "range_constraint_satisfied_by_any_candidate": bool(feasible),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
