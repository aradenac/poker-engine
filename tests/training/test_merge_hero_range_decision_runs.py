#!/usr/bin/env python3
from __future__ import annotations

import copy

from tools.training.generate_hero_range_decisions import HAND_CLASSES, SCHEMA
from tools.training.merge_hero_range_decision_runs import merge_runs


def audit(*, decisions: int, exact: int, fallback: int, flop: int, turn: int, reason: int):
    assert exact + fallback == decisions
    return {
        "decisions": decisions,
        "exact_model_a_decisions": exact,
        "support_closure_decisions": fallback,
        "support_closure_rate": None if decisions == 0 else fallback / decisions,
        "support_closure_by_street": {
            "preflop": 0,
            "flop": flop,
            "turn": turn,
            "river": 0,
        },
        "support_closure_reasons": {
            "missing exact postflop node": reason,
        },
        "fallback_contract": "CHECK_THEN_CALL_THEN_FOLD_V1",
        "nearest_context_substitution": False,
        "range_posterior": "DELEGATED_EXACT_MODEL_A",
    }


def shard(hands, *, opponent, hero):
    return {
        "schema": SCHEMA,
        "status": "EXPERIMENTAL",
        "promotion_authorized": False,
        "population_id": "fixture-population",
        "context": {
            "position": "LJ",
            "spot": "UNOPENED",
            "effective_stack_bb": 100.0,
        },
        "context_id": "fixture-lj-unopened-100bb",
        "version": "fixture-v1",
        "rows": [{"hand_class": hand} for hand in hands],
        "unsupported": [],
        "coverage": {
            "requested": len(hands),
            "completed": len(hands),
            "complete_169": len(hands) == 169,
        },
        "provenance": {
            "code": "fixture-code-sha",
            "models": {
                "preflop_sha256": "preflop",
                "postflop_baseline_sha256": "postflop",
                "postflop_continuation_overlay_sha256": "overlay",
                "postflop_stage_b_decision": "RETAIN_BASELINE",
            },
            "budget": {
                "requested_hand_classes": len(hands),
                "completed_hand_classes": len(hands),
                "samples_per_nonfold_candidate": 16,
                "rollout_samples_consumed": len(hands) * 16,
            },
            "selection": "NOT_PROMOTED_ISSUE_107_EXPERIMENTAL",
            "master_seed": 20260916,
            "hero_future_continuation": {"contract": "fixture-continuation"},
            "opponent_policy": "MODEL_A_SELECTED_POPULATION_CONTINUATION_WITH_AUDITED_PASSIVE_SUPPORT_CLOSURE",
            "continuation_support": {
                "enabled": True,
                "contract": "model-a-continuation-support-closed/v1",
                "fallback_contract": "CHECK_THEN_CALL_THEN_FOLD_V1",
                "nearest_context_substitution": False,
                "opponent_future_actions": opponent,
                "hero_future_actions": hero,
                "interpretation": "EXPERIMENTAL_CONTINUATION_CLOSURE_NOT_A_FITTED_POPULATION_ACTION",
            },
            "sizing_support": {
                "contract": "CERTIFIED_TRAIN_EXACT_NODE_EMPIRICAL_RAISE_SIZING_V1",
                "filters": {"split": "TRAIN", "is_hero": False},
            },
            "decision_source": "tools.simulation.preflop_grid_evaluator.evaluate_preflop_grid",
        },
    }


def main() -> None:
    split = 83
    left = shard(
        HAND_CLASSES[:split],
        opponent=audit(decisions=10, exact=8, fallback=2, flop=1, turn=1, reason=2),
        hero=audit(decisions=7, exact=6, fallback=1, flop=1, turn=0, reason=1),
    )
    right = shard(
        HAND_CLASSES[split:],
        opponent=audit(decisions=20, exact=12, fallback=8, flop=5, turn=3, reason=8),
        hero=audit(decisions=13, exact=9, fallback=4, flop=3, turn=1, reason=4),
    )

    merged = merge_runs([left, right])
    assert merged["coverage"] == {
        "requested": 169,
        "completed": 169,
        "unsupported": 0,
        "accounted": 169,
        "complete_169": True,
    }
    assert merged["provenance"]["budget"]["rollout_samples_consumed"] == 169 * 16

    closure = merged["provenance"]["continuation_support"]
    opponent = closure["opponent_future_actions"]
    assert opponent["decisions"] == 30
    assert opponent["exact_model_a_decisions"] == 20
    assert opponent["support_closure_decisions"] == 10
    assert abs(opponent["support_closure_rate"] - (10 / 30)) <= 1e-12
    assert opponent["support_closure_by_street"] == {
        "flop": 6,
        "preflop": 0,
        "river": 0,
        "turn": 4,
    }
    assert opponent["support_closure_reasons"] == {
        "missing exact postflop node": 10,
    }

    hero = closure["hero_future_actions"]
    assert hero["decisions"] == 20
    assert hero["exact_model_a_decisions"] == 15
    assert hero["support_closure_decisions"] == 5
    assert abs(hero["support_closure_rate"] - 0.25) <= 1e-12

    drift = copy.deepcopy(right)
    drift["provenance"]["continuation_support"]["opponent_future_actions"][
        "range_posterior"
    ] = "NEAREST_CONTEXT"
    try:
        merge_runs([left, drift])
    except ValueError as exc:
        assert "run identity/provenance mismatch" in str(exc)
    else:
        raise AssertionError("static continuation contract drift must remain fail-closed")

    print("Hero shard merge continuation-audit aggregation: PASS")


if __name__ == "__main__":
    main()
