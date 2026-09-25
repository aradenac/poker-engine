'use strict';

const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const Leak=require('../../src/analytics/leak-analyzer.js');
const Adapter=require('../../src/analytics/review-score-adapter.js');
const State=require('../../src/analytics/analysis-state.js');
const Inbox=require('../../src/analytics/review-inbox.js');

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
Table 'Gamma' 6-max Seat #2 is the button
Seat 1: Hero (20000 in chips)
Seat 2: BTN3 (20000 in chips)
Seat 3: SB3 (20000 in chips)
Seat 4: BB3 (20000 in chips)
Seat 5: LJ3 (20000 in chips)
Seat 6: HJ3 (20000 in chips)
SB3: posts small blind 100
BB3: posts big blind 200
*** HOLE CARDS ***
Dealt to Hero [9s 9d]
LJ3: folds
HJ3: folds
Hero: raises 400 to 600
BTN3: raises 1400 to 2000
SB3: folds
BB3: folds
Hero: calls 1400
*** FLOP *** [7h 5d 2s]
Hero: checks
BTN3: bets 2000
Hero: folds
*** SUMMARY ***
Total pot 6100 | Rake 0
`;

const HH4=`PokerStars Zoom Hand #100004: Hold'em No Limit (100/200) - 2026/09/18 21:18:00 CET
Table 'Delta' 6-max Seat #6 is the button
Seat 1: SB4 (20000 in chips)
Seat 2: BB4 (20000 in chips)
Seat 3: LJ4 (20000 in chips)
Seat 4: HJ4 (20000 in chips)
Seat 5: CO4 (20000 in chips)
Seat 6: Hero (20000 in chips)
SB4: posts small blind 100
BB4: posts big blind 200
*** HOLE CARDS ***
Dealt to Hero [Ad Td]
LJ4: folds
HJ4: folds
CO4: folds
Hero: raises 400 to 600
SB4: folds
BB4: calls 400
*** FLOP *** [Tc 8c 4h]
BB4: checks
Hero: bets 800
BB4: calls 800
*** TURN *** [Tc 8c 4h] [2s]
BB4: checks
Hero: bets 1600
BB4: calls 1600
*** SUMMARY ***
Total pot 6100 | Rake 0
`;

function heroSteps(raw){
  const h=Adapter.parseStoredHand(raw,'fixture.txt');
  return {hand:h,steps:h.steps.filter(s=>s.player==='Hero')};
}
const p1=heroSteps(HH1),p2=heroSteps(HH2),p3=heroSteps(HH3),p4=heroSteps(HH4);
const h1raise=p1.steps.find(s=>s.street==='PREFLOP'&&s.actionType==='raise');
const h1bet=p1.steps.find(s=>s.street==='FLOP'&&s.actionType==='bet');
const h2call=p2.steps.find(s=>s.street==='PREFLOP'&&s.actionType==='call');
const h2check=p2.steps.find(s=>s.street==='FLOP'&&s.actionType==='check');
const h3raise=p3.steps.find(s=>s.street==='PREFLOP'&&s.actionType==='raise');
const h3call=p3.steps.find(s=>s.street==='PREFLOP'&&s.actionType==='call');
const h3check=p3.steps.find(s=>s.street==='FLOP'&&s.actionType==='check');
const h3fold=p3.steps.find(s=>s.street==='FLOP'&&s.actionType==='fold');
const h4raise=p4.steps.find(s=>s.street==='PREFLOP'&&s.actionType==='raise');
const h4flop=p4.steps.find(s=>s.street==='FLOP'&&s.actionType==='bet');
const h4turn=p4.steps.find(s=>s.street==='TURN'&&s.actionType==='bet');

for(const step of [h1raise,h1bet,h2call,h2check,h3raise,h3call,h3check,h3fold,h4raise,h4flop,h4turn])assert.ok(step);

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
    handId:'100003',signature:'sig-A',complete:true,analyzableDecisions:4,finishedDecisions:4,details:[
      {stepIndex:h3raise.stepIndex,lossBB:0,rawLossBB:0,chosenEV:.6,bestEV:.6,bestLabel:'RAISE',withinNoise:false,comparable:true,
       simContext:{potType:'UNOPENED',preflopRole:'RFI',relativePosition:'OOP'}},
      {stepIndex:h3call.stepIndex,lossBB:1,rawLossBB:1,chosenEV:-.3,bestEV:.7,bestLabel:'FOLD',withinNoise:false,comparable:true,
       simContext:{potType:'3BET',preflopRole:'CALLER',relativePosition:'OOP'}},
      {stepIndex:h3check.stepIndex,lossBB:0,rawLossBB:0,chosenEV:.2,bestEV:.2,bestLabel:'CHECK',withinNoise:false,comparable:true,
       simContext:{potType:'3BET',preflopRole:'CALLER',relativePosition:'OOP'}},
      {stepIndex:h3fold.stepIndex,lossBB:0,rawLossBB:0,chosenEV:0,bestEV:0,bestLabel:'FOLD',withinNoise:false,comparable:true,
       simContext:{potType:'3BET',preflopRole:'CALLER',relativePosition:'OOP'}}
    ]
  },
  '100004':{
    handId:'100004',signature:'sig-A',complete:false,analyzableDecisions:3,finishedDecisions:2,details:[
      {stepIndex:h4raise.stepIndex,lossBB:0,rawLossBB:0,chosenEV:.8,bestEV:.8,bestLabel:'RAISE',withinNoise:false,comparable:true,
       simContext:{potType:'UNOPENED',preflopRole:'RFI',relativePosition:'IP'}},
      {stepIndex:h4flop.stepIndex,lossBB:.5,rawLossBB:.5,chosenEV:.3,bestEV:.8,bestLabel:'CHECK',withinNoise:false,comparable:true,
       simContext:{potType:'SRP',preflopRole:'PFR',relativePosition:'IP'}}
    ]
  }
};

const metadata0=Inbox.normalizeUserMetadata({});
const metadata1=Inbox.setReviewed(metadata0,'100003',true,'2026-09-19T00:10:00Z');
const metadata2=Inbox.setReviewed(metadata1,'100004',true,'2026-09-19T00:11:00Z');
assert.equal(metadata0.hands['100003'],undefined,'setReviewed must not mutate the original metadata');

const sourceSnapshot=JSON.stringify(reviewScores);
const inbox=Inbox.buildReviewInbox({
  reviewScores,
  hhSources:[{name:'all.txt',content:[HH1,HH2,HH3,HH4].join('\n')}],
  scope:SCOPE,
  user_metadata:metadata2
});
assert.equal(JSON.stringify(reviewScores),sourceSnapshot,'building inbox must never mutate reviewScores');
assert.equal(inbox.schema,Inbox.INBOX_SCHEMA);
assert.equal(inbox.items.length,4);
assert.match(inbox.scope.strategy_version,/runtime-r1@sig-A$/);

const byId=new Map(inbox.items.map(x=>[x.hand_id,x]));
const i1=byId.get('100001'),i2=byId.get('100002'),i3=byId.get('100003'),i4=byId.get('100004');

assert.equal(i1.total_loss_bb,2.5,'sum EV loss must be reconstructed from decision events');
assert.equal(i1.costliest_decision.loss_bb,2);
assert.equal(i1.costliest_decision.decision_id,'review:100001:'+h1bet.stepIndex);
assert.equal(i1.main_street,'FLOP');
assert.equal(i1.position,'BTN');
assert.equal(i1.spot_family,'SRP|PFR|IP');
assert.equal(i1.action_played,'BET');
assert.equal(i1.action_recommended,'BET');
assert.equal(i1.sizing_error,true);
assert.equal(i1.jam,true);
assert.equal(i1.overbet,true);
assert.equal(i1.coverage.state,Inbox.COVERAGE_COMPLETE);
assert.equal(i1.coverage_state,Inbox.COVERAGE_COMPLETE,'coverage_state stays exposed for compatibility');
assert.equal(i1.analysis_state.state,'ANALYSE_DISPONIBLE','a complete comparable hand is an available analysis');
assert.deepEqual(i1.analysis_state.reason_codes,[],'an available analysis carries no blocking reason');
assert.equal(i1.analysis_state_label,'Analyse disponible');
assert.equal(State.isAnalysisState(i1.analysis_state),true,'item.analysis_state must conform to poker-analysis-state/v1');
assert.equal(i1.analysis_state.statistical_support.observations,0,'the reviewed decision count never becomes the model observation count');
assert.notEqual(i1.analysis_state.statistical_support.observations,i1.coverage.decisions_comparable,'2 comparable decisions must not be reported as 2 observations');
assert.equal(i1.analysis_state.statistical_support.distinct_hands,0,'distinct_hands is never invented as 1');
assert.equal(i1.status,Inbox.STATUS.TO_REVIEW);
assert.equal(i1.status_label,'À revoir');
assert.deepEqual(i1.deep_link,{
  schema:Inbox.DEEP_LINK_SCHEMA,kind:'REVIEW_DECISION',hand_id:'100001',
  decision_id:'review:100001:'+h1bet.stepIndex,step_index:h1bet.stepIndex,reason:'COSTLIEST_DECISION'
});

assert.equal(i2.total_loss_bb,0);
assert.equal(i2.coverage.complete,true);
assert.equal(i2.coverage.decisions_within_noise,1);
assert.equal(i2.status,Inbox.STATUS.CORRECT,'complete zero-attributed-loss hand can be Correcte');
assert.equal(i2.costliest_decision,null,'Correcte does not invent a costly mistake');
assert.equal(i2.deep_link.reason,'FIRST_COMPARABLE_DECISION');

assert.equal(i3.total_loss_bb,1);
assert.equal(i3.user_review.reviewed,true);
assert.equal(i3.status,Inbox.STATUS.REVIEWED);
assert.equal(i3.status_label,'Revue');
assert.equal(i3.analysis_state.state,'ANALYSE_DISPONIBLE','a reviewed hand with complete science stays available');
assert.equal(reviewScores['100003'].reviewed,undefined,'user review state must never enter reviewScores');

assert.equal(i4.user_review.reviewed,true,'user metadata remains available even when science is incomplete');
assert.equal(i4.status,Inbox.STATUS.INCOMPLETE_ANALYSIS,'incomplete science must remain visible even if user marked it reviewed');
assert.equal(i4.status_label,'Analyse incomplète');
assert.equal(i4.coverage.complete,false);
assert.equal(i4.coverage_state,Inbox.COVERAGE_INCOMPLETE);
assert.equal(i4.analysis_state.state,'CALCUL_EN_COURS','an unfinished computation is never reported as a scientific conclusion');
for(const reason of ['REVIEW_SCORE_INCOMPLETE','UNFINISHED_DECISIONS','UNSUPPORTED_DECISIONS'])assert.ok(i4.analysis_state.reason_codes.includes(reason),'reason code '+reason+' must survive in the taxonomy');
assert.equal(State.isAnalysisState(i4.analysis_state),true);
assert.ok(i4.coverage.reasons.includes('REVIEW_SCORE_INCOMPLETE'));
assert.ok(i4.coverage.reasons.includes('UNFINISHED_DECISIONS'));
assert.ok(i4.coverage.reasons.includes('UNSUPPORTED_DECISIONS'));
assert.equal(i4.total_loss_bb,.5,'known comparable loss can be retained while status remains incomplete');

assert.deepEqual(inbox.items.map(x=>x.hand_id),['100001','100003','100004','100002'],'default inbox order must be EV-loss descending with stable tie breaker');

const stable=Inbox.sortInboxItems([
  {...i2,hand_id:'b',total_loss_bb:1},
  {...i2,hand_id:'a',total_loss_bb:1},
  {...i2,hand_id:'c',total_loss_bb:2}
],'EV_LOSS_DESC');
assert.deepEqual(stable.map(x=>x.hand_id),['c','a','b'],'EV sort ties must be deterministic by hand_id');

{
  const q=Inbox.queryInbox(inbox,{
    street:'FLOP',position:'BTN',spot_family:'SRP|PFR|IP',
    action_played:'BET',action_recommended:'BET',sizing_error:true,jam:true,overbet:true,
    coverage:'COMPLETE',status:'TO_REVIEW',min_loss_bb:2
  },'EV_LOSS_DESC');
  assert.deepEqual(q.items.map(x=>x.hand_id),['100001'],'combined filters must use all decision facets deterministically');
}
{
  const q=Inbox.queryInbox(inbox,{street:'PREFLOP',action_played:'CALL',action_recommended:'FOLD',status:'REVIEWED'},'POSITION_ASC');
  assert.deepEqual(q.items.map(x=>x.hand_id),['100003']);
}
{
  const q=Inbox.queryInbox(inbox,{coverage:'INCOMPLETE',status:'INCOMPLETE_ANALYSIS'},'STREET_ASC');
  assert.deepEqual(q.items.map(x=>x.hand_id),['100004']);
}
{
  const q=Inbox.queryInbox(inbox,{status:'CORRECT'},'HAND_ID_ASC');
  assert.deepEqual(q.items.map(x=>x.hand_id),['100002']);
}
{
  const q=Inbox.queryInbox(inbox,{analysis_state:'ANALYSE_DISPONIBLE'},'HAND_ID_ASC');
  assert.deepEqual(q.items.map(x=>x.hand_id),['100001','100002','100003'],'analysis_state filter keeps only available analyses');
}
{
  const q=Inbox.queryInbox(inbox,{analysis_state:'CALCUL_EN_COURS'},'HAND_ID_ASC');
  assert.deepEqual(q.items.map(x=>x.hand_id),['100004'],'analysis_state filter isolates an unfinished computation');
}
{
  const q=Inbox.queryInbox(inbox,{analysis_state:['CALCUL_EN_COURS','ANALYSE_PARTIELLE']},'HAND_ID_ASC');
  assert.deepEqual(q.items.map(x=>x.hand_id),['100004'],'analysis_state accepts a list filter');
}
{
  const q=Inbox.queryInbox(inbox,{analysis_state:'SPOT_NON_SUPPORTE'},'HAND_ID_ASC');
  assert.deepEqual(q.items,[],'an unsupported state filter matches nothing here and never falls back to all');
}

// #393 T3: every legacy coverage reason maps to the documented taxonomy state.
{
  const expectations={
    MISSING_HH_SOURCE:'DONNEES_INSUFFISANTES',
    MISSING_REVIEW_SCORE:'DONNEES_INSUFFISANTES',
    REVIEW_SCORE_INCOMPLETE:'DONNEES_INSUFFISANTES',
    NO_DECISION_EVENTS:'DONNEES_INSUFFISANTES',
    UNFINISHED_DECISIONS:'CALCUL_EN_COURS',
    UNSUPPORTED_DECISIONS:'SPOT_NON_SUPPORTE',
    NON_COMPARABLE_DECISIONS:'ANALYSE_PARTIELLE'
  };
  for(const [reason,state] of Object.entries(expectations)){
    const mapped=Inbox.analysisStateFor({complete:false,reasons:[reason],state:'INCOMPLETE'},[]);
    assert.equal(mapped.state,state,'reason '+reason+' must map to '+state);
    assert.ok(mapped.reason_codes.includes(reason),'reason '+reason+' must be preserved');
    assert.equal(State.isAnalysisState(mapped),true);
  }
  const available=Inbox.analysisStateFor({complete:true,reasons:[],state:'COMPLETE'},[]);
  assert.equal(available.state,'ANALYSE_DISPONIBLE');
  assert.deepEqual(available.reason_codes,[]);
}
// A scientific error_type (ACTION_ERROR/SIZING_ERROR/...) is never a worker error.
{
  const comparableRow={support:{covered:true},comparability:{comparable:true},error_type:'SIZING_ERROR'};
  const scientific=Inbox.analysisStateFor({complete:true,reasons:[]},[comparableRow]);
  assert.equal(scientific.state,'ANALYSE_DISPONIBLE','a sizing error is a reviewable decision, not a failed computation');
  const worker=Inbox.analysisStateFor({complete:true,reasons:[]},[{...comparableRow,error_type:'WORKER_ERROR'}]);
  assert.equal(worker.state,'ERREUR_CALCUL');
  assert.equal(worker.error.type,'WORKER_ERROR');
  assert.equal(worker.error.retryable,true);
  assert.ok(worker.reason_codes.includes('WORKER_ERROR'));
  assert.equal(State.isAnalysisState(worker),true);
}
// Support / comparability dimensions flow from the normalized events.
{
  const unsupported=Inbox.analysisStateFor({complete:false,reasons:['UNSUPPORTED_DECISIONS'],state:'INCOMPLETE'},[{support:{covered:false},comparability:{comparable:false},error_type:'UNSUPPORTED'}]);
  assert.equal(unsupported.state,'SPOT_NON_SUPPORTE');
  assert.equal(unsupported.model_support_status,'CONTEXT_UNSUPPORTED');
  assert.equal(unsupported.statistical_support.observations,0,'an unsupported decision carries no model observations');
  assert.equal(unsupported.statistical_support.availability,'UNAVAILABLE','an unsupported context makes the support explicitly unavailable');
  const nonComparable=Inbox.analysisStateFor({complete:false,reasons:['NON_COMPARABLE_DECISIONS'],state:'INCOMPLETE'},[{support:{covered:true},comparability:{comparable:false},error_type:'NON_COMPARABLE'}]);
  assert.equal(nonComparable.state,'ANALYSE_PARTIELLE');
  assert.equal(nonComparable.ev_comparability.comparable,false);
}

// #408 blocker 2: statistical_support must be derived from the real per-decision
// model support, never from the number of comparable review decisions.
{
  const twoDecisions=[
    {support:{covered:true,observations:120},comparability:{comparable:true},error_type:'ACTION_ERROR'},
    {support:{covered:true,observations:450},comparability:{comparable:true},error_type:'ACTION_ERROR'}
  ];
  const support=Inbox.analysisStateFor({complete:true,reasons:[],state:'COMPLETE'},twoDecisions);
  assert.equal(support.statistical_support.observations,120,'2 decisions backed by 120/450 observations aggregate to the conservative minimum 120');
  assert.notEqual(support.statistical_support.observations,twoDecisions.length,'the decision count must never be used as the observation count');
  assert.notEqual(support.statistical_support.observations,570,'unrelated model nodes must never be summed');
  assert.equal(support.statistical_support.distinct_hands,0,'distinct_hands is unavailable and must never be invented as 1');
  assert.notEqual(support.statistical_support.distinct_hands,1);
  assert.equal(support.state,'ANALYSE_DISPONIBLE','the support field change must not alter a complete comparable hand state');
  assert.equal(support.statistical_support.availability,'AVAILABLE','a real positive observation count proves AVAILABLE support');
  assert.equal(State.isAnalysisState(support),true);

  // Event count differs from support count without confusion.
  const threeDecisions=[...twoDecisions,{support:{covered:true,observations:300},comparability:{comparable:true},error_type:'ACTION_ERROR'}];
  const three=Inbox.analysisStateFor({complete:true,reasons:[]},threeDecisions);
  assert.equal(three.statistical_support.observations,120);
  assert.equal(threeDecisions.length,3);

  // Unsupported / non-comparable decisions carry no admissible model support and
  // must not contribute observations; they still map to the right canonical state.
  const withUnsupported=Inbox.analysisStateFor({complete:false,reasons:['UNSUPPORTED_DECISIONS'],state:'INCOMPLETE'},[
    {support:{covered:true,observations:120},comparability:{comparable:true}},
    {support:{covered:false,observations:999},comparability:{comparable:false},error_type:'UNSUPPORTED'}
  ]);
  assert.equal(withUnsupported.statistical_support.observations,120,'only comparable covered decisions feed the aggregation');
  assert.equal(withUnsupported.statistical_support.availability,'AVAILABLE','the real 120 observations still prove available support even when a sibling decision is unsupported');
  assert.equal(withUnsupported.state,'SPOT_NON_SUPPORTE','an unsupported decision still maps to SPOT_NON_SUPPORTE');

  // Missing metadata must not become a fabricated positive support, and a single
  // decision must not become an observation count either.
  const missingMetadata=Inbox.analysisStateFor({complete:true,reasons:[],state:'COMPLETE'},[
    {support:{covered:true},comparability:{comparable:true},error_type:'ACTION_ERROR'}
  ]);
  assert.equal(missingMetadata.statistical_support.observations,0,'missing support metadata is represented as the fail-safe floor, never as a positive count');
  assert.notEqual(missingMetadata.statistical_support.observations,1);
  assert.equal(missingMetadata.statistical_support.distinct_hands,0);
  assert.equal(missingMetadata.statistical_support.availability,'UNKNOWN','missing metadata never reports AVAILABLE support');
  assert.equal(State.isAnalysisState(missingMetadata),true);

  // Non-integer / negative observation metadata is not usable evidence.
  const invalidMetadata=Inbox.analysisStateFor({complete:true,reasons:[]},[
    {support:{covered:true,observations:-5},comparability:{comparable:true}},
    {support:{covered:true,observations:null},comparability:{comparable:true}},
    {support:{covered:true,observations:'n/a'},comparability:{comparable:true}},
    {support:{covered:true,observations:200},comparability:{comparable:true}}
  ]);
  assert.equal(invalidMetadata.statistical_support.observations,200,'only valid integer>=0 observations are aggregated');

  // #408 blocker 2: malformed counts must never be coerced by `Number()` into a
  // fabricated positive support. `true` -> 1, `[120]` -> 120 and `'   '` -> 0
  // are all rejected, so missing/garbage metadata cannot masquerade as evidence.
  const coercedMetadata=Inbox.analysisStateFor({complete:true,reasons:[]},[
    {support:{covered:true,observations:true},comparability:{comparable:true}},
    {support:{covered:true,observations:[120]},comparability:{comparable:true}},
    {support:{covered:true,observations:'   '},comparability:{comparable:true}}
  ]);
  assert.equal(coercedMetadata.statistical_support.observations,0,'boolean/container/blank metadata is not observation evidence');
  assert.equal(coercedMetadata.statistical_support.availability,'UNKNOWN','malformed metadata stays explicitly UNKNOWN');
  assert.equal(State.isAnalysisState(coercedMetadata),true);
  // A well-formed serialized integer string stays admissible evidence.
  const stringMetadata=Inbox.analysisStateFor({complete:true,reasons:[]},[
    {support:{covered:true,observations:'150'},comparability:{comparable:true}}
  ]);
  assert.equal(stringMetadata.statistical_support.observations,150,'a well-formed integer string is a valid serialized count');

  // Partially reported support aggregates over the known decisions only.
  const partial=Inbox.analysisStateFor({complete:true,reasons:[]},[
    {support:{covered:true,observations:80},comparability:{comparable:true}},
    {support:{covered:true},comparability:{comparable:true}}
  ]);
  assert.equal(partial.statistical_support.observations,80);
}

// Low-support / insufficient-support reasons map to DONNEES_INSUFFISANTES.
{
  for(const reason of ['LOW_SUPPORT','INSUFFICIENT_SUPPORT']){
    const mapped=Inbox.analysisStateFor({complete:false,reasons:[reason],state:'INCOMPLETE'},[]);
    assert.equal(mapped.state,'DONNEES_INSUFFISANTES','reason '+reason+' must map to DONNEES_INSUFFISANTES');
    assert.ok(mapped.reason_codes.includes(reason));
    assert.equal(State.isAnalysisState(mapped),true);
  }
}

{
  const altScores=JSON.parse(JSON.stringify(reviewScores));
  altScores['100004'].signature='sig-B';
  const split=Inbox.buildReviewInboxes({
    reviewScores:altScores,
    hhSources:[{name:'all.txt',content:[HH1,HH2,HH3,HH4].join('\n')}],
    scope:SCOPE,
    user_metadata:metadata2
  });
  assert.equal(split.length,2,'different strategy/review signatures must never be mixed');
  assert.deepEqual(split.map(x=>x.scope.strategy_version).sort(),['runtime-r1@sig-A','runtime-r1@sig-B']);
  assert.throws(()=>Inbox.buildReviewInbox({
    reviewScores:altScores,
    hhSources:[{name:'all.txt',content:[HH1,HH2,HH3,HH4].join('\n')}],
    scope:SCOPE,user_metadata:metadata2
  }),/spans 2/);
}

{
  const missing=Inbox.buildReviewInbox({
    reviewScores:{'999999':{handId:'999999',signature:'sig-A',complete:false,analyzableDecisions:1,finishedDecisions:1,details:[]}},
    hhSources:[],scope:SCOPE,user_metadata:{}
  });
  assert.equal(missing.items.length,1);
  const item=missing.items[0];
  assert.equal(item.status,Inbox.STATUS.INCOMPLETE_ANALYSIS);
  assert.ok(item.coverage.reasons.includes('MISSING_HH_SOURCE'));
  assert.equal(item.analysis_state.state,'DONNEES_INSUFFISANTES','missing data is insufficient data, never a generic unavailable label');
  assert.equal(item.analysis_state.computational_status,'COMPLETE');
  assert.equal(item.deep_link,null);
  assert.equal(item.total_loss_bb,0);
}

assert.throws(()=>Inbox.setReviewed({},'x',true,'invalid-date'),/valid timestamp/);
assert.throws(()=>Inbox.queryInbox(inbox,{min_loss_bb:-1}),/non-negative/);
assert.throws(()=>Inbox.queryInbox(inbox,{jam:'maybe'}),/boolean filter/);

// The review-inbox contract advertises the taxonomy field, its enum and its
// dimensions while keeping `coverage` accepted for compatibility.
{
  const schema=JSON.parse(fs.readFileSync(path.join(__dirname,'../../contracts/analytics/review-inbox.schema.json'),'utf8'));
  const item=schema.$defs.item;
  assert.ok(item.required.includes('analysis_state'),'item.analysis_state must be required');
  assert.ok(item.required.includes('coverage'),'coverage must stay accepted');
  assert.ok(item.properties.coverage,'coverage property must be preserved');
  const def=schema.$defs.analysis_state;
  assert.deepEqual(def.properties.state.enum,[
    'ANALYSE_DISPONIBLE','ANALYSE_PARTIELLE','CALCUL_EN_COURS','DONNEES_INSUFFISANTES','SPOT_NON_SUPPORTE','ERREUR_CALCUL'
  ]);
  // #395 T1: the real result is part of the item contract.
  assert.ok(item.required.includes('hero_net_bb'),'item.hero_net_bb must be required');
  assert.ok(item.required.includes('result'),'item.result must be required');
  assert.deepEqual(item.properties.hero_net_bb.type,['number','null'],'hero_net_bb is a number or null, never a coerced placeholder');
  assert.deepEqual(item.properties.result.properties.state.enum,['WIN','LOSS','EVEN','UNKNOWN'],'result.state carries the settlement vocabulary');
  assert.deepEqual(item.properties.result.properties.net_bb.type,['number','null']);
  for(const dimension of ['computational_status','model_support_status','statistical_support','ev_comparability','recommendation_admissibility','posterior_availability','error']){
    assert.ok(def.required.includes(dimension),'analysis_state dimension '+dimension+' must be required');
  }
  // #408 blocker 2 / #393 blocker 2: statistical_support counters are non-null
  // integers >= 0 carrying the fail-safe floor; the explicit availability signal
  // carries unknown/unavailable, matching the canonical schema + JS validator.
  const support=def.properties.statistical_support;
  assert.ok(support,'statistical_support definition must be present');
  for(const field of ['observations','distinct_hands']){
    assert.equal(support.properties[field].type,'integer','statistical_support.'+field+' must be a non-null integer');
    assert.equal(support.properties[field].minimum,0,'statistical_support.'+field+' must carry the fail-safe floor');
  }
  assert.deepEqual(support.properties.availability.enum,['AVAILABLE','UNKNOWN','UNAVAILABLE'],'statistical_support.availability must carry the explicit vocabulary');
  assert.match(support.description||'',/minimum/i,'the statistical_support description must document the aggregation rule');
  assert.equal(State.SCHEMA,Inbox.ANALYSIS_STATE_SCHEMA);
}

// The canonical contract doc documents the hand-level aggregation rule so the
// Inbox producer and its reviewers share one deterministic definition.
{
  const doc=fs.readFileSync(path.join(__dirname,'../../docs/analysis-state-contract.md'),'utf8');
  assert.ok(doc.includes('Règle d\'agrégation du support statistique'),'the contract doc must document the aggregation section');
  assert.ok(doc.includes('event.support.observations'),'the contract doc must reference the per-decision support observations');
  assert.ok(/minimum/i.test(doc),'the contract doc must state the minimum aggregation rule');
  assert.ok(doc.includes('jamais inventé à `1`'),'the contract doc must forbid inventing distinct_hands=1');
}

// #392: an unavailable resolver state flows through as an explicit, filterable scope.
{
  const unavailableScope=Adapter.reviewScopeFromResolution(
    {population_id:SCOPE.population_id,status:'RETAIN_REFERENCE',source:'POPULATION',fail_closed:false,
     strategy_id:'legacy-ranges-v1',strategy_version:'2026-09-19.1',reason_codes:['RETAINED_REFERENCE']},
    {pack_id:SCOPE.pack_id,ev_reference:Adapter.DEFAULT_EV_REFERENCE}
  );
  const scoped=Inbox.buildReviewInbox({
    reviewScores:{'100001':reviewScores['100001']},
    hhSources:[{name:'all.txt',content:HH1}],
    scope:unavailableScope,user_metadata:metadata0
  });
  assert.equal(scoped.scope.strategy_id,Adapter.UNAVAILABLE_STRATEGY_ID);
  assert.equal(scoped.scope.strategy_version,'UNAVAILABLE@RETAIN_REFERENCE@sig-A');
  assert.notEqual(scoped.scope_key,Leak.scopeKey({...SCOPE,strategy_version:'runtime-r1@sig-A'}),'unavailable scope must stay distinct from an admissible scope');
}

// #395 T1: the real hero settlement is an optional, independent input. Without
// `hand_results` no item may claim a settled result, and every pre-existing
// field keeps its value.
{
  for(const item of inbox.items){
    assert.equal(item.hero_net_bb,null,'a hand without settlement evidence carries a null hero_net_bb');
    assert.deepEqual(item.result,{state:'UNKNOWN',net_bb:null},'an absent settlement is UNKNOWN, never a fabricated EVEN');
  }
  assert.equal(i1.total_loss_bb,2.5,'the EV fields stay untouched by the real result');
  assert.equal(Inbox.RESULT.UNKNOWN,'UNKNOWN');
  assert.deepEqual(Inbox.RESULT_STATES,['WIN','LOSS','EVEN','UNKNOWN']);
  for(const mode of ['EV_LOSS_DESC','TIMESTAMP_DESC','TIMESTAMP_ASC','RESULT_GAIN_DESC','RESULT_LOSS_DESC','STATUS_ASC','STREET_ASC','POSITION_ASC','SPOT_FAMILY_ASC','PLAYED_ACTION_ASC','RECOMMENDED_ACTION_ASC','HAND_ID_ASC']){
    assert.ok(Inbox.SORT_MODES.includes(mode),'sort mode '+mode+' must stay supported');
  }
}

// #395 T1: an explicit settlement drives hero_net_bb + result.state without
// touching any other field of the item.
{
  const settled=Inbox.buildReviewInbox({
    reviewScores,
    hhSources:[{name:'all.txt',content:[HH1,HH2,HH3,HH4].join('\n')}],
    scope:SCOPE,
    user_metadata:metadata2,
    hand_results:{'100001':-3.5,'100002':0,'100003':4.25,'100004':null}
  });
  const rows=new Map(settled.items.map(x=>[x.hand_id,x]));
  assert.equal(rows.get('100001').hero_net_bb,-3.5);
  assert.deepEqual(rows.get('100001').result,{state:'LOSS',net_bb:-3.5},'a real loss is LOSS');
  assert.equal(rows.get('100002').hero_net_bb,0);
  assert.deepEqual(rows.get('100002').result,{state:'EVEN',net_bb:0},'a zero settlement is EVEN');
  assert.equal(rows.get('100003').hero_net_bb,4.25);
  assert.deepEqual(rows.get('100003').result,{state:'WIN',net_bb:4.25},'a real gain is WIN');
  assert.equal(rows.get('100004').hero_net_bb,null);
  assert.deepEqual(rows.get('100004').result,{state:'UNKNOWN',net_bb:null},'an explicit null settlement stays UNKNOWN');
  for(const id of ['100001','100002','100003','100004']){
    const before=byId.get(id),after=rows.get(id);
    for(const field of ['total_loss_bb','nominal_loss_bb','main_street','position','spot_family','action_played','action_recommended','status','deep_link','coverage_state','timestamp']){
      assert.deepEqual(after[field],before[field],'the real result must not alter item.'+field);
    }
    assert.deepEqual(after.analysis_state,before.analysis_state,'the real result must not alter the analysis state');
  }
  assert.equal(Inbox.resultFor(2.5).state,'WIN');
  assert.equal(Inbox.resultFor(0).state,'EVEN');
  assert.equal(Inbox.resultFor(-0.25).state,'LOSS');
  assert.equal(Inbox.resultFor(1e-12).state,'EVEN','the EVEN band uses the shared 1e-9 tolerance');
  assert.equal(Inbox.resultFor(-1e-12).state,'EVEN','the EVEN band uses the shared 1e-9 tolerance');
  // Malformed settlements are never coerced into a fabricated (positive) net.
  for(const value of [null,undefined,'','   ','n/a',true,false,[2.5],{},NaN,Infinity,-Infinity]){
    const item=Inbox.buildReviewInbox({
      reviewScores:{'100001':reviewScores['100001']},
      hhSources:[{name:'all.txt',content:HH1}],scope:SCOPE,user_metadata:metadata0,
      hand_results:{'100001':value}
    }).items[0];
    assert.equal(item.hero_net_bb,null,'malformed settlement '+JSON.stringify(value)+' must never become a number');
    assert.equal(item.result.state,'UNKNOWN','malformed settlement '+JSON.stringify(value)+' stays UNKNOWN');
  }
  // A well-formed serialized number stays admissible evidence.
  const serialized=Inbox.buildReviewInbox({
    reviewScores:{'100001':reviewScores['100001']},
    hhSources:[{name:'all.txt',content:HH1}],scope:SCOPE,user_metadata:metadata0,
    hand_results:{'100001':'-1.5'}
  }).items[0];
  assert.equal(serialized.hero_net_bb,-1.5);
  assert.equal(serialized.result.state,'LOSS');
}

// #395 T1: result filters (single + multi), including the explicit UNKNOWN.
{
  const settled=Inbox.buildReviewInbox({
    reviewScores,
    hhSources:[{name:'all.txt',content:[HH1,HH2,HH3,HH4].join('\n')}],
    scope:SCOPE,user_metadata:metadata0,
    hand_results:{'100001':-3.5,'100002':0,'100003':4.25}
  });
  assert.deepEqual(Inbox.queryInbox(settled,{result:'WIN'},'HAND_ID_ASC').items.map(x=>x.hand_id),['100003']);
  assert.deepEqual(Inbox.queryInbox(settled,{result:'LOSS'},'HAND_ID_ASC').items.map(x=>x.hand_id),['100001']);
  assert.deepEqual(Inbox.queryInbox(settled,{result:'EVEN'},'HAND_ID_ASC').items.map(x=>x.hand_id),['100002']);
  assert.deepEqual(Inbox.queryInbox(settled,{result:'UNKNOWN'},'HAND_ID_ASC').items.map(x=>x.hand_id),['100004'],'UNKNOWN must be filterable by its own code');
  assert.deepEqual(Inbox.queryInbox(settled,{result:'unknown'},'HAND_ID_ASC').items.map(x=>x.hand_id),['100004'],'result filters are case-insensitive');
  assert.deepEqual(Inbox.queryInbox(settled,{result:['WIN','LOSS']},'HAND_ID_ASC').items.map(x=>x.hand_id),['100001','100003']);
  assert.deepEqual(Inbox.queryInbox(settled,{result:''},'HAND_ID_ASC').items.map(x=>x.hand_id),['100001','100002','100003','100004'],'an empty result filter matches everything');
  assert.deepEqual(Inbox.queryInbox(settled,{result:'WIN',min_loss_bb:4},'HAND_ID_ASC').items,[],'result composes with the other filters');
}

// #395 T1: temporal and real-result sorts, always tie-broken by hand_id.
{
  const settled=Inbox.buildReviewInbox({
    reviewScores,
    hhSources:[{name:'all.txt',content:[HH1,HH2,HH3,HH4].join('\n')}],
    scope:SCOPE,user_metadata:metadata0,
    hand_results:{'100001':-3.5,'100002':0,'100003':4.25}
  });
  assert.deepEqual(Inbox.sortInboxItems(settled.items,'TIMESTAMP_ASC').map(x=>x.hand_id),['100001','100002','100003','100004'],'TIMESTAMP_ASC orders on the real timestamps');
  assert.deepEqual(Inbox.sortInboxItems(settled.items,'TIMESTAMP_DESC').map(x=>x.hand_id),['100004','100003','100002','100001'],'TIMESTAMP_DESC reverses the real timestamps');
  assert.deepEqual(Inbox.sortInboxItems(settled.items,'RESULT_GAIN_DESC').map(x=>x.hand_id),['100003','100002','100001','100004'],'RESULT_GAIN_DESC puts the biggest gains first and UNKNOWN last');
  assert.deepEqual(Inbox.sortInboxItems(settled.items,'RESULT_LOSS_DESC').map(x=>x.hand_id),['100001','100002','100003','100004'],'RESULT_LOSS_DESC puts the biggest losses first and UNKNOWN last');

  const base=settled.items[0];
  assert.deepEqual(Inbox.sortInboxItems([
    {...base,hand_id:'b',hero_net_bb:1,result:{state:'WIN',net_bb:1}},
    {...base,hand_id:'a',hero_net_bb:1,result:{state:'WIN',net_bb:1}},
    {...base,hand_id:'c',hero_net_bb:3,result:{state:'WIN',net_bb:3}}
  ],'RESULT_GAIN_DESC').map(x=>x.hand_id),['c','a','b'],'RESULT_GAIN_DESC ties are deterministic by hand_id');
  assert.deepEqual(Inbox.sortInboxItems([
    {...base,hand_id:'b',hero_net_bb:-1,result:{state:'LOSS',net_bb:-1}},
    {...base,hand_id:'a',hero_net_bb:-1,result:{state:'LOSS',net_bb:-1}},
    {...base,hand_id:'c',hero_net_bb:-3,result:{state:'LOSS',net_bb:-3}}
  ],'RESULT_LOSS_DESC').map(x=>x.hand_id),['c','a','b'],'RESULT_LOSS_DESC ties are deterministic by hand_id');
  assert.throws(()=>Inbox.sortInboxItems(settled.items,'NOPE_DESC'),/unsupported sort/);

  // The timestamp comparison uses the parsed instant: a lexicographic compare
  // would put 'Z'-less/offset timestamps in the wrong place.
  assert.deepEqual(Inbox.sortInboxItems([
    {...base,hand_id:'late',timestamp:'2026-09-18T23:00:00+02:00'},
    {...base,hand_id:'early',timestamp:'2026-09-18T20:30:00Z'},
    {...base,hand_id:'undated',timestamp:null}
  ],'TIMESTAMP_ASC').map(x=>x.hand_id),['early','late','undated'],'TIMESTAMP_ASC compares instants and carries undated items last');
  assert.deepEqual(Inbox.sortInboxItems([
    {...base,hand_id:'late',timestamp:'2026-09-18T23:00:00+02:00'},
    {...base,hand_id:'early',timestamp:'2026-09-18T20:30:00Z'},
    {...base,hand_id:'undated',timestamp:'not-a-date'}
  ],'TIMESTAMP_DESC').map(x=>x.hand_id),['late','early','undated'],'TIMESTAMP_DESC compares instants (23:00+02:00 = 21:00Z after 20:30Z) and carries undated items last');
}

// #395 T3: real play timestamps that deliberately disagree with the numeric
// hand_id order, plus a settlement map covering gain / loss / neutral / absent.
// The earlier fixtures (#100001..#100004) are monotonic in both id and time, so
// they cannot tell whether a temporal or settlement sort reads the parsed
// instant and the real BB net, or leaks the id / insertion order. Here:
//   200002 2026-09-18T19:45:00Z  WIN    +6.5   earliest, but not the smallest id
//   200005 2026-09-18T20:30:00Z  UNKNOWN        absent from hand_results
//   200003 2026-09-18T21:10:00Z  LOSS   -4
//   200004 2026-09-18T21:10:00Z  WIN    +6.5   shares the instant with 200003
//   200001 2026-09-18T23:20:00Z  EVEN    0     latest, but the smallest id
const T3HH_EARLIEST=`PokerStars Zoom Hand #200002: Hold'em No Limit (100/200) - 2026/09/18 19:45:00 CET
Table 'T3-Earliest' 6-max Seat #6 is the button
Seat 1: SB2 (20000 in chips)
Seat 2: BB2 (20000 in chips)
Seat 3: LJ2 (20000 in chips)
Seat 4: HJ2 (20000 in chips)
Seat 5: CO2 (20000 in chips)
Seat 6: Hero (20000 in chips)
SB2: posts small blind 100
BB2: posts big blind 200
*** HOLE CARDS ***
Dealt to Hero [As Kd]
LJ2: folds
HJ2: folds
CO2: folds
Hero: raises 400 to 600
SB2: folds
BB2: calls 400
*** FLOP *** [Ah 7c 2d]
BB2: checks
Hero: bets 800
BB2: calls 800
*** SUMMARY ***
Total pot 2900 | Rake 0
`;

const T3HH_UNKNOWN=`PokerStars Zoom Hand #200005: Hold'em No Limit (100/200) - 2026/09/18 20:30:00 CET
Table 'T3-Unknown' 6-max Seat #6 is the button
Seat 1: SB5 (20000 in chips)
Seat 2: BB5 (20000 in chips)
Seat 3: LJ5 (20000 in chips)
Seat 4: HJ5 (20000 in chips)
Seat 5: CO5 (20000 in chips)
Seat 6: Hero (20000 in chips)
SB5: posts small blind 100
BB5: posts big blind 200
*** HOLE CARDS ***
Dealt to Hero [As Kd]
LJ5: folds
HJ5: folds
CO5: folds
Hero: raises 400 to 600
SB5: folds
BB5: folds
*** SUMMARY ***
Total pot 900 | Rake 0
`;

const T3HH_TIE_A=`PokerStars Zoom Hand #200003: Hold'em No Limit (100/200) - 2026/09/18 21:10:00 CET
Table 'T3-TieA' 6-max Seat #6 is the button
Seat 1: SB3 (20000 in chips)
Seat 2: BB3 (20000 in chips)
Seat 3: LJ3x (20000 in chips)
Seat 4: HJ3x (20000 in chips)
Seat 5: CO3x (20000 in chips)
Seat 6: Hero (20000 in chips)
SB3: posts small blind 100
BB3: posts big blind 200
*** HOLE CARDS ***
Dealt to Hero [9s 9d]
LJ3x: folds
HJ3x: folds
CO3x: folds
Hero: raises 400 to 600
SB3: folds
BB3: calls 400
*** FLOP *** [7h 5d 2s]
BB3: checks
Hero: bets 800
BB3: calls 800
*** SUMMARY ***
Total pot 2900 | Rake 0
`;

const T3HH_TIE_B=`PokerStars Zoom Hand #200004: Hold'em No Limit (100/200) - 2026/09/18 21:10:00 CET
Table 'T3-TieB' 6-max Seat #6 is the button
Seat 1: SB4 (20000 in chips)
Seat 2: BB4 (20000 in chips)
Seat 3: LJ4 (20000 in chips)
Seat 4: HJ4 (20000 in chips)
Seat 5: CO4 (20000 in chips)
Seat 6: Hero (20000 in chips)
SB4: posts small blind 100
BB4: posts big blind 200
*** HOLE CARDS ***
Dealt to Hero [Qc Jc]
LJ4: folds
HJ4: folds
CO4: raises 200 to 400
Hero: calls 400
SB4: folds
BB4: folds
*** SUMMARY ***
Total pot 1100 | Rake 0
`;

const T3HH_LATEST=`PokerStars Zoom Hand #200001: Hold'em No Limit (100/200) - 2026/09/18 23:20:00 CET
Table 'T3-Latest' 6-max Seat #6 is the button
Seat 1: SB1 (20000 in chips)
Seat 2: BB1 (20000 in chips)
Seat 3: LJ1 (20000 in chips)
Seat 4: HJ1 (20000 in chips)
Seat 5: CO1 (20000 in chips)
Seat 6: Hero (20000 in chips)
SB1: posts small blind 100
BB1: posts big blind 200
*** HOLE CARDS ***
Dealt to Hero [Ad Td]
LJ1: folds
HJ1: folds
CO1: folds
Hero: raises 400 to 600
SB1: folds
BB1: folds
*** SUMMARY ***
Total pot 900 | Rake 0
`;

const t3Earliest=heroSteps(T3HH_EARLIEST),t3Unknown=heroSteps(T3HH_UNKNOWN),t3TieA=heroSteps(T3HH_TIE_A),t3TieB=heroSteps(T3HH_TIE_B),t3Latest=heroSteps(T3HH_LATEST);
const t3EarliestRaise=t3Earliest.steps.find(s=>s.street==='PREFLOP'&&s.actionType==='raise');
const t3EarliestBet=t3Earliest.steps.find(s=>s.street==='FLOP'&&s.actionType==='bet');
const t3UnknownRaise=t3Unknown.steps.find(s=>s.street==='PREFLOP'&&s.actionType==='raise');
const t3TieARaise=t3TieA.steps.find(s=>s.street==='PREFLOP'&&s.actionType==='raise');
const t3TieABet=t3TieA.steps.find(s=>s.street==='FLOP'&&s.actionType==='bet');
const t3TieBCall=t3TieB.steps.find(s=>s.street==='PREFLOP'&&s.actionType==='call');
const t3LatestRaise=t3Latest.steps.find(s=>s.street==='PREFLOP'&&s.actionType==='raise');
for(const step of [t3EarliestRaise,t3EarliestBet,t3UnknownRaise,t3TieARaise,t3TieABet,t3TieBCall,t3LatestRaise])assert.ok(step,'every T3 fixture must expose the reviewed Hero decisions');

const t3ReviewScores={
  '200002':{
    handId:'200002',signature:'sig-A',complete:true,analyzableDecisions:2,finishedDecisions:2,details:[
      {stepIndex:t3EarliestRaise.stepIndex,lossBB:2,rawLossBB:2,chosenEV:-1,bestEV:1,bestLabel:'CALL',withinNoise:false,comparable:true,
       simContext:{potType:'UNOPENED',preflopRole:'RFI',relativePosition:'IP'}},
      {stepIndex:t3EarliestBet.stepIndex,lossBB:1,rawLossBB:1,chosenEV:0,bestEV:1,bestLabel:'CHECK',withinNoise:false,comparable:true,
       simContext:{potType:'SRP',preflopRole:'PFR',relativePosition:'IP'}}
    ]
  },
  '200005':{
    handId:'200005',signature:'sig-A',complete:true,analyzableDecisions:1,finishedDecisions:1,details:[
      {stepIndex:t3UnknownRaise.stepIndex,lossBB:.5,rawLossBB:.5,chosenEV:.5,bestEV:1,bestLabel:'RAISE',withinNoise:false,comparable:true,
       simContext:{potType:'UNOPENED',preflopRole:'RFI',relativePosition:'IP'}}
    ]
  },
  '200003':{
    handId:'200003',signature:'sig-A',complete:true,analyzableDecisions:2,finishedDecisions:2,details:[
      {stepIndex:t3TieARaise.stepIndex,lossBB:0,rawLossBB:0,chosenEV:.6,bestEV:.6,bestLabel:'RAISE',withinNoise:false,comparable:true,
       simContext:{potType:'UNOPENED',preflopRole:'RFI',relativePosition:'IP'}},
      {stepIndex:t3TieABet.stepIndex,lossBB:1,rawLossBB:1,chosenEV:0,bestEV:1,bestLabel:'CHECK',withinNoise:false,comparable:true,
       simContext:{potType:'SRP',preflopRole:'PFR',relativePosition:'IP'}}
    ]
  },
  '200004':{
    handId:'200004',signature:'sig-A',complete:true,analyzableDecisions:1,finishedDecisions:1,details:[
      {stepIndex:t3TieBCall.stepIndex,lossBB:2,rawLossBB:2,chosenEV:-1,bestEV:1,bestLabel:'FOLD',withinNoise:false,comparable:true,
       simContext:{potType:'SRP',preflopRole:'CALLER',relativePosition:'IP'}}
    ]
  },
  '200001':{
    handId:'200001',signature:'sig-A',complete:true,analyzableDecisions:1,finishedDecisions:1,details:[
      {stepIndex:t3LatestRaise.stepIndex,lossBB:0,rawLossBB:0,chosenEV:.6,bestEV:.6,bestLabel:'RAISE',withinNoise:false,comparable:true,
       simContext:{potType:'UNOPENED',preflopRole:'RFI',relativePosition:'IP'}}
    ]
  }
};
const t3Source=[T3HH_EARLIEST,T3HH_UNKNOWN,T3HH_TIE_A,T3HH_TIE_B,T3HH_LATEST].join('\n');
const t3Inbox=Inbox.buildReviewInbox({
  reviewScores:t3ReviewScores,
  hhSources:[{name:'t3.txt',content:t3Source}],
  scope:SCOPE,
  user_metadata:{},
  // No entry for 200005: the absent settlement must stay UNKNOWN.
  hand_results:{'200001':0,'200002':6.5,'200003':-4,'200004':6.5}
});

// #395 T3: settlement mapping, real timestamps and the anti-correlated fixture.
{
  const t3Items=t3Inbox.items,t3=new Map(t3Items.map(x=>[x.hand_id,x]));
  assert.equal(t3Items.length,5,'the T3 fixture must expose all five hands');
  assert.match(t3Inbox.scope.strategy_version,/runtime-r1@sig-A$/);
  for(const id of ['200001','200002','200003','200004','200005'])assert.ok(t3.get(id),'T3 hand '+id+' must be present');

  // The instants are the parsed header timestamps, and the numeric ids are
  // anti-correlated on purpose: the smallest id (200001) is the latest hand,
  // the largest id (200005) is the second earliest, and the instant tie pairs
  // hand 200003 with the larger id 200004.
  assert.equal(t3.get('200002').timestamp,'2026-09-18T19:45:00Z');
  assert.equal(t3.get('200005').timestamp,'2026-09-18T20:30:00Z');
  assert.equal(t3.get('200003').timestamp,'2026-09-18T21:10:00Z');
  assert.equal(t3.get('200004').timestamp,'2026-09-18T21:10:00Z');
  assert.equal(t3.get('200001').timestamp,'2026-09-18T23:20:00Z');
  assert.equal(t3.get('200003').timestamp,t3.get('200004').timestamp,'the tie pair shares one instant on purpose');
  assert.equal(new Set(t3Items.map(x=>x.timestamp)).size,4,'four distinct instants must back the five hands');

  const handResults={'200001':0,'200002':6.5,'200003':-4,'200004':6.5};
  for(const [id,net] of Object.entries(handResults)){
    const item=t3.get(id);
    assert.equal(item.hero_net_bb,net,'hand '+id+' must carry the real settlement in BB');
    assert.equal(item.result.net_bb,net,'hand '+id+' result.net_bb mirrors hero_net_bb');
    assert.equal(item.result.state,Inbox.resultStateFor(net),'hand '+id+' must map its settlement to the right state');
  }
  // The real result is an independent input: the EV loss keeps its own value
  // (+6.5 BB won is not a 6.5 BB EV loss) and is never derived from it.
  assert.notEqual(t3.get('200002').total_loss_bb,t3.get('200002').hero_net_bb,'the real result must never become the EV loss');
  assert.equal(t3.get('200002').total_loss_bb,3,'the T3 EV losses stay computed from the decision events');
  assert.equal(t3.get('200004').total_loss_bb,2);
  assert.equal(t3.get('200003').total_loss_bb,1);
  assert.equal(t3.get('200005').total_loss_bb,.5);
  assert.equal(t3.get('200001').total_loss_bb,0);

  // The absent settlement is UNKNOWN and is never invented as EVEN/0.
  assert.equal(t3.get('200005').hero_net_bb,null,'a hand absent from hand_results never invents a net');
  assert.deepEqual(t3.get('200005').result,{state:'UNKNOWN',net_bb:null});
  assert.deepEqual(['200002','200004','200003','200001','200005'].map(id=>t3.get(id).result.state),['WIN','WIN','LOSS','EVEN','UNKNOWN'],'the fixture must cover gain, loss, neutral and unknown');
}

// #395 T3: TIMESTAMP_DESC/ASC follow the parsed instants, not the hand_id.
{
  const timestampAsc=['200002','200005','200003','200004','200001'];
  const timestampDesc=['200001','200003','200004','200005','200002'];
  assert.deepEqual(Inbox.sortInboxItems(t3Inbox.items,'TIMESTAMP_ASC').map(x=>x.hand_id),timestampAsc,'TIMESTAMP_ASC must order on the real timestamps');
  assert.deepEqual(Inbox.sortInboxItems(t3Inbox.items,'TIMESTAMP_DESC').map(x=>x.hand_id),timestampDesc,'TIMESTAMP_DESC must reverse the real timestamps');
  assert.notDeepEqual(timestampAsc,[...t3Inbox.items.map(x=>x.hand_id)].sort(),'the fixture must not be id-ordered, otherwise the assertion above proves nothing');
  assert.notDeepEqual(timestampDesc,timestampAsc.slice().reverse(),'the descending order keeps the hand_id ascending inside the instant tie instead of mirroring the ascending list');
  assert.deepEqual(timestampAsc.slice(2,4),['200003','200004'],'the two hands sharing 2026-09-18T21:10:00Z are tie-broken by hand_id');
}

// #395 T3: gain/loss sorts rank the real BB net; UNKNOWN is never a 0.
{
  const gainDesc=['200002','200004','200001','200003','200005'];
  const lossDesc=['200003','200001','200002','200004','200005'];
  assert.deepEqual(Inbox.sortInboxItems(t3Inbox.items,'RESULT_GAIN_DESC').map(x=>x.hand_id),gainDesc,'RESULT_GAIN_DESC must rank the biggest gains first');
  assert.deepEqual(Inbox.sortInboxItems(t3Inbox.items,'RESULT_LOSS_DESC').map(x=>x.hand_id),lossDesc,'RESULT_LOSS_DESC must rank the biggest losses first');
  assert.deepEqual(Inbox.sortInboxItems(t3Inbox.items,'RESULT_GAIN_DESC').map(x=>x.hero_net_bb),[6.5,6.5,0,-4,null],'the gain ranking reads the BB net and carries UNKNOWN last');
  assert.deepEqual(Inbox.sortInboxItems(t3Inbox.items,'RESULT_LOSS_DESC').map(x=>x.hero_net_bb),[-4,0,6.5,6.5,null],'the loss ranking reads the BB net and carries UNKNOWN last');
  // Two hands share +6.5 BB and two instants coincide: equal keys are always
  // settled by hand_id, so the input order can never change the output.
  for(const [mode,expected] of [
    ['TIMESTAMP_ASC',['200002','200005','200003','200004','200001']],
    ['TIMESTAMP_DESC',['200001','200003','200004','200005','200002']],
    ['RESULT_GAIN_DESC',gainDesc],
    ['RESULT_LOSS_DESC',lossDesc],
    ['EV_LOSS_DESC',['200002','200004','200003','200005','200001']]
  ]){
    assert.deepEqual(Inbox.sortInboxItems([...t3Inbox.items].reverse(),mode).map(x=>x.hand_id),expected,'sort '+mode+' must be deterministic and independent from the input order');
  }
}

// #395 T3: the result filter, alone and combined with the existing filters.
{
  const ids=(filters,sort)=>Inbox.queryInbox(t3Inbox,filters,sort||'HAND_ID_ASC').items.map(x=>x.hand_id);
  assert.deepEqual(ids({result:'WIN'}),['200002','200004'],'WIN keeps only the positive nets');
  assert.deepEqual(ids({result:'LOSS'}),['200003'],'LOSS keeps only the negative nets');
  assert.deepEqual(ids({result:'EVEN'}),['200001'],'EVEN keeps only the neutral nets');
  assert.deepEqual(ids({result:'unknown'}),['200005'],'the result filter is case-insensitive');
  assert.deepEqual(ids({result:['WIN','LOSS']}),['200002','200003','200004']);
  assert.deepEqual(ids({result:''}),['200001','200002','200003','200004','200005'],'an empty result filter matches everything');
  assert.deepEqual(ids({}),['200001','200002','200003','200004','200005'],'the unknown result stays present in « Toutes »');

  const unknown=Inbox.queryInbox(t3Inbox,{result:'UNKNOWN'},'HAND_ID_ASC').items;
  assert.deepEqual(unknown.map(x=>x.hand_id),['200005']);
  assert.equal(unknown[0].hero_net_bb,null,'an unknown result is never invented as a number');
  assert.deepEqual(unknown[0].result,{state:'UNKNOWN',net_bb:null});
  for(const state of ['WIN','LOSS','EVEN']){
    assert.ok(!ids({result:state}).includes('200005'),'an UNKNOWN settlement must never be reported as '+state);
  }
  assert.deepEqual(ids({result:['WIN','LOSS','EVEN']}),['200001','200002','200003','200004'],'the settled filters exclude the unknown hand');

  // result + the pre-existing filters, on a hand_id-independent sort.
  assert.deepEqual(ids({result:'WIN',min_loss_bb:2.5}),['200002'],'result composes with min_loss_bb');
  assert.deepEqual(ids({result:['WIN','LOSS'],min_loss_bb:2}),['200002','200004']);
  assert.deepEqual(ids({result:'WIN',action_played:'CALL'}),['200004'],'result composes with the played-action facet');
  assert.deepEqual(ids({result:'LOSS',street:'FLOP',action_played:'BET'}),['200003'],'result composes with street + facet filters');
  assert.deepEqual(ids({result:'EVEN',status:'CORRECT'}),['200001'],'result composes with the status filter');
  assert.deepEqual(ids({result:'UNKNOWN',min_loss_bb:1}),[],'an UNKNOWN hand still obeys the other filters');
  assert.deepEqual(Inbox.queryInbox(t3Inbox,{result:['WIN','LOSS']},'RESULT_GAIN_DESC').items.map(x=>x.hand_id),['200002','200004','200003'],'filtered result sorts stay deterministic');
}

// #395 T3: EV_LOSS_DESC stays available and is unchanged by the settlement.
{
  const evLossDesc=['200002','200004','200003','200005','200001'];
  assert.ok(Inbox.SORT_MODES.includes('EV_LOSS_DESC'));
  assert.deepEqual(Inbox.sortInboxItems(t3Inbox.items,'EV_LOSS_DESC').map(x=>x.hand_id),evLossDesc,'EV_LOSS_DESC must keep ranking on the EV loss');
  assert.deepEqual(t3Inbox.items.map(x=>x.hand_id),evLossDesc,'the default inbox order must stay EV_LOSS_DESC');
  assert.equal(Inbox.queryInbox(t3Inbox,{}).sort,'EV_LOSS_DESC','the default query sort must stay EV_LOSS_DESC');
  assert.notDeepEqual(evLossDesc,['200002','200004','200001','200003','200005'],'EV_LOSS_DESC must not be the settlement order');

  const t3Unsettled=Inbox.buildReviewInbox({
    reviewScores:t3ReviewScores,
    hhSources:[{name:'t3.txt',content:t3Source}],
    scope:SCOPE,user_metadata:{}
  });
  const unsettled=new Map(t3Unsettled.items.map(x=>[x.hand_id,x]));
  assert.equal(t3Unsettled.items.length,5);
  for(const item of t3Unsettled.items)assert.deepEqual(item.result,{state:'UNKNOWN',net_bb:null},'without hand_results every hand stays UNKNOWN');
  assert.deepEqual(Inbox.sortInboxItems(t3Unsettled.items,'EV_LOSS_DESC').map(x=>x.hand_id),evLossDesc,'EV_LOSS_DESC must be byte-identical with and without the settlement input');
  assert.deepEqual(t3Unsettled.items.map(x=>x.hand_id),evLossDesc);
  for(const [id,item] of unsettled){
    const settled=t3Inbox.items.find(x=>x.hand_id===id);
    for(const field of ['total_loss_bb','nominal_loss_bb','main_street','position','spot_family','action_played','action_recommended','status','timestamp','coverage_state','deep_link','analysis_state']){
      assert.deepEqual(settled[field],item[field],'the real result must not alter item.'+field+' for hand '+id);
    }
  }
}

// #395 T1: the runtime mirror served by the site stays byte-identical.
{
  const src=fs.readFileSync(path.join(__dirname,'../../src/analytics/review-inbox.js'),'utf8');
  const runtime=fs.readFileSync(path.join(__dirname,'../../site/analytics/review-inbox.js'),'utf8');
  assert.equal(runtime,src,'site/analytics/review-inbox.js must stay byte-identical to src/analytics/review-inbox.js');
}

console.log(JSON.stringify({
  status:'PASS',
  schema:Inbox.INBOX_SCHEMA,
  hands:inbox.items.length,
  top_hand:inbox.items[0].hand_id,
  top_loss_bb:inbox.items[0].total_loss_bb
}));
