#!/usr/bin/env python3
"""Preflop Model-A posterior adapter for poker-opponent-posterior-range/v1.

This is an integration boundary, not a Model-A fit.  Exact-combo reconstruction
is delegated to ModelAContinuationPolicy._posterior_from_history(); this module
adds timeline semantics, exact-node support/provenance, and serialization
through the #320 posterior range contract.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.ranges.posterior_range import (
    SCHEMA as POSTERIOR_SCHEMA,
    PosteriorRangeError,
    build_available_record,
    build_fail_closed_record,
)
from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.model_a_continuation import (
    ModelAContinuationPolicy,
    ModelAUnsupportedContext,
    _position_map,
    _semantic_trace,
    exact_preflop_node,
)

MOMENTS = {"BEFORE_ACTION", "AFTER_ACTION"}


class ModelAPosteriorRuntimeError(ValueError):
    pass


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _public_fingerprint(state: NoLimitHoldemState) -> str:
    """Fingerprint only public state and public action history."""
    return _canonical_sha256(
        {
            "state": state.to_snapshot(include_log=False),
            "public_action_log": [
                {
                    "index": row.get("index"),
                    "street": row.get("street"),
                    "player": row.get("player"),
                    "action": row.get("action"),
                    "target_total_bb": row.get("target_total_bb"),
                    "incremental_cost_bb": row.get("incremental_cost_bb"),
                }
                for row in state.action_log
            ],
        }
    )


def _require_identity_field(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ModelAPosteriorRuntimeError(f"{field} is required")
    return text


@dataclass(frozen=True)
class RuntimeIdentity:
    population_id: str
    model_id: str
    model_version: str
    source_id: str

    def as_contract_identity(self) -> dict[str, str]:
        return {
            "population_id": self.population_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "source_id": self.source_id,
        }


class ModelAPosteriorRuntime:
    """Pure adapter from existing Model-A history posterior to the #320 contract."""

    def __init__(
        self,
        policy: ModelAContinuationPolicy,
        *,
        population_id: str,
        model_id: str,
        model_version: str,
        source_id: str,
    ) -> None:
        if not isinstance(policy, ModelAContinuationPolicy):
            raise TypeError("policy must be ModelAContinuationPolicy")
        self.policy = policy
        self.identity = RuntimeIdentity(
            _require_identity_field(population_id, "population_id"),
            _require_identity_field(model_id, "model_id"),
            _require_identity_field(model_version, "model_version"),
            _require_identity_field(source_id, "source_id"),
        )

    def _base_provenance(self, node_ids: Sequence[str]) -> dict[str, str]:
        node_token = ",".join(node_ids) if node_ids else "UNCONDITIONED_COMBO_PRIOR"
        source_artifact = f"{self.identity.source_id}#preflop_nodes={node_token}"
        policy_identity = dict(self.policy.identity)
        return {
            "producer": "ModelAPosteriorRuntime",
            "contract_version": POSTERIOR_SCHEMA,
            "source_artifact": source_artifact,
            "source_fingerprint": _canonical_sha256(
                {
                    "runtime_identity": self.identity.as_contract_identity(),
                    "policy_identity": policy_identity,
                    "node_ids": list(node_ids),
                }
            ),
        }

    @staticmethod
    def _public_action_from_last_trace(
        state: NoLimitHoldemState,
        player: str,
        trace: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any] | None:
        if not state.action_log or not trace:
            return None
        event = state.action_log[-1]
        item = trace[-1]
        if str(event.get("player") or "") != player or str(item.get("player") or "") != player:
            return None
        if str(event.get("street") or "") != "preflop" or str(item.get("street") or "") != "preflop":
            return None
        semantic = str(item.get("semantic_action") or "")
        raw_action = str(event.get("action") or "").upper()
        state_before = event.get("state_before") or {}
        pot_before = state_before.get("pot_bb")
        incremental = event.get("incremental_cost_bb")
        target_total = event.get("target_total_bb")
        sizing = None
        if raw_action in {"CALL", "RAISE"}:
            if raw_action == "RAISE":
                observed = target_total
                semantic_kind = "TARGET_TOTAL_BB"
            else:
                observed = incremental
                semantic_kind = "INCREMENTAL_COST_BB"
                if target_total is None:
                    target_total = state_before.get("current_bet_bb")
            pot_fraction = None
            try:
                if pot_before is not None and float(pot_before) > 0 and observed is not None:
                    pot_fraction = float(observed) / float(pot_before)
            except (TypeError, ValueError):
                pot_fraction = None
            sizing = {
                "semantic": semantic_kind,
                "observed_size_bb": None if observed is None else float(observed),
                "target_total_bb": None if target_total is None else float(target_total),
                "pot_before_bb": None if pot_before is None else float(pot_before),
                "pot_fraction": pot_fraction,
            }
        return {
            "action": semantic,
            "source_step_id": int(event.get("index", len(state.action_log) - 1)),
            "sizing": sizing,
        }

    def _preflop_support(
        self,
        trace: Sequence[Mapping[str, Any]],
        player: str,
    ) -> tuple[list[str], int]:
        node_ids: list[str] = []
        supports: list[int] = []
        for item in trace:
            if str(item.get("player") or "") != player:
                continue
            if str(item.get("street") or "") != "preflop":
                raise ModelAUnsupportedContext("postflop history is outside #312 preflop runtime")
            decision = item.get("decision") or {}
            semantic = str(item.get("semantic_action") or "")
            node = exact_preflop_node(self.policy.preflop_model, decision)
            if node is None:
                raise ModelAUnsupportedContext(
                    "missing exact preflop Model-A node in posterior history"
                )
            support = int((node.get("coverage") or {}).get("population_decisions") or 0)
            if support <= 0:
                raise ModelAUnsupportedContext(
                    "exact preflop Model-A node has no positive population support"
                )
            legal = {
                str(x)
                for x in ((node.get("population_model") or {}).get("legal_actions") or [])
            }
            if semantic not in legal:
                raise ModelAUnsupportedContext(
                    f"observed preflop action {semantic} is outside exact-node support"
                )
            node_id = str(node.get("id") or "").strip()
            if not node_id:
                raise ModelAUnsupportedContext("exact preflop Model-A node has no id")
            node_ids.append(node_id)
            supports.append(support)
        return node_ids, min(supports) if supports else 0

    def posterior_record(
        self,
        state: NoLimitHoldemState,
        *,
        player: str,
        moment: str,
        hand_id: str,
        step_id: str | int,
        public_state_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        """Return AVAILABLE or fail-closed #320 record for one preflop timeline point."""
        moment = str(moment or "").upper()
        player = str(player or "")
        positions: dict[str, str] = {}
        trace: list[dict[str, Any]] = []
        public_action: dict[str, Any] | None = None
        node_ids: list[str] = []
        source_observations = 0
        fingerprint = public_state_fingerprint or _public_fingerprint(state)

        try:
            if moment not in MOMENTS:
                raise ModelAPosteriorRuntimeError("moment must be BEFORE_ACTION or AFTER_ACTION")
            if state.street != "preflop" or state.board:
                raise ModelAPosteriorRuntimeError(
                    "#312 runtime is preflop-only; future/public board state is not accepted"
                )
            if player not in state.seats:
                raise ModelAPosteriorRuntimeError("player is not seated")
            if not str(hand_id or "").strip():
                raise ModelAPosteriorRuntimeError("hand_id is required")
            positions = _position_map(state)
            trace, replay, _, _, _ = _semantic_trace(state)
            if replay.to_snapshot(include_log=False) != state.to_snapshot(include_log=False):
                raise ModelAPosteriorRuntimeError("semantic replay diverged from public game state")
            if moment == "BEFORE_ACTION":
                if state.next_actor != player:
                    raise ModelAPosteriorRuntimeError(
                        "BEFORE_ACTION requires player to be the next actor"
                    )
            else:
                public_action = self._public_action_from_last_trace(state, player, trace)
                if public_action is None:
                    raise ModelAPosteriorRuntimeError(
                        "AFTER_ACTION requires the immediately preceding public action to belong to player"
                    )

            node_ids, source_observations = self._preflop_support(trace, player)
            combos, weights = self.policy._posterior_from_history(state, player, trace)
            return build_available_record(
                hand_id=str(hand_id),
                step_id=step_id,
                public_state_fingerprint=str(fingerprint),
                player=player,
                position=positions[player],
                identity=self.identity.as_contract_identity(),
                moment=moment,
                public_action=public_action,
                combos=combos,
                weights=weights,
                blockers_applied=[],
                source_observations=source_observations,
                backoff_level=(
                    "EXACT_NODE_HISTORY" if node_ids else "UNCONDITIONED_COMBO_PRIOR"
                ),
                backoff_reason=(
                    None if node_ids else "player has no prior public action at this timeline point"
                ),
                provenance=self._base_provenance(node_ids),
            )
        except ModelAUnsupportedContext as exc:
            return build_fail_closed_record(
                status="UNSUPPORTED",
                reason=str(exc),
                hand_id=str(hand_id),
                step_id=step_id,
                public_state_fingerprint=str(fingerprint),
                player=player,
                position=positions.get(player, "UNKNOWN"),
                identity=self.identity.as_contract_identity(),
                moment=moment if moment in MOMENTS else "BEFORE_ACTION",
                public_action=public_action if moment == "AFTER_ACTION" else None,
                blockers_applied=[],
                source_observations=source_observations,
                backoff_level="EXACT_NODE_REQUIRED",
                backoff_reason=str(exc),
                provenance=self._base_provenance(node_ids),
            )
        except (ModelAPosteriorRuntimeError, PosteriorRangeError, ValueError, KeyError) as exc:
            safe_moment = moment if moment in MOMENTS else "BEFORE_ACTION"
            safe_action = public_action if safe_moment == "AFTER_ACTION" else None
            if safe_moment == "AFTER_ACTION" and safe_action is None:
                # A contract-valid INVALID record cannot claim AFTER_ACTION without
                # the public action. Represent the fail-closed boundary as BEFORE
                # the untrusted/missing action rather than inventing one.
                safe_moment = "BEFORE_ACTION"
            return build_fail_closed_record(
                status="INVALID",
                reason=str(exc),
                hand_id=str(hand_id or "UNKNOWN"),
                step_id=step_id,
                public_state_fingerprint=str(fingerprint),
                player=player or "UNKNOWN",
                position=positions.get(player, "UNKNOWN"),
                identity=self.identity.as_contract_identity(),
                moment=safe_moment,
                public_action=safe_action if safe_moment == "AFTER_ACTION" else None,
                blockers_applied=[],
                source_observations=source_observations,
                backoff_level="FAIL_CLOSED",
                backoff_reason=str(exc),
                provenance=self._base_provenance(node_ids),
            )


__all__ = [
    "RuntimeIdentity",
    "ModelAPosteriorRuntime",
    "ModelAPosteriorRuntimeError",
]
