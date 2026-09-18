#!/usr/bin/env python3
"""Replacement #108 VALIDATION runner with shared, counted Hero support closure.

This module reuses the frozen v2 scenario/statistics machinery.  The only
semantic replacement is the Hero reference runtime described by contract
2026-09-17.2: exact Model A when supported, otherwise the same deterministic
CHECK/CALL/FOLD closure in both reference and candidate arms.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.simulation.full_hand_arena import run_full_hand
from tools.simulation.hero_preflop_overlay import ExactHeroPreflopOverlayPolicy
from tools.simulation.model_a_continuation import ModelAContinuationPolicy
from tools.simulation.model_b_runtime import rake_net
from tools.simulation.model_b_sensitivity import ModelBSensitivityPolicy
from tools.simulation.preflop_strategy_benchmark_v2 import (
    DEFAULT_BINDING,
    DEFAULT_CANDIDATE,
    DEFAULT_SENSITIVITY,
    candidate_policy_binding_path,
    _row_from_pair,
    build_validation_run as build_validation_run_v2,
    load_json,
    select_validation as select_validation_v2,
    sha256_file,
    summarize_environment_rows,
    write_json,
)
from tools.simulation.reference_support_closure import SupportClosedModelAReferencePolicy
from tools.training.validate_preflop_strategy_benchmark_support_closed import validate_contract
from tools.training.validate_preflop_strategy_benchmark_pfpc import (
    DEFAULT_PREVIOUS as DEFAULT_PFPC_PREVIOUS,
    DEFAULT_ZERO_EXPOSURE as DEFAULT_PFPC_ZERO_EXPOSURE,
    validate_contract as validate_pfpc_contract,
)
from tools.training.validate_preflop_strategy_benchmark_v2 import validate_run_manifest

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "training/full_hand/PREFLOP_STRATEGY_BENCHMARK_CONTRACT_20260917_SUPPORT_CLOSED.json"
DEFAULT_REFERENCE = ROOT / "training/full_hand/HERO_REFERENCE_POLICY_20260917_SUPPORT_CLOSED.json"
DEFAULT_BASE = ROOT / "training/full_hand/FULL_HAND_EVALUATION_PROTOCOL_20260915.json"
DEFAULT_BLOCKED = ROOT / "training/runs/20260917_preflop_strategy_validation_v2_blocked/RESULT.json"


def build_validation_run(**kwargs):
    kwargs.setdefault("contract_path", DEFAULT_CONTRACT)
    kwargs.setdefault("reference_path", DEFAULT_REFERENCE)
    kwargs.setdefault("sensitivity_path", DEFAULT_SENSITIVITY)
    kwargs.setdefault("candidate_path", DEFAULT_CANDIDATE)
    kwargs.setdefault("binding_path", DEFAULT_BINDING)
    return build_validation_run_v2(**kwargs)


def _reference_policy(descriptor_path: Path) -> SupportClosedModelAReferencePolicy:
    descriptor = load_json(descriptor_path)
    runtime = descriptor.get("runtime") or {}
    if runtime.get("class") != "SupportClosedModelAReferencePolicy":
        raise ValueError("support-closed benchmark requires SupportClosedModelAReferencePolicy descriptor")
    artifacts = descriptor["artifacts"]
    delegate = ModelAContinuationPolicy.from_paths(
        ROOT / artifacts["preflop_model"]["path"],
        ROOT / artifacts["postflop_baseline"]["path"],
        ROOT / artifacts["postflop_selected_overlay"]["path"],
    )
    return SupportClosedModelAReferencePolicy(delegate)


def _aggregate_support_audits(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    audits = [dict(row.get(key) or {}) for row in rows]
    hero_decisions = sum(int(row.get("hero_decisions", 0)) for row in audits)
    exact = sum(int(row.get("exact_model_a_decisions", 0)) for row in audits)
    fallback = sum(int(row.get("support_closure_decisions", 0)) for row in audits)
    if exact + fallback != hero_decisions:
        raise AssertionError(f"support closure accounting incomplete for {key}")
    by_street = collections.Counter()
    reasons = collections.Counter()
    for audit in audits:
        by_street.update({street: int(value) for street, value in (audit.get("support_closure_by_street") or {}).items()})
        reasons.update({reason: int(value) for reason, value in (audit.get("support_closure_reasons") or {}).items()})
    return {
        "hero_decisions": hero_decisions,
        "exact_model_a_decisions": exact,
        "support_closure_decisions": fallback,
        "support_closure_rate": None if hero_decisions == 0 else fallback / hero_decisions,
        "support_closure_by_street": dict(sorted(by_street.items())),
        "support_closure_reasons": dict(sorted(reasons.items())),
        "fallback_contract": SupportClosedModelAReferencePolicy.fallback_contract,
        "nearest_context_substitution": False,
    }


def run_environment(
    scenario_manifest: Mapping[str, Any],
    run_manifest: Mapping[str, Any],
    *,
    environment_id: str,
    reference_behavior_path: Path,
    issue_104_result_path: Path,
    candidate_path: Path = DEFAULT_CANDIDATE,
    binding_path: Path = DEFAULT_BINDING,
    reference_descriptor_path: Path = DEFAULT_REFERENCE,
    sensitivity_path: Path = DEFAULT_SENSITIVITY,
) -> dict[str, Any]:
    if scenario_manifest.get("split") != "VALIDATION" or run_manifest.get("phase") != "VALIDATION":
        raise ValueError("support-closed executable currently accepts VALIDATION only")
    if run_manifest.get("test_data_read") is not False:
        raise ValueError("VALIDATION run manifest must prove TEST was not read")
    scenario_sha = hashlib.sha256(
        (json.dumps(scenario_manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    ).hexdigest()
    if scenario_sha != run_manifest["identities"]["scenario_manifest_sha256"]:
        raise ValueError("scenario manifest content changed after run identity freeze")
    if sha256_file(reference_descriptor_path) != run_manifest["identities"]["reference_descriptor_sha256"]:
        raise ValueError("reference descriptor changed after run identity freeze")

    policy_binding_path = candidate_policy_binding_path(
        binding_path, candidate_path, run_manifest
    )
    reference = _reference_policy(reference_descriptor_path)
    candidate_reference = _reference_policy(reference_descriptor_path)
    opponent = ModelBSensitivityPolicy.from_paths(
        reference_behavior_path,
        issue_104_result_path,
        environment_id=environment_id,
        sensitivity_path=sensitivity_path,
    )
    candidate = ExactHeroPreflopOverlayPolicy.from_path(
        candidate_path,
        reference_policy=candidate_reference,
        candidate_id=str(run_manifest["identities"]["candidate_id"]),
        policy_binding_path=policy_binding_path,
    )
    if candidate.repository_sha256 != run_manifest["identities"]["candidate_artifact_sha256"]:
        raise ValueError("candidate repository changed after run identity freeze")

    rows: list[dict[str, Any]] = []
    for scenario in scenario_manifest.get("scenarios", []):
        scenario_id = str(scenario["scenario_id"])
        reference_result = run_full_hand(
            scenario,
            hero_policy=reference,
            opponent_policy=opponent,
            net_pot_fn=rake_net,
        )
        candidate_result = run_full_hand(
            scenario,
            hero_policy=candidate,
            opponent_policy=opponent,
            net_pot_fn=rake_net,
        )
        row = _row_from_pair(
            scenario,
            reference_result,
            candidate_result,
            candidate.scenario_audit(scenario_id),
        )
        row["reference_support_audit"] = reference.scenario_audit(scenario_id)
        row["candidate_reference_support_audit"] = candidate_reference.scenario_audit(scenario_id)
        rows.append(row)
    if not rows:
        raise ValueError("VALIDATION manifest contains no scenarios")

    environment_identity = opponent.identity()
    bootstrap_seed = int(run_manifest["budgets"]["master_seed"]) ^ int(
        hashlib.sha256(environment_id.encode("utf-8")).hexdigest()[:16], 16
    )
    report = summarize_environment_rows(
        rows,
        environment=environment_identity,
        candidate_id=str(run_manifest["identities"]["candidate_id"]),
        bootstrap_samples=int(run_manifest["budgets"]["bootstrap_samples"]),
        bootstrap_seed=bootstrap_seed,
        threshold=float(run_manifest["thresholds"]["validation_ci95_lower_bb_per_100"]),
    )
    report["reference_support_closure"] = _aggregate_support_audits(rows, "reference_support_audit")
    report["candidate_reference_support_closure"] = _aggregate_support_audits(rows, "candidate_reference_support_audit")
    report["candidate_policy_identity"] = candidate.identity()
    report["support_closure_contract"] = {
        "shared_semantics": True,
        "fallback_contract": SupportClosedModelAReferencePolicy.fallback_contract,
        "nearest_context_substitution": False,
    }
    return report


def select_validation(reports: Sequence[Mapping[str, Any]], run_manifest: Mapping[str, Any]) -> dict[str, Any]:
    selection = select_validation_v2(reports, run_manifest)
    selection["reference_support_closure"] = {
        str(report["environment"]["environment_id"]): {
            "reference_rate": (report.get("reference_support_closure") or {}).get("support_closure_rate"),
            "candidate_reference_rate": (report.get("candidate_reference_support_closure") or {}).get("support_closure_rate"),
            "reference_by_street": (report.get("reference_support_closure") or {}).get("support_closure_by_street"),
            "candidate_reference_by_street": (report.get("candidate_reference_support_closure") or {}).get("support_closure_by_street"),
        }
        for report in reports
    }
    selection["interpretation_limits"] = [
        "Performance is conditional on the shared CHECK/CALL/FOLD support closure whenever exact Model A is unavailable.",
        "Support-closure frequency is reported and no nearest-context substitution is used.",
        "TEST remains unconsumed unless every frozen environment passes the unchanged clustered CI gate.",
    ]
    return selection


def _preflight_contract(contract_path: Path, reference_path: Path, sensitivity_path: Path) -> None:
    contract = load_json(contract_path)
    sensitivity = load_json(sensitivity_path)
    version = str(contract.get("contract_version") or "")
    if version == "2026-09-17.2":
        result = validate_contract(
            contract,
            load_json(DEFAULT_BASE),
            load_json(reference_path),
            sensitivity,
            load_json(DEFAULT_BLOCKED),
        )
    elif version == "2026-09-18.3":
        result = validate_pfpc_contract(
            contract,
            load_json(DEFAULT_PFPC_PREVIOUS),
            load_json(DEFAULT_BASE),
            load_json(reference_path),
            sensitivity,
            load_json(DEFAULT_PFPC_ZERO_EXPOSURE),
        )
    else:
        raise ValueError(f"unsupported support-closed benchmark contract version {version!r}")
    if result["status"] != "PASS":
        raise ValueError("invalid support-closed benchmark contract: " + "; ".join(result["errors"]))


def _cmd_prepare(args: argparse.Namespace) -> int:
    _preflight_contract(args.contract, args.reference_descriptor, args.sensitivity)
    scenarios, run = build_validation_run(
        population_id=args.population,
        profiles_path=args.profiles,
        archives=args.archive,
        certification=args.certification,
        master_seed=args.seed,
        code_commit_sha=args.code_sha,
        candidate_source_commit_sha=args.candidate_source_commit,
        contract_path=args.contract,
        reference_path=args.reference_descriptor,
        sensitivity_path=args.sensitivity,
        candidate_path=args.candidate,
        binding_path=args.binding,
        hero=args.hero,
    )
    write_json(args.scenarios_out, scenarios)
    if sha256_file(args.scenarios_out) != run["identities"]["scenario_manifest_sha256"]:
        raise AssertionError("persisted scenario manifest hash drifted")
    write_json(args.run_manifest_out, run)
    print(json.dumps({"scenarios": len(scenarios["scenarios"]), "run": run}, indent=2, sort_keys=True))
    return 0


def _cmd_environment(args: argparse.Namespace) -> int:
    report = run_environment(
        load_json(args.scenarios),
        load_json(args.run_manifest),
        environment_id=args.environment_id,
        reference_behavior_path=args.reference_behavior,
        issue_104_result_path=args.issue_104_result,
        candidate_path=args.candidate,
        binding_path=args.binding,
        reference_descriptor_path=args.reference_descriptor,
        sensitivity_path=args.sensitivity,
    )
    write_json(args.output, report)
    print(json.dumps({
        "environment": report["environment"]["environment_id"],
        "paired": report["paired"],
        "gate": report["gate"],
        "candidate_coverage": report["candidate_coverage"],
        "reference_support_closure": report["reference_support_closure"],
        "candidate_reference_support_closure": report["candidate_reference_support_closure"],
    }, indent=2, sort_keys=True))
    return 0


def _cmd_select(args: argparse.Namespace) -> int:
    run = load_json(args.run_manifest)
    selection = select_validation([load_json(path) for path in args.report], run)
    write_json(args.output, selection)
    print(json.dumps(selection, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare-validation")
    prepare.add_argument("--population", required=True)
    prepare.add_argument("--profiles", type=Path, required=True)
    prepare.add_argument("--archive", type=Path, action="append", required=True)
    prepare.add_argument("--certification", type=Path, required=True)
    prepare.add_argument("--seed", type=int, default=20260917)
    prepare.add_argument("--code-sha", required=True)
    prepare.add_argument("--candidate-source-commit", required=True)
    prepare.add_argument("--hero", default="RoiDePiqueNique")
    prepare.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    prepare.add_argument("--reference-descriptor", type=Path, default=DEFAULT_REFERENCE)
    prepare.add_argument("--sensitivity", type=Path, default=DEFAULT_SENSITIVITY)
    prepare.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    prepare.add_argument("--binding", type=Path, default=DEFAULT_BINDING)
    prepare.add_argument("--scenarios-out", type=Path, required=True)
    prepare.add_argument("--run-manifest-out", type=Path, required=True)
    prepare.set_defaults(func=_cmd_prepare)

    environment = sub.add_parser("run-environment")
    environment.add_argument("--scenarios", type=Path, required=True)
    environment.add_argument("--run-manifest", type=Path, required=True)
    environment.add_argument("--environment-id", required=True)
    environment.add_argument("--reference-behavior", type=Path, required=True)
    environment.add_argument("--issue-104-result", type=Path, required=True)
    environment.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    environment.add_argument("--binding", type=Path, default=DEFAULT_BINDING)
    environment.add_argument("--reference-descriptor", type=Path, default=DEFAULT_REFERENCE)
    environment.add_argument("--sensitivity", type=Path, default=DEFAULT_SENSITIVITY)
    environment.add_argument("--output", type=Path, required=True)
    environment.set_defaults(func=_cmd_environment)

    select = sub.add_parser("select-validation")
    select.add_argument("--run-manifest", type=Path, required=True)
    select.add_argument("--report", type=Path, action="append", required=True)
    select.add_argument("--output", type=Path, required=True)
    select.set_defaults(func=_cmd_select)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
