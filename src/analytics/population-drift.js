(function(root,factory){
  const Leak=(typeof module==='object'&&module.exports)?require('./leak-analyzer.js'):(root&&root.PokerLeakAnalyzer);
  const api=factory(Leak);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerPopulationDrift=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(Leak){
  'use strict';

  const REPORT_SCHEMA='poker-population-drift/v1';
  const CONFIG_SCHEMA='poker-population-drift-config/v1';
  const CELL_SCHEMA='poker-population-drift-cell/v1';
  const STATES=['STABLE','DRIFTED','LOW_SUPPORT','NOT_COMPARABLE'];
  const DIMENSIONS=['position','street','spot_family','action','sizing_bucket','jam','overbet','preflop_family','preflop_context'];
  const SCOPE_FIELDS=['population_id','pack_id','strategy_id','strategy_version','ev_reference'];
  const EPS=1e-12;

  const DEFAULT_CONFIG=Object.freeze({
    schema:CONFIG_SCHEMA,
    minimum_decisions_per_cohort:20,
    minimum_distinct_hands_per_cohort:10,
    minimum_supported_decisions_per_cohort:10,
    minimum_supported_ratio:0.5,
    absolute_frequency_delta_threshold:0.15,
    relative_frequency_delta_threshold:0.5,
    relative_delta_min_baseline_frequency:0.05,
    js_divergence_threshold:0.05,
    sizing_js_divergence_threshold:0.08,
    bootstrap_min_decisions_per_cohort:30,
    bootstrap_iterations:200,
    bootstrap_confidence:0.95,
    bootstrap_seed:'population-drift-v1',
    sizing_buckets:{
      pot_ratio_edges:[0.33,0.66,1.0],
      target_bb_edges:[2.5,4,8,20]
    }
  });

  function text(v){return v==null?'':String(v).trim();}
  function upper(v){return text(v).toUpperCase();}
  function round(v){return Math.round((Number(v)+Number.EPSILON)*1e9)/1e9;}
  function finite(v,name){const n=Number(v);if(!Number.isFinite(n))throw new Error(name+' must be finite');return n;}
  function nonNegativeInt(v,name){const n=Number(v);if(!Number.isInteger(n)||n<0)throw new Error(name+' must be a non-negative integer');return n;}
  function positiveInt(v,name){const n=Number(v);if(!Number.isInteger(n)||n<1)throw new Error(name+' must be an integer >= 1');return n;}
  function probability(v,name){const n=finite(v,name);if(n<0||n>1)throw new Error(name+' must be between 0 and 1');return n;}
  function stableStringify(v){
    if(v===null||typeof v!=='object')return JSON.stringify(v);
    if(Array.isArray(v))return '['+v.map(stableStringify).join(',')+']';
    return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+stableStringify(v[k])).join(',')+'}';
  }
  function hash32(s){let h=2166136261>>>0;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)>>>0;}return h>>>0;}
  function hashId(prefix,v){return prefix+hash32(stableStringify(v)).toString(36);}
  function uniqueSorted(values){return Array.from(new Set(values.filter(v=>v!=null&&String(v)!==''))).sort((a,b)=>String(a).localeCompare(String(b)));}
  function sourceRef(e){return {hand_id:String(e.hand_id),decision_id:String(e.decision_id)};}
  function refKey(r){return String(r.hand_id)+'\u0000'+String(r.decision_id);}
  function refs(rows){
    const map=new Map();
    for(const x of rows){const r=sourceRef(x.event||x);map.set(refKey(r),r);}
    return Array.from(map.values()).sort((a,b)=>a.hand_id.localeCompare(b.hand_id)||a.decision_id.localeCompare(b.decision_id));
  }

  function normalizeConfig(input={}){
    const src={...DEFAULT_CONFIG,...(input||{})};
    const sizing={...DEFAULT_CONFIG.sizing_buckets,...(input&&input.sizing_buckets||{})};
    const potEdges=(sizing.pot_ratio_edges||[]).map((x,i)=>finite(x,'sizing_buckets.pot_ratio_edges['+i+']'));
    const bbEdges=(sizing.target_bb_edges||[]).map((x,i)=>finite(x,'sizing_buckets.target_bb_edges['+i+']'));
    if(potEdges.some((x,i)=>i&&x<=potEdges[i-1]))throw new Error('pot_ratio_edges must be strictly increasing');
    if(bbEdges.some((x,i)=>i&&x<=bbEdges[i-1]))throw new Error('target_bb_edges must be strictly increasing');
    const confidence=probability(src.bootstrap_confidence,'bootstrap_confidence');
    if(confidence<=0||confidence>=1)throw new Error('bootstrap_confidence must be > 0 and < 1');
    return {
      schema:CONFIG_SCHEMA,
      minimum_decisions_per_cohort:positiveInt(src.minimum_decisions_per_cohort,'minimum_decisions_per_cohort'),
      minimum_distinct_hands_per_cohort:positiveInt(src.minimum_distinct_hands_per_cohort,'minimum_distinct_hands_per_cohort'),
      minimum_supported_decisions_per_cohort:nonNegativeInt(src.minimum_supported_decisions_per_cohort,'minimum_supported_decisions_per_cohort'),
      minimum_supported_ratio:probability(src.minimum_supported_ratio,'minimum_supported_ratio'),
      absolute_frequency_delta_threshold:probability(src.absolute_frequency_delta_threshold,'absolute_frequency_delta_threshold'),
      relative_frequency_delta_threshold:finite(src.relative_frequency_delta_threshold,'relative_frequency_delta_threshold'),
      relative_delta_min_baseline_frequency:probability(src.relative_delta_min_baseline_frequency,'relative_delta_min_baseline_frequency'),
      js_divergence_threshold:probability(src.js_divergence_threshold,'js_divergence_threshold'),
      sizing_js_divergence_threshold:probability(src.sizing_js_divergence_threshold,'sizing_js_divergence_threshold'),
      bootstrap_min_decisions_per_cohort:positiveInt(src.bootstrap_min_decisions_per_cohort,'bootstrap_min_decisions_per_cohort'),
      bootstrap_iterations:positiveInt(src.bootstrap_iterations,'bootstrap_iterations'),
      bootstrap_confidence:confidence,
      bootstrap_seed:text(src.bootstrap_seed)||'population-drift-v1',
      sizing_buckets:{pot_ratio_edges:potEdges,target_bb_edges:bbEdges}
    };
  }

  function normalizeWindow(input){
    if(input==null)return null;
    if(!input||typeof input!=='object'||Array.isArray(input))throw new Error('cohort.window must be an object or null');
    const start=text(input.start)||null,end=text(input.end)||null;
    for(const [name,v] of [['start',start],['end',end]])if(v&&!Number.isFinite(Date.parse(v)))throw new Error('cohort.window.'+name+' must be an ISO timestamp');
    if(start&&end&&Date.parse(start)>Date.parse(end))throw new Error('cohort.window.start must be <= end');
    return {start,end};
  }
  function normalizeCohortIdentity(input={},label){
    return {
      cohort_id:text(input.cohort_id)||label,
      source:text(input.source)||(()=>{throw new Error(label+'.source is required');})(),
      split:upper(input.split)||(()=>{throw new Error(label+'.split is required');})(),
      window:normalizeWindow(input.window),
      hand_count:nonNegativeInt(input.hand_count,label+'.hand_count'),
      decision_count:nonNegativeInt(input.decision_count,label+'.decision_count'),
      dataset_fingerprint:text(input.dataset_fingerprint)||(()=>{throw new Error(label+'.dataset_fingerprint is required');})(),
      source_fingerprint:text(input.source_fingerprint)||(()=>{throw new Error(label+'.source_fingerprint is required');})()
    };
  }
  function normalizeScope(input){
    const out={};
    for(const k of SCOPE_FIELDS){
      if(k==='pack_id'){out[k]=text(input&&input[k])||null;continue;}
      out[k]=text(input&&input[k])||null;
    }
    return out;
  }
  function scopeKey(s){return SCOPE_FIELDS.map(k=>k+'='+encodeURIComponent(s[k]==null?'':s[k])).join('|');}
  function exactScopeOf(e){return normalizeScope({
    population_id:e.population_id,pack_id:e.pack_id,strategy_id:e.strategy_id,
    strategy_version:e.strategy_version,ev_reference:e.ev_reference
  });}
  function scopesOf(rows){
    const map=new Map();
    for(const row of rows){const s=exactScopeOf(row.event);map.set(scopeKey(s),s);}
    return Array.from(map.values()).sort((a,b)=>scopeKey(a).localeCompare(scopeKey(b)));
  }
  function sameScope(a,b){return SCOPE_FIELDS.every(k=>String(a[k]??'')===String(b[k]??''));}

  function normalizeAction(action){
    const a=upper(action);
    if(a==='FOLD')return 'FOLD';
    if(['CALL','LIMP','OVERLIMP','CALL_SHOVE','CALL-JAM','CALL_JAM'].includes(a))return 'CALL';
    if(['BET','RAISE','OPEN','ISO','SQUEEZE','3BET','4BET','5BET','SHOVE','JAM','ALL_IN','ALL-IN'].includes(a))return 'RAISE';
    if(a==='CHECK')return 'CHECK';
    return a||'OTHER';
  }
  function sizeBucket(e,config){
    const action=normalizeAction(e.played.action);
    if(!['RAISE'].includes(action))return 'NONE';
    const ratio=e.played.size_pot_ratio;
    if(ratio!=null&&Number.isFinite(Number(ratio))){
      const r=Number(ratio),edges=config.sizing_buckets.pot_ratio_edges;
      if(r<=edges[0]+EPS)return 'POT_LE_'+edges[0];
      if(r<=edges[1]+EPS)return 'POT_'+edges[0]+'_'+edges[1];
      if(r<=edges[2]+EPS)return 'POT_'+edges[1]+'_'+edges[2];
      return 'POT_GT_'+edges[2];
    }
    const target=e.played.target_total_bb;
    if(target!=null&&Number.isFinite(Number(target))){
      const t=Number(target),edges=config.sizing_buckets.target_bb_edges;
      if(t<=edges[0]+EPS)return 'TARGET_LE_'+edges[0]+'BB';
      for(let i=1;i<edges.length;i++)if(t<=edges[i]+EPS)return 'TARGET_'+edges[i-1]+'_'+edges[i]+'BB';
      return 'TARGET_GT_'+edges[edges.length-1]+'BB';
    }
    return 'RAISE_SIZE_UNKNOWN';
  }
  function preflopMeta(raw,e,mapping){
    if(upper(e.context.street)!=='PREFLOP')return {family:null,context_id:null};
    const key=String(e.hand_id)+'\u0000'+String(e.decision_id);
    const m=(mapping&&mapping[key])||(mapping&&mapping[e.decision_id])||{};
    return {
      family:upper(m.family||raw.preflop_family||raw.preflop&&raw.preflop.family||e.context.spot_family)||null,
      context_id:text(m.context_id||raw.preflop_context_id||raw.preflop&&raw.preflop.context_id||e.context.context_id)||null
    };
  }
  function normalizeRows(rawEvents,config,mapping){
    if(!Leak)throw new Error('PokerLeakAnalyzer is required');
    const rows=(Array.isArray(rawEvents)?rawEvents:[]).map(raw=>{
      const event=Leak.normalizeEvent(raw);
      return {
        raw,event,
        action_class:normalizeAction(event.played.action),
        sizing_bucket:sizeBucket(event,config),
        preflop:preflopMeta(raw,event,mapping)
      };
    });
    rows.sort((a,b)=>String(a.event.hand_id).localeCompare(String(b.event.hand_id))||String(a.event.decision_id).localeCompare(String(b.event.decision_id)));
    return rows;
  }
  function normalizedFingerprint(rows){
    return hashId('normalized:',rows.map(x=>({
      hand_id:x.event.hand_id,decision_id:x.event.decision_id,population_id:x.event.population_id,
      pack_id:x.event.pack_id,strategy_id:x.event.strategy_id,strategy_version:x.event.strategy_version,
      ev_reference:x.event.ev_reference,position:x.event.context.position,street:x.event.context.street,
      spot_family:x.event.context.spot_family,context_id:x.event.context.context_id,
      action:x.event.played.action,target_total_bb:x.event.played.target_total_bb,size_pot_ratio:x.event.played.size_pot_ratio,
      jam:Boolean(x.event.tags&&x.event.tags.jam),overbet:Boolean(x.event.tags&&x.event.tags.overbet),
      covered:Boolean(x.event.support&&x.event.support.covered),support_observations:x.event.support&&x.event.support.observations,
      preflop:x.preflop
    })));
  }

  function cohortValidation(identity,rows,populationId,label){
    const reasons=[];
    const handCount=uniqueSorted(rows.map(x=>String(x.event.hand_id))).length;
    if(identity.hand_count!==handCount)reasons.push(label.toUpperCase()+'_HAND_COUNT_MISMATCH');
    if(identity.decision_count!==rows.length)reasons.push(label.toUpperCase()+'_DECISION_COUNT_MISMATCH');
    const scopes=scopesOf(rows);
    if(scopes.length!==1)reasons.push(label.toUpperCase()+'_MIXED_SCOPE');
    if(scopes.length===1&&scopes[0].population_id!==populationId)reasons.push(label.toUpperCase()+'_POPULATION_MISMATCH');
    return {reasons,scope:scopes.length===1?scopes[0]:null,actual_hand_count:handCount,actual_decision_count:rows.length,normalized_fingerprint:normalizedFingerprint(rows)};
  }

  function dimensionKey(row,dimension){
    const e=row.event;
    if(dimension==='position')return upper(e.context.position)||'UNKNOWN';
    if(dimension==='street')return upper(e.context.street)||'UNKNOWN';
    if(dimension==='spot_family')return upper(e.context.spot_family)||'UNKNOWN';
    if(dimension==='action')return row.action_class;
    if(dimension==='sizing_bucket')return row.sizing_bucket;
    if(dimension==='jam')return e.tags&&e.tags.jam?'JAM':'NO_JAM';
    if(dimension==='overbet')return e.tags&&e.tags.overbet?'OVERBET':'NO_OVERBET';
    if(dimension==='preflop_family')return row.preflop.family;
    if(dimension==='preflop_context')return row.preflop.context_id;
    throw new Error('unsupported dimension '+dimension);
  }
  function group(rows,dimension){
    const out=new Map();
    for(const row of rows){
      const key=dimensionKey(row,dimension);
      if(key==null||key==='')continue;
      if(!out.has(String(key)))out.set(String(key),[]);
      out.get(String(key)).push(row);
    }
    return out;
  }

  function distribution(rows,getter,categories){
    const counts=Object.fromEntries(categories.map(k=>[k,0]));
    for(const row of rows){const k=String(getter(row));if(!(k in counts))counts[k]=0;counts[k]++;}
    const n=rows.length;
    const probs={};for(const k of Object.keys(counts).sort())probs[k]=n?counts[k]/n:0;
    return {counts:Object.fromEntries(Object.entries(counts).sort()),probabilities:probs};
  }
  function actionDistribution(rows){
    return distribution(rows,r=>r.action_class,['FOLD','CALL','RAISE','CHECK','OTHER']);
  }
  function sizingDistribution(rows){
    const cats=uniqueSorted(rows.map(r=>r.sizing_bucket));
    return distribution(rows,r=>r.sizing_bucket,cats.length?cats:['NONE']);
  }
  function mergedDistribution(a,b){
    const cats=uniqueSorted([...Object.keys(a.counts),...Object.keys(b.counts)]);
    const aa={},bb={};
    for(const k of cats){aa[k]=a.probabilities[k]||0;bb[k]=b.probabilities[k]||0;}
    return [aa,bb];
  }
  function kl(p,m){
    let v=0;
    for(const k of Object.keys(m)){
      const x=p[k]||0,y=m[k]||0;
      if(x>0&&y>0)v+=x*Math.log2(x/y);
    }
    return v;
  }
  function jsd(a,b){
    const keys=uniqueSorted([...Object.keys(a),...Object.keys(b)]);
    const p={},q={},m={};
    for(const k of keys){p[k]=Number(a[k]||0);q[k]=Number(b[k]||0);m[k]=(p[k]+q[k])/2;}
    return round((kl(p,m)+kl(q,m))/2);
  }
  function bernoulliJsd(a,b){return jsd({yes:a,no:1-a},{yes:b,no:1-b});}

  function freq(rows,pred){return rows.length?rows.filter(pred).length/rows.length:0;}
  function relativeDelta(base,target,config){
    if(base<config.relative_delta_min_baseline_frequency-EPS)return null;
    return round((target-base)/base);
  }
  function metric(base,target,config){
    const delta=round(target-base);
    return {baseline:round(base),target:round(target),delta,absolute_delta:round(Math.abs(delta)),relative_delta:relativeDelta(base,target,config)};
  }
  function metricBundle(rows,config){
    return {
      fold_frequency:freq(rows,r=>r.action_class==='FOLD'),
      call_frequency:freq(rows,r=>r.action_class==='CALL'),
      raise_frequency:freq(rows,r=>r.action_class==='RAISE'),
      jam_frequency:freq(rows,r=>Boolean(r.event.tags&&r.event.tags.jam)),
      overbet_frequency:freq(rows,r=>Boolean(r.event.tags&&r.event.tags.overbet))
    };
  }
  function supportSummary(rows){
    const hands=uniqueSorted(rows.map(r=>String(r.event.hand_id)));
    const supported=rows.filter(r=>Boolean(r.event.support&&r.event.support.covered)).length;
    const observations=rows.map(r=>r.event.support&&r.event.support.observations).filter(x=>Number.isInteger(Number(x))&&Number(x)>=0).map(Number);
    return {
      hand_count:hands.length,
      decision_count:rows.length,
      distinct_hands:hands,
      supported_decision_count:supported,
      supported_ratio:rows.length?round(supported/rows.length):null,
      minimum_event_support_observations:observations.length?Math.min(...observations):null,
      source_refs:refs(rows)
    };
  }
  function lowSupport(a,b,config){
    const reasons=[];
    for(const [label,s] of [['BASELINE',a],['TARGET',b]]){
      if(s.decision_count<config.minimum_decisions_per_cohort)reasons.push(label+'_DECISIONS_BELOW_MINIMUM');
      if(s.hand_count<config.minimum_distinct_hands_per_cohort)reasons.push(label+'_HANDS_BELOW_MINIMUM');
      if(s.supported_decision_count<config.minimum_supported_decisions_per_cohort)reasons.push(label+'_SUPPORTED_DECISIONS_BELOW_MINIMUM');
      if(s.supported_ratio==null||s.supported_ratio+EPS<config.minimum_supported_ratio)reasons.push(label+'_SUPPORTED_RATIO_BELOW_MINIMUM');
    }
    return uniqueSorted(reasons);
  }

  function makeRng(seedText){
    let x=hash32(seedText)||0x9e3779b9;
    return ()=>{x^=x<<13;x^=x>>>17;x^=x<<5;return (x>>>0)/4294967296;};
  }
  function resample(rows,rng){
    if(!rows.length)return [];
    const out=[];for(let i=0;i<rows.length;i++)out.push(rows[Math.floor(rng()*rows.length)]);
    return out;
  }
  function quantile(sorted,p){
    if(!sorted.length)return null;
    const pos=(sorted.length-1)*p,lo=Math.floor(pos),hi=Math.ceil(pos);
    if(lo===hi)return sorted[lo];
    return sorted[lo]+(sorted[hi]-sorted[lo])*(pos-lo);
  }
  function interval(values,confidence){
    const xs=[...values].sort((a,b)=>a-b),alpha=(1-confidence)/2;
    return {lower:round(quantile(xs,alpha)),upper:round(quantile(xs,1-alpha))};
  }
  function distances(baseRows,targetRows){
    const adA=actionDistribution(baseRows),adB=actionDistribution(targetRows);
    const [aAct,bAct]=mergedDistribution(adA,adB);
    const sdA=sizingDistribution(baseRows),sdB=sizingDistribution(targetRows);
    const [aSize,bSize]=mergedDistribution(sdA,sdB);
    const jamA=freq(baseRows,r=>Boolean(r.event.tags&&r.event.tags.jam)),jamB=freq(targetRows,r=>Boolean(r.event.tags&&r.event.tags.jam));
    const overA=freq(baseRows,r=>Boolean(r.event.tags&&r.event.tags.overbet)),overB=freq(targetRows,r=>Boolean(r.event.tags&&r.event.tags.overbet));
    const action=jsd(aAct,bAct),sizing=jsd(aSize,bSize),jam=bernoulliJsd(jamA,jamB),overbet=bernoulliJsd(overA,overB);
    return {action_js_divergence:action,sizing_js_divergence:sizing,jam_js_divergence:jam,overbet_js_divergence:overbet,composite_distance:Math.max(action,sizing,jam,overbet)};
  }
  function bootstrap(baseRows,targetRows,config,seed){
    if(baseRows.length<config.bootstrap_min_decisions_per_cohort||targetRows.length<config.bootstrap_min_decisions_per_cohort){
      return {available:false,method:'DETERMINISTIC_BOOTSTRAP',reason:'INSUFFICIENT_SUPPORT',confidence:config.bootstrap_confidence,iterations:config.bootstrap_iterations,seed,delta_ci:null,distance_ci:null};
    }
    const rng=makeRng(seed),metricSamples={fold_frequency:[],call_frequency:[],raise_frequency:[],jam_frequency:[],overbet_frequency:[]},distanceSamples=[];
    for(let i=0;i<config.bootstrap_iterations;i++){
      const a=resample(baseRows,rng),b=resample(targetRows,rng),ma=metricBundle(a,config),mb=metricBundle(b,config);
      for(const k of Object.keys(metricSamples))metricSamples[k].push(mb[k]-ma[k]);
      distanceSamples.push(distances(a,b).composite_distance);
    }
    const delta_ci={};for(const k of Object.keys(metricSamples))delta_ci[k]=interval(metricSamples[k],config.bootstrap_confidence);
    return {available:true,method:'DETERMINISTIC_BOOTSTRAP',reason:null,confidence:config.bootstrap_confidence,iterations:config.bootstrap_iterations,seed,delta_ci,distance_ci:interval(distanceSamples,config.bootstrap_confidence)};
  }

  function driftTriggers(metrics,distance,config){
    const reasons=[];
    for(const [name,m] of Object.entries(metrics)){
      if(m.absolute_delta+EPS>=config.absolute_frequency_delta_threshold)reasons.push(name.toUpperCase()+'_ABS_DELTA');
      if(m.relative_delta!=null&&Math.abs(m.relative_delta)+EPS>=config.relative_frequency_delta_threshold)reasons.push(name.toUpperCase()+'_REL_DELTA');
    }
    if(distance.action_js_divergence+EPS>=config.js_divergence_threshold)reasons.push('ACTION_DISTRIBUTION_JSD');
    if(distance.sizing_js_divergence+EPS>=config.sizing_js_divergence_threshold)reasons.push('SIZING_DISTRIBUTION_JSD');
    if(distance.jam_js_divergence+EPS>=config.js_divergence_threshold)reasons.push('JAM_DISTRIBUTION_JSD');
    if(distance.overbet_js_divergence+EPS>=config.js_divergence_threshold)reasons.push('OVERBET_DISTRIBUTION_JSD');
    return uniqueSorted(reasons);
  }
  function primaryMetric(metrics,distance){
    const candidates=Object.entries(metrics).map(([k,m])=>({name:k,baseline:m.baseline,target:m.target,delta:m.delta,impact:m.absolute_delta,distance:bernoulliJsd(m.baseline,m.target)}));
    candidates.push({name:'action_distribution',baseline:null,target:null,delta:null,impact:distance.action_js_divergence,distance:distance.action_js_divergence});
    candidates.push({name:'sizing_distribution',baseline:null,target:null,delta:null,impact:distance.sizing_js_divergence,distance:distance.sizing_js_divergence});
    return candidates.sort((a,b)=>b.impact-a.impact||a.name.localeCompare(b.name))[0];
  }

  function buildCell(dimension,key,baseRows,targetRows,config,cohorts){
    const baseSupport=supportSummary(baseRows),targetSupport=supportSummary(targetRows);
    const lowReasons=lowSupport(baseSupport,targetSupport,config);
    const mb=metricBundle(baseRows,config),mt=metricBundle(targetRows,config),metrics={};
    for(const k of Object.keys(mb))metrics[k]=metric(mb[k],mt[k],config);
    const dist=distances(baseRows,targetRows);
    const triggers=driftTriggers(metrics,dist,config);
    const state=lowReasons.length?'LOW_SUPPORT':(triggers.length?'DRIFTED':'STABLE');
    const uncertainty=bootstrap(baseRows,targetRows,config,config.bootstrap_seed+'|'+cohorts.baseline.dataset_fingerprint+'|'+cohorts.target.dataset_fingerprint+'|'+dimension+'|'+key);
    const p=primaryMetric(metrics,dist);
    const baseSizing=sizingDistribution(baseRows),targetSizing=sizingDistribution(targetRows);
    const [bs,ts]=mergedDistribution(baseSizing,targetSizing);
    return {
      schema:CELL_SCHEMA,
      cell_id:hashId('drift-cell:',{dimension,key}),
      dimension,key:String(key),state,
      baseline:baseSupport,target:targetSupport,
      metrics,
      sizing_distribution:{baseline:bs,target:ts},
      distance:dist,
      support:{sufficient:!lowReasons.length,reason_codes:lowReasons},
      uncertainty,
      drift_reason_codes:state==='DRIFTED'?triggers:[],
      primary_change:{
        metric:p.name,baseline_value:p.baseline,target_value:p.target,delta:p.delta,
        distance:round(p.distance),impact_score:round(Math.max(p.impact,dist.composite_distance))
      },
      semantics:{descriptive_only:true,retrain_recommended:false,promotion_recommended:false,model_change_recommended:false}
    };
  }

  function incompatibleReport(populationId,baseIdentity,targetIdentity,config,reasons,baseValidation,targetValidation){
    const report={
      schema:REPORT_SCHEMA,config_schema:CONFIG_SCHEMA,population_id:populationId,
      state:'NOT_COMPARABLE',comparable:false,reason_codes:uniqueSorted(reasons),
      baseline_cohort:{...baseIdentity,normalized_fingerprint:baseValidation.normalized_fingerprint},
      target_cohort:{...targetIdentity,normalized_fingerprint:targetValidation.normalized_fingerprint},
      scope:null,config,cells:[],ranking:[],
      semantics:{descriptive_only:true,test_consumed:false,prospective_evaluation:false,ev_metrics_consumed:false,retrain_recommended:false,promotion_recommended:false,model_change_recommended:false}
    };
    report.report_hash=hashId('population-drift-report:',report);
    return report;
  }

  function analyzePopulationDrift(input={}){
    const populationId=text(input.population_id);if(!populationId)throw new Error('population_id is required');
    const config=normalizeConfig(input.config||{});
    const baselineIdentity=normalizeCohortIdentity(input.baseline_cohort||{},'baseline');
    const targetIdentity=normalizeCohortIdentity(input.target_cohort||{},'target');
    if(baselineIdentity.split==='TEST'||targetIdentity.split==='TEST')throw new Error('TEST cohort consumption is forbidden');
    if(Boolean(input.prospective_evaluation))throw new Error('real prospective evaluation is forbidden in population drift analyzer');

    const baseRows=normalizeRows(input.baseline_events,config,input.baseline_preflop_context_by_decision||{});
    const targetRows=normalizeRows(input.target_events,config,input.target_preflop_context_by_decision||{});
    const bv=cohortValidation(baselineIdentity,baseRows,populationId,'baseline'),tv=cohortValidation(targetIdentity,targetRows,populationId,'target');
    const reasons=[...bv.reasons,...tv.reasons];
    if(bv.scope&&tv.scope&&!sameScope(bv.scope,tv.scope))reasons.push('SCOPE_MISMATCH');
    if(!bv.scope||!tv.scope)reasons.push('SCOPE_NOT_EXACT');
    if(reasons.length)return incompatibleReport(populationId,baselineIdentity,targetIdentity,config,reasons,bv,tv);

    const cells=[];
    for(const d of DIMENSIONS){
      const a=group(baseRows,d),b=group(targetRows,d);
      const keys=uniqueSorted([...a.keys(),...b.keys()]);
      for(const key of keys)cells.push(buildCell(d,key,a.get(key)||[],b.get(key)||[],config,{baseline:baselineIdentity,target:targetIdentity}));
    }
    cells.sort((a,b)=>DIMENSIONS.indexOf(a.dimension)-DIMENSIONS.indexOf(b.dimension)||a.key.localeCompare(b.key));
    const ranking=cells.filter(x=>x.state==='DRIFTED').map(x=>({
      cell_id:x.cell_id,dimension:x.dimension,context:x.key,state:x.state,
      metric:x.primary_change.metric,baseline_value:x.primary_change.baseline_value,target_value:x.primary_change.target_value,
      delta:x.primary_change.delta,distance:x.distance.composite_distance,
      support:{baseline_decisions:x.baseline.decision_count,target_decisions:x.target.decision_count,baseline_hands:x.baseline.hand_count,target_hands:x.target.hand_count},
      source_refs:{baseline:x.baseline.source_refs,target:x.target.source_refs},
      impact_score:x.primary_change.impact_score
    })).sort((a,b)=>b.impact_score-a.impact_score||b.distance-a.distance||b.support.target_decisions-a.support.target_decisions||a.dimension.localeCompare(b.dimension)||a.context.localeCompare(b.context));

    const states=cells.map(x=>x.state);
    const overall=states.includes('DRIFTED')?'DRIFTED':(states.includes('LOW_SUPPORT')?'LOW_SUPPORT':'STABLE');
    const report={
      schema:REPORT_SCHEMA,config_schema:CONFIG_SCHEMA,population_id:populationId,state:overall,comparable:true,reason_codes:[],
      baseline_cohort:{...baselineIdentity,normalized_fingerprint:bv.normalized_fingerprint},
      target_cohort:{...targetIdentity,normalized_fingerprint:tv.normalized_fingerprint},
      scope:{...bv.scope},config,cells,ranking,
      summary:{
        cell_count:cells.length,
        stable_cells:cells.filter(x=>x.state==='STABLE').length,
        drifted_cells:cells.filter(x=>x.state==='DRIFTED').length,
        low_support_cells:cells.filter(x=>x.state==='LOW_SUPPORT').length,
        baseline_hands:bv.actual_hand_count,target_hands:tv.actual_hand_count,
        baseline_decisions:bv.actual_decision_count,target_decisions:tv.actual_decision_count
      },
      semantics:{descriptive_only:true,test_consumed:false,prospective_evaluation:false,ev_metrics_consumed:false,retrain_recommended:false,promotion_recommended:false,model_change_recommended:false}
    };
    report.report_hash=hashId('population-drift-report:',report);
    return report;
  }

  function exportJSON(report,options={}){
    if(!report||report.schema!==REPORT_SCHEMA)throw new Error('expected '+REPORT_SCHEMA);
    return JSON.stringify(report,null,options.pretty===false?0:2);
  }

  return {REPORT_SCHEMA,CONFIG_SCHEMA,CELL_SCHEMA,STATES,DIMENSIONS,DEFAULT_CONFIG,normalizeConfig,analyzePopulationDrift,exportJSON};
});
