#!/usr/bin/env python3
"""Calculated Hero preflop overlay for the frozen full-hand benchmark.

Two matching modes are supported:

* legacy/existing exact PFC + 169 hand class;
* explicit PFPC binding + 169 hand class, where PFPC is the versioned bucketed
  public-state policy contract from :mod:`tools.preflop.policy_context`.

PFPC matching is not nearest-context substitution. A live state either maps to
one exact frozen PFPC binding or falls back to the reference policy. The editor
repository remains ``poker-hero-range-repository/v1`` and keeps its exact source
PFC provenance; the separate binding records which source range is authorized
for each PFPC policy state.
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
from tools.preflop.policy_context import SCHEMA as POLICY_CONTEXT_SCHEMA, build_policy_context
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
POLICY_BINDING_SCHEMA = "poker-hero-policy-context-binding/v1"


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
            raise ValueError("benchmark candidate repository requires preflop_context_id on every context")
        if pfc_id in index:
            raise ValueError(f"duplicate candidate canonical context {pfc_id}")
        calculated = ((node.get("layers") or {}).get("calculated") or {})
        hands = calculated.get("hands") or {}
        if not isinstance(hands, Mapping):
            raise ValueError(f"candidate context {pfc_id} has invalid calculated hand map")
        index[pfc_id] = {"context": context, "hands": dict(hands)}
    return index


def _binding_index(
    binding: Mapping[str, Any] | None,
    *,
    repository_sha256: str,
    candidate_index: Mapping[str, Any],
) -> dict[str, dict[str, Any]] | None:
    if binding is None:
        return None
    if binding.get("schema") != POLICY_BINDING_SCHEMA:
        raise ValueError(f"expected {POLICY_BINDING_SCHEMA}, got {binding.get('schema')!r}")
    if binding.get("policy_context_schema") != POLICY_CONTEXT_SCHEMA:
        raise ValueError("Hero policy binding references an unsupported policy-context schema")
    bound_sha = str(binding.get("repository_sha256") or "")
    if bound_sha and bound_sha != repository_sha256:
        raise ValueError("Hero policy binding repository SHA-256 mismatch")
    raw = binding.get("bindings")
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError("Hero policy binding contains no bindings")
    out: dict[str, dict[str, Any]] = {}
    for policy_context_id, row0 in raw.items():
        policy_context_id = str(policy_context_id)
        if not policy_context_id.startswith("PFPC_"):
            raise ValueError(f"invalid policy context id {policy_context_id!r}")
        row = dict(row0 or {})
        source_pfc = str(row.get("preflop_context_id") or "")
        if source_pfc not in candidate_index:
            raise ValueError(
                f"policy context {policy_context_id} binds missing repository context {source_pfc!r}"
            )
        if policy_context_id in out:
            raise ValueError(f"duplicate policy context binding {policy_context_id}")
        row["preflop_context_id"] = source_pfc
        out[policy_context_id] = row
    return out


def _load_binding(path: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    if path is None:
        return None, None
    source = Path(path)
    document = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Hero policy binding must be a JSON object")
    return document, sha256_file(source)


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
    """Exact PFC/PFPC + hand candidate overlay with frozen-reference fallback."""

    def __init__(
        self,
        repository: Mapping[str, Any],
        *,
        repository_sha256: str,
        reference_policy,
        candidate_id: str,
        policy_binding: Mapping[str, Any] | None = None,
        policy_binding_sha256: str | None = None,
    ) -> None:
        self.repository = copy.deepcopy(dict(repository))
        self.repository_sha256 = str(repository_sha256)
        self.reference_policy = reference_policy
        self.candidate_id = str(candidate_id)
        self.index = _candidate_index(self.repository)
        self.policy_binding = None if policy_binding is None else copy.deepcopy(dict(policy_binding))
        self.policy_binding_sha256 = None if policy_binding_sha256 is None else str(policy_binding_sha256)
        self.binding_index = _binding_index(
            self.policy_binding,
            repository_sha256=self.repository_sha256,
            candidate_index=self.index,
        )
        self.policy_id = f"hero-pfc-overlay:{self.candidate_id}"
        self._audit: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)

    @classmethod
    def from_path(
        cls,
        repository_path: Path,
        *,
        reference_policy,
        candidate_id: str,
        policy_binding_path: Path | None = None,
    ) -> "ExactHeroPreflopOverlayPolicy":
        path = Path(repository_path)
        repository_sha = sha256_file(path)
        binding, binding_sha = _load_binding(policy_binding_path)
        return cls(
            _load_repository(path),
            repository_sha256=repository_sha,
            reference_policy=reference_policy,
            candidate_id=candidate_id,
            policy_binding=binding,
            policy_binding_sha256=binding_sha,
        )

    def identity(self) -> dict[str, Any]:
        bound = self.binding_index is not None
        return {
            "schema": "poker-hero-pfc-overlay-policy/v1",
            "candidate_id": self.candidate_id,
            "candidate_repository_sha256": self.repository_sha256,
            "matching": (
                "EXACT_POLICY_CONTEXT_AND_169_HAND_CLASS_ONLY"
                if bound
                else "EXACT_PFC_AND_169_HAND_CLASS_ONLY"
            ),
            "out_of_support": "FROZEN_REFERENCE_FALLBACK",
            "nearest_context_substitution": False,
            "candidate_contexts": sorted(self.index),
            "policy_context_schema": POLICY_CONTEXT_SCHEMA if bound else None,
            "policy_context_binding_sha256": self.policy_binding_sha256,
            "policy_contexts": sorted(self.binding_index) if bound else [],
            "reference": getattr(self.reference_policy, "identity", None),
        }

    def _record(self, scenario_id: str, key: str) -> None:
        self._audit[str(scenario_id)][str(key)] += 1

    def scenario_audit(self, scenario_id: str) -> dict[str, Any]:
        row = self._audit.get(str(scenario_id), collections.Counter())
        contexts: dict[str, dict[str, int]] = {}
        prefix = "policy_context|"
        for key, value in row.items():
            if not str(key).startswith(prefix):
                continue
            _, context_id, metric = str(key).split("|", 2)
            node = contexts.setdefault(
                context_id,
                {
                    "hero_preflop_decisions": 0,
                    "candidate_supported_decisions": 0,
                    "candidate_out_of_support_decisions": 0,
                },
            )
            node[metric] += int(value)
        for context_id, node in contexts.items():
            if (
                node["candidate_supported_decisions"]
                + node["candidate_out_of_support_decisions"]
                != node["hero_preflop_decisions"]
            ):
                raise AssertionError(f"incomplete candidate support audit for {context_id}")
        return {
            "hero_preflop_decisions": int(row.get("hero_preflop_decisions", 0)),
            "candidate_supported_decisions": int(row.get("candidate_supported_decisions", 0)),
            "candidate_out_of_support_decisions": int(row.get("candidate_out_of_support_decisions", 0)),
            "postflop_reference_decisions": int(row.get("postflop_reference_decisions", 0)),
            "policy_contexts": dict(sorted(contexts.items())),
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

    def _resolve_candidate_node(
        self,
        pfc: Mapping[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any], str | None]:
        live_pfc_id = str(pfc["context_id"])
        if self.binding_index is None:
            node = self.index.get(live_pfc_id)
            if node is None:
                return None, {}, f"PFC_OUT_OF_SUPPORT:{live_pfc_id}"
            return node, {"preflop_context_id": live_pfc_id}, None

        policy_context = build_policy_context(pfc)
        policy_context_id = str(policy_context["policy_context_id"])
        binding = self.binding_index.get(policy_context_id)
        if binding is None:
            return None, {
                "policy_context_id": policy_context_id,
                "live_preflop_context_id": live_pfc_id,
            }, f"PFPC_OUT_OF_SUPPORT:{policy_context_id}"
        source_pfc = str(binding["preflop_context_id"])
        node = self.index[source_pfc]
        return node, {
            "policy_context_id": policy_context_id,
            "source_preflop_context_id": source_pfc,
            "live_preflop_context_id": live_pfc_id,
        }, None

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
        candidate_node, match_evidence, miss_reason = self._resolve_candidate_node(pfc)
        audit_context_id = str(
            match_evidence.get("policy_context_id")
            or match_evidence.get("preflop_context_id")
            or pfc["context_id"]
        )
        self._record(scenario_id, f"policy_context|{audit_context_id}|hero_preflop_decisions")
        if candidate_node is None:
            self._record(scenario_id, f"policy_context|{audit_context_id}|candidate_out_of_support_decisions")
            return self._fallback(
                state,
                scenario_id=scenario_id,
                seed_parts=seed_parts,
                reason=str(miss_reason),
                **context,
            )

        hand = combo_class(tuple(context["hole_cards"]))
        strategy = (candidate_node.get("hands") or {}).get(hand)
        if strategy is None:
            self._record(scenario_id, f"policy_context|{audit_context_id}|candidate_out_of_support_decisions")
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
            if action == "SHOVE":
                # SHOVE is a semantic all-in action. PFPC v1 deliberately
                # groups nearby effective stacks (for example 100bb and
                # 106.16bb) in one frozen policy bucket, so the source-PFC
                # numeric target is provenance, not a transferable fixed
                # raise-to amount. Apply the live legal all-in boundary.
                target = float(view["max_raise_to_bb"])
        else:
            raise ValueError(f"unsupported Hero repository action {action!r}")

        if core_action not in legal:
            raise RuleError(
                f"exact candidate action {action}/{core_action} is illegal in {pfc['context_id']}; legal={sorted(legal)}"
            )
        if target is not None and core_action == "RAISE":
            minimum = view["min_raise_to_bb"]
            maximum = float(view["max_raise_to_bb"])
            if target > maximum + 1e-6:
                raise RuleError(f"candidate target {target} exceeds legal all-in {maximum}")
            if minimum is not None and target + 1e-6 < float(minimum) and abs(target - maximum) > 1e-6:
                raise RuleError(f"candidate target {target} below legal minimum {minimum}")
        self._record(scenario_id, "candidate_supported_decisions")
        self._record(scenario_id, f"policy_context|{audit_context_id}|candidate_supported_decisions")
        evidence = {
            "candidate_id": self.candidate_id,
            "supported": True,
            "hand_class": hand,
            "repository_action": action,
            **match_evidence,
        }
        return {
            "schema": "poker-hero-pfc-overlay-decision/v1",
            "action": core_action,
            "target_total_bb": target,
            "benchmark_candidate": evidence,
        }
