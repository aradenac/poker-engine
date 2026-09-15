#!/usr/bin/env python3
"""Shared preflop probability response semantics.

Two modes are deliberately distinct:

- ``strict_probability_response`` is for future candidates. It normalizes over
  the legal actions in ``poker-preflop-context/v1``.
- ``incumbent_v5_passthrough`` is a compatibility view over already promoted
  v5/v83 probabilities. It validates and annotates them but never filters or
  renormalizes them, so observing the new contract cannot silently change the
  promoted policy.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

from tools.preflop.context_contract import (
    EPS,
    PROBABILITY_SCHEMA,
    context_id,
    normalize_action_probabilities,
)


def strict_probability_response(**kwargs: Any) -> dict[str, Any]:
    """Alias the canonical strict legal-action normalization contract."""
    result = normalize_action_probabilities(**kwargs)
    result["behavior_mode"] = "strict_legal_normalized"
    return result


def incumbent_v5_passthrough(
    *,
    context: Mapping[str, Any],
    raw_probabilities: Mapping[str, float],
    hand_class: str | None = None,
    sizing: Mapping[str, Any] | None = None,
    source: str,
    backoff_level: str,
    confidence: str,
    support: int | float,
) -> dict[str, Any]:
    """Expose incumbent probabilities without changing their numerical values."""
    probabilities: dict[str, float] = {}
    for action, raw in raw_probabilities.items():
        name = str(action).upper()
        value = float(raw or 0.0)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"invalid incumbent probability for {name}: {raw!r}")
        probabilities[name] = value
    if not probabilities:
        raise ValueError("incumbent probability response is empty")
    total = sum(probabilities.values())
    if total <= EPS:
        raise ValueError("incumbent probability mass is zero")

    legal = [str(x).upper() for x in context.get("legal_actions") or []]
    legal_set = set(legal)
    positive_model_actions = [a for a, p in probabilities.items() if p > EPS]
    incompatible = [a for a in positive_model_actions if legal_set and a not in legal_set]
    missing = [a for a in legal if a not in probabilities]
    return {
        "schema": PROBABILITY_SCHEMA,
        "behavior_mode": "incumbent_v5_passthrough",
        "context_id": str(context.get("context_id") or context_id(context)),
        "hand_class": hand_class,
        "legal_actions": legal,
        "model_actions": list(probabilities),
        "probabilities": probabilities,
        "probability_sum": total,
        "action_set_compatible": not incompatible,
        "positive_illegal_model_actions": incompatible,
        "missing_legal_model_actions": missing,
        "sizing": dict(sizing) if sizing is not None else None,
        "source": str(source),
        "backoff_level": str(backoff_level),
        "confidence": str(confidence),
        "support": int(support),
        "incumbent_compatibility": {
            "matcher": "v5/v83",
            "probabilities_preserved_without_renormalization": True,
            "runtime_signature_ignores_free_check": True,
        },
    }


def action_probability(response: Mapping[str, Any], action: str) -> float:
    """Read one action probability from either response mode."""
    return float((response.get("probabilities") or {}).get(str(action).upper(), 0.0) or 0.0)
