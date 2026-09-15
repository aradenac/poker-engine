#!/usr/bin/env python3
from __future__ import annotations

import inspect
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop.context_contract import (  # noqa: E402
    PROBABILITY_SCHEMA,
    SCHEMA,
    build_context,
    history_token,
    normalize_action_probabilities,
    normalize_history,
    v5_runtime_signature,
)
from tools.training.audit_preflop_key_runtime_parity import runtime_signature  # noqa: E402

FIXTURE = json.loads((ROOT / "tests/fixtures/preflop_contract_cases.json").read_text(encoding="utf-8"))


def assert_expected(ctx, expected):
    for key, value in expected.items():
        if key == "history_token":
            assert history_token(ctx["history"]) == value, (key, history_token(ctx["history"]), value)
        else:
            assert ctx[key] == value, (key, ctx.get(key), value)


def test_python_fixtures():
    for case in FIXTURE["cases"]:
        ctx = build_context(**case["input"])
        assert ctx["schema"] == SCHEMA
        assert ctx["state_timing"] == "BEFORE_ACTION"
        assert ctx["context_id"].startswith("PFC_")
        assert_expected(ctx, case["expected"])
        serialized = json.dumps(ctx).lower()
        for forbidden in ("cards", "hole", "board", "showdown", "future"):
            assert forbidden not in serialized, (case["name"], forbidden)


def test_js_python_fixture_parity():
    raw = subprocess.check_output(
        ["node", str(ROOT / "tests/preflop/dump_context_contract.js")],
        cwd=ROOT,
        text=True,
    )
    js = json.loads(raw)
    ignore = {"context_id"}  # browser uses a synchronous short display hash
    for case in FIXTURE["cases"]:
        py = build_context(**case["input"])
        j = js[case["name"]]
        for key in sorted(set(py) | set(j)):
            if key in ignore:
                continue
            assert py.get(key) == j.get(key), (case["name"], key, py.get(key), j.get(key))


def test_legacy_history_separator_is_representation_only():
    comma = normalize_history("LJ:LIMP,HJ:LIMP,CO:RAISE")
    native = normalize_history("LJ:LIMP>HJ:LIMP>CO:RAISE")
    assert comma == native
    assert history_token(comma) == "LJ:LIMP>HJ:LIMP>CO:RAISE"


def test_v5_projection_matches_issue_88_runtime_signature():
    for case in FIXTURE["cases"]:
        ctx = build_context(**case["input"])
        # The #88 audit is the executable specification of incumbent v5/v83
        # exact matching.  The new richer context must project to it exactly.
        assert v5_runtime_signature(ctx) == runtime_signature(ctx)


def test_v5_projection_deliberately_ignores_free_check_and_new_fields():
    base = build_context(**FIXTURE["cases"][0]["input"])
    changed = dict(base)
    changed["free_check"] = not base["free_check"]
    changed["effective_stack_bb"] = base["effective_stack_bb"] + 25
    changed["remaining_to_act_positions"] = []
    changed["min_raise_to_bb"] = 99
    assert v5_runtime_signature(base) == v5_runtime_signature(changed)


def test_probability_contract_filters_illegal_actions_and_normalizes():
    ctx = build_context(**FIXTURE["cases"][5]["input"])
    result = normalize_action_probabilities(
        context=ctx,
        raw_probabilities={"FOLD": 2, "CALL": 3, "RAISE": 4, "JAM": 1, "CHECK": 999},
        hand_class="AQs",
        sizing=None,
        source="fixture",
        backoff_level="exact",
        confidence="high",
        support=250,
    )
    assert result["schema"] == PROBABILITY_SCHEMA
    assert result["legal_actions"] == ["FOLD", "CALL", "RAISE", "JAM"]
    assert "CHECK" not in result["probabilities"]
    assert math.isclose(sum(result["probabilities"].values()), 1.0)
    assert result["sizing"] is None  # do not invent a sizing distribution
    assert result["support"] == 250


def test_probability_contract_rejects_zero_legal_mass():
    ctx = build_context(**FIXTURE["cases"][0]["input"])
    try:
        normalize_action_probabilities(
            context=ctx,
            raw_probabilities={"CHECK": 1},
            source="fixture",
            backoff_level="none",
            confidence="none",
            support=0,
        )
    except ValueError as exc:
        assert "zero" in str(exc).lower()
    else:
        raise AssertionError("zero legal probability mass must be rejected")


def test_context_builder_has_no_card_or_future_inputs():
    params = set(inspect.signature(build_context).parameters)
    for forbidden in ("cards", "hole_cards", "board", "showdown", "future_actions", "known_cards"):
        assert forbidden not in params


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"preflop context contract tests: {len(tests)} passed")
