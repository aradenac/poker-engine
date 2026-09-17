#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.game_core import NoLimitHoldemState  # noqa: E402
from tools.simulation.hero_preflop_overlay import (  # noqa: E402
    ExactHeroPreflopOverlayPolicy,
    canonical_preflop_context,
)

PFC = "PFC_0e01f7d1a1da491b"


class DummyReference:
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, state, *, seed_parts, **context):
        del seed_parts
        self.calls += 1
        legal = state.legal_view(str(context["actor"]))["legal_actions"]
        if "CHECK" in legal:
            return {"action": "CHECK"}
        if "CALL" in legal:
            return {"action": "CALL"}
        return {"action": "FOLD"}


def unopened_btn_state(stack: float = 100.0) -> NoLimitHoldemState:
    seats = ["BTN", "SB", "BB", "LJ", "HJ", "CO"]
    state = NoLimitHoldemState(
        seats=seats,
        button="BTN",
        stacks_bb={seat: float(stack) for seat in seats},
    )
    for actor in ("LJ", "HJ", "CO"):
        assert state.next_actor == actor
        state.apply_action(actor, "FOLD")
    assert state.next_actor == "BTN"
    return state


def repository() -> dict:
    return {
        "schema": "poker-hero-range-repository/v1",
        "contexts": {
            f"fixture|{PFC}": {
                "context": {
                    "population_id": "pokerstars_nlhe_100-200_zoom_play_6max_v1",
                    "table_size": 6,
                    "position": "BTN",
                    "effective_stack_bb": 100,
                    "spot": "UNOPENED",
                    "preflop_context_id": PFC,
                },
                "layers": {
                    "calculated": {
                        "hands": {
                            "AA": {
                                "actions": {"OPEN": 1.0},
                                "sizings": {"OPEN": [{"target_total_bb": 3.0, "probability": 1.0}]},
                                "notes": "fixture",
                            },
                            "KK": {
                                "actions": {"SHOVE": 1.0},
                                "sizings": {"SHOVE": [{"target_total_bb": 100.0, "probability": 1.0}]},
                                "notes": "fixture",
                            },
                        }
                    }
                },
            }
        },
    }


def policy(reference: DummyReference) -> ExactHeroPreflopOverlayPolicy:
    return ExactHeroPreflopOverlayPolicy(
        repository(),
        repository_sha256="f" * 64,
        reference_policy=reference,
        candidate_id="fixture-candidate",
    )


def decision_context(cards):
    return {
        "actor": "BTN",
        "hole_cards": cards,
        "profile": None,
        "relative_position": "BTN",
        "pot_type": "UNOPENED",
        "preflop_role": "NO_PRIOR_ACTION",
    }


def test_named_player_arena_state_maps_to_same_canonical_pfc() -> None:
    state = unopened_btn_state()
    context = canonical_preflop_context(state, "BTN")
    assert context["context_id"] == PFC
    assert context["actor_position"] == "BTN"
    assert context["live_positions"] == ["BTN", "SB", "BB"]
    assert context["remaining_to_act_positions"] == ["SB", "BB"]
    assert context["effective_stack_bb"] == 100.0


def test_exact_pfc_and_hand_uses_candidate_action_and_sizing() -> None:
    reference = DummyReference()
    candidate = policy(reference)
    state = unopened_btn_state()
    result = candidate.decide(
        state,
        seed_parts=("scenario-1", 123, "hero", "BTN", 0, "preflop"),
        **decision_context(("As", "Ah")),
    )
    assert result["action"] == "RAISE"
    assert result["target_total_bb"] == 3.0
    assert result["benchmark_candidate"]["supported"] is True
    assert result["benchmark_candidate"]["hand_class"] == "AA"
    assert reference.calls == 0
    assert candidate.scenario_audit("scenario-1") == {
        "hero_preflop_decisions": 1,
        "candidate_supported_decisions": 1,
        "candidate_out_of_support_decisions": 0,
        "postflop_reference_decisions": 0,
    }


def test_missing_hand_falls_back_and_counts_out_of_support() -> None:
    reference = DummyReference()
    candidate = policy(reference)
    state = unopened_btn_state()
    result = candidate.decide(
        state,
        seed_parts=("scenario-2", 123, "hero", "BTN", 0, "preflop"),
        **decision_context(("Ks", "2h")),
    )
    assert result["action"] == "CALL"
    assert result["benchmark_candidate"]["supported"] is False
    assert result["benchmark_candidate"]["reason"] == "HAND_OUT_OF_SUPPORT:K2o"
    assert reference.calls == 1
    assert candidate.scenario_audit("scenario-2")["candidate_out_of_support_decisions"] == 1


def test_stack_context_mismatch_never_nearest_matches() -> None:
    reference = DummyReference()
    candidate = policy(reference)
    state = unopened_btn_state(80.0)
    context = canonical_preflop_context(state, "BTN")
    assert context["context_id"] != PFC
    result = candidate.decide(
        state,
        seed_parts=("scenario-3", 123, "hero", "BTN", 0, "preflop"),
        **decision_context(("As", "Ah")),
    )
    assert result["benchmark_candidate"]["supported"] is False
    assert result["benchmark_candidate"]["reason"].startswith("PFC_OUT_OF_SUPPORT:")
    assert reference.calls == 1


def test_shove_preserves_all_in_boundary() -> None:
    reference = DummyReference()
    candidate = policy(reference)
    result = candidate.decide(
        unopened_btn_state(),
        seed_parts=("scenario-4", 123, "hero", "BTN", 0, "preflop"),
        **decision_context(("Ks", "Kh")),
    )
    assert result["action"] == "RAISE"
    assert result["target_total_bb"] == 100.0
    assert reference.calls == 0


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"Hero PFC overlay tests: {len(tests)} passed")


if __name__ == "__main__":
    main()
