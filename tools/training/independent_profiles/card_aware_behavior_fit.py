#!/usr/bin/env python3
"""Posterior-weighted fitting primitives for card-aware independent Model B.

The central rule is that a hidden hand remains hidden. Each observed decision may
carry a posterior distribution over private hand buckets; its action and sizing
then contribute fractionally to every compatible bucket. A revealed hand is the
special case of a point-mass posterior.

This module deliberately does not infer those posteriors. Issue #103 owns the
reveal-aware latent-range estimator. The functions here define the stable seam
between latent range inference and issue #104 behavior fitting, without importing
Model A or Hero policy outputs.
"""
from __future__ import annotations

import itertools
import math
from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

from tools.simulation.model_b_card_aware_runtime import BEHAVIOR_SCHEMA, SIZING_SEMANTICS, hand_bucket
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


def _class_combo_ids(hand_class: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in itertools.combinations(range(52), 2):
        if combo_class_ids(a, b) == hand_class:
            out.append((a, b))
    if not out:
        raise ValueError(f"unknown 169-class notation: {hand_class}")
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
    from tools.simulation.model_b_runtime import cid

    classes = normalized_posterior(class_posterior)
    blocked = {cid(card) for card in board}
    bucket_mass: dict[str, float] = defaultdict(float)
    retained_class_mass = 0.0
    for hand_class, class_mass in classes.items():
        combos = [(a, b) for a, b in _class_combo_ids(hand_class) if a not in blocked and b not in blocked]
        if not combos:
            continue
        retained_class_mass += class_mass
        combo_mass = class_mass / len(combos)
        for a, b in combos:
            bucket = hand_bucket([ccode(a), ccode(b)], board, street)
            bucket_mass[bucket] += combo_mass
    if retained_class_mass <= 0:
        raise ValueError("latent range has no legal mass after public-card blocking")
    return normalized_posterior(bucket_mass)


def _weighted_action_node() -> dict[str, Any]:
    return {"n": 0.0, "counts": defaultdict(float)}


def _weighted_sizing_node() -> dict[str, Any]:
    return {"n": 0.0, "weighted_values": []}


def _serialize_action_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "n": round(float(node["n"]), 9),
        "counts": {key: round(float(value), 9) for key, value in sorted(node["counts"].items()) if value > 0},
    }


def _serialize_sizing_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "n": round(float(node["n"]), 9),
        "weighted_values": [
            {"value": round(float(row["value"]), 12), "weight": round(float(row["weight"]), 9)}
            for row in node["weighted_values"]
            if float(row["weight"]) > 0
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
    each hierarchy level.
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

        for private_bucket, weight in posterior.items():
            enriched = {**row, "hand_bucket": private_bucket}
            for level_index, columns in enumerate(action_levels):
                key = key_for(columns, enriched)
                node = action_tables[level_index][key]
                node["n"] += weight
                node["counts"][action] += weight

            sizing = row.get("incremental_cost_over_pot")
            if action == "RAISE" and sizing is not None:
                sizing = float(sizing)
                if not math.isfinite(sizing) or sizing <= 0:
                    raise ValueError(f"invalid incremental_cost_over_pot: {sizing}")
                sizing_row = {**enriched, "action": action}
                for level_index, columns in enumerate(sizing_levels):
                    key = key_for(columns, sizing_row)
                    node = sizing_tables[level_index][key]
                    node["n"] += weight
                    node["weighted_values"].append({"value": sizing, "weight": weight})
        if action == "RAISE" and row.get("incremental_cost_over_pot") is not None:
            audit["sizing_decisions"] += 1

    action_serialized = []
    for columns, table in zip(action_levels, action_tables):
        action_serialized.append({
            "cols": list(columns),
            "data": {key: _serialize_action_node(node) for key, node in sorted(table.items())},
        })
    sizing_serialized = []
    for columns, table in zip(sizing_levels, sizing_tables):
        sizing_serialized.append({
            "cols": list(columns),
            "data": {key: _serialize_sizing_node(node) for key, node in sorted(table.items())},
        })

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
