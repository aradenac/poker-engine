#!/usr/bin/env python3
"""Audit canonical-key identity against the production preflop runtime matcher.

This is diagnostic only. It never rewrites the promoted model.  The runtime
signature intentionally mirrors the exactStruct predicate used by v83/v5:
actor position (index partition), table size, raise level, family, live/all-in
position arrays and action/position history.  `free_check` is intentionally not
part of that runtime signature because production does not use it for an exact
match.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return data


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


def history_token(history: list[dict[str, Any]] | None) -> str:
    return ">".join(f"{x.get('position','')}:{x.get('action','')}" for x in (history or []))


def context_parts(context: dict[str, Any]) -> dict[str, str]:
    return {
        "table_size": str(int(context.get("table_size") or 0)),
        "actor_position": str(context.get("actor_position") or ""),
        "family": str(context.get("family") or ""),
        "rl": str(int(context.get("raise_level") or 0)),
        "free": "1" if context.get("free_check") else "0",
        "live": ",".join(str(x) for x in (context.get("live_positions") or [])),
        "allin": ",".join(str(x) for x in (context.get("all_in_positions") or [])),
        "hist": history_token(context.get("history") or []),
    }


def canonical_from_context(context: dict[str, Any]) -> str:
    p = context_parts(context)
    return (
        f"{p['table_size']}|{p['actor_position']}|family={p['family']}|rl={p['rl']}|"
        f"free={p['free']}|live={p['live']}|allin={p['allin']}|hist={p['hist']}"
    )


def canonical_diff_fields(key: str | None, context: dict[str, Any]) -> list[str]:
    stored = canonical_parts(key)
    derived = context_parts(context)
    keys = ("table_size", "actor_position", "family", "rl", "free", "live", "allin", "hist")
    return [k for k in keys if stored.get(k) != derived.get(k)]


def runtime_signature(context: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(context.get("actor_position") or ""),
        int(context.get("table_size") or 0),
        int(context.get("raise_level") or 0),
        str(context.get("family") or ""),
        tuple(context.get("live_positions") or []),
        tuple(context.get("all_in_positions") or []),
        tuple((str(x.get("position") or ""), str(x.get("action") or "")) for x in (context.get("history") or [])),
    )


def parse_hist_token(value: str | None) -> list[tuple[str, str]]:
    if not value:
        return []
    out = []
    for bit in str(value).split(">"):
        if not bit:
            continue
        pos, sep, action = bit.partition(":")
        out.append((pos, action if sep else ""))
    return out


def classify_hist_mismatch(stored_hist: str | None, context: dict[str, Any]) -> str:
    a = parse_hist_token(stored_hist)
    b = [(str(x.get("position") or ""), str(x.get("action") or "")) for x in (context.get("history") or [])]
    if a == b:
        return "MATCH"
    if len(a) < len(b) and a == b[: len(a)]:
        return "CANONICAL_PREFIX_OF_CONTEXT"
    if len(b) < len(a) and b == a[: len(b)]:
        return "CONTEXT_PREFIX_OF_CANONICAL"
    if [x[1] for x in a] == [x[1] for x in b] and [x[0] for x in a] != [x[0] for x in b]:
        return "POSITION_ONLY_DIFFERENCE"
    if [x[0] for x in a] == [x[0] for x in b] and [x[1] for x in a] != [x[1] for x in b]:
        return "ACTION_ONLY_DIFFERENCE"
    return "OTHER"


def legal_actions(node: dict[str, Any]) -> set[str]:
    return {str(x) for x in ((node.get("population_model") or {}).get("legal_actions") or [])}


def support(node: dict[str, Any]) -> int:
    return int((node.get("coverage") or {}).get("population_decisions") or 0)


def audit(model: dict[str, Any], *, examples_limit: int = 25) -> dict[str, Any]:
    nodes = list(model.get("nodes") or [])
    mismatch_fields: collections.Counter[str] = collections.Counter()
    hist_patterns: collections.Counter[str] = collections.Counter()
    mismatch_examples: list[dict[str, Any]] = []
    mismatch_nodes = 0
    mismatch_support = 0

    runtime_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = collections.defaultdict(list)
    for node in nodes:
        ctx = node.get("context") or {}
        runtime_groups[runtime_signature(ctx)].append(node)
        diffs = canonical_diff_fields(node.get("canonical_key"), ctx)
        if diffs:
            mismatch_nodes += 1
            mismatch_support += support(node)
            mismatch_fields[",".join(diffs)] += 1
            stored_hist = canonical_parts(node.get("canonical_key")).get("hist")
            pattern = classify_hist_mismatch(stored_hist, ctx) if "hist" in diffs else "NO_HIST_MISMATCH"
            hist_patterns[pattern] += 1
            if len(mismatch_examples) < examples_limit:
                mismatch_examples.append({
                    "id": node.get("id"),
                    "support": support(node),
                    "canonical_key": node.get("canonical_key"),
                    "derived_canonical_key": canonical_from_context(ctx),
                    "diff_fields": diffs,
                    "hist_pattern": pattern,
                    "stored_hist": stored_hist or "",
                    "context_hist": history_token(ctx.get("history") or []),
                })

    collision_groups = 0
    collision_nodes: set[str] = set()
    collision_support = 0
    collision_actions = 0
    shadowed_support_by_action = 0
    group_examples: list[dict[str, Any]] = []
    canonical_keys_in_collisions: set[str] = set()

    for sig, group in runtime_groups.items():
        if len(group) < 2:
            continue
        per_action = []
        group_has_collision = False
        for action in sorted(set().union(*(legal_actions(n) for n in group))):
            eligible = [n for n in group if action in legal_actions(n)]
            if len(eligible) < 2:
                continue
            group_has_collision = True
            collision_actions += 1
            ranked = sorted(eligible, key=lambda n: (-support(n), str(n.get("id") or "")))
            winner = ranked[0]
            losers = ranked[1:]
            shadowed = sum(support(n) for n in losers)
            shadowed_support_by_action += shadowed
            per_action.append({
                "action": action,
                "winner_id": winner.get("id"),
                "winner_support": support(winner),
                "loser_ids": [n.get("id") for n in losers],
                "loser_support": shadowed,
            })
        if not group_has_collision:
            continue
        collision_groups += 1
        for n in group:
            nid = str(n.get("id") or n.get("canonical_key") or "")
            collision_nodes.add(nid)
            collision_support += support(n)
            canonical_keys_in_collisions.add(str(n.get("canonical_key") or ""))
        if len(group_examples) < examples_limit:
            group_examples.append({
                "actor_position": sig[0],
                "table_size": sig[1],
                "raise_level": sig[2],
                "family": sig[3],
                "live_positions": list(sig[4]),
                "all_in_positions": list(sig[5]),
                "history": [{"position": p, "action": a} for p, a in sig[6]],
                "node_ids": [n.get("id") for n in group],
                "canonical_keys": [n.get("canonical_key") for n in group],
                "free_check_values": sorted({bool((n.get("context") or {}).get("free_check")) for n in group}),
                "total_support": sum(support(n) for n in group),
                "action_collisions": per_action,
            })

    total_support = sum(support(n) for n in nodes)
    exact_context_keys = collections.Counter(canonical_from_context(n.get("context") or {}) for n in nodes)
    duplicated_derived_keys = {k: v for k, v in exact_context_keys.items() if v > 1}

    return {
        "schema": "poker-preflop-canonical-runtime-parity/v1",
        "model": {
            "schema": model.get("schema"),
            "version": model.get("version") or model.get("model_version"),
            "nodes": len(nodes),
            "population_decision_support": total_support,
        },
        "canonical_context_parity": {
            "mismatch_nodes": mismatch_nodes,
            "mismatch_node_fraction": mismatch_nodes / len(nodes) if nodes else 0.0,
            "mismatch_support": mismatch_support,
            "mismatch_support_fraction": mismatch_support / total_support if total_support else 0.0,
            "diff_field_distribution": dict(sorted(mismatch_fields.items())),
            "hist_mismatch_pattern_distribution": dict(sorted(hist_patterns.items())),
            "duplicated_context_derived_canonical_keys": len(duplicated_derived_keys),
            "examples": mismatch_examples,
        },
        "runtime_equivalence": {
            "equivalence_classes": len(runtime_groups),
            "collision_classes": collision_groups,
            "nodes_in_collision_classes": len(collision_nodes),
            "support_in_collision_classes": collision_support,
            "support_fraction_in_collision_classes": collision_support / total_support if total_support else 0.0,
            "action_level_collisions": collision_actions,
            "shadowed_support_sum_by_action": shadowed_support_by_action,
            "distinct_canonical_keys_in_collision_classes": len(canonical_keys_in_collisions),
            "examples": group_examples,
        },
        "runtime_contract": {
            "free_check_in_exact_signature": False,
            "history_uses": ["position", "action"],
            "exact_fields": [
                "actor_position", "table_size", "raise_level", "family",
                "live_positions", "all_in_positions", "history(position,action)",
            ],
        },
        "production_effect": "NONE",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--examples", type=int, default=25)
    args = ap.parse_args()
    result = audit(load_json(args.model), examples_limit=max(0, args.examples))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "model": result["model"],
        "canonical_context_parity": {k: v for k, v in result["canonical_context_parity"].items() if k != "examples"},
        "runtime_equivalence": {k: v for k, v in result["runtime_equivalence"].items() if k != "examples"},
        "production_effect": "NONE",
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
