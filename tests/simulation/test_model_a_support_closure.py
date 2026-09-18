#!/usr/bin/env python3
from __future__ import annotations

from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.model_a_continuation import ModelAContinuationPolicy
from tools.simulation.model_a_support_closure import SupportClosedModelAContinuationPolicy


def empty_policy():
    return ModelAContinuationPolicy({"nodes": []}, {"nodes": []})


def test_facing_missing_node_closes_with_call_and_audits():
    state = NoLimitHoldemState(
        seats=["Hero", "Villain"],
        button="Hero",
        stacks_bb={"Hero": 20, "Villain": 20},
    )
    state.apply_action("Hero", "RAISE", target_total_bb=2.5)
    policy = SupportClosedModelAContinuationPolicy(empty_policy())
    out = policy.decide(
        NoLimitHoldemState.from_snapshot(state.to_snapshot()),
        seed_parts=("scenario-1", 0),
        actor="Villain",
        hole_cards=("Ks", "Qh"),
    )
    assert out["action"] == "CALL"
    assert out["benchmark_reference_support_closure"]["used"] is True
    audit = policy.aggregate_audit()
    assert audit["decisions"] == 1
    assert audit["support_closure_decisions"] == 1
    assert audit["exact_model_a_decisions"] == 0
    assert audit["support_closure_by_street"]["preflop"] == 1
    assert audit["nearest_context_substitution"] is False


def test_free_missing_node_closes_with_check():
    state = NoLimitHoldemState(
        seats=["Hero", "Villain"],
        button="Hero",
        stacks_bb={"Hero": 20, "Villain": 20},
    )
    state.apply_action("Hero", "CALL")
    state.apply_action("Villain", "CHECK")
    state.advance_street(["2s", "7h", "Jc"])
    # In heads-up postflop Villain acts first.
    actor = state.next_actor
    assert actor == "Villain"
    policy = SupportClosedModelAContinuationPolicy(empty_policy())
    out = policy.decide(
        NoLimitHoldemState.from_snapshot(state.to_snapshot()),
        seed_parts=("scenario-2", 0),
        actor=actor,
        hole_cards=("9s", "8h"),
    )
    assert out["action"] == "CHECK"
    audit = policy.aggregate_audit()
    assert audit["support_closure_by_street"]["flop"] == 1


def test_exact_model_attributes_and_posterior_api_are_delegated():
    delegate = empty_policy()
    policy = SupportClosedModelAContinuationPolicy(delegate)
    assert policy.preflop_model is delegate.preflop_model
    assert policy.postflop_model is delegate.postflop_model
    assert policy._posterior_from_history.__self__ is delegate


def main():
    tests=[v for k,v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    print(f"Model A continuation support-closure tests: {len(tests)} passed")


if __name__ == "__main__":
    main()
