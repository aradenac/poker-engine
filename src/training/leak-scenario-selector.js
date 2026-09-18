(function(root,factory){
  const Target=(typeof module==='object'&&module.exports)?require('../analytics/leak-training-target.js'):(root&&root.PokerLeakTrainingTarget);
  const api=factory(Target);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerLeakScenarioSelector=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(Target){
  'use strict';

  const PLAN_SCHEMA='poker-leak-training-session-plan/v1';
  const PLAN_ITEM_SCHEMA='poker-leak-training-session-plan-item/v1';
  const RUNTIME_SUMMARY_SCHEMA='poker-leak-training-runtime-summary/v1';
  const FALLBACK='INSUFFICIENT_SUPPORTED_SCENARIOS';
  const IDENTITY_FIELDS=['population_id','pack_id','strategy_id','strategy_version','ev_reference'];
  const EPS=1e-9;

  function text(v){return v==null?'':String(v).trim();}
  function upper(v){return text(v).toUpperCase();}
  function positiveInt(v,name,def){
    if(v==null||v==='')return def;
    const n=Number(v);if(!Number.isInteger(n)||n<1)throw new Error(name+' must be an integer >= 1');return n;
  }
  function nonNegativeInt(v,name,def=0){
    if(v==null||v==='')return def;
    const n=Number(v);if(!Number.isInteger(n)||n<0)throw new Error(name+' must be a non-negative integer');return n;
  }
  function round(v){return Math.round((Number(v)+Number.EPSILON)*1e9)/1e9;}
  function stableStringify(v){
    if(v===null||typeof v!=='object')return JSON.stringify(v);
    if(Array.isArray(v))return '['+v.map(stableStringify).join(',')+']';
    return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+stableStringify(v[k])).join(',')+'}';
  }
  function hash32(s){
    let h=2166136261>>>0;
    for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)>>>0;}
    return h>>>0;
  }
  function hashId(prefix,value){return prefix+hash32(value).toString(36);}
  function sameIdentity(a={},b={}){
    return IDENTITY_FIELDS.every(k=>String(a[k]==null?'':a[k])===String(b[k]==null?'':b[k]));
  }
  function exactIdentity(input={}){
    const out={};
    for(const k of IDENTITY_FIELDS){
      if(k==='pack_id'){out[k]=text(input[k])||null;continue;}
      const v=text(input[k]);if(!v)throw new Error('identity.'+k+' is required');out[k]=v;
    }
    return out;
  }
  function scenarioId(s){
    const explicit=text(s&&s.scenario_id);if(explicit)return explicit;
    const basis={
      identity:s&&s.identity||null,context:s&&s.context||null,policy:s&&s.policy||null,
      focus:s&&s.focus||s&&s.capabilities||null,diversity_key:s&&s.diversity_key||null,
      payload_key:s&&s.payload_key||null
    };
    return hashId('scenario:auto:',stableStringify(basis));
  }
  function scenarioIdentity(s){return exactIdentity((s&&s.identity)||s||{});}
  function normalizeSupport(s={},minimumObservations=0){
    const support=s.support&&typeof s.support==='object'?s.support:{};
    const coverage=s.coverage&&typeof s.coverage==='object'?s.coverage:{};
    const covered=s.supported!==false&&support.covered!==false&&coverage.covered!==false&&coverage.supported!==false;
    const observations=support.observations==null?coverage.observations:support.observations;
    const n=observations==null?null:Number(observations);
    const observationCount=Number.isInteger(n)&&n>=0?n:null;
    let sufficient=covered,reason=null;
    if(!covered){sufficient=false;reason=text(support.reason)||text(coverage.reason)||'UNSUPPORTED';}
    else if(minimumObservations>0&&observationCount==null){sufficient=false;reason='MISSING_SUPPORT_OBSERVATIONS';}
    else if(minimumObservations>0&&observationCount<minimumObservations){sufficient=false;reason='LOW_SUPPORT_OBSERVATIONS';}
    return {covered,observations:observationCount,minimum_observations:minimumObservations,sufficient,reason};
  }
  function scenarioContext(s){return (s&&s.context)||s||{};}
  function scenarioPolicy(s){return (s&&s.policy)||s||{};}
  function scenarioFocus(s){return (s&&s.focus)||(s&&s.capabilities)||s||{};}
  function diversityKey(s,id){
    const explicit=text(s&&s.diversity_key)||text(s&&s.hand_key)||text(s&&s.variant_key);
    if(explicit)return explicit;
    const c=scenarioContext(s),p=scenarioPolicy(s),f=scenarioFocus(s);
    const basis={
      position:upper(c.position),street:upper(c.street),spot_family:upper(c.spot_family),
      recommended_action:upper(p.recommended_action),
      sizing_decision:Boolean(f.sizing_decision),jam_available:Boolean(f.jam_available),overbet_available:Boolean(f.overbet_available),
      hand_class:text(s&&s.hand_class)||null,board_class:text(s&&s.board_class)||null
    };
    const generic=stableStringify(basis);
    return generic==='{}'?id:hashId('diversity:',generic);
  }
  function compareExpected(expected,actual,normalizer=text){return expected==null||expected===''||normalizer(expected)===normalizer(actual);}
  function rejectionReasons(s,target,criteria,support){
    const reasons=[];
    let sid;
    try{sid=scenarioIdentity(s);}catch(_){reasons.push('INVALID_IDENTITY');sid=null;}
    if(sid){
      const labels={
        population_id:'POPULATION_MISMATCH',pack_id:'PACK_MISMATCH',strategy_id:'STRATEGY_MISMATCH',
        strategy_version:'STRATEGY_VERSION_MISMATCH',ev_reference:'EV_REFERENCE_MISMATCH'
      };
      for(const k of IDENTITY_FIELDS)if(String(sid[k]==null?'':sid[k])!==String(target.identity[k]==null?'':target.identity[k]))reasons.push(labels[k]);
    }
    const c=scenarioContext(s),p=scenarioPolicy(s),f=scenarioFocus(s);
    if(!compareExpected(criteria.context.position,c.position,upper))reasons.push('POSITION_MISMATCH');
    if(!compareExpected(criteria.context.street,c.street,upper))reasons.push('STREET_MISMATCH');
    if(!compareExpected(criteria.context.spot_family,c.spot_family,upper))reasons.push('SPOT_FAMILY_MISMATCH');
    if(!compareExpected(criteria.policy.recommended_action,p.recommended_action,upper))reasons.push('RECOMMENDED_ACTION_MISMATCH');
    if(criteria.focus.sizing_decision===true&&f.sizing_decision!==true)reasons.push('SIZING_FOCUS_MISMATCH');
    if(criteria.focus.jam_available===true&&f.jam_available!==true)reasons.push('JAM_FOCUS_MISMATCH');
    if(criteria.focus.overbet_available===true&&f.overbet_available!==true)reasons.push('OVERBET_FOCUS_MISMATCH');
    if(!support.sufficient)reasons.push(support.reason||'UNSUPPORTED');
    return Array.from(new Set(reasons)).sort();
  }
  function normalizeCandidate(s,index,minimumObservations){
    const id=scenarioId(s),support=normalizeSupport(s,minimumObservations);
    return {
      scenario_id:id,
      original_index:index,
      identity:(()=>{try{return scenarioIdentity(s);}catch(_){return null;}})(),
      context:{...scenarioContext(s)},
      policy:{...scenarioPolicy(s)},
      focus:{...scenarioFocus(s)},
      support,
      diversity_key:diversityKey(s,id),
      raw:s
    };
  }
  function deduplicate(candidates){
    const groups=new Map();
    for(const row of candidates){
      if(!groups.has(row.scenario_id))groups.set(row.scenario_id,[]);
      groups.get(row.scenario_id).push(row);
    }
    const unique=[],duplicates=[];
    for(const [id,rows] of Array.from(groups.entries()).sort((a,b)=>a[0].localeCompare(b[0]))){
      const sorted=[...rows].sort((a,b)=>stableStringify(a.raw).localeCompare(stableStringify(b.raw))||a.original_index-b.original_index);
      unique.push(sorted[0]);
      for(const row of sorted.slice(1))duplicates.push({scenario_id:id,reasons:['DUPLICATE_SCENARIO'],support_reason:null});
    }
    return {unique,duplicates};
  }
  function deterministicOrder(rows,seed){
    const groups=new Map();
    for(const row of rows){
      if(!groups.has(row.diversity_key))groups.set(row.diversity_key,[]);
      groups.get(row.diversity_key).push(row);
    }
    const groupRows=Array.from(groups.entries()).map(([key,items])=>({
      key,
      score:hash32(String(seed)+'|group|'+key),
      items:[...items].sort((a,b)=>{
        const ha=hash32(String(seed)+'|scenario|'+a.scenario_id),hb=hash32(String(seed)+'|scenario|'+b.scenario_id);
        return ha-hb||a.scenario_id.localeCompare(b.scenario_id);
      })
    })).sort((a,b)=>a.score-b.score||a.key.localeCompare(b.key));
    const out=[];
    let remaining=true,roundIndex=0;
    while(remaining){
      remaining=false;
      for(const g of groupRows){
        if(roundIndex<g.items.length){out.push(g.items[roundIndex]);remaining=true;}
      }
      roundIndex++;
    }
    return out;
  }
  function criteriaSnapshot(criteria){
    return {
      identity:{...criteria.identity},
      context:{...criteria.context},
      policy:{...criteria.policy},
      focus:{...criteria.focus},
      coverage:{...criteria.coverage},
      source_played_action_diagnostic_only:true
    };
  }
  function reasonCounts(rejected){
    const out={};
    for(const r of rejected)for(const reason of r.reasons)out[reason]=(out[reason]||0)+1;
    return Object.fromEntries(Object.entries(out).sort((a,b)=>a[0].localeCompare(b[0])));
  }

  function buildSessionPlan(targetInput,pool=[],options={}){
    if(!Target)throw new Error('PokerLeakTrainingTarget is required');
    const target=targetInput&&targetInput.schema===Target.TARGET_SCHEMA?targetInput:Target.buildTrainingTarget(targetInput);
    const criteria=Target.compileScenarioCriteria(target);
    const runtimeIdentity=options.identity?exactIdentity(options.identity):{...target.identity};
    if(!sameIdentity(runtimeIdentity,target.identity))throw new Error('runtime identity does not match target identity');

    const requestedSize=positiveInt(options.session_size,'session_size',Math.max(1,target.minimum_support.scenarios));
    const minimumObservations=nonNegativeInt(options.minimum_observations_per_scenario,'minimum_observations_per_scenario',0);
    const seed=text(options.seed)||target.target_id;
    const candidates=(Array.isArray(pool)?pool:[]).map((s,i)=>normalizeCandidate(s,i,minimumObservations));
    const dedup=deduplicate(candidates),accepted=[],rejected=[...dedup.duplicates];

    for(const row of dedup.unique){
      const reasons=rejectionReasons(row.raw,target,criteria,row.support);
      if(reasons.length)rejected.push({scenario_id:row.scenario_id,reasons,support_reason:row.support.reason});
      else accepted.push(row);
    }
    rejected.sort((a,b)=>a.scenario_id.localeCompare(b.scenario_id)||a.reasons.join('|').localeCompare(b.reasons.join('|')));

    const ordered=deterministicOrder(accepted,seed);
    const minimumRequired=Math.max(target.minimum_support.scenarios,requestedSize);
    const sufficient=ordered.length>=minimumRequired;
    const selected=sufficient?ordered.slice(0,requestedSize):[];
    const fallback=sufficient?null:FALLBACK;
    const poolCount=candidates.length,uniqueCount=dedup.unique.length;
    const supportedUnique=dedup.unique.filter(x=>x.support.sufficient).length;
    const matchedSupported=accepted.length;
    const planId=hashId('leak-session-plan:',stableStringify({
      target_id:target.target_id,criteria_id:criteria.criteria_id,seed,requested_size:requestedSize,
      selected:selected.map(x=>x.scenario_id)
    }));

    return {
      schema:PLAN_SCHEMA,
      plan_id:planId,
      target_id:target.target_id,
      criteria_id:criteria.criteria_id,
      target,
      runtime_identity:runtimeIdentity,
      criteria_applied:criteriaSnapshot(criteria),
      request:{
        session_size:requestedSize,
        seed,
        target_minimum_supported_scenarios:target.minimum_support.scenarios,
        effective_minimum_supported_scenarios:minimumRequired,
        minimum_observations_per_scenario:minimumObservations
      },
      pool:{
        candidates:poolCount,
        unique_candidates:uniqueCount,
        supported_unique:supportedUnique,
        matching_supported:matchedSupported,
        rejected:rejected.length,
        selected:selected.length,
        supported_coverage_pct:uniqueCount?round(supportedUnique*100/uniqueCount):null,
        matching_coverage_pct:uniqueCount?round(matchedSupported*100/uniqueCount):null,
        requested_coverage_pct:requestedSize?round(Math.min(matchedSupported,requestedSize)*100/requestedSize):null,
        rejection_reasons:reasonCounts(rejected)
      },
      rejected,
      selection:selected.map((row,index)=>({
        schema:PLAN_ITEM_SCHEMA,rank:index+1,scenario_id:row.scenario_id,diversity_key:row.diversity_key,
        support:{...row.support},identity:{...row.identity},context:{...row.context},policy:{...row.policy},focus:{...row.focus},
        scenario:row.raw
      })),
      ready:sufficient,
      fallback,
      fallback_detail:sufficient?null:{
        code:FALLBACK,
        matching_supported:matchedSupported,
        required:minimumRequired,
        message:'Targeted session is not executable: the exact requested leak context has insufficient supported scenarios. No alternate spot was selected.'
      }
    };
  }

  function summarizePlannedSession(plan,inputEvents,options={}){
    if(!plan||plan.schema!==PLAN_SCHEMA)throw new Error('expected '+PLAN_SCHEMA);
    const base=Target.summarizeTargetedSession(plan.target,inputEvents,options);
    const matched=(Array.isArray(inputEvents)?inputEvents:[]).filter(e=>{
      try{return Target.eventMatchesTarget(e,plan.target);}catch(_){return false;}
    });
    const spotsPlayed=new Set(matched.map(e=>String(e.hand_id))).size;
    const minimumLongTerm=positiveInt(options.minimum_long_term_spots,'minimum_long_term_spots',50);
    return {
      schema:RUNTIME_SUMMARY_SCHEMA,
      target_id:plan.target_id,
      criteria_id:plan.criteria_id,
      plan_id:plan.plan_id,
      planned_spots:plan.selection.length,
      spots_played:spotsPlayed,
      identity:{...base.identity},
      context:{...base.context},
      summary:{
        covered_comparable:base.summary.decisions_eligible,
        covered_matching:base.summary.decisions_matching_context-base.summary.unsupported_decisions,
        unsupported:base.summary.unsupported_decisions,
        non_comparable:base.summary.non_comparable_decisions,
        within_noise:base.summary.within_noise_decisions,
        total_delta_ev_loss_bb:base.summary.total_delta_ev_loss_bb,
        average_delta_ev_loss_bb:base.summary.average_delta_ev_loss_bb,
        loss_bb_per_100_decisions:base.summary.loss_bb_per_100_decisions,
        decisions_contributing:base.summary.decisions_contributing
      },
      source_refs:[...base.source_refs],
      within_session_change:base.summary.within_session_change,
      long_term_progression:{
        claimed:false,
        minimum_spots_for_any_long_term_assessment:minimumLongTerm,
        sample_sufficient_for_assessment:spotsPlayed>=minimumLongTerm,
        reason:spotsPlayed<minimumLongTerm?'INSUFFICIENT_SAMPLE':'NOT_INFERRED_FROM_SINGLE_SESSION'
      }
    };
  }

  return {PLAN_SCHEMA,PLAN_ITEM_SCHEMA,RUNTIME_SUMMARY_SCHEMA,FALLBACK,buildSessionPlan,summarizePlannedSession};
});
