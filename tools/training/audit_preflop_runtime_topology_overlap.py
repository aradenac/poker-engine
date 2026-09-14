#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
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


def canonical_parts(key: str | None) -> dict[str, str]:
    if not key:
        return {}
    bits = str(key).split("|")
    out: dict[str, str] = {}
    if bits:
        out["table_size"] = bits[0]
    if len(bits) > 1:
        out["actor_position"] = bits[1]
    for bit in bits[2:]:
        if "=" in bit:
            k, v = bit.split("=", 1)
            out[k] = v
    return out


def canonical_diff(a: str | None, b: str | None) -> list[str]:
    aa, bb = canonical_parts(a), canonical_parts(b)
    keys = sorted(set(aa) | set(bb))
    return [key for key in keys if aa.get(key) != bb.get(key)]


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
    canonical_diff_counts: collections.Counter[str] = collections.Counter()
    context_diff_counts: collections.Counter[str] = collections.Counter()
    targets_single_canonical_diff: collections.Counter[str] = collections.Counter()

    for spec in specs:
        per_action = []
        target_canonical_diff_sets: set[tuple[str, ...]] = set()
        for action in spec["actions"]:
            decision = representative(spec["context"], train_by_key[spec["key"]], action)
            match = find_closest(index, decision)
            if not match or not match["exact"]:
                per_action.append({"action": action, "runtime_exact": False})
                continue
            action_collisions += 1
            node = match["node"]
            ctx_diff = context_diff(spec["context"], node.get("context") or {})
            can_diff = canonical_diff(spec["key"], node.get("canonical_key") or node.get("id"))
            canonical_diff_counts[",".join(can_diff) or "NONE"] += 1
            context_diff_counts[",".join(ctx_diff) or "NONE"] += 1
            target_canonical_diff_sets.add(tuple(can_diff))
            per_action.append({
                "action": action,
                "runtime_exact": True,
                "baseline_node_id": node.get("id"),
                "baseline_canonical_key": node.get("canonical_key"),
                "baseline_support": int((node.get("coverage") or {}).get("population_decisions") or 0),
                "target_support": spec["support"],
                "canonical_diff_fields": can_diff,
                "context_diff_fields": ctx_diff,
            })
        if len(target_canonical_diff_sets) == 1:
            only = next(iter(target_canonical_diff_sets))
            targets_single_canonical_diff[",".join(only) or "NONE"] += 1
        else:
            targets_single_canonical_diff["MIXED"] += 1
        rows.append({
            "target_canonical_key": spec["key"],
            "target_support": spec["support"],
            "target_free_check": bool(spec["context"].get("free_check")),
            "actions": per_action,
        })

    all_actions_collide = all(
        all(action.get("runtime_exact") for action in row["actions"])
        for row in rows
    )
    result = {
        "schema": "poker-preflop-runtime-topology-overlap/v2",
        "target_contract": "canonical contexts absent from v5 with TRAIN support >=20",
        "target_nodes": len(specs),
        "target_train_rows": sum(x["support"] for x in specs),
        "runtime_exact_action_collisions": action_collisions,
        "all_target_actions_already_runtime_exact": all_actions_collide,
        "canonical_diff_distribution_by_action": dict(sorted(canonical_diff_counts.items())),
        "context_diff_distribution_by_action": dict(sorted(context_diff_counts.items())),
        "target_canonical_diff_distribution": dict(sorted(targets_single_canonical_diff.items())),
        "conclusion": (
            "CANONICAL_TOPOLOGY_EXTENSION_IS_RUNTIME_NO_OP"
            if all_actions_collide else
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
        "all_target_actions_already_runtime_exact", "canonical_diff_distribution_by_action",
        "target_canonical_diff_distribution", "conclusion",
    )}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
