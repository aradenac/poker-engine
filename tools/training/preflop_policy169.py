#!/usr/bin/env python3
"""Runtime-compatible helpers for preflop ``policy169`` refits.

The browser consumes ``node.population_model.policy169_q_b64`` before falling
back to node marginals.  That field is an object containing an action-major
uint16 payload (`data`, `shape`, `actions`, `scale`, `dtype`, optional
`hand_order`).  These helpers intentionally mirror that exact representation,
including the browser's tiny positive decode value for quantized zeros.

Hidden-card decisions update only action marginals.  Genuinely revealed hands
provide conservative residual composition evidence; hidden hands are never
imputed.
"""
from __future__ import annotations

import base64
import copy
import math
import struct
from typing import Any, Mapping

EPS = 1e-12
DEFAULT_SCALE = 65535
SUPPORTED_DTYPES = {"uint16-le", "uint16-be"}


def _normalise(values: Mapping[str, float], keys: list[str]) -> dict[str, float]:
    clean = {k: max(0.0, float(values.get(k, 0.0) or 0.0)) for k in keys}
    total = sum(clean.values())
    if total <= EPS:
        return {k: 1.0 / len(keys) for k in keys} if keys else {}
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
    if total <= 0:
        raise ValueError("hand grid has no positive combo weight")
    return {h: raw[h] / total for h in hand_grid}


def policy_object(node: Mapping[str, Any]) -> dict[str, Any]:
    q = ((node.get("population_model") or {}).get("policy169_q_b64"))
    if not isinstance(q, dict):
        raise ValueError("node population_model has no policy169_q_b64 object")
    return q


def policy_meta(
    node: Mapping[str, Any], fallback_grid: list[str] | None = None
) -> tuple[list[str], list[str], int, str]:
    q = policy_object(node)
    actions = [str(a).upper() for a in (q.get("actions") or [])]
    hand_order = q.get("hand_order")
    if isinstance(hand_order, list):
        grid_source = hand_order
    elif hand_order in (None, "", "hand_grid.classes"):
        grid_source = fallback_grid or []
    else:
        raise ValueError(f"unsupported policy169 hand_order reference: {hand_order!r}")
    grid = [str(h) for h in grid_source]
    shape = list(q.get("shape") or [])
    scale = int(q.get("scale") or 0)
    dtype = str(q.get("dtype") or "")
    if not actions or not grid or scale <= 0:
        raise ValueError("policy169 must define actions, hand order and positive scale")
    if len(set(actions)) != len(actions) or len(set(grid)) != len(grid):
        raise ValueError("policy169 contains duplicate actions or hand classes")
    if len(shape) != 2 or int(shape[0]) != len(actions) or int(shape[1]) != len(grid):
        raise ValueError("policy169 shape does not match actions/hand order")
    if dtype not in SUPPORTED_DTYPES:
        raise ValueError(f"unsupported policy169 dtype: {dtype}")
    if not isinstance(q.get("data"), str):
        raise ValueError("policy169 data must be base64 text")
    return actions, grid, scale, dtype


def decode_policy169(
    node: Mapping[str, Any], fallback_grid: list[str] | None = None
) -> dict[str, dict[str, float]]:
    q = policy_object(node)
    actions, grid, scale, dtype = policy_meta(node, fallback_grid)
    try:
        raw = base64.b64decode(q["data"], validate=True)
    except Exception as exc:  # binascii.Error is an implementation detail here.
        raise ValueError("invalid policy169 base64 payload") from exc
    count = len(actions) * len(grid)
    if len(raw) != count * 2:
        raise ValueError(f"policy169 payload length mismatch: got {len(raw)}, expected {count * 2}")
    endian = "<" if dtype == "uint16-le" else ">"
    values = struct.unpack(endian + "H" * count, raw)
    out: dict[str, dict[str, float]] = {}
    for hi, hand in enumerate(grid):
        # Browser parity: a zero quantized cell gets a tiny positive value before
        # the row is normalized.  This prevents impossible-action zero traps.
        probs = {}
        for ai, action in enumerate(actions):
            qv = int(values[ai * len(grid) + hi])
            probs[action] = (0.25 / scale) if qv == 0 else (qv / scale)
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
    if any(v < 0 or v > 65535 for v in ints.values()):
        raise ValueError("policy169 quantized value is outside uint16")
    return ints


def encode_policy169(
    policy: Mapping[str, Mapping[str, float]],
    *,
    actions: list[str],
    hand_grid: list[str],
    scale: int = DEFAULT_SCALE,
    dtype: str = "uint16-le",
    template: Mapping[str, Any] | None = None,
    method: str | None = None,
) -> dict[str, Any]:
    if dtype not in SUPPORTED_DTYPES:
        raise ValueError(f"unsupported policy169 dtype: {dtype}")
    if scale <= 0 or scale > 65535:
        raise ValueError("policy169 scale must fit uint16 and be positive")
    if any(hand not in policy for hand in hand_grid):
        missing = [hand for hand in hand_grid if hand not in policy]
        raise ValueError(f"policy169 missing hand classes: {missing[:5]}")
    by_hand = {h: _quantize_distribution(policy[h], actions, scale) for h in hand_grid}
    values = [by_hand[h][action] for action in actions for h in hand_grid]
    endian = "<" if dtype == "uint16-le" else ">"
    raw = struct.pack(endian + "H" * len(values), *values)
    q = copy.deepcopy(dict(template or {}))
    q.update({
        "actions": list(actions),
        "shape": [len(actions), len(hand_grid)],
        "scale": int(scale),
        "dtype": dtype,
        "data": base64.b64encode(raw).decode("ascii"),
    })
    # Keep an explicit hand order when the source had one; otherwise runtime
    # deliberately falls back to the model root hand_grid.
    if template and isinstance(template.get("hand_order"), list):
        q["hand_order"] = list(hand_grid)
    elif template and template.get("hand_order") == "hand_grid.classes":
        q["hand_order"] = "hand_grid.classes"
    else:
        q.pop("hand_order", None)
    if method is not None:
        q["method"] = method
    return q


def policy_marginals(
    policy: Mapping[str, Mapping[str, float]], *, actions: list[str], weights: Mapping[str, float]
) -> dict[str, float]:
    return {
        action: sum(float(weights[h]) * float(policy[h].get(action, 0.0)) for h in weights)
        for action in actions
    }


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
    """Use shown hands without pretending that missing cards are known."""
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
            {
                a: (1.0 - weight) * float(baseline[hand].get(a, 0.0))
                + weight * float(fitted[hand].get(a, 0.0))
                for a in actions
            },
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
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not 0.0 <= update_weight <= 1.0:
        raise ValueError("policy update weight must be in [0, 1]")
    actions, grid, scale, dtype = policy_meta(node, fallback_grid)
    original_q = policy_object(node)
    known_total = sum(
        sum(int(v or 0) for v in (counts or {}).values())
        for counts in (delta.get("known_by_action") or {}).values()
    )
    if update_weight == 0.0:
        return copy.deepcopy(original_q), {
            "method": "zero-weight control; original runtime policy169 object preserved",
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
    previous_method = str(original_q.get("method") or "embedded_policy169")
    method = previous_method if "+policy169_refit_v1" in previous_method else previous_method + "+policy169_refit_v1"
    encoded = encode_policy169(
        blended,
        actions=actions,
        hand_grid=grid,
        scale=scale,
        dtype=dtype,
        template=original_q,
        method=method,
    )
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
