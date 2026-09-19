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

from tools.preflop.model_a_sizing_likelihood import (  # noqa: E402
    BACKOFF_POLICY,
    CANDIDATE_STATUS,
    SizingLikelihoodError,
    canonical_candidate_sha256,
    make_synthetic_candidate,
    public_sizing_context,
    resolve_likelihood,
    support_context_key,
)

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
from tools.training.fit_model_a_preflop_sizing import (  # noqa: E402
    build_candidate as build_issue339_candidate,
    evaluate_validation as evaluate_issue339_validation,
    load_protocol as load_issue339_protocol,
    load_support_report as load_issue339_support_report,
)
from tools.repro_preflop_model_parity import (  # noqa: E402
    REPORT_PATH as MODEL_PARITY_REPORT_PATH,
    build_parity_report,
    verify_persisted_report,
)

FIXTURE = json.loads((ROOT / "tests/fixtures/preflop_contract_cases.json").read_text(encoding="utf-8"))
SIZING_FIXTURE = json.loads((ROOT / "tests/fixtures/model_a_preflop_sizing_cases.json").read_text(encoding="utf-8"))


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



def test_public_price_projection_fields_are_present_and_consistent():
    for case in SIZING_FIXTURE["contexts"]:
        ctx = build_context(**case["input"])
        public = public_sizing_context(ctx)
        for key, expected in case["expected"].items():
            assert public[key] == expected, (case["name"], key, public[key], expected)
        assert public["target_total_bb"] == ctx["current_price_bb"]
        assert public["limper_count"] == len(set(ctx["limper_positions"]))
        assert public["caller_count"] == len(set(ctx["caller_positions"]))


def test_sizing_candidate_distinguishes_4bb_and_6bb_exactly():
    four, six = SIZING_FIXTURE["contexts"]
    four_ctx = build_context(**four["input"])
    six_ctx = build_context(**six["input"])
    rows = [
        {
            "node_id": "KTs@4",
            "context": four_ctx,
            "hand_class": "KTs",
            "probabilities": four["probabilities"],
            "support": 20,
        },
        {
            "node_id": "marginal@4",
            "context": four_ctx,
            "hand_class": None,
            "probabilities": four["marginal_probabilities"],
            "support": 100,
        },
        {
            "node_id": "KTs@6",
            "context": six_ctx,
            "hand_class": "KTs",
            "probabilities": six["probabilities"],
            "support": 18,
        },
    ]
    candidate = make_synthetic_candidate(
        population_id=SIZING_FIXTURE["population_id"],
        rows=rows,
    )
    r4 = resolve_likelihood(candidate=candidate, context=four_ctx, hand_class="KTs")
    r6 = resolve_likelihood(candidate=candidate, context=six_ctx, hand_class="KTs")
    assert r4["status"] == r6["status"] == "RESOLVED"
    assert r4["backoff_level"] == r6["backoff_level"] == BACKOFF_POLICY[0]
    assert r4["sizing_context_key"] != r6["sizing_context_key"]
    assert r4["probabilities"] != r6["probabilities"]
    assert r4["public_context"]["target_total_bb"] == 4
    assert r6["public_context"]["target_total_bb"] == 6


def test_sizing_backoff_is_hand_to_marginal_at_same_exact_price_only():
    four, six = SIZING_FIXTURE["contexts"]
    four_ctx = build_context(**four["input"])
    six_ctx = build_context(**six["input"])
    candidate = make_synthetic_candidate(
        population_id=SIZING_FIXTURE["population_id"],
        rows=[
            {
                "node_id": "marginal@4",
                "context": four_ctx,
                "hand_class": None,
                "probabilities": four["marginal_probabilities"],
                "support": 100,
            },
            {
                "node_id": "KTs@6",
                "context": six_ctx,
                "hand_class": "KTs",
                "probabilities": six["probabilities"],
                "support": 18,
            },
        ],
    )
    result = resolve_likelihood(candidate=candidate, context=four_ctx, hand_class="Q9s")
    assert result["status"] == "RESOLVED"
    assert result["backoff_level"] == BACKOFF_POLICY[1]
    assert result["node_id"] == "marginal@4"


def test_no_nearest_price_fallback_for_5bb_between_4bb_and_6bb():
    four, six = SIZING_FIXTURE["contexts"]
    four_ctx = build_context(**four["input"])
    six_ctx = build_context(**six["input"])
    five_input = json.loads(json.dumps(four["input"]))
    five_input["contribution_bb_by_position"]["SB"] = 5
    five_input["current_price_bb"] = 5
    five_input["pot_before_bb"] = 8
    five_input["min_raise_to_bb"] = 9
    five_ctx = build_context(**five_input)
    candidate = make_synthetic_candidate(
        population_id=SIZING_FIXTURE["population_id"],
        rows=[
            {
                "node_id": "KTs@4",
                "context": four_ctx,
                "hand_class": "KTs",
                "probabilities": four["probabilities"],
                "support": 20,
            },
            {
                "node_id": "KTs@6",
                "context": six_ctx,
                "hand_class": "KTs",
                "probabilities": six["probabilities"],
                "support": 18,
            },
        ],
    )
    result = resolve_likelihood(candidate=candidate, context=five_ctx, hand_class="KTs")
    assert result["status"] == "UNRESOLVED"
    assert result["backoff_level"] == "UNRESOLVED"
    assert result["reason_code"] == "EXACT_PRICE_UNSUPPORTED_NO_NEAREST_PRICE"
    assert result["probabilities"] is None


def test_candidate_identity_is_explicit_non_active_and_deterministic():
    four = SIZING_FIXTURE["contexts"][0]
    ctx = build_context(**four["input"])
    candidate = make_synthetic_candidate(
        population_id=SIZING_FIXTURE["population_id"],
        rows=[
            {
                "node_id": "KTs@4",
                "context": ctx,
                "hand_class": "KTs",
                "probabilities": four["probabilities"],
                "support": 20,
            }
        ],
    )
    assert candidate["identity"]["status"] == CANDIDATE_STATUS
    assert candidate["identity"]["model_family"] == "MODEL_A_PREFLOP"
    assert candidate["identity"]["active_model_replaced"] is False
    assert candidate["nearest_price_fallback"] is False
    assert canonical_candidate_sha256(candidate) == canonical_candidate_sha256(candidate)


def test_sizing_projection_is_public_only_and_fail_closed():
    four = SIZING_FIXTURE["contexts"][0]
    ctx = build_context(**four["input"])
    assert public_sizing_context(ctx)["information_boundary"]["public_only"] is True
    contaminated = dict(ctx)
    contaminated["hole_cards"] = ["Ks", "Ts"]
    try:
        public_sizing_context(contaminated)
    except SizingLikelihoodError as exc:
        assert "private" in str(exc).lower() or "card" in str(exc).lower()
    else:
        raise AssertionError("private cards must be rejected by sizing projection")

    incomplete = dict(ctx)
    incomplete.pop("current_price_bb")
    try:
        public_sizing_context(incomplete)
    except SizingLikelihoodError as exc:
        assert "missing public sizing fields" in str(exc)
    else:
        raise AssertionError("missing price fields must fail closed")


def test_v5_projection_ignores_new_sizing_candidate_fields():
    base = build_context(**SIZING_FIXTURE["contexts"][0]["input"])
    changed = dict(base)
    changed["target_total_bb"] = 999
    changed["price_to_pot_ratio"] = 999
    changed["pot_odds"] = 0.999
    changed["limper_count"] = 99
    changed["caller_count"] = 99
    assert v5_runtime_signature(base) == v5_runtime_signature(changed)



def test_iso_sizing_final_posterior_binding_contract():
    subprocess.run(
        ["node", str(ROOT / "tests/preflop/test_iso_sizing_diagnostics.js")],
        cwd=ROOT,
        check=True,
    )


def test_sizing_likelihood_schema_locks_candidate_only_and_no_nearest_price():
    schema = json.loads(
        (ROOT / "contracts/training/model-a-preflop-sizing-likelihood.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema["properties"]["schema"]["const"] == "poker-model-a-preflop-sizing-likelihood/v1"
    identity = schema["properties"]["identity"]["properties"]
    assert identity["model_family"]["const"] == "MODEL_A_PREFLOP"
    assert identity["status"]["const"] == "CANDIDATE_ONLY_NOT_ACTIVE"
    assert identity["active_model_replaced"]["const"] is False
    assert schema["properties"]["nearest_price_fallback"]["const"] is False
    assert schema["properties"]["backoff_policy"]["const"] == list(BACKOFF_POLICY)


def test_issue339_support_key_matches_319_dimensions_not_nearest_numeric_state():
    four = build_context(**SIZING_FIXTURE["contexts"][0]["input"])
    same_price = dict(four)
    same_price["pot_before_bb"] = float(four["pot_before_bb"]) + 20.0
    same_price["effective_stack_bb"] = float(four["effective_stack_bb"]) + 50.0
    assert support_context_key(four) == support_context_key(same_price)

    six = build_context(**SIZING_FIXTURE["contexts"][1]["input"])
    assert support_context_key(four) != support_context_key(six)


def test_issue339_train_fit_is_hash_bound_and_frozen_validation_executes_without_test():
    protocol = load_issue339_protocol()
    _, report = load_issue339_support_report()
    candidate, fit = build_issue339_candidate(protocol, report)
    assert candidate["identity"]["fit_scope"] == "TRAIN_EMPIRICAL_FIT"
    assert candidate["identity"]["data_scope"] == "CERTIFIED_TRAIN_ONLY"
    assert candidate["identity"]["source_report_hash"] == "5db39f3e461431f2c3cba9417cdf96f5b53437304b166e1886b3f2d9764c7f99"
    assert fit["nodes"]["marginal_exact_price"] == 282
    assert fit["nodes"]["identifiable_revealed_hand_class"] > 0
    assert fit["test_consumed"] is False
    support = {int(row["target_total_bb"]): int(row["observations"]) for row in fit["kts_sb_two_limpers_exact_price_support"]}
    assert support == {4: 54, 5: 161, 6: 43}

    validation = evaluate_issue339_validation(protocol, candidate, fit)
    assert validation["selection_split"] == "VALIDATION"
    assert validation["test_consumed"] is False
    assert validation["test_authorized"] is False
    assert validation["production_effect"] == "NONE"
    assert validation["active_model_replaced"] is False
    assert validation["model_b_consumed"] is False
    assert validation["hero_ev_consumed"] is False
    assert validation["ui_modified"] is False
    print("ISSUE339_RESULT=" + json.dumps({"fit": fit, "validation": validation}, sort_keys=True, separators=(",", ":")))


def test_canonical_321_model_a_b_public_context_parity():
    report = build_parity_report(ROOT)
    assert report["status"] == "PASS", report["violations"]
    assert report["source_fixture"]["scenario_id"] == "kts_sb_two_limp_iso4_three_calls_v1"
    assert report["source_fixture"]["used_directly"] is True
    assert report["source_fixture"]["new_kts_fixture_created"] is False
    assert verify_persisted_report(ROOT) == []

    persisted = json.loads(MODEL_PARITY_REPORT_PATH.read_text(encoding="utf-8"))
    assert persisted == report

    by_actor = {row["actor"]: row for row in report["decisions"]}
    expected = {
        "BB": (7.0, 0.428571429, "P25_50", "VS_ISO", 0),
        "CO": (10.0, 0.3, "P25_50", "LIMPER_VS_ISO_CALLERS", 1),
        "BTN": (13.0, 0.230769231, "P00_25", "LIMPER_VS_ISO_CALLERS", 2),
    }
    for actor, (pot, ratio, bucket, family, callers) in expected.items():
        row = by_actor[actor]
        assert row["status"] == "PASS"
        assert all(row["checks"].values()), (actor, row["checks"])
        assert row["canonical_public"]["target_total_bb"] == 4.0
        assert row["canonical_public"]["to_call_bb"] == 3.0
        assert row["canonical_public"]["pot_before_bb"] == pot
        assert row["canonical_public"]["price_to_pot"] == ratio
        assert row["model_a"]["price_to_pot_ratio"] == ratio
        assert row["model_a"]["effective_stack_bb"] == 100.0
        assert row["model_a"]["limper_count"] == 2
        assert row["model_a"]["caller_count"] == callers
        assert row["model_a"]["family"] == family
        assert row["model_b_input"]["facing_price_to_pot"] == ratio
        assert row["model_b"]["price_bucket"] == bucket
        assert row["model_b"]["raise_size_bucket"] == "S3_4P5"
        assert row["model_b"]["effective_stack_bucket"] == "E80_150"
        assert row["model_b"]["limper_count_bucket"] == "L2"

    legacy = report["legacy_scaffold_fixture_audit"]
    assert legacy["status"] == "DOCUMENTED_NOT_PARITY_SOURCE"
    assert legacy["used_to_build_parity_rows"] is False
    assert legacy["model_a_scaffold_fixture"]["legacy_limper_positions"] == ["LJ", "HJ"]
    assert legacy["model_a_scaffold_fixture"]["canonical_limper_positions"] == ["CO", "BTN"]
    assert legacy["model_b_scaffold_fixture"]["legacy_4bb_facing_price_to_pot"] == {
        "BB": 0.55,
        "CO": 0.55,
        "BTN": 0.55,
    }


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"preflop context contract tests: {len(tests)} passed")
