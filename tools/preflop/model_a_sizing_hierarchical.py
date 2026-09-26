#!/usr/bin/env python3
"""Hierarchical exact-context Model-A preflop sizing likelihood candidate.

Candidate-only implementation of the frozen #419 spec
(``analysis/issue419_hierarchical_tree/HIERARCHICAL_MODEL_SPEC.json``).  It adds
the identity ``model-a-preflop-sizing-hierarchical-candidate-v1``, which is
distinct from the ``...-candidate-v1``/``...-v2`` exact-price candidates and is
never active.

Contract highlights
-------------------
* Identity *and* support granularity is ``hierarchical_exact_key`` (L0), the
  byte-identical composition of the #388/#419 ``audit_exact_key``.
* Pooling only ever changes the *parameters*: support counts (observations,
  distinct hands, effective sample size) are computed exclusively from rows
  whose ``hierarchical_exact_key`` equals the requested key
  (``SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT``).
* Status is one of ``EXACT_EMPIRICAL_STRONG`` / ``EXACT_HIERARCHICAL_ESTIMATE``
  / ``EXACT_UNRESOLVED``.  Every hierarchical estimate reports a Dirichlet
  marginal uncertainty band at the level actually used; it is mandatory.
* Fail-closed: no admissible support/pooling raises, a support source that is
  not the requested key raises ``COARSE_KEY_SUPPORT_LAUNDERING``, an exact
  claim whose pooling level is not L0 raises, and an unresolved raise sizing
  frontier stays ``EXACT_UNRESOLVED``.
* There is no nearest-price and no nearest-context substitution.  Lookup is
  exact string equality on the requested key.
* No private or future information may appear in keys, features or reasons.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from tools.preflop.context_contract import EPS, normalize_history
from tools.preflop.model_a_sizing_likelihood import (
    CANDIDATE_IDS as EXACT_PRICE_CANDIDATE_IDS,
    support_context_key,
)
from tools.preflop.policy_context import STACK_BUCKETS, stack_bucket

SCHEMA = "poker-model-a-preflop-sizing-hierarchical-likelihood/v1"
RESPONSE_SCHEMA = "poker-hierarchical-support-response/v1"
HIERARCHY_SPEC_SCHEMA = "poker-hierarchical-exact-context-model-spec/v1"
PUBLIC_CONTEXT_SCHEMA = "poker-model-a-preflop-sizing-public-context/v1"

CANDIDATE_ID = "model-a-preflop-sizing-hierarchical-candidate-v1"
CANDIDATE_IDS = (CANDIDATE_ID,)
MODEL_FAMILY = "MODEL_A_PREFLOP"
CANDIDATE_STATUS = "CANDIDATE_ONLY_NOT_ACTIVE"
EXACT_GRANULARITY = "hierarchical_exact_key"
SUPPORT_LEVEL = "L0_EXACT_KEY"
SUPPORT_ISOLATION_RULE = "SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT"
SUPPORT_LAUNDERING_REASON = "COARSE_KEY_SUPPORT_LAUNDERING"

POOLING_LEVELS = (
    "L0_EXACT_KEY",
    "L1_STACK_POOL",
    "L2_POT_POOL",
    "L3_RUNTIME_SUPPORT_CONTEXT",
    "L4_POSITION_PRICE_PRIOR",
)

STATUS_EXACT_EMPIRICAL_STRONG = "EXACT_EMPIRICAL_STRONG"
STATUS_EXACT_HIERARCHICAL_ESTIMATE = "EXACT_HIERARCHICAL_ESTIMATE"
STATUS_EXACT_UNRESOLVED = "EXACT_UNRESOLVED"
STATUSES = (
    STATUS_EXACT_EMPIRICAL_STRONG,
    STATUS_EXACT_HIERARCHICAL_ESTIMATE,
    STATUS_EXACT_UNRESOLVED,
)

REASON_NO_ADMISSIBLE_POOLING = "NO_ADMISSIBLE_POOLING_LEVEL"
REASON_RAISE_SIZING_UNRESOLVED = "RAISE_SIZING_UNRESOLVED_NO_NEAREST_PRICE"
REASON_NO_EXACT_SUPPORT_NO_CONTEXT = "NO_EXACT_SUPPORT_AND_NO_CONTEXT"

# Two-layer provider contract.  Layer A is the exact empirical support of the
# requested key; layer B is the exact-context estimate admissibility.  The
# layer-B gate ids and reason codes are byte-identical to the frozen T1
# vocabulary (``FROZEN_VALIDATION_PROTOCOL_V2.json#layers.layer_b_*``), so a
# response can be audited per gate without re-deriving the protocol.
LAYER_A_EXACT_EMPIRICAL_SUPPORT = "A_EXACT_EMPIRICAL_SUPPORT"
LAYER_B_EXACT_CONTEXT_ESTIMATE_ADMISSIBILITY = (
    "B_EXACT_CONTEXT_ESTIMATE_ADMISSIBILITY"
)
NODE_CLOSURE_RULE_ID = "NODE_CLOSES_IFF_ALL_FROZEN_LAYER_B_GATES_PASS"

GATE_EXACT_KEY_IDENTITY = "EXACT_KEY_IDENTITY"
GATE_POOLING_PROVENANCE = "POOLING_PROVENANCE"
GATE_POOLING_LEVEL = "POOLING_LEVEL"
GATE_EFFECTIVE_SAMPLE_SIZE = "EFFECTIVE_SAMPLE_SIZE"
GATE_UNCERTAINTY = "UNCERTAINTY"
GATE_CALIBRATION = "CALIBRATION"
GATE_RAISE_SIZING_FRONTIER = "RAISE_SIZING_FRONTIER"

# ``(order, gate_id, reason_code, applies_to)`` for the seven frozen layer-B
# gates.  ``applies_to`` mirrors the protocol: ``POOLING_PROVENANCE`` gates the
# estimate only, every other gate gates both answered statuses.
LAYER_B_GATES: tuple[tuple[int, str, str, tuple[str, ...]], ...] = (
    (
        1,
        GATE_EXACT_KEY_IDENTITY,
        "REFUSED_EXACT_KEY_IDENTITY",
        (STATUS_EXACT_EMPIRICAL_STRONG, STATUS_EXACT_HIERARCHICAL_ESTIMATE),
    ),
    (2, GATE_POOLING_PROVENANCE, "REFUSED_POOLING_PROVENANCE", (STATUS_EXACT_HIERARCHICAL_ESTIMATE,)),
    (
        3,
        GATE_POOLING_LEVEL,
        "REFUSED_POOLING_LEVEL",
        (STATUS_EXACT_EMPIRICAL_STRONG, STATUS_EXACT_HIERARCHICAL_ESTIMATE),
    ),
    (
        4,
        GATE_EFFECTIVE_SAMPLE_SIZE,
        "REFUSED_EFFECTIVE_SAMPLE_SIZE",
        (STATUS_EXACT_EMPIRICAL_STRONG, STATUS_EXACT_HIERARCHICAL_ESTIMATE),
    ),
    (
        5,
        GATE_UNCERTAINTY,
        "REFUSED_UNCERTAINTY",
        (STATUS_EXACT_EMPIRICAL_STRONG, STATUS_EXACT_HIERARCHICAL_ESTIMATE),
    ),
    (
        6,
        GATE_CALIBRATION,
        "REFUSED_CALIBRATION",
        (STATUS_EXACT_EMPIRICAL_STRONG, STATUS_EXACT_HIERARCHICAL_ESTIMATE),
    ),
    (
        7,
        GATE_RAISE_SIZING_FRONTIER,
        "REFUSED_RAISE_SIZING_FRONTIER",
        (STATUS_EXACT_EMPIRICAL_STRONG, STATUS_EXACT_HIERARCHICAL_ESTIMATE),
    ),
)
GATE_REASON_BY_ID = {gate_id: reason for _, gate_id, reason, _ in LAYER_B_GATES}
GATE_ORDER_BY_ID = {gate_id: order for order, gate_id, _, _ in LAYER_B_GATES}

# Frozen thresholds: they are never lowered to close the tree.
MIN_MARGINAL_OBSERVATIONS = 20
MIN_DISTINCT_HANDS = 20

# Frozen shrinkage: kappa0 = 16 with alpha = 0.5 per legal marginal action
# reproduces the pinned #352/#388 prospective_shrinkage rule.
KAPPA0 = 16.0
ALPHA_PER_LEGAL_ACTION = 0.5
PARENT_DOMINATED_FLAG_BELOW = 0.5
DEFAULT_UNCERTAINTY_LEVEL = 0.9

RESPONSES = ("FOLD", "CALL", "RAISE", "JAM", "CHECK")
STACK_BUCKET_LABELS = tuple(label for _, label in STACK_BUCKETS)

ALL_AXES = (
    "requested_key_identity",
    "actor_position",
    "aggressor_position",
    "target_total_bb",
    "to_call_bb",
    "effective_stack_bucket",
    "pot_before_bb",
    "history",
    "live_positions",
    "all_in_positions",
    "table_size",
    "raise_level",
    "limper_count",
    "caller_count",
    "family",
)
NEVER_MUTUALIZABLE_AXES = (
    "requested_key_identity",
    "actor_position",
    "aggressor_position",
    "target_total_bb",
    "to_call_bb",
)
MUTUALIZABLE_AXES = tuple(
    axis for axis in ALL_AXES if axis not in NEVER_MUTUALIZABLE_AXES
)
WHITELIST_AXES = tuple(axis for axis in ALL_AXES if axis != "requested_key_identity")

# The requested key identity is the *question* being answered, not a pooling
# dimension: it is retained semantically on every level (a parent never answers
# a different question) while the level key is composed from the retained axes
# below.  The never-mutualizable axes are part of every level key.
_LEVEL_DROPS = {
    "L0_EXACT_KEY": (),
    "L1_STACK_POOL": ("effective_stack_bucket",),
    "L2_POT_POOL": ("effective_stack_bucket", "pot_before_bb"),
    "L3_RUNTIME_SUPPORT_CONTEXT": (
        "effective_stack_bucket",
        "pot_before_bb",
        "history",
        "live_positions",
        "all_in_positions",
        "table_size",
        "raise_level",
    ),
    "L4_POSITION_PRICE_PRIOR": (
        "effective_stack_bucket",
        "pot_before_bb",
        "history",
        "live_positions",
        "all_in_positions",
        "table_size",
        "raise_level",
        "limper_count",
        "caller_count",
        "family",
    ),
}
_LEVEL_PURPOSE = {
    "L0_EXACT_KEY": "SUPPORT_AND_IDENTITY",
    "L1_STACK_POOL": "PARAMETERS_ONLY",
    "L2_POT_POOL": "PARAMETERS_ONLY",
    "L3_RUNTIME_SUPPORT_CONTEXT": "PARAMETERS_ONLY",
    "L4_POSITION_PRICE_PRIOR": "LAST_RESORT_PARAMETERS_ONLY",
}

LEVEL_SPECS: tuple[dict[str, Any], ...] = tuple(
    {
        "level": level,
        "rank": rank,
        "purpose": _LEVEL_PURPOSE[level],
        "drops": list(_LEVEL_DROPS[level]),
        "retains": [axis for axis in ALL_AXES if axis not in _LEVEL_DROPS[level]],
        "support_source_allowed": level == SUPPORT_LEVEL,
        "equals_runtime_provider_key": level == "L3_RUNTIME_SUPPORT_CONTEXT",
        # The level key composition: retained axes minus the answer identity,
        # always including the frozen never-mutualizable axes.
        "key_axes": [
            axis
            for axis in ALL_AXES
            if axis not in _LEVEL_DROPS[level] and axis != "requested_key_identity"
        ],
    }
    for rank, level in enumerate(POOLING_LEVELS)
)
LEVEL_SPEC_BY_NAME = {spec["level"]: spec for spec in LEVEL_SPECS}

SENSITIVE_TOKENS = (
    "hole",
    "cards",
    "board",
    "showdown",
    "future",
    "opponent_private",
    "known_cards",
)


class HierarchicalSizingError(RuntimeError):
    """Fail-closed hierarchical resolution error."""


class SupportIsolationError(HierarchicalSizingError):
    """Support was (or would be) declared from a different key."""

    reason_code = SUPPORT_LAUNDERING_REASON

    def __init__(self, message: str) -> None:
        super().__init__(f"{SUPPORT_LAUNDERING_REASON}: {message}")


def stable_hash(value: Any) -> str:
    """Byte-identical to the #388/#419 ``stable_hash``."""
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(token in normalized for token in SENSITIVE_TOKENS):
                return True
            if _contains_sensitive_key(child):
                return True
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_sensitive_key(child) for child in value)
    return False


def _finite_nonnegative(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise HierarchicalSizingError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or number < -EPS:
        raise HierarchicalSizingError(f"{field} must be finite and non-negative")
    return round(max(0.0, number), 6)


def _int_nonnegative(value: Any, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise HierarchicalSizingError(f"{field} must be an integer") from exc
    if number < 0:
        raise HierarchicalSizingError(f"{field} must be non-negative")
    return number


def normalize_action(action: Any) -> str:
    text = str(action or "").upper()
    return "CALL" if text == "LIMP" else text


def _history_rows(history: Any) -> list[dict[str, str]]:
    return [
        {"position": row["position"], "action": row["action"]}
        for row in normalize_history(history)
    ]


def _history_features(history: Sequence[Mapping[str, Any]]) -> tuple[str | None, int, int]:
    """Byte-identical to ``audit_preflop_sizing_support.history_features``."""
    first_raise = next(
        (index for index, row in enumerate(history) if row.get("action") in {"RAISE", "JAM"}),
        None,
    )
    end = len(history) if first_raise is None else first_raise
    limpers = sum(1 for row in history[:end] if row.get("action") == "LIMP")
    callers = (
        0
        if first_raise is None
        else sum(1 for row in history[first_raise + 1 :] if row.get("action") == "CALL")
    )
    aggressors = [
        str(row.get("position") or "")
        for row in history
        if row.get("action") in {"RAISE", "JAM"}
    ]
    return (aggressors[-1] if aggressors else None), limpers, callers


def hierarchical_public_whitelist(context: Mapping[str, Any]) -> dict[str, Any]:
    """Explicit public whitelist, byte-identical to the #388 ``public_context``.

    Reveals are labels only: nothing here may carry cards, future action or any
    opponent-private information.
    """
    if not isinstance(context, Mapping):
        raise HierarchicalSizingError("context must be a mapping")
    if _contains_sensitive_key(context):
        raise HierarchicalSizingError(
            "private/future card information is forbidden in the public whitelist"
        )
    history = _history_rows(context.get("history"))
    aggressor, limpers, callers = _history_features(history)
    target_raw = context.get("current_price_bb", context.get("target_total_bb"))
    if target_raw is None:
        raise HierarchicalSizingError(
            "current_price_bb/target_total_bb is required for the exact key"
        )
    if "effective_stack_bb" not in context:
        raise HierarchicalSizingError(
            "effective_stack_bb is required for the exact key"
        )
    if "to_call_bb" not in context:
        raise HierarchicalSizingError("to_call_bb is required for the exact key")
    whitelist = {
        "family": str(context.get("family") or ""),
        "actor_position": str(context.get("actor_position") or ""),
        "aggressor_position": aggressor,
        "limper_count": _int_nonnegative(limpers, "limper_count"),
        "caller_count": _int_nonnegative(callers, "caller_count"),
        "target_total_bb": _finite_nonnegative(target_raw, "target_total_bb"),
        "to_call_bb": _finite_nonnegative(context["to_call_bb"], "to_call_bb"),
        "table_size": _int_nonnegative(context.get("table_size"), "table_size"),
        "raise_level": _int_nonnegative(context.get("raise_level", 0), "raise_level"),
        "live_positions": sorted(str(p) for p in context.get("live_positions") or []),
        "all_in_positions": sorted(str(p) for p in context.get("all_in_positions") or []),
        "history": history,
        "pot_before_bb": _finite_nonnegative(context.get("pot_before_bb", 0.0), "pot_before_bb"),
        "effective_stack_bucket": stack_bucket(context["effective_stack_bb"]),
    }
    if not whitelist["family"] or not whitelist["actor_position"]:
        raise HierarchicalSizingError("family and actor_position are required")
    if whitelist["table_size"] < 2:
        raise HierarchicalSizingError("table_size must be at least 2")
    return whitelist


def validate_whitelist(whitelist: Mapping[str, Any]) -> None:
    if not isinstance(whitelist, Mapping):
        raise HierarchicalSizingError("public whitelist must be a mapping")
    if _contains_sensitive_key(whitelist):
        raise HierarchicalSizingError("private/future information is forbidden")
    missing = [axis for axis in WHITELIST_AXES if axis not in whitelist]
    if missing:
        raise HierarchicalSizingError(
            "public whitelist missing axes: " + ", ".join(missing)
        )
    extra = [axis for axis in whitelist if axis not in WHITELIST_AXES]
    if extra:
        raise HierarchicalSizingError(
            "public whitelist has non-contract axes: " + ", ".join(sorted(extra))
        )
    if whitelist["effective_stack_bucket"] not in STACK_BUCKET_LABELS:
        raise HierarchicalSizingError("effective_stack_bucket is not a frozen v1 bucket")
    if not str(whitelist["family"]) or not str(whitelist["actor_position"]):
        raise HierarchicalSizingError("family and actor_position are required")
    for field in ("target_total_bb", "to_call_bb", "pot_before_bb"):
        _finite_nonnegative(whitelist[field], field)
    for field in ("limper_count", "caller_count", "table_size", "raise_level"):
        _int_nonnegative(whitelist[field], field)
    for position in list(whitelist["live_positions"]) + list(whitelist["all_in_positions"]):
        if not isinstance(position, str) or not position:
            raise HierarchicalSizingError("positions must be non-empty strings")
    for row in whitelist["history"]:
        if not isinstance(row, Mapping) or "position" not in row or "action" not in row:
            raise HierarchicalSizingError("history rows need position and action")
        if normalize_action(row["action"]) not in RESPONSES:
            raise HierarchicalSizingError(f"unknown history action: {row['action']!r}")


def _support_context_key_from_whitelist(whitelist: Mapping[str, Any]) -> str:
    """The runtime provider key (L3) computed from the whitelist."""
    return support_context_key(
        {
            "family": whitelist["family"],
            "actor_position": whitelist["actor_position"],
            "aggressor_position": whitelist["aggressor_position"],
            "limper_count": whitelist["limper_count"],
            "caller_count": whitelist["caller_count"],
            "target_total_bb": whitelist["target_total_bb"],
            "to_call_bb": whitelist["to_call_bb"],
        }
    )


def as_whitelist(obj: Mapping[str, Any]) -> dict[str, Any]:
    """Accept either an explicit whitelist or a live public context."""
    if not isinstance(obj, Mapping):
        raise HierarchicalSizingError("expected a whitelist or a public context")
    if "effective_stack_bucket" in obj and "effective_stack_bb" not in obj:
        whitelist = dict(obj)
        validate_whitelist(whitelist)
        return whitelist
    return hierarchical_public_whitelist(obj)


def hierarchical_exact_key_from_whitelist(whitelist: Mapping[str, Any]) -> str:
    """``hierarchical_exact_key`` from an explicit public whitelist."""
    validate_whitelist(whitelist)
    return _support_context_key_from_whitelist(whitelist) + "|public=" + stable_hash(whitelist)


def hierarchical_exact_key(context: Mapping[str, Any]) -> str:
    """Exact L0 requested key for a live public context."""
    return hierarchical_exact_key_from_whitelist(hierarchical_public_whitelist(context))


def runtime_exact_preflop_node_key(whitelist: Mapping[str, Any]) -> str:
    """Structural raise-sizing identity, byte-identical to the #388 audit."""
    whitelist = as_whitelist(whitelist)
    projected = {
        "actor_position": str(whitelist["actor_position"]),
        "table_size": int(whitelist["table_size"]),
        "raise_level": int(whitelist["raise_level"]),
        "family": str(whitelist["family"]),
        "live_positions": list(whitelist["live_positions"]),
        "all_in_positions": list(whitelist["all_in_positions"]),
        "history": [
            {"position": str(row["position"]), "action": str(row["action"])}
            for row in whitelist["history"]
        ],
    }
    return "MAPNODE_" + stable_hash(projected)


def level_key(level: str, whitelist: Mapping[str, Any]) -> str:
    """Deterministic pooling-level key; equality is exact string equality."""
    spec = LEVEL_SPEC_BY_NAME.get(level)
    if spec is None:
        raise HierarchicalSizingError(f"unknown pooling level: {level}")
    whitelist = as_whitelist(whitelist)
    if level == SUPPORT_LEVEL:
        return hierarchical_exact_key_from_whitelist(whitelist)
    if spec["equals_runtime_provider_key"]:
        return _support_context_key_from_whitelist(whitelist)
    payload = {axis: whitelist[axis] for axis in spec["key_axes"]}
    return f"LEVELKEY_{spec['rank']}_{stable_hash(payload)}"


def level_keys(whitelist: Mapping[str, Any]) -> dict[str, str]:
    whitelist = as_whitelist(whitelist)
    return {level: level_key(level, whitelist) for level in POOLING_LEVELS}


def candidate_identity(
    *,
    population_id: str,
    fit_scope: str = "SCAFFOLD_ONLY_NO_FINAL_FIT",
    data_scope: str = "SYNTHETIC_OR_TRAIN_ONLY",
    source_report_hash: str | None = None,
    hierarchy_spec_sha256: str | None = None,
) -> dict[str, Any]:
    if not population_id:
        raise HierarchicalSizingError("population_id is required")
    if CANDIDATE_ID in EXACT_PRICE_CANDIDATE_IDS:
        raise HierarchicalSizingError("hierarchical candidate id must be distinct")
    identity = {
        "candidate_id": CANDIDATE_ID,
        "model_family": MODEL_FAMILY,
        "status": CANDIDATE_STATUS,
        "population_id": str(population_id),
        "feature_contract": PUBLIC_CONTEXT_SCHEMA,
        "likelihood_contract": SCHEMA,
        "response_contract": RESPONSE_SCHEMA,
        "hierarchy_spec_schema": HIERARCHY_SPEC_SCHEMA,
        "identity_granularity": EXACT_GRANULARITY,
        "support_isolation_rule": SUPPORT_ISOLATION_RULE,
        "active_model_replaced": False,
        "fit_scope": str(fit_scope),
        "data_scope": str(data_scope),
    }
    if source_report_hash:
        identity["source_report_hash"] = str(source_report_hash)
    if hierarchy_spec_sha256:
        identity["hierarchy_spec_sha256"] = str(hierarchy_spec_sha256)
    return identity


def _normalize_observation(observation: Mapping[str, Any], index: int) -> dict[str, Any]:
    if not isinstance(observation, Mapping):
        raise HierarchicalSizingError("observations must be mappings")
    if _contains_sensitive_key(observation):
        raise HierarchicalSizingError(
            "private/future card information is forbidden in observations"
        )
    if "whitelist" in observation:
        whitelist = dict(observation["whitelist"])
        validate_whitelist(whitelist)
    else:
        raw = observation.get("public_context", observation.get("context"))
        if raw is None:
            raise HierarchicalSizingError(
                "observations need a public_context/context or an explicit whitelist"
            )
        if "effective_stack_bucket" in raw and "effective_stack_bb" not in raw:
            whitelist = dict(raw)
            validate_whitelist(whitelist)
        else:
            whitelist = hierarchical_public_whitelist(raw)
    if "whitelist" in observation and observation.get("public_context") is not None:
        if hierarchical_public_whitelist(observation["public_context"]) != whitelist:
            raise HierarchicalSizingError("observation whitelist/public_context disagree")
    action = normalize_action(observation.get("action"))
    if action not in RESPONSES:
        raise HierarchicalSizingError(f"unknown observation action: {observation.get('action')!r}")
    target = observation.get("target_total_bb")
    if action in ("RAISE", "JAM") and target is None:
        # A raise observation without an exact target cannot support a price.
        target = None
    elif target is not None:
        target = _finite_nonnegative(target, "target_total_bb")
    hand_id = str(observation.get("hand_id") or observation.get("observation_id") or "")
    if not hand_id:
        raise HierarchicalSizingError("observation needs hand_id")
    exact = hierarchical_exact_key_from_whitelist(whitelist)
    declared = observation.get("hierarchical_exact_key")
    if declared is not None and str(declared) != exact:
        raise HierarchicalSizingError(
            "declared hierarchical_exact_key does not match its public context"
        )
    return {
        "observation_id": str(observation.get("observation_id") or f"obs-{index}"),
        "hand_id": hand_id,
        "hierarchical_exact_key": exact,
        "level_keys": level_keys(whitelist),
        "public_context": whitelist,
        "action": action,
        "target_total_bb": target,
        # A reveal is a descriptive label of the observed sample only: it is
        # never a key axis, a feature, a support quantity or a shrinkage input.
        "reveal_label": (
            None
            if observation.get("reveal_label") in (None, "")
            else str(observation["reveal_label"])
        ),
    }


def make_synthetic_hierarchical_candidate(
    *,
    population_id: str,
    observations: Sequence[Mapping[str, Any]],
    unresolved_raise_frontiers: Sequence[str] = (),
    fit_scope: str = "SCAFFOLD_ONLY_NO_FINAL_FIT",
    data_scope: str = "SYNTHETIC_OR_TRAIN_ONLY",
    source_report_hash: str | None = None,
    hierarchy_spec_sha256: str | None = None,
) -> dict[str, Any]:
    """Build a candidate contract from already-observed public rows."""
    rows = [
        _normalize_observation(observation, index)
        for index, observation in enumerate(observations)
    ]
    frontiers = sorted({str(key) for key in unresolved_raise_frontiers})
    return {
        "schema": SCHEMA,
        "identity": candidate_identity(
            population_id=population_id,
            fit_scope=fit_scope,
            data_scope=data_scope,
            source_report_hash=source_report_hash,
            hierarchy_spec_sha256=hierarchy_spec_sha256,
        ),
        "exact_context_granularity": EXACT_GRANULARITY,
        "support_isolation_rule": SUPPORT_ISOLATION_RULE,
        "nearest_price_fallback": False,
        "nearest_context_fallback": False,
        "representative_price_fallback": False,
        "pooling_levels": [dict(spec) for spec in LEVEL_SPECS],
        "shrinkage": {
            "method": "hierarchical_dirichlet_shrinkage",
            "kappa0": KAPPA0,
            "alpha_per_legal_marginal_action": ALPHA_PER_LEGAL_ACTION,
        },
        "thresholds": {
            "minimum_marginal_observations": MIN_MARGINAL_OBSERVATIONS,
            "minimum_distinct_hands": MIN_DISTINCT_HANDS,
        },
        "unresolved_raise_frontiers": frontiers,
        "observations": rows,
    }


def validate_candidate(candidate: Mapping[str, Any]) -> None:
    if not isinstance(candidate, Mapping):
        raise HierarchicalSizingError("candidate must be a mapping")
    if candidate.get("schema") != SCHEMA:
        raise HierarchicalSizingError("unsupported hierarchical candidate schema")
    identity = candidate.get("identity")
    if not isinstance(identity, Mapping):
        raise HierarchicalSizingError("candidate identity is required")
    if identity.get("candidate_id") not in CANDIDATE_IDS:
        raise HierarchicalSizingError("unexpected hierarchical candidate identity")
    if identity.get("candidate_id") in EXACT_PRICE_CANDIDATE_IDS:
        raise HierarchicalSizingError("hierarchical candidate id must stay distinct")
    if identity.get("model_family") != MODEL_FAMILY:
        raise HierarchicalSizingError("candidate must be Model-A preflop")
    if identity.get("status") != CANDIDATE_STATUS:
        raise HierarchicalSizingError("candidate must remain non-active")
    if identity.get("active_model_replaced") is not False:
        raise HierarchicalSizingError("candidate cannot replace active Model-A")
    if identity.get("identity_granularity") != EXACT_GRANULARITY:
        raise HierarchicalSizingError("identity granularity must be exact")
    if identity.get("support_isolation_rule") != SUPPORT_ISOLATION_RULE:
        raise HierarchicalSizingError("support isolation rule must be unchanged")
    for flag in (
        "nearest_price_fallback",
        "nearest_context_fallback",
        "representative_price_fallback",
    ):
        if candidate.get(flag) is not False:
            raise HierarchicalSizingError(f"{flag} is forbidden")
    if candidate.get("exact_context_granularity") != EXACT_GRANULARITY:
        raise HierarchicalSizingError("exact context granularity must be hierarchical")
    if candidate.get("support_isolation_rule") != SUPPORT_ISOLATION_RULE:
        raise HierarchicalSizingError("support isolation rule must be unchanged")
    shrinkage = candidate.get("shrinkage")
    if not isinstance(shrinkage, Mapping):
        raise HierarchicalSizingError("candidate shrinkage contract is required")
    if float(shrinkage.get("kappa0", -1)) != KAPPA0:
        raise HierarchicalSizingError("kappa0 is frozen")
    if float(shrinkage.get("alpha_per_legal_marginal_action", -1)) != ALPHA_PER_LEGAL_ACTION:
        raise HierarchicalSizingError("alpha per legal action is frozen")
    thresholds = candidate.get("thresholds")
    if not isinstance(thresholds, Mapping):
        raise HierarchicalSizingError("candidate thresholds are required")
    if int(thresholds.get("minimum_marginal_observations", -1)) != MIN_MARGINAL_OBSERVATIONS:
        raise HierarchicalSizingError("observation threshold is frozen")
    if int(thresholds.get("minimum_distinct_hands", -1)) != MIN_DISTINCT_HANDS:
        raise HierarchicalSizingError("distinct-hand threshold is frozen")
    observations = candidate.get("observations")
    if not isinstance(observations, list):
        raise HierarchicalSizingError("candidate observations must be a list")
    for index, row in enumerate(observations):
        normalized = _normalize_observation(row, index)
        if normalized["hierarchical_exact_key"] != row.get("hierarchical_exact_key"):
            raise HierarchicalSizingError("observation exact key drift")
        if normalized["level_keys"] != row.get("level_keys"):
            raise HierarchicalSizingError("observation level key drift")
    frontiers = candidate.get("unresolved_raise_frontiers") or []
    if not isinstance(frontiers, list) or any(not isinstance(key, str) for key in frontiers):
        raise HierarchicalSizingError("unresolved_raise_frontiers must be a list of keys")


def canonical_candidate_sha256(candidate: Mapping[str, Any]) -> str:
    return canonical_sha256(candidate)


def assert_support_isolation(*, requested_key: str, source_key: str) -> None:
    """Invariant: ``support.source_key == requested_key``."""
    if str(source_key) != str(requested_key):
        raise SupportIsolationError(
            "support source key is not the requested key; "
            "a key may never be supported by observations of another key"
        )


def _counts(rows: Sequence[Mapping[str, Any]], legal: Sequence[str]) -> dict[str, int]:
    legal_set = set(legal)
    counts = {action: 0 for action in legal}
    for row in rows:
        action = normalize_action(row.get("action"))
        if action not in legal_set:
            raise HierarchicalSizingError(
                f"observation action {action} is outside the legal marginal action set"
            )
        counts[action] += 1
    return counts


def _distinct_hands(rows: Sequence[Mapping[str, Any]]) -> int:
    return len({str(row.get("hand_id")) for row in rows})


def _dirichlet_mean(counts: Mapping[str, int], legal: Sequence[str]) -> dict[str, float]:
    alpha_total = ALPHA_PER_LEGAL_ACTION * len(legal)
    denom = sum(int(counts.get(action, 0)) for action in legal) + alpha_total
    return {
        action: round((int(counts.get(action, 0)) + ALPHA_PER_LEGAL_ACTION) / denom, 12)
        for action in legal
    }


def _normalize_distribution(distribution: Mapping[str, float]) -> dict[str, float]:
    total = sum(float(value) for value in distribution.values())
    if total <= EPS:
        raise HierarchicalSizingError("posterior mass must be positive")
    normalized = {
        action: round(float(value) / total, 12) for action, value in distribution.items()
    }
    # Repair the rounding residual on the largest mass so the vector sums to 1.
    heaviest = max(normalized, key=lambda action: normalized[action])
    residual = round(1.0 - sum(normalized.values()), 12)
    normalized[heaviest] = round(normalized[heaviest] + residual, 12)
    return normalized


def _blend(
    *,
    exact_counts: Mapping[str, int],
    parent_posterior: Mapping[str, float],
    exact_observations: int,
    legal: Sequence[str],
) -> tuple[dict[str, float], float]:
    weight = round(exact_observations / (exact_observations + KAPPA0), 12)
    exact_posterior = _dirichlet_mean(exact_counts, legal)
    blended = {
        action: weight * exact_posterior[action] + (1.0 - weight) * parent_posterior[action]
        for action in legal
    }
    return _normalize_distribution(blended), weight


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularised incomplete beta (Lentz)."""
    max_iterations = 300
    tiny = 3e-14
    floor = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < floor:
        d = floor
    d = 1.0 / d
    h = d
    for m in range(1, max_iterations + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < floor:
            d = floor
        c = 1.0 + aa / c
        if abs(c) < floor:
            c = floor
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < floor:
            d = floor
        c = 1.0 + aa / c
        if abs(c) < floor:
            c = floor
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < tiny:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _beta_quantile(p: float, a: float, b: float) -> float:
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(200):
        mid = 0.5 * (low + high)
        if _betainc(a, b, mid) < p:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


def _uncertainty(
    *,
    posterior: Mapping[str, float],
    level_used: str,
    level_effective_sample_size: float,
    confidence: float,
) -> dict[str, Any]:
    """Dirichlet marginal credible intervals plus standard error.

    The band reflects the level actually used, never the exact level alone.
    """
    k = len(posterior)
    concentration = max(float(level_effective_sample_size), 0.0) + ALPHA_PER_LEGAL_ACTION * k
    tail = (1.0 - confidence) / 2.0
    actions: dict[str, Any] = {}
    for action, mass in posterior.items():
        alpha_i = max(float(mass) * concentration, 1e-9)
        beta_i = max(concentration - alpha_i, 1e-9)
        actions[action] = {
            "mean": round(float(mass), 12),
            "alpha": round(alpha_i, 12),
            "beta": round(beta_i, 12),
            "std_error": round(math.sqrt(max(0.0, float(mass) * (1.0 - float(mass))) / (concentration + 1.0)), 12),
            "credible_interval": {
                "level": round(float(confidence), 6),
                "low": round(_beta_quantile(tail, alpha_i, beta_i), 12),
                "high": round(_beta_quantile(1.0 - tail, alpha_i, beta_i), 12),
            },
        }
    return {
        "method": "DIRICHLET_MARGINAL_BETA_CREDIBLE_INTERVAL",
        "confidence_level": round(float(confidence), 6),
        "level_used": level_used,
        "effective_sample_size": round(float(level_effective_sample_size), 6),
        "concentration": round(concentration, 12),
        "actions": actions,
    }


def _finite(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


def empirical_support_block(
    *, requested_key: str, support: Mapping[str, Any]
) -> dict[str, Any]:
    """Layer A: the exact-key empirical support of the requested key, only.

    Every count here is re-derived from rows whose ``hierarchical_exact_key``
    equals ``requested_key``; a pooled parent level never feeds this block.
    """
    observations = int(support["observations"])
    distinct_hands = int(support["distinct_hands"])
    meets_observations = observations >= MIN_MARGINAL_OBSERVATIONS
    meets_hands = distinct_hands >= MIN_DISTINCT_HANDS
    return {
        "layer": LAYER_A_EXACT_EMPIRICAL_SUPPORT,
        "support_granularity": EXACT_GRANULARITY,
        "support_level": SUPPORT_LEVEL,
        "requested_key": str(requested_key),
        "source_key": str(requested_key),
        "observations": observations,
        "distinct_hands": distinct_hands,
        "effective_sample_size": float(support["effective_sample_size"]),
        "action_counts": dict(support["action_counts"]),
        "denominator": int(support["denominator"]),
        "thresholds": {
            "minimum_marginal_observations": MIN_MARGINAL_OBSERVATIONS,
            "minimum_distinct_hands": MIN_DISTINCT_HANDS,
        },
        "meets_observation_threshold": meets_observations,
        "meets_distinct_hand_threshold": meets_hands,
        "qualifies_as_exact_support": bool(meets_observations and meets_hands),
        # A pooled parent level may move the *parameters* only.  These two flags
        # pin that no pooled level ever contributes to a layer-A quantity.
        "counts_from_pooled_level": False,
        "borrowed_from_other_keys": False,
        "support_isolation_rule": SUPPORT_ISOLATION_RULE,
    }


def pooling_provenance_block(
    *, requested_key: str, pooling: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    """Layer B provenance: the declared parent level that supplied the prior."""
    if pooling is None:
        return None
    return {
        "level": pooling["level"],
        "rank": int(pooling["rank"]),
        "purpose": pooling["purpose"],
        "source_key": pooling["source_key"],
        "requested_key": str(requested_key),
        "retained_axes": list(pooling["retained_axes"]),
        "pooled_axes": list(pooling["pooled_axes"]),
        "source_observations": int(pooling["source_observations"]),
        "source_distinct_hands": int(pooling["source_distinct_hands"]),
        "source_effective_sample_size": float(pooling["source_effective_sample_size"]),
        "weight_exact": float(pooling["weight_exact"]),
        "weight_parent": float(pooling["weight_parent"]),
        "parent_dominated": bool(pooling["parent_dominated"]),
        "kappa0": float(pooling["kappa0"]),
        "alpha_per_legal_marginal_action": float(
            pooling["alpha_per_legal_marginal_action"]
        ),
        "support_source_key": pooling["support_source_key"],
        "counts_as_exact_support": pooling["level"] == SUPPORT_LEVEL,
        "support_isolation_rule": SUPPORT_ISOLATION_RULE,
    }


def effective_sample_size_block(
    *, support: Mapping[str, Any], pooling: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Layer A/B effective sample size, credited at the hand level."""
    return {
        "support_effective_sample_size": float(support["effective_sample_size"]),
        "support_distinct_hands": int(support["distinct_hands"]),
        "pooling_source_effective_sample_size": (
            None
            if pooling is None
            else float(pooling["source_effective_sample_size"])
        ),
        "level_used": None if pooling is None else pooling["level"],
        "credited_at": "DISTINCT_HANDS_NEVER_INFLATED_BY_POOLING",
    }


def uncertainty_is_machine_readable(uncertainty: Mapping[str, Any] | None) -> bool:
    """A band is usable only when every reported action carries a finite band."""
    if not isinstance(uncertainty, Mapping):
        return False
    actions = uncertainty.get("actions")
    if not isinstance(actions, Mapping) or not actions:
        return False
    if not _finite(uncertainty.get("effective_sample_size")):
        return False
    for band in actions.values():
        if not isinstance(band, Mapping):
            return False
        for field in ("mean", "std_error"):
            if not _finite(band.get(field)):
                return False
        interval = band.get("credible_interval")
        if not isinstance(interval, Mapping):
            return False
        low, high, mean = (
            interval.get("low"),
            interval.get("high"),
            band.get("mean"),
        )
        if not (_finite(low) and _finite(high) and _finite(mean)):
            return False
        if not (float(low) - EPS <= float(mean) <= float(high) + EPS):
            return False
        if float(float(band.get("std_error"))) < -EPS:
            return False
    return True


def _layer_b_gate_states(
    *,
    requested_key: str,
    support: Mapping[str, Any],
    pooling: Mapping[str, Any] | None,
    uncertainty: Mapping[str, Any] | None,
    raise_sizing: Mapping[str, Any],
    status: str,
    primary_failure_gate: str | None,
) -> list[dict[str, Any]]:
    """Per-gate machine-readable admissibility state, aligned with the T1 codes."""
    strong = status == STATUS_EXACT_EMPIRICAL_STRONG
    estimate = status == STATUS_EXACT_HIERARCHICAL_ESTIMATE
    answered = strong or estimate
    identity_ok = bool(
        str(support.get("source_key")) == str(requested_key)
        and support.get("borrowed_from_other_keys") is False
    )
    if pooling is not None:
        identity_ok = identity_ok and set(NEVER_MUTUALIZABLE_AXES).issubset(
            set(pooling.get("retained_axes") or ())
        )
    provenance_ok = bool(
        pooling is not None
        and pooling.get("level") in POOLING_LEVELS
        and pooling.get("source_key")
        and "source_observations" in pooling
        and "source_distinct_hands" in pooling
        and "retained_axes" in pooling
        and "pooled_axes" in pooling
    )
    level_ok = bool(
        pooling is not None
        and (
            (strong and pooling.get("level") == SUPPORT_LEVEL)
            or (
                estimate
                and pooling.get("level") in POOLING_LEVELS[1:]
            )
        )
    )
    ess_ok = bool(
        _finite(support.get("effective_sample_size"))
        and float(support.get("effective_sample_size"))
        == float(support.get("distinct_hands"))
        and (
            pooling is None
            or (
                _finite(pooling.get("source_effective_sample_size"))
                and float(pooling.get("source_effective_sample_size"))
                == float(pooling.get("source_distinct_hands"))
            )
        )
    )
    uncertainty_ok = uncertainty_is_machine_readable(uncertainty)
    raise_ok = not bool(raise_sizing.get("unresolved"))

    decisions: dict[str, tuple[bool, bool, bool | None, str]] = {
        # gate_id -> (applicable, evaluated, satisfied, detail)
        GATE_EXACT_KEY_IDENTITY: (
            answered,
            answered or primary_failure_gate == GATE_EXACT_KEY_IDENTITY,
            identity_ok if answered else None,
            "support.source_key == requested_key and never-mutualizable axes retained",
        ),
        GATE_POOLING_PROVENANCE: (
            estimate,
            estimate or primary_failure_gate == GATE_POOLING_PROVENANCE,
            provenance_ok if estimate else None,
            "pooling.level/source/counts/axes are reported for the level actually used",
        ),
        GATE_POOLING_LEVEL: (
            answered,
            answered or primary_failure_gate == GATE_POOLING_LEVEL,
            level_ok if answered else None,
            "EXACT_EMPIRICAL_STRONG only at L0_EXACT_KEY; an estimate pools L1..L4",
        ),
        GATE_EFFECTIVE_SAMPLE_SIZE: (
            answered,
            answered or primary_failure_gate == GATE_EFFECTIVE_SAMPLE_SIZE,
            ess_ok if answered else None,
            "effective sample size reported at the level used and never inflated",
        ),
        GATE_UNCERTAINTY: (
            answered,
            answered or primary_failure_gate == GATE_UNCERTAINTY,
            uncertainty_ok if answered else None,
            "uncertainty band and posterior reflect the level actually used",
        ),
        GATE_CALIBRATION: (
            answered,
            False,
            None,
            "calibration is evaluated at VALIDATION time, never at answer time",
        ),
        GATE_RAISE_SIZING_FRONTIER: (
            answered,
            answered or primary_failure_gate == GATE_RAISE_SIZING_FRONTIER,
            raise_ok if answered else None,
            "raise sizing is exact-support-only; an unresolved frontier stays unresolved",
        ),
    }

    states: list[dict[str, Any]] = []
    for order, gate_id, reason_code, applies_to in LAYER_B_GATES:
        applicable, evaluated, satisfied, detail = decisions[gate_id]
        if primary_failure_gate == gate_id:
            applicable, evaluated, satisfied = True, True, False
        states.append(
            {
                "order": order,
                "gate_id": gate_id,
                "reason_code": reason_code,
                "status_scope": list(applies_to),
                "applicable": bool(applicable),
                "evaluated": bool(evaluated),
                "satisfied": None if satisfied is None else bool(satisfied),
                "detail": detail,
            }
        )
    return states


def admissibility_block(
    *,
    requested_key: str,
    support: Mapping[str, Any],
    pooling: Mapping[str, Any] | None,
    uncertainty: Mapping[str, Any] | None,
    raise_sizing: Mapping[str, Any],
    status: str,
    primary_failure_gate: str | None = None,
) -> dict[str, Any]:
    """Layer B: per-gate admissibility state plus its aligned T1 reason code."""
    gates = _layer_b_gate_states(
        requested_key=requested_key,
        support=support,
        pooling=pooling,
        uncertainty=uncertainty,
        raise_sizing=raise_sizing,
        status=status,
        primary_failure_gate=primary_failure_gate,
    )
    if primary_failure_gate is not None:
        failing_gate = primary_failure_gate
    else:
        failing_gate = next(
            (
                gate["gate_id"]
                for gate in gates
                if gate["applicable"] and gate["evaluated"] and gate["satisfied"] is False
            ),
            None,
        )
    reason_code = None if failing_gate is None else GATE_REASON_BY_ID[failing_gate]
    admissible = bool(
        status in (STATUS_EXACT_EMPIRICAL_STRONG, STATUS_EXACT_HIERARCHICAL_ESTIMATE)
        and failing_gate is None
    )
    return {
        "layer": LAYER_B_EXACT_CONTEXT_ESTIMATE_ADMISSIBILITY,
        "node_closure_rule_id": NODE_CLOSURE_RULE_ID,
        "status": status,
        "answered": status
        in (STATUS_EXACT_EMPIRICAL_STRONG, STATUS_EXACT_HIERARCHICAL_ESTIMATE),
        "admissible": admissible,
        "primary_failure_gate": failing_gate,
        "reason_code": reason_code,
        "deferred_gates": [GATE_CALIBRATION],
        "gates": gates,
    }


def posterior_identity_block(
    *,
    status: str,
    reason_code: str,
    unresolved_reason: str | None,
    reason_detail: str | None,
    posterior: Mapping[str, float] | None,
) -> dict[str, Any]:
    """Machine-readable identity of the emitted (or withheld) posterior."""
    return {
        "status": status,
        "reason_code": reason_code,
        "unresolved_reason": unresolved_reason,
        "reason_detail": reason_detail,
        "posterior_present": posterior is not None,
        "probability_emitted": posterior is not None,
        "posterior_sha256": (
            None if posterior is None else canonical_sha256(posterior)
        ),
    }


def _level_diagnostics(
    *,
    rows: Sequence[Mapping[str, Any]],
    whitelist: Mapping[str, Any],
    legal: Sequence[str],
) -> list[dict[str, Any]]:
    diagnostics = []
    for spec in LEVEL_SPECS:
        key = level_key(spec["level"], whitelist)
        level_rows = [row for row in rows if row["level_keys"][spec["level"]] == key]
        observations = len(level_rows)
        distinct = _distinct_hands(level_rows)
        diagnostics.append(
            {
                "level": spec["level"],
                "rank": spec["rank"],
                "purpose": spec["purpose"],
                "source_key": key,
                "source_observations": observations,
                "source_distinct_hands": distinct,
                "source_effective_sample_size": float(distinct),
                "action_counts": _counts(level_rows, legal),
                "qualifies": observations >= MIN_MARGINAL_OBSERVATIONS
                and distinct >= MIN_DISTINCT_HANDS,
                "support_source_allowed": spec["support_source_allowed"],
            }
        )
    return diagnostics


def _raise_sizing(
    *,
    rows: Sequence[Mapping[str, Any]],
    whitelist: Mapping[str, Any],
    requested_key: str,
    legal: Sequence[str],
    declared_unresolved: bool,
    has_exact_support: bool,
) -> dict[str, Any]:
    raise_legal = bool({"RAISE", "JAM"} & set(legal))
    targets: dict[str, int] = {}
    for row in rows:
        if normalize_action(row.get("action")) not in {"RAISE", "JAM"}:
            continue
        target = row.get("target_total_bb")
        if target is None:
            continue
        token = f"{round(float(target), 6):g}"
        targets[token] = targets.get(token, 0) + 1
    supported = [
        {"target_total_bb": float(token), "observations": count}
        for token, count in sorted(targets.items(), key=lambda item: float(item[0]))
    ]
    if declared_unresolved:
        state = "UNRESOLVED_SIZING_FRONTIER"
    elif not raise_legal:
        state = "NO_RAISE_BRANCH"
    elif supported:
        state = "EXACT_SUPPORTED"
    elif has_exact_support:
        state = "UNRESOLVED_SIZING_FRONTIER"
    else:
        state = "NO_EXACT_SUPPORT"
    return {
        "policy": "exact-support-only",
        "state": state,
        "supported_targets": supported,
        "exact_support_only": True,
        "nearest_price_used": False,
        "representative_price_used": False,
        "interpolation_used": False,
        "source_key": requested_key,
        "structural_node_key": runtime_exact_preflop_node_key(whitelist),
        "unresolved": state == "UNRESOLVED_SIZING_FRONTIER",
    }


def _validate_two_layer_blocks(
    response: Mapping[str, Any],
    *,
    requested_key: str,
    support: Mapping[str, Any],
    status: str,
) -> None:
    """Enforce the explicit two-layer serialization of one response."""
    empirical = response.get("empirical_support")
    if not isinstance(empirical, Mapping):
        raise HierarchicalSizingError("empirical_support is required")
    if empirical.get("layer") != LAYER_A_EXACT_EMPIRICAL_SUPPORT:
        raise HierarchicalSizingError("empirical_support must be the layer-A block")
    if empirical.get("support_level") != SUPPORT_LEVEL:
        raise HierarchicalSizingError("empirical_support is only ever claimed at L0")
    if str(empirical.get("source_key")) != requested_key:
        raise HierarchicalSizingError(
            "empirical_support.source_key must be the requested key"
        )
    if str(empirical.get("requested_key")) != requested_key:
        raise HierarchicalSizingError(
            "empirical_support.requested_key must be the requested key"
        )
    # A pooled level may never fill a layer-A field, and the recount must match
    # the exact-key support exactly.
    if empirical.get("counts_from_pooled_level") is not False:
        raise HierarchicalSizingError(
            "no pooled level may contribute to empirical_support"
        )
    if empirical.get("borrowed_from_other_keys") is not False:
        raise HierarchicalSizingError("empirical_support may never be borrowed")
    for field in ("observations", "distinct_hands", "effective_sample_size", "denominator"):
        if empirical.get(field) != support.get(field):
            raise HierarchicalSizingError(
                f"empirical_support.{field} must equal the exact-key support"
            )
    if dict(empirical.get("action_counts") or {}) != dict(support.get("action_counts") or {}):
        raise HierarchicalSizingError(
            "empirical_support.action_counts must equal the exact-key support"
        )
    thresholds = empirical.get("thresholds") or {}
    if (
        int(thresholds.get("minimum_marginal_observations", -1))
        != MIN_MARGINAL_OBSERVATIONS
        or int(thresholds.get("minimum_distinct_hands", -1)) != MIN_DISTINCT_HANDS
    ):
        raise HierarchicalSizingError("empirical_support thresholds must be frozen")
    qualifies = bool(
        int(support["observations"]) >= MIN_MARGINAL_OBSERVATIONS
        and int(support["distinct_hands"]) >= MIN_DISTINCT_HANDS
    )
    if bool(empirical.get("qualifies_as_exact_support")) != qualifies:
        raise HierarchicalSizingError(
            "empirical_support.qualifies_as_exact_support must match the 20/20 thresholds"
        )

    pooling = response.get("pooling")
    provenance = response.get("pooling_provenance")
    if pooling is None:
        if provenance is not None:
            raise HierarchicalSizingError(
                "pooling_provenance must be null when no pooling level is used"
            )
    else:
        if not isinstance(provenance, Mapping):
            raise HierarchicalSizingError("pooling_provenance is required")
        for field in ("level", "source_key", "retained_axes", "pooled_axes"):
            if provenance.get(field) != pooling.get(field):
                raise HierarchicalSizingError(
                    f"pooling_provenance.{field} must match the used pooling level"
                )
        if str(provenance.get("requested_key")) != requested_key:
            raise HierarchicalSizingError(
                "pooling_provenance.requested_key must be the requested key"
            )
        for field in (
            "source_observations",
            "source_distinct_hands",
            "source_effective_sample_size",
            "weight_exact",
            "weight_parent",
        ):
            if provenance.get(field) != pooling.get(field):
                raise HierarchicalSizingError(
                    f"pooling_provenance.{field} must match the used pooling level"
                )
        counts_as_exact = provenance.get("level") == SUPPORT_LEVEL
        if bool(provenance.get("counts_as_exact_support")) != counts_as_exact:
            raise HierarchicalSizingError(
                "pooling_provenance.counts_as_exact_support must match its level"
            )

    ess = response.get("effective_sample_size")
    if not isinstance(ess, Mapping):
        raise HierarchicalSizingError("effective_sample_size is required")
    if ess.get("support_effective_sample_size") != support.get("effective_sample_size"):
        raise HierarchicalSizingError(
            "effective_sample_size.support_effective_sample_size must equal support"
        )
    expected_pooling_ess = None if pooling is None else pooling.get("source_effective_sample_size")
    if ess.get("pooling_source_effective_sample_size") != expected_pooling_ess:
        raise HierarchicalSizingError(
            "effective_sample_size.pooling_source_effective_sample_size must match pooling"
        )

    admissibility = response.get("admissibility")
    if not isinstance(admissibility, Mapping):
        raise HierarchicalSizingError("admissibility is required")
    if admissibility.get("layer") != LAYER_B_EXACT_CONTEXT_ESTIMATE_ADMISSIBILITY:
        raise HierarchicalSizingError("admissibility must be the layer-B block")
    if admissibility.get("node_closure_rule_id") != NODE_CLOSURE_RULE_ID:
        raise HierarchicalSizingError("admissibility must publish the frozen closure rule")
    if admissibility.get("status") != status:
        raise HierarchicalSizingError("admissibility.status must equal the response status")
    gates = admissibility.get("gates")
    if not isinstance(gates, list):
        raise HierarchicalSizingError("admissibility.gates is required")
    gate_ids = [gate.get("gate_id") for gate in gates]
    expected_ids = [gate_id for _, gate_id, _, _ in LAYER_B_GATES]
    if gate_ids != expected_ids:
        raise HierarchicalSizingError(
            "admissibility gates must cover the frozen T1 gate vocabulary in order"
        )
    for gate, (_, gate_id, reason_code, _) in zip(gates, LAYER_B_GATES):
        if gate.get("reason_code") != reason_code:
            raise HierarchicalSizingError(
                f"admissibility gate {gate_id} must carry its T1 reason code"
            )
    failing = admissibility.get("primary_failure_gate")
    if status == STATUS_EXACT_UNRESOLVED:
        if admissibility.get("admissible") is not False:
            raise HierarchicalSizingError("an unresolved node is never admissible")
        if failing not in GATE_REASON_BY_ID:
            raise HierarchicalSizingError(
                "an unresolved node must name its failing T1 gate"
            )
        if admissibility.get("reason_code") != GATE_REASON_BY_ID[failing]:
            raise HierarchicalSizingError(
                "admissibility.reason_code must be the failing gate's T1 code"
            )
    else:
        if admissibility.get("admissible") is not True or failing is not None:
            raise HierarchicalSizingError(
                "an answered node must pass every decidable layer-B gate"
            )

    identity = response.get("posterior_identity")
    if not isinstance(identity, Mapping):
        raise HierarchicalSizingError("posterior_identity is required")
    if identity.get("status") != status or identity.get("reason_code") != status:
        raise HierarchicalSizingError("posterior_identity must carry the response status")
    posterior_present = response.get("posterior") is not None
    if bool(identity.get("posterior_present")) != posterior_present:
        raise HierarchicalSizingError(
            "posterior_identity.posterior_present must match the emitted posterior"
        )
    if bool(identity.get("probability_emitted")) != posterior_present:
        raise HierarchicalSizingError(
            "posterior_identity.probability_emitted must match the emitted posterior"
        )


def validate_response(response: Mapping[str, Any]) -> None:
    """Enforce the machine-readable response contract; fail closed."""
    if not isinstance(response, Mapping):
        raise HierarchicalSizingError("response must be a mapping")
    if response.get("schema") != RESPONSE_SCHEMA:
        raise HierarchicalSizingError("unsupported hierarchical response schema")
    status = response.get("status")
    if status not in STATUSES:
        raise HierarchicalSizingError("unknown hierarchical reason code")
    if response.get("reason_code") != status:
        raise HierarchicalSizingError("reason_code must equal the status")
    requested_key = str(response.get("requested_key") or "")
    if not requested_key.startswith("MAPSUP_") or "|public=" not in requested_key:
        raise HierarchicalSizingError("requested_key must be a hierarchical exact key")
    support = response.get("support")
    if not isinstance(support, Mapping):
        raise HierarchicalSizingError("support is required")
    assert_support_isolation(
        requested_key=requested_key, source_key=str(support.get("source_key") or "")
    )
    if support.get("borrowed_from_other_keys") is not False:
        raise HierarchicalSizingError("support may never be borrowed from other keys")
    if not response.get("pooling_diagnostics"):
        raise HierarchicalSizingError("per-level pooling diagnostics are required")
    # Scan only data-bearing fields: the `information_boundary` block declares
    # the booleans `future_cards_consumed`/`opponent_hole_cards_consumed`, which
    # are contract declarations rather than consumed information.
    if _contains_sensitive_key(
        {key: value for key, value in response.items() if key != "information_boundary"}
    ):
        raise HierarchicalSizingError("private/future information is forbidden")
    posterior = response.get("posterior")
    uncertainty = response.get("uncertainty")
    pooling = response.get("pooling")
    if status == STATUS_EXACT_UNRESOLVED:
        if posterior is not None or uncertainty is not None:
            raise HierarchicalSizingError("an unresolved decision emits no probability")
        if not str(response.get("reason_detail") or ""):
            raise HierarchicalSizingError("an unresolved decision needs a reason detail")
        if response.get("raise_sizing", {}).get("unresolved") and not str(
            response.get("reason_detail")
        ):
            raise HierarchicalSizingError("an unresolved raise frontier needs a reason")
        _validate_two_layer_blocks(
            response, requested_key=requested_key, support=support, status=status
        )
        return
    if not isinstance(posterior, Mapping) or not posterior:
        raise HierarchicalSizingError("a resolved decision needs a posterior")
    if not isinstance(uncertainty, Mapping) or not uncertainty.get("actions"):
        raise HierarchicalSizingError(
            "uncertainty is mandatory for any resolved or hierarchical estimate"
        )
    if not isinstance(pooling, Mapping):
        raise HierarchicalSizingError("pooling provenance is required")
    if abs(sum(float(value) for value in posterior.values()) - 1.0) > 1e-9:
        raise HierarchicalSizingError("posterior must sum to 1 over legal actions")
    if set(posterior) != set(uncertainty["actions"]):
        raise HierarchicalSizingError("uncertainty must cover every reported action")
    level = pooling.get("level")
    if status == STATUS_EXACT_EMPIRICAL_STRONG:
        if level != SUPPORT_LEVEL:
            raise HierarchicalSizingError(
                "an EXACT_EMPIRICAL_STRONG claim requires pooling.level == L0_EXACT_KEY"
            )
        if pooling.get("source_key") != requested_key:
            raise HierarchicalSizingError("an exact claim must use its own support key")
        if uncertainty.get("level_used") != SUPPORT_LEVEL:
            raise HierarchicalSizingError("an exact claim reports its own uncertainty level")
    elif status == STATUS_EXACT_HIERARCHICAL_ESTIMATE:
        if level == SUPPORT_LEVEL:
            raise HierarchicalSizingError(
                "a hierarchical estimate must report the parent level it used"
            )
        if pooling.get("source_key") == requested_key:
            raise HierarchicalSizingError(
                "a hierarchical estimate must pool toward a parent, not itself"
            )
        if uncertainty.get("level_used") != level:
            raise HierarchicalSizingError(
                "uncertainty must reflect the level actually used"
            )
    _validate_two_layer_blocks(
        response, requested_key=requested_key, support=support, status=status
    )


def resolve_exact_context(
    *,
    candidate: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
    requested_key: str | None = None,
    legal_actions: Sequence[str] | None = None,
    confidence: float = DEFAULT_UNCERTAINTY_LEVEL,
) -> dict[str, Any]:
    """Deterministically resolve one exact public context.

    ``context`` supplies the live public state; ``requested_key`` may instead be
    given directly (with ``legal_actions``).  When both are given they must agree
    exactly, otherwise the call fails closed.
    """
    validate_candidate(candidate)
    if not 0.5 < float(confidence) < 1.0:
        raise HierarchicalSizingError("confidence must be between 0.5 and 1")

    whitelist: dict[str, Any] | None = None
    if context is not None:
        whitelist = hierarchical_public_whitelist(context)
        computed = hierarchical_exact_key_from_whitelist(whitelist)
        if requested_key is not None and str(requested_key) != computed:
            raise HierarchicalSizingError(
                "requested_key does not match the exact key of the supplied context"
            )
        requested_key = computed
    if requested_key is None:
        raise HierarchicalSizingError("context or requested_key is required")
    requested_key = str(requested_key)

    if legal_actions is None:
        if context is None or not context.get("legal_actions"):
            raise HierarchicalSizingError(
                "legal_actions are required to resolve the marginal action set"
            )
        legal_actions = context["legal_actions"]
    legal = [normalize_action(action) for action in legal_actions]
    if not legal:
        raise HierarchicalSizingError("the legal marginal action set cannot be empty")
    if len(set(legal)) != len(legal):
        raise HierarchicalSizingError("the legal marginal action set has duplicates")
    for action in legal:
        if action not in RESPONSES:
            raise HierarchicalSizingError(f"illegal marginal action: {action}")

    observations = candidate["observations"]
    exact_rows = [row for row in observations if row["hierarchical_exact_key"] == requested_key]
    support_observations = len(exact_rows)
    support_distinct_hands = _distinct_hands(exact_rows)
    support_counts = _counts(exact_rows, legal)
    support = {
        "observations": support_observations,
        "distinct_hands": support_distinct_hands,
        "effective_sample_size": float(support_distinct_hands),
        "action_counts": support_counts,
        "denominator": sum(support_counts.values()),
        "source_key": requested_key,
        "borrowed_from_other_keys": False,
        "support_isolation_rule": SUPPORT_ISOLATION_RULE,
    }
    assert_support_isolation(requested_key=requested_key, source_key=support["source_key"])

    # Resolving by key alone is supported, but pooling needs the requested key's
    # own public context.  When at least one exact observation carries that key
    # the whitelist is recoverable (all rows of one exact key share it), so the
    # parent level keys are still exact.  Without either the context or an exact
    # observation the call fails closed instead of guessing a neighbouring key.
    if whitelist is not None:
        level_whitelist: dict[str, Any] | None = whitelist
    elif exact_rows:
        level_whitelist = dict(exact_rows[0]["public_context"])
    else:
        level_whitelist = None
    diagnostics = (
        _level_diagnostics(rows=observations, whitelist=level_whitelist, legal=legal)
        if level_whitelist is not None
        else [
            {
                "level": spec["level"],
                "rank": spec["rank"],
                "purpose": spec["purpose"],
                "source_key": None,
                "source_observations": 0,
                "source_distinct_hands": 0,
                "source_effective_sample_size": 0.0,
                "action_counts": {action: 0 for action in legal},
                "qualifies": False,
                "support_source_allowed": spec["support_source_allowed"],
            }
            for spec in LEVEL_SPECS
        ]
    )

    declared_unresolved = requested_key in set(candidate.get("unresolved_raise_frontiers") or [])
    if level_whitelist is None:
        raise_sizing = {
            "policy": "exact-support-only",
            "state": "NO_EXACT_SUPPORT",
            "supported_targets": [],
            "exact_support_only": True,
            "nearest_price_used": False,
            "representative_price_used": False,
            "interpolation_used": False,
            "source_key": requested_key,
            "structural_node_key": None,
            "unresolved": False,
        }
    else:
        raise_sizing = _raise_sizing(
            rows=exact_rows,
            whitelist=level_whitelist,
            requested_key=requested_key,
            legal=legal,
            declared_unresolved=declared_unresolved,
            has_exact_support=bool(exact_rows),
        )

    base = {
        "schema": RESPONSE_SCHEMA,
        "candidate_identity": dict(candidate["identity"]),
        "requested_key": requested_key,
        "requested_key_granularity": EXACT_GRANULARITY,
        "support": support,
        "pooling": None,
        "pooling_diagnostics": diagnostics,
        "posterior": None,
        "uncertainty": None,
        "raise_sizing": raise_sizing,
        "information_boundary": {
            "public_only": True,
            "future_cards_consumed": False,
            "opponent_hole_cards_consumed": False,
            "private_information_consumed": False,
        },
        "granularity": {
            "identity": EXACT_GRANULARITY,
            "support": SUPPORT_LEVEL,
            "parameter_pooling_allowed": True,
            "nearest_price_lookup": False,
            "nearest_context_lookup": False,
        },
    }

    def finalize(
        *,
        status: str,
        unresolved_reason: str | None = None,
        reason_detail: str | None = None,
        primary_failure_gate: str | None = None,
    ) -> dict[str, Any]:
        """Serialize the two layers explicitly for exactly one response."""
        base["status"] = status
        base["reason_code"] = status
        base["reason_detail"] = reason_detail
        if unresolved_reason is None:
            base.pop("unresolved_reason", None)
        else:
            base["unresolved_reason"] = unresolved_reason
        base["empirical_support"] = empirical_support_block(
            requested_key=requested_key, support=base["support"]
        )
        base["pooling_provenance"] = pooling_provenance_block(
            requested_key=requested_key, pooling=base["pooling"]
        )
        base["effective_sample_size"] = effective_sample_size_block(
            support=base["support"], pooling=base["pooling"]
        )
        base["admissibility"] = admissibility_block(
            requested_key=requested_key,
            support=base["support"],
            pooling=base["pooling"],
            uncertainty=base["uncertainty"],
            raise_sizing=base["raise_sizing"],
            status=status,
            primary_failure_gate=primary_failure_gate,
        )
        base["posterior_identity"] = posterior_identity_block(
            status=status,
            reason_code=status,
            unresolved_reason=unresolved_reason,
            reason_detail=reason_detail,
            posterior=base["posterior"],
        )
        validate_response(base)
        return base

    if level_whitelist is None:
        return finalize(
            status=STATUS_EXACT_UNRESOLVED,
            reason_detail=(
                "no exact observation carries the requested key and no public context was "
                "supplied, so pooling level keys cannot be established; the call fails closed "
                "instead of resolving a different key"
            ),
            unresolved_reason=REASON_NO_EXACT_SUPPORT_NO_CONTEXT,
            primary_failure_gate=GATE_POOLING_LEVEL,
        )

    if raise_sizing["unresolved"]:
        return finalize(
            status=STATUS_EXACT_UNRESOLVED,
            reason_detail=(
                "raise sizing for this exact context is an unresolved frontier; "
                "no representative, legal-minimum, nearest or interpolated price is permitted"
            ),
            unresolved_reason=REASON_RAISE_SIZING_UNRESOLVED,
            primary_failure_gate=GATE_RAISE_SIZING_FRONTIER,
        )

    chosen = next((row for row in diagnostics if row["qualifies"]), None)
    if chosen is None:
        return finalize(
            status=STATUS_EXACT_UNRESOLVED,
            reason_detail=(
                "no pooling level meets the frozen 20 observations / 20 distinct hands "
                "thresholds for this exact key"
            ),
            unresolved_reason=REASON_NO_ADMISSIBLE_POOLING,
            primary_failure_gate=GATE_POOLING_LEVEL,
        )

    if chosen["level"] == SUPPORT_LEVEL:
        status = STATUS_EXACT_EMPIRICAL_STRONG
        posterior = _dirichlet_mean(support_counts, legal)
        weight = 1.0
        level_ess = float(support_distinct_hands)
    else:
        status = STATUS_EXACT_HIERARCHICAL_ESTIMATE
        parent_counts = chosen["action_counts"]
        parent_posterior = _dirichlet_mean(parent_counts, legal)
        posterior, weight = _blend(
            exact_counts=support_counts,
            parent_posterior=parent_posterior,
            exact_observations=support_observations,
            legal=legal,
        )
        level_ess = float(chosen["source_effective_sample_size"])

    spec = LEVEL_SPEC_BY_NAME[chosen["level"]]
    base["status"] = status
    base["reason_code"] = status
    base["reason_detail"] = None
    base["posterior"] = posterior
    base["pooling"] = {
        "level": chosen["level"],
        "rank": chosen["rank"],
        "purpose": chosen["purpose"],
        "source_key": chosen["source_key"],
        "source_observations": chosen["source_observations"],
        "source_distinct_hands": chosen["source_distinct_hands"],
        "source_effective_sample_size": chosen["source_effective_sample_size"],
        "retained_axes": list(spec["retains"]),
        "pooled_axes": list(spec["drops"]),
        "weight_exact": round(float(weight), 12),
        "weight_parent": round(1.0 - float(weight), 12),
        "parent_dominated": float(weight) < PARENT_DOMINATED_FLAG_BELOW,
        "kappa0": KAPPA0,
        "alpha_per_legal_marginal_action": ALPHA_PER_LEGAL_ACTION,
        "support_source_key": requested_key,
        "support_isolation_rule": SUPPORT_ISOLATION_RULE,
    }
    base["uncertainty"] = _uncertainty(
        posterior=posterior,
        level_used=chosen["level"],
        level_effective_sample_size=level_ess,
        confidence=float(confidence),
    )
    # Fail closed: an answered node that cannot satisfy every layer-B gate the
    # provider can decide (identity, provenance, level, effective sample size,
    # uncertainty, raise sizing) is downgraded to EXACT_UNRESOLVED with the
    # failing gate's frozen reason code.  Calibration is deferred to VALIDATION.
    gate_check = admissibility_block(
        requested_key=requested_key,
        support=base["support"],
        pooling=base["pooling"],
        uncertainty=base["uncertainty"],
        raise_sizing=base["raise_sizing"],
        status=status,
    )
    if not gate_check["admissible"]:
        failing_gate = gate_check["primary_failure_gate"]
        base["posterior"] = None
        base["uncertainty"] = None
        base["pooling"] = None
        return finalize(
            status=STATUS_EXACT_UNRESOLVED,
            reason_detail=(
                "the answered node cannot satisfy the frozen layer-B admissibility gate "
                f"{failing_gate}; no probability is emitted and the node stays unresolved"
            ),
            unresolved_reason=REASON_NO_ADMISSIBLE_POOLING,
            primary_failure_gate=failing_gate,
        )
    return finalize(status=status)


def canonical_response_sha256(response: Mapping[str, Any]) -> str:
    return canonical_sha256(response)
