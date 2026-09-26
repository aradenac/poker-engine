#!/usr/bin/env python3
"""Generalized public-only adverse preflop response model library (#421).

The library consumes the public-only rows produced by
``tools/training/build_generalized_response_dataset.py`` and exposes two
*comparable* architectures that share one API and one distribution contract:

``regularized_multinomial_spline`` (architecture **A**)
    A regularized additive multinomial log-linear model.  Every public axis is
    expanded either as a categorical block or as a *linear spline* block over a
    monotone ``log1p`` axis, and a bounded whitelist of interaction blocks is
    added.  Each block/node coefficient is a multinomial *lift* estimated with
    closed-form Dirichlet/m-estimate smoothing toward its parent (the global
    action distribution, or the family node for interaction cells); interactions
    are pruned by minimum support and capped at a fixed cell budget, and a single
    global lift scale is selected on a deterministic, hand-disjoint holdout.

``hierarchical_empirical_bayes_dirichlet`` (architecture **B**)
    A partial-pooling empirical-Bayes model.  The same node grid stores raw
    multinomial counts; each node's prediction is a Dirichlet-multinomial
    posterior mean whose prior strength is *measured from the data* (method of
    moments on the between-cell dispersion), pooled along the same hierarchy
    (global -> family -> cell).  Prediction sums each block's deviation from its
    parent (global prior, or the matched family node for interaction cells) with
    a holdout-selected deviation scale, then floors the result into the simplex.

Both architectures share the price/sizing channel:

* the current price the actor faces (``to_call_bb``, ``pot_before_bb``,
  ``effective_stack_bb``) is part of the discrete-choice core;
* the queried raise target (``target_total_bb``) is evaluated through a
  conditional sizing density estimated from observed RAISE/JAM sizings and
  applied as a gain on the RAISE/JAM branches.

Because both channels are *linear splines with partition-of-unity weights*, a
variation of ``target_total_bb`` (or of the current price) is recomputed
directly, continuously and piecewise-linearly from the queried value: the model
never rounds to, or substitutes, a neighbouring cell.  The observations carry no
counterfactual sizing label, so the sizing channel is an explicit
conditional price-response surface, not a causal effect.

Contract surface
----------------

* :func:`fit` -> JSON-serializable ``candidate`` document (persisted by
  :func:`persist_candidate` with its canonical payload hash);
* :func:`predict` / :meth:`ResponseModel.predict` -> ``{P(FOLD), P(CALL),
  P(RAISE), P(JAM)}`` plus a normalized, legal distribution;
* :func:`evaluate` -> direct evaluation (log loss, Brier, accuracy) which is
  itself a function of the queried price/sizing;
* :func:`price_response` -> the direct price/sizing response curve;
* :func:`raise_sizing_query` / :func:`generate_raise_sizings` /
  :func:`score_raise_sizing` -> the conditional ``P(sizing | RAISE, JAM,
  public context)`` model restricted to the engine's legal raise window, with
  per-request support/uncertainty, a deterministic legal generation grid and a
  fail-closed policy that never substitutes a nearest price or a nearest
  context (see :func:`raise_sizing_report`);
* :func:`ood_gate_decision` -> the frozen OOD/uncertainty verdict of one public
  context, one of ``MODEL_SUPPORTED``, ``MODEL_SUPPORTED_HIGH_UNCERTAINTY`` or
  ``MODEL_OOD_ABSTAIN``, combining never-seen categories, sizing/stack
  extrapolation, density/local support, robust domain distance and predictive
  uncertainty (see :func:`build_ood_calibration_report` for the TRAIN-only
  cross-validated thresholds and ``OOD_CALIBRATION_REPORT.json``);
* :func:`compare_candidates` -> architecture-vs-architecture comparison on the
  same rows;
* ``contracts/training/generalized-response-model.schema.json`` -> the contract
  for every produced/persisted document;
* ``contracts/training/generalized-response-ood-gate.schema.json`` -> the
  contract of the OOD gate decision, its frozen calibration and the calibration
  report.

Only the Python standard library is used (arithmetic, ``bisect``, ``hashlib``,
``json``/``math``; no numpy/sklearn/scipy/pandas).
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = "poker-generalized-response-model/v1"
PREDICTION_SCHEMA = "poker-generalized-response-action-probabilities/v1"
EVALUATION_SCHEMA = "poker-generalized-response-evaluation/v1"
COMPARISON_SCHEMA = "poker-generalized-response-comparison/v1"
PRICE_RESPONSE_SCHEMA = "poker-generalized-response-price-response/v1"
CONTRACT_PATH = ROOT / "contracts/training/generalized-response-model.schema.json"
DEFAULT_DATASET = ROOT / "analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "analysis/issue421_generalized_response/model"

ACTIONS = ("FOLD", "CALL", "RAISE", "JAM")
ACTION_INDEX = {action: index for index, action in enumerate(ACTIONS)}
AGGRESSIVE_ACTIONS = ("RAISE", "JAM")

ARCH_REGULARIZED = "regularized_multinomial_spline"
ARCH_HIERARCHICAL = "hierarchical_empirical_bayes_dirichlet"
ARCHITECTURES = (ARCH_REGULARIZED, ARCH_HIERARCHICAL)

TRAIN_SPLITS = ("TRAIN", "VALIDATION")
FORBIDDEN_SPLITS = ("TEST",)

EPS = 1e-12
PRIOR_FLOOR = 1e-6
PROBABILITY_FLOOR = 1e-12
MAX_SIZING_RATIO = 1.0e4
MISSING = "<MISSING>"
NONE = "NONE"

#: Monotone ``log1p`` spline axes used by both architectures.  Knots are the
#: observed-domain positions; the candidate stores them with the applied
#: transform so a persisted candidate predicts without re-deriving them.
SPLINE_AXES: dict[str, tuple[float, ...]] = {
    "to_call_bb": (0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 40.0, 100.0),
    "pot_before_bb": (1.0, 2.0, 3.5, 6.0, 10.0, 20.0, 40.0, 80.0, 160.0),
    "effective_stack_bb": (1.0, 5.0, 10.0, 20.0, 35.0, 60.0, 100.0, 160.0, 300.0),
}
SIZING_AXIS: tuple[float, ...] = (0.1, 0.25, 0.5, 0.8, 1.2, 2.0, 3.5, 7.0, 15.0)

AXIS_TRANSFORM = "log1p"

#: Categorical primary blocks.
CATEGORICAL_BLOCKS: tuple[str, ...] = (
    "family",
    "actor_position",
    "aggressor_position",
    "caller_count",
    "limper_count",
    "raise_level",
    "live_position_count",
)

#: Spline primary blocks: block name -> context field.
SPLINE_BLOCKS: tuple[tuple[str, str], ...] = (
    ("to_call_bb", "to_call_bb"),
    ("pot_before_bb", "pot_before_bb"),
    ("effective_stack_bb", "effective_stack_bb"),
)

#: Bounded interaction whitelist: (block name, left axis, right axis).
INTERACTION_BLOCKS: tuple[tuple[str, str, str], ...] = (
    ("family_x_actor_position", "family", "actor_position"),
    ("family_x_aggressor_position", "family", "aggressor_position"),
    ("family_x_to_call_bb", "family", "to_call_bucket"),
    ("family_x_effective_stack_bb", "family", "effective_stack_bucket"),
)
INTERACTION_BLOCK_NAMES = tuple(name for name, _, _ in INTERACTION_BLOCKS)

#: Coarse bucket edges used by interaction blocks.
COARSE_BUCKETS: dict[str, tuple[float, ...]] = {
    "to_call_bucket": (0.25, 1.0, 4.0, 16.0),
    "effective_stack_bucket": (5.0, 20.0, 60.0, 160.0),
}

CATEGORICAL_CAPS = {
    "caller_count": 3,
    "limper_count": 3,
    "raise_level": 3,
    "live_position_count": 5,
}

DEFAULT_CONFIG: dict[str, Any] = {
    "smoothing_mass": 8.0,
    "interaction_smoothing_mass": 8.0,
    "interaction_min_support": 20,
    "interaction_max_cells": 48,
    "interaction_block_weight": 0.5,
    "lift_scale_grid": [1.0, 2.0, 3.0, 4.0, 6.0, 8.0],
    "deviation_scale_grid": [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.45],
    "deviation_clip": 0.5,
    "hierarchical_strength_bounds": [1.0, 400.0],
    "hierarchical_min_cells": 2,
    "holdout_modulus": 5,
    "tuning_max_rows": 8000,
    "default_target_to_pot_ratio": 1.2,
    "sizing_gain_bounds": [0.125, 8.0],
    "sizing_smoothing_mass": 8.0,
    "spline_knots": {name: list(knots) for name, knots in SPLINE_AXES.items()},
    "sizing_axis_knots": list(SIZING_AXIS),
}

CONFIG_KEYS = frozenset(DEFAULT_CONFIG)


class GeneralizedResponseModelError(RuntimeError):
    """Fail-closed error for the generalized response model surface."""


# ---------------------------------------------------------------------------
# canonicalization helpers
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """Byte-identical to the repository-wide canonical JSON encoding."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_hash(value: Any) -> str:
    """Byte-identical to the repository-wide ``stable_hash``."""
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_candidate_sha256(candidate: Mapping[str, Any]) -> str:
    """Canonical hash of a candidate document, excluding the hash field itself."""
    if not isinstance(candidate, Mapping):
        raise TypeError("candidate must be a mapping")
    payload = {key: value for key, value in candidate.items() if key != "canonical_payload_sha256"}
    return stable_hash(payload)


def _round(value: Any, digits: int = 6) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    rounded = round(number, digits)
    return 0.0 if rounded == 0 else rounded


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


def make_config(**overrides: Any) -> dict[str, Any]:
    """Return a validated config: the defaults merged with ``overrides``.

    Unknown keys fail closed so a typo can never silently change a candidate.
    """
    unknown = sorted(set(overrides) - CONFIG_KEYS)
    if unknown:
        raise GeneralizedResponseModelError(f"unknown config key(s): {', '.join(unknown)}")
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    config.update(json.loads(json.dumps(overrides)))
    _validate_config(config)
    return config


def _validate_config(config: Mapping[str, Any]) -> None:
    missing = sorted(CONFIG_KEYS - set(config))
    if missing:
        raise GeneralizedResponseModelError(f"missing config key(s): {', '.join(missing)}")
    unknown = sorted(set(config) - CONFIG_KEYS)
    if unknown:
        raise GeneralizedResponseModelError(f"unknown config key(s): {', '.join(unknown)}")
    for key in ("smoothing_mass", "interaction_smoothing_mass", "sizing_smoothing_mass"):
        if float(config[key]) <= 0:
            raise GeneralizedResponseModelError(f"{key} must be positive")
    for key in ("interaction_min_support", "interaction_max_cells", "holdout_modulus", "tuning_max_rows"):
        if int(config[key]) < 1:
            raise GeneralizedResponseModelError(f"{key} must be >= 1")
    if not 0.0 < float(config["interaction_block_weight"]) <= 1.0:
        raise GeneralizedResponseModelError("interaction_block_weight must be in (0, 1]")
    if float(config["deviation_clip"]) <= 0.0:
        raise GeneralizedResponseModelError("deviation_clip must be positive")
    bounds = [float(x) for x in config["sizing_gain_bounds"]]
    if len(bounds) != 2 or not 0.0 < bounds[0] < bounds[1]:
        raise GeneralizedResponseModelError("sizing_gain_bounds must be an increasing positive pair")
    strength = [float(x) for x in config["hierarchical_strength_bounds"]]
    if len(strength) != 2 or not 0.0 < strength[0] < strength[1]:
        raise GeneralizedResponseModelError("hierarchical_strength_bounds must be an increasing positive pair")
    for grid_key in ("lift_scale_grid", "deviation_scale_grid"):
        grid = [float(x) for x in config[grid_key]]
        if not grid or any(value <= 0 for value in grid):
            raise GeneralizedResponseModelError(f"{grid_key} must be a non-empty positive list")
    if float(config["default_target_to_pot_ratio"]) <= 0:
        raise GeneralizedResponseModelError("default_target_to_pot_ratio must be positive")
    for axis, knots in config["spline_knots"].items():
        values = [float(x) for x in knots]
        if len(values) < 2 or any(b <= a for a, b in zip(values, values[1:])):
            raise GeneralizedResponseModelError(f"spline_knots[{axis}] must be strictly increasing")
    sizing_knots = [float(x) for x in config["sizing_axis_knots"]]
    if len(sizing_knots) < 2 or any(b <= a for a, b in zip(sizing_knots, sizing_knots[1:])):
        raise GeneralizedResponseModelError("sizing_axis_knots must be strictly increasing")


# ---------------------------------------------------------------------------
# feature expansion
# ---------------------------------------------------------------------------


def _transform(value: float) -> float:
    return math.log1p(max(0.0, float(value)))


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise GeneralizedResponseModelError(f"non-numeric public feature {field}: {value!r}") from None
    if not math.isfinite(number):
        raise GeneralizedResponseModelError(f"non-finite public feature {field}: {value!r}")
    return number


def spline_weights(value: float, knots: Sequence[float]) -> dict[int, float]:
    """Partition-of-unity linear spline weights over a monotone ``log1p`` axis.

    Exactly two adjacent knots receive weight when the queried value falls
    between them, and the weights are continuous (piecewise-linear) in the value.
    Values beyond the extreme knots clamp to the extreme knot: this is an
    extrapolation clamp, never a substitution of a neighbouring cell.
    """
    if not knots:
        raise GeneralizedResponseModelError("spline axis has no knots")
    axis = [_transform(knot) for knot in knots]
    u = _transform(value)
    if u <= axis[0]:
        return {0: 1.0}
    if u >= axis[-1]:
        return {len(axis) - 1: 1.0}
    index = bisect.bisect_right(axis, u) - 1
    low, high = axis[index], axis[index + 1]
    if high <= low:
        return {index: 1.0}
    upper_weight = (u - low) / (high - low)
    return {index: 1.0 - upper_weight, index + 1: upper_weight}


def _public_level(value: Any) -> str:
    text = str(value).strip().upper() if value is not None else ""
    return text or MISSING


def _count_level(value: Any, cap: int) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return MISSING
    return str(max(0, min(number, cap)))


def _coarse_bucket(label: str, value: Any) -> str:
    edges = COARSE_BUCKETS[label]
    try:
        number = float(value)
    except (TypeError, ValueError):
        return MISSING
    axis = [_transform(edge) for edge in edges]
    index = bisect.bisect_right(axis, _transform(number)) - 1
    return f"B{index}"


def _live_position_count(context: Mapping[str, Any]) -> str:
    positions = context.get("live_positions")
    if positions is None:
        table_size = context.get("table_size")
        if table_size is None:
            return MISSING
        return _count_level(table_size, CATEGORICAL_CAPS["live_position_count"])
    return _count_level(len(list(positions)), CATEGORICAL_CAPS["live_position_count"])


def categorical_node(block: str, context: Mapping[str, Any]) -> str:
    """Return the categorical node label of ``block`` for ``context``."""
    if block == "family":
        return _public_level(context.get("family"))
    if block == "actor_position":
        return _public_level(context.get("actor_position"))
    if block == "aggressor_position":
        return _public_level(context.get("aggressor_position") or NONE)
    if block == "live_position_count":
        return _live_position_count(context)
    if block in CATEGORICAL_CAPS:
        return _count_level(context.get(block), CATEGORICAL_CAPS[block])
    raise GeneralizedResponseModelError(f"unknown categorical block: {block}")


def interaction_node(block: str, context: Mapping[str, Any]) -> str:
    """Return the interaction node label of ``block`` for ``context``."""
    spec = {name: (left, right) for name, left, right in INTERACTION_BLOCKS}
    if block not in spec:
        raise GeneralizedResponseModelError(f"unknown interaction block: {block}")
    left_axis, right_axis = spec[block]

    def axis_value(name: str) -> str:
        if name in COARSE_BUCKETS:
            source = "to_call_bb" if name == "to_call_bucket" else "effective_stack_bb"
            return _coarse_bucket(name, context.get(source))
        return categorical_node(name, context)

    return f"{axis_value(left_axis)}|{axis_value(right_axis)}"


def context_block_nodes(context: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    """Expand one public context into per-block node queries.

    Categorical/interaction blocks return ``{node_label: 1.0}``; spline blocks
    return ``{knot_index: weight}`` with partition-of-unity spline weights.
    """
    nodes: dict[str, Any] = {}
    for block in CATEGORICAL_BLOCKS:
        nodes[block] = {categorical_node(block, context): 1.0}
    for block, field in SPLINE_BLOCKS:
        nodes[block] = spline_weights(
            _finite(context.get(field, 0.0), field), [float(x) for x in config["spline_knots"][block]]
        )
    for block in INTERACTION_BLOCK_NAMES:
        nodes[block] = {interaction_node(block, context): 1.0}
    return nodes


# ---------------------------------------------------------------------------
# price / sizing channel
# ---------------------------------------------------------------------------


def sizing_context(context: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the queried raise target and its pot-relative sizing ratio.

    ``target_total_bb`` (the artifact field) is accepted first, then
    ``raise_target_total_bb``; when neither is present the documented default
    pot-relative raise size is used and the response is flagged as such.
    """
    to_call = _finite(context.get("to_call_bb", 0.0), "to_call_bb")
    pot_before = _finite(context.get("pot_before_bb", 0.0), "pot_before_bb")
    denominator = max(pot_before + to_call, EPS)
    target = context.get("target_total_bb")
    source = "context"
    if target is None:
        target = context.get("raise_target_total_bb")
    if target is None:
        target = float(config["default_target_to_pot_ratio"]) * denominator
        source = "default_pot_relative"
    target = _finite(target, "target_total_bb")
    ratio = max(0.0, target) / denominator
    ratio = min(ratio, MAX_SIZING_RATIO)
    stack = _finite(context.get("effective_stack_bb", 0.0), "effective_stack_bb")
    jam_ratio = min(max(stack, 0.0) / denominator, MAX_SIZING_RATIO)
    return {
        "target_total_bb": _round(target),
        "to_call_bb": _round(to_call),
        "pot_before_bb": _round(pot_before),
        "sizing_ratio": _round(ratio),
        "jam_ratio": _round(jam_ratio),
        "source": source,
    }


def _sizing_density(channel: Mapping[str, Any], action: str, family: str, ratio: float) -> float:
    """Evaluate the conditional sizing density of ``action`` at ``ratio``."""
    table = (channel["families"].get(family) or {}).get(action)
    if table is None:
        table = channel["global"][action]
    weights = spline_weights(ratio, [float(x) for x in channel["axis_knots"]])
    density = 0.0
    for index, weight in weights.items():
        density += float(weight) * float(table["density"][index])
    return max(density, PROBABILITY_FLOOR)


def sizing_gain(candidate: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    """RAISE/JAM gains of the queried target relative to each action reference.

    The reference points are the documented default raise size (RAISE) and the
    actor's all-in pot ratio (JAM), so querying a reference reproduces the
    marginal distribution.  The gain is a continuous function of the queried
    ``target_total_bb``.
    """
    config = candidate["config"]
    channel = candidate["params"]["sizing_channel"]
    query = sizing_context(context, config)
    family = _public_level(context.get("family"))
    low, high = (float(x) for x in config["sizing_gain_bounds"])
    gains: dict[str, float] = {}
    for action in AGGRESSIVE_ACTIONS:
        reference = (
            float(config["default_target_to_pot_ratio"])
            if action == "RAISE"
            else max(float(query["jam_ratio"] or 0.0), PROBABILITY_FLOOR)
        )
        numerator = _sizing_density(channel, action, family, float(query["sizing_ratio"]))
        denominator = _sizing_density(channel, action, family, reference)
        gains[action] = min(max(numerator / denominator, low), high)
    return {"query": query, "gains": gains, "gain_bounds": [low, high]}


# ---------------------------------------------------------------------------
# legal action space
# ---------------------------------------------------------------------------


def _mapped_response_action(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text == "LIMP":
        text = "CALL"
    return text if text in ACTION_INDEX else None


def legal_response_actions(context: Mapping[str, Any]) -> list[str]:
    """Return the legal FOLD/CALL/RAISE/JAM space of one public context.

    An explicit ``legal_actions`` list is authoritative when supplied (this is
    the ``poker-preflop-context/v1`` surface).  Otherwise the space is derived
    from public pre-action features:

    * ``FOLD`` is always legal;
    * ``CALL`` requires a price to call (``to_call_bb > 0``);
    * ``RAISE``/``JAM`` require at least one other live player and an open
      betting round (``raise_reopened`` / ``facing_all_in`` are honoured when the
      caller supplies them).

    Masking happens *before* normalization: illegal actions can never receive
    probability mass.
    """
    explicit = context.get("legal_actions")
    if explicit:
        legal = [action for action in ACTIONS if action in {
            mapped for mapped in (_mapped_response_action(raw) for raw in explicit) if mapped
        }]
        if legal:
            return legal

    try:
        to_call = max(0.0, float(context.get("to_call_bb") or 0.0))
    except (TypeError, ValueError):
        to_call = 0.0
    positions = context.get("live_positions")
    actor = _public_level(context.get("actor_position"))
    if positions is None:
        others = max(int(context.get("table_size") or 2) - 1, 0)
    else:
        live = [_public_level(position) for position in positions]
        others = len(live) - (1 if actor in live else 0)
    if "raise_reopened" in context:
        can_raise = bool(context.get("raise_reopened"))
    elif "facing_all_in" in context:
        can_raise = not bool(context.get("facing_all_in"))
    else:
        can_raise = True
    can_raise = can_raise and others >= 1

    legal = ["FOLD"]
    if to_call > EPS:
        legal.append("CALL")
    if can_raise:
        legal.extend(["RAISE", "JAM"])
    return legal


def _normalize_legal(weights: Mapping[str, float], legal: Sequence[str]) -> tuple[dict[str, float], str]:
    """Mask, normalize and exactly close the legal distribution.

    Illegal actions are pinned to ``0.0``; the final normalization guarantees
    ``sum(probabilities.values()) == 1.0`` in IEEE-754 arithmetic.
    """
    legal = list(legal)
    probability = {action: 0.0 for action in ACTIONS}
    total = 0.0
    raw: dict[str, float] = {}
    for action in legal:
        value = float(weights.get(action, 0.0))
        if not math.isfinite(value) or value < 0.0:
            value = 0.0
        raw[action] = value
        total += value
    if total <= EPS:
        share = 1.0 / len(legal)
        for action in legal:
            probability[action] = share
        probability[legal[-1]] = max(0.0, 1.0 - share * (len(legal) - 1))
        return probability, "uniform_legal_fallback"
    for action in legal:
        probability[action] = raw[action] / total
    others = sum(probability[action] for action in legal[:-1])
    probability[legal[-1]] = max(0.0, 1.0 - others)
    return probability, "legal_normalized"


def _softmax_legal(logits: Mapping[str, float], legal: Sequence[str]) -> tuple[dict[str, float], str]:
    """Softmax restricted to the legal actions (masking precedes normalization)."""
    if not legal:
        raise GeneralizedResponseModelError("context has no legal action")
    peak = max(float(logits[action]) for action in legal)
    exponentials = {action: math.exp(float(logits[action]) - peak) for action in legal}
    return _normalize_legal(exponentials, legal)


# ---------------------------------------------------------------------------
# dataset rows
# ---------------------------------------------------------------------------


def _row_action(row: Mapping[str, Any]) -> str:
    action = str(row.get("action") or "").strip().upper()
    if action not in ACTION_INDEX:
        raise GeneralizedResponseModelError(f"row action outside the response space: {row.get('action')!r}")
    return action


def _row_split(row: Mapping[str, Any]) -> str:
    return str(row.get("split") or "").strip().upper()


def _assert_consumable(row: Mapping[str, Any]) -> str:
    split = _row_split(row)
    if split in FORBIDDEN_SPLITS:
        raise GeneralizedResponseModelError(
            "TEST is forbidden: the response model only consumes TRAIN/VALIDATION"
        )
    if split and split not in TRAIN_SPLITS:
        raise GeneralizedResponseModelError(f"unsupported split {split!r}; allowed: {', '.join(TRAIN_SPLITS)}")
    return split


def _row_identity(row: Mapping[str, Any], index: int) -> str:
    hand_id = str(row.get("hand_id") or "").strip()
    return hand_id or f"#{index}"


def _holdout_bucket(identity: str, seed: int, modulus: int) -> int:
    return int(stable_hash(f"grm/{int(seed)}/{identity}")[:8], 16) % int(modulus)


def order_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Order rows deterministically so a candidate never depends on input order."""
    prepared: list[tuple[str, str, dict[str, Any]]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TypeError("train rows must be mappings")
        materialized = dict(row)
        _assert_consumable(materialized)
        _row_action(materialized)
        prepared.append((_row_identity(materialized, index), canonical_json(materialized), materialized))
    prepared.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in prepared]


def read_dataset_rows(
    path: str | Path = DEFAULT_DATASET,
    *,
    splits: Sequence[str] = TRAIN_SPLITS,
) -> list[dict[str, Any]]:
    """Read the persisted JSONL dataset, failing closed on TEST."""
    wanted = {str(split).upper() for split in splits}
    forbidden = wanted & set(FORBIDDEN_SPLITS)
    if forbidden:
        raise GeneralizedResponseModelError(f"TEST is forbidden: {sorted(forbidden)}")
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if _row_split(row) in wanted:
                rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# fitting: shared counting pass
# ---------------------------------------------------------------------------


class _Counts:
    """Sufficient statistics of the shared node grid."""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.config = config
        self.global_counts = [0.0, 0.0, 0.0, 0.0]
        self.family_counts: dict[str, list[float]] = {}
        self.block_counts: dict[str, dict[str, list[float]]] = {}
        self.block_spline_counts: dict[str, list[list[float]]] = {block: [] for block, _ in SPLINE_BLOCKS}
        knot_count = len(config["sizing_axis_knots"])
        self.sizing_counts: dict[str, dict[str, list[float]]] = {
            action: {"GLOBAL": [0.0] * knot_count} for action in AGGRESSIVE_ACTIONS
        }
        self.rows = 0

    def _spline_slot(self, block: str, index: int) -> list[float]:
        table = self.block_spline_counts[block]
        while len(table) <= index:
            table.append([0.0, 0.0, 0.0, 0.0])
        return table[index]

    def add(self, row: Mapping[str, Any], nodes: Mapping[str, Any], action: str) -> None:
        index = ACTION_INDEX[action]
        self.global_counts[index] += 1.0
        self.rows += 1
        family = _public_level(row.get("family"))
        self.family_counts.setdefault(family, [0.0, 0.0, 0.0, 0.0])[index] += 1.0
        for block, query in nodes.items():
            if block in self.block_spline_counts:
                for knot_index, weight in query.items():
                    self._spline_slot(block, int(knot_index))[index] += float(weight)
            else:
                table = self.block_counts.setdefault(block, {})
                for node, weight in query.items():
                    table.setdefault(node, [0.0, 0.0, 0.0, 0.0])[index] += float(weight)
        if action in AGGRESSIVE_ACTIONS:
            sizing = sizing_context(row, self.config)
            weights = spline_weights(
                float(sizing["sizing_ratio"]), [float(x) for x in self.config["sizing_axis_knots"]]
            )
            global_table = self.sizing_counts[action]["GLOBAL"]
            family_table = self.sizing_counts[action].setdefault(
                family, [0.0] * len(self.config["sizing_axis_knots"])
            )
            for knot_index, weight in weights.items():
                global_table[knot_index] += float(weight)
                family_table[knot_index] += float(weight)


def _prior_from_counts(counts: Sequence[float]) -> list[float]:
    total = float(sum(counts))
    if total <= 0:
        raise GeneralizedResponseModelError("no rows: cannot fit a response model")
    prior = [max(float(count) / total, PRIOR_FLOOR) for count in counts]
    normalizer = sum(prior)
    return [value / normalizer for value in prior]


def _posterior_rate(counts: Sequence[float], parent: Sequence[float], mass: float) -> list[float]:
    """Dirichlet/m-estimate posterior mean of a four-action cell."""
    total = float(sum(counts))
    mass = max(float(mass), EPS)
    rate = [(float(counts[i]) + mass * float(parent[i])) / (total + mass) for i in range(4)]
    normalizer = sum(rate)
    return [max(value / normalizer, PROBABILITY_FLOOR) for value in rate]


def _lift(rate: Sequence[float], parent: Sequence[float]) -> list[float]:
    return [
        math.log(max(float(rate[i]), PROBABILITY_FLOOR) / max(float(parent[i]), PRIOR_FLOOR))
        for i in range(4)
    ]


def _select_interaction_nodes(entries: Mapping[str, Sequence[float]], config: Mapping[str, Any]) -> list[str]:
    """Support-pruned, deterministically capped interaction cell list."""
    supported = [
        (node, float(sum(counts)))
        for node, counts in entries.items()
        if float(sum(counts)) >= float(config["interaction_min_support"])
    ]
    supported.sort(key=lambda item: (-item[1], item[0]))
    return [item[0] for item in supported[: int(config["interaction_max_cells"])]]


# ---------------------------------------------------------------------------
# fitting: architecture A - regularized multinomial with spline lifts
# ---------------------------------------------------------------------------


def _regularized_blocks(
    counts: _Counts,
    prior: Sequence[float],
    config: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    smoothing = float(config["smoothing_mass"])
    interaction_smoothing = float(config["interaction_smoothing_mass"])
    family_rates = {
        family: _posterior_rate(values, prior, smoothing)
        for family, values in counts.family_counts.items()
    }
    blocks: dict[str, dict[str, Any]] = {}
    for block, _ in SPLINE_BLOCKS:
        table = counts.block_spline_counts[block]
        knots = [float(x) for x in config["spline_knots"][block]]
        cells = [table[index] if index < len(table) else [0.0, 0.0, 0.0, 0.0] for index in range(len(knots))]
        blocks[block] = {
            "kind": "primary",
            "basis": "spline",
            "transform": AXIS_TRANSFORM,
            "knots": knots,
            "nodes": [str(knot) for knot in knots],
            "support": [int(round(sum(cell))) for cell in cells],
            "lift": [
                [_round(value) for value in _lift(_posterior_rate(cell, prior, smoothing), prior)]
                for cell in cells
            ],
        }
    for block in CATEGORICAL_BLOCKS:
        entries = counts.block_counts.get(block, {})
        nodes = sorted(entries)
        blocks[block] = {
            "kind": "primary",
            "basis": "categorical",
            "transform": None,
            "knots": None,
            "nodes": nodes,
            "support": [int(round(sum(entries[node]))) for node in nodes],
            "lift": [
                [_round(value) for value in _lift(_posterior_rate(entries[node], prior, smoothing), prior)]
                for node in nodes
            ],
        }
    for block in INTERACTION_BLOCK_NAMES:
        entries = counts.block_counts.get(block, {})
        selected = _select_interaction_nodes(entries, config)
        nodes: list[str] = []
        support: list[int] = []
        values: list[list[float]] = []
        for node in selected:
            cell = entries[node]
            parent = family_rates.get(str(node).split("|")[0], prior)
            nodes.append(node)
            support.append(int(round(sum(cell))))
            values.append(_lift(_posterior_rate(cell, parent, interaction_smoothing), parent))
        blocks[block] = {
            "kind": "interaction",
            "basis": "categorical",
            "transform": None,
            "knots": None,
            "nodes": nodes,
            "support": support,
            "lift": [[_round(value) for value in row] for row in values],
        }
    return blocks


def _match_node(block_spec: Mapping[str, Any], key: Any) -> int | None:
    """Resolve one queried node key to an index, or ``None`` when unseen."""
    if block_spec["basis"] == "spline":
        index = int(key)
        return index if 0 <= index < len(block_spec["nodes"]) else None
    try:
        return block_spec["nodes"].index(str(key))
    except ValueError:
        return None


def _regularized_logits(
    candidate: Mapping[str, Any],
    nodes: Mapping[str, Any],
    *,
    lift_scale: float,
) -> tuple[dict[str, float], int]:
    params = candidate["params"]
    config = candidate["config"]
    prior = params["prior"]
    support = 0
    contributions: list[list[float]] = []
    for block, block_spec in params["blocks"].items():
        query = nodes.get(block)
        if not query:
            continue
        block_weight = (
            float(config["interaction_block_weight"]) if block_spec["kind"] == "interaction" else 1.0
        )
        used = 0.0
        contribution = [0.0, 0.0, 0.0, 0.0]
        for key, spline_weight in query.items():
            index = _match_node(block_spec, key)
            if index is None:
                continue
            row = block_spec["lift"][index]
            support += int(block_spec["support"][index])
            used += float(spline_weight)
            for action_index in range(4):
                contribution[action_index] += float(spline_weight) * float(row[action_index])
        if used <= EPS:
            continue
        # Normalise inside the block (a pruned or unseen node must not silently
        # zero the block) and average the blocks that actually matched.
        contributions.append([block_weight * contribution[i] / used for i in range(4)])
    logits = {action: math.log(max(float(prior[action]), PRIOR_FLOOR)) for action in ACTIONS}
    if contributions:
        count = float(len(contributions))
        for action_index, action in enumerate(ACTIONS):
            logits[action] += float(lift_scale) * sum(row[action_index] for row in contributions) / count
    return logits, support


# ---------------------------------------------------------------------------
# fitting: architecture B - hierarchical empirical-Bayes Dirichlet
# ---------------------------------------------------------------------------


def _eb_strength(
    cells: Sequence[Sequence[float]],
    parent: Sequence[float],
    bounds: Sequence[float],
) -> float:
    """Method-of-moments Dirichlet-multinomial prior strength.

    The support-weighted between-cell dispersion of the action rates is compared
    with the dispersion expected from sampling alone; the excess identifies the
    prior mass ``m``.  ``m`` is clipped to ``bounds`` and falls back to maximal
    pooling when the dispersion carries no signal.
    """
    low, high = float(bounds[0]), float(bounds[1])
    usable = [list(cell) for cell in cells if sum(cell) > 0]
    if len(usable) < 2:
        return high
    total = sum(sum(cell) for cell in usable)
    if total <= 0:
        return high
    estimates: list[float] = []
    for action_index in range(4):
        pooled = sum(float(cell[action_index]) for cell in usable) / total
        pooled = min(max(pooled, PRIOR_FLOOR), 1.0 - PRIOR_FLOOR)
        dispersion = 0.0
        sampling = 0.0
        for cell in usable:
            size = float(sum(cell))
            rate = float(cell[action_index]) / size
            dispersion += size * (rate - pooled) ** 2
            sampling += size * pooled * (1.0 - pooled) / size
        dispersion /= total
        sampling /= total
        excess = dispersion - sampling
        if excess <= 1e-9:
            estimates.append(high)
            continue
        estimates.append(min(max(pooled * (1.0 - pooled) / excess - 1.0, low), high))
    # Weight the per-action estimates by the parent action mass: rare actions
    # carry a noisy dispersion and must not dominate the strength.
    weights = [max(float(parent[i]), PRIOR_FLOOR) for i in range(4)]
    strength = sum(estimate * weights[i] for i, estimate in enumerate(estimates)) / sum(weights)
    return min(max(strength, low), high)


def _hierarchical_blocks(
    counts: _Counts,
    prior: Sequence[float],
    config: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Store raw counts plus the measured per-block prior strengths."""
    bounds = [float(x) for x in config["hierarchical_strength_bounds"]]
    min_cells = int(config["hierarchical_min_cells"])
    blocks: dict[str, dict[str, Any]] = {}
    strengths: dict[str, dict[str, Any]] = {}
    for block, _ in SPLINE_BLOCKS:
        table = counts.block_spline_counts[block]
        knots = [float(x) for x in config["spline_knots"][block]]
        cells = [table[index] if index < len(table) else [0.0, 0.0, 0.0, 0.0] for index in range(len(knots))]
        strength = _eb_strength(cells, prior, bounds) if len([c for c in cells if sum(c) > 0]) >= min_cells else bounds[1]
        strengths[block] = {"prior_strength": _round(strength), "basis": "method_of_moments"}
        blocks[block] = {
            "kind": "primary",
            "basis": "spline",
            "transform": AXIS_TRANSFORM,
            "knots": knots,
            "nodes": [str(knot) for knot in knots],
            "support": [int(round(sum(cell))) for cell in cells],
            "counts": [[_round(value, 6) for value in cell] for cell in cells],
        }
    for block in CATEGORICAL_BLOCKS:
        entries = counts.block_counts.get(block, {})
        nodes = sorted(entries)
        cells = [entries[node] for node in nodes]
        strength = _eb_strength(cells, prior, bounds) if len([c for c in cells if sum(c) > 0]) >= min_cells else bounds[1]
        strengths[block] = {"prior_strength": _round(strength), "basis": "method_of_moments"}
        blocks[block] = {
            "kind": "primary",
            "basis": "categorical",
            "transform": None,
            "knots": None,
            "nodes": nodes,
            "support": [int(round(sum(entries[node]))) for node in nodes],
            "counts": [[_round(value, 6) for value in entries[node]] for node in nodes],
        }
    interaction_cells: list[Sequence[float]] = []
    selected_by_block: dict[str, list[str]] = {}
    for block in INTERACTION_BLOCK_NAMES:
        entries = counts.block_counts.get(block, {})
        selected = _select_interaction_nodes(entries, config)
        selected_by_block[block] = selected
        interaction_cells.extend(entries[node] for node in selected)
    interaction_strength = _eb_strength(interaction_cells, prior, bounds) \
        if len(interaction_cells) >= min_cells else bounds[1]
    # The family nodes carry their own counts in ``blocks["family"]``; the
    # interaction strength is the measured prior mass shared by every
    # interaction block (their cells pool onto the matching family node at
    # prediction time).
    for block in INTERACTION_BLOCK_NAMES:
        entries = counts.block_counts.get(block, {})
        nodes: list[str] = []
        support: list[int] = []
        cells: list[list[float]] = []
        for node in selected_by_block[block]:
            cell = entries[node]
            nodes.append(node)
            support.append(int(round(sum(cell))))
            cells.append([_round(value, 6) for value in cell])
        strengths[block] = {"prior_strength": _round(interaction_strength), "basis": "method_of_moments"}
        blocks[block] = {
            "kind": "interaction",
            "basis": "categorical",
            "transform": None,
            "knots": None,
            "nodes": nodes,
            "support": support,
            "counts": cells,
        }
    return blocks, strengths


def _strength(entry: Mapping[str, Any] | None, fallback: float) -> float:
    if not entry:
        return float(fallback)
    value = entry.get("prior_strength")
    return float(fallback) if value is None else float(value)


def _clamp_strength(value: float, config: Mapping[str, Any]) -> float:
    low, high = (float(x) for x in config["hierarchical_strength_bounds"])
    return min(max(float(value), low), high)


def _hierarchical_weights(
    candidate: Mapping[str, Any],
    nodes: Mapping[str, Any],
    *,
    deviation_scale: float,
) -> tuple[dict[str, float], int]:
    """Additive ensemble of empirical-Bayes deviations from the parent rate.

    Every node prediction is the Dirichlet-multinomial posterior mean recomputed
    from its stored counts with the *measured* prior strength, so partial pooling
    is data-driven rather than hand-set.  Each block then contributes its
    deviation from its parent (the global prior for primary blocks, the matched
    family node for interaction cells); the deviations are summed with the
    holdout-selected ``deviation_scale`` (each one clipped at ``deviation_clip``
    so a single low-support block cannot dominate) and floored into the simplex.
    """
    params = candidate["params"]
    config = candidate["config"]
    prior = [float(params["prior"][action]) for action in ACTIONS]
    blocks = params["blocks"]
    family_block = blocks.get("family")
    family_rates: dict[str, list[float]] = {}
    if family_block is not None:
        mass = _clamp_strength(_strength(params["block_strengths"].get("family"), 1.0), config)
        for index, node in enumerate(family_block["nodes"]):
            family_rates[str(node)] = _posterior_rate(family_block["counts"][index], prior, mass)
    weights = {action: float(prior[ACTION_INDEX[action]]) for action in ACTIONS}
    clip = float(config["deviation_clip"])
    support = 0
    for block, block_spec in blocks.items():
        query = nodes.get(block)
        if not query:
            continue
        block_weight = (
            float(config["interaction_block_weight"]) if block_spec["kind"] == "interaction" else 1.0
        )
        mass = _clamp_strength(_strength(params["block_strengths"].get(block), 1.0), config)
        for key, spline_weight in query.items():
            index = _match_node(block_spec, key)
            if index is None:
                continue
            counts = block_spec["counts"][index]
            if block_spec["kind"] == "interaction":
                parent = family_rates.get(str(key).split("|")[0], prior)
            else:
                parent = prior
            rate = _posterior_rate(counts, parent, mass)
            weight = float(spline_weight) * block_weight
            support += int(block_spec["support"][index])
            for action_index, action in enumerate(ACTIONS):
                deviation = min(max(rate[action_index] - parent[action_index], -clip), clip)
                weights[action] += float(deviation_scale) * weight * deviation
    for action in ACTIONS:
        weights[action] = max(weights[action], PROBABILITY_FLOOR)
    return weights, support


# ---------------------------------------------------------------------------
# sizing channel fitting (shared)
# ---------------------------------------------------------------------------


def _fit_sizing_channel(counts: _Counts, config: Mapping[str, Any]) -> dict[str, Any]:
    return _fit_sizing_channel_from_counts(counts.sizing_counts, config)


def _fit_sizing_channel_from_counts(
    sizing_counts: Mapping[str, Mapping[str, Sequence[float]]], config: Mapping[str, Any]
) -> dict[str, Any]:
    """Smooth raw RAISE/JAM ratio counts into the shared conditional channel."""
    mass = float(config["sizing_smoothing_mass"])
    knots = [float(x) for x in config["sizing_axis_knots"]]
    channel: dict[str, Any] = {
        "axis_knots": knots,
        "actions": list(AGGRESSIVE_ACTIONS),
        "global": {},
        "families": {},
    }
    for action in AGGRESSIVE_ACTIONS:
        global_counts = list(sizing_counts[action]["GLOBAL"])
        total = float(sum(global_counts))
        if total <= 0:
            density = [1.0 / len(knots)] * len(knots)
        else:
            density = [(float(value) + mass / len(knots)) / (total + mass) for value in global_counts]
        channel["global"][action] = {
            "total": int(round(total)),
            "density": [_round(value, 9) for value in density],
        }
        for family, values in sizing_counts[action].items():
            if family == "GLOBAL" or float(sum(values)) <= 0:
                continue
            smoothed = [
                (float(values[i]) + mass * density[i]) / (float(sum(values)) + mass)
                for i in range(len(knots))
            ]
            channel["families"].setdefault(family, {})[action] = {
                "total": int(round(sum(values))),
                "density": [_round(value, 9) for value in smoothed],
            }
    for family, tables in channel["families"].items():
        for action in AGGRESSIVE_ACTIONS:
            tables.setdefault(action, {"total": 0, "density": list(channel["global"][action]["density"])})
    return channel


def _sizing_channel_summary(channel: Mapping[str, Any]) -> dict[str, Any]:
    return {
        action: {
            "global_total": int((channel["global"][action] or {}).get("total") or 0),
            "families": sorted(
                family
                for family, tables in channel["families"].items()
                if int((tables.get(action) or {}).get("total") or 0) > 0
            ),
        }
        for action in AGGRESSIVE_ACTIONS
    }


# ---------------------------------------------------------------------------
# holdout tuning of the single regularization scale
# ---------------------------------------------------------------------------


def _prepare_rows(
    rows: Sequence[Mapping[str, Any]], config: Mapping[str, Any]
) -> list[tuple[dict[str, Any], int, list[str]]]:
    prepared: list[tuple[dict[str, Any], int, list[str]]] = []
    for row in rows:
        prepared.append(
            (context_block_nodes(row, config), ACTION_INDEX[_row_action(row)], legal_response_actions(row))
        )
    return prepared


def _tune_scale(
    candidate: Mapping[str, Any],
    prepared: Sequence[tuple[Mapping[str, Any], int, Sequence[str]]],
    prior: Sequence[float],
    grid: Sequence[float],
    *,
    architecture: str,
) -> dict[str, Any]:
    """Select the single regularization scale on a hand-disjoint holdout."""
    results: list[dict[str, Any]] = []
    best: tuple[float, float] | None = None
    for scale in grid:
        total = 0.0
        for nodes, action_index, legal in prepared:
            if architecture == ARCH_REGULARIZED:
                logits, _ = _regularized_logits(candidate, nodes, lift_scale=float(scale))
                probabilities, _ = _softmax_legal(logits, legal)
            else:
                weights, _ = _hierarchical_weights(candidate, nodes, deviation_scale=float(scale))
                probabilities, _ = _normalize_legal(weights, legal)
            total -= math.log2(max(float(probabilities[ACTIONS[action_index]]), PROBABILITY_FLOOR))
        loss = total / max(len(prepared), 1)
        results.append({"scale": float(scale), "holdout_log_loss_bits_per_decision": _round(loss)})
        if best is None or loss < best[0] - 1e-12:
            best = (loss, float(scale))
    return {
        "grid": [float(scale) for scale in grid],
        "results": results,
        "selected": best[1] if best else float(grid[0]),
        "selected_holdout_log_loss_bits_per_decision": _round(best[0]) if best else None,
        "baseline_log_loss_bits_per_decision": _round(
            -sum(math.log2(max(float(prior[action_index]), PROBABILITY_FLOOR)) for _, action_index, _ in prepared)
            / max(len(prepared), 1)
        ),
    }


# ---------------------------------------------------------------------------
# fit
# ---------------------------------------------------------------------------


def fit(
    train_rows: Iterable[Mapping[str, Any]],
    seed: int = 0,
    *,
    architecture: str = ARCH_REGULARIZED,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fit one architecture and return the JSON-serializable candidate document.

    The fit is deterministic: the rows are canonically ordered first, the
    hand-disjoint holdout fold is a function of ``seed`` and ``hand_id``, the
    tuning sub-sample is a deterministic stride, and no RNG is used anywhere.
    """
    if architecture not in ARCHITECTURES:
        raise GeneralizedResponseModelError(
            f"unknown architecture {architecture!r}; expected one of {', '.join(ARCHITECTURES)}"
        )
    merged = make_config(**dict(config)) if isinstance(config, Mapping) else make_config()
    rows = order_rows(train_rows)
    if not rows:
        raise GeneralizedResponseModelError("no train rows supplied")

    modulus = int(merged["holdout_modulus"])
    fit_rows: list[dict[str, Any]] = []
    holdout_rows: list[dict[str, Any]] = []
    hands: set[str] = set()
    for index, row in enumerate(rows):
        identity = _row_identity(row, index)
        hands.add(identity)
        if _holdout_bucket(identity, seed, modulus) == 0:
            holdout_rows.append(row)
        else:
            fit_rows.append(row)
    if not fit_rows or not holdout_rows:
        fit_rows, holdout_rows = rows, rows

    counts = _Counts(merged)
    for row in fit_rows:
        counts.add(row, context_block_nodes(row, merged), _row_action(row))
    prior = _prior_from_counts(counts.global_counts)

    if architecture == ARCH_REGULARIZED:
        blocks: dict[str, dict[str, Any]] = _regularized_blocks(counts, prior, merged)
        block_strengths: dict[str, Any] = {}
        grid = [float(x) for x in merged["lift_scale_grid"]]
    else:
        blocks, block_strengths = _hierarchical_blocks(counts, prior, merged)
        grid = [float(x) for x in merged["deviation_scale_grid"]]

    sizing_channel = _fit_sizing_channel(counts, merged)
    candidate: dict[str, Any] = {
        "schema": SCHEMA,
        "architecture": architecture,
        "seed": int(seed),
        "config": merged,
        "action_space": list(ACTIONS),
        "params": {
            "prior": {action: _round(prior[ACTION_INDEX[action]]) for action in ACTIONS},
            "blocks": blocks,
            "block_strengths": block_strengths,
            "sizing_channel": sizing_channel,
            "estimator": (
                "m_estimate_dirichlet_lift"
                if architecture == ARCH_REGULARIZED
                else "empirical_bayes_dirichlet_posterior_mean"
            ),
        },
    }

    # Tune the single regularization scale on the hand-disjoint holdout, using a
    # deterministic stride cap so the cost stays bounded and reproducible.
    cap = int(merged["tuning_max_rows"])
    stride = max(1, len(holdout_rows) // cap)
    tuning_rows = holdout_rows[::stride][:cap]
    prepared_tuning = _prepare_rows(tuning_rows, merged)
    tuning = _tune_scale(candidate, prepared_tuning, prior, grid, architecture=architecture)
    candidate["params"]["regularization"] = {
        "kind": "lift_scale" if architecture == ARCH_REGULARIZED else "deviation_scale",
        "scale": tuning["selected"],
    }

    # Refit the node tables on every supplied row once the scale is fixed.
    full_counts = _Counts(merged)
    for row in rows:
        full_counts.add(row, context_block_nodes(row, merged), _row_action(row))
    if architecture == ARCH_REGULARIZED:
        candidate["params"]["blocks"] = _regularized_blocks(full_counts, prior, merged)
    else:
        candidate["params"]["blocks"], candidate["params"]["block_strengths"] = _hierarchical_blocks(
            full_counts, prior, merged
        )
    candidate["params"]["sizing_channel"] = _fit_sizing_channel(full_counts, merged)

    holdout = evaluate(candidate, holdout_rows)
    candidate["fit_summary"] = {
        "rows": len(rows),
        "distinct_hands": len(hands),
        "fit_rows": len(fit_rows),
        "holdout_rows": len(holdout_rows),
        "tuning_rows": len(prepared_tuning),
        "holdout_modulus": modulus,
        "action_counts": {
            action: int(round(full_counts.global_counts[ACTION_INDEX[action]])) for action in ACTIONS
        },
        "action_rates": {action: _round(prior[ACTION_INDEX[action]]) for action in ACTIONS},
        "tuning": tuning,
        "baseline_log_loss_bits_per_decision": holdout["baseline_log_loss_bits_per_decision"],
        "holdout_log_loss_bits_per_decision": holdout["log_loss_bits_per_decision"],
        "holdout_gain_bits_per_decision": holdout["gain_bits_per_decision"],
        "interaction_cells": {
            block: len(candidate["params"]["blocks"][block]["nodes"]) for block in INTERACTION_BLOCK_NAMES
        },
        "sizing_channel": _sizing_channel_summary(candidate["params"]["sizing_channel"]),
    }
    candidate["canonical_payload_sha256"] = canonical_candidate_sha256(candidate)
    return candidate


def fit_many(
    train_rows: Sequence[Mapping[str, Any]],
    seed: int = 0,
    *,
    architectures: Sequence[str] = ARCHITECTURES,
    config: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fit several architectures on the same rows."""
    return [fit(train_rows, seed, architecture=architecture, config=config) for architecture in architectures]


# ---------------------------------------------------------------------------
# predict
# ---------------------------------------------------------------------------


def _core_distribution(
    candidate: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    legal: Sequence[str],
) -> tuple[dict[str, float], int]:
    nodes = context_block_nodes(context, candidate["config"])
    architecture = candidate["architecture"]
    if architecture == ARCH_REGULARIZED:
        logits, support = _regularized_logits(
            candidate, nodes, lift_scale=float(candidate["params"]["regularization"]["scale"])
        )
        return _softmax_legal(logits, legal)[0], support
    if architecture == ARCH_HIERARCHICAL:
        weights, support = _hierarchical_weights(
            candidate, nodes, deviation_scale=float(candidate["params"]["regularization"]["scale"])
        )
        return _normalize_legal(weights, legal)[0], support
    raise GeneralizedResponseModelError(f"unknown architecture {architecture!r}")


def predict(
    candidate: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
    *,
    legal_actions: Sequence[str] | None = None,
    **legacy: Any,
) -> dict[str, Any]:
    """Predict the legal response distribution of one public context.

    ``predict(candidate, context)`` mirrors ``fit(train_rows, seed) -> candidate;
    predict(context) -> {P(FOLD), P(CALL), P(RAISE), P(JAM)}``.  ``context`` may
    be passed positionally or as ``context=``; ``legal_actions`` overrides the
    masking space explicitly.
    """
    if context is None:
        context = legacy.pop("context", None)
    if context is None:
        raise GeneralizedResponseModelError("predict requires a context mapping")
    if legacy:
        raise GeneralizedResponseModelError(f"unexpected predict argument(s): {', '.join(sorted(legacy))}")
    if not isinstance(context, Mapping):
        raise TypeError("context must be a mapping")
    if _row_split(context) in FORBIDDEN_SPLITS:
        raise GeneralizedResponseModelError("refusing to predict on a TEST row")
    requested = (
        {str(x).upper() for x in legal_actions} if legal_actions is not None else set(legal_response_actions(context))
    )
    legal = [action for action in ACTIONS if action in requested]
    if not legal:
        raise GeneralizedResponseModelError("context has no legal action")
    probabilities, support = _core_distribution(candidate, context, legal=legal)
    gain = sizing_gain(candidate, context)
    weights = dict(probabilities)
    for action in AGGRESSIVE_ACTIONS:
        if action in legal:
            weights[action] *= float(gain["gains"][action])
    probabilities, normalization = _normalize_legal(weights, legal)
    response: dict[str, Any] = {
        "schema": PREDICTION_SCHEMA,
        "model_schema": SCHEMA,
        "architecture": candidate["architecture"],
        "candidate_canonical_payload_sha256": candidate.get("canonical_payload_sha256"),
        "legal_actions": legal,
        "masked_actions": [action for action in ACTIONS if action not in set(legal)],
        "probabilities": probabilities,
        "probability_sum": sum(probabilities.values()),
        "normalization": normalization,
        "sizing": {
            "conditioned": gain["query"]["source"] == "context",
            "source": gain["query"]["source"],
            "target_total_bb": gain["query"]["target_total_bb"],
            "sizing_ratio": gain["query"]["sizing_ratio"],
            "jam_ratio": gain["query"]["jam_ratio"],
            "gains": {action: _round(value, 9) for action, value in gain["gains"].items()},
            "gain_bounds": gain["gain_bounds"],
            "basis": "conditional_sizing_density_ratio",
            "interpolation": "linear_spline_partition_of_unity",
        },
        "support": int(support),
    }
    for action in ACTIONS:
        response[f"P({action})"] = probabilities[action]
    return response


def price_response(
    candidate: Mapping[str, Any],
    context: Mapping[str, Any],
    sizings: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Evaluate the response directly at each candidate raise target.

    Every point is recomputed from the queried ``target_total_bb``; nothing is
    looked up or borrowed from a neighbouring cell.  Returns the pointwise
    probabilities, the distinct-response count and the largest jump between
    adjacent queries, so a caller can audit direct, continuous recalculation.
    """
    if sizings is None:
        topology = max(float(context.get("effective_stack_bb") or 100.0), 1.0)
        pot = max(float(context.get("pot_before_bb") or 2.5) + float(context.get("to_call_bb") or 1.0), EPS)
        sizings = [
            round(pot * ratio, 6)
            for ratio in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0)
            if pot * ratio <= topology
        ]
        if not sizings:
            sizings = [round(min(pot, topology), 6)]
    sizings = [float(sizing) for sizing in sizings]
    if not sizings:
        raise GeneralizedResponseModelError("price_response requires at least one queried sizing")
    points: list[dict[str, Any]] = []
    vectors: list[tuple[float, ...]] = []
    for sizing in sizings:
        query = dict(context)
        query["target_total_bb"] = float(sizing)
        response = predict(candidate, query)
        vectors.append(tuple(float(response["probabilities"][action]) for action in ACTIONS))
        points.append(
            {
                "target_total_bb": _round(float(sizing)),
                "probabilities": dict(response["probabilities"]),
                "sizing_ratio": response["sizing"]["sizing_ratio"],
                "gains": dict(response["sizing"]["gains"]),
            }
        )
    max_jump = 0.0
    max_jump_action: str | None = None
    for previous, current in zip(vectors, vectors[1:]):
        for index, action in enumerate(ACTIONS):
            jump = abs(current[index] - previous[index])
            if jump > max_jump:
                max_jump, max_jump_action = jump, action
    return {
        "schema": PRICE_RESPONSE_SCHEMA,
        "architecture": candidate["architecture"],
        "targets": [_round(float(sizing)) for sizing in sizings],
        "points": points,
        "distinct_probability_vectors": len(set(vectors)),
        "monotone_target_axis": True,
        "direct_recalculation": True,
        "interpolation": "linear_spline_partition_of_unity",
        "max_adjacent_probability_jump": _round(max_jump, 9),
        "max_adjacent_jump_action": max_jump_action,
    }


# ---------------------------------------------------------------------------
# conditional raise / jam sizing model (#421; #388/#419 raise-sizing frontiers)
#
# The sizing channel above answers "how does the queried target move the
# RAISE/JAM gain".  This section answers the complementary question:
#
#     P(raise target | RAISE or JAM, public context)
#
# restricted to the *legal* target window of the engine:
#
#     min_raise_to_bb <= target <= max_raise_to_bb
#
# Three rules are non-negotiable and are asserted by
# ``tests/preflop/test_generalized_response_sizing.py``:
#
# 1. every produced target is legal (inside the window);
# 2. a missing statistic is *never* substituted by the nearest observed price
#    or the nearest public context -- the request fails closed instead;
# 3. every request exposes its support and its uncertainty.
#
# Engine legality, reconstructed from public features only
# --------------------------------------------------------
# The engine raises to ``current_bet + last_full_raise`` with
# ``last_full_raise >= big_blind``.  Let ``committed`` be the actor's own
# pre-action street contribution and ``cb = to_call + committed`` the current
# bet; the previous bet level ``prev`` always satisfies
# ``prev >= max(committed, big_blind)``.  Therefore
#
#     true_min = cb + (cb - prev) <= max(2*cb - max(committed, BB), cb + BB)
#
# so the expression on the right is a *conservative upper bound* of the true
# minimum raise: any target at or above it is legal.  The cap is the engine
# ``max_raise_to_bb`` when supplied, otherwise ``effective_stack_bb``, which is
# the minimum over the live stacks and therefore never exceeds the actor's own
# remaining stack -- again a conservative (legal) cap.  A missing commitment
# outside the free (``raise_level == 0``) regime fails closed, because a raise
# could then be produced below the true minimum.
# ---------------------------------------------------------------------------

RAISE_SIZING_SCHEMA = "poker-generalized-response-raise-sizing/v1"
RAISE_SIZING_REPORT_SCHEMA = "poker-generalized-response-raise-sizing-report/v1"
RAISE_SIZING_WINDOW_SCHEMA = "poker-generalized-response-raise-sizing-window/v1"

BIG_BLIND_BB = 1.0
POSITION_BLIND_BB: dict[str, float] = {"SB": 0.5, "BB": BIG_BLIND_BB}

#: Frozen raise-sizing evidence from the #388 exhaustive tree audit and the
#: #419 hierarchical exact-tree integration bundle.
FRONTIER_RESOLUTION_PATH = (
    ROOT / "analysis/issue419_hierarchical_tree/raise_sizing_frontiers_v2/RAISE_SIZING_FRONTIER_RESOLUTION.json"
)
EXACT_TREE_PATH = ROOT / "analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json"
DEFAULT_SIZING_REPORT_PATH = ROOT / "analysis/issue421_generalized_response/RAISE_SIZING_MODEL_REPORT.json"

#: Deterministic quadrature resolution of the truncated conditional density.
SIZING_QUADRATURE_STEPS = 96
MIN_FAMILY_SIZING_SUPPORT = 20
SIZING_QUANTILE_LEVELS = (
    0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50,
    0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95,
)
SIZING_GENERATION_QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)
CALIBRATION_LEVELS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
PIT_BINS = 10

#: Public pre-action contribution fields accepted from a preflop context.
CONTRIBUTION_FIELDS: tuple[str, ...] = (
    "actor_contribution_bb",
    "actor_street_contribution_bb",
    "actor_committed_bb",
    "street_contribution_bb",
)


def _free_position_blind(position: Any) -> float:
    return float(POSITION_BLIND_BB.get(_public_level(position), 0.0))


def raise_sizing_window(
    context: Mapping[str, Any],
    *,
    action: str | None = None,
    config: Mapping[str, Any] | None = None,
    actor_commitment_bb: float | None = None,
) -> dict[str, Any]:
    """Resolve the legal raise-target window of one public context.

    The engine interval (``min_raise_to_bb`` / ``max_raise_to_bb`` or
    ``legal_target_interval_bb``) is authoritative when the caller supplies it.
    Otherwise the window is *derived* from public features and is a
    conservative sub-window of the legal interval, so any produced target is
    legal without ever consulting a neighbouring observation.
    """
    if not isinstance(context, Mapping):
        raise GeneralizedResponseModelError("raise_sizing_window requires a context mapping")
    merged = make_config(**dict(config)) if isinstance(config, Mapping) else make_config()
    if action is not None and action not in AGGRESSIVE_ACTIONS:
        raise GeneralizedResponseModelError(
            f"raise sizing is defined for {AGGRESSIVE_ACTIONS}, not {action!r}"
        )

    to_call = max(_finite(context.get("to_call_bb") or 0.0, "to_call_bb"), 0.0)
    pot_before = max(_finite(context.get("pot_before_bb") or 0.0, "pot_before_bb"), 0.0)
    denominator = max(pot_before + to_call, EPS)

    explicit_min = context.get("min_raise_to_bb")
    explicit_max = context.get("max_raise_to_bb")
    interval = context.get("legal_target_interval_bb")
    if isinstance(interval, (list, tuple)) and len(interval) == 2:
        if explicit_min is None:
            explicit_min = interval[0]
        if explicit_max is None:
            explicit_max = interval[1]
    explicit_min = None if explicit_min is None else max(_finite(explicit_min, "min_raise_to_bb"), 0.0)
    explicit_max = None if explicit_max is None else max(_finite(explicit_max, "max_raise_to_bb"), 0.0)

    commitment: float | None = None
    commitment_source: str | None = None
    if actor_commitment_bb is not None:
        commitment = max(_finite(actor_commitment_bb, "actor_commitment_bb"), 0.0)
        commitment_source = "argument"
    else:
        for field in CONTRIBUTION_FIELDS:
            if context.get(field) is not None:
                commitment = max(_finite(context[field], field), 0.0)
                commitment_source = f"context.{field}"
                break

    current_bet: float | None = None
    for field in ("current_bet_bb", "current_price_bb"):
        if context.get(field) is not None:
            current_bet = max(_finite(context[field], field), 0.0)
            break

    try:
        raise_level = max(int(float(context.get("raise_level") or 0)), 0)
    except (TypeError, ValueError):
        raise_level = 0
    if commitment is None and raise_level == 0:
        # Free regime: the actor is an unacted blind, so the posted blind *is*
        # the pre-action contribution.
        commitment = _free_position_blind(context.get("actor_position"))
        commitment_source = "position_blind_raise_level_0"
    if current_bet is None and commitment is not None:
        current_bet = to_call + commitment

    derived_min: float | None = None
    if current_bet is not None and commitment is not None:
        previous_bet_lower_bound = max(commitment, BIG_BLIND_BB)
        derived_min = max(
            2.0 * current_bet - previous_bet_lower_bound,
            current_bet + BIG_BLIND_BB,
        )

    min_raise_to = explicit_min if explicit_min is not None else derived_min
    cap = explicit_max
    cap_source = "engine_max_raise_to"
    if cap is None:
        raw_cap = context.get("effective_stack_bb")
        cap = None if raw_cap is None else max(_finite(raw_cap, "effective_stack_bb"), 0.0)
        cap_source = "effective_stack_bb_conservative"

    reason: str | None = None
    if cap is None:
        reason = "MISSING_MAX_RAISE_TO"
    elif min_raise_to is None:
        reason = "MISSING_MIN_RAISE_TO_UNVERIFIED_COMMITMENT"

    jam_floor = current_bet if current_bet is not None else to_call
    if action == "RAISE":
        floor: float | None = min_raise_to
    elif action == "JAM":
        # An all-in shove is still subject to the minimum raise whenever the
        # stack allows one; when the minimum raise exceeds the effective stack
        # the only legal aggressive target is the full shove itself.
        floor = jam_floor
        if min_raise_to is not None and cap is not None:
            floor = max(jam_floor, min(min_raise_to, cap))
    else:
        floor = min_raise_to if min_raise_to is not None else jam_floor

    if reason is None and min_raise_to is not None and cap is not None and min_raise_to > cap + EPS:
        # The legal raise window is empty: only an all-in (which may be an
        # incomplete raise) remains legal, so a RAISE request fails closed.
        if action == "RAISE":
            reason = "RAISE_WINDOW_EMPTY_BELOW_STACK"
        elif floor is not None:
            floor = min(floor, cap)

    verified = min_raise_to is not None and cap is not None
    return {
        "schema": RAISE_SIZING_WINDOW_SCHEMA,
        "action": action,
        "to_call_bb": _round(to_call),
        "pot_before_bb": _round(pot_before),
        "ratio_denominator_bb": _round(denominator),
        "current_bet_bb": _round(current_bet),
        "actor_commitment_bb": _round(commitment),
        "actor_commitment_source": commitment_source,
        "min_raise_to_bb": _round(min_raise_to),
        "max_raise_to_bb": _round(cap),
        "jam_floor_bb": _round(jam_floor),
        "floor_bb": _round(floor),
        "cap_bb": _round(cap),
        "bounds_source": {
            "min": "engine_interval" if explicit_min is not None else "derived_conservative_floor",
            "max": cap_source,
        },
        "min_raise_floor_is_conservative": explicit_min is None,
        "cap_is_conservative": cap_source == "effective_stack_bb_conservative",
        "verified": bool(verified),
        "fail_closed": bool(reason is not None),
        "fail_closed_reason": reason,
    }


def sizing_channel_of(model: Mapping[str, Any]) -> Mapping[str, Any]:
    """Accept either a fitted candidate or a bare sizing channel document."""
    if not isinstance(model, Mapping):
        raise GeneralizedResponseModelError("sizing model must be a mapping")
    params = model.get("params")
    if isinstance(params, Mapping) and isinstance(params.get("sizing_channel"), Mapping):
        return params["sizing_channel"]
    if isinstance(model.get("global"), Mapping) and isinstance(model.get("axis_knots"), list):
        return model
    raise GeneralizedResponseModelError(
        "document carries neither params.sizing_channel nor a sizing channel"
    )


def fit_sizing_channel(
    rows: Iterable[Mapping[str, Any]],
    config: Mapping[str, Any] | None = None,
    *,
    min_family_support: int = MIN_FAMILY_SIZING_SUPPORT,
) -> dict[str, Any]:
    """Fit the conditional RAISE/JAM sizing channel straight from public rows.

    The returned document carries the same continuous ``log1p`` pot-relative
    density a full :func:`fit` stores under ``params.sizing_channel`` plus a
    ``boundary`` block with the measured atoms at the minimum raise and at the
    all-in cap.  Only sizing statistics are accumulated, so the fit is cheap.

    ``boundary`` is a *sizing-layer* extension: a candidate document keeps its
    contract-frozen channel (``contracts/training/generalized-response-model.
    schema.json`` forbids extra channel properties), so a query against a bare
    candidate channel reports ``boundary_mass_source == "unavailable"`` and
    falls back to the continuous density instead of inventing an atom.
    """
    merged = make_config(**dict(config)) if isinstance(config, Mapping) else make_config()
    all_rows = [dict(row) for row in rows]
    knots = [float(x) for x in merged["sizing_axis_knots"]]
    counters: dict[str, dict[str, list[float]]] = {
        action: {"GLOBAL": [0.0] * len(knots)} for action in AGGRESSIVE_ACTIONS
    }
    rows_seen = 0
    for row in all_rows:
        if not isinstance(row, Mapping):
            raise TypeError("sizing rows must be mappings")
        materialized = dict(row)
        _assert_consumable(materialized)
        action = _row_action(materialized)
        rows_seen += 1
        if action not in AGGRESSIVE_ACTIONS:
            continue
        sizing = sizing_context(materialized, merged)
        family = _public_level(materialized.get("family"))
        weights = spline_weights(float(sizing["sizing_ratio"]), knots)
        family_table = counters[action].setdefault(family, [0.0] * len(knots))
        for index, weight in weights.items():
            counters[action]["GLOBAL"][index] += float(weight)
            family_table[index] += float(weight)
    if rows_seen == 0:
        raise GeneralizedResponseModelError("no rows supplied to fit_sizing_channel")
    channel = _fit_sizing_channel_from_counts(counters, merged)
    channel["boundary"] = _fit_boundary_mass(all_rows, merged, min_family_support)
    return channel


def _ratio_density_on_grid(
    channel: Mapping[str, Any],
    action: str,
    family: str,
    ratios: Sequence[float],
) -> list[float]:
    """Piecewise-linear (log1p) density of ``action`` at each queried ratio."""
    tables = channel["families"].get(family) or {}
    table = tables.get(action) or channel["global"][action]
    axis = [_transform(float(knot)) for knot in channel["axis_knots"]]
    values = [float(value) for value in table["density"]]
    density: list[float] = []
    for ratio in ratios:
        u = _transform(ratio)
        if u <= axis[0]:
            value = values[0]
        elif u >= axis[-1]:
            value = values[-1]
        else:
            index = bisect.bisect_right(axis, u) - 1
            low, high = axis[index], axis[index + 1]
            weight = 0.0 if high <= low else (u - low) / (high - low)
            value = values[index] * (1.0 - weight) + values[index + 1] * weight
        density.append(max(float(value), 0.0))
    return density


def _sizing_support(
    channel: Mapping[str, Any], action: str, family: str, min_family_support: int
) -> dict[str, Any]:
    family_table = ((channel["families"].get(family) or {}).get(action)) or {}
    family_total = int(family_table.get("total") or 0)
    global_total = int((channel["global"][action] or {}).get("total") or 0)
    if family_total >= int(min_family_support):
        level, total = "FAMILY", family_total
    elif global_total > 0:
        level, total = "GLOBAL_FALLBACK", global_total
    else:
        level, total = "NO_SUPPORT", 0
    density = list(family_table.get("density") or channel["global"][action]["density"])
    distinct = sum(1 for value in density if float(value) > 0.0)
    return {
        "support_level": level,
        "action_observations": total,
        "family_observations": family_total,
        "global_observations": global_total,
        "min_family_support": int(min_family_support),
        "distinct_density_bins": distinct,
        "effective_sample_size": float(total),
    }


def _sizing_grid_density(
    channel: Mapping[str, Any],
    action: str,
    family: str,
    floor: float,
    cap: float,
    denominator: float,
    steps: int,
) -> tuple[list[float], list[float], float]:
    """Truncated density on the legal window: (grid, probabilities, mass).

    ``probabilities[index]`` is the mass of the interval
    ``[grid[index], grid[index + 1]]`` and is spread uniformly inside it, so the
    quantiles and the probability integral transform stay interval-consistent.
    """
    low_ratio = floor / denominator
    high_ratio = cap / denominator
    grid = [low_ratio + (high_ratio - low_ratio) * (index / steps) for index in range(steps + 1)]
    density = _ratio_density_on_grid(channel, action, family, grid)
    masses = [
        0.5 * (density[index] + density[index + 1]) * (grid[index + 1] - grid[index])
        for index in range(steps)
    ]
    mass = math.fsum(masses)
    if mass <= EPS:
        return grid, [], mass
    return grid, [value / mass for value in masses], mass


def _interval_quantile(grid: Sequence[float], probabilities: Sequence[float], level: float) -> float:
    """Linear-within-interval quantile of a piecewise-constant density."""
    cumulative = 0.0
    for index, probability in enumerate(probabilities):
        if probability <= 0.0:
            continue
        if cumulative + probability >= level:
            share = (level - cumulative) / probability
            return grid[index] + share * (grid[index + 1] - grid[index])
        cumulative += probability
    return grid[-1]


def _interval_pit(grid: Sequence[float], probabilities: Sequence[float], value: float) -> float:
    """Probability integral transform with uniform-within-interval mass."""
    if value <= grid[0]:
        return 0.0
    if value >= grid[-1]:
        return 1.0
    cumulative = 0.0
    for index, probability in enumerate(probabilities):
        left, right = grid[index], grid[index + 1]
        if value <= right:
            width = right - left
            share = 0.0 if width <= 0 else (value - left) / width
            return min(max(cumulative + probability * share, 0.0), 1.0)
        cumulative += probability
    return 1.0


def _continuous_mass_between(
    grid: Sequence[float], probabilities: Sequence[float], low: float, high: float
) -> float:
    """Mass of the piecewise-uniform continuous part within ``[low, high]``."""
    if high <= low or not probabilities:
        return 0.0
    low = max(low, grid[0])
    high = min(high, grid[-1])
    if high <= low:
        return 0.0
    total = 0.0
    for index, probability in enumerate(probabilities):
        if probability <= 0.0:
            continue
        left, right = grid[index], grid[index + 1]
        if right <= low:
            continue
        if left >= high:
            break
        overlap = min(right, high) - max(left, low)
        width = right - left
        if overlap > 0.0 and width > 0.0:
            total += probability * (overlap / width)
    return total


def _fit_boundary_mass(
    rows: Iterable[Mapping[str, Any]],
    config: Mapping[str, Any],
    min_family_support: int,
) -> dict[str, Any]:
    """Empirical atoms at the two ends of the legal raise window.

    Real preflop populations put large atoms on "raise to exactly the minimum"
    and on "shove the whole (effective) stack".  A purely continuous density
    cannot represent them, so the two atoms are measured directly -- with the
    actor's pre-action contribution recovered from the public row -- and are
    smoothed toward the pooled rate with the standard sizing smoothing mass.
    """
    counters: dict[str, dict[str, list[float]]] = {
        action: {"GLOBAL": [0.0, 0.0, 0.0]} for action in AGGRESSIVE_ACTIONS
    }
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("sizing rows must be mappings")
        action = str(row.get("action") or "").strip().upper()
        if action not in AGGRESSIVE_ACTIONS:
            continue
        target = row.get("target_total_bb")
        if target is None:
            continue
        window = raise_sizing_window(
            row, action=action, config=config, actor_commitment_bb=recover_actor_commitment(row)
        )
        floor, cap = window["floor_bb"], window["cap_bb"]
        if window["fail_closed"] or floor is None or cap is None or cap <= floor:
            continue
        family = _public_level(row.get("family"))
        table = counters[action].setdefault(family, [0.0, 0.0, 0.0])
        for bucket in (counters[action]["GLOBAL"], table):
            bucket[0] += 1.0
            if abs(float(target) - float(floor)) <= 1e-6:
                bucket[1] += 1.0
            if abs(float(target) - float(cap)) <= 1e-6:
                bucket[2] += 1.0

    smoothing = float(config["sizing_smoothing_mass"])
    pooled: dict[str, float] = {}
    for action in AGGRESSIVE_ACTIONS:
        global_counts = counters[action]["GLOBAL"]
        total = float(global_counts[0])
        pooled[action] = (global_counts[1] / total) if total > 0 else 0.0
        pooled[f"{action}:cap"] = (global_counts[2] / total) if total > 0 else 0.0

    def smoothed(counts: Sequence[float], action: str) -> dict[str, Any]:
        total = float(counts[0])
        if total <= 0:
            return {"n": 0, "at_floor": 0, "at_cap": 0, "p_floor": 0.0, "p_cap": 0.0}
        p_floor = (counts[1] + smoothing * pooled[action]) / (total + smoothing)
        p_cap = (counts[2] + smoothing * pooled[f"{action}:cap"]) / (total + smoothing)
        if p_floor + p_cap > 0.95:
            scale = 0.95 / (p_floor + p_cap)
            p_floor, p_cap = p_floor * scale, p_cap * scale
        return {
            "n": int(round(total)),
            "at_floor": int(round(counts[1])),
            "at_cap": int(round(counts[2])),
            "p_floor": _round(p_floor, 9),
            "p_cap": _round(p_cap, 9),
        }

    boundary: dict[str, Any] = {
        "min_family_support": int(min_family_support),
        "tolerance_bb": 1e-6,
        "global": {
            action: smoothed(counters[action]["GLOBAL"], action) for action in AGGRESSIVE_ACTIONS
        },
        "families": {},
    }
    for action in AGGRESSIVE_ACTIONS:
        for family, counts in counters[action].items():
            if family == "GLOBAL":
                continue
            boundary["families"].setdefault(family, {})[action] = smoothed(counts, action)
    return boundary


def _boundary_mass(
    channel: Mapping[str, Any], action: str, family: str, min_family_support: int
) -> tuple[float, float, str]:
    """Smoothed ``(p_floor, p_cap, source)`` of one action/family request."""
    boundary = channel.get("boundary")
    if not isinstance(boundary, Mapping):
        return 0.0, 0.0, "unavailable"
    family_table = ((boundary.get("families") or {}).get(family) or {}).get(action) or {}
    global_table = (boundary.get("global") or {}).get(action) or {}
    if int(family_table.get("n") or 0) >= int(min_family_support):
        return (
            float(family_table.get("p_floor") or 0.0),
            float(family_table.get("p_cap") or 0.0),
            "FAMILY",
        )
    if int(global_table.get("n") or 0) > 0:
        return (
            float(global_table.get("p_floor") or 0.0),
            float(global_table.get("p_cap") or 0.0),
            "GLOBAL_FALLBACK",
        )
    return 0.0, 0.0, "NO_SUPPORT"


def _mixed_sizing_model(
    channel: Mapping[str, Any],
    action: str,
    family: str,
    window: Mapping[str, Any],
    denominator: float,
    steps: int,
    min_family_support: int,
) -> dict[str, Any]:
    """Mixture of two boundary atoms and the truncated continuous density."""
    floor, cap = float(window["floor_bb"]), float(window["cap_bb"])
    grid, continuous, mass = _sizing_grid_density(
        channel, action, family, floor, cap, denominator, steps
    )
    atom_floor, atom_cap, source = _boundary_mass(channel, action, family, min_family_support)
    if not continuous:
        return {
            "floor": floor,
            "cap": cap,
            "denominator": denominator,
            "grid": [floor, cap],
            "continuous": [],
            "unit_continuous": [],
            "truncation_mass": mass,
            "atom_floor": atom_floor,
            "atom_cap": atom_cap,
            "continuous_mass": 0.0,
            "boundary_source": source,
        }
    continuous_mass = max(0.0, 1.0 - atom_floor - atom_cap)
    return {
        "floor": floor,
        "cap": cap,
        "denominator": denominator,
        "grid": grid,
        "continuous": [probability * continuous_mass for probability in continuous],
        "unit_continuous": continuous,
        "truncation_mass": mass,
        "atom_floor": atom_floor,
        "atom_cap": atom_cap,
        "continuous_mass": continuous_mass,
        "boundary_source": source,
    }


def _sizing_spec(
    channel: Mapping[str, Any],
    action: str,
    family: str,
    window: Mapping[str, Any],
    denominator: float,
    steps: int,
    min_family_support: int,
) -> dict[str, Any]:
    """Mixed sizing spec of one window, including the degenerate shove-only case."""
    floor, cap = float(window["floor_bb"]), float(window["cap_bb"])
    if cap <= floor + EPS:
        # A single legal aggressive target (the shove-only short stack): the
        # conditional distribution is the degenerate point mass on it.
        return {
            "floor": floor,
            "cap": cap,
            "denominator": denominator,
            "grid": [floor, cap],
            "continuous": [],
            "unit_continuous": [],
            "truncation_mass": 0.0,
            "atom_floor": 1.0,
            "atom_cap": 0.0,
            "continuous_mass": 0.0,
            "boundary_source": "single_legal_target",
        }
    return _mixed_sizing_model(
        channel, action, family, window, denominator, steps, min_family_support
    )


def _mixed_support(spec: Mapping[str, Any]) -> tuple[list[float], list[float]]:
    """Discrete support/weights of the mixed model, in bb units."""
    denominator = spec["denominator"]
    points = [spec["floor"]]
    weights = [spec["atom_floor"]]
    for index, probability in enumerate(spec["continuous"]):
        points.append(0.5 * (spec["grid"][index] + spec["grid"][index + 1]) * denominator)
        weights.append(probability)
    points.append(spec["cap"])
    weights.append(spec["atom_cap"])
    return points, weights


def _mixed_quantile(spec: Mapping[str, Any], level: float) -> float:
    """Quantile in bb units of the mixed model."""
    atom_floor, atom_cap = spec["atom_floor"], spec["atom_cap"]
    if level <= atom_floor:
        return spec["floor"]
    if level >= 1.0 - atom_cap:
        return spec["cap"]
    share = (level - atom_floor) / max(spec["continuous_mass"], EPS)
    return _interval_quantile(spec["grid"], spec["unit_continuous"], share) * spec["denominator"]


def _mixed_pit(spec: Mapping[str, Any], target: float) -> float:
    """Probability integral transform of the mixed distribution."""
    if target <= spec["floor"]:
        return min(spec["atom_floor"], 1.0)
    if target >= spec["cap"]:
        return 1.0
    inner = _interval_pit(spec["grid"], spec["unit_continuous"], target / spec["denominator"])
    return min(max(spec["atom_floor"] + spec["continuous_mass"] * inner, 0.0), 1.0)


def _mixed_bin_mass(spec: Mapping[str, Any], target: float, width: float = 1.0) -> float:
    """Probability of a ``width``-wide window around ``target`` (bb units)."""
    low, high = target - width / 2.0, target + width / 2.0
    mass = spec["continuous_mass"] * _continuous_mass_between(
        spec["grid"],
        spec["unit_continuous"],
        low / spec["denominator"],
        high / spec["denominator"],
    )
    if low <= spec["floor"] <= high:
        mass += spec["atom_floor"]
    if low <= spec["cap"] <= high:
        mass += spec["atom_cap"]
    return mass


def _mixed_crps_bb(points: Sequence[float], weights: Sequence[float], target: float) -> float:
    """CRPS (bb) of the discrete mixed support."""
    term1 = math.fsum(weight * abs(point - target) for point, weight in zip(points, weights))
    cumulative_weight = 0.0
    cumulative_moment = 0.0
    pair = 0.0
    for point, weight in zip(points, weights):
        pair += weight * (point * cumulative_weight - cumulative_moment)
        cumulative_weight += weight
        cumulative_moment += weight * point
    return term1 - pair


def raise_sizing_distribution(
    model: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    action: str = "RAISE",
    config: Mapping[str, Any] | None = None,
    steps: int = SIZING_QUADRATURE_STEPS,
    actor_commitment_bb: float | None = None,
    min_family_support: int = MIN_FAMILY_SIZING_SUPPORT,
) -> dict[str, Any]:
    """Conditional P(sizing | action, public context): atoms plus density.

    The distribution is a two-atom mixture: a measured atom at the minimum
    legal raise, a measured atom at the all-in cap, and the truncated ``log1p``
    pot-relative density in between.  Nothing is looked up in, or borrowed
    from, a neighbouring cell: the window, the atoms and the density are all
    functions of the query and the fitted channel.
    """
    if action not in AGGRESSIVE_ACTIONS:
        raise GeneralizedResponseModelError(f"unknown sizing action {action!r}")
    channel = sizing_channel_of(model)
    merged = make_config(**dict(config)) if isinstance(config, Mapping) else make_config()
    steps = max(int(steps), 8)
    window = raise_sizing_window(
        context, action=action, config=merged, actor_commitment_bb=actor_commitment_bb
    )
    family = _public_level(context.get("family"))
    support = _sizing_support(channel, action, family, min_family_support)
    base: dict[str, Any] = {
        "schema": RAISE_SIZING_SCHEMA,
        "action": action,
        "family": family,
        "legal_window": window,
        "support": support,
        "nearest_price_substituted": False,
        "nearest_context_substituted": False,
        "interpolation": (
            "boundary_atoms_plus_linear_spline_partition_of_unity_truncated_to_legal_window"
        ),
    }
    floor, cap = window["floor_bb"], window["cap_bb"]
    if window["fail_closed"] or floor is None or cap is None or cap < floor - EPS:
        base.update(
            {
                "status": "FAIL_CLOSED",
                "fail_closed_reason": window["fail_closed_reason"] or "EMPTY_LEGAL_WINDOW",
                "uncertainty": None,
                "quantiles_bb": None,
                "density": None,
            }
        )
        return base
    denominator = float(window["ratio_denominator_bb"])
    spec = _sizing_spec(channel, action, family, window, denominator, steps, min_family_support)
    points, weights = _mixed_support(spec)
    if math.fsum(weights) <= EPS:
        base.update(
            {
                "status": "FAIL_CLOSED",
                "fail_closed_reason": "NO_SUPPORT_INSIDE_LEGAL_WINDOW",
                "uncertainty": None,
                "quantiles_bb": None,
                "density": None,
            }
        )
        return base
    positive = [weight for weight in weights if weight > 0.0]
    entropy = -math.fsum(weight * math.log(weight) for weight in positive)
    normalized_entropy = entropy / math.log(len(positive)) if len(positive) > 1 else 0.0
    mode_index = max(range(len(weights)), key=lambda index: weights[index])
    credible_low = _mixed_quantile(spec, 0.1)
    credible_high = _mixed_quantile(spec, 0.9)
    base.update(
        {
            "status": "RESOLVED",
            "density": {
                "grid_points": steps + 1,
                "quadrature": "deterministic_trapezoid_on_ratio_grid",
                "truncation_mass": _round(spec["truncation_mass"], 12),
                "continuous_mass": _round(spec["continuous_mass"], 9),
                "atom_floor_probability": _round(spec["atom_floor"], 9),
                "atom_cap_probability": _round(spec["atom_cap"], 9),
                "boundary_mass_source": spec["boundary_source"],
                "window_ratio": _round(float(floor) / denominator),
                "window_ratio_high": _round(float(cap) / denominator),
                "unnormalized_peak_density": _round(
                    max(_ratio_density_on_grid(channel, action, family, spec["grid"])), 12
                ),
            },
            "uncertainty": {
                "entropy_nats": _round(entropy, 9),
                "entropy_normalized": _round(normalized_entropy, 9),
                "concentration": _round(1.0 - normalized_entropy, 9),
                "credible_interval_bb": [
                    _round(credible_low),
                    _round(credible_high),
                ],
                "credible_interval_width_bb": _round(credible_high - credible_low),
                "credible_interval_ratio": [
                    _round(credible_low / denominator),
                    _round(credible_high / denominator),
                ],
                "mode_bb": _round(points[mode_index]),
                "median_bb": _round(_mixed_quantile(spec, 0.5)),
                "mode_probability": _round(weights[mode_index], 9),
                "mean_bb": _round(math.fsum(p * w for p, w in zip(points, weights))),
                "boundary_probabilities": {
                    "floor": _round(spec["atom_floor"], 9),
                    "cap": _round(spec["atom_cap"], 9),
                    "continuous": _round(spec["continuous_mass"], 9),
                },
                "window_width_bb": _round(float(cap) - float(floor)),
                "window_width_ratio": _round((float(cap) - float(floor)) / denominator),
            },
            "quantiles_bb": {
                f"{level:.2f}": _round(_mixed_quantile(spec, level))
                for level in SIZING_QUANTILE_LEVELS
            },
            "probability_sum": _round(math.fsum(weights), 12),
            "cdf_check": 1.0,
            "illegal_generated_count": 0,
        }
    )
    return base


def generate_raise_sizings(
    model: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    action: str = "RAISE",
    config: Mapping[str, Any] | None = None,
    steps: int = SIZING_QUADRATURE_STEPS,
    actor_commitment_bb: float | None = None,
    quantiles: Sequence[float] = SIZING_GENERATION_QUANTILES,
    distribution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce several plausible, always-legal sizings for one context.

    Generation is the deterministic quantile grid of the truncated conditional
    density, so the targets are legal by construction and the request stays
    reproducible; no randomness and no nearest-price lookup is involved.
    """
    resolved = distribution or raise_sizing_distribution(
        model,
        context,
        action=action,
        config=config,
        steps=steps,
        actor_commitment_bb=actor_commitment_bb,
    )
    window = resolved["legal_window"]
    result: dict[str, Any] = {
        "schema": RAISE_SIZING_SCHEMA,
        "action": action,
        "status": resolved["status"],
        "fail_closed_reason": resolved.get("fail_closed_reason"),
        "legal_window": window,
        "method": "deterministic_quantile_grid",
        "quantile_levels": [round(float(level), 6) for level in quantiles],
        "nearest_price_substituted": False,
        "nearest_context_substituted": False,
    }
    if resolved["status"] != "RESOLVED":
        result.update({"sizings_bb": [], "generated_count": 0, "illegal_count": 0})
        return result
    floor, cap = float(window["floor_bb"]), float(window["cap_bb"])
    quantiles_map = resolved["quantiles_bb"]
    produced: list[float] = []
    for level in quantiles:
        key = f"{float(level):.2f}"
        value = quantiles_map.get(key)
        if value is None:
            value = resolved["uncertainty"]["median_bb"]
        produced.append(float(value))
    produced = sorted({round(min(max(value, floor), cap), 6) for value in produced})
    illegal = sum(1 for value in produced if value < floor - 1e-9 or value > cap + 1e-9)
    result.update(
        {
            "sizings_bb": produced,
            "generated_count": len(produced),
            "illegal_count": illegal,
            "support": resolved["support"],
            "uncertainty": resolved["uncertainty"],
            "ratio_denominator_bb": window["ratio_denominator_bb"],
        }
    )
    return result


def score_raise_sizing(
    model: Mapping[str, Any],
    context: Mapping[str, Any],
    target_total_bb: float,
    *,
    action: str = "RAISE",
    config: Mapping[str, Any] | None = None,
    steps: int = SIZING_QUADRATURE_STEPS,
    actor_commitment_bb: float | None = None,
    distribution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Score one queried raise target under the conditional sizing model.

    Returns the negative log likelihood (bits), the CRPS (bb) and the PIT of
    the queried target.  The likelihood is a mixed likelihood at a fixed 1 bb
    resolution: an observation on a boundary atom uses that atom's probability,
    and a continuous observation uses the mass the density puts in the 1 bb
    window around it, so atoms and density stay on one comparable scale.  A
    target outside the legal window is reported as such and left unscored: it
    is never re-scored against a neighbouring price.
    """
    target = _finite(target_total_bb, "target_total_bb")
    resolved = distribution or raise_sizing_distribution(
        model,
        context,
        action=action,
        config=config,
        steps=steps,
        actor_commitment_bb=actor_commitment_bb,
    )
    window = resolved["legal_window"]
    result: dict[str, Any] = {
        "schema": RAISE_SIZING_SCHEMA,
        "action": action,
        "target_total_bb": _round(target),
        "legal_window": window,
        "status": resolved["status"],
        "nearest_price_substituted": False,
    }
    if resolved["status"] != "RESOLVED":
        result.update(
            {
                "inside_window": False,
                "scored": False,
                "fail_closed_reason": resolved.get("fail_closed_reason"),
            }
        )
        return result
    floor, cap = float(window["floor_bb"]), float(window["cap_bb"])
    inside = floor - 1e-9 <= target <= cap + 1e-9
    result["inside_window"] = bool(inside)
    if not inside:
        result.update({"scored": False, "fail_closed_reason": "TARGET_OUTSIDE_LEGAL_WINDOW"})
        return result

    channel = sizing_channel_of(model)
    steps = max(int(steps), 8)
    family = _public_level(context.get("family"))
    denominator = float(window["ratio_denominator_bb"])
    spec = _sizing_spec(
        channel,
        action,
        family,
        window,
        denominator,
        steps,
        int(resolved["support"].get("min_family_support") or MIN_FAMILY_SIZING_SUPPORT),
    )
    points, weights = _mixed_support(spec)
    if math.fsum(weights) <= EPS:
        result.update({"scored": False, "fail_closed_reason": "NO_SUPPORT_INSIDE_LEGAL_WINDOW"})
        return result

    bin_mass = _mixed_bin_mass(spec, target, 1.0)
    nll_bits = -math.log2(max(bin_mass, PROBABILITY_FLOOR))
    pit = _mixed_pit(spec, target)
    crps_bb = _mixed_crps_bb(points, weights, target)
    uniform_nll_bits = math.log2(max(cap - floor, EPS))

    result.update(
        {
            "scored": True,
            "log_density_bits": _round(-nll_bits),
            "negative_log_likelihood_bits": _round(nll_bits),
            "uniform_window_nll_bits": _round(uniform_nll_bits),
            "nll_gain_vs_uniform_bits": _round(uniform_nll_bits - nll_bits),
            "crps_bb": _round(crps_bb),
            "pit": _round(pit, 9),
            "bin_mass_bb": _round(bin_mass, 9),
            "on_boundary_atom": bool(
                abs(target - floor) <= 1e-6 or abs(target - cap) <= 1e-6
            ),
            "truncation_mass": _round(spec["truncation_mass"], 12),
            "support": resolved["support"],
        }
    )
    return result


def raise_sizing_query(
    model: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    action: str | None = None,
    config: Mapping[str, Any] | None = None,
    steps: int = SIZING_QUADRATURE_STEPS,
    actor_commitment_bb: float | None = None,
) -> dict[str, Any]:
    """One sizing request: legal window, support, uncertainty, quantiles, samples."""
    if action is None:
        legal = legal_response_actions(context)
        action = "RAISE" if "RAISE" in legal else "JAM"
    distribution = raise_sizing_distribution(
        model,
        context,
        action=action,
        config=config,
        steps=steps,
        actor_commitment_bb=actor_commitment_bb,
    )
    generation = generate_raise_sizings(
        model,
        context,
        action=action,
        config=config,
        steps=steps,
        actor_commitment_bb=actor_commitment_bb,
        distribution=distribution,
    )
    return {
        "schema": RAISE_SIZING_SCHEMA,
        "action": action,
        "status": distribution["status"],
        "fail_closed_reason": distribution.get("fail_closed_reason"),
        "legal_window": distribution["legal_window"],
        "support": distribution["support"],
        "uncertainty": distribution["uncertainty"],
        "quantiles_bb": distribution["quantiles_bb"],
        "generated_sizings_bb": generation["sizings_bb"],
        "generated_count": generation["generated_count"],
        "illegal_count": generation["illegal_count"],
        "nearest_price_substituted": False,
        "nearest_context_substituted": False,
    }


def _parse_raise_amount(token: Any) -> float | None:
    text = str(token or "")
    if "@" not in text:
        return None
    raw = text.rsplit("@", 1)[1].strip()
    try:
        return float(raw)
    except ValueError:
        return None


RAISE_VERBS = ("RAISE", "JAM", "ISO", "3BET", "4BET", "5BET", "6BET")


def reconstruct_frontier_context(frontier: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild the public pre-action state of one frozen #388/#419 frontier.

    Only the public structural context, the exact tree path, the contract
    history and the blind structure are consumed; the reconstruction is echoed
    in the report so the derived window can be checked against the frozen
    engine interval.
    """
    structural = dict(frontier.get("structural_context") or {})
    path = [str(token) for token in (frontier.get("path") or [])]
    history = [dict(item) for item in (structural.get("history") or [])]
    actor = str(structural.get("actor_position") or "")
    table_size = int(structural.get("table_size") or 6)

    seat_order = list(("LJ", "HJ", "CO", "BTN", "SB", "BB")[-table_size:])
    contributions: dict[str, float] = {}
    if "SB" in seat_order:
        contributions["SB"] = POSITION_BLIND_BB["SB"]
    if "BB" in seat_order:
        contributions["BB"] = POSITION_BLIND_BB["BB"]
    current_bet = BIG_BLIND_BB if "BB" in seat_order else 0.0

    raise_amount = None
    for token in path:
        parsed = _parse_raise_amount(token)
        if parsed is not None:
            raise_amount = parsed
    for token in path:
        position, _, rest = token.partition(":")
        verb = rest.split("@", 1)[0].upper()
        if verb in ("CALL", "LIMP"):
            contributions[position] = max(contributions.get(position, 0.0), current_bet)
        elif verb in RAISE_VERBS:
            amount = _parse_raise_amount(token) or current_bet
            contributions[position] = amount
            current_bet = amount
    for item in history:
        position = str(item.get("position") or "")
        verb = str(item.get("action") or "").upper()
        if verb == "LIMP":
            contributions[position] = max(contributions.get(position, 0.0), BIG_BLIND_BB)
        elif verb == "CALL":
            contributions[position] = max(contributions.get(position, 0.0), current_bet)
        elif verb in RAISE_VERBS:
            amount = _parse_raise_amount(item.get("amount")) or raise_amount or current_bet
            contributions[position] = amount
            current_bet = amount

    commitment = contributions.get(actor)
    if commitment is None:
        if actor == "BB":
            commitment = BIG_BLIND_BB
        elif actor == "SB":
            commitment = POSITION_BLIND_BB["SB"]
        else:
            commitment = 0.0
    context: dict[str, Any] = {
        "family": structural.get("family"),
        "actor_position": actor,
        "table_size": table_size,
        "live_positions": list(structural.get("live_positions") or []),
        "raise_level": int(structural.get("raise_level") or 0),
        "current_bet_bb": current_bet,
        "actor_contribution_bb": commitment,
        "to_call_bb": round(max(current_bet - commitment, 0.0), 6),
        "pot_before_bb": round(math.fsum(contributions.values()), 6),
    }
    context["context_reconstruction"] = {
        "contributions_bb": {position: _round(value) for position, value in sorted(contributions.items())},
        "seat_order": seat_order,
        "rule": "public seat contributions rebuilt from blinds, the exact tree path and the contract history",
    }
    interval = frontier.get("legal_target_interval_bb")
    if interval and len(interval) == 2:
        # The frozen engine interval carries the actor's cap (its maximum
        # raise-to), which the public response rows expose as the effective
        # stack; echoing it keeps the derived window checkable.
        context["effective_stack_bb"] = float(interval[1])
    return context


def load_raise_sizing_frontiers(
    frontier_path: str | Path = FRONTIER_RESOLUTION_PATH,
    exact_tree_path: str | Path = EXACT_TREE_PATH,
) -> dict[str, Any]:
    """Load the frozen 7 raise-sizing frontiers, failing closed when absent."""
    resolved_path = Path(frontier_path)
    tree_path = Path(exact_tree_path)
    def _label(path: Path) -> str:
        try:
            return str(path.relative_to(ROOT))
        except ValueError:
            return str(path)

    document: dict[str, Any] = {
        "frontier_source": _label(resolved_path),
        "exact_tree_source": _label(tree_path),
        "loaded": False,
        "frontiers": [],
    }
    if not resolved_path.exists():
        document["fail_closed_reason"] = "FRONTIER_RESOLUTION_MISSING"
        return document
    resolution = json.loads(resolved_path.read_text(encoding="utf-8"))
    exact_tree: dict[str, Any] = {}
    if tree_path.exists():
        tree_document = json.loads(tree_path.read_text(encoding="utf-8"))
        for item in tree_document.get("unresolved_sizing_frontiers") or []:
            exact_tree[str(item.get("node_id"))] = {
                "status": "UNRESOLVED",
                "legal_target_interval_bb": item.get("legal_target_interval_bb"),
                "action": item.get("action"),
                "descendants": item.get("descendants"),
                "expansion_rule": item.get("expansion_rule"),
            }
    typed: list[dict[str, Any]] = []
    for frontier in resolution.get("frontiers") or []:
        node_id = str(frontier.get("node_id"))
        exact = exact_tree.get(node_id) or {}
        interval = exact.get("legal_target_interval_bb") or frontier.get("legal_target_interval_bb") or []
        exact_support = dict(frontier.get("exact_support") or {})
        typed.append(
            {
                "node_id": node_id,
                "path": list(frontier.get("path") or []),
                "action": str(frontier.get("action") or "RAISE"),
                "resolution_state": str(frontier.get("resolution_state") or "UNRESOLVED"),
                "blocker_reason_code": frontier.get("blocker_reason_code"),
                "blocks_required_tree_complete": bool(
                    frontier.get("blocks_required_tree_complete", True)
                ),
                "legal_target_interval_bb": [float(value) for value in interval] if interval else None,
                "structural_context": dict(frontier.get("structural_context") or {}),
                "exact_tree_status": exact.get("status") or "UNRESOLVED",
                "exact_tree_satisfied": False,
                "exact_support": {
                    "nearest_price_substituted": bool(exact_support.get("nearest_price_substituted", False)),
                    "legal_minimum_fallback_substituted": bool(
                        exact_support.get("legal_minimum_fallback_substituted", False)
                    ),
                    "translatable_sizing_stat_keys_present": list(
                        exact_support.get("translatable_sizing_stat_keys_present") or []
                    ),
                },
            }
        )
    document.update(
        {
            "loaded": True,
            "schema": resolution.get("schema"),
            "revision": resolution.get("revision"),
            "frontiers_total": int(resolution.get("frontiers_total") or len(typed)),
            "frontiers": typed,
        }
    )
    return document


# ---------------------------------------------------------------------------
# evaluate / compare
# ---------------------------------------------------------------------------


def evaluate(
    candidate: Mapping[str, Any],
    rows: Iterable[Mapping[str, Any]],
    *,
    sizing: str = "marginal",
    target_total_bb: float | None = None,
) -> dict[str, Any]:
    """Direct evaluation of one candidate on rows.

    ``sizing="marginal"`` (default) evaluates the discrete choice without the
    conditional sizing channel; ``sizing="observed_where_available"`` feeds each
    row's own observed ``target_total_bb`` into the price/sizing response, which
    is the direct evaluation of the price/sizing function.

    ``target_total_bb`` evaluates every row at one explicitly queried raise
    target: the returned log loss is then a direct function of the queried price
    and sizing rather than of the row's own observed sizing.
    """
    if sizing not in ("marginal", "observed_where_available"):
        raise GeneralizedResponseModelError(f"unknown sizing mode: {sizing!r}")
    materialized = order_rows(rows)
    if target_total_bb is not None:
        queried = _finite(target_total_bb, "target_total_bb")
        materialized = [dict(row, target_total_bb=queried) for row in materialized]
    prior = {action: float(candidate["params"]["prior"][action]) for action in ACTIONS}
    total_log_loss = 0.0
    baseline_log_loss = 0.0
    brier = 0.0
    correct = 0
    sum_error = 0.0
    illegal_mass = 0.0
    per_action: dict[str, dict[str, Any]] = {action: {"count": 0, "probability_sum": 0.0} for action in ACTIONS}
    by_family: dict[str, dict[str, float]] = {}
    for row in materialized:
        observed = _row_action(row)
        query = dict(row)
        if sizing == "observed_where_available" and row.get("target_total_bb") is None:
            query.pop("target_total_bb", None)
        response = predict(candidate, query)
        probabilities = response["probabilities"]
        log_loss = -math.log2(max(float(probabilities[observed]), PROBABILITY_FLOOR))
        baseline = -math.log2(max(prior[observed], PROBABILITY_FLOOR))
        total_log_loss += log_loss
        baseline_log_loss += baseline
        brier += sum(
            (float(probabilities[action]) - (1.0 if action == observed else 0.0)) ** 2 for action in ACTIONS
        )
        correct += 1 if max(probabilities, key=lambda action: probabilities[action]) == observed else 0
        sum_error = max(sum_error, abs(float(response["probability_sum"]) - 1.0))
        illegal_mass = max(
            illegal_mass, sum(float(probabilities[action]) for action in response["masked_actions"])
        )
        per_action[observed]["count"] += 1
        per_action[observed]["probability_sum"] += float(probabilities[observed])
        family = _public_level(row.get("family"))
        bucket = by_family.setdefault(family, {"n": 0.0, "log_loss": 0.0, "baseline": 0.0})
        bucket["n"] += 1.0
        bucket["log_loss"] += log_loss
        bucket["baseline"] += baseline
    n = len(materialized)
    if n == 0:
        raise GeneralizedResponseModelError("no rows to evaluate")
    return {
        "schema": EVALUATION_SCHEMA,
        "architecture": candidate["architecture"],
        "candidate_canonical_payload_sha256": candidate.get("canonical_payload_sha256"),
        "n": n,
        "sizing_mode": sizing,
        "queried_target_total_bb": _round(target_total_bb),
        "log_loss_bits_per_decision": _round(total_log_loss / n),
        "baseline_log_loss_bits_per_decision": _round(baseline_log_loss / n),
        "gain_bits_per_decision": _round((baseline_log_loss - total_log_loss) / n),
        "brier_score": _round(brier / n),
        "accuracy": _round(correct / n),
        "probability_sum_max_abs_error": _round(sum_error, 12),
        "illegal_mass_max": _round(illegal_mass, 12),
        "observed_action_counts": {action: per_action[action]["count"] for action in ACTIONS},
        "mean_observed_probability": {
            action: _round(per_action[action]["probability_sum"] / per_action[action]["count"])
            for action in ACTIONS
            if per_action[action]["count"]
        },
        "by_family": {
            family: {
                "n": int(round(values["n"])),
                "log_loss_bits_per_decision": _round(values["log_loss"] / values["n"]),
                "baseline_log_loss_bits_per_decision": _round(values["baseline"] / values["n"]),
            }
            for family, values in sorted(by_family.items())
        },
    }


def compare_candidates(
    candidates: Sequence[Mapping[str, Any]],
    rows: Iterable[Mapping[str, Any]],
    *,
    sizing: str = "marginal",
) -> dict[str, Any]:
    """Evaluate several candidates on the same rows and rank them."""
    if not candidates:
        raise GeneralizedResponseModelError("no candidates to compare")
    materialized = order_rows(rows)
    metrics: dict[str, Any] = {}
    for candidate in candidates:
        digest = str(candidate.get("canonical_payload_sha256") or canonical_candidate_sha256(candidate))
        key = f"{candidate['architecture']}:{digest[:12]}"
        metrics[key] = evaluate(candidate, materialized, sizing=sizing)
    ranking = sorted(metrics, key=lambda key: (metrics[key]["log_loss_bits_per_decision"], key))
    best = metrics[ranking[0]]
    return {
        "schema": COMPARISON_SCHEMA,
        "sizing_mode": sizing,
        "rows": len(materialized),
        "candidates": metrics,
        "ranking": ranking,
        "best": ranking[0],
        "log_loss_delta_vs_best_bits_per_decision": {
            key: _round(float(value["log_loss_bits_per_decision"]) - float(best["log_loss_bits_per_decision"]))
            for key, value in metrics.items()
        },
    }
# ---------------------------------------------------------------------------
# raise-sizing model report (#421 acceptance evidence)
# ---------------------------------------------------------------------------


def recover_actor_commitment(row: Mapping[str, Any]) -> float | None:
    """Recover the actor's *pre-action* street contribution of one raise row.

    The response dataset exposes the observed ``target_total_bb`` (the
    raise-to total) and ``observed_sizing_bb`` (the incremental cost of the
    action).  Their difference is the actor's own contribution *before*
    acting -- purely pre-action public state -- and is what the conservative
    minimum-raise floor needs.  Rows without an observed aggressive action
    return ``None``.
    """
    target = row.get("target_total_bb")
    incremental = row.get("observed_sizing_bb")
    if target is None or incremental is None:
        return None
    commitment = float(target) - float(incremental)
    if not math.isfinite(commitment) or commitment < -1e-9:
        return None
    return max(commitment, 0.0)


def _calibration_summary(
    pits: Sequence[float],
    coverage: Mapping[str, Sequence[int]],
) -> dict[str, Any]:
    """PIT histogram plus nominal-vs-empirical quantile coverage.

    Coverage is measured directly as ``P(observed <= predicted quantile)``: with
    boundary atoms the PIT-based shortcut ``PIT <= q`` would understate it, so
    the predicted quantiles are compared to the observations explicitly.
    """
    bins = [0] * PIT_BINS
    for value in pits:
        index = min(int(max(min(value, 1.0), 0.0) * PIT_BINS), PIT_BINS - 1)
        bins[index] += 1
    total = len(pits)
    fractions = [_round(count / total) if total else 0.0 for count in bins]
    expected = 1.0 / PIT_BINS
    max_bin_error = (
        max((abs((count / total) - expected) for count in bins), default=0.0) if total else 0.0
    )
    rows = []
    max_coverage_error = 0.0
    for level in sorted({float(level) for level in CALIBRATION_LEVELS}):
        hits, count = (coverage.get(f"{level:.2f}") or (0, 0))[:2]
        empirical = (hits / count) if count else None
        error = None if empirical is None else abs(empirical - level)
        if error is not None:
            max_coverage_error = max(max_coverage_error, error)
        rows.append(
            {
                "nominal": _round(level),
                "empirical": None if empirical is None else _round(empirical),
                "abs_error": None if error is None else _round(error),
                "n": count,
            }
        )
    return {
        "n": total,
        "pit_bins": PIT_BINS,
        "pit_histogram": fractions,
        "pit_uniform_expected_bin": _round(expected),
        "pit_max_abs_bin_error": _round(max_bin_error),
        "quantile_coverage": rows,
        "quantile_max_abs_error": _round(max_coverage_error),
        "mean_pit": _round(math.fsum(pits) / total) if total else None,
    }


def _score_sizing_rows(
    channel: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    *,
    steps: int,
    min_family_support: int,
) -> dict[str, Any]:
    """Score every observed RAISE/JAM target and generate legal sizings for it."""
    nll: list[float] = []
    crps: list[float] = []
    pits: list[float] = []
    uniform_nll: list[float] = []
    coverage: dict[str, list[int]] = {f"{level:.2f}": [0, 0] for level in CALIBRATION_LEVELS}
    generated = 0
    illegal = 0
    fail_closed = 0
    fail_closed_reasons: dict[str, int] = {}
    by_action: dict[str, dict[str, Any]] = {}
    by_family: dict[str, dict[str, Any]] = {}
    per_action_nll: dict[str, list[float]] = {action: [] for action in AGGRESSIVE_ACTIONS}

    def bump(mapping: dict[str, int], key: str) -> None:
        mapping[key] = mapping.get(key, 0) + 1

    def mean(values: Sequence[float]) -> float | None:
        return _round(math.fsum(values) / len(values)) if values else None

    for row in rows:
        action = str(row.get("action") or "").strip().upper()
        if action not in AGGRESSIVE_ACTIONS:
            continue
        target = row.get("target_total_bb")
        if target is None:
            continue
        commitment = recover_actor_commitment(row)
        distribution = raise_sizing_distribution(
            channel,
            row,
            action=action,
            config=config,
            steps=steps,
            actor_commitment_bb=commitment,
            min_family_support=min_family_support,
        )
        bucket = by_action.setdefault(
            action,
            {
                "rows": 0,
                "scored": 0,
                "fail_closed": 0,
                "generated": 0,
                "illegal_generated": 0,
                "support_levels": {},
            },
        )
        bucket["rows"] += 1
        level = distribution["support"]["support_level"]
        bucket["support_levels"][level] = bucket["support_levels"].get(level, 0) + 1
        if distribution["status"] != "RESOLVED":
            fail_closed += 1
            bucket["fail_closed"] += 1
            bump(fail_closed_reasons, str(distribution.get("fail_closed_reason")))
            continue
        score = score_raise_sizing(
            channel,
            row,
            float(target),
            action=action,
            config=config,
            steps=steps,
            actor_commitment_bb=commitment,
            distribution=distribution,
        )
        if not score.get("scored"):
            fail_closed += 1
            bucket["fail_closed"] += 1
            bump(fail_closed_reasons, str(score.get("fail_closed_reason")))
            continue
        nll.append(float(score["negative_log_likelihood_bits"]))
        per_action_nll[action].append(float(score["negative_log_likelihood_bits"]))
        uniform_nll.append(float(score["uniform_window_nll_bits"]))
        crps.append(float(score["crps_bb"]))
        pits.append(float(score["pit"]))
        quantiles = distribution.get("quantiles_bb") or {}
        for level in CALIBRATION_LEVELS:
            key = f"{float(level):.2f}"
            predicted = quantiles.get(key)
            if predicted is None:
                continue
            coverage[key][1] += 1
            if float(target) <= float(predicted) + 1e-9:
                coverage[key][0] += 1
        bucket["scored"] += 1

        generation = generate_raise_sizings(
            channel,
            row,
            action=action,
            config=config,
            steps=steps,
            actor_commitment_bb=commitment,
            distribution=distribution,
        )
        generated += generation["generated_count"]
        illegal += generation["illegal_count"]
        bucket["generated"] += generation["generated_count"]
        bucket["illegal_generated"] += generation["illegal_count"]
        family = _public_level(row.get("family"))
        entry = by_family.setdefault(family, {"scored": 0, "fail_closed": 0, "nll": [], "crps": []})
        entry["scored"] += 1
        entry["nll"].append(float(score["negative_log_likelihood_bits"]))
        entry["crps"].append(float(score["crps_bb"]))

    nll_mean = mean(nll)
    uniform_mean = mean(uniform_nll)
    return {
        "rows": sum(bucket["rows"] for bucket in by_action.values()),
        "scored": len(nll),
        "fail_closed": fail_closed,
        "fail_closed_reasons": dict(sorted(fail_closed_reasons.items())),
        "nll_bits_per_sizing": nll_mean,
        "uniform_window_nll_bits_per_sizing": uniform_mean,
        "nll_gain_vs_uniform_bits": (
            None if nll_mean is None or uniform_mean is None else _round(uniform_mean - nll_mean)
        ),
        "crps_bb": mean(crps),
        "calibration": _calibration_summary(pits, coverage),
        "generated_sizings": generated,
        "illegal_generated_sizings": illegal,
        "illegal_generated_rate": _round(illegal / generated) if generated else None,
        "per_action": {
            action: {
                "rows": bucket["rows"],
                "scored": bucket["scored"],
                "fail_closed": bucket["fail_closed"],
                "generated": bucket["generated"],
                "illegal_generated": bucket["illegal_generated"],
                "support_levels": dict(sorted(bucket["support_levels"].items())),
                "nll_bits_per_sizing": mean(per_action_nll[action]),
            }
            for action, bucket in sorted(by_action.items())
        },
        "per_family": {
            family: {
                "scored": entry["scored"],
                "fail_closed": entry["fail_closed"],
                "nll_bits_per_sizing": mean(entry["nll"]),
                "crps_bb": mean(entry["crps"]),
            }
            for family, entry in sorted(by_family.items())
        },
    }


def evaluate_raise_sizing_frontiers(
    channel: Mapping[str, Any],
    *,
    config: Mapping[str, Any] | None = None,
    steps: int = SIZING_QUADRATURE_STEPS,
    min_family_support: int = MIN_FAMILY_SIZING_SUPPORT,
    frontiers: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify each frozen #388/#419 raise-sizing frontier explicitly.

    Two independent statuses are reported per frontier:

    * ``model_status`` -- whether *this* conditional population model answers
      the sizing request with a legal, supported distribution;
    * ``exact_tree_status`` -- the frozen #388/#419 verdict, which demands an
      exactly supported raise target at the structural node and therefore
      stays ``UNRESOLVED``: the population model never claims to satisfy it.
    """
    merged = make_config(**dict(config)) if isinstance(config, Mapping) else make_config()
    source = frontiers if isinstance(frontiers, Mapping) else load_raise_sizing_frontiers()
    items: list[dict[str, Any]] = []
    resolved = 0
    fail_closed = 0
    for frontier in source.get("frontiers") or []:
        action = str(frontier.get("action") or "RAISE")
        context = reconstruct_frontier_context(frontier)
        interval = frontier.get("legal_target_interval_bb")
        query_context = dict(context)
        if interval and len(interval) == 2:
            query_context["legal_target_interval_bb"] = list(interval)
        query = raise_sizing_query(channel, query_context, action=action, config=merged, steps=steps)
        derived = raise_sizing_window(query_context, action=action, config=merged)
        window_matches = bool(
            interval
            and derived["min_raise_to_bb"] is not None
            and abs(float(derived["min_raise_to_bb"]) - float(interval[0])) <= 1e-6
            and abs(float(derived["max_raise_to_bb"]) - float(interval[1])) <= 1e-6
        )
        if query["status"] == "RESOLVED":
            model_status = "RESOLVED"
            resolved += 1
        else:
            model_status = "FAIL_CLOSED"
            fail_closed += 1
        items.append(
            {
                "node_id": frontier.get("node_id"),
                "path": frontier.get("path"),
                "action": action,
                "family": context.get("family"),
                "actor_position": context.get("actor_position"),
                "legal_target_interval_bb": interval,
                "derived_legal_window_bb": [
                    derived["min_raise_to_bb"],
                    derived["max_raise_to_bb"],
                ],
                "derived_window_matches_frozen_interval": window_matches,
                "window_bounds_source": derived["bounds_source"],
                "model_status": model_status,
                "model_status_detail": (
                    "CONDITIONAL_POPULATION_SIZING_DENSITY"
                    if model_status == "RESOLVED"
                    else "FAIL_CLOSED_NO_SUBSTITUTION"
                ),
                "model_fail_closed_reason": query.get("fail_closed_reason"),
                "support": query["support"],
                "uncertainty": query["uncertainty"],
                "quantiles_bb": query["quantiles_bb"],
                "generated_sizings_bb": query["generated_sizings_bb"],
                "illegal_generated": query["illegal_count"],
                "nearest_price_substituted": False,
                "nearest_context_substituted": False,
                "exact_tree_status": frontier.get("exact_tree_status"),
                "exact_tree_satisfied": False,
                "exact_tree_blocks_required_tree_complete": bool(
                    frontier.get("blocks_required_tree_complete", True)
                ),
                "frozen_blocker_reason_code": frontier.get("blocker_reason_code"),
                "exact_support": frontier.get("exact_support"),
                "context_reconstruction": context.get("context_reconstruction"),
            }
        )
    return {
        "total": len(items),
        "resolved": resolved,
        "fail_closed": fail_closed,
        "classification_rule": (
            "model_status=RESOLVED means this conditional population sizing model answers the "
            "request with a legal, supported target window and never substitutes a nearest "
            "price; exact_tree_status is the independent frozen #388/#419 verdict and stays "
            "UNRESOLVED because no exactly supported per-node raise sizing statistic exists"
        ),
        "exact_tree_unresolved": sum(
            1 for item in items if item["exact_tree_status"] == "UNRESOLVED"
        ),
        "no_nearest_price_substituted": all(
            not item["nearest_price_substituted"]
            and not (item["exact_support"] or {}).get("nearest_price_substituted", False)
            for item in items
        ),
        "source": source.get("frontier_source"),
        "exact_tree_source": source.get("exact_tree_source"),
        "items": items,
    }


def raise_sizing_report(
    rows: Iterable[Mapping[str, Any]],
    *,
    config: Mapping[str, Any] | None = None,
    channel: Mapping[str, Any] | None = None,
    seed: int = 421,
    dataset_path: str | Path | None = None,
    frontier_path: str | Path = FRONTIER_RESOLUTION_PATH,
    exact_tree_path: str | Path = EXACT_TREE_PATH,
    steps: int = SIZING_QUADRATURE_STEPS,
    min_family_support: int = MIN_FAMILY_SIZING_SUPPORT,
    metrics_split: str | None = None,
) -> dict[str, Any]:
    """Build the #421 conditional raise-sizing report.

    The report carries the probabilistic metric (NLL in bits and CRPS in bb),
    the quantile calibration, the illegal-generation rate and the explicit
    status of each frozen #388/#419 raise-sizing frontier.
    """
    merged = make_config(**dict(config)) if isinstance(config, Mapping) else make_config()
    materialized = [dict(row) for row in rows]
    fitted = (
        channel
        if channel is not None
        else fit_sizing_channel(materialized, merged, min_family_support=min_family_support)
    )
    split = str(metrics_split or "").strip().upper()
    scoped = [row for row in materialized if not split or _row_split(row) == split]
    metrics = _score_sizing_rows(
        fitted, scoped, merged, steps=steps, min_family_support=min_family_support
    )
    frontiers = evaluate_raise_sizing_frontiers(
        fitted,
        config=merged,
        steps=steps,
        min_family_support=min_family_support,
        frontiers=load_raise_sizing_frontiers(frontier_path, exact_tree_path),
    )
    report: dict[str, Any] = {
        "schema": RAISE_SIZING_REPORT_SCHEMA,
        "seed": int(seed),
        "config": {
            "sizing_smoothing_mass": merged["sizing_smoothing_mass"],
            "sizing_axis_knots": merged["sizing_axis_knots"],
            "default_target_to_pot_ratio": merged["default_target_to_pot_ratio"],
        },
        "sizing_model": {
            "basis": "piecewise_linear_log1p_partition_of_unity_restricted_to_the_legal_window",
            "target_axis": "target_total_bb divided by (pot_before_bb + to_call_bb)",
            "window_rule": (
                "min_raise_to = max(2*current_bet - max(commitment, BB), current_bet + BB), a "
                "conservative upper bound of the engine minimum raise; cap = max_raise_to_bb "
                "when supplied else effective_stack_bb"
            ),
            "generation": "deterministic_quantile_grid_of_the_truncated_density",
            "no_nearest_price": True,
            "no_nearest_context": True,
            "quadrature_steps": int(steps),
            "min_family_support": int(min_family_support),
            "sizing_quantile_levels": list(SIZING_QUANTILE_LEVELS),
            "generation_quantile_levels": list(SIZING_GENERATION_QUANTILES),
            "boundary_mass": dict((fitted.get("boundary") or {}).get("global") or {}),
            "boundary_mass_source": (
                "fit_sizing_channel: measured atoms at the minimum raise and the all-in cap"
                if isinstance(fitted.get("boundary"), Mapping)
                else "unavailable"
            ),
        },
        "notes": [
            "Every request is evaluated on a conservative sub-window of the engine's legal "
            "raise interval: the minimum-raise floor is a proven upper bound of the engine "
            "minimum and the cap never exceeds max_raise_to_bb / effective_stack_bb.",
            "A statistic that is absent inside the legal window fails closed: no nearest "
            "price and no nearest public context is ever substituted.",
            "The quantile-coverage steps come from the measured boundary atoms: a large share "
            "of observed raises sits exactly at the minimum raise, so predicted low quantiles "
            "collapse onto that atom and coverage is conservative rather than nominal there.",
            "The seven frozen #388/#419 frontiers are reported twice: model_status describes "
            "this conditional population model, exact_tree_status keeps the frozen exact-node "
            "verdict (UNRESOLVED) and exact_tree_satisfied is false.",
        ],
        "metrics_split": split or None,
        "rows_consumed": len(scoped),
        "metrics": metrics,
        "frontiers": frontiers,
        "guarantees": {
            "generated_sizings_always_legal": metrics["illegal_generated_sizings"] == 0,
            "no_nearest_price_substitution": True,
            "support_exposed_per_request": True,
            "uncertainty_exposed_per_request": True,
            "fail_closed_instead_of_substitution": True,
            "frontiers_classified": frontiers["total"] == 7,
            "frontiers_resolved": frontiers["resolved"],
            "frontiers_fail_closed": frontiers["fail_closed"],
            "frontiers_exact_tree_unresolved": frontiers["exact_tree_unresolved"],
        },
        "provenance": {
            "module_sha256": _sha256_file(Path(__file__)),
            "frontier_resolution": frontiers.get("source"),
            "exact_tree": frontiers.get("exact_tree_source"),
        },
    }
    if dataset_path is not None:
        resolved = Path(dataset_path)
        if resolved.exists():
            label = str(resolved)
            try:
                label = str(resolved.relative_to(ROOT))
            except ValueError:
                label = str(resolved)
            report["provenance"]["dataset"] = label
            report["provenance"]["dataset_sha256"] = _sha256_file(resolved)
    return report


def write_raise_sizing_report(
    report: Mapping[str, Any], path: str | Path = DEFAULT_SIZING_REPORT_PATH
) -> dict[str, Any]:
    """Persist the report byte-reproducibly and return its identity metadata."""
    target = Path(path)
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    target.write_text(payload, encoding="utf-8")
    return {
        "path": str(target),
        "sha256": sha256_bytes(payload.encode("utf-8")),
        "bytes": len(payload.encode("utf-8")),
        "schema": report.get("schema"),
    }


# ---------------------------------------------------------------------------
# OOD / uncertainty gate (T6, #421)
#
# ``predict`` always answers; the gate is the *independent*, machine-readable
# verdict that says whether that answer may be used.  It combines four signal
# families into exactly one status:
#
# 1. never-seen categories -- a single-feature node label the calibration never
#    observed (``UNSEEN_CATEGORY``);
# 2. extrapolation -- a queried sizing / stack (or price) outside the calibrated
#    TRAIN domain (``EXTRAPOLATION_SIZING`` / ``EXTRAPOLATION_STACK`` /
#    ``EXTRAPOLATION_PRICE``);
# 3. density / local support -- a rare feature label, an exact context cell
#    never observed in TRAIN, a robust distance past the TRAIN core or a value
#    past the model's outermost spline knot (``LOW_FEATURE_SUPPORT`` /
#    ``LOW_EXACT_CONTEXT_SUPPORT`` / ``DOMAIN_DISTANCE`` /
#    ``SPLINE_BOUNDARY_EXTRAPOLATION``);
# 4. predictive uncertainty -- the normalized entropy of the model's legal
#    distribution and the fitted node support the prediction actually used
#    (``HIGH_PREDICTIVE_ENTROPY`` / ``LOW_MODEL_NODE_SUPPORT``).
#
# Only (1) and (2) can produce an abstention.  An exact context that was never
# observed while every one of its single-feature labels *was* observed is **not**
# OOD by definition: the exact-cell support is reported, and it can raise the
# status to ``MODEL_SUPPORTED_HIGH_UNCERTAINTY``, but it never produces
# ``MODEL_OOD_ABSTAIN``.
#
# The thresholds are calibrated on TRAIN only, through a hand-grouped
# cross-validation of the TRAIN rows (never VALIDATION, never TEST); the report
# records ``validation_consumed=false`` / ``test_consumed=false`` and the
# calibration refuses to consume any other split.
# ---------------------------------------------------------------------------

OOD_GATE_SCHEMA = "poker-generalized-response-ood-gate/v1"
OOD_CALIBRATION_SCHEMA = "poker-generalized-response-ood-calibration/v1"
OOD_REPORT_SCHEMA = "poker-generalized-response-ood-calibration-report/v1"
OOD_CONTRACT_PATH = ROOT / "contracts/training/generalized-response-ood-gate.schema.json"
DEFAULT_OOD_REPORT_PATH = ROOT / "analysis/issue421_generalized_response/OOD_CALIBRATION_REPORT.json"

#: The three stable, machine-readable statuses of the gate.
STATUS_MODEL_SUPPORTED = "MODEL_SUPPORTED"
STATUS_MODEL_SUPPORTED_HIGH_UNCERTAINTY = "MODEL_SUPPORTED_HIGH_UNCERTAINTY"
STATUS_MODEL_OOD_ABSTAIN = "MODEL_OOD_ABSTAIN"
OOD_STATUSES: tuple[str, ...] = (
    STATUS_MODEL_SUPPORTED,
    STATUS_MODEL_SUPPORTED_HIGH_UNCERTAINTY,
    STATUS_MODEL_OOD_ABSTAIN,
)
OOD_STATUS_DEFINITIONS: dict[str, str] = {
    STATUS_MODEL_SUPPORTED: (
        "the context is inside the calibrated TRAIN domain, every category was observed, the "
        "local support is above the calibrated floor and the predictive uncertainty is below the "
        "calibrated ceiling: the answer may be used as a supported model output"
    ),
    STATUS_MODEL_SUPPORTED_HIGH_UNCERTAINTY: (
        "the context stays inside the calibrated TRAIN domain and no category is unseen, but at "
        "least one uncertainty signal is in its calibrated tail (rare feature label, exact cell "
        "never observed in TRAIN, robust domain distance, spline-knot boundary, high predictive "
        "entropy or low fitted node support): the answer is still emitted, but it must be "
        "reported as a high-uncertainty output"
    ),
    STATUS_MODEL_OOD_ABSTAIN: (
        "the context is out of the calibrated distribution: a never-observed category or a "
        "queried sizing / stack / price outside the calibrated TRAIN domain. The gate abstains "
        "and no model answer may be used"
    ),
}

#: Deterministic review order of the reason codes.
OOD_REASON_ORDER: tuple[str, ...] = (
    "UNSEEN_CATEGORY",
    "EXTRAPOLATION_STACK",
    "EXTRAPOLATION_SIZING",
    "EXTRAPOLATION_PRICE",
    "MISSING_DOMAIN_AXIS",
    "SPLINE_BOUNDARY_EXTRAPOLATION",
    "DOMAIN_DISTANCE",
    "LOW_FEATURE_SUPPORT",
    "LOW_EXACT_CONTEXT_SUPPORT",
    "HIGH_PREDICTIVE_ENTROPY",
    "LOW_MODEL_NODE_SUPPORT",
    "PREDICTIVE_UNCERTAINTY_UNAVAILABLE",
)
#: Reason codes that abstain; every other reason only raises the uncertainty.
OOD_HARD_REASONS: tuple[str, ...] = (
    "UNSEEN_CATEGORY",
    "EXTRAPOLATION_STACK",
    "EXTRAPOLATION_SIZING",
    "EXTRAPOLATION_PRICE",
    "MISSING_DOMAIN_AXIS",
)
OOD_SOFT_REASONS: tuple[str, ...] = tuple(
    reason for reason in OOD_REASON_ORDER if reason not in OOD_HARD_REASONS
)

#: Single-feature node labels deciding the in-domain / never-seen-category
#: surface: the seven categorical blocks of the model plus the two coarse
#: buckets the interaction blocks already index plus one pot bucket.
OOD_FEATURE_BLOCKS: tuple[str, ...] = CATEGORICAL_BLOCKS + (
    "to_call_bucket",
    "effective_stack_bucket",
    "pot_bucket",
)
OOD_POT_BUCKET_EDGES: tuple[float, ...] = (2.5, 6.0, 15.0, 40.0)
OOD_COARSE_SOURCE: dict[str, str] = {
    "to_call_bucket": "to_call_bb",
    "effective_stack_bucket": "effective_stack_bb",
}
OOD_PRICE_AXES: tuple[str, ...] = ("to_call_bb", "pot_before_bb", "effective_stack_bb")
OOD_SIZING_AXIS = "sizing_ratio"
OOD_NUMERIC_AXES: tuple[str, ...] = OOD_PRICE_AXES + (OOD_SIZING_AXIS,)
#: Hard extrapolation reason of each numeric axis.
OOD_AXIS_EXTRAPOLATION_REASON: dict[str, str] = {
    "to_call_bb": "EXTRAPOLATION_PRICE",
    "pot_before_bb": "EXTRAPOLATION_PRICE",
    "effective_stack_bb": "EXTRAPOLATION_STACK",
    OOD_SIZING_AXIS: "EXTRAPOLATION_SIZING",
}

#: Strata of the out-of-fold gate evaluation.
OOD_STRATUM_FREQUENT_EXACT = "frequent_exact"
OOD_STRATUM_RARE_EXACT = "rare_exact"
OOD_STRATUM_EXACT_ABSENT_IN_DOMAIN = "exact_absent_in_domain"
OOD_STRATUM_EXACT_ABSENT_OUT_OF_DOMAIN = "exact_absent_out_of_domain"
OOD_STRATA: tuple[str, ...] = (
    OOD_STRATUM_FREQUENT_EXACT,
    OOD_STRATUM_RARE_EXACT,
    OOD_STRATUM_EXACT_ABSENT_IN_DOMAIN,
    OOD_STRATUM_EXACT_ABSENT_OUT_OF_DOMAIN,
)
OOD_FREQUENT_EXACT_MIN_SUPPORT = 20

#: Calibration protocol.
OOD_CALIBRATION_SEED = 421
OOD_CALIBRATION_FOLDS = 5
OOD_CALIBRATION_MAX_ROWS = 24000
OOD_CALIBRATION_TUNING_ROWS = 3000
#: Tail quantiles of the TRAIN-only out-of-fold signal distributions.
OOD_HIGH_TAIL = 0.95
OOD_LOW_TAIL = 0.05
#: Documented, deterministic fallbacks when a signal array is empty.  The three
#: density signals are expressed as *shares* of the calibration rows so a
#: threshold calibrated on a cross-validation fold stays comparable with a
#: frozen calibration built from the whole TRAIN split.
OOD_FALLBACK_THRESHOLDS: dict[str, float] = {
    "min_feature_share": 0.0,
    "min_exact_context_share": 0.0,
    "min_model_node_support_per_row": 0.0,
    "normalized_entropy": 0.9,
    "domain_distance": 1.0,
    "extrapolation_margin": 0.0,
}


def _ood_pot_bucket(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return MISSING
    if not math.isfinite(number):
        return MISSING
    axis = [_transform(edge) for edge in OOD_POT_BUCKET_EDGES]
    return f"P{bisect.bisect_right(axis, _transform(number))}"


def ood_feature_levels(context: Mapping[str, Any]) -> dict[str, str]:
    """One node label per single-feature block (the gate's in-domain surface).

    The surface is the seven categorical blocks of the model plus the two coarse
    buckets the model's interaction blocks already index -- evaluated on the
    model's own ``log1p`` edges, so a label here is a node label the model really
    uses -- plus one documented pot bucket.  The bucket values match the T4
    cross-validation surface; the T4 report buckets on the raw axis, this gate on
    the model's transformed axis.
    """
    levels = {block: categorical_node(block, context) for block in CATEGORICAL_BLOCKS}
    for block, source in OOD_COARSE_SOURCE.items():
        levels[block] = _coarse_bucket(block, context.get(source))
    levels["pot_bucket"] = _ood_pot_bucket(context.get("pot_before_bb"))
    return levels


def ood_exact_context_key(context: Mapping[str, Any]) -> str:
    """Exact context signature: the ordered single-feature node labels."""
    levels = ood_feature_levels(context)
    return "|".join(levels[block] for block in OOD_FEATURE_BLOCKS)


def _ood_axis_values(context: Mapping[str, Any]) -> dict[str, float | None]:
    """Queried numeric axes; ``sizing_ratio`` is ``None`` when no target is asked."""

    def number(field: str) -> float | None:
        raw = context.get(field)
        if raw is None:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    values: dict[str, float | None] = {axis: number(axis) for axis in OOD_PRICE_AXES}
    target = context.get("target_total_bb")
    if target is None:
        target = context.get("raise_target_total_bb")
    ratio: float | None = None
    if target is not None:
        target_value = number("target_total_bb")
        if target_value is None:
            target_value = number("raise_target_total_bb")
        to_call, pot = values["to_call_bb"], values["pot_before_bb"]
        if target_value is not None and to_call is not None and pot is not None:
            denominator = pot + to_call
            if denominator > EPS:
                ratio = min(max(target_value, 0.0) / denominator, MAX_SIZING_RATIO)
    values[OOD_SIZING_AXIS] = ratio
    return values


def _ood_spline_knot_max(axis: str, config: Mapping[str, Any]) -> float | None:
    if axis == OOD_SIZING_AXIS:
        knots = [float(value) for value in config["sizing_axis_knots"]]
    elif axis in config["spline_knots"]:
        knots = [float(value) for value in config["spline_knots"][axis]]
    else:
        return None
    return max(knots) if knots else None


def _quantile(sorted_values: Sequence[float], level: float) -> float | None:
    """Linear-interpolation quantile of an already sorted sequence."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * min(max(float(level), 0.0), 1.0)
    low = int(math.floor(position))
    high = min(low + 1, len(sorted_values) - 1)
    weight = position - low
    return float(sorted_values[low]) * (1.0 - weight) + float(sorted_values[high]) * weight


def _assert_ood_train_only(rows: Iterable[Mapping[str, Any]]) -> None:
    """The gate calibrates on TRAIN only; any other split fails closed."""
    for row in rows:
        split = _row_split(row)
        if split != "TRAIN":
            raise GeneralizedResponseModelError(
                "the OOD gate calibrates on TRAIN only; refused a "
                f"{split or '<EMPTY>'} row (VALIDATION and TEST are never consumed)"
            )


def _ood_domain_stats(
    rows: Sequence[Mapping[str, Any]], config: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """TRAIN envelope + robust core + spline boundary of every numeric axis."""
    observed: dict[str, list[float]] = {axis: [] for axis in OOD_NUMERIC_AXES}
    for row in rows:
        values = _ood_axis_values(row)
        for axis in OOD_NUMERIC_AXES:
            value = values.get(axis)
            if value is not None:
                observed[axis].append(float(value))
    domain: dict[str, dict[str, Any]] = {}
    for axis in OOD_NUMERIC_AXES:
        values = sorted(observed[axis])
        domain[axis] = {
            "observations": len(values),
            "trained_min": _round(values[0]) if values else None,
            "trained_max": _round(values[-1]) if values else None,
            "core_low": _round(_quantile(values, OOD_LOW_TAIL)),
            "core_high": _round(_quantile(values, OOD_HIGH_TAIL)),
            "spline_knot_max": _round(_ood_spline_knot_max(axis, config)),
        }
    return domain


def _ood_category_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {block: {} for block in OOD_FEATURE_BLOCKS}
    for row in rows:
        for block, label in ood_feature_levels(row).items():
            counts[block][label] = counts[block].get(label, 0) + 1
    return counts


def _ood_exact_context_support(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    support: dict[str, int] = {}
    for row in rows:
        key = ood_exact_context_key(row)
        support[key] = support.get(key, 0) + 1
    return support


def _ood_axis_distance(value: float, stats: Mapping[str, Any]) -> float:
    """Robust excursion past the TRAIN core, in core widths (0 inside the core)."""
    core_low, core_high = stats.get("core_low"), stats.get("core_high")
    if core_low is None or core_high is None:
        return 0.0
    core_low, core_high = float(core_low), float(core_high)
    scale = core_high - core_low
    if scale <= EPS:
        return 0.0
    if value < core_low:
        return (core_low - value) / scale
    if value > core_high:
        return (value - core_high) / scale
    return 0.0


def _candidate_of(model: Any) -> Mapping[str, Any] | None:
    """Accept a candidate mapping, a ``ResponseModel`` wrapper, or ``None``."""
    if model is None:
        return None
    candidate = getattr(model, "candidate", None)
    if candidate is not None:
        return candidate
    if isinstance(model, Mapping):
        return model
    raise GeneralizedResponseModelError(
        "the OOD gate needs a fitted candidate, a ResponseModel, or None"
    )


def _ood_evaluate(
    calibration: Mapping[str, Any],
    model: Any,
    context: Mapping[str, Any],
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Raw signal bundle of one context: hard reasons, soft reasons, signals."""
    del config  # the frozen calibration carries every statistic the gate needs
    if not isinstance(context, Mapping):
        raise TypeError("context must be a mapping")
    thresholds = dict(calibration["thresholds"])
    margin = float(thresholds.get("extrapolation_margin") or 0.0)

    levels = ood_feature_levels(context)
    category_counts = calibration["category_counts"]
    unseen = sorted(
        block for block, label in levels.items() if label not in set(category_counts.get(block) or {})
    )
    total_rows = max(int((calibration.get("provenance") or {}).get("rows") or 0), 0)
    if total_rows <= 0:
        total_rows = max(
            [sum(counts.values()) for counts in category_counts.values()] or [0]
        )
    feature_support = {
        block: int((category_counts.get(block) or {}).get(levels[block], 0))
        for block in OOD_FEATURE_BLOCKS
    }
    feature_share = {
        block: (count / total_rows if total_rows > 0 else 0.0)
        for block, count in feature_support.items()
    }
    min_block = min(feature_support, key=lambda block: (feature_support[block], block))

    query = _ood_axis_values(context)
    axes: dict[str, dict[str, Any]] = {}
    domain_distance = 0.0
    for axis in OOD_NUMERIC_AXES:
        stats = dict(calibration["domain"].get(axis) or {})
        value = query.get(axis)
        entry: dict[str, Any] = {
            "queried": value is not None,
            "value": _round(value),
            "trained_min": stats.get("trained_min"),
            "trained_max": stats.get("trained_max"),
            "core_low": stats.get("core_low"),
            "core_high": stats.get("core_high"),
            "spline_knot_max": stats.get("spline_knot_max"),
            "extrapolation": False,
            "spline_boundary": False,
            "domain_distance": 0.0,
        }
        if value is not None:
            low, high = stats.get("trained_min"), stats.get("trained_max")
            if low is not None and float(value) < float(low) - margin - 1e-9:
                entry["extrapolation"] = True
            elif high is not None and float(value) > float(high) + margin + 1e-9:
                entry["extrapolation"] = True
            knot = stats.get("spline_knot_max")
            if knot is not None and float(value) > float(knot) + 1e-9:
                entry["spline_boundary"] = True
            entry["domain_distance"] = _round(_ood_axis_distance(float(value), stats), 9)
            domain_distance = max(domain_distance, float(entry["domain_distance"] or 0.0))
        axes[axis] = entry

    hard: set[str] = set()
    soft: set[str] = set()
    if unseen:
        hard.add("UNSEEN_CATEGORY")
    for axis, entry in axes.items():
        if entry["queried"] and entry["extrapolation"]:
            hard.add(OOD_AXIS_EXTRAPOLATION_REASON[axis])
        if entry["queried"] and entry["spline_boundary"]:
            soft.add("SPLINE_BOUNDARY_EXTRAPOLATION")
        if axis != OOD_SIZING_AXIS and not entry["queried"]:
            hard.add("MISSING_DOMAIN_AXIS")
    if domain_distance > float(thresholds.get("domain_distance") or 0.0):
        soft.add("DOMAIN_DISTANCE")
    if feature_share[min_block] < float(thresholds.get("min_feature_share") or 0.0):
        soft.add("LOW_FEATURE_SUPPORT")

    signature = ood_exact_context_key(context)
    exact_support = int((calibration.get("exact_context_support") or {}).get(signature, 0))
    exact_share = exact_support / total_rows if total_rows > 0 else 0.0
    if exact_share < float(thresholds.get("min_exact_context_share") or 0.0):
        # Deliberately a *soft* signal: an exact context absent from TRAIN is
        # never OOD by itself, it only lowers the confidence of the answer.
        soft.add("LOW_EXACT_CONTEXT_SUPPORT")

    candidate = _candidate_of(model)
    predictive: dict[str, Any] | None = None
    if candidate is None:
        soft.add("PREDICTIVE_UNCERTAINTY_UNAVAILABLE")
    else:
        response = predict(candidate, context)
        probabilities = response["probabilities"]
        positive = [value for value in probabilities.values() if value > 0.0]
        entropy = -math.fsum(value * math.log(value) for value in positive)
        normalized = entropy / math.log(len(positive)) if len(positive) > 1 else 0.0
        ordered = sorted(probabilities.values(), reverse=True)
        fit_rows = int((candidate.get("fit_summary") or {}).get("rows") or 0)
        node_support_per_row = (
            int(response["support"]) / fit_rows if fit_rows > 0 else 0.0
        )
        predictive = {
            "legal_actions": response["legal_actions"],
            "normalized_entropy": _round(normalized, 9),
            "max_probability": _round(max(probabilities.values()), 9),
            "probability_margin": _round(
                ordered[0] - ordered[1] if len(ordered) > 1 else ordered[0], 9
            ),
            "model_node_support": int(response["support"]),
            "model_node_support_per_row": _round(node_support_per_row, 12),
            "fit_rows": fit_rows,
        }
        if normalized >= float(thresholds.get("normalized_entropy") or 0.0):
            soft.add("HIGH_PREDICTIVE_ENTROPY")
        if node_support_per_row < float(thresholds.get("min_model_node_support_per_row") or 0.0):
            soft.add("LOW_MODEL_NODE_SUPPORT")

    def ordered_reasons(reasons: set[str]) -> list[str]:
        return [reason for reason in OOD_REASON_ORDER if reason in reasons]

    return {
        "hard_reasons": ordered_reasons(hard),
        "soft_reasons": ordered_reasons(soft),
        "signals": {
            "feature_levels": levels,
            "unseen_categories": {block: levels[block] for block in unseen},
            "axes": axes,
            "domain_distance": _round(domain_distance, 9),
            "local_support": {
                "feature_support": feature_support,
                "feature_share": {block: _round(value, 12) for block, value in feature_share.items()},
                "min_feature_block": min_block,
                "min_feature_support": feature_support[min_block],
                "min_feature_share": _round(feature_share[min_block], 12),
                "min_feature_share_threshold": _round(
                    float(thresholds.get("min_feature_share") or 0.0), 12
                ),
            },
            "exact_context": {
                "signature": signature,
                "support": exact_support,
                "share": _round(exact_share, 12),
                "seen_in_calibration": exact_support > 0,
                "min_share_threshold": _round(
                    float(thresholds.get("min_exact_context_share") or 0.0), 12
                ),
                "decisive": False,
                "rule": (
                    "an exact context absent from TRAIN while every single-feature label is "
                    "in-domain is not OOD by definition: this field is reported, never treated "
                    "as an abstention cause"
                ),
            },
            "predictive_uncertainty": predictive,
        },
    }


def ood_gate_decision(
    model: Any,
    context: Mapping[str, Any],
    *,
    calibration: Mapping[str, Any] | None = None,
    report_path: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Frozen OOD / uncertainty verdict of one public context.

    ``model`` may be a fitted candidate, a :class:`ResponseModel` or ``None``
    (then the predictive-uncertainty family is reported as unavailable and the
    status can never be ``MODEL_SUPPORTED``).  ``calibration`` is the frozen
    calibration document; when omitted it is loaded from ``report_path`` (by
    default :data:`DEFAULT_OOD_REPORT_PATH`).
    """
    resolved = calibration if calibration is not None else load_ood_calibration(report_path)
    evaluation = _ood_evaluate(resolved, model, context, config=config)
    hard, soft = evaluation["hard_reasons"], evaluation["soft_reasons"]
    if hard:
        status = STATUS_MODEL_OOD_ABSTAIN
    elif soft:
        status = STATUS_MODEL_SUPPORTED_HIGH_UNCERTAINTY
    else:
        status = STATUS_MODEL_SUPPORTED
    return {
        "schema": OOD_GATE_SCHEMA,
        "status": status,
        "supported": status != STATUS_MODEL_OOD_ABSTAIN,
        "abstain": status == STATUS_MODEL_OOD_ABSTAIN,
        "high_uncertainty": status == STATUS_MODEL_SUPPORTED_HIGH_UNCERTAINTY,
        "decided_by": "frozen_combination_of_domain_signals",
        "reasons": hard + soft,
        "hard_reasons": hard,
        "soft_reasons": soft,
        "status_definition": OOD_STATUS_DEFINITIONS[status],
        "signals": evaluation["signals"],
        "thresholds": dict(resolved["thresholds"]),
        "calibration": {
            "schema": resolved.get("schema"),
            "canonical_payload_sha256": resolved.get("canonical_payload_sha256"),
            "consumed_splits": list((resolved.get("provenance") or {}).get("consumed_splits") or []),
        },
        "validation_consumed": False,
        "test_consumed": False,
    }


def _ood_probe_context(row: Mapping[str, Any], **overrides: Any) -> dict[str, Any]:
    probe = dict(row)
    probe["split"] = "TRAIN"
    probe.update(overrides)
    return probe


def _ood_novel_in_domain_probe(
    rows: Sequence[Mapping[str, Any]],
    category_counts: Mapping[str, Mapping[str, int]],
    exact_context_support: Mapping[str, int],
) -> dict[str, Any] | None:
    """Deterministic context whose labels are all known but whose exact cell never was."""
    known = {block: set(counts) for block, counts in category_counts.items()}
    materialized = list(rows)
    outer = materialized[:512]
    stride = max(1, len(materialized) // 512)
    inner = materialized[::stride]
    for left in outer:
        for right in inner:
            candidate = dict(left)
            for field in OOD_PRICE_AXES:
                candidate[field] = right.get(field)
            candidate["target_total_bb"] = None
            candidate["observed_sizing_bb"] = None
            levels = ood_feature_levels(candidate)
            if any(levels[block] not in known[block] for block in OOD_FEATURE_BLOCKS):
                continue
            if exact_context_support.get(ood_exact_context_key(candidate), 0) == 0:
                return candidate
    return None


def _ood_fold_of(identity: str, seed: int, folds: int) -> int:
    return int(stable_hash(f"grm-ood/{int(seed)}/{identity}")[:8], 16) % int(folds)


def _ood_status_counts(statuses: Sequence[str]) -> dict[str, Any]:
    counts = {status: 0 for status in OOD_STATUSES}
    for status in statuses:
        counts[status] += 1
    total = len(statuses)
    return {
        "n": total,
        "counts": counts,
        "shares": {
            status: (_round(count / total) if total else None) for status, count in counts.items()
        },
    }


def _ood_stratum(exact_support: int, feature_in_domain: bool) -> str:
    if exact_support >= OOD_FREQUENT_EXACT_MIN_SUPPORT:
        return OOD_STRATUM_FREQUENT_EXACT
    if exact_support > 0:
        return OOD_STRATUM_RARE_EXACT
    return OOD_STRATUM_EXACT_ABSENT_IN_DOMAIN if feature_in_domain else OOD_STRATUM_EXACT_ABSENT_OUT_OF_DOMAIN


def _ood_sample_rows(
    rows: Sequence[Mapping[str, Any]], seed: int, folds: int, max_rows: int
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]], int]:
    total = len(rows)
    stride = max(1, total // max(int(max_rows), 1))
    sample = list(rows)[::stride][: int(max_rows)]
    folds = max(int(folds), 2)
    buckets: dict[int, list[dict[str, Any]]] = {index: [] for index in range(folds)}
    for index, row in enumerate(sample):
        buckets[_ood_fold_of(_row_identity(row, index), seed, folds)].append(row)
    return sample, buckets, stride


def _ood_calibrate_thresholds(
    rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    *,
    seed: int,
    folds: int,
    max_rows: int,
    tuning_max_rows: int,
    architectures: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Hand-grouped TRAIN-only cross-validation of the gate signal distributions.

    Each fold refits the model on the fit-fold rows and evaluates the *fit-fold*
    calibration on the held-out rows, so both the predictions and the domain
    statistics behind them are genuinely out of fold.  The thresholds are then
    read off the pooled out-of-fold TRAIN signal distributions.
    """
    folds = max(int(folds), 2)
    sample, buckets, stride = _ood_sample_rows(rows, seed, folds, max_rows)
    records: list[dict[str, Any]] = []
    fold_summaries: list[dict[str, Any]] = []
    for fold_index in range(folds):
        holdout = buckets[fold_index]
        fit_rows = [row for index, bucket in buckets.items() if index != fold_index for row in bucket]
        if not holdout or not fit_rows:
            fold_summaries.append(
                {"fold": fold_index, "fit_rows": len(fit_rows), "holdout_rows": len(holdout), "skipped": True}
            )
            continue
        fit_support = _ood_exact_context_support(fit_rows)
        fold_calibration = {
            "schema": OOD_CALIBRATION_SCHEMA,
            "domain": _ood_domain_stats(fit_rows, config),
            "category_counts": _ood_category_counts(fit_rows),
            "exact_context_support": fit_support,
            "thresholds": {**OOD_FALLBACK_THRESHOLDS, "domain_distance": float("inf")},
            "provenance": {
                "consumed_splits": ["TRAIN"],
                "rows": len(fit_rows),
                "validation_consumed": False,
                "test_consumed": False,
            },
        }
        models = [
            fit(
                fit_rows,
                seed,
                architecture=architecture,
                config=make_config(tuning_max_rows=tuning_max_rows),
            )
            for architecture in architectures
        ]
        for row in holdout:
            for architecture, candidate in zip(architectures, models):
                evaluation = _ood_evaluate(fold_calibration, candidate, row)
                signals = evaluation["signals"]
                records.append(
                    {
                        "architecture": architecture,
                        "fold": fold_index,
                        "stratum": _ood_stratum(
                            int(signals["exact_context"]["support"]),
                            not signals["unseen_categories"],
                        ),
                        "hard_reasons": list(evaluation["hard_reasons"]),
                        "signals": {
                            "normalized_entropy": signals["predictive_uncertainty"]["normalized_entropy"],
                            "model_node_support_per_row": signals["predictive_uncertainty"][
                                "model_node_support_per_row"
                            ],
                            "min_feature_share": signals["local_support"]["min_feature_share"],
                            "exact_context_share": signals["exact_context"]["share"],
                            "domain_distance": signals["domain_distance"],
                        },
                    }
                )
        fold_summaries.append(
            {
                "fold": fold_index,
                "fit_rows": len(fit_rows),
                "holdout_rows": len(holdout),
                "skipped": False,
                "fit_exact_contexts": len(fit_support),
            }
        )

    # Thresholds are read off the rows that are in-domain for their own fit fold
    # only: the tails must describe supported decisions, not the abstentions.
    in_domain = [record for record in records if not record["hard_reasons"]]
    signal_keys = (
        "normalized_entropy",
        "model_node_support_per_row",
        "min_feature_share",
        "exact_context_share",
        "domain_distance",
    )
    observed: dict[str, list[float]] = {
        key: sorted(
            float(record["signals"][key])
            for record in in_domain
            if record["signals"][key] is not None
        )
        for key in signal_keys
    }

    def tail(key: str, level: float) -> float:
        values = observed[key]
        if not values:
            return float(OOD_FALLBACK_THRESHOLDS[key])
        return float(_quantile(values, level))

    thresholds = {
        "min_feature_share": _round(tail("min_feature_share", OOD_LOW_TAIL), 12),
        "min_exact_context_share": _round(tail("exact_context_share", OOD_LOW_TAIL), 12),
        "min_model_node_support_per_row": _round(
            tail("model_node_support_per_row", OOD_LOW_TAIL), 12
        ),
        "normalized_entropy": _round(tail("normalized_entropy", OOD_HIGH_TAIL), 9),
        "domain_distance": _round(tail("domain_distance", OOD_HIGH_TAIL), 9),
        "extrapolation_margin": float(OOD_FALLBACK_THRESHOLDS["extrapolation_margin"]),
    }
    evidence = {
        "protocol": {
            "kind": "train_only_hand_grouped_cross_validation",
            "consumed_splits": ["TRAIN"],
            "validation_consumed": False,
            "test_consumed": False,
            "fold_assignment": f"int(stable_hash('grm-ood/{int(seed)}/<hand_id>')[:8], 16) % {folds}",
            "group_key": "hand_id",
            "folds": folds,
            "seed": int(seed),
            "architectures": list(architectures),
            "sample_rows": len(sample),
            "stride": stride,
            "high_tail": OOD_HIGH_TAIL,
            "low_tail": OOD_LOW_TAIL,
            "threshold_rule": (
                "soft thresholds are read off the pooled out-of-fold TRAIN signal distributions of "
                "the rows that are in-domain for their own fit fold: high tail (95th percentile) "
                "for the normalized entropy and the robust domain distance, low tail (5th "
                "percentile) for the feature-, exact-context- and fitted-node-support share floors"
            ),
        },
        "folds": fold_summaries,
        "records": len(records),
        "signal_quantiles": {
            key: {
                "n": len(observed[key]),
                "min": _round(_quantile(observed[key], 0.0), 12),
                "p05": _round(_quantile(observed[key], OOD_LOW_TAIL), 12),
                "median": _round(_quantile(observed[key], 0.5), 12),
                "p95": _round(_quantile(observed[key], OOD_HIGH_TAIL), 12),
                "max": _round(_quantile(observed[key], 1.0), 12),
            }
            for key in signal_keys
        },
    }
    return thresholds, evidence


def _ood_out_of_fold(
    rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    calibration: Mapping[str, Any],
    *,
    seed: int,
    folds: int,
    max_rows: int,
    tuning_max_rows: int,
    architectures: Sequence[str],
) -> dict[str, Any]:
    """Frozen-threshold status coverage on genuinely held-out TRAIN decisions."""
    folds = max(int(folds), 2)
    sample, buckets, stride = _ood_sample_rows(rows, seed, folds, max_rows)
    statuses: list[str] = []
    reasons: dict[str, int] = {}
    by_stratum: dict[str, list[str]] = {stratum: [] for stratum in OOD_STRATA}
    absent_in_domain = {
        "rows": 0,
        "abstained": 0,
        "abstained_without_extrapolation": 0,
        "abstain_reason_counts": {},
        "statuses": {status: 0 for status in OOD_STATUSES},
    }
    for fold_index in range(folds):
        holdout = buckets[fold_index]
        fit_rows = [row for index, bucket in buckets.items() if index != fold_index for row in bucket]
        if not holdout or not fit_rows:
            continue
        fold_calibration = {
            "schema": OOD_CALIBRATION_SCHEMA,
            "domain": _ood_domain_stats(fit_rows, config),
            "category_counts": _ood_category_counts(fit_rows),
            "exact_context_support": _ood_exact_context_support(fit_rows),
            "thresholds": calibration["thresholds"],
            "provenance": {
                "consumed_splits": ["TRAIN"],
                "rows": len(fit_rows),
                "validation_consumed": False,
                "test_consumed": False,
            },
        }
        candidate = fit(
            fit_rows,
            seed,
            architecture=architectures[0],
            config=make_config(tuning_max_rows=tuning_max_rows),
        )
        for row in holdout:
            decision = ood_gate_decision(candidate, row, calibration=fold_calibration)
            status = decision["status"]
            statuses.append(status)
            for reason in decision["reasons"]:
                reasons[reason] = reasons.get(reason, 0) + 1
            stratum = _ood_stratum(
                int(decision["signals"]["exact_context"]["support"]),
                not decision["signals"]["unseen_categories"],
            )
            by_stratum[stratum].append(status)
            if stratum == OOD_STRATUM_EXACT_ABSENT_IN_DOMAIN:
                absent_in_domain["rows"] += 1
                absent_in_domain["statuses"][status] += 1
                if status == STATUS_MODEL_OOD_ABSTAIN:
                    absent_in_domain["abstained"] += 1
                    for reason in decision["reasons"]:
                        bucket = absent_in_domain["abstain_reason_counts"]
                        bucket[reason] = bucket.get(reason, 0) + 1
                    if not any(
                        reason in set(OOD_HARD_REASONS)
                        and reason.startswith("EXTRAPOLATION_")
                        for reason in decision["reasons"]
                    ):
                        # The acceptance rule under test: a never-observed exact
                        # context must not, on its own, cause an abstention.
                        absent_in_domain["abstained_without_extrapolation"] += 1
    pooled = _ood_status_counts(statuses)
    pooled["abstain_reason_counts"] = dict(sorted(reasons.items()))
    pooled["by_stratum"] = {
        stratum: _ood_status_counts(values) for stratum, values in sorted(by_stratum.items())
    }
    absent_in_domain["abstain_reason_counts"] = dict(
        sorted(absent_in_domain["abstain_reason_counts"].items())
    )
    pooled["exact_context_absent_in_domain"] = absent_in_domain
    pooled["reference_architecture"] = architectures[0]
    pooled["folds"] = folds
    pooled["rows"] = len(sample)
    pooled["stride"] = stride
    return pooled


def _ood_report_checks(
    rows: Sequence[Mapping[str, Any]],
    reference_candidate: Mapping[str, Any],
    calibration: Mapping[str, Any],
    category_counts: Mapping[str, Mapping[str, int]],
    exact_context_support: Mapping[str, int],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Deterministic acceptance probes of the frozen calibration."""
    reference = rows[0]
    unseen_probe = _ood_probe_context(reference, family="NEVER_OBSERVED_FAMILY_421")
    stack_high = float((calibration["domain"]["effective_stack_bb"] or {}).get("trained_max") or 100.0)
    stack_probe = _ood_probe_context(reference, effective_stack_bb=stack_high * 2.0 + 10.0)
    ratio_high = float((calibration["domain"][OOD_SIZING_AXIS] or {}).get("trained_max") or 1.0)
    aggressive = next((row for row in rows if row.get("target_total_bb") is not None), reference)
    denominator = float(aggressive.get("pot_before_bb") or 0.0) + float(aggressive.get("to_call_bb") or 0.0)
    sizing_probe = _ood_probe_context(
        aggressive, target_total_bb=round((ratio_high * 2.0 + 1.0) * max(denominator, 1.0), 6)
    )
    novel = _ood_novel_in_domain_probe(rows, category_counts, exact_context_support)
    probes: dict[str, Any] = {}
    for name, probe in (
        ("never_seen_category", unseen_probe),
        ("stack_extrapolation", stack_probe),
        ("sizing_extrapolation", sizing_probe),
        ("exact_context_absent_in_domain", novel),
    ):
        if probe is None:
            probes[name] = {"available": False}
            continue
        decision = ood_gate_decision(reference_candidate, probe, calibration=calibration)
        probes[name] = {
            "available": True,
            "status": decision["status"],
            "abstain": decision["abstain"],
            "reasons": decision["reasons"],
            "exact_context_support": int(decision["signals"]["exact_context"]["support"]),
            "unseen_categories": decision["signals"]["unseen_categories"],
            "context": {
                key: probe.get(key)
                for key in (
                    "family",
                    "actor_position",
                    "aggressor_position",
                    "to_call_bb",
                    "pot_before_bb",
                    "effective_stack_bb",
                    "target_total_bb",
                    "raise_level",
                    "limper_count",
                    "caller_count",
                )
            },
        }
    checks = {
        "never_seen_category_abstains": bool(
            probes["never_seen_category"].get("status") == STATUS_MODEL_OOD_ABSTAIN
            and "UNSEEN_CATEGORY" in probes["never_seen_category"].get("reasons", [])
        ),
        "stack_extrapolation_abstains": bool(
            probes["stack_extrapolation"].get("status") == STATUS_MODEL_OOD_ABSTAIN
            and "EXTRAPOLATION_STACK" in probes["stack_extrapolation"].get("reasons", [])
        ),
        "sizing_extrapolation_abstains": bool(
            probes["sizing_extrapolation"].get("status") == STATUS_MODEL_OOD_ABSTAIN
            and "EXTRAPOLATION_SIZING" in probes["sizing_extrapolation"].get("reasons", [])
        ),
        "exact_context_absent_in_domain_is_not_ood": bool(
            probes["exact_context_absent_in_domain"].get("available")
            and probes["exact_context_absent_in_domain"].get("status") != STATUS_MODEL_OOD_ABSTAIN
            and probes["exact_context_absent_in_domain"].get("abstain") is False
        ),
        "thresholds_calibrated_on_train_only": True,
        "validation_not_consumed": True,
        "test_not_consumed": True,
    }
    return checks, probes


def build_ood_calibration_report(
    rows: Iterable[Mapping[str, Any]],
    *,
    config: Mapping[str, Any] | None = None,
    seed: int = OOD_CALIBRATION_SEED,
    folds: int = OOD_CALIBRATION_FOLDS,
    max_rows: int = OOD_CALIBRATION_MAX_ROWS,
    tuning_max_rows: int = OOD_CALIBRATION_TUNING_ROWS,
    architectures: Sequence[str] = ARCHITECTURES,
    dataset_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build the frozen, TRAIN-only OOD/uncertainty gate calibration report."""
    merged = make_config(**dict(config)) if isinstance(config, Mapping) else make_config()
    for architecture in architectures:
        if architecture not in ARCHITECTURES:
            raise GeneralizedResponseModelError(f"unknown architecture {architecture!r}")
    materialized = order_rows(rows)
    if not materialized:
        raise GeneralizedResponseModelError("no TRAIN rows supplied to the OOD calibration")
    _assert_ood_train_only(materialized)

    # Frozen domain surface: the whole supplied TRAIN set (cheap, no fitting).
    domain = _ood_domain_stats(materialized, merged)
    category_counts = _ood_category_counts(materialized)
    exact_context_support = _ood_exact_context_support(materialized)
    thresholds, evidence = _ood_calibrate_thresholds(
        materialized,
        merged,
        seed=seed,
        folds=folds,
        max_rows=max_rows,
        tuning_max_rows=tuning_max_rows,
        architectures=architectures,
    )
    # Frozen floors: one observed TRAIN decision is the smallest density that
    # counts as evidence, so a never-observed feature label or exact cell always
    # falls below the calibrated floor and lands in the high-uncertainty band.
    support_floor = 1.0 / len(materialized)
    thresholds["min_feature_share"] = _round(
        max(float(thresholds["min_feature_share"]), support_floor), 12
    )
    thresholds["min_exact_context_share"] = _round(
        max(float(thresholds["min_exact_context_share"]), support_floor), 12
    )
    thresholds["support_floor_share"] = _round(support_floor, 12)

    calibration: dict[str, Any] = {
        "schema": OOD_CALIBRATION_SCHEMA,
        "gate_schema": OOD_GATE_SCHEMA,
        "statuses": list(OOD_STATUSES),
        "status_definitions": dict(OOD_STATUS_DEFINITIONS),
        "reason_codes": {
            "hard": list(OOD_HARD_REASONS),
            "soft": list(OOD_SOFT_REASONS),
            "order": list(OOD_REASON_ORDER),
        },
        "feature_blocks": list(OOD_FEATURE_BLOCKS),
        "numeric_axes": list(OOD_NUMERIC_AXES),
        "domain": domain,
        "category_counts": {
            block: dict(sorted(counts.items())) for block, counts in category_counts.items()
        },
        "exact_context_support": dict(sorted(exact_context_support.items())),
        "exact_context_diagnostic_only": True,
        "thresholds": thresholds,
        "provenance": {
            "consumed_splits": ["TRAIN"],
            "validation_consumed": False,
            "test_consumed": False,
            "rows": len(materialized),
            "distinct_exact_contexts": len(exact_context_support),
            "seed": int(seed),
            "folds": int(folds),
            "architectures": list(architectures),
            "threshold_calibration": "train_only_hand_grouped_cross_validation",
            "module": str(Path(__file__).resolve().relative_to(ROOT)),
            "module_sha256": _sha256_file(Path(__file__)),
            "contract": (
                str(OOD_CONTRACT_PATH.relative_to(ROOT)) if OOD_CONTRACT_PATH.exists() else None
            ),
            "contract_sha256": (
                _sha256_file(OOD_CONTRACT_PATH) if OOD_CONTRACT_PATH.exists() else None
            ),
            "config": merged,
        },
    }
    calibration["canonical_payload_sha256"] = canonical_candidate_sha256(calibration)
    # One reference candidate for the acceptance probes, fitted on a
    # deterministic stride of the TRAIN rows (cheap, and never sees VALIDATION).
    probe_rows, _, _ = _ood_sample_rows(materialized, seed, max(int(folds), 2), max_rows)
    reference_candidate = fit(
        probe_rows,
        seed,
        architecture=architectures[0],
        config=make_config(tuning_max_rows=tuning_max_rows),
    )
    checks, probes = _ood_report_checks(
        materialized, reference_candidate, calibration, category_counts, exact_context_support
    )
    report: dict[str, Any] = {
        "schema": OOD_REPORT_SCHEMA,
        "kind": "train_only_ood_uncertainty_gate_calibration",
        "statuses": list(OOD_STATUSES),
        "status_definitions": dict(OOD_STATUS_DEFINITIONS),
        "gate_rules": {
            "combination": (
                "status = MODEL_OOD_ABSTAIN when any hard reason fires (never-observed category or "
                "extrapolation outside the calibrated TRAIN domain); otherwise "
                "MODEL_SUPPORTED_HIGH_UNCERTAINTY when any soft reason fires (density / local "
                "support, robust domain distance, spline-knot boundary, predictive uncertainty); "
                "otherwise MODEL_SUPPORTED"
            ),
            "hard_reasons": list(OOD_HARD_REASONS),
            "soft_reasons": list(OOD_SOFT_REASONS),
            "never_seen_category_abstains": True,
            "sizing_extrapolation_abstains": True,
            "stack_extrapolation_abstains": True,
            "exact_context_absent_is_not_ood": (
                "the exact-context cell support is reported as a diagnostic and can only raise the "
                "status to MODEL_SUPPORTED_HIGH_UNCERTAINTY; a context whose exact cell was never "
                "observed while every single-feature label is in-domain is never abstained"
            ),
            "thresholds_calibrated_on": ["TRAIN", "CV"],
            "numeric_axes": {
                "to_call_bb": (
                    "absolute price to call, in bb; domain measured on every TRAIN decision and "
                    "hard-failed by EXTRAPOLATION_PRICE when the query leaves the TRAIN hull"
                ),
                "pot_before_bb": (
                    "pot before the decision, in bb; domain measured on every TRAIN decision and "
                    "hard-failed by EXTRAPOLATION_PRICE when the query leaves the TRAIN hull"
                ),
                "effective_stack_bb": (
                    "effective stack, in bb; domain measured on every TRAIN decision and "
                    "hard-failed by EXTRAPOLATION_STACK when the query leaves the TRAIN hull"
                ),
                OOD_SIZING_AXIS: (
                    "queried target_total_bb / (pot_before_bb + to_call_bb); the axis is only "
                    "queried when a raise target is supplied, its domain is measured on the "
                    "observed aggressive TRAIN rows and a query outside it hard-fails with "
                    "EXTRAPOLATION_SIZING"
                ),
            },
            "soft_signal_union_note": (
                "every soft signal is calibrated at its own TRAIN out-of-fold tail (95th "
                "percentile on the high side, 5th percentile on the low side), so the union of "
                "the soft signals flags more than 5% of the in-domain decisions; the measured "
                "out-of-fold rate is reported under out_of_fold.shares"
            ),
            "validation_consumed": False,
            "test_consumed": False,
        },
        "calibration": calibration,
        "calibration_evidence": evidence,
        "scope": {
            "consumed_splits": ["TRAIN"],
            "validation_consumed": False,
            "test_consumed": False,
            "rows_consumed": len(materialized),
            "cv_rows": evidence["protocol"]["sample_rows"],
        },
        "probes": probes,
        "acceptance_checks": checks,
        "provenance": {
            "module_sha256": calibration["provenance"]["module_sha256"],
            "contract": calibration["provenance"]["contract"],
            "contract_sha256": calibration["provenance"]["contract_sha256"],
            "config": merged,
            "reference_candidate_architecture": reference_candidate["architecture"],
            "reference_candidate_canonical_payload_sha256": reference_candidate[
                "canonical_payload_sha256"
            ],
        },
    }
    if dataset_path is not None:
        resolved = Path(dataset_path)
        if resolved.exists():
            label = str(resolved)
            try:
                label = str(resolved.relative_to(ROOT))
            except ValueError:
                label = str(resolved)
            report["provenance"]["dataset"] = label
            report["provenance"]["dataset_sha256"] = _sha256_file(resolved)
    report["out_of_fold"] = _ood_out_of_fold(
        materialized,
        merged,
        calibration,
        seed=seed,
        folds=folds,
        max_rows=max_rows,
        tuning_max_rows=tuning_max_rows,
        architectures=architectures,
    )
    report["gate_rules"]["measured_out_of_fold_status_shares"] = report["out_of_fold"]["shares"]
    return report


def validate_ood_calibration(calibration: Mapping[str, Any]) -> list[str]:
    """Fail-closed structural validation of a frozen gate calibration."""
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(isinstance(calibration, Mapping), "calibration must be an object")
    if not isinstance(calibration, Mapping):
        return errors
    require(
        calibration.get("schema") == OOD_CALIBRATION_SCHEMA,
        f"schema must be {OOD_CALIBRATION_SCHEMA}",
    )
    require(
        list(calibration.get("statuses") or []) == list(OOD_STATUSES),
        "statuses must be the three frozen statuses",
    )
    domain = calibration.get("domain")
    require(isinstance(domain, Mapping), "domain must be an object")
    if isinstance(domain, Mapping):
        for axis in OOD_NUMERIC_AXES:
            require(axis in domain, f"domain must carry the {axis} axis")
    counts = calibration.get("category_counts")
    require(isinstance(counts, Mapping), "category_counts must be an object")
    if isinstance(counts, Mapping):
        for block in OOD_FEATURE_BLOCKS:
            require(block in counts and bool(counts[block]), f"category_counts must cover {block}")
    require(
        isinstance(calibration.get("exact_context_support"), Mapping),
        "exact_context_support must be an object",
    )
    require(
        calibration.get("exact_context_diagnostic_only") is True,
        "exact_context_support must be declared diagnostic-only",
    )
    thresholds = calibration.get("thresholds")
    require(isinstance(thresholds, Mapping), "thresholds must be an object")
    if isinstance(thresholds, Mapping):
        for key in (
            "min_feature_share",
            "min_exact_context_share",
            "min_model_node_support_per_row",
            "normalized_entropy",
            "domain_distance",
        ):
            require(key in thresholds, f"thresholds must carry {key}")
    provenance = calibration.get("provenance")
    require(isinstance(provenance, Mapping), "provenance must be an object")
    if isinstance(provenance, Mapping):
        require(provenance.get("consumed_splits") == ["TRAIN"], "consumed_splits must be TRAIN only")
        require(provenance.get("validation_consumed") is False, "validation_consumed must be false")
        require(provenance.get("test_consumed") is False, "test_consumed must be false")
    digest = calibration.get("canonical_payload_sha256")
    require(
        isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest),
        "canonical_payload_sha256 must be a lowercase sha256",
    )
    if isinstance(digest, str) and len(digest) == 64:
        require(
            digest == canonical_candidate_sha256(calibration),
            "canonical_payload_sha256 does not match the calibration payload",
        )
    return errors


def validate_ood_decision(decision: Mapping[str, Any]) -> list[str]:
    """Fail-closed structural validation of a gate decision."""
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(isinstance(decision, Mapping), "decision must be an object")
    if not isinstance(decision, Mapping):
        return errors
    require(decision.get("schema") == OOD_GATE_SCHEMA, f"schema must be {OOD_GATE_SCHEMA}")
    status = decision.get("status")
    require(status in OOD_STATUSES, f"status must be one of {list(OOD_STATUSES)}")
    require(
        decision.get("abstain") is (status == STATUS_MODEL_OOD_ABSTAIN),
        "abstain must match the status",
    )
    require(
        decision.get("supported") is (status != STATUS_MODEL_OOD_ABSTAIN),
        "supported must match the status",
    )
    reasons = decision.get("reasons")
    require(isinstance(reasons, list), "reasons must be a list")
    if isinstance(reasons, list):
        unknown = [reason for reason in reasons if reason not in OOD_REASON_ORDER]
        require(not unknown, f"reasons must be known reason codes, got {unknown}")
        if status == STATUS_MODEL_OOD_ABSTAIN:
            require(
                bool(set(reasons) & set(OOD_HARD_REASONS)),
                "an abstention must carry at least one hard reason",
            )
        else:
            require(
                not (set(reasons) & set(OOD_HARD_REASONS)),
                f"{status} must not carry a hard reason",
            )
    require(decision.get("validation_consumed") is False, "validation_consumed must be false")
    require(decision.get("test_consumed") is False, "test_consumed must be false")
    signals = decision.get("signals")
    require(isinstance(signals, Mapping), "signals must be an object")
    if isinstance(signals, Mapping):
        exact = signals.get("exact_context")
        require(isinstance(exact, Mapping), "signals.exact_context must be an object")
        if isinstance(exact, Mapping):
            require(exact.get("decisive") is False, "the exact-context signal must stay non-decisive")
    return errors


def load_ood_calibration(path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate the frozen calibration from the persisted report."""
    target = Path(path) if path is not None else DEFAULT_OOD_REPORT_PATH
    if not target.exists():
        raise GeneralizedResponseModelError(
            f"no OOD calibration report at {target}; run --ood-calibration-report"
        )
    document = json.loads(target.read_text(encoding="utf-8"))
    calibration = document.get("calibration") if isinstance(document, Mapping) else None
    if not isinstance(calibration, Mapping):
        raise GeneralizedResponseModelError(f"{target} does not carry a calibration document")
    errors = validate_ood_calibration(calibration)
    if errors:
        raise GeneralizedResponseModelError("invalid OOD calibration: " + "; ".join(errors))
    return dict(calibration)


def write_ood_calibration_report(
    report: Mapping[str, Any], path: str | Path = DEFAULT_OOD_REPORT_PATH
) -> dict[str, Any]:
    """Persist the calibration report byte-reproducibly and return its identity."""
    target = Path(path)
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    target.write_text(payload, encoding="utf-8")
    return {
        "path": str(target),
        "sha256": sha256_bytes(payload.encode("utf-8")),
        "bytes": len(payload.encode("utf-8")),
        "schema": report.get("schema"),
        "calibration_canonical_payload_sha256": (
            report.get("calibration") or {}
        ).get("canonical_payload_sha256"),
    }


# ---------------------------------------------------------------------------
# persistence and validation
# ---------------------------------------------------------------------------


def validate_candidate(candidate: Mapping[str, Any]) -> list[str]:
    """Fail-closed structural validation of a candidate document (stdlib only)."""
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(isinstance(candidate, Mapping), "candidate must be an object")
    if not isinstance(candidate, Mapping):
        return errors
    require(candidate.get("schema") == SCHEMA, f"schema must be {SCHEMA}")
    architecture = candidate.get("architecture")
    require(architecture in ARCHITECTURES, "architecture must be a known architecture")
    require(isinstance(candidate.get("seed"), int) and not isinstance(candidate.get("seed"), bool), "seed must be an int")
    config = candidate.get("config")
    require(isinstance(config, Mapping) and sorted(dict(config)) == sorted(CONFIG_KEYS),
            "config must carry exactly the documented keys")
    require(candidate.get("action_space") == list(ACTIONS), f"action_space must be {list(ACTIONS)}")
    params = candidate.get("params")
    require(isinstance(params, Mapping), "params must be an object")
    if isinstance(params, Mapping):
        prior = params.get("prior")
        require(isinstance(prior, Mapping) and sorted(prior) == sorted(ACTIONS),
                "params.prior must cover the four actions")
        if isinstance(prior, Mapping) and sorted(prior) == sorted(ACTIONS):
            require(abs(sum(float(prior[action]) for action in ACTIONS) - 1.0) <= 1e-6,
                    "params.prior must sum to 1")
        blocks = params.get("blocks")
        require(isinstance(blocks, Mapping) and bool(blocks), "params.blocks must be a non-empty object")
        kernel = "lift" if architecture == ARCH_REGULARIZED else "counts"
        if isinstance(blocks, Mapping):
            for name, block in blocks.items():
                require(isinstance(block, Mapping), f"block {name} must be an object")
                if not isinstance(block, Mapping):
                    continue
                require(block.get("kind") in ("primary", "interaction"), f"block {name} has an invalid kind")
                require(block.get("basis") in ("categorical", "spline"), f"block {name} has an invalid basis")
                nodes, support, values = block.get("nodes"), block.get("support"), block.get(kernel)
                require(isinstance(nodes, list) and isinstance(support, list) and isinstance(values, list),
                        f"block {name} must carry nodes/support/{kernel} lists")
                if isinstance(nodes, list) and isinstance(support, list) and isinstance(values, list):
                    require(len(nodes) == len(support) == len(values), f"block {name} list lengths must match")
                    for row in values:
                        require(
                            isinstance(row, list) and len(row) == len(ACTIONS)
                            and all(isinstance(value, (int, float)) for value in row),
                            f"block {name} rows must be four-number vectors",
                        )
                if block.get("basis") == "spline":
                    require(block.get("transform") == AXIS_TRANSFORM,
                            f"block {name} must declare its axis transform")
                    require(isinstance(block.get("knots"), list), f"block {name} must carry its knots")
                    knots = block.get("knots")
                    if isinstance(knots, list):
                        require(
                            len(knots) >= 2
                            and all(float(b) > float(a) for a, b in zip(knots, knots[1:])),
                            f"block {name} knots must be strictly increasing",
                        )
                        require(isinstance(nodes, list) and len(nodes) == len(knots),
                                f"block {name} nodes must align with its knots")
        channel = params.get("sizing_channel")
        require(isinstance(channel, Mapping), "params.sizing_channel must be an object")
        if isinstance(channel, Mapping):
            knots = channel.get("axis_knots")
            require(isinstance(knots, list) and len(knots) >= 2, "sizing channel needs at least two knots")
            for action in AGGRESSIVE_ACTIONS:
                global_table = (channel.get("global") or {}).get(action)
                require(isinstance(global_table, Mapping), f"sizing channel needs the global {action} density")
                scopes = [global_table]
                for tables in (channel.get("families") or {}).values():
                    if isinstance(tables, Mapping):
                        scopes.append(tables.get(action))
                for table in scopes:
                    if not isinstance(table, Mapping):
                        continue
                    density = table.get("density")
                    require(
                        isinstance(density, list) and isinstance(knots, list) and len(density) == len(knots),
                        f"sizing density {action} must align with the knots",
                    )
                    if isinstance(density, list) and density:
                        require(all(float(value) >= 0 for value in density),
                                f"sizing density {action} must be non-negative")
        regularization = params.get("regularization")
        require(isinstance(regularization, Mapping), "params.regularization must be an object")
        if isinstance(regularization, Mapping):
            expected = "lift_scale" if architecture == ARCH_REGULARIZED else "deviation_scale"
            require(regularization.get("kind") == expected,
                    f"params.regularization.kind must be {expected} for {architecture}")
            require(
                isinstance(regularization.get("scale"), (int, float))
                and not isinstance(regularization.get("scale"), bool)
                and float(regularization["scale"]) > 0,
                "params.regularization must carry a positive scale",
            )
    summary = candidate.get("fit_summary")
    require(isinstance(summary, Mapping), "fit_summary must be an object")
    if isinstance(summary, Mapping):
        require(int(summary.get("rows") or 0) > 0, "fit_summary.rows must be positive")
        require(int(summary.get("distinct_hands") or 0) > 0, "fit_summary.distinct_hands must be positive")
    digest = candidate.get("canonical_payload_sha256")
    require(
        isinstance(digest, str) and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest),
        "canonical_payload_sha256 must be a lowercase sha256",
    )
    if isinstance(digest, str) and len(digest) == 64:
        require(digest == canonical_candidate_sha256(candidate),
                "canonical_payload_sha256 does not match the payload")
    return errors


def persist_candidate(candidate: Mapping[str, Any], path: str | Path) -> dict[str, Any]:
    """Write a candidate byte-reproducibly and return its identity metadata."""
    errors = validate_candidate(candidate)
    if errors:
        raise GeneralizedResponseModelError("refusing to persist an invalid candidate: " + "; ".join(errors))
    target = Path(path)
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(candidate, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    target.write_text(payload, encoding="utf-8")
    return {
        "path": str(target),
        "sha256": sha256_bytes(payload.encode("utf-8")),
        "bytes": len(payload.encode("utf-8")),
        "canonical_payload_sha256": canonical_candidate_sha256(candidate),
        "architecture": candidate.get("architecture"),
    }


def load_candidate(path: str | Path) -> dict[str, Any]:
    """Load a persisted candidate and verify its canonical hash."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    errors = validate_candidate(document)
    if errors:
        raise GeneralizedResponseModelError("invalid persisted candidate: " + "; ".join(errors))
    return document


class ResponseModel:
    """Thin object wrapper so ``fit``/``predict`` read as a familiar API."""

    def __init__(self, candidate: Mapping[str, Any]) -> None:
        errors = validate_candidate(candidate)
        if errors:
            raise GeneralizedResponseModelError("invalid candidate: " + "; ".join(errors))
        self.candidate: dict[str, Any] = dict(candidate)

    @classmethod
    def fit(
        cls,
        train_rows: Iterable[Mapping[str, Any]],
        seed: int = 0,
        **kwargs: Any,
    ) -> "ResponseModel":
        return cls(fit(train_rows, seed, **kwargs))

    @property
    def canonical_payload_sha256(self) -> str:
        return str(self.candidate["canonical_payload_sha256"])

    def predict(self, context: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
        return predict(self.candidate, context, **kwargs)

    def price_response(self, context: Mapping[str, Any], sizings: Sequence[float] | None = None) -> dict[str, Any]:
        return price_response(self.candidate, context, sizings)

    def evaluate(self, rows: Iterable[Mapping[str, Any]], **kwargs: Any) -> dict[str, Any]:
        return evaluate(self.candidate, rows, **kwargs)

    def sizing_window(self, context: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Legal raise-target window of one public context (#421 sizing model)."""
        return raise_sizing_window(context, **kwargs)

    def raise_sizing(self, context: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Conditional P(sizing | RAISE/JAM, context): support, uncertainty, samples."""
        return raise_sizing_query(self.candidate, context, **kwargs)

    def score_sizing(
        self, context: Mapping[str, Any], target_total_bb: float, **kwargs: Any
    ) -> dict[str, Any]:
        """NLL/CRPS of one queried raise target under the conditional density."""
        return score_raise_sizing(self.candidate, context, target_total_bb, **kwargs)

    def ood_gate(self, context: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Frozen OOD / uncertainty verdict: MODEL_SUPPORTED, HIGH_UNCERTAINTY or ABSTAIN."""
        return ood_gate_decision(self.candidate, context, **kwargs)

    def ood_status(self, context: Mapping[str, Any], **kwargs: Any) -> str:
        """Just the machine-readable status of :meth:`ood_gate`."""
        return str(self.ood_gate(context, **kwargs)["status"])


# ---------------------------------------------------------------------------
# CLI and dependency-free self-check
# ---------------------------------------------------------------------------


def synthetic_rows(count: int, seed: int) -> list[dict[str, Any]]:
    """Deterministic synthetic public rows used by the fast self-check."""
    families = ("UNOPENED", "VS_LIMPERS", "VS_RFI", "VS_ISO", "VS_RFI_CALLERS", "COLD_VS_3BET")
    positions = ("LJ", "HJ", "CO", "BTN", "SB", "BB")
    rows: list[dict[str, Any]] = []
    for index in range(count):
        digest = stable_hash(f"self-check/{int(seed)}/{index}")
        family = families[int(digest[0:2], 16) % len(families)]
        position = positions[int(digest[2:4], 16) % len(positions)]
        stack = 8.0 + (int(digest[4:8], 16) % 2400) / 20.0
        to_call = 1.0 if family in ("UNOPENED", "VS_LIMPERS") else 2.5 + (int(digest[8:10], 16) % 60) / 4.0
        pot = to_call + 1.5 + (int(digest[10:12], 16) % 80) / 4.0
        price = to_call / (to_call + pot)
        tilt = 0.45 - 1.6 * price + 0.02 * math.log1p(stack) - (0.25 if family == "UNOPENED" else 0.0)
        bucket = int(digest[12:16], 16) % 1000 / 1000.0
        if bucket < max(0.02, 0.55 - max(tilt, 0.0)):
            action = "FOLD"
        elif bucket < max(0.04, 0.86 - max(tilt, 0.0) * 0.6):
            action = "CALL"
        elif bucket < 0.97:
            action = "RAISE"
        else:
            action = "JAM"
        target = None
        if action in AGGRESSIVE_ACTIONS:
            target = min(round((pot + to_call) * (1.0 + (int(digest[16:20], 16) % 200) / 100.0), 3), stack)
        rows.append(
            {
                "hand_id": f"{1000000 + index}",
                "split": "TRAIN",
                "table_size": 6,
                "family": family,
                "actor_position": position,
                "aggressor_position": None if family == "UNOPENED" else "CO",
                "limper_count": 1 if family == "VS_LIMPERS" else 0,
                "caller_count": int(digest[20:21], 16) % 3,
                "live_positions": list(positions),
                "raise_level": 0 if family in ("UNOPENED", "VS_LIMPERS") else 1,
                "to_call_bb": round(to_call, 3),
                "pot_before_bb": round(pot, 3),
                "pot_odds": round(price, 6),
                "price_to_pot": round(to_call / max(pot, 0.01), 6),
                "effective_stack_bb": round(stack, 3),
                "target_total_bb": target,
                "observed_sizing_bb": None if target is None else round(max(target - to_call, 0.0), 3),
                "action": action,
            }
        )
    return rows


def self_check(seed: int = 421) -> dict[str, Any]:
    """Fast, dependency-free end-to-end check of both architectures."""
    rows = synthetic_rows(2400, seed)
    candidates = fit_many(rows, seed, config=make_config(tuning_max_rows=400))
    comparison = compare_candidates(candidates, rows[:600])
    context = dict(rows[0])
    context["target_total_bb"] = 4.0
    return {
        "schema": "poker-generalized-response-self-check/v1",
        "rows": len(rows),
        "candidates": [
            {
                "architecture": candidate["architecture"],
                "canonical_payload_sha256": candidate["canonical_payload_sha256"],
                "holdout_log_loss_bits_per_decision": candidate["fit_summary"]["holdout_log_loss_bits_per_decision"],
                "prediction": predict(candidate, context)["probabilities"],
            }
            for candidate in candidates
        ],
        "comparison": {
            "ranking": comparison["ranking"],
            "log_loss_delta_vs_best_bits_per_decision": comparison["log_loss_delta_vs_best_bits_per_decision"],
        },
    }


def _cli_sizing_report(args: argparse.Namespace) -> int:
    dataset_path = Path(args.dataset).resolve()
    rows = read_dataset_rows(dataset_path, splits=tuple(args.sizing_splits))
    config = make_config(tuning_max_rows=args.tuning_max_rows, holdout_modulus=args.holdout_modulus)
    report = raise_sizing_report(
        rows,
        config=config,
        seed=args.seed,
        dataset_path=dataset_path,
        steps=args.sizing_steps,
        metrics_split=args.sizing_metrics_split or None,
    )
    persisted = write_raise_sizing_report(report, args.sizing_report_out)
    print(json.dumps({"persisted": persisted, "guarantees": report["guarantees"]}, indent=2, sort_keys=True))
    return 0


def _cli_ood_calibration_report(args: argparse.Namespace) -> int:
    dataset_path = Path(args.dataset).resolve()
    rows = read_dataset_rows(dataset_path, splits=("TRAIN",))
    config = make_config(tuning_max_rows=args.tuning_max_rows, holdout_modulus=args.holdout_modulus)
    report = build_ood_calibration_report(
        rows,
        config=config,
        seed=args.seed,
        folds=args.ood_folds,
        max_rows=args.ood_max_rows,
        tuning_max_rows=args.ood_tuning_rows,
        dataset_path=dataset_path,
    )
    persisted = write_ood_calibration_report(report, args.ood_report_out)
    print(
        json.dumps(
            {
                "persisted": persisted,
                "acceptance_checks": report["acceptance_checks"],
                "thresholds": report["calibration"]["thresholds"],
                "out_of_fold": report["out_of_fold"]["shares"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _cli_fit(args: argparse.Namespace) -> int:
    dataset_path = Path(args.dataset).resolve()
    dataset_label = str(dataset_path)
    try:
        dataset_label = str(dataset_path.relative_to(ROOT))
    except ValueError:
        pass
    rows = read_dataset_rows(dataset_path, splits=(args.train_split,))
    eval_rows = read_dataset_rows(dataset_path, splits=(args.eval_split,)) if args.eval_split else []
    config = make_config(tuning_max_rows=args.tuning_max_rows, holdout_modulus=args.holdout_modulus)
    candidates = fit_many(rows, args.seed, config=config)
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    persisted = [
        persist_candidate(candidate, output_dir / f"candidate_{candidate['architecture']}.json")
        for candidate in candidates
    ]
    for entry in persisted:
        try:
            entry["path"] = str(Path(str(entry["path"])).resolve().relative_to(ROOT))
        except ValueError:
            pass
    comparison = compare_candidates(candidates, eval_rows) if eval_rows else {}
    report = {
        "schema": "poker-generalized-response-fit-report/v1",
        "seed": args.seed,
        "dataset": dataset_label,
        "dataset_sha256": _sha256_file(dataset_path),
        "module_sha256": _sha256_file(Path(__file__)),
        "contract_sha256": _sha256_file(CONTRACT_PATH),
        "train_split": args.train_split,
        "eval_split": args.eval_split,
        "config": config,
        "candidates": [
            {
                "architecture": candidate["architecture"],
                "canonical_payload_sha256": candidate["canonical_payload_sha256"],
                "fit_summary": candidate["fit_summary"],
            }
            for candidate in candidates
        ],
        "persisted": persisted,
        "comparison": comparison,
    }
    (output_dir / "FIT_REPORT.json").write_text(
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    (output_dir / "SUMMARY.md").write_text(summary_text(report), encoding="utf-8")
    # The index is written last so it hashes the complete directory.
    write_artifact_index(output_dir, persisted)
    print(json.dumps({"persisted": persisted, "best": comparison.get("best")}, indent=2, sort_keys=True))
    return 0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_artifact_index(output_dir: Path, persisted: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Index every file of the model directory by content hash."""
    index: dict[str, Any] = {}
    for path in sorted(Path(output_dir).iterdir()):
        if path.name == "ARTIFACTS.json":
            continue
        payload = path.read_bytes()
        index[path.name] = {
            "bytes": len(payload),
            "sha256": sha256_bytes(payload),
        }
    for entry in persisted:
        name = Path(str(entry["path"])).name
        if name in index:
            index[name]["canonical_payload_sha256"] = entry["canonical_payload_sha256"]
            index[name]["architecture"] = entry["architecture"]
    (Path(output_dir) / "ARTIFACTS.json").write_text(
        json.dumps(index, sort_keys=True, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return index


def summary_text(report: Mapping[str, Any]) -> str:
    """Human-readable summary of one persisted fit report."""
    lines = [
        "# #421 - generalizing adverse-response model library",
        "",
        "Two comparable architectures trained on the public-only adverse-response",
        "dataset, sharing one API, one legal-distribution contract and one direct",
        "price/sizing recalculation path. Standard library only.",
        "",
        "## Provenance",
        "",
        f"- dataset: `{report['dataset']}` (sha256 `{report['dataset_sha256']}`)",
        f"- train split: **{report['train_split']}**, evaluation split: **{report['eval_split']}**",
        f"- seed: **{report['seed']}**",
        f"- module sha256: `{report['module_sha256']}`",
        f"- contract sha256: `{report['contract_sha256']}`",
        "",
        "## Candidates",
        "",
        "| architecture | rows | hands | holdout LL (bits/decision) | baseline | gain | tuned scale | canonical hash |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for candidate in report["candidates"]:
        summary = candidate["fit_summary"]
        lines.append(
            "| `{architecture}` | {rows} | {distinct_hands} | {holdout} | {baseline} | {gain} | {scale} | `{digest}` |".format(
                architecture=candidate["architecture"],
                rows=summary["rows"],
                distinct_hands=summary["distinct_hands"],
                holdout=summary["holdout_log_loss_bits_per_decision"],
                baseline=summary["baseline_log_loss_bits_per_decision"],
                gain=summary["holdout_gain_bits_per_decision"],
                scale=summary["tuning"]["selected"],
                digest=candidate["canonical_payload_sha256"],
            )
        )
    comparison = report.get("comparison") or {}
    if comparison:
        lines.extend(["", "## Direct evaluation on the evaluation split", ""])
        for key, metrics in sorted(comparison.get("candidates", {}).items()):
            lines.append(
                f"- `{key}`: n={metrics['n']}, log loss {metrics['log_loss_bits_per_decision']} bits/decision, "
                f"baseline {metrics['baseline_log_loss_bits_per_decision']}, accuracy {metrics['accuracy']}, "
                f"probability-sum error {metrics['probability_sum_max_abs_error']}, "
                f"illegal mass {metrics['illegal_mass_max']}"
            )
        lines.append(f"- best: `{comparison.get('best')}`")
    lines.extend(
        [
            "",
            "## Guarantees exercised by the tests",
            "",
            "- both architectures are trainable and comparable on the same dataset;",
            "- same rows + seed + config => byte-identical candidate hash and identical predictions;",
            "- the returned distribution is legal, sums to exactly 1.0 and masks illegal actions before",
            "  the final normalization;",
            "- a variation of `target_total_bb` is recomputed directly through the partition-of-unity",
            "  sizing spline (no neighbouring-cell substitution);",
            "- no dependency outside the Python standard library.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generalized preflop response model (#421)")
    parser.add_argument("--self-check", action="store_true", help="fit both architectures on synthetic rows")
    parser.add_argument("--fit", action="store_true", help="fit the persisted dataset and persist candidates")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--train-split", default="TRAIN")
    parser.add_argument("--eval-split", default="VALIDATION")
    parser.add_argument("--seed", type=int, default=421)
    parser.add_argument("--tuning-max-rows", type=int, default=8000)
    parser.add_argument("--holdout-modulus", type=int, default=5)
    parser.add_argument(
        "--sizing-report",
        action="store_true",
        help="fit the conditional RAISE/JAM sizing model and persist RAISE_SIZING_MODEL_REPORT.json",
    )
    parser.add_argument("--sizing-report-out", default=str(DEFAULT_SIZING_REPORT_PATH))
    parser.add_argument(
        "--sizing-splits",
        nargs="+",
        default=["TRAIN", "VALIDATION"],
        help="folds consumed by the sizing model (TEST stays fail-closed)",
    )
    parser.add_argument("--sizing-metrics-split", default="", help="optional fold restriction for the metrics")
    parser.add_argument("--sizing-steps", type=int, default=SIZING_QUADRATURE_STEPS)
    parser.add_argument(
        "--ood-calibration-report",
        action="store_true",
        help="calibrate the OOD/uncertainty gate on TRAIN and persist OOD_CALIBRATION_REPORT.json",
    )
    parser.add_argument("--ood-report-out", default=str(DEFAULT_OOD_REPORT_PATH))
    parser.add_argument("--ood-folds", type=int, default=OOD_CALIBRATION_FOLDS)
    parser.add_argument("--ood-max-rows", type=int, default=OOD_CALIBRATION_MAX_ROWS)
    parser.add_argument("--ood-tuning-rows", type=int, default=OOD_CALIBRATION_TUNING_ROWS)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_check:
        print(json.dumps(self_check(args.seed), sort_keys=True, indent=2))
        return 0
    if args.fit:
        return _cli_fit(args)
    if args.sizing_report:
        return _cli_sizing_report(args)
    if args.ood_calibration_report:
        return _cli_ood_calibration_report(args)
    print("nothing to do: pass --self-check, --fit, --sizing-report or --ood-calibration-report")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
