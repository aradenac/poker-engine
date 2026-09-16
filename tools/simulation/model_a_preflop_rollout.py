#!/usr/bin/env python3
"""Full-hand rollout bridge for the #106 preflop action/sizing EV grid.

The grid evaluator calls this object after applying one Hero candidate.  Hidden
opponent cards are sampled from Model A ranges conditioned only on actions that
are already public at the decision point, with Hero/dealt-card blockers applied
jointly.  A fresh board is then sampled from the remaining deck.  All subsequent
betting, side pots, refunds and settlement use the shared ``NoLimitHoldemState``.

The bridge deliberately requires a separate Hero continuation policy.  Model A
models the population and is not silently reused as an "optimal" Hero strategy.
If either policy lacks exact support, the rollout reports ``supported=False`` so
the preflop evaluator fails closed instead of ranking a partially modelled grid.
"""
from __future__ import annotations

import collections
import hashlib
import json
import random
from typing import Any, Mapping, Sequence

from tools.simulation.game_core import EPS, NoLimitHoldemState, RuleError
from tools.simulation.model_a_continuation import (
    ModelAContinuationPolicy,
    ModelAUnsupportedContext,
    _semantic_trace,
)
from tools.simulation.model_b_runtime import best, ccode, cid, hseed, rake_net, weighted_choice

ROLLOUT_SCHEMA = "model-a-preflop-continuation-rollout/v1"


class RolloutUnsupported(ValueError):
    """A sampled continuation cannot be evaluated under the declared contracts."""


def _invoke_policy(policy: Any, state: NoLimitHoldemState, *, seed_parts: Sequence[object], actor: str, hole_cards: Sequence[str]) -> dict[str, Any]:
    context = {"actor": actor, "hole_cards": tuple(hole_cards)}
    if hasattr(policy, "decide"):
        result = policy.decide(state, seed_parts=tuple(seed_parts), **context)
    elif callable(policy):
        result = policy(state, seed_parts=tuple(seed_parts), **context)
    else:
        raise TypeError("continuation policy must be callable or expose decide(state, ...)")
    if not isinstance(result, Mapping):
        raise TypeError("continuation policy decision must be a mapping")
    return dict(result)


def _apply_policy_decision(state: NoLimitHoldemState, actor: str, decision: Mapping[str, Any]) -> None:
    view = state.legal_view(actor)
    legal = set(view["legal_actions"])
    action = str(decision.get("action") or "").upper().replace("-", "_")
    target = decision.get("target_total_bb")
    if action == "BET":
        action = "RAISE"
    if action in {"ALL_IN", "ALLIN", "JAM"}:
        if "RAISE" in legal:
            action = "RAISE"
            target = float(view["max_raise_to_bb"])
        elif "CALL" in legal:
            action = "CALL"
            target = None
        else:
            raise RolloutUnsupported("continuation policy requested an unavailable all-in")
    if action not in legal:
        raise RolloutUnsupported(f"continuation policy returned illegal {action!r}; legal={sorted(legal)}")
    if action == "RAISE":
        if target is None:
            raise RolloutUnsupported("continuation RAISE requires target_total_bb")
        target = float(target)
        if target > float(view["max_raise_to_bb"]) + EPS:
            raise RolloutUnsupported("continuation raise exceeds actor stack")
        state.apply_action(actor, "RAISE", target_total_bb=target)
    else:
        state.apply_action(actor, action)


def _filter_posterior(
    combos: Sequence[tuple[int, int]],
    weights: Sequence[float],
    blocked: set[int],
) -> tuple[list[tuple[int, int]], list[float]]:
    kept = [
        (combo, max(0.0, float(weight)))
        for combo, weight in zip(combos, weights)
        if combo[0] not in blocked and combo[1] not in blocked and float(weight) > 0
    ]
    if not kept:
        raise RolloutUnsupported("joint blocker conditioning removed all opponent combos")
    out_combos, out_weights = zip(*kept)
    total = sum(out_weights)
    if total <= EPS:
        raise RolloutUnsupported("conditioned opponent range has zero probability mass")
    return list(out_combos), [weight / total for weight in out_weights]


def _sample_fingerprint(holes: Mapping[str, Sequence[str]], board: Sequence[str]) -> str:
    payload = json.dumps(
        {
            "holes": {player: list(cards) for player, cards in sorted(holes.items())},
            "board": list(board),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ModelAPreflopContinuationRollout:
    """Callable rollout compatible with ``evaluate_preflop_grid``."""

    def __init__(
        self,
        *,
        opponent_policy: ModelAContinuationPolicy,
        hero_hole_cards: Sequence[str],
        hero_continuation_policy: Any,
        max_actions: int = 200,
    ) -> None:
        if len(hero_hole_cards) != 2:
            raise ValueError("hero_hole_cards must contain exactly two cards")
        if hero_hole_cards[0] == hero_hole_cards[1]:
            raise ValueError("hero_hole_cards must be distinct")
        if int(max_actions) < 1:
            raise ValueError("max_actions must be positive")
        self.opponent_policy = opponent_policy
        self.hero_hole_cards = tuple(str(card) for card in hero_hole_cards)
        self.hero_continuation_policy = hero_continuation_policy
        self.max_actions = int(max_actions)

    def _sample_private_cards(
        self,
        state: NoLimitHoldemState,
        *,
        hero: str,
        seed: int,
    ) -> dict[str, tuple[str, str]]:
        hero_ids = tuple(cid(card) for card in self.hero_hole_cards)
        if hero_ids[0] == hero_ids[1]:
            raise RolloutUnsupported("Hero cards collapse to one card id")
        blocked = set(hero_ids)
        blocked.update(cid(card) for card in state.board)
        holes: dict[str, tuple[str, str]] = {hero: self.hero_hole_cards}
        trace, _, _, _, _ = _semantic_trace(state)

        for player in state.seats:
            if player == hero:
                continue
            try:
                combos, weights = self.opponent_policy._posterior_from_history(
                    state, player, trace
                )
            except ModelAUnsupportedContext as exc:
                raise RolloutUnsupported(
                    f"cannot reconstruct {player} range from public history: {exc}"
                ) from exc
            combos, weights = _filter_posterior(combos, weights, blocked)
            chosen = weighted_choice(
                list(range(len(combos))),
                weights,
                seed,
                "model-a-preflop-rollout",
                "hole",
                player,
            )
            combo = combos[int(chosen)]
            blocked.update(combo)
            holes[player] = (ccode(combo[0]), ccode(combo[1]))
        return holes

    @staticmethod
    def _sample_board(
        state: NoLimitHoldemState,
        holes: Mapping[str, Sequence[str]],
        *,
        seed: int,
    ) -> list[str]:
        known_board = list(state.board)
        blocked = {cid(card) for cards in holes.values() for card in cards}
        blocked.update(cid(card) for card in known_board)
        deck = [card_id for card_id in range(52) if card_id not in blocked]
        random.Random(hseed(seed, "model-a-preflop-rollout", "board")).shuffle(deck)
        missing = 5 - len(known_board)
        if missing < 0 or len(deck) < missing:
            raise RolloutUnsupported("cannot construct a complete collision-free runout")
        return known_board + [ccode(card_id) for card_id in deck[:missing]]

    def _run_to_terminal(
        self,
        state: NoLimitHoldemState,
        *,
        hero: str,
        holes: Mapping[str, Sequence[str]],
        board: Sequence[str],
        seed: int,
        sample_index: int,
        candidate_id: str,
    ) -> dict[str, Any]:
        decision_no = collections.Counter()
        actions = 0
        settlement = None

        for _ in range(self.max_actions + 20):
            if len(state.live_players) == 1:
                settlement = state.settle_by_fold(net_pot_fn=rake_net)
                break
            actor = state.next_actor
            if actor is not None:
                if actions >= self.max_actions:
                    raise RolloutUnsupported("continuation exceeded max_actions")
                policy = (
                    self.hero_continuation_policy
                    if actor == hero
                    else self.opponent_policy
                )
                if policy is None:
                    raise RolloutUnsupported(
                        "Hero requires a declared continuation policy after the fixed preflop candidate"
                    )
                seed_parts = (
                    seed,
                    sample_index,
                    candidate_id,
                    actor,
                    int(decision_no[actor]),
                    state.street,
                )
                try:
                    decision = _invoke_policy(
                        policy,
                        NoLimitHoldemState.from_snapshot(state.to_snapshot()),
                        seed_parts=seed_parts,
                        actor=actor,
                        hole_cards=holes[actor],
                    )
                    _apply_policy_decision(state, actor, decision)
                except ModelAUnsupportedContext as exc:
                    raise RolloutUnsupported(
                        f"Model A unsupported for {actor} on {state.street}: {exc}"
                    ) from exc
                decision_no[actor] += 1
                actions += 1
                continue

            if state.street == "river":
                ranks = {
                    player: best(list(holes[player]) + list(board))
                    for player in state.live_players
                }
                settlement = state.settle_showdown(ranks, net_pot_fn=rake_net)
                break
            if state.street == "preflop":
                next_cards = list(board[:3])
            elif state.street == "flop":
                next_cards = [board[3]]
            elif state.street == "turn":
                next_cards = [board[4]]
            else:
                raise RolloutUnsupported(f"unknown street {state.street!r}")
            state.advance_street(next_cards)
        else:
            raise RolloutUnsupported("continuation failed to terminate")

        if settlement is None:
            raise RolloutUnsupported("continuation terminated without settlement")
        return {
            "ending_stack_bb": float(state.stacks_bb[hero]),
            "terminal": settlement.terminal,
            "rake_bb": float(settlement.rake_bb),
            "pot_layers": len(settlement.pots),
            "actions_after_candidate": actions,
        }

    def __call__(
        self,
        state: NoLimitHoldemState,
        *,
        actor: str,
        seed: int,
        sample_index: int,
        candidate: Mapping[str, Any],
    ) -> dict[str, Any]:
        if state.street != "preflop":
            return {"supported": False, "reason": "#106 rollout expects a preflop state after the fixed candidate"}
        if actor not in state.seats:
            return {"supported": False, "reason": f"Hero {actor!r} is not seated"}
        if len(set(self.hero_hole_cards + tuple(state.board))) != 2 + len(state.board):
            return {"supported": False, "reason": "Hero cards collide with the public board"}
        try:
            holes = self._sample_private_cards(state, hero=actor, seed=int(seed))
            board = self._sample_board(state, holes, seed=int(seed))
            branch = NoLimitHoldemState.from_snapshot(state.to_snapshot())
            terminal = self._run_to_terminal(
                branch,
                hero=actor,
                holes=holes,
                board=board,
                seed=int(seed),
                sample_index=int(sample_index),
                candidate_id=str(candidate.get("id") or ""),
            )
        except (RolloutUnsupported, ModelAUnsupportedContext, RuleError, ValueError) as exc:
            return {
                "schema": ROLLOUT_SCHEMA,
                "supported": False,
                "reason": str(exc),
            }
        return {
            "schema": ROLLOUT_SCHEMA,
            "supported": True,
            **terminal,
            "sample_fingerprint_sha256": _sample_fingerprint(holes, board),
            "board": board,
            "randomness_contract": {
                "opponent_holes": "Model-A public-history posterior, joint blocker-conditioned",
                "board": "fresh remaining-deck shuffle after all hole cards are fixed",
                "future_actions": "deterministic seed namespace per actor decision",
            },
        }
