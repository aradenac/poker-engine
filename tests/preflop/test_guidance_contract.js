'use strict';

const assert=require('node:assert/strict');
const Decision=require('../../src/preflop/decision.js');
const Guidance=require('../../src/preflop/guidance.js');

const POP='pokerstars_nlhe_100-200_zoom_play_6max_v1';
const SHA_A='a'.repeat(64);
const SHA_B='b'.repeat(64);

function uncertainty(se=.08){
  return {
    monte_carlo:{standard_error_bb:se,samples:4000,method:'stratified_mc'},
    model:{lower_bb:-.3,upper_bb:.4,method:'bootstrap_context',status:'ESTIMATED'}
  };
}
function support(n=120){return {observations:n,backoff_level:'EXACT',source:'TRAIN'};}
function alternative(id,action,target,cost,ev){
  return {id,action,target_total_bb:target,incremental_cost_bb:cost,ev_bb:ev,support:support(),confidence:.72,uncertainty:uncertainty()};
}
function decision(){
  return Decision.buildDecision({
    context_id:'ctx-open-callers-co-100',population_id:POP,actor_contribution_bb:.5,
    legal_actions:['FOLD','CALL','3BET'],selected_id:'3bet-7.5',
    alternatives:[
      alternative('fold','FOLD',null,0,0),
      alternative('call','CALL',2,1.5,.62),
      alternative('3bet-6.5','3BET',6.5,6,1.08),
      alternative('3bet-7.5','3BET',7.5,7,1.21),
      alternative('3bet-9.0','3BET',9,8.5,1.13)
    ],
    search:{candidate_ids:['fold','call','3bet-6.5','3bet-7.5','3bet-9.0'],sizing_grid_source:'observed_plus_local_grid',budget:20000,seed:'109-guidance-fixture'}
  });
}
function strategy(state='PROMOTED',sha=SHA_A){
  return {state,strategy_id:'hero-preflop-v1',strategy_sha256:sha,population_id:POP,source:'promotion-registry'};
}
function snapshot(extra={}){
  return {street:'PREFLOP',context_id:'ctx-open-callers-co-100',population_id:POP,hero_hand_class:'AQs',board:[],...extra};
}

{
  const guidance=Guidance.buildGuidance({decision:decision(),strategy:strategy(),public_snapshot:snapshot()});
  assert.equal(guidance.schema,'poker-preflop-guidance/v1');
  assert.equal(guidance.recommendation_state,'PROMOTED');
  assert.equal(guidance.default_advice,true);
  assert.equal(guidance.advisory_label,'PROMOTED_GUIDANCE');
  assert.equal(guidance.future_cards_consumed,false);
  const shown=Guidance.surfacePayload(guidance);
  assert.equal(shown.action,'3BET');
  assert.equal(shown.target_total_bb,7.5);
  assert.equal(shown.incremental_cost_bb,7);
  assert.equal(shown.ev_bb,1.21);
  assert.equal(shown.ev_reference,'decision_point_incremental_bb');
  assert.equal(shown.alternatives.find(x=>x.id==='3bet-9.0').ev_bb,1.13);
  assert.equal(shown.support.observations,120);
  assert.equal(shown.confidence,.72);
}

{
  const guidance=Guidance.buildGuidance({decision:decision(),strategy:strategy(),public_snapshot:snapshot()});
  const surfaces=Guidance.surfaceBundle(guidance);
  assert.deepEqual(surfaces.feed,surfaces.detail,'feed and detail must receive the same canonical recommendation payload');
  assert.deepEqual(surfaces.feed,surfaces.trainer,'trainer must not recompute action, sizing or EV');
  for(const key of ['action','target_total_bb','incremental_cost_bb','ev_bb','selected_id','alternatives']){
    assert.deepEqual(surfaces.feed[key],Guidance.surfacePayload(guidance)[key],`${key} drifted between surfaces`);
  }
}

{
  const experimental=Guidance.buildGuidance({decision:decision(),strategy:strategy('EXPERIMENTAL'),public_snapshot:snapshot()});
  assert.equal(experimental.default_advice,false);
  assert.equal(experimental.advisory_label,'EXPERIMENTAL_NOT_DEFAULT');
  const defaultView=Guidance.surfacePayload(experimental);
  assert.equal(defaultView.action,null,'experimental candidates must never become default advice');
  assert.equal(defaultView.ev_bb,null);
  assert.equal(defaultView.alternatives.length,0);
  const optIn=Guidance.surfacePayload(experimental,{allow_experimental:true});
  assert.equal(optIn.action,'3BET');
  assert.equal(optIn.ev_bb,1.21);
  assert.equal(optIn.default_advice,false,'explicit experimental inspection must remain labelled non-default');
  assert.equal(optIn.recommendation_state,'EXPERIMENTAL');
}

{
  const none=Guidance.buildGuidance({decision:decision(),strategy:{state:'NO_VERDICT'},public_snapshot:snapshot()});
  const shown=Guidance.surfacePayload(none);
  assert.equal(shown.action,null);
  assert.equal(shown.target_total_bb,null);
  assert.equal(shown.incremental_cost_bb,null);
  assert.equal(shown.ev_bb,null);
  assert.equal(shown.recommendation_state,'NO_VERDICT');
}

assert.throws(()=>Guidance.buildGuidance({
  decision:decision(),strategy:{state:'PROMOTED',strategy_id:'x',population_id:POP},public_snapshot:snapshot()
}),/strategy_sha256/,'promotion without an immutable strategy identity must fail closed');

assert.throws(()=>Guidance.buildGuidance({
  decision:decision(),strategy:{state:'PROMOTED',strategy_id:'x',strategy_sha256:'short',population_id:POP},public_snapshot:snapshot()
}),/strategy_sha256/);

assert.throws(()=>Guidance.buildGuidance({
  decision:decision(),strategy:{state:'PROMOTED',strategy_id:'x',strategy_sha256:SHA_A,population_id:'other-pop'},public_snapshot:snapshot()
}),/population_id/,'cross-population guidance must fail closed');

for(const leaked of [
  {board:[12,14,31]},
  {public_cards:['As','Kd','2c']},
  {future_cards:[7]},
  {future_public_cards:['Qs']}
]){
  assert.throws(()=>Guidance.buildGuidance({decision:decision(),strategy:strategy(),public_snapshot:snapshot(leaked)}),/forbids/,'preflop guidance must not consume future public cards');
}

assert.throws(()=>Guidance.buildGuidance({
  decision:decision(),strategy:strategy(),public_snapshot:snapshot({street:'FLOP'})
}),/postflop street/);

assert.throws(()=>Guidance.buildGuidance({
  decision:decision(),strategy:strategy(),public_snapshot:snapshot({context_id:'other-context'})
}),/context_id/,'surface context must match the evaluated decision');

{
  const tampered=decision();
  tampered.ev_bb=999;
  assert.throws(()=>Guidance.buildGuidance({decision:tampered,strategy:strategy(),public_snapshot:snapshot()}),/does not match selected alternative/,'guidance cannot detach displayed EV from the evaluated sizing');
}

{
  const a1=Guidance.buildGuidance({decision:decision(),strategy:strategy('PROMOTED',SHA_A),public_snapshot:snapshot()});
  const a2=Guidance.buildGuidance({decision:decision(),strategy:strategy('PROMOTED',SHA_A),public_snapshot:snapshot()});
  const b=Guidance.buildGuidance({decision:decision(),strategy:strategy('PROMOTED',SHA_B),public_snapshot:snapshot()});
  assert.equal(a1.cache_key,a2.cache_key,'cache identity must be deterministic for the same strategy/context/decision');
  assert.notEqual(a1.cache_key,b.cache_key,'a promoted strategy revision must invalidate cached guidance');
  assert.ok(a1.cache_key.includes(encodeURIComponent(SHA_A)),'cache key must carry the immutable strategy identity');
}

{
  const d=decision();
  d.status='PROMOTED';
  const guidance=Guidance.buildGuidance({decision:d,strategy:strategy('EXPERIMENTAL'),public_snapshot:snapshot()});
  assert.equal(guidance.recommendation_state,'EXPERIMENTAL','decision.status must not self-promote a candidate');
  assert.equal(Guidance.surfacePayload(guidance).action,null);
}

console.log(JSON.stringify({status:'PASS',schema:Guidance.SCHEMA,tests:'promotion state surface parity future-card isolation cache identity'}));
