#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

from tools.simulation.baseline_report import cluster_ratio, initial_spr, paired_policy_comparisons, spr_bucket
from tools.simulation.model_b_runtime import sha256_file

SCHEMA = "sequential-environment-drift-report/v1"


def pmap(doc: dict, policy: str) -> dict[str, dict]:
    return {str(x["scenario_id"]): x for x in doc.get("results", []) if x.get("policy") == policy}


def signature(row: dict) -> tuple:
    return tuple((a.get("street"), a.get("label"), a.get("executed_kind"), round(float(a.get("executed_cost_bb") or 0), 8)) for a in row.get("hero_actions", []))


def validate_identity(a: dict, b: dict) -> None:
    if a.get("schema") != "sequential-independent-arena/v2" or b.get("schema") != a.get("schema"):
        raise ValueError("arena schema mismatch")
    am, bm = a["metadata"], b["metadata"]
    for key in ("scenario_fingerprint_sha256", "scenario_split", "master_seed", "trials", "policies", "engine", "model_a"):
        if am.get(key) != bm.get(key):
            raise ValueError(f"fixed benchmark input changed: {key}")
    af = am["model_b"]["artifact_sha256"]
    bf = bm["model_b"]["artifact_sha256"]
    for name in ("profiles.json", "preflop_ranges.json"):
        if af.get(name) != bf.get(name):
            raise ValueError(f"scenario dependency changed: {name}")
    if af == bf:
        raise ValueError("Model B response environment did not change")


def pairs(a: dict, b: dict, policy: str) -> list[dict]:
    ma, mb = pmap(a, policy), pmap(b, policy)
    if set(ma) != set(mb):
        raise ValueError(f"scenario mismatch for {policy}")
    scenarios = {str(x["scenario_id"]): x for x in a["scenario_manifest"]["scenarios"]}
    out = []
    for sid in sorted(ma):
        x, y = ma[sid], mb[sid]
        s = scenarios[sid]
        hero = s["hero"]
        out.append({
            "hand_id": str(x["hand_id"]),
            "delta": float(y["utility_bb"]) - float(x["utility_bb"]),
            "incumbent": float(x["utility_bb"]),
            "candidate": float(y["utility_bb"]),
            "profile": str(x.get("profile", "unknown")),
            "hero_position": str(s.get("positions", {}).get(hero, "NA")),
            "pot_type": str(s.get("pot_type", "unknown")),
            "spr": spr_bucket(initial_spr(s)),
            "same_terminal": x.get("terminal") == y.get("terminal"),
            "same_actions": signature(x) == signature(y),
            "same_first_action": signature(x)[:1] == signature(y)[:1],
        })
    return out


def summarize(rows: list[dict], seed: int, label: str) -> dict:
    if not rows:
        return {"paired_scenarios": 0}
    stat = cluster_ratio(rows, lambda x: x["delta"], lambda _x: 1.0, seed=seed, label=label)
    n = len(rows)
    return {
        "paired_scenarios": n,
        "paired_base_hands": len({x["hand_id"] for x in rows}),
        "mean_incumbent_utility_bb": sum(x["incumbent"] for x in rows) / n,
        "mean_candidate_utility_bb": sum(x["candidate"] for x in rows) / n,
        "mean_delta_candidate_minus_incumbent_bb": stat["estimate"],
        "delta_ci95_cluster_bootstrap": stat["ci95_cluster_bootstrap"],
        "same_terminal_fraction": sum(x["same_terminal"] for x in rows) / n,
        "same_hero_action_sequence_fraction": sum(x["same_actions"] for x in rows) / n,
        "same_first_hero_action_fraction": sum(x["same_first_action"] for x in rows) / n,
    }


def grouped(rows: list[dict], key: str, seed: int) -> dict:
    buckets: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        buckets[str(row[key])].append(row)
    return {k: summarize(v, seed, f"{key}:{k}") for k, v in sorted(buckets.items())}


def sensitivity(a: dict, b: dict, seed: int) -> dict:
    policies = list(a["metadata"].get("policies", []))
    if policies == ["current"]:
        return {"available": False, "reason": "protected current-only split"}
    acmp, areg = paired_policy_comparisons(a["results"], seed)
    bcmp, breg = paired_policy_comparisons(b["results"], seed)
    out = {"available": True, "incumbent": acmp, "candidate": bcmp, "incumbent_regret": areg, "candidate_regret": breg, "difference_in_difference": {}}
    for policy in policies:
        if policy == "current":
            continue
        ai, ap = pmap(a, "current"), pmap(a, policy)
        bi, bp = pmap(b, "current"), pmap(b, policy)
        rows = []
        for sid in sorted(set(ai) & set(ap) & set(bi) & set(bp)):
            rows.append({"hand_id": str(ai[sid]["hand_id"]), "delta": (float(bp[sid]["utility_bb"]) - float(bi[sid]["utility_bb"])) - (float(ap[sid]["utility_bb"]) - float(ai[sid]["utility_bb"]))})
        stat = cluster_ratio(rows, lambda x: x["delta"], lambda _x: 1.0, seed=seed, label=f"did:{policy}")
        out["difference_in_difference"][policy] = {"estimate_bb": stat["estimate"], "ci95_cluster_bootstrap": stat["ci95_cluster_bootstrap"], "paired_scenarios": len(rows)}
    return out


def build(a: dict, b: dict, seed: int) -> dict:
    validate_identity(a, b)
    rows = pairs(a, b, "current")
    return {
        "schema": SCHEMA,
        "provenance": {
            "scenario_fingerprint_sha256": a["metadata"]["scenario_fingerprint_sha256"],
            "scenario_split": a["metadata"]["scenario_split"],
            "master_seed": a["metadata"]["master_seed"],
            "trials": a["metadata"]["trials"],
            "engine": a["metadata"]["engine"],
            "model_a": a["metadata"]["model_a"],
            "incumbent_model_b": a["metadata"]["model_b"],
            "candidate_model_b": b["metadata"]["model_b"],
            "scenario_materialization": b["scenario_manifest"].get("scenario_materialization_provenance"),
            "strategy_changed": False,
            "model_a_changed": False,
            "production_effect": "NONE",
        },
        "current_policy": {
            "overall": summarize(rows, seed, "overall"),
            "by_profile": grouped(rows, "profile", seed),
            "by_hero_position": grouped(rows, "hero_position", seed),
            "by_initial_spr": grouped(rows, "spr", seed),
            "by_pot_type": grouped(rows, "pot_type", seed),
        },
        "policy_sensitivity": sensitivity(a, b, seed),
        "scope": {
            "supported": ["heads_up_postflop"],
            "not_supported": ["multiway", "preflop", "overall_cash_game_win_rate"],
            "candidate_response_dimension": "facing_price_to_pot",
            "strategy_promotion_authorized": False,
        },
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--incumbent-arena", required=True)
    p.add_argument("--candidate-arena", required=True)
    p.add_argument("--seed", type=int, default=20260913)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    ia, ca = Path(args.incumbent_arena), Path(args.candidate_arena)
    a = json.loads(ia.read_text(encoding="utf-8"))
    b = json.loads(ca.read_text(encoding="utf-8"))
    report = build(a, b, args.seed)
    report["provenance"]["input_sha256"] = {"incumbent_arena": sha256_file(ia), "candidate_arena": sha256_file(ca)}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report["current_policy"]["overall"], indent=2))


if __name__ == "__main__":
    main()
