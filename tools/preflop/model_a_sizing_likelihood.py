#!/usr/bin/env python3
"""Sizing-aware Model-A preflop likelihood scaffold.

Candidate-only: this module does not replace or mutate the active Model-A
preflop model. It provides a pure public-context projection and exact-price
lookup contract for future TRAIN-only fitting.

Backoff is deliberately constrained to the same exact public price:
  1. exact hand class + exact price/context;
  2. marginal hand class + exact price/context;
  3. unresolved.

There is no nearest-price fallback.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from tools.preflop.context_contract import EPS, canonical_key

SCHEMA = "poker-model-a-preflop-sizing-likelihood/v1"
PUBLIC_CONTEXT_SCHEMA = "poker-model-a-preflop-sizing-public-context/v1"
RUNTIME_CANDIDATE_ID = "model-a-preflop-sizing-aware-candidate-v1"
RUNTIME_CANDIDATE_V2_ID = "model-a-preflop-sizing-aware-candidate-v2"
CANDIDATE_IDS = (RUNTIME_CANDIDATE_ID, RUNTIME_CANDIDATE_V2_ID)
MODEL_FAMILY = "MODEL_A_PREFLOP"
CANDIDATE_STATUS = "CANDIDATE_ONLY_NOT_ACTIVE"
BACKOFF_POLICY = (
    "EXACT_HAND_CLASS_EXACT_PRICE",
    "MARGINAL_EXACT_PRICE",
    "UNRESOLVED",
)
SENSITIVE_TOKENS = (
    "hole",
    "cards",
    "board",
    "showdown",
    "future",
    "opponent_private",
    "known_cards",
)


class SizingLikelihoodError(RuntimeError):
    pass


def _finite_nonnegative(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SizingLikelihoodError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or number < -EPS:
        raise SizingLikelihoodError(f"{field} must be finite and non-negative")
    return round(max(0.0, number), 9)


def _int_nonnegative(value: Any, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise SizingLikelihoodError(f"{field} must be an integer") from exc
    if number < 0:
        raise SizingLikelihoodError(f"{field} must be non-negative")
    return number


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


def _decimal_token(value: float) -> str:
    text = f"{float(value):.9f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _history_support_features(history: Sequence[Mapping[str, Any]]) -> tuple[str | None, int, int]:
    first_raise = next(
        (i for i, row in enumerate(history) if str(row.get("action") or "").upper() in {"RAISE", "JAM"}),
        None,
    )
    limper_end = len(history) if first_raise is None else first_raise
    limpers = sum(
        1
        for row in history[:limper_end]
        if str(row.get("action") or "").upper() == "LIMP"
    )
    callers = 0 if first_raise is None else sum(
        1
        for row in history[first_raise + 1 :]
        if str(row.get("action") or "").upper() == "CALL"
    )
    aggressors = [
        str(row.get("position") or "")
        for row in history
        if str(row.get("action") or "").upper() in {"RAISE", "JAM"}
    ]
    return (aggressors[-1] if aggressors else None), limpers, callers


def support_context_key(context: Mapping[str, Any]) -> str:
    """Exact #319 support key; no numeric-nearest fallback is permitted."""
    history = list(context.get("history") or [])
    aggressor, derived_limpers, derived_callers = _history_support_features(history)
    target_raw = context.get("target_total_bb", context.get("current_price_bb"))
    if target_raw is None:
        raise SizingLikelihoodError("target_total_bb/current_price_bb is required for support key")
    target = _finite_nonnegative(target_raw, "target_total_bb")
    to_call = _finite_nonnegative(context.get("to_call_bb"), "to_call_bb")
    limpers = _int_nonnegative(context.get("limper_count", derived_limpers), "limper_count")
    callers = _int_nonnegative(context.get("caller_count", derived_callers), "caller_count")
    payload = "|".join(
        [
            f"family={str(context.get('family') or '')}",
            f"actor={str(context.get('actor_position') or '')}",
            f"aggressor={str(context.get('aggressor_position') or aggressor or '')}",
            f"limpers={limpers}",
            f"callers={callers}",
            f"target={_decimal_token(target)}",
            f"call={_decimal_token(to_call)}",
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"MAPSUP_{digest}:{payload}"


def public_sizing_context(context: Mapping[str, Any]) -> dict[str, Any]:
    """Extract only public sizing/price features required by the candidate."""
    if not isinstance(context, Mapping):
        raise SizingLikelihoodError("context must be a mapping")
    if _contains_sensitive_key(context):
        raise SizingLikelihoodError("private/future card information is forbidden")

    required = (
        "table_size",
        "actor_position",
        "family",
        "raise_level",
        "to_call_bb",
        "pot_before_bb",
        "effective_stack_bb",
    )
    missing = [field for field in required if field not in context]
    if missing:
        raise SizingLikelihoodError(
            "missing public sizing fields: " + ", ".join(missing)
        )

    target_raw = context.get("target_total_bb", context.get("current_price_bb"))
    if target_raw is None:
        raise SizingLikelihoodError(
            "missing public sizing fields: target_total_bb/current_price_bb"
        )
    target = _finite_nonnegative(target_raw, "target_total_bb")
    to_call = _finite_nonnegative(context["to_call_bb"], "to_call_bb")
    pot = _finite_nonnegative(context["pot_before_bb"], "pot_before_bb")
    effective = _finite_nonnegative(
        context["effective_stack_bb"], "effective_stack_bb"
    )
    ratio = (
        0.0
        if pot <= EPS and to_call <= EPS
        else None
        if pot <= EPS
        else round(to_call / pot, 9)
    )
    denom = pot + to_call
    odds = round(to_call / denom, 9) if denom > EPS else 0.0
    table_size = _int_nonnegative(context["table_size"], "table_size")
    if table_size < 2:
        raise SizingLikelihoodError("table_size must be at least 2")
    raise_level = _int_nonnegative(context["raise_level"], "raise_level")
    limpers = _int_nonnegative(
        context.get("limper_count", len(set(context.get("limper_positions") or []))),
        "limper_count",
    )
    callers = _int_nonnegative(
        context.get("caller_count", len(set(context.get("caller_positions") or []))),
        "caller_count",
    )

    structural = str(context.get("canonical_key") or canonical_key(context))
    history = list(context.get("history") or [])
    aggressor, _, _ = _history_support_features(history)
    projection = {
        "schema": PUBLIC_CONTEXT_SCHEMA,
        "state_timing": str(context.get("state_timing") or "BEFORE_ACTION"),
        "table_size": table_size,
        "actor_position": str(context["actor_position"]),
        "family": str(context["family"]),
        "aggressor_position": context.get("aggressor_position", aggressor),
        "raise_level": raise_level,
        "structural_key": structural,
        "target_total_bb": target,
        "to_call_bb": to_call,
        "pot_before_bb": pot,
        "price_to_pot_ratio": ratio,
        "pot_odds": odds,
        "effective_stack_bb": effective,
        "limper_count": limpers,
        "caller_count": callers,
        "information_boundary": {
            "public_only": True,
            "future_cards_consumed": False,
            "opponent_hole_cards_consumed": False,
        },
    }
    projection["sizing_context_key"] = sizing_context_key(projection)
    projection["support_context_key"] = support_context_key({**context, **projection})
    return projection


def sizing_context_key(public_context: Mapping[str, Any]) -> str:
    """Exact-price key. Numeric proximity is intentionally never consulted."""
    fields = (
        str(public_context.get("structural_key") or ""),
        f"target={_decimal_token(float(public_context.get('target_total_bb') or 0.0))}",
        f"call={_decimal_token(float(public_context.get('to_call_bb') or 0.0))}",
        f"pot={_decimal_token(float(public_context.get('pot_before_bb') or 0.0))}",
        f"eff={_decimal_token(float(public_context.get('effective_stack_bb') or 0.0))}",
        f"limpers={int(public_context.get('limper_count') or 0)}",
        f"callers={int(public_context.get('caller_count') or 0)}",
    )
    payload = "|".join(fields)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"MAPSIZ_{digest}:{payload}"


def candidate_identity(
    *,
    population_id: str,
    fit_scope: str = "SCAFFOLD_ONLY_NO_FINAL_FIT",
    data_scope: str = "SYNTHETIC_OR_TRAIN_ONLY",
    source_report_hash: str | None = None,
    candidate_id: str = RUNTIME_CANDIDATE_ID,
) -> dict[str, Any]:
    if not population_id:
        raise SizingLikelihoodError("population_id is required")
    if candidate_id not in CANDIDATE_IDS:
        raise SizingLikelihoodError("unsupported sizing-aware candidate_id")
    identity = {
        "candidate_id": candidate_id,
        "model_family": MODEL_FAMILY,
        "status": CANDIDATE_STATUS,
        "population_id": str(population_id),
        "feature_contract": PUBLIC_CONTEXT_SCHEMA,
        "likelihood_contract": SCHEMA,
        "active_model_replaced": False,
        "fit_scope": str(fit_scope),
        "data_scope": str(data_scope),
    }
    if source_report_hash:
        identity["source_report_hash"] = str(source_report_hash)
    return identity


def _normalized_probabilities(
    raw: Mapping[str, Any], legal_actions: Sequence[str]
) -> dict[str, float]:
    if not isinstance(raw, Mapping) or not raw:
        raise SizingLikelihoodError("probabilities must be a non-empty mapping")
    legal = {str(action).upper() for action in legal_actions}
    out: dict[str, float] = {}
    for action, value in raw.items():
        name = str(action).upper()
        if legal and name not in legal:
            raise SizingLikelihoodError(
                f"probability action {name} is not legal in this public context"
            )
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise SizingLikelihoodError(f"invalid probability for {name}")
        out[name] = number
    total = sum(out.values())
    if total <= EPS:
        raise SizingLikelihoodError("probability mass must be positive")
    if abs(total - 1.0) > 1e-9:
        raise SizingLikelihoodError(
            f"candidate likelihood probabilities must sum to 1, got {total}"
        )
    return out


def make_synthetic_candidate(
    *,
    population_id: str,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a candidate contract from already-normalized synthetic/TRAIN rows."""
    nodes: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        public_context = public_sizing_context(row["context"])
        legal = list(row["context"].get("legal_actions") or [])
        nodes.append(
            {
                "node_id": str(row.get("node_id") or f"synthetic-{index}"),
                "sizing_context_key": public_context["sizing_context_key"],
                "public_context": public_context,
                "hand_class": (
                    None
                    if row.get("hand_class") in (None, "")
                    else str(row["hand_class"])
                ),
                "probabilities": _normalized_probabilities(
                    row["probabilities"], legal
                ),
                "support": _int_nonnegative(row.get("support", 0), "support"),
                "support_class": str(row.get("support_class") or "SYNTHETIC"),
            }
        )
    return {
        "schema": SCHEMA,
        "identity": candidate_identity(population_id=population_id),
        "backoff_policy": list(BACKOFF_POLICY),
        "nearest_price_fallback": False,
        "nodes": nodes,
    }


def validate_candidate(candidate: Mapping[str, Any]) -> None:
    if candidate.get("schema") != SCHEMA:
        raise SizingLikelihoodError("unsupported sizing-likelihood schema")
    identity = candidate.get("identity")
    if not isinstance(identity, Mapping):
        raise SizingLikelihoodError("candidate identity is required")
    if identity.get("candidate_id") not in CANDIDATE_IDS:
        raise SizingLikelihoodError("unexpected candidate identity")
    if identity.get("model_family") != MODEL_FAMILY:
        raise SizingLikelihoodError("candidate must be Model-A preflop")
    if identity.get("status") != CANDIDATE_STATUS:
        raise SizingLikelihoodError("candidate must remain non-active")
    if identity.get("active_model_replaced") is not False:
        raise SizingLikelihoodError("candidate cannot replace active Model-A")
    if candidate.get("backoff_policy") != list(BACKOFF_POLICY):
        raise SizingLikelihoodError("backoff policy must be exact and canonical")
    if candidate.get("nearest_price_fallback") is not False:
        raise SizingLikelihoodError("nearest-price fallback is forbidden")
    nodes = candidate.get("nodes")
    if not isinstance(nodes, list):
        raise SizingLikelihoodError("candidate nodes must be a list")


def resolve_support_likelihood(
    *,
    candidate: Mapping[str, Any],
    context: Mapping[str, Any],
    hand_class: str | None,
) -> dict[str, Any]:
    """Resolve a #319 exact support cell without requiring a full UI context projection."""
    validate_candidate(candidate)
    key = support_context_key(context)
    exact_price_nodes = [
        node
        for node in candidate["nodes"]
        if isinstance(node, Mapping) and node.get("support_context_key") == key
    ]
    hand = None if hand_class in (None, "") else str(hand_class)
    if hand is not None:
        exact_hand = [node for node in exact_price_nodes if node.get("hand_class") == hand]
        if len(exact_hand) > 1:
            raise SizingLikelihoodError("duplicate exact hand-class likelihood nodes")
        if exact_hand:
            node = exact_hand[0]
            return {
                "status": "RESOLVED",
                "backoff_level": BACKOFF_POLICY[0],
                "node_id": node.get("node_id"),
                "support_context_key": key,
                "hand_class": hand,
                "probabilities": dict(node["probabilities"]),
                "support": int(node.get("support") or 0),
                "candidate_identity": dict(candidate["identity"]),
                "source_report_hash": node.get("source_report_hash"),
            }
    marginal = [node for node in exact_price_nodes if node.get("hand_class") in (None, "")]
    if len(marginal) > 1:
        raise SizingLikelihoodError("duplicate exact-price marginal nodes")
    if marginal:
        node = marginal[0]
        return {
            "status": "RESOLVED",
            "backoff_level": BACKOFF_POLICY[1],
            "node_id": node.get("node_id"),
            "support_context_key": key,
            "hand_class": hand,
            "probabilities": dict(node["probabilities"]),
            "support": int(node.get("support") or 0),
            "candidate_identity": dict(candidate["identity"]),
            "source_report_hash": node.get("source_report_hash"),
        }
    return {
        "status": "UNRESOLVED",
        "backoff_level": BACKOFF_POLICY[2],
        "reason_code": "EXACT_PRICE_UNSUPPORTED_NO_NEAREST_PRICE",
        "support_context_key": key,
        "hand_class": hand,
        "probabilities": None,
        "support": 0,
        "candidate_identity": dict(candidate["identity"]),
        "source_report_hash": candidate.get("identity", {}).get("source_report_hash"),
    }


def resolve_likelihood(
    *,
    candidate: Mapping[str, Any],
    context: Mapping[str, Any],
    hand_class: str | None,
) -> dict[str, Any]:
    """Resolve only exact-price nodes; hand-class may back off to same-price marginal."""
    validate_candidate(candidate)
    public_context = public_sizing_context(context)
    sizing_key = public_context["sizing_context_key"]
    support_key = public_context["support_context_key"]
    exact_price_nodes = [
        node
        for node in candidate["nodes"]
        if isinstance(node, Mapping)
        and (
            node.get("support_context_key") == support_key
            or (
                node.get("support_context_key") in (None, "")
                and node.get("sizing_context_key") == sizing_key
            )
        )
    ]
    key = support_key if any(node.get("support_context_key") for node in exact_price_nodes) else sizing_key

    hand = None if hand_class in (None, "") else str(hand_class)
    if hand is not None:
        exact_hand = [
            node for node in exact_price_nodes if node.get("hand_class") == hand
        ]
        if len(exact_hand) > 1:
            raise SizingLikelihoodError(
                "duplicate exact hand-class likelihood nodes"
            )
        if exact_hand:
            node = exact_hand[0]
            return {
                "status": "RESOLVED",
                "backoff_level": BACKOFF_POLICY[0],
                "node_id": node.get("node_id"),
                "sizing_context_key": key,
                "hand_class": hand,
                "probabilities": dict(node["probabilities"]),
                "support": int(node.get("support") or 0),
                "candidate_identity": dict(candidate["identity"]),
                "public_context": public_context,
            }

    marginal = [
        node for node in exact_price_nodes if node.get("hand_class") in (None, "")
    ]
    if len(marginal) > 1:
        raise SizingLikelihoodError("duplicate exact-price marginal nodes")
    if marginal:
        node = marginal[0]
        return {
            "status": "RESOLVED",
            "backoff_level": BACKOFF_POLICY[1],
            "node_id": node.get("node_id"),
            "sizing_context_key": key,
            "hand_class": hand,
            "probabilities": dict(node["probabilities"]),
            "support": int(node.get("support") or 0),
            "candidate_identity": dict(candidate["identity"]),
            "public_context": public_context,
        }

    return {
        "status": "UNRESOLVED",
        "backoff_level": BACKOFF_POLICY[2],
        "reason_code": "EXACT_PRICE_UNSUPPORTED_NO_NEAREST_PRICE",
        "sizing_context_key": key,
        "hand_class": hand,
        "probabilities": None,
        "support": 0,
        "candidate_identity": dict(candidate["identity"]),
        "public_context": public_context,
    }


def canonical_candidate_sha256(candidate: Mapping[str, Any]) -> str:
    payload = json.dumps(
        candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
