#!/usr/bin/env python3
"""Compare a refreshed Model B candidate with the promoted incumbent on one holdout.

Selection remains VALIDATION-only. TEST metrics are persisted for final diagnosis but
must not alter the already determined promotion/rejection decision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(report: dict, split: str) -> dict:
    row = report[split]
    return {
        "action_n": row["actions"]["n"],
        "action_log_loss": row["actions"]["log_loss"],
        "action_improvement": row["actions"]["log_loss_improvement"],
        "action_ece": row["actions"]["ece_confidence"],
        "range_n": row["range"]["n"],
        "range_log_loss": row["range"]["log_loss"],
        "range_improvement": row["range"]["log_loss_improvement"],
        "sizing_n": row["sizing"]["n"],
        "sizing_inside_p10_p90": row["sizing"]["inside_training_p10_p90_fraction"],
        "sizing_above_p99": row["sizing"]["above_training_p99_fraction"],
        "profile_stability_weighted": row["profile_stability"]["appearance_weighted_stable_fraction"],
    }


def delta(candidate: dict, incumbent: dict) -> dict:
    keys = (
        "action_log_loss", "action_improvement", "action_ece",
        "range_log_loss", "range_improvement",
        "sizing_inside_p10_p90", "sizing_above_p99",
        "profile_stability_weighted",
    )
    return {
        key: (candidate[key] - incumbent[key])
        if candidate[key] is not None and incumbent[key] is not None else None
        for key in keys
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--selection", required=True, type=Path)
    p.add_argument("--candidate", required=True, type=Path)
    p.add_argument("--incumbent", required=True, type=Path)
    p.add_argument("--run-dir", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()

    selection = load(args.selection)
    candidate = load(args.candidate)
    incumbent = load(args.incumbent)
    assert selection["selection_split"] == "VALIDATION"
    assert selection["test_used_for_selection"] is False
    selected_k = int(selection["selected_k"])
    selected = next(row for row in selection["candidates"] if int(row["k"]) == selected_k)
    weights = [float(x) for x in selected["profile_weights"]]
    no_micro = min(weights) >= 0.05

    splits = {}
    for split in ("validation", "test"):
        c = snapshot(candidate, split)
        i = snapshot(incumbent, split)
        assert candidate[split]["hands"] == incumbent[split]["hands"]
        assert c["action_n"] == i["action_n"]
        assert c["range_n"] == i["range_n"]
        assert c["sizing_n"] == i["sizing_n"]
        splits[split] = {
            "hands": candidate[split]["hands"],
            "candidate": c,
            "incumbent": i,
            "candidate_minus_incumbent": delta(c, i),
        }

    # Predeclared promotion decision: only VALIDATION may decide structure/promotion.
    v = splits["validation"]
    vd = v["candidate_minus_incumbent"]
    validation_competitive = (
        vd["action_log_loss"] <= 0.0
        and vd["range_log_loss"] <= 0.0
        and v["candidate"]["action_ece"] <= 0.05
        and v["candidate"]["action_improvement"] >= 0.015
        and v["candidate"]["range_improvement"] > 0.0
    )
    decision = "PROMOTE" if no_micro and validation_competitive else "RETAIN_INCUMBENT"

    root = args.run_dir
    artifacts = {}
    for key, rel in {
        "features": "features/player_features.json",
        "selection": "evaluation/profile_count_selection.json",
        "candidate_summary": "model/summary.json",
        "candidate_profiles": "model/profiles.json",
        "candidate_ranges": "model/preflop_ranges.json",
        "candidate_actions": "model/postflop_actions.json",
        "candidate_sizing": "model/sizing.json",
        "candidate_holdout": "evaluation/candidate_holdout.json",
        "incumbent_holdout": "evaluation/incumbent_holdout.json",
    }.items():
        path = root / rel
        artifacts[f"{key}_sha256"] = sha256(path)

    report = {
        "schema": "independent-model-b-paired-refresh/v1",
        "cycle": root.name,
        "independence_contract": "Hand histories only; no Model A EV, policy, recommendation or engine outputs used.",
        "selection": {
            "selected_k": selected_k,
            "profile_weights": weights,
            "selection_split": "VALIDATION",
            "test_used_for_selection": False,
            "no_micro_profile": no_micro,
        },
        "comparison_contract": "Candidate and incumbent are evaluated by the same evaluator on identical enlarged VALIDATION/TEST hands and observation sets.",
        "splits": splits,
        "decision": decision,
        "decision_basis": "VALIDATION candidate must not worsen aggregate action or range log-loss, retain positive action/range signal and ECE <= 0.05, and satisfy the >=5% profile-weight guard. TEST is diagnostic only after this decision.",
        "artifacts": artifacts,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
