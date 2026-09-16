#!/usr/bin/env python3
"""Executable exact-node Model-A continuation policy for multiway simulation.

This adapter is intentionally stricter than the browser's convenience matcher:
it reconstructs the canonical preflop/postflop context from ``NoLimitHoldemState``
and refuses missing exact nodes.  The policy uses the acting player's own hole
cards only.  Opponent ranges used by postflop IPF are rebuilt from that player's
prior public actions; no future board or target action is consumed.

Issue #106 uses this policy as the population continuation component behind the
preflop action/sizing EV grid.  It does not promote a Hero strategy.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.simulation.game_core import EPS, NoLimitHoldemState
from tools.simulation.model_b_runtime import cid, combo_class_ids, legal_combos, weighted_choice
from tools.training.increment_decisions import board_features
from tools.training.model_a_latent_ranges import decode_policy169
from tools.training.model_a_postflop_runtime import (
    calibrated_action_matrix,
    exact_postflop_node,
    target_frequencies,
)
from tools.training.refit_postflop_combo_policy import apply_overlay

DECISION_SCHEMA = "model-a-continuation-decision/v1"
PRE_ORDER = ["LJ", "HJ", "CO", "BTN", "SB", "BB", "SB_BTN"]
POST_ORDER = ["SB", "BB", "LJ", "HJ", "CO", "BTN", "SB_BTN"]
STREETS = ("preflop", "flop", "turn", "river")


class ModelAUnsupportedContext(ValueError):
    """Raised when exact Model-A continuation support does not exist."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize(values: Mapping[str, float]) -> dict[str, float]:
    clean = {str(key): max(0.0, float(value)) for key, value in values.items() if math.isfinite(float(value))}
    total = sum(clean.values())
    if total <= EPS:
        raise ModelAUnsupportedContext("Model A has no positive supported action probability")
    return {key: value / total for key, value in clean.items()}


def _normalize_weights(weights: Sequence[float]) -> list[float]:
    clean = [max(0.0, float(value)) for value in weights]
    total = sum(clean)
    if total <= EPS:
        raise ModelAUnsupportedContext("Model-A latent range lost all probability mass")
    return [value / total for value in clean]


def _position_map(state: NoLimitHoldemState) -> dict[str, str]:
    seats = list(state.seats)
    button_index = seats.index(state.button)
    ordered = [seats[(button_index + offset) % len(seats)] for offset in range(len(seats))]
    templates = {
        2: ["SB_BTN", "BB"],
        3: ["BTN", "SB", "BB"],
        4: ["BTN", "SB", "BB", "CO"],
        5: ["BTN", "SB", "BB", "HJ", "CO"],
        6: ["BTN", "SB", "BB", "LJ", "HJ", "CO"],
    }
    positions = templates.get(len(seats))
    if positions is None:
        raise ModelAUnsupportedContext(f"Model A supports 2-6 seats, got {len(seats)}")
    return dict(zip(ordered, positions))


def _ordered_positions(players: Sequence[str], positions: Mapping[str, str], order: Sequence[str]) -> list[str]:
    rank = {position: index for index, position in enumerate(order)}
    return sorted((positions[player] for player in players), key=lambda position: (rank.get(position, 999), position))


def _family(history: Sequence[Mapping[str, Any]], actor_position: str) -> str:
    if not history:
        return "UNOPENED"
    raises = [i for i, row in enumerate(history) if row["action"] in {"RAISE", "JAM"}]
    limps = [row for row in history if row["action"] == "LIMP"]
    if not raises:
        return "VS_LIMPERS"
    first = raises[0]
    callers = [row for row in history[first + 1 :] if row["action"] == "CALL"]
    actor_raised = any(row["position"] == actor_position and row["action"] in {"RAISE", "JAM"} for row in history)
    actor_called = any(row["position"] == actor_position and row["action"] in {"CALL", "LIMP"} for row in history)
    if len(raises) == 1:
        if limps and first > 0:
            actor_limped = any(row["position"] == actor_position and row["action"] == "LIMP" for row in history)
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


def _pot_type_and_role(preflop_history: Sequence[Mapping[str, Any]], actor: str) -> tuple[str, str]:
    raises = [row for row in preflop_history if row["action"] in {"RAISE", "JAM"}]
    pot_type = "LIMPED" if not raises else "SRP" if len(raises) == 1 else "3BP" if len(raises) == 2 else "4BP_PLUS"
    last_aggressor = raises[-1]["player"] if raises else None
    actor_actions = [row["action"] for row in preflop_history if row["player"] == actor]
    if actor == last_aggressor:
        role = "PFA"
    elif "CALL" in actor_actions:
        role = "CALLER"
    elif "LIMP" in actor_actions:
        role = "LIMPER"
    elif "CHECK" in actor_actions:
        role = "BB_CHECK"
    else:
        role = "OTHER"
    return pot_type, role


def _advance_one(replay: NoLimitHoldemState, final_board: Sequence[str]) -> None:
    if replay.street == "preflop":
        cards = list(final_board[:3])
    elif replay.street == "flop":
        cards = [final_board[3]]
    elif replay.street == "turn":
        cards = [final_board[4]]
    else:
        raise ModelAUnsupportedContext("cannot advance beyond river")
    replay.advance_street(cards)


def _semantic_action(replay: NoLimitHoldemState, event: Mapping[str, Any], preflop_history: Sequence[Mapping[str, Any]]) -> str:
    action = str(event.get("action") or "").upper()
    actor = str(event.get("player") or "")
    view = replay.legal_view(actor)
    if action != "RAISE":
        if replay.street == "preflop" and action == "CALL":
            raised = any(row["action"] in {"RAISE", "JAM"} for row in preflop_history)
            return "CALL" if raised else "LIMP"
        return action
    target = float(event.get("target_total_bb") or 0.0)
    if abs(target - float(view["max_raise_to_bb"])) <= 1e-6:
        return "JAM"
    if replay.street == "preflop":
        return "RAISE"
    return "BET" if float(view["current_price_bb"]) <= EPS else "RAISE"


def _preflop_decision(replay: NoLimitHoldemState, actor: str, history: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    positions = _position_map(replay)
    actor_position = positions[actor]
    live = [player for player in replay.seats if not replay.folded[player] and not replay.all_in[player]]
    all_in = [player for player in replay.seats if not replay.folded[player] and replay.all_in[player]]
    clean_history = [{"position": row["position"], "action": row["action"]} for row in history]
    return {
        "actor_position": actor_position,
        "table_size": len(replay.seats),
        "raise_level": sum(row["action"] in {"RAISE", "JAM"} for row in history),
        "family": _family(clean_history, actor_position),
        "live_positions": _ordered_positions(live, positions, PRE_ORDER),
        "all_in_positions": _ordered_positions(all_in, positions, PRE_ORDER),
        "history": clean_history,
    }


def _postflop_decision(
    replay: NoLimitHoldemState,
    actor: str,
    *,
    preflop_history: Sequence[Mapping[str, Any]],
    street_history: Sequence[str],
    street_start_players: int,
) -> dict[str, Any]:
    positions = _position_map(replay)
    active = [player for player in replay.seats if not replay.folded[player] and not replay.all_in[player]]
    ordered = sorted(active, key=lambda player: (POST_ORDER.index(positions[player]) if positions[player] in POST_ORDER else 999, positions[player]))
    index = ordered.index(actor)
    relative = "ONLY" if len(ordered) <= 1 else "OOP" if index == 0 else "IP" if index == len(ordered) - 1 else "MIDDLE"
    pot_type, role = _pot_type_and_role(preflop_history, actor)
    history_token = ">".join(action for action in street_history if action != "FOLD")
    key = "|".join(map(str, [replay.street, street_start_players, len(active), relative, pot_type, role, history_token]))
    view = replay.legal_view(actor)
    pot = float(view["pot_before_bb"])
    to_call = float(view["to_call_bb"])
    remaining = float(view["actor_remaining_bb"])
    return {
        "street": replay.street,
        "mode": "FACING" if to_call > EPS else "FREE",
        "street_start_players": int(street_start_players),
        "active_players": len(active),
        "relative_position": relative,
        "pot_type": pot_type,
        "preflop_role": role,
        "street_history": history_token,
        "canonical_key": key,
        "board": list(replay.board),
        "board_features": board_features(list(replay.board)),
        "pot_before_bb": pot,
        "to_call_bb": to_call,
        "facing_price_pot": to_call / pot if pot > EPS else 0.0,
        "own_size_pot": None,
        "spr": remaining / pot if pot > EPS else 0.0,
    }


def _semantic_trace(state: NoLimitHoldemState) -> tuple[list[dict[str, Any]], NoLimitHoldemState, list[dict[str, Any]], dict[str, list[str]], dict[str, int]]:
    replay = NoLimitHoldemState(
        seats=list(state.seats),
        button=state.button,
        stacks_bb=state.starting_stacks_bb,
        small_blind_bb=state.small_blind_bb,
        big_blind_bb=state.big_blind_bb,
    )
    preflop_history: list[dict[str, Any]] = []
    street_histories: dict[str, list[str]] = {street: [] for street in STREETS}
    street_start = {"preflop": sum(not replay.all_in[player] for player in replay.live_players)}
    trace: list[dict[str, Any]] = []

    for event in state.action_log:
        target_street = str(event.get("street") or "")
        while replay.street != target_street:
            _advance_one(replay, state.board)
            street_start[replay.street] = sum(not replay.all_in[player] for player in replay.live_players)
        actor = str(event["player"])
        semantic = _semantic_action(replay, event, preflop_history)
        if replay.street == "preflop":
            decision = _preflop_decision(replay, actor, preflop_history)
        else:
            decision = _postflop_decision(
                replay,
                actor,
                preflop_history=preflop_history,
                street_history=street_histories[replay.street],
                street_start_players=street_start[replay.street],
            )
        trace.append({"player": actor, "street": replay.street, "semantic_action": semantic, "decision": decision})
        replay.apply_action(actor, str(event["action"]), target_total_bb=event.get("target_total_bb"))
        if semantic != "FOLD":
            if target_street == "preflop":
                preflop_history.append({"player": actor, "position": decision["actor_position"], "action": semantic})
            else:
                street_histories[target_street].append(semantic)

    while replay.street != state.street:
        _advance_one(replay, state.board)
        street_start[replay.street] = sum(not replay.all_in[player] for player in replay.live_players)

    return trace, replay, preflop_history, street_histories, street_start


def exact_preflop_node(model: Mapping[str, Any], decision: Mapping[str, Any]) -> Mapping[str, Any] | None:
    matches = []
    wanted_history = [(str(row.get("position")), str(row.get("action"))) for row in decision.get("history", [])]
    for node in model.get("nodes", []):
        context = node.get("context") or {}
        history = [(str(row.get("position")), str(row.get("action"))) for row in context.get("history", [])]
        if (
            str(context.get("actor_position") or "") == str(decision.get("actor_position") or "")
            and int(context.get("table_size") or 0) == int(decision.get("table_size") or 0)
            and int(context.get("raise_level") or 0) == int(decision.get("raise_level") or 0)
            and str(context.get("family") or "") == str(decision.get("family") or "")
            and list(context.get("live_positions") or []) == list(decision.get("live_positions") or [])
            and list(context.get("all_in_positions") or []) == list(decision.get("all_in_positions") or [])
            and history == wanted_history
        ):
            matches.append(node)
    if not matches:
        return None
    return max(matches, key=lambda node: int((node.get("coverage") or {}).get("population_decisions") or 0))


def _remove_blockers(combos: list[tuple[int, int]], weights: list[float], board: Sequence[str]) -> tuple[list[tuple[int, int]], list[float]]:
    blocked = {cid(card) for card in board}
    kept = [(combo, weight) for combo, weight in zip(combos, weights) if combo[0] not in blocked and combo[1] not in blocked]
    if not kept:
        raise ModelAUnsupportedContext("public board removed all latent combos")
    out_combos, out_weights = zip(*kept)
    return list(out_combos), _normalize_weights(out_weights)


def _node_action_probability(node: Mapping[str, Any], model: Mapping[str, Any], combo: tuple[int, int], semantic_action: str) -> float:
    policy = decode_policy169(dict(node), dict(model))
    if policy is not None:
        hand = combo_class_ids(*combo)
        return max(0.0, float((policy.get(hand) or {}).get(semantic_action) or 0.0))
    frequencies = (node.get("population_model") or {}).get("frequencies") or {}
    return max(0.0, float(frequencies.get(semantic_action) or 0.0))


def _semantic_legal(semantic: str, decision: Mapping[str, Any], view: Mapping[str, Any]) -> bool:
    legal = set(view["legal_actions"])
    if semantic in {"FOLD", "CHECK"}:
        return semantic in legal
    if semantic in {"LIMP", "CALL"}:
        expected = "LIMP" if int(decision.get("raise_level") or 0) == 0 else "CALL"
        return "CALL" in legal and semantic == expected
    if semantic == "JAM":
        return "RAISE" in legal
    if semantic == "RAISE":
        return "RAISE" in legal and str(decision.get("street") or "preflop") == "preflop"
    if semantic == "BET":
        return "RAISE" in legal and str(decision.get("mode") or "") == "FREE"
    return semantic == "RAISE" and "RAISE" in legal and str(decision.get("mode") or "") == "FACING"


def _stat_value(stats: Any) -> float | None:
    if isinstance(stats, (int, float)) and math.isfinite(float(stats)):
        return float(stats)
    if not isinstance(stats, Mapping):
        return None
    for key in ("median", "p50", "mean"):
        value = stats.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0:
            return float(value)
    return None


def _empirical_raise_target(node: Mapping[str, Any], state: NoLimitHoldemState, actor: str) -> tuple[float, str]:
    view = state.legal_view(actor)
    paid = float(view["actor_street_contribution_bb"])
    pot = float(view["pot_before_bb"])
    minimum = None if view["min_raise_to_bb"] is None else float(view["min_raise_to_bb"])
    maximum = float(view["max_raise_to_bb"])
    current = float(view["current_price_bb"])
    containers = [node.get("continuous") or {}, (node.get("population_model") or {}).get("continuous") or {}]
    target = None
    source = "LEGAL_MIN_FALLBACK"
    for container in containers:
        for key in ("target_total_bb", "raise_to_bb"):
            value = _stat_value(container.get(key))
            if value is not None:
                target, source = value, f"EXACT_NODE_{key.upper()}"
                break
        if target is not None:
            break
        for key in ("action_add_bb", "raise_add_bb"):
            value = _stat_value(container.get(key))
            if value is not None:
                target, source = paid + value, f"EXACT_NODE_{key.upper()}"
                break
        if target is not None:
            break
        for key in ("own_size_pot", "raise_size_pot", "action_size_pot"):
            value = _stat_value(container.get(key))
            if value is not None and pot > EPS:
                target, source = paid + value * pot, f"EXACT_NODE_{key.upper()}"
                break
        if target is not None:
            break
    if target is None:
        target = minimum if minimum is not None else min(maximum, current + state.big_blind_bb)
    target = min(maximum, max(float(target), minimum if minimum is not None else current + EPS))
    if target <= current + EPS:
        raise ModelAUnsupportedContext("exact node has no translatable legal raise sizing")
    return round(target, 9), source


class ModelAContinuationPolicy:
    """Exact-node card-aware Model-A policy using the selected #102 continuation."""

    def __init__(self, preflop_model: Mapping[str, Any], postflop_model: Mapping[str, Any], *, identity: Mapping[str, Any] | None = None) -> None:
        self.preflop_model = dict(preflop_model)
        self.postflop_model = dict(postflop_model)
        self.identity = dict(identity or {})

    @classmethod
    def from_paths(cls, preflop_path: Path, postflop_base_path: Path, continuation_overlay_path: Path) -> "ModelAContinuationPolicy":
        preflop_path = Path(preflop_path)
        postflop_base_path = Path(postflop_base_path)
        continuation_overlay_path = Path(continuation_overlay_path)
        preflop = json.loads(preflop_path.read_text(encoding="utf-8"))
        base = json.loads(postflop_base_path.read_text(encoding="utf-8"))
        overlay = json.loads(continuation_overlay_path.read_text(encoding="utf-8"))
        actual_base = _sha256(postflop_base_path)
        if str(overlay.get("base_postflop_model_sha256") or "") != actual_base:
            raise ValueError("#102 continuation overlay does not match the supplied postflop baseline")
        if (overlay.get("selection") or {}).get("test_consumed") is not False:
            raise ValueError("#102 continuation selection must not consume TEST")
        selected = apply_overlay(base, overlay)
        return cls(
            preflop,
            selected,
            identity={
                "preflop_sha256": _sha256(preflop_path),
                "postflop_baseline_sha256": actual_base,
                "continuation_overlay_sha256": _sha256(continuation_overlay_path),
                "stage_b_decision": (overlay.get("selection") or {}).get("stage_b_decision"),
            },
        )

    def _posterior_from_history(self, state: NoLimitHoldemState, actor: str, trace: Sequence[Mapping[str, Any]]) -> tuple[list[tuple[int, int]], list[float]]:
        combos = list(legal_combos([], []))
        weights = [1.0 / len(combos)] * len(combos)
        current_board: list[str] = []
        for item in trace:
            if item["player"] != actor:
                continue
            decision = item["decision"]
            semantic = str(item["semantic_action"])
            if item["street"] == "preflop":
                node = exact_preflop_node(self.preflop_model, decision)
                if node is None:
                    raise ModelAUnsupportedContext("missing exact preflop Model-A node in prior history")
                weights = _normalize_weights([
                    weight * max(1e-12, _node_action_probability(node, self.preflop_model, combo, semantic))
                    for combo, weight in zip(combos, weights)
                ])
                continue
            board = list(decision.get("board") or [])
            if board != current_board:
                combos, weights = _remove_blockers(combos, weights, board)
                current_board = board
            node = exact_postflop_node(self.postflop_model, decision)
            if node is None:
                raise ModelAUnsupportedContext("missing exact postflop Model-A node in prior history")
            target = target_frequencies(node, decision, self.postflop_model)
            actions, matrix = calibrated_action_matrix(combos, weights, decision, target, self.postflop_model)
            if semantic not in actions:
                raise ModelAUnsupportedContext(f"prior postflop action {semantic} is outside exact-node support")
            ai = actions.index(semantic)
            weights = _normalize_weights([weight * max(1e-12, matrix[index][ai]) for index, weight in enumerate(weights)])
        if list(state.board) != current_board:
            combos, weights = _remove_blockers(combos, weights, state.board)
        return combos, weights

    def action_probabilities(self, state: NoLimitHoldemState, *, actor: str, hole_cards: Sequence[str], **_: Any) -> dict[str, Any]:
        if state.next_actor != actor:
            raise ModelAUnsupportedContext(f"{actor} is not the next player to act")
        if len(hole_cards) != 2:
            raise ValueError("Model A requires exactly two acting-player hole cards")
        trace, replay, preflop_history, street_histories, street_start = _semantic_trace(state)
        if replay.to_snapshot(include_log=False) != state.to_snapshot(include_log=False):
            raise AssertionError("semantic replay diverged from NoLimitHoldemState")
        view = state.legal_view(actor)
        if state.street == "preflop":
            decision = _preflop_decision(state, actor, preflop_history)
            node = exact_preflop_node(self.preflop_model, decision)
            if node is None:
                raise ModelAUnsupportedContext("missing exact preflop Model-A node")
            policy = decode_policy169(dict(node), self.preflop_model)
            hand = combo_class_ids(cid(hole_cards[0]), cid(hole_cards[1]))
            raw = (policy or {}).get(hand) if policy is not None else None
            if raw is None:
                raw = (node.get("population_model") or {}).get("frequencies") or {}
                source = "EXACT_NODE_MARGINAL_FALLBACK"
            else:
                source = "EXACT_NODE_POLICY169"
            supported = {action: float(probability) for action, probability in raw.items() if _semantic_legal(action, decision, view)}
        else:
            decision = _postflop_decision(
                state,
                actor,
                preflop_history=preflop_history,
                street_history=street_histories[state.street],
                street_start_players=street_start[state.street],
            )
            node = exact_postflop_node(self.postflop_model, decision)
            if node is None:
                raise ModelAUnsupportedContext("missing exact postflop Model-A node")
            combos, weights = self._posterior_from_history(state, actor, trace)
            actual = tuple(sorted((cid(hole_cards[0]), cid(hole_cards[1]))))
            try:
                combo_index = combos.index(actual)
            except ValueError as exc:
                raise ModelAUnsupportedContext("acting player's dealt combo is outside reconstructed Model-A support") from exc
            target = target_frequencies(node, decision, self.postflop_model)
            actions, matrix = calibrated_action_matrix(combos, weights, decision, target, self.postflop_model)
            supported = {
                action: float(matrix[combo_index][index])
                for index, action in enumerate(actions)
                if _semantic_legal(action, decision, view)
            }
            source = "EXACT_NODE_SELECTED_CONTINUATION"
        probabilities = _normalize(supported)
        return {
            "probabilities": probabilities,
            "semantic_context": decision,
            "node_id": node.get("id"),
            "support": int((node.get("coverage") or {}).get("population_decisions") or 0),
            "source": source,
        }

    def decide(self, state: NoLimitHoldemState, *, seed_parts: Sequence[object], **context: Any) -> dict[str, Any]:
        actor = str(context["actor"])
        info = self.action_probabilities(state, **context)
        probabilities = info["probabilities"]
        semantic = str(weighted_choice(list(probabilities), list(probabilities.values()), *seed_parts, "model-a-action"))
        view = state.legal_view(actor)
        target = None
        sizing_source = None
        if semantic in {"LIMP", "CALL"}:
            core = "CALL"
        elif semantic in {"BET", "RAISE"}:
            core = "RAISE"
            if state.street == "preflop":
                node = exact_preflop_node(self.preflop_model, info["semantic_context"])
            else:
                node = exact_postflop_node(self.postflop_model, info["semantic_context"])
            if node is None:
                raise ModelAUnsupportedContext("selected raise lost exact-node support")
            target, sizing_source = _empirical_raise_target(node, state, actor)
        elif semantic == "JAM":
            core = "RAISE"
            target = float(view["max_raise_to_bb"])
            sizing_source = "JAM_BOUNDARY"
        else:
            core = semantic
        incremental = (
            float(target) - float(view["actor_street_contribution_bb"])
            if core == "RAISE"
            else float(view["to_call_bb"]) if core == "CALL" else 0.0
        )
        return {
            "schema": DECISION_SCHEMA,
            "action": core,
            "semantic_action": semantic,
            "target_total_bb": target,
            "incremental_cost_bb": round(incremental, 9),
            "probabilities": probabilities,
            "node_id": info["node_id"],
            "support": info["support"],
            "source": info["source"],
            "sizing_source": sizing_source,
            "semantic_context": info["semantic_context"],
        }
