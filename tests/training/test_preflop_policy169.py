#!/usr/bin/env python3
from __future__ import annotations

import base64
import math
import struct
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.preflop_policy169 import (  # noqa: E402
    DEFAULT_SCALE,
    apply_revealed_composition_residual,
    calibrate_to_marginals,
    decode_policy169,
    encode_policy169,
    hand_weights,
    policy_marginals,
    refit_node_policy169,
)

ACTIONS = ["FOLD", "CALL", "RAISE"]
GRID = ["AA", "AKs", "72o"]
META = {
    "AA": {"combo_weight": 6},
    "AKs": {"combo_weight": 4},
    "72o": {"combo_weight": 12},
}


def baseline_policy():
    return {
        "AA": {"FOLD": 0.02, "CALL": 0.18, "RAISE": 0.80},
        "AKs": {"FOLD": 0.08, "CALL": 0.42, "RAISE": 0.50},
        "72o": {"FOLD": 0.84, "CALL": 0.14, "RAISE": 0.02},
    }


def node_from_policy(policy, *, dtype="uint16-le"):
    q = encode_policy169(
        policy,
        actions=ACTIONS,
        hand_grid=GRID,
        scale=DEFAULT_SCALE,
        dtype=dtype,
        template={"hand_order": GRID, "method": "fixture_embedded"},
    )
    return {
        "population_model": {
            "legal_actions": ACTIONS,
            "frequencies": {"FOLD": 0.45, "CALL": 0.35, "RAISE": 0.20},
            "policy169_q_b64": q,
        },
    }


def assert_close(a, b, eps=1e-8):
    assert abs(a - b) <= eps, (a, b)


def test_round_trip_distribution_is_normalized():
    node = node_from_policy(baseline_policy())
    decoded = decode_policy169(node)
    for hand in GRID:
        assert_close(sum(decoded[hand].values()), 1.0)
        assert set(decoded[hand]) == set(ACTIONS)


def test_encoding_is_action_major_uint16_little_endian():
    node = node_from_policy(baseline_policy())
    q = node["population_model"]["policy169_q_b64"]
    raw = base64.b64decode(q["data"])
    values = struct.unpack("<" + "H" * (len(ACTIONS) * len(GRID)), raw)
    assert q["shape"] == [len(ACTIONS), len(GRID)]
    assert q["dtype"] == "uint16-le"
    assert len(values) == len(ACTIONS) * len(GRID)
    for hi in range(len(GRID)):
        assert sum(values[ai * len(GRID) + hi] for ai in range(len(ACTIONS))) == DEFAULT_SCALE


def test_big_endian_contract_round_trips_too():
    node = node_from_policy(baseline_policy(), dtype="uint16-be")
    decoded = decode_policy169(node)
    assert decoded["AA"]["RAISE"] > decoded["AA"]["CALL"]
    assert_close(sum(decoded["72o"].values()), 1.0)


def test_symbolic_root_hand_order_matches_browser_contract():
    node = node_from_policy(baseline_policy())
    q = node["population_model"]["policy169_q_b64"]
    q["hand_order"] = "hand_grid.classes"
    decoded = decode_policy169(node, GRID)
    assert list(decoded) == GRID
    encoded, _ = refit_node_policy169(
        node,
        {"n_delta": 3, "actions": {"FOLD": 1, "CALL": 1, "RAISE": 1}},
        root_hand_meta=META,
        fallback_grid=GRID,
        prior_strength=40,
        update_weight=1.0,
    )
    assert encoded["hand_order"] == "hand_grid.classes"


def test_runtime_zero_quantization_floor_is_mirrored():
    policy = {
        "AA": {"FOLD": 0.0, "CALL": 0.0, "RAISE": 1.0},
        "AKs": {"FOLD": 0.0, "CALL": 1.0, "RAISE": 0.0},
        "72o": {"FOLD": 1.0, "CALL": 0.0, "RAISE": 0.0},
    }
    node = node_from_policy(policy)
    decoded = decode_policy169(node)
    assert 0.0 < decoded["AA"]["FOLD"] < 1e-4
    assert decoded["AA"]["RAISE"] > 0.999
    assert_close(sum(decoded["AA"].values()), 1.0)


def test_ipf_matches_all_decision_action_marginals():
    policy = baseline_policy()
    weights = hand_weights(GRID, META)
    target = {"FOLD": 0.50, "CALL": 0.30, "RAISE": 0.20}
    fitted, diag = calibrate_to_marginals(policy, actions=ACTIONS, weights=weights, target=target)
    marginals = policy_marginals(fitted, actions=ACTIONS, weights=weights)
    for action in ACTIONS:
        assert_close(marginals[action], target[action], 1e-8)
    assert diag["max_absolute_marginal_error"] <= 1e-8


def test_no_revealed_cards_means_no_composition_residual():
    policy = baseline_policy()
    weights = hand_weights(GRID, META)
    adjusted, diag = apply_revealed_composition_residual(
        policy,
        actions=ACTIONS,
        weights=weights,
        delta_actions={"FOLD": 40, "CALL": 20, "RAISE": 10},
        known_by_action={},
        prior_strength=40,
    )
    for hand in GRID:
        for action in ACTIONS:
            assert_close(adjusted[hand][action], policy[hand][action])
    assert all(not row["applied"] for row in diag.values())


def test_revealed_evidence_changes_nested_runtime_policy_without_imputation():
    node = node_from_policy(baseline_policy())
    delta = {
        "n_delta": 80,
        "actions": {"FOLD": 40, "CALL": 20, "RAISE": 20},
        "known_by_action": {
            "RAISE": {"AA": 8, "AKs": 2},
            "CALL": {"AKs": 2},
        },
    }
    no_reveal_delta = dict(delta)
    no_reveal_delta["known_by_action"] = {}
    neutral_encoded, _ = refit_node_policy169(
        node, no_reveal_delta, root_hand_meta=META, fallback_grid=GRID,
        prior_strength=40, update_weight=1.0,
    )
    encoded, diag = refit_node_policy169(
        node, delta, root_hand_meta=META, fallback_grid=GRID,
        prior_strength=40, update_weight=1.0,
    )
    neutral_node = {"population_model": dict(node["population_model"])}
    neutral_node["population_model"]["policy169_q_b64"] = neutral_encoded
    candidate = {"population_model": dict(node["population_model"])}
    candidate["population_model"]["policy169_q_b64"] = encoded
    neutral = decode_policy169(neutral_node)
    after = decode_policy169(candidate)
    assert diag["hidden_hands_imputed"] == 0
    assert diag["train_revealed_rows"] == 12
    assert after["AA"]["RAISE"] > neutral["AA"]["RAISE"]
    assert after["72o"]["RAISE"] < neutral["72o"]["RAISE"]
    assert encoded["method"].endswith("+policy169_refit_v1")


def test_zero_update_weight_preserves_runtime_object_exactly():
    node = node_from_policy(baseline_policy())
    original = node["population_model"]["policy169_q_b64"]
    delta = {
        "n_delta": 20,
        "actions": {"FOLD": 10, "CALL": 5, "RAISE": 5},
        "known_by_action": {"RAISE": {"AA": 5}},
    }
    encoded, _ = refit_node_policy169(
        node, delta, root_hand_meta=META, fallback_grid=GRID,
        prior_strength=40, update_weight=0.0,
    )
    assert encoded == original
    assert encoded is not original


def test_malformed_payload_is_rejected():
    node = node_from_policy(baseline_policy())
    node["population_model"]["policy169_q_b64"]["data"] = base64.b64encode(b"short").decode("ascii")
    try:
        decode_policy169(node)
    except ValueError as exc:
        assert "length mismatch" in str(exc)
    else:
        raise AssertionError("malformed policy payload should fail")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"preflop policy169 tests: {len(tests)} passed")
