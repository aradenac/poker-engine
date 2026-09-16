#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from tools.training.generate_hero_range_decisions import HAND_CLASSES
from tools.training.merge_hero_range_decision_shards import merge


def make_run(index: int, count: int) -> dict:
    hands = [hand for i, hand in enumerate(HAND_CLASSES) if i % count == index]
    rows = [{"hand_class": hand, "representative_cards": ["As", "Ah"], "decision": {"schema": "poker-preflop-decision/v1"}} for hand in hands]
    return {
        "schema": "poker-hero-range-decision-run/v1",
        "status": "EXPERIMENTAL",
        "promotion_authorized": False,
        "population_id": "pokerstars_nlhe_100-200_zoom_play_6max_v1",
        "context": {"population_id": "pokerstars_nlhe_100-200_zoom_play_6max_v1", "table_size": 6, "position": "BTN", "effective_stack_bb": 100.0, "spot": "UNOPENED"},
        "context_id": "ctx",
        "version": "v1",
        "rows": rows,
        "unsupported": [],
        "coverage": {"requested": len(hands), "completed": len(hands), "complete_169": False},
        "provenance": {
            "code": "deadbeef",
            "models": {"preflop_sha256": "a", "postflop_baseline_sha256": "b"},
            "budget": {
                "requested_hand_classes": len(hands),
                "completed_hand_classes": len(hands),
                "samples_per_nonfold_candidate": 8,
                "rollout_samples_consumed": len(hands) * 40,
            },
            "selection": "NOT_PROMOTED_ISSUE_107_EXPERIMENTAL",
            "master_seed": 20260916,
            "hero_future_continuation": {"claim": "NOT_OPTIMAL_HERO_STRATEGY"},
            "opponent_policy": "MODEL_A_SELECTED_POPULATION_CONTINUATION",
            "sizing_support": {"contract": "CERTIFIED_TRAIN_EXACT_NODE_EMPIRICAL_RAISE_SIZING_V1", "evidence_sha256": "c"},
            "decision_source": "tools.simulation.preflop_grid_evaluator.evaluate_preflop_grid",
            "shard": {"index": index, "count": count, "partition": "canonical_hand_index_modulo_shard_count"},
        },
    }


def main() -> None:
    count = 17
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        paths = []
        for index in range(count):
            path = root / f"shard-{index}.json"
            path.write_text(json.dumps(make_run(index, count)), encoding="utf-8")
            paths.append(path)
        out = merge(paths)
        assert out["coverage"] == {"requested": 169, "completed": 169, "complete_169": True}
        assert [row["hand_class"] for row in out["rows"]] == list(HAND_CLASSES)
        assert out["unsupported"] == []
        assert out["provenance"]["budget"]["samples_per_nonfold_candidate"] == 8
        assert out["provenance"]["budget"]["rollout_samples_consumed"] == 169 * 40
        assert out["provenance"]["budget"]["shard_count"] == count
        assert "shard" not in out["provenance"]
        assert len(out["provenance"]["merge"]["input_shards"]) == count

        duplicate = root / "duplicate.json"
        duplicate.write_text(json.dumps(make_run(0, count)), encoding="utf-8")
        try:
            merge(paths + [duplicate])
        except ValueError as exc:
            assert "duplicate shard index" in str(exc)
        else:
            raise AssertionError("duplicate shard must fail closed")

        bad = copy.deepcopy(make_run(1, count))
        bad["provenance"]["master_seed"] = 7
        bad_path = root / "bad.json"
        bad_path.write_text(json.dumps(bad), encoding="utf-8")
        replaced = [paths[0], bad_path] + paths[2:]
        try:
            merge(replaced)
        except ValueError as exc:
            assert "provenance mismatch" in str(exc)
        else:
            raise AssertionError("cross-shard provenance drift must fail closed")

    print("Hero 169 deterministic shard merge contract: PASS")


if __name__ == "__main__":
    main()
