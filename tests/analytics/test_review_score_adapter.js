'use strict';

const assert=require('node:assert/strict');
const Leak=require('../../src/analytics/leak-analyzer.js');
const Adapter=require('../../src/analytics/review-score-adapter.js');

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
*** SHOW DOWN ***
Hero: shows [As Kd]
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
Hero: bets 600
CO2: calls 600
*** TURN *** [Qh 8d 3s] [2c]
CO2: checks
Hero: checks
*** RIVER *** [Qh 8d 3s 2c] [9s]
CO2: bets 1200
Hero: folds
*** SUMMARY ***
Total pot 3400 | Rake 0
`;

const h1=Adapter.parseStoredHand(HH1,'one.txt');
const h2=Adapter.parseStoredHand(HH2,'two.txt');
assert.equal(h1.heroPosition,'BTN');
assert.equal(h2.heroPosition,'BTN');
const hero1=h1.steps.filter(s=>s.player==='Hero');
const hero2=h2.steps.filter(s=>s.player==='Hero');
const h1Raise=hero1.find(s=>s.street==='PREFLOP'&&s.actionType==='raise');
const h1Bet=hero1.find(s=>s.street==='FLOP'&&s.actionType==='bet');
const h2Call=hero2.find(s=>s.street==='PREFLOP'&&s.actionType==='call');
const h2Bet=hero2.find(s=>s.street==='FLOP'&&s.actionType==='bet');
const h2Check=hero2.find(s=>s.street==='TURN'&&s.actionType==='check');
const h2Fold=hero2.find(s=>s.street==='RIVER'&&s.actionType==='fold');
assert.ok(h1Raise&&h1Bet&&h2Call&&h2Bet&&h2Check&&h2Fold);

const reviewScores={
  '100001':{
    handId:'100001',signature:'sig-A',complete:true,details:[
      {stepIndex:h1Bet.stepIndex,lossBB:1.7,rawLossBB:2,chosenEV:-1,bestEV:1,bestLabel:'CHECK',withinNoise:false,comparable:true,
       simContext:{potType:'SRP',preflopRole:'PFR',relativePosition:'IP'}}
    ]
  },
  '100002':{
    handId:'100002',signature:'sig-A',complete:true,details:[
      {stepIndex:h2Call.stepIndex,lossBB:.08,rawLossBB:.1,chosenEV:.9,bestEV:1,bestLabel:'FOLD',withinNoise:true,comparable:true},
      {stepIndex:h2Bet.stepIndex,lossBB:.6,rawLossBB:.7,chosenEV:.2,bestEV:.9,bestLabel:'BET 5 BB',bestCostBB:5,withinNoise:false,comparable:true,
       simContext:{potType:'SRP',preflopRole:'CALLER',relativePosition:'IP'}},
      {stepIndex:h2Check.stepIndex,lossBB:0,rawLossBB:0,chosenEV:.5,bestEV:.5,bestLabel:'CHECK',withinNoise:false,comparable:true},
      {stepIndex:h2Fold.stepIndex,lossBB:0,rawLossBB:.4,chosenEV:null,bestEV:null,bestLabel:'CALL',withinNoise:false,comparable:false}
    ]
  }
};

const scope={population_id:'pokerstars_nlhe_100-200_zoom_play_6max_v1',pack_id:'zoom-pack@1',strategy_id:'custom_ranges_v1',strategy_version:'runtime-r1'};
const adapted=Adapter.adaptPersistedReviewData({reviewScores,hhSources:[{name:'hands.txt',content:HH1+'\n'+HH2}],scope});
assert.equal(adapted.schema,Adapter.ADAPTER_SCHEMA);
assert.equal(adapted.scope_keys.length,1);
assert.equal(adapted.warnings.length,0);

const byId=new Map(adapted.events.map(e=>[e.decision_id,e]));
const unsupported=byId.get(`review:100001:${h1Raise.stepIndex}`);
const jam=byId.get(`review:100001:${h1Bet.stepIndex}`);
const noise=byId.get(`review:100002:${h2Call.stepIndex}`);
const sizing=byId.get(`review:100002:${h2Bet.stepIndex}`);
const nonComparable=byId.get(`review:100002:${h2Fold.stepIndex}`);
assert.ok(unsupported&&!unsupported.support.covered);
assert.equal(unsupported.error_type,'UNSUPPORTED');
assert.equal(jam.tags.jam,true);
assert.equal(jam.tags.overbet,true);
assert.equal(jam.context.position,'BTN');
assert.equal(jam.context.street,'FLOP');
assert.equal(jam.context.spot_family,'SRP|PFR|IP');
assert.equal(jam.ev.attributed_loss_bb,1.7);
assert.equal(noise.within_noise,true);
assert.equal(noise.error_type,'WITHIN_NOISE');
assert.equal(noise.ev.attributed_loss_bb,0);
assert.equal(sizing.error_type,'SIZING_ERROR');
assert.equal(sizing.sizing_error,true);
assert.equal(sizing.recommended.target_total_bb,5);
assert.equal(nonComparable.error_type,'NON_COMPARABLE');
assert.equal(nonComparable.ev.played_bb,null);
assert.match(jam.strategy_version,/runtime-r1@sig-A$/);
assert.equal(jam.ev_reference,Adapter.DEFAULT_EV_REFERENCE);

const report=Leak.analyzeLeaks(adapted.events);
assert.equal(report.summary.total_loss_bb,2.3);
assert.equal(report.summary.within_noise_decisions,1);
assert.equal(report.summary.unsupported_decisions,1);
assert.equal(report.summary.non_comparable_decisions,1);
assert.equal(report.leaks.aggressive_sizing.jam.total_loss_bb,1.7);
assert.ok(report.leaks.by.spot_family.some(x=>x.key==='SRP|CALLER|IP'));

const source=Adapter.handSource(adapted,'100001',jam.decision_id);
assert.equal(source.source_name,'hands.txt');
assert.equal(source.hero_position,'BTN');
assert.match(source.action_line,/Hero: bets 1400 and is all-in/);
assert.match(source.raw_hand_history,/PokerStars Zoom Hand #100001/);

const filtered=Leak.analyzeLeaks(adapted.events,{action_played:'BET',sizing_error:true,position:'BTN'});
assert.equal(filtered.summary.decisions_selected,1);
assert.equal(filtered.decision_events[0].decision_id,sizing.decision_id);

const secondScores=JSON.parse(JSON.stringify(reviewScores));
secondScores['100002'].signature='sig-B';
const split=Adapter.adaptPersistedReviewData({reviewScores:secondScores,hhSources:[{name:'hands.txt',content:HH1+'\n'+HH2}],scope});
assert.equal(split.scope_keys.length,2);
assert.throws(()=>Leak.analyzeLeaks(split.events),/analysis spans 2/);
assert.equal(Leak.analyzeByScope(split.events).length,2);

const missing=Adapter.adaptPersistedReviewData({reviewScores:{'999999':{signature:'x',details:[]}},hhSources:[],scope});
assert.equal(missing.events.length,0);
assert.deepEqual(missing.warnings,['Missing HH source for review score 999999']);

// #392: the Review scope can be derived from the population-bound resolver.
{
  const resolvedScope=Adapter.reviewScopeFromResolution({
    population_id:scope.population_id,status:'ADMISSIBLE_CALCULATED',source:'POPULATION',fail_closed:false,
    strategy_id:'hero-candidate-196',strategy_version:'gen-196'
  },{pack_id:scope.pack_id});
  assert.equal(resolvedScope.strategy_id,'hero-candidate-196');
  assert.equal(resolvedScope.strategy_version,'gen-196');
  assert.equal(resolvedScope.availability.available,true);

  const unavailableScope=Adapter.reviewScopeFromResolution({
    population_id:scope.population_id,status:'UNAVAILABLE',source:'NONE',fail_closed:true,reason_codes:['NO_ADMISSIBLE_STRATEGY']
  },{pack_id:scope.pack_id});
  assert.equal(unavailableScope.strategy_id,Adapter.UNAVAILABLE_STRATEGY_ID);
  assert.equal(unavailableScope.strategy_version,'UNAVAILABLE@UNAVAILABLE');
  assert.equal(unavailableScope.availability.available,false);
  assert.ok(unavailableScope.availability.reason_codes.includes('NO_ADMISSIBLE_STRATEGY'));
}

console.log(JSON.stringify({status:'PASS',schema:Adapter.ADAPTER_SCHEMA,events:adapted.events.length,total_loss_bb:report.summary.total_loss_bb}));
