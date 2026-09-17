#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.game_core import NoLimitHoldemState  # noqa: E402
from tools.simulation.model_a_continuation import ModelAUnsupportedContext  # noqa: E402
from tools.simulation.reference_support_closure import SupportClosedModelAReferencePolicy  # noqa: E402


class ExactDelegate:
    identity = {"name": "exact-fixture"}

    def decide(self, state, *, seed_parts, **context):
        del state, seed_parts, context
        return {"action": "FOLD"}


class MissingDelegate:
    identity = {"name": "missing-fixture"}

    def decide(self, state, *, seed_parts, **context):
        del state, seed_parts, context
        raise ModelAUnsupportedContext("fixture exact node missing")


def unopened_btn_state() -> NoLimitHoldemState:
    seats = ["BTN", "SB", "BB", "LJ", "HJ", "CO"]
    state = NoLimitHoldemState(seats=seats, button="BTN", stacks_bb={seat: 100.0 for seat in seats})
    for actor in ("LJ", "HJ", "CO"):
        state.apply_action(actor, "FOLD")
    assert state.next_actor == "BTN"
    return state


def context():
    return {
        "actor": "BTN",
        "hole_cards": ("As", "Ah"),
        "profile": None,
        "relative_position": "BTN",
        "pot_type": "UNOPENED",
        "preflop_role": "NO_PRIOR_ACTION",
    }


def test_exact_delegate_is_preserved() -> None:
    policy = SupportClosedModelAReferencePolicy(ExactDelegate())
    result = policy.decide(
        unopened_btn_state(),
        seed_parts=("scenario-exact", 7, "hero", "BTN", 0, "preflop"),
        **context(),
    )
    assert result == {"action": "FOLD"}
    audit = policy.scenario_audit("scenario-exact")
    assert audit["hero_decisions"] == 1
    assert audit["exact_model_a_decisions"] == 1
    assert audit["support_closure_decisions"] == 0


def test_missing_exact_node_uses_predeclared_passive_legal_action() -> None:
    policy = SupportClosedModelAReferencePolicy(MissingDelegate())
    result = policy.decide(
        unopened_btn_state(),
        seed_parts=("scenario-miss", 7, "hero", "BTN", 0, "preflop"),
        **context(),
    )
    # At an unopened BTN decision CALL is the low-level limp action.
    assert result["action"] == "CALL"
    marker = result["benchmark_reference_support_closure"]
    assert marker["used"] is True
    assert marker["nearest_context_substitution"] is False
    assert marker["reason"] == "fixture exact node missing"
    audit = policy.scenario_audit("scenario-miss")
    assert audit["support_closure_decisions"] == 1
    assert audit["support_closure_by_street"]["preflop"] == 1
    assert audit["support_closure_reasons"] == {"fixture exact node missing": 1}


def test_free_check_prefers_check() -> None:
    policy = SupportClosedModelAReferencePolicy(MissingDelegate())
    state = unopened_btn_state()
    state.apply_action("BTN", "CALL")
    state.apply_action("SB", "CALL")
    assert state.next_actor == "BB"
    result = policy.decide(
        state,
        seed_parts=("scenario-check", 7, "hero", "BB", 0, "preflop"),
        actor="BB",
        hole_cards=("Ks", "Kh"),
        profile=None,
        relative_position="BB",
        pot_type="LIMPED",
        preflop_role="NO_PRIOR_ACTION",
    )
    assert result["action"] == "CHECK"


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"Reference support closure tests: {len(tests)} passed")


if __name__ == "__main__":
    main()
