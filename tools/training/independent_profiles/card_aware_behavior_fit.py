#!/usr/bin/env python3
"""Posterior-weighted fitting primitives for card-aware independent Model B.

The central rule is that a hidden hand remains hidden. Each observed decision may
carry a posterior distribution over private hand buckets; its action and sizing
then contribute fractionally to every compatible bucket. A revealed hand is the
special case of a point-mass posterior.

This module deliberately does not infer those posteriors. Issue #103 owns the
reveal-bias evidence; issue #104 uses an action-independent TRAIN prior at the
fit seam so the target action cannot leak into its own private-hand assignment.
"""
from __future__ import annotations

import itertools
import math
from collections import Counter, defaultdict
from functools import lru_cache
from typing import Any, Iterable, Mapping, Sequence

from tools.simulation.model_b_card_aware_runtime import (
    BEHAVIOR_SCHEMA,
    CATEGORY,
    RANK_VALUE,
    SIZING_SEMANTICS,
    _draw_tags,
    hand_bucket,
)
from tools.simulation.model_b_runtime import ccode, combo_class_ids, key_for

ACTION_LABELS = ("FOLD", "CHECK", "CALL", "RAISE")


def normalized_posterior(values: Mapping[str, float]) -> dict[str, float]:
    clean: dict[str, float] = {}
    for key, value in values.items():
        value = float(value)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"invalid posterior mass for {key}: {value}")
        if value > 0:
            clean[str(key)] = value
    total = sum(clean.values())
    if total <= 0:
        raise ValueError("posterior must contain positive finite mass")
    return {key: value / total for key, value in clean.items()}


def exact_hand_posterior(hole_cards: Sequence[str], board: Sequence[str], street: str) -> dict[str, float]:
    return {hand_bucket(hole_cards, board, street): 1.0}


@lru_cache(maxsize=169)
def _class_combo_ids(hand_class: str) -> tuple[tuple[int, int], ...]:
    out: list[tuple[int, int]] = []
    for a, b in itertools.combinations(range(52), 2):
        if combo_class_ids(a, b) == hand_class:
            out.append((a, b))
    if not out:
        raise ValueError(f"unknown 169-class notation: {hand_class}")
    return tuple(out)


def _has_straight(ranks: Iterable[int]) -> bool:
    values = set(int(rank) for rank in ranks)
    if 14 in values:
        values.add(1)
    return any(all(rank in values for rank in range(low, low + 5)) for low in range(1, 11))


def _made_category_fast(cards: Sequence[str]) -> int:
    """Return the best 5-card category for 5-7 cards without tie-break work.

    ``hand_bucket`` needs only the category.  The canonical ``best`` evaluator
    also computes complete kickers/tie-breaks by enumerating every 5-card subset;
    avoiding that work keeps the posterior projection exact while making the full
    TRAIN/VALIDATION fit tractable.
    """
    if not 5 <= len(cards) <= 7:
        raise ValueError("card-aware category requires 5-7 cards")
    rank_counts = Counter(RANK_VALUE[str(card)[0].upper()] for card in cards)
    by_suit: dict[str, list[int]] = defaultdict(list)
    for card in cards:
        by_suit[str(card)[1].lower()].append(RANK_VALUE[str(card)[0].upper()])

    if any(len(ranks) >= 5 and _has_straight(ranks) for ranks in by_suit.values()):
        return 8
    if any(count >= 4 for count in rank_counts.values()):
        return 7
    trips = [rank for rank, count in rank_counts.items() if count >= 3]
    if trips and any(count >= 2 and rank not in trips[:1] for rank, count in rank_counts.items()):
        # Equivalent to "one trip plus another pair/trip".  Using rank identity
        # rather than count arithmetic also handles two distinct trips correctly.
        primary = trips[0]
        if any(rank != primary and count >= 2 for rank, count in rank_counts.items()):
            return 6
    if any(len(ranks) >= 5 for ranks in by_suit.values()):
        return 5
    if _has_straight(rank_counts):
        return 4
    if trips:
        return 3
    pairs = sum(count >= 2 for count in rank_counts.values())
    if pairs >= 2:
        return 2
    if pairs == 1:
        return 1
    return 0


def _projected_hand_bucket(hole_cards: Sequence[str], board: Sequence[str], street: str) -> str:
    """Fast exact equivalent of runtime ``hand_bucket`` for postflop projection."""
    cards = [str(card) for card in list(hole_cards) + list(board)]
    if len(cards) != len(set(cards)):
        raise ValueError("duplicate private/public card in Model B state")
    street = str(street).lower()
    if street == "preflop":
        return hand_bucket(hole_cards, board, street)
    category = _made_category_fast(cards)
    return "+".join([CATEGORY[category]] + _draw_tags(hole_cards, board, category))


@lru_cache(maxsize=64)
def _board_class_bucket_frequencies(
    board_tuple: tuple[str, ...], street: str
) -> dict[str, tuple[int, tuple[tuple[str, int], ...]]]:
    """Map each 169 class to exact runtime-bucket frequencies for one board.

    This expensive card evaluation depends on the public board, not on the
    profile/position prior.  Several actors on the same hand therefore share it.
    The small LRU intentionally retains only recent boards and bounds memory.
    """
    from tools.simulation.model_b_runtime import cid

    blocked = {cid(card) for card in board_tuple}
    out: dict[str, tuple[int, tuple[tuple[str, int], ...]]] = {}
    # The 169 classes are exactly those present in the cached combo map once it is
    # warmed.  Generate names directly from all exact combos here to stay local.
    classes: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for a, b in itertools.combinations(range(52), 2):
        classes[combo_class_ids(a, b)].append((a, b))
    for hand_class, all_combos in classes.items():
        counts: Counter[str] = Counter()
        legal = 0
        for a, b in all_combos:
            if a in blocked or b in blocked:
                continue
            legal += 1
            bucket = _projected_hand_bucket([ccode(a), ccode(b)], board_tuple, street)
            counts[bucket] += 1
        out[hand_class] = (legal, tuple(sorted(counts.items())))
    return out


def bucket_posterior_from_classes(
    class_posterior: Mapping[str, float],
    *,
    board: Sequence[str],
    street: str,
) -> dict[str, float]:
    """Project a latent 169-class posterior into runtime hand buckets.

    Within each class, legal exact combinations are exchangeable unless another
    independent Model-B component supplies finer information. Public board cards
    are blocked before the class mass is distributed. No future board cards are
    accepted or generated.
    """
    classes = normalized_posterior(class_posterior)
    street = str(street).lower()
    if street == "preflop":
        return {f"PREFLOP_{key}": value for key, value in classes.items()}

    frequencies = _board_class_bucket_frequencies(tuple(str(card) for card in board), street)
    bucket_mass: dict[str, float] = defaultdict(float)
    retained_class_mass = 0.0
    for hand_class, class_mass in classes.items():
        legal, counts = frequencies.get(hand_class, (0, ()))
        if legal <= 0:
            continue
        retained_class_mass += class_mass
        for bucket, count in counts:
            bucket_mass[bucket] += class_mass * float(count) / float(legal)
    if retained_class_mass <= 0:
        raise ValueError("latent range has no legal mass after public-card blocking")
    return normalized_posterior(bucket_mass)


def _weighted_action_node() -> dict[str, Any]:
    return {"n": 0.0, "counts": defaultdict(float)}


def _weighted_sizing_node() -> dict[str, Any]:
    return {"n": 0.0, "value_weights": defaultdict(float)}


def _serialize_action_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "n": round(float(node["n"]), 9),
        "counts": {key: round(float(value), 9) for key, value in sorted(node["counts"].items()) if value > 0},
    }


def _serialize_sizing_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "n": round(float(node["n"]), 9),
        "weighted_values": [
            {"value": float(value), "weight": round(float(weight), 9)}
            for value, weight in sorted(node["value_weights"].items())
            if float(weight) > 0
        ],
    }


def fit_behavior_from_soft_decisions(
    decisions: Iterable[Mapping[str, Any]],
    *,
    action_levels: Sequence[Sequence[str]],
    sizing_levels: Sequence[Sequence[str]],
    action_backoff_min_observations: int = 30,
    sizing_backoff_min_observations: int = 12,
    alpha_per_action: float = 1.0,
    population_id: str | None = None,
) -> dict[str, Any]:
    """Fit hierarchical behavior tables from soft private-hand assignments.

    Expected decision row fields:
      public: profile, street, mode, relative_position, pot_type, preflop_role,
              price_bucket, spr_bucket, opponents_bucket, sequence_bucket,
              raise_level, board_texture
      target: action in FOLD/CHECK/CALL/RAISE
      latent: hand_posterior {runtime_hand_bucket: probability}
      optional sizing: incremental_cost_over_pot (positive finite float)

    ``n`` is effective posterior-weighted observation mass and may therefore be
    fractional. Every original decision contributes total mass exactly 1.0 to
    each hierarchy level. Sizing values are keyed by their exact Python float and
    posterior weights are accumulated rather than duplicating samples.
    """
    if int(action_backoff_min_observations) <= 0 or int(sizing_backoff_min_observations) <= 0:
        raise ValueError("backoff thresholds must be positive")
    if float(alpha_per_action) <= 0:
        raise ValueError("alpha_per_action must be positive")

    action_tables: list[dict[str, dict[str, Any]]] = [defaultdict(_weighted_action_node) for _ in action_levels]
    sizing_tables: list[dict[str, dict[str, Any]]] = [defaultdict(_weighted_sizing_node) for _ in sizing_levels]
    audit = {
        "decisions": 0,
        "revealed_point_mass_decisions": 0,
        "latent_soft_decisions": 0,
        "sizing_decisions": 0,
        "posterior_mass_error_max": 0.0,
    }

    for raw in decisions:
        row = dict(raw)
        action = str(row.get("action", "")).upper()
        if action not in ACTION_LABELS:
            raise ValueError(f"unsupported canonical action: {action}")
        posterior = normalized_posterior(row.get("hand_posterior") or {})
        mass_error = abs(sum(posterior.values()) - 1.0)
        audit["posterior_mass_error_max"] = max(audit["posterior_mass_error_max"], mass_error)
        audit["decisions"] += 1
        audit["revealed_point_mass_decisions" if len(posterior) == 1 else "latent_soft_decisions"] += 1

        sizing = row.get("incremental_cost_over_pot")
        if action == "RAISE" and sizing is not None:
            sizing = float(sizing)
            if not math.isfinite(sizing) or sizing <= 0:
                raise ValueError(f"invalid incremental_cost_over_pot: {sizing}")

        for private_bucket, weight in posterior.items():
            enriched = {**row, "hand_bucket": private_bucket}
            for level_index, columns in enumerate(action_levels):
                key = key_for(columns, enriched)
                node = action_tables[level_index][key]
                node["n"] += weight
                node["counts"][action] += weight

            if action == "RAISE" and sizing is not None:
                sizing_row = {**enriched, "action": action}
                for level_index, columns in enumerate(sizing_levels):
                    key = key_for(columns, sizing_row)
                    node = sizing_tables[level_index][key]
                    node["n"] += weight
                    node["value_weights"][sizing] += weight
        if action == "RAISE" and sizing is not None:
            audit["sizing_decisions"] += 1

    action_serialized = [
        {
            "cols": list(columns),
            "data": {key: _serialize_action_node(node) for key, node in sorted(table.items())},
        }
        for columns, table in zip(action_levels, action_tables)
    ]
    sizing_serialized = [
        {
            "cols": list(columns),
            "data": {key: _serialize_sizing_node(node) for key, node in sorted(table.items())},
        }
        for columns, table in zip(sizing_levels, sizing_tables)
    ]

    return {
        "schema": BEHAVIOR_SCHEMA,
        "population_id": population_id,
        "fit": {
            "private_hand_assignment": "posterior_weighted; revealed hands are point masses and hidden hands remain latent",
            "source_split": "TRAIN",
            "model_a_inputs": False,
            "hero_policy_inputs": False,
        },
        "action": {
            "alpha_per_action": float(alpha_per_action),
            "backoff_min_observations": int(action_backoff_min_observations),
            "levels": action_serialized,
        },
        "sizing": {
            "semantics": SIZING_SEMANTICS,
            "backoff_min_observations": int(sizing_backoff_min_observations),
            "levels": sizing_serialized,
        },
        "audit": audit,
    }
