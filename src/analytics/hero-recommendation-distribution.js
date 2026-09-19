(function(root,factory){
  const Leak=(typeof module==='object'&&module.exports)?require('./leak-analyzer.js'):(root&&root.PokerLeakAnalyzer);
  const api=factory(Leak);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerHeroRecommendationDistribution=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(Leak){
  'use strict';

  const REPORT_SCHEMA='poker-hero-recommendation-distribution/v1';
  const INPUT_SCHEMA='poker-hero-recommendation-observation/v1';
  const CONFIG_SCHEMA='poker-hero-recommendation-distribution-config/v1';
  const CANONICAL_PREFLOP_SCHEMA='poker-preflop-decision/v1';
  const CANONICAL_PREFLOP_PROFILE='CANONICAL_RUNTIME_DECISION_V1';
  const DIMENSIONS=['street','position','spot_family','context','support'];
  const ACTIONS=['FOLD','CHECK','CALL','BET','RAISE','JAM','OTHER'];
  const LOW_SUPPORT_TIERS=new Set(['LOW','SPARSE','UNKNOWN']);
  const EPS=1e-9;

  const DEFAULT_CONFIG=Object.freeze({
    schema:CONFIG_SCHEMA,
    supported_tiers:['MEDIUM','HIGH','VERY_HIGH'],
    large_sizing_pot_ratio:1,
    large_sizing_target_bb:20,
    sizing_buckets:{
      pot_ratio_edges:[0.33,0.66,1,1.5],
      target_bb_edges:[2.5,4,8,20,50]
    },
    ranking_limit:50
  });

  function text(v){return v==null?'':String(v).trim();}
  function upper(v){return text(v).toUpperCase();}
  function finiteOrNull(v){if(v==null||v==='')return null;const n=Number(v);return Number.isFinite(n)?n:null;}
  function round(v){return Math.round((Number(v)+Number.EPSILON)*1e9)/1e9;}
  function clone(v){return v==null?v:JSON.parse(JSON.stringify(v));}
  function stableStringify(v){
    if(v===null||typeof v!=='object')return JSON.stringify(v);
    if(Array.isArray(v))return '['+v.map(stableStringify).join(',')+']';
    return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+stableStringify(v[k])).join(',')+'}';
  }
  function hash32(s){let h=2166136261>>>0;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)>>>0;}return h>>>0;}
  function hashId(prefix,v){return prefix+hash32(stableStringify(v)).toString(36);}
  function uniqueSorted(values){return Array.from(new Set((values||[]).filter(v=>v!=null&&String(v)!==''))).sort((a,b)=>String(a).localeCompare(String(b)));}
  function normalizeRefs(values){
    const map=new Map();
    for(const r of values||[]){
      if(!r||r.hand_id==null||r.decision_id==null)continue;
      const x={hand_id:String(r.hand_id),decision_id:String(r.decision_id)};
      map.set(x.hand_id+'\u0000'+x.decision_id,x);
    }
    return Array.from(map.values()).sort((a,b)=>a.hand_id.localeCompare(b.hand_id)||a.decision_id.localeCompare(b.decision_id));
  }

  function normalizeConfig(input={}){
    const src={...DEFAULT_CONFIG,...(input||{})};
    const sizing={...DEFAULT_CONFIG.sizing_buckets,...(input&&input.sizing_buckets||{})};
    const pot=(sizing.pot_ratio_edges||[]).map(Number);
    const bb=(sizing.target_bb_edges||[]).map(Number);
    if(!pot.length||pot.some((x,i)=>!Number.isFinite(x)||x<0||(i&&x<=pot[i-1])))throw new Error('pot_ratio_edges must be finite, non-negative and strictly increasing');
    if(!bb.length||bb.some((x,i)=>!Number.isFinite(x)||x<0||(i&&x<=bb[i-1])))throw new Error('target_bb_edges must be finite, non-negative and strictly increasing');
    const tiers=uniqueSorted((src.supported_tiers||[]).map(upper));
    if(!tiers.length)throw new Error('supported_tiers must not be empty');
    const largePot=Number(src.large_sizing_pot_ratio),largeBB=Number(src.large_sizing_target_bb),limit=Number(src.ranking_limit);
    if(!Number.isFinite(largePot)||largePot<0)throw new Error('large_sizing_pot_ratio must be >= 0');
    if(!Number.isFinite(largeBB)||largeBB<0)throw new Error('large_sizing_target_bb must be >= 0');
    if(!Number.isInteger(limit)||limit<1)throw new Error('ranking_limit must be >= 1');
    return {
      schema:CONFIG_SCHEMA,
      supported_tiers:tiers,
      large_sizing_pot_ratio:largePot,
      large_sizing_target_bb:largeBB,
      sizing_buckets:{pot_ratio_edges:pot,target_bb_edges:bb},
      ranking_limit:limit
    };
  }

  function actionClass(v){
    const a=upper(v);
    if(a==='FOLD')return 'FOLD';
    if(a==='CHECK')return 'CHECK';
    if(['CALL','LIMP','OVERLIMP','CALL_SHOVE','CALL_JAM','CALL-JAM'].includes(a))return 'CALL';
    if(a==='BET')return 'BET';
    if(['SHOVE','JAM','ALL_IN','ALL-IN'].includes(a))return 'JAM';
    if(['RAISE','OPEN','ISO','SQUEEZE','3BET','4BET','5BET'].includes(a))return 'RAISE';
    return a?'OTHER':'OTHER';
  }
  function exactIdentity(raw={}){
    const out={
      population_id:text(raw.population_id),
      pack_id:text(raw.pack_id)||null,
      pack_version:text(raw.pack_version)||null,
      strategy_id:text(raw.strategy_id),
      strategy_version:text(raw.strategy_version),
      ev_reference:text(raw.ev_reference)
    };
    for(const k of ['population_id','strategy_id','strategy_version','ev_reference'])if(!out[k])throw new Error('identity.'+k+' is required');
    return out;
  }
  function identityKey(x){
    return ['population_id','pack_id','pack_version','strategy_id','strategy_version','ev_reference']
      .map(k=>k+'='+encodeURIComponent(x[k]==null?'':x[k])).join('|');
  }
  function sameIdentity(a,b){
    return identityKey(a)===identityKey(b);
  }
  function sourceGuard(source){
    const s=source&&typeof source==='object'?source:{};
    if(upper(s.split)==='TEST')throw new Error('TEST consumption is forbidden');
    if(Number(s.issue)===108)throw new Error('#108 consumption is forbidden');
    if(s.optimization===true)throw new Error('optimization output is forbidden');
    if(s.promotion===true)throw new Error('promotion output is forbidden');
    return {split:upper(s.split)||null,issue:s.issue==null?null:Number(s.issue),source:text(s.source)||null};
  }
  function recommendedTail(action,ratio,target,config){
    const jam=action==='JAM';
    const overbet=ratio!=null&&ratio>1+EPS;
    const large=(ratio!=null&&ratio+EPS>=config.large_sizing_pot_ratio)||(target!=null&&target+EPS>=config.large_sizing_target_bb);
    return {jam,overbet,large_sizing:large};
  }
  function observedWeight(record,contextId,input){
    let w=finiteOrNull(record.observed_spot_frequency_weight);
    if(w==null&&input&&input.observed_weights_by_context&&contextId!=null)w=finiteOrNull(input.observed_weights_by_context[contextId]);
    if(w!=null&&w<0)throw new Error('observed frequency weight must be >= 0');
    return w;
  }

  function fromCanonical(decision,input){
    if(decision.contract_profile!==CANONICAL_PREFLOP_PROFILE)throw new Error('unsupported preflop decision profile');
    const id=exactIdentity(decision.identity||{});
    const admiss=Boolean(decision.recommendation_admissibility&&decision.recommendation_admissibility.admissible);
    const recAction=admiss?actionClass(decision.recommended_action):null;
    const target=admiss?finiteOrNull(decision.recommended_target_sizing&&decision.recommended_target_sizing.target_total_bb):null;
    const playedTarget=finiteOrNull(decision.played_target_sizing&&decision.played_target_sizing.target_total_bb);
    const contextId=text(decision.context_id)||null;
    const supportTier=upper(decision.support_tier)||'UNKNOWN';
    const coverageState=upper(decision.coverage_state)||'ANALYSIS_MISSING';
    const recRatio=finiteOrNull(decision.recommended_size_pot_ratio);
    const playedRatio=finiteOrNull(decision.played_size_pot_ratio);
    return {
      hand_id:text(decision.hand_id)||null,
      decision_id:text(decision.decision_id),
      identity:id,
      position:upper(decision.hero_position)||'UNKNOWN',
      street:'PREFLOP',
      spot_family:upper(decision.facing_context)||'UNKNOWN',
      context_id:contextId,
      support_tier:supportTier,
      coverage_state:coverageState,
      admissible:admiss,
      admissibility_status:text(decision.recommendation_admissibility&&decision.recommendation_admissibility.status)||null,
      recommendation:admiss?{action:recAction,target_total_bb:target,size_pot_ratio:recRatio}:null,
      played:{action:decision.played_action?actionClass(decision.played_action):null,target_total_bb:playedTarget,size_pot_ratio:playedRatio},
      population_observed:null,
      weight:observedWeight(decision,contextId,input),
      source:sourceGuard(decision.source||{}),
      source_ref:decision.hand_id&&decision.decision_id?{hand_id:String(decision.hand_id),decision_id:String(decision.decision_id)}:null
    };
  }

  function fromObservation(obs,input){
    if(!Leak)throw new Error('PokerLeakAnalyzer is required for decision_event observations');
    const event=Leak.normalizeEvent(obs.decision_event||{});
    const id=exactIdentity(obs.identity||{
      population_id:event.population_id,pack_id:event.pack_id,pack_version:obs.pack_version,
      strategy_id:event.strategy_id,strategy_version:event.strategy_version,ev_reference:event.ev_reference
    });
    const eventId=exactIdentity({
      population_id:event.population_id,pack_id:event.pack_id,pack_version:obs.pack_version,
      strategy_id:event.strategy_id,strategy_version:event.strategy_version,ev_reference:event.ev_reference
    });
    if(!sameIdentity(id,eventId))throw new Error('observation identity does not match decision_event');
    const adm=obs.recommendation_admissibility||{};
    const admiss=adm.admissible===true;
    const coverageState=upper(obs.coverage_state)||(event.support.covered?'COVERED':'UNSUPPORTED');
    const supportTier=upper(obs.support_tier)||'UNKNOWN';
    const contextId=text(event.context.context_id)||null;
    const recAction=admiss?actionClass(event.recommended.action):null;
    const recTarget=admiss?finiteOrNull(event.recommended.target_total_bb):null;
    const recRatio=admiss?finiteOrNull(event.recommended.size_pot_ratio):null;
    const pop=obs.population_observed&&typeof obs.population_observed==='object'?{
      action:obs.population_observed.action?actionClass(obs.population_observed.action):null,
      target_total_bb:finiteOrNull(obs.population_observed.target_total_bb),
      size_pot_ratio:finiteOrNull(obs.population_observed.size_pot_ratio)
    }:null;
    return {
      hand_id:String(event.hand_id),
      decision_id:String(event.decision_id),
      identity:id,
      position:upper(event.context.position)||'UNKNOWN',
      street:upper(event.context.street)||'UNKNOWN',
      spot_family:upper(event.context.spot_family)||'UNKNOWN',
      context_id:contextId,
      support_tier:supportTier,
      coverage_state:coverageState,
      admissible:admiss,
      admissibility_status:text(adm.status)||null,
      recommendation:admiss?{action:recAction,target_total_bb:recTarget,size_pot_ratio:recRatio}:null,
      played:{action:event.played.action?actionClass(event.played.action):null,target_total_bb:finiteOrNull(event.played.target_total_bb),size_pot_ratio:finiteOrNull(event.played.size_pot_ratio)},
      population_observed:pop,
      weight:observedWeight(obs,contextId,input),
      source:sourceGuard(obs.source||{}),
      source_ref:{hand_id:String(event.hand_id),decision_id:String(event.decision_id)}
    };
  }
  function normalizeRecord(record,input){
    if(!record||typeof record!=='object')throw new Error('recommendation record must be an object');
    if(record.schema===CANONICAL_PREFLOP_SCHEMA)return fromCanonical(record,input);
    if(record.schema===INPUT_SCHEMA)return fromObservation(record,input);
    throw new Error('unsupported recommendation record schema');
  }

  function supported(row,config){
    return row.admissible&&row.coverage_state==='COVERED'&&config.supported_tiers.includes(row.support_tier)&&!LOW_SUPPORT_TIERS.has(row.support_tier);
  }
  function sizingBucket(row,config){
    const r=row.recommendation&&row.recommendation.size_pot_ratio;
    const t=row.recommendation&&row.recommendation.target_total_bb;
    if(r!=null){
      const e=config.sizing_buckets.pot_ratio_edges;
      for(let i=0;i<e.length;i++)if(r<=e[i]+EPS)return i===0?'POT_LE_'+e[i]:'POT_'+e[i-1]+'_'+e[i];
      return 'POT_GT_'+e[e.length-1];
    }
    if(t!=null){
      const e=config.sizing_buckets.target_bb_edges;
      for(let i=0;i<e.length;i++)if(t<=e[i]+EPS)return i===0?'TARGET_LE_'+e[i]+'BB':'TARGET_'+e[i-1]+'_'+e[i]+'BB';
      return 'TARGET_GT_'+e[e.length-1]+'BB';
    }
    return 'NO_COMPARABLE_SIZING';
  }

  function exposure(rows,config){
    const admissible=rows.filter(r=>r.admissible);
    const supportedRows=admissible.filter(r=>supported(r,config));
    const failClosed=rows.filter(r=>!r.admissible);
    const uncovered=admissible.filter(r=>r.coverage_state!=='COVERED');
    const low=admissible.filter(r=>r.coverage_state==='COVERED'&&!supported(r,config));
    const weighted=admissible.filter(r=>r.weight!=null);
    return {
      input_decisions:rows.length,
      admissible_recommendations:admissible.length,
      fail_closed_decisions:failClosed.length,
      uncovered_admissible_decisions:uncovered.length,
      low_support_admissible_decisions:low.length,
      supported_recommendations:supportedRows.length,
      weighted_recommendations:weighted.length,
      admissible_ratio:rows.length?round(admissible.length/rows.length):null,
      supported_ratio:admissible.length?round(supportedRows.length/admissible.length):null,
      weighted_coverage_ratio:admissible.length?round(weighted.length/admissible.length):null,
      fail_closed_reasons:Object.fromEntries(uniqueSorted(failClosed.map(r=>r.admissibility_status||'UNKNOWN')).map(reason=>[reason,failClosed.filter(r=>(r.admissibility_status||'UNKNOWN')===reason).length])),
      coverage_states:Object.fromEntries(uniqueSorted(admissible.map(r=>r.coverage_state)).map(state=>[state,admissible.filter(r=>r.coverage_state===state).length])),
      support_tiers:Object.fromEntries(uniqueSorted(admissible.map(r=>r.support_tier)).map(tier=>[tier,admissible.filter(r=>r.support_tier===tier).length]))
    };
  }

  function weightedCount(rows,weightFn){
    return round(rows.reduce((s,r)=>s+Number(weightFn(r)||0),0));
  }
  function actionDistribution(rows,weightFn){
    const total=weightedCount(rows,weightFn),counts={};
    for(const a of ACTIONS)counts[a]=0;
    for(const r of rows){
      const a=r.recommendation?r.recommendation.action:'OTHER';
      counts[ACTIONS.includes(a)?a:'OTHER']+=Number(weightFn(r)||0);
    }
    const out={};
    for(const a of ACTIONS)out[a]={count:round(counts[a]),frequency:total?round(counts[a]/total):0};
    return {total_weight:total,actions:out};
  }
  function sizingDistribution(rows,weightFn,config){
    const groups=new Map(),pot=[],bb=[];
    for(const r of rows){
      const w=Number(weightFn(r)||0),bucket=sizingBucket(r,config);
      groups.set(bucket,(groups.get(bucket)||0)+w);
      const ratio=r.recommendation&&r.recommendation.size_pot_ratio,target=r.recommendation&&r.recommendation.target_total_bb;
      if(ratio!=null)pot.push({v:ratio,w});
      if(target!=null)bb.push({v:target,w});
    }
    const total=weightedCount(rows,weightFn);
    const buckets={};
    for(const k of Array.from(groups.keys()).sort())buckets[k]={count:round(groups.get(k)),frequency:total?round(groups.get(k)/total):0};
    const stats=(values)=>{
      const weight=values.reduce((s,x)=>s+x.w,0);
      if(!weight)return {count:values.length,weighted_mean:null,min:null,max:null};
      return {count:values.length,weighted_mean:round(values.reduce((s,x)=>s+x.v*x.w,0)/weight),min:round(Math.min(...values.map(x=>x.v))),max:round(Math.max(...values.map(x=>x.v)))};
    };
    return {buckets,pot_fraction:stats(pot),target_bb:stats(bb)};
  }
  function tails(rows,weightFn,config){
    let jam=0,overbet=0,large=0,total=0;
    for(const r of rows){
      const w=Number(weightFn(r)||0),rec=r.recommendation||{},t=recommendedTail(rec.action,rec.size_pot_ratio,rec.target_total_bb,config);
      total+=w;if(t.jam)jam+=w;if(t.overbet)overbet+=w;if(t.large_sizing)large+=w;
    }
    return {
      jam:{count:round(jam),frequency:total?round(jam/total):0},
      overbet:{count:round(overbet),frequency:total?round(overbet/total):0},
      large_sizing:{count:round(large),frequency:total?round(large/total):0}
    };
  }
  function playedComparison(rows,weightFn){
    const comparable=rows.filter(r=>r.played&&r.played.action);
    const total=weightedCount(comparable,weightFn);
    const played={};for(const a of ACTIONS)played[a]=0;
    const recommended={};for(const a of ACTIONS)recommended[a]=0;
    for(const r of comparable){
      const w=Number(weightFn(r)||0),pa=ACTIONS.includes(r.played.action)?r.played.action:'OTHER',ra=ACTIONS.includes(r.recommendation.action)?r.recommendation.action:'OTHER';
      played[pa]+=w;recommended[ra]+=w;
    }
    const actions={};
    for(const a of ACTIONS){
      const pf=total?played[a]/total:0,rf=total?recommended[a]/total:0;
      actions[a]={played_frequency:round(pf),recommended_frequency:round(rf),delta:round(rf-pf)};
    }
    const sizingComparable=comparable.filter(r=>{
      const p=r.played||{},q=r.recommendation||{};
      return (p.size_pot_ratio!=null&&q.size_pot_ratio!=null)||(p.target_total_bb!=null&&q.target_total_bb!=null);
    });
    return {
      decision_count:comparable.length,
      actions,
      sizing_comparable_count:sizingComparable.length,
      mean_target_bb_delta:sizingComparable.some(r=>r.played.target_total_bb!=null&&r.recommendation.target_total_bb!=null)
        ?round(sizingComparable.filter(r=>r.played.target_total_bb!=null&&r.recommendation.target_total_bb!=null).reduce((s,r)=>s+(r.recommendation.target_total_bb-r.played.target_total_bb),0)/sizingComparable.filter(r=>r.played.target_total_bb!=null&&r.recommendation.target_total_bb!=null).length):null,
      mean_pot_fraction_delta:sizingComparable.some(r=>r.played.size_pot_ratio!=null&&r.recommendation.size_pot_ratio!=null)
        ?round(sizingComparable.filter(r=>r.played.size_pot_ratio!=null&&r.recommendation.size_pot_ratio!=null).reduce((s,r)=>s+(r.recommendation.size_pot_ratio-r.played.size_pot_ratio),0)/sizingComparable.filter(r=>r.played.size_pot_ratio!=null&&r.recommendation.size_pot_ratio!=null).length):null
    };
  }
  function view(rows,weightFn,config){
    return {
      recommendation_count:rows.length,
      action_distribution:actionDistribution(rows,weightFn),
      sizing_distribution:sizingDistribution(rows,weightFn,config),
      tails:tails(rows,weightFn,config),
      played_comparison:playedComparison(rows,weightFn),
      source_refs:normalizeRefs(rows.map(r=>r.source_ref))
    };
  }
  function views(rows,config){
    const admissible=rows.filter(r=>r.admissible);
    const supportRows=admissible.filter(r=>supported(r,config));
    const weightedRows=admissible.filter(r=>r.weight!=null&&r.weight>0);
    return {
      raw:view(admissible,()=>1,config),
      supported:view(supportRows,()=>1,config),
      observed_frequency_weighted:view(weightedRows,r=>r.weight,config)
    };
  }

  function dimensionKey(row,d){
    if(d==='street')return row.street;
    if(d==='position')return row.position;
    if(d==='spot_family')return row.spot_family;
    if(d==='context')return row.context_id||'NO_CONTEXT';
    if(d==='support')return row.support_tier;
    throw new Error('unsupported dimension '+d);
  }
  function groupedRows(rows,d){
    const m=new Map();
    for(const r of rows){
      const k=String(dimensionKey(r,d)||'UNKNOWN');
      if(!m.has(k))m.set(k,[]);
      m.get(k).push(r);
    }
    return m;
  }
  function segment(d,key,rows,config){
    return {
      segment_id:hashId('hero-rec-segment:',{dimension:d,key}),
      dimension:d,key:String(key),
      exposure:exposure(rows,config),
      distributions:views(rows,config),
      source_refs:normalizeRefs(rows.map(r=>r.source_ref))
    };
  }

  function tailRanking(rows,config){
    const admissible=rows.filter(r=>r.admissible);
    const m=new Map();
    for(const r of admissible){
      const key=[r.street,r.position,r.spot_family,r.context_id||'NO_CONTEXT',r.support_tier].join('|');
      if(!m.has(key))m.set(key,[]);
      m.get(key).push(r);
    }
    const out=[];
    for(const [key,group] of m){
      let jam=0,overbet=0,large=0,weighted=0,weightedTail=0;
      for(const r of group){
        const rec=r.recommendation,t=recommendedTail(rec.action,rec.size_pot_ratio,rec.target_total_bb,config);
        if(t.jam)jam++;if(t.overbet)overbet++;if(t.large_sizing)large++;
        if(r.weight!=null){weighted+=r.weight;if(t.jam||t.overbet||t.large_sizing)weightedTail+=r.weight;}
      }
      const tailCount=jam+overbet+large;
      if(!tailCount)continue;
      const [street,position,spot_family,context_id,support_tier]=key.split('|');
      out.push({
        context:{street,position,spot_family,context_id,support_tier},
        decision_count:group.length,
        jam_count:jam,overbet_count:overbet,large_sizing_count:large,
        aggressive_tail_events:tailCount,
        aggressive_tail_decision_count:group.filter(r=>{const t=recommendedTail(r.recommendation.action,r.recommendation.size_pot_ratio,r.recommendation.target_total_bb,config);return t.jam||t.overbet||t.large_sizing;}).length,
        weighted_tail_share:weighted?round(weightedTail/weighted):null,
        source_refs:normalizeRefs(group.filter(r=>{const t=recommendedTail(r.recommendation.action,r.recommendation.size_pot_ratio,r.recommendation.target_total_bb,config);return t.jam||t.overbet||t.large_sizing;}).map(r=>r.source_ref))
      });
    }
    return out.sort((a,b)=>b.aggressive_tail_decision_count-a.aggressive_tail_decision_count||b.jam_count-a.jam_count||b.overbet_count-a.overbet_count||b.large_sizing_count-a.large_sizing_count||(b.weighted_tail_share||0)-(a.weighted_tail_share||0)||stableStringify(a.context).localeCompare(stableStringify(b.context))).slice(0,config.ranking_limit);
  }

  function analyzeRecommendationDistribution(input={}){
    const config=normalizeConfig(input.config||{});
    const records=Array.isArray(input.records)?input.records:[];
    const rows=records.map(r=>normalizeRecord(r,input));
    rows.sort((a,b)=>(a.hand_id||'').localeCompare(b.hand_id||'')||a.decision_id.localeCompare(b.decision_id));
    const ids=new Map();for(const r of rows)ids.set(identityKey(r.identity),r.identity);
    if(ids.size>1)throw new Error('recommendation audit spans multiple population/pack/version/strategy/EV identities');
    const declared=input.identity?exactIdentity(input.identity):null;
    const inferred=ids.size?Array.from(ids.values())[0]:null;
    if(declared&&inferred&&!sameIdentity(declared,inferred))throw new Error('declared identity does not match recommendation records');
    const identity=declared||inferred;
    if(!identity)throw new Error('identity is required when records are empty');

    const segments=[];
    for(const d of DIMENSIONS){
      const groups=groupedRows(rows,d);
      for(const key of Array.from(groups.keys()).sort())segments.push(segment(d,key,groups.get(key),config));
    }
    segments.sort((a,b)=>DIMENSIONS.indexOf(a.dimension)-DIMENSIONS.indexOf(b.dimension)||a.key.localeCompare(b.key));

    const report={
      schema:REPORT_SCHEMA,
      config_schema:CONFIG_SCHEMA,
      identity,
      config,
      exposure:exposure(rows,config),
      distributions:views(rows,config),
      segments,
      aggressive_tail_ranking:tailRanking(rows,config),
      source_refs:normalizeRefs(rows.map(r=>r.source_ref)),
      semantics:{
        descriptive_only:true,
        support_coverage_separate_from_distribution:true,
        fail_closed_counted_as_recommendation:false,
        test_consumed:false,
        issue_108_consumed:false,
        optimization_performed:false,
        promotion_performed:false,
        strategy_modified:false,
        automatic_aggressiveness_verdict:false,
        ev_metrics_consumed:false
      }
    };
    report.report_hash=hashId('hero-recommendation-distribution:',report);
    return report;
  }

  function exportJSON(report,options={}){
    if(!report||report.schema!==REPORT_SCHEMA)throw new Error('expected '+REPORT_SCHEMA);
    return JSON.stringify(report,null,options.pretty===false?0:2);
  }

  return {
    REPORT_SCHEMA,INPUT_SCHEMA,CONFIG_SCHEMA,DIMENSIONS,ACTIONS,DEFAULT_CONFIG,
    normalizeConfig,analyzeRecommendationDistribution,exportJSON
  };
});
