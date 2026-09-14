#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.evaluate_preflop_topology_candidate import (  # noqa: E402
    build_target_specs,
    by_actor,
    find_closest,
    load_json,
    read_rows,
    representative,
)


def context_diff(a: dict, b: dict) -> list[str]:
    fields = (
        "table_size", "actor_position", "family", "raise_level", "free_check",
        "live_positions", "all_in_positions", "history",
    )
    return [name for name in fields if a.get(name) != b.get(name)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True, type=Path)
    ap.add_argument("--decisions", required=True, type=Path)
    ap.add_argument("--overlay", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    baseline = load_json(args.baseline)
    overlay = load_json(args.overlay)
    _, train_by_key = read_rows(args.decisions, "VALIDATION")
    specs = build_target_specs(baseline, overlay, train_by_key, 20)
    index = by_actor(list(baseline.get("nodes") or []))
    rows = []
    action_collisions = 0
    free_only_actions = 0
    targets_all_free_only = 0

    for spec in specs:
        per_action = []
        all_free_only = True
        for action in spec["actions"]:
            decision = representative(spec["context"], train_by_key[spec["key"]], action)
            match = find_closest(index, decision)
            if not match or not match["exact"]:
                all_free_only = False
                per_action.append({"action": action, "runtime_exact": False})
                continue
            action_collisions += 1
            node = match["node"]
            diff = context_diff(spec["context"], node.get("context") or {})
            free_only = diff == ["free_check"]
            free_only_actions += int(free_only)
            all_free_only = all_free_only and free_only
            per_action.append({
                "action": action,
                "runtime_exact": True,
                "baseline_node_id": node.get("id"),
                "baseline_canonical_key": node.get("canonical_key"),
                "baseline_support": int((node.get("coverage") or {}).get("population_decisions") or 0),
                "target_support": spec["support"],
                "context_diff_fields": diff,
                "free_check_only": free_only,
            })
        targets_all_free_only += int(all_free_only)
        rows.append({
            "target_canonical_key": spec["key"],
            "target_support": spec["support"],
            "target_free_check": bool(spec["context"].get("free_check")),
            "all_actions_runtime_exact_free_check_only": all_free_only,
            "actions": per_action,
        })

    result = {
        "schema": "poker-preflop-runtime-topology-overlap/v1",
        "target_contract": "canonical contexts absent from v5 with TRAIN support >=20",
        "target_nodes": len(specs),
        "target_train_rows": sum(x["support"] for x in specs),
        "runtime_exact_action_collisions": action_collisions,
        "runtime_exact_action_collisions_free_check_only": free_only_actions,
        "targets_all_actions_collide_free_check_only": targets_all_free_only,
        "conclusion": (
            "ALL_TARGETS_ALREADY_RUNTIME_EXACT_DUE_TO_FREE_CHECK_OMISSION"
            if targets_all_free_only == len(specs) else
            "MIXED_RUNTIME_OVERLAP"
        ),
        "production_effect": "NONE",
        "test_used": False,
        "targets": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "target_nodes", "target_train_rows", "runtime_exact_action_collisions",
        "runtime_exact_action_collisions_free_check_only",
        "targets_all_actions_collide_free_check_only", "conclusion",
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
