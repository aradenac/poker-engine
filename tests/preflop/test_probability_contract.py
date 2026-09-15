#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop.context_contract import build_context  # noqa: E402
from tools.preflop.probability_contract import (  # noqa: E402
    action_probability,
    incumbent_v5_passthrough,
    strict_probability_response,
)


def fixture_context():
    return build_context(
        table_size=6,
        actor_position="CO",
        live_positions=["LJ", "HJ", "CO", "BTN", "SB", "BB"],
        history=[{"position": "LJ", "action": "RAISE"}, {"position": "HJ", "action": "CALL"}],
        raise_level=1,
        contribution_bb_by_position={"LJ": 2.5, "HJ": 2.5, "CO": 0, "BTN": 0, "SB": 0.5, "BB": 1},
        stack_bb_by_position={p: 100 for p in ["LJ", "HJ", "CO", "BTN", "SB", "BB"]},
        pot_before_bb=7,
        current_price_bb=2.5,
        min_raise_to_bb=4,
    )


def test_incumbent_preserves_every_probability_without_renormalization():
    ctx = fixture_context()
    raw = {"FOLD": .41, "CALL": .37, "RAISE": .18, "JAM": .04, "CHECK": .000123}
    response = incumbent_v5_passthrough(
        context=ctx,
        raw_probabilities=raw,
        hand_class="AQs",
        source="fixture",
        backoff_level="closest",
        confidence="medium",
        support=123,
    )
    assert response["behavior_mode"] == "incumbent_v5_passthrough"
    assert response["probabilities"] == raw
    assert response["probability_sum"] == sum(raw.values())
    assert response["positive_illegal_model_actions"] == ["CHECK"]
    assert response["action_set_compatible"] is False
    assert action_probability(response, "CALL") == raw["CALL"]
    assert response["incumbent_compatibility"]["probabilities_preserved_without_renormalization"] is True


def test_strict_mode_renormalizes_only_legal_actions():
    ctx = fixture_context()
    response = strict_probability_response(
        context=ctx,
        raw_probabilities={"FOLD": 2, "CALL": 3, "RAISE": 4, "JAM": 1, "CHECK": 999},
        source="fixture",
        backoff_level="exact",
        confidence="high",
        support=456,
    )
    assert response["behavior_mode"] == "strict_legal_normalized"
    assert set(response["probabilities"]) == set(ctx["legal_actions"])
    assert abs(sum(response["probabilities"].values()) - 1) < 1e-12
    assert "CHECK" not in response["probabilities"]


def test_js_incumbent_passthrough_matches_python_semantics():
    js = json.loads(subprocess.check_output(
        ["node", str(ROOT / "tests/preflop/dump_probability_contract.js")],
        cwd=ROOT,
        text=True,
    ))
    py = incumbent_v5_passthrough(
        context=fixture_context(),
        raw_probabilities={"FOLD": .41, "CALL": .37, "RAISE": .18, "JAM": .04, "CHECK": .000123},
        hand_class="AQs",
        source="fixture",
        backoff_level="closest",
        confidence="medium",
        support=123,
    )
    for key in (
        "schema", "behavior_mode", "hand_class", "legal_actions", "model_actions",
        "probabilities", "action_set_compatible",
        "positive_illegal_model_actions", "missing_legal_model_actions", "source",
        "backoff_level", "confidence", "support", "incumbent_compatibility",
    ):
        assert js[key] == py[key], (key, js[key], py[key])
    assert math.isclose(js["probability_sum"], py["probability_sum"], rel_tol=0, abs_tol=1e-15)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"preflop probability contract tests: {len(tests)} passed")
