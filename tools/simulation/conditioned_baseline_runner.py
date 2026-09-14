#!/usr/bin/env python3
"""Run the frozen v83 arena against the unpromoted price-conditioned Model B v3.

This combines the v3 response runtime with the same strict review-detail fallback used
by the frozen v2 strategic baseline. It never changes registry promotion pointers.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from tools.simulation import sequential_postflop as arena
from tools.simulation import sequential_postflop_conditioned as conditioned
from tools.simulation.baseline_runner import BaselineAnalyzerOracle
from tools.simulation.model_b_conditioned_runtime import ConditionedModelBEnvironment


async def run(args) -> dict:
    BaselineAnalyzerOracle.fallback_hand_hashes = []
    original_env = arena.ModelBEnvironment
    original_rollout = arena.rollout
    original_oracle = arena.AnalyzerOracle
    original_preflop_prefix = arena.preflop_prefix
    arena.ModelBEnvironment = ConditionedModelBEnvironment
    arena.rollout = conditioned.rollout
    arena.AnalyzerOracle = BaselineAnalyzerOracle
    arena.preflop_prefix = conditioned.preflop_prefix_for_v83
    try:
        document = await arena.run(args)
    finally:
        arena.ModelBEnvironment = original_env
        arena.rollout = original_rollout
        arena.AnalyzerOracle = original_oracle
        arena.preflop_prefix = original_preflop_prefix

    hashes = sorted(set(BaselineAnalyzerOracle.fallback_hand_hashes))
    document.setdefault("metadata", {})["oracle_reconstruction_fallback"] = {
        "count": len(BaselineAnalyzerOracle.fallback_hand_hashes),
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
        "rule": "French PokerStars source histories are normalized to the equivalent English v83 parser grammar before synthetic postflop actions are appended.",
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
