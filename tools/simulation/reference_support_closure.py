#!/usr/bin/env python3
"""Shared fail-soft closure for a frozen Hero reference policy.

The #108 full-hand benchmark intentionally compares only the Hero *preflop*
change.  Model A remains the preferred Hero continuation on every exact node it
supports.  When the frozen exact policy has no node, this wrapper applies one
predeclared deterministic legal fallback to both benchmark arms and records the
fallback.  It never searches a nearby context and never changes opponent play.
"""
from __future__ import annotations

import collections
from typing import Any, Mapping, Sequence

from tools.simulation.model_a_continuation import ModelAUnsupportedContext


class SupportClosedModelAReferencePolicy:
    """Model A exact policy with a shared deterministic legality-only closure."""

    policy_id = "model-a-reference-support-closed/v1"
    fallback_contract = "CHECK_THEN_CALL_THEN_FOLD_V1"

    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.population_id = getattr(delegate, "population_id", None)
        self.identity = {
            "contract": self.policy_id,
            "delegate": dict(getattr(delegate, "identity", {}) or {}),
            "unsupported_exact_node": self.fallback_contract,
            "nearest_context_substitution": False,
            "claim": "BENCHMARK_SUPPORT_CLOSURE_NOT_OPTIMIZED_HERO_STRATEGY",
        }
        self._audit: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)

    @staticmethod
    def _scenario_id(seed_parts: Sequence[object]) -> str:
        return str(seed_parts[0]) if seed_parts else "<unknown-scenario>"

    @staticmethod
    def _fallback(state, actor: str) -> dict[str, Any]:
        legal = list(state.legal_view(actor)["legal_actions"])
        if "CHECK" in legal:
            action = "CHECK"
        elif "CALL" in legal:
            action = "CALL"
        elif "FOLD" in legal:
            action = "FOLD"
        else:
            raise ModelAUnsupportedContext(
                f"support closure found no passive legal action for {actor}: {legal}"
            )
        return {
            "action": action,
            "target_total_bb": None,
            "benchmark_reference_support_closure": {
                "used": True,
                "contract": SupportClosedModelAReferencePolicy.fallback_contract,
                "nearest_context_substitution": False,
            },
        }

    def decide(
        self,
        state,
        *,
        seed_parts: Sequence[object],
        **context: Any,
    ) -> Mapping[str, Any]:
        actor = str(context["actor"])
        scenario = self._scenario_id(seed_parts)
        audit = self._audit[scenario]
        audit["hero_decisions"] += 1
        audit[f"street_{state.street}_decisions"] += 1
        try:
            decision = dict(
                self.delegate.decide(
                    state,
                    seed_parts=tuple(seed_parts),
                    **context,
                )
            )
        except ModelAUnsupportedContext as exc:
            audit["support_closure_decisions"] += 1
            audit[f"support_closure_street_{state.street}"] += 1
            audit[f"reason:{str(exc)}"] += 1
            decision = self._fallback(state, actor)
            decision["benchmark_reference_support_closure"]["reason"] = str(exc)
            decision["benchmark_reference_support_closure"]["street"] = str(state.street)
            return decision
        audit["exact_model_a_decisions"] += 1
        return decision

    def scenario_audit(self, scenario_id: str) -> dict[str, Any]:
        counts = self._audit.get(str(scenario_id), collections.Counter())
        reasons = {
            key.removeprefix("reason:"): int(value)
            for key, value in counts.items()
            if key.startswith("reason:")
        }
        by_street = {
            street: int(counts.get(f"support_closure_street_{street}", 0))
            for street in ("preflop", "flop", "turn", "river")
        }
        return {
            "hero_decisions": int(counts.get("hero_decisions", 0)),
            "exact_model_a_decisions": int(counts.get("exact_model_a_decisions", 0)),
            "support_closure_decisions": int(counts.get("support_closure_decisions", 0)),
            "support_closure_by_street": by_street,
            "support_closure_reasons": dict(sorted(reasons.items())),
            "fallback_contract": self.fallback_contract,
            "nearest_context_substitution": False,
        }
