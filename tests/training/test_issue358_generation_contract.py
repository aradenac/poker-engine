#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from tools.training.generate_hero_preflop_noniso import (
    ALLOWED_GROUPS,
    FORBIDDEN_GROUPS,
    scope_from_plan,
)

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "analysis/hero_preflop_generation_plan.json"
MANIFEST_SCHEMA = ROOT / "contracts/training/hero-preflop-generation-manifest.schema.json"
STRATEGY_SCHEMA = ROOT / "contracts/training/hero-preflop-strategy.schema.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_issue358_scope_is_mechanical_and_noniso() -> None:
    plan = load(PLAN)
    scope = scope_from_plan(plan)
    assert scope["eligible_context_count"] == 22
    assert scope["eligible_hand_class_cells"] == 3718
    assert scope["eligible_group_counts"] == {
        "RFI_CALLERS_SQUEEZE": 8,
        "VS_RFI": 14,
    }
    assert scope["test_consumed"] is False
    assert scope["nearest_context_allowed"] is False
    by_id = {row["context_id"]: row for row in plan["contexts"]}
    assert scope["eligible_context_ids"] == [
        context_id
        for context_id in plan["generation_order"]
        if by_id[context_id]["coverage_group"] in ALLOWED_GROUPS
    ]
    assert all(by_id[cid]["readiness"] == "READY_FOR_GENERATION" for cid in scope["eligible_context_ids"])
    assert all(by_id[cid]["coverage_group"] not in FORBIDDEN_GROUPS for cid in scope["eligible_context_ids"])
    assert not any(by_id[cid]["coverage_group"] in {"VS_3BET", "VS_4BET_OR_JAM"} for cid in scope["eligible_context_ids"])
    assert len(scope["excluded_ready"]) == 22
    assert {row["coverage_group"] for row in scope["excluded_ready"]} == {"VS_LIMPERS_ISO"}


def test_contracts_expose_authorized_subset_and_nonmeasured_exact_fold() -> None:
    manifest = load(MANIFEST_SCHEMA)
    assert "AUTHORIZED_READY_SUBSET" in manifest["properties"]["generation_scope"]["enum"]
    strategy = load(STRATEGY_SCHEMA)
    for name in ("action", "sizing", "ev", "rollout"):
        assert "EXACT_DETERMINISTIC" in strategy["$defs"][name]["properties"]["status"]["enum"]


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"issue #358 generation contract tests: {len(tests)} passed")
