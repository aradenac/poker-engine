'use strict';

const assert=require('node:assert/strict');
const Leak=require('../../src/analytics/leak-analyzer.js');
const Drift=require('../../src/analytics/population-drift.js');

const POP='pokerstars_nlhe_100-200_zoom_play_6max_v1';
const SCOPE={
  population_id:POP,
  pack_id:'zoom-pack@1',
  strategy_id:'observed-population-v1',
  strategy_version:'normalizer-v1',
  ev_reference:'review_score_policy_adjusted_incremental_bb'
};
const CONFIG={
  schema:'poker-population-drift-config/v1',
  minimum_decisions_per_cohort:10,
  minimum_distinct_hands_per_cohort:10,
  minimum_supported_decisions_per_cohort:10,
  minimum_supported_ratio:.8,
  absolute_frequency_delta_threshold:.15,
  relative_frequency_delta_threshold:.5,
  relative_delta_min_baseline_frequency:.05,
  js_divergence_threshold:.04,
  sizing_js_divergence_threshold:.04,
  bootstrap_min_decisions_per_cohort:20,
  bootstrap_iterations:80,
  bootstrap_confidence:.9,
  bootstrap_seed:'fixture-seed',
  sizing_buckets:{pot_ratio_edges:[.33,.66,1],target_bb_edges:[2.5,4,8,20]}
};

function actionFor(i,mode='stable'){
  if(mode==='stable')return i<20?'FOLD':i<40?'CALL':'RAISE';
  if(mode==='action-drift')return i<8?'FOLD':i<28?'CALL':'RAISE';
  return i<20?'FOLD':i<40?'CALL':'RAISE';
}
function makeEvents(prefix,{mode='stable',population=POP,count=60,unsupported=0}={}){
  const rows=[];
  for(let i=0;i<count;i++){
    const action=actionFor(i,mode);
    let ratio=null,target=null,isAllIn=false;
    if(action==='RAISE'){
      if(mode==='sizing-drift')ratio=.95;
      else ratio=.45;
      target=6;
      if(mode==='jam-drift'&&i>=48){action==='RAISE';isAllIn=true;target=100;ratio=1.6;}
      if(mode==='overbet-drift'&&i>=48){ratio=1.6;}
    }
    const actualAction=isAllIn?'SHOVE':action;
    const covered=i>=unsupported;
    const e=Leak.buildDecisionEvent({
      hand_id:prefix+'-h'+String(i).padStart(3,'0'),
      decision_id:prefix+'-d'+String(i).padStart(3,'0'),
      timestamp:'2026-09-01T'+String(Math.floor(i/60)).padStart(2,'0')+':'+String(i%60).padStart(2,'0')+':00Z',
      population_id:population,pack_id:SCOPE.pack_id,strategy_id:SCOPE.strategy_id,
      strategy_version:SCOPE.strategy_version,ev_reference:SCOPE.ev_reference,
      position:'BTN',street:'PREFLOP',spot_family:'UNOPENED',context_id:'ctx-btn-unopened',
      action_played:actualAction,played_target_total_bb:target,played_size_pot_ratio:ratio,
      played_is_all_in:isAllIn,played_is_overbet:ratio!=null&&ratio>1,
      action_recommended:'CHECK',
      played_ev_bb:covered?-9876.54321:null,best_ev_bb:covered?0:null,
      support:covered?{covered:true,observations:120,source:'SYNTHETIC_TRAIN'}:{covered:false,observations:0,source:'SYNTHETIC_TRAIN',reason:'NO_SUPPORT'},
      comparability:covered?{comparable:true}:{comparable:false,reason:'NO_SUPPORT'}
    });
    rows.push({...e,preflop_family:'UNOPENED',preflop_context_id:'ctx-btn-unopened'});
  }
  return rows;
}
function cohort(id,events,{split='TRAIN',source='synthetic',datasetFingerprint=null,sourceFingerprint=null}={}){
  return {
    cohort_id:id,source,split,
    window:{start:'2026-09-01T00:00:00Z',end:'2026-09-30T23:59:59Z'},
    hand_count:new Set(events.map(x=>x.hand_id)).size,
    decision_count:events.length,
    dataset_fingerprint:datasetFingerprint||id+'-dataset-sha256',
    source_fingerprint:sourceFingerprint||id+'-source-sha256'
  };
}
function analyze(base,target,opts={}){
  return Drift.analyzePopulationDrift({
    population_id:opts.population_id||POP,
    baseline_cohort:cohort('baseline',base,opts.baseline_identity||{}),
    target_cohort:cohort('target',target,opts.target_identity||{}),
    baseline_events:base,target_events:target,
    config:{...CONFIG,...(opts.config||{})},
    prospective_evaluation:false
  });
}
function cell(report,dimension,key){
  const r=report.cells.find(x=>x.dimension===dimension&&x.key===key);
  assert.ok(r,'missing cell '+dimension+' '+key);
  return r;
}

{
  const base=makeEvents('b');
  const target=makeEvents('t');
  const report=analyze(base,target);
  assert.equal(report.schema,'poker-population-drift/v1');
  assert.equal(report.config_schema,'poker-population-drift-config/v1');
  assert.equal(report.state,'STABLE');
  assert.equal(report.comparable,true);
  assert.equal(report.ranking.length,0);
  assert.equal(report.summary.drifted_cells,0);
  assert.equal(report.summary.low_support_cells,0);
  assert.equal(cell(report,'position','BTN').state,'STABLE');
  assert.equal(cell(report,'position','BTN').metrics.fold_frequency.delta,0);
  assert.equal(cell(report,'position','BTN').metrics.call_frequency.delta,0);
  assert.equal(cell(report,'position','BTN').metrics.raise_frequency.delta,0);
  assert.equal(cell(report,'position','BTN').distance.action_js_divergence,0);
  assert.equal(cell(report,'position','BTN').distance.sizing_js_divergence,0);
  assert.equal(cell(report,'preflop_family','UNOPENED').state,'STABLE');
  assert.equal(cell(report,'preflop_context','ctx-btn-unopened').state,'STABLE');
  assert.equal(cell(report,'position','BTN').uncertainty.available,true);
  assert.equal(cell(report,'position','BTN').uncertainty.method,'DETERMINISTIC_BOOTSTRAP');
}

{
  const base=makeEvents('b');
  const target=makeEvents('t',{mode:'action-drift'});
  const report=analyze(base,target);
  assert.equal(report.state,'DRIFTED');
  const pos=cell(report,'position','BTN');
  assert.equal(pos.state,'DRIFTED');
  assert.equal(pos.metrics.fold_frequency.baseline,1/3);
  assert.equal(pos.metrics.fold_frequency.target,round9(8/60));
  assert.equal(pos.metrics.fold_frequency.delta,round9(8/60-1/3));
  assert.ok(pos.metrics.fold_frequency.absolute_delta>.19);
  assert.ok(pos.metrics.raise_frequency.absolute_delta>.19);
  assert.ok(pos.distance.action_js_divergence>0);
  assert.ok(report.ranking.some(x=>x.dimension==='position'&&x.context==='BTN'));
  assert.equal(report.ranking[0].state,'DRIFTED');
  assert.equal(report.ranking[0].support.baseline_decisions,60);
  assert.equal(report.ranking[0].support.target_decisions,60);
}

{
  const base=makeEvents('b');
  const target=makeEvents('t',{mode:'sizing-drift'});
  const report=analyze(base,target);
  assert.equal(report.state,'DRIFTED');
  const pos=cell(report,'position','BTN');
  assert.equal(pos.metrics.fold_frequency.delta,0);
  assert.equal(pos.metrics.call_frequency.delta,0);
  assert.equal(pos.metrics.raise_frequency.delta,0);
  assert.ok(pos.distance.sizing_js_divergence>=CONFIG.sizing_js_divergence_threshold);
  assert.ok(pos.drift_reason_codes.includes('SIZING_DISTRIBUTION_JSD'));
  assert.ok(Object.keys(pos.sizing_distribution.baseline).some(x=>x.includes('POT_')));
}

{
  const base=makeEvents('b');
  const target=makeEvents('t',{mode:'jam-drift'});
  const report=analyze(base,target);
  const pos=cell(report,'position','BTN');
  assert.equal(report.state,'DRIFTED');
  assert.equal(pos.metrics.jam_frequency.baseline,0);
  assert.equal(pos.metrics.jam_frequency.target,.2);
  assert.ok(pos.drift_reason_codes.some(x=>x.includes('JAM')));
  assert.ok(pos.distance.jam_js_divergence>0);
}

{
  const base=makeEvents('b');
  const target=makeEvents('t',{mode:'overbet-drift'});
  const report=analyze(base,target);
  const pos=cell(report,'position','BTN');
  assert.equal(report.state,'DRIFTED');
  assert.equal(pos.metrics.overbet_frequency.baseline,0);
  assert.equal(pos.metrics.overbet_frequency.target,.2);
  assert.ok(pos.drift_reason_codes.some(x=>x.includes('OVERBET')));
  assert.ok(pos.distance.overbet_js_divergence>0);
}

{
  const base=makeEvents('lb',{count:6});
  const target=makeEvents('lt',{count:6,mode:'action-drift'});
  const report=analyze(base,target);
  assert.equal(report.state,'LOW_SUPPORT');
  assert.equal(report.ranking.length,0,'LOW_SUPPORT cells must never be ranked as DRIFTED');
  const pos=cell(report,'position','BTN');
  assert.equal(pos.state,'LOW_SUPPORT');
  assert.equal(pos.support.sufficient,false);
  assert.ok(pos.support.reason_codes.includes('BASELINE_DECISIONS_BELOW_MINIMUM'));
  assert.equal(pos.uncertainty.available,false);
  assert.equal(pos.uncertainty.reason,'INSUFFICIENT_SUPPORT');
  assert.deepEqual(pos.drift_reason_codes,[]);
}

{
  const base=makeEvents('b');
  const target=makeEvents('t',{population:'other-population'});
  const report=analyze(base,target);
  assert.equal(report.state,'NOT_COMPARABLE');
  assert.equal(report.comparable,false);
  assert.ok(report.reason_codes.includes('TARGET_POPULATION_MISMATCH'));
  assert.ok(report.reason_codes.includes('SCOPE_MISMATCH'));
  assert.deepEqual(report.cells,[]);
  assert.deepEqual(report.ranking,[]);
}

{
  const base=makeEvents('b'),target=makeEvents('t',{mode:'action-drift'});
  const report1=analyze(base,target);
  const report2=analyze([...base].reverse(),[...target].reverse());
  assert.deepEqual(report1,report2,'permuting HH/decision order must not change the report');
  assert.equal(report1.report_hash,report2.report_hash);
  assert.equal(Drift.exportJSON(report1,{pretty:false}),Drift.exportJSON(report2,{pretty:false}));
}

{
  const base=makeEvents('b'),target=makeEvents('t',{mode:'action-drift'});
  const one=analyze(base,target),two=analyze(base,target);
  assert.deepEqual(one,two);
  assert.equal(one.report_hash,two.report_hash);
  assert.equal(Drift.exportJSON(one),Drift.exportJSON(two));
  const pos=cell(one,'position','BTN');
  assert.deepEqual(pos.baseline.source_refs.slice(0,2),[
    {hand_id:'b-h000',decision_id:'b-d000'},
    {hand_id:'b-h001',decision_id:'b-d001'}
  ]);
  assert.deepEqual(pos.target.source_refs.slice(0,2),[
    {hand_id:'t-h000',decision_id:'t-d000'},
    {hand_id:'t-h001',decision_id:'t-d001'}
  ]);
  assert.deepEqual(one.ranking.find(x=>x.dimension==='position'&&x.context==='BTN').source_refs.baseline,pos.baseline.source_refs);
}

{
  const report=analyze(makeEvents('b'),makeEvents('t',{mode:'action-drift'}));
  const json=Drift.exportJSON(report,{pretty:false});
  assert.equal(json.includes('9876.54321'),false,'EV must not contaminate population-drift output');
  assert.equal(report.semantics.ev_metrics_consumed,false);
  assert.equal(report.semantics.test_consumed,false);
  assert.equal(report.semantics.prospective_evaluation,false);
  assert.equal(report.semantics.retrain_recommended,false);
  assert.equal(report.semantics.promotion_recommended,false);
  assert.equal(report.semantics.model_change_recommended,false);
  for(const row of report.ranking){
    assert.equal(Object.prototype.hasOwnProperty.call(row,'recommended_action'),false);
    assert.equal(Object.prototype.hasOwnProperty.call(row,'retrain'),false);
  }
}

{
  const base=makeEvents('b'),target=makeEvents('t');
  assert.throws(()=>Drift.analyzePopulationDrift({
    population_id:POP,baseline_cohort:cohort('baseline',base,{split:'TEST'}),target_cohort:cohort('target',target),
    baseline_events:base,target_events:target,config:CONFIG
  }),/TEST cohort consumption is forbidden/);
  assert.throws(()=>Drift.analyzePopulationDrift({
    population_id:POP,baseline_cohort:cohort('baseline',base),target_cohort:cohort('target',target),
    baseline_events:base,target_events:target,config:CONFIG,prospective_evaluation:true
  }),/real prospective evaluation is forbidden/);
}

{
  const base=makeEvents('b'),target=makeEvents('t');
  const bad=cohort('baseline',base);bad.decision_count++;
  const report=Drift.analyzePopulationDrift({
    population_id:POP,baseline_cohort:bad,target_cohort:cohort('target',target),
    baseline_events:base,target_events:target,config:CONFIG
  });
  assert.equal(report.state,'NOT_COMPARABLE');
  assert.ok(report.reason_codes.includes('BASELINE_DECISION_COUNT_MISMATCH'));
}

function round9(x){return Math.round((x+Number.EPSILON)*1e9)/1e9;}

console.log(JSON.stringify({
  status:'PASS',
  schema:Drift.REPORT_SCHEMA,
  config_schema:Drift.CONFIG_SCHEMA,
  states:Drift.STATES,
  dimensions:Drift.DIMENSIONS
}));
