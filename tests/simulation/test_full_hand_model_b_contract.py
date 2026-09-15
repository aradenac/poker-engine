#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.full_hand_arena import run_full_hand
from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.model_b_card_aware_runtime import BEHAVIOR_SCHEMA, SIZING_SEMANTICS
from tools.simulation.model_b_public_reference import (
    REFERENCE_ARTIFACT_NAME,
    RETAIN_DECISION,
    RetainedPublicModelBPolicy,
)


class CapturePassivePolicy:
    def __init__(self):
        self.calls = []

    def decide(self, state, *, seed_parts, **context):
        self.calls.append({"street": state.street, "context": dict(context), "seed_parts": tuple(seed_parts)})
        legal = state.legal_view(context["actor"])["legal_actions"]
        if "CHECK" in legal:
            return {"action": "CHECK"}
        if "CALL" in legal:
            return {"action": "CALL"}
        return {"action": "FOLD"}


def arena_scenario() -> dict:
    return {
        "schema": "full-hand-arena-scenario/v1",
        "scenario_id": "contract-context",
        "cluster_id": "contract-context",
        "population_id": "fixture-population",
        "hero": "BTN",
        "seats": ["BTN", "SB", "BB"],
        "button": "BTN",
        "positions": {"BTN": "BTN", "SB": "SB", "BB": "BB"},
        "stacks_bb": {"BTN": 100.0, "SB": 100.0, "BB": 100.0},
        "hole_cards": {"BTN": ["As", "Kd"], "SB": ["Qh", "Qc"], "BB": ["Js", "Td"]},
        "board": ["2c", "3d", "4h", "5s", "6c"],
        "profiles": {"BTN": None, "SB": 0, "BB": 1},
        "component_seeds": {"deck": 1, "opponent_actions": 2, "hero_policy": 3, "monte_carlo": 4},
    }


def public_behavior() -> dict:
    return {
        "schema": BEHAVIOR_SCHEMA,
        "population_id": "pokerstars_nlhe_100-200_zoom_play_6max_v1",
        "action": {
            "alpha_per_action": 1.0,
            "backoff_min_observations": 1,
            "levels": [{"cols": [], "data": {"ALL": {"n": 100, "counts": {"FOLD": 10, "CHECK": 30, "CALL": 30, "RAISE": 30}}}}],
        },
        "sizing": {
            "semantics": SIZING_SEMANTICS,
            "backoff_min_observations": 1,
            "levels": [{"cols": [], "data": {"ALL": {"n": 20, "weighted_values": [{"value": 1.0, "weight": 20.0}]}}}],
        },
    }


def result_for(path: Path, *, decision: str = RETAIN_DECISION) -> dict:
    raw = path.read_bytes()
    return {
        "schema": "independent-model-b-card-aware-result/v1",
        "decision": decision,
        "test_consumed": False,
        "production_model_b_effect": "NONE",
        "hero_strategy_effect": "NONE",
        "candidate_artifacts": {
            REFERENCE_ARTIFACT_NAME: {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
        },
        "validation": {
            "actions": {"delta": 0.01},
            "sizing": {"candidate_mean_absolute_log_error": 0.8, "reference_mean_absolute_log_error": 0.7},
        },
    }


class FullHandModelBContractTests(unittest.TestCase):
    def test_arena_context_matches_issue_104_training_labels(self):
        hero = CapturePassivePolicy()
        opponents = CapturePassivePolicy()
        run_full_hand(arena_scenario(), hero_policy=hero, opponent_policy=opponents)

        first = hero.calls[0]
        self.assertEqual(first["street"], "preflop")
        self.assertEqual(first["context"]["relative_position"], "BTN")
        self.assertEqual(first["context"]["pot_type"], "UNOPENED")
        self.assertEqual(first["context"]["preflop_role"], "NO_PRIOR_ACTION")

        flop_sb = next(
            row for row in opponents.calls
            if row["street"] == "flop" and row["context"]["actor"] == "SB"
        )
        self.assertEqual(flop_sb["context"]["relative_position"], "SB")
        self.assertEqual(flop_sb["context"]["pot_type"], "LIMPED")
        self.assertEqual(flop_sb["context"]["preflop_role"], "LIMPER")

    def _write_fixture(self, directory: Path, behavior: dict | None = None, *, decision: str = RETAIN_DECISION):
        behavior_path = directory / REFERENCE_ARTIFACT_NAME
        behavior_path.write_text(json.dumps(behavior or public_behavior(), sort_keys=True), encoding="utf-8")
        result_path = directory / "RESULT.json"
        result_path.write_text(json.dumps(result_for(behavior_path, decision=decision), sort_keys=True), encoding="utf-8")
        return behavior_path, result_path

    def test_retained_public_reference_is_hole_card_invariant(self):
        with tempfile.TemporaryDirectory() as tmp:
            behavior_path, result_path = self._write_fixture(Path(tmp))
            policy = RetainedPublicModelBPolicy.from_paths(behavior_path, result_path)
            state = NoLimitHoldemState(
                seats=["BTN", "BB"], button="BTN", stacks_bb={"BTN": 100.0, "BB": 100.0}
            )
            common = {
                "actor": "BTN", "profile": 0, "relative_position": "SB_BTN",
                "pot_type": "UNOPENED", "preflop_role": "NO_PRIOR_ACTION",
            }
            left = policy.decide(state, seed_parts=(1, 2, 3), hole_cards=["As", "Ad"], **common)
            right = policy.decide(state, seed_parts=(1, 2, 3), hole_cards=["7c", "2d"], **common)
            self.assertEqual(left["action"], right["action"])
            self.assertEqual(left["target_total_bb"], right["target_total_bb"])
            self.assertEqual(left["probabilities"], right["probabilities"])
            self.assertEqual(policy.identity()["selection_decision"], RETAIN_DECISION)
            self.assertFalse(policy.identity()["test_consumed_by_issue_104"])

    def test_reference_loader_fails_closed_on_hash_or_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            behavior_path, result_path = self._write_fixture(directory)
            behavior_path.write_text(behavior_path.read_text() + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                RetainedPublicModelBPolicy.from_paths(behavior_path, result_path)

            behavior_path, result_path = self._write_fixture(directory, decision="ACCEPT_EXPERIMENTAL_BEHAVIOR_COMPONENT")
            with self.assertRaisesRegex(ValueError, "did not retain"):
                RetainedPublicModelBPolicy.from_paths(behavior_path, result_path)

    def test_reference_loader_rejects_private_hand_conditioning(self):
        behavior = copy.deepcopy(public_behavior())
        behavior["action"]["levels"][0]["cols"] = ["hand_bucket"]
        behavior["action"]["levels"][0]["data"] = {
            "PREFLOP_AA": {"n": 100, "counts": {"FOLD": 1, "CHECK": 1, "CALL": 1, "RAISE": 97}}
        }
        with tempfile.TemporaryDirectory() as tmp:
            behavior_path, result_path = self._write_fixture(Path(tmp), behavior)
            with self.assertRaisesRegex(ValueError, "public-only.*hand_bucket"):
                RetainedPublicModelBPolicy.from_paths(behavior_path, result_path)


if __name__ == "__main__":
    unittest.main()
