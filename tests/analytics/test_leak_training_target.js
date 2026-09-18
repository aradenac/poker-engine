'use strict';

const assert=require('node:assert/strict');
const Leak=require('../../src/analytics/leak-analyzer.js');
const Target=require('../../src/analytics/leak-training-target.js');

const ID={
  population_id:'pokerstars_nlhe_100-200_zoom_play_6max_v1',
  pack_id:'zoom-pack@1',
  strategy_id:'custom_ranges_v1',
  strategy_version:'runtime-r1@review-sig-A',
  ev_reference:'review_score_policy_adjusted_incremental_bb'
};

function event(id,overrides={}){
  return {
    hand_id:'h'+id,
    decision_id:'d'+id,
    timestamp:'2026-09-'+String(10+id).padStart(2,'0')+'T12:00:00Z',
    ...ID,
    position:'BTN',street:'PREFLOP',spot_family:'VS_RFI',
    action_played:'CALL',action_recommended:'FOLD',
    played_ev_bb:-1,best_ev_bb:0,uncertainty_bb:.05,
    support:{covered:true,observations:100,source:'reviewScores'},
    comparability:{comparable:true},
    ...overrides
  };
}

const sourceEvents=[
  event(1,{played_ev_bb:-1.5}),
  event(2,{played_ev_bb:-.8}),
  event(3,{action_played:'FOLD',action_recommended:'FOLD',played_ev_bb:0,best_ev_bb:0}),
  event(4,{position:'CO',street:'RIVER',spot_family:'RIVER_FACING_BET',action_played:'BET',action_recommended:'BET',
    played_ev_bb:.2,best_ev_bb:1,played_target_total_bb:20,recommended_target_total_bb:10,played_size_pot_ratio:1.5,recommended_size_pot_ratio:.75,sizing_error:true}),
  event(5,{position:'BB',street:'PREFLOP',spot_family:'VS_4BET',action_played:'SHOVE',action_recommended:'CALL',
    played_ev_bb:-2,best_ev_bb:0,played_is_all_in:true,played_size_pot_ratio:2.2})
];
const report=Leak.analyzeLeaks(sourceEvents);

{
  const target=Target.targetFromLeakReport(report,{dimension:'action_pair',key:'CALL->FOLD',minimum_decisions:2,minimum_scenarios:3});
  assert.equal(target.schema,Target.TARGET_SCHEMA);
  assert.equal(target.identity.population_id,ID.population_id);
  assert.equal(target.identity.pack_id,ID.pack_id);
  assert.equal(target.identity.strategy_id,ID.strategy_id);
  assert.equal(target.identity.strategy_version,ID.strategy_version);
  assert.equal(target.identity.ev_reference,ID.ev_reference);
  assert.deepEqual(target.context,{position:'BTN',street:'PREFLOP',spot_family:'VS_RFI'});
  assert.equal(target.source_pattern.played_action,'CALL');
  assert.equal(target.source_pattern.recommended_action,'FOLD');
  assert.equal(target.source_pattern.sizing_error,null);
  assert.equal(target.source_leak.decisions,2);
  assert.equal(target.source_leak.total_loss_bb,2.3);
  assert.equal(target.source_support.sufficient,true);
  assert.equal(target.minimum_support.scenarios,3);
  assert.deepEqual(target.source_leak.source_refs,[{hand_id:'h1',decision_id:'d1'},{hand_id:'h2',decision_id:'d2'}]);

  const same=Target.targetFromLeakReport(report,{dimension:'action_pair',key:'CALL->FOLD',minimum_decisions:2,minimum_scenarios:3});
  assert.equal(same.target_id,target.target_id,'same leak and support contract must produce a stable target id');

  const criteria=Target.compileScenarioCriteria(target);
  assert.equal(criteria.schema,Target.CRITERIA_SCHEMA);
  assert.equal(criteria.identity.strategy_version,ID.strategy_version);
  assert.equal(criteria.context.position,'BTN');
  assert.equal(criteria.policy.recommended_action,'FOLD');
  assert.equal(criteria.focus.source_played_action,'CALL');
  assert.equal(criteria.coverage.minimum_matching_scenarios,3);

  const scenario={
    schema:Target.SCENARIO_SCHEMA,
    identity:{...ID},
    context:{position:'BTN',street:'PREFLOP',spot_family:'VS_RFI'},
    policy:{recommended_action:'FOLD'},
    focus:{sizing_decision:false,jam_available:false,overbet_available:false},
    supported:true
  };
  assert.equal(Target.scenarioMatchesCriteria(scenario,criteria),true,'scenario must not require the user to repeat CALL');
  assert.equal(Target.scenarioMatchesCriteria({...scenario,identity:{...ID,strategy_version:'other'}},criteria),false);
  assert.equal(Target.scenarioMatchesCriteria({...scenario,context:{...scenario.context,position:'CO'}},criteria),false);
  assert.equal(Target.scenarioMatchesCriteria({...scenario,supported:false},criteria),false);

  const coverage=Target.evaluateScenarioCoverage(target,[
    scenario,
    {...scenario,context:{...scenario.context,street:'FLOP'}},
    {...scenario,supported:false},
    {...scenario,policy:{recommended_action:'CALL'}}
  ]);
  assert.equal(coverage.matching_scenarios,1);
  assert.equal(coverage.supported_matching_scenarios,1);
  assert.equal(coverage.sufficient,false);
  assert.equal(coverage.fallback,'INSUFFICIENT_SUPPORTED_SCENARIOS');

  const sufficient=Target.evaluateScenarioCoverage(target,[scenario,{...scenario},{...scenario}]);
  assert.equal(sufficient.supported_matching_scenarios,3);
  assert.equal(sufficient.sufficient,true);
  assert.equal(sufficient.fallback,null);
}

{
  const weak=Target.targetFromLeakReport(report,{dimension:'action_pair',key:'CALL->FOLD',minimum_decisions:3});
  assert.equal(weak.source_support.observed_decisions,2);
  assert.equal(weak.source_support.sufficient,false);
}

{
  const sizing=Target.targetFromLeakReport(report,{dimension:'error_type',key:'SIZING_ERROR'});
  assert.equal(sizing.source_pattern.sizing_error,true);
  assert.equal(sizing.context.position,'CO');
  assert.equal(sizing.context.street,'RIVER');
  assert.equal(sizing.source_pattern.recommended_action,'BET');
  const criteria=Target.compileScenarioCriteria(sizing);
  assert.equal(criteria.focus.sizing_decision,true);
  const scenario={
    identity:{...ID},context:{position:'CO',street:'RIVER',spot_family:'RIVER_FACING_BET'},
    policy:{recommended_action:'BET'},focus:{sizing_decision:true},supported:true
  };
  assert.equal(Target.scenarioMatchesCriteria(scenario,criteria),true);
  assert.equal(Target.scenarioMatchesCriteria({...scenario,focus:{sizing_decision:false}},criteria),false);
}

{
  const jam=Target.targetFromLeakReport(report,{dimension:'jam',key:'JAM'});
  assert.equal(jam.source_pattern.jam,true);
  assert.equal(jam.context.position,'BB');
  assert.equal(jam.context.spot_family,'VS_4BET');
  assert.equal(Target.compileScenarioCriteria(jam).focus.jam_available,true);
}

{
  const overbet=Target.targetFromLeakReport(report,{dimension:'overbet',key:'OVERBET'});
  assert.equal(overbet.source_pattern.overbet,true);
  assert.equal(overbet.source_leak.decisions,2,'both sizing overbet and shove overbet are represented by the analyzer tag');
}

{
  const direct=Target.buildTrainingTarget({
    identity:ID,
    context:{position:'BB',street:'PREFLOP',spot_family:'VS_RFI'},
    source_pattern:{played_action:'CALL',recommended_action:'FOLD'},
    source_leak:{dimension:'position',key:'BB',decisions:0,source_refs:[]}
  });
  assert.equal(direct.minimum_support.decisions,1);
  assert.equal(direct.minimum_support.scenarios,1);
  assert.equal(direct.source_support.sufficient,false);
}

{
  const target=Target.targetFromLeakReport(report,{dimension:'action_pair',key:'CALL->FOLD'});
  const session=[
    event(11,{hand_id:'s1',decision_id:'s1d',timestamp:'2026-10-01T10:00:00Z',played_ev_bb:-1,best_ev_bb:0}),
    event(12,{hand_id:'s2',decision_id:'s2d',timestamp:'2026-10-01T10:01:00Z',action_played:'FOLD',played_ev_bb:0,best_ev_bb:0}),
    event(13,{hand_id:'s3',decision_id:'s3d',timestamp:'2026-10-01T10:02:00Z',played_ev_bb:.9,best_ev_bb:1,within_noise:true}),
    event(14,{hand_id:'s4',decision_id:'s4d',timestamp:'2026-10-01T10:03:00Z',played_ev_bb:-.6,best_ev_bb:0}),
    event(15,{hand_id:'s5',decision_id:'s5d',timestamp:'2026-10-01T10:04:00Z',played_ev_bb:-.2,best_ev_bb:0}),
    event(16,{hand_id:'s6',decision_id:'s6d',timestamp:'2026-10-01T10:05:00Z',played_ev_bb:null,best_ev_bb:null,
      support:{covered:false,reason:'NO_MODEL_SUPPORT'},comparability:{comparable:false,reason:'NO_MODEL_SUPPORT'}}),
    event(17,{hand_id:'s7',decision_id:'s7d',timestamp:'2026-10-01T10:06:00Z',played_ev_bb:null,best_ev_bb:null,
      comparability:{comparable:false,reason:'NO_COMPARABLE_EV'}}),
    event(18,{hand_id:'other-context',decision_id:'other-context',timestamp:'2026-10-01T10:07:00Z',position:'CO',played_ev_bb:-8,best_ev_bb:0}),
    event(19,{hand_id:'other-version',decision_id:'other-version',timestamp:'2026-10-01T10:08:00Z',strategy_version:'other',played_ev_bb:-9,best_ev_bb:0})
  ];
  const summary=Target.summarizeTargetedSession(target,session,{minimum_trend_decisions:4});
  assert.equal(summary.schema,Target.SESSION_SCHEMA);
  assert.equal(summary.summary.decisions_matching_context,7,'identity/context mismatches must be excluded');
  assert.equal(summary.summary.decisions_eligible,5,'unsupported and non-comparable decisions remain visible but do not enter loss');
  assert.equal(summary.summary.total_delta_ev_loss_bb,1.8,'within-noise nominal gap must not be attributed');
  assert.equal(summary.summary.nominal_delta_ev_loss_bb,1.9);
  assert.equal(summary.summary.average_delta_ev_loss_bb,.36);
  assert.equal(summary.summary.loss_bb_per_100_decisions,36);
  assert.equal(summary.summary.within_noise_decisions,1);
  assert.equal(summary.summary.unsupported_decisions,1);
  assert.equal(summary.summary.non_comparable_decisions,1);
  assert.equal(summary.summary.source_played_action_recurrences,4);
  assert.ok(summary.summary.within_session_change);
  assert.equal(summary.summary.within_session_change.interpretation,'DESCRIPTIVE_WITHIN_SESSION_ONLY');
  assert.equal(summary.summary.within_session_change_reason,null);
  assert.equal(summary.source_refs.length,5);

  const small=Target.summarizeTargetedSession(target,session.slice(0,3),{minimum_trend_decisions:4});
  assert.equal(small.summary.within_session_change,null);
  assert.equal(small.summary.within_session_change_reason,'INSUFFICIENT_SAMPLE_FOR_WITHIN_SESSION_CHANGE');
}

{
  const target=Target.targetFromLeakReport(report,{dimension:'action_pair',key:'CALL->FOLD'});
  const noEligible=Target.summarizeTargetedSession(target,[
    event(31,{played_ev_bb:null,best_ev_bb:null,support:{covered:false,reason:'X'},comparability:{comparable:false,reason:'X'}})
  ]);
  assert.equal(noEligible.summary.decisions_eligible,0);
  assert.equal(noEligible.summary.loss_bb_per_100_decisions,null);
  assert.equal(noEligible.summary.average_delta_ev_loss_bb,null);
}

assert.throws(()=>Target.buildTrainingTarget({identity:{...ID,population_id:''},source_leak:{dimension:'position',key:'BB'}}),/population_id is required/);
assert.throws(()=>Target.buildTrainingTarget({identity:ID,source_leak:{dimension:'unknown',key:'x'}}),/unsupported/);
assert.throws(()=>Target.targetFromLeakReport(report,{dimension:'position',key:'UTG'}),/leak group not found/);

console.log(JSON.stringify({status:'PASS',target_schema:Target.TARGET_SCHEMA,session_schema:Target.SESSION_SCHEMA}));
