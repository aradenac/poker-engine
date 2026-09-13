#!/usr/bin/env python3
"""Rebuild a conservative preflop Model A exact-marginal candidate.

Only TRAIN population rows matching an existing exact structural node are
applied. The previous posterior is carried as pseudo-evidence of mass
``old_n + alpha_exact``. Hand-level policy169, revealed-card policy models,
response models and continuous population adjustments are frozen.
"""
from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import json
from pathlib import Path


def fingerprint(ids):
    return hashlib.sha256("\n".join(sorted(set(map(str, ids)))).encode()).hexdigest()


def split_metadata(decisions: Path):
    ids={"TRAIN":set(),"VALIDATION":set(),"TEST":set()}
    with decisions.open(encoding="utf-8") as f:
        for line in f:
            row=json.loads(line); ids[row["split"]].add(str(row["hand_id"]))
    return {k:{"hands":len(v),"fingerprint":fingerprint(v)} for k,v in ids.items()}


def node_key(node):
    return node.get("canonical_key") or node.get("id")


def rebuild(*, baseline: Path, overlay_path: Path, decisions: Path, out: Path,
            date: str, source_label: str, lineage_fingerprint: str,
            model_version: str="preflop_v6_incremental_exact_marginals_REJECTED"):
    base=json.loads(baseline.read_text(encoding="utf-8"))
    overlay=json.loads(overlay_path.read_text(encoding="utf-8"))
    obj=copy.deepcopy(base)
    omap={node_key(x):x for x in overlay.get("preflop_nodes",[])}
    alphas=list((base.get("training",{}) or {}).get("selected_hierarchy_alphas") or [])
    alpha_exact=int(alphas[-1] if alphas else 40)
    applied_rows=0; touched=0; train_hands_applied=set(); applied_by_action=collections.Counter()

    existing_keys={node_key(n) for n in obj.get("nodes",[])}
    with decisions.open(encoding="utf-8") as f:
        for line in f:
            row=json.loads(line)
            if row.get("split")!="TRAIN" or row.get("is_hero") or row.get("street")!="preflop":
                continue
            if row.get("canonical_key") in existing_keys:
                train_hands_applied.add(str(row["hand_id"]))

    for node in obj.get("nodes",[]):
        key=node_key(node); delta=omap.get(key)
        if not delta or not int(delta.get("n_delta") or 0):
            continue
        touched+=1
        dn=int(delta["n_delta"])
        observed_old=node.get("population_observed") or {}
        old_n=int(observed_old.get("n") or 0); new_n=old_n+dn
        model=node.get("population_model") or {}
        legal=list(model.get("legal_actions") or (delta.get("actions") or {}).keys())
        old_actions=observed_old.get("actions") or {}; delta_actions=delta.get("actions") or {}
        observed={}
        for action in legal:
            dc=int(delta_actions.get(action) or 0)
            count=int((old_actions.get(action) or {}).get("count") or 0)+dc
            observed[action]={"count":count,"frequency":count/new_n if new_n else 0.0}
            applied_by_action[action]+=dc
        node["population_observed"]={"n":new_n,"actions":observed}
        old_freq=dict(model.get("frequencies") or {})
        carry=old_n+alpha_exact; denom=carry+dn
        model["frequencies"]={a:(float(old_freq.get(a,0.0))*carry+int(delta_actions.get(a) or 0))/denom for a in legal}
        # Keep policy169, response-model key and continuous-adjustment fields byte/value frozen.
        if "+increment_exact_marginals_v1" not in str(model.get("method") or ""):
            model["method"]=str(model.get("method") or "hierarchical_train_only_v4")+"+increment_exact_marginals_v1"
        node.setdefault("coverage",{})["population_decisions"]=new_n
        applied_rows+=dn

    # Ranking/serialization follows the production v5 convention: descending exact
    # population support with the incoming node order as deterministic tie-break.
    total=sum(int((n.get("coverage") or {}).get("population_decisions") or 0) for n in obj.get("nodes",[]))
    ranked=sorted(enumerate(obj.get("nodes",[])),key=lambda item:(-int((item[1].get("coverage") or {}).get("population_decisions") or 0),item[0]))
    cumulative=0
    for rank,(_idx,node) in enumerate(ranked,1):
        cov=node.setdefault("coverage",{}); count=int(cov.get("population_decisions") or 0); previous=cumulative/total if total else 0.0
        cumulative+=count; cov["population_share"]=count/total if total else 0.0
        cov["core90"]=previous<0.90; cov["core95"]=previous<0.95; cov["core99"]=previous<0.99
        node["rank_population"]=rank
    obj["nodes"]=[node for _idx,node in ranked]
    obj["coverage"]={f"core{pct}_nodes":sum(bool((n.get("coverage") or {}).get(f"core{pct}")) for n in obj.get("nodes",[])) for pct in (90,95,99)}

    train_available=sum(int(x.get("n_delta") or 0) for x in overlay.get("preflop_nodes",[]))
    skipped=train_available-applied_rows
    splits=split_metadata(decisions)
    obj["model_version"]=model_version
    obj["incremental_update"]={
        "version":"1.0.0","date":date,"source":source_label,
        "delta_hands":sum(v["hands"] for v in splits.values()),
        "train_hands":splits["TRAIN"]["hands"],"validation_hands":splits["VALIDATION"]["hands"],"test_hands":splits["TEST"]["hands"],
        "delta_split_fingerprints":{k:splits[k]["fingerprint"] for k in ("TRAIN","VALIDATION","TEST")},
        "lineage_fingerprint_sha256":lineage_fingerprint,
        "mode":"existing exact structural nodes only; unseen exact contexts are not materialized",
        "marginal_update":f"full-weight additive evidence with posterior carry-forward mass old_n+{alpha_exact}",
        "alpha_exact":alpha_exact,
        "train_population_rows_available":train_available,"train_population_rows_applied":applied_rows,
        "train_population_rows_skipped_no_exact_node":skipped,"touched_nodes":touched,
        "train_hands_with_at_least_one_applied_preflop_row":len(train_hands_applied),
        "applied_by_action":dict(sorted(applied_by_action.items())),
        "policy169":"FROZEN from v5","revealed_policy_models":"FROZEN from v5",
        "response_models":"FROZEN from v5","continuous_population":"FROZEN from v5",
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(obj,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    semantic={
        "nodes":obj.get("nodes"),"coverage":obj.get("coverage"),
        "hand_grid":obj.get("hand_grid"),"response_models":obj.get("response_models"),
        "revealed_policy_models":obj.get("revealed_policy_models"),
    }
    result={
        "out":str(out),"sha256":hashlib.sha256(out.read_bytes()).hexdigest(),
        "semantic_sha256":hashlib.sha256(json.dumps(semantic,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest(),
        "touched_nodes":touched,"applied":applied_rows,"skipped":skipped,
        "coverage":obj["coverage"],"incremental_update":obj["incremental_update"],
    }
    print(json.dumps(result,indent=2,ensure_ascii=False)); return obj


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline",required=True,type=Path);p.add_argument("--overlay",required=True,type=Path);p.add_argument("--decisions",required=True,type=Path);p.add_argument("--out",required=True,type=Path)
    p.add_argument("--date",required=True);p.add_argument("--source-label",required=True);p.add_argument("--lineage-fingerprint",required=True);p.add_argument("--model-version",default="preflop_v6_incremental_exact_marginals_REJECTED")
    a=p.parse_args();rebuild(baseline=a.baseline,overlay_path=a.overlay,decisions=a.decisions,out=a.out,date=a.date,source_label=a.source_label,lineage_fingerprint=a.lineage_fingerprint,model_version=a.model_version)

if __name__=="__main__":main()
