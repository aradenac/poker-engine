#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.independent_profiles.conditioned_response_candidate import (
    action_levels,
    sizing_levels,
    state_buckets,
    validation_gate,
)


def test_hierarchy_keeps_v2_backoff_and_omits_strength():
    levels = action_levels(["price_bucket", "spr_bucket", "texture_bucket"])
    assert levels[-1] == []
    assert ["street", "mode"] in levels
    assert any("price_bucket" in row and "spr_bucket" in row and "texture_bucket" in row for row in levels)
    assert all("strength_bucket" not in row for row in levels)
    slevels = sizing_levels(["price_bucket", "spr_bucket"])
    assert slevels[-1] == []
    assert ["street", "mode", "action"] in slevels


def test_state_buckets_are_observable_only():
    facing = state_buckets(mode="FACING", to_call=50, pot=100, remaining=250, board=["As", "7h", "2c"])
    assert facing == {
        "price_bucket": "P25_50",
        "spr_bucket": "SPR_1_3",
        "texture_bucket": "UNPAIRED_RAINBOW",
    }
    free = state_buckets(mode="FREE", to_call=0, pot=100, remaining=1200, board=["Ah", "Ad", "7h", "2h"])
    assert free["price_bucket"] == "FREE"
    assert free["spr_bucket"] == "SPR_12_PLUS"
    assert free["texture_bucket"] == "PAIRED_3_FLUSH"


def test_validation_gate_requires_statistical_action_win():
    base = {
        "paired_action_log_loss": {"ci95": [-0.02, -0.001]},
        "candidate_actions": {"ece_confidence": 0.02},
        "candidate_sizing": {
            "inside_training_p10_p90_fraction": 0.80,
            "above_training_p99_fraction": 0.01,
        },
    }
    assert validation_gate(base)["pass"] is True
    base["paired_action_log_loss"]["ci95"][1] = 0.001
    assert validation_gate(base)["pass"] is False


if __name__ == "__main__":
    test_hierarchy_keeps_v2_backoff_and_omits_strength()
    test_state_buckets_are_observable_only()
    test_validation_gate_requires_statistical_action_win()
    print("ok")
