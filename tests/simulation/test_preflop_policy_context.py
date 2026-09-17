#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop.policy_context import (  # noqa: E402
    SCHEMA,
    build_policy_context,
    contract_descriptor,
)
from tools.simulation.game_core import NoLimitHoldemState  # noqa: E402
from tools.simulation.hero_preflop_overlay import canonical_preflop_context  # noqa: E402


def unopened_btn_state(stack: float) -> NoLimitHoldemState:
    seats = ["BTN", "SB", "BB", "LJ", "HJ", "CO"]
    state = NoLimitHoldemState(
        seats=seats,
        button="BTN",
        stacks_bb={seat: float(stack) for seat in seats},
    )
    for actor in ("LJ", "HJ", "CO"):
        state.apply_action(actor, "FOLD")
    assert state.next_actor == "BTN"
    return state


def test_exact_pfc_changes_inside_same_policy_stack_bucket() -> None:
    pfc80 = canonical_preflop_context(unopened_btn_state(80), "BTN")
    pfc100 = canonical_preflop_context(unopened_btn_state(100), "BTN")
    assert pfc80["context_id"] != pfc100["context_id"]
    policy80 = build_policy_context(pfc80)
    policy100 = build_policy_context(pfc100)
    assert policy80["schema"] == SCHEMA
    assert policy80["effective_stack_bucket"] == "GT75_LE125"
    assert policy80["policy_context_id"] == policy100["policy_context_id"]


def test_policy_stack_boundary_is_explicit_not_nearest() -> None:
    policy70 = build_policy_context(canonical_preflop_context(unopened_btn_state(70), "BTN"))
    policy80 = build_policy_context(canonical_preflop_context(unopened_btn_state(80), "BTN"))
    assert policy70["effective_stack_bucket"] == "GT40_LE75"
    assert policy80["effective_stack_bucket"] == "GT75_LE125"
    assert policy70["policy_context_id"] != policy80["policy_context_id"]


def test_price_and_to_call_buckets_are_part_of_identity() -> None:
    pfc = canonical_preflop_context(unopened_btn_state(100), "BTN")
    base = build_policy_context(pfc)
    altered = copy.deepcopy(pfc)
    altered["current_price_bb"] = 3.0
    altered["to_call_bb"] = 3.0
    altered["pot_before_bb"] = 4.5
    altered["min_raise_to_bb"] = 5.0
    changed = build_policy_context(altered)
    assert base["current_price_bucket"] != changed["current_price_bucket"]
    assert base["to_call_bucket"] != changed["to_call_bucket"]
    assert base["policy_context_id"] != changed["policy_context_id"]


def test_history_and_actor_remain_structural() -> None:
    pfc = canonical_preflop_context(unopened_btn_state(100), "BTN")
    base = build_policy_context(pfc)
    altered = copy.deepcopy(pfc)
    altered["history"] = [{"position": "CO", "action": "LIMP"}]
    altered["family"] = "VS_LIMPERS"
    changed = build_policy_context(altered)
    assert base["policy_context_id"] != changed["policy_context_id"]


def test_contract_descriptor_forbids_nearest_context() -> None:
    descriptor = contract_descriptor()
    assert descriptor["schema"] == SCHEMA
    assert descriptor["matching"] == "EXACT_PFPC_ONLY_NO_NEAREST_CONTEXT"
    assert descriptor["stack_buckets"][-1]["upper_inclusive"] is None


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"Preflop policy context tests: {len(tests)} passed")


if __name__ == "__main__":
    main()
