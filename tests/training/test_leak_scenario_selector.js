'use strict';

const assert=require('node:assert/strict');
const Leak=require('../../src/analytics/leak-analyzer.js');
const Target=require('../../src/analytics/leak-training-target.js');
const Selector=require('../../src/training/leak-scenario-selector.js');

const ID={
  population_id:'pokerstars_nlhe_100-200_zoom_play_6max_v1',
  pack_id:'zoom-pack@1',
  strategy_id:'custom_ranges_v1',
  strategy_version:'runtime-r1@review-sig-A',
  ev_reference:'review_score_policy_adjusted_incremental_bb'
};

function target(overrides={}){
  return Target.buildTrainingTarget({
    identity:ID,
    context:{position:'BB',street:'PREFLOP',spot_family:'VS_RFI',...(overrides.context||{})},
    source_pattern:{
      played_action:'CALL',
      recommended_action:'FOLD',
      sizing_error:null,
      jam:null,
      overbet:null,
      ...(overrides.source_pattern||{})
    },
    source_leak:{
      dimension:'action_pair',key:'CALL->FOLD',decisions:12,total_loss_bb:8.2,source_refs:[],
      ...(overrides.source_leak||{})
    },
    minimum_support:{decisions:2,scenarios:1,...(overrides.minimum_support||{})}
  });
}

function scenario(id,overrides={}){
  const base={
    schema:Target.SCENARIO_SCHEMA,
    scenario_id:id,
    identity:{...ID},
    context:{position:'BB',street:'PREFLOP',spot_family:'VS_RFI'},
    policy:{recommended_action:'FOLD',played_action_context:'RAISE'},
    focus:{sizing_decision:false,jam_available:false,overbet_available:false},
    support:{covered:true,observations:40,source:'fixture'},
    supported:true,
    diversity_key:'hand-'+id
  };
  const out={...base,...overrides};
  if(overrides.identity)out.identity={...base.identity,...overrides.identity};
  if(overrides.context)out.context={...base.context,...overrides.context};
  if(overrides.policy)out.policy={...base.policy,...overrides.policy};
  if(overrides.focus)out.focus={...base.focus,...overrides.focus};
  if(overrides.support)out.support={...base.support,...overrides.support};
  return out;
}

{
  const t=target();
  const pool=[scenario('s1'),scenario('s2'),scenario('s3')];
  const plan=Selector.buildSessionPlan(t,pool,{session_size:2,seed:'seed-A',identity:ID});
  assert.equal(plan.schema,Selector.PLAN_SCHEMA);
  assert.equal(plan.target_id,t.target_id);
  assert.equal(plan.criteria_id,Target.compileScenarioCriteria(t).criteria_id);
  assert.equal(plan.ready,true);
  assert.equal(plan.fallback,null);
  assert.equal(plan.pool.candidates,3);
  assert.equal(plan.pool.unique_candidates,3);
  assert.equal(plan.pool.supported_unique,3);
  assert.equal(plan.pool.matching_supported,3);
  assert.equal(plan.pool.selected,2);
  assert.equal(plan.selection.length,2);
  assert.equal(plan.criteria_applied.source_played_action_diagnostic_only,true);
  assert.equal(plan.criteria_applied.focus.source_played_action,'CALL');
  assert.ok(plan.selection.every(x=>x.scenario.policy.played_action_context==='RAISE'),
    'source played_action must remain diagnostic and must not require repeating CALL');
}

{
  const t=target();
  const pool=[
    scenario('exact'),
    scenario('bad-pos',{context:{position:'SB'}}),
    scenario('bad-street',{context:{street:'FLOP'}}),
    scenario('bad-spot',{context:{spot_family:'VS_3BET'}}),
    scenario('bad-action',{policy:{recommended_action:'CALL'}}),
    scenario('bad-pop',{identity:{population_id:'other'}}),
    scenario('bad-strategy',{identity:{strategy_id:'other'}}),
    scenario('bad-version',{identity:{strategy_version:'other'}}),
    scenario('bad-pack',{identity:{pack_id:'other'}}),
    scenario('bad-ev',{identity:{ev_reference:'other'}}),
    scenario('unsupported',{supported:false,support:{covered:false,reason:'NO_MODEL_SUPPORT'}})
  ];
  const plan=Selector.buildSessionPlan(t,pool,{session_size:1,seed:'combined'});
  assert.equal(plan.ready,true);
  assert.deepEqual(plan.selection.map(x=>x.scenario_id),['exact']);
  assert.equal(plan.pool.matching_supported,1);
  assert.equal(plan.pool.rejected,10);
  for(const reason of [
    'POSITION_MISMATCH','STREET_MISMATCH','SPOT_FAMILY_MISMATCH','RECOMMENDED_ACTION_MISMATCH',
    'POPULATION_MISMATCH','STRATEGY_MISMATCH','STRATEGY_VERSION_MISMATCH','PACK_MISMATCH',
    'EV_REFERENCE_MISMATCH','NO_MODEL_SUPPORT'
  ]) assert.equal(plan.pool.rejection_reasons[reason],1,reason);
}

{
  const t=target({minimum_support:{scenarios:3}});
  const plan=Selector.buildSessionPlan(t,[scenario('s1'),scenario('s2')],{session_size:2,seed:'too-small'});
  assert.equal(plan.ready,false);
  assert.equal(plan.fallback,Selector.FALLBACK);
  assert.equal(plan.fallback,'INSUFFICIENT_SUPPORTED_SCENARIOS');
  assert.equal(plan.selection.length,0,'fail-closed plan must not silently execute a smaller or alternate session');
  assert.equal(plan.fallback_detail.matching_supported,2);
  assert.equal(plan.fallback_detail.required,3);
}

{
  const t=target();
  const plan=Selector.buildSessionPlan(t,[
    scenario('covered'),
    scenario('missing-obs',{support:{covered:true,observations:null}}),
    scenario('low-obs',{support:{covered:true,observations:2}})
  ],{session_size:1,seed:'support',minimum_observations_per_scenario:10});
  assert.equal(plan.ready,true);
  assert.deepEqual(plan.selection.map(x=>x.scenario_id),['covered']);
  assert.equal(plan.pool.rejection_reasons.MISSING_SUPPORT_OBSERVATIONS,1);
  assert.equal(plan.pool.rejection_reasons.LOW_SUPPORT_OBSERVATIONS,1);
}

{
  const t=target({source_pattern:{sizing_error:true},source_leak:{dimension:'error_type',key:'SIZING_ERROR'}});
  const plan=Selector.buildSessionPlan(t,[
    scenario('yes',{focus:{sizing_decision:true}}),
    scenario('no',{focus:{sizing_decision:false}})
  ],{session_size:1,seed:'sizing'});
  assert.equal(plan.ready,true);
  assert.deepEqual(plan.selection.map(x=>x.scenario_id),['yes']);
  assert.equal(plan.pool.rejection_reasons.SIZING_FOCUS_MISMATCH,1);
}

{
  const t=target({source_pattern:{jam:true},source_leak:{dimension:'jam',key:'JAM'}});
  const plan=Selector.buildSessionPlan(t,[
    scenario('jam',{focus:{jam_available:true}}),
    scenario('not-jam',{focus:{jam_available:false}})
  ],{session_size:1,seed:'jam'});
  assert.deepEqual(plan.selection.map(x=>x.scenario_id),['jam']);
  assert.equal(plan.pool.rejection_reasons.JAM_FOCUS_MISMATCH,1);
}

{
  const t=target({source_pattern:{overbet:true},source_leak:{dimension:'overbet',key:'OVERBET'}});
  const plan=Selector.buildSessionPlan(t,[
    scenario('over',{focus:{overbet_available:true}}),
    scenario('not-over',{focus:{overbet_available:false}})
  ],{session_size:1,seed:'overbet'});
  assert.deepEqual(plan.selection.map(x=>x.scenario_id),['over']);
  assert.equal(plan.pool.rejection_reasons.OVERBET_FOCUS_MISMATCH,1);
}

{
  const t=target();
  const pool=[
    scenario('a1',{diversity_key:'A'}),
    scenario('a2',{diversity_key:'A'}),
    scenario('b1',{diversity_key:'B'}),
    scenario('b2',{diversity_key:'B'}),
    scenario('c1',{diversity_key:'C'}),
    scenario('c2',{diversity_key:'C'})
  ];
  const one=Selector.buildSessionPlan(t,pool,{session_size:3,seed:'repro'});
  const two=Selector.buildSessionPlan(t,[...pool].reverse(),{session_size:3,seed:'repro'});
  assert.deepEqual(one.selection.map(x=>x.scenario_id),two.selection.map(x=>x.scenario_id),
    'same seed must reproduce selection independent of pool order');
  assert.equal(new Set(one.selection.map(x=>x.diversity_key)).size,3,
    'round-robin selection should maximize diversity before repeating a group');
  const other=Selector.buildSessionPlan(t,pool,{session_size:3,seed:'other-seed'});
  assert.notEqual(one.plan_id,other.plan_id,'seed participates in deterministic plan identity');
}

{
  const t=target();
  const dupA=scenario('dup',{payload_key:'z',diversity_key:'A'});
  const dupB=scenario('dup',{payload_key:'a',diversity_key:'B'});
  const plan1=Selector.buildSessionPlan(t,[dupA,dupB,scenario('unique')],{session_size:2,seed:'dedupe'});
  const plan2=Selector.buildSessionPlan(t,[dupB,scenario('unique'),dupA],{session_size:2,seed:'dedupe'});
  assert.equal(plan1.pool.candidates,3);
  assert.equal(plan1.pool.unique_candidates,2);
  assert.equal(plan1.pool.rejection_reasons.DUPLICATE_SCENARIO,1);
  assert.deepEqual(plan1.selection.map(x=>x.scenario_id),plan2.selection.map(x=>x.scenario_id));
}

{
  const t=target();
  assert.throws(()=>Selector.buildSessionPlan(t,[scenario('s1')],{
    session_size:1,identity:{...ID,strategy_version:'wrong'}
  }),/runtime identity does not match target identity/);
}

function event(id,overrides={}){
  return Leak.buildDecisionEvent({
    hand_id:'train-'+id,decision_id:'train-decision-'+id,timestamp:'2026-10-01T10:'+String(id).padStart(2,'0')+':00Z',
    ...ID,position:'BB',street:'PREFLOP',spot_family:'VS_RFI',
    action_played:'CALL',action_recommended:'FOLD',played_ev_bb:-1,best_ev_bb:0,
    support:{covered:true,observations:30,source:'runtime'},comparability:{comparable:true},
    ...overrides
  });
}

{
  const t=target();
  const plan=Selector.buildSessionPlan(t,[scenario('s1'),scenario('s2'),scenario('s3')],{session_size:3,seed:'summary'});
  const events=[
    event(1,{played_ev_bb:-1,best_ev_bb:0}),
    event(2,{action_played:'FOLD',played_ev_bb:0,best_ev_bb:0}),
    event(3,{played_ev_bb:.9,best_ev_bb:1,within_noise:true}),
    event(4,{played_ev_bb:null,best_ev_bb:null,support:{covered:false,reason:'NO_MODEL_SUPPORT'},comparability:{comparable:false,reason:'NO_MODEL_SUPPORT'}}),
    event(5,{played_ev_bb:null,best_ev_bb:null,comparability:{comparable:false,reason:'NO_COMPARABLE_EV'}}),
    event(6,{position:'SB',played_ev_bb:-9,best_ev_bb:0}),
    event(7,{strategy_version:'other',played_ev_bb:-8,best_ev_bb:0})
  ];
  const summary=Selector.summarizePlannedSession(plan,events,{minimum_trend_decisions:3,minimum_long_term_spots:20});
  assert.equal(summary.schema,Selector.RUNTIME_SUMMARY_SCHEMA);
  assert.equal(summary.target_id,plan.target_id);
  assert.equal(summary.criteria_id,plan.criteria_id);
  assert.equal(summary.plan_id,plan.plan_id);
  assert.equal(summary.planned_spots,3);
  assert.equal(summary.spots_played,5,'only target-matching training hands count as played spots');
  assert.equal(summary.summary.covered_comparable,3);
  assert.equal(summary.summary.unsupported,1);
  assert.equal(summary.summary.non_comparable,1);
  assert.equal(summary.summary.total_delta_ev_loss_bb,1);
  assert.equal(summary.summary.average_delta_ev_loss_bb,1/3);
  assert.equal(summary.summary.loss_bb_per_100_decisions,100/3);
  assert.equal(summary.long_term_progression.claimed,false);
  assert.equal(summary.long_term_progression.sample_sufficient_for_assessment,false);
  assert.equal(summary.long_term_progression.reason,'INSUFFICIENT_SAMPLE');
}

{
  const t=target();
  const plan=Selector.buildSessionPlan(t,[scenario('s1')],{session_size:1,seed:'no-eligible'});
  const summary=Selector.summarizePlannedSession(plan,[
    event(8,{played_ev_bb:null,best_ev_bb:null,support:{covered:false,reason:'X'},comparability:{comparable:false,reason:'X'}})
  ]);
  assert.equal(summary.summary.covered_comparable,0);
  assert.equal(summary.summary.average_delta_ev_loss_bb,null);
  assert.equal(summary.summary.loss_bb_per_100_decisions,null);
}

console.log(JSON.stringify({
  status:'PASS',
  plan_schema:Selector.PLAN_SCHEMA,
  fallback:Selector.FALLBACK
}));
