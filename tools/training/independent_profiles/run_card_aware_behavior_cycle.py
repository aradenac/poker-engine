#!/usr/bin/env python3
"""Fit and validate issue #104 card-aware independent Model-B behavior.

The candidate and its public-only reference are fitted from exactly the same
certified TRAIN decisions. Hidden private hands are represented by a TRAIN-only,
action-independent profile/position prior; eventual revealed TRAIN cards become
point-mass labels. VALIDATION is never used to fit either the private-hand prior
or behavior tables.

Primary evaluation marginalizes private hand buckets for every VALIDATION action,
so selection does not condition on whether a hand happened to be revealed. A
revealed-hand conditional metric is emitted only as a diagnostic and cannot select
the candidate under the frozen protocol.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import random
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from tools.datasets.build_hand_history_increment import split_for
from tools.simulation.game_core import EPS, NoLimitHoldemState
from tools.simulation.hand_history_state import replay_public_hand
from tools.simulation.model_b_card_aware_runtime import (
    board_texture,
    opponents_bucket,
    price_bucket,
    recent_sequence_bucket,
    spr_bucket,
)
from tools.simulation.model_b_runtime import key_for, select_node
from tools.training.independent_profiles.build_model_b import (
    combo_class,
    hand_notations,
    parse_hand,
    preflop_summary,
)
from tools.training.independent_profiles.card_aware_behavior_fit import (
    bucket_posterior_from_classes,
    exact_hand_posterior,
    fit_behavior_from_soft_decisions,
)
from tools.training.independent_profiles.reveal_aware_ranges import certified_records

EPS_PROB = 1e-15
PRIOR_LEVELS = [["profile", "position"], ["profile"], []]
ACTION_MAP = {
    "fold": "FOLD",
    "check": "CHECK",
    "call": "CALL",
    "bet": "RAISE",
    "raise": "RAISE",
    "FOLD": "FOLD",
    "CHECK": "CHECK",
    "CALL": "CALL",
    "RAISE": "RAISE",
}
PRICE_ORDER = ["P00_25", "P25_50", "P50_75", "P75_100", "P100_150", "P150_PLUS"]


def load(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def profile_bundle(profiles: Mapping[str, Any]) -> tuple[dict[str, int], int]:
    player_profile = {str(k): int(v) for k, v in profiles["player_profile"].items()}
    default = int(max(profiles["profiles"], key=lambda row: row["appearance_weight"])["profile"])
    return player_profile, default


def build_action_independent_prior(
    records: Iterable[Any],
    profiles: Mapping[str, Any],
    excluded_players: set[str],
    *,
    minimum_revealed_labels: int,
    prior_strength: float,
) -> dict[str, Any]:
    """Build P(hand-class | TRAIN profile, position) without target actions."""
    names, multiplicity = hand_notations()
    player_profile, default_profile = profile_bundle(profiles)
    tables: list[dict[str, dict[str, Any]]] = [collections.defaultdict(lambda: {
        "n": 0,
        "revealed_n": 0,
        "counts": collections.Counter(),
    }) for _ in PRIOR_LEVELS]
    audit = {"train_hands": 0, "player_observations": 0, "revealed": 0, "hidden": 0}

    for record in records:
        if split_for(record.hand_id) != "TRAIN":
            continue
        hand = parse_hand(record)
        if hand is None:
            continue
        audit["train_hands"] += 1
        known = hand.get("known_cards") or {}
        for player, position in (hand.get("positions") or {}).items():
            if player in excluded_players:
                continue
            audit["player_observations"] += 1
            profile = int(player_profile.get(player, default_profile))
            row = {"profile": profile, "position": str(position)}
            hand_class = combo_class(known.get(player, [])) if player in known else None
            audit["revealed" if hand_class else "hidden"] += 1
            for level_index, cols in enumerate(PRIOR_LEVELS):
                node = tables[level_index][key_for(cols, row)]
                node["n"] += 1
                if hand_class:
                    node["revealed_n"] += 1
                    node["counts"][hand_class] += 1

    levels = []
    for cols, table in zip(PRIOR_LEVELS, tables):
        data = {}
        for key, node in sorted(table.items()):
            data[key] = {
                "n": int(node["n"]),
                "revealed_n": int(node["revealed_n"]),
                "counts": {name: int(node["counts"].get(name, 0)) for name in names if node["counts"].get(name, 0)},
            }
        levels.append({"cols": list(cols), "data": data})

    return {
        "schema": "independent-model-b-action-independent-hand-prior/v1",
        "source_split": "TRAIN",
        "levels": levels,
        "minimum_revealed_labels": int(minimum_revealed_labels),
        "prior_strength": float(prior_strength),
        "multiplicity": multiplicity,
        "audit": audit,
        "independence": {
            "action_target_used": False,
            "future_public_action_used": False,
            "model_a_used": False,
        },
    }


def choose_prior_node(prior: Mapping[str, Any], row: Mapping[str, Any]) -> tuple[dict[str, Any], int, str]:
    minimum = int(prior["minimum_revealed_labels"])
    levels = prior["levels"]
    for level_index, level in enumerate(levels):
        key = key_for(level["cols"], row)
        node = level["data"].get(key)
        if node is None:
            continue
        if int(node.get("revealed_n", 0)) >= minimum or level_index == len(levels) - 1:
            return node, level_index, key
    raise ValueError("action-independent hand prior has no fallback node")


def class_posterior(prior: Mapping[str, Any], row: Mapping[str, Any]) -> tuple[dict[str, float], dict[str, Any]]:
    node, level, key = choose_prior_node(prior, row)
    multiplicity = prior["multiplicity"]
    prior_strength = float(prior["prior_strength"])
    revealed_n = float(node.get("revealed_n", 0))
    denominator = revealed_n + prior_strength
    probabilities = {}
    for hand_class, combos in multiplicity.items():
        probabilities[hand_class] = (
            float(node.get("counts", {}).get(hand_class, 0.0))
            + prior_strength * float(combos) / 1326.0
        ) / denominator
    total = sum(probabilities.values())
    probabilities = {key_: value / total for key_, value in probabilities.items()}
    return probabilities, {
        "level": level,
        "key": key,
        "n": int(node.get("n", 0)),
        "revealed_n": int(node.get("revealed_n", 0)),
    }


def canonical_action(value: str) -> str:
    try:
        return ACTION_MAP[str(value)]
    except KeyError as exc:
        raise ValueError(f"unsupported action {value}") from exc


def _preflop_before_labels(trace: Sequence[Mapping[str, Any]], index: int, actor: str) -> tuple[str, str]:
    prior = [row for row in trace[:index] if row["street"] == "preflop"]
    actions = [canonical_action(row["action"]) for row in prior]
    raises = sum(action == "RAISE" for action in actions)
    calls = sum(action == "CALL" for action in actions)
    if raises == 0:
        pot_type = "UNOPENED" if calls == 0 else "LIMPED"
    elif raises == 1:
        pot_type = "SINGLE_RAISED"
    elif raises == 2:
        pot_type = "THREE_BET"
    else:
        pot_type = "FOUR_BET_PLUS"

    actor_actions = [canonical_action(row["action"]) for row in prior if row["player"] == actor]
    if not actor_actions:
        role = "NO_PRIOR_ACTION"
    elif actor_actions[-1] == "RAISE":
        role = "AGGRESSOR"
    elif actor_actions[-1] == "CALL":
        role = "LIMPER" if raises == 0 else "CALLER"
    elif actor_actions[-1] == "CHECK":
        role = "CHECKER"
    else:
        role = "OTHER"
    return pot_type, role


def public_features(
    trace: Sequence[Mapping[str, Any]],
    index: int,
    hand: Mapping[str, Any],
    profile: int,
    postflop_pot_type: str,
    postflop_roles: Mapping[str, str],
) -> tuple[dict[str, Any], NoLimitHoldemState]:
    entry = trace[index]
    actor = str(entry["player"])
    state = NoLimitHoldemState.from_snapshot(entry["state_before"])
    state.action_log = [
        {"street": row["street"], "action": canonical_action(row["action"])}
        for row in trace[:index]
    ]
    view = state.legal_view(actor)
    pot = float(view["pot_before_bb"])
    to_call = float(view["to_call_bb"])
    remaining = float(view["actor_remaining_bb"])
    mode = "FREE" if bool(view["free_check"]) else "FACING"
    if state.street == "preflop":
        pot_type, preflop_role = _preflop_before_labels(trace, index, actor)
    else:
        pot_type = str(postflop_pot_type)
        preflop_role = str(postflop_roles.get(actor, "OTHER"))
    row = {
        "profile": int(profile),
        "street": state.street,
        "mode": mode,
        # The existing Model-B column name is retained; value is the actor's
        # canonical table position, which is fully known before the action.
        "relative_position": str((hand.get("positions") or {}).get(actor, "NA")),
        "pot_type": pot_type,
        "preflop_role": preflop_role,
        "price_bucket": "FREE" if mode == "FREE" else price_bucket(to_call / pot if pot > EPS else None),
        "spr_bucket": spr_bucket(remaining / pot if pot > EPS else None),
        "opponents_bucket": opponents_bucket(sum(1 for player in state.live_players if player != actor)),
        "sequence_bucket": recent_sequence_bucket(state),
        "raise_level": sum(
            1 for event in state.action_log
            if event.get("street") == state.street and event.get("action") == "RAISE"
        ),
        "board_texture": board_texture(state.board),
        "legal_actions": list(view["legal_actions"]),
        "board": list(state.board),
    }
    return row, state


def observed_sizing_ratio(
    trace: Sequence[Mapping[str, Any]],
    index: int,
    state: NoLimitHoldemState,
    action: str,
) -> float | None:
    if action != "RAISE" or index + 1 >= len(trace):
        return None
    actor = str(trace[index]["player"])
    before = float(trace[index]["state_before"]["total_committed_bb"][actor])
    after = float(trace[index + 1]["state_before"]["total_committed_bb"][actor])
    incremental = after - before
    pot = float(state.pot_bb)
    if incremental <= EPS or pot <= EPS:
        return None
    ratio = incremental / pot
    return ratio if math.isfinite(ratio) and ratio > 0 else None


def extract_decisions(
    records: Iterable[Any],
    split_name: str,
    prior: Mapping[str, Any],
    profiles: Mapping[str, Any],
    excluded_players: set[str],
    *,
    training_labels: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    player_profile, default_profile = profile_bundle(profiles)
    rows: list[dict[str, Any]] = []
    audit = collections.Counter()
    bucket_cache: dict[tuple[Any, ...], dict[str, float]] = {}

    for record in records:
        if split_for(record.hand_id) != split_name:
            continue
        audit["hands_seen"] += 1
        hand = parse_hand(record)
        if hand is None:
            audit["parse_hand_skipped"] += 1
            continue
        try:
            replay = replay_public_hand(record.text)
        except Exception:
            audit["public_replay_skipped"] += 1
            continue
        trace = replay["trace"]
        try:
            postflop_pot_type, postflop_roles, _, _, _ = preflop_summary(hand)
        except Exception:
            audit["preflop_summary_skipped"] += 1
            continue
        known = hand.get("known_cards") or {}
        positions = hand.get("positions") or {}
        audit["hands_replayed"] += 1

        for index, entry in enumerate(trace):
            actor = str(entry["player"])
            if actor in excluded_players or actor not in positions:
                continue
            action = canonical_action(entry["action"])
            profile = int(player_profile.get(actor, default_profile))
            try:
                features, state = public_features(
                    trace, index, hand, profile, postflop_pot_type, postflop_roles
                )
            except Exception:
                audit["decision_state_skipped"] += 1
                continue
            if action not in features["legal_actions"]:
                audit["illegal_observed_action"] += 1
                continue

            prior_row = {"profile": profile, "position": str(positions.get(actor, "NA"))}
            classes, prior_selection = class_posterior(prior, prior_row)
            cache_key = (
                prior_selection["level"], prior_selection["key"], state.street, tuple(state.board)
            )
            soft = bucket_cache.get(cache_key)
            if soft is None:
                soft = bucket_posterior_from_classes(classes, board=state.board, street=state.street)
                bucket_cache[cache_key] = soft

            actual = None
            if actor in known:
                try:
                    actual = next(iter(exact_hand_posterior(known[actor], state.board, state.street)))
                except Exception:
                    audit["revealed_card_state_skipped"] += 1
                    actual = None

            if training_labels and actual is not None:
                posterior = {actual: 1.0}
                assignment = "REVEALED_POINT_MASS"
            else:
                posterior = soft
                assignment = "ACTION_INDEPENDENT_PRIOR"

            row = {
                **features,
                "hand_id": str(record.hand_id),
                "player": actor,
                "action": action,
                "hand_posterior": posterior,
                "actual_hand_bucket": actual,
                "private_assignment": assignment,
                "prior_selection": prior_selection,
            }
            sizing = observed_sizing_ratio(trace, index, state, action)
            if sizing is not None:
                row["incremental_cost_over_pot"] = sizing
                audit["sizing_observations"] += 1
            rows.append(row)
            audit["decisions"] += 1
            audit[f"street_{state.street}"] += 1
            audit[f"assignment_{assignment}"] += 1
    return rows, dict(audit)


def action_probabilities(
    behavior: Mapping[str, Any],
    row: Mapping[str, Any],
    hand_bucket_value: str,
) -> tuple[dict[str, float], dict[str, Any]]:
    cfg = behavior["action"]
    enriched = {**row, "hand_bucket": hand_bucket_value}
    node, level, key = select_node(cfg["levels"], enriched, int(cfg["backoff_min_observations"]))
    legal = list(row["legal_actions"])
    alpha = float(cfg["alpha_per_action"])
    masses = {action: max(0.0, float(node.get("counts", {}).get(action, 0.0))) + alpha for action in legal}
    total = sum(masses.values())
    probabilities = {action: value / total for action, value in masses.items()}
    return probabilities, {"level": int(level), "key": str(key), "support": float(node.get("n", 0.0))}


def marginal_action_probabilities(
    behavior: Mapping[str, Any], row: Mapping[str, Any]
) -> tuple[dict[str, float], dict[int, float]]:
    out = {action: 0.0 for action in row["legal_actions"]}
    levels: dict[int, float] = collections.defaultdict(float)
    for bucket, weight in row["hand_posterior"].items():
        probs, selection = action_probabilities(behavior, row, bucket)
        for action, probability in probs.items():
            out[action] += float(weight) * probability
        levels[int(selection["level"])] += float(weight)
    total = sum(out.values())
    if total <= 0:
        raise ValueError("marginal action probabilities have zero mass")
    return {key: value / total for key, value in out.items()}, dict(levels)


def _sizing_samples(
    behavior: Mapping[str, Any], row: Mapping[str, Any], hand_bucket_value: str
) -> list[tuple[float, float]]:
    cfg = behavior["sizing"]
    enriched = {**row, "hand_bucket": hand_bucket_value, "action": "RAISE"}
    node, _, _ = select_node(cfg["levels"], enriched, int(cfg["backoff_min_observations"]))
    if "weighted_values" in node:
        return [
            (float(item["value"]), float(item["weight"]))
            for item in node.get("weighted_values", [])
            if float(item.get("value", 0)) > 0 and float(item.get("weight", 0)) > 0
        ]
    return [(float(value), 1.0) for value in node.get("values", []) if float(value) > 0]


def weighted_median(samples: Sequence[tuple[float, float]]) -> float | None:
    clean = sorted((float(value), float(weight)) for value, weight in samples if value > 0 and weight > 0)
    total = sum(weight for _, weight in clean)
    if total <= 0:
        return None
    target = total / 2.0
    running = 0.0
    for value, weight in clean:
        running += weight
        if running >= target:
            return value
    return clean[-1][0]


def marginal_sizing_prediction(behavior: Mapping[str, Any], row: Mapping[str, Any]) -> float | None:
    samples: list[tuple[float, float]] = []
    for bucket, outer_weight in row["hand_posterior"].items():
        for value, weight in _sizing_samples(behavior, row, bucket):
            samples.append((value, float(outer_weight) * weight))
    return weighted_median(samples)


def percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentile requires observations")
    if len(ordered) == 1:
        return ordered[0]
    x = q * (len(ordered) - 1)
    lo = int(math.floor(x))
    hi = int(math.ceil(x))
    if lo == hi:
        return ordered[lo]
    fraction = x - lo
    return ordered[lo] * (1 - fraction) + ordered[hi] * fraction


def paired_bootstrap(
    per_hand: Mapping[str, tuple[float, int]], *, seed: int, samples: int
) -> dict[str, Any]:
    rows = [(key, float(value), int(n)) for key, (value, n) in per_hand.items() if int(n) > 0]
    if not rows:
        return {"hands": 0, "observations": 0, "observed": None, "ci95": None, "samples": 0, "seed": seed}
    observed = sum(value for _, value, _ in rows) / sum(n for _, _, n in rows)
    rng = random.Random(seed)
    draws = []
    for _ in range(samples):
        value_sum = 0.0
        n_sum = 0
        for _ in range(len(rows)):
            _, value, n = rows[rng.randrange(len(rows))]
            value_sum += value
            n_sum += n
        if n_sum:
            draws.append(value_sum / n_sum)
    return {
        "hands": len(rows),
        "observations": sum(n for _, _, n in rows),
        "observed": observed,
        "ci95": [percentile(draws, 0.025), percentile(draws, 0.975)],
        "samples": len(draws),
        "seed": seed,
        "probability_candidate_better": sum(value < 0 for value in draws) / len(draws),
    }


def confidence_ece(predictions: Sequence[tuple[dict[str, float], str]], bins: int = 10) -> float:
    cells = [dict(n=0, confidence=0.0, correct=0.0) for _ in range(bins)]
    for probs, actual in predictions:
        predicted = max(probs, key=probs.get)
        confidence = float(probs[predicted])
        index = min(bins - 1, int(confidence * bins))
        cells[index]["n"] += 1
        cells[index]["confidence"] += confidence
        cells[index]["correct"] += float(predicted == actual)
    total = sum(cell["n"] for cell in cells)
    if total == 0:
        return float("nan")
    error = 0.0
    for cell in cells:
        if not cell["n"]:
            continue
        confidence = cell["confidence"] / cell["n"]
        accuracy = cell["correct"] / cell["n"]
        error += cell["n"] / total * abs(confidence - accuracy)
    return error


def evaluate(
    validation_rows: Sequence[Mapping[str, Any]],
    candidate: Mapping[str, Any],
    reference: Mapping[str, Any],
    *,
    bootstrap_samples: int,
    seed: int,
) -> dict[str, Any]:
    action_by_hand: dict[str, list[float]] = collections.defaultdict(list)
    sizing_by_hand: dict[str, list[float]] = collections.defaultdict(list)
    candidate_predictions: list[tuple[dict[str, float], str]] = []
    reference_predictions: list[tuple[dict[str, float], str]] = []
    candidate_loss = reference_loss = 0.0
    candidate_brier = reference_brier = 0.0
    hierarchy_mass: dict[int, float] = collections.defaultdict(float)
    by_street: dict[str, dict[str, float]] = collections.defaultdict(lambda: {
        "n": 0, "candidate_loss": 0.0, "reference_loss": 0.0
    })
    revealed = {"n": 0, "candidate_loss": 0.0, "reference_loss": 0.0}
    sizing = {"n": 0, "candidate_error": 0.0, "reference_error": 0.0}

    for row in validation_rows:
        actual = str(row["action"])
        cand_probs, levels = marginal_action_probabilities(candidate, row)
        ref_probs, _ = marginal_action_probabilities(reference, row)
        for level, mass in levels.items():
            hierarchy_mass[level] += mass
        cand_ll = -math.log(max(float(cand_probs.get(actual, 0.0)), EPS_PROB))
        ref_ll = -math.log(max(float(ref_probs.get(actual, 0.0)), EPS_PROB))
        candidate_loss += cand_ll
        reference_loss += ref_ll
        action_by_hand[str(row["hand_id"])].append(cand_ll - ref_ll)
        candidate_predictions.append((cand_probs, actual))
        reference_predictions.append((ref_probs, actual))
        candidate_brier += sum((prob - float(action == actual)) ** 2 for action, prob in cand_probs.items())
        reference_brier += sum((prob - float(action == actual)) ** 2 for action, prob in ref_probs.items())
        street = str(row["street"])
        by_street[street]["n"] += 1
        by_street[street]["candidate_loss"] += cand_ll
        by_street[street]["reference_loss"] += ref_ll

        actual_bucket = row.get("actual_hand_bucket")
        if actual_bucket:
            exact_row = {**row, "hand_posterior": {str(actual_bucket): 1.0}}
            exact_cand, _ = marginal_action_probabilities(candidate, exact_row)
            exact_ref, _ = marginal_action_probabilities(reference, exact_row)
            revealed["n"] += 1
            revealed["candidate_loss"] += -math.log(max(exact_cand.get(actual, 0.0), EPS_PROB))
            revealed["reference_loss"] += -math.log(max(exact_ref.get(actual, 0.0), EPS_PROB))

        observed = row.get("incremental_cost_over_pot")
        if actual == "RAISE" and observed is not None:
            cand_size = marginal_sizing_prediction(candidate, row)
            ref_size = marginal_sizing_prediction(reference, row)
            if cand_size and ref_size and float(observed) > 0:
                cand_error = abs(math.log(cand_size / float(observed)))
                ref_error = abs(math.log(ref_size / float(observed)))
                sizing["n"] += 1
                sizing["candidate_error"] += cand_error
                sizing["reference_error"] += ref_error
                sizing_by_hand[str(row["hand_id"])].append(cand_error - ref_error)

    n = len(validation_rows)
    action_cluster = {
        hand_id: (sum(values), len(values)) for hand_id, values in action_by_hand.items()
    }
    sizing_cluster = {
        hand_id: (sum(values), len(values)) for hand_id, values in sizing_by_hand.items()
    }
    action_bootstrap = paired_bootstrap(action_cluster, seed=seed, samples=bootstrap_samples)
    sizing_bootstrap = paired_bootstrap(sizing_cluster, seed=seed + 1, samples=bootstrap_samples)

    street_report = {}
    for street, values in sorted(by_street.items()):
        count = int(values["n"])
        street_report[street] = {
            "n": count,
            "candidate_log_loss": values["candidate_loss"] / count,
            "reference_log_loss": values["reference_loss"] / count,
            "delta": (values["candidate_loss"] - values["reference_loss"]) / count,
        }

    return {
        "actions": {
            "n": n,
            "candidate_log_loss": candidate_loss / n,
            "reference_log_loss": reference_loss / n,
            "delta": (candidate_loss - reference_loss) / n,
            "candidate_brier": candidate_brier / n,
            "reference_brier": reference_brier / n,
            "candidate_confidence_ece": confidence_ece(candidate_predictions),
            "reference_confidence_ece": confidence_ece(reference_predictions),
            "paired_hand_bootstrap": action_bootstrap,
            "candidate_hierarchy_mass": {str(k): v for k, v in sorted(hierarchy_mass.items())},
            "by_street": street_report,
        },
        "sizing": {
            "n": int(sizing["n"]),
            "candidate_mean_absolute_log_error": (
                sizing["candidate_error"] / sizing["n"] if sizing["n"] else None
            ),
            "reference_mean_absolute_log_error": (
                sizing["reference_error"] / sizing["n"] if sizing["n"] else None
            ),
            "paired_hand_bootstrap": sizing_bootstrap,
        },
        "revealed_only_report_not_for_selection": {
            "n": int(revealed["n"]),
            "candidate_log_loss": revealed["candidate_loss"] / revealed["n"] if revealed["n"] else None,
            "reference_log_loss": revealed["reference_loss"] / revealed["n"] if revealed["n"] else None,
        },
    }


def counterfactual_price_diagnostic(
    validation_rows: Sequence[Mapping[str, Any]], candidate: Mapping[str, Any], limit: int = 500
) -> dict[str, Any]:
    tested = monotone = 0
    changes = []
    for row in validation_rows:
        if tested >= limit:
            break
        if row["mode"] != "FACING" or "FOLD" not in row["legal_actions"]:
            continue
        bucket = max(row["hand_posterior"], key=row["hand_posterior"].get)
        fold_probs = []
        for price in PRICE_ORDER:
            mutated = {**row, "price_bucket": price}
            probs, _ = action_probabilities(candidate, mutated, bucket)
            fold_probs.append(float(probs.get("FOLD", 0.0)))
        tested += 1
        if all(a <= b + 1e-12 for a, b in zip(fold_probs, fold_probs[1:])):
            monotone += 1
        changes.append(max(fold_probs) - min(fold_probs))
    return {
        "contexts": tested,
        "monotone_non_decreasing_fold_probability": monotone,
        "monotone_rate": monotone / tested if tested else None,
        "mean_fold_probability_range": sum(changes) / len(changes) if changes else None,
        "selection_gate": false if False else False
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incumbent-dir", type=Path, required=True)
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--certification", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--stake", action="append", default=["100/200"])
    parser.add_argument("--exclude-player", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    protocol = load(args.protocol)
    profiles = load(args.incumbent_dir / "profiles.json")
    records, population = certified_records(args.archive, set(args.stake), args.certification)
    excluded = set(args.exclude_player)
    prior_cfg = protocol["hidden_hand_assignment"]
    prior = build_action_independent_prior(
        records,
        profiles,
        excluded,
        minimum_revealed_labels=int(prior_cfg["minimum_revealed_labels_per_node"]),
        prior_strength=float(prior_cfg["combinatorial_prior_strength"]),
    )

    train_rows, train_audit = extract_decisions(
        records, "TRAIN", prior, profiles, excluded, training_labels=True
    )
    candidate_cfg = protocol["candidate"]
    reference_cfg = protocol["reference"]
    candidate = fit_behavior_from_soft_decisions(
        train_rows,
        action_levels=candidate_cfg["action_levels"],
        sizing_levels=candidate_cfg["sizing_levels"],
        action_backoff_min_observations=int(candidate_cfg["action_backoff_min_observations"]),
        sizing_backoff_min_observations=int(candidate_cfg["sizing_backoff_min_observations"]),
        alpha_per_action=float(candidate_cfg["alpha_per_legal_action"]),
        population_id=protocol["population_id"],
    )
    reference = fit_behavior_from_soft_decisions(
        train_rows,
        action_levels=reference_cfg["action_levels"],
        sizing_levels=reference_cfg["sizing_levels"],
        action_backoff_min_observations=int(candidate_cfg["action_backoff_min_observations"]),
        sizing_backoff_min_observations=int(candidate_cfg["sizing_backoff_min_observations"]),
        alpha_per_action=float(candidate_cfg["alpha_per_legal_action"]),
        population_id=protocol["population_id"],
    )

    validation_rows, validation_audit = extract_decisions(
        records, "VALIDATION", prior, profiles, excluded, training_labels=False
    )
    validation_cfg = protocol["validation"]
    validation = evaluate(
        validation_rows,
        candidate,
        reference,
        bootstrap_samples=int(validation_cfg["bootstrap_samples"]),
        seed=int(validation_cfg["bootstrap_seed"]),
    )
    validation["counterfactual_price_diagnostic"] = counterfactual_price_diagnostic(
        validation_rows, candidate
    )

    action_ci = validation["actions"]["paired_hand_bootstrap"]["ci95"]
    sizing_ci = validation["sizing"]["paired_hand_bootstrap"]["ci95"]
    action_pass = bool(action_ci and float(action_ci[1]) <= 0.0)
    sizing_pass = bool(sizing_ci and float(sizing_ci[1]) <= 0.0)
    accepted = action_pass and sizing_pass
    result = {
        "schema": "independent-model-b-card-aware-result/v1",
        "related_issue": 104,
        "protocol": str(args.protocol),
        "population": population,
        "fit": {
            "prior_audit": prior["audit"],
            "decision_audit": train_audit,
            "candidate_audit": candidate["audit"],
            "reference_audit": reference["audit"],
        },
        "validation_audit": validation_audit,
        "validation": validation,
        "gate": {
            "action_ci95_upper_at_most": 0.0,
            "action_pass": action_pass,
            "sizing_ci95_upper_at_most": 0.0,
            "sizing_pass": sizing_pass,
            "pass": accepted,
        },
        "decision": "ACCEPT_EXPERIMENTAL_BEHAVIOR_COMPONENT" if accepted else "RETAIN_PUBLIC_ONLY_REFERENCE_FOR_BEHAVIOR_COMPONENT",
        "test_consumed": False,
        "production_model_b_effect": "NONE",
        "hero_strategy_effect": "NONE",
        "issue_103_input_status": "RETAIN_BASELINE_RANGE_COMPONENT; action-conditioned latent posterior not used for issue #104 target-side assignment",
    }

    out = args.output_dir
    write(out / "hand_prior.json", prior)
    write(out / "candidate_behavior.json", candidate)
    write(out / "public_reference_behavior.json", reference)
    write(out / "TRAIN_AUDIT.json", train_audit)
    write(out / "VALIDATION.json", validation)
    write(out / "RESULT.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
