#!/usr/bin/env python3
"""Generate #107 Hero decision evidence with certified TRAIN sizing support.

Model A v5 intentionally excludes the actor's chosen raise size from continuous
features to prevent target leakage. Candidate non-jam sizings therefore come
from certified TRAIN-only population RAISE rows on the exact structural node,
either read directly from the normalized corpus or from a compact frozen
manifest built from that corpus. The actual alternatives are still evaluated by
the existing #106 ``evaluate_preflop_grid`` engine.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.simulation.game_core import EPS, NoLimitHoldemState
from tools.simulation.model_a_continuation import (
    ModelAContinuationPolicy,
    ModelAUnsupportedContext,
    _preflop_decision,
    _semantic_trace,
    exact_preflop_node,
)
from tools.simulation.model_a_preflop_rollout import ModelAPreflopContinuationRollout
from tools.simulation.preflop_grid_evaluator import (
    PreflopEvaluationError,
    UnsupportedAlternative,
    evaluate_preflop_grid,
)
from tools.training import generate_hero_range_decisions as base

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = base.SCHEMA
SIZING_EVIDENCE_SCHEMA = "poker-hero-preflop-sizing-evidence/v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _nearest_rank(values: Sequence[float], q: float) -> float:
    if not values:
        raise ValueError("cannot compute empirical quantile of empty values")
    ordered = sorted(float(v) for v in values)
    index = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def _legalize_targets(
    targets: Sequence[float], state: NoLimitHoldemState, actor: str
) -> list[float]:
    view = state.legal_view(actor)
    current = float(view["current_price_bb"])
    minimum = view["min_raise_to_bb"]
    maximum = float(view["max_raise_to_bb"])
    legal: list[float] = []
    for raw in targets:
        target = float(raw)
        if not math.isfinite(target):
            continue
        if target <= current + EPS or target >= maximum - EPS:
            continue
        if minimum is not None and target + EPS < float(minimum):
            continue
        legal.append(round(target, 6))
    return sorted(set(legal))


def empirical_raise_targets(
    decisions_path: Path,
    *,
    canonical_key: str,
    state: NoLimitHoldemState,
    actor: str,
) -> tuple[list[float], dict[str, Any]]:
    """Return legal empirical p25/p50/p75 targets from exact-node TRAIN raises."""
    decisions_path = Path(decisions_path)
    if not decisions_path.is_file():
        raise FileNotFoundError(decisions_path)
    observed: list[float] = []
    matching_decisions = 0
    with decisions_path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid decision JSONL at line {line_number}: {exc}") from exc
            if (
                row.get("split") != "TRAIN"
                or row.get("street") != "preflop"
                or bool(row.get("is_hero"))
                or row.get("v4_canonical_key") != canonical_key
            ):
                continue
            matching_decisions += 1
            if row.get("action") != "RAISE":
                continue
            sizing = row.get("action_sizing_v1") or {}
            target = sizing.get("target_total_bb")
            if isinstance(target, (int, float)) and math.isfinite(float(target)):
                observed.append(float(target))

    if not observed:
        raise ModelAUnsupportedContext(
            "exact preflop node has no certified TRAIN population RAISE sizing evidence"
        )

    quantiles = {
        "p25": _nearest_rank(observed, 0.25),
        "p50": _nearest_rank(observed, 0.50),
        "p75": _nearest_rank(observed, 0.75),
    }
    targets = _legalize_targets(list(quantiles.values()), state, actor)
    if not targets:
        raise ModelAUnsupportedContext(
            "certified TRAIN sizing observations exist but empirical quantiles are illegal at this stack"
        )
    return targets, {
        "contract": "CERTIFIED_TRAIN_EXACT_NODE_EMPIRICAL_RAISE_SIZING_V1",
        "canonical_key": canonical_key,
        "decisions_sha256": sha256_file(decisions_path),
        "filters": {
            "split": "TRAIN",
            "street": "preflop",
            "is_hero": False,
            "action": "RAISE",
            "structural_key": "v4_canonical_key exact",
            "jam": "excluded; evaluated separately by #106",
        },
        "matching_population_decisions": matching_decisions,
        "observed_nonjam_raises": len(observed),
        "observed_min_target_total_bb": min(observed),
        "observed_max_target_total_bb": max(observed),
        "empirical_nearest_rank_targets_bb": quantiles,
        "legal_grid_targets_bb": targets,
    }


def _exact_node(
    policy: ModelAContinuationPolicy,
    state: NoLimitHoldemState,
    actor: str,
) -> Mapping[str, Any]:
    _, replay, history, _, _ = _semantic_trace(state)
    decision = _preflop_decision(replay, actor, history)
    node = exact_preflop_node(policy.preflop_model, decision)
    if node is None:
        raise ModelAUnsupportedContext(f"no exact preflop Model-A node for {decision!r}")
    if not str(node.get("canonical_key") or ""):
        raise ModelAUnsupportedContext("exact preflop Model-A node has no canonical_key")
    return node


def observed_raise_targets(
    policy: ModelAContinuationPolicy,
    state: NoLimitHoldemState,
    actor: str,
    decisions_path: Path,
) -> tuple[list[float], dict[str, Any]]:
    node = _exact_node(policy, state, actor)
    canonical_key = str(node["canonical_key"])
    targets, support = empirical_raise_targets(
        decisions_path,
        canonical_key=canonical_key,
        state=state,
        actor=actor,
    )
    support.update({
        "model_node_id": node.get("id") or node.get("node_id"),
        "model_population_decisions": int((node.get("coverage") or {}).get("population_decisions") or 0),
    })
    return targets, support


def frozen_raise_targets(
    policy: ModelAContinuationPolicy,
    state: NoLimitHoldemState,
    actor: str,
    evidence_path: Path,
    *,
    expected_context_id: str,
) -> tuple[list[float], dict[str, Any]]:
    """Validate and reuse a compact sizing manifest without reopening selection."""
    evidence_path = Path(evidence_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence.get("schema") != SIZING_EVIDENCE_SCHEMA:
        raise ValueError(f"unexpected sizing evidence schema: {evidence.get('schema')!r}")
    if evidence.get("context_id") != expected_context_id:
        raise ValueError("sizing evidence context_id does not match requested context")
    if evidence.get("population_id") != base.POPULATION_ID:
        raise ValueError("sizing evidence population mismatch")
    if evidence.get("selection") != "TRAIN_ONLY_NO_VALIDATION_NO_TEST":
        raise ValueError("sizing evidence must be frozen from TRAIN only")
    models = evidence.get("models") or {}
    for key in (
        "preflop_sha256",
        "postflop_baseline_sha256",
        "continuation_overlay_sha256",
        "stage_b_decision",
    ):
        if models.get(key) != policy.identity.get(key):
            raise ValueError(f"sizing evidence model identity mismatch for {key}")
    node = _exact_node(policy, state, actor)
    support = dict(evidence.get("sizing_support") or {})
    if support.get("contract") != "CERTIFIED_TRAIN_EXACT_NODE_EMPIRICAL_RAISE_SIZING_V1":
        raise ValueError("invalid sizing-support contract")
    if support.get("canonical_key") != node.get("canonical_key"):
        raise ValueError("sizing evidence canonical key differs from exact runtime node")
    filters = support.get("filters") or {}
    if filters.get("split") != "TRAIN" or filters.get("is_hero") is not False:
        raise ValueError("sizing evidence is not TRAIN-only population evidence")
    targets = _legalize_targets(evidence.get("legal_grid_targets_bb") or [], state, actor)
    if targets != sorted(set(float(x) for x in evidence.get("legal_grid_targets_bb") or [])):
        raise ValueError("frozen sizing targets are no longer legal in requested context")
    if not targets:
        raise ModelAUnsupportedContext("frozen sizing evidence exposes no legal non-jam target")
    support["evidence_sha256"] = sha256_file(evidence_path)
    support["evidence_schema"] = SIZING_EVIDENCE_SCHEMA
    support["model_node_id"] = node.get("id") or node.get("node_id")
    support["model_population_decisions"] = int((node.get("coverage") or {}).get("population_decisions") or 0)
    return targets, support


def generate_run(
    *,
    spec: base.ContextSpec,
    policy: ModelAContinuationPolicy,
    sizing_decisions: Path | None,
    sizing_evidence: Path | None,
    hand_classes: Sequence[str],
    samples_per_candidate: int,
    master_seed: int,
    code_sha: str,
    version: str,
) -> dict[str, Any]:
    state = base.build_context_state(spec)
    if state.next_actor != spec.position:
        raise AssertionError(f"context actor mismatch: {state.next_actor!r} != {spec.position!r}")
    if (sizing_decisions is None) == (sizing_evidence is None):
        raise ValueError("provide exactly one of sizing_decisions or sizing_evidence")
    if sizing_evidence is not None:
        raise_targets, sizing_support = frozen_raise_targets(
            policy, state, spec.position, sizing_evidence, expected_context_id=spec.context_id
        )
    else:
        raise_targets, sizing_support = observed_raise_targets(
            policy, state, spec.position, Path(sizing_decisions)
        )
    call_action, raise_action = base.semantic_grid_labels(state)
    hero_continuation = base.FixedPopulationDerivedHeroContinuation(policy)
    rows: list[dict[str, Any]] = []
    unsupported: list[dict[str, str]] = []
    total_rollouts = 0

    for hand in hand_classes:
        cards = base.representative_cards(hand)
        rollout = ModelAPreflopContinuationRollout(
            opponent_policy=policy,
            hero_hole_cards=cards,
            hero_continuation_policy=hero_continuation,
        )
        hand_seed = int.from_bytes(
            hashlib.sha256(f"{master_seed}|{spec.context_id}|{hand}".encode()).digest()[:8],
            "big",
        )
        try:
            decision = evaluate_preflop_grid(
                NoLimitHoldemState.from_snapshot(state.to_snapshot()),
                actor=spec.position,
                context_id=f"{spec.context_id}:{hand}",
                population_id=spec.population_id,
                raise_targets_bb=raise_targets,
                rollout=rollout,
                samples_per_candidate=samples_per_candidate,
                base_seed=hand_seed,
                call_action=call_action,
                raise_action=raise_action,
                include_jam=True,
                sizing_grid_source="certified TRAIN exact-node population RAISE empirical p25/p50/p75",
                status="EXPERIMENTAL",
                notes=(
                    "Issue #107 candidate evidence. Sizing grid is TRAIN-only observed population evidence; "
                    "future Hero continuation is the frozen baseline declared in provenance."
                ),
            )
        except (UnsupportedAlternative, PreflopEvaluationError, ModelAUnsupportedContext, ValueError) as exc:
            unsupported.append({"hand_class": hand, "reason": str(exc)})
            continue
        rows.append({"hand_class": hand, "representative_cards": list(cards), "decision": decision})
        total_rollouts += int((decision.get("search") or {}).get("budget") or 0)

    provenance = {
        "code": code_sha,
        "models": {
            "preflop_sha256": policy.identity.get("preflop_sha256"),
            "postflop_baseline_sha256": policy.identity.get("postflop_baseline_sha256"),
            "postflop_continuation_overlay_sha256": policy.identity.get("continuation_overlay_sha256"),
            "postflop_stage_b_decision": policy.identity.get("stage_b_decision"),
        },
        "budget": {
            "requested_hand_classes": len(hand_classes),
            "completed_hand_classes": len(rows),
            "samples_per_nonfold_candidate": int(samples_per_candidate),
            "rollout_samples_consumed": total_rollouts,
        },
        "selection": "NOT_PROMOTED_ISSUE_107_EXPERIMENTAL",
        "master_seed": int(master_seed),
        "hero_future_continuation": hero_continuation.identity,
        "opponent_policy": "MODEL_A_SELECTED_POPULATION_CONTINUATION",
        "sizing_support": sizing_support,
        "decision_source": "tools.simulation.preflop_grid_evaluator.evaluate_preflop_grid",
    }
    return {
        "schema": SCHEMA,
        "status": "EXPERIMENTAL",
        "promotion_authorized": False,
        "population_id": spec.population_id,
        "context": spec.repository_context(),
        "context_id": spec.context_id,
        "version": version,
        "rows": rows,
        "unsupported": unsupported,
        "coverage": {
            "requested": len(hand_classes),
            "completed": len(rows),
            "complete_169": len(hand_classes) == 169 and len(rows) == 169,
        },
        "provenance": provenance,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--position", default="BTN", choices=list(base.DEFAULT_SEATS))
    parser.add_argument("--spot", default="UNOPENED", choices=["UNOPENED", "VS_LIMPERS", "VS_RFI", "VS_RFI_CALLERS"])
    parser.add_argument("--stack-bb", type=float, default=100.0)
    parser.add_argument("--opener-position")
    parser.add_argument("--caller-position")
    parser.add_argument("--limper-position")
    parser.add_argument("--open-to-bb", type=float, default=2.5)
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument("--seed", type=int, default=20260916)
    parser.add_argument("--version", default="hero-calculated-certified-sizing-experimental-v1")
    parser.add_argument("--code-sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--preflop-model", type=Path, default=base.DEFAULT_PREFLOP)
    parser.add_argument("--postflop-model", type=Path, default=base.DEFAULT_POSTFLOP)
    parser.add_argument("--continuation-overlay", type=Path, default=base.DEFAULT_OVERLAY)
    sizing = parser.add_mutually_exclusive_group(required=True)
    sizing.add_argument("--sizing-decisions", type=Path)
    sizing.add_argument("--sizing-evidence", type=Path)
    parser.add_argument("--hand-class", action="append", dest="hand_classes")
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--shard-count", type=int)
    parser.add_argument("--rows-out", type=Path, required=True)
    parser.add_argument("--candidate-out", type=Path)
    parser.add_argument("--allow-partial", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.samples < 1:
        raise SystemExit("--samples must be >= 1")
    if not str(args.code_sha).strip():
        raise SystemExit("--code-sha (or GITHUB_SHA) is required")
    sharded = args.shard_index is not None or args.shard_count is not None
    if sharded:
        if args.shard_index is None or args.shard_count is None:
            raise SystemExit("--shard-index and --shard-count must be supplied together")
        if args.hand_classes:
            raise SystemExit("--hand-class cannot be combined with deterministic sharding")
        if args.shard_count < 1 or args.shard_count > len(base.HAND_CLASSES):
            raise SystemExit("--shard-count must be between 1 and 169")
        if args.shard_index < 0 or args.shard_index >= args.shard_count:
            raise SystemExit("--shard-index must satisfy 0 <= index < count")
        hands = [
            hand for index, hand in enumerate(base.HAND_CLASSES)
            if index % args.shard_count == args.shard_index
        ]
    else:
        hands = args.hand_classes or list(base.HAND_CLASSES)
    unknown = sorted(set(hands) - set(base.HAND_CLASSES))
    if unknown:
        raise SystemExit(f"unknown hand classes: {unknown}")
    if len(hands) != len(set(hands)):
        raise SystemExit("duplicate hand classes are not allowed")
    spec = base.ContextSpec(
        position=args.position,
        effective_stack_bb=args.stack_bb,
        spot=args.spot,
        opener_position=args.opener_position,
        caller_position=args.caller_position,
        limper_position=args.limper_position,
        open_to_bb=args.open_to_bb,
    )
    policy = ModelAContinuationPolicy.from_paths(
        args.preflop_model, args.postflop_model, args.continuation_overlay
    )
    run = generate_run(
        spec=spec,
        policy=policy,
        sizing_decisions=args.sizing_decisions,
        sizing_evidence=args.sizing_evidence,
        hand_classes=hands,
        samples_per_candidate=args.samples,
        master_seed=args.seed,
        code_sha=str(args.code_sha),
        version=args.version,
    )
    if sharded:
        run["provenance"]["shard"] = {
            "index": args.shard_index,
            "count": args.shard_count,
            "partition": "canonical_hand_index_modulo_shard_count",
        }
    args.rows_out.parent.mkdir(parents=True, exist_ok=True)
    args.rows_out.write_text(json.dumps(run, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if run["unsupported"] and not args.allow_partial:
        print(json.dumps({"coverage": run["coverage"], "unsupported": run["unsupported"][:10]}, indent=2))
        return 2
    if args.candidate_out:
        args.candidate_out.parent.mkdir(parents=True, exist_ok=True)
        base.export_candidate(run, run_path=args.rows_out, output_path=args.candidate_out)
    print(json.dumps({
        "context_id": run["context_id"],
        "coverage": run["coverage"],
        "shard": run["provenance"].get("shard"),
        "sizing_support": run["provenance"]["sizing_support"],
        "budget": run["provenance"]["budget"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
