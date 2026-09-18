'use strict';

const assert=require('node:assert/strict');
const Leak=require('../../src/analytics/leak-analyzer.js');

const POP='pokerstars_nlhe_100-200_zoom_play_6max_v1';
const STRATEGY='hero-strategy';
const VERSION='v1';
const EVREF='decision_point_incremental_bb';

function event(id,overrides={}){
  return {
    hand_id:`h${id}`,
    decision_id:`d${id}`,
    timestamp:`2026-09-${String(10+id).padStart(2,'0')}T12:00:00Z`,
    population_id:POP,
    pack_id:'zoom-pack-v1',
    strategy_id:STRATEGY,
    strategy_version:VERSION,
    ev_reference:EVREF,
    position:'CO',street:'PREFLOP',spot_family:'OPEN_VS_3BET',context_id:`ctx-${id}`,
    action_played:'CALL',action_recommended:'FOLD',
    played_ev_bb:-1,best_ev_bb:0,uncertainty_bb:.05,
    support:{covered:true,observations:120,source:'replayer'},
    comparability:{comparable:true},
    ...overrides
  };
}

const events=[
  event(1,{played_ev_bb:-1.5,position:'CO',action_played:'CALL',action_recommended:'FOLD'}),
  event(2,{played_ev_bb:.2,best_ev_bb:1,position:'BTN',street:'RIVER',spot_family:'RIVER_FACING_BET',action_played:'BET',action_recommended:'BET',played_target_total_bb:20,recommended_target_total_bb:10,played_size_pot_ratio:1.5,recommended_size_pot_ratio:.75}),
  event(3,{played_ev_bb:.95,best_ev_bb:1,uncertainty_bb:.1,position:'SB',street:'TURN',spot_family:'TURN_PROBE',action_played:'CHECK',action_recommended:'BET'}),
  event(4,{played_ev_bb:-9,best_ev_bb:0,support:{covered:false,reason:'NO_MODEL_SUPPORT'},position:'BB'}),
  event(5,{played_ev_bb:-7,best_ev_bb:0,comparability:{comparable:false,reason:'DIFFERENT_EV_BASELINE'},position:'HJ'}),
  event(6,{played_ev_bb:.4,best_ev_bb:.4,position:'UTG',street:'FLOP',spot_family:'CBET',action_played:'CHECK',action_recommended:'CHECK'}),
  event(7,{played_ev_bb:-2,best_ev_bb:0,position:'BTN',street:'PREFLOP',spot_family:'4BET_POT',action_played:'SHOVE',action_recommended:'CALL',played_is_all_in:true})
];

{
  const built=Leak.buildDecisionEvent(events[0]);
  assert.equal(built.schema,Leak.EVENT_SCHEMA);
  assert.equal(built.error_type,'ACTION_ERROR');
  assert.equal(built.ev.nominal_loss_bb,1.5);
  assert.equal(built.ev.attributed_loss_bb,1.5);
}

{
  const report=Leak.analyzeLeaks(events);
  assert.equal(report.schema,Leak.REPORT_SCHEMA);
  assert.deepEqual(report.scope,{
    population_id:POP,pack_id:'zoom-pack-v1',strategy_id:STRATEGY,strategy_version:VERSION,ev_reference:EVREF
  });
  assert.equal(report.summary.decisions_selected,7);
  assert.equal(report.summary.decisions_eligible,5,'unsupported and non-comparable decisions must not enter EV totals');
  assert.equal(report.summary.decisions_contributing,3,'within-noise and zero-loss decisions must not become leaks');
  assert.equal(report.summary.within_noise_decisions,1);
  assert.equal(report.summary.total_loss_bb,4.3);
  assert.equal(report.summary.nominal_loss_bb,4.35,'nominal loss remains auditable even when a delta is within uncertainty');
  assert.equal(report.summary.hands_analyzed,5);
  assert.equal(report.summary.loss_bb_per_100_hands,86);
  assert.equal(report.summary.coverage_pct,71.428571429);
  assert.equal(report.summary.exclusions['UNSUPPORTED:NO_MODEL_SUPPORT'],1);
  assert.equal(report.summary.exclusions['NON_COMPARABLE:DIFFERENT_EV_BASELINE'],1);

  const sum=report.decision_events
    .filter(x=>x.support.covered&&x.comparability.comparable)
    .reduce((acc,x)=>acc+x.ev.attributed_loss_bb,0);
  assert.equal(Math.round(sum*1e9)/1e9,report.summary.total_loss_bb,'aggregate loss must be exactly reconstructible from source decisions');

  const actionErrors=report.leaks.by.error_type.find(x=>x.key==='ACTION_ERROR');
  const sizingErrors=report.leaks.by.error_type.find(x=>x.key==='SIZING_ERROR');
  assert.equal(actionErrors.total_loss_bb,3.5);
  assert.equal(sizingErrors.total_loss_bb,.8);
  assert.deepEqual(sizingErrors.source_refs,[{hand_id:'h2',decision_id:'d2'}]);
  assert.equal(report.leaks.aggressive_sizing.overbet.total_loss_bb,.8);
  assert.equal(report.leaks.aggressive_sizing.jam.total_loss_bb,2);
  assert.equal(report.leaks.top_decisions[0].decision_id,'d7');
  assert.equal(report.leaks.top_decisions[1].decision_id,'d1');
}

{
  const report=Leak.analyzeLeaks(events,{position:['BTN'],from:'2026-09-12T00:00:00Z',to:'2026-09-17T23:59:59Z'});
  assert.equal(report.summary.decisions_selected,2);
  assert.equal(report.summary.total_loss_bb,2.8);
  assert.equal(report.leaks.by.position[0].key,'BTN');
}

{
  const other=event(8,{strategy_version:'v2'});
  assert.throws(()=>Leak.analyzeLeaks([...events,other]),/analysis spans 2/,'strategy versions must never be silently mixed');
  const scoped=Leak.analyzeByScope([...events,other]);
  assert.equal(scoped.length,2);
  assert.deepEqual(scoped.map(x=>x.scope.strategy_version),['v1','v2']);
}

{
  const report=Leak.analyzeLeaks(events);
  const json=Leak.exportReportJSON(report,{pretty:false});
  assert.equal(JSON.parse(json).summary.total_loss_bb,4.3);
  const csv=Leak.exportReportCSV(report);
  assert.ok(csv.startsWith('row_type,dimension,key,'));
  assert.ok(csv.includes('GROUP,error_type,ACTION_ERROR'));
  assert.ok(csv.includes('DECISION,,,h2,d2'));
}

assert.throws(()=>Leak.buildDecisionEvent(event(9,{population_id:''})),/population_id is required/);
assert.throws(()=>Leak.buildDecisionEvent(event(9,{support:{covered:true,observations:1.5}})),/non-negative integer/);
assert.throws(()=>Leak.analyzeLeaks(events,{from:'not-a-date'}),/valid timestamp/);

console.log(JSON.stringify({status:'PASS',schema:Leak.REPORT_SCHEMA,total_loss_bb:Leak.analyzeLeaks(events).summary.total_loss_bb}));
