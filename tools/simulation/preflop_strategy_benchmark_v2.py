#!/usr/bin/env python3
"""Executable paired VALIDATION benchmark for frozen preflop strategy contract v2.

This module intentionally exposes no automatic TEST path.  It prepares one
certified VALIDATION scenario manifest, freezes the run identities before any
policy result is produced, evaluates reference/candidate on identical scenarios
inside one predeclared Model-B sensitivity environment, and aggregates paired
candidate-minus-reference deltas with hand-id clustered bootstrap intervals.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from tools.populations.registry import resolve_population
from tools.simulation.full_hand_arena import run_full_hand
from tools.simulation.full_hand_benchmark import ProfileSource, build_manifest_from_archives
from tools.simulation.full_hand_scenarios import eligible_table_templates
from tools.simulation.game_core import EPS, NoLimitHoldemState
from tools.simulation.hero_preflop_overlay import (
    POLICY_BINDING_SCHEMA,
    ExactHeroPreflopOverlayPolicy,
    canonical_preflop_context,
)
from tools.simulation.model_a_continuation import ModelAContinuationPolicy
from tools.simulation.model_b_runtime import rake_net
from tools.simulation.model_b_sensitivity import ModelBSensitivityPolicy, load_sensitivity_set
from tools.training.independent_profiles.reveal_aware_ranges import certified_records
from tools.training.validate_preflop_strategy_benchmark_v2 import validate_run_manifest

ROOT = Path(__file__).resolve().parents[2]
RUN_SCHEMA = "poker-preflop-strategy-benchmark-run/v2"
ENV_REPORT_SCHEMA = "poker-preflop-strategy-environment-report/v2"
SELECTION_SCHEMA = "poker-preflop-strategy-validation-selection/v2"
DEFAULT_CONTRACT = ROOT / "training/full_hand/PREFLOP_STRATEGY_BENCHMARK_CONTRACT_20260917.json"
DEFAULT_REFERENCE = ROOT / "training/full_hand/HERO_REFERENCE_POLICY_20260917.json"
DEFAULT_SENSITIVITY = ROOT / "training/full_hand/MODEL_B_SENSITIVITY_ENVIRONMENTS_20260917.json"
DEFAULT_CANDIDATE = ROOT / "training/runs/20260917_hero_preflop_169_btn_unopened_pfc_v1/HERO_RANGE_REPOSITORY_PFC.json"
DEFAULT_BINDING = ROOT / "training/runs/20260917_hero_preflop_169_btn_unopened_pfc_v1/PFC_BINDING.json"
PFC_BINDING_SCHEMA = "poker-hero-range-pfc-binding/v1"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def candidate_binding_identity(binding_path: Path, candidate_path: Path) -> dict[str, str]:
    """Validate one frozen #107 binding and return content-addressed identities.

    Legacy exact-PFC bindings and the new exact-PFPC policy binding are both
    accepted.  The policy binding itself is always hashed so future runs can
    prove that the PFPC -> source-PFC authorization map did not drift after the
    run identity was frozen.
    """
    binding_path = Path(binding_path)
    candidate_path = Path(candidate_path)
    binding = load_json(binding_path)
    schema = str(binding.get("schema") or "")
    if schema == PFC_BINDING_SCHEMA:
        expected_candidate_sha = str(
            (binding.get("artifact_sha256") or {}).get("hero_range_repository_pfc") or ""
        )
    elif schema == POLICY_BINDING_SCHEMA:
        expected_candidate_sha = str(binding.get("repository_sha256") or "")
    else:
        raise ValueError(f"unsupported #107 candidate binding schema {schema!r}")

    actual_candidate_sha = sha256_file(candidate_path)
    if actual_candidate_sha != expected_candidate_sha:
        raise ValueError("candidate repository hash differs from frozen #107 binding")
    if binding.get("promotion_authorized") is not False:
        raise ValueError("#107 candidate binding must remain non-promoted")
    boundary = binding.get("selection_boundary") or {}
    if boundary.get("validation_consumed") is not False:
        raise ValueError("#107 candidate binding must precede VALIDATION consumption")
    if boundary.get("test_consumed") is not False:
        raise ValueError("#107 candidate binding unexpectedly consumed TEST")
    candidate_id = str(binding.get("run_id") or "")
    if not candidate_id:
        raise ValueError("#107 candidate binding must freeze run_id")

    return {
        "candidate_id": candidate_id,
        "candidate_artifact_sha256": actual_candidate_sha,
        "candidate_binding_sha256": sha256_file(binding_path),
        "candidate_binding_schema": schema,
    }


def candidate_policy_binding_path(
    binding_path: Path,
    candidate_path: Path,
    run_manifest: Mapping[str, Any],
) -> Path | None:
    """Revalidate frozen candidate/binding identities and select runtime mode."""
    actual = candidate_binding_identity(binding_path, candidate_path)
    frozen = dict(run_manifest.get("identities") or {})
    for field in ("candidate_id", "candidate_artifact_sha256"):
        if str(frozen.get(field) or "") != str(actual[field]):
            raise ValueError(f"{field} changed after run identity freeze")

    frozen_binding_sha = frozen.get("candidate_binding_sha256")
    frozen_binding_schema = frozen.get("candidate_binding_schema")
    if frozen_binding_sha is not None and str(frozen_binding_sha) != actual["candidate_binding_sha256"]:
        raise ValueError("candidate binding changed after run identity freeze")
    if frozen_binding_schema is not None and str(frozen_binding_schema) != actual["candidate_binding_schema"]:
        raise ValueError("candidate binding schema changed after run identity freeze")

    if actual["candidate_binding_schema"] == POLICY_BINDING_SCHEMA:
        return Path(binding_path)
    return None


def _certified_eligible_count(
    *,
    population_id: str,
    archives: Sequence[Path],
    certification: Path,
    split: str,
    hero: str,
) -> tuple[int, dict[str, Any]]:
    population = resolve_population(ROOT, population_id)
    certified, certification_summary = certified_records(
        [Path(path) for path in archives],
        {str(population["identity"]["stake"])},
        Path(certification),
    )
    allowed = {str(record.hand_id) for record in certified}
    templates, source = eligible_table_templates(
        population_id=population_id,
        hero=hero,
        split=split,
        root=ROOT,
        archives=[Path(path) for path in archives],
    )
    eligible = [row for row in templates if str(row["source_hand_id"]) in allowed]
    if not eligible:
        raise ValueError("no certified eligible full-hand templates")
    split_count = int((certification_summary.get("split_counts") or {}).get(str(split).upper(), 0))
    return len(eligible), {
        "certified_split_hands": split_count,
        "simulatable_certified_templates": len(eligible),
        "excluded_before_simulation": split_count - len(eligible),
        "eligible_template_ids_sha256": hashlib.sha256(
            "\n".join(sorted(str(row["source_hand_id"]) for row in eligible)).encode("utf-8")
        ).hexdigest(),
        "source_audit": source.get("audit") or {},
    }


def build_validation_run(
    *,
    population_id: str,
    profiles_path: Path,
    archives: Sequence[Path],
    certification: Path,
    master_seed: int,
    code_commit_sha: str,
    candidate_source_commit_sha: str,
    contract_path: Path = DEFAULT_CONTRACT,
    reference_path: Path = DEFAULT_REFERENCE,
    sensitivity_path: Path = DEFAULT_SENSITIVITY,
    candidate_path: Path = DEFAULT_CANDIDATE,
    binding_path: Path = DEFAULT_BINDING,
    hero: str = "RoiDePiqueNique",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Freeze scenarios and run identities before any strategy result exists."""
    contract = load_json(contract_path)
    sensitivity = load_sensitivity_set(sensitivity_path)
    binding_identity = candidate_binding_identity(binding_path, candidate_path)
    if contract.get("population", {}).get("population_id") != population_id:
        raise ValueError("benchmark population does not match frozen contract")

    count, eligibility = _certified_eligible_count(
        population_id=population_id,
        archives=archives,
        certification=certification,
        split="VALIDATION",
        hero=hero,
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
        split="VALIDATION",
        hero=hero,
        root=ROOT,
    )
    if scenario_manifest.get("split") != "VALIDATION":
        raise AssertionError("scenario builder crossed the frozen holdout boundary")
    scenario_manifest["eligibility"] = eligibility
    scenario_sha = hashlib.sha256(
        (json.dumps(scenario_manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    ).hexdigest()

    environment_ids = [str(row["environment_id"]) for row in sensitivity["environments"]]
    run_manifest = {
        "schema": RUN_SCHEMA,
        "contract_version": contract["contract_version"],
        "phase": "VALIDATION",
        "results_inspected": False,
        "test_data_read": False,
        "identities": {
            "code_commit_sha": str(code_commit_sha),
            "dataset_population_fingerprint_sha256": contract["population"]["population_fingerprint_sha256"],
            "scenario_manifest_sha256": scenario_sha,
            "reference_descriptor_sha256": sha256_file(reference_path),
            "candidate_id": binding_identity["candidate_id"],
            "candidate_artifact_sha256": binding_identity["candidate_artifact_sha256"],
            "candidate_binding_sha256": binding_identity["candidate_binding_sha256"],
            "candidate_binding_schema": binding_identity["candidate_binding_schema"],
            "candidate_source_commit_sha": str(candidate_source_commit_sha),
            "model_b_sensitivity_descriptor_sha256": sha256_file(sensitivity_path),
            "model_b_base_artifact_sha256": contract["environment_sensitivity"]["base_artifact_sha256"],
            "model_b_environment_ids": environment_ids,
        },
        "budgets": {
            "master_seed": int(master_seed),
            "rollouts_per_base_hand": reps,
            "bootstrap_samples": int(contract["statistics"]["bootstrap_samples"]),
            "certified_validation_hands": int(eligibility["certified_split_hands"]),
            "simulatable_validation_hands": int(count),
            "simulated_scenarios_per_policy_environment": int(count * reps),
        },
        "thresholds": {
            "validation_ci95_lower_bb_per_100": contract["validation_selection"]["required_ci95_lower_bound_bb_per_100"],
            "test_ci95_lower_bb_per_100": contract["test_confirmation"]["required_ci95_lower_bound_bb_per_100"],
            "environment_gate_rule": contract["validation_selection"]["minimum_environment_gate_rule"],
        },
        "selection_boundary": {
            "candidate_frozen_before_validation": True,
            "scenario_manifest_frozen_before_policy_results": True,
            "test_visible": False,
            "test_consumed": False,
        },
    }
    check = validate_run_manifest(contract, sensitivity, run_manifest)
    if check["status"] != "PASS":
        raise ValueError("invalid frozen VALIDATION run manifest: " + "; ".join(check["errors"]))
    return scenario_manifest, run_manifest


def _reference_policy(descriptor_path: Path) -> ModelAContinuationPolicy:
    descriptor = load_json(descriptor_path)
    artifacts = descriptor["artifacts"]
    return ModelAContinuationPolicy.from_paths(
        ROOT / artifacts["preflop_model"]["path"],
        ROOT / artifacts["postflop_baseline"]["path"],
        ROOT / artifacts["postflop_selected_overlay"]["path"],
    )


def _first_hero_preflop_context(result: Mapping[str, Any]) -> dict[str, Any] | None:
    hero = str(result["hero"])
    for row in result.get("trace", []):
        if row.get("street") != "preflop" or str(row.get("actor")) != hero:
            continue
        state = NoLimitHoldemState.from_snapshot(row["public_state_before"])
        return canonical_preflop_context(state, hero)
    return None


def _hero_preflop_jam(result: Mapping[str, Any]) -> bool:
    hero = str(result["hero"])
    for row in result.get("trace", []):
        if row.get("street") != "preflop" or str(row.get("actor")) != hero:
            continue
        if str(row.get("action")) != "RAISE":
            continue
        state = NoLimitHoldemState.from_snapshot(row["public_state_before"])
        view = state.legal_view(hero)
        target = row.get("target_total_bb")
        if target is not None and abs(float(target) - float(view["max_raise_to_bb"])) <= 1e-6:
            return True
    return False


def _hero_all_in_preflop(result: Mapping[str, Any]) -> bool:
    hero = str(result["hero"])
    return any(
        row.get("street") == "preflop"
        and str(row.get("actor")) == hero
        and bool(row.get("actor_all_in_after"))
        for row in result.get("trace", [])
    )


def _stack_bucket(value: float | None) -> str:
    if value is None:
        return "NO_HERO_PREFLOP_DECISION"
    value = float(value)
    if value <= 40:
        return "LE40"
    if value <= 75:
        return "GT40_LE75"
    if value <= 125:
        return "GT75_LE125"
    return "GT125"


def _row_from_pair(
    scenario: Mapping[str, Any],
    reference_result: Mapping[str, Any],
    candidate_result: Mapping[str, Any],
    candidate_audit: Mapping[str, Any],
) -> dict[str, Any]:
    if reference_result["scenario_id"] != candidate_result["scenario_id"]:
        raise AssertionError("paired results lost scenario identity")
    hero = str(scenario["hero"])
    pfc = _first_hero_preflop_context(reference_result)
    history = [] if pfc is None else list(pfc.get("history") or [])
    raises = [row for row in history if row.get("action") in {"RAISE", "JAM"}]
    first_raise = next((i for i, row in enumerate(history) if row.get("action") in {"RAISE", "JAM"}), None)
    limpers = sum(1 for row in history if row.get("action") == "LIMP")
    callers = 0 if first_raise is None else sum(1 for row in history[first_raise + 1 :] if row.get("action") == "CALL")
    ref_net = float(reference_result["hero_net_bb"])
    cand_net = float(candidate_result["hero_net_bb"])
    return {
        "scenario_id": str(scenario["scenario_id"]),
        "hand_id": str(scenario.get("cluster_id") or scenario.get("source_hand_id")),
        "rep": int(scenario.get("rep", 0)),
        "hero_position": str((scenario.get("positions") or {}).get(hero, "NA")),
        "preflop_context_id": None if pfc is None else pfc["context_id"],
        "preflop_family": "NO_HERO_PREFLOP_DECISION" if pfc is None else pfc["family"],
        "limper_count": int(limpers),
        "caller_count": int(callers),
        "raise_level": 0 if pfc is None else int(pfc["raise_level"]),
        "effective_stack_bb": None if pfc is None else float(pfc["effective_stack_bb"]),
        "stack_depth_bucket": _stack_bucket(None if pfc is None else pfc["effective_stack_bb"]),
        "reference_net_bb": ref_net,
        "candidate_net_bb": cand_net,
        "delta_bb": cand_net - ref_net,
        "candidate_audit": dict(candidate_audit),
        "reference_outcome": {
            "players_to_flop": int(reference_result["coverage"]["players_to_flop"]),
            "won_without_flop": bool(not reference_result["coverage"]["reached_flop"] and ref_net > EPS),
            "all_in_preflop": _hero_all_in_preflop(reference_result),
            "hero_jam_preflop": _hero_preflop_jam(reference_result),
            "side_pot": bool(reference_result["coverage"]["side_pot"]),
        },
        "candidate_outcome": {
            "players_to_flop": int(candidate_result["coverage"]["players_to_flop"]),
            "won_without_flop": bool(not candidate_result["coverage"]["reached_flop"] and cand_net > EPS),
            "all_in_preflop": _hero_all_in_preflop(candidate_result),
            "hero_jam_preflop": _hero_preflop_jam(candidate_result),
            "side_pot": bool(candidate_result["coverage"]["side_pot"]),
        },
    }


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("quantile requires values")
    position = (len(sorted_values) - 1) * float(probability)
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return float(sorted_values[low])
    weight = position - low
    return float(sorted_values[low]) * (1.0 - weight) + float(sorted_values[high]) * weight


def paired_cluster_bootstrap(
    rows: Sequence[Mapping[str, Any]],
    *,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    clusters: dict[str, list[float]] = collections.defaultdict(list)
    for row in rows:
        clusters[str(row["hand_id"])].append(float(row["delta_bb"]))
    if not clusters:
        raise ValueError("paired bootstrap requires at least one hand cluster")
    cluster_means = {key: statistics.fmean(values) for key, values in clusters.items()}
    keys = sorted(cluster_means)
    observed = statistics.fmean(cluster_means.values()) * 100.0
    rng = random.Random(int(seed))
    draws: list[float] = []
    for _ in range(int(samples)):
        selected = rng.choices(keys, k=len(keys))
        draws.append(statistics.fmean(cluster_means[key] for key in selected) * 100.0)
    draws.sort()
    return {
        "cluster_unit": "hand_id",
        "independent_hands": len(keys),
        "observations": len(rows),
        "repetitions_per_hand": dict(sorted(collections.Counter(str(row["hand_id"]) for row in rows).items())).popitem()[1]
        if len(set(collections.Counter(str(row["hand_id"]) for row in rows).values())) == 1
        else None,
        "observed_delta_bb_per_100": observed,
        "ci95_bb_per_100": [_quantile(draws, 0.025), _quantile(draws, 0.975)],
        "bootstrap_samples": int(samples),
        "bootstrap_seed": int(seed),
    }


def _delta_groups(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[float]] = collections.defaultdict(list)
    for row in rows:
        groups[str(row.get(key))].append(float(row["delta_bb"]))
    return {
        name: {"scenarios": len(values), "delta_bb_per_100": statistics.fmean(values) * 100.0}
        for name, values in sorted(groups.items())
    }


def _policy_outcomes(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    payloads = [dict(row[key]) for row in rows]
    n = len(payloads)
    players = collections.Counter(str(row["players_to_flop"]) for row in payloads)
    return {
        "scenarios": n,
        "players_to_flop": dict(sorted(players.items())),
        "won_without_flop_rate": sum(bool(row["won_without_flop"]) for row in payloads) / n,
        "all_in_preflop_rate": sum(bool(row["all_in_preflop"]) for row in payloads) / n,
        "jam_frequency": sum(bool(row["hero_jam_preflop"]) for row in payloads) / n,
        "side_pot_frequency": sum(bool(row["side_pot"]) for row in payloads) / n,
    }


def summarize_environment_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    environment: Mapping[str, Any],
    candidate_id: str,
    bootstrap_samples: int,
    bootstrap_seed: int,
    threshold: float,
) -> dict[str, Any]:
    stats = paired_cluster_bootstrap(rows, samples=bootstrap_samples, seed=bootstrap_seed)
    audits = [dict(row.get("candidate_audit") or {}) for row in rows]
    total_preflop = sum(int(row.get("hero_preflop_decisions", 0)) for row in audits)
    supported = sum(int(row.get("candidate_supported_decisions", 0)) for row in audits)
    out = sum(int(row.get("candidate_out_of_support_decisions", 0)) for row in audits)
    if supported + out != total_preflop:
        raise AssertionError("candidate support accounting does not cover every Hero preflop decision")
    low = float(stats["ci95_bb_per_100"][0])
    return {
        "schema": ENV_REPORT_SCHEMA,
        "phase": "VALIDATION",
        "candidate_id": candidate_id,
        "environment": dict(environment),
        "paired": stats,
        "gate": {
            "required_ci95_lower_bound_bb_per_100": float(threshold),
            "pass": low >= float(threshold),
        },
        "candidate_coverage": {
            "hero_preflop_decisions": total_preflop,
            "supported_decisions": supported,
            "out_of_support_decisions": out,
            "supported_decision_rate": None if total_preflop == 0 else supported / total_preflop,
            "out_of_support_decision_rate": None if total_preflop == 0 else out / total_preflop,
        },
        "breakdowns": {
            "position": _delta_groups(rows, "hero_position"),
            "preflop_family": _delta_groups(rows, "preflop_family"),
            "limper_count": _delta_groups(rows, "limper_count"),
            "caller_count": _delta_groups(rows, "caller_count"),
            "stack_depth_bucket": _delta_groups(rows, "stack_depth_bucket"),
            "reference_outcomes": _policy_outcomes(rows, "reference_outcome"),
            "candidate_outcomes": _policy_outcomes(rows, "candidate_outcome"),
        },
        "rows": list(rows),
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
        raise ValueError("#108 executable currently accepts VALIDATION only")
    if run_manifest.get("test_data_read") is not False:
        raise ValueError("VALIDATION run manifest must prove TEST was not read")
    scenario_sha = hashlib.sha256(
        (json.dumps(scenario_manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    ).hexdigest()
    if scenario_sha != run_manifest["identities"]["scenario_manifest_sha256"]:
        raise ValueError("scenario manifest content changed after run identity freeze")

    policy_binding_path = candidate_policy_binding_path(
        binding_path, candidate_path, run_manifest
    )
    reference = _reference_policy(reference_descriptor_path)
    opponent = ModelBSensitivityPolicy.from_paths(
        reference_behavior_path,
        issue_104_result_path,
        environment_id=environment_id,
        sensitivity_path=sensitivity_path,
    )
    candidate = ExactHeroPreflopOverlayPolicy.from_path(
        candidate_path,
        reference_policy=reference,
        candidate_id=str(run_manifest["identities"]["candidate_id"]),
        policy_binding_path=policy_binding_path,
    )
    if candidate.repository_sha256 != run_manifest["identities"]["candidate_artifact_sha256"]:
        raise ValueError("candidate repository changed after run identity freeze")

    rows = []
    for scenario in scenario_manifest.get("scenarios", []):
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
        rows.append(
            _row_from_pair(
                scenario,
                reference_result,
                candidate_result,
                candidate.scenario_audit(str(scenario["scenario_id"])),
            )
        )
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
    report["candidate_policy_identity"] = candidate.identity()
    return report


def select_validation(reports: Sequence[Mapping[str, Any]], run_manifest: Mapping[str, Any]) -> dict[str, Any]:
    expected = list(run_manifest["identities"]["model_b_environment_ids"])
    by_id = {str(report["environment"]["environment_id"]): report for report in reports}
    if set(by_id) != set(expected):
        raise ValueError(f"environment report set mismatch: expected {expected}, got {sorted(by_id)}")
    candidate_id = str(run_manifest["identities"]["candidate_id"])
    if any(str(row.get("candidate_id")) != candidate_id for row in reports):
        raise ValueError("environment reports compare different candidates")
    passes = {environment_id: bool(by_id[environment_id]["gate"]["pass"]) for environment_id in expected}
    pass_all = all(passes.values())
    outcome = "FREEZE_FINALIST" if pass_all else "RETAIN_REFERENCE"
    return {
        "schema": SELECTION_SCHEMA,
        "phase": "VALIDATION",
        "contract_version": run_manifest["contract_version"],
        "candidate_id": candidate_id,
        "environment_gate_rule": "PASS_ALL_PREDECLARED_ENVIRONMENTS",
        "environment_pass": passes,
        "outcome": outcome,
        "frozen_finalist": candidate_id if pass_all else None,
        "test_authorized": pass_all,
        "test_used_for_selection": False,
        "test_consumed": False,
        "promotion_authorized": False,
        "interpretation": (
            "Candidate may proceed, unchanged, to the separately authorized TEST confirmation."
            if pass_all
            else "Reference retained; TEST remains unconsumed and active strategy pointers must remain unchanged."
        ),
        "environment_summaries": {
            environment_id: {
                "delta_bb_per_100": by_id[environment_id]["paired"]["observed_delta_bb_per_100"],
                "ci95_bb_per_100": by_id[environment_id]["paired"]["ci95_bb_per_100"],
                "supported_decision_rate": by_id[environment_id]["candidate_coverage"]["supported_decision_rate"],
                "out_of_support_decision_rate": by_id[environment_id]["candidate_coverage"]["out_of_support_decision_rate"],
            }
            for environment_id in expected
        },
    }


def _cmd_prepare(args: argparse.Namespace) -> int:
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
    # Recompute the persisted-file hash, which must equal the precomputed identity.
    persisted_sha = sha256_file(args.scenarios_out)
    if persisted_sha != run["identities"]["scenario_manifest_sha256"]:
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
        "coverage": report["candidate_coverage"],
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

    prepare = sub.add_parser("prepare-validation", help="freeze VALIDATION scenarios and identities")
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

    environment = sub.add_parser("run-environment", help="evaluate one frozen Model-B environment")
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

    select = sub.add_parser("select-validation", help="apply the predeclared all-environment VALIDATION gate")
    select.add_argument("--run-manifest", type=Path, required=True)
    select.add_argument("--report", type=Path, action="append", required=True)
    select.add_argument("--output", type=Path, required=True)
    select.set_defaults(func=_cmd_select)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
