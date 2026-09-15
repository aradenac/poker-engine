#!/usr/bin/env python3
"""Rebuild a conservative preflop Model A candidate from TRAIN evidence.

Two evidence modes are explicit:

``incremental`` (historical default)
    Existing observed counts remain evidence and new TRAIN rows are additive.
    With the default zero policy169 weight this path is intentionally identical
    to the closed historical rebuild contract.

``replace_population`` (#101 target-population mode)
    Historical v5 counts are *not* treated as target-population observations.
    v5 supplies topology and a fixed-strength probability prior only. Certified
    target TRAIN rows replace population_observed/coverage on supported nodes;
    nodes with no target TRAIN support remain labelled prior-only fallbacks.

In target-population mode, the runtime-consumed
``node.population_model.policy169_q_b64`` object may be refitted. Revealed cards
are used only when they were actually observed; hidden hands are never imputed.
"""
from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.training.preflop_policy169 import refit_node_policy169  # noqa: E402

EVIDENCE_MODES = {"incremental", "replace_population"}


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


def _hand_grid_contract(base):
    root=base.get("hand_grid") or {}
    if isinstance(root,dict):
        classes=list(root.get("classes") or [])
        meta=root.get("meta") or {}
    else:
        classes=list(root or [])
        meta={}
    return classes,meta


def _normalise(values, legal):
    raw={a:max(0.0,float(values.get(a,0.0) or 0.0)) for a in legal}
    total=sum(raw.values())
    if total <= 0:
        return {a:1.0/len(legal) for a in legal} if legal else {}
    return {a:raw[a]/total for a in legal}


def rebuild(*, baseline: Path, overlay_path: Path, decisions: Path, out: Path,
            date: str, source_label: str, lineage_fingerprint: str,
            model_version: str="preflop_v6_incremental_exact_marginals_REJECTED",
            policy169_update_weight: float=0.0,
            policy169_prior_strength: float | None=None,
            evidence_mode: str="incremental",
            action_prior_strength: float | None=None):
    if not 0.0 <= float(policy169_update_weight) <= 1.0:
        raise ValueError("policy169_update_weight must be in [0, 1]")
    if evidence_mode not in EVIDENCE_MODES:
        raise ValueError(f"evidence_mode must be one of {sorted(EVIDENCE_MODES)}")
    if evidence_mode == "incremental" and policy169_update_weight != 0.0:
        raise ValueError("policy169 refit is restricted to replace_population mode; historical incremental mode stays frozen")

    base=json.loads(baseline.read_text(encoding="utf-8"))
    overlay=json.loads(overlay_path.read_text(encoding="utf-8"))
    obj=copy.deepcopy(base)
    omap={node_key(x):x for x in overlay.get("preflop_nodes",[])}
    alphas=list((base.get("training",{}) or {}).get("selected_hierarchy_alphas") or [])
    alpha_exact=int(alphas[-1] if alphas else 40)
    prior_strength=float(policy169_prior_strength if policy169_prior_strength is not None else alpha_exact)
    action_prior=float(action_prior_strength if action_prior_strength is not None else alpha_exact)
    if prior_strength <= 0 or action_prior <= 0:
        raise ValueError("prior strengths must be positive")
    hand_grid,hand_meta=_hand_grid_contract(base)
    applied_rows=0; touched=0; applied_by_action=collections.Counter()
    policy_nodes_seen=0; policy_nodes_refit=0; policy_nodes_changed=0
    policy_revealed_rows=0; hidden_hands_imputed=0; prior_only_nodes=0

    for node in obj.get("nodes",[]):
        key=node_key(node); delta=omap.get(key)
        dn=int((delta or {}).get("n_delta") or 0)
        model=node.get("population_model") or {}
        old_freq=dict(model.get("frequencies") or {})
        legal=list(model.get("legal_actions") or ((delta or {}).get("actions") or {}).keys())

        if evidence_mode == "replace_population" and dn <= 0:
            prior_only_nodes+=1
            node["population_observed"]={
                "n":0,
                "actions":{a:{"count":0,"frequency":0.0} for a in legal},
            }
            node.setdefault("coverage",{})["population_decisions"]=0
            model["frequencies"]=_normalise(old_freq,legal)
            base_method=str(model.get("method") or "hierarchical_train_only_v4")
            if "+target_prior_only_v1" not in base_method:
                model["method"]=base_method+"+target_prior_only_v1"
            continue
        if dn <= 0:
            continue

        touched+=1
        observed_old=node.get("population_observed") or {}
        old_n=int(observed_old.get("n") or 0)
        old_actions=observed_old.get("actions") or {}
        delta_actions=(delta or {}).get("actions") or {}
        observed={}

        if evidence_mode == "replace_population":
            new_n=dn
            for action in legal:
                dc=int(delta_actions.get(action) or 0)
                observed[action]={"count":dc,"frequency":dc/new_n if new_n else 0.0}
                applied_by_action[action]+=dc
            node["population_observed"]={"n":new_n,"actions":observed}
            prior=_normalise(old_freq,legal)
            model["frequencies"]=_normalise(
                {a:int(delta_actions.get(a) or 0)+action_prior*prior.get(a,0.0) for a in legal},
                legal,
            )

            original_policy=model.get("policy169_q_b64")
            if isinstance(original_policy,dict):
                policy_nodes_seen+=1
                before=copy.deepcopy(original_policy)
                encoded,diag=refit_node_policy169(
                    node,
                    delta,
                    root_hand_meta=hand_meta,
                    fallback_grid=hand_grid,
                    prior_strength=prior_strength,
                    update_weight=float(policy169_update_weight),
                )
                model["policy169_q_b64"]=encoded
                policy_nodes_refit+=1
                policy_revealed_rows+=int(diag.get("train_revealed_rows") or 0)
                hidden_hands_imputed+=int(diag.get("hidden_hands_imputed") or 0)
                if encoded != before:
                    policy_nodes_changed+=1

            current_method=str(model.get("method") or "hierarchical_train_only_v4")
            parts=["target_population_refit_v1"]
            if policy169_update_weight > 0 and isinstance(model.get("policy169_q_b64"),dict):
                parts.append("policy169_refit_v1")
            for part in parts:
                if f"+{part}" not in current_method:
                    current_method+=f"+{part}"
            model["method"]=current_method
        else:
            # Keep this block identical in semantics and arithmetic to the
            # historical implementation. Closed-run reproducibility depends on
            # exact floating-point operation order and coverage flags.
            new_n=old_n+dn
            for action in legal:
                dc=int(delta_actions.get(action) or 0)
                count=int((old_actions.get(action) or {}).get("count") or 0)+dc
                observed[action]={"count":count,"frequency":count/new_n if new_n else 0.0}
                applied_by_action[action]+=dc
            node["population_observed"]={"n":new_n,"actions":observed}
            carry=old_n+alpha_exact; denom=carry+dn
            model["frequencies"]={a:(float(old_freq.get(a,0.0))*carry+int(delta_actions.get(a) or 0))/denom for a in legal}
            if "+increment_exact_marginals_v1" not in str(model.get("method") or ""):
                model["method"]=str(model.get("method") or "hierarchical_train_only_v4")+"+increment_exact_marginals_v1"

        node.setdefault("coverage",{})["population_decisions"]=new_n
        applied_rows+=dn

    if hidden_hands_imputed:
        raise AssertionError("policy169 refit must never impute hidden hand classes")

    total=sum(int((n.get("coverage") or {}).get("population_decisions") or 0) for n in obj.get("nodes",[]))
    ranked=sorted(enumerate(obj.get("nodes",[])),key=lambda item:(-int((item[1].get("coverage") or {}).get("population_decisions") or 0),item[0]))
    cumulative=0
    for rank,(_idx,node) in enumerate(ranked,1):
        cov=node.setdefault("coverage",{}); count=int(cov.get("population_decisions") or 0); previous=cumulative/total if total else 0.0
        cumulative+=count; cov["population_share"]=count/total if total else 0.0
        if evidence_mode == "incremental":
            cov["core90"]=previous<0.90; cov["core95"]=previous<0.95; cov["core99"]=previous<0.99
        else:
            cov["core90"]=bool(count) and previous<0.90; cov["core95"]=bool(count) and previous<0.95; cov["core99"]=bool(count) and previous<0.99
        node["rank_population"]=rank
    obj["nodes"]=[node for _idx,node in ranked]
    obj["coverage"]={f"core{pct}_nodes":sum(bool((n.get("coverage") or {}).get(f"core{pct}")) for n in obj.get("nodes",[])) for pct in (90,95,99)}

    train_available=sum(int(x.get("n_delta") or 0) for x in overlay.get("preflop_nodes",[]))
    skipped=train_available-applied_rows
    splits=split_metadata(decisions)
    obj["model_version"]=model_version

    if evidence_mode == "incremental":
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
            "applied_by_action":dict(sorted(applied_by_action.items())),
            "policy169":"FROZEN from v5","revealed_policy_models":"FROZEN from v5",
            "response_models":"FROZEN from v5","continuous_population":"FROZEN from v5",
        }
    else:
        policy_mode=(
            "FROZEN from baseline (target marginal-only control)"
            if policy169_update_weight == 0
            else "REFIT runtime population_model.policy169_q_b64 from TRAIN marginals plus revelation-rate-shrunk observed hand/action residuals"
        )
        obj["incremental_update"]={
            "version":"1.2.0","date":date,"source":source_label,
            "delta_hands":sum(v["hands"] for v in splits.values()),
            "train_hands":splits["TRAIN"]["hands"],"validation_hands":splits["VALIDATION"]["hands"],"test_hands":splits["TEST"]["hands"],
            "delta_split_fingerprints":{k:splits[k]["fingerprint"] for k in ("TRAIN","VALIDATION","TEST")},
            "lineage_fingerprint_sha256":lineage_fingerprint,
            "mode":"existing exact structural nodes only; unseen exact contexts are not materialized",
            "evidence_mode":evidence_mode,
            "marginal_update":f"certified target TRAIN replaces observed counts; v5 probabilities are prior-only with mass {action_prior:g}",
            "alpha_exact":alpha_exact,
            "action_prior_strength":action_prior,
            "train_population_rows_available":train_available,"train_population_rows_applied":applied_rows,
            "train_population_rows_skipped_no_exact_node":skipped,"touched_nodes":touched,
            "prior_only_nodes":prior_only_nodes,
            "applied_by_action":dict(sorted(applied_by_action.items())),
            "policy169":policy_mode,
            "policy169_update_weight":float(policy169_update_weight),
            "policy169_prior_strength":prior_strength,
            "policy169_nodes_seen":policy_nodes_seen,
            "policy169_nodes_refit":policy_nodes_refit,
            "policy169_nodes_changed":policy_nodes_changed,
            "policy169_train_revealed_rows":policy_revealed_rows,
            "policy169_hidden_hands_imputed":hidden_hands_imputed,
            "policy169_limitations":[
                "Hidden hand classes are never imputed.",
                "Within-action card revelation is not assumed missing-at-random; revealed composition is shrunk by action-level revelation rate and prior strength.",
            ],
            "population_scope":"certified target TRAIN only; historical counts excluded from target evidence",
            "revealed_policy_models":"FROZEN from baseline; policy169 refit is isolated and auditable",
            "response_models":"FROZEN from baseline","continuous_population":"FROZEN from baseline",
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
    p.add_argument("--policy169-update-weight",type=float,default=0.0,help="0 preserves historical policy; #101 target candidates use a positive weight")
    p.add_argument("--policy169-prior-strength",type=float,default=None,help="shrinkage strength for actually revealed hand/action residuals; defaults to alpha_exact")
    p.add_argument("--evidence-mode",choices=sorted(EVIDENCE_MODES),default="incremental",help="historical additive evidence or certified target evidence replacement")
    p.add_argument("--action-prior-strength",type=float,default=None,help="fixed probability-prior mass in replace_population mode; defaults to alpha_exact")
    a=p.parse_args();rebuild(
        baseline=a.baseline,overlay_path=a.overlay,decisions=a.decisions,out=a.out,
        date=a.date,source_label=a.source_label,lineage_fingerprint=a.lineage_fingerprint,
        model_version=a.model_version,policy169_update_weight=a.policy169_update_weight,
        policy169_prior_strength=a.policy169_prior_strength,evidence_mode=a.evidence_mode,
        action_prior_strength=a.action_prior_strength,
    )

if __name__=="__main__":main()
