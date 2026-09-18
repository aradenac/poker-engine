#!/usr/bin/env python3
from __future__ import annotations

from tools.simulation.preflop_strategy_test_confirmation import (
    _holdout_generation,
    _validation_authorization,
    consume_holdout_ledger,
    select_test_confirmation,
)

ENVS = [
    "model-b-public-reference-nominal-v1",
    "model-b-public-reference-lower-aggression-v1",
    "model-b-public-reference-higher-aggression-v1",
]
CANDIDATE = {
    "candidate_id": "candidate-pfpc",
    "candidate_artifact_sha256": "a" * 64,
    "candidate_binding_sha256": "b" * 64,
    "candidate_binding_schema": "poker-hero-policy-context-binding/v1",
}


def validation_run():
    return {
        "schema": "poker-preflop-strategy-benchmark-run/v2",
        "contract_version": "2026-09-18.3",
        "phase": "VALIDATION",
        "test_data_read": False,
        "results_inspected": False,
        "identities": dict(CANDIDATE),
    }


def validation_selection():
    return {
        "schema": "poker-preflop-strategy-validation-selection/v2",
        "phase": "VALIDATION",
        "contract_version": "2026-09-18.3",
        "candidate_id": CANDIDATE["candidate_id"],
        "outcome": "FREEZE_FINALIST",
        "frozen_finalist": CANDIDATE["candidate_id"],
        "test_authorized": True,
        "test_used_for_selection": False,
        "test_consumed": False,
        "promotion_authorized": False,
        "candidate_exposure_validity": {"status": "PASS"},
    }


def ledger():
    return {
        "schema": "poker-test-holdout-ledger/v1",
        "population_id": "pokerstars_nlhe_100-200_zoom_play_6max_v1",
        "generations": [
            {
                "generation_id": "zoom_100-200_play_20260915_g1",
                "source_population_fingerprint_sha256": "c" * 64,
                "split": "TEST",
                "unique_hands": 2449,
                "status": "UNCONSUMED",
                "consumed_by_cycle": None,
                "consumed_by_frozen_finalist": None,
                "consumed_at_commit": None,
                "replacement_generation": None,
            }
        ],
    }


def test_validation_finalist_is_required_before_test():
    _validation_authorization(
        validation_run(),
        validation_selection(),
        candidate_identity=CANDIDATE,
        contract_version="2026-09-18.3",
    )
    broken = validation_selection()
    broken["outcome"] = "RETAIN_REFERENCE"
    broken["test_authorized"] = False
    try:
        _validation_authorization(
            validation_run(),
            broken,
            candidate_identity=CANDIDATE,
            contract_version="2026-09-18.3",
        )
    except ValueError as exc:
        assert "FREEZE_FINALIST" in str(exc)
    else:
        raise AssertionError("TEST must reject non-finalist VALIDATION outcome")


def test_candidate_identity_cannot_change_between_validation_and_test():
    altered = dict(CANDIDATE)
    altered["candidate_binding_sha256"] = "d" * 64
    try:
        _validation_authorization(
            validation_run(),
            validation_selection(),
            candidate_identity=altered,
            contract_version="2026-09-18.3",
        )
    except ValueError as exc:
        assert "candidate_binding_sha256" in str(exc)
    else:
        raise AssertionError("candidate drift must fail closed")


def test_holdout_must_be_unconsumed_and_match_population_fingerprint():
    row = _holdout_generation(
        ledger(),
        generation_id="zoom_100-200_play_20260915_g1",
        population_id="pokerstars_nlhe_100-200_zoom_play_6max_v1",
        population_fingerprint="c" * 64,
    )
    assert row["unique_hands"] == 2449

    consumed = ledger()
    consumed["generations"][0]["status"] = "CONSUMED"
    try:
        _holdout_generation(
            consumed,
            generation_id="zoom_100-200_play_20260915_g1",
            population_id="pokerstars_nlhe_100-200_zoom_play_6max_v1",
            population_fingerprint="c" * 64,
        )
    except ValueError as exc:
        assert "already consumed" in str(exc)
    else:
        raise AssertionError("consumed TEST generation must never run again")


def test_consumption_is_recorded_even_before_knowing_if_finalist_passes():
    out = consume_holdout_ledger(
        ledger(),
        generation_id="zoom_100-200_play_20260915_g1",
        cycle_id="test-cycle",
        finalist_id=CANDIDATE["candidate_id"],
        consumed_at_commit="e" * 40,
    )
    row = out["generations"][0]
    assert row["status"] == "CONSUMED"
    assert row["consumed_by_cycle"] == "test-cycle"
    assert row["consumed_by_frozen_finalist"] == CANDIDATE["candidate_id"]
    assert row["consumed_at_commit"] == "e" * 40


def run_manifest():
    return {
        "contract_version": "2026-09-18.3",
        "test_holdout_generation_id": "zoom_100-200_play_20260915_g1",
        "identities": {
            "candidate_id": CANDIDATE["candidate_id"],
            "model_b_environment_ids": list(ENVS),
        },
    }


def report(environment_id, *, supported=20, unsupported=80, passed=True):
    total = supported + unsupported
    return {
        "phase": "TEST",
        "candidate_id": CANDIDATE["candidate_id"],
        "environment": {"environment_id": environment_id},
        "gate": {"pass": passed},
        "paired": {
            "observed_delta_bb_per_100": 1.0 if passed else -1.0,
            "ci95_bb_per_100": [0.1, 1.9] if passed else [-1.9, -0.1],
        },
        "candidate_coverage": {
            "hero_preflop_decisions": total,
            "supported_decisions": supported,
            "out_of_support_decisions": unsupported,
        },
    }


def test_test_confirmation_promotes_only_when_every_environment_passes_with_exposure():
    result = select_test_confirmation(
        [report(env) for env in ENVS],
        run_manifest(),
    )
    assert result["outcome"] == "CONFIRM_FINALIST"
    assert result["promotion_authorized"] is True
    assert result["test_consumed"] is True
    assert result["retuning_authorized"] is False
    assert result["alternative_selection_authorized"] is False


def test_test_failure_retains_reference_but_still_consumes_holdout():
    reports = [
        report(ENVS[0], passed=True),
        report(ENVS[1], passed=False),
        report(ENVS[2], passed=True),
    ]
    result = select_test_confirmation(reports, run_manifest())
    assert result["outcome"] == "RETAIN_REFERENCE"
    assert result["promotion_authorized"] is False
    assert result["test_consumed"] is True
    assert result["performance_gate_interpretable"] is True


def test_zero_test_exposure_is_inconclusive_and_retains_reference():
    reports = [
        report(ENVS[0], supported=0, unsupported=100),
        report(ENVS[1]),
        report(ENVS[2]),
    ]
    result = select_test_confirmation(reports, run_manifest())
    assert result["outcome"] == "RETAIN_REFERENCE"
    assert result["promotion_authorized"] is False
    assert result["test_consumed"] is True
    assert result["performance_gate_interpretable"] is False
    assert result["candidate_exposure_validity"]["status"] == "INCONCLUSIVE_ZERO_EXPOSURE"


def main():
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for fn in tests:
        fn()
    print(f"PFPC TEST confirmation tests: {len(tests)} passed")


if __name__ == "__main__":
    main()
