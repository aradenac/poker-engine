#!/usr/bin/env python3
"""Paired holdout evaluator for the issue-103 reveal-aware range component.

Only the requested split is read.  The default is VALIDATION; TEST is therefore
not consumed during candidate selection.  Because issue #103 freezes profiles,
postflop actions and sizing byte-identically, the paired action-loss delta is
exactly zero by construction and this evaluator focuses on the changed range
probability surface over actually revealed holdout hands.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any

from tools.datasets.build_hand_history_increment import split_for
from tools.training.independent_profiles.build_model_b import combo_class, parse_hand, preflop_summary
from tools.training.independent_profiles.evaluate_model_b import choose_node, range_probability
from tools.training.independent_profiles.reveal_aware_ranges import certified_records, sha256_file

SCHEMA = "independent-preflop-reveal-aware-paired-evaluation/v1"
EPS = 1e-15


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def percentile(values: list[float], q: float) -> float:
    values = sorted(values)
    if not values:
        raise ValueError("percentile requires observations")
    if len(values) == 1:
        return values[0]
    x = q * (len(values) - 1)
    lo = int(math.floor(x))
    hi = int(math.ceil(x))
    if lo == hi:
        return values[lo]
    t = x - lo
    return values[lo] * (1.0 - t) + values[hi] * t


def load_bundle(model_dir: Path) -> dict[str, Any]:
    profiles = load(model_dir / "profiles.json")
    ranges = load(model_dir / "preflop_ranges.json")
    default_profile = int(max(profiles["profiles"], key=lambda p: p["appearance_weight"])["profile"])
    return {
        "dir": model_dir,
        "profiles": profiles,
        "ranges": ranges,
        "player_profile": {str(k): int(v) for k, v in profiles["player_profile"].items()},
        "default_profile": default_profile,
        "range_min": int(ranges["backoff_min_observations"]),
    }


def score_hand(
    hand: dict[str, Any],
    bundle: dict[str, Any],
    excluded_players: set[str],
    prior_strength: float,
) -> tuple[int, float]:
    ranges = bundle["ranges"]
    multiplicity = ranges["multiplicity"]
    pot_type, roles, active_after_preflop, _, _ = preflop_summary(hand)
    n = 0
    loss = 0.0
    for player, cards in hand["known_cards"].items():
        if player in excluded_players or player not in active_after_preflop:
            continue
        hand_class = combo_class(cards)
        if hand_class is None:
            continue
        profile = int(bundle["player_profile"].get(player, bundle["default_profile"]))
        row = {
            "profile": profile,
            "position": hand["positions"].get(player, "NA"),
            "pot_type": pot_type,
            "preflop_role": roles.get(player, "OTHER"),
        }
        node, _, _ = choose_node(ranges["levels"], row, bundle["range_min"])
        probability = max(range_probability(node, hand_class, multiplicity, prior_strength), EPS)
        n += 1
        loss += -math.log(probability)
    return n, loss


def paired_rows(
    records,
    split_name: str,
    incumbent: dict[str, Any],
    candidate: dict[str, Any],
    excluded_players: set[str],
    prior_strength: float,
) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        if split_for(record.hand_id) != split_name:
            continue
        hand = parse_hand(record)
        if hand is None:
            continue
        base_n, base_loss = score_hand(hand, incumbent, excluded_players, prior_strength)
        cand_n, cand_loss = score_hand(hand, candidate, excluded_players, prior_strength)
        if base_n != cand_n:
            raise AssertionError((record.hand_id, base_n, cand_n))
        rows.append({
            "hand_id": str(record.hand_id),
            "range_n": base_n,
            "delta_loss_sum": cand_loss - base_loss,
        })
    return rows


def observed_delta(rows: list[dict[str, Any]]) -> float:
    n = sum(int(row["range_n"]) for row in rows)
    if n == 0:
        raise ValueError("holdout contains no revealed active opponent hands")
    return sum(float(row["delta_loss_sum"]) for row in rows) / n


def bootstrap(rows: list[dict[str, Any]], seed: int, samples: int) -> dict[str, Any]:
    rng = random.Random(seed)
    draws = []
    for _ in range(samples):
        loss = 0.0
        n = 0
        for _ in range(len(rows)):
            row = rows[rng.randrange(len(rows))]
            loss += float(row["delta_loss_sum"])
            n += int(row["range_n"])
        if n:
            draws.append(loss / n)
    if not draws:
        raise ValueError("bootstrap produced no revealed observations")
    return {
        "cluster_unit": "hand_id",
        "samples": samples,
        "seed": seed,
        "observed": observed_delta(rows),
        "ci95": [percentile(draws, 0.025), percentile(draws, 0.975)],
        "probability_candidate_better": sum(x < 0 for x in draws) / len(draws),
        "revealed_hands": sum(int(row["range_n"]) for row in rows),
        "base_hands": len(rows),
    }


def frozen_component_check(incumbent_dir: Path, candidate_dir: Path) -> dict[str, Any]:
    checks = {}
    for name in ("profiles.json", "postflop_actions.json", "sizing.json"):
        left = sha256_file(incumbent_dir / name)
        right = sha256_file(candidate_dir / name)
        checks[name] = {"incumbent_sha256": left, "candidate_sha256": right, "identical": left == right}
    if not all(row["identical"] for row in checks.values()):
        raise ValueError("issue #103 candidate changed a frozen non-range component")
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incumbent-dir", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--certification", type=Path, required=True)
    parser.add_argument("--stake", action="append", default=["100/200"])
    parser.add_argument("--exclude-player", action="append", default=[])
    parser.add_argument("--split", choices=["VALIDATION", "TEST"], default="VALIDATION")
    parser.add_argument("--range-prior-strength", type=float, default=50.0)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    frozen = frozen_component_check(args.incumbent_dir, args.candidate_dir)
    records, population = certified_records(args.archive, set(args.stake), args.certification)
    incumbent = load_bundle(args.incumbent_dir)
    candidate = load_bundle(args.candidate_dir)
    rows = paired_rows(
        records,
        args.split,
        incumbent,
        candidate,
        set(args.exclude_player),
        args.range_prior_strength,
    )
    stats = bootstrap(rows, args.seed, args.bootstrap_samples)
    threshold = 0.0
    passed = float(stats["ci95"][1]) <= threshold
    result = {
        "schema": SCHEMA,
        "related_issue": 103,
        "split": args.split,
        "test_consumed": args.split == "TEST",
        "population": population,
        "candidate": {
            "summary_sha256": sha256_file(args.candidate_dir / "summary.json"),
            "ranges_sha256": sha256_file(args.candidate_dir / "preflop_ranges.json"),
        },
        "incumbent": {
            "summary_sha256": sha256_file(args.incumbent_dir / "summary.json"),
            "ranges_sha256": sha256_file(args.incumbent_dir / "preflop_ranges.json"),
        },
        "frozen_components": frozen,
        "paired_range_log_loss_delta_candidate_minus_incumbent": stats,
        "gate": {
            "rule": "paired range-log-loss candidate-minus-incumbent 95% CI upper bound <= 0",
            "threshold": threshold,
            "pass": passed,
            "action_log_loss_delta": 0.0,
            "action_delta_reason": "postflop action table and profiles are byte-identical to incumbent",
        },
        "decision": (
            "ACCEPT_EXPERIMENTAL_RANGE_COMPONENT" if passed and args.split == "VALIDATION"
            else "CONFIRM_RANGE_COMPONENT" if passed
            else "RETAIN_BASELINE_RANGE_COMPONENT"
        ),
        "promotion_scope": "range component only; this does not promote Model B production or Hero strategy",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
