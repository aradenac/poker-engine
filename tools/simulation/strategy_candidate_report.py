#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.simulation.baseline_report import cluster_ratio
from tools.simulation.model_b_runtime import sha256_file

SCHEMA = "paired-strategy-candidate-report/v1"


def pmap(doc: dict) -> dict[str, dict]:
    return {str(x["scenario_id"]): x for x in doc.get("results", []) if x.get("policy") == "current"}


def signature(row: dict) -> tuple:
    return tuple((a.get("street"), a.get("label"), a.get("executed_kind"), round(float(a.get("executed_cost_bb") or 0), 8)) for a in row.get("hero_actions", []))


def validate_identity(base: dict, cand: dict) -> None:
    if base.get("schema") != "sequential-independent-arena/v2" or cand.get("schema") != base.get("schema"):
        raise ValueError("arena schema mismatch")
    bm, cm = base["metadata"], cand["metadata"]
    for key in ("scenario_fingerprint_sha256", "scenario_split", "master_seed", "trials", "policies", "model_a", "model_b"):
        if bm.get(key) != cm.get(key):
            raise ValueError(f"strategy comparison changed fixed input: {key}")
    if bm.get("engine") == cm.get("engine"):
        raise ValueError("candidate engine is byte-identical to baseline")


def build(base: dict, cand: dict, contract: dict, phase: str, seed: int) -> dict:
    validate_identity(base, cand)
    b, c = pmap(base), pmap(cand)
    if set(b) != set(c):
        raise ValueError("scenario result mismatch")
    rows = []
    for sid in sorted(b):
        x, y = b[sid], c[sid]
        if str(x["hand_id"]) != str(y["hand_id"]):
            raise ValueError(f"hand mismatch for {sid}")
        rows.append({
            "hand_id": str(x["hand_id"]),
            "delta": float(y["utility_bb"]) - float(x["utility_bb"]),
            "baseline": float(x["utility_bb"]),
            "candidate": float(y["utility_bb"]),
            "same_terminal": x.get("terminal") == y.get("terminal"),
            "same_actions": signature(x) == signature(y),
        })
    stat = cluster_ratio(rows, lambda x: x["delta"], lambda _x: 1.0, seed=seed, label=f"strategy:{phase}")
    lower = float(stat["ci95_cluster_bootstrap"][0])
    strategy = contract["strategy"]
    threshold = float(strategy["promotion_requires_validation_ci95_lower_at_least"] if phase == "VALIDATION" else strategy["promotion_requires_test_ci95_lower_at_least"])
    passed = lower >= threshold
    decision = ("ADVANCE_TO_TEST" if passed else "RETAIN_V83") if phase == "VALIDATION" else ("PROMOTE_V84" if passed else "RETAIN_V83")
    return {
        "schema": SCHEMA,
        "phase": phase,
        "metric": strategy["metric"],
        "interpretation": strategy["interpretation"],
        "paired_scenarios": len(rows),
        "paired_base_hands": len({x["hand_id"] for x in rows}),
        "mean_baseline_utility_bb": sum(x["baseline"] for x in rows) / len(rows),
        "mean_candidate_utility_bb": sum(x["candidate"] for x in rows) / len(rows),
        "mean_delta_candidate_minus_v83_bb": stat["estimate"],
        "delta_ci95_cluster_bootstrap": stat["ci95_cluster_bootstrap"],
        "required_ci95_lower_at_least": threshold,
        "gate_pass": passed,
        "decision": decision,
        "same_terminal_fraction": sum(x["same_terminal"] for x in rows) / len(rows),
        "same_action_sequence_fraction": sum(x["same_actions"] for x in rows) / len(rows),
        "selection_split": phase,
        "test_used_for_selection": False if phase == "VALIDATION" else None,
        "provenance": {
            "scenario_fingerprint_sha256": base["metadata"]["scenario_fingerprint_sha256"],
            "master_seed": base["metadata"]["master_seed"],
            "trials": base["metadata"]["trials"],
            "model_a": base["metadata"]["model_a"],
            "model_b": base["metadata"]["model_b"],
            "baseline_engine": base["metadata"]["engine"],
            "candidate_engine": cand["metadata"]["engine"],
        },
        "scope": {
            "candidate_change": "postflop sizing candidate grid only",
            "supported": ["heads_up_postflop"],
            "preflop_changed": False,
            "multiway_promotion_supported": False,
        },
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--baseline-arena", required=True)
    p.add_argument("--candidate-arena", required=True)
    p.add_argument("--contract", default="training/PROMOTION_GATE_CONTRACT.json")
    p.add_argument("--phase", choices=("VALIDATION", "TEST"), required=True)
    p.add_argument("--seed", type=int, default=20260913)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    bp, cp, gp = Path(args.baseline_arena), Path(args.candidate_arena), Path(args.contract)
    report = build(json.loads(bp.read_text()), json.loads(cp.read_text()), json.loads(gp.read_text()), args.phase, args.seed)
    report["input_sha256"] = {"baseline_arena": sha256_file(bp), "candidate_arena": sha256_file(cp), "gate_contract": sha256_file(gp)}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: report[k] for k in ("phase", "mean_delta_candidate_minus_v83_bb", "delta_ci95_cluster_bootstrap", "decision")}, indent=2))


if __name__ == "__main__":
    main()
