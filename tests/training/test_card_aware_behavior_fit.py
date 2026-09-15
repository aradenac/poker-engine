#!/usr/bin/env python3
from __future__ import annotations

from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.model_b_card_aware_runtime import CardAwareModelBPolicy
from tools.training.independent_profiles.card_aware_behavior_fit import (
    bucket_posterior_from_classes,
    exact_hand_posterior,
    fit_behavior_from_soft_decisions,
    normalized_posterior,
)

ACTION_LEVELS = [
    ["street", "mode", "hand_bucket"],
    [],
]
SIZING_LEVELS = [
    ["street", "mode", "hand_bucket", "action"],
    [],
]


def public_row(action: str, posterior: dict[str, float], sizing: float | None = None) -> dict:
    row = {
        "profile": 1,
        "street": "flop",
        "mode": "FREE",
        "relative_position": "OOP",
        "pot_type": "LIMPED",
        "preflop_role": "CALLER",
        "price_bucket": "FREE",
        "spr_bucket": "SPR_12_PLUS",
        "opponents_bucket": "HEADS_UP",
        "sequence_bucket": "EMPTY",
        "raise_level": 0,
        "board_texture": "UNPAIRED_RAINBOW",
        "action": action,
        "hand_posterior": posterior,
    }
    if sizing is not None:
        row["incremental_cost_over_pot"] = sizing
    return row


def fitted() -> dict:
    return fit_behavior_from_soft_decisions(
        [
            public_row("CHECK", {"ONE_PAIR": 0.75, "HIGH_CARD": 0.25}),
            public_row("RAISE", {"ONE_PAIR": 0.25, "HIGH_CARD": 0.75}, sizing=1.0),
        ],
        action_levels=ACTION_LEVELS,
        sizing_levels=SIZING_LEVELS,
        action_backoff_min_observations=1,
        sizing_backoff_min_observations=1,
        population_id="synthetic",
    )


def heads_up_flop() -> NoLimitHoldemState:
    state = NoLimitHoldemState(
        seats=["hero", "villain"],
        button="hero",
        stacks_bb={"hero": 100.0, "villain": 100.0},
    )
    state.apply_action("hero", "CALL")
    state.apply_action("villain", "CHECK")
    state.advance_street(["2s", "7d", "Tc"])
    return state


def runtime_context(cards: list[str]) -> dict:
    return {
        "actor": "villain",
        "hole_cards": cards,
        "profile": 1,
        "relative_position": "OOP",
        "pot_type": "LIMPED",
        "preflop_role": "CALLER",
    }


def test_soft_decision_preserves_one_unit_of_mass_per_hierarchy_level() -> None:
    artifact = fitted()
    all_node = artifact["action"]["levels"][1]["data"]["ALL"]
    assert abs(all_node["n"] - 2.0) < 1e-12
    assert abs(all_node["counts"]["CHECK"] - 1.0) < 1e-12
    assert abs(all_node["counts"]["RAISE"] - 1.0) < 1e-12

    pair = artifact["action"]["levels"][0]["data"]["flop|FREE|ONE_PAIR"]
    high = artifact["action"]["levels"][0]["data"]["flop|FREE|HIGH_CARD"]
    assert abs(pair["n"] - 1.0) < 1e-12
    assert pair["counts"] == {"CHECK": 0.75, "RAISE": 0.25}
    assert abs(high["n"] - 1.0) < 1e-12
    assert high["counts"] == {"CHECK": 0.25, "RAISE": 0.75}


def test_soft_sizing_keeps_fractional_posterior_weights() -> None:
    artifact = fitted()
    pair = artifact["sizing"]["levels"][0]["data"]["flop|FREE|ONE_PAIR|RAISE"]
    high = artifact["sizing"]["levels"][0]["data"]["flop|FREE|HIGH_CARD|RAISE"]
    assert pair["n"] == 0.25
    assert pair["weighted_values"] == [{"value": 1.0, "weight": 0.25}]
    assert high["n"] == 0.75
    assert high["weighted_values"] == [{"value": 1.0, "weight": 0.75}]
    all_node = artifact["sizing"]["levels"][1]["data"]["ALL"]
    assert all_node["n"] == 1.0
    assert sum(row["weight"] for row in all_node["weighted_values"]) == 1.0


def test_fitted_artifact_is_consumable_by_runtime_without_hard_labels() -> None:
    artifact = fitted()
    policy = CardAwareModelBPolicy(artifact)
    state = heads_up_flop()
    pair = policy.action_probabilities(state, **runtime_context(["As", "Ac"]))
    high = policy.action_probabilities(state, **runtime_context(["Kh", "Qd"]))
    assert pair["probabilities"]["CHECK"] > pair["probabilities"]["RAISE"]
    assert high["probabilities"]["RAISE"] > high["probabilities"]["CHECK"]

    sizing = policy.sizing_candidates(state, **runtime_context(["As", "Ac"]))
    # Pair-specific sizing support is fractional (<1), so hierarchy backoff uses ALL.
    assert sizing["selection"]["level"] == 1
    assert sizing["selection"]["support"] == 1.0
    assert sizing["candidates"][0]["weight"] == 1.0


def test_revealed_cards_are_point_mass_not_a_special_parallel_pipeline() -> None:
    posterior = exact_hand_posterior(["As", "Ac"], ["2s", "7d", "Tc"], "flop")
    assert posterior == {"ONE_PAIR": 1.0}


def test_latent_169_class_projection_respects_current_public_blockers() -> None:
    preflop = bucket_posterior_from_classes({"AA": 0.7, "KK": 0.3}, board=[], street="preflop")
    assert preflop == {"PREFLOP_AA": 0.7, "PREFLOP_KK": 0.3}

    flop = bucket_posterior_from_classes({"AA": 1.0}, board=["As", "7d", "Tc"], street="flop")
    assert flop == {"TRIPS": 1.0}


def test_posterior_is_normalized_and_invalid_mass_fails_closed() -> None:
    assert normalized_posterior({"A": 2, "B": 1}) == {"A": 2 / 3, "B": 1 / 3}
    for values in ({}, {"A": -1.0}, {"A": float("nan")}):
        try:
            normalized_posterior(values)
        except ValueError:
            pass
        else:
            raise AssertionError(f"posterior should be rejected: {values}")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"posterior-weighted Model B fit tests: {len(tests)} passed")
