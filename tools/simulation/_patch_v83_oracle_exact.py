#!/usr/bin/env python3
from pathlib import Path
import textwrap

path = Path('tools/simulation/sequential_postflop.py')
text = path.read_text()
start_marker = '        detail = await self.page.evaluate(\n'
end_marker = '\n\n\nasync def rollout'
start = text.index(start_marker)
end = text.index(end_marker, start)
body = r'''detail = await self.page.evaluate(
    """()=>{
      const result=state.reviewScores[Object.keys(state.reviewScores)[0]];
      const detail=result?.details?.[result.details.length-1];
      const a=window.__p?.actions?.[0];
      if(!detail||!a)return detail;
      const priorEq=a.values?.[a.sources?.prior],req=a.req,kind=a.actionType;
      if(!['Flop','Turn','River'].includes(a.street)||!Number.isFinite(priorEq)||!req)return detail;
      const alts=[];
      let chosenEV=NaN,chosenSE=0,chosenLabel=String(kind||'').toUpperCase();
      const callEV=()=>{
        const cost=Math.max(0,Number(a.toCallBB)||0);
        if(!(cost>0))return NaN;
        return priorEq*actionRakeInfo(a.hand,(Number(req.potBefore)||0)+cost).netPotBB-cost;
      };
      const checkEV=()=>priorEq*actionRakeInfo(a.hand,Number(req.potBefore)||0).netPotBB;
      if(kind==='fold'){
        chosenEV=0;chosenLabel='FOLD';
        const v=callEV();if(Number.isFinite(v))alts.push({label:'CALL',evBB:v,seBB:0,kind:'call'});
      }else if(kind==='check'){
        chosenEV=checkEV();chosenLabel='CHECK';
      }else if(kind==='call'){
        chosenEV=priorEq*req.netPotAfter-req.cost;chosenLabel='CALL';
        alts.push({label:'FOLD',evBB:0,seBB:0,kind:'fold'});
      }else if(kind==='bet'){
        chosenEV=Number(a.treeValues?.prior?.evBB);chosenSE=Number(a.treeValues?.prior?.evStdErrBB)||0;chosenLabel='BET réel';
        const v=checkEV();if(Number.isFinite(v))alts.push({label:'CHECK',evBB:v,seBB:0,kind:'check'});
      }else if(kind==='raise'){
        chosenEV=Number(a.treeValues?.prior?.evBB);chosenSE=Number(a.treeValues?.prior?.evStdErrBB)||0;chosenLabel='RAISE réel';
        alts.push({label:'FOLD',evBB:0,seBB:0,kind:'fold'});
        const v=callEV();if(Number.isFinite(v))alts.push({label:'CALL',evBB:v,seBB:0,kind:'call'});
      }else{
        return detail;
      }
      annotatePostflopSizingSanity(a.sizingResults||[]);
      for(const c of a.sizingResults||[]){
        if(!c.tree||!Number.isFinite(c.tree.evBB)||c.kind==='actual'||c.tree.sanityInvalid)continue;
        alts.push({
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
      if(!Number.isFinite(chosenEV)||!alts.length)return detail;
      alts.push({label:chosenLabel,evBB:chosenEV,seBB:chosenSE,kind:'chosen',chosen:true});
      annotatePostflopPolicyAlternatives(a.street,alts,Number(req.potBefore)||0);
      const rawBest=alts.slice().sort((x,y)=>Number(y.evBB)-Number(x.evBB))[0];
      const best=alts.slice().sort((x,y)=>finalDecisionEV(y)-finalDecisionEV(x))[0]||rawBest;
      return {
        ...detail,
        alternatives:alts,
        reconstructedBestLabel:best?.label??null,
        reconstructedBestEV:best?finalDecisionEV(best):null
      };
    }"""
)
if detail is None:
    raise RuntimeError("analyser returned no review detail")
reconstructed = detail.get("reconstructedBestLabel")
if reconstructed and detail.get("bestLabel") and reconstructed != detail.get("bestLabel"):
    raise RuntimeError(
        f"v83 recommendation mismatch: detail={detail.get('bestLabel')!r} reconstructed={reconstructed!r}"
    )
self.cache[key] = detail
return detail'''
fixed = textwrap.indent(body, '        ')
if 'resolveCheckContinuationEV' in fixed:
    raise SystemExit('stale hidden-scope helper still present')
if "c.kind==='actual'" not in fixed or 'Number(c.costBB)' not in fixed:
    raise SystemExit('v83 sizing alternative contract incomplete')
path.write_text(text[:start] + fixed + text[end:])
