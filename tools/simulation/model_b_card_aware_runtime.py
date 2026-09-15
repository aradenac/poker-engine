#!/usr/bin/env python3
"""Card/context-aware candidate runtime for independent opponent Model B.

This module is intentionally a *runtime contract*, not a fitted production model.
It consumes only an independent Model-B behavior artifact plus the simulated
opponent's own private cards and the public :mod:`game_core` state. Model A
outputs are neither accepted nor imported.

The artifact can condition action/sizing tables on public price, stack, sequence
and player-count features plus a private hand bucket. Hierarchical backoff keeps
sparse contexts explicit. Action probabilities are always re-normalized over
the actions currently legal under the shared NLHE rules core.
"""
from __future__ import annotations

import collections
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.simulation.game_core import EPS, NoLimitHoldemState
from tools.simulation.model_b_runtime import best, combo_class, select_node, weighted_choice

BEHAVIOR_SCHEMA = "independent-opponent-model-b-behavior/v1"
DECISION_SCHEMA = "independent-opponent-model-b-decision/v1"
SIZING_SEMANTICS = "incremental_cost_over_pot_before"
CATEGORY = {
    0: "HIGH_CARD",
    1: "ONE_PAIR",
    2: "TWO_PAIR",
    3: "TRIPS",
    4: "STRAIGHT",
    5: "FLUSH",
    6: "FULL_HOUSE",
    7: "QUADS",
    8: "STRAIGHT_FLUSH",
}
RANK_VALUE = {rank: i for i, rank in enumerate("23456789TJQKA", start=2)}


def price_bucket(value: float | None) -> str:
    if value is None or not math.isfinite(float(value)):
        return "UNKNOWN"
    value = float(value)
    if value <= 0.25:
        return "P00_25"
    if value <= 0.50:
        return "P25_50"
    if value <= 0.75:
        return "P50_75"
    if value <= 1.00:
        return "P75_100"
    if value <= 1.50:
        return "P100_150"
    return "P150_PLUS"


def spr_bucket(value: float | None) -> str:
    if value is None or not math.isfinite(float(value)) or float(value) < 0:
        return "UNKNOWN"
    value = float(value)
    if value < 1.0:
        return "SPR_LT1"
    if value < 3.0:
        return "SPR_1_3"
    if value < 6.0:
        return "SPR_3_6"
    if value < 12.0:
        return "SPR_6_12"
    return "SPR_12_PLUS"


def opponents_bucket(opponents: int) -> str:
    opponents = int(opponents)
    if opponents <= 0:
        return "NONE"
    if opponents == 1:
        return "HEADS_UP"
    if opponents == 2:
        return "THREE_WAY"
    return "FOUR_PLUS"


def recent_sequence_bucket(state: NoLimitHoldemState, *, limit: int = 6) -> str:
    """Return the recent voluntary public sequence on the current street."""
    tokens = []
    token = {"FOLD": "F", "CHECK": "X", "CALL": "C", "RAISE": "R"}
    for event in state.action_log:
        if event.get("street") != state.street:
            continue
        action = str(event.get("action", "")).upper()
        if action in token:
            tokens.append(token[action])
    if not tokens:
        return "EMPTY"
    return ">".join(tokens[-max(1, int(limit)):])


def board_texture(board: Sequence[str]) -> str:
    if len(board) < 3:
        return "PREFLOP"
    ranks = [str(card)[0].upper() for card in board]
    suits = collections.Counter(str(card)[1].lower() for card in board)
    paired = "PAIRED" if len(set(ranks)) < len(ranks) else "UNPAIRED"
    max_suit = max(suits.values())
    suit = "RAINBOW" if max_suit == 1 else "TWO_SUIT" if max_suit == 2 else f"{max_suit}_FLUSH"
    return f"{paired}_{suit}"


def _draw_tags(hole_cards: Sequence[str], board: Sequence[str], made_category: int) -> list[str]:
    if len(board) >= 5:
        return []
    cards = list(hole_cards) + list(board)
    tags: list[str] = []

    if made_category < 5:
        suit_counts = collections.Counter(card[1].lower() for card in cards)
        for suit, count in suit_counts.items():
            if count == 4 and any(card[1].lower() == suit for card in hole_cards):
                tags.append("FD")
                break

    if made_category < 4:
        ranks = {RANK_VALUE[card[0].upper()] for card in cards}
        hole_ranks = {RANK_VALUE[card[0].upper()] for card in hole_cards}
        if 14 in ranks:
            ranks.add(1)
        if 14 in hole_ranks:
            hole_ranks.add(1)
        for low in range(1, 11):
            window = set(range(low, low + 5))
            if len(ranks & window) == 4 and bool(hole_ranks & window):
                tags.append("SD")
                break
    return tags


def hand_bucket(hole_cards: Sequence[str], board: Sequence[str], street: str) -> str:
    if len(hole_cards) != 2:
        raise ValueError("Model B decision requires exactly two opponent hole cards")
    cards = [str(card) for card in list(hole_cards) + list(board)]
    if len(cards) != len(set(cards)):
        raise ValueError("duplicate private/public card in Model B state")
    street = str(street).lower()
    if street == "preflop":
        return f"PREFLOP_{combo_class(hole_cards)}"
    if len(board) < 3:
        raise ValueError(f"{street} requires a public flop")
    category = int(best(cards)[0])
    label = CATEGORY.get(category)
    if label is None:
        raise ValueError(f"unknown hand category {category}")
    return "+".join([label] + _draw_tags(hole_cards, board, category))


def _support_state(n: float, minimum: int) -> str:
    return "SUPPORTED" if float(n) >= float(minimum) else "BACKOFF_LOW_SUPPORT"


def _sizing_observations(node: Mapping[str, Any]) -> list[tuple[float, float]]:
    """Return (ratio, weight), accepting old unweighted and new soft-fit nodes."""
    if "weighted_values" in node:
        rows: list[tuple[float, float]] = []
        for raw in node.get("weighted_values") or []:
            if not isinstance(raw, Mapping):
                continue
            value = float(raw.get("value", 0.0))
            weight = float(raw.get("weight", 0.0))
            if math.isfinite(value) and value > 0 and math.isfinite(weight) and weight > 0:
                rows.append((value, weight))
        return rows
    rows = []
    for raw in node.get("values", []):
        value = float(raw)
        if math.isfinite(value) and value > 0:
            rows.append((value, 1.0))
    return rows


class CardAwareModelBPolicy:
    """Evaluate a card-aware independent Model-B behavior artifact."""

    def __init__(self, behavior: Mapping[str, Any]) -> None:
        self.behavior = dict(behavior)
        self._validate()

    @classmethod
    def from_path(cls, path: Path) -> "CardAwareModelBPolicy":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def _validate(self) -> None:
        if self.behavior.get("schema") != BEHAVIOR_SCHEMA:
            raise ValueError(f"unsupported behavior schema: {self.behavior.get('schema')}")
        action = self.behavior.get("action")
        sizing = self.behavior.get("sizing")
        if not isinstance(action, dict) or not isinstance(action.get("levels"), list) or not action["levels"]:
            raise ValueError("behavior action hierarchy is required")
        if float(action.get("alpha_per_action", 0.0)) <= 0:
            raise ValueError("action alpha_per_action must be positive")
        if int(action.get("backoff_min_observations", 0)) <= 0:
            raise ValueError("action backoff_min_observations must be positive")
        if not isinstance(sizing, dict) or not isinstance(sizing.get("levels"), list) or not sizing["levels"]:
            raise ValueError("behavior sizing hierarchy is required")
        if sizing.get("semantics") != SIZING_SEMANTICS:
            raise ValueError(f"unsupported sizing semantics: {sizing.get('semantics')}")
        if int(sizing.get("backoff_min_observations", 0)) <= 0:
            raise ValueError("sizing backoff_min_observations must be positive")

    def features(
        self,
        state: NoLimitHoldemState,
        *,
        actor: str,
        hole_cards: Sequence[str],
        profile: int,
        relative_position: str = "NA",
        pot_type: str = "NA",
        preflop_role: str = "NA",
    ) -> dict[str, Any]:
        view = state.legal_view(actor)
        pot = float(view["pot_before_bb"])
        to_call = float(view["to_call_bb"])
        remaining = float(view["actor_remaining_bb"])
        mode = "FREE" if bool(view["free_check"]) else "FACING"
        live_opponents = sum(1 for player in state.live_players if player != actor)
        return {
            "profile": int(profile),
            "street": state.street,
            "mode": mode,
            "relative_position": str(relative_position),
            "pot_type": str(pot_type),
            "preflop_role": str(preflop_role),
            "price_bucket": "FREE" if mode == "FREE" else price_bucket(to_call / pot if pot > EPS else None),
            "spr_bucket": spr_bucket(remaining / pot if pot > EPS else None),
            "opponents_bucket": opponents_bucket(live_opponents),
            "sequence_bucket": recent_sequence_bucket(state),
            "raise_level": sum(
                1 for event in state.action_log
                if event.get("street") == state.street and str(event.get("action", "")).upper() == "RAISE"
            ),
            "board_texture": board_texture(state.board),
            "hand_bucket": hand_bucket(hole_cards, state.board, state.street),
        }

    @staticmethod
    def _selected(levels: Sequence[dict], row: dict[str, Any], minimum: int) -> tuple[dict, dict[str, Any]]:
        node, level, key = select_node(levels, row, minimum)
        n = float(node.get("n", 0.0))
        return node, {
            "level": int(level),
            "key": str(key),
            "support": n,
            "support_state": _support_state(n, minimum),
        }

    def action_probabilities(self, state: NoLimitHoldemState, **context: Any) -> dict[str, Any]:
        actor = str(context["actor"])
        features = self.features(state, **context)
        cfg = self.behavior["action"]
        node, support = self._selected(cfg["levels"], features, int(cfg["backoff_min_observations"]))
        legal = list(state.legal_view(actor)["legal_actions"])
        counts = node.get("counts", {})
        alpha = float(cfg["alpha_per_action"])
        masses = {action: max(0.0, float(counts.get(action, 0.0))) + alpha for action in legal}
        total = sum(masses.values())
        if total <= 0 or not math.isfinite(total):
            raise ValueError("card-aware Model B action node has no finite legal probability mass")
        probabilities = {action: mass / total for action, mass in masses.items()}
        return {
            "probabilities": probabilities,
            "features": features,
            "selection": support,
            "legal_actions": legal,
        }

    def sizing_candidates(self, state: NoLimitHoldemState, **context: Any) -> dict[str, Any]:
        actor = str(context["actor"])
        view = state.legal_view(actor)
        if "RAISE" not in view["legal_actions"]:
            raise ValueError("RAISE is not legal in this state")
        features = self.features(state, **context)
        row = {**features, "action": "RAISE"}
        cfg = self.behavior["sizing"]
        node, support = self._selected(cfg["levels"], row, int(cfg["backoff_min_observations"]))
        pot = float(view["pot_before_bb"])
        if pot <= EPS:
            raise ValueError("cannot translate pot-relative sizing with an empty pot")
        paid = float(view["actor_street_contribution_bb"])
        current_price = float(view["current_price_bb"])
        max_to = float(view["max_raise_to_bb"])
        min_to = None if view["min_raise_to_bb"] is None else float(view["min_raise_to_bb"])

        candidates: list[dict[str, float]] = []
        for ratio, weight in _sizing_observations(node):
            target = paid + ratio * pot
            if target <= current_price + EPS or target > max_to + EPS:
                continue
            if min_to is not None and target + EPS < min_to and abs(target - max_to) > EPS:
                continue
            candidates.append({
                "incremental_cost_over_pot": ratio,
                "target_total_bb": round(min(target, max_to), 9),
                "weight": weight,
            })

        source = "EMPIRICAL"
        if not candidates:
            if max_to <= current_price + EPS:
                raise ValueError("no legal raise target remains")
            target = max_to if min_to is None or min_to > max_to + EPS else min_to
            candidates = [{
                "incremental_cost_over_pot": (target - paid) / pot,
                "target_total_bb": round(target, 9),
                "weight": 1.0,
            }]
            source = "LEGAL_BOUNDARY_FALLBACK"

        unique: dict[float, dict[str, float]] = {}
        for candidate in candidates:
            target = candidate["target_total_bb"]
            if target not in unique:
                unique[target] = dict(candidate)
            else:
                prior_weight = unique[target]["weight"]
                added_weight = candidate["weight"]
                total_weight = prior_weight + added_weight
                unique[target]["incremental_cost_over_pot"] = (
                    unique[target]["incremental_cost_over_pot"] * prior_weight
                    + candidate["incremental_cost_over_pot"] * added_weight
                ) / total_weight
                unique[target]["weight"] = total_weight
        candidates = [unique[key] for key in sorted(unique)]
        return {
            "candidates": candidates,
            "features": features,
            "selection": support,
            "source": source,
            "legal_bounds": {"min_raise_to_bb": min_to, "max_raise_to_bb": max_to},
        }

    def sample_action(self, state: NoLimitHoldemState, *, seed_parts: Sequence[object], **context: Any) -> str:
        result = self.action_probabilities(state, **context)
        probabilities = result["probabilities"]
        return str(weighted_choice(list(probabilities), list(probabilities.values()), *seed_parts))

    def sample_raise_target(
        self,
        state: NoLimitHoldemState,
        *,
        seed_parts: Sequence[object],
        **context: Any,
    ) -> tuple[float, dict[str, Any]]:
        result = self.sizing_candidates(state, **context)
        candidates = result["candidates"]
        selected = weighted_choice(candidates, [row["weight"] for row in candidates], *seed_parts)
        return float(selected["target_total_bb"]), result

    def decide(
        self,
        state: NoLimitHoldemState,
        *,
        seed_parts: Sequence[object],
        **context: Any,
    ) -> dict[str, Any]:
        actor = str(context["actor"])
        view = state.legal_view(actor)
        action_info = self.action_probabilities(state, **context)
        probabilities = action_info["probabilities"]
        action = str(weighted_choice(list(probabilities), list(probabilities.values()), *seed_parts, "action"))
        target = None
        sizing_info = None
        if action == "RAISE":
            target, sizing_info = self.sample_raise_target(state, seed_parts=tuple(seed_parts) + ("sizing",), **context)
            incremental = target - float(view["actor_street_contribution_bb"])
        elif action == "CALL":
            incremental = float(view["to_call_bb"])
        else:
            incremental = 0.0
        return {
            "schema": DECISION_SCHEMA,
            "action": action,
            "target_total_bb": target,
            "incremental_cost_bb": round(float(incremental), 9),
            "probabilities": probabilities,
            "features": action_info["features"],
            "action_selection": action_info["selection"],
            "sizing": sizing_info,
        }
