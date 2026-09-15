'use strict';

const assert=require('node:assert/strict');
const Decision=require('../../src/preflop/decision.js');
const Guidance=require('../../src/preflop/guidance.js');

const POP='pokerstars_nlhe_100-200_zoom_play_6max_v1';
const SHA='a'.repeat(64);

function uncertainty(){
  return {
    monte_carlo:{standard_error_bb:.08,samples:4000,method:'fixture'},
    model:{lower_bb:-.3,upper_bb:.4,method:'fixture',status:'ESTIMATED'}
  };
}
function support(){return {observations:120,backoff_level:'EXACT',source:'TRAIN'};}
function alt(id,action,target,cost,ev){
  return {id,action,target_total_bb:target,incremental_cost_bb:cost,ev_bb:ev,support:support(),confidence:.72,uncertainty:uncertainty()};
}
function decision(){
  return Decision.buildDecision({
    context_id:'ctx-tamper-guard',population_id:POP,actor_contribution_bb:.5,
    legal_actions:['FOLD','CALL','3BET'],selected_id:'raise',
    alternatives:[alt('fold','FOLD',null,0,0),alt('call','CALL',2,1.5,.4),alt('raise','3BET',7.5,7,1.2)],
    search:{candidate_ids:['fold','call','raise'],sizing_grid_source:'fixture',budget:1000,seed:'fixture-seed'}
  });
}
function strategy(state){
  return {state,strategy_id:'hero-preflop-v1',strategy_sha256:SHA,population_id:POP,source:'registry'};
}
function snapshot(){
  return {street:'PREFLOP',context_id:'ctx-tamper-guard',population_id:POP,hero_hand_class:'AQs',board:[]};
}
function clone(value){return JSON.parse(JSON.stringify(value));}
function guidance(state='EXPERIMENTAL'){
  return Guidance.buildGuidance({decision:decision(),strategy:strategy(state),public_snapshot:snapshot()});
}

{
  const promoted=guidance('PROMOTED');
  assert.equal(Guidance.surfacePayload(promoted).action,'3BET');
  const experimental=guidance();
  assert.equal(Guidance.surfacePayload(experimental).action,null);
  assert.equal(Guidance.surfacePayload(experimental,{allow_experimental:true}).action,'3BET');
}

{
  const value=clone(guidance());
  value.recommendation_state='PROMOTED';
  assert.throws(()=>Guidance.surfacePayload(value),/recommendation_state/,'post-build EXPERIMENTAL->PROMOTED mutation must fail closed');
}
{
  const value=clone(guidance());
  value.strategy.state='PROMOTED';
  assert.throws(()=>Guidance.surfacePayload(value),/recommendation_state/,'strategy authority mutation must not bypass envelope consistency');
}
{
  const value=clone(guidance());
  value.default_advice=true;
  assert.throws(()=>Guidance.surfacePayload(value),/default_advice/,'experimental guidance cannot be relabelled as default advice');
}
{
  const value=clone(guidance());
  value.advisory_label='PROMOTED_GUIDANCE';
  assert.throws(()=>Guidance.surfacePayload(value),/advisory_label/,'promotion label must remain derived from strategy state');
}
{
  const value=clone(guidance());
  value.cache_key+='tampered';
  assert.throws(()=>Guidance.surfacePayload(value,{allow_experimental:true}),/cache_key/,'cached envelope identity must be recomputed at surface time');
}
{
  const value=clone(guidance());
  value.evidence_decision.ev_bb=999;
  assert.throws(()=>Guidance.surfacePayload(value,{allow_experimental:true}),/selected alternative/,'cached decision must be revalidated before surfacing');
}
{
  const value=clone(guidance());
  value.evidence_decision.support.observations=999;
  assert.throws(()=>Guidance.surfacePayload(value,{allow_experimental:true}),/support/,'surfaced support must remain tied to the selected alternative');
}
{
  const value=clone(guidance());
  value.evidence_decision.confidence=.99;
  assert.throws(()=>Guidance.surfacePayload(value,{allow_experimental:true}),/confidence/,'surfaced confidence must remain tied to the selected alternative');
}
{
  const value=clone(guidance());
  value.evidence_decision.uncertainty.model.status='CERTAIN';
  assert.throws(()=>Guidance.surfacePayload(value,{allow_experimental:true}),/uncertainty/,'surfaced uncertainty must remain tied to the selected alternative');
}
{
  const value=clone(guidance());
  const reordered=value.evidence_decision.support;
  value.evidence_decision.support={source:reordered.source,backoff_level:reordered.backoff_level,observations:reordered.observations};
  assert.doesNotThrow(()=>Guidance.surfacePayload(value,{allow_experimental:true}),'semantically identical metadata must not depend on object key order');
}
{
  const value=clone(guidance());
  value.future_cards_consumed=true;
  assert.throws(()=>Guidance.surfacePayload(value),/future_cards_consumed/,'future-card attestation cannot be mutated after construction');
}

console.log(JSON.stringify({status:'PASS',schema:Guidance.SCHEMA,tests:'post-build guidance envelope tamper guard'}));
