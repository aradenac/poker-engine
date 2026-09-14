#!/usr/bin/env python3
"""Run the frozen v83 arena against the unpromoted price-conditioned Model B v3.

This combines the v3 response runtime with the same strict review-detail fallback used
by the frozen v2 strategic baseline. It never changes registry promotion pointers.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from tools.simulation import sequential_postflop as arena
from tools.simulation import sequential_postflop_conditioned as conditioned
from tools.simulation import v83_hh_compat as compat
from tools.simulation.baseline_runner import BaselineAnalyzerOracle
from tools.simulation.model_b_conditioned_runtime import ConditionedModelBEnvironment


class ConditionedAnalyzerOracle(BaselineAnalyzerOracle):
    """Baseline oracle with deterministic diagnostics for parser/plan rejection.

    The diagnostic path does not recover, skip, or alter a state. It only turns the
    opaque JavaScript null-plan exception into reproducible evidence that identifies
    whether parsing or review-plan construction rejected the synthetic history.
    """

    async def decide(self, hand_history: str) -> dict:
        try:
            return await super().decide(hand_history)
        except Exception as exc:
            text = str(exc)
            if "Cannot read properties of null (reading 'actions')" not in text:
                raise
            diag = await self.page.evaluate(
                """txt=>{
                  const h=parsePokerStarsHand(txt,'sim');
                  if(!h)return {parse_ok:false,plan_ok:false};
                  const p=buildReviewBatchPlan(h);
                  return {
                    parse_ok:true,
                    plan_ok:!!p,
                    id:String(h.id??''),
                    hero:String(h.heroName??''),
                    action_count:Array.isArray(p?.actions)?p.actions.length:null,
                    streets:Array.isArray(p?.actions)?[...new Set(p.actions.map(a=>a.street))]:[]
                  };
                }""",
                hand_history,
            )
            digest = hashlib.sha256(hand_history.encode("utf-8")).hexdigest()
            numbered = "\n".join(
                f"{i + 1:02d}: {line}" for i, line in enumerate(hand_history.splitlines())
            )
            raise RuntimeError(
                "conditioned synthetic history rejected before evaluation; "
                f"sha256={digest} diag={json.dumps(diag, sort_keys=True)}\n{numbered}"
            ) from exc


async def run(args) -> dict:
    ConditionedAnalyzerOracle.fallback_hand_hashes = []
    original_env = arena.ModelBEnvironment
    original_rollout = arena.rollout
    original_oracle = arena.AnalyzerOracle
    original_preflop_prefix = arena.preflop_prefix
    original_conditioned_prefix = conditioned.preflop_prefix_for_v83
    original_conditioned_action = conditioned.localized_action_line
    original_conditioned_marker = conditioned.street_marker

    def v83_prefix(raw: str) -> str:
        return compat.normalize_prefix_text_for_v83(original_conditioned_prefix(raw))

    arena.ModelBEnvironment = ConditionedModelBEnvironment
    arena.rollout = conditioned.rollout
    arena.AnalyzerOracle = ConditionedAnalyzerOracle
    arena.preflop_prefix = v83_prefix
    # conditioned.rollout resolves these module globals at runtime. Force its
    # synthetic shell to the exact English grammar consumed by the frozen v83
    # parser while preserving the source hand's cards, amounts and chronology.
    conditioned.preflop_prefix_for_v83 = v83_prefix
    conditioned.localized_action_line = compat.action_line_for_v83
    conditioned.street_marker = compat.street_marker_for_v83
    try:
        document = await arena.run(args)
    finally:
        arena.ModelBEnvironment = original_env
        arena.rollout = original_rollout
        arena.AnalyzerOracle = original_oracle
        arena.preflop_prefix = original_preflop_prefix
        conditioned.preflop_prefix_for_v83 = original_conditioned_prefix
        conditioned.localized_action_line = original_conditioned_action
        conditioned.street_marker = original_conditioned_marker

    hashes = sorted(set(ConditionedAnalyzerOracle.fallback_hand_hashes))
    document.setdefault("metadata", {})["oracle_reconstruction_fallback"] = {
        "count": len(ConditionedAnalyzerOracle.fallback_hand_hashes),
        "unique_states": len(hashes),
        "hand_history_sha256": hashes,
        "rule": (
            "Fallback is allowed only when the analyser completed the review action plan "
            "but omitted the finalized review detail; unreconstructible states remain fatal."
        ),
    }
    document["metadata"]["environment_role"] = "unpromoted_response_conditioned_candidate"
    document["metadata"]["production_effect"] = "NONE"
    document["metadata"]["synthetic_history_compatibility"] = {
        "rule": (
            "French PokerStars source prefixes, NBSP actor separators and all synthetic "
            "postflop actions/markers are serialized to the equivalent English v83 parser grammar."
        ),
        "strategy_effect": "NONE",
        "cards_amounts_action_chronology_preserved": True,
    }
    return document


async def main() -> None:
    args = arena.parse_args()
    document = await run(args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"DONE {out} fallback_count={document['metadata']['oracle_reconstruction_fallback']['count']}",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
