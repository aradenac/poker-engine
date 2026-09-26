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
* :func:`compare_candidates` -> architecture-vs-architecture comparison on the
  same rows;
* ``contracts/training/generalized-response-model.schema.json`` -> the contract
  for every produced/persisted document.

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
    mass = float(config["sizing_smoothing_mass"])
    knots = [float(x) for x in config["sizing_axis_knots"]]
    channel: dict[str, Any] = {
        "axis_knots": knots,
        "actions": list(AGGRESSIVE_ACTIONS),
        "global": {},
        "families": {},
    }
    for action in AGGRESSIVE_ACTIONS:
        global_counts = counts.sizing_counts[action]["GLOBAL"]
        total = float(sum(global_counts))
        if total <= 0:
            density = [1.0 / len(knots)] * len(knots)
        else:
            density = [(float(value) + mass / len(knots)) / (total + mass) for value in global_counts]
        channel["global"][action] = {
            "total": int(round(total)),
            "density": [_round(value, 9) for value in density],
        }
        for family, values in counts.sizing_counts[action].items():
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
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_check:
        print(json.dumps(self_check(args.seed), sort_keys=True, indent=2))
        return 0
    if args.fit:
        return _cli_fit(args)
    print("nothing to do: pass --self-check or --fit")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
