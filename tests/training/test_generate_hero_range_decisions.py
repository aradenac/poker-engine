#!/usr/bin/env python3
from __future__ import annotations

from tools.simulation.model_a_continuation import (
    ModelAContinuationPolicy,
    ModelAUnsupportedContext,
    _preflop_decision,
    _semantic_trace,
)
from tools.simulation.model_b_runtime import combo_class
from tools.training.generate_hero_range_decisions import (
    HAND_CLASSES,
    ContextSpec,
    FixedPopulationDerivedHeroContinuation,
    build_context_state,
    observed_raise_targets,
    representative_cards,
    semantic_grid_labels,
)


def exact_node_for_state(state, actor, *, continuous=None):
    _, replay, history, _, _ = _semantic_trace(state)
    decision = _preflop_decision(replay, actor, history)
    return {
        "node_id": "fixture-exact",
        "context": {
            "actor_position": decision["actor_position"],
            "table_size": decision["table_size"],
            "raise_level": decision["raise_level"],
            "family": decision["family"],
            "live_positions": decision["live_positions"],
            "all_in_positions": decision["all_in_positions"],
            "history": decision["history"],
        },
        "coverage": {"population_decisions": 123},
        "continuous": continuous or {},
        "population_model": {"frequencies": {"FOLD": 0.5, "RAISE": 0.5}},
    }


def main() -> None:
    assert len(HAND_CLASSES) == 169
    assert len(set(HAND_CLASSES)) == 169
    assert {"AA", "22", "AKs", "AKo", "32s", "32o"}.issubset(HAND_CLASSES)
    for hand in HAND_CLASSES:
        cards = representative_cards(hand)
        assert len(set(cards)) == 2
        assert combo_class(cards) == hand

    unopened = build_context_state(ContextSpec(position="BTN", spot="UNOPENED"))
    assert unopened.next_actor == "BTN"
    assert semantic_grid_labels(unopened) == ("LIMP", "OPEN")

    limped = build_context_state(
        ContextSpec(position="BTN", spot="VS_LIMPERS", limper_position="CO")
    )
    assert limped.next_actor == "BTN"
    assert semantic_grid_labels(limped) == ("OVERLIMP", "ISO")

    versus_rfi = build_context_state(
        ContextSpec(position="BTN", spot="VS_RFI", opener_position="CO", open_to_bb=2.5)
    )
    assert versus_rfi.next_actor == "BTN"
    assert semantic_grid_labels(versus_rfi) == ("CALL", "3BET")

    squeeze = build_context_state(
        ContextSpec(
            position="SB",
            spot="VS_RFI_CALLERS",
            opener_position="CO",
            caller_position="BTN",
            open_to_bb=2.5,
        )
    )
    assert squeeze.next_actor == "SB"
    assert semantic_grid_labels(squeeze) == ("CALL", "SQUEEZE")

    node = exact_node_for_state(
        unopened,
        "BTN",
        continuous={
            "target_total_bb": {"p25": 2.0, "median": 2.5, "p75": 3.0},
        },
    )
    policy = ModelAContinuationPolicy({"nodes": [node]}, {"nodes": []}, identity={"fixture": True})
    targets, support = observed_raise_targets(policy, unopened, "BTN")
    assert targets == [2.0, 2.5, 3.0], targets
    assert support["node_id"] == "fixture-exact"
    assert support["population_decisions"] == 123
    assert all("target_total_bb" in source for source in support["sources"]), support

    fallback_node = exact_node_for_state(unopened, "BTN", continuous={})
    fallback_policy = ModelAContinuationPolicy({"nodes": [fallback_node]}, {"nodes": []})
    try:
        observed_raise_targets(fallback_policy, unopened, "BTN")
    except ModelAUnsupportedContext:
        pass
    else:
        raise AssertionError("a legal minimum without observed sizing must remain unsupported")

    continuation = FixedPopulationDerivedHeroContinuation(policy)
    assert continuation.identity["claim"] == "NOT_OPTIMAL_HERO_STRATEGY"
    assert "POPULATION_DERIVED" in continuation.identity["contract"]

    try:
        build_context_state(ContextSpec(position="BB", spot="UNOPENED"))
    except ValueError:
        pass
    else:
        raise AssertionError("BB unopened context must fail closed")

    print("Hero range decision generation contracts: PASS")


if __name__ == "__main__":
    main()
