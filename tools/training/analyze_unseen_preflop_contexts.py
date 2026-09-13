#!/usr/bin/env python3
"""Characterize TRAIN preflop contexts absent from the promoted Model A topology.

This tool is diagnostic only. It never materializes nodes or changes a promoted
model. It compares a TRAIN-only increment overlay with the exact structural keys
already present in the promoted preflop model and emits a machine-readable support
profile that can be used to decide whether a topology-extension experiment is
statistically justified.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "poker-preflop-unseen-context-audit/v1"


def node_key(node: dict[str, Any]) -> str:
    return str(node.get("canonical_key") or node.get("id") or "")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bucket_support(n: int) -> str:
    if n >= 100:
        return "100_plus"
    if n >= 50:
        return "50_99"
    if n >= 20:
        return "20_49"
    if n >= 10:
        return "10_19"
    if n >= 5:
        return "5_9"
    if n >= 2:
        return "2_4"
    return "1"


def context_signature(context: dict[str, Any]) -> dict[str, Any]:
    history = context.get("history") or []
    return {
        "table_size": context.get("table_size"),
        "actor_position": context.get("actor_position"),
        "family": context.get("family"),
        "raise_level": context.get("raise_level"),
        "free_check": bool(context.get("free_check")),
        "live_player_count": len(context.get("live_positions") or []),
        "allin_player_count": len(context.get("all_in_positions") or []),
        "history_depth": len(history),
        "history_actions": ">".join(str(x.get("action") or "") for x in history),
    }


def _counter(items: list[Any]) -> dict[str, int]:
    c = collections.Counter(str(x) for x in items)
    return dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))


def _weighted_counter(rows: list[dict[str, Any]], getter) -> dict[str, int]:
    c: collections.Counter[str] = collections.Counter()
    for row in rows:
        c[str(getter(row))] += int(row["n_delta"])
    return dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))


def audit(*, baseline: Path, overlay: Path) -> dict[str, Any]:
    base = json.loads(baseline.read_text(encoding="utf-8"))
    inc = json.loads(overlay.read_text(encoding="utf-8"))
    existing = {node_key(x) for x in base.get("nodes", [])}
    pre_nodes = list(inc.get("preflop_nodes") or [])
    unseen = [x for x in pre_nodes if node_key(x) not in existing and int(x.get("n_delta") or 0) > 0]
    seen = [x for x in pre_nodes if node_key(x) in existing and int(x.get("n_delta") or 0) > 0]

    unseen_rows = sum(int(x.get("n_delta") or 0) for x in unseen)
    seen_rows = sum(int(x.get("n_delta") or 0) for x in seen)
    total_rows = unseen_rows + seen_rows
    ordered = sorted(unseen, key=lambda x: (-int(x.get("n_delta") or 0), node_key(x)))

    support_buckets_nodes: collections.Counter[str] = collections.Counter()
    support_buckets_rows: collections.Counter[str] = collections.Counter()
    action_rows: collections.Counter[str] = collections.Counter()
    for row in unseen:
        n = int(row.get("n_delta") or 0)
        b = bucket_support(n)
        support_buckets_nodes[b] += 1
        support_buckets_rows[b] += n
        for action, count in (row.get("actions") or {}).items():
            action_rows[str(action)] += int(count or 0)

    def share_top(k: int) -> float:
        if not unseen_rows:
            return 0.0
        return sum(int(x.get("n_delta") or 0) for x in ordered[:k]) / unseen_rows

    high_support = [x for x in unseen if int(x.get("n_delta") or 0) >= 20]
    very_high_support = [x for x in unseen if int(x.get("n_delta") or 0) >= 50]
    singleton_rows = support_buckets_rows.get("1", 0)
    sparse_rows = sum(v for k, v in support_buckets_rows.items() if k in {"1", "2_4"})

    top_contexts = []
    for row in ordered[:50]:
        ctx = row.get("context") or {}
        top_contexts.append({
            "canonical_key": node_key(row),
            "n_delta": int(row.get("n_delta") or 0),
            "actions": dict(sorted((row.get("actions") or {}).items())),
            "context": context_signature(ctx),
        })

    report = {
        "schema": SCHEMA,
        "baseline": {
            "path": baseline.as_posix(),
            "sha256": sha256_file(baseline),
            "model_version": base.get("model_version"),
            "exact_nodes": len(existing),
        },
        "overlay": {
            "path": overlay.as_posix(),
            "sha256": sha256_file(overlay),
            "preflop_nodes_train": len(pre_nodes),
            "train_population_rows": int((inc.get("summary") or {}).get("train_population_rows") or 0),
        },
        "coverage": {
            "seen_exact_nodes_touched": len(seen),
            "unseen_exact_nodes": len(unseen),
            "seen_rows": seen_rows,
            "unseen_rows": unseen_rows,
            "total_preflop_population_rows": total_rows,
            "unseen_row_fraction": unseen_rows / total_rows if total_rows else 0.0,
        },
        "support": {
            "node_buckets": dict(sorted(support_buckets_nodes.items())),
            "row_buckets": dict(sorted(support_buckets_rows.items())),
            "top_10_row_share": share_top(10),
            "top_25_row_share": share_top(25),
            "top_50_row_share": share_top(50),
            "nodes_ge_20": len(high_support),
            "rows_ge_20": sum(int(x.get("n_delta") or 0) for x in high_support),
            "nodes_ge_50": len(very_high_support),
            "rows_ge_50": sum(int(x.get("n_delta") or 0) for x in very_high_support),
            "singleton_rows": singleton_rows,
            "sparse_rows_n_le_4": sparse_rows,
        },
        "weighted_distribution": {
            "actor_position": _weighted_counter(unseen, lambda x: (x.get("context") or {}).get("actor_position")),
            "family": _weighted_counter(unseen, lambda x: (x.get("context") or {}).get("family")),
            "raise_level": _weighted_counter(unseen, lambda x: (x.get("context") or {}).get("raise_level")),
            "table_size": _weighted_counter(unseen, lambda x: (x.get("context") or {}).get("table_size")),
            "history_depth": _weighted_counter(unseen, lambda x: len((x.get("context") or {}).get("history") or [])),
            "live_player_count": _weighted_counter(unseen, lambda x: len((x.get("context") or {}).get("live_positions") or [])),
            "free_check": _weighted_counter(unseen, lambda x: bool((x.get("context") or {}).get("free_check"))),
            "action": dict(sorted(action_rows.items(), key=lambda kv: (-kv[1], kv[0]))),
        },
        "top_contexts": top_contexts,
        "interpretation_contract": {
            "diagnostic_only": True,
            "production_effect": "NONE",
            "test_used": False,
            "minimum_support_for_structural_candidate": 20,
            "candidate_rule": (
                "A future topology candidate may materialize only pre-specified unseen contexts with TRAIN support >= 20; "
                "all lower-support contexts must continue to use the existing fallback hierarchy. Hyperparameters and the "
                "materialization threshold must be selected on VALIDATION only, with locked TEST reserved for final confirmation."
            ),
        },
    }
    return report


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", required=True, type=Path)
    p.add_argument("--overlay", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    report = audit(baseline=args.baseline, overlay=args.overlay)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"coverage": report["coverage"], "support": report["support"]}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
