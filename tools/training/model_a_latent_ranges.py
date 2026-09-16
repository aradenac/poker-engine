#!/usr/bin/env python3
"""Training-side exact-combo posterior helpers for Model A.

The helpers reconstruct a player's private-card posterior from information that
was available strictly before a target decision.  Preflop actions are
conditioned with the embedded 169-class policy.  Earlier postflop actions are
conditioned with the same calibrated combo/action matrix consumed by the
runtime; newly exposed board cards are removed only when they become public.

The target action is never used to build its own prior.  This is the contract
needed by the Stage-B postflop combo-policy refit in issue #102.
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
            qv = values[ai * hand_count + hi]
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
    matched_postflop_actions: int = 0

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


def _condition_preflop(
    combos: list[tuple[int, int]],
    weights: list[float],
    hand_rows: Sequence[dict],
    target_index: int,
    player: str,
    preflop_model: dict,
) -> int:
    matched = 0
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
        weights[:] = _normalize(weights)
        matched += 1
    if not matched:
        raise LatentRangeError("no matched preflop action for target player")
    return matched


def _remove_public_blockers(
    combos: list[tuple[int, int]], weights: list[float], board: Sequence[str]
) -> tuple[list[tuple[int, int]], list[float]]:
    blocked = {cid(card) for card in board}
    kept_combos = []
    kept_weights = []
    for combo, weight in zip(combos, weights):
        if combo[0] in blocked or combo[1] in blocked:
            continue
        kept_combos.append(combo)
        kept_weights.append(weight)
    if not kept_combos:
        raise LatentRangeError("public-card blocking removed all combos")
    return kept_combos, _normalize(kept_weights)


def posterior_before_postflop_action(
    hand_rows: Sequence[dict],
    target_index: int,
    preflop_model: dict,
    postflop_model: dict,
) -> ComboPosterior:
    """Reconstruct the exact-combo posterior immediately before a postflop action.

    Earlier actions by the target player are applied chronologically.  The
    calibrated postflop likelihood is evaluated with only the board public at
    that earlier decision; turn/river blockers are removed only after those
    cards become public.  The target action itself is never inspected for
    conditioning.
    """
    if not 0 <= target_index < len(hand_rows):
        raise IndexError(target_index)
    target = hand_rows[target_index]
    if target.get("street") not in {"flop", "turn", "river"}:
        raise LatentRangeError("target is not postflop")
    player = str(target.get("player") or "")
    prior_post = _target_player_prior_postflop_rows(hand_rows, target_index, player)
    hero = _hero_blockers(hand_rows)

    initial_board = list((prior_post[0] if prior_post else target).get("board") or [])
    combos = list(legal_combos(hero, initial_board))
    weights = [1.0] * len(combos)
    matched_pre = _condition_preflop(combos, weights, hand_rows, target_index, player, preflop_model)

    current_board = list(initial_board)
    matched_post = 0
    if prior_post:
        from tools.training.model_a_postflop_runtime import observed_action_probabilities

        for row in prior_post:
            row_board = list(row.get("board") or [])
            if row_board != current_board:
                combos, weights = _remove_public_blockers(combos, weights, row_board)
                current_board = row_board
            try:
                likelihood = observed_action_probabilities(combos, weights, row, postflop_model)
            except (KeyError, ValueError) as exc:
                raise LatentRangeError(f"missing exact postflop runtime support: {exc}") from exc
            if len(likelihood) != len(weights):
                raise LatentRangeError("postflop likelihood length mismatch")
            weights = _normalize([w * max(EPS, float(p)) for w, p in zip(weights, likelihood)])
            matched_post += 1

    target_board = list(target.get("board") or [])
    if target_board != current_board:
        combos, weights = _remove_public_blockers(combos, weights, target_board)

    return ComboPosterior(
        tuple(combos), tuple(weights), matched_pre, tuple(hero + target_board), matched_post
    )


def posterior_before_first_postflop_action(
    hand_rows: Sequence[dict], target_index: int, preflop_model: dict
) -> ComboPosterior:
    """Compatibility helper for the original fail-closed first-action subset."""
    if not 0 <= target_index < len(hand_rows):
        raise IndexError(target_index)
    target = hand_rows[target_index]
    player = str(target.get("player") or "")
    prior_post = _target_player_prior_postflop_rows(hand_rows, target_index, player)
    if prior_post:
        raise UnsupportedPostflopHistory(
            "target player has earlier postflop action(s); use posterior_before_postflop_action with runtime parity"
        )
    hero = _hero_blockers(hand_rows)
    board = list(target.get("board") or [])
    combos = list(legal_combos(hero, board))
    weights = [1.0] * len(combos)
    matched = _condition_preflop(combos, weights, hand_rows, target_index, player, preflop_model)
    return ComboPosterior(tuple(combos), tuple(weights), matched, tuple(hero + board), 0)


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
        "matched_postflop_actions": posterior.matched_postflop_actions,
        "blocked_cards": list(posterior.blocked_cards),
        "probability_mass": sum(posterior.weights),
    }
