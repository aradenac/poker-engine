#!/usr/bin/env python3
"""Evaluate a targeted preflop topology extension without leaking TEST.

The candidate is defined *only* from TRAIN contexts that are absent from the
promoted v5 canonical-key topology and have pre-specified support >= 20.  The
browser v83/v5 nearest-node matcher is reproduced here so adding a node is
scored with the same exact/fallback behavior the application uses.

VALIDATION may select only the smoothing alpha. TEST can be run only from a
VALIDATION report that explicitly authorizes it. This tool never changes a
production model or registry pointer.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any

SCHEMA = "poker-preflop-topology-candidate/v1"
ACTIONS = ("FOLD", "CHECK", "LIMP", "CALL", "RAISE", "JAM")
DEFAULT_ALPHAS = (0.0, 10.0, 20.0, 40.0, 80.0, 160.0, 320.0)
EPS = 1e-12


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return data


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_key(row: dict[str, Any]) -> str:
    if row.get("v4_canonical_key"):
        return str(row["v4_canonical_key"])
    hist = ">".join(f"{x['position']}:{x['action']}" for x in (row.get("history") or []))
    return (
        f"{row['table_size']}|{row['actor_position']}|family={row['family']}|"
        f"rl={row['raise_level']}|free={1 if row.get('free_check') else 0}|"
        f"live={','.join(row.get('live_positions') or [])}|"
        f"allin={','.join(row.get('all_in_positions') or [])}|hist={hist}"
    )


def node_key(node: dict[str, Any]) -> str:
    return str(node.get("canonical_key") or node.get("id") or "")


def by_actor(nodes: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for node in nodes:
        actor = str((node.get("context") or {}).get("actor_position") or "")
        if actor:
            out[actor].append(node)
    return dict(out)


def same_string_array(a: list[Any] | None, b: list[Any] | None) -> bool:
    x, y = a or [], b or []
    return len(x) == len(y) and all(v == y[i] for i, v in enumerate(x))


def history_match_score(a: list[dict[str, Any]] | None, b: list[dict[str, Any]] | None) -> float:
    x, y = a or [], b or []
    if not x and not y:
        return 70.0
    score = 0.0
    for i in range(min(len(x), len(y))):
        score += 13 if x[i].get("action") == y[i].get("action") else -15
        score += 8 if x[i].get("position") == y[i].get("position") else -5
    score -= abs(len(x) - len(y)) * 18
    if len(x) == len(y) and all(
        x[i].get("action") == y[i].get("action") and x[i].get("position") == y[i].get("position")
        for i in range(len(x))
    ):
        score += 75
    return score


def set_similarity_score(a: list[Any] | None, b: list[Any] | None) -> float:
    aa, bb = set(a or []), set(b or [])
    union = aa | bb
    if not union:
        return 20.0
    inter = len(aa & bb)
    j = inter / len(union)
    return 25 * j - 7 * (len(union) - inter)


def continuous_penalty(decision: dict[str, Any], node: dict[str, Any]) -> float:
    stats = node.get("continuous_population") or {}
    penalty = 0.0
    for field, weight in (("pot_before_bb", 1.2), ("actor_start_stack_bb", 0.35), ("action_add_bb", 0.45)):
        actual = decision.get(field)
        median = (stats.get(field) or {}).get("median")
        if isinstance(actual, (int, float)) and actual > 0 and isinstance(median, (int, float)) and median > 0:
            penalty += min(14.0, abs(math.log(actual / median)) * weight * 5)
    return penalty


def runtime_exact(context: dict[str, Any], decision: dict[str, Any]) -> bool:
    h1, h2 = context.get("history") or [], decision.get("history") or []
    history_exact = len(h1) == len(h2) and all(
        h1[i].get("action") == h2[i].get("action") and h1[i].get("position") == h2[i].get("position")
        for i in range(len(h1))
    )
    # Intentionally mirrors site/index.html: free_check is not part of the
    # runtime exactStruct predicate, even though it is part of canonical_key.
    return (
        int(context.get("table_size") or 0) == int(decision.get("table_size") or 0)
        and int(context.get("raise_level") or 0) == int(decision.get("raise_level") or 0)
        and context.get("family") == decision.get("family")
        and same_string_array(context.get("live_positions"), decision.get("live_positions"))
        and same_string_array(context.get("all_in_positions"), decision.get("all_in_positions"))
        and history_exact
    )


def find_closest(index: dict[str, list[dict[str, Any]]], decision: dict[str, Any]) -> dict[str, Any] | None:
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
        if runtime_exact(c, decision):
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


def prediction(index: dict[str, list[dict[str, Any]]], row: dict[str, Any]) -> tuple[float, str | None, bool]:
    match = find_closest(index, row)
    if not match:
        return EPS, None, False
    node = match["node"]
    p = float(((node.get("population_model") or {}).get("frequencies") or {}).get(row.get("action"), 0.0) or 0.0)
    return max(EPS, min(1.0, p)), str(node.get("id") or node_key(node)), bool(match["exact"])


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo] * (hi - pos) + xs[hi] * (pos - lo)


def bootstrap(rows: list[dict[str, Any]], *, samples: int, seed: int) -> dict[str, Any]:
    grouped: dict[str, list[float]] = collections.defaultdict(list)
    for r in rows:
        grouped[str(r["hand_id"])].append(float(r["delta_nll"]))
    hands = sorted(grouped)
    if not hands:
        return {"hands": 0, "samples": samples, "mean": 0.0, "ci95": [0.0, 0.0], "probability_candidate_better": 0.0}
    rng = random.Random(seed)
    vals = []
    for _ in range(samples):
        total = 0.0
        count = 0
        for _j in hands:
            hid = hands[rng.randrange(len(hands))]
            ds = grouped[hid]
            total += sum(ds)
            count += len(ds)
        vals.append(total / max(1, count))
    mean = sum(float(r["delta_nll"]) for r in rows) / len(rows)
    return {
        "hands": len(hands),
        "samples": samples,
        "seed": seed,
        "mean": mean,
        "ci95": [percentile(vals, 0.025), percentile(vals, 0.975)],
        "probability_candidate_better": sum(v < 0 for v in vals) / len(vals),
    }


def read_rows(decisions: Path, split: str) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    scored = []
    train_by_key: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    with decisions.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row.get("street") != "preflop" or row.get("is_hero"):
                continue
            if row.get("split") == "TRAIN":
                train_by_key[canonical_key(row)].append(row)
            elif row.get("split") == split:
                scored.append(row)
    return scored, train_by_key


def median_stat(rows: list[dict[str, Any]], field: str) -> float | None:
    xs = [float(r[field]) for r in rows if isinstance(r.get(field), (int, float)) and math.isfinite(float(r[field]))]
    return statistics.median(xs) if xs else None


def theoretical_actions(context: dict[str, Any], observed: set[str]) -> list[str]:
    if context.get("free_check"):
        base = {"CHECK", "RAISE", "JAM"}
    elif int(context.get("raise_level") or 0) == 0:
        base = {"FOLD", "LIMP", "RAISE", "JAM"}
    else:
        base = {"FOLD", "CALL", "RAISE", "JAM"}
    return [a for a in ACTIONS if a in (base | observed)]


def representative(context: dict[str, Any], rows: list[dict[str, Any]], action: str) -> dict[str, Any]:
    out = dict(context)
    out["action"] = action
    for field in ("pot_before_bb", "actor_start_stack_bb", "action_add_bb"):
        out[field] = median_stat(rows, field)
    return out


def build_target_specs(
    baseline: dict[str, Any], overlay: dict[str, Any], train_by_key: dict[str, list[dict[str, Any]]], min_support: int
) -> list[dict[str, Any]]:
    base_nodes = list(baseline.get("nodes") or [])
    base_keys = {node_key(n) for n in base_nodes}
    base_index = by_actor(base_nodes)
    specs = []
    for src in overlay.get("preflop_nodes") or []:
        key = node_key(src)
        n = int(src.get("n_delta") or 0)
        if n < min_support or key in base_keys:
            continue
        rows = train_by_key.get(key) or []
        if len(rows) != n:
            raise SystemExit(f"TRAIN row/support mismatch for {key}: {len(rows)} != {n}")
        observed = {str(a) for a, count in (src.get("actions") or {}).items() if int(count or 0) > 0}
        actions = theoretical_actions(src.get("context") or {}, observed)
        prior_raw = {}
        runtime_exact_actions = []
        fallback_nodes = {}
        for action in actions:
            d = representative(src.get("context") or {}, rows, action)
            match = find_closest(base_index, d)
            p = EPS
            if match:
                pm = match["node"].get("population_model") or {}
                p = max(EPS, float((pm.get("frequencies") or {}).get(action, 0.0) or 0.0))
                fallback_nodes[action] = str(match["node"].get("id") or node_key(match["node"]))
                if match["exact"]:
                    runtime_exact_actions.append(action)
            prior_raw[action] = p
        z = sum(prior_raw.values()) or 1.0
        prior = {a: prior_raw[a] / z for a in actions}
        cont = {}
        for field in ("pot_before_bb", "actor_start_stack_bb", "action_add_bb"):
            med = median_stat(rows, field)
            if med is not None:
                cont[field] = {"median": med}
        specs.append({
            "key": key,
            "id": "PF61_" + hashlib.sha1(key.encode()).hexdigest()[:12],
            "context": src.get("context") or {},
            "support": n,
            "counts": {a: int((src.get("actions") or {}).get(a, 0) or 0) for a in actions},
            "actions": actions,
            "prior": prior,
            "continuous_population": cont,
            "fallback_nodes": fallback_nodes,
            "baseline_runtime_exact_actions": runtime_exact_actions,
        })
    specs.sort(key=lambda x: (-x["support"], x["key"]))
    return specs


def candidate_nodes(specs: list[dict[str, Any]], alpha: float) -> list[dict[str, Any]]:
    nodes = []
    for s in specs:
        denom = s["support"] + alpha
        raw = {
            a: (s["counts"].get(a, 0) + alpha * s["prior"].get(a, 0.0)) / max(EPS, denom)
            for a in s["actions"]
        }
        z = sum(raw.values()) or 1.0
        freqs = {a: raw[a] / z for a in s["actions"]}
        nodes.append({
            "id": s["id"],
            "canonical_key": s["key"],
            "context": s["context"],
            "continuous_population": s["continuous_population"],
            "coverage": {"population_decisions": s["support"]},
            "population_model": {
                "legal_actions": s["actions"],
                "frequencies": freqs,
                "method": f"targeted_train_context_alpha_{alpha:g}",
                "source": "20260912 TRAIN unseen exact contexts only",
            },
        })
    return nodes


def score(rows: list[dict[str, Any]], baseline_nodes: list[dict[str, Any]], added: list[dict[str, Any]], target_keys: set[str]) -> dict[str, Any]:
    bi = by_actor(baseline_nodes)
    ci = by_actor(baseline_nodes + added)
    detail = []
    base_nll = cand_nll = 0.0
    target_base = target_cand = 0.0
    target_count = affected = new_exact = 0
    for row in rows:
        bp, bid, _ = prediction(bi, row)
        cp, cid, cexact = prediction(ci, row)
        bn, cn = -math.log(bp), -math.log(cp)
        base_nll += bn; cand_nll += cn
        key = canonical_key(row)
        target = key in target_keys
        if target:
            target_count += 1; target_base += bn; target_cand += cn
        changed = abs(bp - cp) > 1e-15 or bid != cid
        if changed:
            affected += 1
        if cid and cid.startswith("PF61_") and cexact:
            new_exact += 1
        detail.append({"hand_id": str(row["hand_id"]), "delta_nll": cn - bn, "target": target, "changed": changed})
    n = len(rows)
    return {
        "rows": n,
        "baseline_logloss": base_nll / max(1, n),
        "candidate_logloss": cand_nll / max(1, n),
        "delta_candidate_minus_baseline": (cand_nll - base_nll) / max(1, n),
        "target_rows": target_count,
        "target_baseline_logloss": target_base / max(1, target_count),
        "target_candidate_logloss": target_cand / max(1, target_count),
        "target_delta_candidate_minus_baseline": (target_cand - target_base) / max(1, target_count),
        "affected_rows": affected,
        "new_exact_rows": new_exact,
        "detail": detail,
    }


def semantic_sha(nodes: list[dict[str, Any]]) -> str:
    payload = json.dumps(nodes, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def evaluate_validation(args: argparse.Namespace) -> dict[str, Any]:
    baseline = load_json(args.baseline)
    overlay = load_json(args.overlay)
    rows, train_by_key = read_rows(args.decisions, "VALIDATION")
    specs = build_target_specs(baseline, overlay, train_by_key, args.min_support)
    if len(specs) != args.expected_target_nodes:
        raise SystemExit(f"target node count changed: {len(specs)} != {args.expected_target_nodes}")
    target_keys = {s["key"] for s in specs}
    base_nodes = list(baseline.get("nodes") or [])
    grid = []
    scored_by_alpha = {}
    for alpha in args.alphas:
        added = candidate_nodes(specs, alpha)
        s = score(rows, base_nodes, added, target_keys)
        scored_by_alpha[alpha] = s
        grid.append({k: v for k, v in s.items() if k != "detail"} | {"alpha": alpha, "candidate_nodes_sha256": semantic_sha(added)})
    best = min(grid, key=lambda x: (x["candidate_logloss"], x["alpha"]))
    best_score = scored_by_alpha[best["alpha"]]
    boot = bootstrap(best_score["detail"], samples=args.bootstrap_samples, seed=args.seed)
    ci_hi = float(boot["ci95"][1])
    authorized = best["delta_candidate_minus_baseline"] < 0 and ci_hi < 0 and best["affected_rows"] > 0
    result = {
        "schema": SCHEMA,
        "phase": "VALIDATION",
        "cycle": "2026-09-12-preflop-topology-followup",
        "selection_split": "VALIDATION",
        "test_used": False,
        "production_effect": "NONE",
        "inputs": {
            "baseline": {"path": str(args.baseline), "sha256": sha256_file(args.baseline)},
            "decisions": {"path": str(args.decisions), "sha256": sha256_file(args.decisions)},
            "overlay": {"path": str(args.overlay), "sha256": sha256_file(args.overlay)},
        },
        "candidate_contract": {
            "minimum_train_support": args.min_support,
            "target_nodes": len(specs),
            "target_train_rows": sum(s["support"] for s in specs),
            "alpha_grid": args.alphas,
            "runtime_matcher": "site/index.html v83 findClosestPopulationNode parity; free_check intentionally excluded from runtime exactStruct",
            "materialization": "TRAIN-only unseen canonical contexts; marginal frequencies smoothed toward v5 runtime fallback",
        },
        "runtime_overlap": {
            "target_nodes_with_any_baseline_runtime_exact_action": sum(bool(s["baseline_runtime_exact_actions"]) for s in specs),
            "examples": [
                {"key": s["key"], "support": s["support"], "actions": s["baseline_runtime_exact_actions"]}
                for s in specs if s["baseline_runtime_exact_actions"]
            ][:10],
        },
        "validation": {
            "population_preflop_rows": len(rows),
            "grid": grid,
            "selected_alpha": best["alpha"],
            "selected_candidate_nodes_sha256": best["candidate_nodes_sha256"],
            "paired_bootstrap": boot,
        },
        "outcome": "VALIDATION_FINALIST" if authorized else "RETAIN_BASELINE",
        "test_authorized": authorized,
        "reason": (
            "candidate improves full VALIDATION preflop logloss with paired-hand CI95 strictly below zero"
            if authorized else
            "targeted topology does not establish a statistically reliable full-VALIDATION improvement; protected TEST remains locked"
        ),
        "target_contexts": [
            {"key": s["key"], "support": s["support"], "actions": s["counts"], "fallback_nodes": s["fallback_nodes"]}
            for s in specs
        ],
    }
    return result


def evaluate_test(args: argparse.Namespace) -> dict[str, Any]:
    if not args.validation_selection:
        raise SystemExit("TEST requires --validation-selection")
    selection = load_json(args.validation_selection)
    if selection.get("phase") != "VALIDATION" or selection.get("test_authorized") is not True:
        raise SystemExit("protected TEST is not authorized by VALIDATION selection")
    alpha = float(selection["validation"]["selected_alpha"])
    baseline = load_json(args.baseline)
    overlay = load_json(args.overlay)
    rows, train_by_key = read_rows(args.decisions, "TEST")
    specs = build_target_specs(baseline, overlay, train_by_key, args.min_support)
    target_keys = {s["key"] for s in specs}
    added = candidate_nodes(specs, alpha)
    s = score(rows, list(baseline.get("nodes") or []), added, target_keys)
    boot = bootstrap(s["detail"], samples=args.bootstrap_samples, seed=args.seed + 1)
    confirmed = s["delta_candidate_minus_baseline"] <= 0 and float(boot["ci95"][1]) <= 0
    return {
        "schema": SCHEMA,
        "phase": "TEST",
        "cycle": selection.get("cycle"),
        "selection_split": "VALIDATION",
        "test_used": True,
        "test_used_for_selection": False,
        "production_effect": "NONE",
        "selected_alpha": alpha,
        "candidate_nodes_sha256": semantic_sha(added),
        "test": {k: v for k, v in s.items() if k != "detail"} | {"paired_bootstrap": boot},
        "outcome": "FINALIST_CONFIRMED" if confirmed else "RETAIN_BASELINE",
        "promotion_allowed": confirmed,
        "reason": "locked TEST confirms non-regression" if confirmed else "locked TEST does not confirm the VALIDATION finalist",
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", choices=("validation", "test"), default="validation")
    p.add_argument("--baseline", required=True, type=Path)
    p.add_argument("--decisions", required=True, type=Path)
    p.add_argument("--overlay", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--validation-selection", type=Path)
    p.add_argument("--min-support", type=int, default=20)
    p.add_argument("--expected-target-nodes", type=int, default=51)
    p.add_argument("--alphas", type=float, nargs="+", default=list(DEFAULT_ALPHAS))
    p.add_argument("--bootstrap-samples", type=int, default=5000)
    p.add_argument("--seed", type=int, default=20260914)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.min_support != 20:
        raise SystemExit("#61 contract freezes minimum TRAIN support at 20; do not tune the threshold on VALIDATION")
    result = evaluate_validation(args) if args.phase == "validation" else evaluate_test(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    compact = {
        "phase": result["phase"],
        "outcome": result["outcome"],
        "test_authorized": result.get("test_authorized"),
        "validation": result.get("validation"),
        "test": result.get("test"),
    }
    print(json.dumps(compact, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
