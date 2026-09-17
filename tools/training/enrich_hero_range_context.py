#!/usr/bin/env python3
"""Bind a #107 decision run to the canonical card-free preflop context.

This is deliberately an identity-only transformation.  It reconstructs the same
public ``NoLimitHoldemState`` used by the generator, derives the existing
``poker-preflop-context/v1`` PFC id, and adds that id to the Hero repository
context.  Decisions, alternatives, sizing, EVs, search budgets and seeds are not
recomputed or changed.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop.context_contract import build_context  # noqa: E402
from tools.simulation.model_a_continuation import _preflop_decision, _semantic_trace  # noqa: E402
from tools.training.generate_hero_range_decisions import (  # noqa: E402
    ContextSpec,
    build_context_state,
    export_candidate,
)

SCHEMA = "poker-hero-range-decision-run/v1"


def canonical_context_for_state(state, actor: str) -> dict[str, Any]:
    if state.street != "preflop":
        raise ValueError("Hero range context enrichment is preflop-only")
    if state.next_actor != actor:
        raise ValueError(f"{actor!r} is not next to act")
    _, replay, history, _, _ = _semantic_trace(state)
    if replay.to_snapshot(include_log=False) != state.to_snapshot(include_log=False):
        raise AssertionError("semantic replay diverged while deriving canonical preflop context")
    semantic = _preflop_decision(replay, actor, history)
    view = state.legal_view(actor)
    live = list(state.live_players)
    all_in = [player for player in live if state.all_in[player]]
    contributions = {player: float(state.street_committed_bb[player]) for player in live}
    starting_stacks = {player: float(state.starting_stacks_bb[player]) for player in live}
    context = build_context(
        table_size=len(state.seats),
        actor_position=actor,
        live_positions=live,
        all_in_positions=all_in,
        history=semantic["history"],
        raise_level=int(semantic["raise_level"]),
        contribution_bb_by_position=contributions,
        stack_bb_by_position=starting_stacks,
        pot_before_bb=float(view["pot_before_bb"]),
        current_price_bb=float(view["current_price_bb"]),
        pending_positions=list(view["remaining_to_act"]),
        min_raise_to_bb=(None if view["min_raise_to_bb"] is None else float(view["min_raise_to_bb"])),
        raise_reopened=bool(view["raise_reopened"]),
    )
    if context["family"] != semantic["family"]:
        raise AssertionError(f"canonical family drift: {context['family']} != {semantic['family']}")
    if context["actor_position"] != semantic["actor_position"]:
        raise AssertionError("canonical actor position drift")
    return context


def _assert_run_matches_spec(run: Mapping[str, Any], spec: ContextSpec) -> None:
    if run.get("schema") != SCHEMA:
        raise ValueError(f"expected {SCHEMA}, got {run.get('schema')!r}")
    if str(run.get("population_id")) != spec.population_id:
        raise ValueError("run population does not match requested context")
    context = run.get("context") or {}
    expected = spec.repository_context()
    for field in ("population_id", "table_size", "position", "spot"):
        if str(context.get(field)) != str(expected.get(field)):
            raise ValueError(f"run context {field} does not match requested context")
    if abs(float(context.get("effective_stack_bb")) - float(spec.effective_stack_bb)) > 1e-9:
        raise ValueError("run effective stack does not match requested context")
    if str(run.get("context_id")) != spec.context_id:
        raise ValueError("run legacy context id does not match the reconstructed ContextSpec")


def enrich_run(run: Mapping[str, Any], spec: ContextSpec) -> dict[str, Any]:
    _assert_run_matches_spec(run, spec)
    state = build_context_state(spec)
    canonical = canonical_context_for_state(state, spec.position)
    out = copy.deepcopy(dict(run))
    legacy_id = str(out["context_id"])
    out["legacy_context_id"] = legacy_id
    out["context_id"] = canonical["context_id"]
    out["context"]["preflop_context_id"] = canonical["context_id"]
    out["canonical_preflop_context"] = canonical
    provenance = out.setdefault("provenance", {})
    provenance["context_identity"] = {
        "schema": canonical["schema"],
        "preflop_context_id": canonical["context_id"],
        "legacy_context_id": legacy_id,
        "binding": "IDENTITY_ONLY_FROM_SAME_PUBLIC_STATE_BEFORE_ACTION",
        "decision_payload_mutation": "NONE",
        "rollout_recomputation": false,
    }
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-out", type=Path)
    parser.add_argument("--position", default="BTN")
    parser.add_argument("--spot", default="UNOPENED", choices=["UNOPENED", "VS_LIMPERS", "VS_RFI", "VS_RFI_CALLERS"])
    parser.add_argument("--stack-bb", type=float, default=100.0)
    parser.add_argument("--opener-position")
    parser.add_argument("--caller-position")
    parser.add_argument("--limper-position")
    parser.add_argument("--open-to-bb", type=float, default=2.5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run = json.loads(args.input.read_text(encoding="utf-8"))
    spec = ContextSpec(
        position=args.position,
        effective_stack_bb=args.stack_bb,
        spot=args.spot,
        opener_position=args.opener_position,
        caller_position=args.caller_position,
        limper_position=args.limper_position,
        open_to_bb=args.open_to_bb,
    )
    enriched = enrich_run(run, spec)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(enriched, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.candidate_out:
        args.candidate_out.parent.mkdir(parents=True, exist_ok=True)
        export_candidate(enriched, run_path=args.output, output_path=args.candidate_out)
    print(json.dumps({
        "legacy_context_id": enriched["legacy_context_id"],
        "preflop_context_id": enriched["context_id"],
        "rows": len(enriched.get("rows") or []),
        "rollout_recomputation": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
