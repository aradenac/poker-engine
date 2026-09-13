#!/usr/bin/env python3
"""Build TRAIN-only additive sufficient statistics for Model A calibration."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import sha256_file  # noqa: E402


def pre_v4_key(r):
    hist = ">".join(f"{x['position']}:{x['action']}" for x in (r.get("history") or []))
    free = 1 if r.get("free_check") else 0
    return f"{r['table_size']}|{r['actor_position']}|family={r['family']}|rl={r['raise_level']}|free={free}|live={','.join(r.get('live_positions') or [])}|allin={','.join(r.get('all_in_positions') or [])}|hist={hist}"


def pre_v4_id(key):
    return "PF4_" + hashlib.sha1(key.encode()).hexdigest()[:12]


def node_context_pre(r):
    return {
        "table_size": r["table_size"], "actor_position": r["actor_position"], "family": r["family"],
        "raise_level": r["raise_level"], "live_positions": r.get("live_positions") or [],
        "all_in_positions": r.get("all_in_positions") or [], "history": r.get("history") or [],
        "free_check": bool(r.get("free_check")),
    }


def add_num(acc, key, value):
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
        return
    s = acc.setdefault(key, {"n": 0, "sum": 0.0, "sum_sq": 0.0, "min": value, "max": value})
    s["n"] += 1; s["sum"] += value; s["sum_sq"] += value * value; s["min"] = min(s["min"], value); s["max"] = max(s["max"], value)


def finalize_num(d):
    for value in d.values():
        n = value["n"]; value["mean"] = value["sum"] / n if n else None
        var = max(0.0, value["sum_sq"] / n - value["mean"] ** 2) if n else None
        value["std"] = math.sqrt(var) if var is not None else None


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def build(decisions: Path, out: Path, provenance_out: Path | None = None):
    pre = collections.OrderedDict(); post = collections.OrderedDict()
    summary = {"rows": 0, "population_rows": 0, "train_population_rows": 0, "known_train_population_rows": 0}
    by_split = collections.Counter()
    with decisions.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line); summary["rows"] += 1; by_split[r["split"]] += 1
            if r.get("is_hero"): continue
            summary["population_rows"] += 1
            if r["split"] != "TRAIN": continue
            summary["train_population_rows"] += 1
            if r.get("known_hand_class"): summary["known_train_population_rows"] += 1
            if r["street"] == "preflop":
                key = pre_v4_key(r); nid = pre_v4_id(key)
                n = pre.setdefault(key, {"id": nid, "canonical_key": key, "context": node_context_pre(r), "n_delta": 0, "actions": collections.Counter(), "known_by_action": {}, "continuous": {}})
                n["n_delta"] += 1; n["actions"][r["action"]] += 1
                hc = r.get("known_hand_class")
                if hc: n["known_by_action"].setdefault(r["action"], collections.Counter())[hc] += 1
                add_num(n["continuous"], "pot_before_bb", r.get("pot_before_bb")); add_num(n["continuous"], "to_call_bb", r.get("to_call_bb")); add_num(n["continuous"], "current_price_bb", r.get("current_price_bb")); add_num(n["continuous"], "action_add_bb", r.get("action_add_bb")); add_num(n["continuous"], "actor_start_stack_bb", r.get("actor_start_stack_bb")); add_num(n["continuous"], "actor_remaining_bb_before", r.get("actor_remaining_bb_before"))
            else:
                key = r["canonical_key"]
                n = post.setdefault(key, {"id": "PFLOP_" + hashlib.sha1(key.encode()).hexdigest()[:12], "canonical_key": key, "context": {k: r.get(k) for k in ["street", "street_start_players", "active_players", "relative_position", "pot_type", "preflop_role", "street_history", "mode"]}, "n_delta": 0, "actions": collections.Counter(), "known_by_action": {}, "continuous": {}})
                n["n_delta"] += 1; n["actions"][r["action"]] += 1
                hc = r.get("known_hand_class")
                if hc: n["known_by_action"].setdefault(r["action"], collections.Counter())[hc] += 1
                for k in ["pot_before_bb", "spr", "facing_price_pot", "own_size_pot"]: add_num(n["continuous"], k, r.get(k))
    for coll in (pre, post):
        for n in coll.values():
            n["actions"] = dict(n["actions"]); n["known_by_action"] = {a: dict(c) for a, c in n["known_by_action"].items()}; finalize_num(n["continuous"])
    obj = {
        "schema": "poker-population-increment-overlay/v1",
        "purpose": "Additive sufficient statistics for population-model calibration. Contains TRAIN only; VALIDATION/TEST remain in the decision JSONL for model selection/non-regression.",
        "base_contract": {"preflop_model": "preflop_population_model_v4.json", "postflop_model": "postflop_population_model_v5.json", "historical_corpus_fingerprint_sha256": "91a1b1c285add6ace2aedafa568bfc039c644b94216b9d2fdcd28cea59b73d4b", "split_namespace": "poker-population-split-v1"},
        "source": decisions.name,
        "summary": {**summary, "row_counts_by_split": dict(by_split), "preflop_nodes_train": len(pre), "postflop_nodes_train": len(post)},
        "preflop_nodes": list(pre.values()), "postflop_nodes": list(post.values()),
        "merge_rules": {
            "marginal_counts": "Add delta action counts to historical TRAIN sufficient statistics; never add VALIDATION or TEST counts.",
            "known_hand_composition": "Treat delta revealed-card counts as additional TRAIN evidence only for observable actions. Do not infer FOLD composition from missing showdown cards.",
            "continuous": "Sufficient moments are diagnostic only; raw TRAIN rows in the JSONL are retained for any future refit of continuous response models.",
            "validation": "Select any changed hyperparameter/scale only on VALIDATION. TEST remains metrics-only.",
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if provenance_out:
        provenance_out.parent.mkdir(parents=True, exist_ok=True)
        provenance = {
            "schema": "poker-population-increment-overlay-provenance/v1", "source_decisions": decisions.as_posix(),
            "source_decisions_sha256": sha256_file(decisions), "overlay_sha256": sha256_file(out),
            "builder": Path(__file__).relative_to(ROOT).as_posix(), "builder_sha256": sha256_file(Path(__file__)), "code_commit": git_commit(),
            "summary": obj["summary"], "base_contract": obj["base_contract"],
        }
        provenance_out.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(obj["summary"], indent=2, ensure_ascii=False)); print("WROTE", out, out.stat().st_size)
    return obj


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--decisions", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--provenance-out", type=Path, default=None)
    return p.parse_args()


def main():
    args = parse_args(); build(args.decisions, args.out, args.provenance_out)


if __name__ == "__main__":
    main()
