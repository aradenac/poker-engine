#!/usr/bin/env python3
"""#423 hybrid preflop response router: pre-action signals and simple rules.

The frozen #423 preregistration
(``analysis/issue423_hybrid_router/HYBRID_ROUTER_SPEC.json``) decides how a
preflop adverse-response request is routed: either to the *active strong
support* model (the exact context is strongly observed), to the *generalized
sparse in-domain* channel (the exact cell is sparse or absent while every
single-feature label stays inside the calibrated domain), or to a fail-closed
*abstention*.  This module is the executable counterpart of that spec: it
computes the nine pre-action signals and lets a small catalogue of *simple,
explicable, comparable* :class:`RouteRule` objects turn them into one of the
three route sources.

Signals, computed before the action
-----------------------------------

``compute_signals(context)`` returns one deterministic bundle carrying all ten
signals the spec names, each of them computable **before** the action and
independent of the hidden hand and of the observed result:

``support_exact``
    fit-fold occurrences of the decision's exact context signature, looked up
    **exactly** in the frozen ``exact_context_support`` index;
``support_feature_level``
    the weakest per-block share of the single-feature node labels in the
    calibrated fold (``local_support.min_feature_share``);
``distance_to_domain``
    the robust distance of the queried numerics to the calibrated core;
``predictive_uncertainty``
    the normalized predictive entropy / fitted node support of the generalized
    channel, or ``None`` when no fitted candidate was supplied;
``extrapolation_sizing`` / ``extrapolation_stack`` / ``extrapolation_price``
    whether the queried raise target, effective stack or to-call / pot leaves
    the calibrated TRAIN domain;
``ood_status``, ``hard_reasons``, ``soft_reasons``
    the verdict of the frozen #421 OOD / uncertainty gate;
``family`` / ``actor_position`` / ``aggressor_position``
    the public categorical node labels of the request, reported so a route can
    be explained (never consumed unless the frozen TRAIN breakdown justifies
    it).

No hidden hand, no observed result, no nearest lookup
-----------------------------------------------------

The router never reads ``action`` / ``observed_sizing_bb`` or any other
realised outcome, and it never substitutes a neighbouring observation for the
queried one:

* :func:`resolve_support_exact` looks the *exact* context signature up in the
  frozen index and returns ``0`` for an absent key -- it never falls back on the
  nearest supported context;
* :func:`resolve_numeric_axis` reads the *exact* queried axis and returns
  ``None`` when the axis is absent from the request -- it never substitutes the
  nearest price;
* both refuse, with a stable ``NEAREST_NEIGHBOUR_SUBSTITUTION_REFUSED`` code,
  any caller that explicitly asks for a neighbour substitution, and the module
  declares :data:`NO_NEAREST_PRICE_SUBSTITUTION` /
  :data:`NO_NEAREST_CONTEXT_SUBSTITUTION`.

There is no ad-hoc table of contexts anywhere in this module: the only
context-keyed data structure it reads is the frozen, TRAIN-calibrated support
index of the #421 gate.

The rule catalogue and the simplicity policy
--------------------------------------------

Three rules of increasing complexity are declared (``ROUTE_RULES``), each a
plain, auditable function of the signal bundle:

``R1_HARD_GATE`` (complexity 1)
    abstain on any hard reason, answer from the active model when the exact
    context is strongly supported, use the sparse channel otherwise;
``R2_SUPPORT_GATE`` (complexity 2)
    the frozen preregistered table: the same, plus an explicit
    ``feature_in_domain`` condition before the sparse channel;
``R3_UNCERTAINTY_GATE`` (complexity 3)
    the same, but a sparse context whose numerics sit in the calibrated tail is
    refused instead of answered.

:func:`select_rule` applies the preregistered *simplicity policy*: it measures
every rule against the frozen reference rule on a probe set and keeps the
**simplest** rule whose agreement stays within
:data:`RULE_SIMPLICITY_MARGIN` of the best.  A rule is never simplified away
from the reference without measuring the loss first.

:func:`route` turns a context into the routing document: the selected route
source, the support state, the uncertainty flag, the frozen OOD status, the
stratum, the full signal bundle and the rule provenance.  When the caller
supplies route *channels* (the active and the generalized probability
providers) the document also carries the legal, renormalised probabilities and
the sizing provenance of an aggressive answer; an abstention never carries
probabilities, a selected action or sizing.  The legality surface a channel
answer is masked to is the *frozen engine* one
(``generalized_response_model.legal_response_actions``), never a router-local
approximation of it.

Only the Python standard library is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_model as model  # noqa: E402
from tools.preflop import generalized_response_runtime as runtime  # noqa: E402

MODULE_PATH = Path(__file__).resolve()

ROUTING_DOCUMENT_SCHEMA = "poker-hybrid-router-routing-decision/v1"
ROUTING_CONTRACT_SCHEMA = "poker-hybrid-router-runtime-contract/v1"

#: The three stable route sources of the frozen #423 spec.
ROUTE_SOURCE_ACTIVE = "ACTIVE_STRONG_SUPPORT"
ROUTE_SOURCE_SPARSE = "GENERALIZED_SPARSE_IN_DOMAIN"
ROUTE_SOURCE_ABSTAIN = "OOD_ABSTAIN"
ROUTE_SOURCES: tuple[str, ...] = (
    ROUTE_SOURCE_ACTIVE,
    ROUTE_SOURCE_SPARSE,
    ROUTE_SOURCE_ABSTAIN,
)

#: Support states declared by the route sources.
SUPPORT_STATE_STRONG = "STRONG_EXACT_SUPPORT"
SUPPORT_STATE_SPARSE = "SPARSE_IN_DOMAIN"
SUPPORT_STATE_ABSTAIN = "OOD_ABSTAIN"
SUPPORT_STATE_OF_ROUTE: dict[str, str] = {
    ROUTE_SOURCE_ACTIVE: SUPPORT_STATE_STRONG,
    ROUTE_SOURCE_SPARSE: SUPPORT_STATE_SPARSE,
    ROUTE_SOURCE_ABSTAIN: SUPPORT_STATE_ABSTAIN,
}

#: The four frozen strata of the held-out gate evaluation.
STRATUM_FREQUENT_EXACT = model.OOD_STRATUM_FREQUENT_EXACT
STRATUM_RARE_EXACT = model.OOD_STRATUM_RARE_EXACT
STRATUM_EXACT_ABSENT_IN_DOMAIN = model.OOD_STRATUM_EXACT_ABSENT_IN_DOMAIN
STRATUM_EXACT_ABSENT_OUT_OF_DOMAIN = model.OOD_STRATUM_EXACT_ABSENT_OUT_OF_DOMAIN
STRATA: tuple[str, ...] = (
    STRATUM_FREQUENT_EXACT,
    STRATUM_RARE_EXACT,
    STRATUM_EXACT_ABSENT_IN_DOMAIN,
    STRATUM_EXACT_ABSENT_OUT_OF_DOMAIN,
)

#: Strata each route source is allowed to answer.
ROUTED_STRATA_OF_SOURCE: dict[str, tuple[str, ...]] = {
    ROUTE_SOURCE_ACTIVE: (STRATUM_FREQUENT_EXACT,),
    ROUTE_SOURCE_SPARSE: (STRATUM_RARE_EXACT, STRATUM_EXACT_ABSENT_IN_DOMAIN),
    ROUTE_SOURCE_ABSTAIN: (STRATUM_EXACT_ABSENT_OUT_OF_DOMAIN,),
}

#: Declared model identity of each route source (use ``none`` when abstaining).
DECLARED_MODEL_ID: dict[str, str] = {
    ROUTE_SOURCE_ACTIVE: "active_model_a_preflop_population",
    ROUTE_SOURCE_SPARSE: "generalized_adverse_response_candidate_v1",
    ROUTE_SOURCE_ABSTAIN: "none",
}

#: Preregistered support thresholds of the strata (reused from the #421 CV).
FREQUENT_EXACT_MIN_SUPPORT = model.OOD_FREQUENT_EXACT_MIN_SUPPORT
RARE_EXACT_MIN_SUPPORT = 1

#: Preregistered simplicity margin of the rule policy: the simplest rule whose
#: agreement with the reference rule stays within this share of the best.
RULE_SIMPLICITY_MARGIN = 0.02
DEFAULT_RULE_ID = "R2_SUPPORT_GATE"
REFERENCE_RULE_ID = "R2_SUPPORT_GATE"

#: The nine pre-action signals the spec names, in review order.
SIGNAL_IDS: tuple[str, ...] = (
    "support_exact",
    "support_feature_level",
    "distance_to_domain",
    "predictive_uncertainty",
    "extrapolation_sizing",
    "extrapolation_stack",
    "extrapolation_price",
    "family",
    "actor_position",
    "aggressor_position",
)

#: Every routing document carries these keys.
ROUTING_DOCUMENT_REQUIRED_KEYS: tuple[str, ...] = (
    "schema",
    "timing",
    "deterministic",
    "context_key",
    "route_source",
    "rule",
    "support_state",
    "uncertainty",
    "ood_status",
    "stratum",
    "reasons",
    "signals",
    "model_id",
    "model_hash",
    "probabilities",
    "selected_action",
    "sizing_provenance",
    "analysis_admissible",
    "no_nearest_price_substitution",
    "no_nearest_context_substitution",
)

TIMING_BEFORE_ACTION = "BEFORE_ACTION"

CANONICAL_DECIMALS = runtime.CANONICAL_DECIMALS
SIZING_TARGET_TOLERANCE = 1e-9

#: Declaration of the no-substitution contract (see the module docstring).
NO_NEAREST_PRICE_SUBSTITUTION = True
NO_NEAREST_CONTEXT_SUBSTITUTION = True
#: Runtime evidence that no substitution happened (never set to ``True``).
NEAREST_PRICE_SUBSTITUTED = False
NEAREST_CONTEXT_SUBSTITUTED = False

#: Machine-readable fail-closed codes.
FAIL_CLOSED_REFUSED_SPLIT = "REFUSED_SPLIT"
FAIL_CLOSED_CALIBRATION_INVALID = "CALIBRATION_INVALID"
FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION = "NEAREST_NEIGHBOUR_SUBSTITUTION_REFUSED"
FAIL_CLOSED_UNKNOWN_AXIS = "UNKNOWN_DOMAIN_AXIS"
FAIL_CLOSED_NO_LEGAL_MASS = "NO_LEGAL_PROBABILITY_MASS"
FAIL_CLOSED_MISSING_SIZING = "MISSING_SIZING_PROVENANCE"
FAIL_CLOSED_SIZING_TARGET = "SIZING_TARGET_MISMATCH"
FAIL_CLOSED_INVALID_MODEL_HASH = "INVALID_MODEL_HASH"

#: Hard / soft classification of every frozen reason code.
REASON_CLASS: dict[str, str] = {
    **{code: "hard" for code in model.OOD_HARD_REASONS},
    **{code: "soft" for code in model.OOD_SOFT_REASONS},
}

RouteDecider = Callable[[Mapping[str, Any]], str]
RouteChannel = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class RouterError(RuntimeError):
    """Fail-closed router error carrying a stable machine-readable ``code``."""

    code = "ROUTER_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class NeighbourSubstitutionRefused(RouterError):
    """A caller asked for a nearest-price / nearest-context substitution."""

    code = FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION


def canonical_float(value: Any, *, decimals: int = CANONICAL_DECIMALS) -> float | None:
    """Quantise one number on the fixed decimal grid (see the runtime module)."""
    return runtime.canonical_float(value, decimals=decimals)


def canonical_json(document: Any) -> str:
    """Byte-stable JSON of a JSON-shaped document (sorted keys, ASCII, no NaN)."""
    return json.dumps(document, sort_keys=True, ensure_ascii=True, allow_nan=False)


def canonical_sha256(document: Any) -> str:
    """SHA-256 of the byte-stable JSON of ``document``."""
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# calibration
# ---------------------------------------------------------------------------


def validate_calibration(calibration: Mapping[str, Any]) -> list[str]:
    """Minimal structural validation of an #421 OOD calibration document."""
    errors: list[str] = []
    if not isinstance(calibration, Mapping):
        return ["calibration must be a mapping"]
    for key in ("thresholds", "category_counts", "domain"):
        if not isinstance(calibration.get(key), Mapping):
            errors.append(f"calibration.{key} must be a mapping")
    for block in model.OOD_FEATURE_BLOCKS:
        counts = (calibration.get("category_counts") or {}).get(block)
        if not isinstance(counts, Mapping) or not counts:
            errors.append(f"calibration.category_counts.{block} must be a non-empty mapping")
    for axis in model.OOD_NUMERIC_AXES:
        if not isinstance((calibration.get("domain") or {}).get(axis), Mapping):
            errors.append(f"calibration.domain.{axis} must be a mapping")
    support = calibration.get("exact_context_support")
    if support is not None and not isinstance(support, Mapping):
        errors.append("calibration.exact_context_support must be a mapping when present")
    return errors


def resolve_calibration(calibration: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The supplied calibration, or the frozen #421 report's calibration."""
    resolved = (
        dict(calibration)
        if calibration is not None
        else model.load_ood_calibration(model.DEFAULT_OOD_REPORT_PATH)
    )
    errors = validate_calibration(resolved)
    if errors:
        raise RouterError(
            "invalid calibration: " + "; ".join(errors), code=FAIL_CLOSED_CALIBRATION_INVALID
        )
    return resolved


def _row_split(row: Mapping[str, Any]) -> str:
    raw = row.get("split")
    return str(raw).strip().upper() if raw is not None else ""


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


def build_calibration(
    rows: Iterable[Mapping[str, Any]],
    *,
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, TRAIN-only calibration document from raw rows.

    The builder mirrors the frozen #421 gate calibration: every row must belong
    to ``TRAIN`` (any other split is refused before a single count is taken),
    the categorical surface is the model's own ``ood_feature_levels``, the exact
    support is keyed by ``ood_exact_context_key`` and the numeric domain carries
    the trained envelope plus the 5% / 95% robust core of every axis.
    """
    materialized = list(rows)
    for row in materialized:
        split = _row_split(row)
        if split != "TRAIN":
            raise RouterError(
                "the router calibrates on TRAIN only; refused a "
                f"{split or '<EMPTY>'} row (VALIDATION and TEST are never consumed)",
                code=FAIL_CLOSED_REFUSED_SPLIT,
            )

    category_counts: dict[str, dict[str, int]] = {block: {} for block in model.OOD_FEATURE_BLOCKS}
    exact_context_support: dict[str, int] = {}
    observed: dict[str, list[float]] = {axis: [] for axis in model.OOD_NUMERIC_AXES}
    for row in materialized:
        for block, label in model.ood_feature_levels(row).items():
            category_counts[block][label] = category_counts[block].get(label, 0) + 1
        key = model.ood_exact_context_key(row)
        exact_context_support[key] = exact_context_support.get(key, 0) + 1
        for axis, value in model._ood_axis_values(row).items():  # noqa: SLF001 - same package
            if value is not None:
                observed[axis].append(float(value))

    domain: dict[str, dict[str, Any]] = {}
    for axis in model.OOD_NUMERIC_AXES:
        values = sorted(observed[axis])
        domain[axis] = {
            "observations": len(values),
            "trained_min": canonical_float(values[0]) if values else None,
            "trained_max": canonical_float(values[-1]) if values else None,
            "core_low": canonical_float(_quantile(values, model.OOD_LOW_TAIL)),
            "core_high": canonical_float(_quantile(values, model.OOD_HIGH_TAIL)),
            "spline_knot_max": None,
        }

    calibrated = dict(model.OOD_FALLBACK_THRESHOLDS)
    if thresholds:
        calibrated.update({key: float(value) for key, value in thresholds.items()})

    return {
        "schema": model.OOD_CALIBRATION_SCHEMA,
        "gate_schema": model.OOD_GATE_SCHEMA,
        "statuses": list(model.OOD_STATUSES),
        "reason_codes": list(model.OOD_REASON_ORDER),
        "feature_blocks": list(model.OOD_FEATURE_BLOCKS),
        "numeric_axes": list(model.OOD_NUMERIC_AXES),
        "exact_context_diagnostic_only": True,
        "thresholds": calibrated,
        "category_counts": category_counts,
        "exact_context_support": exact_context_support,
        "domain": domain,
        "provenance": {
            "module": str(_repo_relative(MODULE_PATH)),
            "rows": len(materialized),
            "consumed_splits": ["TRAIN"],
            "validation_consumed": False,
            "test_consumed": False,
        },
        "canonical_payload_sha256": None,
    }


def _repo_relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:  # pragma: no cover - a path outside the repository
        return str(path)


# ---------------------------------------------------------------------------
# exact (never nearest-neighbour) lookups
# ---------------------------------------------------------------------------


def exact_context_key(context: Mapping[str, Any]) -> str:
    """The exact context signature: the ordered single-feature node labels."""
    return model.ood_exact_context_key(context)


def resolve_support_exact(
    support_index: Mapping[str, int],
    key: str,
    *,
    allow_nearest_neighbour: bool = False,
) -> int:
    """Exact-only support lookup, refusing every neighbour substitution.

    ``support_index`` is the frozen ``exact_context_support`` mapping.  An
    absent key yields ``0``: the exact cell was never observed, which is a
    genuine signal, never a reason to read a neighbouring context's support.
    """
    if allow_nearest_neighbour:
        raise NeighbourSubstitutionRefused(
            "the router never substitutes a neighbouring context for the queried "
            f"exact context key {key!r}",
            code=FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION,
        )
    raw = support_index.get(key, 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def exact_context_support(
    context: Mapping[str, Any],
    calibration: Mapping[str, Any],
    *,
    allow_nearest_neighbour: bool = False,
) -> int:
    """Exact support of ``context``'s own signature in the frozen index."""
    index = calibration.get("exact_context_support") or {}
    return resolve_support_exact(
        index,
        exact_context_key(context),
        allow_nearest_neighbour=allow_nearest_neighbour,
    )


def resolve_numeric_axis(
    context: Mapping[str, Any],
    axis: str,
    *,
    allow_nearest_price: bool = False,
) -> float | None:
    """The exact queried value of one domain axis, or ``None`` when absent.

    The queried axis is read from its own context field.  A missing axis stays
    missing (``None``): the router never substitutes the nearest observed price
    or the value of a neighbouring axis.
    """
    if axis not in model.OOD_NUMERIC_AXES:
        raise RouterError(f"unknown domain axis: {axis}", code=FAIL_CLOSED_UNKNOWN_AXIS)
    if allow_nearest_price:
        raise NeighbourSubstitutionRefused(
            f"the router never substitutes a neighbouring price for the queried {axis!r}",
            code=FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION,
        )
    if axis != model.OOD_SIZING_AXIS:
        raw = context.get(axis)
        if raw is None:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None
    target = context.get("target_total_bb")
    if target is None:
        target = context.get("raise_target_total_bb")
    if target is None:
        return None
    try:
        queried = float(target)
    except (TypeError, ValueError):
        return None
    to_call = resolve_numeric_axis(context, "to_call_bb")
    pot = resolve_numeric_axis(context, "pot_before_bb")
    if not math.isfinite(queried) or to_call is None or pot is None:
        return None
    denominator = pot + to_call
    if denominator <= model.EPS:
        return None
    return min(max(queried, 0.0) / denominator, model.MAX_SIZING_RATIO)


# ---------------------------------------------------------------------------
# pre-action signals
# ---------------------------------------------------------------------------


def classify_stratum(support_exact: int, feature_in_domain: bool) -> str:
    """The frozen stratum of an exact support and an in-domain feature surface."""
    if support_exact >= FREQUENT_EXACT_MIN_SUPPORT:
        return STRATUM_FREQUENT_EXACT
    if support_exact >= RARE_EXACT_MIN_SUPPORT:
        return STRATUM_RARE_EXACT
    if feature_in_domain:
        return STRATUM_EXACT_ABSENT_IN_DOMAIN
    return STRATUM_EXACT_ABSENT_OUT_OF_DOMAIN


def compute_signals(
    context: Mapping[str, Any],
    *,
    calibration: Mapping[str, Any] | None = None,
    model_candidate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The deterministic pre-action signal bundle of one public context.

    ``model_candidate`` is the fitted generalized candidate, or ``None`` when
    the predictive-uncertainty family cannot be computed; in the latter case the
    frozen gate reports ``PREDICTIVE_UNCERTAINTY_UNAVAILABLE`` and the status
    can never be ``MODEL_SUPPORTED``.  Nothing here depends on the observed
    action or its result.
    """
    if not isinstance(context, Mapping):
        raise TypeError("context must be a mapping")
    resolved = resolve_calibration(calibration)
    gate = model.ood_gate_decision(model_candidate, context, calibration=resolved)
    raw = gate["signals"]

    key = raw["exact_context"]["signature"]
    support_exact = resolve_support_exact(
        resolved.get("exact_context_support") or {}, key
    )
    local_support = raw["local_support"]
    axes = raw["axes"]
    thresholds = resolved["thresholds"]
    predictive = raw["predictive_uncertainty"]

    distance_to_domain = float(raw["domain_distance"] or 0.0)
    extrapolation_sizing = bool(axes[model.OOD_SIZING_AXIS]["extrapolation"])
    extrapolation_stack = bool(axes["effective_stack_bb"]["extrapolation"])
    extrapolation_price = bool(
        axes["to_call_bb"]["extrapolation"] or axes["pot_before_bb"]["extrapolation"]
    )
    unseen_categories = dict(raw["unseen_categories"])
    feature_in_domain = not unseen_categories
    levels = dict(raw["feature_levels"])

    predictive_available = predictive is not None
    predictive_entropy_high = bool(
        predictive_available
        and float(predictive["normalized_entropy"])
        >= float(thresholds.get("normalized_entropy") or 0.0)
    )
    model_node_support_low = bool(
        predictive_available
        and float(predictive["model_node_support_per_row"])
        < float(thresholds.get("min_model_node_support_per_row") or 0.0)
    )
    domain_distance_high = distance_to_domain > float(thresholds.get("domain_distance") or 0.0)
    feature_support_low = float(local_support["min_feature_share"]) < float(
        thresholds.get("min_feature_share") or 0.0
    )

    signals: dict[str, Any] = {
        "context_key": key,
        "support_exact": support_exact,
        "support_feature_level": float(local_support["min_feature_share"]),
        "distance_to_domain": distance_to_domain,
        "predictive_uncertainty": predictive,
        "extrapolation_sizing": extrapolation_sizing,
        "extrapolation_stack": extrapolation_stack,
        "extrapolation_price": extrapolation_price,
        "family": levels.get("family"),
        "actor_position": levels.get("actor_position"),
        "aggressor_position": levels.get("aggressor_position"),
        "stratum": classify_stratum(support_exact, feature_in_domain),
        "feature_in_domain": feature_in_domain,
        "unseen_categories": unseen_categories,
        "hard_reasons": list(gate["hard_reasons"]),
        "soft_reasons": list(gate["soft_reasons"]),
        "reasons": list(gate["reasons"]),
        "ood_status": gate["status"],
        "detail": {
            "feature_support": dict(local_support["feature_support"]),
            "feature_share": dict(local_support["feature_share"]),
            "min_feature_block": local_support["min_feature_block"],
            "min_feature_support": local_support["min_feature_support"],
            "min_feature_share": float(local_support["min_feature_share"]),
            "exact_context": dict(raw["exact_context"]),
            "axes": {axis: dict(entry) for axis, entry in axes.items()},
            "thresholds": {
                name: float(thresholds.get(name) or 0.0)
                for name in sorted(model.OOD_FALLBACK_THRESHOLDS)
            },
            "uncertainty_flags": {
                "predictive_uncertainty_available": predictive_available,
                "predictive_entropy_high": predictive_entropy_high,
                "model_node_support_low": model_node_support_low,
                "domain_distance_high": domain_distance_high,
                "feature_support_low": feature_support_low,
            },
        },
        "timing": TIMING_BEFORE_ACTION,
        "deterministic": True,
        "computed_before_action": True,
        "uses_hidden_hand": False,
        "uses_observed_result": False,
        "no_nearest_price_substitution": NO_NEAREST_PRICE_SUBSTITUTION,
        "no_nearest_context_substitution": NO_NEAREST_CONTEXT_SUBSTITUTION,
    }
    signals["canonical_sha256"] = canonical_sha256(signals)
    return signals


def signal_digest(signals: Mapping[str, Any]) -> str:
    """Digest of a signal bundle with its own self-digest removed."""
    payload = {key: value for key, value in signals.items() if key != "canonical_sha256"}
    return canonical_sha256(payload)


# ---------------------------------------------------------------------------
# rule catalogue
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RouteRule:
    """A simple, explicable mapping from a signal bundle to a route source."""

    id: str
    complexity: int
    definition: str
    decide: RouteDecider
    requires: tuple[str, ...]

    def __call__(self, signals: Mapping[str, Any]) -> str:
        source = self.decide(signals)
        if source not in ROUTE_SOURCES:  # pragma: no cover - defensive invariant
            raise RouterError(f"rule {self.id} produced an unknown route source: {source!r}")
        return source

    def as_document(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "complexity": self.complexity,
            "definition": self.definition,
            "requires": list(self.requires),
        }


def _r1_hard_gate(signals: Mapping[str, Any]) -> str:
    if signals["hard_reasons"]:
        return ROUTE_SOURCE_ABSTAIN
    if int(signals["support_exact"]) >= FREQUENT_EXACT_MIN_SUPPORT:
        return ROUTE_SOURCE_ACTIVE
    return ROUTE_SOURCE_SPARSE


def _r2_support_gate(signals: Mapping[str, Any]) -> str:
    if signals["hard_reasons"]:
        return ROUTE_SOURCE_ABSTAIN
    if int(signals["support_exact"]) >= FREQUENT_EXACT_MIN_SUPPORT:
        return ROUTE_SOURCE_ACTIVE
    if signals["feature_in_domain"]:
        return ROUTE_SOURCE_SPARSE
    return ROUTE_SOURCE_ABSTAIN


def _r3_uncertainty_gate(signals: Mapping[str, Any]) -> str:
    if signals["hard_reasons"]:
        return ROUTE_SOURCE_ABSTAIN
    if int(signals["support_exact"]) >= FREQUENT_EXACT_MIN_SUPPORT:
        return ROUTE_SOURCE_ACTIVE
    if not signals["feature_in_domain"]:
        return ROUTE_SOURCE_ABSTAIN
    if signals["detail"]["uncertainty_flags"]["domain_distance_high"]:
        return ROUTE_SOURCE_ABSTAIN
    return ROUTE_SOURCE_SPARSE


ROUTE_RULES: tuple[RouteRule, ...] = (
    RouteRule(
        id="R1_HARD_GATE",
        complexity=1,
        definition=(
            "abstain on any hard OOD reason; answer from the active strong-support model "
            "when the exact context support reaches FREQUENT_EXACT_MIN_SUPPORT; otherwise "
            "use the generalized sparse channel"
        ),
        decide=_r1_hard_gate,
        requires=("hard_reasons", "support_exact"),
    ),
    RouteRule(
        id="R2_SUPPORT_GATE",
        complexity=2,
        definition=(
            "the frozen preregistered table: abstain on any hard OOD reason; answer from "
            "the active model on strong exact support; use the sparse channel only when "
            "every single-feature label stays in domain; abstain otherwise"
        ),
        decide=_r2_support_gate,
        requires=("hard_reasons", "support_exact", "feature_in_domain"),
    ),
    RouteRule(
        id="R3_UNCERTAINTY_GATE",
        complexity=3,
        definition=(
            "as R2, but a sparse context whose robust distance to the calibrated numeric "
            "core exceeds the calibrated tail abstains instead of being answered"
        ),
        decide=_r3_uncertainty_gate,
        requires=("hard_reasons", "support_exact", "feature_in_domain", "distance_to_domain"),
    ),
)

ROUTE_RULE_BY_ID: dict[str, RouteRule] = {rule.id: rule for rule in ROUTE_RULES}


def route_rule(rule: str | RouteRule | None = None) -> RouteRule:
    """Resolve a rule reference to a :class:`RouteRule`."""
    if rule is None:
        return ROUTE_RULE_BY_ID[DEFAULT_RULE_ID]
    if isinstance(rule, RouteRule):
        return rule
    resolved = ROUTE_RULE_BY_ID.get(str(rule))
    if resolved is None:
        raise RouterError(f"unknown route rule: {rule!r}")
    return resolved


def route_source(signals: Mapping[str, Any], *, rule: str | RouteRule | None = None) -> str:
    """The route source of a signal bundle under one rule (default: the reference)."""
    return route_rule(rule)(signals)


def evaluate_rule(
    rule: str | RouteRule,
    probe_signals: Sequence[Mapping[str, Any]],
    *,
    reference_rule: str | RouteRule | None = None,
) -> dict[str, Any]:
    """Agreement of one rule with the reference rule over a probe set."""
    resolved = route_rule(rule)
    reference = route_rule(reference_rule or REFERENCE_RULE_ID)
    agreements = 0
    disagreements: list[dict[str, Any]] = []
    for position, signals in enumerate(probe_signals):
        decided = resolved(signals)
        expected = reference(signals)
        if decided == expected:
            agreements += 1
        else:
            disagreements.append(
                {
                    "probe": position,
                    "context_key": signals.get("context_key"),
                    "rule": decided,
                    "reference": expected,
                }
            )
    total = len(probe_signals)
    return {
        "rule_id": resolved.id,
        "complexity": resolved.complexity,
        "agreement": (agreements / total) if total else 0.0,
        "agreements": agreements,
        "probes": total,
        "disagreements": disagreements,
    }


def select_rule(
    probe_signals: Sequence[Mapping[str, Any]],
    *,
    margin: float = RULE_SIMPLICITY_MARGIN,
    reference_rule: str | RouteRule | None = None,
) -> dict[str, Any]:
    """The simplicity policy: simplest rule within ``margin`` of the best agreement.

    Every rule of :data:`ROUTE_RULES` is measured against the reference rule and
    the lowest-complexity rule whose agreement stays within ``margin`` of the
    best observed agreement is kept.  Ordering is deterministic: complexity
    first, then the declaration order of :data:`ROUTE_RULES`.
    """
    if not probe_signals:
        raise RouterError("rule selection needs at least one probe")
    evaluations = [
        evaluate_rule(rule, probe_signals, reference_rule=reference_rule)
        for rule in ROUTE_RULES
    ]
    best = max(item["agreement"] for item in evaluations)
    threshold = best - max(float(margin), 0.0)
    eligible = [item for item in evaluations if item["agreement"] >= threshold]
    eligible.sort(key=lambda item: (item["complexity"], item["rule_id"]))
    chosen = eligible[0]
    return {
        "rule_id": chosen["rule_id"],
        "complexity": chosen["complexity"],
        "agreement": chosen["agreement"],
        "best_agreement": best,
        "margin": float(margin),
        "reference_rule_id": route_rule(reference_rule or REFERENCE_RULE_ID).id,
        "rationale": (
            "simplest declared rule whose agreement with the reference rule stays "
            f"within the simplicity margin {float(margin):.6g} of the best observed agreement"
        ),
        "evaluations": evaluations,
    }


# ---------------------------------------------------------------------------
# channel answers: legality, masking, sizing provenance
# ---------------------------------------------------------------------------


def legal_response_actions(context: Mapping[str, Any]) -> list[str]:
    """The legal response actions of a public context, in the frozen engine order.

    The masking surface is the *engine* surface, not a router-local one: an
    explicit ``legal_actions`` list is authoritative, and otherwise legality is
    derived by the frozen #421 model from the public pre-action features.  The
    router never widens or narrows the legal space the channel was fitted on.
    """
    return model.legal_response_actions(context)


def queried_sizing_target(context: Mapping[str, Any]) -> float | None:
    """The exact raise target the caller queried, or ``None``."""
    return _queried_target(context)


def _queried_target(context: Mapping[str, Any]) -> float | None:
    raw = context.get("target_total_bb")
    if raw is None:
        raw = context.get("raise_target_total_bb")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def canonical_legal_distribution(
    probabilities: Mapping[str, Any], legal: Sequence[str]
) -> tuple[dict[str, float], float, float]:
    """Quantised, re-closed legal distribution (delegates to the #421 runtime)."""
    return runtime.canonical_legal_distribution(probabilities, legal)


def _validate_model_hash(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise RouterError(
            "model_hash must be a 64-character lowercase sha256 digest",
            code=FAIL_CLOSED_INVALID_MODEL_HASH,
        )
    return text


def attach_channel_answer(
    context: Mapping[str, Any],
    *,
    route_source: str,
    channel: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one channel answer and return its canonical, legal distribution.

    The probability vector is masked to the context's legal actions and
    re-closed on the runtime's canonical grid.  An aggressive answer must carry
    a sizing provenance whose target is the **exact** queried target: a
    provenance that declares ``no_nearest_price_substitution`` false, or that
    reports a different target, fails closed.
    """
    legal = legal_response_actions(context)
    declared_mass = math.fsum(
        max(0.0, float(raw))
        for action, raw in (channel.get("probabilities") or {}).items()
        if action in set(legal) and isinstance(raw, (int, float)) and math.isfinite(float(raw))
    )
    if declared_mass <= 0.0:
        raise RouterError(
            f"the {route_source} channel emitted no legal probability mass",
            code=FAIL_CLOSED_NO_LEGAL_MASS,
        )
    vector, probability_sum, illegal_mass = canonical_legal_distribution(
        channel.get("probabilities") or {}, legal
    )
    if probability_sum <= 0.0:
        raise RouterError(
            f"the {route_source} channel emitted no legal probability mass",
            code=FAIL_CLOSED_NO_LEGAL_MASS,
        )
    selected = max(legal, key=lambda action: (vector[action], -model.ACTIONS.index(action)))
    sizing_provenance: dict[str, Any] | None = None
    if selected in model.AGGRESSIVE_ACTIONS:
        provenance = channel.get("sizing_provenance")
        if not isinstance(provenance, Mapping):
            raise RouterError(
                f"the {route_source} channel selected {selected} without a sizing provenance",
                code=FAIL_CLOSED_MISSING_SIZING,
            )
        if provenance.get("no_nearest_price_substitution") is not True:
            raise NeighbourSubstitutionRefused(
                f"the {route_source} channel sizing provenance does not refuse a nearest-price "
                "substitution",
                code=FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION,
            )
        target = provenance.get("target_total_bb")
        if target is None:
            raise RouterError(
                f"the {route_source} channel sizing provenance carries no target_total_bb",
                code=FAIL_CLOSED_MISSING_SIZING,
            )
        queried = _queried_target(context)
        if queried is not None and abs(float(target) - queried) > SIZING_TARGET_TOLERANCE:
            raise RouterError(
                "the sizing provenance target "
                f"{float(target)!r} differs from the queried target {queried!r}: a "
                "neighbouring target is never substituted",
                code=FAIL_CLOSED_SIZING_TARGET,
            )
        sizing_provenance = dict(provenance)
    return {
        "probabilities": dict(vector),
        "probability_sum": probability_sum,
        "illegal_mass": illegal_mass,
        "legal_actions": legal,
        "selected_action": selected,
        "sizing_provenance": sizing_provenance,
        "model_id": str(
            channel.get("model_id") or DECLARED_MODEL_ID.get(route_source, "unknown")
        ),
        "model_hash": _validate_model_hash(channel.get("model_hash")),
    }


# ---------------------------------------------------------------------------
# routing document
# ---------------------------------------------------------------------------


def _request_view(context: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "family",
        "actor_position",
        "aggressor_position",
        "caller_count",
        "limper_count",
        "raise_level",
        "to_call_bb",
        "pot_before_bb",
        "effective_stack_bb",
        "target_total_bb",
    )
    return {field: context.get(field) for field in fields}


def route(
    context: Mapping[str, Any],
    *,
    calibration: Mapping[str, Any] | None = None,
    model_candidate: Mapping[str, Any] | None = None,
    rule: str | RouteRule | None = None,
    channels: Mapping[str, RouteChannel] | None = None,
) -> dict[str, Any]:
    """Route one public request and emit the routing document.

    ``channels`` maps a route source to a callable returning that channel's
    answer (``model_id``, ``model_hash``, ``probabilities`` and, for an
    aggressive answer, ``sizing_provenance``).  When no channel is supplied the
    document still carries the full routing decision and reports
    ``analysis_admissible=False``: routing and probabilities are separate
    surfaces, and the router never invents a distribution.
    """
    resolved_rule = route_rule(rule)
    signals = compute_signals(
        context, calibration=calibration, model_candidate=model_candidate
    )
    source = resolved_rule(signals)

    answer: dict[str, Any] | None = None
    model_id = DECLARED_MODEL_ID[source]
    model_hash: str | None = None
    probabilities: dict[str, float] | None = None
    selected_action: str | None = None
    sizing_provenance: dict[str, Any] | None = None
    if source != ROUTE_SOURCE_ABSTAIN:
        channel = (channels or {}).get(source)
        if channel is not None:
            answer = attach_channel_answer(
                context, route_source=source, channel=channel(context)
            )
            model_id = answer["model_id"]
            model_hash = answer["model_hash"]
            probabilities = answer["probabilities"]
            selected_action = answer["selected_action"]
            sizing_provenance = answer["sizing_provenance"]

    analysis_admissible = bool(
        source != ROUTE_SOURCE_ABSTAIN
        and probabilities is not None
        and (selected_action not in model.AGGRESSIVE_ACTIONS or sizing_provenance is not None)
    )

    document: dict[str, Any] = {
        "schema": ROUTING_DOCUMENT_SCHEMA,
        "contract_schema": ROUTING_CONTRACT_SCHEMA,
        "timing": TIMING_BEFORE_ACTION,
        "deterministic": True,
        "uses_hidden_hand": False,
        "uses_observed_result": False,
        "no_nearest_price_substitution": NO_NEAREST_PRICE_SUBSTITUTION,
        "no_nearest_context_substitution": NO_NEAREST_CONTEXT_SUBSTITUTION,
        "context_key": signals["context_key"],
        "request": _request_view(context),
        "route_source": source,
        "rule": resolved_rule.as_document(),
        "support_state": SUPPORT_STATE_OF_ROUTE[source],
        "uncertainty": "HIGH" if signals["soft_reasons"] else "NONE",
        "ood_status": signals["ood_status"],
        "stratum": signals["stratum"],
        "routed_strata": list(ROUTED_STRATA_OF_SOURCE[source]),
        "reasons": {
            "hard": list(signals["hard_reasons"]),
            "soft": list(signals["soft_reasons"]),
            "all": list(signals["reasons"]),
            "catalog": {code: REASON_CLASS[code] for code in signals["reasons"]},
        },
        "signals": signals,
        "model_id": model_id,
        "model_hash": model_hash,
        "probabilities": probabilities,
        "selected_action": selected_action,
        "sizing_provenance": sizing_provenance,
        "analysis_admissible": analysis_admissible,
        "abstain": source == ROUTE_SOURCE_ABSTAIN,
        "channel": (
            {
                "probability_sum": answer["probability_sum"],
                "illegal_mass": answer["illegal_mass"],
                "legal_actions": answer["legal_actions"],
            }
            if answer
            else None
        ),
    }
    document["decision_canonical_sha256"] = canonical_sha256(document)
    return document


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Route one preflop adverse-response request (#423 hybrid router)."
    )
    parser.add_argument("--context", required=True, help="path to a JSON context file")
    parser.add_argument(
        "--calibration",
        default=None,
        help="path to an OOD calibration report (default: frozen #421 report)",
    )
    parser.add_argument("--rule", default=DEFAULT_RULE_ID, help="route rule id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    context = json.loads(Path(args.context).read_text(encoding="utf-8"))
    calibration = (
        model.load_ood_calibration(args.calibration) if args.calibration else None
    )
    document = route(context, calibration=calibration, rule=args.rule)
    print(canonical_json(document))
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
