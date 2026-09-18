#!/usr/bin/env python3
"""TRAIN-only coverage audit for future Hero preflop expansion (#196).

Certification is authoritative. Only certified TRAIN hand IDs are normalized into
decision rows; VALIDATION and TEST hands never cross the parser boundary.
Diagnostic only: no Hero strategy generation, EV evaluation, or holdout use.
"""
from __future__ import annotations
import argparse, collections, json, math, sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.datasets.build_hand_history_increment import fingerprint, read_archive, sha256_file, split_for
from tools.training.increment_decisions import decision_rows, parse_hand

SCHEMA = "poker-hero-preflop-coverage-audit/v1"
DEFAULT_CERTIFICATION = ROOT / "training/datasets/NLHE_100-200/population_certification.json"
TARGET_GROUPS = ("VS_RFI", "RFI_CALLERS_SQUEEZE", "VS_LIMPERS_ISO", "VS_3BET", "VS_4BET_OR_JAM")

def quantile(values: list[float], q: float) -> float | None:
    xs = sorted(float(x) for x in values if math.isfinite(float(x)))
    if not xs: return None
    if len(xs) == 1: return xs[0]
    pos = q * (len(xs) - 1); lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi: return xs[lo]
    f = pos - lo
    return xs[lo] * (1-f) + xs[hi] * f

def stack_summary(values: list[float], *, include_top: bool = True) -> dict[str, Any]:
    xs = [round(float(x), 6) for x in values if math.isfinite(float(x)) and float(x) > 0]
    result = {
        "n": len(xs), "min_bb": min(xs) if xs else None,
        "p10_bb": quantile(xs,.10), "p25_bb": quantile(xs,.25),
        "p50_bb": quantile(xs,.50), "p75_bb": quantile(xs,.75),
        "p90_bb": quantile(xs,.90), "p95_bb": quantile(xs,.95),
        "max_bb": max(xs) if xs else None,
    }
    if include_top:
        rounded = collections.Counter(round(x) for x in xs)
        result["top_rounded_bb"] = [{"effective_stack_bb": int(s), "observations": int(n)}
            for s,n in sorted(rounded.items(), key=lambda kv:(-kv[1],kv[0]))[:20]]
    return result

def aggressors(history):
    return [str(x.get("position")) for x in history if x.get("action") in {"RAISE","JAM"}]

def limpers_before_first_raise(history):
    n=0
    for x in history:
        if x.get("action") in {"RAISE","JAM"}: break
        n += x.get("action") == "LIMP"
    return n

def callers_after_first_raise(history):
    seen=False; n=0
    for x in history:
        if x.get("action") in {"RAISE","JAM"} and not seen:
            seen=True; continue
        if seen and x.get("action") == "CALL": n += 1
    return n

def coverage_group(row):
    f=str(row.get("family") or "")
    if f=="VS_RFI": return "VS_RFI"
    if f=="VS_RFI_CALLERS": return "RFI_CALLERS_SQUEEZE"
    if f in {"VS_LIMPERS","VS_ISO","VS_ISO_CALLERS","LIMPER_VS_ISO","LIMPER_VS_ISO_CALLERS"}:
        return "VS_LIMPERS_ISO"
    if f in {"OPENER_OR_ISO_VS_3BET","CALLER_VS_SQUEEZE_OR_3BET","COLD_VS_3BET"}:
        return "VS_3BET"
    if f in {"AGGRESSOR_VS_4BET","CALLER_VS_4BET","COLD_VS_4BET","VS_5BET","VS_6BET_PLUS"}:
        return "VS_4BET_OR_JAM"
    return "UNOPENED" if f=="UNOPENED" else "OTHER"

def matrix_key(row):
    h=list(row.get("history") or []); ag=aggressors(h)
    return (coverage_group(row), str(row.get("actor_position") or ""), ag[0] if ag else "",
            callers_after_first_raise(h), limpers_before_first_raise(h), ag[-1] if ag else "",
            bool(h and h[-1].get("action")=="JAM"), str(row.get("family") or ""))

def support_tier(n):
    return "VERY_HIGH" if n>=1000 else "HIGH" if n>=250 else "MEDIUM" if n>=50 else "LOW" if n>=20 else "SPARSE"

def load_train_records(certification_path):
    cert=json.loads(certification_path.read_text(encoding="utf-8"))
    if cert.get("schema")!="poker-population-certification/v1": raise ValueError("unexpected certification schema")
    status=cert.get("status") or {}; adm=status.get("ADMISSIBLE") or {}
    exc=status.get("EXCLUDED") or {}; amb=status.get("AMBIGUOUS") or {}
    if int(amb.get("unique_hands") or 0): raise ValueError("AMBIGUOUS certified hands present")
    by_id={}; evidence=[]
    for a in cert.get("archives") or []:
        rel=str(a.get("path") or ""); p=ROOT/rel
        if not p.is_file(): raise FileNotFoundError(p)
        actual=sha256_file(p)
        if actual!=str(a.get("sha256") or ""): raise ValueError(f"archive SHA mismatch: {rel}")
        records,meta=read_archive(p)
        evidence.append({"path":rel,"sha256":actual,"unique_hands":int(meta["unique_hands"])})
        for r in records:
            old=by_id.get(r.hand_id)
            if old is None or (getattr(old,"language","")!="en" and r.language=="en"): by_id[r.hand_id]=r
    target=set(by_id)-{str(x) for x in exc.get("hand_ids") or []}
    if len(target)!=int(adm.get("unique_hands") or 0) or fingerprint(target)!=str(adm.get("fingerprint_sha256") or ""):
        raise ValueError("certified target identity mismatch")
    train={x for x in target if split_for(x)=="TRAIN"}
    splits=adm.get("split_counts") or {}
    if len(train)!=int(splits.get("TRAIN") or 0): raise ValueError("TRAIN count mismatch")
    provenance={"certification_path":certification_path.relative_to(ROOT).as_posix(),
        "certification_sha256":sha256_file(certification_path),
        "population_fingerprint_sha256":str(adm.get("fingerprint_sha256") or ""),
        "certified_hands":int(adm.get("unique_hands") or 0),
        "certified_split_counts":{k:int(splits.get(k) or 0) for k in ("TRAIN","VALIDATION","TEST")},
        "archives":evidence}
    return [by_id[x] for x in sorted(train,key=int)], provenance

def audit(certification_path=DEFAULT_CERTIFICATION):
    records,prov=load_train_records(certification_path)
    parsed=0; parsed_ids=set(); decisions=[]; errors=[]
    for r in records:
        if split_for(r.hand_id)!="TRAIN": raise AssertionError("non-TRAIN record crossed parser boundary")
        hand=parse_hand(r.text,r.source_file)
        if not hand: errors.append(r.hand_id); continue
        parsed+=1; parsed_ids.add(str(r.hand_id))
        for row in decision_rows(hand,include_preflop_context_v1=True):
            if row.get("split")!="TRAIN": raise AssertionError("non-TRAIN decision row produced")
            if row.get("street")=="preflop": decisions.append(row)
    if errors: raise ValueError(f"{len(errors)} TRAIN hands failed normalization: {errors[:10]}")
    pop=[r for r in decisions if not r.get("is_hero")]; hero=[r for r in decisions if r.get("is_hero")]
    fam=collections.Counter(str(r.get("family") or "") for r in pop)
    groups=collections.Counter(coverage_group(r) for r in pop)
    grouped={}
    for row in pop:
        group=coverage_group(row)
        if group not in TARGET_GROUPS: continue
        key=matrix_key(row); e=grouped.setdefault(key,{"n":0,"hands":set(),"stacks":[]})
        e["n"]+=1; e["hands"].add(str(row["hand_id"]))
        s=(row.get("preflop_context_v1") or {}).get("effective_stack_bb")
        if s is not None: e["stacks"].append(float(s))
    targeted=sum(e["n"] for e in grouped.values()); matrix=[]
    for rank,(key,e) in enumerate(sorted(grouped.items(),key=lambda kv:(-kv[1]["n"],kv[0])),1):
        group,actor,opener,callers,limpers,last,jam,family=key; n=e["n"]
        matrix.append({"priority_rank":rank,"coverage_group":group,"family":family,"actor_position":actor,
            "opener_position":opener or None,"callers_after_first_raise":callers,
            "limpers_before_first_raise":limpers,"last_aggressor_position":last or None,"facing_jam":jam,
            "observations":n,"distinct_hands":len(e["hands"]),
            "frequency_of_targeted":n/targeted if targeted else 0.0,
            "frequency_of_population_preflop":n/len(pop) if pop else 0.0,
            "support_tier":support_tier(n),"effective_stack":stack_summary(e["stacks"], include_top=False)})
    stacks=[float(s) for r in pop if coverage_group(r) in TARGET_GROUPS
        for s in [(r.get("preflop_context_v1") or {}).get("effective_stack_bb")] if s is not None]
    return {"schema":SCHEMA,"population_id":"pokerstars_nlhe_100-200_zoom_play_6max_v1",
        "scope":{"split_consumed":"TRAIN","validation_consumed":False,"test_consumed":False,
            "strategy_generated":False,"ev_evaluated":False,
            "purpose":"TRAIN-only coverage audit / preparatory slice for issue #196"},
        "provenance":prov,"accounting":{"train_hands_expected":prov["certified_split_counts"]["TRAIN"],
            "train_hands_parsed":parsed,"train_unique_hand_ids_parsed":len(parsed_ids),
            "train_preflop_decisions_all":len(decisions),"train_preflop_decisions_population":len(pop),
            "train_preflop_decisions_hero":len(hero),"targeted_population_preflop_decisions":targeted},
        "family_distribution_population":dict(sorted(fam.items(),key=lambda kv:(-kv[1],kv[0]))),
        "coverage_group_distribution_population":dict(sorted(groups.items(),key=lambda kv:(-kv[1],kv[0]))),
        "effective_stack_targeted_population":stack_summary(stacks),
        "priority_contract":{"ordering":"descending TRAIN population observations; lexical matrix-key tie-break",
            "support_tiers":{"VERY_HIGH":">=1000 observations","HIGH":"250-999 observations",
                "MEDIUM":"50-249 observations","LOW":"20-49 observations","SPARSE":"<20 observations"},
            "interpretation":"Descriptive TRAIN coverage order only; not a strategy or promotion decision."},
        "matrix":matrix}

def render_markdown(report):
    a=report["accounting"]; s=report["effective_stack_targeted_population"]; total=a["train_preflop_decisions_population"] or 1
    lines=["# Hero preflop coverage — TRAIN-only preparatory audit","",
        "Diagnostic only: no Hero strategy is generated and neither VALIDATION nor TEST decisions are consumed.","",
        "## Accounting","",f"- Certified TRAIN hands parsed: **{a['train_hands_parsed']:,} / {a['train_hands_expected']:,}**",
        f"- Population preflop decisions: **{a['train_preflop_decisions_population']:,}**",
        f"- Targeted future-coverage decisions: **{a['targeted_population_preflop_decisions']:,}**",
        f"- Effective-stack median (targeted): **{s['p50_bb']:.1f} BB**" if s["p50_bb"] is not None else "- Effective-stack median: n/a",
        "","## Family/group frequency",""]
    for g,n in report["coverage_group_distribution_population"].items():
        lines.append(f"- {g}: {n:,} ({100*n/total:.2f} % of population preflop decisions)")
    lines += ["","## Highest-priority TRAIN-supported matrix cells","",
        "| Rank | Group | Family | Actor | Opener | Callers | Limpers | Jam | Obs. | Support |",
        "|---:|---|---|---|---|---:|---:|:---:|---:|---|"]
    for r in report["matrix"][:40]:
        lines.append(f"| {r['priority_rank']} | {r['coverage_group']} | {r['family']} | {r['actor_position']} | {r['opener_position'] or '—'} | {r['callers_after_first_raise']} | {r['limpers_before_first_raise']} | {'yes' if r['facing_jam'] else 'no'} | {r['observations']} | {r['support_tier']} |")
    lines += ["","## Reproduction","",
        "python3 tools/training/audit_hero_preflop_coverage.py --output-json analysis/hero_preflop_coverage_train.json --output-md analysis/hero_preflop_coverage_train.md","",
        "The tool verifies certification/archive SHA identities and filters to TRAIN hand IDs before normalization.",""]
    return "\n".join(lines)

def write_outputs(report,json_path,md_path):
    json_path.parent.mkdir(parents=True,exist_ok=True); md_path.parent.mkdir(parents=True,exist_ok=True)
    json_path.write_text(json.dumps(report,indent=2,ensure_ascii=False,sort_keys=True)+"\n",encoding="utf-8")
    md_path.write_text(render_markdown(report),encoding="utf-8")

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--certification",type=Path,default=DEFAULT_CERTIFICATION)
    p.add_argument("--output-json",type=Path); p.add_argument("--output-md",type=Path); p.add_argument("--print-json",action="store_true")
    a=p.parse_args(); cert=a.certification if a.certification.is_absolute() else ROOT/a.certification; report=audit(cert)
    if a.output_json or a.output_md:
        if not (a.output_json and a.output_md): raise SystemExit("--output-json and --output-md must be supplied together")
        write_outputs(report,a.output_json if a.output_json.is_absolute() else ROOT/a.output_json,
            a.output_md if a.output_md.is_absolute() else ROOT/a.output_md)
    print(json.dumps(report if a.print_json else {"accounting":report["accounting"],"top_matrix":report["matrix"][:10]},
        ensure_ascii=False,sort_keys=a.print_json,indent=None if a.print_json else 2,separators=(",",":") if a.print_json else None))
    return 0
if __name__=="__main__": raise SystemExit(main())
