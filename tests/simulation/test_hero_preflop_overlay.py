#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop.policy_context import SCHEMA as POLICY_CONTEXT_SCHEMA, build_policy_context  # noqa: E402
from tools.simulation.game_core import NoLimitHoldemState  # noqa: E402
from tools.simulation.hero_preflop_overlay import (  # noqa: E402
    ExactHeroPreflopOverlayPolicy,
    POLICY_BINDING_SCHEMA,
    canonical_preflop_context,
)

PFC = "PFC_0e01f7d1a1da491b"
REPOSITORY_SHA = "f" * 64


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
                            "QQ": {
                                "actions": {"3BET": 1.0},
                                "sizings": {"3BET": [{"target_total_bb": 9.0, "probability": 1.0}]},
                                "notes": "fixture",
                            },
                            "JJ": {
                                "actions": {"4BET": 1.0},
                                "sizings": {"4BET": [{"target_total_bb": 22.0, "probability": 1.0}]},
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
        repository_sha256=REPOSITORY_SHA,
        reference_policy=reference,
        candidate_id="fixture-candidate",
    )


def bucket_binding() -> dict:
    source = build_policy_context(canonical_preflop_context(unopened_btn_state(100.0), "BTN"))
    return {
        "schema": POLICY_BINDING_SCHEMA,
        "policy_context_schema": POLICY_CONTEXT_SCHEMA,
        "repository_sha256": REPOSITORY_SHA,
        "bindings": {
            source["policy_context_id"]: {
                "preflop_context_id": PFC,
                "source_effective_stack_bb": 100.0,
            }
        },
    }


def bound_policy(reference: DummyReference) -> ExactHeroPreflopOverlayPolicy:
    return ExactHeroPreflopOverlayPolicy(
        repository(),
        repository_sha256=REPOSITORY_SHA,
        reference_policy=reference,
        candidate_id="fixture-bound-candidate",
        policy_binding=bucket_binding(),
        policy_binding_sha256="e" * 64,
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
    assert result["benchmark_candidate"]["preflop_context_id"] == PFC
    assert reference.calls == 0
    audit = candidate.scenario_audit("scenario-1")
    assert audit["hero_preflop_decisions"] == 1
    assert audit["candidate_supported_decisions"] == 1
    assert audit["candidate_out_of_support_decisions"] == 0
    assert audit["postflop_reference_decisions"] == 0
    assert audit["policy_contexts"][PFC] == {
        "hero_preflop_decisions": 1,
        "candidate_supported_decisions": 1,
        "candidate_out_of_support_decisions": 0,
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


def test_stack_context_mismatch_never_nearest_matches_in_legacy_mode() -> None:
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


def test_explicit_pfpc_binding_matches_same_declared_stack_bucket() -> None:
    reference = DummyReference()
    candidate = bound_policy(reference)
    live_state = unopened_btn_state(80.0)
    live_pfc = canonical_preflop_context(live_state, "BTN")
    assert live_pfc["context_id"] != PFC
    live_policy_context = build_policy_context(live_pfc)
    result = candidate.decide(
        live_state,
        seed_parts=("scenario-bound", 123, "hero", "BTN", 0, "preflop"),
        **decision_context(("As", "Ah")),
    )
    evidence = result["benchmark_candidate"]
    assert evidence["supported"] is True
    assert evidence["policy_context_id"] == live_policy_context["policy_context_id"]
    assert evidence["source_preflop_context_id"] == PFC
    assert evidence["live_preflop_context_id"] == live_pfc["context_id"]
    assert result["target_total_bb"] == 3.0
    assert reference.calls == 0
    audit = candidate.scenario_audit("scenario-bound")
    assert audit["policy_contexts"][live_policy_context["policy_context_id"]] == {
        "hero_preflop_decisions": 1,
        "candidate_supported_decisions": 1,
        "candidate_out_of_support_decisions": 0,
    }
    identity = candidate.identity()
    assert identity["matching"] == "EXACT_POLICY_CONTEXT_AND_169_HAND_CLASS_ONLY"
    assert identity["nearest_context_substitution"] is False


def test_pfpc_non_shove_aggression_preserves_source_sizing_within_bucket() -> None:
    reference = DummyReference()
    candidate = bound_policy(reference)
    live_state = unopened_btn_state(106.16)

    cases = [
        (("As", "Ah"), 3.0, "OPEN"),
        (("Qs", "Qh"), 9.0, "3BET"),
        (("Js", "Jh"), 22.0, "4BET"),
    ]
    for index, (cards, expected_target, repository_action) in enumerate(cases):
        result = candidate.decide(
            live_state,
            seed_parts=(f"scenario-bound-nonshove-{index}", 123, "hero", "BTN", 0, "preflop"),
            **decision_context(cards),
        )
        assert result["action"] == "RAISE"
        assert result["target_total_bb"] == expected_target
        assert result["benchmark_candidate"]["repository_action"] == repository_action
        assert result["benchmark_candidate"]["supported"] is True

    assert reference.calls == 0


def test_pfpc_binding_does_not_cross_declared_stack_bucket() -> None:
    reference = DummyReference()
    candidate = bound_policy(reference)
    live_state = unopened_btn_state(70.0)
    result = candidate.decide(
        live_state,
        seed_parts=("scenario-bound-miss", 123, "hero", "BTN", 0, "preflop"),
        **decision_context(("As", "Ah")),
    )
    assert result["benchmark_candidate"]["supported"] is False
    assert result["benchmark_candidate"]["reason"].startswith("PFPC_OUT_OF_SUPPORT:")
    miss_id = build_policy_context(canonical_preflop_context(live_state, "BTN"))["policy_context_id"]
    audit = candidate.scenario_audit("scenario-bound-miss")
    assert audit["policy_contexts"][miss_id] == {
        "hero_preflop_decisions": 1,
        "candidate_supported_decisions": 0,
        "candidate_out_of_support_decisions": 1,
    }
    assert reference.calls == 1


def test_binding_repository_hash_mismatch_fails_closed() -> None:
    reference = DummyReference()
    binding = bucket_binding()
    binding["repository_sha256"] = "0" * 64
    try:
        ExactHeroPreflopOverlayPolicy(
            repository(),
            repository_sha256=REPOSITORY_SHA,
            reference_policy=reference,
            candidate_id="bad-binding",
            policy_binding=binding,
        )
    except ValueError as exc:
        assert "SHA-256 mismatch" in str(exc)
    else:
        raise AssertionError("binding/repository identity mismatch must fail closed")


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


def test_pfpc_shove_retargets_to_live_all_in_within_frozen_stack_bucket() -> None:
    reference = DummyReference()
    candidate = bound_policy(reference)
    live_stack = 106.16
    live_state = unopened_btn_state(live_stack)
    live_policy_context = build_policy_context(canonical_preflop_context(live_state, "BTN"))
    source_policy_context = build_policy_context(canonical_preflop_context(unopened_btn_state(100.0), "BTN"))
    assert live_policy_context["policy_context_id"] == source_policy_context["policy_context_id"]

    result = candidate.decide(
        live_state,
        seed_parts=("scenario-bound-shove", 123, "hero", "BTN", 0, "preflop"),
        **decision_context(("Ks", "Kh")),
    )
    assert result["action"] == "RAISE"
    assert result["target_total_bb"] == live_stack
    assert result["benchmark_candidate"]["supported"] is True
    assert result["benchmark_candidate"]["source_preflop_context_id"] == PFC
    assert reference.calls == 0


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"Hero PFC/PFPC overlay tests: {len(tests)} passed")


if __name__ == "__main__":
    main()
