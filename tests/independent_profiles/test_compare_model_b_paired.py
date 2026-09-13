#!/usr/bin/env python3
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.independent_profiles.compare_model_b_paired import (  # noqa: E402
    assert_same_dataset,
    metric_delta,
    paired_bootstrap,
)


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


def canonical_dataset():
    return {
        "unique_scoped_hands": 31003,
        "split_counts": {"TRAIN": 24755, "VALIDATION": 3073, "TEST": 3175},
        "sorted_hand_ids_sha256": "4d6ec2cdebd9488b69b733a86bb41aba5b022fcd9da49be0c5ea3dbec71c52bf",
    }


def test_dataset_identity_requires_same_hands_splits_and_fingerprint():
    dataset = canonical_dataset()
    left = {"dataset": dict(dataset)}
    right = {"dataset": dict(dataset)}
    assert assert_same_dataset(left, right) == dataset

    right["dataset"]["sorted_hand_ids_sha256"] = "different"
    try:
        assert_same_dataset(left, right)
    except AssertionError:
        pass
    else:
        raise AssertionError("paired comparison accepted a different holdout identity")


def test_dataset_identity_rejects_split_mismatch():
    left = {"dataset": canonical_dataset()}
    changed = canonical_dataset()
    changed["split_counts"] = {"TRAIN": 24754, "VALIDATION": 3074, "TEST": 3175}
    right = {"dataset": changed}
    try:
        assert_same_dataset(left, right)
    except AssertionError as exc:
        assert exc.args[0][0] == "split_counts"
    else:
        raise AssertionError("paired comparison accepted a different deterministic split")


if __name__ == "__main__":
    test_better_candidate_is_negative_and_reproducible()
    test_mixed_candidate_does_not_fake_sign()
    test_dataset_identity_requires_same_hands_splits_and_fingerprint()
    test_dataset_identity_rejects_split_mismatch()
    print("paired Model B comparison tests: PASS")
