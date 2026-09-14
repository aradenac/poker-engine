#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.strategy_candidate_gate import evaluate_test, evaluate_validation  # noqa: E402

CONTRACT = json.loads((ROOT / "training" / "strategy" / "STRATEGY_CANDIDATE_CONTRACT_20260913.json").read_text(encoding="utf-8"))


def report(cap3_ci=(-0.2, 0.5), cap3_mean=0.1, cap4_ci=(-0.1, 0.4), cap4_mean=0.2, base_hands=96) -> dict:
    return {
        "environment_variant": "independent_model_b_v3_response_conditioned_candidate",
        "sample": {"base_hands": base_hands, "scenarios": base_hands * 2},
        "paired_policy_comparisons_vs_current": {
            "cap_3": {
                "reference": "current",
                "paired_scenarios": base_hands * 2,
                "paired_base_hands": base_hands,
                "mean_delta_utility_bb": cap3_mean,
                "delta_ci95_cluster_bootstrap": list(cap3_ci),
                "win_tie_loss": {"win": 10, "tie": 80, "loss": 6},
            },
            "cap_4": {
                "reference": "current",
                "paired_scenarios": base_hands * 2,
                "paired_base_hands": base_hands,
                "mean_delta_utility_bb": cap4_mean,
                "delta_ci95_cluster_bootstrap": list(cap4_ci),
                "win_tie_loss": {"win": 11, "tie": 79, "loss": 6},
            },
        },
    }


def test_validation_retains_baseline_when_no_candidate_clears_ci() -> None:
    result = evaluate_validation(CONTRACT, report())
    assert result["outcome"] == "RETAIN_BASELINE", result
    assert result["frozen_finalist"] is None
    assert result["test_authorized"] is False
    assert result["test_used_for_selection"] is False


def test_validation_freezes_best_eligible_candidate_by_lower_bound() -> None:
    result = evaluate_validation(
        CONTRACT,
        report(cap3_ci=(0.05, 0.5), cap3_mean=0.2, cap4_ci=(0.02, 0.8), cap4_mean=0.4),
    )
    assert result["outcome"] == "FREEZE_FINALIST", result
    assert result["frozen_finalist"] == "cap_3", result
    assert result["test_authorized"] is True


def test_validation_contract_order_breaks_exact_tie() -> None:
    result = evaluate_validation(
        CONTRACT,
        report(cap3_ci=(0.1, 0.5), cap3_mean=0.3, cap4_ci=(0.1, 0.5), cap4_mean=0.3),
    )
    assert result["frozen_finalist"] == "cap_3", result


def test_validation_rejects_incomplete_sample_even_with_positive_ci() -> None:
    try:
        evaluate_validation(
            CONTRACT,
            report(cap3_ci=(0.2, 0.5), cap4_ci=(0.3, 0.6), base_hands=95),
        )
    except ValueError as exc:
        assert "requires 96" in str(exc)
    else:
        raise AssertionError("incomplete VALIDATION sample unexpectedly accepted")


def frozen_validation(finalist="cap_3") -> dict:
    value = evaluate_validation(
        CONTRACT,
        report(cap3_ci=(0.1, 0.5), cap3_mean=0.3, cap4_ci=(0.02, 0.8), cap4_mean=0.4),
    )
    if finalist != "cap_3":
        value = copy.deepcopy(value)
        value["frozen_finalist"] = finalist
    return value


def test_test_confirms_only_frozen_finalist() -> None:
    test_report = report(cap3_ci=(0.01, 0.4), cap3_mean=0.2, cap4_ci=(0.5, 1.0), cap4_mean=0.7)
    result = evaluate_test(CONTRACT, test_report, frozen_validation("cap_3"))
    assert result["outcome"] == "CONFIRM_FINALIST", result
    assert result["strategy_decision"] == "PROMOTE_CANDIDATE"
    assert result["frozen_finalist"] == "cap_3"
    assert result["test_may_select_alternative"] is False
    assert result["test_may_retune"] is False


def test_test_failure_retains_baseline_instead_of_switching_candidate() -> None:
    test_report = report(cap3_ci=(-0.05, 0.4), cap3_mean=0.1, cap4_ci=(0.5, 1.0), cap4_mean=0.7)
    result = evaluate_test(CONTRACT, test_report, frozen_validation("cap_3"))
    assert result["outcome"] == "RETAIN_BASELINE", result
    assert result["strategy_decision"] == "RETAIN_BASELINE"
    assert result["frozen_finalist"] == "cap_3"


def test_test_cannot_run_after_validation_retain() -> None:
    validation = evaluate_validation(CONTRACT, report())
    try:
        evaluate_test(CONTRACT, report(cap3_ci=(0.1, 0.5)), validation)
    except ValueError as exc:
        assert "without a frozen VALIDATION finalist" in str(exc)
    else:
        raise AssertionError("TEST unexpectedly ran without a frozen finalist")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"strategy candidate gate tests: {len(tests)} passed")
