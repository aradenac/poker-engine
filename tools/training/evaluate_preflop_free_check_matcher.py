#!/usr/bin/env python3
"""Compare current v5 runtime matching with a stricter free_check exact predicate.

Selection is VALIDATION-only. This tool does not touch TEST or production.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.evaluate_preflop_topology_candidate import (  # noqa: E402
    bootstrap,
    by_actor,
    continuous_penalty,
    find_closest,
    history_match_score,
    load_json,
    read_rows,
    same_string_array,
    set_similarity_score,
)

EPS = 1e-12


def runtime_exact_strict(context: dict, decision: dict) -> bool:
    h1, h2 = context.get("history") or [], decision.get("history") or []
    history_exact = len(h1) == len(h2) and all(
        h1[i].get("action") == h2[i].get("action") and h1[i].get("position") == h2[i].get("position")
        for i in range(len(h1))
    )
    return (
        int(context.get("table_size") or 0) == int(decision.get("table_size") or 0)
        and int(context.get("raise_level") or 0) == int(decision.get("raise_level") or 0)
        and context.get("family") == decision.get("family")
        and bool(context.get("free_check")) == bool(decision.get("free_check"))
        and same_string_array(context.get("live_positions"), decision.get("live_positions"))
        and same_string_array(context.get("all_in_positions"), decision.get("all_in_positions"))
        and history_exact
    )


def find_closest_strict(index: dict[str, list[dict]], decision: dict) -> dict | None:
    actor = str(decision.get("actor_position") or "")
    candidates = list(index.get(actor) or [])
    if not candidates:
        return None
    action = str(decision.get("action") or "")
    legal = [n for n in candidates if action in ((n.get("population_model") or {}).get("legal_actions") or [])]
    if legal:
        candidates = legal
    exact = None
    best = None
    best_score = -math.inf
    for node in candidates:
        c = node.get("context") or {}
        if runtime_exact_strict(c, decision):
            n = float((node.get("coverage") or {}).get("population_decisions") or 0)
            if exact is None or n > float((exact.get("coverage") or {}).get("population_decisions") or 0):
                exact = node
            continue
        score = 0.0
        ts, dts = int(c.get("table_size") or 0), int(decision.get("table_size") or 0)
        rl, drl = int(c.get("raise_level") or 0), int(decision.get("raise_level") or 0)
        score += 45 if ts == dts else -18 * abs(ts - dts)
        score += 35 if rl == drl else -22 * abs(rl - drl)
        score += 38 if c.get("family") == decision.get("family") else -10
        score += history_match_score(c.get("history"), decision.get("history"))
        score += set_similarity_score(c.get("live_positions"), decision.get("live_positions"))
        score += 0.45 * set_similarity_score(c.get("all_in_positions"), decision.get("all_in_positions"))
        score -= continuous_penalty(decision, node)
        n = float((node.get("coverage") or {}).get("population_decisions") or 0)
        score += min(8.0, math.log10(n + 1) * 2.2)
        if score > best_score:
            best_score, best = score, node
    node = exact or best
    if node is None:
        return None
    return {"node": node, "exact": exact is not None, "score": 999.0 if exact else best_score}


def action_probability(match: dict | None, action: str) -> float:
    if not match:
        return EPS
    p = float((((match["node"].get("population_model") or {}).get("frequencies") or {}).get(action, 0.0)) or 0.0)
    return max(EPS, min(1.0, p))


def evaluate(model: dict, decisions: Path) -> dict:
    rows, _ = read_rows(decisions, "VALIDATION")
    index = by_actor(list(model.get("nodes") or []))
    scored = []
    changed_examples = []
    current_exact = strict_exact = 0
    changed_node = changed_probability = 0
    changed_free_true = changed_free_false = 0
    nll_current = nll_strict = 0.0
    free_counts = collections.Counter()

    for row in rows:
        current = find_closest(index, row)
        strict = find_closest_strict(index, row)
        if current and current.get("exact"):
            current_exact += 1
        if strict and strict.get("exact"):
            strict_exact += 1
        action = str(row.get("action") or "")
        p0 = action_probability(current, action)
        p1 = action_probability(strict, action)
        d0, d1 = -math.log(p0), -math.log(p1)
        nll_current += d0
        nll_strict += d1
        current_id = str((current or {}).get("node", {}).get("id") or "")
        strict_id = str((strict or {}).get("node", {}).get("id") or "")
        is_changed = current_id != strict_id
        if is_changed:
            changed_node += 1
            if bool(row.get("free_check")):
                changed_free_true += 1
            else:
                changed_free_false += 1
            if len(changed_examples) < 30:
                changed_examples.append({
                    "hand_id": row.get("hand_id"),
                    "actor_position": row.get("actor_position"),
                    "family": row.get("family"),
                    "action": action,
                    "free_check": bool(row.get("free_check")),
                    "current_node": current_id,
                    "strict_node": strict_id,
                    "current_exact": bool(current and current.get("exact")),
                    "strict_exact": bool(strict and strict.get("exact")),
                    "current_probability": p0,
                    "strict_probability": p1,
                    "delta_nll_strict_minus_current": d1 - d0,
                })
        if abs(p0 - p1) > 1e-15:
            changed_probability += 1
        free_counts["true" if row.get("free_check") else "false"] += 1
        scored.append({"hand_id": row.get("hand_id"), "delta_nll": d1 - d0})

    n = len(rows)
    delta = (nll_strict - nll_current) / n if n else 0.0
    paired = bootstrap(scored, samples=5000, seed=20260914)
    # Pre-specified conservative rule: change runtime semantics only when the
    # strict matcher is measurably better on VALIDATION (upper CI < 0).
    promote = changed_probability > 0 and paired["ci95"][1] < 0.0
    return {
        "schema": "poker-preflop-free-check-matcher-validation/v1",
        "split": "VALIDATION",
        "test_used": False,
        "rows": n,
        "free_check_rows": dict(sorted(free_counts.items())),
        "current_exact_rows": current_exact,
        "strict_exact_rows": strict_exact,
        "changed_selected_node_rows": changed_node,
        "changed_probability_rows": changed_probability,
        "changed_rows_by_free_check": {"false": changed_free_false, "true": changed_free_true},
        "current_logloss": nll_current / n if n else 0.0,
        "strict_logloss": nll_strict / n if n else 0.0,
        "delta_strict_minus_current": delta,
        "paired_bootstrap": paired,
        "decision": "PROMOTE_STRICT_FREE_CHECK_MATCHER" if promote else "RETAIN_CURRENT_MATCHER",
        "test_authorized": bool(promote),
        "promotion_effect": "NONE",
        "changed_examples": changed_examples,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True, type=Path)
    ap.add_argument("--decisions", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    result = evaluate(load_json(args.model), args.decisions)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "changed_examples"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
