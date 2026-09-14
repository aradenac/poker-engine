#!/usr/bin/env python3
"""Explain the systematic v5 canonical-history mismatch and runtime collisions."""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.audit_preflop_key_runtime_parity import (  # noqa: E402
    canonical_diff_fields,
    canonical_parts,
    load_json,
    runtime_signature,
    support,
)


def history_pairs_from_key(value: str | None) -> tuple[tuple[str, str], ...]:
    if not value:
        return ()
    # Legacy v5 serializes multiple history actions with commas. Current
    # repo-native canonical keys use '>'. Both are representation delimiters;
    # action/position tokens themselves are unchanged.
    normalized = str(value).replace(",", ">")
    out = []
    for token in normalized.split(">"):
        if not token:
            continue
        pos, sep, action = token.partition(":")
        out.append((pos, action if sep else ""))
    return tuple(out)


def history_pairs_from_context(context: dict) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(x.get("position") or ""), str(x.get("action") or ""))
        for x in (context.get("history") or [])
    )


def legal_actions(node: dict) -> set[str]:
    return {str(x) for x in ((node.get("population_model") or {}).get("legal_actions") or [])}


def collision_cause(group: list[dict]) -> str:
    contexts = [n.get("context") or {} for n in group]
    fields = (
        "table_size", "actor_position", "family", "raise_level", "free_check",
        "live_positions", "all_in_positions", "history",
    )
    varying = []
    for field in fields:
        vals = [json.dumps(c.get(field), sort_keys=True, separators=(",", ":")) for c in contexts]
        if len(set(vals)) > 1:
            varying.append(field)
    return ",".join(varying) or "IDENTICAL_CONTEXT"


def explain(model: dict) -> dict:
    nodes = list(model.get("nodes") or [])
    key_mismatch_nodes = 0
    key_mismatch_support = 0
    hist_explanations: collections.Counter[str] = collections.Counter()
    unexplained_examples = []

    groups: dict[tuple, list[dict]] = collections.defaultdict(list)
    for node in nodes:
        context = node.get("context") or {}
        groups[runtime_signature(context)].append(node)
        diffs = canonical_diff_fields(node.get("canonical_key"), context)
        if not diffs:
            continue
        key_mismatch_nodes += 1
        key_mismatch_support += support(node)
        if diffs != ["hist"]:
            explanation = "NON_HISTORY_FIELDS"
        else:
            stored = canonical_parts(node.get("canonical_key")).get("hist")
            a = history_pairs_from_key(stored)
            b = history_pairs_from_context(context)
            if a == b and stored != ">".join(f"{p}:{a_}" for p, a_ in b):
                explanation = "LEGACY_COMMA_DELIMITER_ONLY"
            elif a == b:
                explanation = "TOKEN_EQUIVALENT_OTHER_FORMAT"
            else:
                explanation = "UNEXPLAINED_HISTORY_CONTENT"
        hist_explanations[explanation] += 1
        if explanation.startswith("UNEXPLAINED") or explanation == "NON_HISTORY_FIELDS":
            if len(unexplained_examples) < 20:
                unexplained_examples.append({
                    "id": node.get("id"),
                    "canonical_key": node.get("canonical_key"),
                    "context_history": context.get("history") or [],
                    "diff_fields": diffs,
                    "explanation": explanation,
                })

    collision_causes: collections.Counter[str] = collections.Counter()
    action_collision_causes: collections.Counter[str] = collections.Counter()
    collision_classes = 0
    collision_nodes = 0
    collision_support = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        overlapping_actions = [
            action for action in sorted(set().union(*(legal_actions(n) for n in group)))
            if sum(action in legal_actions(n) for n in group) >= 2
        ]
        if not overlapping_actions:
            continue
        collision_classes += 1
        collision_nodes += len(group)
        collision_support += sum(support(n) for n in group)
        cause = collision_cause(group)
        collision_causes[cause] += 1
        action_collision_causes[cause] += len(overlapping_actions)

    total_support = sum(support(n) for n in nodes)
    all_hist_explained = hist_explanations.get("UNEXPLAINED_HISTORY_CONTENT", 0) == 0 and hist_explanations.get("NON_HISTORY_FIELDS", 0) == 0
    all_collisions_free_check_only = collision_classes > 0 and collision_causes == {"free_check": collision_classes}
    return {
        "schema": "poker-preflop-key-runtime-explanation/v1",
        "model_version": model.get("version") or model.get("model_version"),
        "nodes": len(nodes),
        "population_decision_support": total_support,
        "canonical_key_mismatch": {
            "nodes": key_mismatch_nodes,
            "support": key_mismatch_support,
            "explanation_distribution": dict(sorted(hist_explanations.items())),
            "all_mismatches_explained": all_hist_explained,
            "unexplained_examples": unexplained_examples,
        },
        "runtime_collisions": {
            "classes": collision_classes,
            "nodes": collision_nodes,
            "support": collision_support,
            "class_cause_distribution": dict(sorted(collision_causes.items())),
            "action_collision_cause_distribution": dict(sorted(action_collision_causes.items())),
            "all_collisions_free_check_only": all_collisions_free_check_only,
        },
        "interpretation": {
            "canonical_history": "Legacy v5 uses ',' between history action tokens; current repo-native canonical keys use '>'. The parsed action/position sequences are otherwise identical when all mismatches are explained.",
            "runtime_collision": "Production exact matching omits free_check. Runtime-equivalent duplicate classes therefore collapse free_check=false/true nodes and select the highest-support node for overlapping legal actions.",
        },
        "production_effect": "NONE",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    result = explain(load_json(args.model))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["canonical_key_mismatch"]["all_mismatches_explained"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
