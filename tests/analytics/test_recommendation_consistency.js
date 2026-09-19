'use strict';

const assert=require('node:assert/strict');
const Audit=require('../../src/analytics/recommendation-consistency.js');

const ID={
  population_id:'pokerstars_nlhe_100-200_zoom_play_6max_v1',
  pack_id:'fixture-pack',
  pack_version:'pack-v1',
  strategy_id:'fixture-strategy',
  strategy_version:'strategy-v1',
  strategy_sha256:'a'.repeat(64),
  decision_source_sha256:'b'.repeat(64),
  ev_reference:'decision_point_incremental_bb'
};

function uncertainty(se=.05){
  return {monte_carlo:{standard_error_bb:se,samples:1000,method:'synthetic'}};
}
function alt(id,action,target,cost,ev,{comparable=true,se=.05}={}){
  return {
    id,action,
    target_sizing:target==null?null:{target_total_bb:target,bet_to_bb:target},
    incremental_cost_bb:cost,
    ev_bb:ev,
    uncertainty:uncertainty(se),
    support:{observations:100,source:'SYNTHETIC'},
    comparable,
    comparability_reason:comparable?null:'FIXTURE_NON_COMPARABLE'
  };
}
function baseDecision(overrides={}){
  const alternatives=[
    alt('fold','FOLD',null,0,0),
    alt('call','CALL',3,2,2.0),
    alt('jam','JAM',100,99,1.2)
  ];
  const d={
    schema:'poker-preflop-decision/v1',
    contract_profile:'CANONICAL_RUNTIME_DECISION_V1',
    decision_id:'decision-1',
    hand_id:'hand-1',
    timestamp:'2026-09-19T01:00:00Z',
    street:'PREFLOP',
    public_state_fingerprint:'fixture-public',
    public_state:{
      actor:'BB',legal_actions:['FOLD','CALL','RAISE'],
      to_call_bb:2,current_bet_bb:3,actor_contribution_bb:1,actor_remaining_bb:99
    },
    context_id:'ctx-vs-rfi',
    hero_position:'BB',
    effective_stack_bb:100,
    pot_before_action_bb:6,
    facing_action:'RAISE',
    facing_context:'VS_RFI',
    played_action:'CALL',
    played_target_sizing:{target_total_bb:3,bet_to_bb:3},
    recommended_action:'CALL',
    recommended_target_sizing:{target_total_bb:3,bet_to_bb:3},
    incremental_cost_bb:2,
    recommended_ev_bb:2.0,
    played_ev_bb:2.0,
    delta_ev_bb:0,
    ev_comparable:true,
    alternatives,
    coverage_state:'COVERED',
    support_tier:'HIGH',
    support:{observations:100,source:'SYNTHETIC'},
    recommendation_admissibility:{
      admissible:true,status:'ADMISSIBLE',default_advice:true,reason_codes:[],
      source_guidance_schema:'poker-preflop-guidance/v1',
      source_recommendation_state:'PROMOTED',
      selected_alternative_id:'call'
    },
    reason_codes:[],
    identity:{...ID},
    information_boundary:{
      public_only_fingerprint:true,future_cards_consumed:false,opponent_hole_cards_consumed:false,
      ignored_sensitive_fields:[],fingerprint_excludes_board_and_private_cards:true
    },
    source:{split:'SYNTHETIC',source:'fixture'}
  };
  return {...d,...overrides};
}
function surfaces(d){
  return {
    feed:structuredClone(d),
    detail:structuredClone(d),
    replayer:structuredClone(d),
    trainer:structuredClone(d),
    review:structuredClone(d)
  };
}
function record(d=baseDecision(), surfaceOverride=null, source=null){
  const s=surfaces(d);
  if(surfaceOverride)surfaceOverride(s);
  return {decision:d,surfaces:s,source:source||{split:'SYNTHETIC',source:'fixture'}};
}
function types(row){return row.violations.map(x=>x.type);}
function byType(report,type){
  return report.violations.by_type.find(x=>x.key===type)||null;
}

{
  const d=baseDecision();
  const row=Audit.auditDecision(record(d));
  assert.equal(row.status,'PASS');
  assert.equal(row.counts.certain,0);
  assert.equal(row.counts.within_noise,0);
  assert.equal(row.surface_parity.complete,true);
  assert.deepEqual(row.surface_parity.present_surfaces,['feed','detail','replayer','trainer','review']);
  assert.equal(row.recommendation_tuple.action,'CALL');
  assert.equal(row.recommendation_tuple.sizing.target_total_bb,3);
  assert.equal(row.recommendation_tuple.incremental_cost_bb,2);
  assert.equal(row.recommendation_tuple.ev_bb,2);
}

{
  // Historical class: feed says JAM while CALL is the canonical/max-EV recommendation.
  const d=baseDecision();
  const row=Audit.auditDecision(record(d,s=>{
    s.feed.recommended_action='JAM';
    s.feed.recommended_target_sizing={target_total_bb:100,bet_to_bb:100};
    s.feed.incremental_cost_bb=99;
    s.feed.recommended_ev_bb=1.2;
  }));
  assert.equal(row.status,'FAIL');
  assert.ok(types(row).includes('SURFACE_DIVERGENCE'));
  assert.ok(types(row).includes('NON_MAX_EV_RECOMMENDATION'));
  const feed=row.surface_parity.surfaces.feed;
  assert.ok(feed.violations.includes('SURFACE_DIVERGENCE'));
  assert.ok(feed.violations.includes('NON_MAX_EV_RECOMMENDATION'));
}

{
  const d=baseDecision({
    recommended_action:'JAM',
    recommended_target_sizing:{target_total_bb:3,bet_to_bb:3},
    incremental_cost_bb:2,
    recommended_ev_bb:2
  });
  const row=Audit.auditDecision(record(d));
  assert.equal(row.status,'FAIL');
  assert.ok(types(row).includes('ACTION_EV_MISMATCH'));
}

{
  const d=baseDecision({
    recommended_target_sizing:{target_total_bb:100,bet_to_bb:100},
    incremental_cost_bb:99
  });
  const row=Audit.auditDecision(record(d));
  assert.equal(row.status,'FAIL');
  assert.ok(types(row).includes('SIZING_EV_MISMATCH'));
}

{
  const d=baseDecision({recommended_ev_bb:1.2});
  const row=Audit.auditDecision(record(d));
  assert.equal(row.status,'FAIL');
  assert.ok(types(row).includes('RECOMMENDED_EV_MISMATCH'));
}

{
  const d=baseDecision({
    recommended_action:'JAM',
    recommended_target_sizing:{target_total_bb:100,bet_to_bb:100},
    incremental_cost_bb:99,
    recommended_ev_bb:1.2,
    recommendation_admissibility:{
      ...baseDecision().recommendation_admissibility,
      selected_alternative_id:'jam'
    }
  });
  const row=Audit.auditDecision(record(d));
  assert.equal(row.status,'FAIL');
  const f=row.violations.find(x=>x.type==='NON_MAX_EV_RECOMMENDATION'&&x.certainty==='CERTAIN');
  assert.ok(f);
  assert.equal(f.details.best_alternative_id,'call');
  assert.equal(f.details.selected_alternative_id,'jam');
  assert.equal(f.details.ev_gap_bb,.8);
}

{
  const d=baseDecision({incremental_cost_bb:99});
  const row=Audit.auditDecision(record(d));
  assert.equal(row.status,'FAIL');
  assert.ok(types(row).includes('INCREMENTAL_COST_MISMATCH'));
  const f=row.violations.find(x=>x.type==='INCREMENTAL_COST_MISMATCH'&&x.details.expected_incremental_cost_bb===2);
  assert.ok(f);
}

{
  const d=baseDecision();
  const row=Audit.auditDecision(record(d,s=>{
    s.detail.decision_id='other-decision';
    s.trainer.identity={...s.trainer.identity,strategy_version:'wrong-version'};
  }));
  assert.equal(row.status,'FAIL');
  assert.ok(types(row).includes('SURFACE_DIVERGENCE'));
  assert.ok(types(row).includes('IDENTITY_MISMATCH'));
}

{
  const d=baseDecision({
    recommended_action:null,
    recommended_target_sizing:null,
    incremental_cost_bb:null,
    recommended_ev_bb:null,
    alternatives:[],
    support:null,
    recommendation_admissibility:{
      admissible:false,status:'LOW_SUPPORT',default_advice:false,reason_codes:['LOW_SUPPORT'],
      source_guidance_schema:'poker-preflop-guidance/v1',source_recommendation_state:'PROMOTED',
      selected_alternative_id:null
    }
  });
  const row=Audit.auditDecision(record(d));
  assert.equal(row.status,'PASS','valid fail-closed decision with five matching surfaces is coherent');
  assert.equal(types(row).includes('FAIL_CLOSED_RECOMMENDATION_PRESENT'),false);

  const bad=structuredClone(d);
  bad.recommended_action='CALL';
  bad.recommended_target_sizing={target_total_bb:3,bet_to_bb:3};
  bad.incremental_cost_bb=2;
  bad.recommended_ev_bb=2;
  const badRow=Audit.auditDecision(record(bad));
  assert.equal(badRow.status,'FAIL');
  assert.ok(types(badRow).includes('FAIL_CLOSED_RECOMMENDATION_PRESENT'));
}

{
  // Within-noise non-max is reported but does not become a certain FAIL.
  const d=baseDecision({
    recommended_ev_bb:1.95,
    alternatives:[
      alt('fold','FOLD',null,0,0),
      alt('call','CALL',3,2,1.95,{se:.1}),
      alt('jam','JAM',100,99,2.0,{se:.1})
    ]
  });
  const row=Audit.auditDecision(record(d),{
    ev_tolerance_bb:1e-6,
    within_noise_standard_error_multiplier:2
  });
  assert.equal(row.status,'INCONCLUSIVE');
  const f=row.violations.find(x=>x.type==='NON_MAX_EV_RECOMMENDATION');
  assert.ok(f);
  assert.equal(f.certainty,'WITHIN_NOISE');
}

{
  // Non-comparable selected evidence is distinct from a certain inconsistency.
  const d=baseDecision({
    alternatives:[
      alt('fold','FOLD',null,0,0),
      alt('call','CALL',3,2,2.0,{comparable:false}),
      alt('jam','JAM',100,99,5.0,{comparable:false})
    ]
  });
  const row=Audit.auditDecision(record(d));
  assert.equal(row.status,'INCONCLUSIVE');
  const f=row.violations.find(x=>x.type==='NON_MAX_EV_RECOMMENDATION');
  assert.ok(f);
  assert.equal(f.certainty,'NOT_COMPARABLE');
}

{
  // Exact tie uses deterministic alternative-id ascending policy.
  const d=baseDecision({
    alternatives:[
      alt('a-call','CALL',3,2,2.0),
      alt('z-call','CALL',3,2,2.0)
    ],
    recommendation_admissibility:{
      ...baseDecision().recommendation_admissibility,
      selected_alternative_id:'z-call'
    }
  });
  const row=Audit.auditDecision(record(d),{tie_break:'ALTERNATIVE_ID_ASC'});
  assert.equal(row.status,'FAIL');
  const f=row.violations.find(x=>x.type==='TIE_POLICY_MISMATCH');
  assert.ok(f);
  assert.equal(f.details.expected_alternative_id,'a-call');
  assert.deepEqual(f.details.tied_alternative_ids,['a-call','z-call']);
}

{
  const d1=baseDecision({decision_id:'decision-a',hand_id:'hand-a',context_id:'ctx-a'});
  const d2=baseDecision({
    decision_id:'decision-b',hand_id:'hand-b',context_id:'ctx-b',
    recommended_action:'JAM',
    recommended_target_sizing:{target_total_bb:100,bet_to_bb:100},
    incremental_cost_bb:99,
    recommended_ev_bb:1.2,
    recommendation_admissibility:{...baseDecision().recommendation_admissibility,selected_alternative_id:'jam'}
  });
  const input=[record(d1),record(d2)];
  const a=Audit.analyzeConsistency({records:input});
  const b=Audit.analyzeConsistency({records:[...input].reverse()});
  assert.deepEqual(a,b);
  assert.equal(a.report_hash,b.report_hash);
  assert.equal(Audit.exportJSON(a,{pretty:false}),Audit.exportJSON(b,{pretty:false}));
  assert.equal(a.summary.decision_count,2);
  assert.equal(a.summary.pass_count,1);
  assert.equal(a.summary.fail_count,1);
  assert.ok(byType(a,'NON_MAX_EV_RECOMMENDATION'));
  assert.equal(byType(a,'NON_MAX_EV_RECOMMENDATION').decision_count,1);
  assert.deepEqual(a.source_refs,[
    {hand_id:'hand-a',decision_id:'decision-a'},
    {hand_id:'hand-b',decision_id:'decision-b'}
  ]);
  assert.equal(a.semantics.scientific_effect,'NONE_VALIDATION_ONLY');
  assert.equal(a.semantics.test_consumed,false);
  assert.equal(a.semantics.issue_108_consumed,false);
  assert.equal(a.semantics.optimization_performed,false);
  assert.equal(a.semantics.promotion_performed,false);
  assert.equal(a.semantics.central_ui_modified,false);
}

{
  const d=baseDecision();
  const row=Audit.auditDecision({decision:d,source:{split:'SYNTHETIC'}});
  assert.equal(row.status,'INCONCLUSIVE','missing surface snapshots makes parity not fully evaluated');
  assert.equal(row.surface_parity.complete,false);
}

{
  assert.throws(()=>Audit.auditDecision(record(baseDecision(),null,{split:'TEST'})),/TEST consumption is forbidden/);
  assert.throws(()=>Audit.auditDecision(record(baseDecision(),null,{issue:108})),/#108 consumption is forbidden/);
  assert.throws(()=>Audit.auditDecision(record(baseDecision(),null,{optimization:true})),/optimization output is forbidden/);
}

console.log(JSON.stringify({
  status:'PASS',
  report_schema:Audit.REPORT_SCHEMA,
  decision_schema:Audit.DECISION_SCHEMA,
  policy_schema:Audit.POLICY_SCHEMA,
  violations:Audit.VIOLATION_TYPES
}));
