#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.paired_adaptive_preflop_ev import AdaptiveBudget
from tools.simulation.paired_preflop_grid_evaluator import (
    bridge_integration_file,
    evaluate_preflop_grid_paired,
)
from tools.simulation.preflop_grid_evaluator import PreflopEvaluationError


class RealGridIntegrationTests(unittest.TestCase):
    CONTEXT_ID = (
        "pfgen:v1:family=VS_LIMPERS:hero=CO:opener=NONE:lastagg=NONE:"
        "callers=0:limpers=1:jam=0:stack=B3_P50_P75"
    )
    POP = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
    PLAN = Path("analysis/hero_preflop_generation_plan.json")

    @staticmethod
    def state():
        state = NoLimitHoldemState(
            seats=["UTG", "CO", "BTN", "SB", "BB"],
            button="BTN",
            stacks_bb={p: 100 for p in ["UTG", "CO", "BTN", "SB", "BB"]},
        )
        state.apply_action("UTG", "CALL")
        assert state.next_actor == "CO"
        return state

    @classmethod
    def identity(cls):
        raw = cls.PLAN.read_bytes()
        plan = json.loads(raw)
        return {
            "population_id": plan["population_id"],
            "generation_id": "ISSUE_338_VALIDATION_TEST_GENERATION",
            "candidate_id": "ISSUE_338_VALIDATION_TEST_ARTIFACT",
            "source_plan_sha256": hashlib.sha256(raw).hexdigest(),
            "source_train_audit_sha256": plan["source"]["sha256"],
            "generator_version": "paired-preflop-grid-integration/1",
            "code_sha": "a" * 40,
            "environment_identity_slot": "env:ISSUE_338_VALIDATION",
            "generation_parameters_slot": "params:ISSUE_338_VALIDATION",
            "scientific_effect": "VALIDATION_ONLY_NO_PROMOTION",
        }

    def test_common_worlds_and_measured_bridge(self):
        calls = {}

        def rollout(state, *, actor, seed, sample_index, candidate):
            del state, actor
            alternative_id = candidate["alternative_id"]
            calls.setdefault(sample_index, {})[alternative_id] = (seed, candidate["id"])
            noise = ((seed % 101) - 50) / 10000.0
            bonus = 1.0 if alternative_id == "ISO@4BB" else 0.15
            return {"ending_stack_bb": 100.0 + bonus + noise}

        result = evaluate_preflop_grid_paired(
            self.state(),
            actor="CO",
            context_id=self.CONTEXT_ID,
            hand_class="AA",
            population_id=self.POP,
            raise_targets_bb=[4.0],
            rollout=rollout,
            budget=AdaptiveBudget(4, 12, 4, 24),
            base_seed="issue-338-real-grid",
            call_action="OVERLIMP",
            raise_action="ISO",
            include_jam=False,
            sizing_grid_source="VALIDATION_FROZEN",
        )
        self.assertEqual(result["decision"]["selected_id"], "ISO@4BB")
        self.assertFalse(result["test_consumed"])
        for per_sample in calls.values():
            self.assertEqual(per_sample["OVERLIMP@1BB"], per_sample["ISO@4BB"])
            self.assertTrue(per_sample["ISO@4BB"][1].startswith("PAIRED_WORLD:"))

        bridged = bridge_integration_file(
            result, artifact_identity=self.identity(), plan_path=self.PLAN
        )
        self.assertEqual(bridged["bridge_state"], "MEASURED_COMPATIBLE")
        self.assertEqual(bridged["alternative_id"], "ISO@4BB")
        self.assertNotEqual(bridged["alternative_id"], bridged["candidate_id"])
        self.assertEqual(bridged["strategy_cell"]["action"]["value"], "RAISE")
        self.assertEqual(bridged["strategy_cell"]["sizing"]["kind"], "FIXED_BB")
        self.assertEqual(bridged["strategy_cell"]["sizing"]["value"], 4.0)
        self.assertEqual(
            bridged["strategy_cell"]["ev"]["estimate_bb"],
            result["decision"]["ev_bb"],
        )
        self.assertTrue(result["paired_result"]["pairwise_deltas"])

    def test_validation_materialized_world_requirement_fails_closed_for_generic_rollout(self):
        def rollout(state, *, actor, seed, sample_index, candidate):
            del state, actor, seed, sample_index, candidate
            return {"ending_stack_bb": 100.0}

        with self.assertRaisesRegex(
            PreflopEvaluationError, "common-world materialization"
        ):
            evaluate_preflop_grid_paired(
                self.state(),
                actor="CO",
                context_id=self.CONTEXT_ID,
                hand_class="AA",
                population_id=self.POP,
                raise_targets_bb=[4.0],
                rollout=rollout,
                budget=AdaptiveBudget(4, 8, 4, 16),
                base_seed="issue-338-require-world",
                call_action="OVERLIMP",
                raise_action="ISO",
                include_jam=False,
                require_materialized_common_world=True,
            )

    def test_exact_fold_never_becomes_measured(self):
        def rollout(state, *, actor, seed, sample_index, candidate):
            del state, actor, seed, sample_index, candidate
            return {"ending_stack_bb": 99.0}

        result = evaluate_preflop_grid_paired(
            self.state(),
            actor="CO",
            context_id=self.CONTEXT_ID,
            hand_class="AKs",
            population_id=self.POP,
            raise_targets_bb=[4.0],
            rollout=rollout,
            budget=AdaptiveBudget(4, 8, 4, 16),
            base_seed="issue-338-fold",
            call_action="OVERLIMP",
            raise_action="ISO",
            include_jam=False,
        )
        self.assertEqual(result["decision"]["selected_id"], "FOLD")
        bridged = bridge_integration_file(
            result, artifact_identity=self.identity(), plan_path=self.PLAN
        )
        self.assertEqual(
            bridged["bridge_state"], "EXACT_ZERO_ROLLOUT_NON_MATERIALIZABLE"
        )
        self.assertIsNone(bridged["strategy_cell"])
        self.assertEqual(bridged["evidence"]["rollouts"], 0)


if __name__ == "__main__":
    unittest.main()
