#!/usr/bin/env python3
"""Exact #107 Hero preflop overlay for the frozen #108 full-hand benchmark.

The candidate is deliberately narrow: a calculated Hero strategy is used only
when both the canonical card-free PFC context and the 169 hand class match an
entry in the immutable #107 repository. Every other Hero decision delegates to
the frozen Model-A reference. No nearest-context or stack/position backoff is
permitted.
"""
from __future__ import annotations

import collections
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.preflop.context_contract import build_context
from tools.simulation.game_core import EPS, NoLimitHoldemState, RuleError
from tools.simulation.model_a_continuation import (
    ModelAContinuationPolicy,
    _position_map,
    _preflop_decision,
    _semantic_trace,
)
from tools.simulation.model_b_runtime import combo_class, weighted_choice

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_SCHEMA = "poker-hero-range-repository/v1"
PFC_SCHEMA = "poker-preflop-context/v1"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_preflop_context(state: NoLimitHoldemState, actor: str) -> dict[str, Any]:
    """Derive the canonical PFC identity from an arena state with named players."""
    if state.street != "preflop":
        raise ValueError("canonical Hero overlay context is preflop-only")
    if state.next_actor != actor:
        raise ValueError(f"{actor!r} is not next to act")

    _, replay, history, _, _ = _semantic_trace(state)
    if replay.to_snapshot(include_log=False) != state.to_snapshot(include_log=False):
        raise AssertionError("semantic replay diverged while deriving Hero PFC context")

    semantic = _preflop_decision(replay, actor, history)
    positions = _position_map(replay)
    view = replay.legal_view(actor)
    live_players = list(replay.live_players)
    all_in_players = [player for player in live_players if replay.all_in[player]]
    live_positions = [positions[player] for player in live_players]
    all_in_positions = [positions[player] for player in all_in_players]
    contributions = {
        positions[player]: float(replay.street_committed_bb[player])
        for player in live_players
    }
    starting_stacks = {
        positions[player]: float(replay.starting_stacks_bb[player])
        for player in live_players
    }
    pending = [positions[player] for player in view["remaining_to_act"]]

    canonical = build_context(
        table_size=len(replay.seats),
        actor_position=positions[actor],
        live_positions=live_positions,
        all_in_positions=all_in_positions,
        history=semantic["history"],
        raise_level=int(semantic["raise_level"]),
        contribution_bb_by_position=contributions,
        stack_bb_by_position=starting_stacks,
        pot_before_bb=float(view["pot_before_bb"]),
        current_price_bb=float(view["current_price_bb"]),
        pending_positions=pending,
        min_raise_to_bb=(
            None
            if view["min_raise_to_bb"] is None
            else float(view["min_raise_to_bb"])
        ),
        raise_reopened=bool(view["raise_reopened"]),
    )
    if canonical["schema"] != PFC_SCHEMA:
        raise AssertionError("unexpected canonical preflop context schema")
    if canonical["actor_position"] != semantic["actor_position"]:
        raise AssertionError("arena/PFC actor-position drift")
    if canonical["family"] != semantic["family"]:
        raise AssertionError("arena/PFC preflop-family drift")
    return canonical


def _load_repository(path: Path) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema") != REPOSITORY_SCHEMA:
        raise ValueError(f"expected {REPOSITORY_SCHEMA}, got {document.get('schema')!r}")
    contexts = document.get("contexts")
    if not isinstance(contexts, Mapping) or not contexts:
        raise ValueError("Hero repository contains no contexts")
    return document


def _candidate_index(repository: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for node in (repository.get("contexts") or {}).values():
        context = dict(node.get("context") or {})
        pfc_id = str(context.get("preflop_context_id") or "")
        if not pfc_id:
            raise ValueError("#108 candidate repository requires preflop_context_id on every context")
        if pfc_id in index:
            raise ValueError(f"duplicate candidate canonical context {pfc_id}")
        calculated = ((node.get("layers") or {}).get("calculated") or {})
        hands = calculated.get("hands") or {}
        if not isinstance(hands, Mapping):
            raise ValueError(f"candidate context {pfc_id} has invalid calculated hand map")
        index[pfc_id] = {"context": context, "hands": dict(hands)}
    return index


def _choose_weighted(mapping: Mapping[str, Any], *seed_parts: object) -> str:
    names = [str(name).upper() for name, value in mapping.items() if float(value) > EPS]
    weights = [float(mapping[name]) if name in mapping else float(mapping[name.lower()]) for name in names]
    if not names:
        raise ValueError("candidate strategy has no positive action mass")
    if any(not math.isfinite(value) or value < 0 for value in weights):
        raise ValueError("candidate strategy contains invalid action probability")
    return str(weighted_choice(names, weights, *seed_parts))


def _choose_sizing(rows: Sequence[Mapping[str, Any]], *seed_parts: object) -> float:
    clean = [dict(row) for row in rows if float(row.get("probability", 0.0)) > EPS]
    if not clean:
        raise ValueError("candidate aggressive action has no supported sizing")
    selected = weighted_choice(
        clean,
        [float(row["probability"]) for row in clean],
        *seed_parts,
    )
    target = float(selected["target_total_bb"])
    if not math.isfinite(target) or target <= 0:
        raise ValueError("candidate sizing target must be finite and positive")
    return target


class ExactHeroPreflopOverlayPolicy:
    """Exact PFC+hand candidate overlay with frozen-reference fallback."""

    def __init__(
        self,
        repository: Mapping[str, Any],
        *,
        repository_sha256: str,
        reference_policy,
        candidate_id: str,
    ) -> None:
        self.repository = copy.deepcopy(dict(repository))
        self.repository_sha256 = str(repository_sha256)
        self.reference_policy = reference_policy
        self.candidate_id = str(candidate_id)
        self.index = _candidate_index(self.repository)
        self.policy_id = f"hero-pfc-overlay:{self.candidate_id}"
        self._audit: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)

    @classmethod
    def from_path(
        cls,
        repository_path: Path,
        *,
        reference_policy,
        candidate_id: str,
    ) -> "ExactHeroPreflopOverlayPolicy":
        path = Path(repository_path)
        return cls(
            _load_repository(path),
            repository_sha256=sha256_file(path),
            reference_policy=reference_policy,
            candidate_id=candidate_id,
        )

    def identity(self) -> dict[str, Any]:
        return {
            "schema": "poker-hero-pfc-overlay-policy/v1",
            "candidate_id": self.candidate_id,
            "candidate_repository_sha256": self.repository_sha256,
            "matching": "EXACT_PFC_AND_169_HAND_CLASS_ONLY",
            "out_of_support": "FROZEN_REFERENCE_FALLBACK",
            "nearest_context_substitution": False,
            "candidate_contexts": sorted(self.index),
            "reference": getattr(self.reference_policy, "identity", None),
        }

    def _record(self, scenario_id: str, key: str) -> None:
        self._audit[str(scenario_id)][str(key)] += 1

    def scenario_audit(self, scenario_id: str) -> dict[str, int]:
        row = self._audit.get(str(scenario_id), collections.Counter())
        return {
            "hero_preflop_decisions": int(row.get("hero_preflop_decisions", 0)),
            "candidate_supported_decisions": int(row.get("candidate_supported_decisions", 0)),
            "candidate_out_of_support_decisions": int(row.get("candidate_out_of_support_decisions", 0)),
            "postflop_reference_decisions": int(row.get("postflop_reference_decisions", 0)),
        }

    def clear_audit(self) -> None:
        self._audit.clear()

    def _fallback(
        self,
        state: NoLimitHoldemState,
        *,
        scenario_id: str,
        seed_parts: Sequence[object],
        reason: str,
        **context: Any,
    ) -> dict[str, Any]:
        if state.street == "preflop":
            self._record(scenario_id, "candidate_out_of_support_decisions")
        decision = dict(self.reference_policy.decide(state, seed_parts=tuple(seed_parts), **context))
        decision["benchmark_candidate"] = {
            "candidate_id": self.candidate_id,
            "supported": False,
            "fallback": "FROZEN_REFERENCE",
            "reason": reason,
        }
        return decision

    def decide(
        self,
        state: NoLimitHoldemState,
        *,
        seed_parts: Sequence[object],
        **context: Any,
    ) -> dict[str, Any]:
        scenario_id = str(seed_parts[0]) if seed_parts else "<missing-scenario>"
        if state.street != "preflop":
            self._record(scenario_id, "postflop_reference_decisions")
            return dict(self.reference_policy.decide(state, seed_parts=tuple(seed_parts), **context))

        self._record(scenario_id, "hero_preflop_decisions")
        actor = str(context["actor"])
        pfc = canonical_preflop_context(state, actor)
        candidate_node = self.index.get(str(pfc["context_id"]))
        if candidate_node is None:
            return self._fallback(
                state,
                scenario_id=scenario_id,
                seed_parts=seed_parts,
                reason=f"PFC_OUT_OF_SUPPORT:{pfc['context_id']}",
                **context,
            )

        hand = combo_class(tuple(context["hole_cards"]))
        strategy = (candidate_node.get("hands") or {}).get(hand)
        if strategy is None:
            return self._fallback(
                state,
                scenario_id=scenario_id,
                seed_parts=seed_parts,
                reason=f"HAND_OUT_OF_SUPPORT:{hand}",
                **context,
            )

        action = _choose_weighted(
            strategy.get("actions") or {},
            *seed_parts,
            "candidate-action",
        )
        view = state.legal_view(actor)
        legal = set(view["legal_actions"])
        target = None
        if action in {"FOLD", "CHECK"}:
            core_action = action
        elif action in {"LIMP", "OVERLIMP", "CALL", "CALL_SHOVE"}:
            core_action = "CALL"
        elif action in {"OPEN", "ISO", "3BET", "4BET", "SHOVE"}:
            core_action = "RAISE"
            sizing_rows = (strategy.get("sizings") or {}).get(action) or []
            target = _choose_sizing(sizing_rows, *seed_parts, "candidate-sizing", action)
            if action == "SHOVE" and abs(target - float(view["max_raise_to_bb"])) > 1e-6:
                raise RuleError(
                    f"candidate SHOVE target {target} != legal all-in {view['max_raise_to_bb']}"
                )
        else:
            raise ValueError(f"unsupported Hero repository action {action!r}")

        if core_action not in legal:
            raise RuleError(
                f"exact candidate action {action}/{core_action} is illegal in {pfc['context_id']}; legal={sorted(legal)}"
            )
        self._record(scenario_id, "candidate_supported_decisions")
        return {
            "schema": "poker-hero-pfc-overlay-decision/v1",
            "action": core_action,
            "target_total_bb": target,
            "benchmark_candidate": {
                "candidate_id": self.candidate_id,
                "supported": True,
                "preflop_context_id": pfc["context_id"],
                "hand_class": hand,
                "repository_action": action,
            },
        }
