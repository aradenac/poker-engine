'use strict';

const assert=require('node:assert/strict');
const Leak=require('../../src/analytics/leak-analyzer.js');
const Coverage=require('../../src/analytics/analysis-coverage.js');

const SCOPE={
  population_id:'pokerstars_nlhe_100-200_zoom_play_6max_v1',
  pack_id:'zoom-pack',
  pack_version:'pack-v7',
  strategy_id:'custom_ranges_v1',
  strategy_version:'runtime-r2@review-sig',
  ev_reference:'review_score_policy_adjusted_incremental_bb'
};

function ev(id,overrides={}){
  const base={
    hand_id:'h'+id,
    decision_id:'d'+id,
    timestamp:'2026-09-19T00:0'+id+':00Z',
    population_id:SCOPE.population_id,
    pack_id:SCOPE.pack_id,
    pack_version:SCOPE.pack_version,
    strategy_id:SCOPE.strategy_id,
    strategy_version:SCOPE.strategy_version,
    ev_reference:SCOPE.ev_reference,
    position:'BB',
    street:'PREFLOP',
    spot_family:'VS_RFI',
    action_played:'CALL',
    action_recommended:'FOLD',
    played_ev_bb:-1234.56789,
    best_ev_bb:0,
    support:{covered:true,observations:100,source:'fixture'},
    comparability:{comparable:true}
  };
  return {...base,...overrides,
    support:{...base.support,...(overrides.support||{})},
    comparability:{...base.comparability,...(overrides.comparability||{})}
  };
}

const events=[
  ev(1,{spot_family:'COVERED_SPOT',support:{observations:100}}),
  ev(2,{street:'FLOP',position:'BTN',spot_family:'LOW_SPOT',action_played:'BET',action_recommended:'CHECK',
    played_target_total_bb:12,recommended_target_total_bb:0,played_size_pot_ratio:.75,sizing_error:true,
    support:{observations:5}}),
  ev(3,{street:'TURN',position:'CO',spot_family:'UNSUPPORTED_SPOT',action_played:'SHOVE',action_recommended:'CALL',
    played_is_all_in:true,played_size_pot_ratio:1.5,
    played_ev_bb:null,best_ev_bb:null,
    support:{covered:false,observations:0,reason:'NO_MODEL_SUPPORT'},
    comparability:{comparable:false,reason:'NO_MODEL_SUPPORT'}}),
  ev(4,{street:'RIVER',position:'SB',spot_family:'NONCOMP_SPOT',action_played:'BET',action_recommended:'BET',
    played_ev_bb:null,best_ev_bb:null,
    support:{covered:true,observations:80},
    comparability:{comparable:false,reason:'MISSING_COMPARABLE_EV'}}),
  ev(5,{spot_family:'VS_4BET',action_played:'SHOVE',action_recommended:'CALL',
    played_is_all_in:true,played_size_pot_ratio:2.2,support:{observations:150},played_ev_bb:-4321.12345,best_ev_bb:0})
];

function matrixRow({family,group,pos,obs,hands,callers=0,limpers=0,jam=false,opener=null,lastAgg=null,tier}){
  return {
    actor_position:pos,
    callers_after_first_raise:callers,
    coverage_group:group,
    distinct_hands:hands,
    effective_stack:{n:hands,p50_bb:100},
    facing_jam:jam,
    family,
    frequency_of_population_preflop:obs/10000,
    frequency_of_targeted:obs/3000,
    last_aggressor_position:lastAgg,
    limpers_before_first_raise:limpers,
    observations:obs,
    opener_position:opener,
    priority_rank:1,
    support_tier:tier
  };
}
function sourceKey(r){
  return JSON.stringify({
    actor_position:r.actor_position,
    callers_after_first_raise:r.callers_after_first_raise,
    facing_jam:r.facing_jam,
    family:r.family,
    last_aggressor_position:r.last_aggressor_position,
    limpers_before_first_raise:r.limpers_before_first_raise,
    opener_position:r.opener_position
  });
}

const a1=matrixRow({family:'VS_RFI',group:'VS_RFI',pos:'BB',obs:500,hands:480,opener:'BTN',tier:'HIGH'});
const a2=matrixRow({family:'VS_LIMPERS',group:'VS_LIMPERS_ISO',pos:'BTN',obs:1000,hands:900,limpers:1,tier:'VERY_HIGH'});
const a3=matrixRow({family:'VS_4BET',group:'VS_4BET_OR_JAM',pos:'BB',obs:10,hands:9,jam:true,lastAgg:'CO',tier:'LOW'});

const audit={
  schema:'poker-hero-preflop-coverage-audit/v1',
  population_id:SCOPE.population_id,
  scope:{split_consumed:'TRAIN',validation_consumed:false,test_consumed:false,strategy_generated:false,ev_evaluated:false},
  matrix:[a1,a2,a3]
};
const plan={
  schema:'poker-hero-preflop-generation-plan/v1',
  population_id:SCOPE.population_id,
  scope:{
    split_consumed:'TRAIN',validation_consumed:false,test_consumed:false,strategy_generated:false,ev_evaluated:false,
    actions_recommended:false,sizings_recommended:false
  },
  contexts:[
    {context_id:'ctx-vs-rfi',family:'VS_RFI',coverage_group:'VS_RFI',hero_position:'BB',caller_count:0,limper_count:0,jam_state:false,
      opener_position:'BTN',last_aggressor_position:null,train_observations:500,distinct_hands:480,support_tier:'HIGH',
      readiness:'READY_FOR_GENERATION',frequency:{of_targeted:.2},source_matrix_key:sourceKey(a1)},
    {context_id:'ctx-missing',family:'VS_LIMPERS',coverage_group:'VS_LIMPERS_ISO',hero_position:'BTN',caller_count:0,limper_count:1,jam_state:false,
      opener_position:null,last_aggressor_position:null,train_observations:1000,distinct_hands:900,support_tier:'VERY_HIGH',
      readiness:'READY_FOR_GENERATION',frequency:{of_targeted:.4},source_matrix_key:sourceKey(a2)},
    {context_id:'ctx-vs-4bet',family:'VS_4BET',coverage_group:'VS_4BET_OR_JAM',hero_position:'BB',caller_count:0,limper_count:0,jam_state:true,
      opener_position:null,last_aggressor_position:'CO',train_observations:10,distinct_hands:9,support_tier:'LOW',
      readiness:'DEFERRED',frequency:{of_targeted:.01},source_matrix_key:sourceKey(a3)}
  ]
};

const map={
  'h1\u0000d1':{family:'VS_RFI',context_id:'ctx-vs-rfi'},
  'h5\u0000d5':{family:'VS_4BET',context_id:'ctx-vs-4bet'}
};

const report=Coverage.analyzeCoverage({
  decision_events:events,
  scope:SCOPE,
  minimum_supported_observations:20,
  preflop_train_audit:audit,
  preflop_generation_plan:plan,
  preflop_context_by_decision:map,
  coverage_gap_limit:100
});

assert.equal(report.schema,Coverage.COVERAGE_SCHEMA);
assert.equal(report.scope_key,Coverage.scopeKey(SCOPE));
assert.deepEqual(report.scope,SCOPE);
assert.equal(report.summary.hand_count,5);
assert.equal(report.summary.decision_count,5);
assert.equal(report.summary.supported_count,4);
assert.equal(report.summary.comparable_count,3);
assert.equal(report.summary.covered_count,2);
assert.equal(report.summary.low_support_count,1);
assert.equal(report.summary.unsupported_count,1);
assert.equal(report.summary.non_comparable_count,1);
assert.equal(report.summary.coverage_ratio,.8);
assert.equal(report.summary.comparable_ratio,.6);
assert.deepEqual(report.summary.distinct_hands,['h1','h2','h3','h4','h5']);

function row(d,k){
  const r=report.rows.find(x=>x.dimension===d&&x.key===k);
  assert.ok(r,'missing row '+d+' '+k);
  return r;
}
assert.equal(row('spot_family','COVERED_SPOT').state,'COVERED');
assert.equal(row('spot_family','LOW_SPOT').state,'LOW_SUPPORT');
assert.equal(row('spot_family','UNSUPPORTED_SPOT').state,'UNSUPPORTED');
assert.equal(row('spot_family','NONCOMP_SPOT').state,'NON_COMPARABLE');
assert.equal(row('preflop_context','ctx-missing').state,'ANALYSIS_MISSING');

assert.deepEqual(row('spot_family','COVERED_SPOT').source_refs,[{hand_id:'h1',decision_id:'d1'}]);
assert.equal(row('spot_family','COVERED_SPOT').coverage_ratio,1);
assert.equal(row('spot_family','LOW_SPOT').support_tier,'LOW');
assert.equal(row('spot_family','LOW_SPOT').support_tier_source,'ANALYSIS');
assert.equal(row('spot_family','LOW_SPOT').exclusion_reasons['LOW_SUPPORT:OBSERVATIONS_BELOW_20'],1);
assert.equal(row('spot_family','UNSUPPORTED_SPOT').exclusion_reasons['UNSUPPORTED:NO_MODEL_SUPPORT'],1);
assert.equal(row('spot_family','NONCOMP_SPOT').exclusion_reasons['NON_COMPARABLE:MISSING_COMPARABLE_EV'],1);

const missing=row('preflop_context','ctx-missing');
assert.equal(missing.decision_count,0);
assert.equal(missing.coverage_ratio,null);
assert.equal(missing.support_tier,'VERY_HIGH');
assert.equal(missing.support_tier_source,'TRAIN_ONLY');
assert.equal(missing.train_evidence.train_observations,1000);
assert.equal(missing.train_evidence.context_ids[0],'ctx-missing');
assert.equal(missing.semantics.usable_as_ev_leak,false);
assert.equal(missing.semantics.training_target_eligible,false);

const joined=row('preflop_context','ctx-vs-rfi');
assert.equal(joined.state,'COVERED');
assert.equal(joined.decision_count,1);
assert.equal(joined.train_evidence.train_observations,500);
assert.deepEqual(joined.source_refs,[{hand_id:'h1',decision_id:'d1'}]);

const family=row('preflop_family','VS_RFI');
assert.equal(family.state,'COVERED');
assert.equal(family.train_evidence.context_count,1);
assert.equal(family.train_evidence.train_observations,500);

assert.ok(report.matrix.position.length>0);
assert.ok(report.matrix.action_context.length>0);
assert.ok(report.matrix.sizing_context.length>0);
assert.ok(report.matrix.jam.length>0);
assert.ok(report.matrix.overbet.length>0);
assert.ok(report.matrix.preflop_family.includes(family.row_id));
assert.ok(report.matrix.preflop_context.includes(missing.row_id));

assert.equal(row('jam','JAM').decision_count,2);
assert.equal(row('overbet','OVERBET').decision_count,2);
assert.equal(row('sizing_context','SIZING_ERROR').decision_count,1);

assert.equal(report.preflop_train_evidence.context_count,3);
assert.equal(report.preflop_train_evidence.total_train_observations,1510);
assert.deepEqual(report.preflop_train_evidence.support_tiers,['HIGH','LOW','VERY_HIGH']);
assert.equal(report.semantics.ev_loss_aggregated,false);
assert.deepEqual(report.semantics.states_excluded_from_ev_leaks,
  ['LOW_SUPPORT','UNSUPPORTED','NON_COMPARABLE','ANALYSIS_MISSING']);

for(const r of report.rows){
  if(r.state!=='COVERED')assert.equal(r.semantics.usable_as_ev_leak,false);
}
const json=Coverage.exportCoverageJSON(report,{pretty:false});
assert.equal(json,Coverage.exportCoverageJSON(Coverage.analyzeCoverage({
  decision_events:events,scope:SCOPE,minimum_supported_observations:20,
  preflop_train_audit:audit,preflop_generation_plan:plan,preflop_context_by_decision:map,coverage_gap_limit:100
}),{pretty:false}),'export must be deterministic');
assert.equal(json.includes('1234.56789'),false,'decision EV must not leak into coverage JSON');
assert.equal(json.includes('4321.12345'),false,'decision EV must not leak into coverage JSON');

assert.ok(report.coverage_gaps.length>0);
assert.ok(report.coverage_gaps.some(x=>x.dimension==='preflop_context'&&x.key==='ctx-missing'&&x.state==='ANALYSIS_MISSING'));
for(const gap of report.coverage_gaps)assert.equal(Object.prototype.hasOwnProperty.call(gap,'loss_bb'),false);

const evidence=Coverage.normalizePreflopTrainEvidence(audit,plan);
assert.equal(evidence.schema,Coverage.PREFLOP_EVIDENCE_SCHEMA);
assert.equal(evidence.contexts.length,3);
assert.equal(evidence.contexts.find(x=>x.context_id==='ctx-vs-rfi').train_observations,500);

assert.throws(()=>Coverage.normalizePreflopTrainEvidence(
  audit,{...plan,scope:{...plan.scope,validation_consumed:true}}
),/validation_consumed must be false/);

assert.throws(()=>Coverage.analyzeCoverage({
  decision_events:[events[0],{...events[1],strategy_version:'other'}],
  minimum_supported_observations:20
}),/spans 2/);

assert.throws(()=>Coverage.analyzeCoverage({
  decision_events:[events[0]],scope:{...SCOPE,pack_version:'other'}
}),/declared scope mismatch/);

const byScope=Coverage.analyzeCoverageByScope({
  decision_events:[events[0],{...events[1],strategy_version:'other'}],
  minimum_supported_observations:20
});
assert.equal(byScope.length,2);

const noEvents=Coverage.analyzeCoverage({
  decision_events:[],scope:SCOPE,preflop_train_audit:audit,preflop_generation_plan:plan
});
assert.equal(noEvents.summary.decision_count,0);
assert.equal(noEvents.summary.coverage_ratio,null);
assert.equal(noEvents.summary.analysis_missing_rows,6);

console.log(JSON.stringify({
  status:'PASS',
  schema:Coverage.COVERAGE_SCHEMA,
  states:Coverage.STATES,
  rows:report.rows.length,
  preflop_contexts:report.preflop_train_evidence.context_count
}));
