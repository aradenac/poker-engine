#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.game_core import NoLimitHoldemState  # noqa: E402
from tools.simulation.model_b_sensitivity import (  # noqa: E402
    ModelBSensitivityPolicy,
    load_sensitivity_set,
)

CONFIG = ROOT / "training/full_hand/MODEL_B_SENSITIVITY_ENVIRONMENTS_20260917.json"
BASE_SHA = "fc54f874220fdd8ec42ad69c3eff4d3235296f15f7e22ca4a5bb1837b97636ca"


class FakeBase:
    population_id = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
    artifact_sha256 = BASE_SHA

    def identity(self):
        return {"schema": "fixture", "artifact_sha256": self.artifact_sha256}

    def action_probabilities(self, state, **context):
        del state, context
        return {
            "probabilities": {"FOLD": 0.25, "CALL": 0.50, "RAISE": 0.25},
            "features": {"fixture": True},
            "selection": {"support": 100},
            "legal_actions": ["FOLD", "CALL", "RAISE"],
        }

    def sizing_candidates(self, state, **context):
        actor = context["actor"]
        view = state.legal_view(actor)
        return {
            "candidates": [
                {
                    "incremental_cost_over_pot": 1.0,
                    "target_total_bb": 3.0,
                    "weight": 2.0,
                }
            ],
            "features": {"fixture": True},
            "selection": {"support": 50},
            "source": "EMPIRICAL",
            "legal_bounds": {
                "min_raise_to_bb": view["min_raise_to_bb"],
                "max_raise_to_bb": view["max_raise_to_bb"],
            },
        }


def policy(environment_id: str, *, base=None):
    doc = load_sensitivity_set(CONFIG)
    return ModelBSensitivityPolicy(
        base or FakeBase(),
        sensitivity_document=doc,
        sensitivity_sha256="a" * 64,
        environment_id=environment_id,
    )


def preflop_state():
    return NoLimitHoldemState(
        seats=["BTN", "SB", "BB"],
        button="BTN",
        stacks_bb={"BTN": 100, "SB": 100, "BB": 100},
    )


def context(state):
    actor = state.next_actor
    assert actor == "BTN"
    return {
        "actor": actor,
        "hole_cards": ("As", "Kd"),
        "profile": 0,
        "relative_position": "BTN",
        "pot_type": "UNOPENED",
        "preflop_role": "NO_PRIOR_ACTION",
    }


def test_config_is_frozen_and_symmetric() -> None:
    doc = load_sensitivity_set(CONFIG)
    rows = {row["role"]: row for row in doc["environments"]}
    assert set(rows) == {"nominal", "lower_aggression", "higher_aggression"}
    assert abs(rows["lower_aggression"]["raise_odds_multiplier"] * rows["higher_aggression"]["raise_odds_multiplier"] - 1.0) < 1e-12
    assert abs(rows["lower_aggression"]["raise_sizing_multiplier"] * rows["higher_aggression"]["raise_sizing_multiplier"] - 1.0) < 1e-12


def test_nominal_preserves_action_probabilities_and_sizing() -> None:
    state = preflop_state()
    ctx = context(state)
    p = policy("model-b-public-reference-nominal-v1")
    info = p.action_probabilities(state, **ctx)
    assert info["probabilities"] == {"FOLD": 0.25, "CALL": 0.50, "RAISE": 0.25}
    sizing = p.sizing_candidates(state, **ctx)
    assert len(sizing["candidates"]) == 1
    assert sizing["candidates"][0]["target_total_bb"] == 3.0


def test_aggression_variants_move_raise_mass_in_opposite_directions() -> None:
    state = preflop_state()
    ctx = context(state)
    low = policy("model-b-public-reference-lower-aggression-v1").action_probabilities(state, **ctx)["probabilities"]
    nominal = policy("model-b-public-reference-nominal-v1").action_probabilities(state, **ctx)["probabilities"]
    high = policy("model-b-public-reference-higher-aggression-v1").action_probabilities(state, **ctx)["probabilities"]
    assert low["RAISE"] < nominal["RAISE"] < high["RAISE"]
    assert abs(sum(low.values()) - 1.0) < 1e-12
    assert abs(sum(high.values()) - 1.0) < 1e-12


def test_sizing_variants_remain_inside_shared_legal_bounds() -> None:
    state = preflop_state()
    ctx = context(state)
    low = policy("model-b-public-reference-lower-aggression-v1").sizing_candidates(state, **ctx)["candidates"][0]["target_total_bb"]
    nominal = policy("model-b-public-reference-nominal-v1").sizing_candidates(state, **ctx)["candidates"][0]["target_total_bb"]
    high = policy("model-b-public-reference-higher-aggression-v1").sizing_candidates(state, **ctx)["candidates"][0]["target_total_bb"]
    view = state.legal_view("BTN")
    assert float(view["min_raise_to_bb"]) <= low <= nominal <= high <= float(view["max_raise_to_bb"])


def test_base_artifact_identity_mismatch_fails_closed() -> None:
    bad = FakeBase()
    bad.artifact_sha256 = "0" * 64
    try:
        policy("model-b-public-reference-nominal-v1", base=bad)
    except ValueError as exc:
        assert "does not target" in str(exc)
    else:
        raise AssertionError("wrong retained Model B artifact must fail closed")


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"Model B sensitivity tests: {len(tests)} passed")


if __name__ == "__main__":
    main()
