#!/usr/bin/env python3
"""Frozen VALIDATION benchmark for #338 paired/adaptive preflop EV search."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
from typing import Any

from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.hand_history_state import replay_public_hand
from tools.simulation.model_a_continuation import ModelAContinuationPolicy, ModelAUnsupportedContext
from tools.simulation.model_a_preflop_rollout import ModelAPreflopContinuationRollout
from tools.simulation.model_a_support_closure import SupportClosedModelAContinuationPolicy
from tools.simulation.model_b_runtime import combo_class
from tools.simulation.paired_adaptive_preflop_ev import AdaptiveBudget
from tools.simulation.paired_preflop_grid_evaluator import evaluate_preflop_grid_paired
from tools.simulation.preflop_grid_evaluator import (
    build_candidates,
    evaluate_preflop_grid,
)
from tools.training import generate_hero_range_decisions as generation

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL = ROOT / "training/runs/20260919_paired_adaptive_preflop_validation/PROTOCOL_V2.json"
DEFAULT_CORPUS = ROOT / "training/runs/20260913_strategy_candidate_v84/validation_scenarios.json"


def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def state_at_first_hero_preflop(raw_hand: str, hero: str) -> NoLimitHoldemState:
    replay = replay_public_hand(raw_hand)
    trace = replay["trace"]
    target = next(
        i for i, row in enumerate(trace)
        if row["street"] == "preflop" and row["player"] == hero
    )
    state = NoLimitHoldemState.from_snapshot(trace[target]["state_before"])
    events = []
    for i, row in enumerate(trace[:target]):
        if row["street"] != "preflop":
            raise ValueError("Hero has no preflop decision before postflop trace")
        action = str(row["action"]).upper()
        core = {
            "FOLD": "FOLD",
            "CHECK": "CHECK",
            "CALL": "CALL",
            "RAISE": "RAISE",
            "BET": "RAISE",
        }.get(action)
        if core is None:
            raise ValueError(f"unsupported replay action {action!r}")
        event = {"street": "preflop", "player": row["player"], "action": core}
        if core == "RAISE":
            after = trace[i + 1]["state_before"]
            event["target_total_bb"] = float(
                after["street_committed_bb"][row["player"]]
            )
        events.append(event)
    state.action_log = events
    if state.next_actor != hero:
        raise AssertionError(f"reconstructed next actor {state.next_actor!r} != {hero!r}")
    return state


def selected_scenarios(manifest: dict[str, Any], count: int) -> list[dict[str, Any]]:
    if manifest.get("split") != "VALIDATION":
        raise ValueError("benchmark corpus must declare VALIDATION")
    out = []
    seen = set()
    for row in manifest.get("scenarios") or []:
        hand_id = str(row["hand_id"])
        if hand_id in seen:
            continue
        seen.add(hand_id)
        out.append(row)
        if len(out) == count:
            break
    if len(out) != count:
        raise ValueError(f"requested {count} distinct VALIDATION hands, found {len(out)}")
    return out


def _evaluate_scenario(task: tuple[dict[str, Any], dict[str, Any], int]) -> dict[str, Any]:
    scenario, protocol, decision_index = task
    budget_cfg = protocol["budget"]
    fixed_samples = int(budget_cfg["fixed_samples_per_non_exact_alternative"])
    initial = int(budget_cfg["paired_initial_samples_per_non_exact_alternative"])
    maximum = int(budget_cfg["paired_max_samples_per_non_exact_alternative"])
    batch = int(budget_cfg["paired_batch_size"])
    seed_blocks = [int(x) for x in protocol["comparison"]["seed_blocks"]]

    strict = ModelAContinuationPolicy.from_paths(
        generation.DEFAULT_PREFLOP,
        generation.DEFAULT_POSTFLOP,
        generation.DEFAULT_OVERLAY,
    )
    opponent = SupportClosedModelAContinuationPolicy(strict)
    hero_future = SupportClosedModelAContinuationPolicy(strict)
    hero_continuation = generation.FixedPopulationDerivedHeroContinuation(hero_future)

    hero = str(scenario["hero"])
    state = state_at_first_hero_preflop(str(scenario["raw_hand"]), hero)
    hand_class = combo_class(tuple(scenario["hero_cards"]))
    try:
        raise_targets, sizing_support = generation.observed_raise_targets(strict, state, hero)
    except ModelAUnsupportedContext as exc:
        if "exposes no observed legal raise sizing" not in str(exc):
            raise
        raise_targets = []
        sizing_support = {
            "sources": [],
            "grid_contract": "EXACT_NODE_OBSERVED_NONJAM_SIZINGS_PLUS_SEPARATE_JAM",
            "fallback": "NO_OBSERVED_LEGAL_NONJAM_SIZING__JAM_ONLY",
            "reason": str(exc),
        }
    call_action, raise_action = generation.semantic_grid_labels(state)
    candidates = build_candidates(
        state,
        actor=hero,
        raise_targets_bb=raise_targets,
        call_action=call_action,
        raise_action=raise_action,
        include_jam=True,
        sizing_grid_source="MODEL_A_EXACT_NODE_OBSERVED",
    )
    non_exact = sum(candidate.core_action != "FOLD" for candidate in candidates)
    max_total = non_exact * maximum
    context_id = f"validation:{scenario['hand_id']}:hero-preflop-0"
    rollout = ModelAPreflopContinuationRollout(
        opponent_policy=opponent,
        hero_hole_cards=scenario["hero_cards"],
        hero_continuation_policy=hero_continuation,
    )

    fixed_rollouts = 0
    paired_rollouts = 0
    deterministic_fixed = None
    deterministic_paired = None
    block_rows = []
    for seed in seed_blocks:
        fixed = evaluate_preflop_grid(
            NoLimitHoldemState.from_snapshot(state.to_snapshot()),
            actor=hero,
            context_id=context_id,
            population_id=protocol["population_id"],
            raise_targets_bb=raise_targets,
            rollout=rollout,
            samples_per_candidate=fixed_samples,
            base_seed=seed,
            call_action=call_action,
            raise_action=raise_action,
            include_jam=True,
            sizing_grid_source="MODEL_A_EXACT_NODE_OBSERVED",
            status="EXPERIMENTAL",
        )
        paired = evaluate_preflop_grid_paired(
            NoLimitHoldemState.from_snapshot(state.to_snapshot()),
            actor=hero,
            context_id=context_id,
            hand_class=hand_class,
            population_id=protocol["population_id"],
            raise_targets_bb=raise_targets,
            rollout=rollout,
            budget=AdaptiveBudget(
                initial_samples_per_alternative=initial,
                max_samples_per_alternative=maximum,
                batch_size=batch,
                max_total_rollouts=max_total,
                confidence_z=float(budget_cfg["confidence_z"]),
                elimination_margin_bb=float(budget_cfg["elimination_margin_bb"]),
            ),
            base_seed=seed,
            call_action=call_action,
            raise_action=raise_action,
            include_jam=True,
            sizing_grid_source="MODEL_A_EXACT_NODE_OBSERVED",
            status="EXPERIMENTAL",
            require_materialized_common_world=True,
        )
        fixed_rollouts += int(fixed["search"]["budget"])
        paired_rollouts += int(paired["decision"]["search"]["budget"])
        block_rows.append({
            "seed": seed,
            "fixed_selected_id": fixed["selected_id"],
            "paired_selected_id": paired["decision"]["selected_id"],
            "fixed_rollouts": int(fixed["search"]["budget"]),
            "paired_rollouts": int(paired["decision"]["search"]["budget"]),
            "paired_pairwise_deltas": paired["paired_result"]["pairwise_deltas"],
            "paired_common_world_mode": paired["decision"]["search"]["common_world_mode"],
        })

        if decision_index == 0 and seed == seed_blocks[0]:
            fixed_again = evaluate_preflop_grid(
                NoLimitHoldemState.from_snapshot(state.to_snapshot()),
                actor=hero,
                context_id=context_id,
                population_id=protocol["population_id"],
                raise_targets_bb=raise_targets,
                rollout=rollout,
                samples_per_candidate=fixed_samples,
                base_seed=seed,
                call_action=call_action,
                raise_action=raise_action,
                include_jam=True,
                sizing_grid_source="MODEL_A_EXACT_NODE_OBSERVED",
                status="EXPERIMENTAL",
            )
            paired_again = evaluate_preflop_grid_paired(
                NoLimitHoldemState.from_snapshot(state.to_snapshot()),
                actor=hero,
                context_id=context_id,
                hand_class=hand_class,
                population_id=protocol["population_id"],
                raise_targets_bb=raise_targets,
                rollout=rollout,
                budget=AdaptiveBudget(
                    initial_samples_per_alternative=initial,
                    max_samples_per_alternative=maximum,
                    batch_size=batch,
                    max_total_rollouts=max_total,
                    confidence_z=float(budget_cfg["confidence_z"]),
                    elimination_margin_bb=float(budget_cfg["elimination_margin_bb"]),
                ),
                base_seed=seed,
                call_action=call_action,
                raise_action=raise_action,
                include_jam=True,
                sizing_grid_source="MODEL_A_EXACT_NODE_OBSERVED",
                status="EXPERIMENTAL",
                require_materialized_common_world=True,
            )
            deterministic_fixed = canonical(fixed) == canonical(fixed_again)
            deterministic_paired = canonical(paired) == canonical(paired_again)

    fixed_same = len({row["fixed_selected_id"] for row in block_rows}) == 1
    paired_same = len({row["paired_selected_id"] for row in block_rows}) == 1
    return {
        "decision": {
            "hand_id": str(scenario["hand_id"]),
            "hero": hero,
            "hand_class": hand_class,
            "context_id": context_id,
            "candidate_ids": [candidate.id for candidate in candidates],
            "sizing_support": sizing_support,
            "fixed_stable": fixed_same,
            "paired_stable": paired_same,
            "seed_blocks": block_rows,
        },
        "fixed_rollouts": fixed_rollouts,
        "paired_rollouts": paired_rollouts,
        "deterministic_fixed": deterministic_fixed,
        "deterministic_paired": deterministic_paired,
        "continuation_support": {
            "opponent": opponent.aggregate_audit(),
            "hero": hero_future.aggregate_audit(),
        },
    }


def run_validation(
    protocol_path: Path = DEFAULT_PROTOCOL,
    corpus_path: Path = DEFAULT_CORPUS,
) -> dict[str, Any]:
    protocol = json.loads(Path(protocol_path).read_text(encoding="utf-8"))
    corpus = json.loads(Path(corpus_path).read_text(encoding="utf-8"))
    if protocol.get("schema") != "poker-paired-adaptive-preflop-validation-protocol/v2":
        raise ValueError("unexpected #338 protocol schema")
    if protocol.get("phase") != "VALIDATION" or protocol.get("status") != "FROZEN_BEFORE_RESULTS":
        raise ValueError("#338 protocol must be frozen VALIDATION")
    boundaries = protocol.get("scientific_boundaries") or {}
    if boundaries.get("test_consumed") is not False or boundaries.get("test_authorized") is not False:
        raise ValueError("TEST must remain forbidden")

    count = int((protocol.get("corpus") or {}).get("distinct_hands") or 0)
    scenarios = selected_scenarios(corpus, count)
    tasks = [(scenario, protocol, index) for index, scenario in enumerate(scenarios)]
    workers = min(4, len(tasks), max(1, int(os.cpu_count() or 1)))
    if workers > 1:
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=workers,
            mp_context=multiprocessing.get_context("fork"),
        ) as executor:
            rows = list(executor.map(_evaluate_scenario, tasks))
    else:
        rows = [_evaluate_scenario(task) for task in tasks]

    decisions = [row["decision"] for row in rows]
    fixed_rollouts = sum(int(row["fixed_rollouts"]) for row in rows)
    paired_rollouts = sum(int(row["paired_rollouts"]) for row in rows)
    fixed_stable = sum(int(row["decision"]["fixed_stable"]) for row in rows)
    paired_stable = sum(int(row["decision"]["paired_stable"]) for row in rows)
    deterministic_fixed = rows[0]["deterministic_fixed"]
    deterministic_paired = rows[0]["deterministic_paired"]

    n = len(decisions)
    seed_count = len(protocol["comparison"]["seed_blocks"])
    fixed_rate = fixed_stable / n
    paired_rate = paired_stable / n
    fixed_mean = fixed_rollouts / (n * seed_count)
    paired_mean = paired_rollouts / (n * seed_count)
    materialized_common_worlds = all(
        block["paired_common_world_mode"] == "MATERIALIZED_MODEL_A_HOLES_AND_BOARD"
        for decision in decisions
        for block in decision["seed_blocks"]
    )
    passed = (
        deterministic_fixed is True
        and deterministic_paired is True
        and materialized_common_worlds
        and paired_rate >= fixed_rate
        and paired_mean <= fixed_mean
    )
    return {
        "schema": "poker-paired-adaptive-preflop-validation-result/v1",
        "issue": 338,
        "phase": "VALIDATION",
        "protocol": {
            "path": str(Path(protocol_path).relative_to(ROOT)),
            "sha256": sha256_path(protocol_path),
        },
        "corpus": {
            "path": str(Path(corpus_path).relative_to(ROOT)),
            "sha256": sha256_path(corpus_path),
            "declared_split": corpus.get("split"),
            "distinct_hands": n,
        },
        "execution": {
            "parallel_unit": "independent_validation_hand",
            "workers": workers,
            "result_order": "manifest_order",
            "scientific_semantics_changed": False,
        },
        "metrics": {
            "fixed_stability": fixed_rate,
            "paired_stability": paired_rate,
            "fixed_mean_rollouts": fixed_mean,
            "paired_mean_rollouts": paired_mean,
            "fixed_total_rollouts": fixed_rollouts,
            "paired_total_rollouts": paired_rollouts,
            "deterministic_fixed": deterministic_fixed,
            "deterministic_paired": deterministic_paired,
            "materialized_common_worlds": materialized_common_worlds,
        },
        "acceptance": {
            "rule": "materialized common worlds AND paired_stability>=fixed_stability AND paired_mean_rollouts<=fixed_mean_rollouts AND deterministic",
            "pass": passed,
        },
        "scientific_boundaries": {
            "test_consumed": False,
            "test_authorized": False,
            "promotion_authorized": False,
            "model_a_modified": False,
            "model_b_modified": False,
            "ui_modified": False,
        },
        "continuation_support": {
            "by_hand": {
                row["decision"]["hand_id"]: row["continuation_support"]
                for row in rows
            },
        },
        "decisions": decisions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_validation(args.protocol, args.corpus)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "phase": result["phase"],
        "metrics": result["metrics"],
        "acceptance": result["acceptance"],
        "scientific_boundaries": result["scientific_boundaries"],
    }, indent=2, sort_keys=True))
    return 0 if result["acceptance"]["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
