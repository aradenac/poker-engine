#!/usr/bin/env python3
from __future__ import annotations

import copy
import unittest

from tests.simulation.test_paired_preflop_grid_integration import RealGridIntegrationTests

from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.preflop_grid_evaluator import (
    DECISION_SCHEMA,
    EV_REFERENCE,
    PreflopEvaluationError,
    UnsupportedAlternative,
    build_candidates,
    evaluate_preflop_grid,
)

POP = "pokerstars_nlhe_100-200_zoom_play_6max_v1"


class EndingStackOracle:
    def __init__(self, values: dict[str, list[float] | float], unsupported: set[str] | None = None):
        self.values = values
        self.unsupported = unsupported or set()
        self.calls: list[tuple[str, int, int]] = []

    def __call__(self, state, *, actor, seed, sample_index, candidate):
        cid = candidate["id"]
        self.calls.append((cid, seed, sample_index))
        if cid in self.unsupported:
            return {"supported": False, "reason": "fixture outside support"}
        raw = self.values[cid]
        value = raw[sample_index % len(raw)] if isinstance(raw, list) else raw
        return {"ending_stack_bb": value}


def unopened_three_way() -> NoLimitHoldemState:
    state = NoLimitHoldemState(
        seats=["BTN", "SB", "BB"],
        button="BTN",
        stacks_bb={"BTN": 100, "SB": 100, "BB": 100},
    )
    assert state.next_actor == "BTN"
    return state


def five_way_two_limpers() -> NoLimitHoldemState:
    state = NoLimitHoldemState(
        seats=["UTG", "HJ", "BTN", "SB", "BB"],
        button="BTN",
        stacks_bb={p: 100 for p in ["UTG", "HJ", "BTN", "SB", "BB"]},
    )
    assert state.next_actor == "UTG"
    state.apply_action("UTG", "CALL")
    state.apply_action("HJ", "CALL")
    assert state.next_actor == "BTN"
    return state


def six_way_raise_and_callers() -> NoLimitHoldemState:
    state = NoLimitHoldemState(
        seats=["UTG", "HJ", "CO", "BTN", "SB", "BB"],
        button="BTN",
        stacks_bb={p: 100 for p in ["UTG", "HJ", "CO", "BTN", "SB", "BB"]},
    )
    assert state.next_actor == "UTG"
    state.apply_action("UTG", "RAISE", target_total_bb=2.5)
    state.apply_action("HJ", "CALL")
    assert state.next_actor == "CO"
    return state


class CandidateGridTests(unittest.TestCase):
    def test_unopened_grid_contains_limp_open_sizings_and_jam(self):
        rows = build_candidates(
            unopened_three_way(),
            actor="BTN",
            call_action="LIMP",
            raise_action="OPEN",
            raise_targets_bb=[1.5, 2.0, 2.5, 3.0, 500],
            include_jam=True,
            sizing_grid_source="observed",
        )
        got = [(x.action, x.target_total_bb, x.sizing_origin) for x in rows]
        self.assertEqual(got[0], ("FOLD", None, None))
        self.assertIn(("LIMP", 1.0, "RULE_CALL_PRICE"), got)
        self.assertIn(("OPEN", 2.0, "observed"), got)
        self.assertIn(("OPEN", 2.5, "observed"), got)
        self.assertIn(("OPEN", 3.0, "observed"), got)
        self.assertIn(("SHOVE", 100.0, "JAM_BOUNDARY"), got)
        self.assertNotIn(("OPEN", 1.5, "observed"), got)
        self.assertEqual(len([x for x in rows if x.action == "SHOVE"]), 1)

    def test_legal_raise_without_any_legal_sizing_fails_closed(self):
        with self.assertRaisesRegex(PreflopEvaluationError, "no legal raise candidate"):
            build_candidates(
                unopened_three_way(),
                actor="BTN",
                call_action="LIMP",
                raise_action="OPEN",
                raise_targets_bb=[1.1, 500],
                include_jam=False,
            )

    def test_two_limpers_map_call_to_overlimp_and_raise_to_iso(self):
        rows = build_candidates(
            five_way_two_limpers(),
            actor="BTN",
            call_action="OVERLIMP",
            raise_action="ISO",
            raise_targets_bb=[3, 4, 5],
            include_jam=False,
            sizing_grid_source="observed_vs_limpers",
        )
        self.assertIn("OVERLIMP", [x.action for x in rows])
        self.assertEqual([x.target_total_bb for x in rows if x.action == "ISO"], [3.0, 4.0, 5.0])

    def test_open_plus_caller_maps_reraise_to_squeeze(self):
        rows = build_candidates(
            six_way_raise_and_callers(),
            actor="CO",
            call_action="CALL",
            raise_action="SQUEEZE",
            raise_targets_bb=[6, 8, 10],
            include_jam=False,
            sizing_grid_source="observed_vs_rfi_callers",
        )
        self.assertIn(("CALL", 2.5), [(x.action, x.target_total_bb) for x in rows])
        self.assertEqual([x.target_total_bb for x in rows if x.action == "SQUEEZE"], [6.0, 8.0, 10.0])

    def test_short_all_in_call_uses_call_shove(self):
        state = NoLimitHoldemState(
            seats=["UTG", "HJ", "BTN", "SB", "BB"],
            button="BTN",
            stacks_bb={"UTG": 100, "HJ": 4, "BTN": 100, "SB": 100, "BB": 100},
        )
        state.apply_action("UTG", "RAISE", target_total_bb=10)
        rows = build_candidates(
            state,
            actor="HJ",
            call_action="CALL",
            raise_action="3BET",
            raise_targets_bb=[20],
            include_jam=True,
            sizing_grid_source="fixture",
        )
        self.assertEqual([(x.action, x.target_total_bb) for x in rows], [("FOLD", None), ("CALL_SHOVE", 4.0)])

    def test_free_check_is_materialized_with_zero_cost_semantics(self):
        state = NoLimitHoldemState(
            seats=["BTN", "BB"],
            button="BTN",
            stacks_bb={"BTN": 100, "BB": 100},
        )
        state.apply_action("BTN", "CALL")
        rows = build_candidates(
            state,
            actor="BB",
            call_action="CALL",
            raise_action="ISO",
            raise_targets_bb=[2, 3],
            include_jam=False,
        )
        self.assertEqual(rows[0].action, "CHECK")
        self.assertIsNone(rows[0].target_total_bb)


class EvaluationTests(unittest.TestCase):
    def test_action_sizing_ev_identity_and_separate_uncertainties(self):
        state = unopened_three_way()
        decision_stack = state.stacks_bb["BTN"]
        oracle = EndingStackOracle(
            {
                "LIMP@1BB": [decision_stack - 0.1, decision_stack, decision_stack + 0.1],
                "OPEN@2BB": [decision_stack + 0.05, decision_stack + 0.10, decision_stack + 0.15],
                "OPEN@2.5BB": [decision_stack + 0.30, decision_stack + 0.40, decision_stack + 0.50],
                "OPEN@3BB": [decision_stack + 0.10, decision_stack + 0.20, decision_stack + 0.30],
                "SHOVE@100BB": [decision_stack - 1.2, decision_stack - 1.0, decision_stack - 0.8],
            }
        )

        def support(candidate):
            return {"observations": 80 if candidate.id == "OPEN@2.5BB" else 20, "backoff_level": "EXACT", "source": "fixture"}

        def confidence(candidate):
            return 0.9 if candidate.id == "OPEN@2.5BB" else 0.5

        def model_uncertainty(candidate):
            if candidate.id == "OPEN@2.5BB":
                return {"lower_bb": 0.25, "upper_bb": 0.55, "method": "fixture-band", "status": "SUPPORTED"}
            return {"status": "SUPPORTED", "method": "fixture-band"}

        result = evaluate_preflop_grid(
            state,
            actor="BTN",
            context_id="fixture:BTN:UNOPENED:100",
            population_id=POP,
            raise_targets_bb=[2, 2.5, 3],
            rollout=oracle,
            samples_per_candidate=3,
            base_seed=20260915,
            call_action="LIMP",
            raise_action="OPEN",
            include_jam=True,
            sizing_grid_source="observed-fixture",
            support_provider=support,
            confidence_provider=confidence,
            model_uncertainty_provider=model_uncertainty,
        )
        self.assertEqual(result["schema"], DECISION_SCHEMA)
        self.assertEqual(result["ev_reference"], EV_REFERENCE)
        self.assertEqual(result["action"], "OPEN")
        self.assertEqual(result["target_total_bb"], 2.5)
        self.assertEqual(result["bet_to_bb"], 2.5)
        self.assertEqual(result["incremental_cost_bb"], 2.5)
        self.assertAlmostEqual(result["ev_bb"], 0.4)
        self.assertEqual(result["support"]["observations"], 80)
        self.assertEqual(result["confidence"], 0.9)
        self.assertEqual(result["uncertainty"]["model"], {
            "lower_bb": 0.25,
            "upper_bb": 0.55,
            "method": "fixture-band",
            "status": "SUPPORTED",
        })
        self.assertGreater(result["uncertainty"]["monte_carlo"]["standard_error_bb"], 0)
        self.assertEqual(result["uncertainty"]["monte_carlo"]["samples"], 3)
        self.assertEqual(result["search"]["budget"], 15)
        self.assertIn("FOLD", result["search"]["candidate_ids"])
        fold = next(x for x in result["alternatives"] if x["action"] == "FOLD")
        self.assertEqual(fold["ev_bb"], 0)
        self.assertEqual(fold["incremental_cost_bb"], 0)
        self.assertIsNone(fold["target_total_bb"])
        self.assertEqual(fold["uncertainty"]["monte_carlo"]["method"], "exact_fold_reference")

    def test_past_contributions_are_sunk_and_call_cost_is_applied_exactly(self):
        state = six_way_raise_and_callers()
        start = state.stacks_bb["CO"]
        candidates = build_candidates(
            state,
            actor="CO",
            call_action="CALL",
            raise_action="SQUEEZE",
            raise_targets_bb=[6],
            include_jam=False,
        )
        call_id = next(x.id for x in candidates if x.action == "CALL")
        squeeze_id = next(x.id for x in candidates if x.action == "SQUEEZE")
        oracle = EndingStackOracle({call_id: start, squeeze_id: start - 1})
        result = evaluate_preflop_grid(
            state,
            actor="CO",
            context_id="fixture:CO:VS_RFI_CALLERS",
            population_id=POP,
            raise_targets_bb=[6],
            rollout=oracle,
            samples_per_candidate=1,
            base_seed=1,
            call_action="CALL",
            raise_action="SQUEEZE",
            include_jam=False,
        )
        call = next(x for x in result["alternatives"] if x["action"] == "CALL")
        self.assertEqual(call["target_total_bb"], 2.5)
        self.assertEqual(call["incremental_cost_bb"], 2.5)
        self.assertEqual(call["ev_bb"], 0)

    def test_unsupported_alternative_fails_closed_instead_of_ranking_partial_grid(self):
        state = unopened_three_way()
        start = state.stacks_bb["BTN"]
        oracle = EndingStackOracle(
            {
                "LIMP@1BB": start,
                "OPEN@2.5BB": start + 0.2,
                "SHOVE@100BB": start,
            },
            unsupported={"OPEN@2.5BB"},
        )
        with self.assertRaisesRegex(UnsupportedAlternative, "OPEN@2.5BB"):
            evaluate_preflop_grid(
                state,
                actor="BTN",
                context_id="fixture:unsupported",
                population_id=POP,
                raise_targets_bb=[2.5],
                rollout=oracle,
                samples_per_candidate=2,
                base_seed=7,
                call_action="LIMP",
                raise_action="OPEN",
                include_jam=True,
            )

    def test_rollout_seeds_and_result_are_deterministic(self):
        state = unopened_three_way()
        start = state.stacks_bb["BTN"]
        values = {"LIMP@1BB": start, "OPEN@2.5BB": start + 0.2, "SHOVE@100BB": start - 1}
        first = EndingStackOracle(values)
        second = EndingStackOracle(values)
        kwargs = dict(
            actor="BTN",
            context_id="fixture:deterministic",
            population_id=POP,
            raise_targets_bb=[2.5],
            samples_per_candidate=3,
            base_seed="stable-seed",
            call_action="LIMP",
            raise_action="OPEN",
            include_jam=True,
        )
        a = evaluate_preflop_grid(copy.deepcopy(state), rollout=first, **kwargs)
        b = evaluate_preflop_grid(copy.deepcopy(state), rollout=second, **kwargs)
        self.assertEqual(a, b)
        self.assertEqual(first.calls, second.calls)
        self.assertEqual(len({seed for _, seed, _ in first.calls}), len(first.calls))

    def test_promoted_status_and_invalid_confidence_are_rejected(self):
        state = unopened_three_way()
        start = state.stacks_bb["BTN"]
        oracle = EndingStackOracle({"LIMP@1BB": start, "OPEN@2.5BB": start, "SHOVE@100BB": start})
        base = dict(
            state=state,
            actor="BTN",
            context_id="fixture:guard",
            population_id=POP,
            raise_targets_bb=[2.5],
            rollout=oracle,
            samples_per_candidate=1,
            base_seed=1,
            call_action="LIMP",
            raise_action="OPEN",
            include_jam=True,
        )
        with self.assertRaisesRegex(PreflopEvaluationError, "cannot promote"):
            evaluate_preflop_grid(**base, status="PROMOTED")
        with self.assertRaisesRegex(PreflopEvaluationError, "must be in"):
            evaluate_preflop_grid(**base, confidence_provider=lambda _: 1.1)


if __name__ == "__main__":
    unittest.main()
