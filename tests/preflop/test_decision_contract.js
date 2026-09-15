'use strict';

const assert=require('node:assert/strict');
const Decision=require('../../src/preflop/decision.js');

function uncertainty(se=.08){
  return {
    monte_carlo:{standard_error_bb:se,samples:4000,method:'stratified_mc'},
    model:{lower_bb:-.3,upper_bb:.4,method:'bootstrap_context',status:'ESTIMATED'}
  };
}

function support(n=120){return {observations:n,backoff_level:'EXACT',source:'TRAIN'};}

function alternative(id,action,target,cost,ev,extra={}){
  return {
    id,action,target_total_bb:target,incremental_cost_bb:cost,ev_bb:ev,
    support:support(),confidence:.72,uncertainty:uncertainty(),...extra
  };
}

function base(overrides={}){
  return {
    context_id:'ctx-open-callers-co-100',
    population_id:'pokerstars_nlhe_100-200_zoom_play_6max_v1',
    actor_contribution_bb:.5,
    legal_actions:['FOLD','CALL','3BET'],
    selected_id:'3bet-7.5',
    alternatives:[
      alternative('fold','FOLD',null,0,0),
      alternative('call','CALL',2,1.5,.62),
      alternative('3bet-6.5','3BET',6.5,6,1.08,{sizing_origin:'observed'}),
      alternative('3bet-7.5','3BET',7.5,7,1.21,{sizing_origin:'observed'}),
      alternative('3bet-9.0','3BET',9,8.5,1.13,{sizing_origin:'grid'})
    ],
    search:{
      candidate_ids:['fold','call','3bet-6.5','3bet-7.5','3bet-9.0'],
      sizing_grid_source:'observed_plus_local_grid',budget:20000,seed:'106-contract-fixture'
    },
    ...overrides
  };
}

{
  const result=Decision.buildDecision(base());
  assert.equal(result.schema,'poker-preflop-decision/v1');
  assert.equal(result.ev_reference,'decision_point_incremental_bb');
  assert.equal(result.action,'3BET');
  assert.equal(result.target_total_bb,7.5);
  assert.equal(result.bet_to_bb,7.5);
  assert.equal(result.incremental_cost_bb,7);
  assert.equal(result.ev_bb,1.21);
  assert.equal(result.alternatives.find(x=>x.id==='3bet-6.5').ev_bb,1.08);
  assert.equal(result.alternatives.find(x=>x.id==='3bet-9.0').target_total_bb,9);
  assert.equal(result.uncertainty.monte_carlo.standard_error_bb,.08);
  assert.equal(result.uncertainty.model.status,'ESTIMATED');
  assert.equal(Decision.validateDecision(result),true);
}

{
  const result=Decision.buildDecision({
    context_id:'bb-free-check',actor_contribution_bb:1,legal_actions:['CHECK'],selected_id:'check',
    alternatives:[alternative('check','CHECK',null,0,.37)],search:{candidate_ids:['check'],budget:1000,seed:7}
  });
  assert.equal(result.action,'CHECK');
  assert.equal(result.incremental_cost_bb,0);
  assert.equal(result.target_total_bb,null);
  assert.equal(result.ev_bb,.37,'check can retain continuation EV while costing zero now');
}

assert.throws(()=>Decision.buildDecision(base({
  alternatives:[
    alternative('fold','FOLD',null,0,0),
    alternative('bad','3BET',7.5,6.5,1.3)
  ],selected_id:'bad',search:{candidate_ids:['fold','bad']}
})),/does not match target_total_bb/,'EV/sizing rows may not lie about incremental cost');

assert.throws(()=>Decision.buildDecision(base({
  alternatives:[alternative('bad-fold','FOLD',null,0,.1)],selected_id:'bad-fold',legal_actions:['FOLD'],search:{candidate_ids:['bad-fold']}
})),/FOLD EV must be 0/,'fold is zero only under the explicit decision-point incremental reference');

assert.throws(()=>Decision.buildDecision(base({
  selected_id:'3bet-6.5'
})),/not maximal EV/,'selected action must be the maximum among actually evaluated alternatives');

assert.throws(()=>Decision.buildDecision(base({
  legal_actions:['FOLD','CALL']
})),/illegal action 3BET/,'an evaluated alternative cannot silently violate the legal-action set');

assert.throws(()=>Decision.buildDecision(base({
  legal_actions:[]
})),/legal_actions must not be empty/);

assert.throws(()=>Decision.buildDecision(base({
  search:{candidate_ids:['fold','call','3bet-6.5','3bet-9.0']}
})),/selected alternative must belong/,'the recommendation must belong to the declared search grid');

assert.throws(()=>Decision.buildDecision(base({
  alternatives:[alternative('bad-uncertainty','FOLD',null,0,0,{uncertainty:{monte_carlo:{samples:10},model:{lower_bb:1,upper_bb:-1}}})],
  selected_id:'bad-uncertainty',legal_actions:['FOLD'],search:{candidate_ids:['bad-uncertainty']}
})),/lower_bb must be <= upper_bb/);

assert.throws(()=>Decision.buildDecision(base({
  alternatives:[alternative('fractional-support','FOLD',null,0,0,{support:{observations:1.5}})],
  selected_id:'fractional-support',legal_actions:['FOLD'],search:{candidate_ids:['fractional-support']}
})),/non-negative integer/);

{
  const result=Decision.buildDecision(base());
  const tampered=JSON.parse(JSON.stringify(result));
  tampered.ev_bb=999;
  assert.throws(()=>Decision.validateDecision(tampered),/does not match selected alternative/,'feed/detail/export cannot detach top-level EV from selected alternative');
}

console.log(JSON.stringify({status:'PASS',schema:Decision.SCHEMA,tests:'decision sizing cost EV uncertainty invariants'}));
