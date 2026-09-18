'use strict';

const assert=require('node:assert/strict');
const Leak=require('../../src/analytics/leak-analyzer.js');
const Adapter=require('../../src/analytics/review-score-adapter.js');
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
assert.equal(reviewScores['100003'].reviewed,undefined,'user review state must never enter reviewScores');

assert.equal(i4.user_review.reviewed,true,'user metadata remains available even when science is incomplete');
assert.equal(i4.status,Inbox.STATUS.INCOMPLETE_ANALYSIS,'incomplete science must remain visible even if user marked it reviewed');
assert.equal(i4.status_label,'Analyse incomplète');
assert.equal(i4.coverage.complete,false);
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
    reviewScores:{'999999':{handId:'999999',signature:'sig-A',complete:false,analyzableDecisions:1,finishedDecisions:0,details:[]}},
    hhSources:[],scope:SCOPE,user_metadata:{}
  });
  assert.equal(missing.items.length,1);
  const item=missing.items[0];
  assert.equal(item.status,Inbox.STATUS.INCOMPLETE_ANALYSIS);
  assert.ok(item.coverage.reasons.includes('MISSING_HH_SOURCE'));
  assert.equal(item.deep_link,null);
  assert.equal(item.total_loss_bb,0);
}

assert.throws(()=>Inbox.setReviewed({},'x',true,'invalid-date'),/valid timestamp/);
assert.throws(()=>Inbox.queryInbox(inbox,{min_loss_bb:-1}),/non-negative/);
assert.throws(()=>Inbox.queryInbox(inbox,{jam:'maybe'}),/boolean filter/);

console.log(JSON.stringify({
  status:'PASS',
  schema:Inbox.INBOX_SCHEMA,
  hands:inbox.items.length,
  top_hand:inbox.items[0].hand_id,
  top_loss_bb:inbox.items[0].total_loss_bb
}));
