'use strict';

const assert=require('node:assert/strict');
const Leak=require('../../src/analytics/leak-analyzer.js');
const Adapter=require('../../src/analytics/review-score-adapter.js');
const Inbox=require('../../src/analytics/review-inbox.js');
const Target=require('../../src/analytics/leak-training-target.js');
const State=require('../../src/analytics/analysis-state.js');
const Dashboard=require('../../src/analytics/review-dashboard.js');

const SCOPE={
  population_id:'pokerstars_nlhe_100-200_zoom_play_6max_v1',
  pack_id:'zoom-pack@1',
  strategy_id:'custom_ranges_v1',
  strategy_version:'runtime-r1',
  ev_reference:Adapter.DEFAULT_EV_REFERENCE
};

const HH1=`PokerStars Zoom Hand #100001: Hold'em No Limit (100/200) - 2026/09/18 21:15:00 CET
Table 'Alpha' 6-max Seat #6 is the button
Seat 1: SBPlayer (20000 in chips)
Seat 2: BBPlayer (20000 in chips)
Seat 3: LJPlayer (20000 in chips)
Seat 4: HJPlayer (20000 in chips)
Seat 5: COPlayer (20000 in chips)
Seat 6: Hero (2000 in chips)
SBPlayer: posts small blind 100
BBPlayer: posts big blind 200
*** HOLE CARDS ***
Dealt to Hero [As Kd]
LJPlayer: folds
HJPlayer: folds
COPlayer: folds
Hero: raises 400 to 600
SBPlayer: folds
BBPlayer: calls 400
*** FLOP *** [Ah 7c 2d]
BBPlayer: checks
Hero: bets 1400 and is all-in
BBPlayer: calls 1400
*** SUMMARY ***
Total pot 4100 | Rake 0
`;

const HH2=`PokerStars Zoom Hand #100002: Hold'em No Limit (100/200) - 2026/09/18 21:16:00 CET
Table 'Beta' 6-max Seat #6 is the button
Seat 1: SB2 (20000 in chips)
Seat 2: BB2 (20000 in chips)
Seat 3: LJ2 (20000 in chips)
Seat 4: HJ2 (20000 in chips)
Seat 5: CO2 (20000 in chips)
Seat 6: Hero (20000 in chips)
SB2: posts small blind 100
BB2: posts big blind 200
*** HOLE CARDS ***
Dealt to Hero [Qc Jc]
LJ2: folds
HJ2: folds
CO2: raises 400 to 400
Hero: calls 400
SB2: folds
BB2: folds
*** FLOP *** [Qh 8d 3s]
CO2: checks
Hero: checks
*** SUMMARY ***
Total pot 1100 | Rake 0
`;

const HH3=`PokerStars Zoom Hand #100003: Hold'em No Limit (100/200) - 2026/09/18 21:17:00 CET
Table 'Gamma' 6-max Seat #6 is the button
Seat 1: SB3 (20000 in chips)
Seat 2: BB3 (20000 in chips)
Seat 3: LJ3 (20000 in chips)
Seat 4: HJ3 (20000 in chips)
Seat 5: CO3 (20000 in chips)
Seat 6: Hero (20000 in chips)
SB3: posts small blind 100
BB3: posts big blind 200
*** HOLE CARDS ***
Dealt to Hero [Ad Td]
LJ3: folds
HJ3: folds
CO3: folds
Hero: raises 400 to 600
SB3: folds
BB3: calls 400
*** FLOP *** [Tc 8c 4h]
BB3: checks
Hero: bets 800
BB3: calls 800
*** TURN *** [Tc 8c 4h] [2s]
BB3: checks
Hero: bets 1600
BB3: calls 1600
*** SUMMARY ***
Total pot 6100 | Rake 0
`;

function heroSteps(raw){
  const h=Adapter.parseStoredHand(raw,'fixture.txt');
  return {hand:h,steps:h.steps.filter(s=>s.player==='Hero')};
}
const p1=heroSteps(HH1),p2=heroSteps(HH2),p3=heroSteps(HH3);
const h1raise=p1.steps.find(s=>s.street==='PREFLOP'&&s.actionType==='raise');
const h1bet=p1.steps.find(s=>s.street==='FLOP'&&s.actionType==='bet');
const h2call=p2.steps.find(s=>s.street==='PREFLOP'&&s.actionType==='call');
const h2check=p2.steps.find(s=>s.street==='FLOP'&&s.actionType==='check');
const h3raise=p3.steps.find(s=>s.street==='PREFLOP'&&s.actionType==='raise');
const h3flop=p3.steps.find(s=>s.street==='FLOP'&&s.actionType==='bet');
const h3turn=p3.steps.find(s=>s.street==='TURN'&&s.actionType==='bet');
for(const s of [h1raise,h1bet,h2call,h2check,h3raise,h3flop,h3turn])assert.ok(s);

const reviewScores={
  '100001':{
    handId:'100001',signature:'sig-A',complete:true,analyzableDecisions:2,finishedDecisions:2,details:[
      {stepIndex:h1raise.stepIndex,lossBB:.5,rawLossBB:.5,chosenEV:.5,bestEV:1,bestLabel:'CALL',withinNoise:false,comparable:true,
       simContext:{potType:'UNOPENED',preflopRole:'RFI',relativePosition:'IP'}},
      {stepIndex:h1bet.stepIndex,lossBB:2,rawLossBB:2,chosenEV:-1,bestEV:1,bestLabel:'BET 4 BB',bestCostBB:4,withinNoise:false,comparable:true,
       simContext:{potType:'SRP',preflopRole:'PFR',relativePosition:'IP'}}
    ]
  },
  '100002':{
    handId:'100002',signature:'sig-A',complete:true,analyzableDecisions:2,finishedDecisions:2,details:[
      {stepIndex:h2call.stepIndex,lossBB:0,rawLossBB:0,chosenEV:.5,bestEV:.5,bestLabel:'CALL',withinNoise:false,comparable:true,
       simContext:{potType:'SRP',preflopRole:'CALLER',relativePosition:'IP'}},
      {stepIndex:h2check.stepIndex,lossBB:0,rawLossBB:.05,chosenEV:.95,bestEV:1,bestLabel:'BET',withinNoise:true,comparable:true,
       simContext:{potType:'SRP',preflopRole:'CALLER',relativePosition:'IP'}}
    ]
  },
  '100003':{
    handId:'100003',signature:'sig-A',complete:false,analyzableDecisions:3,finishedDecisions:2,details:[
      {stepIndex:h3raise.stepIndex,lossBB:0,rawLossBB:0,chosenEV:.8,bestEV:.8,bestLabel:'RAISE',withinNoise:false,comparable:true,
       simContext:{potType:'UNOPENED',preflopRole:'RFI',relativePosition:'IP'}},
      {stepIndex:h3flop.stepIndex,lossBB:.5,rawLossBB:.5,chosenEV:.3,bestEV:.8,bestLabel:'BET 2 BB',bestCostBB:2,withinNoise:false,comparable:true,
       simContext:{potType:'SRP',preflopRole:'PFR',relativePosition:'IP'}}
    ]
  }
};

const hhSources=[{name:'all.txt',content:[HH1,HH2,HH3].join('\n')}];
const userMetadata=Inbox.setReviewed({},'100002',true,'2026-09-19T00:10:00Z');

const dashboard=Dashboard.buildReviewDashboard({
  reviewScores,hhSources,scope:SCOPE,user_metadata:userMetadata,
  top_leaks_limit:3,training_min_decisions:1,training_min_scenarios:2
});

assert.equal(dashboard.schema,Dashboard.DASHBOARD_SCHEMA);
assert.equal(dashboard.state,Dashboard.EMPTY_STATES.READY);
assert.equal(dashboard.analysis_state.state,State.ANALYSIS_STATES.ANALYSE_DISPONIBLE,'READY derives ANALYSE_DISPONIBLE from the shared taxonomy');
assert.equal(dashboard.analysis_state_label,'Analyse disponible');
assert.equal(State.isAnalysisState(dashboard.analysis_state),true,'dashboard.analysis_state must conform to poker-analysis-state/v1');
assert.equal(dashboard.analysis_state.reason_codes.includes('READY'),true,'the legacy empty state stays a secondary technical reason');
assert.match(dashboard.scope.strategy_version,/runtime-r1@sig-A$/);
assert.equal(dashboard.metrics.hands_loaded,3);
assert.equal(dashboard.metrics.hands_with_review_score,3);
assert.equal(dashboard.metrics.hands_in_scope,3);
assert.equal(dashboard.metrics.hands_incomplete,1);
assert.equal(dashboard.metrics.decisions_analyzed,6);
assert.equal(dashboard.metrics.decisions_to_review,3);
assert.equal(dashboard.metrics.total_ev_loss_bb,3);
assert.equal(dashboard.metrics.nominal_ev_loss_bb,3.05);
assert.equal(dashboard.metrics.source_refs.length,3);

assert.ok(dashboard.top_leaks.length>=1);
assert.equal(dashboard.top_leaks[0].dimension,'spot_family');
assert.equal(dashboard.top_leaks[0].key,'SRP|PFR|IP');
assert.equal(dashboard.top_leaks[0].total_loss_bb,2.5);
assert.equal(dashboard.top_leaks[0].decisions,2);

assert.equal(dashboard.priority.hand.hand_id,'100001');
assert.equal(dashboard.priority.hand.total_loss_bb,2.5);
assert.equal(dashboard.priority.decision.decision_id,'review:100001:'+h1bet.stepIndex);
assert.equal(dashboard.priority.decision.loss_bb,2);

assert.equal(dashboard.ctas.review.schema,Dashboard.CTA_SCHEMA);
assert.equal(dashboard.ctas.review.enabled,true);
assert.equal(dashboard.ctas.review.target.hand_id,'100001');
assert.equal(dashboard.ctas.review.target.decision_id,'review:100001:'+h1bet.stepIndex);
assert.equal(dashboard.ctas.review.target.step_index,h1bet.stepIndex);

assert.equal(dashboard.ctas.leak.enabled,true);
assert.equal(dashboard.ctas.leak.target.scope_key,dashboard.scope_key);
assert.equal(dashboard.ctas.leak.target.dimension,'spot_family');
assert.equal(dashboard.ctas.leak.target.key,'SRP|PFR|IP');

assert.equal(dashboard.ctas.training.enabled,true);
assert.equal(dashboard.ctas.training.target.schema,Target.TARGET_SCHEMA);
assert.equal(dashboard.ctas.training.target.source_leak.dimension,'spot_family');
assert.equal(dashboard.ctas.training.target.source_leak.key,'SRP|PFR|IP');
assert.equal(dashboard.ctas.training.target.minimum_support.scenarios,2);

const reconstructed=dashboard.metrics.source_refs.map(r=>{
  const adapted=Adapter.adaptPersistedReviewData({reviewScores,hhSources,scope:SCOPE});
  return adapted.events.find(e=>e.hand_id===r.hand_id&&e.decision_id===r.decision_id);
}).reduce((s,e)=>s+(e?e.ev.attributed_loss_bb:0),0);
assert.equal(Math.round(reconstructed*1e9)/1e9,dashboard.metrics.total_ev_loss_bb,'dashboard EV must be reconstructible from source refs');

{
  const strict=Dashboard.buildReviewDashboard({
    reviewScores,hhSources,scope:SCOPE,user_metadata:userMetadata,
    training_min_decisions:3
  });
  assert.equal(strict.ctas.training.enabled,false);
  assert.equal(strict.ctas.training.reason,'INSUFFICIENT_SOURCE_SUPPORT');
}

{
  const zeroScores={
    '100002':reviewScores['100002']
  };
  const d=Dashboard.buildReviewDashboard({reviewScores:zeroScores,hhSources:[{name:'one.txt',content:HH2}],scope:SCOPE,user_metadata:{}});
  assert.equal(d.metrics.total_ev_loss_bb,0);
  assert.equal(d.metrics.decisions_to_review,0);
  assert.equal(d.state,Dashboard.EMPTY_STATES.NO_SIGNIFICANT_LOSS);
  assert.equal(d.analysis_state.state,State.ANALYSIS_STATES.ANALYSE_DISPONIBLE,'NO_SIGNIFICANT_LOSS derives ANALYSE_DISPONIBLE');
  assert.equal(d.analysis_state_label,'Analyse disponible');
  assert.equal(State.isAnalysisState(d.analysis_state),true);
  assert.equal(d.ctas.leak.enabled,false);
  assert.equal(d.ctas.training.enabled,false);
  assert.equal(d.ctas.review.enabled,true);
}

{
  const d=Dashboard.buildReviewDashboard({reviewScores:{},hhSources:[],scope:SCOPE,user_metadata:{}});
  assert.equal(d.state,Dashboard.EMPTY_STATES.NO_HANDS);
  assert.equal(d.analysis_state.state,State.ANALYSIS_STATES.DONNEES_INSUFFISANTES,'NO_HANDS derives DONNEES_INSUFFISANTES');
  assert.equal(d.analysis_state_label,'Données insuffisantes');
  assert.deepEqual(d.analysis_state.reason_codes,['NO_HANDS'],'technical reason codes stay in the secondary analysis_state field');
  assert.equal(State.isAnalysisState(d.analysis_state),true);
  assert.equal(d.metrics.hands_loaded,0);
  assert.equal(d.metrics.decisions_analyzed,0);
  assert.equal(d.ctas.review.enabled,false);
  assert.equal(d.scope.strategy_version,'runtime-r1','empty dashboard must preserve runtime scope version exactly');
}

{
  const d=Dashboard.buildReviewDashboard({reviewScores:{},hhSources:[{name:'one.txt',content:HH1}],scope:SCOPE,user_metadata:{}});
  assert.equal(d.state,Dashboard.EMPTY_STATES.ANALYSIS_PENDING);
  assert.equal(d.analysis_state.state,State.ANALYSIS_STATES.CALCUL_EN_COURS,'ANALYSIS_PENDING derives CALCUL_EN_COURS');
  assert.equal(d.analysis_state_label,'Calcul en cours');
  assert.equal(d.analysis_state.computational_status,'PENDING');
  assert.deepEqual(d.analysis_state.reason_codes,['ANALYSIS_PENDING']);
  assert.equal(State.isAnalysisState(d.analysis_state),true);
  assert.equal(d.metrics.hands_loaded,1);
  assert.equal(d.metrics.hands_with_review_score,0);
}

{
  const incompleteOnly={
    '100003':reviewScores['100003']
  };
  const d=Dashboard.buildReviewDashboard({reviewScores:incompleteOnly,hhSources:[{name:'one.txt',content:HH3}],scope:SCOPE,user_metadata:{}});
  assert.equal(d.metrics.hands_incomplete,1);
  assert.equal(d.metrics.decisions_analyzed,2);
  assert.equal(d.metrics.decisions_to_review,1);
  assert.equal(d.state,Dashboard.EMPTY_STATES.READY,'known attributable loss can still make an incomplete inbox actionable');
  assert.equal(d.analysis_state.state,State.ANALYSIS_STATES.ANALYSE_DISPONIBLE);
}

// #393 T4: ANALYSIS_INCOMPLETE is disambiguated by cause. An incomplete scope
// whose comparable decisions exist but carry no attributable loss is a partial
// analysis; one without any analyzable decision is a support shortage.
{
  const partialScores=JSON.parse(JSON.stringify(reviewScores));
  partialScores['100003'].details=partialScores['100003'].details.map(x=>({...x,lossBB:0,rawLossBB:0}));
  const d=Dashboard.buildReviewDashboard({reviewScores:{'100003':partialScores['100003']},hhSources:[{name:'one.txt',content:HH3}],scope:SCOPE,user_metadata:{}});
  assert.equal(d.state,Dashboard.EMPTY_STATES.ANALYSIS_INCOMPLETE);
  assert.ok(d.metrics.decisions_analyzed>0);
  assert.equal(d.metrics.decisions_to_review,0);
  assert.equal(d.analysis_state.state,State.ANALYSIS_STATES.ANALYSE_PARTIELLE,'incomplete with analyzable decisions derives ANALYSE_PARTIELLE');
  assert.equal(d.analysis_state_label,'Analyse partielle');
  assert.deepEqual(d.analysis_state.reason_codes,['ANALYSIS_INCOMPLETE']);
  assert.equal(State.isAnalysisState(d.analysis_state),true);

  const supportScores=JSON.parse(JSON.stringify(reviewScores));
  supportScores['100003'].details=supportScores['100003'].details.map(x=>({...x,comparable:false}));
  const s=Dashboard.buildReviewDashboard({reviewScores:{'100003':supportScores['100003']},hhSources:[{name:'one.txt',content:HH3}],scope:SCOPE,user_metadata:{}});
  assert.equal(s.state,Dashboard.EMPTY_STATES.ANALYSIS_INCOMPLETE);
  assert.equal(s.metrics.decisions_analyzed,0);
  assert.equal(s.analysis_state.state,State.ANALYSIS_STATES.DONNEES_INSUFFISANTES,'incomplete without any analyzable decision derives DONNEES_INSUFFISANTES');
  assert.equal(s.analysis_state_label,'Données insuffisantes');
  assert.deepEqual(s.analysis_state.reason_codes.slice().sort(),['ANALYSIS_INCOMPLETE','INSUFFICIENT_SUPPORT']);
  assert.equal(State.isAnalysisState(s.analysis_state),true);
}

// #393 T5: the legacy empty-state -> taxonomy mapping is an explicit,
// exhaustive, exported table. Every dashboard empty state must have exactly one
// derived user-facing taxonomy state, so no screen can collapse two causes into
// a single generic message.
{
  assert.deepEqual(
    Object.keys(Dashboard.EMPTY_STATE_REASON_CODES).sort(),
    Object.values(Dashboard.EMPTY_STATES).sort(),
    'every legacy empty state must have an explicit taxonomy mapping'
  );
  assert.deepEqual(Dashboard.EMPTY_STATE_REASON_CODES,{
    NO_HANDS:['NO_HANDS'],
    ANALYSIS_PENDING:['ANALYSIS_PENDING'],
    ANALYSIS_INCOMPLETE:['ANALYSIS_INCOMPLETE'],
    NO_SIGNIFICANT_LOSS:['NO_SIGNIFICANT_LOSS'],
    READY:['READY']
  });
  // Cause disambiguation is the only dynamic part of the mapping.
  assert.deepEqual(Dashboard.analysisStateReasonCodes('READY',{}),['READY']);
  assert.deepEqual(Dashboard.analysisStateReasonCodes('NO_HANDS',{}),['NO_HANDS']);
  assert.deepEqual(
    Dashboard.analysisStateReasonCodes('ANALYSIS_INCOMPLETE',{decisions_analyzed:2}),
    ['ANALYSIS_INCOMPLETE'],
    'incomplete with analyzable decisions stays a partial analysis'
  );
  assert.deepEqual(
    Dashboard.analysisStateReasonCodes('ANALYSIS_INCOMPLETE',{decisions_analyzed:0}),
    ['ANALYSIS_INCOMPLETE',Dashboard.INCOMPLETE_SUPPORT_SHORTAGE],
    'incomplete without any analyzable decision is a support shortage'
  );
  // Every non-incomplete mapping resolves to its documented taxonomy state
  // through the shared mapper.
  const expectedStates={
    NO_HANDS:State.ANALYSIS_STATES.DONNEES_INSUFFISANTES,
    ANALYSIS_PENDING:State.ANALYSIS_STATES.CALCUL_EN_COURS,
    NO_SIGNIFICANT_LOSS:State.ANALYSIS_STATES.ANALYSE_DISPONIBLE,
    READY:State.ANALYSIS_STATES.ANALYSE_DISPONIBLE
  };
  for(const [legacyState,expectedState] of Object.entries(expectedStates)){
    const mapped=Dashboard.analysisStateFor(legacyState,{});
    assert.equal(mapped.state,expectedState,legacyState+' derives '+expectedState);
    assert.equal(State.isAnalysisState(mapped),true,legacyState+' must expose a schema-valid analysis_state');
  }
  assert.equal(
    Dashboard.analysisStateFor('ANALYSIS_INCOMPLETE',{decisions_analyzed:0}).state,
    State.ANALYSIS_STATES.DONNEES_INSUFFISANTES
  );
  assert.equal(
    Dashboard.analysisStateFor('ANALYSIS_INCOMPLETE',{decisions_analyzed:1}).state,
    State.ANALYSIS_STATES.ANALYSE_PARTIELLE
  );
}

{
  const splitScores=JSON.parse(JSON.stringify(reviewScores));
  splitScores['100003'].signature='sig-B';
  const dashboards=Dashboard.buildReviewDashboards({reviewScores:splitScores,hhSources,scope:SCOPE,user_metadata:{}});
  assert.equal(dashboards.length,2);
  assert.deepEqual(dashboards.map(x=>x.scope.strategy_version).sort(),['runtime-r1@sig-A','runtime-r1@sig-B']);
  assert.throws(()=>Dashboard.buildReviewDashboard({reviewScores:splitScores,hhSources,scope:SCOPE,user_metadata:{}}),/spans 2/);
}

// #392: an unavailable resolver state stays explicit instead of becoming Custom.
{
  const unavailableScope=Adapter.reviewScopeFromResolution(
    {population_id:SCOPE.population_id,status:'UNAVAILABLE',source:'NONE',fail_closed:true,reason_codes:['NO_ADMISSIBLE_STRATEGY']},
    {pack_id:SCOPE.pack_id,ev_reference:Adapter.DEFAULT_EV_REFERENCE}
  );
  const d=Dashboard.buildReviewDashboard({reviewScores,hhSources,scope:unavailableScope,user_metadata:{}});
  assert.equal(d.scope.strategy_id,Adapter.UNAVAILABLE_STRATEGY_ID);
  assert.equal(d.scope.strategy_version,'UNAVAILABLE@UNAVAILABLE@sig-A');
  assert.equal(d.scope.availability,undefined,'scope key stays the canonical five-field identity');
}

assert.equal(dashboard.traceability.inbox_schema,Inbox.INBOX_SCHEMA);
assert.equal(dashboard.traceability.leak_report_schema,Leak.REPORT_SCHEMA);
assert.equal(dashboard.traceability.event_schema,Leak.EVENT_SCHEMA);
assert.equal(dashboard.traceability.adapter_schema,Adapter.ADAPTER_SCHEMA);
assert.equal(dashboard.traceability.training_target_schema,Target.TARGET_SCHEMA);

console.log(JSON.stringify({
  status:'PASS',
  schema:Dashboard.DASHBOARD_SCHEMA,
  state:dashboard.state,
  analysis_state:dashboard.analysis_state.state,
  analysis_state_label:dashboard.analysis_state_label,
  hands:dashboard.metrics.hands_loaded,
  decisions_to_review:dashboard.metrics.decisions_to_review,
  total_ev_loss_bb:dashboard.metrics.total_ev_loss_bb
}));
