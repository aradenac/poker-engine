#!/usr/bin/env python3
"""Canonical, card-free preflop decision context and action-probability contract.

The context describes the table *immediately before* one voluntary action.  It
never contains hole cards, board cards, showdown cards, or future actions.
Cards belong only to probability consumers that evaluate
P(action, sizing | hand, context).

The promoted v5/v83 matcher is intentionally preserved through
``v5_runtime_signature``.  That compatibility projection mirrors issue #88:
``free_check`` and the richer sizing/stack fields are NOT part of incumbent
exact matching, and legacy comma/``>`` history separators are semantically
normalized rather than rewritten in persisted v5 artifacts.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "poker-preflop-context/v1"
PROBABILITY_SCHEMA = "poker-preflop-action-probabilities/v1"
STATE_TIMING = "BEFORE_ACTION"
EPS = 1e-9

POSITION_ORDER_6MAX = ("LJ", "HJ", "CO", "BTN", "SB", "BB")
POSITION_ORDER_HU = ("SB_BTN", "BB")
ACTIONS = ("FOLD", "CHECK", "LIMP", "CALL", "RAISE", "JAM")


def normalize_position(position: str | None, table_size: int) -> str:
    p = "LJ" if str(position or "").upper() == "UTG" else str(position or "").upper()
    if int(table_size) == 2 and p == "BTN":
        return "SB_BTN"
    return p


def position_order(table_size: int) -> tuple[str, ...]:
    return POSITION_ORDER_HU if int(table_size) == 2 else POSITION_ORDER_6MAX


def sort_positions(positions: Iterable[str], table_size: int) -> list[str]:
    order = position_order(table_size)
    rank = {p: i for i, p in enumerate(order)}
    unique = {normalize_position(p, table_size) for p in positions if p}
    return sorted(unique, key=lambda p: (rank.get(p, 999), p))


def normalize_history(history: str | Sequence[Mapping[str, Any]] | None) -> list[dict[str, str]]:
    """Return ordered ``[{position, action}, ...]`` with legacy delimiters normalized."""
    if history is None:
        return []
    if isinstance(history, str):
        out: list[dict[str, str]] = []
        # Historical v5 keys used commas between history tokens; repo-native
        # keys use '>'.  Issue #88 established these are representation-only.
        for token in re.split(r"[>,]", history):
            token = token.strip()
            if not token:
                continue
            position, sep, action = token.partition(":")
            if not sep:
                raise ValueError(f"invalid preflop history token: {token!r}")
            out.append({"position": position.strip().upper(), "action": action.strip().upper()})
        return out
    out = []
    for item in history:
        if not isinstance(item, Mapping):
            raise TypeError("history items must be mappings")
        pos = str(item.get("position") or "").strip().upper()
        action = str(item.get("action") or "").strip().upper()
        if not pos or not action:
            raise ValueError(f"invalid preflop history item: {item!r}")
        out.append({"position": pos, "action": action})
    return out


def history_token(history: str | Sequence[Mapping[str, Any]] | None) -> str:
    return ">".join(f"{x['position']}:{x['action']}" for x in normalize_history(history))


def family_from_history(history: str | Sequence[Mapping[str, Any]] | None, actor_position: str) -> str:
    hist = normalize_history(history)
    actor = str(actor_position or "").upper()
    if not hist:
        return "UNOPENED"
    raises = [i for i, x in enumerate(hist) if x["action"] in ("RAISE", "JAM")]
    limps = [x for x in hist if x["action"] == "LIMP"]
    if not raises:
        return "VS_LIMPERS"
    first = raises[0]
    callers = [x for x in hist[first + 1 :] if x["action"] == "CALL"]
    actor_raised = any(x["position"] == actor and x["action"] in ("RAISE", "JAM") for x in hist)
    actor_called = any(x["position"] == actor and x["action"] in ("CALL", "LIMP") for x in hist)
    if len(raises) == 1:
        if limps and first > 0:
            actor_limped = any(x["position"] == actor and x["action"] == "LIMP" for x in hist)
            if actor_limped:
                return "LIMPER_VS_ISO_CALLERS" if callers else "LIMPER_VS_ISO"
            return "VS_ISO_CALLERS" if callers else "VS_ISO"
        return "VS_RFI_CALLERS" if callers else "VS_RFI"
    if len(raises) == 2:
        return "OPENER_OR_ISO_VS_3BET" if actor_raised else ("CALLER_VS_SQUEEZE_OR_3BET" if actor_called else "COLD_VS_3BET")
    if len(raises) == 3:
        return "AGGRESSOR_VS_4BET" if actor_raised else ("CALLER_VS_4BET" if actor_called else "COLD_VS_4BET")
    if len(raises) == 4:
        return "VS_5BET"
    return "VS_6BET_PLUS"


def _finite_nonnegative(value: Any, field: str) -> float:
    v = float(value or 0.0)
    if not math.isfinite(v) or v < -EPS:
        raise ValueError(f"{field} must be a finite non-negative number")
    return max(0.0, v)


def _round_bb(value: float) -> float:
    return round(float(value), 9)


def legal_actions_for_state(
    *,
    to_call_bb: float,
    actor_contribution_bb: float,
    actor_remaining_bb: float,
    min_raise_to_bb: float | None,
    max_raise_to_bb: float,
    raise_reopened: bool = True,
    raise_level: int = 0,
) -> list[str]:
    """Return legal action families, keeping CALL-all-in distinct from JAM."""
    to_call = max(0.0, float(to_call_bb))
    remaining = max(0.0, float(actor_remaining_bb))
    actor_contribution = max(0.0, float(actor_contribution_bb))
    max_to = max(actor_contribution, float(max_raise_to_bb))
    legal: list[str] = []
    if to_call > EPS:
        legal.append("FOLD")
        if remaining > EPS:
            legal.append("CALL")
    else:
        legal.append("CHECK")
        # A voluntary call with zero price is never represented as CALL.
        if int(raise_level) == 0 and actor_contribution + EPS < max_to:
            legal.append("LIMP")

    can_increase_price = remaining > to_call + EPS and max_to > actor_contribution + to_call + EPS
    if raise_reopened and can_increase_price:
        if min_raise_to_bb is not None and max_to + EPS >= float(min_raise_to_bb):
            legal.append("RAISE")
        # JAM is an action/sizing family when all-in increases the price, even
        # when a short stack cannot make a full legal raise.
        legal.append("JAM")
    return legal


def canonical_key(context: Mapping[str, Any]) -> str:
    hist = history_token(context.get("history") or [])
    live = ",".join(context.get("live_positions") or [])
    allin = ",".join(context.get("all_in_positions") or [])
    remaining = ",".join(context.get("remaining_to_act_positions") or [])
    return (
        f"{int(context.get('table_size') or 0)}|{context.get('actor_position') or ''}|"
        f"family={context.get('family') or ''}|rl={int(context.get('raise_level') or 0)}|"
        f"free={1 if context.get('free_check') else 0}|live={live}|allin={allin}|"
        f"remaining={remaining}|hist={hist}"
    )


def context_id(context: Mapping[str, Any]) -> str:
    structural = {
        k: context[k]
        for k in (
            "schema", "state_timing", "table_size", "actor_position", "family", "raise_level",
            "live_positions", "all_in_positions", "remaining_to_act_positions", "history",
            "limper_positions", "caller_positions", "contribution_bb_by_position",
            "actor_contribution_bb", "current_price_bb", "to_call_bb", "free_check",
            "pot_before_bb", "actor_remaining_bb", "effective_stack_bb", "legal_actions",
            "min_raise_to_bb", "max_raise_to_bb", "raise_reopened",
        )
        if k in context
    }
    payload = json.dumps(structural, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "PFC_" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def build_context(
    *,
    table_size: int,
    actor_position: str,
    live_positions: Sequence[str],
    all_in_positions: Sequence[str] = (),
    history: str | Sequence[Mapping[str, Any]] | None = None,
    raise_level: int | None = None,
    contribution_bb_by_position: Mapping[str, float] | None = None,
    stack_bb_by_position: Mapping[str, float] | None = None,
    pot_before_bb: float = 0.0,
    current_price_bb: float | None = None,
    pending_positions: Sequence[str] | None = None,
    min_raise_to_bb: float | None = None,
    raise_reopened: bool = True,
) -> dict[str, Any]:
    """Build the complete card-free state immediately before the actor acts."""
    n = int(table_size)
    if n < 2:
        raise ValueError("table_size must be at least 2")
    actor = normalize_position(actor_position, n)
    hist = normalize_history(history)
    hist = [{"position": normalize_position(x["position"], n), "action": x["action"]} for x in hist]
    live = sort_positions(live_positions, n)
    allin = sort_positions(all_in_positions, n)
    if actor not in live:
        raise ValueError(f"actor {actor!r} must be in live_positions")
    if actor in allin:
        raise ValueError("all-in actor cannot face another voluntary decision")

    contrib_in = contribution_bb_by_position or {}
    contrib = {p: _round_bb(_finite_nonnegative(contrib_in.get(p, 0.0), f"contribution[{p}]")) for p in live + allin}
    actor_paid = contrib.get(actor, 0.0)
    price = _finite_nonnegative(
        max(contrib.values(), default=0.0) if current_price_bb is None else current_price_bb,
        "current_price_bb",
    )
    to_call = max(0.0, price - actor_paid)

    stacks_in = stack_bb_by_position or {}
    actor_stack = _finite_nonnegative(stacks_in.get(actor, actor_paid), "actor stack")
    if actor_stack + EPS < actor_paid:
        raise ValueError("actor stack cannot be below contribution")
    actor_remaining = max(0.0, actor_stack - actor_paid)
    opponent_stacks = [
        _finite_nonnegative(stacks_in.get(p, contrib.get(p, 0.0)), f"stack[{p}]")
        for p in live
        if p != actor
    ]
    effective_stack = min(actor_stack, max(opponent_stacks, default=actor_stack))
    max_raise_to = actor_stack

    rl = int(raise_level) if raise_level is not None else sum(1 for x in hist if x["action"] in ("RAISE", "JAM"))
    if rl < 0:
        raise ValueError("raise_level cannot be negative")

    if min_raise_to_bb is None:
        # A 1 BB full-bet increment is the NLHE preflop baseline.  Consumers
        # with an observed prior full-raise increment should pass it explicitly.
        min_raise_to = price + max(1.0, price if rl == 0 and price < 1.0 else 1.0)
        if rl == 0 and price >= 1.0:
            min_raise_to = price + 1.0
    else:
        min_raise_to = _finite_nonnegative(min_raise_to_bb, "min_raise_to_bb")

    if pending_positions is None:
        order = [p for p in position_order(n) if p in live and p not in allin]
        idx = order.index(actor) if actor in order else -1
        pending = order[idx + 1 :] if idx >= 0 else []
    else:
        pending = [normalize_position(p, n) for p in pending_positions]
        pending = [p for p in pending if p in live and p not in allin and p != actor]

    first_raise = next((i for i, x in enumerate(hist) if x["action"] in ("RAISE", "JAM")), None)
    limpers = [x["position"] for x in hist[: first_raise if first_raise is not None else len(hist)] if x["action"] == "LIMP"]
    callers = [] if first_raise is None else [x["position"] for x in hist[first_raise + 1 :] if x["action"] == "CALL"]
    family = family_from_history(hist, actor)

    legal = legal_actions_for_state(
        to_call_bb=to_call,
        actor_contribution_bb=actor_paid,
        actor_remaining_bb=actor_remaining,
        min_raise_to_bb=min_raise_to,
        max_raise_to_bb=max_raise_to,
        raise_reopened=raise_reopened,
        raise_level=rl,
    )
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "state_timing": STATE_TIMING,
        "table_size": n,
        "actor_position": actor,
        "family": family,
        "raise_level": rl,
        "live_positions": live,
        "all_in_positions": allin,
        "remaining_to_act_positions": pending,
        "history": hist,
        "limper_positions": sort_positions(limpers, n),
        "caller_positions": sort_positions(callers, n),
        "contribution_bb_by_position": {p: contrib[p] for p in sort_positions(contrib, n)},
        "actor_contribution_bb": _round_bb(actor_paid),
        "current_price_bb": _round_bb(price),
        "to_call_bb": _round_bb(to_call),
        "free_check": to_call <= EPS,
        "pot_before_bb": _round_bb(_finite_nonnegative(pot_before_bb, "pot_before_bb")),
        "actor_remaining_bb": _round_bb(actor_remaining),
        "effective_stack_bb": _round_bb(effective_stack),
        "legal_actions": legal,
        "min_raise_to_bb": _round_bb(min_raise_to) if min_raise_to <= max_raise_to + EPS else None,
        "max_raise_to_bb": _round_bb(max_raise_to),
        "raise_reopened": bool(raise_reopened),
        "amount_semantics": {
            "call_or_bet_cost": "incremental_cost_bb",
            "raise_cost": "incremental_cost_bb",
            "raise_target": "target_total_bb",
            "check_and_fold_cost_bb": 0.0,
        },
    }
    result["canonical_key"] = canonical_key(result)
    result["context_id"] = context_id(result)
    return result


def v5_runtime_signature(context: Mapping[str, Any]) -> tuple[Any, ...]:
    """Issue #88 compatibility projection; deliberately ignores ``free_check``."""
    return (
        str(context.get("actor_position") or ""),
        int(context.get("table_size") or 0),
        int(context.get("raise_level") or 0),
        str(context.get("family") or ""),
        tuple(context.get("live_positions") or []),
        tuple(context.get("all_in_positions") or []),
        tuple((x["position"], x["action"]) for x in normalize_history(context.get("history") or [])),
    )


def normalize_action_probabilities(
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
    """Normalize one probability response over actions legal in ``context``.

    Unknown/illegal actions are discarded.  Missing legal actions receive zero
    mass.  No sizing distribution is fabricated: callers must omit ``sizing``
    or supply evidence-backed sizing metadata.
    """
    legal = [str(x).upper() for x in context.get("legal_actions") or []]
    if not legal:
        raise ValueError("context has no legal actions")
    weights: dict[str, float] = {}
    for action in legal:
        value = float(raw_probabilities.get(action, 0.0) or 0.0)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"invalid probability weight for {action}: {value!r}")
        weights[action] = value
    total = sum(weights.values())
    if total <= EPS:
        raise ValueError("probability mass over legal actions is zero")
    probs = {action: weights[action] / total for action in legal}
    return {
        "schema": PROBABILITY_SCHEMA,
        "context_id": str(context.get("context_id") or context_id(context)),
        "hand_class": hand_class,
        "legal_actions": legal,
        "probabilities": probs,
        "sizing": dict(sizing) if sizing is not None else None,
        "source": str(source),
        "backoff_level": str(backoff_level),
        "confidence": str(confidence),
        "support": int(support),
        "incumbent_compatibility": {
            "matcher": "v5/v83",
            "runtime_signature_ignores_free_check": True,
        },
    }
