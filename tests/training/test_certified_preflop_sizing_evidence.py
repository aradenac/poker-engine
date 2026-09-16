#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from tools.training.generate_certified_hero_range_decisions import empirical_raise_targets
from tools.training.generate_hero_range_decisions import ContextSpec, build_context_state
from tools.simulation.model_a_continuation import ModelAUnsupportedContext


def row(*, split="TRAIN", is_hero=False, action="RAISE", key="exact", target=2.5):
    return {
        "split": split,
        "street": "preflop",
        "is_hero": is_hero,
        "action": action,
        "v4_canonical_key": key,
        "action_sizing_v1": {"target_total_bb": target},
    }


def main() -> None:
    state = build_context_state(ContextSpec(position="BTN", spot="UNOPENED", effective_stack_bb=100.0))
    rows = [
        row(target=2.0), row(target=2.5), row(target=3.0), row(target=4.0),
        row(split="VALIDATION", target=8.0),
        row(split="TEST", target=9.0),
        row(is_hero=True, target=7.0),
        row(action="JAM", target=100.0),
        row(key="other", target=6.0),
    ]
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "decisions.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        targets, support = empirical_raise_targets(
            path, canonical_key="exact", state=state, actor="BTN"
        )
        assert targets == [2.0, 2.5, 3.0], targets
        assert support["matching_population_decisions"] == 5, support
        assert support["observed_nonjam_raises"] == 4, support
        assert support["empirical_nearest_rank_targets_bb"] == {
            "p25": 2.0, "p50": 2.5, "p75": 3.0
        }, support
        assert support["filters"]["split"] == "TRAIN"
        assert support["filters"]["is_hero"] is False
        assert support["filters"]["jam"].startswith("excluded")
        assert len(support["decisions_sha256"]) == 64

        empty = Path(td) / "empty.jsonl"
        empty.write_text(json.dumps(row(split="VALIDATION", target=2.5)) + "\n", encoding="utf-8")
        try:
            empirical_raise_targets(empty, canonical_key="exact", state=state, actor="BTN")
        except ModelAUnsupportedContext:
            pass
        else:
            raise AssertionError("VALIDATION sizing evidence must never substitute for missing TRAIN support")

    print("Certified TRAIN exact-node sizing evidence contract: PASS")


if __name__ == "__main__":
    main()
