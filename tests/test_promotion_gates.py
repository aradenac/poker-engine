#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
from pathlib import Path

from tools.evaluate_promotion_gates import evaluate

ROOT = Path(__file__).resolve().parents[1]
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
                "validation_delta_candidate_minus_baseline": 0.001,
                "reason": "candidate loses on validation",
            },
            "postflop": {
                "selection_split": "VALIDATION",
                "test_used_for_selection": False,
                "comparison_complete": True,
                "candidate_persisted": True,
                "decision": "RETAIN_BASELINE",
                "validation_delta_candidate_minus_baseline": 0.002,
                "reason": "candidate loses on validation",
            },
        },
        "model_b": {
            "selection_split": "VALIDATION",
            "test_used_for_selection": False,
            "comparison_complete": True,
            "candidate_persisted": True,
            "independent_from_model_a": True,
            "decision": "RETAIN_BASELINE",
            "reason": "paired comparison retains incumbent",
        },
        "strategy": {
            "baseline_persisted": True,
            "comparison_complete": True,
            "candidate_persisted": True,
            "selection_split": "VALIDATION",
            "test_used_for_tuning": False,
            "environment_validity_pass": True,
            "scenario_manifest_persisted": True,
            "decision": "RETAIN_BASELINE",
            "change_scope": ["heads_up_postflop"],
            "unsupported_contexts_covered": False,
            "reason": "paired benchmark retains v83",
        },
        "regressions": {
            "pathological_engine_suite_pass": True,
            "trainer_contract_suite_pass": True,
            "sequential_arena_contract_suite_pass": True,
        },
        "provenance": {
            "code_commit": "abc123",
            "dataset_fingerprints": ["dataset:sha256"],
            "model_hashes": ["model:sha256"],
            "seed_or_scenario_manifest": "training/evaluations/scenarios.json",
        },
        "release_identity": {
            "engine_release_artifact": "user/releases/v83.html",
            "engine_release_sha256": "engine-sha256",
            "assembled_site_entrypoint": "site/index.html",
            "assembled_site_git_blob_sha": "site-blob",
            "assets_tree_git_sha": "assets-tree",
            "assembled_from_commit": "commit-sha",
        },
        "registry_transition": {"unchanged_before_explicit_promotion": True},
        "deployment": {"site_release_attempted": False},
    }


def by_name(report: dict, name: str) -> dict:
    return next(x for x in report["components"] if x["name"] == name)


def test_rejected_candidates_can_complete_a_valid_cycle() -> None:
    report = evaluate(passing_evidence(), CONTRACT)
    assert report["status"] == "PASS", report
    assert report["promotion_ready"] is True
    assert by_name(report, "model_a_preflop")["decision"] == "RETAIN_BASELINE"
    assert by_name(report, "strategy")["promotion_allowed"] is False
    assert report["rules"]["registry_update_allowed"] is True


def test_promote_model_a_requires_validation_non_regression_and_paired_ci() -> None:
    evidence = passing_evidence()
    pre = evidence["model_a"]["preflop"]
    pre.update({
        "decision": "PROMOTE_CANDIDATE",
        "validation_delta_candidate_minus_baseline": 0.0001,
        "paired_validation_delta_ci95": [-0.0002, 0.0004],
        "reason": "incorrect attempted promotion",
    })
    report = evaluate(evidence, CONTRACT)
    gate = by_name(report, "model_a_preflop")
    assert gate["status"] == "FAIL", gate
    assert gate["promotion_allowed"] is False
    assert report["status"] == "FAIL"


def test_missing_required_evidence_is_blocked_not_pass() -> None:
    evidence = passing_evidence()
    del evidence["strategy"]["baseline_persisted"]
    report = evaluate(evidence, CONTRACT)
    gate = by_name(report, "strategy")
    assert gate["status"] == "BLOCKED", gate
    assert report["status"] == "BLOCKED"
    assert report["promotion_ready"] is False
    assert report["rules"]["registry_update_allowed"] is False


def test_strategy_promotion_uses_paired_validation_and_final_test_ci() -> None:
    evidence = passing_evidence()
    strategy = evidence["strategy"]
    strategy.update({
        "decision": "PROMOTE_CANDIDATE",
        "paired_validation_delta_utility_ci95": [0.05, 0.30],
        "paired_test_delta_utility_ci95": [-0.02, 0.28],
        "reason": "validation wins but final TEST remains inconclusive",
    })
    report = evaluate(evidence, CONTRACT)
    gate = by_name(report, "strategy")
    assert gate["status"] == "FAIL", gate
    assert gate["candidate_quality_status"] == "FAIL"
    assert gate["promotion_allowed"] is False


def test_test_split_cannot_select_model_b() -> None:
    evidence = passing_evidence()
    evidence["model_b"]["test_used_for_selection"] = True
    report = evaluate(evidence, CONTRACT)
    gate = by_name(report, "model_b")
    assert gate["status"] == "FAIL", gate
    assert report["status"] == "FAIL"


def test_unsupported_strategy_scope_requires_independent_coverage() -> None:
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
    assert by_name(report, "model_a_preflop")["status"] == "FAIL"
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
