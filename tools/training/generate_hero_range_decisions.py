#!/usr/bin/env python3
"""Generate #107 Hero range decision evidence from the real #106 preflop engine.

The output of this module is deliberately an *experimental decision run*, not a
promoted Hero range.  Every exported hand class is evaluated through
``evaluate_preflop_grid`` and keeps the resulting ``poker-preflop-decision/v1``
object intact.  A separate Node exporter turns the rows into the existing
``poker-hero-calculated-range-candidate/v1`` repository contract.

Opponent reactions use selected Model A.  Hero actions *after* the fixed
preflop candidate use an explicitly labelled, frozen population-derived
continuation baseline.  This baseline is an evaluation device only; it is not
claimed to be an optimal Hero strategy and is not an opponent-range copy.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.game_core import EPS, NoLimitHoldemState
from tools.simulation.model_a_continuation import (
    ModelAContinuationPolicy,
    ModelAUnsupportedContext,
    _empirical_raise_target,
    _preflop_decision,
    _semantic_trace,
    exact_preflop_node,
)
from tools.simulation.model_a_preflop_rollout import ModelAPreflopContinuationRollout
from tools.simulation.model_b_runtime import combo_class
from tools.simulation.preflop_grid_evaluator import (
    PreflopEvaluationError,
    UnsupportedAlternative,
    evaluate_preflop_grid,
)

SCHEMA = "poker-hero-range-decision-run/v1"
POPULATION_ID = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
RANKS = "AKQJT98765432"
DEFAULT_PREFLOP = ROOT / "training/models/preflop_population_model_v5.json"
DEFAULT_POSTFLOP = ROOT / "training/models/postflop_population_model_v5.json"
DEFAULT_OVERLAY = ROOT / "training/runs/20260916_model_a_postflop_continuation_v1/postflop-selected-overlay.json"
DEFAULT_SEATS = ("BTN", "SB", "BB", "LJ", "HJ", "CO")


def canonical_hand_classes() -> list[str]:
    out: list[str] = []
    for i, hi in enumerate(RANKS):
        out.append(hi + hi)
        for lo in RANKS[i + 1 :]:
            out.extend((hi + lo + "s", hi + lo + "o"))
    if len(out) != 169 or len(set(out)) != 169:
        raise AssertionError("canonical hand-class generator must produce 169 unique classes")
    return out


HAND_CLASSES = tuple(canonical_hand_classes())


def representative_cards(hand_class: str) -> tuple[str, str]:
    """Return one deterministic collision-free concrete combo for a 169 class."""
    hand = str(hand_class).strip()
    if len(hand) == 2 and hand[0] == hand[1] and hand[0] in RANKS:
        cards = (hand[0] + "s", hand[1] + "h")
    elif len(hand) == 3 and hand[0] in RANKS and hand[1] in RANKS and hand[0] != hand[1]:
        if hand[2] == "s":
            cards = (hand[0] + "s", hand[1] + "s")
        elif hand[2] == "o":
            cards = (hand[0] + "s", hand[1] + "h")
        else:
            raise ValueError(f"invalid hand class {hand_class!r}")
    else:
        raise ValueError(f"invalid hand class {hand_class!r}")
    if combo_class(cards) != hand:
        raise AssertionError(f"representative {cards!r} does not map back to {hand!r}")
    return cards


@dataclasses.dataclass(frozen=True)
class ContextSpec:
    population_id: str = POPULATION_ID
    table_size: int = 6
    position: str = "BTN"
    effective_stack_bb: float = 100.0
    spot: str = "UNOPENED"
    opener_position: str | None = None
    caller_position: str | None = None
    limper_position: str | None = None
    open_to_bb: float = 2.5

    @property
    def context_id(self) -> str:
        extras = []
        for key in ("opener_position", "caller_position", "limper_position"):
            value = getattr(self, key)
            if value:
                extras.append(f"{key}={value}")
        suffix = ":" + ",".join(extras) if extras else ""
        return (
            f"{self.population_id}:{self.table_size}max:{self.position}:"
            f"{self.spot}:{self.effective_stack_bb:g}bb{suffix}"
        )

    def repository_context(self) -> dict[str, Any]:
        return {
            "population_id": self.population_id,
            "table_size": self.table_size,
            "position": self.position,
            "effective_stack_bb": float(self.effective_stack_bb),
            "spot": self.spot,
        }


class FixedPopulationDerivedHeroContinuation:
    """Explicit fixed future-Hero baseline; never presented as an optimized policy."""

    contract = "FIXED_POPULATION_DERIVED_MODEL_A_CONTINUATION_BASELINE_V1"

    def __init__(self, policy: ModelAContinuationPolicy) -> None:
        self.policy = policy
        self.identity = {
            "contract": self.contract,
            "purpose": "future-Hero continuation baseline after the fixed candidate",
            "claim": "NOT_OPTIMAL_HERO_STRATEGY",
            "source_model_a": dict(policy.identity),
        }

    def decide(self, state: NoLimitHoldemState, **kwargs: Any) -> Mapping[str, Any]:
        return self.policy.decide(state, **kwargs)


def _apply_until_actor(state: NoLimitHoldemState, target: str, chooser) -> None:
    for _ in range(12):
        actor = state.next_actor
        if actor is None:
            raise ValueError(f"betting closed before target actor {target}")
        if actor == target:
            return
        action, target_total = chooser(actor, state)
        state.apply_action(actor, action, target_total_bb=target_total)
    raise RuntimeError(f"failed to reach target actor {target}")


def build_context_state(spec: ContextSpec) -> NoLimitHoldemState:
    if spec.table_size != 6:
        raise ValueError("current #107 generator supports the certified 6-max population only")
    if spec.position not in DEFAULT_SEATS:
        raise ValueError(f"unsupported 6-max position {spec.position!r}")
    if spec.position == "BB" and spec.spot == "UNOPENED":
        raise ValueError("BB has no meaningful UNOPENED decision after SB acts")
    if spec.effective_stack_bb <= 1:
        raise ValueError("effective_stack_bb must exceed one big blind")

    stacks = {seat: float(spec.effective_stack_bb) for seat in DEFAULT_SEATS}
    state = NoLimitHoldemState(seats=DEFAULT_SEATS, button="BTN", stacks_bb=stacks)
    spot = spec.spot.upper()

    if spot == "UNOPENED":
        _apply_until_actor(state, spec.position, lambda actor, _state: ("FOLD", None))
        return state

    if spot == "VS_LIMPERS":
        limper = spec.limper_position
        if not limper:
            raise ValueError("VS_LIMPERS requires limper_position")
        seen_limper = False

        def choose(actor: str, _state: NoLimitHoldemState):
            nonlocal seen_limper
            if actor == limper:
                seen_limper = True
                return "CALL", None
            return "FOLD", None

        _apply_until_actor(state, spec.position, choose)
        if not seen_limper:
            raise ValueError("limper_position must act before Hero")
        return state

    if spot in {"VS_RFI", "VS_RFI_CALLERS"}:
        opener = spec.opener_position
        if not opener:
            raise ValueError(f"{spot} requires opener_position")
        opened = False
        called = False
        caller = spec.caller_position
        if spot == "VS_RFI_CALLERS" and not caller:
            raise ValueError("VS_RFI_CALLERS requires caller_position")

        def choose(actor: str, _state: NoLimitHoldemState):
            nonlocal opened, called
            if actor == opener:
                opened = True
                return "RAISE", float(spec.open_to_bb)
            if spot == "VS_RFI_CALLERS" and actor == caller:
                if not opened:
                    raise ValueError("caller_position must act after opener_position")
                called = True
                return "CALL", None
            return "FOLD", None

        _apply_until_actor(state, spec.position, choose)
        if not opened or (spot == "VS_RFI_CALLERS" and not called):
            raise ValueError("declared opener/caller must act before Hero")
        return state

    raise ValueError(f"unsupported spot {spec.spot!r}")


def _stat_values(stats: Any) -> list[float]:
    if isinstance(stats, (int, float)):
        return [float(stats)]
    if not isinstance(stats, Mapping):
        return []
    values = []
    for key in ("p10", "p25", "q25", "median", "p50", "mean", "p75", "q75", "p90"):
        value = stats.get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def observed_raise_targets(
    policy: ModelAContinuationPolicy,
    state: NoLimitHoldemState,
    actor: str,
) -> tuple[list[float], dict[str, Any]]:
    """Build a legal grid from exact-node continuous observations, never a fixed chart."""
    trace, replay, history, _, _ = _semantic_trace(state)
    del trace
    decision = _preflop_decision(replay, actor, history)
    node = exact_preflop_node(policy.preflop_model, decision)
    if node is None:
        raise ModelAUnsupportedContext(f"no exact preflop node for {decision!r}")
    view = state.legal_view(actor)
    paid = float(view["actor_street_contribution_bb"])
    pot = float(view["pot_before_bb"])
    current = float(view["current_price_bb"])
    minimum = view["min_raise_to_bb"]
    maximum = float(view["max_raise_to_bb"])
    values: list[tuple[float, str]] = []

    def add(value: float, source: str) -> None:
        if not (value > current + EPS and value <= maximum + EPS):
            return
        if minimum is not None and value + EPS < float(minimum):
            return
        if abs(value - maximum) <= EPS:
            return
        values.append((round(float(value), 6), source))

    containers = [
        ("node", node.get("continuous") or {}),
        ("population", (node.get("population_model") or {}).get("continuous") or {}),
    ]
    for container_name, container in containers:
        for field in ("target_total_bb", "raise_to_bb"):
            for value in _stat_values(container.get(field)):
                add(value, f"{container_name}.{field}")
        for field in ("action_add_bb", "raise_add_bb"):
            for value in _stat_values(container.get(field)):
                add(paid + value, f"{container_name}.{field}")
        for field in ("own_size_pot", "raise_size_pot", "action_size_pot"):
            for value in _stat_values(container.get(field)):
                if pot > EPS:
                    add(paid + value * pot, f"{container_name}.{field}")

    observed_count = len(values)
    empirical, empirical_source = _empirical_raise_target(node, state, actor)
    if empirical_source != "LEGAL_MIN_FALLBACK":
        add(empirical, empirical_source)
    if observed_count == 0 and empirical_source == "LEGAL_MIN_FALLBACK":
        raise ModelAUnsupportedContext("exact preflop node exposes no observed legal raise sizing")
    unique = sorted({value for value, _ in values})
    sources = sorted({source for _, source in values})
    if not unique:
        raise ModelAUnsupportedContext("observed raise sizings exist but none are legal in this stack context")
    return unique, {
        "node_id": node.get("node_id") or node.get("id"),
        "population_decisions": int((node.get("coverage") or {}).get("population_decisions") or 0),
        "sources": sources,
        "grid_contract": "EXACT_NODE_CONTINUOUS_OBSERVATIONS_ONLY_PLUS_SEPARATE_JAM",
    }


def semantic_grid_labels(state: NoLimitHoldemState) -> tuple[str, str]:
    trace, _, history, _, _ = _semantic_trace(state)
    del trace
    raises = [row for row in history if row["action"] in {"RAISE", "JAM"}]
    limps = [row for row in history if row["action"] == "LIMP"]
    if not raises:
        return ("OVERLIMP" if limps else "LIMP", "ISO" if limps else "OPEN")
    last_raise_index = max(i for i, row in enumerate(history) if row["action"] in {"RAISE", "JAM"})
    callers_after_last_raise = any(row["action"] == "CALL" for row in history[last_raise_index + 1 :])
    if len(raises) == 1:
        return "CALL", "SQUEEZE" if callers_after_last_raise else "3BET"
    if len(raises) == 2:
        return "CALL", "4BET"
    return "CALL", f"{len(raises) + 2}BET"


def generate_run(
    *,
    spec: ContextSpec,
    policy: ModelAContinuationPolicy,
    hand_classes: Sequence[str],
    samples_per_candidate: int,
    master_seed: int,
    code_sha: str,
    version: str,
) -> dict[str, Any]:
    state = build_context_state(spec)
    if state.next_actor != spec.position:
        raise AssertionError(f"context actor mismatch: {state.next_actor!r} != {spec.position!r}")
    raise_targets, sizing_support = observed_raise_targets(policy, state, spec.position)
    call_action, raise_action = semantic_grid_labels(state)
    hero_continuation = FixedPopulationDerivedHeroContinuation(policy)
    rows = []
    unsupported = []
    total_rollouts = 0

    for hand in hand_classes:
        cards = representative_cards(hand)
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
                sizing_grid_source=(
                    "ModelA exact-node continuous observations; "
                    + ",".join(sizing_support["sources"])
                ),
                status="EXPERIMENTAL",
                notes=(
                    "Issue #107 candidate evidence. Future Hero continuation is the frozen "
                    "population-derived baseline declared in run provenance; no promotion implied."
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


def export_candidate(run: Mapping[str, Any], *, run_path: Path, output_path: Path) -> None:
    del run
    cmd = [
        "node",
        str(ROOT / "tools/training/export_calculated_hero_candidate.mjs"),
        "--input",
        str(run_path),
        "--output",
        str(output_path),
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--position", default="BTN", choices=list(DEFAULT_SEATS))
    parser.add_argument("--spot", default="UNOPENED", choices=["UNOPENED", "VS_LIMPERS", "VS_RFI", "VS_RFI_CALLERS"])
    parser.add_argument("--stack-bb", type=float, default=100.0)
    parser.add_argument("--opener-position")
    parser.add_argument("--caller-position")
    parser.add_argument("--limper-position")
    parser.add_argument("--open-to-bb", type=float, default=2.5)
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument("--seed", type=int, default=20260916)
    parser.add_argument("--version", default="hero-calculated-experimental-v1")
    parser.add_argument("--code-sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--preflop-model", type=Path, default=DEFAULT_PREFLOP)
    parser.add_argument("--postflop-model", type=Path, default=DEFAULT_POSTFLOP)
    parser.add_argument("--continuation-overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--hand-class", action="append", dest="hand_classes", help="limit to selected 169 class; repeatable for smoke runs")
    parser.add_argument("--rows-out", type=Path, required=True)
    parser.add_argument("--candidate-out", type=Path)
    parser.add_argument("--allow-partial", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.samples < 1:
        raise SystemExit("--samples must be >= 1")
    if not str(args.code_sha).strip():
        raise SystemExit("--code-sha (or GITHUB_SHA) is required for reproducible provenance")
    hands = args.hand_classes or list(HAND_CLASSES)
    unknown = sorted(set(hands) - set(HAND_CLASSES))
    if unknown:
        raise SystemExit(f"unknown hand classes: {unknown}")
    if len(hands) != len(set(hands)):
        raise SystemExit("duplicate --hand-class values are not allowed")
    spec = ContextSpec(
        position=args.position,
        effective_stack_bb=args.stack_bb,
        spot=args.spot,
        opener_position=args.opener_position,
        caller_position=args.caller_position,
        limper_position=args.limper_position,
        open_to_bb=args.open_to_bb,
    )
    policy = ModelAContinuationPolicy.from_paths(
        args.preflop_model,
        args.postflop_model,
        args.continuation_overlay,
    )
    run = generate_run(
        spec=spec,
        policy=policy,
        hand_classes=hands,
        samples_per_candidate=args.samples,
        master_seed=args.seed,
        code_sha=str(args.code_sha),
        version=args.version,
    )
    args.rows_out.parent.mkdir(parents=True, exist_ok=True)
    args.rows_out.write_text(json.dumps(run, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if run["unsupported"] and not args.allow_partial:
        print(json.dumps({"coverage": run["coverage"], "unsupported": run["unsupported"][:10]}, indent=2))
        return 2
    if args.candidate_out:
        args.candidate_out.parent.mkdir(parents=True, exist_ok=True)
        export_candidate(run, run_path=args.rows_out, output_path=args.candidate_out)
    print(json.dumps({"context_id": run["context_id"], "coverage": run["coverage"], "budget": run["provenance"]["budget"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
