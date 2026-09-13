#!/usr/bin/env python3
"""Evaluate a normalized promotion-evidence document against the repository contract.

The evaluator distinguishes three materially different outcomes:
- PASS: the required evidence exists and is internally consistent;
- FAIL: evidence exists and violates a required gate;
- BLOCKED: required evidence is not yet available.

A rejected candidate can therefore be a valid completed cycle outcome: its candidate
quality may be FAIL while the subsystem process is PASS with decision
RETAIN_BASELINE. Use --require-ready when this command is the final pre-promotion
barrier; any overall status other than PASS then returns a non-zero exit code.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "training" / "PROMOTION_GATE_CONTRACT.json"


def check(check_id: str, status: str, reason: str, *, observed: Any = None, threshold: Any = None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": check_id, "status": status, "reason": reason}
    if observed is not None:
        out["observed"] = observed
    if threshold is not None:
        out["threshold"] = threshold
    return out


def combine(checks: list[dict[str, Any]]) -> str:
    states = {x["status"] for x in checks}
    if "FAIL" in states:
        return "FAIL"
    if "BLOCKED" in states:
        return "BLOCKED"
    return "PASS"


def bool_check(section: dict[str, Any] | None, key: str, check_id: str, reason: str) -> dict[str, Any]:
    if section is None or key not in section:
        return check(check_id, "BLOCKED", f"missing evidence: {key}")
    value = bool(section[key])
    return check(check_id, "PASS" if value else "FAIL", reason, observed=value, threshold=True)


def value_check(section: dict[str, Any] | None, key: str, check_id: str, predicate, threshold: Any, reason: str) -> dict[str, Any]:
    if section is None or key not in section or section[key] is None:
        return check(check_id, "BLOCKED", f"missing evidence: {key}", threshold=threshold)
    value = section[key]
    try:
        ok = bool(predicate(value))
    except (TypeError, ValueError, OverflowError):
        return check(check_id, "FAIL", f"invalid evidence value for {key}", observed=value, threshold=threshold)
    return check(check_id, "PASS" if ok else "FAIL", reason, observed=value, threshold=threshold)


def string_present(section: dict[str, Any] | None, key: str, check_id: str) -> dict[str, Any]:
    if section is None or key not in section:
        return check(check_id, "BLOCKED", f"missing evidence: {key}")
    value = section[key]
    ok = isinstance(value, str) and bool(value.strip())
    return check(check_id, "PASS" if ok else "FAIL", f"{key} must be a non-empty string", observed=value)


def list_present(section: dict[str, Any] | None, key: str, check_id: str) -> dict[str, Any]:
    if section is None or key not in section:
        return check(check_id, "BLOCKED", f"missing evidence: {key}")
    value = section[key]
    ok = isinstance(value, list) and len(value) > 0 and all(bool(str(x).strip()) for x in value)
    return check(check_id, "PASS" if ok else "FAIL", f"{key} must contain at least one persisted identity", observed=value)


def ci_bound(section: dict[str, Any] | None, key: str, index: int, check_id: str, predicate, threshold: float, reason: str) -> dict[str, Any]:
    if section is None or key not in section or section[key] is None:
        return check(check_id, "BLOCKED", f"missing paired confidence interval: {key}", threshold=threshold)
    ci = section[key]
    if not isinstance(ci, list) or len(ci) != 2:
        return check(check_id, "FAIL", f"{key} must be [lower, upper]", observed=ci, threshold=threshold)
    try:
        bound = float(ci[index])
    except (TypeError, ValueError):
        return check(check_id, "FAIL", f"{key} contains a non-numeric bound", observed=ci, threshold=threshold)
    if not math.isfinite(bound):
        return check(check_id, "FAIL", f"{key} contains a non-finite bound", observed=ci, threshold=threshold)
    return check(check_id, "PASS" if predicate(bound) else "FAIL", reason, observed=ci, threshold=threshold)


def component(name: str, checks: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"name": name, "status": combine(checks), "checks": checks, **extra}


def evaluate_data(evidence: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    section = evidence.get("data_integrity")
    cfg = contract["data_integrity"]
    checks = [
        bool_check(section, "source_verified", "data.source_verified", "canonical source identity must be verified"),
        bool_check(section, "exact_deduplication", "data.exact_deduplication", "exact hand-ID deduplication must be complete"),
        bool_check(section, "split_disjoint", "data.split_disjoint", "TRAIN/VALIDATION/TEST must be disjoint"),
        bool_check(section, "fingerprints_recorded", "data.fingerprints_recorded", "dataset fingerprints must be persisted"),
        value_check(section, "parse_errors", "data.parse_errors", lambda x: int(x) <= int(cfg["max_parse_errors"]), cfg["max_parse_errors"], "parse errors must not exceed the contract maximum"),
    ]
    return component("data_integrity", checks)


def evaluate_model_a_part(name: str, section: dict[str, Any] | None, contract: dict[str, Any]) -> dict[str, Any]:
    cfg = contract["model_a"]
    process = [
        value_check(section, "selection_split", f"{name}.selection_split", lambda x: str(x) == cfg["selection_split"], cfg["selection_split"], "candidate selection must use VALIDATION"),
        value_check(section, "test_used_for_selection", f"{name}.test_not_used_for_selection", lambda x: x is False, False, "TEST must not participate in candidate selection"),
        bool_check(section, "comparison_complete", f"{name}.comparison_complete", "candidate-versus-baseline comparison must be complete"),
        bool_check(section, "candidate_persisted", f"{name}.candidate_persisted", "accepted or rejected candidate artifact must be persisted"),
        string_present(section, "reason", f"{name}.decision_reason"),
    ]
    decision = section.get("decision") if section else None
    if decision not in {"PROMOTE_CANDIDATE", "RETAIN_BASELINE"}:
        process.append(check(f"{name}.decision", "BLOCKED" if decision is None else "FAIL", "decision must be PROMOTE_CANDIDATE or RETAIN_BASELINE", observed=decision))

    quality: list[dict[str, Any]] = []
    if section is not None and section.get("validation_delta_candidate_minus_baseline") is not None:
        quality.append(value_check(
            section,
            "validation_delta_candidate_minus_baseline",
            f"{name}.validation_non_regression",
            lambda x: float(x) <= float(cfg["max_validation_delta_candidate_minus_baseline"]),
            cfg["max_validation_delta_candidate_minus_baseline"],
            "candidate validation log-loss delta must not exceed baseline",
        ))
    elif decision == "PROMOTE_CANDIDATE":
        quality.append(check(f"{name}.validation_non_regression", "BLOCKED", "promotion requires candidate-minus-baseline VALIDATION delta"))

    if cfg["paired_confidence_required_for_promotion"] and decision == "PROMOTE_CANDIDATE":
        quality.append(ci_bound(
            section,
            "paired_validation_delta_ci95",
            1,
            f"{name}.paired_validation_ci95",
            lambda x: x <= float(cfg["promotion_requires_paired_ci95_upper_at_most"]),
            float(cfg["promotion_requires_paired_ci95_upper_at_most"]),
            "95% paired CI upper bound must establish non-regression",
        ))

    quality_status = combine(quality) if quality else "BLOCKED"
    status = combine(process + quality) if decision == "PROMOTE_CANDIDATE" else combine(process)
    return {
        "name": name,
        "status": status,
        "decision": decision,
        "candidate_quality_status": quality_status,
        "promotion_allowed": decision == "PROMOTE_CANDIDATE" and status == "PASS" and quality_status == "PASS",
        "checks": process + quality,
    }


def evaluate_model_b(section: dict[str, Any] | None, contract: dict[str, Any]) -> dict[str, Any]:
    cfg = contract["model_b"]
    pair = cfg["candidate_vs_incumbent"]
    guard = cfg["absolute_guardrails"]
    process = [
        value_check(section, "selection_split", "model_b.selection_split", lambda x: str(x) == cfg["selection_split"], cfg["selection_split"], "profile/model selection must use VALIDATION"),
        value_check(section, "test_used_for_selection", "model_b.test_not_used_for_selection", lambda x: x is False, False, "TEST must not participate in Model B selection"),
        bool_check(section, "comparison_complete", "model_b.comparison_complete", "candidate and incumbent must be compared on the same holdout"),
        bool_check(section, "candidate_persisted", "model_b.candidate_persisted", "candidate Model B and its features must be persisted"),
        bool_check(section, "independent_from_model_a", "model_b.independence", "Model B must remain independent from Model A outputs"),
        string_present(section, "reason", "model_b.decision_reason"),
    ]
    decision = section.get("decision") if section else None
    if decision not in {"PROMOTE_CANDIDATE", "RETAIN_BASELINE"}:
        process.append(check("model_b.decision", "BLOCKED" if decision is None else "FAIL", "decision must be PROMOTE_CANDIDATE or RETAIN_BASELINE", observed=decision))

    quality: list[dict[str, Any]] = []
    if decision == "PROMOTE_CANDIDATE":
        quality.extend([
            ci_bound(section, "paired_action_log_loss_delta_ci95", 1, "model_b.action_log_loss_ci95", lambda x: x <= float(pair["action_log_loss_delta_candidate_minus_incumbent_ci95_upper_at_most"]), float(pair["action_log_loss_delta_candidate_minus_incumbent_ci95_upper_at_most"]), "paired action-log-loss CI must establish non-regression"),
            ci_bound(section, "paired_range_log_loss_delta_ci95", 1, "model_b.range_log_loss_ci95", lambda x: x <= float(pair["range_log_loss_delta_candidate_minus_incumbent_ci95_upper_at_most"]), float(pair["range_log_loss_delta_candidate_minus_incumbent_ci95_upper_at_most"]), "paired range-log-loss CI must establish non-regression"),
            value_check(section, "validation_action_ece", "model_b.validation_action_ece", lambda x: float(x) <= float(guard["max_action_ece"]), guard["max_action_ece"], "VALIDATION action ECE must satisfy the established guardrail"),
            value_check(section, "test_action_ece", "model_b.test_action_ece", lambda x: float(x) <= float(guard["max_action_ece"]), guard["max_action_ece"], "TEST action ECE must satisfy the established guardrail"),
            value_check(section, "known_player_coverage", "model_b.known_player_coverage", lambda x: float(x) >= float(guard["min_known_player_coverage"]), guard["min_known_player_coverage"], "known-player coverage must satisfy the established guardrail"),
            value_check(section, "weighted_profile_stability", "model_b.profile_stability", lambda x: float(x) >= float(guard["min_weighted_profile_stability"]), guard["min_weighted_profile_stability"], "weighted profile stability must satisfy the established guardrail"),
            value_check(section, "state_anomaly_rate", "model_b.state_anomaly_rate", lambda x: float(x) <= float(guard["max_state_anomaly_rate"]), guard["max_state_anomaly_rate"], "state anomaly rate must satisfy the established guardrail"),
        ])
    quality_status = combine(quality) if quality else "BLOCKED"
    status = combine(process + quality) if decision == "PROMOTE_CANDIDATE" else combine(process)
    return {
        "name": "model_b",
        "status": status,
        "decision": decision,
        "candidate_quality_status": quality_status,
        "promotion_allowed": decision == "PROMOTE_CANDIDATE" and status == "PASS" and quality_status == "PASS",
        "checks": process + quality,
    }


def evaluate_strategy(section: dict[str, Any] | None, contract: dict[str, Any]) -> dict[str, Any]:
    cfg = contract["strategy"]
    process = [
        bool_check(section, "baseline_persisted", "strategy.baseline_persisted", "promoted-engine baseline must be frozen before candidate selection"),
        bool_check(section, "comparison_complete", "strategy.comparison_complete", "paired candidate comparison must be complete"),
        bool_check(section, "candidate_persisted", "strategy.candidate_persisted", "strategy candidate and parameters must be persisted"),
        value_check(section, "selection_split", "strategy.selection_split", lambda x: str(x) == cfg["selection_split"], cfg["selection_split"], "strategy selection must use VALIDATION"),
        value_check(section, "test_used_for_tuning", "strategy.test_not_used_for_tuning", lambda x: x is False, False, "TEST must remain untouched during strategy tuning"),
        bool_check(section, "environment_validity_pass", "strategy.environment_validity", "environment realism/sensitivity gate must pass for promotion-oriented sizing conclusions"),
        bool_check(section, "scenario_manifest_persisted", "strategy.scenario_manifest", "scenario/seed manifest must be persisted"),
        string_present(section, "reason", "strategy.decision_reason"),
    ]
    decision = section.get("decision") if section else None
    if decision not in {"PROMOTE_CANDIDATE", "RETAIN_BASELINE"}:
        process.append(check("strategy.decision", "BLOCKED" if decision is None else "FAIL", "decision must be PROMOTE_CANDIDATE or RETAIN_BASELINE", observed=decision))

    change_scope = section.get("change_scope") if section else None
    if change_scope is None:
        process.append(check("strategy.change_scope", "BLOCKED", "strategy change scope is not declared"))
    elif not isinstance(change_scope, list):
        process.append(check("strategy.change_scope", "FAIL", "change_scope must be a list", observed=change_scope))
    else:
        unsupported = {"preflop", "multiway"}.intersection({str(x) for x in change_scope})
        if unsupported:
            covered = bool(section.get("unsupported_contexts_covered")) if section else False
            process.append(check("strategy.unsupported_contexts", "PASS" if covered else "FAIL", "preflop/multiway changes require independent evidence outside the current HU postflop arena", observed=sorted(unsupported), threshold="covered"))
        else:
            process.append(check("strategy.unsupported_contexts", "PASS", "declared strategy change is within the current arena scope", observed=change_scope))

    quality: list[dict[str, Any]] = []
    if decision == "PROMOTE_CANDIDATE":
        quality.extend([
            ci_bound(section, "paired_validation_delta_utility_ci95", 0, "strategy.validation_utility_ci95", lambda x: x >= float(cfg["promotion_requires_validation_ci95_lower_at_least"]), float(cfg["promotion_requires_validation_ci95_lower_at_least"]), "VALIDATION paired utility CI lower bound must establish non-regression"),
            ci_bound(section, "paired_test_delta_utility_ci95", 0, "strategy.test_utility_ci95", lambda x: x >= float(cfg["promotion_requires_test_ci95_lower_at_least"]), float(cfg["promotion_requires_test_ci95_lower_at_least"]), "frozen-finalist TEST paired utility CI lower bound must establish non-regression"),
        ])
    quality_status = combine(quality) if quality else "BLOCKED"
    status = combine(process + quality) if decision == "PROMOTE_CANDIDATE" else combine(process)
    return {
        "name": "strategy",
        "status": status,
        "decision": decision,
        "candidate_quality_status": quality_status,
        "promotion_allowed": decision == "PROMOTE_CANDIDATE" and status == "PASS" and quality_status == "PASS",
        "metric": cfg["metric"],
        "checks": process + quality,
    }


def evaluate_regressions(evidence: dict[str, Any]) -> dict[str, Any]:
    section = evidence.get("regressions")
    checks = [
        bool_check(section, "pathological_engine_suite_pass", "regression.pathological", "permanent pathological-engine suite must pass"),
        bool_check(section, "trainer_contract_suite_pass", "regression.trainer", "trainer contract/browser suite must pass"),
        bool_check(section, "sequential_arena_contract_suite_pass", "regression.sequential_arena", "determinism/trial-budget/betting legality contracts must pass"),
    ]
    return component("regressions", checks)


def evaluate_provenance(evidence: dict[str, Any]) -> dict[str, Any]:
    section = evidence.get("provenance")
    checks = [
        string_present(section, "code_commit", "provenance.code_commit"),
        list_present(section, "dataset_fingerprints", "provenance.dataset_fingerprints"),
        list_present(section, "model_hashes", "provenance.model_hashes"),
        string_present(section, "seed_or_scenario_manifest", "provenance.seed_or_scenario_manifest"),
    ]
    return component("provenance", checks)


def evaluate_release_identity(evidence: dict[str, Any]) -> dict[str, Any]:
    section = evidence.get("release_identity")
    checks = [
        string_present(section, "engine_release_artifact", "release.engine_artifact"),
        string_present(section, "engine_release_sha256", "release.engine_sha256"),
        string_present(section, "assembled_site_entrypoint", "release.site_entrypoint"),
        string_present(section, "assembled_site_git_blob_sha", "release.site_blob_sha"),
        string_present(section, "assets_tree_git_sha", "release.assets_tree_sha"),
        string_present(section, "assembled_from_commit", "release.assembled_commit"),
    ]
    if section and section.get("engine_release_artifact") and section.get("assembled_site_entrypoint"):
        same = section["engine_release_artifact"] == section["assembled_site_entrypoint"]
        checks.append(check("release.distinct_identities", "FAIL" if same else "PASS", "engine release artifact and assembled site entrypoint must be distinct identities", observed=not same, threshold=True))
    else:
        checks.append(check("release.distinct_identities", "BLOCKED", "release identities are incomplete"))
    return component("release_identity", checks)


def evaluate_registry(evidence: dict[str, Any]) -> dict[str, Any]:
    section = evidence.get("registry_transition")
    checks = [
        bool_check(section, "unchanged_before_explicit_promotion", "registry.pre_promotion_unchanged", "promoted registry pointers must remain unchanged before explicit promotion")
    ]
    return component("registry_transition", checks)


def evaluate_deployment(evidence: dict[str, Any]) -> dict[str, Any]:
    section = evidence.get("deployment")
    if not section or not section.get("site_release_attempted"):
        return {"name": "deployment_verification", "status": "NOT_APPLICABLE", "checks": [], "post_promotion": True}
    checks = [
        bool_check(section, "production_build_success", "deployment.build", "production build must succeed"),
        bool_check(section, "public_url_verified", "deployment.public_url", "public production URL must be verified"),
        bool_check(section, "deployed_commit_verified", "deployment.commit", "deployed build must be traceable to the intended commit"),
        bool_check(section, "application_smoke_verified", "deployment.smoke", "published analyser/trainer/assets smoke must pass"),
    ]
    return {**component("deployment_verification", checks), "post_promotion": True}


def evaluate(evidence: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    if evidence.get("schema") != "poker-promotion-evidence/v1":
        raise ValueError("evidence schema must be poker-promotion-evidence/v1")
    if contract.get("schema") != "poker-promotion-gate-contract/v1":
        raise ValueError("unsupported promotion contract schema")

    model_a = evidence.get("model_a") or {}
    components = [
        evaluate_data(evidence, contract),
        evaluate_model_a_part("model_a_preflop", model_a.get("preflop"), contract),
        evaluate_model_a_part("model_a_postflop", model_a.get("postflop"), contract),
        evaluate_model_b(evidence.get("model_b"), contract),
        evaluate_strategy(evidence.get("strategy"), contract),
        evaluate_regressions(evidence),
        evaluate_provenance(evidence),
        evaluate_release_identity(evidence),
        evaluate_registry(evidence),
    ]
    overall = combine([{"status": c["status"]} for c in components])
    deployment = evaluate_deployment(evidence)
    decisions = {
        c["name"]: {
            "status": c["status"],
            "decision": c.get("decision"),
            "promotion_allowed": c.get("promotion_allowed", c["status"] == "PASS"),
        }
        for c in components
        if c["name"] in {"model_a_preflop", "model_a_postflop", "model_b", "strategy"}
    }
    return {
        "schema": "poker-promotion-gate-report/v1",
        "contract_version": contract["contract_version"],
        "cycle": evidence.get("cycle"),
        "status": overall,
        "promotion_ready": overall == "PASS",
        "components": components,
        "candidate_decisions": decisions,
        "deployment_verification": deployment,
        "rules": {
            "registry_update_allowed": overall == "PASS",
            "blocked_is_not_pass": True,
            "rejected_candidate_can_complete_cycle": True,
            "test_may_select_or_retune": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, help="normalized poker-promotion-evidence/v1 JSON")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--out", default="", help="optional output path; stdout is always emitted")
    parser.add_argument("--require-ready", action="store_true", help="return exit code 2 unless the aggregate promotion gate is PASS")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    report = evaluate(evidence, contract)
    text = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text, end="")
    if args.require_ready and report["status"] != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
