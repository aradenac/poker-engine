#!/usr/bin/env python3
"""Issue #358 real Hero preflop generation for READY non-ISO #269 contexts.

The generator is intentionally exact-only:
- source contexts are a mechanical READY subset of #269;
- representative public states come from certified TRAIN hands only;
- no private/showdown/future cards are used to select representatives;
- legal alternatives come from the shared NoLimitHoldemState core;
- raise sizing support comes from exact-node certified TRAIN observations;
- EV uses #198 paired/adaptive common random worlds;
- #277 content-addressed artifacts are finalized only for contexts with 169/169
  materializable cells;
- #287 import is performed separately and can stay inactive.

VALIDATION and TEST data are never read by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.model_a_continuation import ModelAContinuationPolicy
from tools.simulation.model_a_preflop_rollout import ModelAPreflopContinuationRollout
from tools.simulation.model_a_support_closure import SupportClosedModelAContinuationPolicy
from tools.simulation.paired_adaptive_preflop_ev import AdaptiveBudget
from tools.simulation.paired_preflop_grid_evaluator import (
    bridge_integration_file,
    evaluate_preflop_grid_paired,
)
from tools.training import generate_hero_range_decisions as base
from tools.training.audit_hero_preflop_coverage import (
    callers_after_first_raise,
    coverage_group,
    aggressors,
    limpers_before_first_raise,
    load_train_records,
)
from tools.training.generate_certified_hero_range_decisions import observed_raise_targets
from tools.training.increment_decisions import decision_rows, norm_pos, parse_hand
from tools.training.validate_hero_preflop_generation import (
    CANONICAL_HAND_CLASSES,
    canonical_json_bytes,
    load_json,
    sha256_path,
    validate_generation,
)

SCHEMA = "poker-hero-preflop-noniso-generation/v1"
SCOPE_SCHEMA = "poker-hero-preflop-noniso-scope/v1"
REP_SCHEMA = "poker-hero-preflop-representatives/v1"
PART_SCHEMA = "poker-hero-preflop-generation-part/v1"
RESULT_SCHEMA = "poker-hero-preflop-noniso-generation-result/v1"
GENERATION_ID = "20260919_HERO_PREFLOP_NONISO_READY_V1"
CANDIDATE_ID = "HERO_PREFLOP_NONISO_READY_CANDIDATE_V1"
GENERATOR_VERSION = "hero-preflop-noniso-paired-adaptive/1"
ENV_SLOT = "env:ISSUE358_NONISO_V1"
PARAMS_SLOT = "params:ISSUE358_NONISO_V1"
MASTER_SEED = 20260919
HAND_SHARDS = 8
ALLOWED_GROUPS = (
    "VS_RFI",
    "RFI_CALLERS_SQUEEZE",
    "VS_3BET",
    "VS_4BET_OR_JAM",
)
FORBIDDEN_GROUPS = ("VS_LIMPERS_ISO",)
DEFAULT_PLAN = ROOT / "analysis/hero_preflop_generation_plan.json"
DEFAULT_AUDIT = ROOT / "analysis/hero_preflop_coverage_train.json"
DEFAULT_CERTIFICATION = ROOT / "training/datasets/NLHE_100-200/population_certification.json"


def write_json(path: Path, value: object) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def scope_from_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if plan.get("schema") != "poker-hero-preflop-generation-plan/v1":
        raise ValueError("unexpected #269 plan schema")
    ready_order = list(plan.get("generation_order") or [])
    by_id = {str(row["context_id"]): row for row in plan.get("contexts") or []}
    eligible: list[dict[str, Any]] = []
    excluded_ready: list[dict[str, Any]] = []
    for context_id in ready_order:
        row = by_id[context_id]
        group = str(row["coverage_group"])
        if row.get("readiness") != "READY_FOR_GENERATION":
            raise AssertionError("generation_order contains non-READY context")
        if group in ALLOWED_GROUPS:
            eligible.append(dict(row))
        else:
            excluded_ready.append({
                "context_id": context_id,
                "coverage_group": group,
                "family": row["family"],
                "reason": "EXCLUDED_BY_ISSUE_358_SCOPE",
            })
    if any(row["coverage_group"] in FORBIDDEN_GROUPS for row in eligible):
        raise AssertionError("VS_LIMPERS/ISO leaked into issue #358 scope")
    counts: dict[str, int] = {}
    for row in eligible:
        counts[str(row["coverage_group"])] = counts.get(str(row["coverage_group"]), 0) + 1
    return {
        "schema": SCOPE_SCHEMA,
        "issue": 358,
        "parent_issue": 196,
        "population_id": plan["population_id"],
        "source_plan_sha256": sha256_path(DEFAULT_PLAN),
        "source_train_audit_sha256": str((plan.get("source") or {}).get("sha256") or ""),
        "allowed_groups": list(ALLOWED_GROUPS),
        "forbidden_groups": list(FORBIDDEN_GROUPS),
        "eligible_context_ids": [row["context_id"] for row in eligible],
        "eligible_context_count": len(eligible),
        "eligible_hand_class_cells": len(eligible) * 169,
        "eligible_group_counts": dict(sorted(counts.items())),
        "excluded_ready": excluded_ready,
        "test_consumed": False,
        "nearest_context_allowed": False,
    }


def _source_key(row: Mapping[str, Any]) -> str:
    history = list(row.get("history") or [])
    aggs = aggressors(history)
    payload = {
        "family": row["family"],
        "actor_position": row["actor_position"],
        "opener_position": aggs[0] if aggs else None,
        "last_aggressor_position": aggs[-1] if aggs else None,
        "callers_after_first_raise": callers_after_first_raise(history),
        "limpers_before_first_raise": limpers_before_first_raise(history),
        "facing_jam": bool(history and history[-1].get("action") == "JAM"),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _voluntary_actions(hand: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    by = hand["by"]
    return [
        row
        for row in hand["streets"]["preflop"]
        if row.get("type") in {"fold", "check", "call", "raise", "bet"}
        and row.get("player") in by
    ]


def _replay_before(hand: Mapping[str, Any], target_index: int) -> NoLimitHoldemState:
    players = list(hand["players"])
    if len(players) != 6:
        raise ValueError("representative hand is not six-handed")
    bb = float(hand["bb"])
    if bb <= 0:
        raise ValueError("invalid big blind")
    position_to_player: dict[str, Mapping[str, Any]] = {}
    for player in players:
        position = norm_pos(player["pos"], 6)
        if position in position_to_player:
            raise ValueError("duplicate position")
        position_to_player[position] = player
    expected = set(base.DEFAULT_SEATS)
    if set(position_to_player) != expected:
        raise ValueError(f"representative positions {sorted(position_to_player)} != {sorted(expected)}")
    stacks = {
        position: float(player["chips"]) / bb
        for position, player in position_to_player.items()
    }
    state = NoLimitHoldemState(
        seats=base.DEFAULT_SEATS,
        button="BTN",
        stacks_bb=stacks,
    )
    actions = _voluntary_actions(hand)
    if not (0 <= target_index < len(actions)):
        raise ValueError("target action index outside preflop actions")
    by_name = hand["by"]
    for index, row in enumerate(actions):
        actor = norm_pos(by_name[row["player"]]["pos"], 6)
        if index == target_index:
            if state.next_actor != actor:
                raise ValueError(f"target actor drift {state.next_actor!r} != {actor!r}")
            return state
        if state.next_actor != actor:
            raise ValueError(f"public replay actor drift {state.next_actor!r} != {actor!r}")
        kind = str(row["type"])
        if kind == "fold":
            state.apply_action(actor, "FOLD")
        elif kind == "check":
            state.apply_action(actor, "CHECK")
        elif kind == "call":
            state.apply_action(actor, "CALL")
        elif kind in {"raise", "bet"}:
            target = float(state.street_committed_bb[actor]) + float(row["raw"]) / bb
            state.apply_action(actor, "RAISE", target_total_bb=target)
        else:
            raise AssertionError(kind)
    raise ValueError("target action not reached")


def _public_row_matches_state(row: Mapping[str, Any], state: NoLimitHoldemState) -> None:
    view = state.legal_view(state.next_actor)
    checks = {
        "pot_before_bb": (float(row["pot_before_bb"]), float(view["pot_before_bb"])),
        "to_call_bb": (float(row["to_call_bb"]), float(view["to_call_bb"])),
        "current_price_bb": (float(row["current_price_bb"]), float(view["current_price_bb"])),
    }
    for name, (expected, actual) in checks.items():
        if abs(expected - actual) > 1e-6:
            raise ValueError(f"{name} replay mismatch {actual} != {expected}")
    pfc = row.get("preflop_context_v1") or {}
    if str(pfc.get("family") or row.get("family") or "") != str(row.get("family") or ""):
        raise ValueError("preflop context family drift")
    if str(pfc.get("actor_position") or "") != str(row.get("actor_position") or ""):
        raise ValueError("actor position drift")


def prepare_representatives(
    plan_path: Path,
    certification_path: Path,
) -> dict[str, Any]:
    plan = load_json(plan_path)
    scope = scope_from_plan(plan)
    plan_by_source = {
        str(row["source_matrix_key"]): row
        for row in plan.get("contexts") or []
        if row["context_id"] in set(scope["eligible_context_ids"])
    }
    records, provenance = load_train_records(certification_path)
    best: dict[str, tuple[tuple[float, int, int], dict[str, Any]]] = {}
    skipped = 0
    for record in records:
        hand = parse_hand(record.text, record.source_file)
        if not hand:
            continue
        rows = [row for row in decision_rows(hand, include_preflop_context_v1=True) if row.get("street") == "preflop"]
        actions = _voluntary_actions(hand)
        if len(rows) != len(actions):
            raise ValueError(f"preflop row/action cardinality drift for {record.hand_id}")
        for index, row in enumerate(rows):
            if row.get("split") != "TRAIN":
                raise AssertionError("non-TRAIN row crossed representative selector")
            if row.get("is_hero") or int(row.get("table_size") or 0) != 6:
                continue
            key = _source_key(row)
            plan_row = plan_by_source.get(key)
            if plan_row is None:
                continue
            pfc = row.get("preflop_context_v1") or {}
            stack = pfc.get("effective_stack_bb")
            target = (plan_row.get("effective_stack_observed") or {}).get("p50_bb")
            if not isinstance(stack, (int, float)) or not isinstance(target, (int, float)):
                skipped += 1
                continue
            try:
                state = _replay_before(hand, index)
                _public_row_matches_state(row, state)
            except Exception:
                skipped += 1
                continue
            distance = abs(float(stack) - float(target))
            tie = (distance, int(str(record.hand_id)), index)
            payload = {
                "context_id": plan_row["context_id"],
                "source_matrix_key": key,
                "source_hand_id": str(record.hand_id),
                "source_file": str(record.source_file),
                "source_action_index": index,
                "effective_stack_bb": float(stack),
                "target_p50_effective_stack_bb": float(target),
                "absolute_stack_distance_bb": distance,
                "actor": str(state.next_actor),
                "state_snapshot": state.to_snapshot(),
                "public_state_sha256": sha256_bytes(canonical_json_bytes(state.to_snapshot())),
                "selection_uses_private_cards": False,
                "selection_uses_future_cards": False,
            }
            current = best.get(plan_row["context_id"])
            if current is None or tie < current[0]:
                best[plan_row["context_id"]] = (tie, payload)
    missing = [context_id for context_id in scope["eligible_context_ids"] if context_id not in best]
    return {
        "schema": REP_SCHEMA,
        "issue": 358,
        "split_consumed": "TRAIN",
        "test_consumed": False,
        "validation_consumed": False,
        "source_plan_sha256": sha256_path(plan_path),
        "certification": provenance,
        "eligible_context_ids": scope["eligible_context_ids"],
        "representatives": [best[context_id][1] for context_id in scope["eligible_context_ids"] if context_id in best],
        "missing_contexts": [{"context_id": context_id, "reason": "NO_REPLAYABLE_CERTIFIED_TRAIN_REPRESENTATIVE"} for context_id in missing],
        "skipped_candidate_rows": skipped,
        "information_boundary": {
            "private_cards_consumed_for_selection": False,
            "future_cards_consumed_for_selection": False,
        },
    }


def make_environment_identity(code_sha: str) -> dict[str, Any]:
    model_paths = [
        base.DEFAULT_PREFLOP,
        base.DEFAULT_POSTFLOP,
        base.DEFAULT_OVERLAY,
        ROOT / "tools/simulation/paired_preflop_grid_evaluator.py",
        ROOT / "tools/simulation/paired_adaptive_preflop_ev.py",
        ROOT / "tools/simulation/game_core.py",
    ]
    return {
        "schema": "poker-hero-preflop-generation-environment/v1",
        "slot_id": ENV_SLOT,
        "code_sha": code_sha,
        "python_version": platform.python_version(),
        "runner_os": os.environ.get("RUNNER_OS"),
        "runner_arch": os.environ.get("RUNNER_ARCH"),
        "sources": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": sha256_path(path),
            }
            for path in model_paths
        ],
        "paired_engine": "tools.simulation.paired_preflop_grid_evaluator.evaluate_preflop_grid_paired",
        "game_core": "tools.simulation.game_core.NoLimitHoldemState",
        "scientific_effect": "REAL_GENERATION_EXPERIMENTAL_NO_PROMOTION",
        "test_consumed": False,
    }


def make_generation_parameters(plan: Mapping[str, Any], scope: Mapping[str, Any], code_sha: str) -> dict[str, Any]:
    return {
        "schema": "poker-hero-preflop-generation-parameters/v1",
        "slot_id": PARAMS_SLOT,
        "issue": 358,
        "generation_id": GENERATION_ID,
        "candidate_id": CANDIDATE_ID,
        "code_sha": code_sha,
        "source_plan_sha256": sha256_path(DEFAULT_PLAN),
        "source_train_audit_sha256": plan["source"]["sha256"],
        "context_ids": scope["eligible_context_ids"],
        "hand_class_order_id": "poker-hand-class-169-matrix-row-major-v1",
        "hand_classes_per_context": 169,
        "hand_shards": HAND_SHARDS,
        "master_seed": MASTER_SEED,
        "paired_adaptive_budget": {
            "initial_samples_per_alternative": 4,
            "max_samples_per_alternative": 8,
            "batch_size": 4,
            "max_total_rollouts": 32,
            "confidence_z": 1.96,
            "elimination_margin_bb": 0.0,
        },
        "support_closure": {
            "enabled": True,
            "policy": SupportClosedModelAContinuationPolicy.policy_id,
            "nearest_context_substitution": False,
        },
        "sizing_grid": "CERTIFIED_TRAIN_EXACT_NODE_EMPIRICAL_RAISE_SIZING_V1",
        "exact_lookup": True,
        "nearest_context_allowed": False,
        "validation_split_consumed": False,
        "test_consumed": False,
        "activation_authorized": False,
        "promotion_authorized": False,
    }


def matrix_for_generation(scope: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "context_index": context_index,
            "context_id": context_id,
            "hand_shard_index": hand_shard,
            "hand_shard_count": HAND_SHARDS,
        }
        for context_index, context_id in enumerate(scope["eligible_context_ids"])
        for hand_shard in range(HAND_SHARDS)
    ]


def _artifact_identity(plan: Mapping[str, Any], params: Mapping[str, Any], code_sha: str) -> dict[str, Any]:
    return {
        "population_id": plan["population_id"],
        "generation_id": GENERATION_ID,
        "candidate_id": CANDIDATE_ID,
        "source_plan_sha256": sha256_path(DEFAULT_PLAN),
        "source_train_audit_sha256": plan["source"]["sha256"],
        "generator_version": GENERATOR_VERSION,
        "code_sha": code_sha,
        "environment_identity_slot": ENV_SLOT,
        "generation_parameters_slot": PARAMS_SLOT,
        "scientific_effect": "REAL_GENERATION_EXPERIMENTAL_NO_PROMOTION",
    }


def generate_part(
    *,
    plan_path: Path,
    representatives_path: Path,
    decisions_path: Path,
    parameters_path: Path,
    context_id: str,
    hand_shard_index: int,
    hand_shard_count: int,
    code_sha: str,
) -> dict[str, Any]:
    plan = load_json(plan_path)
    reps = load_json(representatives_path)
    params = load_json(parameters_path)
    if params.get("code_sha") != code_sha:
        raise ValueError("generation code SHA differs from frozen parameters")
    plan_by_id = {row["context_id"]: row for row in plan["contexts"]}
    if context_id not in set(scope_from_plan(plan)["eligible_context_ids"]):
        raise ValueError("context outside #358 READY non-ISO scope")
    rep_by_id = {row["context_id"]: row for row in reps["representatives"]}
    rep = rep_by_id.get(context_id)
    if rep is None:
        return {
            "schema": PART_SCHEMA,
            "context_id": context_id,
            "hand_shard_index": hand_shard_index,
            "cells": [],
            "deferred": [{"hand_class": None, "reason": "NO_REPLAYABLE_CERTIFIED_TRAIN_REPRESENTATIVE"}],
            "test_consumed": False,
        }
    state = NoLimitHoldemState.from_snapshot(rep["state_snapshot"])
    actor = str(rep["actor"])
    plan_row = plan_by_id[context_id]

    strict_policy = ModelAContinuationPolicy.from_paths(
        base.DEFAULT_PREFLOP,
        base.DEFAULT_POSTFLOP,
        base.DEFAULT_OVERLAY,
    )
    opponent_policy = SupportClosedModelAContinuationPolicy(strict_policy)
    hero_policy = SupportClosedModelAContinuationPolicy(strict_policy)
    hero_continuation = base.FixedPopulationDerivedHeroContinuation(hero_policy)
    try:
        raise_targets, sizing_support = observed_raise_targets(strict_policy, state, actor, decisions_path)
    except Exception as exc:
        return {
            "schema": PART_SCHEMA,
            "context_id": context_id,
            "hand_shard_index": hand_shard_index,
            "cells": [],
            "deferred": [{"hand_class": None, "reason": f"EXACT_TRAIN_SIZING_UNSUPPORTED:{exc}"}],
            "test_consumed": False,
        }
    call_action, raise_action = base.semantic_grid_labels(state)
    budget_cfg = params["paired_adaptive_budget"]
    budget = AdaptiveBudget(**budget_cfg)
    hands = list(CANONICAL_HAND_CLASSES)[hand_shard_index::hand_shard_count]
    identity = _artifact_identity(plan, params, code_sha)
    cells: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for hand in hands:
        cards = base.representative_cards(hand)
        rollout = ModelAPreflopContinuationRollout(
            opponent_policy=opponent_policy,
            hero_hole_cards=cards,
            hero_continuation_policy=hero_continuation,
        )
        seed = int.from_bytes(
            hashlib.sha256(f"{MASTER_SEED}|{context_id}|{hand}".encode()).digest()[:8],
            "big",
        )
        try:
            integration = evaluate_preflop_grid_paired(
                NoLimitHoldemState.from_snapshot(state.to_snapshot()),
                actor=actor,
                context_id=context_id,
                hand_class=hand,
                population_id=plan["population_id"],
                raise_targets_bb=raise_targets,
                rollout=rollout,
                budget=budget,
                base_seed=seed,
                call_action=call_action,
                raise_action=raise_action,
                include_jam=True,
                sizing_grid_source=(
                    "certified TRAIN exact-node empirical p25/p50/p75;"
                    + str(sizing_support.get("decisions_sha256") or "")
                ),
                support_provider=lambda candidate: {
                    "observations": int(plan_row["train_observations"]),
                    "backoff_level": "EXACT_TRAIN_READY",
                    "source": context_id,
                },
                status="EXPERIMENTAL",
                notes="Issue #358 real generation; no promotion/activation; TEST unconsumed.",
                require_materialized_common_world=True,
            )
            bridged = bridge_integration_file(
                integration,
                artifact_identity=identity,
                plan_path=plan_path,
            )
            cell = bridged.get("strategy_cell")
            if cell is None:
                deferred.append({
                    "hand_class": hand,
                    "reason": str(bridged.get("bridge_state") or "NON_MATERIALIZABLE"),
                    "alternative_id": bridged.get("alternative_id"),
                })
                continue
            cells.append(cell)
            evidence.append({
                "hand_class": hand,
                "decision_id": integration["decision_id"],
                "selected_id": integration["decision"]["selected_id"],
                "action": integration["decision"]["action"],
                "target_total_bb": integration["decision"]["target_total_bb"],
                "incremental_cost_bb": integration["decision"]["incremental_cost_bb"],
                "ev_bb": integration["decision"]["ev_bb"],
                "uncertainty": integration["decision"]["uncertainty"],
                "rollout_budget": integration["decision"]["search"]["budget"],
                "worlds_materialized": integration["paired_result"]["search"]["worlds_materialized"],
                "paired_result_sha256": bridged["evidence"]["source_result_sha256"],
                "bridge_state": bridged["bridge_state"],
            })
        except Exception as exc:
            deferred.append({"hand_class": hand, "reason": f"GENERATION_ERROR:{type(exc).__name__}:{exc}"})
    return {
        "schema": PART_SCHEMA,
        "issue": 358,
        "context_id": context_id,
        "family": plan_row["family"],
        "coverage_group": plan_row["coverage_group"],
        "hand_shard_index": hand_shard_index,
        "hand_shard_count": hand_shard_count,
        "requested_hand_classes": hands,
        "cells": cells,
        "deferred": deferred,
        "evidence": evidence,
        "representative": {
            key: rep[key]
            for key in (
                "source_hand_id",
                "source_file",
                "source_action_index",
                "effective_stack_bb",
                "target_p50_effective_stack_bb",
                "absolute_stack_distance_bb",
                "public_state_sha256",
            )
        },
        "sizing_support": sizing_support,
        "support_closure": {
            "opponent": opponent_policy.aggregate_audit(),
            "hero": hero_policy.aggregate_audit(),
        },
        "information_boundary": {
            "representative_private_cards_consumed": False,
            "representative_future_cards_consumed": False,
            "paired_worlds_materialized_before_alternative": True,
        },
        "test_consumed": False,
    }


def assemble_generation(
    *,
    plan_path: Path,
    scope_path: Path,
    representatives_path: Path,
    parameters_path: Path,
    environment_path: Path,
    parts_dir: Path,
    output_root: Path,
    code_sha: str,
) -> dict[str, Any]:
    plan = load_json(plan_path)
    scope = load_json(scope_path)
    reps = load_json(representatives_path)
    params = load_json(parameters_path)
    env = load_json(environment_path)
    parts = [load_json(path) for path in sorted(Path(parts_dir).glob("*.json"))]
    expected_pairs = {
        (context_id, hand_shard)
        for context_id in scope["eligible_context_ids"]
        for hand_shard in range(HAND_SHARDS)
    }
    actual_pairs = {(row["context_id"], int(row["hand_shard_index"])) for row in parts}
    if actual_pairs != expected_pairs:
        missing = sorted(expected_pairs - actual_pairs)
        raise ValueError(f"generation parts incomplete: missing={missing[:5]} count={len(missing)}")

    by_context: dict[str, list[dict[str, Any]]] = {context_id: [] for context_id in scope["eligible_context_ids"]}
    for part in parts:
        by_context[part["context_id"]].append(part)
    plan_by_id = {row["context_id"]: row for row in plan["contexts"]}
    generated_ids: list[str] = []
    deferred_contexts: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    cell_by_context: dict[str, list[dict[str, Any]]] = {}
    for context_id in scope["eligible_context_ids"]:
        context_parts = sorted(by_context[context_id], key=lambda row: int(row["hand_shard_index"]))
        cells = [cell for part in context_parts for cell in part.get("cells") or []]
        deferred = [item for part in context_parts for item in part.get("deferred") or []]
        evidence_rows.extend(
            {"context_id": context_id, **item}
            for part in context_parts
            for item in part.get("evidence") or []
        )
        hands = [str(cell.get("hand_class") or "") for cell in cells]
        if deferred or len(cells) != 169 or set(hands) != set(CANONICAL_HAND_CLASSES):
            deferred_contexts.append({
                "context_id": context_id,
                "coverage_group": plan_by_id[context_id]["coverage_group"],
                "family": plan_by_id[context_id]["family"],
                "reason": "INCOMPLETE_169_MATERIALIZATION",
                "materialized_cells": len(cells),
                "deferred_entries": deferred,
            })
            continue
        generated_ids.append(context_id)
        cell_by_context[context_id] = cells

    if not generated_ids:
        raise ValueError("no complete 169/169 context was materialized")

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    write_json(output_root / "environment_identity.json", env)
    write_json(output_root / "generation_parameters.json", params)

    artifacts: list[dict[str, Any]] = [
        {
            "role": "ENVIRONMENT_IDENTITY",
            "path": "environment_identity.json",
            "sha256": sha256_path(output_root / "environment_identity.json"),
            "shard_id": None,
            "context_ids": [],
            "cell_count": 0,
        },
        {
            "role": "GENERATION_PARAMETERS",
            "path": "generation_parameters.json",
            "sha256": sha256_path(output_root / "generation_parameters.json"),
            "shard_id": None,
            "context_ids": [],
            "cell_count": 0,
        },
    ]
    binding_rows: list[dict[str, Any]] = []
    generated_set = set(generated_ids)
    shard_count = 0
    for source_shard in plan["shard_plan"]["shards"]:
        context_ids = [cid for cid in source_shard["context_ids"] if cid in generated_set]
        if not context_ids:
            continue
        shard_count += 1
        shard_id = f"ISSUE358-{source_shard['shard_id']}"
        cells = [cell for cid in context_ids for cell in cell_by_context[cid]]
        shard = {
            "schema": "poker-hero-preflop-strategy-shard/v1",
            "population_id": plan["population_id"],
            "generation_id": GENERATION_ID,
            "candidate_id": CANDIDATE_ID,
            "shard_id": shard_id,
            "synthetic_fixture": False,
            "cells": cells,
        }
        rel = f"shards/{shard_id}.json"
        write_json(output_root / rel, shard)
        digest = sha256_path(output_root / rel)
        artifacts.append({
            "role": "STRATEGY_SHARD",
            "path": rel,
            "sha256": digest,
            "shard_id": shard_id,
            "context_ids": context_ids,
            "cell_count": len(cells),
        })
        for context_id in context_ids:
            binding_rows.append({
                "context_id": context_id,
                "population_id": plan["population_id"],
                "generation_id": GENERATION_ID,
                "candidate_id": CANDIDATE_ID,
                "stack_bucket": plan_by_id[context_id]["effective_stack_bucket"],
                "shard_id": shard_id,
                "artifact_path": rel,
                "artifact_sha256": digest,
            })

    binding = {
        "schema": "poker-hero-preflop-generation-binding/v1",
        "population_id": plan["population_id"],
        "generation_id": GENERATION_ID,
        "candidate_id": CANDIDATE_ID,
        "lookup_policy": {
            "mode": "EXACT_CONTEXT_ONLY",
            "nearest_context_allowed": False,
            "fallback_states": ["EXACT_GENERATED", "EXACT_INCUMBENT_FALLBACK", "EXACT_UNAVAILABLE"],
        },
        "bindings": binding_rows,
    }
    write_json(output_root / "binding.json", binding)
    artifacts.append({
        "role": "BINDING",
        "path": "binding.json",
        "sha256": sha256_path(output_root / "binding.json"),
        "shard_id": None,
        "context_ids": generated_ids,
        "cell_count": 0,
    })
    projection = {
        "ready_context_count": len(plan["generation_order"]),
        "expected_hand_classes_per_context": 169,
        "ready_cell_count": plan["structural_compute_estimator"]["ready_hand_class_cells"],
        "planned_shard_count": plan["structural_compute_estimator"]["planned_shards"],
    }
    manifest = {
        "schema": "poker-hero-preflop-generation-manifest/v1",
        "population_id": plan["population_id"],
        "generation_id": GENERATION_ID,
        "candidate_id": CANDIDATE_ID,
        "generator_version": GENERATOR_VERSION,
        "source_plan_sha256": sha256_path(plan_path),
        "source_train_audit_sha256": plan["source"]["sha256"],
        "code_sha": code_sha,
        "environment_identity": {
            "slot_id": ENV_SLOT,
            "path": "environment_identity.json",
            "sha256": sha256_path(output_root / "environment_identity.json"),
        },
        "generation_parameters": {
            "slot_id": PARAMS_SLOT,
            "path": "generation_parameters.json",
            "sha256": sha256_path(output_root / "generation_parameters.json"),
        },
        "generation_scope": "AUTHORIZED_READY_SUBSET",
        "synthetic_fixture": False,
        "context_count": len(generated_ids),
        "expected_hand_classes_per_context": 169,
        "shard_count": shard_count,
        "hand_class_order_id": "poker-hand-class-169-matrix-row-major-v1",
        "plan_projection": projection,
        "expected_context_ids": generated_ids,
        "artifacts": artifacts,
        "completeness": {
            "state": "FINALIZED",
            "expected_context_count": len(generated_ids),
            "actual_context_count": len(generated_ids),
            "expected_cells": len(generated_ids) * 169,
            "actual_cells": len(generated_ids) * 169,
            "expected_shard_count": shard_count,
            "actual_shard_count": shard_count,
        },
        "fallback_contract": {
            "states": ["EXACT_GENERATED", "EXACT_INCUMBENT_FALLBACK", "EXACT_UNAVAILABLE"],
            "resolution_order": ["EXACT_GENERATED", "EXACT_INCUMBENT_FALLBACK", "EXACT_UNAVAILABLE"],
            "lookup": "EXACT_CONTEXT_ONLY",
            "nearest_context_allowed": False,
            "forbidden_substitutions": [
                "NEAREST_STACK",
                "NEAREST_POSITION",
                "NEAREST_OPENER",
                "NEAREST_FAMILY",
                "CALLER_COUNT_BACKOFF",
                "LIMPER_COUNT_BACKOFF",
                "JAM_STATE_BACKOFF",
            ],
        },
        "immutability": {
            "content_addressed": True,
            "hash_algorithm": "sha256",
            "in_place_modification_allowed": False,
            "correction_policy": "NEW_GENERATION_ID",
            "finalized_state": "FINALIZED",
        },
    }
    write_json(output_root / "manifest.json", manifest)
    validation = validate_generation(output_root, plan_path, allow_synthetic=False)

    status_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    for context_id in generated_ids:
        for cell in cell_by_context[context_id]:
            status = str((cell.get("action") or {}).get("status"))
            action = str((cell.get("action") or {}).get("value"))
            status_counts[status] = status_counts.get(status, 0) + 1
            action_counts[action] = action_counts.get(action, 0) + 1
    result = {
        "schema": RESULT_SCHEMA,
        "issue": 358,
        "parent_issue": 196,
        "generation_id": GENERATION_ID,
        "candidate_id": CANDIDATE_ID,
        "source_plan_sha256": sha256_path(plan_path),
        "source_train_audit_sha256": plan["source"]["sha256"],
        "code_sha": code_sha,
        "scope": {
            "eligible_context_count": scope["eligible_context_count"],
            "eligible_context_ids": scope["eligible_context_ids"],
            "generated_context_count": len(generated_ids),
            "generated_context_ids": generated_ids,
            "deferred_context_count": len(deferred_contexts),
            "deferred_contexts": deferred_contexts,
            "excluded_ready": scope["excluded_ready"],
        },
        "generation": {
            "cells": len(generated_ids) * 169,
            "action_status_counts": dict(sorted(status_counts.items())),
            "action_counts": dict(sorted(action_counts.items())),
            "manifest_sha256": sha256_path(output_root / "manifest.json"),
            "binding_sha256": sha256_path(output_root / "binding.json"),
            "validator": validation,
        },
        "paired_evidence": {
            "rows": len(evidence_rows),
            "sha256": sha256_bytes(canonical_json_bytes(evidence_rows)),
            "note": "full paired evidence is retained in CI artifacts; finalized cells bind selected evidence through action/sizing/EV/uncertainty/sample/world/provenance fields",
        },
        "scientific_boundaries": {
            "validation_consumed": False,
            "test_consumed": False,
            "activation_authorized": False,
            "promotion_authorized": False,
            "ui_modified": False,
            "pack_published": False,
            "vs_limpers_iso_generated": False,
            "nearest_context_substitution": False,
        },
    }
    write_json(output_root / "GENERATION_RESULT.json", result)
    write_json(output_root / "DEFERRED_CONTEXTS.json", {
        "schema": "poker-hero-preflop-deferred-contexts/v1",
        "issue": 358,
        "deferred": deferred_contexts,
        "not_ready_groups": {
            group: [
                row["context_id"]
                for row in plan["contexts"]
                if row["coverage_group"] == group and row["readiness"] != "READY_FOR_GENERATION"
            ]
            for group in ("VS_3BET", "VS_4BET_OR_JAM")
        },
        "test_consumed": False,
    })
    return result


def _cmd_scope(args: argparse.Namespace) -> int:
    plan = load_json(args.plan)
    scope = scope_from_plan(plan)
    if args.output:
        write_json(args.output, scope)
    print(json.dumps(scope, indent=2, sort_keys=True))
    return 0


def _cmd_prepare(args: argparse.Namespace) -> int:
    plan = load_json(args.plan)
    scope = scope_from_plan(plan)
    reps = prepare_representatives(args.plan, args.certification)
    env = make_environment_identity(args.code_sha)
    params = make_generation_parameters(plan, scope, args.code_sha)
    write_json(args.scope_output, scope)
    write_json(args.representatives_output, reps)
    write_json(args.environment_output, env)
    write_json(args.parameters_output, params)
    matrix = matrix_for_generation(scope)
    write_json(args.matrix_output, {"include": matrix})
    print(json.dumps({
        "eligible_contexts": len(scope["eligible_context_ids"]),
        "representatives": len(reps["representatives"]),
        "missing_representatives": len(reps["missing_contexts"]),
        "matrix_jobs": len(matrix),
        "matrix": {"include": matrix},
    }, separators=(",", ":")))
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    part = generate_part(
        plan_path=args.plan,
        representatives_path=args.representatives,
        decisions_path=args.decisions,
        parameters_path=args.parameters,
        context_id=args.context_id,
        hand_shard_index=args.hand_shard_index,
        hand_shard_count=args.hand_shard_count,
        code_sha=args.code_sha,
    )
    write_json(args.output, part)
    print(json.dumps({
        "context_id": part["context_id"],
        "hand_shard_index": part["hand_shard_index"],
        "cells": len(part["cells"]),
        "deferred": len(part["deferred"]),
    }, sort_keys=True))
    return 0


def _cmd_assemble(args: argparse.Namespace) -> int:
    result = assemble_generation(
        plan_path=args.plan,
        scope_path=args.scope,
        representatives_path=args.representatives,
        parameters_path=args.parameters,
        environment_path=args.environment,
        parts_dir=args.parts_dir,
        output_root=args.output_root,
        code_sha=args.code_sha,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    scope = sub.add_parser("scope")
    scope.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    scope.add_argument("--output", type=Path)
    scope.set_defaults(func=_cmd_scope)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    prepare.add_argument("--certification", type=Path, default=DEFAULT_CERTIFICATION)
    prepare.add_argument("--code-sha", required=True)
    prepare.add_argument("--scope-output", type=Path, required=True)
    prepare.add_argument("--representatives-output", type=Path, required=True)
    prepare.add_argument("--environment-output", type=Path, required=True)
    prepare.add_argument("--parameters-output", type=Path, required=True)
    prepare.add_argument("--matrix-output", type=Path, required=True)
    prepare.set_defaults(func=_cmd_prepare)

    generate = sub.add_parser("generate-part")
    generate.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    generate.add_argument("--representatives", type=Path, required=True)
    generate.add_argument("--decisions", type=Path, required=True)
    generate.add_argument("--parameters", type=Path, required=True)
    generate.add_argument("--context-id", required=True)
    generate.add_argument("--hand-shard-index", type=int, required=True)
    generate.add_argument("--hand-shard-count", type=int, default=HAND_SHARDS)
    generate.add_argument("--code-sha", required=True)
    generate.add_argument("--output", type=Path, required=True)
    generate.set_defaults(func=_cmd_generate)

    assemble = sub.add_parser("assemble")
    assemble.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    assemble.add_argument("--scope", type=Path, required=True)
    assemble.add_argument("--representatives", type=Path, required=True)
    assemble.add_argument("--parameters", type=Path, required=True)
    assemble.add_argument("--environment", type=Path, required=True)
    assemble.add_argument("--parts-dir", type=Path, required=True)
    assemble.add_argument("--output-root", type=Path, required=True)
    assemble.add_argument("--code-sha", required=True)
    assemble.set_defaults(func=_cmd_assemble)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
