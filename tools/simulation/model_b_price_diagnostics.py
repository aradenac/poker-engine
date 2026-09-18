#!/usr/bin/env python3
"""Diagnostics for future-generation Model B response-to-price candidates.

All comparisons are validation-style and machine-readable. No environment is
assigned a probability and no diagnostic here promotes a candidate or consumes
TEST automatically.
"""
from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from typing import Any, Callable, Iterable, Mapping, Sequence

from tools.simulation.model_b_price_response import ACTIONS, price_bucket, spr_bucket

EPS = 1e-15
REPORT_SCHEMA = "model-b-response-to-price-diagnostics/v1"
Predictor = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def _action_metrics(rows: Sequence[tuple[str, Mapping[str, float]]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    loss = 0.0
    brier = 0.0
    observed = Counter()
    predicted = defaultdict(float)
    for actual, probabilities in rows:
        loss += -math.log(max(EPS, float(probabilities[actual])))
        brier += sum(
            (float(probabilities[action]) - (1.0 if action == actual else 0.0)) ** 2
            for action in ACTIONS
        )
        observed[actual] += 1
        for action in ACTIONS:
            predicted[action] += float(probabilities[action])
    n = len(rows)
    observed_frequency = {action: observed[action] / n for action in ACTIONS}
    mean_predicted_frequency = {action: predicted[action] / n for action in ACTIONS}
    calibration_l1 = sum(
        abs(observed_frequency[action] - mean_predicted_frequency[action])
        for action in ACTIONS
    ) / len(ACTIONS)
    return {
        "n": n,
        "log_loss": loss / n,
        "brier": brier / n,
        "calibration_l1": calibration_l1,
        "observed_frequency": observed_frequency,
        "mean_predicted_frequency": mean_predicted_frequency,
    }


def _percentile(values: Sequence[float], q: float) -> float:
    if not values:
        raise ValueError("cannot compute percentile of empty values")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    pos = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    w = pos - lo
    return ordered[lo] * (1.0 - w) + ordered[hi] * w


def paired_bootstrap(
    deltas_by_hand: Mapping[str, Sequence[float]],
    *,
    seed: int = 20260919,
    samples: int = 2000,
) -> dict[str, Any]:
    hands = sorted(deltas_by_hand)
    if not hands:
        raise ValueError("paired bootstrap requires at least one hand")
    observed_values = [
        value
        for hand in hands
        for value in deltas_by_hand[hand]
    ]
    observed = sum(observed_values) / len(observed_values)
    rng = random.Random(seed)
    draws = []
    for _ in range(int(samples)):
        sample = []
        for _ in hands:
            hand = hands[rng.randrange(len(hands))]
            sample.extend(deltas_by_hand[hand])
        draws.append(sum(sample) / len(sample))
    return {
        "cluster_unit": "hand_id",
        "hands": len(hands),
        "decisions": len(observed_values),
        "seed": seed,
        "bootstrap_samples": int(samples),
        "observed_candidate_minus_reference_log_loss": observed,
        "ci95": [_percentile(draws, 0.025), _percentile(draws, 0.975)],
        "probability_candidate_better": sum(value < 0 for value in draws) / len(draws),
    }


def support_audit(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    cells = Counter()
    for row in rows:
        cells[
            (
                price_bucket(row.get("facing_price_to_pot")),
                spr_bucket(row.get("spr")),
            )
        ] += 1
    return {
        "schema": "model-b-response-support-audit/v1",
        "cells": [
            {
                "price_bucket": price,
                "spr_bucket": spr,
                "n": count,
            }
            for (price, spr), count in sorted(cells.items())
        ],
    }


def evaluate_validation(
    rows: Iterable[Mapping[str, Any]],
    *,
    candidate_predict: Predictor,
    reference_predict: Predictor,
    bootstrap_samples: int = 2000,
) -> dict[str, Any]:
    candidate_rows = []
    reference_rows = []
    tail_candidate = []
    tail_reference = []
    candidate_sizing_errors = []
    reference_sizing_errors = []
    tail_candidate_sizing_errors = []
    tail_reference_sizing_errors = []
    deltas_by_hand: dict[str, list[float]] = defaultdict(list)
    support_rows = []
    selection_levels = Counter()
    identifiability = Counter()

    materialized = list(rows)
    for index, row in enumerate(materialized):
        actual = str(row.get("action") or "").upper()
        if actual not in ACTIONS:
            raise ValueError(f"validation row has unsupported action: {actual!r}")
        candidate = candidate_predict(row)
        reference = reference_predict(row)
        cp = {
            action: float(candidate["probabilities"][action])
            for action in ACTIONS
        }
        rp = {
            action: float(reference["probabilities"][action])
            for action in ACTIONS
        }
        candidate_rows.append((actual, cp))
        reference_rows.append((actual, rp))
        c_loss = -math.log(max(EPS, cp[actual]))
        r_loss = -math.log(max(EPS, rp[actual]))
        hand_id = str(row.get("hand_id") or f"row-{index}")
        deltas_by_hand[hand_id].append(c_loss - r_loss)

        selection = candidate.get("selection") or {}
        selection_levels[str(selection.get("level", "UNKNOWN"))] += 1
        identifiability[str(candidate.get("identifiability", "UNKNOWN"))] += 1
        support_rows.append(row)

        price = row.get("facing_price_to_pot")
        actual_sizing = row.get("raise_sizing_ratio")
        is_tail = (
            bool(row.get("is_jam"))
            or (price is not None and float(price) > 1.5)
            or (actual_sizing is not None and float(actual_sizing) > 1.5)
        )
        if is_tail:
            tail_candidate.append((actual, cp))
            tail_reference.append((actual, rp))

        if actual_sizing is not None and actual == "RAISE":
            actual_value = float(actual_sizing)
            c_median = (candidate.get("sizing") or {}).get("median")
            r_median = (reference.get("sizing") or {}).get("median")
            if c_median is not None:
                error = abs(float(c_median) - actual_value)
                candidate_sizing_errors.append(error)
                if is_tail:
                    tail_candidate_sizing_errors.append(error)
            if r_median is not None:
                error = abs(float(r_median) - actual_value)
                reference_sizing_errors.append(error)
                if is_tail:
                    tail_reference_sizing_errors.append(error)

    def sizing_summary(values: Sequence[float]) -> dict[str, Any]:
        return {
            "n": len(values),
            "mae": sum(values) / len(values) if values else None,
        }

    sizing = {
        "candidate": sizing_summary(candidate_sizing_errors),
        "reference": sizing_summary(reference_sizing_errors),
    }
    tail_sizing = {
        "candidate": sizing_summary(tail_candidate_sizing_errors),
        "reference": sizing_summary(tail_reference_sizing_errors),
    }
    return {
        "schema": REPORT_SCHEMA,
        "split": "VALIDATION",
        "candidate_actions": _action_metrics(candidate_rows),
        "reference_actions": _action_metrics(reference_rows),
        "paired_action_log_loss": paired_bootstrap(
            deltas_by_hand,
            samples=bootstrap_samples,
        ),
        "sizing_error": sizing,
        "tail_diagnostics": {
            "definition": "is_jam OR facing_price_to_pot > 1.5 OR raise_sizing_ratio > 1.5",
            "candidate_actions": _action_metrics(tail_candidate),
            "reference_actions": _action_metrics(tail_reference),
            "sizing_error": tail_sizing,
        },
        "support": support_audit(support_rows),
        "selected_level_counts": dict(sorted(selection_levels.items())),
        "identifiability_counts": dict(sorted(identifiability.items())),
        "promotion_effect": "NONE",
        "test_consumed": False,
    }


def counterfactual_response_report(
    contexts: Iterable[Mapping[str, Any]],
    *,
    price_points: Sequence[float],
    predict: Predictor,
) -> dict[str, Any]:
    rows = []
    for context_index, context in enumerate(contexts):
        curve = []
        for price in price_points:
            probe = dict(context)
            probe["facing_price_to_pot"] = float(price)
            prediction = predict(probe)
            curve.append(
                {
                    "price": float(price),
                    "fold": float(prediction["probabilities"]["FOLD"]),
                    "call": float(prediction["probabilities"]["CALL"]),
                    "raise": float(prediction["probabilities"]["RAISE"]),
                    "identifiability": prediction.get("identifiability"),
                    "selection": prediction.get("selection"),
                }
            )
        folds = [point["fold"] for point in curve]
        rows.append(
            {
                "context_index": context_index,
                "curve": curve,
                "fold_spread": max(folds) - min(folds),
                "fold_non_decreasing": all(
                    b >= a
                    for a, b in zip(folds, folds[1:])
                ),
                "monotonicity_is_gate": False,
            }
        )
    return {
        "schema": "model-b-response-counterfactual/v1",
        "varied_feature": "facing_price_to_pot",
        "fixed_features": "all supplied context except facing_price_to_pot",
        "contexts": rows,
    }


def plausible_action_environments(
    prediction: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Expose unweighted action environments from the candidate uncertainty band."""
    nominal = {
        action: float(prediction["probabilities"][action])
        for action in ACTIONS
    }
    fold_interval = prediction["uncertainty"]["FOLD"]["approx_95"]

    def with_fold(target_fold: float) -> dict[str, float]:
        target = min(1.0, max(0.0, float(target_fold)))
        residual = 1.0 - nominal["FOLD"]
        if residual <= EPS:
            return {"FOLD": 1.0, "CALL": 0.0, "RAISE": 0.0}
        scale = (1.0 - target) / residual
        return {
            "FOLD": target,
            "CALL": nominal["CALL"] * scale,
            "RAISE": nominal["RAISE"] * scale,
        }

    return [
        {
            "environment_id": "fold-low",
            "probabilities": with_fold(fold_interval[0]),
            "weight": None,
        },
        {
            "environment_id": "nominal",
            "probabilities": nominal,
            "weight": None,
        },
        {
            "environment_id": "fold-high",
            "probabilities": with_fold(fold_interval[1]),
            "weight": None,
        },
    ]


def summarize_strategy_sensitivity(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    materialized = list(rows)
    if not materialized:
        raise ValueError("strategy sensitivity requires at least one environment")
    actions = [str(row["action"]) for row in materialized]
    sizings = [row.get("sizing") for row in materialized]
    evs = [float(row["ev_bb"]) for row in materialized]
    best = max(evs)
    regrets = [best - value for value in evs]
    return {
        "schema": "hero-response-model-sensitivity/v1",
        "environment_count": len(materialized),
        "action_stable": len(set(actions)) == 1,
        "sizing_stable": len(
            {
                None if value is None else round(float(value), 9)
                for value in sizings
            }
        ) == 1,
        "ev_range_bb": [min(evs), max(evs)],
        "max_regret_bb": max(regrets),
        "environments_weighted": False,
    }
