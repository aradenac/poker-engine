#!/usr/bin/env python3
from __future__ import annotations

import math

from tools.training.independent_profiles.reveal_aware_ranges import (
    build_latent_ranges,
    fit_latent_node,
)


def obs(signature: str, hand_class: str | None) -> dict:
    return {
        "profile": 0,
        "position": "BTN",
        "pot_type": "SRP",
        "preflop_role": "PFA" if signature == "RAISE" else "CALLER",
        "signature": signature,
        "hand_class": hand_class,
    }


def test_hidden_folds_are_counted_but_never_promoted_to_known_cards() -> None:
    observations = [obs("RAISE", "AA") for _ in range(20)]
    observations += [obs("CALL", "72o") for _ in range(20)]
    observations += [obs("FOLD", None) for _ in range(100)]
    node = fit_latent_node(
        observations,
        ["AA", "72o"],
        {"AA": 1, "72o": 1},
        prior_strength=2.0,
        action_prior_strength=2.0,
    )
    assert node["n"] == 140
    assert node["revealed_n"] == 40
    assert node["hidden_n"] == 100
    assert node["revealed_counts"] == {"72o": 20, "AA": 20}
    assert "FOLD" in node["nonidentified_signatures"]
    assert math.isclose(sum(node["counts"].values()), 140.0, abs_tol=1e-5)


def test_action_signal_recovers_known_synthetic_mixture_better_than_no_signal() -> None:
    observations = []
    truth = {"AA": 120, "72o": 80}
    cells = {
        ("AA", "RAISE"): 90,
        ("AA", "CALL"): 30,
        ("72o", "RAISE"): 10,
        ("72o", "CALL"): 70,
    }
    # Exactly half of every hand/action cell is revealed: missing-at-random
    # conditional on the observable action.  The other half remains truly latent.
    for (hand_class, signature), n in cells.items():
        observations.extend(obs(signature, hand_class) for _ in range(n // 2))
        observations.extend(obs(signature, None) for _ in range(n - n // 2))

    nominal = fit_latent_node(
        observations,
        ["AA", "72o"],
        {"AA": 1, "72o": 1},
        prior_strength=1.0,
        action_prior_strength=1.0,
        decision_signal_power=1.0,
    )
    no_signal = fit_latent_node(
        observations,
        ["AA", "72o"],
        {"AA": 1, "72o": 1},
        prior_strength=1.0,
        action_prior_strength=1.0,
        decision_signal_power=0.0,
    )
    nominal_error = abs(nominal["counts"]["AA"] - truth["AA"])
    no_signal_error = abs(no_signal["counts"]["AA"] - truth["AA"])
    assert nominal_error < 5.0, nominal
    assert nominal_error < no_signal_error


def test_sensitivity_is_exported_for_identifiable_hidden_decisions() -> None:
    observations = [obs("RAISE", "AA") for _ in range(40)]
    observations += [obs("CALL", "72o") for _ in range(40)]
    observations += [obs("RAISE", None) for _ in range(80)]
    observations += [obs("CALL", None) for _ in range(20)]
    ranges, sensitivity = build_latent_ranges(
        observations,
        backoff_min_observations=1,
        prior_strength=2.0,
        action_prior_strength=2.0,
    )
    global_node = ranges["levels"][-1]["data"]["ALL"]
    assert global_node["sensitivity_total_variation_from_nominal"]["0.0"] > 0
    assert global_node["sensitivity_total_variation_from_nominal"]["0.5"] > 0
    assert sensitivity["levels"][-1]["nodes"] == 1


def test_expected_counts_remain_legacy_probability_consumer_compatible() -> None:
    observations = [obs("RAISE", "AA") for _ in range(10)] + [obs("FOLD", None) for _ in range(10)]
    ranges, _ = build_latent_ranges(observations, backoff_min_observations=1)
    node = ranges["levels"][-1]["data"]["ALL"]
    assert isinstance(node["n"], int)
    assert isinstance(node["counts"], dict)
    assert all(isinstance(value, (int, float)) for value in node["counts"].values())
    assert math.isclose(sum(node["counts"].values()), node["n"], abs_tol=1e-5)


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"reveal-aware range tests: {len(tests)} passed")
