#!/usr/bin/env python3
from __future__ import annotations

import math
from tools.training.independent_profiles.compare_model_b_paired import metric_delta, paired_bootstrap


def test_better_candidate_is_negative_and_reproducible():
    rows = [
        {"hand_id": "1", "action_n": 2, "action_delta_loss_sum": -0.20, "range_n": 1, "range_delta_loss_sum": -0.10},
        {"hand_id": "2", "action_n": 1, "action_delta_loss_sum": -0.05, "range_n": 1, "range_delta_loss_sum": -0.03},
        {"hand_id": "3", "action_n": 3, "action_delta_loss_sum": -0.30, "range_n": 0, "range_delta_loss_sum": 0.0},
    ]
    assert math.isclose(metric_delta(rows, "action"), -0.55 / 6)
    assert math.isclose(metric_delta(rows, "range"), -0.13 / 2)
    a = paired_bootstrap(rows, seed=7, samples=500)
    b = paired_bootstrap(rows, seed=7, samples=500)
    assert a == b
    assert a["action_log_loss_delta_candidate_minus_incumbent"]["ci95"][1] < 0
    assert a["range_log_loss_delta_candidate_minus_incumbent"]["ci95"][1] < 0


def test_mixed_candidate_does_not_fake_sign():
    rows = [
        {"hand_id": "1", "action_n": 1, "action_delta_loss_sum": -0.1, "range_n": 1, "range_delta_loss_sum": 0.2},
        {"hand_id": "2", "action_n": 1, "action_delta_loss_sum": 0.2, "range_n": 1, "range_delta_loss_sum": -0.1},
    ]
    stats = paired_bootstrap(rows, seed=11, samples=500)
    assert stats["action_log_loss_delta_candidate_minus_incumbent"]["observed"] > 0
    assert stats["range_log_loss_delta_candidate_minus_incumbent"]["observed"] > 0


if __name__ == "__main__":
    test_better_candidate_is_negative_and_reproducible()
    test_mixed_candidate_does_not_fake_sign()
    print("paired Model B comparison tests: PASS")
