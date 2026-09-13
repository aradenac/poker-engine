#!/usr/bin/env python3
"""Run the sequential arena with a strict reconstruction fallback for baseline jobs.

The production background-review path normally returns a finalized review detail.
A larger frozen corpus exposed legal synthetic states where the review action plan
was fully computed but the finalized `details` list was empty. In that case this
runner reconstructs the same alternative set from the completed action-plan data
already produced by the analyser. It does not skip the scenario and does not invent
an action: if that evidence is insufficient, the original failure remains fatal.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from tools.simulation import sequential_postflop as arena


class BaselineAnalyzerOracle(arena.AnalyzerOracle):
    """Analyzer oracle that recovers only from an absent finalized review detail."""

    fallback_hand_hashes: list[str] = []

    async def decide(self, hand_history: str) -> dict:
        try:
            return await super().decide(hand_history)
        except RuntimeError as exc:
            if str(exc) != "analyser returned no review detail":
                raise

        detail = await self.page.evaluate(
            """()=>{
              const a=window.__p?.actions?.[0];
              if(!a)return null;
              const priorEq=a.values?.[a.sources?.prior],req=a.req,kind=a.actionType;
              if(!['Flop','Turn','River'].includes(a.street)||!Number.isFinite(priorEq)||!req)return null;

              const alts=[];
              let chosenEV=NaN,chosenSE=0,chosenLabel=String(kind||'').toUpperCase(),chosenCost=0;
              const callEV=()=>{
                const cost=Math.max(0,Number(a.toCallBB)||0);
                if(!(cost>0))return NaN;
                return priorEq*actionRakeInfo(a.hand,(Number(req.potBefore)||0)+cost).netPotBB-cost;
              };
              const checkEV=()=>priorEq*actionRakeInfo(a.hand,Number(req.potBefore)||0).netPotBB;
              const push=(x)=>{if(x&&Number.isFinite(Number(x.evBB)))alts.push(x);};

              if(kind==='fold'){
                chosenEV=0;chosenLabel='FOLD';chosenCost=0;
                const v=callEV();if(Number.isFinite(v))push({label:'CALL',evBB:v,seBB:0,kind:'call',costBB:Number(req.cost)||Number(a.toCallBB)||0});
              }else if(kind==='check'){
                chosenEV=checkEV();chosenLabel='CHECK';chosenCost=0;
              }else if(kind==='call'){
                chosenEV=priorEq*req.netPotAfter-req.cost;chosenLabel='CALL';chosenCost=Number(req.cost)||Number(a.toCallBB)||0;
                push({label:'FOLD',evBB:0,seBB:0,kind:'fold',costBB:0});
              }else if(kind==='bet'){
                chosenEV=Number(a.treeValues?.prior?.evBB);chosenSE=Number(a.treeValues?.prior?.evStdErrBB)||0;chosenLabel='BET réel';chosenCost=Number(req.cost)||0;
                const v=checkEV();if(Number.isFinite(v))push({label:'CHECK',evBB:v,seBB:0,kind:'check',costBB:0});
              }else if(kind==='raise'){
                chosenEV=Number(a.treeValues?.prior?.evBB);chosenSE=Number(a.treeValues?.prior?.evStdErrBB)||0;chosenLabel='RAISE réel';chosenCost=Number(req.cost)||0;
                push({label:'FOLD',evBB:0,seBB:0,kind:'fold',costBB:0});
                const v=callEV();if(Number.isFinite(v))push({label:'CALL',evBB:v,seBB:0,kind:'call',costBB:Number(a.toCallBB)||0});
              }else{
                return null;
              }

              annotatePostflopSizingSanity(a.sizingResults||[]);
              for(const c of a.sizingResults||[]){
                if(!c.tree||!Number.isFinite(c.tree.evBB)||c.kind==='actual'||c.tree.sanityInvalid)continue;
                push({
                  label:c.label,
                  evBB:Number(c.tree.evBB),
                  seBB:Number(c.tree.evStdErrBB)||0,
                  kind:'aggression',
                  costBB:Number(c.costBB),
                  responseObservationFloor:c.tree.responseObservationFloor??null,
                  responseConfidence:c.tree.responseConfidence??null,
                  responseConfidenceLabel:c.tree.responseConfidenceLabel??null,
                  responseSource:c.tree.responseSource??null,
                  responseFallbackPath:Array.isArray(c.tree.responseFallbackPath)?[...c.tree.responseFallbackPath]:[],
                  continueRangeQuality:c.tree.continueRangeQuality??null,
                  pAllFold:Number.isFinite(c.tree.pAllFold)?Number(c.tree.pAllFold):null,
                  terminalFoldContributionBB:Number.isFinite(c.tree.terminalFoldContributionBB)?Number(c.tree.terminalFoldContributionBB):null,
                  branchProbabilityMass:Number.isFinite(c.tree.branchProbabilityMass)?Number(c.tree.branchProbabilityMass):null
                });
              }

              if(!Number.isFinite(chosenEV))return null;
              push({label:chosenLabel,evBB:chosenEV,seBB:chosenSE,kind:'chosen',chosen:true,costBB:chosenCost});
              if(!alts.length)return null;
              annotatePostflopPolicyAlternatives(a.street,alts,Number(req.potBefore)||0);
              const rawBest=alts.slice().sort((x,y)=>Number(y.evBB)-Number(x.evBB))[0];
              const best=alts.slice().sort((x,y)=>finalDecisionEV(y)-finalDecisionEV(x))[0]||rawBest;
              if(!best||!Number.isFinite(finalDecisionEV(best)))return null;
              return {
                bestLabel:best.label,
                bestCostBB:Number.isFinite(Number(best.costBB))?Number(best.costBB):0,
                bestEV:finalDecisionEV(best),
                alternatives:alts,
                reconstructedBestLabel:best.label,
                reconstructedBestEV:finalDecisionEV(best),
                reconstructedFallback:true,
                reconstructedStreet:a.street,
                reconstructedActionType:kind,
                assumption:'completed review action plan; missing finalized review detail'
              };
            }"""
        )
        if detail is None:
            raise RuntimeError("analyser returned no review detail and action-plan reconstruction was impossible")

        key = hashlib.sha256(hand_history.encode("utf-8")).hexdigest()
        self.cache[key] = detail
        type(self).fallback_hand_hashes.append(key)
        return detail


async def run(args) -> dict:
    BaselineAnalyzerOracle.fallback_hand_hashes = []
    original = arena.AnalyzerOracle
    arena.AnalyzerOracle = BaselineAnalyzerOracle
    try:
        document = await arena.run(args)
    finally:
        arena.AnalyzerOracle = original
    hashes = sorted(set(BaselineAnalyzerOracle.fallback_hand_hashes))
    document.setdefault("metadata", {})["oracle_reconstruction_fallback"] = {
        "count": len(BaselineAnalyzerOracle.fallback_hand_hashes),
        "unique_states": len(hashes),
        "hand_history_sha256": hashes,
        "rule": "Fallback is allowed only when the analyser completed the review action plan but omitted the finalized review detail; unreconstructible states remain fatal.",
    }
    return document


async def main() -> None:
    args = arena.parse_args()
    document = await run(args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"DONE {out} fallback_count={document['metadata']['oracle_reconstruction_fallback']['count']}",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
