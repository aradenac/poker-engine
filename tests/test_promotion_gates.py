from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.evaluate_promotion_gates import evaluate

CONTRACT = json.loads((ROOT / "training" / "PROMOTION_GATE_CONTRACT.json").read_text(encoding="utf-8"))


def passing_evidence() -> dict:
    return {
        "schema": "poker-promotion-evidence/v1",
        "cycle": "synthetic-pass",
        "data_integrity": {
            "source_verified": True,
            "exact_deduplication": True,
            "split_disjoint": True,
            "fingerprints_recorded": True,
            "parse_errors": 0,
        },
        "model_a": {
            "preflop": {
                "selection_split": "VALIDATION",
                "test_used_for_selection": False,
                "comparison_complete": True,
                "candidate_persisted": True,
                "decision": "RETAIN_BASELINE",
                "validation_delta_candidate_minus_baseline": 0.01,
                "reason": "candidate was worse; baseline retained",
            },
            "postflop": {
                "selection_split": "VALIDATION",
                "test_used_for_selection": False,
                "comparison_complete": True,
                "candidate_persisted": True,
                "decision": "RETAIN_BASELINE",
                "validation_delta_candidate_minus_baseline": 0.02,
                "reason": "candidate was worse; baseline retained",
            },
        },
        "model_b": {
            "selection_split": "VALIDATION",
            "test_used_for_selection": False,
            "comparison_complete": True,
            "candidate_persisted": True,
            "independent_from_model_a": True,
            "decision": "RETAIN_INCUMBENT",
            "reason": "candidate failed paired non-regression; incumbent retained",
            "validation": {
                "action_log_loss_delta_candidate_minus_incumbent_ci95": [-0.01, 0.01],
                "range_log_loss_delta_candidate_minus_incumbent_ci95": [-0.02, 0.02],
                "action_ece": 0.03,
                "known_player_coverage": 0.97,
                "weighted_profile_stability": 0.60,
                "state_anomaly_rate": 0.0,
            },
        },
        "strategy": {
            "baseline_persisted": True,
            "candidate_persisted": True,
            "selection_split": "VALIDATION",
            "test_used_for_tuning": False,
            "change_scope": ["heads_up_postflop"],
            "unsupported_contexts_covered": True,
            "environment_valid": True,
            "validation_delta_candidate_minus_baseline_ci95": [0.0, 0.01],
            "test_delta_candidate_minus_baseline_ci95": [0.0, 0.01],
            "decision": "RETAIN_BASELINE",
            "reason": "candidate retained no advantage over the baseline",
        },
        "regressions": {
            "pathological_engine_suite_pass": True,
            "trainer_contract_suite_pass": True,
            "sequential_arena_contract_suite_pass": True,
        },
        "provenance": {
            "code_commit": "deadbeef",
            "dataset_fingerprints": ["data:abc"],
            "model_hashes": ["model:def"],
        },
        "release_identity": {
            "engine_release_artifact": "engine.html",
            "engine_release_sha256": "a" * 64,
            "assembled_site_entrypoint": "site/index.html",
            "assembled_site_git_blob_sha": "b" * 40,
            "assets_tree_git_sha": "c" * 40,
            "assembled_from_commit": "d" * 40,
        },
        "registry_transition": {"unchanged_before_explicit_promotion": True},
        "deployment": {"site_release_attempted": False},
    }


def by_name(report: dict, name: str) -> dict:
    return next(c for c in report["components"] if c["name"] == name)


def test_rejected_candidates_can_complete_a_valid_cycle() -> None:
    report = evaluate(passing_evidence(), CONTRACT)
    assert report["status"] == "PASS", report
    assert by_name(report, "model_a_preflop")["status"] == "PASS"
    assert by_name(report, "model_a_preflop")["promotion_allowed"] is False
    assert by_name(report, "model_b")["status"] == "PASS"
    assert report["promotion_ready"] is True


def test_model_a_promotion_requires_non_regression_and_paired_ci() -> None:
    evidence = passing_evidence()
    evidence["model_a"]["preflop"].update(
        {
            "decision": "PROMOTE_CANDIDATE",
            "validation_delta_candidate_minus_baseline": 0.001,
            "paired_validation_delta_ci95": [-0.01, 0.02],
        }
    )
    report = evaluate(evidence, CONTRACT)
    gate = by_name(report, "model_a_preflop")
    assert gate["status"] == "FAIL", gate
    assert gate["promotion_allowed"] is False


def test_missing_evidence_is_blocked() -> None:
    evidence = passing_evidence()
    del evidence["model_b"]["comparison_complete"]
    report = evaluate(evidence, CONTRACT)
    assert by_name(report, "model_b")["status"] == "BLOCKED"
    assert report["promotion_ready"] is False


def test_strategy_promotion_requires_validation_and_test_ci() -> None:
    evidence = passing_evidence()
    evidence["strategy"].update(
        {
            "decision": "PROMOTE_CANDIDATE",
            "validation_delta_candidate_minus_baseline_ci95": [-0.01, 0.01],
            "test_delta_candidate_minus_baseline_ci95": [0.0, 0.01],
        }
    )
    report = evaluate(evidence, CONTRACT)
    gate = by_name(report, "strategy")
    assert gate["status"] == "FAIL", gate
    assert gate["promotion_allowed"] is False


def test_test_split_cannot_select_model_b() -> None:
    evidence = passing_evidence()
    evidence["model_b"]["selection_split"] = "TEST"
    report = evaluate(evidence, CONTRACT)
    assert by_name(report, "model_b")["status"] == "FAIL"


def test_unsupported_scope_cannot_be_authorized_by_hu_arena() -> None:
    evidence = passing_evidence()
    evidence["strategy"]["change_scope"] = ["heads_up_postflop", "multiway"]
    evidence["strategy"]["unsupported_contexts_covered"] = False
    report = evaluate(evidence, CONTRACT)
    gate = by_name(report, "strategy")
    assert gate["status"] == "FAIL", gate


def test_deployment_failure_is_reported_separately_from_pre_promotion_gate() -> None:
    evidence = passing_evidence()
    evidence["deployment"] = {
        "site_release_attempted": True,
        "production_build_success": True,
        "public_url_verified": False,
        "deployed_commit_verified": True,
        "application_smoke_verified": False,
    }
    report = evaluate(evidence, CONTRACT)
    assert report["status"] == "PASS", report
    assert report["deployment_verification"]["status"] == "FAIL"
    assert report["deployment_verification"]["post_promotion"] is True


def test_current_cycle_snapshot_cannot_be_promoted_yet() -> None:
    evidence = json.loads((ROOT / "training" / "gates" / "20260912_evidence.json").read_text(encoding="utf-8"))
    report = evaluate(evidence, CONTRACT)
    assert report["status"] in {"FAIL", "BLOCKED"}, report
    assert report["promotion_ready"] is False
    assert report["rules"]["registry_update_allowed"] is False
    # Model A is now a valid completed RETAIN_BASELINE decision: its rejected
    # candidates are reproducible and persisted by immutable input + semantic digest.
    assert by_name(report, "model_a_preflop")["status"] == "PASS"
    assert by_name(report, "model_a_postflop")["status"] == "PASS"
    assert by_name(report, "model_b")["status"] == "BLOCKED"
    assert by_name(report, "strategy")["status"] == "BLOCKED"


if __name__ == "__main__":
    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"promotion gate tests: {len(tests)} passed")
