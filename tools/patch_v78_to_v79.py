#!/usr/bin/env python3
"""Patch Poker Range Equity Offline v78 -> v79.

The patch is deliberately fail-fast: every structural replacement is checked so
we do not silently produce a partially patched simulator.

Usage:
  python3 patch_v78_to_v79.py poker_range_equity_offline_multiway_v78.html
  python3 patch_v78_to_v79.py input.html output.html
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected exactly 1 occurrence, found {n}")
    return text.replace(old, new, 1)


def sub_checked(text: str, pattern: str, repl: str, label: str, expected: int = 1, flags: int = 0) -> str:
    out, n = re.subn(pattern, repl, text, count=expected, flags=flags)
    if n != expected:
        raise RuntimeError(f"{label}: expected {expected} replacement(s), got {n}")
    return out


def patch(src: str) -> str:
    text = src

    # Visible/version markers. The title in v78 still says v76, so accept any v7x.
    text, n = re.subn(r"<title>Poker Range Equity — Offline v7\d</title>",
                      "<title>Poker Range Equity — Offline v79</title>", text, count=1)
    if n != 1:
        raise RuntimeError(f"document title: expected 1 replacement, got {n}")

    # ------------------------------------------------------------------
    # 1) Weak-node sizing support: bring local empirical support into the
    #    postflop response metadata so sanity filtering can use it.
    # ------------------------------------------------------------------
    anchor = "function postflopAggressionSupportInfo(street,potType,ratio){"
    if anchor not in text:
        raise RuntimeError("postflopAggressionSupportInfo anchor not found")

    helper = r'''function postflopLocalFacingSupport(node){
  if(!node)return {confidence:'',observations:0,p90:NaN};
  const observations=Number(node.coverage?.population_decisions)||Number(node.population_observed?.n)||0;
  const confidence=String(node.population_model?.confidence||node.model?.confidence||node.confidence||'').toLowerCase();
  const roots=[node.continuous_population,node.continuous_all,node.continuous,node.population_continuous,node.stats];
  const keys=['facing_size_pot_original','facing_price_pot','to_call_pot','facing_size_pot','aggressor_size_pot_original'];
  let p90=NaN;
  for(const root of roots){
    if(!root)continue;
    for(const key of keys){
      const v=Number(root?.[key]?.p90);
      if(Number.isFinite(v)&&v>0){p90=v;break;}
    }
    if(Number.isFinite(p90))break;
  }
  return {confidence,observations,p90};
}
'''
    text = text.replace(anchor, helper + anchor, 1)

    # Enrich every responseMeta record produced by the postflop EV tree.
    # Keep the statistic in the same units as the model's local support:
    # facingPricePot is compared to continuous.facing_price_pot.p90.
    old_meta = (
        "responseMeta.push({name:player.name,nodeId:match.node.id,quality:match.quality,exact:match.exact,"
        "observations:Number(match.node.coverage?.population_decisions)||0,callAmountBB,effectiveActorCostBB,"
        "responderCannotRaise,facingSizePotOriginal:decision.facing_size_pot_original,...qstats,target});"
    )
    new_meta = (
        "responseMeta.push({name:player.name,nodeId:match.node.id,quality:match.quality,exact:match.exact,"
        "observations:Number(match.node.coverage?.population_decisions)||0,callAmountBB,effectiveActorCostBB,"
        "responderCannotRaise,facingSizePotOriginal:decision.facing_size_pot_original,"
        "facingPricePot:decision.facing_price_pot,...postflopLocalFacingSupport(match.node),...qstats,target});"
    )
    text = replace_once(text, old_meta, new_meta, "responseMeta support metadata")

    # ------------------------------------------------------------------
    # 2) Replace v78 sizing sanity with v79 rules.
    #    - very_low node with >=5 obs: do not recommend beyond its local P90
    #    - JAM / >=2x pot with <10 obs: never recommend as a hypothetical
    #    - preserve the existing monotonic anomaly checks for the remaining
    #      weak-node edge cases.
    # ------------------------------------------------------------------
    sanity_pattern = r"function annotatePostflopSizingSanity\(candidates\)\{.*?\n\s*return candidates;\n\}"
    sanity_repl = r'''function annotatePostflopSizingSanity(candidates){
  const ordered=(candidates||[]).filter(c=>c.tree&&Number.isFinite(c.tree.evBB)).slice().sort((a,b)=>(Number(a.costBB)||0)-(Number(b.costBB)||0));
  let prevValid=null;
  const invalidate=(tree,msg)=>{tree.sanityInvalid=true;tree.sanityReason=tree.sanityReason?`${tree.sanityReason} ${msg}`:msg;};
  const responseSupport=tree=>{
    const metas=(tree?.responseMeta||[]);
    const obs=metas.map(x=>Number(x?.observations)).filter(Number.isFinite);
    const floor=obs.length?Math.min(...obs):NaN;
    const veryLow=metas.filter(x=>String(x?.confidence||'').toLowerCase()==='very_low');
    const sparseVeryLow=veryLow.filter(x=>Number(x?.observations)<5);
    const localOod=veryLow.filter(x=>{
      const n=Number(x?.observations),p90=Number(x?.p90),price=Number(x?.facingPricePot);
      return n>=5&&Number.isFinite(p90)&&p90>0&&Number.isFinite(price)&&price>p90+1e-9;
    });
    return {floor,veryLow:veryLow.length>0,sparseVeryLow,localOod};
  };
  for(const c of ordered){
    const q=postflopTreeContinuationQuality(c.tree),pf=Number(c.tree.pAllFold),ratio=Number(c.tree.aggressorSizePot),rs=responseSupport(c.tree),obs=rs.floor;
    c.tree.continueRangeQuality=q;c.tree.sanityInvalid=false;c.tree.sanityReason='';c.tree.responseObservationFloor=obs;
    const support=postflopAggressionSupportInfo(c.tree.street,c.tree.potType,ratio);c.tree.empiricalSizingSupport=support;
    if(support?.ood)invalidate(c.tree,`Sizing hors distribution réelle : ${support.ratio.toFixed(1)}× pot > P99,5 ${support.threshold.toFixed(1)}× (${support.n} actions observées, base ${support.source}).`);

    // Below five exact decisions a very-low-confidence node is essentially a
    // prior-dominated extrapolation.  It may still inform passive decisions,
    // but it is too weak to promote a hypothetical bet/raise as the optimum.
    if(!c.tree.sanityInvalid&&c.kind!=='actual'&&rs.sparseVeryLow.length){
      const x=rs.sparseVeryLow[0];
      invalidate(c.tree,`Agression hypothétique non recommandable : nœud très faible avec seulement ${Number(x.observations)||0} observations.`);
    }

    // Local support is expressed as the responder's price-to-pot ratio, not as
    // the aggressor's bet/pot ratio.  Mixing those units would wrongly reject
    // ordinary sizings.
    if(!c.tree.sanityInvalid&&rs.localOod.length){
      const x=rs.localOod[0],price=Number(x.facingPricePot),p90=Number(x.p90);
      invalidate(c.tree,`Prix de call hors P90 local sur nœud très faible : ${price.toFixed(3)} > ${p90.toFixed(3)} (${Number(x.observations)||0} observations).`);
    }

    const extreme=(c.kind==='jam')||(Number.isFinite(ratio)&&ratio>=2.0);
    const weakExtreme=extreme&&Number.isFinite(obs)&&obs<10;
    if(!c.tree.sanityInvalid&&weakExtreme&&c.kind!=='actual'){
      invalidate(c.tree,`JAM/overbet non recommandable : seulement ${obs} observations sur le nœud de réponse le plus faible.`);
    }

    if(!c.tree.sanityInvalid&&prevValid&&Number.isFinite(ratio)&&Number.isFinite(prevValid.ratio)){
      const largeJump=ratio>=Math.max(prevValid.ratio*1.5,prevValid.ratio+0.75);
      const weakNode=Number.isFinite(obs)&&obs<10;
      if(extreme&&largeJump&&weakNode){
        const qDrop=(Number.isFinite(prevValid.q)&&Number.isFinite(q))?prevValid.q-q:0;
        const fDrop=(Number.isFinite(prevValid.pf)&&Number.isFinite(pf))?prevValid.pf-pf:0;
        if(fDrop>0.10)invalidate(c.tree,`Extrapolation extrême fragile : fold equity baisse de ${(100*fDrop).toFixed(1)} points avec seulement ${obs} observations.`);
        if(!c.tree.sanityInvalid&&qDrop>0.06)invalidate(c.tree,`Extrapolation extrême fragile : qualité de continuation baisse de ${qDrop.toFixed(3)} avec seulement ${obs} observations.`);
        if(!c.tree.sanityInvalid&&fDrop>0.06&&qDrop>0.03)invalidate(c.tree,`Extrapolation extrême fragile : fold equity et qualité se dégradent simultanément avec seulement ${obs} observations.`);
      }
    }
    if(!c.tree.sanityInvalid&&Number.isFinite(ratio))prevValid={ratio,q,pf};
  }
  return candidates;
}'''
    text = sub_checked(text, sanity_pattern, sanity_repl, "annotatePostflopSizingSanity", flags=re.S)

    # ------------------------------------------------------------------
    # 3) Hard-invalid sizings stay invalid.  v78 had a permissive fallback in
    #    sizingOptimizationSummary(): when every candidate was sanityInvalid,
    #    it silently re-enabled them all.  That made the sizing-only panel able
    #    to crown an explicitly rejected overbet/JAM as "best".  Return null
    #    instead when there is no supported sizing.
    # ------------------------------------------------------------------
    old_summary = (
        "function sizingOptimizationSummary(candidates,actualTree,boardLen){annotatePostflopSizingSanity(candidates);"
        "let done=(candidates||[]).filter(x=>x.tree&&Number.isFinite(x.tree.evBB)&&!x.tree.sanityInvalid);"
        "if(!done.length)done=(candidates||[]).filter(x=>x.tree&&Number.isFinite(x.tree.evBB));"
        "if(!done.length)return null;done.sort((a,b)=>b.tree.evBB-a.tree.evBB);"
    )
    new_summary = (
        "function sizingOptimizationSummary(candidates,actualTree,boardLen){annotatePostflopSizingSanity(candidates);"
        "const done=(candidates||[]).filter(x=>x.tree&&Number.isFinite(x.tree.evBB)&&!x.tree.sanityInvalid);"
        "if(!done.length)return null;done.sort((a,b)=>b.tree.evBB-a.tree.evBB);"
    )
    text = replace_once(text, old_summary, new_summary, "hard sizing-sanity fallback")

    # ------------------------------------------------------------------
    # 4) Calibration: remove the three generic JAM residual bonuses.
    #    The other label/street residual corrections stay intact.
    # ------------------------------------------------------------------
    for key in ("Flop|jam", "Turn|jam", "River|jam"):
        pattern = rf'("{re.escape(key)}"\s*:\s*)-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?'
        text = sub_checked(text, pattern, rf'\g<1>0', f"zero {key} calibration")

    # Hybrid switch threshold becomes irrelevant; set to zero for transparent
    # exported configuration as well.
    text = sub_checked(
        text,
        r'("switch_threshold_bb"\s*:\s*)-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?',
        r'\g<1>0',
        "switch_threshold_bb",
    )

    # ------------------------------------------------------------------
    # 5) Interactive decision: best action is always argmax(finalDecisionEV).
    #    No raw-EV fallback and no 0.5 BB policy switch gate.
    # ------------------------------------------------------------------
    interactive_pattern = (
        r"const rawBest=alts\.slice\(\)\.sort\(\(a,b\)=>Number\(b\.evBB\)-Number\(a\.evBB\)\)\[0\],"
        r"policyCandidate=alts\.slice\(\)\.sort\(\(a,b\)=>\(Number\(b\.policyAdjustedEVBB\)\|\|-Infinity\)-"
        r"\(Number\(a\.policyAdjustedEVBB\)\|\|-Infinity\)\)\[0\],switchThreshold=Number\(POSTFLOP_POLICY_CALIBRATION_V3\.params\?\.switch_threshold_bb\)\|\|0;\s*"
        r"const best=\(policyCandidate&&rawBest&&policyCandidate\.label!==rawBest\.label&&Number\(policyCandidate\.policyAdjustedEVBB\)-"
        r"Number\(rawBest\.policyAdjustedEVBB\)>=switchThreshold\)\?policyCandidate:rawBest;\s*"
        r"alts\.sort\(\(a,b\)=>\(a===best\?-1:b===best\?1:\(Number\(b\.policyAdjustedEVBB\)\|\|-Infinity\)-"
        r"\(Number\(a\.policyAdjustedEVBB\)\|\|-Infinity\)\)\);"
    )
    interactive_repl = (
        "const rawBest=alts.slice().sort((a,b)=>Number(b.evBB)-Number(a.evBB))[0];\n"
        "  const best=alts.slice().sort((a,b)=>finalDecisionEV(b)-finalDecisionEV(a))[0]||rawBest;\n"
        "  alts.sort((a,b)=>(a===best?-1:b===best?1:finalDecisionEV(b)-finalDecisionEV(a)));"
    )
    text = sub_checked(text, interactive_pattern, interactive_repl, "interactive best-action argmax", flags=re.S)

    # ------------------------------------------------------------------
    # 6) Background review has its own copy of the selection rule. Patch it
    #    too, otherwise list-level regret and replayer feed can disagree.
    # ------------------------------------------------------------------
    review_pattern = (
        r"rawBest=alts\.slice\(\)\.sort\(\(x,y\)=>Number\(y\.evBB\)-Number\(x\.evBB\)\)\[0\],"
        r"policyCandidate=alts\.slice\(\)\.sort\(\(x,y\)=>\(Number\(y\.policyAdjustedEVBB\)\|\|-Infinity\)-"
        r"\(Number\(x\.policyAdjustedEVBB\)\|\|-Infinity\)\)\[0\],switchThreshold=Number\(POSTFLOP_POLICY_CALIBRATION_V3\.params\?\.switch_threshold_bb\)\|\|0;\s*"
        r"const best=\(policyCandidate&&rawBest&&policyCandidate\.label!==rawBest\.label&&Number\(policyCandidate\.policyAdjustedEVBB\)-"
        r"Number\(rawBest\.policyAdjustedEVBB\)>=switchThreshold\)\?policyCandidate:rawBest;"
    )
    review_repl = (
        "rawBest=alts.slice().sort((x,y)=>Number(y.evBB)-Number(x.evBB))[0];\n"
        "  const best=alts.slice().sort((x,y)=>finalDecisionEV(y)-finalDecisionEV(x))[0]||rawBest;"
    )
    text = sub_checked(text, review_pattern, review_repl, "background review argmax", flags=re.S)

    # Cache/signature bump, so old v78 review scores are not reused.
    text = sub_checked(
        text,
        r"'evtree-v76-policy-v3-weaknode-extreme-sanity'",
        "'evtree-v79-finalev-sparse5-extreme10-p90-nojambonus'",
        "review context signature",
    )

    # Export version marker.
    text, n = re.subn(r'application:\{name:"Poker Range Equity Offline",version:"v\d+"',
                      'application:{name:"Poker Range Equity Offline",version:"v79"', text, count=1)
    if n != 1:
        raise RuntimeError(f"AI export version: expected 1 replacement, got {n}")

    # Replace the obsolete calibration caveat with the v79 rule set.
    old_caveat_fragment = (
        "Postflop recommendations use policy calibration v3, frozen before the H3 holdout; it corrects systematic street×sizing EV bias and applies a small deep-aggression penalty beyond 2× pot. "
        "The user-facing UI exposes a single final EV, identical to the value used by the recommendation feed. Raw tree EV remains internal/export-only for diagnostics. Extreme monotonicity vetoes are restricted to response nodes with fewer than 10 observations."
    )
    new_caveat_fragment = (
        "Postflop recommendations use one final EV and select its strict argmax. Street×sizing residual calibration is retained, but the generic JAM residual bonuses are disabled. "
        "Hypothetical aggression is excluded when any response node is very-low-confidence with fewer than 5 observations. JAM/overbet candidates require at least 10 response observations; for very-low-confidence nodes with at least 5 observations, hypothetical actions beyond the locally observed P90 call-price support are excluded when that statistic is available. Raw tree EV remains export-only for diagnostics."
    )
    if old_caveat_fragment in text:
        text = text.replace(old_caveat_fragment, new_caveat_fragment, 1)

    # Footer marker; keep historical markers but add an unambiguous v79 marker.
    marker = "/* v67 bounded replayer scheduler active */"
    if marker in text and "/* v79 final-EV recommendation guard active */" not in text:
        text = text.replace(marker, marker + "\n/* v79 final-EV recommendation guard active */", 1)

    # ------------------------------------------------------------------
    # Structural assertions: detect partial patches before writing output.
    # ------------------------------------------------------------------
    forbidden = [
        '"Flop|jam":6.4719764929167365',
        '"Turn|jam":3.7876460698280696',
        '"River|jam":5.333738215581607',
        'switchThreshold=Number(POSTFLOP_POLICY_CALIBRATION_V3.params?.switch_threshold_bb)',
        "if(!done.length)done=(candidates||[]).filter(x=>x.tree&&Number.isFinite(x.tree.evBB));",
    ]
    leftovers = [s for s in forbidden if s in text]
    if leftovers:
        raise RuntimeError("v79 verification failed; obsolete constructs remain: " + ", ".join(leftovers))

    required = [
        "function postflopLocalFacingSupport(node)",
        "facingPricePot:decision.facing_price_pot",
        "Prix de call hors P90 local",
        "Agression hypothétique non recommandable",
        "JAM/overbet non recommandable",
        "const done=(candidates||[]).filter(x=>x.tree&&Number.isFinite(x.tree.evBB)&&!x.tree.sanityInvalid);",
        '"Flop|jam":0',
        '"Turn|jam":0',
        '"River|jam":0',
        "const best=alts.slice().sort((a,b)=>finalDecisionEV(b)-finalDecisionEV(a))[0]||rawBest;",
        "const best=alts.slice().sort((x,y)=>finalDecisionEV(y)-finalDecisionEV(x))[0]||rawBest;",
        "evtree-v79-finalev-sparse5-extreme10-p90-nojambonus",
    ]
    missing = [s for s in required if s not in text]
    if missing:
        raise RuntimeError("v79 verification failed; expected constructs missing: " + ", ".join(missing))

    return text


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print("Usage: patch_v78_to_v79.py INPUT_v78.html [OUTPUT_v79.html]", file=sys.stderr)
        return 2
    inp = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) == 3 else inp.with_name("poker_range_equity_offline_multiway_v79.html")
    src = inp.read_text(encoding="utf-8")
    patched = patch(src)
    out.write_text(patched, encoding="utf-8")
    print(f"v79 written: {out}")
    print(f"bytes: {len(patched.encode('utf-8')):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
