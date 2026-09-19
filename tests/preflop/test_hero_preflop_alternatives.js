#!/usr/bin/env node
'use strict';

const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const Core=require('../../src/training/nlhe-game-state.js');
const Alternatives=require('../../src/preflop/hero-preflop-alternatives.js');
const Diagnostics=require('../../src/preflop/iso-sizing-diagnostics.js');

const ROOT=path.resolve(__dirname,'../..');
const FIX=JSON.parse(fs.readFileSync(path.join(ROOT,'tests/fixtures/hero-preflop-alternatives/scenarios.json'),'utf8'));
const ISSUE321=JSON.parse(fs.readFileSync(path.join(ROOT,'tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.snapshots.json'),'utf8'));
const ISSUE319=JSON.parse(fs.readFileSync(path.join(ROOT,'analysis/preflop_sizing_support_train.json'),'utf8'));

function buildState(setup,actions=[]){
  const state=new Core.NoLimitHoldemState(setup);
  for(const row of actions){
    const options=row.target_total_bb==null?{}:{target_total_bb:row.target_total_bb};
    state.applyAction(row.player,row.action,options);
  }
  return state;
}

function supportView(rows,id='fixture-exact-support'){
  return {
    schema:Alternatives.SUPPORT_VIEW_SCHEMA,
    source_schema:'poker-preflop-sizing-support-audit/v1',
    source_id:id,
    source_hash:'sha256:fixture',
    exact_price_only:true,
    no_silent_nearest_price:true,
    exact_target_support:rows
  };
}

function alt(result,id){
  const row=result.alternatives.find(item=>item.id===id);
  assert(row,'missing alternative '+id);
  return row;
}

function canonicalAlternativeShape(row){
  assert.deepEqual(
    Object.keys(row).sort(),
    ['action','comparable','comparability_reason','confidence','ev_bb','id','incremental_cost_bb','support','target_sizing','uncertainty'].sort()
  );
  assert.equal(row.ev_bb,null);
  assert.equal(row.uncertainty,null);
  assert.equal(row.confidence,null);
  assert.equal(row.comparable,false);
}

function testGenericScenariosUseRealCore(){
  for(const scenario of FIX.generic_scenarios){
    const state=buildState(scenario.setup,scenario.pre_actions);
    assert.equal(state.next_actor,scenario.actor,scenario.id+' actor');
    const legal=state.legalView();
    const result=Alternatives.enumerateHeroAlternatives({
      state,
      requested_raise_targets_bb:scenario.requested_raise_targets_bb,
      exact_support:supportView(scenario.exact_support,scenario.id)
    });
    assert.equal(result.schema,Alternatives.SCHEMA);
    assert.equal(result.core_legal_view.min_raise_to_bb,legal.min_raise_to_bb);
    assert.equal(result.core_legal_view.max_raise_to_bb,legal.max_raise_to_bb);
    assert.equal(result.core_legal_view.to_call_bb,legal.to_call_bb);
    assert.equal(result.exact_support.nearest_price_used,false);
    assert.equal(result.information_boundary.future_cards_consumed,false);
    assert.equal(result.information_boundary.opponent_hole_cards_consumed,false);
    assert.equal(result.information_boundary.recommendation_consumed,false);
    assert.equal(result.scientific_boundary.ev_computed,false);

    const call=result.alternatives.find(row=>row.action===scenario.expected_call_action);
    assert(call,scenario.id+' expected '+scenario.expected_call_action);
    assert.equal(call.incremental_cost_bb,legal.to_call_bb);

    for(const row of scenario.exact_support){
      const id=scenario.expected_raise_action+'@'+String(row.target_total_bb);
      const candidate=alt(result,id);
      assert.equal(candidate.support.status,Alternatives.EXACT_SUPPORTED);
      assert.equal(candidate.support.observations,row.observations);
      assert.equal(candidate.incremental_cost_bb,Number(row.target_total_bb)-legal.actor_street_contribution_bb);
      canonicalAlternativeShape(candidate);
    }
    const unsupportedTarget=scenario.requested_raise_targets_bb.at(-1);
    const unsupported=alt(result,scenario.expected_raise_action+'@'+String(unsupportedTarget));
    assert.equal(unsupported.support.status,Alternatives.LEGAL_BUT_UNSUPPORTED);
    assert.equal(unsupported.support.observations,0);
    assert.match(unsupported.comparability_reason,/LEGAL_BUT_UNSUPPORTED/);
  }
}

function testIssue321AgainstRealFixtureAndIssue319(){
  assert.equal(ISSUE321.scenario_id,'kts_sb_two_limp_iso4_three_calls_v1');
  const state=new Core.NoLimitHoldemState({
    seats:['BTN','Hero','BB','UTG','HJ','CO'],
    button:'BTN',
    stacks_bb:{BTN:100,Hero:100,BB:100,UTG:100,HJ:100,CO:100}
  });
  state.applyAction('UTG','FOLD');
  state.applyAction('HJ','FOLD');
  state.applyAction('CO','CALL');
  state.applyAction('BTN','CALL');

  const expected=ISSUE321.snapshots.find(row=>row.id==='before_hero');
  assert(expected,'#321 before_hero snapshot is required');
  assert.deepEqual(state.toSnapshot({include_log:false}),expected.state);
  assert.deepEqual(state.legalView(),expected.legal);

  const support=Alternatives.supportViewFromIssue319Kts(ISSUE319);
  const supportByTarget=Object.fromEntries(support.exact_target_support.map(row=>[row.target_total_bb,row.observations]));
  assert.equal(supportByTarget[4],13);
  assert.equal(supportByTarget[5],56);
  assert.equal(supportByTarget[6],9);

  const result=Alternatives.enumerateHeroAlternatives({
    state,
    requested_raise_targets_bb:FIX.canonical_fixture_reference.requested_raise_targets_bb,
    exact_support:support
  });
  assert.equal(result.family,'VS_LIMPERS');
  assert.equal(result.hero_position,'SB');
  assert.deepEqual(result.core_legal_view.legal_actions,['FOLD','CALL','RAISE']);
  assert.equal(result.core_legal_view.min_raise_to_bb,2);
  assert.equal(result.core_legal_view.max_raise_to_bb,100);

  assert.equal(alt(result,'FOLD').incremental_cost_bb,0);
  assert.equal(alt(result,'OVERLIMP@1').incremental_cost_bb,.5);
  assert.equal(alt(result,'ISO@4').incremental_cost_bb,3.5);
  assert.equal(alt(result,'ISO@5').incremental_cost_bb,4.5);
  assert.equal(alt(result,'ISO@6').incremental_cost_bb,5.5);
  assert.equal(alt(result,'ISO@4').support.observations,13);
  assert.equal(alt(result,'ISO@5').support.observations,56);
  assert.equal(alt(result,'ISO@6').support.observations,9);

  const near=alt(result,'ISO@6.0001');
  assert.equal(near.support.status,Alternatives.LEGAL_BUT_UNSUPPORTED,'nearest-price substitution is forbidden');
  assert.equal(result.exact_support.nearest_price_used,false);
  assert(result.legal_but_unsupported_ids.includes('ISO@6.0001'));

  const bounds=Alternatives.enumerateHeroAlternatives({
    state,
    requested_raise_targets_bb:[1.5,101],
    exact_support:support
  });
  assert.deepEqual(bounds.rejected_targets,[
    {target_total_bb:1.5,status:'ILLEGAL',reason:'BELOW_MIN'},
    {target_total_bb:101,status:'ILLEGAL',reason:'ABOVE_MAX'}
  ]);
}

function test322And278CompatibilityWithoutEv(){
  const scenario=FIX.generic_scenarios.find(row=>row.id==='squeeze_candidate');
  const state=buildState(scenario.setup,scenario.pre_actions);
  const result=Alternatives.enumerateHeroAlternatives({
    state,
    requested_raise_targets_bb:scenario.requested_raise_targets_bb,
    exact_support:supportView(scenario.exact_support,scenario.id)
  });
  for(const row of result.alternatives)canonicalAlternativeShape(row);

  const canonical={
    schema:'poker-preflop-decision/v1',
    contract_profile:'CANONICAL_RUNTIME_DECISION_V1',
    decision_id:null,
    context_id:result.context_id,
    alternatives:result.alternatives
  };
  const normalized=Diagnostics.canonicalDecision(canonical);
  assert.equal(normalized.context_id,result.context_id);
  assert.equal(normalized.alternatives.length,result.alternatives.length);
  assert(normalized.alternatives.every(row=>row.ev_bb===null));
  assert(normalized.alternatives.some(row=>row.action==='SQUEEZE'));
}

function testSupportViewFailsClosed(){
  const bad={
    schema:Alternatives.SUPPORT_VIEW_SCHEMA,
    source_id:'bad',
    exact_price_only:true,
    no_silent_nearest_price:false,
    exact_target_support:[{target_total_bb:5,observations:1}]
  };
  assert.throws(
    ()=>Alternatives.normalizeExactSupportView(bad),
    err=>err.code==='SUPPORT_VIEW_INVALID'
  );
}

const tests=[
  testGenericScenariosUseRealCore,
  testIssue321AgainstRealFixtureAndIssue319,
  test322And278CompatibilityWithoutEv,
  testSupportViewFailsClosed
];
for(const fn of tests)fn();
console.log('hero preflop legal alternatives tests: '+tests.length+' passed');
