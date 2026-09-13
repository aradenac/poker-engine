#!/usr/bin/env python3
"""Paired incumbent-vs-candidate gate for independent Model B.

The two models are scored on exactly the same deterministic VALIDATION/TEST
hands. Per-hand loss sums are the bootstrap cluster unit, preventing multiple
decisions from one poker hand from being treated as independent observations.
Model selection remains VALIDATION-only; TEST is a locked confirmation of the
already frozen K=3 candidate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

# Support both `python -m ...compare_model_b_paired` and direct execution from
# the repository root, which is how the promotion-gate workflow invokes this
# script. Python otherwise places only this script directory on sys.path.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import split_for  # noqa: E402
from tools.training.independent_profiles.build_model_b import (  # noqa: E402
    apply_event,
    combo_class,
    key_for,
    parse_hand,
    preflop_summary,
    relative_position,
)
from tools.training.independent_profiles.build_player_features import merge_archives  # noqa: E402
from tools.training.independent_profiles.evaluate_model_b import (  # noqa: E402
    EPS,
    action_probabilities,
    choose_node,
    load,
    range_probability,
)

SCHEMA = "independent-model-b-paired-comparison/v1"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def percentile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("percentile requires observations")
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    x = q * (len(values) - 1)
    lo = int(math.floor(x))
    hi = int(math.ceil(x))
    if lo == hi:
        return values[lo]
    t = x - lo
    return values[lo] * (1.0 - t) + values[hi] * t


def load_bundle(feature_path: Path, model_dir: Path) -> dict:
    profiles = load(model_dir / "profiles.json")
    ranges = load(model_dir / "preflop_ranges.json")
    actions = load(model_dir / "postflop_actions.json")
    sizings = load(model_dir / "sizing.json")
    feature_doc = load(feature_path)
    default_profile = max(profiles["profiles"], key=lambda p: p["appearance_weight"])["profile"]
    return {
        "feature_path": feature_path,
        "model_dir": model_dir,
        "features": feature_doc,
        "profiles": profiles,
        "ranges": ranges,
        "actions": actions,
        "sizings": sizings,
        "player_profile": profiles["player_profile"],
        "default_profile": int(default_profile),
        "range_min": int(ranges["backoff_min_observations"]),
        "action_min": int(actions["backoff_min_observations"]),
    }


def score_hand(
    hand: dict,
    bundle: dict,
    excluded_players: set[str],
    action_alpha: float,
    range_prior_strength: float,
) -> dict:
    profiles = bundle["profiles"]
    ranges = bundle["ranges"]
    actions = bundle["actions"]
    player_profile = bundle["player_profile"]
    default_profile = bundle["default_profile"]
    multiplicity = ranges["multiplicity"]

    action_n = 0
    action_loss_sum = 0.0
    range_n = 0
    range_loss_sum = 0.0

    pot_type, roles, active_after_preflop, _, _ = preflop_summary(hand)

    for player, cards in hand["known_cards"].items():
        if player in excluded_players or player not in active_after_preflop:
            continue
        hand_class = combo_class(cards)
        if hand_class is None:
            continue
        profile = int(player_profile.get(player, default_profile))
        row = {
            "profile": profile,
            "position": hand["positions"].get(player, "NA"),
            "pot_type": pot_type,
            "preflop_role": roles.get(player, "OTHER"),
        }
        node, _, _ = choose_node(ranges["levels"], row, bundle["range_min"])
        p = max(range_probability(node, hand_class, multiplicity, range_prior_strength), EPS)
        range_n += 1
        range_loss_sum += -math.log(p)

    pre_paid = defaultdict(float)
    pre_price = 0.0
    pot = 0.0
    active = set(hand["players"])
    allin = set()
    for event in hand["events"]["preflop"]:
        pot, pre_price, _ = apply_event(event, pre_paid, pot, pre_price)
        if event["type"] == "fold":
            active.discard(event["player"])
        if event["allin"]:
            allin.add(event["player"])

    for street in ("flop", "turn", "river"):
        paid = defaultdict(float)
        price = 0.0
        for event in hand["events"][street]:
            actor = event["player"]
            typ = event["type"]
            if typ in {"return", "post"}:
                pot, price, _ = apply_event(event, paid, pot, price)
                continue
            if typ not in {"fold", "check", "call", "bet", "raise"}:
                continue
            to_call = max(0.0, price - paid[actor])
            mode = "FACING" if to_call > 1e-9 else "FREE"
            action = {
                "check": "CHECK",
                "fold": "FOLD",
                "call": "CALL",
                "bet": "BET",
                "raise": "RAISE",
            }[typ]
            valid = (mode == "FREE" and action in {"CHECK", "BET"}) or (
                mode == "FACING" and action in {"FOLD", "CALL", "RAISE"}
            )
            profile = int(player_profile.get(actor, default_profile))
            row = {
                "profile": profile,
                "street": street,
                "mode": mode,
                "relative_position": relative_position(hand, actor, active, allin),
                "pot_type": pot_type,
                "preflop_role": roles.get(actor, "OTHER"),
                "action": action,
            }
            if actor not in excluded_players and valid:
                labels = actions["labels"][mode]
                node, _, _ = choose_node(actions["levels"], row, bundle["action_min"])
                probs = action_probabilities(node, labels, action_alpha)
                action_n += 1
                action_loss_sum += -math.log(max(probs[action], EPS))

            pot, price, _ = apply_event(event, paid, pot, price)
            if typ == "fold":
                active.discard(actor)
                allin.discard(actor)
            if event["allin"]:
                allin.add(actor)

    return {
        "action_n": action_n,
        "action_loss_sum": action_loss_sum,
        "range_n": range_n,
        "range_loss_sum": range_loss_sum,
    }


def paired_rows(
    records,
    split_name: str,
    incumbent: dict,
    candidate: dict,
    excluded_players: set[str],
    action_alpha: float,
    range_prior_strength: float,
) -> list[dict]:
    rows = []
    for record in records:
        if split_for(record.hand_id) != split_name:
            continue
        hand = parse_hand(record)
        if hand is None:
            continue
        base = score_hand(hand, incumbent, excluded_players, action_alpha, range_prior_strength)
        cand = score_hand(hand, candidate, excluded_players, action_alpha, range_prior_strength)
        if base["action_n"] != cand["action_n"] or base["range_n"] != cand["range_n"]:
            raise AssertionError((record.hand_id, base, cand))
        rows.append(
            {
                "hand_id": str(record.hand_id),
                "action_n": base["action_n"],
                "action_delta_loss_sum": cand["action_loss_sum"] - base["action_loss_sum"],
                "range_n": base["range_n"],
                "range_delta_loss_sum": cand["range_loss_sum"] - base["range_loss_sum"],
            }
        )
    return rows


def metric_delta(rows: list[dict], prefix: str) -> float | None:
    n = sum(int(row[f"{prefix}_n"]) for row in rows)
    if not n:
        return None
    return sum(float(row[f"{prefix}_delta_loss_sum"]) for row in rows) / n


def paired_bootstrap(rows: list[dict], *, seed: int, samples: int) -> dict:
    if not rows:
        raise ValueError("paired bootstrap requires hands")
    rng = random.Random(seed)
    n_hands = len(rows)
    action_deltas: list[float] = []
    range_deltas: list[float] = []
    for _ in range(samples):
        a_sum = r_sum = 0.0
        a_n = r_n = 0
        for _ in range(n_hands):
            row = rows[rng.randrange(n_hands)]
            a_sum += float(row["action_delta_loss_sum"])
            a_n += int(row["action_n"])
            r_sum += float(row["range_delta_loss_sum"])
            r_n += int(row["range_n"])
        if a_n:
            action_deltas.append(a_sum / a_n)
        if r_n:
            range_deltas.append(r_sum / r_n)
    return {
        "cluster_unit": "hand_id",
        "hands": n_hands,
        "bootstrap_samples": samples,
        "seed": seed,
        "action_log_loss_delta_candidate_minus_incumbent": {
            "observed": metric_delta(rows, "action"),
            "ci95": [percentile(action_deltas, 0.025), percentile(action_deltas, 0.975)],
            "probability_candidate_better": sum(x < 0 for x in action_deltas) / len(action_deltas),
            "decisions": sum(int(row["action_n"]) for row in rows),
        },
        "range_log_loss_delta_candidate_minus_incumbent": {
            "observed": metric_delta(rows, "range"),
            "ci95": [percentile(range_deltas, 0.025), percentile(range_deltas, 0.975)],
            "probability_candidate_better": sum(x < 0 for x in range_deltas) / len(range_deltas),
            "revealed_hands": sum(int(row["range_n"]) for row in rows),
        },
    }


def anomaly_rate(split: dict) -> float:
    audit = split.get("audit", {})
    n = int(split.get("actions", {}).get("n", 0))
    anomalies = sum(
        int(v) for k, v in audit.items() if k not in {"hands_parsed", "hands_unparsed"}
    )
    return anomalies / n if n else math.inf


def assert_same_dataset(incumbent_eval: dict, candidate_eval: dict) -> dict:
    left = incumbent_eval["dataset"]
    right = candidate_eval["dataset"]
    for key in ("unique_scoped_hands", "split_counts", "sorted_hand_ids_sha256"):
        if left.get(key) != right.get(key):
            raise AssertionError((key, left.get(key), right.get(key)))
    return {
        "unique_scoped_hands": right.get("unique_scoped_hands"),
        "split_counts": right.get("split_counts"),
        "sorted_hand_ids_sha256": right.get("sorted_hand_ids_sha256"),
    }


def guardrails(split: dict, contract: dict) -> dict:
    g = contract["model_b"]["absolute_guardrails"]
    checks = {
        "action_ece": float(split["actions"]["ece_confidence"]) <= float(g["max_action_ece"]),
        "known_player_coverage": float(split["actions"]["warm_fraction"]) >= float(g["min_known_player_coverage"]),
        "weighted_profile_stability": float(
            split["profile_stability"]["appearance_weighted_stable_fraction"]
        ) >= float(g["min_weighted_profile_stability"]),
        "state_anomaly_rate": anomaly_rate(split) <= float(g["max_state_anomaly_rate"]),
        "sizing_p10_p90_coverage": 0.70
        <= float(split["sizing"]["inside_training_p10_p90_fraction"])
        <= 0.90,
        "sizing_above_p99_tail": float(split["sizing"]["above_training_p99_fraction"])
        <= 0.03,
    }
    return {
        "checks": checks,
        "pass": all(checks.values()),
        "observed": {
            "action_ece": split["actions"]["ece_confidence"],
            "known_player_coverage": split["actions"]["warm_fraction"],
            "weighted_profile_stability": split["profile_stability"][
                "appearance_weighted_stable_fraction"
            ],
            "state_anomaly_rate": anomaly_rate(split),
            "sizing_p10_p90_coverage": split["sizing"]["inside_training_p10_p90_fraction"],
            "sizing_above_p99_tail": split["sizing"]["above_training_p99_fraction"],
        },
    }


def comparison_pass(stats: dict, contract: dict) -> bool:
    rule = contract["model_b"]["candidate_vs_incumbent"]
    action_limit = float(
        rule["action_log_loss_delta_candidate_minus_incumbent_ci95_upper_at_most"]
    )
    range_limit = float(
        rule["range_log_loss_delta_candidate_minus_incumbent_ci95_upper_at_most"]
    )
    return (
        float(stats["action_log_loss_delta_candidate_minus_incumbent"]["ci95"][1])
        <= action_limit
        and float(stats["range_log_loss_delta_candidate_minus_incumbent"]["ci95"][1])
        <= range_limit
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--incumbent-features", type=Path, required=True)
    p.add_argument("--incumbent-model-dir", type=Path, required=True)
    p.add_argument("--incumbent-evaluation", type=Path, required=True)
    p.add_argument("--candidate-features", type=Path, required=True)
    p.add_argument("--candidate-model-dir", type=Path, required=True)
    p.add_argument("--candidate-evaluation", type=Path, required=True)
    p.add_argument("--archive", type=Path, action="append", required=True)
    p.add_argument("--stake", action="append", default=["100/200"])
    p.add_argument("--exclude-player", action="append", default=[])
    p.add_argument("--action-alpha", type=float, default=1.0)
    p.add_argument("--range-prior-strength", type=float, default=50.0)
    p.add_argument(
        "--contract", type=Path, default=Path("training/PROMOTION_GATE_CONTRACT.json")
    )
    p.add_argument("--bootstrap-samples", type=int, default=5000)
    p.add_argument("--seed", type=int, default=20260913)
    p.add_argument("--code-commit", default=None)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    contract = load(args.contract)
    incumbent_eval = load(args.incumbent_evaluation)
    candidate_eval = load(args.candidate_evaluation)
    dataset = assert_same_dataset(incumbent_eval, candidate_eval)
    if dataset["unique_scoped_hands"] != 31003:
        raise AssertionError(dataset)
    expected_splits = {"TRAIN": 24755, "VALIDATION": 3073, "TEST": 3175}
    if dataset["split_counts"] != expected_splits:
        raise AssertionError((dataset["split_counts"], expected_splits))

    by_id, provenance = merge_archives(args.archive, set(args.stake))
    if provenance.get("sorted_hand_ids_sha256") != dataset["sorted_hand_ids_sha256"]:
        raise AssertionError("comparison archives do not match evaluation provenance")
    records = list(by_id.values())
    excluded = set(args.exclude_player)
    incumbent = load_bundle(args.incumbent_features, args.incumbent_model_dir)
    candidate = load_bundle(args.candidate_features, args.candidate_model_dir)

    split_stats = {}
    for i, split in enumerate(("VALIDATION", "TEST")):
        rows = paired_rows(
            records,
            split,
            incumbent,
            candidate,
            excluded,
            args.action_alpha,
            args.range_prior_strength,
        )
        split_stats[split.lower()] = paired_bootstrap(
            rows, seed=args.seed + i * 1000003, samples=args.bootstrap_samples
        )

    validation_guard = guardrails(candidate_eval["validation"], contract)
    test_guard = guardrails(candidate_eval["test"], contract)
    validation_comparison = comparison_pass(split_stats["validation"], contract)
    test_comparison = comparison_pass(split_stats["test"], contract)
    validation_pass = validation_comparison and validation_guard["pass"]
    test_pass = test_comparison and test_guard["pass"]
    promote = validation_pass and test_pass

    report = {
        "schema": SCHEMA,
        "cycle": "2026-09-12",
        "code_commit": args.code_commit,
        "contract": {
            "path": args.contract.as_posix(),
            "sha256": sha256_file(args.contract),
            "selection_split": contract["model_b"]["selection_split"],
            "paired_confidence_required": contract["model_b"]["candidate_vs_incumbent"][
                "paired_confidence_required_for_promotion"
            ],
        },
        "dataset": dataset,
        "candidate": candidate_eval["model"],
        "incumbent": incumbent_eval["model"],
        "paired": split_stats,
        "guardrails": {"validation": validation_guard, "test": test_guard},
        "decision": {
            "validation_selection_pass": validation_pass,
            "locked_test_confirmation_pass": test_pass,
            "test_used_for_selection": False,
            "outcome": "PROMOTE_CANDIDATE" if promote else "RETAIN_INCUMBENT",
            "production_effect": "NONE",
            "reason": (
                "Candidate clears paired 95% action/range non-regression on VALIDATION and locked TEST plus absolute guardrails. Explicit promotion is still a separate state transition."
                if promote
                else "Candidate does not clear every pre-specified paired 95% action/range and absolute guardrail requirement; incumbent remains promoted. TEST was not used to retune or select an alternative."
            ),
        },
        "scope_limit": (
            "Same-structure Model B refresh only. Response-representation realism remains "
            "governed by issue #46 and is not proven by this comparison."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
