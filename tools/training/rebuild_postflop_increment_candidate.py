#!/usr/bin/env python3
"""Rebuild a postflop Model A exact-marginal incremental candidate.

The historical update contract carries the previous hierarchical posterior as
pseudo-evidence of mass ``old_n + alpha_exact`` and adds only TRAIN rows that
match an existing exact structural node. Continuous response, combo-policy and
hand-policy components are deliberately frozen.
"""
from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import json
from pathlib import Path

ACTIONS_FREE = ("CHECK", "BET", "JAM")
ACTIONS_FACING = ("FOLD", "CALL", "RAISE", "JAM")


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
            model_version: str="postflop_v6_incremental_exact_marginals"):
    base=json.loads(baseline.read_text(encoding="utf-8"))
    overlay=json.loads(overlay_path.read_text(encoding="utf-8"))
    obj=copy.deepcopy(base)
    omap={node_key(x):x for x in overlay.get("postflop_nodes",[])}
    alpha_exact=int((base.get("training",{}).get("selected_hyperparameters") or {}).get("alpha_exact",40))
    applied_by_street=collections.Counter(); applied_by_mode=collections.Counter()
    applied_rows=0; touched=0
    matched_overlay=set()
    train_hands_applied=set()

    # Collect hand IDs which actually hit an existing exact postflop node.
    existing_keys={node_key(n) for n in obj.get("nodes",[])}
    with decisions.open(encoding="utf-8") as f:
        for line in f:
            row=json.loads(line)
            if row.get("split")!="TRAIN" or row.get("is_hero") or row.get("street")=="preflop":
                continue
            if row.get("canonical_key") in existing_keys:
                train_hands_applied.add(str(row["hand_id"]))

    for node in obj.get("nodes",[]):
        key=node_key(node); delta=omap.get(key)
        if not delta or not int(delta.get("n_delta") or 0):
            continue
        matched_overlay.add(key); touched+=1
        dn=int(delta["n_delta"]); old_n=int((node.get("population_observed") or {}).get("n") or 0); new_n=old_n+dn
        mode=str((node.get("context") or {}).get("mode") or "")
        street=str((node.get("context") or {}).get("street") or "")
        legal=list((node.get("population_model") or {}).get("legal_actions") or (ACTIONS_FACING if mode=="FACING" else ACTIONS_FREE))
        old_actions=(node.get("population_observed") or {}).get("actions") or {}
        delta_actions=delta.get("actions") or {}
        observed={}
        for action in legal:
            count=int((old_actions.get(action) or {}).get("count") or 0)+int(delta_actions.get(action) or 0)
            observed[action]={"count":count,"frequency":count/new_n if new_n else 0.0}
        node["population_observed"]={"n":new_n,"actions":observed}
        model=node["population_model"]; old_freq=dict(model.get("frequencies") or {})
        carry=old_n+alpha_exact; denom=carry+dn
        model["frequencies"]={a:(float(old_freq.get(a,0.0))*carry+int(delta_actions.get(a) or 0))/denom for a in legal}
        model["method"]="hierarchical_backoff_train_only_v2+increment_exact_marginals_v1"
        node.setdefault("coverage",{})["population_decisions"]=new_n
        applied_by_street[street]+=dn; applied_by_mode[mode]+=dn; applied_rows+=dn

    # Historical ranking is a stable sort by exact population count: original node
    # order is the deterministic tie-break. The historical candidate also serialized
    # nodes in this ranked order, so restore that order after assigning ranks.
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

    dataset=obj.setdefault("dataset",{})
    street_counts=dict(dataset.get("street_train_population_decisions") or {})
    mode_counts=dict(dataset.get("mode_train_population_decisions") or {})
    for k,v in applied_by_street.items(): street_counts[k]=int(street_counts.get(k,0))+v
    for k,v in applied_by_mode.items(): mode_counts[k]=int(mode_counts.get(k,0))+v
    dataset["street_train_population_decisions"]=street_counts; dataset["mode_train_population_decisions"]=mode_counts

    splits=split_metadata(decisions)
    train_available=int((overlay.get("summary") or {}).get("train_population_rows") or 0)-sum(int(x.get("n_delta") or 0) for x in overlay.get("preflop_nodes",[]))
    skipped=train_available-applied_rows
    obj["model_version"]=model_version
    obj["incremental_update"]={
        "version":"1.0.0","date":date,"source":source_label,
        "delta_hands":sum(v["hands"] for v in splits.values()),
        "train_hands":splits["TRAIN"]["hands"],"validation_hands":splits["VALIDATION"]["hands"],"test_hands":splits["TEST"]["hands"],
        "delta_split_fingerprints":{k:splits[k]["fingerprint"] for k in ("TRAIN","VALIDATION","TEST")},
        "lineage_fingerprint_sha256":lineage_fingerprint,
        "mode":"existing exact structural nodes only; unmatched parser keys are ignored rather than creating fallback-derived nodes",
        "marginal_update":"full-weight additive evidence with historical posterior carry-forward mass old_n+40",
        "train_population_rows_available":train_available,"train_population_rows_applied":applied_rows,
        "train_population_rows_skipped_no_exact_node":skipped,"touched_nodes":touched,
        "train_hands_with_at_least_one_applied_postflop_row":len(train_hands_applied),
        "applied_by_street":dict(sorted(applied_by_street.items())),"applied_by_mode":dict(sorted(applied_by_mode.items())),
        "continuous_response_models":"FROZEN from v5","combo_policy_models":"FROZEN from v5","hand_policy_prior":"FROZEN from v5","ev_confidence":"not added",
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(obj,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print(json.dumps({"out":str(out),"sha256":hashlib.sha256(out.read_bytes()).hexdigest(),"touched_nodes":touched,"applied":applied_rows,"skipped":skipped,"coverage":obj["coverage"],"incremental_update":obj["incremental_update"]},indent=2,ensure_ascii=False))
    return obj


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline",required=True,type=Path);p.add_argument("--overlay",required=True,type=Path);p.add_argument("--decisions",required=True,type=Path);p.add_argument("--out",required=True,type=Path)
    p.add_argument("--date",required=True);p.add_argument("--source-label",required=True);p.add_argument("--lineage-fingerprint",required=True);p.add_argument("--model-version",default="postflop_v6_incremental_exact_marginals")
    a=p.parse_args();rebuild(baseline=a.baseline,overlay_path=a.overlay,decisions=a.decisions,out=a.out,date=a.date,source_label=a.source_label,lineage_fingerprint=a.lineage_fingerprint,model_version=a.model_version)

if __name__=="__main__":main()
