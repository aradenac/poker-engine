#!/usr/bin/env python3
"""One-shot TEST confirmation for the frozen #108 PFPC finalist.

This module deliberately exposes no candidate search or retuning. TEST may be
constructed only after an immutable VALIDATION selection freezes exactly one
finalist. Reading TEST consumes the named holdout generation regardless of
whether the finalist is confirmed, rejected, or yields zero usable exposure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.simulation.full_hand_arena import run_full_hand
from tools.simulation.hero_preflop_overlay import ExactHeroPreflopOverlayPolicy
from tools.simulation.model_b_runtime import rake_net
from tools.simulation.model_b_sensitivity import ModelBSensitivityPolicy, load_sensitivity_set
from tools.simulation.preflop_strategy_benchmark_support_closed import (
    DEFAULT_REFERENCE,
    _aggregate_support_audits,
    _preflight_contract,
    _reference_policy,
)
from tools.simulation.preflop_strategy_benchmark_v2 import (
    RUN_SCHEMA,
    _certified_eligible_count,
    _row_from_pair,
    candidate_binding_identity,
    candidate_policy_binding_path,
    load_json,
    sha256_file,
    summarize_environment_rows,
    write_json,
)
from tools.simulation.full_hand_benchmark import ProfileSource, build_manifest_from_archives
from tools.training.validate_preflop_strategy_benchmark_v2 import validate_run_manifest

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "training/full_hand/PREFLOP_STRATEGY_BENCHMARK_CONTRACT_20260918_PFPC.json"
DEFAULT_SENSITIVITY = ROOT / "training/full_hand/MODEL_B_SENSITIVITY_ENVIRONMENTS_20260917.json"
DEFAULT_LEDGER = ROOT / "training/full_hand/TEST_HOLDOUT_LEDGER.json"
TEST_RESULT_SCHEMA = "poker-preflop-strategy-test-confirmation/v1"


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _validation_authorization(
    validation_run: Mapping[str, Any],
    selection: Mapping[str, Any],
    *,
    candidate_identity: Mapping[str, str],
    contract_version: str,
) -> None:
    _need(validation_run.get("schema") == RUN_SCHEMA, "VALIDATION run schema mismatch")
    _need(validation_run.get("contract_version") == contract_version, "VALIDATION contract version mismatch")
    _need(validation_run.get("phase") == "VALIDATION", "authorization source is not VALIDATION")
    _need(validation_run.get("test_data_read") is False, "VALIDATION already read TEST")
    _need(validation_run.get("results_inspected") is False, "VALIDATION run identity was not frozen pre-result")

    identities = dict(validation_run.get("identities") or {})
    for field in (
        "candidate_id",
        "candidate_artifact_sha256",
        "candidate_binding_sha256",
        "candidate_binding_schema",
    ):
        _need(
            str(identities.get(field) or "") == str(candidate_identity.get(field) or ""),
            f"VALIDATION finalist identity differs on {field}",
        )

    _need(selection.get("schema") == "poker-preflop-strategy-validation-selection/v2", "selection schema mismatch")
    _need(selection.get("phase") == "VALIDATION", "selection phase mismatch")
    _need(selection.get("contract_version") == contract_version, "selection contract mismatch")
    _need(selection.get("outcome") == "FREEZE_FINALIST", "TEST requires FREEZE_FINALIST")
    _need(selection.get("frozen_finalist") == candidate_identity["candidate_id"], "frozen finalist differs from candidate")
    _need(selection.get("candidate_id") == candidate_identity["candidate_id"], "selection candidate differs")
    _need(selection.get("test_authorized") is True, "VALIDATION did not authorize TEST")
    _need(selection.get("test_used_for_selection") is False, "TEST was used for selection")
    _need(selection.get("test_consumed") is False, "selection says TEST already consumed")
    _need(selection.get("promotion_authorized") is False, "VALIDATION may not directly authorize promotion")
    validity = dict(selection.get("candidate_exposure_validity") or {})
    _need(validity.get("status") == "PASS", "VALIDATION candidate exposure was not valid")


def _holdout_generation(
    ledger: Mapping[str, Any],
    *,
    generation_id: str,
    population_id: str,
    population_fingerprint: str,
) -> dict[str, Any]:
    _need(ledger.get("schema") == "poker-test-holdout-ledger/v1", "holdout ledger schema mismatch")
    _need(str(ledger.get("population_id") or "") == population_id, "holdout ledger population mismatch")
    rows = [
        dict(row)
        for row in ledger.get("generations") or []
        if str((row or {}).get("generation_id") or "") == generation_id
    ]
    _need(len(rows) == 1, f"holdout generation {generation_id!r} not uniquely defined")
    row = rows[0]
    _need(row.get("split") == "TEST", "holdout generation is not TEST")
    _need(row.get("status") == "UNCONSUMED", "holdout generation is already consumed")
    _need(
        str(row.get("source_population_fingerprint_sha256") or "") == population_fingerprint,
        "holdout population fingerprint mismatch",
    )
    _need(int(row.get("unique_hands") or 0) > 0, "holdout generation has no hands")
    _need(row.get("consumed_by_cycle") is None, "unconsumed generation has cycle owner")
    _need(row.get("consumed_by_frozen_finalist") is None, "unconsumed generation has finalist owner")
    _need(row.get("consumed_at_commit") is None, "unconsumed generation has consumption commit")
    return row


def build_test_run(
    *,
    population_id: str,
    profiles_path: Path,
    archives: Sequence[Path],
    certification: Path,
    master_seed: int,
    code_commit_sha: str,
    candidate_source_commit_sha: str,
    candidate_path: Path,
    binding_path: Path,
    validation_run_path: Path,
    validation_selection_path: Path,
    holdout_ledger_path: Path,
    holdout_generation_id: str,
    contract_path: Path = DEFAULT_CONTRACT,
    reference_path: Path = DEFAULT_REFERENCE,
    sensitivity_path: Path = DEFAULT_SENSITIVITY,
    hero: str = "RoiDePiqueNique",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Authorize then materialize TEST scenarios exactly once for one finalist."""
    _preflight_contract(contract_path, reference_path, sensitivity_path)
    contract = load_json(contract_path)
    sensitivity = load_sensitivity_set(sensitivity_path)
    candidate_identity = candidate_binding_identity(binding_path, candidate_path)
    validation_run = load_json(validation_run_path)
    selection = load_json(validation_selection_path)
    _validation_authorization(
        validation_run,
        selection,
        candidate_identity=candidate_identity,
        contract_version=str(contract["contract_version"]),
    )

    population = dict(contract.get("population") or {})
    _need(population.get("population_id") == population_id, "TEST population differs from frozen contract")
    ledger = load_json(holdout_ledger_path)
    generation = _holdout_generation(
        ledger,
        generation_id=holdout_generation_id,
        population_id=population_id,
        population_fingerprint=str(population["population_fingerprint_sha256"]),
    )

    count, eligibility = _certified_eligible_count(
        population_id=population_id,
        archives=archives,
        certification=certification,
        split="TEST",
        hero=hero,
    )
    _need(
        int(eligibility["certified_split_hands"]) == int(generation["unique_hands"]),
        "TEST certification count differs from frozen holdout ledger",
    )
    profiles = ProfileSource.from_path(profiles_path, population_id=population_id)
    reps = int(contract["scenarios"]["rollouts_per_base_hand"])
    scenario_manifest = build_manifest_from_archives(
        population_id=population_id,
        profiles=profiles,
        archives=archives,
        certification=certification,
        count=count,
        reps=reps,
        master_seed=int(master_seed),
        start=0,
        split="TEST",
        hero=hero,
        root=ROOT,
    )
    _need(scenario_manifest.get("split") == "TEST", "scenario builder crossed TEST boundary")
    scenario_manifest["eligibility"] = eligibility
    scenario_sha = hashlib.sha256(
        (json.dumps(scenario_manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    ).hexdigest()
    environment_ids = [str(row["environment_id"]) for row in sensitivity["environments"]]

    run_manifest = {
        "schema": RUN_SCHEMA,
        "contract_version": contract["contract_version"],
        "phase": "TEST",
        "results_inspected": False,
        "test_data_read": True,
        "test_holdout_generation_id": holdout_generation_id,
        "validation_selection": selection,
        "identities": {
            "code_commit_sha": str(code_commit_sha),
            "dataset_population_fingerprint_sha256": population["population_fingerprint_sha256"],
            "scenario_manifest_sha256": scenario_sha,
            "reference_descriptor_sha256": sha256_file(reference_path),
            **candidate_identity,
            "candidate_source_commit_sha": str(candidate_source_commit_sha),
            "model_b_sensitivity_descriptor_sha256": sha256_file(sensitivity_path),
            "model_b_base_artifact_sha256": contract["environment_sensitivity"]["base_artifact_sha256"],
            "model_b_environment_ids": environment_ids,
            "validation_run_manifest_sha256": sha256_file(validation_run_path),
            "validation_selection_sha256": sha256_file(validation_selection_path),
            "holdout_ledger_sha256_before": sha256_file(holdout_ledger_path),
        },
        "budgets": {
            "master_seed": int(master_seed),
            "rollouts_per_base_hand": reps,
            "bootstrap_samples": int(contract["statistics"]["bootstrap_samples"]),
            "certified_test_hands": int(eligibility["certified_split_hands"]),
            "simulatable_test_hands": int(count),
            "simulated_scenarios_per_policy_environment": int(count * reps),
        },
        "thresholds": {
            "validation_ci95_lower_bb_per_100": contract["validation_selection"]["required_ci95_lower_bound_bb_per_100"],
            "test_ci95_lower_bb_per_100": contract["test_confirmation"]["required_ci95_lower_bound_bb_per_100"],
            "environment_gate_rule": contract["test_confirmation"]["minimum_environment_gate_rule"],
        },
        "selection_boundary": {
            "candidate_frozen_from_validation": True,
            "test_generation_consumed_by_this_run": True,
            "test_may_select_alternative": False,
            "test_may_retune_candidate": False,
            "test_may_change_thresholds": False,
        },
    }
    check = validate_run_manifest(contract, sensitivity, run_manifest)
    _need(check["status"] == "PASS", "invalid frozen TEST run manifest: " + "; ".join(check["errors"]))
    return scenario_manifest, run_manifest


def run_test_environment(
    scenario_manifest: Mapping[str, Any],
    run_manifest: Mapping[str, Any],
    *,
    environment_id: str,
    reference_behavior_path: Path,
    issue_104_result_path: Path,
    candidate_path: Path,
    binding_path: Path,
    reference_descriptor_path: Path = DEFAULT_REFERENCE,
    sensitivity_path: Path = DEFAULT_SENSITIVITY,
) -> dict[str, Any]:
    _need(scenario_manifest.get("split") == "TEST", "TEST runner received non-TEST scenarios")
    _need(run_manifest.get("phase") == "TEST", "TEST runner received non-TEST manifest")
    _need(run_manifest.get("test_data_read") is True, "TEST manifest does not acknowledge holdout consumption")
    scenario_sha = hashlib.sha256(
        (json.dumps(scenario_manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    ).hexdigest()
    _need(scenario_sha == run_manifest["identities"]["scenario_manifest_sha256"], "TEST scenario manifest drift")
    _need(
        sha256_file(reference_descriptor_path) == run_manifest["identities"]["reference_descriptor_sha256"],
        "reference descriptor changed after TEST freeze",
    )

    policy_binding_path = candidate_policy_binding_path(binding_path, candidate_path, run_manifest)
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
    _need(
        candidate.repository_sha256 == run_manifest["identities"]["candidate_artifact_sha256"],
        "candidate repository changed after TEST freeze",
    )

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
    _need(bool(rows), "TEST manifest contains no scenarios")

    environment_identity = opponent.identity()
    bootstrap_seed = int(run_manifest["budgets"]["master_seed"]) ^ int(
        hashlib.sha256(("TEST|" + environment_id).encode("utf-8")).hexdigest()[:16], 16
    )
    report = summarize_environment_rows(
        rows,
        environment=environment_identity,
        candidate_id=str(run_manifest["identities"]["candidate_id"]),
        bootstrap_samples=int(run_manifest["budgets"]["bootstrap_samples"]),
        bootstrap_seed=bootstrap_seed,
        threshold=float(run_manifest["thresholds"]["test_ci95_lower_bb_per_100"]),
    )
    report["phase"] = "TEST"
    report["reference_support_closure"] = _aggregate_support_audits(rows, "reference_support_audit")
    report["candidate_reference_support_closure"] = _aggregate_support_audits(
        rows, "candidate_reference_support_audit"
    )
    report["candidate_policy_identity"] = candidate.identity()
    report["support_closure_contract"] = {
        "shared_semantics": True,
        "fallback_contract": "CHECK_THEN_CALL_THEN_FOLD_V1",
        "nearest_context_substitution": False,
    }
    return report


def select_test_confirmation(
    reports: Sequence[Mapping[str, Any]],
    run_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    expected = [str(value) for value in run_manifest["identities"]["model_b_environment_ids"]]
    candidate_id = str(run_manifest["identities"]["candidate_id"])
    by_id: dict[str, Mapping[str, Any]] = {}
    for report in reports:
        environment_id = str((report.get("environment") or {}).get("environment_id") or "")
        _need(environment_id in expected, f"unexpected TEST environment {environment_id!r}")
        _need(environment_id not in by_id, f"duplicate TEST environment {environment_id}")
        _need(report.get("phase") == "TEST", f"{environment_id}: report phase is not TEST")
        _need(str(report.get("candidate_id") or "") == candidate_id, "TEST reports compare different candidates")
        by_id[environment_id] = report
    _need(set(by_id) == set(expected), "TEST environment report set incomplete")

    coverage: dict[str, dict[str, Any]] = {}
    zero_exposure: list[str] = []
    environment_pass: dict[str, bool] = {}
    for environment_id in expected:
        report = by_id[environment_id]
        row = dict(report.get("candidate_coverage") or {})
        hero = int(row.get("hero_preflop_decisions") or 0)
        supported = int(row.get("supported_decisions") or 0)
        unsupported = int(row.get("out_of_support_decisions") or 0)
        _need(supported + unsupported == hero, f"{environment_id}: incomplete candidate coverage accounting")
        coverage[environment_id] = {
            "hero_preflop_decisions": hero,
            "supported_decisions": supported,
            "out_of_support_decisions": unsupported,
            "supported_decision_rate": None if hero == 0 else supported / hero,
            "out_of_support_decision_rate": None if hero == 0 else unsupported / hero,
        }
        if hero <= 0 or supported <= 0:
            zero_exposure.append(environment_id)
        environment_pass[environment_id] = bool((report.get("gate") or {}).get("pass"))

    performance_interpretable = not zero_exposure
    confirmed = performance_interpretable and all(environment_pass.values())
    return {
        "schema": TEST_RESULT_SCHEMA,
        "phase": "TEST",
        "contract_version": run_manifest["contract_version"],
        "candidate_id": candidate_id,
        "frozen_finalist": candidate_id,
        "holdout_generation_id": run_manifest["test_holdout_generation_id"],
        "environment_gate_rule": "PASS_ALL_PREDECLARED_ENVIRONMENTS_AND_NONZERO_CANDIDATE_EXPOSURE",
        "environment_pass": environment_pass,
        "candidate_exposure_validity": {
            "status": "PASS" if performance_interpretable else "INCONCLUSIVE_ZERO_EXPOSURE",
            "zero_exposure_environments": zero_exposure,
            "coverage": coverage,
        },
        "performance_gate_interpretable": performance_interpretable,
        "outcome": "CONFIRM_FINALIST" if confirmed else "RETAIN_REFERENCE",
        "promotion_authorized": confirmed,
        "test_used_for_selection": False,
        "test_consumed": True,
        "retuning_authorized": False,
        "alternative_selection_authorized": False,
        "interpretation": (
            "Frozen VALIDATION finalist confirmed on the one-shot TEST generation."
            if confirmed
            else (
                "TEST consumed but candidate exposure was insufficient; reference retained."
                if not performance_interpretable
                else "TEST consumed and at least one frozen environment failed; reference retained."
            )
        ),
        "environment_summaries": {
            environment_id: {
                "delta_bb_per_100": by_id[environment_id]["paired"]["observed_delta_bb_per_100"],
                "ci95_bb_per_100": by_id[environment_id]["paired"]["ci95_bb_per_100"],
                "supported_decision_rate": coverage[environment_id]["supported_decision_rate"],
                "out_of_support_decision_rate": coverage[environment_id]["out_of_support_decision_rate"],
            }
            for environment_id in expected
        },
    }


def consume_holdout_ledger(
    ledger: Mapping[str, Any],
    *,
    generation_id: str,
    cycle_id: str,
    finalist_id: str,
    consumed_at_commit: str,
) -> dict[str, Any]:
    value = json.loads(json.dumps(ledger))
    rows = [
        row
        for row in value.get("generations") or []
        if str((row or {}).get("generation_id") or "") == generation_id
    ]
    _need(len(rows) == 1, f"holdout generation {generation_id!r} not uniquely defined")
    row = rows[0]
    _need(row.get("status") == "UNCONSUMED", "holdout generation already consumed")
    row["status"] = "CONSUMED"
    row["consumed_by_cycle"] = str(cycle_id)
    row["consumed_by_frozen_finalist"] = str(finalist_id)
    row["consumed_at_commit"] = str(consumed_at_commit)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare-test")
    prepare.add_argument("--population", required=True)
    prepare.add_argument("--profiles", type=Path, required=True)
    prepare.add_argument("--archive", type=Path, action="append", required=True)
    prepare.add_argument("--certification", type=Path, required=True)
    prepare.add_argument("--seed", type=int, default=20260917)
    prepare.add_argument("--code-sha", required=True)
    prepare.add_argument("--candidate-source-commit", required=True)
    prepare.add_argument("--candidate", type=Path, required=True)
    prepare.add_argument("--binding", type=Path, required=True)
    prepare.add_argument("--validation-run-manifest", type=Path, required=True)
    prepare.add_argument("--validation-selection", type=Path, required=True)
    prepare.add_argument("--holdout-ledger", type=Path, default=DEFAULT_LEDGER)
    prepare.add_argument("--holdout-generation-id", required=True)
    prepare.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    prepare.add_argument("--reference-descriptor", type=Path, default=DEFAULT_REFERENCE)
    prepare.add_argument("--sensitivity", type=Path, default=DEFAULT_SENSITIVITY)
    prepare.add_argument("--hero", default="RoiDePiqueNique")
    prepare.add_argument("--scenarios-out", type=Path, required=True)
    prepare.add_argument("--run-manifest-out", type=Path, required=True)

    environment = sub.add_parser("run-environment")
    environment.add_argument("--scenarios", type=Path, required=True)
    environment.add_argument("--run-manifest", type=Path, required=True)
    environment.add_argument("--environment-id", required=True)
    environment.add_argument("--reference-behavior", type=Path, required=True)
    environment.add_argument("--issue-104-result", type=Path, required=True)
    environment.add_argument("--candidate", type=Path, required=True)
    environment.add_argument("--binding", type=Path, required=True)
    environment.add_argument("--reference-descriptor", type=Path, default=DEFAULT_REFERENCE)
    environment.add_argument("--sensitivity", type=Path, default=DEFAULT_SENSITIVITY)
    environment.add_argument("--output", type=Path, required=True)

    select = sub.add_parser("select-test")
    select.add_argument("--run-manifest", type=Path, required=True)
    select.add_argument("--report", type=Path, action="append", required=True)
    select.add_argument("--output", type=Path, required=True)
    select.add_argument("--holdout-ledger", type=Path, default=DEFAULT_LEDGER)
    select.add_argument("--consumed-ledger-out", type=Path, required=True)
    select.add_argument("--cycle-id", required=True)
    select.add_argument("--consumed-at-commit", required=True)

    args = parser.parse_args()
    if args.command == "prepare-test":
        scenarios, run = build_test_run(
            population_id=args.population,
            profiles_path=args.profiles,
            archives=args.archive,
            certification=args.certification,
            master_seed=args.seed,
            code_commit_sha=args.code_sha,
            candidate_source_commit_sha=args.candidate_source_commit,
            candidate_path=args.candidate,
            binding_path=args.binding,
            validation_run_path=args.validation_run_manifest,
            validation_selection_path=args.validation_selection,
            holdout_ledger_path=args.holdout_ledger,
            holdout_generation_id=args.holdout_generation_id,
            contract_path=args.contract,
            reference_path=args.reference_descriptor,
            sensitivity_path=args.sensitivity,
            hero=args.hero,
        )
        write_json(args.scenarios_out, scenarios)
        _need(
            sha256_file(args.scenarios_out) == run["identities"]["scenario_manifest_sha256"],
            "persisted TEST scenario hash drifted",
        )
        write_json(args.run_manifest_out, run)
        print(json.dumps({"scenarios": len(scenarios["scenarios"]), "run": run}, indent=2, sort_keys=True))
        return 0

    if args.command == "run-environment":
        report = run_test_environment(
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
        }, indent=2, sort_keys=True))
        return 0

    run = load_json(args.run_manifest)
    result = select_test_confirmation([load_json(path) for path in args.report], run)
    write_json(args.output, result)
    consumed = consume_holdout_ledger(
        load_json(args.holdout_ledger),
        generation_id=str(run["test_holdout_generation_id"]),
        cycle_id=args.cycle_id,
        finalist_id=str(run["identities"]["candidate_id"]),
        consumed_at_commit=args.consumed_at_commit,
    )
    write_json(args.consumed_ledger_out, consumed)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
