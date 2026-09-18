#!/usr/bin/env python3
"""Audited support closure for experimental Model-A continuation rollouts.

The strict ModelAContinuationPolicy remains unchanged and fail-closed.  This
wrapper is opt-in for candidate generation when a future exact Model-A action
node is missing.  It reuses the already frozen CHECK -> CALL -> FOLD closure
from #108, never searches a nearby context, and delegates all range/posterior
reconstruction to the exact Model-A policy.

This is a modelling closure, not a fitted population action.  Consumers must
persist the closure audit and keep the generated policy experimental until an
independent benchmark validates it.
"""
from __future__ import annotations

import collections
from typing import Any

from tools.simulation.reference_support_closure import SupportClosedModelAReferencePolicy


class SupportClosedModelAContinuationPolicy(SupportClosedModelAReferencePolicy):
    """Opt-in continuation wrapper with transparent aggregate closure audit."""

    policy_id = "model-a-continuation-support-closed/v1"

    def __init__(self, delegate) -> None:
        super().__init__(delegate)
        self.identity["claim"] = "EXPERIMENTAL_CONTINUATION_CLOSURE_NOT_A_FITTED_POPULATION_ACTION"
        self.identity["purpose"] = "candidate generation continuation only"
        self.identity["range_posterior"] = "DELEGATED_EXACT_MODEL_A"
        self.identity["nearest_context_substitution"] = False

    def __getattr__(self, name: str) -> Any:
        # ModelAPreflopContinuationRollout intentionally uses exact Model-A
        # posterior reconstruction before future betting.  Forward those model
        # attributes/methods rather than approximating hidden-card ranges.
        return getattr(self.delegate, name)

    def aggregate_audit(self) -> dict[str, Any]:
        totals: collections.Counter[str] = collections.Counter()
        for row in self._audit.values():
            totals.update(row)
        reasons = {
            key.removeprefix("reason:"): int(value)
            for key, value in totals.items()
            if key.startswith("reason:")
        }
        by_street = {
            street: int(totals.get(f"support_closure_street_{street}", 0))
            for street in ("preflop", "flop", "turn", "river")
        }
        hero_decisions = int(totals.get("hero_decisions", 0))
        closure = int(totals.get("support_closure_decisions", 0))
        exact = int(totals.get("exact_model_a_decisions", 0))
        if exact + closure != hero_decisions:
            raise AssertionError("support closure accounting is incomplete")
        return {
            "decisions": hero_decisions,
            "exact_model_a_decisions": exact,
            "support_closure_decisions": closure,
            "support_closure_rate": None if hero_decisions == 0 else closure / hero_decisions,
            "support_closure_by_street": by_street,
            "support_closure_reasons": dict(sorted(reasons.items())),
            "fallback_contract": self.fallback_contract,
            "nearest_context_substitution": False,
            "range_posterior": "DELEGATED_EXACT_MODEL_A",
        }
