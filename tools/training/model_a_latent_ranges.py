#!/usr/bin/env python3
"""Training-side exact-combo posterior helpers for Model A.

The module intentionally starts with the part that can be made exactly equivalent
to the browser without circularity: preflop action conditioning plus public-card
blocking.  A target postflop decision is only admitted while it has no earlier
postflop action by the same player.  Later decisions fail closed until the
postflop action-likelihood/IPF runtime has an explicit Python parity port.

This makes the first Stage-B dataset scientifically usable instead of silently
pretending a turn/river range is still the flop prior.
"""
from __future__ import annotations

import base64
import math
import struct
from dataclasses import dataclass
from typing import Iterable, Sequence

from tools.simulation.model_b_runtime import ccode, cid, combo_class_ids, legal_combos

EPS = 1e-12


class LatentRangeError(ValueError):
    pass


class UnsupportedPostflopHistory(LatentRangeError):
    pass


def matrix_notations() -> list[str]:
    """Mirror site/index.html matrixNotations() ordering."""
    ranks = list(reversed("23456789TJQKA"))
    out = []
    for row in range(13):
        for col in range(13):
            if row == col:
                out.append(ranks[row] + ranks[col])
            elif row < col:
                out.append(ranks[row] + ranks[col] + "s")
            else:
                out.append(ranks[col] + ranks[row] + "o")
    return out


def decode_policy169(node: dict, model: dict) -> dict[str, dict[str, float]] | None:
    """Decode the browser's embedded action-major uint16 policy contract."""
    q = ((node.get("population_model") or {}).get("policy169_q_b64"))
    if not q:
        return None
    hand_order = q.get("hand_order")
    if isinstance(hand_order, list):
        hands = list(hand_order)
    elif hand_order in (None, "", "hand_grid.classes"):
        hands = list((model.get("hand_grid") or {}).get("classes") or matrix_notations())
    else:
        raise LatentRangeError(f"unsupported policy169 hand_order reference: {hand_order!r}")
    actions = list(q.get("actions") or [])
    shape = list(q.get("shape") or [])
    if len(shape) != 2 or int(shape[0]) != len(actions) or int(shape[1]) != len(hands):
        raise LatentRangeError("invalid policy169 shape")
    scale = float(q.get("scale") or 0.0)
    dtype = q.get("dtype")
    if scale <= 0 or dtype not in {"uint16-le", "uint16-be"} or not isinstance(q.get("data"), str):
        raise LatentRangeError("invalid policy169 encoding contract")
    raw = base64.b64decode(q["data"], validate=True)
    action_count, hand_count = map(int, shape)
    if len(raw) != action_count * hand_count * 2:
        raise LatentRangeError("policy169 byte length does not match shape")
    endian = "<" if dtype == "uint16-le" else ">"
    values = struct.unpack(endian + "H" * (action_count * hand_count), raw)
    policy: dict[str, dict[str, float]] = {}
    for hi, hand in enumerate(hands):
        row = {}
        total = 0.0
        for ai, action in enumerate(actions):
            qv = values[ai * hand_count + hi]  # v3 action-major layout
            value = (0.25 / scale) if qv == 0 else (qv / scale)
            row[action] = value
            total += value
        if total <= 0:
            raise LatentRangeError(f"zero policy mass for {hand}")
        policy[hand] = {action: value / total for action, value in row.items()}
    return policy


def _same_strings(a: Iterable[str] | None, b: Iterable[str] | None) -> bool:
    return list(a or []) == list(b or [])


def _history_equal(a: Iterable[dict] | None, b: Iterable[dict] | None) -> bool:
    aa, bb = list(a or []), list(b or [])
    return len(aa) == len(bb) and all(
        str(x.get("action")) == str(y.get("action")) and str(x.get("position")) == str(y.get("position"))
        for x, y in zip(aa, bb)
    )


def exact_preflop_node(model: dict, decision: dict) -> dict | None:
    """Exact structural half of browser findClosestPopulationNode().

    Training never falls back to a nearest node: a missing exact context is
    excluded and audited.
    """
    candidates = []
    for node in model.get("nodes") or []:
        c = node.get("context") or {}
        if str(c.get("actor_position") or "") != str(decision.get("actor_position") or ""):
            continue
        if int(c.get("table_size") or 0) != int(decision.get("table_size") or 0):
            continue
        if int(c.get("raise_level") or 0) != int(decision.get("raise_level") or 0):
            continue
        if str(c.get("family") or "") != str(decision.get("family") or ""):
            continue
        if not _same_strings(c.get("live_positions"), decision.get("live_positions")):
            continue
        if not _same_strings(c.get("all_in_positions"), decision.get("all_in_positions")):
            continue
        if not _history_equal(c.get("history"), decision.get("history")):
            continue
        legal = list((node.get("population_model") or {}).get("legal_actions") or [])
        if decision.get("action") not in legal:
            continue
        candidates.append(node)
    if not candidates:
        return None
    return max(candidates, key=lambda n: int((n.get("coverage") or {}).get("population_decisions") or 0))


@dataclass(frozen=True)
class ComboPosterior:
    combos: tuple[tuple[int, int], ...]
    weights: tuple[float, ...]
    matched_preflop_actions: int
    blocked_cards: tuple[str, ...]

    @property
    def support(self) -> int:
        return sum(1 for w in self.weights if w > 0)

    @property
    def effective_support(self) -> float:
        den = sum(w * w for w in self.weights)
        return (1.0 / den) if den > 0 else 0.0

    @property
    def entropy_nats(self) -> float:
        return -sum(w * math.log(w) for w in self.weights if w > 0)

    def probability_of_cards(self, cards: Sequence[str]) -> float:
        if len(cards) != 2:
            return 0.0
        target = tuple(sorted((cid(cards[0]), cid(cards[1]))))
        for combo, weight in zip(self.combos, self.weights):
            if combo == target:
                return weight
        return 0.0

    def class_mass(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for (a, b), weight in zip(self.combos, self.weights):
            hand = combo_class_ids(a, b)
            out[hand] = out.get(hand, 0.0) + weight
        return out


def _normalize(weights: list[float]) -> list[float]:
    total = sum(max(0.0, float(w)) for w in weights)
    if total <= 0:
        raise LatentRangeError("range posterior lost all probability mass")
    return [max(0.0, float(w)) / total for w in weights]


def _hero_blockers(hand_rows: Sequence[dict]) -> list[str]:
    for row in hand_rows:
        if row.get("is_hero") and row.get("known_cards"):
            cards = list(row.get("known_cards") or [])
            if len(cards) == 2:
                return cards
    return []


def _target_player_prior_postflop_rows(hand_rows: Sequence[dict], target_index: int, player: str) -> list[dict]:
    return [
        row for row in hand_rows[:target_index]
        if row.get("player") == player and row.get("street") in {"flop", "turn", "river"}
    ]


def posterior_before_first_postflop_action(
    hand_rows: Sequence[dict], target_index: int, preflop_model: dict
) -> ComboPosterior:
    """Reconstruct the target player's exact-combo posterior without leakage.

    The target action is never read for conditioning.  Public board cards at the
    target step and Hero's hole cards are legitimate blockers.  A player with an
    earlier postflop decision fails closed until postflop IPF parity is ported.
    """
    if not 0 <= target_index < len(hand_rows):
        raise IndexError(target_index)
    target = hand_rows[target_index]
    if target.get("street") not in {"flop", "turn", "river"}:
        raise LatentRangeError("target is not postflop")
    player = str(target.get("player") or "")
    prior_post = _target_player_prior_postflop_rows(hand_rows, target_index, player)
    if prior_post:
        raise UnsupportedPostflopHistory(
            "target player has earlier postflop action(s); refusing an unconditioned latent range"
        )

    hero = _hero_blockers(hand_rows)
    board = list(target.get("board") or [])
    blockers = hero + board
    combos = legal_combos(hero, board)
    weights = [1.0] * len(combos)
    matched = 0

    # Decision rows are emitted in chronological order by increment_decisions.py.
    # Only this player's *earlier preflop* actions condition their private range.
    for row in hand_rows[:target_index]:
        if row.get("street") != "preflop" or row.get("player") != player:
            continue
        node = exact_preflop_node(preflop_model, row)
        if node is None:
            raise LatentRangeError("missing exact preflop Model A node")
        policy = decode_policy169(node, preflop_model)
        if policy is None:
            raise LatentRangeError("exact preflop node has no embedded policy169")
        action = str(row.get("action") or "")
        for i, (a, b) in enumerate(combos):
            hand = combo_class_ids(a, b)
            weights[i] *= max(EPS, float((policy.get(hand) or {}).get(action) or 0.0))
        weights = _normalize(weights)
        matched += 1

    if not matched:
        raise LatentRangeError("no matched preflop action for target player")
    weights = _normalize(weights)
    return ComboPosterior(tuple(combos), tuple(weights), matched, tuple(blockers))


def revealed_label_audit(posterior: ComboPosterior, known_cards: Sequence[str] | None) -> dict:
    """Audit a reveal *after* constructing the pre-action latent posterior."""
    cards = list(known_cards or [])
    if len(cards) != 2:
        return {
            "revealed": False,
            "label_policy": "LATENT_POSTERIOR",
            "posterior_probability": None,
            "negative_log_probability": None,
        }
    p = posterior.probability_of_cards(cards)
    return {
        "revealed": True,
        "label_policy": "POINT_MASS_AFTER_POSTERIOR_BUILD",
        "posterior_probability": p,
        "negative_log_probability": -math.log(max(EPS, p)),
    }


def posterior_audit(posterior: ComboPosterior) -> dict:
    return {
        "exact_combo_support": posterior.support,
        "effective_combo_support": posterior.effective_support,
        "entropy_nats": posterior.entropy_nats,
        "matched_preflop_actions": posterior.matched_preflop_actions,
        "blocked_cards": list(posterior.blocked_cards),
        "probability_mass": sum(posterior.weights),
    }
