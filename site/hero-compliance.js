(function(root,factory){
  const api=factory(root&&root.PokerHeroRanges);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerHeroCompliance=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(HeroRanges){
  'use strict';

  const SCHEMA='poker-hero-range-compliance/v1';
  const SIZING_ABS_TOLERANCE_BB=.05;
  const SIZING_REL_TOLERANCE=.02;

  function fnv1a(text){let h=2166136261>>>0;for(let i=0;i<text.length;i++){h^=text.charCodeAt(i);h=Math.imul(h,16777619)>>>0;}return h>>>0;}
  function stableStringify(value){
    if(value===null||typeof value!=='object')return JSON.stringify(value);
    if(Array.isArray(value))return '['+value.map(stableStringify).join(',')+']';
    return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+stableStringify(value[k])).join(',')+'}';
  }
  function repositoryVersionToken(repo){
    if(!repo||typeof repo!=='object')return null;
    const schema=String(repo.schema||'unknown').replace(/[^a-zA-Z0-9_-]/g,'_');
    return `${schema}-${fnv1a(stableStringify(repo)).toString(16).padStart(8,'0')}`;
  }

  function spotForDecision(decision){
    const ctx=decision?.preflop_context_v1||decision||{};
    const history=ctx.history||decision?.history||[];
    const last=history[history.length-1];
    const toCall=Number(ctx.to_call_bb??decision?.to_call_bb)||0;
    if(last?.action==='JAM'&&toCall>1e-9)return 'VS_JAM';
    const family=String(ctx.family||decision?.family||'').toUpperCase();
    const map={
      UNOPENED:'UNOPENED',
      VS_LIMPERS:'VS_LIMPERS',
      VS_RFI:'VS_RFI',
      VS_RFI_CALLERS:'VS_RFI_CALLERS',
      VS_ISO:'VS_RFI',
      LIMPER_VS_ISO:'VS_RFI',
      VS_ISO_CALLERS:'VS_RFI_CALLERS',
      LIMPER_VS_ISO_CALLERS:'VS_RFI_CALLERS',
      OPENER_OR_ISO_VS_3BET:'VS_3BET',
      CALLER_VS_SQUEEZE_OR_3BET:'VS_3BET',
      COLD_VS_3BET:'VS_3BET',
      AGGRESSOR_VS_4BET:'VS_4BET',
      CALLER_VS_4BET:'VS_4BET',
      COLD_VS_4BET:'VS_4BET'
    };
    return map[family]||null;
  }

  function plannedActionForDecision(decision){
    const ctx=decision?.preflop_context_v1||decision||{};
    const action=String(decision?.action||'').toUpperCase();
    const history=ctx.history||decision?.history||[];
    const last=history[history.length-1];
    const raiseLevel=Number(ctx.raise_level??decision?.raise_level)||0;
    if(action==='FOLD'||action==='CHECK')return action;
    if(action==='LIMP')return history.some(x=>x.action==='LIMP')?'OVERLIMP':'LIMP';
    if(action==='CALL')return last?.action==='JAM'?'CALL_SHOVE':'CALL';
    if(action==='JAM')return 'SHOVE';
    if(action==='RAISE'){
      if(raiseLevel===0)return history.some(x=>x.action==='LIMP')?'ISO':'OPEN';
      if(raiseLevel===1)return '3BET';
      if(raiseLevel===2)return '4BET';
      return null;
    }
    return null;
  }

  function effectiveStackForDecision(decision){
    // #96 defines effective_stack_bb on the canonical before-action context. Do
    // not infer a Hero-range context from remaining/start stacks: #97 keys
    // ranges by the exact canonical effective stack and owns no bucket policy.
    const hasCanonical=!!(decision&&decision.preflop_context_v1);
    const raw=hasCanonical?decision.preflop_context_v1?.effective_stack_bb:decision?.effective_stack_bb;
    const n=Number(raw);
    return Number.isFinite(n)&&n>0?n:null;
  }

  function comparableContexts(repo,base){
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
      out.push({node,context:c,abs,rel});
    }
    out.sort((a,b)=>a.abs-b.abs||a.rel-b.rel||String(a.context.effective_stack_bb).localeCompare(String(b.context.effective_stack_bb)));
    return out;
  }

  function resolveContext(repo,decision,{populationId=null}={}){
    if(!HeroRanges||!repo||repo.schema!==HeroRanges.SCHEMA)return {status:'NO_REPOSITORY',context:null,node:null};
    const ctx=decision?.preflop_context_v1||decision||{};
    const position=String(ctx.actor_position||decision?.actor_position||'').toUpperCase();
    const spot=spotForDecision(decision);
    const stack=effectiveStackForDecision(decision);
    const population_id=String(populationId||repo.defaults?.population_id||'');
    const table_size=Number(ctx.table_size||decision?.table_size||6);
    if(!population_id||!position||!spot||!Number.isFinite(stack)||stack<=0)return {status:'UNSUPPORTED_CONTEXT',context:null,node:null};
    if(Array.isArray(HeroRanges.SPOTS)&&!HeroRanges.SPOTS.includes(spot))return {status:'UNSUPPORTED_CONTEXT',context:null,node:null};

    let base,key;
    try{
      base=HeroRanges.normalizeContext({population_id,table_size,position,effective_stack_bb:stack,spot});
      key=HeroRanges.contextKey(base);
    }catch(_){
      return {status:'UNSUPPORTED_CONTEXT',context:null,node:null};
    }
    const exact=repo.contexts?.[key];
    if(exact)return {status:'RESOLVED',context:exact.context,node:exact,depth_match:'exact',depth_delta_bb:0,depth_delta_fraction:0};

    // A nearest context is diagnostic only. It must never authorize a
    // compliance verdict unless a future repository version explicitly owns a
    // persisted stack-bucket policy.
    const candidates=comparableContexts(repo,base);
    if(!candidates.length)return {status:'UNCOVERED_CONTEXT',context:base,node:null};
    const best=candidates[0];
    return {status:'UNCOVERED_DEPTH',context:base,node:null,nearest_context:best.context,depth_delta_bb:best.abs,depth_delta_fraction:best.rel};
  }

  const STRATEGY_SOURCE=Object.freeze({POPULATION:'POPULATION',PERSONAL_OVERRIDE:'PERSONAL_OVERRIDE',NONE:'NONE'});

  function text(value){return value==null?'':String(value).trim();}
  function isObject(value){return !!value&&typeof value==='object'&&!Array.isArray(value);}

  function contextLayers(node,hand){
    const personal=node?.layers?.personal?.hands?.[hand]||null;
    const calculated=node?.layers?.calculated?.hands?.[hand]||null;
    return {
      personal:personal?{strategy:personal,layer:'personal',version:node.layers.personal.version??null,provenance:node.layers.personal.provenance??null}:null,
      calculated:calculated?{strategy:calculated,layer:'calculated',version:node.layers.calculated.version??null,provenance:node.layers.calculated.provenance??null}:null
    };
  }

  function materializedCalculatedPopulations(repo){
    const populations=[];
    for(const node of Object.values(repo?.contexts||{})){
      const calculated=isObject(node)&&isObject(node.layers)?node.layers.calculated:null;
      if(!isObject(calculated))continue;
      const defined=Object.keys(isObject(calculated.hands)?calculated.hands:{}).length;
      const materialized=defined>0||calculated.version!=null||calculated.provenance!=null;
      if(!materialized)continue;
      const population=isObject(node.context)?text(node.context.population_id):'';
      if(population)populations.push(population);
    }
    return Array.from(new Set(populations));
  }

  // A compliance verdict is only legitimate against the population it was
  // resolved for. If the repository defaults or any materialized calculated
  // context belong to a different population, fail closed instead of reading a
  // foreign strategy. The runtime resolver (#392) is authoritative when it is
  // supplied, but this local guard keeps direct callers honest too.
  function populationCompatibility(repo,requestedPopulation){
    const requested=text(requestedPopulation),defaults=text(repo?.defaults?.population_id);
    if(requested&&defaults&&requested!==defaults)return {compatible:false,status:'POPULATION_INCOMPATIBLE',reason:'REPOSITORY_DEFAULTS_POPULATION_MISMATCH'};
    if(requested){
      const foreign=materializedCalculatedPopulations(repo).filter(population=>population!==requested);
      if(foreign.length)return {compatible:false,status:'POPULATION_INCOMPATIBLE',reason:'CALCULATED_CONTEXT_POPULATION_MISMATCH'};
    }
    return {compatible:true,status:'RESOLVED',reason:null};
  }

  function sizingCompliance(strategy,plannedAction,decision){
    const expected=strategy?.sizings?.[plannedAction]||null;
    if(!expected?.length)return {status:'UNCOVERED',observed_target_total_bb:null,expected:[]};
    const observed=Number(decision?.action_sizing_v1?.target_total_bb);
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

  function evaluateDecision({repo,decision,handClass,populationId=null,strategyResolution=null}={}){
    const repository_token=repositoryVersionToken(repo);
    const resolution=isObject(strategyResolution)?strategyResolution:null;
    const resolutionStatus=resolution?text(resolution.status):null;
    const resolutionSource=resolution?text(resolution.source):null;
    const resolutionFailClosed=resolution?resolution.fail_closed===true:false;
    const requestedPopulation=text(populationId||repo?.defaults?.population_id);
    const population=resolution?text(resolution.population_id||requestedPopulation):requestedPopulation;
    const base={
      schema:SCHEMA,
      repository_token,
      hand_class:String(handClass||''),
      observed_runtime_action:String(decision?.action||''),
      planned_action:null,
      action_probability:null,
      action_status:null,
      sizing:{status:'NOT_APPLICABLE',expected:[]},
      resolved_context:null,
      context_status:null,
      layer:null,
      layer_version:null,
      provenance:null,
      population_id:population||null,
      strategy_source:STRATEGY_SOURCE.NONE,
      strategy_status:resolutionStatus,
      strategy_fail_closed:resolutionFailClosed,
      personal_override:false,
      ev_deviation_bb:null,
      ev_status:'NOT_EVALUATED',
      frequency_calibration_status:'NOT_EVALUATED_PER_SINGLE_DECISION'
    };
    if(!HeroRanges||!repo||repo.schema!==HeroRanges.SCHEMA)return {...base,context_status:'NO_REPOSITORY',action_status:'NO_VERDICT',editor_href:'./hero-ranges.html'};
    if(!HeroRanges.HAND_CLASSES.includes(base.hand_class))return {...base,context_status:'UNKNOWN_HAND',action_status:'NO_VERDICT',editor_href:'./hero-ranges.html'};

    // A mismatching population is a hard boundary: no context may be read from
    // another population's strategy, not even to score a personal overlay.
    if(resolution&&resolutionStatus==='POPULATION_INCOMPATIBLE'){
      return {...base,context_status:'POPULATION_INCOMPATIBLE',action_status:'NO_VERDICT',strategy_source:STRATEGY_SOURCE.NONE,editor_href:'./hero-ranges.html'};
    }
    const compatibility=populationCompatibility(repo,population);
    if(!compatibility.compatible){
      return {...base,context_status:compatibility.status,action_status:'NO_VERDICT',strategy_source:STRATEGY_SOURCE.NONE,strategy_reason:compatibility.reason,editor_href:'./hero-ranges.html'};
    }

    // Only an explicitly admitted, fully-covered calculated strategy authorizes
    // a population verdict (#201/#305/#196). Retained references, partial
    // coverage and unresolved artifacts never do. Without a resolution, legacy
    // direct callers keep the local compatibility guarantee above.
    const populationAuthorized=resolution
      ?(resolutionSource===STRATEGY_SOURCE.POPULATION&&resolutionStatus==='ADMISSIBLE_CALCULATED'&&!resolutionFailClosed)
      :true;

    const resolved=resolveContext(repo,decision,{populationId:population});
    if(resolved.status!=='RESOLVED')return {...base,context_status:resolved.status,resolved_context:resolved.context||null,nearest_context:resolved.nearest_context||null,depth_delta_bb:resolved.depth_delta_bb??null,action_status:'NO_VERDICT',editor_href:editorHref({...base,resolved_context:resolved.context||null})};

    const planned=plannedActionForDecision(decision);
    const layers=contextLayers(resolved.node,base.hand_class);
    const personalAvailable=!!layers.personal;
    let selected=null,effectiveSource=STRATEGY_SOURCE.NONE;
    if(populationAuthorized&&layers.calculated){selected=layers.calculated;effectiveSource=STRATEGY_SOURCE.POPULATION;}
    else if(layers.personal){selected=layers.personal;effectiveSource=STRATEGY_SOURCE.PERSONAL_OVERRIDE;}
    const strategySource=selected?effectiveSource:(personalAvailable?STRATEGY_SOURCE.PERSONAL_OVERRIDE:STRATEGY_SOURCE.NONE);
    const common={
      ...base,
      context_status:'RESOLVED',
      resolved_context:resolved.context,
      depth_match:resolved.depth_match,
      depth_delta_bb:resolved.depth_delta_bb,
      layer:selected?selected.layer:null,
      layer_version:selected?selected.version:null,
      provenance:selected?selected.provenance:null,
      planned_action:planned,
      strategy_source:strategySource,
      personal_override:personalAvailable
    };
    if(!selected){
      if(!populationAuthorized&&resolution&&resolutionSource===STRATEGY_SOURCE.POPULATION){
        return {...common,context_status:'STRATEGY_UNAVAILABLE',action_status:'NO_VERDICT',strategy_source:STRATEGY_SOURCE.POPULATION,editor_href:editorHref({...common,hand_class:base.hand_class})};
      }
      if(!populationAuthorized&&resolution&&resolutionSource===STRATEGY_SOURCE.NONE){
        return {...common,context_status:'STRATEGY_UNAVAILABLE',action_status:'NO_VERDICT',strategy_source:STRATEGY_SOURCE.NONE,editor_href:editorHref({...common,hand_class:base.hand_class})};
      }
      return {...common,action_status:'UNCOVERED_HAND',editor_href:editorHref({...common,hand_class:base.hand_class})};
    }
    if(!planned||!HeroRanges.ACTIONS.includes(planned))return {...common,action_status:'UNKNOWN_ACTION',editor_href:editorHref({...common,hand_class:base.hand_class})};
    const strategy=selected.strategy;
    const probability=Number(strategy.actions?.[planned]||0);
    const actionStatus=probability>1e-12?(probability<1-1e-12?'MIXED_ALLOWED':'COMPLIANT'):'OUT_OF_RANGE';
    const aggressive=['OPEN','ISO','3BET','4BET','SHOVE'].includes(planned);
    const sizing=aggressive&&probability>1e-12?sizingCompliance(strategy,planned,decision):{status:'NOT_APPLICABLE',expected:[]};
    const result={...common,action_probability:probability,action_status:actionStatus,sizing,notes:String(strategy.notes||'')};
    result.editor_href=editorHref(result);
    return result;
  }

  function summarize(results){
    const rows=(results||[]).filter(Boolean),groups={};
    let judged=0,allowed=0,out=0,uncovered=0,sizingOut=0;
    for(const r of rows){
      const judgedStatus=['COMPLIANT','MIXED_ALLOWED','OUT_OF_RANGE'].includes(r.action_status);
      if(judgedStatus){judged++;if(r.action_status==='OUT_OF_RANGE')out++;else allowed++;}else uncovered++;
      if(r.sizing?.status==='OUT_OF_RANGE')sizingOut++;
      const c=r.resolved_context,key=c?`${c.position}|${c.spot}`:'UNRESOLVED';
      const g=groups[key]||(groups[key]={key,position:c?.position||null,spot:c?.spot||null,decisions:0,judged:0,allowed:0,out_of_range:0,uncovered:0,sizing_out_of_range:0});
      g.decisions++;
      if(judgedStatus){g.judged++;if(r.action_status==='OUT_OF_RANGE')g.out_of_range++;else g.allowed++;}else g.uncovered++;
      if(r.sizing?.status==='OUT_OF_RANGE')g.sizing_out_of_range++;
    }
    return {
      schema:'poker-hero-range-compliance-summary/v1',
      repository_token:rows.find(r=>r.repository_token)?.repository_token||null,
      decisions:rows.length,
      judged,
      allowed,
      out_of_range:out,
      uncovered,
      sizing_out_of_range:sizingOut,
      frequency_calibration_status:'NOT_EVALUATED_PER_SINGLE_HAND',
      groups:Object.values(groups)
    };
  }

  return {SCHEMA,STRATEGY_SOURCE,repositoryVersionToken,spotForDecision,plannedActionForDecision,effectiveStackForDecision,resolveContext,populationCompatibility,evaluateDecision,summarize,editorHref};
});
