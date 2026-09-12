#!/usr/bin/env python3
"""Evaluate independent opponent Model B on deterministic VALIDATION/TEST hands.

No held-out hand contributes to profile fitting or behavior-table estimation. The
script measures predictive quality, backoff coverage, sizing calibration, and
profile stability relative to the TRAIN-only player assignments.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from tools.datasets.build_hand_history_increment import split_for
from tools.training.independent_profiles.build_player_features import (
    merge_archives,
    new_counter,
    update_hand_features,
)
from tools.training.independent_profiles.build_model_b import (
    FEATURE_KEYS,
    apply_event,
    combo_class,
    key_for,
    parse_hand,
    preflop_summary,
    relative_position,
    sha256_file,
    squared_distance,
)

SCHEMA = "independent-opponent-model-b-evaluation/v1"
PREDICTION_CONTRACT_SCHEMA = "independent-opponent-model-b-prediction-contract/v1"
EPS = 1e-15


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    x = q * (len(values) - 1)
    lo = int(math.floor(x))
    hi = int(math.ceil(x))
    if lo == hi:
        return values[lo]
    t = x - lo
    return values[lo] * (1 - t) + values[hi] * t


def choose_node(levels: list[dict], row: dict, min_observations: int) -> tuple[dict, int, str]:
    fallback = None
    fallback_index = len(levels) - 1
    fallback_key = "ALL"
    for i, level in enumerate(levels):
        key = key_for(level["cols"], row)
        node = level["data"].get(key)
        if i == len(levels) - 1:
            fallback = node
            fallback_index = i
            fallback_key = key
        if node and int(node.get("n", 0)) >= min_observations:
            return node, i, key
    if fallback is not None:
        return fallback, fallback_index, fallback_key
    raise ValueError("model has no fallback node")


def action_probabilities(node: dict, labels: list[str], alpha: float) -> dict[str, float]:
    """Return a normalized posterior over the legal labels for the current mode.

    Coarse fallback nodes can contain labels from both FREE and FACING states. The
    denominator therefore uses only counts belonging to ``labels`` rather than the
    node's aggregate ``n``.
    """
    counts = node.get("counts", {})
    legal_n = sum(float(counts.get(label, 0)) for label in labels)
    den = legal_n + alpha * len(labels)
    return {label: (float(counts.get(label, 0)) + alpha) / den for label in labels}


def range_probability(node: dict, hand_class: str, multiplicity: dict[str, int], prior_strength: float) -> float:
    prior = float(multiplicity[hand_class]) / 1326.0
    return (float(node.get("counts", {}).get(hand_class, 0)) + prior_strength * prior) / (
        float(node.get("n", 0)) + prior_strength
    )


def new_action_metrics() -> dict:
    return {
        "n": 0,
        "log_loss_sum": 0.0,
        "brier_sum": 0.0,
        "correct": 0,
        "baseline_log_loss_sum": 0.0,
        "observed": Counter(),
        "predicted_sum": defaultdict(float),
        "levels": Counter(),
        "warm": 0,
        "cold": 0,
        "reliability": defaultdict(lambda: {"n": 0, "confidence_sum": 0.0, "correct": 0}),
    }


def add_action_observation(
    metrics: dict,
    action: str,
    probs: dict[str, float],
    baseline_probs: dict[str, float],
    level: int,
    warm: bool,
) -> None:
    labels = list(probs)
    p_actual = max(probs[action], EPS)
    p_base = max(baseline_probs[action], EPS)
    metrics["n"] += 1
    metrics["log_loss_sum"] += -math.log(p_actual)
    metrics["baseline_log_loss_sum"] += -math.log(p_base)
    metrics["brier_sum"] += sum((probs[x] - (1.0 if x == action else 0.0)) ** 2 for x in labels)
    pred = max(labels, key=lambda x: (probs[x], x))
    correct = int(pred == action)
    metrics["correct"] += correct
    metrics["observed"][action] += 1
    for label in labels:
        metrics["predicted_sum"][label] += probs[label]
    metrics["levels"][str(level)] += 1
    metrics["warm" if warm else "cold"] += 1
    confidence = max(probs.values())
    b = min(9, int(confidence * 10))
    bucket = metrics["reliability"][str(b)]
    bucket["n"] += 1
    bucket["confidence_sum"] += confidence
    bucket["correct"] += correct


def finalize_action_metrics(metrics: dict) -> dict:
    n = metrics["n"]
    if not n:
        return {"n": 0}
    reliability = {}
    ece = 0.0
    for b in sorted(metrics["reliability"], key=int):
        row = metrics["reliability"][b]
        avg_conf = row["confidence_sum"] / row["n"]
        accuracy = row["correct"] / row["n"]
        reliability[b] = {"n": row["n"], "confidence": avg_conf, "accuracy": accuracy}
        ece += row["n"] / n * abs(avg_conf - accuracy)
    labels = sorted(set(metrics["observed"]) | set(metrics["predicted_sum"]))
    return {
        "n": n,
        "log_loss": metrics["log_loss_sum"] / n,
        "street_mode_fallback_log_loss": metrics["baseline_log_loss_sum"] / n,
        "log_loss_improvement": (metrics["baseline_log_loss_sum"] - metrics["log_loss_sum"]) / n,
        "brier": metrics["brier_sum"] / n,
        "accuracy": metrics["correct"] / n,
        "ece_confidence": ece,
        "warm_fraction": metrics["warm"] / n,
        "cold_fraction": metrics["cold"] / n,
        "selected_level_counts": dict(sorted(metrics["levels"].items(), key=lambda x: int(x[0]))),
        "observed_frequency": {x: metrics["observed"][x] / n for x in labels},
        "mean_predicted_frequency": {x: metrics["predicted_sum"][x] / n for x in labels},
        "frequency_residual": {
            x: metrics["predicted_sum"][x] / n - metrics["observed"][x] / n for x in labels
        },
        "reliability": reliability,
    }


def new_range_metrics() -> dict:
    return {
        "n": 0,
        "log_loss_sum": 0.0,
        "prior_log_loss_sum": 0.0,
        "levels": Counter(),
        "warm": 0,
        "cold": 0,
        "by_profile": defaultdict(lambda: {"n": 0, "loss": 0.0, "prior": 0.0}),
    }


def add_range_observation(
    metrics: dict,
    hand_class: str,
    probability: float,
    multiplicity: dict[str, int],
    level: int,
    profile: int,
    warm: bool,
) -> None:
    p = max(probability, EPS)
    prior = max(float(multiplicity[hand_class]) / 1326.0, EPS)
    loss = -math.log(p)
    prior_loss = -math.log(prior)
    metrics["n"] += 1
    metrics["log_loss_sum"] += loss
    metrics["prior_log_loss_sum"] += prior_loss
    metrics["levels"][str(level)] += 1
    metrics["warm" if warm else "cold"] += 1
    row = metrics["by_profile"][str(profile)]
    row["n"] += 1
    row["loss"] += loss
    row["prior"] += prior_loss


def finalize_range_metrics(metrics: dict) -> dict:
    n = metrics["n"]
    if not n:
        return {"n": 0}
    by_profile = {}
    for profile, row in sorted(metrics["by_profile"].items(), key=lambda x: int(x[0])):
        by_profile[profile] = {
            "n": row["n"],
            "log_loss": row["loss"] / row["n"],
            "combinatorial_prior_log_loss": row["prior"] / row["n"],
            "log_loss_improvement": (row["prior"] - row["loss"]) / row["n"],
        }
    return {
        "n": n,
        "log_loss": metrics["log_loss_sum"] / n,
        "combinatorial_prior_log_loss": metrics["prior_log_loss_sum"] / n,
        "log_loss_improvement": (metrics["prior_log_loss_sum"] - metrics["log_loss_sum"]) / n,
        "warm_fraction": metrics["warm"] / n,
        "cold_fraction": metrics["cold"] / n,
        "selected_level_counts": dict(sorted(metrics["levels"].items(), key=lambda x: int(x[0]))),
        "by_profile": by_profile,
    }


def new_sizing_metrics() -> dict:
    return {
        "n": 0,
        "levels": Counter(),
        "abs_log2_errors": [],
        "inside_p10_p90": 0,
        "above_p99": 0,
        "below_p10": 0,
        "warm": 0,
        "cold": 0,
    }


def add_sizing_observation(metrics: dict, ratio: float, node: dict, level: int, warm: bool) -> None:
    median = float(node["p50"])
    if median <= 0 or ratio <= 0:
        return
    metrics["n"] += 1
    metrics["levels"][str(level)] += 1
    metrics["abs_log2_errors"].append(abs(math.log(ratio / median, 2)))
    metrics["inside_p10_p90"] += int(float(node["p10"]) <= ratio <= float(node["p90"]))
    metrics["above_p99"] += int(ratio > float(node["p99"]))
    metrics["below_p10"] += int(ratio < float(node["p10"]))
    metrics["warm" if warm else "cold"] += 1


def finalize_sizing_metrics(metrics: dict) -> dict:
    n = metrics["n"]
    if not n:
        return {"n": 0}
    errors = metrics["abs_log2_errors"]
    return {
        "n": n,
        "median_absolute_log2_error": percentile(errors, 0.50),
        "p90_absolute_log2_error": percentile(errors, 0.90),
        "inside_training_p10_p90_fraction": metrics["inside_p10_p90"] / n,
        "above_training_p99_fraction": metrics["above_p99"] / n,
        "below_training_p10_fraction": metrics["below_p10"] / n,
        "warm_fraction": metrics["warm"] / n,
        "cold_fraction": metrics["cold"] / n,
        "selected_level_counts": dict(sorted(metrics["levels"].items(), key=lambda x: int(x[0]))),
    }


def assign_profile_from_rates(rates: dict[str, float], profiles: dict) -> int:
    means = profiles["standardization"]["mean"]
    stds = profiles["standardization"]["std"]
    point = [(rates[k] - float(means[k])) / float(stds[k]) for k in FEATURE_KEYS]
    centroid_points = []
    for p in profiles["profiles"]:
        centroid_points.append([
            (float(p["centroid"][k]) - float(means[k])) / float(stds[k]) for k in FEATURE_KEYS
        ])
    return min(range(len(centroid_points)), key=lambda i: (squared_distance(point, centroid_points[i]), i))


def holdout_profile_stability(records, feature_doc: dict, profiles: dict, excluded_players: set[str], min_hands: int) -> dict:
    features = defaultdict(new_counter)
    parser_stats = Counter()
    unmatched = {}
    for record in records:
        update_hand_features(record, features, excluded_players, parser_stats, unmatched)

    global_rates = feature_doc["shrinkage"]["global_rates"]
    strength = float(feature_doc["shrinkage"]["prior_strength"])
    train_assignment = profiles["player_profile"]
    transitions = Counter()
    n = stable = 0
    weighted_n = weighted_stable = 0
    for player, f in features.items():
        appearances = int(f.get("appearances", 0))
        if appearances < min_hands or player not in train_assignment:
            continue

        def shrunk(num_key: str, den_key: str, rate_key: str) -> float:
            den = int(f.get(den_key, 0))
            num = int(f.get(num_key, 0))
            return (num + strength * float(global_rates[rate_key])) / (den + strength)

        rates = {
            "vpip": shrunk("vpip_hands", "appearances", "vpip"),
            "pfr": shrunk("pfr_hands", "appearances", "pfr"),
            "limp": shrunk("limp_hands", "appearances", "limp"),
            "threebet": shrunk("threebet_hands", "threebet_opportunities", "threebet"),
            "post_aggression_frequency": shrunk(
                "post_aggressive_actions", "post_decisions", "post_aggression_frequency"
            ),
            "post_fold_facing_aggression": shrunk(
                "post_face_aggression_fold", "post_face_aggression_opportunities", "post_fold_facing_aggression"
            ),
        }
        predicted = assign_profile_from_rates(rates, profiles)
        trained = int(train_assignment[player])
        transitions[f"{trained}->{predicted}"] += 1
        n += 1
        stable += int(predicted == trained)
        weighted_n += appearances
        weighted_stable += appearances * int(predicted == trained)
    return {
        "min_holdout_appearances": min_hands,
        "players_evaluated": n,
        "stable_fraction": stable / n if n else None,
        "appearance_weighted_stable_fraction": weighted_stable / weighted_n if weighted_n else None,
        "transition_counts": dict(sorted(transitions.items())),
        "parser_audit": dict(sorted(parser_stats.items())),
    }


def evaluate_split(
    records,
    split_name: str,
    feature_doc: dict,
    profiles: dict,
    ranges: dict,
    actions: dict,
    sizings: dict,
    excluded_players: set[str],
    action_alpha: float,
    range_prior_strength: float,
) -> dict:
    selected = [r for r in records if split_for(r.hand_id) == split_name]
    player_profile = profiles["player_profile"]
    default_profile = max(profiles["profiles"], key=lambda p: p["appearance_weight"])["profile"]
    multiplicity = ranges["multiplicity"]
    range_min = int(ranges["backoff_min_observations"])
    action_min = int(actions["backoff_min_observations"])
    sizing_min = int(sizings["backoff_min_observations"])

    range_metrics = new_range_metrics()
    action_metrics = new_action_metrics()
    action_context_metrics = defaultdict(new_action_metrics)
    sizing_metrics = new_sizing_metrics()
    audit = Counter()

    street_mode_level = next(
        i for i, level in enumerate(actions["levels"]) if level["cols"] == ["street", "mode"]
    )

    for record in selected:
        hand = parse_hand(record)
        if hand is None:
            audit["hands_unparsed"] += 1
            continue
        audit["hands_parsed"] += 1
        pot_type, roles, active_after_preflop, _, _ = preflop_summary(hand)

        for player, cards in hand["known_cards"].items():
            if player in excluded_players or player not in active_after_preflop:
                continue
            hc = combo_class(cards)
            if hc is None:
                continue
            warm = player in player_profile
            profile = int(player_profile.get(player, default_profile))
            row = {
                "profile": profile,
                "position": hand["positions"].get(player, "NA"),
                "pot_type": pot_type,
                "preflop_role": roles.get(player, "OTHER"),
            }
            node, level, _ = choose_node(ranges["levels"], row, range_min)
            p = range_probability(node, hc, multiplicity, range_prior_strength)
            add_range_observation(range_metrics, hc, p, multiplicity, level, profile, warm)

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
                    "check": "CHECK", "fold": "FOLD", "call": "CALL", "bet": "BET", "raise": "RAISE"
                }[typ]
                valid = (mode == "FREE" and action in {"CHECK", "BET"}) or (
                    mode == "FACING" and action in {"FOLD", "CALL", "RAISE"}
                )
                warm = actor in player_profile
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
                pot_before = pot

                if actor not in excluded_players and valid:
                    labels = actions["labels"][mode]
                    node, level, _ = choose_node(actions["levels"], row, action_min)
                    probs = action_probabilities(node, labels, action_alpha)
                    base_level = actions["levels"][street_mode_level]
                    base_key = key_for(base_level["cols"], row)
                    base_node = base_level["data"].get(base_key) or actions["levels"][-1]["data"]["ALL"]
                    base_probs = action_probabilities(base_node, labels, action_alpha)
                    add_action_observation(action_metrics, action, probs, base_probs, level, warm)
                    context_key = f"P{profile}|{street}|{mode}"
                    add_action_observation(
                        action_context_metrics[context_key], action, probs, base_probs, level, warm
                    )
                elif actor not in excluded_players:
                    audit[f"invalid_{mode.lower()}_{action.lower()}"] += 1

                pot, price, added = apply_event(event, paid, pot, price)
                if (
                    actor not in excluded_players
                    and valid
                    and action in {"BET", "RAISE"}
                    and pot_before > 0
                    and added > 0
                ):
                    ratio = added / pot_before
                    if math.isfinite(ratio) and ratio > 0:
                        node, level, _ = choose_node(sizings["levels"], row, sizing_min)
                        add_sizing_observation(sizing_metrics, ratio, node, level, warm)
                if typ == "fold":
                    active.discard(actor)
                    allin.discard(actor)
                if event["allin"]:
                    allin.add(actor)

    return {
        "split": split_name,
        "hands": len(selected),
        "range": finalize_range_metrics(range_metrics),
        "actions": finalize_action_metrics(action_metrics),
        "actions_by_profile_street_mode": {
            key: finalize_action_metrics(value) for key, value in sorted(action_context_metrics.items())
        },
        "sizing": finalize_sizing_metrics(sizing_metrics),
        "profile_stability": holdout_profile_stability(
            selected, feature_doc, profiles, excluded_players, min_hands=10
        ),
        "audit": dict(sorted(audit.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--stake", action="append", default=["100/200"])
    parser.add_argument("--exclude-player", action="append", default=[])
    parser.add_argument("--action-alpha", type=float, default=1.0)
    parser.add_argument("--range-prior-strength", type=float, default=50.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prediction-contract", type=Path)
    args = parser.parse_args()

    feature_doc = load(args.features)
    root = args.model_dir
    profiles = load(root / "profiles.json")
    ranges = load(root / "preflop_ranges.json")
    actions = load(root / "postflop_actions.json")
    sizings = load(root / "sizing.json")
    by_id, provenance = merge_archives(args.archive, set(args.stake))
    records = list(by_id.values())
    excluded = set(args.exclude_player)

    contract = {
        "schema": PREDICTION_CONTRACT_SCHEMA,
        "model_schema": "independent-opponent-model-b/v2",
        "profile_assignment": {
            "known_player": "TRAIN-derived nearest deterministic profile",
            "cold_start": "profile with largest TRAIN appearance_weight",
        },
        "preflop_range": {
            "selection": "finest hierarchy node with n >= backoff_min_observations, else ALL",
            "posterior": "(class_count + prior_strength * combo_multiplicity/1326) / (n + prior_strength)",
            "prior_strength": args.range_prior_strength,
        },
        "postflop_action": {
            "selection": "finest hierarchy node with n >= backoff_min_observations, else ALL",
            "smoothing": "symmetric Dirichlet/additive smoothing over legal labels for current mode",
            "alpha_per_action": args.action_alpha,
        },
        "sizing": {
            "selection": "finest hierarchy node with n >= backoff_min_observations, else ALL",
            "distribution": "empirical TRAIN values; no clipping or synthetic tail",
        },
    }

    result = {
        "schema": SCHEMA,
        "model": {
            "dir": root.as_posix(),
            "summary_sha256": sha256_file(root / "summary.json"),
            "profiles_sha256": sha256_file(root / "profiles.json"),
            "ranges_sha256": sha256_file(root / "preflop_ranges.json"),
            "actions_sha256": sha256_file(root / "postflop_actions.json"),
            "sizing_sha256": sha256_file(root / "sizing.json"),
        },
        "dataset": provenance,
        "prediction_contract": contract,
        "validation": evaluate_split(
            records, "VALIDATION", feature_doc, profiles, ranges, actions, sizings,
            excluded, args.action_alpha, args.range_prior_strength
        ),
        "test": evaluate_split(
            records, "TEST", feature_doc, profiles, ranges, actions, sizings,
            excluded, args.action_alpha, args.range_prior_strength
        ),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.prediction_contract:
        args.prediction_contract.parent.mkdir(parents=True, exist_ok=True)
        args.prediction_contract.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
