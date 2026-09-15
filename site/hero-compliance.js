(function(root,factory){
  const api=factory(root&&root.PokerHeroRanges);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerHeroCompliance=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(HeroRanges){
  'use strict';

  const SCHEMA='poker-hero-range-compliance/v1';
  const DEPTH_ABS_TOLERANCE_BB=2;
  const SIZING_ABS_TOLERANCE_BB=.05;
  const SIZING_REL_TOLERANCE=.02;
  const tokenCache=typeof WeakMap==='function'?new WeakMap():null;

  function fnv1a(text){let h=2166136261>>>0;for(let i=0;i<text.length;i++){h^=text.charCodeAt(i);h=Math.imul(h,16777619)>>>0;}return h>>>0;}
  function stableStringify(value){
    if(value===null||typeof value!=='object')return JSON.stringify(value);
    if(Array.isArray(value))return '['+value.map(stableStringify).join(',')+']';
    return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+stableStringify(value[k])).join(',')+'}';
  }
  function repositoryVersionToken(repo){
    if(!repo||typeof repo!=='object')return null;
    if(tokenCache?.has(repo))return tokenCache.get(repo);
    const schema=String(repo.schema||'unknown').replace(/[^a-zA-Z0-9_-]/g,'_');
    // The preserved legacy source is provenance, not the editable strategy.
    // Tokenize the actual decision-bearing repository state only.
    const identity={schema:repo.schema||null,version:repo.version??null,defaults:repo.defaults||null,contexts:repo.contexts||{}};
    const token=`${schema}-${fnv1a(stableStringify(identity)).toString(16).padStart(8,'0')}`;
    tokenCache?.set(repo,token);return token;
  }

  function decisionHistory(decision){return decision?.history||decision?.preflop_context_v1?.history||[];}
  function lastAggressiveAction(history){
    for(let i=(history||[]).length-1;i>=0;i--){const a=String(history[i]?.action||'').toUpperCase();if(a==='RAISE'||a==='JAM')return a;}
    return null;
  }

  function spotForDecision(decision){
    const history=decisionHistory(decision),toCall=Number(decision?.to_call_bb??decision?.preflop_context_v1?.to_call_bb)||0;
    if(lastAggressiveAction(history)==='JAM'&&toCall>1e-9)return 'VS_JAM';
    const family=String(decision?.family||decision?.preflop_context_v1?.family||'').toUpperCase();
    const map={
      UNOPENED:'UNOPENED',VS_LIMPERS:'VS_LIMPERS',
      VS_RFI:'VS_RFI',VS_RFI_CALLERS:'VS_RFI_CALLERS',
      VS_ISO:'VS_ISO',LIMPER_VS_ISO:'VS_ISO',
      VS_ISO_CALLERS:'VS_ISO_CALLERS',LIMPER_VS_ISO_CALLERS:'VS_ISO_CALLERS',
      OPENER_OR_ISO_VS_3BET:'VS_3BET',CALLER_VS_SQUEEZE_OR_3BET:'VS_3BET',COLD_VS_3BET:'VS_3BET',
      AGGRESSOR_VS_4BET:'VS_4BET',CALLER_VS_4BET:'VS_4BET',COLD_VS_4BET:'VS_4BET',
      VS_5BET:'VS_5BET',VS_6BET_PLUS:'VS_6BET_PLUS'
    };
    return map[family]||null;
  }

  function plannedActionForDecision(decision){
    const action=String(decision?.action||'').toUpperCase(),history=decisionHistory(decision);
    const raiseLevel=Number(decision?.raise_level??decision?.preflop_context_v1?.raise_level)||0;
    if(action==='FOLD'||action==='CHECK')return action;
    if(action==='LIMP')return history.some(x=>x.action==='LIMP')?'OVERLIMP':'LIMP';
    if(action==='CALL')return lastAggressiveAction(history)==='JAM'?'CALL_SHOVE':'CALL';
    if(action==='JAM')return 'SHOVE';
    if(action==='RAISE'){
      if(raiseLevel===0)return history.some(x=>x.action==='LIMP')?'ISO':'OPEN';
      if(raiseLevel===1)return '3BET';
      if(raiseLevel===2)return '4BET';
      return null;
    }
    return null;
  }

  function candidateContexts(repo,base){
    const out=[];
    for(const node of Object.values(repo?.contexts||{})){
      const c=node?.context||{};
      if(String(c.population_id)!==String(base.population_id))continue;
      if(Number(c.table_size)!==Number(base.table_size))continue;
      if(String(c.position)!==String(base.position))continue;
      if(String(c.spot)!==String(base.spot))continue;
      const stack=Number(c.effective_stack_bb),wanted=Number(base.effective_stack_bb);
      if(!Number.isFinite(stack)||!Number.isFinite(wanted)||wanted<=0)continue;
      const abs=Math.abs(stack-wanted),rel=abs/Math.max(1,wanted);
      out.push({node,context:c,abs,rel,exact:abs<=1e-9});
    }
    out.sort((a,b)=>a.abs-b.abs||a.rel-b.rel);
    return out;
  }

  function resolveContext(repo,decision,{populationId=null}={}){
    if(!HeroRanges||!repo||repo.schema!==HeroRanges.SCHEMA)return {status:'NO_REPOSITORY',context:null,node:null};
    const ctx=decision?.preflop_context_v1||decision||{};
    const position=String(ctx.actor_position||decision?.actor_position||'').toUpperCase(),spot=spotForDecision(decision),stack=Number(ctx.effective_stack_bb);
    const population_id=String(populationId||repo.defaults?.population_id||''),table_size=Number(ctx.table_size||decision?.table_size||6);
    if(!population_id||!position||!spot||!Number.isFinite(stack)||stack<=0)return {status:'UNSUPPORTED_CONTEXT',context:null,node:null};
    const base={population_id,table_size,position,effective_stack_bb:stack,spot},candidates=candidateContexts(repo,base);
    if(!candidates.length)return {status:'UNCOVERED_CONTEXT',context:base,node:null};
    const best=candidates[0],covered=best.exact||best.abs<=DEPTH_ABS_TOLERANCE_BB;
    if(!covered)return {status:'UNCOVERED_DEPTH',context:base,node:null,nearest_context:best.context,depth_delta_bb:best.abs,depth_delta_fraction:best.rel};
    return {status:'RESOLVED',context:best.context,node:best.node,depth_match:best.exact?'exact':'nearest',depth_delta_bb:best.abs,depth_delta_fraction:best.rel};
  }

  function layerStrategy(node,hand){
    const personal=node?.layers?.personal?.hands?.[hand]||null;
    if(personal)return {strategy:personal,layer:'personal',version:node.layers.personal.version??null,provenance:node.layers.personal.provenance??null};
    const calculated=node?.layers?.calculated?.hands?.[hand]||null;
    if(calculated)return {strategy:calculated,layer:'calculated',version:node.layers.calculated.version??null,provenance:node.layers.calculated.provenance??null};
    return {strategy:null,layer:null,version:null,provenance:null};
  }

  function sizingCompliance(strategy,plannedAction,decision){
    const expected=strategy?.sizings?.[plannedAction]||null,observed=Number(decision?.action_sizing_v1?.target_total_bb);
    if(!expected?.length)return {status:'UNCOVERED',observed_target_total_bb:Number.isFinite(observed)?observed:null,expected:[]};
    if(!Number.isFinite(observed))return {status:'UNKNOWN_OBSERVED_SIZE',observed_target_total_bb:null,expected};
    let best=null;
    for(const row of expected){
      const target=Number(row.target_total_bb);if(!Number.isFinite(target))continue;
      const delta=Math.abs(observed-target),tol=Math.max(SIZING_ABS_TOLERANCE_BB,Math.abs(target)*SIZING_REL_TOLERANCE);
      const candidate={...row,target_total_bb:target,delta_bb:delta,tolerance_bb:tol,matched:delta<=tol};
      if(!best||candidate.delta_bb<best.delta_bb)best=candidate;
    }
    if(!best)return {status:'UNCOVERED',observed_target_total_bb:observed,expected};
    return {status:best.matched?'MATCHED':'OUT_OF_RANGE',observed_target_total_bb:observed,expected,best};
  }

  function editorHref(result){
    if(!result?.resolved_context)return './hero-ranges.html';
    const c=result.resolved_context,p=new URLSearchParams({population:c.population_id,position:c.position,stack:String(c.effective_stack_bb),spot:c.spot,hand:result.hand_class||''});
    return `./hero-ranges.html?${p.toString()}`;
  }

  function evaluateDecision({repo,decision,handClass,populationId=null}={}){
    const repository_token=repositoryVersionToken(repo);
    const base={schema:SCHEMA,repository_token,hand_class:String(handClass||''),observed_runtime_action:String(decision?.action||''),planned_action:null,action_probability:null,action_status:null,sizing:{status:'NOT_APPLICABLE',expected:[]},resolved_context:null,context_status:null,layer:null,layer_version:null,provenance:null,ev_deviation_bb:null,ev_status:'NOT_EVALUATED',frequency_calibration_status:'SAMPLE_REQUIRED'};
    if(!HeroRanges||!repo||repo.schema!==HeroRanges.SCHEMA)return {...base,context_status:'NO_REPOSITORY',action_status:'NO_VERDICT',editor_href:'./hero-ranges.html'};
    if(!HeroRanges.HAND_CLASSES.includes(base.hand_class))return {...base,context_status:'UNKNOWN_HAND',action_status:'NO_VERDICT',editor_href:'./hero-ranges.html'};
    const resolved=resolveContext(repo,decision,{populationId});
    if(resolved.status!=='RESOLVED')return {...base,context_status:resolved.status,resolved_context:resolved.context||null,nearest_context:resolved.nearest_context||null,depth_delta_bb:resolved.depth_delta_bb??null,action_status:'NO_VERDICT',editor_href:editorHref({...base,resolved_context:resolved.context||null})};
    const planned=plannedActionForDecision(decision),layer=layerStrategy(resolved.node,base.hand_class);
    const common={...base,context_status:'RESOLVED',resolved_context:resolved.context,depth_match:resolved.depth_match,depth_delta_bb:resolved.depth_delta_bb,layer:layer.layer,layer_version:layer.version,provenance:layer.provenance,planned_action:planned};
    if(!layer.strategy)return {...common,action_status:'UNCOVERED_HAND',editor_href:editorHref({...common,hand_class:base.hand_class})};
    if(!planned||!HeroRanges.ACTIONS.includes(planned))return {...common,action_status:'UNKNOWN_ACTION',editor_href:editorHref({...common,hand_class:base.hand_class})};
    const probability=Number(layer.strategy.actions?.[planned]||0),actionStatus=probability>1e-12?(probability<1-1e-12?'MIXED_ALLOWED':'COMPLIANT'):'OUT_OF_RANGE';
    const aggressive=['OPEN','ISO','3BET','4BET','SHOVE'].includes(planned),sizing=aggressive&&probability>1e-12?sizingCompliance(layer.strategy,planned,decision):{status:'NOT_APPLICABLE',expected:[]};
    const result={...common,action_probability:probability,action_status:actionStatus,sizing,notes:String(layer.strategy.notes||'')};
    result.editor_href=editorHref(result);return result;
  }

  function summarize(results){
    const rows=(results||[]).filter(Boolean),groups={};let judged=0,allowed=0,out=0,uncovered=0,sizingOut=0;
    for(const r of rows){
      if(['COMPLIANT','MIXED_ALLOWED','OUT_OF_RANGE'].includes(r.action_status)){judged++;if(r.action_status==='OUT_OF_RANGE')out++;else allowed++;}else uncovered++;
      if(r.sizing?.status==='OUT_OF_RANGE')sizingOut++;
      const c=r.resolved_context,key=c?`${c.position}|${c.spot}`:'UNRESOLVED';
      const g=groups[key]||(groups[key]={key,position:c?.position||null,spot:c?.spot||null,decisions:0,judged:0,allowed:0,out_of_range:0,uncovered:0,sizing_out_of_range:0});
      g.decisions++;if(['COMPLIANT','MIXED_ALLOWED','OUT_OF_RANGE'].includes(r.action_status)){g.judged++;if(r.action_status==='OUT_OF_RANGE')g.out_of_range++;else g.allowed++;}else g.uncovered++;if(r.sizing?.status==='OUT_OF_RANGE')g.sizing_out_of_range++;
    }
    return {schema:'poker-hero-range-compliance-summary/v1',repository_token:rows.find(r=>r.repository_token)?.repository_token||null,decisions:rows.length,judged,allowed,out_of_range:out,uncovered,sizing_out_of_range:sizingOut,frequency_calibration_status:'SAMPLE_REQUIRED',groups:Object.values(groups)};
  }

  return {SCHEMA,DEPTH_ABS_TOLERANCE_BB,repositoryVersionToken,spotForDecision,plannedActionForDecision,resolveContext,evaluateDecision,summarize,editorHref};
});
