#!/usr/bin/env python3
"""Runtime-compatible helpers for preflop ``policy169`` refits.

The browser consumes ``policy169_q_b64`` before falling back to node
marginals. This module deliberately works on that exact representation.
Hidden-card decisions update the action marginal; genuinely revealed hands
provide only conservative residual composition evidence. No hidden hand is
imputed.
"""
from __future__ import annotations

import base64
import math
import struct
from typing import Any, Mapping

EPS = 1e-12
DEFAULT_SCALE = 65535
SUPPORTED_ENCODING = "uint16_le_base64"


def _normalise(values: Mapping[str, float], keys: list[str]) -> dict[str, float]:
    clean = {k: max(0.0, float(values.get(k, 0.0) or 0.0)) for k in keys}
    total = sum(clean.values())
    if total <= EPS:
        return {k: 1.0 / len(keys) for k in keys}
    return {k: clean[k] / total for k in keys}


def combo_weight(hand_class: str, meta: Mapping[str, Any] | None = None) -> float:
    if meta:
        value = meta.get("combo_weight")
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    hand = str(hand_class)
    if len(hand) == 2 and hand[0] == hand[1]:
        return 6.0
    if hand.endswith("s"):
        return 4.0
    if hand.endswith("o"):
        return 12.0
    return 1.0


def hand_weights(hand_grid: list[str], root_meta: Mapping[str, Any] | None = None) -> dict[str, float]:
    raw = {h: combo_weight(h, (root_meta or {}).get(h)) for h in hand_grid}
    total = sum(raw.values())
    return {h: raw[h] / total for h in hand_grid}


def policy_meta(node: Mapping[str, Any], fallback_grid: list[str] | None = None) -> tuple[list[str], list[str], int]:
    meta = node.get("policy169_q_meta") or {}
    encoding = str(meta.get("encoding") or SUPPORTED_ENCODING)
    if encoding != SUPPORTED_ENCODING:
        raise ValueError(f"unsupported policy169 encoding: {encoding}")
    actions = [str(a).upper() for a in (meta.get("actions") or [])]
    grid = [str(h) for h in (meta.get("hand_grid") or fallback_grid or [])]
    scale = int(meta.get("scale") or DEFAULT_SCALE)
    if not actions or not grid or scale <= 0:
        raise ValueError("policy169 metadata must define actions, hand_grid and positive scale")
    if len(set(actions)) != len(actions) or len(set(grid)) != len(grid):
        raise ValueError("policy169 metadata contains duplicate actions or hand classes")
    return actions, grid, scale


def decode_policy169(node: Mapping[str, Any], fallback_grid: list[str] | None = None) -> dict[str, dict[str, float]]:
    blob = node.get("policy169_q_b64")
    if not blob:
        raise ValueError("node has no policy169_q_b64")
    actions, grid, scale = policy_meta(node, fallback_grid)
    raw = base64.b64decode(str(blob), validate=True)
    count = len(actions) * len(grid)
    if len(raw) != count * 2:
        raise ValueError(f"policy169 payload length mismatch: got {len(raw)}, expected {count * 2}")
    values = struct.unpack("<" + "H" * count, raw)
    out: dict[str, dict[str, float]] = {}
    for hi, hand in enumerate(grid):
        probs = {action: values[ai * len(grid) + hi] / scale for ai, action in enumerate(actions)}
        out[hand] = _normalise(probs, actions)
    return out


def _quantize_distribution(probs: Mapping[str, float], actions: list[str], scale: int) -> dict[str, int]:
    p = _normalise(probs, actions)
    raw = {a: p[a] * scale for a in actions}
    ints = {a: int(math.floor(raw[a])) for a in actions}
    remaining = scale - sum(ints.values())
    order = sorted(actions, key=lambda a: (-(raw[a] - ints[a]), actions.index(a)))
    for action in order[:remaining]:
        ints[action] += 1
    if sum(ints.values()) != scale:
        raise AssertionError("quantized policy does not sum to scale")
    return ints


def encode_policy169(
    policy: Mapping[str, Mapping[str, float]], *, actions: list[str], hand_grid: list[str], scale: int = DEFAULT_SCALE
) -> str:
    by_hand = {h: _quantize_distribution(policy[h], actions, scale) for h in hand_grid}
    values = [by_hand[h][action] for action in actions for h in hand_grid]
    raw = struct.pack("<" + "H" * len(values), *values)
    return base64.b64encode(raw).decode("ascii")


def policy_marginals(
    policy: Mapping[str, Mapping[str, float]], *, actions: list[str], weights: Mapping[str, float]
) -> dict[str, float]:
    return {action: sum(float(weights[h]) * float(policy[h].get(action, 0.0)) for h in weights) for action in actions}


def calibrate_to_marginals(
    policy: Mapping[str, Mapping[str, float]],
    *,
    actions: list[str],
    weights: Mapping[str, float],
    target: Mapping[str, float],
    max_iterations: int = 250,
    tolerance: float = 1e-10,
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    """Apply action intercepts until combo-weighted marginals match ``target``."""
    target_n = _normalise(target, actions)
    base = {h: _normalise(policy[h], actions) for h in weights}
    factors = {a: 1.0 for a in actions}
    fitted = base
    max_error = math.inf
    iteration = 0
    for iteration in range(1, max_iterations + 1):
        fitted = {}
        for hand in weights:
            fitted[hand] = _normalise(
                {a: max(EPS, base[hand].get(a, 0.0)) * factors[a] for a in actions}, actions
            )
        current = policy_marginals(fitted, actions=actions, weights=weights)
        max_error = max(abs(current[a] - target_n[a]) for a in actions)
        if max_error <= tolerance:
            break
        for action in actions:
            factors[action] *= target_n[action] / max(EPS, current[action])
        logs = [math.log(max(EPS, factors[a])) for a in actions]
        centre = math.exp(sum(logs) / len(logs))
        for action in actions:
            factors[action] /= centre
    return fitted, {
        "iterations": iteration,
        "max_absolute_marginal_error": max_error,
        "target": target_n,
        "fitted": policy_marginals(fitted, actions=actions, weights=weights),
    }


def apply_revealed_composition_residual(
    policy: Mapping[str, Mapping[str, float]],
    *,
    actions: list[str],
    weights: Mapping[str, float],
    delta_actions: Mapping[str, Any],
    known_by_action: Mapping[str, Mapping[str, Any]],
    prior_strength: float,
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    """Use shown hands without pretending that missing cards are known.

    The observed P(hand|action,revealed) is shrunk toward the policy-implied
    composition. Effective evidence is ``known_n * revelation_rate`` so sparse
    revelation has less leverage. This does not make within-action MNAR
    revelation identifiable; callers must preserve that limitation in reports.
    """
    if prior_strength <= 0:
        raise ValueError("prior_strength must be positive")
    factors: dict[str, dict[str, float]] = {a: {h: 1.0 for h in weights} for a in actions}
    diagnostics: dict[str, Any] = {}
    for action in actions:
        counts = known_by_action.get(action) or {}
        known_n = sum(max(0, int(v or 0)) for v in counts.values())
        action_n = max(0, int(delta_actions.get(action) or 0))
        reveal_rate = known_n / action_n if action_n else 0.0
        expected_mass = sum(weights[h] * float(policy[h].get(action, 0.0)) for h in weights)
        diagnostics[action] = {
            "action_rows": action_n,
            "revealed_rows": known_n,
            "revelation_rate": reveal_rate,
            "effective_revealed_rows": known_n * reveal_rate,
            "applied": False,
        }
        if known_n <= 0 or action_n <= 0 or expected_mass <= EPS:
            continue
        expected = {h: weights[h] * float(policy[h].get(action, 0.0)) / expected_mass for h in weights}
        effective_n = known_n * reveal_rate
        denom = prior_strength + effective_n
        for hand in weights:
            empirical = max(0, int(counts.get(hand) or 0)) / known_n
            posterior = (prior_strength * expected[hand] + effective_n * empirical) / denom
            factors[action][hand] = posterior / max(EPS, expected[hand])
        diagnostics[action]["applied"] = effective_n > 0

    adjusted: dict[str, dict[str, float]] = {}
    for hand in weights:
        adjusted[hand] = _normalise(
            {a: float(policy[hand].get(a, 0.0)) * factors[a][hand] for a in actions}, actions
        )
    return adjusted, diagnostics


def blend_policy(
    baseline: Mapping[str, Mapping[str, float]],
    fitted: Mapping[str, Mapping[str, float]],
    *,
    actions: list[str],
    weight: float,
) -> dict[str, dict[str, float]]:
    if not 0.0 <= weight <= 1.0:
        raise ValueError("policy update weight must be in [0, 1]")
    return {
        hand: _normalise(
            {a: (1.0 - weight) * float(baseline[hand].get(a, 0.0)) + weight * float(fitted[hand].get(a, 0.0)) for a in actions},
            actions,
        )
        for hand in baseline
    }


def refit_node_policy169(
    node: Mapping[str, Any],
    delta: Mapping[str, Any],
    *,
    root_hand_meta: Mapping[str, Any] | None,
    fallback_grid: list[str] | None,
    prior_strength: float,
    update_weight: float = 1.0,
) -> tuple[str, dict[str, Any]]:
    if not 0.0 <= update_weight <= 1.0:
        raise ValueError("policy update weight must be in [0, 1]")
    actions, grid, scale = policy_meta(node, fallback_grid)
    known_total = sum(
        sum(int(v or 0) for v in (counts or {}).values())
        for counts in (delta.get("known_by_action") or {}).values()
    )
    if update_weight == 0.0:
        return str(node["policy169_q_b64"]), {
            "method": "zero-weight control; original policy169 bytes preserved",
            "prior_strength": prior_strength,
            "update_weight": 0.0,
            "train_action_rows": int(delta.get("n_delta") or 0),
            "train_revealed_rows": known_total,
            "hidden_hands_imputed": 0,
            "revelation": {},
        }
    baseline = decode_policy169(node, fallback_grid)
    weights = hand_weights(grid, root_hand_meta)
    model = node.get("population_model") or {}
    target = {a: float((model.get("frequencies") or {}).get(a, 0.0) or 0.0) for a in actions}
    marginal_fit, marginal_diag = calibrate_to_marginals(
        baseline, actions=actions, weights=weights, target=target
    )
    revealed_fit, reveal_diag = apply_revealed_composition_residual(
        marginal_fit,
        actions=actions,
        weights=weights,
        delta_actions=delta.get("actions") or {},
        known_by_action=delta.get("known_by_action") or {},
        prior_strength=prior_strength,
    )
    fitted, post_diag = calibrate_to_marginals(
        revealed_fit, actions=actions, weights=weights, target=target
    )
    blended = blend_policy(baseline, fitted, actions=actions, weight=update_weight)
    encoded = encode_policy169(blended, actions=actions, hand_grid=grid, scale=scale)
    return encoded, {
        "method": "all-decision marginal IPF + revelation-rate-shrunk P(hand|action) residual",
        "prior_strength": prior_strength,
        "update_weight": update_weight,
        "train_action_rows": int(delta.get("n_delta") or 0),
        "train_revealed_rows": known_total,
        "hidden_hands_imputed": 0,
        "revelation": reveal_diag,
        "marginal_fit_before_revealed_residual": marginal_diag,
        "marginal_fit_after_revealed_residual": post_diag,
        "limitations": [
            "Within-action card revelation is not assumed missing-at-random and is not identifiable from hidden folds/calls.",
            "Revealed composition is shrunk by its action-level revelation rate and the v5-derived prior strength.",
        ],
    }


def policy_probability(
    node: Mapping[str, Any], hand_class: str, action: str, fallback_grid: list[str] | None = None
) -> float:
    """Return the hand-conditioned probability family preferred by runtime."""
    action = str(action).upper()
    try:
        policy = decode_policy169(node, fallback_grid)
        if hand_class in policy and action in policy[hand_class]:
            return max(EPS, min(1.0, float(policy[hand_class][action])))
    except (ValueError, TypeError):
        pass
    marginal = float(((node.get("population_model") or {}).get("frequencies") or {}).get(action, 0.0) or 0.0)
    return max(EPS, min(1.0, marginal))
