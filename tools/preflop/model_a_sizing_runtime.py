#!/usr/bin/env python3
"""#339 sizing-aware Model-A likelihood bridge into the #312/#320 posterior runtime."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from tools.preflop.model_a_sizing_likelihood import (
    canonical_candidate_sha256,
    resolve_support_likelihood,
    validate_candidate,
)
from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.model_a_continuation import (
    ModelAContinuationPolicy,
    ModelAUnsupportedContext,
    _normalize_weights,
)
from tools.simulation.model_b_runtime import combo_class_ids, legal_combos


def _response_action(action: Any) -> str:
    value = str(action or "").upper()
    return "CALL" if value == "LIMP" else value


class SizingAwareModelAContinuationPolicy(ModelAContinuationPolicy):
    """Preflop-only candidate policy with exact-price likelihood conditioning.

    It subclasses the existing Model-A continuation policy so the #312 adapter
    remains the serialization/timeline authority.  No postflop or Hero EV path
    is introduced here.
    """

    def __init__(self, candidate: Mapping[str, Any]) -> None:
        validate_candidate(candidate)
        self.sizing_candidate = dict(candidate)
        candidate_sha = canonical_candidate_sha256(candidate)
        identity = dict(candidate.get("identity") or {})
        super().__init__(
            {"nodes": []},
            {
                "nodes": [],
                "response_models": {},
                "combo_policy_models": {},
                "hand_policy_prior": {},
            },
            identity={
                "candidate_id": str(identity.get("candidate_id") or ""),
                "candidate_sha256": candidate_sha,
                "population_id": str(identity.get("population_id") or ""),
                "source_report_hash": str(identity.get("source_report_hash") or ""),
                "fit_scope": str(identity.get("fit_scope") or ""),
                "posterior_bridge": "issue-339-sizing-aware-v1",
            },
        )

    def _resolve(
        self,
        decision: Mapping[str, Any],
        hand_class: str | None,
    ) -> dict[str, Any]:
        result = resolve_support_likelihood(
            candidate=self.sizing_candidate,
            context=decision,
            hand_class=hand_class,
        )
        if result.get("status") != "RESOLVED":
            raise ModelAUnsupportedContext(
                "sizing-aware Model A has no supported exact-price cell: "
                + str(result.get("support_context_key") or "")
            )
        return result

    def posterior_support_for_trace(
        self,
        trace: Sequence[Mapping[str, Any]],
        player: str,
    ) -> tuple[list[str], int]:
        """Hook consumed by ModelAPosteriorRuntime for exact candidate provenance."""
        node_ids: list[str] = []
        supports: list[int] = []
        for item in trace:
            if str(item.get("player") or "") != player:
                continue
            if str(item.get("street") or "") != "preflop":
                raise ModelAUnsupportedContext(
                    "postflop history is outside #339 sizing-aware preflop posterior"
                )
            result = self._resolve(item.get("decision") or {}, None)
            action = _response_action(item.get("semantic_action"))
            if action not in (result.get("probabilities") or {}):
                raise ModelAUnsupportedContext(
                    f"observed action {action} is outside sizing candidate support"
                )
            node_id = str(result.get("node_id") or "")
            support = int(result.get("support") or 0)
            if not node_id or support <= 0:
                raise ModelAUnsupportedContext(
                    "resolved sizing candidate node has invalid identity/support"
                )
            node_ids.append(node_id)
            supports.append(support)
        return node_ids, min(supports) if supports else 0

    def _posterior_from_history(
        self,
        state: NoLimitHoldemState,
        actor: str,
        trace: Sequence[Mapping[str, Any]],
    ) -> tuple[list[tuple[int, int]], list[float]]:
        """Condition the exact-combo prior on the actor's public preflop actions."""
        if state.street != "preflop" or state.board:
            raise ModelAUnsupportedContext(
                "#339 sizing-aware posterior is preflop-only"
            )
        combos = list(legal_combos([], []))
        if not combos:
            raise ModelAUnsupportedContext("no legal preflop combos")
        weights = [1.0 / len(combos)] * len(combos)
        for item in trace:
            if str(item.get("player") or "") != actor:
                continue
            if str(item.get("street") or "") != "preflop":
                raise ModelAUnsupportedContext(
                    "postflop action encountered in #339 preflop posterior"
                )
            decision = item.get("decision") or {}
            action = _response_action(item.get("semantic_action"))
            updated: list[float] = []
            for combo, weight in zip(combos, weights):
                hand_class = combo_class_ids(*combo)
                resolved = self._resolve(decision, hand_class)
                probability = float(
                    (resolved.get("probabilities") or {}).get(action, 0.0) or 0.0
                )
                updated.append(weight * max(0.0, probability))
            weights = _normalize_weights(updated)
        return combos, weights


__all__ = ["SizingAwareModelAContinuationPolicy"]
