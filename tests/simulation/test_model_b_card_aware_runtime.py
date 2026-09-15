#!/usr/bin/env python3
from __future__ import annotations

import copy

from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.model_b_card_aware_runtime import (
    BEHAVIOR_SCHEMA,
    CardAwareModelBPolicy,
    hand_bucket,
    recent_sequence_bucket,
)


def behavior_fixture() -> dict:
    return {
        "schema": BEHAVIOR_SCHEMA,
        "population_id": "synthetic",
        "action": {
            "alpha_per_action": 1.0,
            "backoff_min_observations": 20,
            "levels": [
                {
                    "cols": ["street", "mode", "hand_bucket"],
                    "data": {
                        "flop|FREE|ONE_PAIR": {"n": 100, "counts": {"CHECK": 5, "RAISE": 95}},
                        "flop|FREE|HIGH_CARD": {"n": 100, "counts": {"CHECK": 95, "RAISE": 5}},
                    },
                },
                {
                    "cols": [],
                    "data": {
                        "ALL": {
                            "n": 500,
                            "counts": {"FOLD": 150, "CHECK": 150, "CALL": 100, "RAISE": 100},
                        }
                    },
                },
            ],
        },
        "sizing": {
            "semantics": "incremental_cost_over_pot_before",
            "backoff_min_observations": 12,
            "levels": [
                {
                    "cols": ["street", "mode", "hand_bucket", "action"],
                    "data": {
                        "flop|FREE|ONE_PAIR|RAISE": {"n": 50, "values": [0.1, 1.0, 100.0]},
                    },
                },
                {"cols": [], "data": {"ALL": {"n": 100, "values": [0.75, 1.0]}}},
            ],
        },
    }


def heads_up_flop() -> NoLimitHoldemState:
    state = NoLimitHoldemState(
        seats=["hero", "villain"],
        button="hero",
        stacks_bb={"hero": 100.0, "villain": 100.0},
    )
    assert state.next_actor == "hero"
    state.apply_action("hero", "CALL")
    state.apply_action("villain", "CHECK")
    state.advance_street(["2s", "7d", "Tc"])
    assert state.next_actor == "villain"
    return state


def context(actor: str, cards: list[str], *, profile: int = 1) -> dict:
    return {
        "actor": actor,
        "hole_cards": cards,
        "profile": profile,
        "relative_position": "OOP" if actor == "villain" else "IP",
        "pot_type": "LIMPED",
        "preflop_role": "CALLER",
    }


def test_private_cards_change_policy_when_model_supports_it() -> None:
    policy = CardAwareModelBPolicy(behavior_fixture())
    state = heads_up_flop()
    pair = policy.action_probabilities(state, **context("villain", ["As", "Ac"]))
    high = policy.action_probabilities(state, **context("villain", ["Kh", "Qd"]))
    assert pair["features"]["hand_bucket"] == "ONE_PAIR"
    assert high["features"]["hand_bucket"] == "HIGH_CARD"
    assert pair["probabilities"]["RAISE"] > 0.9
    assert high["probabilities"]["CHECK"] > 0.9
    assert pair["selection"]["level"] == 0
    assert high["selection"]["level"] == 0


def test_action_probability_is_normalized_over_currently_legal_actions() -> None:
    policy = CardAwareModelBPolicy(behavior_fixture())
    state = heads_up_flop()
    state.apply_action("villain", "RAISE", target_total_bb=2.0)
    assert state.next_actor == "hero"
    result = policy.action_probabilities(state, **context("hero", ["Ah", "Kd"]))
    assert set(result["legal_actions"]) == {"FOLD", "CALL", "RAISE"}
    assert set(result["probabilities"]) == {"FOLD", "CALL", "RAISE"}
    assert abs(sum(result["probabilities"].values()) - 1.0) < 1e-12
    assert all(value > 0 for value in result["probabilities"].values())


def test_empirical_sizing_filters_targets_outside_rule_and_stack_bounds() -> None:
    policy = CardAwareModelBPolicy(behavior_fixture())
    state = heads_up_flop()
    result = policy.sizing_candidates(state, **context("villain", ["As", "Ac"]))
    assert result["source"] == "EMPIRICAL"
    assert result["selection"]["level"] == 0
    # Pot is 2 BB. 0.1 pot is below the 1-BB minimum; 100 pot exceeds stack.
    assert [row["target_total_bb"] for row in result["candidates"]] == [2.0]
    assert result["legal_bounds"]["min_raise_to_bb"] == 1.0
    assert result["legal_bounds"]["max_raise_to_bb"] == 99.0


def test_sizing_uses_explicit_legal_boundary_fallback_when_empirical_support_is_unusable() -> None:
    artifact = copy.deepcopy(behavior_fixture())
    artifact["sizing"]["levels"][0]["data"]["flop|FREE|ONE_PAIR|RAISE"]["values"] = [0.01, 1000.0]
    artifact["sizing"]["levels"][1]["data"]["ALL"]["values"] = [0.01, 1000.0]
    policy = CardAwareModelBPolicy(artifact)
    state = heads_up_flop()
    result = policy.sizing_candidates(state, **context("villain", ["As", "Ac"]))
    assert result["source"] == "LEGAL_BOUNDARY_FALLBACK"
    assert [row["target_total_bb"] for row in result["candidates"]] == [1.0]


def test_preflop_features_expose_exact_hand_multiway_count_and_public_sequence_only() -> None:
    state = NoLimitHoldemState(
        seats=["sb", "bb", "utg", "btn"],
        button="btn",
        stacks_bb={player: 100.0 for player in ["sb", "bb", "utg", "btn"]},
    )
    assert state.next_actor == "utg"
    policy = CardAwareModelBPolicy(behavior_fixture())
    features = policy.features(
        state,
        actor="utg",
        hole_cards=["As", "Ks"],
        profile=2,
        relative_position="EP",
        pot_type="UNOPENED",
        preflop_role="PFA",
    )
    assert features["hand_bucket"] == "PREFLOP_AKs"
    assert features["opponents_bucket"] == "FOUR_PLUS"
    assert features["sequence_bucket"] == "EMPTY"
    state.apply_action("utg", "CALL")
    assert recent_sequence_bucket(state) == "C"


def test_postflop_draw_bucket_uses_only_current_board() -> None:
    assert hand_bucket(["8h", "9h"], ["7h", "Th", "2c"], "flop") == "HIGH_CARD+FD+SD"
    # The unseen turn/river are not arguments and therefore cannot influence this bucket.
    assert hand_bucket(["8h", "9h"], ["7h", "Th", "2c"], "flop") == "HIGH_CARD+FD+SD"


def test_duplicate_private_public_cards_fail_closed() -> None:
    try:
        hand_bucket(["As", "Kd"], ["As", "7d", "Tc"], "flop")
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate card state must be rejected")


def test_decision_is_deterministic_for_same_seed_and_contains_canonical_cost() -> None:
    policy = CardAwareModelBPolicy(behavior_fixture())
    left = heads_up_flop()
    right = heads_up_flop()
    kwargs = context("villain", ["As", "Ac"])
    a = policy.decide(left, seed_parts=("hand-1", "villain", "flop"), **kwargs)
    b = policy.decide(right, seed_parts=("hand-1", "villain", "flop"), **kwargs)
    assert a == b
    assert a["action"] in left.legal_view("villain")["legal_actions"]
    if a["action"] == "RAISE":
        assert a["target_total_bb"] is not None
        assert a["incremental_cost_bb"] == a["target_total_bb"]
    else:
        assert a["target_total_bb"] is None


def test_invalid_behavior_schema_is_rejected() -> None:
    artifact = behavior_fixture()
    artifact["schema"] = "wrong"
    try:
        CardAwareModelBPolicy(artifact)
    except ValueError as exc:
        assert "schema" in str(exc)
    else:
        raise AssertionError("invalid schema must fail closed")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"card-aware Model B runtime tests: {len(tests)} passed")
