#!/usr/bin/env python3
"""Versioned public-state policy context used by calculated Hero overlays.

`poker-preflop-context/v1` (PFC) is an exact before-action state identity and
therefore includes continuous stack, contribution and price fields.  That is the
right identity for audit/replay, but it is too narrow for a reusable calculated
policy: two strategically equivalent 96bb and 104bb unopened states receive
different PFC ids.

This module defines a separate, explicitly lossy policy identity.  The loss is
part of the contract, not a nearest-context fallback.  Consumers either match
one PFPC exactly or declare the state out of support.

The bucket boundaries are frozen in v1.  They may only change through a new
schema/version because changing them changes which public states share a policy.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping

PFC_SCHEMA = "poker-preflop-context/v1"
SCHEMA = "poker-preflop-policy-context/v1"
STATE_TIMING = "BEFORE_ACTION"
ID_PREFIX = "PFPC_"
EPS = 1e-9

STACK_BUCKETS = (
    (40.0, "LE40"),
    (75.0, "GT40_LE75"),
    (125.0, "GT75_LE125"),
    (math.inf, "GT125"),
)
PRICE_BUCKETS = (
    (1.0, "LE1"),
    (2.5, "GT1_LE2_5"),
    (3.5, "GT2_5_LE3_5"),
    (5.0, "GT3_5_LE5"),
    (10.0, "GT5_LE10"),
    (25.0, "GT10_LE25"),
    (math.inf, "GT25"),
)
TO_CALL_BUCKETS = (
    (0.0, "FREE"),
    (1.5, "GT0_LE1_5"),
    (2.5, "GT1_5_LE2_5"),
    (4.0, "GT2_5_LE4"),
    (8.0, "GT4_LE8"),
    (20.0, "GT8_LE20"),
    (math.inf, "GT20"),
)
POT_BUCKETS = (
    (1.5, "LE1_5"),
    (3.0, "GT1_5_LE3"),
    (6.0, "GT3_LE6"),
    (12.0, "GT6_LE12"),
    (30.0, "GT12_LE30"),
    (math.inf, "GT30"),
)
RAISE_INCREMENT_BUCKETS = PRICE_BUCKETS


def _number(value: Any, field: str) -> float:
    out = float(value)
    if not math.isfinite(out) or out < -EPS:
        raise ValueError(f"{field} must be a finite non-negative number")
    return max(0.0, out)


def _bucket(value: float, buckets, *, zero_label: str | None = None) -> str:
    value = float(value)
    if zero_label is not None and value <= EPS:
        return zero_label
    for upper, label in buckets:
        if value <= upper + EPS:
            return str(label)
    raise AssertionError("bucket table must terminate with infinity")


def stack_bucket(value: Any) -> str:
    return _bucket(_number(value, "effective_stack_bb"), STACK_BUCKETS)


def price_bucket(value: Any) -> str:
    return _bucket(_number(value, "current_price_bb"), PRICE_BUCKETS)


def to_call_bucket(value: Any) -> str:
    return _bucket(_number(value, "to_call_bb"), TO_CALL_BUCKETS, zero_label="FREE")


def pot_bucket(value: Any) -> str:
    return _bucket(_number(value, "pot_before_bb"), POT_BUCKETS)


def raise_increment_bucket(current_price_bb: Any, min_raise_to_bb: Any) -> str:
    price = _number(current_price_bb, "current_price_bb")
    minimum = _number(min_raise_to_bb, "min_raise_to_bb")
    increment = max(0.0, minimum - price)
    return _bucket(increment, RAISE_INCREMENT_BUCKETS, zero_label="NONE")


def _history(value: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in value or []:
        if not isinstance(row, Mapping):
            raise TypeError("history entries must be mappings")
        position = str(row.get("position") or "").upper().strip()
        action = str(row.get("action") or "").upper().strip()
        if not position or not action:
            raise ValueError(f"invalid history entry {row!r}")
        out.append({"position": position, "action": action})
    return out


def _positions(value: Any) -> list[str]:
    return [str(position).upper().strip() for position in (value or []) if str(position).strip()]


def build_policy_context(preflop_context: Mapping[str, Any]) -> dict[str, Any]:
    """Compress one exact PFC into the frozen v1 calculated-policy identity."""
    if str(preflop_context.get("schema") or "") != PFC_SCHEMA:
        raise ValueError(f"expected {PFC_SCHEMA}")
    if str(preflop_context.get("state_timing") or "") != STATE_TIMING:
        raise ValueError("policy context requires BEFORE_ACTION PFC state")

    current_price = _number(preflop_context.get("current_price_bb", 0.0), "current_price_bb")
    raw_minimum = preflop_context.get("min_raise_to_bb", current_price)
    minimum = current_price if raw_minimum is None else _number(raw_minimum, "min_raise_to_bb")
    legal = sorted({str(action).upper() for action in (preflop_context.get("legal_actions") or [])})
    result = {
        "schema": SCHEMA,
        "state_timing": STATE_TIMING,
        "source_schema": PFC_SCHEMA,
        "table_size": int(preflop_context.get("table_size") or 0),
        "actor_position": str(preflop_context.get("actor_position") or "").upper(),
        "family": str(preflop_context.get("family") or "").upper(),
        "raise_level": int(preflop_context.get("raise_level") or 0),
        "live_positions": _positions(preflop_context.get("live_positions")),
        "all_in_positions": _positions(preflop_context.get("all_in_positions")),
        "remaining_to_act_positions": _positions(preflop_context.get("remaining_to_act_positions")),
        "history": _history(preflop_context.get("history")),
        "effective_stack_bucket": stack_bucket(preflop_context.get("effective_stack_bb", 0.0)),
        "current_price_bucket": price_bucket(current_price),
        "to_call_bucket": to_call_bucket(preflop_context.get("to_call_bb", 0.0)),
        "pot_before_bucket": pot_bucket(preflop_context.get("pot_before_bb", 0.0)),
        "min_raise_increment_bucket": raise_increment_bucket(current_price, minimum),
        "free_check": bool(preflop_context.get("free_check")),
        "raise_reopened": bool(preflop_context.get("raise_reopened", True)),
        "legal_actions": legal,
    }
    if result["table_size"] < 2:
        raise ValueError("table_size must be >= 2")
    if not result["actor_position"] or not result["family"]:
        raise ValueError("actor_position and family are required")
    result["policy_context_id"] = policy_context_id(result)
    return result


def policy_context_id(policy_context: Mapping[str, Any]) -> str:
    structural = {
        key: policy_context[key]
        for key in (
            "schema",
            "state_timing",
            "source_schema",
            "table_size",
            "actor_position",
            "family",
            "raise_level",
            "live_positions",
            "all_in_positions",
            "remaining_to_act_positions",
            "history",
            "effective_stack_bucket",
            "current_price_bucket",
            "to_call_bucket",
            "pot_before_bucket",
            "min_raise_increment_bucket",
            "free_check",
            "raise_reopened",
            "legal_actions",
        )
    }
    payload = json.dumps(structural, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return ID_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def contract_descriptor() -> dict[str, Any]:
    """Machine-readable frozen boundaries for evidence manifests."""
    def serialise(rows):
        return [{"upper_inclusive": None if math.isinf(upper) else upper, "label": label} for upper, label in rows]

    return {
        "schema": SCHEMA,
        "matching": "EXACT_PFPC_ONLY_NO_NEAREST_CONTEXT",
        "source": PFC_SCHEMA,
        "stack_buckets": serialise(STACK_BUCKETS),
        "price_buckets": serialise(PRICE_BUCKETS),
        "to_call_buckets": serialise(TO_CALL_BUCKETS),
        "pot_buckets": serialise(POT_BUCKETS),
        "min_raise_increment_buckets": serialise(RAISE_INCREMENT_BUCKETS),
    }
