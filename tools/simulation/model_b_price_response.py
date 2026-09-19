#!/usr/bin/env python3
"""Future-generation Model B response-to-price representation.

This module is deliberately additive: it does not change the promoted Model B
pointer or any frozen scientific protocol. It builds/loads a candidate from
TRAIN-derived decision rows only, conditions on public response context, and
uses explicit hierarchical backoff instead of imposing a monotonic fold curve.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "independent-opponent-model-b-response-to-price/v1"
ACTIONS = ("FOLD", "CALL", "RAISE")
PRICE_EDGES = (0.25, 0.50, 0.75, 1.00, 1.50, 2.50)
SPR_EDGES = (1.0, 2.0, 4.0, 8.0)
REQUIRED_CONTEXT = (
    "profile",
    "street",
    "relative_position",
    "pot_type",
    "sequence",
)
FULL_DIMENSIONS = REQUIRED_CONTEXT + ("price_bucket", "spr_bucket")
HIERARCHY = (
    FULL_DIMENSIONS,
    ("street", "relative_position", "pot_type", "sequence", "price_bucket", "spr_bucket"),
    ("street", "pot_type", "sequence", "price_bucket", "spr_bucket"),
    ("street", "sequence", "price_bucket", "spr_bucket"),
    ("street", "price_bucket", "spr_bucket"),
    ("street", "price_bucket"),
    ("street",),
    (),
)


def _finite_nonnegative(value: Any, *, name: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result


def price_bucket(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    x = _finite_nonnegative(value, name="facing_price_to_pot")
    labels = (
        "P00_25",
        "P25_50",
        "P50_75",
        "P75_100",
        "P100_150",
        "P150_250",
        "P250_PLUS",
    )
    for edge, label in zip(PRICE_EDGES, labels):
        if x <= edge:
            return label
    return labels[-1]


def spr_bucket(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    x = _finite_nonnegative(value, name="spr")
    labels = ("SPR00_1", "SPR1_2", "SPR2_4", "SPR4_8", "SPR8_PLUS")
    for edge, label in zip(SPR_EDGES, labels):
        if x <= edge:
            return label
    return labels[-1]


def _key(columns: Sequence[str], row: Mapping[str, Any]) -> str:
    return "ALL" if not columns else "|".join(str(row[name]) for name in columns)


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    pos = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def _context_row(row: Mapping[str, Any]) -> dict[str, Any]:
    missing = [name for name in REQUIRED_CONTEXT if row.get(name) is None]
    if missing:
        raise ValueError(f"missing response-to-price context fields: {missing}")
    return {
        "profile": int(row["profile"]),
        "street": str(row["street"]).lower(),
        "relative_position": str(row["relative_position"]),
        "pot_type": str(row["pot_type"]),
        "sequence": str(row["sequence"]),
        "price_bucket": price_bucket(row.get("facing_price_to_pot")),
        "spr_bucket": spr_bucket(row.get("spr")),
    }


def build_response_artifact(
    observations: Iterable[Mapping[str, Any]],
    *,
    min_support: int = 30,
    sizing_min_support: int = 12,
    alpha_per_action: float = 1.0,
    model_version: str = "model_b_response_to_price_v1_candidate",
) -> dict[str, Any]:
    """Build a versioned candidate table from TRAIN-like decision observations.

    The input must already be split upstream; this function never reads TEST and
    never performs model selection. Action frequencies are empirical and no
    monotonic relationship between price and folding is introduced.
    """
    if int(min_support) <= 0:
        raise ValueError("min_support must be positive")
    if int(sizing_min_support) <= 0:
        raise ValueError("sizing_min_support must be positive")
    alpha = float(alpha_per_action)
    if not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("alpha_per_action must be finite and positive")

    counts: list[dict[str, Counter[str]]] = [defaultdict(Counter) for _ in HIERARCHY]
    sizings: list[dict[str, list[float]]] = [defaultdict(list) for _ in HIERARCHY]
    total = 0
    sizing_total = 0
    for raw in observations:
        row = _context_row(raw)
        action = str(raw.get("action") or "").upper()
        if action not in ACTIONS:
            raise ValueError(f"unsupported response action: {action!r}")
        total += 1
        sizing = raw.get("raise_sizing_ratio")
        clean_sizing = None
        if sizing is not None:
            clean_sizing = float(sizing)
            if not math.isfinite(clean_sizing) or clean_sizing <= 0:
                raise ValueError("raise_sizing_ratio must be finite and positive")
            if action != "RAISE":
                raise ValueError("raise_sizing_ratio is only valid for RAISE observations")
            sizing_total += 1
        for level_index, columns in enumerate(HIERARCHY):
            key = _key(columns, row)
            counts[level_index][key][action] += 1
            if clean_sizing is not None:
                sizings[level_index][key].append(clean_sizing)

    if total == 0:
        raise ValueError("at least one observation is required")

    levels = []
    for columns, level_counts, level_sizings in zip(HIERARCHY, counts, sizings):
        data: dict[str, Any] = {}
        for key in sorted(level_counts):
            action_counts = level_counts[key]
            values = level_sizings.get(key, [])
            data[key] = {
                "n": int(sum(action_counts.values())),
                "counts": {action: int(action_counts.get(action, 0)) for action in ACTIONS},
                "raise_sizing_ratios": [float(value) for value in values],
            }
        levels.append({"cols": list(columns), "data": data})

    return {
        "schema": SCHEMA,
        "model_version": model_version,
        "status": "CANDIDATE_NOT_PROMOTED",
        "fit_split": "TRAIN",
        "production_effect": "NONE",
        "feature_contract": {
            "allowed_dimensions": list(FULL_DIMENSIONS),
            "forbidden_sources": ["model_a_ev", "model_a_policy", "model_a_recommendation"],
            "price_monotonicity_assumption": "NONE",
        },
        "price_edges": list(PRICE_EDGES),
        "spr_edges": list(SPR_EDGES),
        "backoff_min_observations": int(min_support),
        "sizing_backoff_min_observations": int(sizing_min_support),
        "alpha_per_action": alpha,
        "training_counts": {"decisions": total, "raise_sizings": sizing_total},
        "levels": levels,
    }


def validate_artifact(document: Mapping[str, Any]) -> None:
    if document.get("schema") != SCHEMA:
        raise ValueError(f"unsupported response-to-price schema: {document.get('schema')!r}")
    if document.get("status") != "CANDIDATE_NOT_PROMOTED":
        raise ValueError("response-to-price artifact must remain an unpromoted candidate")
    if document.get("production_effect") != "NONE":
        raise ValueError("candidate artifact must not change active Model B")
    if document.get("fit_split") != "TRAIN":
        raise ValueError("response-to-price candidates must be fit on TRAIN only")
    feature_contract = document.get("feature_contract") or {}
    if tuple(feature_contract.get("allowed_dimensions") or ()) != FULL_DIMENSIONS:
        raise ValueError("response-to-price feature contract differs from the approved public context")
    if feature_contract.get("price_monotonicity_assumption") != "NONE":
        raise ValueError("price monotonicity must not be hard-coded")
    if int(document.get("backoff_min_observations", 0)) <= 0:
        raise ValueError("invalid backoff support threshold")
    if int(document.get("sizing_backoff_min_observations", 0)) <= 0:
        raise ValueError("invalid sizing backoff support threshold")
    alpha = float(document.get("alpha_per_action", 0.0))
    if not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("invalid alpha_per_action")
    levels = document.get("levels") or []
    if len(levels) != len(HIERARCHY):
        raise ValueError("response-to-price hierarchy is incomplete")
    for expected, level in zip(HIERARCHY, levels):
        if tuple(level.get("cols") or ()) != expected:
            raise ValueError("response-to-price hierarchy order changed")


def artifact_sha256(document: Mapping[str, Any]) -> str:
    payload = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class Selection:
    level: int
    columns: tuple[str, ...]
    key: str
    support: int
    used_backoff: bool
    below_min_support: bool


class ResponseToPriceModel:
    """Read-only runtime for an unpromoted response-to-price candidate."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        self.document = dict(document)
        validate_artifact(self.document)
        self.min_support = int(self.document["backoff_min_observations"])
        self.sizing_min_support = int(self.document["sizing_backoff_min_observations"])
        self.alpha = float(self.document["alpha_per_action"])
        self.identity = {
            "schema": SCHEMA,
            "model_version": str(self.document["model_version"]),
            "artifact_sha256": artifact_sha256(self.document),
            "production_effect": "NONE",
        }

    def _select(self, row: Mapping[str, Any]) -> tuple[Mapping[str, Any], Selection]:
        context = _context_row(row)
        fallback = None
        fallback_selection = None
        for index, level in enumerate(self.document["levels"]):
            columns = tuple(level["cols"])
            key = _key(columns, context)
            node = (level.get("data") or {}).get(key)
            if node is None:
                continue
            support = int(node.get("n", 0))
            selection = Selection(
                level=index,
                columns=columns,
                key=key,
                support=support,
                used_backoff=index > 0,
                below_min_support=support < self.min_support,
            )
            fallback = node
            fallback_selection = selection
            if support >= self.min_support:
                return node, selection
        if fallback is None or fallback_selection is None:
            raise KeyError(f"no response-to-price node for context {context}")
        return fallback, fallback_selection

    def _select_sizing(
        self,
        row: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any] | None, Selection | None]:
        context = _context_row(row)
        fallback = None
        fallback_selection = None
        for index, level in enumerate(self.document["levels"]):
            columns = tuple(level["cols"])
            key = _key(columns, context)
            node = (level.get("data") or {}).get(key)
            if node is None:
                continue
            values = [
                float(value)
                for value in node.get("raise_sizing_ratios", [])
                if math.isfinite(float(value)) and float(value) > 0
            ]
            if not values:
                continue
            support = len(values)
            selection = Selection(
                level=index,
                columns=columns,
                key=key,
                support=support,
                used_backoff=index > 0,
                below_min_support=support < self.sizing_min_support,
            )
            fallback = node
            fallback_selection = selection
            if support >= self.sizing_min_support:
                return node, selection
        return fallback, fallback_selection

    def sizing_values(self, **context: Any) -> list[float]:
        node, _ = self._select_sizing(context)
        if node is None:
            return []
        return [
            float(value)
            for value in node.get("raise_sizing_ratios", [])
            if math.isfinite(float(value)) and float(value) > 0
        ]

    def predict(self, **context: Any) -> dict[str, Any]:
        node, selection = self._select(context)
        counts = {
            action: float((node.get("counts") or {}).get(action, 0.0))
            for action in ACTIONS
        }
        posterior = {action: counts[action] + self.alpha for action in ACTIONS}
        total = sum(posterior.values())
        probabilities = {action: posterior[action] / total for action in ACTIONS}
        uncertainty = {}
        for action in ACTIONS:
            a = posterior[action]
            var = a * (total - a) / (total * total * (total + 1.0))
            sd = math.sqrt(max(0.0, var))
            mean = probabilities[action]
            uncertainty[action] = {
                "mean": mean,
                "approx_95": [
                    max(0.0, mean - 1.96 * sd),
                    min(1.0, mean + 1.96 * sd),
                ],
            }
        sizing_node, sizing_selection = self._select_sizing(context)
        sizing_values = [] if sizing_node is None else [
            float(value)
            for value in sizing_node.get("raise_sizing_ratios", [])
            if math.isfinite(float(value)) and float(value) > 0
        ]
        if sizing_values:
            sizing = {
                "n": len(sizing_values),
                "p10": _quantile(sizing_values, 0.10),
                "median": _quantile(sizing_values, 0.50),
                "p90": _quantile(sizing_values, 0.90),
                "p99": _quantile(sizing_values, 0.99),
            }
        else:
            sizing = {
                "n": 0,
                "p10": None,
                "median": None,
                "p90": None,
                "p99": None,
            }
        return {
            "schema": "model-b-response-to-price-prediction/v1",
            "identity": self.identity,
            "probabilities": probabilities,
            "uncertainty": uncertainty,
            "sizing": sizing,
            "selection": {
                "level": selection.level,
                "columns": list(selection.columns),
                "key": selection.key,
                "support": selection.support,
                "used_backoff": selection.used_backoff,
                "below_min_support": selection.below_min_support,
            },
            "sizing_selection": None if sizing_selection is None else {
                "level": sizing_selection.level,
                "columns": list(sizing_selection.columns),
                "key": sizing_selection.key,
                "support": sizing_selection.support,
                "used_backoff": sizing_selection.used_backoff,
                "below_min_support": sizing_selection.below_min_support,
            },
            "identifiability": (
                "LOW_SUPPORT"
                if selection.below_min_support
                else "BACKOFF_SUPPORTED"
                if selection.used_backoff
                else "LOCAL_SUPPORTED"
            ),
            "buckets": {
                "price": price_bucket(context.get("facing_price_to_pot")),
                "spr": spr_bucket(context.get("spr")),
            },
        }

    def counterfactual_price_curve(
        self,
        *,
        price_points: Sequence[float],
        **fixed_context: Any,
    ) -> list[dict[str, Any]]:
        """Vary only facing price while keeping all other public context fixed."""
        out = []
        for price in price_points:
            prediction = self.predict(
                **fixed_context,
                facing_price_to_pot=float(price),
            )
            out.append({"facing_price_to_pot": float(price), **prediction})
        return out
