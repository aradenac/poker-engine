#!/usr/bin/env python3
"""Build a versioned Model-B candidate whose preflop ranges treat hidden cards as latent.

To isolate issue #103, profile assignments and postflop action/sizing tables are
held byte-identical to the incumbent Model-B bundle.  They were already fitted
from TRAIN only.  Only the preflop range component is rebuilt from the certified
target population.  New/unseen players use the incumbent TRAIN cold-start
profile.  Later issue #104 may change action policies independently.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from tools.training.independent_profiles.reveal_aware_ranges import (
    build_from_records,
    certified_records,
    sha256_file,
)

MODEL_SCHEMA = "independent-opponent-model-b/v3-reveal-aware-candidate"
CONTRACT_SCHEMA = "independent-opponent-model-b-prediction-contract/v2"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_candidate(
    incumbent_dir: Path,
    archives: list[Path],
    certification: Path,
    stakes: set[str],
    excluded_players: set[str],
    output_dir: Path,
    *,
    backoff_min_observations: int,
    prior_strength: float,
    action_prior_strength: float,
) -> dict:
    profiles_path = incumbent_dir / "profiles.json"
    profiles = load(profiles_path)
    records, population = certified_records(archives, stakes, certification)
    ranges, sensitivity, audit = build_from_records(
        records,
        profiles,
        excluded_players,
        backoff_min_observations=backoff_min_observations,
        prior_strength=prior_strength,
        action_prior_strength=action_prior_strength,
    )
    for doc in (ranges, sensitivity, audit):
        doc["population"] = population
        doc["profiles_sha256"] = sha256_file(profiles_path)

    model_dir = output_dir / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    for name in ("profiles.json", "postflop_actions.json", "sizing.json"):
        shutil.copy2(incumbent_dir / name, model_dir / name)
    write(model_dir / "preflop_ranges.json", ranges)
    write(model_dir / "reveal_sensitivity.json", sensitivity)
    write(model_dir / "reveal_audit.json", audit)

    contract = {
        "schema": CONTRACT_SCHEMA,
        "model_schema": MODEL_SCHEMA,
        "context_compatibility": "same Model-B RANGE_LEVELS columns as v2; FOLDER is an explicit preflop_role extension for latent observations",
        "profile_assignment": {
            "known_player": "incumbent TRAIN-derived deterministic profile (frozen for issue #103 isolation)",
            "cold_start": "incumbent profile with largest TRAIN appearance_weight",
        },
        "preflop_range": {
            "selection": "finest hierarchy node with n >= backoff_min_observations, else ALL",
            "posterior": "existing range_probability consumer over expected latent counts plus the configured combinatorial prior",
            "count_semantics": "fractional expected hand-class counts; revealed_counts remain separately auditable",
            "fit_split": "TRAIN",
            "prior_strength": prior_strength,
            "action_prior_strength": action_prior_strength,
            "hidden_cards": "never assigned observed labels; posterior mass derives only from aggregate TRAIN action/revelation evidence",
            "reveal_bias": "missingness is not assumed identifiable; decision-signal powers 0.0/0.5/1.0 are reported as sensitivity variants",
        },
        "postflop_action": {"status": "BYTE_IDENTICAL_TO_INCUMBENT_V2"},
        "sizing": {"status": "BYTE_IDENTICAL_TO_INCUMBENT_V2"},
        "future_information_rule": "eventual TRAIN revelations may fit aggregate parameters; a runtime decision never receives a card before its actual reveal event",
    }
    write(model_dir / "prediction_contract.json", contract)

    summary = {
        "schema": MODEL_SCHEMA,
        "model_version": "independent_model_b_v3_reveal_aware_candidate_20260915",
        "related_issue": 103,
        "promotion_status": "candidate_not_promoted",
        "independence_contract": "TRAIN PokerStars HH decisions/revelations plus frozen TRAIN-derived Model-B profiles only; no Model-A EV, policy, recommendation, range or pseudo-label input",
        "population": population,
        "fit": {
            "split": "TRAIN",
            "backoff_min_observations": backoff_min_observations,
            "prior_strength": prior_strength,
            "action_prior_strength": action_prior_strength,
            "excluded_players": sorted(excluded_players),
        },
        "frozen_incumbent_components": {
            name: sha256_file(incumbent_dir / name)
            for name in ("profiles.json", "postflop_actions.json", "sizing.json")
        },
        "candidate_components": {
            "preflop_ranges.json": sha256_file(model_dir / "preflop_ranges.json"),
            "reveal_sensitivity.json": sha256_file(model_dir / "reveal_sensitivity.json"),
            "reveal_audit.json": sha256_file(model_dir / "reveal_audit.json"),
            "prediction_contract.json": sha256_file(model_dir / "prediction_contract.json"),
        },
        "scientific_limits": audit["identification_limits"],
    }
    write(model_dir / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incumbent-dir", type=Path, required=True)
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--certification", type=Path, required=True)
    parser.add_argument("--stake", action="append", default=["100/200"])
    parser.add_argument("--exclude-player", action="append", default=[])
    parser.add_argument("--backoff-min-observations", type=int, default=20)
    parser.add_argument("--prior-strength", type=float, default=50.0)
    parser.add_argument("--action-prior-strength", type=float, default=20.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    summary = build_candidate(
        args.incumbent_dir,
        args.archive,
        args.certification,
        set(args.stake),
        set(args.exclude_player),
        args.output_dir,
        backoff_min_observations=args.backoff_min_observations,
        prior_strength=args.prior_strength,
        action_prior_strength=args.action_prior_strength,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
