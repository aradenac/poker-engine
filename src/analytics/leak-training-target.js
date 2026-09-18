(function(root,factory){
  const Leak=(typeof module==='object'&&module.exports)?require('./leak-analyzer.js'):(root&&root.PokerLeakAnalyzer);
  const api=factory(Leak);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerLeakTrainingTarget=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(Leak){
  'use strict';

  const TARGET_SCHEMA='poker-leak-training-target/v1';
  const CRITERIA_SCHEMA='poker-training-scenario-criteria/v1';
  const SESSION_SCHEMA='poker-leak-training-session-summary/v1';
  const SCENARIO_SCHEMA='poker-training-scenario-descriptor/v1';
  const TARGET_DIMENSIONS=['position','street','spot_family','action_pair','error_type','jam','overbet'];

  function text(v){return v==null?'':String(v).trim();}
  function upper(v){return text(v).toUpperCase();}
  function required(v,name){const s=text(v);if(!s)throw new Error(name+' is required');return s;}
  function int(v,name,min=0){const n=Number(v);if(!Number.isInteger(n)||n<min)throw new Error(name+' must be an integer >= '+min);return n;}
  function optionalBool(v){return v==null?null:Boolean(v);}
  function round(v){return Math.round((Number(v)+Number.EPSILON)*1e9)/1e9;}
  function hash(s){let h=2166136261>>>0;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)>>>0;}return h.toString(36);}
  function stableStringify(v){
    if(v===null||typeof v!=='object')return JSON.stringify(v);
    if(Array.isArray(v))return '['+v.map(stableStringify).join(',')+']';
    return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+stableStringify(v[k])).join(',')+'}';
  }
  function identity(input={}){
    return {
      population_id:required(input.population_id,'identity.population_id'),
      pack_id:text(input.pack_id)||null,
      strategy_id:required(input.strategy_id,'identity.strategy_id'),
      strategy_version:required(input.strategy_version,'identity.strategy_version'),
      ev_reference:required(input.ev_reference,'identity.ev_reference')
    };
  }
  function context(input={}){
    return {
      position:upper(input.position)||null,
      street:upper(input.street)||null,
      spot_family:upper(input.spot_family)||null
    };
  }
  function sourcePattern(input={}){
    return {
      played_action:upper(input.played_action)||null,
      recommended_action:upper(input.recommended_action)||null,
      sizing_error:optionalBool(input.sizing_error),
      jam:optionalBool(input.jam),
      overbet:optionalBool(input.overbet)
    };
  }
  function normalizeRefs(refs){
    const out=[],seen=new Set();
    for(const r of Array.isArray(refs)?refs:[]){
      const h=text(r&&r.hand_id),d=text(r&&r.decision_id);if(!h||!d)continue;
      const k=h+'\u0000'+d;if(seen.has(k))continue;seen.add(k);out.push({hand_id:h,decision_id:d});
    }
    return out.sort((a,b)=>a.hand_id.localeCompare(b.hand_id)||a.decision_id.localeCompare(b.decision_id));
  }
  function buildTrainingTarget(input={}){
    if(input.schema&&input.schema!==TARGET_SCHEMA)throw new Error('expected '+TARGET_SCHEMA);
    const id=identity(input.identity||input);
    const ctx=context(input.context||input);
    const pattern=sourcePattern(input.source_pattern||input);
    const source=input.source_leak||{};
    const dimension=required(source.dimension||input.dimension,'source_leak.dimension');
    if(!TARGET_DIMENSIONS.includes(dimension))throw new Error('unsupported source_leak.dimension '+dimension);
    const key=required(source.key||input.key,'source_leak.key');
    const sourceDecisions=int(source.decisions==null?0:source.decisions,'source_leak.decisions',0);
    const minimumDecisions=int(input.minimum_support&&input.minimum_support.decisions==null?1:input.minimum_support&&input.minimum_support.decisions,'minimum_support.decisions',1);
    const minimumScenarios=int(input.minimum_support&&input.minimum_support.scenarios==null?1:input.minimum_support&&input.minimum_support.scenarios,'minimum_support.scenarios',1);
    const refs=normalizeRefs(source.source_refs||input.source_refs);
    const payload={identity:id,context:ctx,source_pattern:pattern,source_leak:{dimension,key},minimum_support:{decisions:minimumDecisions,scenarios:minimumScenarios}};
    const target_id=text(input.target_id)||('leak-target:'+hash(stableStringify(payload)));
    return {
      schema:TARGET_SCHEMA,target_id,identity:id,context:ctx,source_pattern:pattern,
      source_leak:{dimension,key,decisions:sourceDecisions,total_loss_bb:Number.isFinite(Number(source.total_loss_bb))?round(source.total_loss_bb):null,
        frequency_pct:Number.isFinite(Number(source.frequency_pct))?round(source.frequency_pct):null,source_refs:refs},
      minimum_support:{decisions:minimumDecisions,scenarios:minimumScenarios},
      source_support:{observed_decisions:sourceDecisions,sufficient:sourceDecisions>=minimumDecisions},
      semantics:{
        source_played_action_is_diagnostic:true,
        generated_scenarios_must_not_require_repeating_source_mistake:true,
        delta_ev_reference:id.ev_reference
      }
    };
  }

  function lookupEvent(report,ref){
    return (report.decision_events||[]).find(e=>String(e.hand_id)===String(ref.hand_id)&&String(e.decision_id)===String(ref.decision_id))||null;
  }
  function unanimous(events,getter){
    const vals=events.map(getter).filter(v=>v!==null&&v!==undefined&&String(v)!=='');
    if(!vals.length)return null;const first=String(vals[0]);return vals.every(v=>String(v)===first)?vals[0]:null;
  }
  function resolveGroup(report,dimension,key){
    if(dimension==='jam'){
      const g=report.leaks&&report.leaks.aggressive_sizing&&report.leaks.aggressive_sizing.jam;
      if(g&&(key==='JAM'||key===g.key))return g;
    }
    if(dimension==='overbet'){
      const g=report.leaks&&report.leaks.aggressive_sizing&&report.leaks.aggressive_sizing.overbet;
      if(g&&(key==='OVERBET'||key===g.key))return g;
    }
    const rows=report.leaks&&report.leaks.by&&report.leaks.by[dimension];
    return Array.isArray(rows)?rows.find(x=>String(x.key)===String(key))||null:null;
  }
  function targetFromLeakReport(report,options={}){
    if(!Leak||report&&report.schema!==Leak.REPORT_SCHEMA)throw new Error('expected '+(Leak&&Leak.REPORT_SCHEMA||'poker-leak-analysis/v1'));
    const dimension=required(options.dimension,'dimension'),key=required(options.key,'key');
    if(!TARGET_DIMENSIONS.includes(dimension))throw new Error('unsupported dimension '+dimension);
    const group=resolveGroup(report,dimension,key);if(!group)throw new Error('leak group not found: '+dimension+' '+key);
    const refs=normalizeRefs(group.source_refs),events=refs.map(r=>lookupEvent(report,r)).filter(Boolean);
    const ctx={
      position:dimension==='position'?key:unanimous(events,e=>e.context&&e.context.position),
      street:dimension==='street'?key:unanimous(events,e=>e.context&&e.context.street),
      spot_family:dimension==='spot_family'?key:unanimous(events,e=>e.context&&e.context.spot_family)
    };
    let played=unanimous(events,e=>e.played&&e.played.action),recommended=unanimous(events,e=>e.recommended&&e.recommended.action);
    if(dimension==='action_pair'){
      const parts=String(key).split('->');if(parts.length===2){played=parts[0];recommended=parts[1];}
    }
    const sizing=dimension==='error_type'&&String(key)==='SIZING_ERROR'?true:(events.length&&events.every(e=>e.sizing_error===true)?true:null);
    const jam=dimension==='jam'?true:(events.length&&events.every(e=>e.tags&&e.tags.jam===true)?true:null);
    const overbet=dimension==='overbet'?true:(events.length&&events.every(e=>e.tags&&e.tags.overbet===true)?true:null);
    return buildTrainingTarget({
      identity:report.scope,context:ctx,source_pattern:{played_action:played,recommended_action:recommended,sizing_error:sizing,jam,overbet},
      source_leak:{dimension,key,decisions:group.decisions,total_loss_bb:group.total_loss_bb,frequency_pct:group.frequency_pct,source_refs:refs},
      minimum_support:{decisions:options.minimum_decisions==null?1:options.minimum_decisions,scenarios:options.minimum_scenarios==null?1:options.minimum_scenarios}
    });
  }

  function compileScenarioCriteria(targetInput){
    const target=targetInput&&targetInput.schema===TARGET_SCHEMA?targetInput:buildTrainingTarget(targetInput);
    const criteria={
      schema:CRITERIA_SCHEMA,target_id:target.target_id,identity:{...target.identity},context:{...target.context},
      policy:{recommended_action:target.source_pattern.recommended_action},
      focus:{
        source_played_action:target.source_pattern.played_action,
        sizing_decision:target.source_pattern.sizing_error===true?true:null,
        jam_available:target.source_pattern.jam===true?true:null,
        overbet_available:target.source_pattern.overbet===true?true:null
      },
      coverage:{require_supported:true,minimum_matching_scenarios:target.minimum_support.scenarios},
      notes:['source_played_action is diagnostic context only and is never required as the player action in generated scenarios']
    };
    criteria.criteria_id='scenario-criteria:'+hash(stableStringify(criteria));
    return criteria;
  }
  function sameIfSet(expected,actual,normalizer=text){return expected==null||expected===''||normalizer(actual)===normalizer(expected);}
  function scenarioMatchesCriteria(scenario={},criteriaInput){
    const c=criteriaInput&&criteriaInput.schema===CRITERIA_SCHEMA?criteriaInput:compileScenarioCriteria(criteriaInput);
    if(c.coverage.require_supported&&scenario.supported===false)return false;
    const si=scenario.identity||scenario,sc=scenario.context||scenario,sp=scenario.policy||scenario,sf=scenario.focus||scenario.capabilities||scenario;
    for(const k of ['population_id','pack_id','strategy_id','strategy_version','ev_reference'])if(!sameIfSet(c.identity[k],si[k],text))return false;
    for(const k of ['position','street','spot_family'])if(!sameIfSet(c.context[k],sc[k],upper))return false;
    if(!sameIfSet(c.policy.recommended_action,sp.recommended_action,upper))return false;
    for(const k of ['sizing_decision','jam_available','overbet_available'])if(c.focus[k]===true&&sf[k]!==true)return false;
    return true;
  }
  function evaluateScenarioCoverage(target,scenarios=[]){
    const criteria=compileScenarioCriteria(target),all=Array.isArray(scenarios)?scenarios:[],matching=all.filter(s=>scenarioMatchesCriteria(s,criteria));
    const supported=matching.filter(s=>s.supported!==false);
    return {
      target_id:criteria.target_id,criteria_id:criteria.criteria_id,total_scenarios:all.length,matching_scenarios:matching.length,
      supported_matching_scenarios:supported.length,minimum_required:criteria.coverage.minimum_matching_scenarios,
      sufficient:supported.length>=criteria.coverage.minimum_matching_scenarios,
      fallback:supported.length>=criteria.coverage.minimum_matching_scenarios?null:'INSUFFICIENT_SUPPORTED_SCENARIOS'
    };
  }

  function eventIdentity(e){return {population_id:e.population_id,pack_id:e.pack_id,strategy_id:e.strategy_id,strategy_version:e.strategy_version,ev_reference:e.ev_reference};}
  function eventMatchesTarget(event,targetInput){
    const e=Leak.normalizeEvent(event),t=targetInput&&targetInput.schema===TARGET_SCHEMA?targetInput:buildTrainingTarget(targetInput);
    for(const k of ['population_id','pack_id','strategy_id','strategy_version','ev_reference'])if(!sameIfSet(t.identity[k],eventIdentity(e)[k],text))return false;
    if(!sameIfSet(t.context.position,e.context.position,upper)||!sameIfSet(t.context.street,e.context.street,upper)||!sameIfSet(t.context.spot_family,e.context.spot_family,upper))return false;
    if(!sameIfSet(t.source_pattern.recommended_action,e.recommended.action,upper))return false;
    return true;
  }
  function averageLoss(rows){return rows.length?round(rows.reduce((s,e)=>s+e.ev.attributed_loss_bb,0)/rows.length):null;}
  function summarizeTargetedSession(targetInput,inputEvents,options={}){
    if(!Leak)throw new Error('PokerLeakAnalyzer is required');
    const target=targetInput&&targetInput.schema===TARGET_SCHEMA?targetInput:buildTrainingTarget(targetInput);
    const events=(Array.isArray(inputEvents)?inputEvents:[]).map(Leak.normalizeEvent).filter(e=>eventMatchesTarget(e,target));
    const eligible=events.filter(e=>e.support.covered&&e.comparability.comparable);
    const contributing=eligible.filter(e=>e.ev.attributed_loss_bb>0);
    const total=round(eligible.reduce((s,e)=>s+e.ev.attributed_loss_bb,0)),nominal=round(eligible.reduce((s,e)=>s+e.ev.nominal_loss_bb,0));
    const withinNoise=eligible.filter(e=>e.within_noise).length;
    const minTrend=int(options.minimum_trend_decisions==null?10:options.minimum_trend_decisions,'minimum_trend_decisions',2);
    const ordered=[...eligible].sort((a,b)=>Date.parse(a.timestamp)-Date.parse(b.timestamp)||a.decision_id.localeCompare(b.decision_id));
    let withinSessionChange=null;
    if(ordered.length>=minTrend){
      const cut=Math.floor(ordered.length/2),first=ordered.slice(0,cut),second=ordered.slice(cut);
      const a=averageLoss(first),b=averageLoss(second);
      withinSessionChange={first_segment_decisions:first.length,second_segment_decisions:second.length,first_segment_avg_loss_bb:a,second_segment_avg_loss_bb:b,
        delta_avg_loss_bb:round(b-a),interpretation:'DESCRIPTIVE_WITHIN_SESSION_ONLY'};
    }
    const repeatSourceAction=target.source_pattern.played_action?eligible.filter(e=>upper(e.played.action)===upper(target.source_pattern.played_action)).length:null;
    const sizingErrors=eligible.filter(e=>e.sizing_error).length,jams=eligible.filter(e=>e.tags.jam).length,overbets=eligible.filter(e=>e.tags.overbet).length;
    return {
      schema:SESSION_SCHEMA,target_id:target.target_id,identity:{...target.identity},context:{...target.context},
      summary:{
        decisions_matching_context:events.length,decisions_eligible:eligible.length,decisions_contributing:contributing.length,
        total_delta_ev_loss_bb:total,nominal_delta_ev_loss_bb:nominal,average_delta_ev_loss_bb:averageLoss(eligible),
        loss_bb_per_100_decisions:eligible.length?round(total*100/eligible.length):null,
        within_noise_decisions:withinNoise,unsupported_decisions:events.filter(e=>!e.support.covered).length,
        non_comparable_decisions:events.filter(e=>e.support.covered&&!e.comparability.comparable).length,
        source_played_action_recurrences:repeatSourceAction,sizing_errors:sizingErrors,jams,overbets,
        within_session_change:withinSessionChange,
        within_session_change_reason:withinSessionChange?null:'INSUFFICIENT_SAMPLE_FOR_WITHIN_SESSION_CHANGE'
      },
      source_refs:eligible.map(e=>({hand_id:e.hand_id,decision_id:e.decision_id}))
    };
  }

  return {TARGET_SCHEMA,CRITERIA_SCHEMA,SESSION_SCHEMA,SCENARIO_SCHEMA,TARGET_DIMENSIONS,buildTrainingTarget,targetFromLeakReport,
    compileScenarioCriteria,scenarioMatchesCriteria,evaluateScenarioCoverage,eventMatchesTarget,summarizeTargetedSession};
});
