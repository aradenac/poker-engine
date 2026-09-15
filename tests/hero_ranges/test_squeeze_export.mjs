#!/usr/bin/env node
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';

const require=createRequire(import.meta.url);
const H=require('../../site/hero-ranges.js');
const D=require('../../src/preflop/decision.js');
const X=require('../../src/preflop/hero_range_export.js');

const POP='pokerstars_nlhe_100-200_zoom_play_6max_v1';
const CONTEXT={population_id:POP,table_size:6,position:'BTN',effective_stack_bb:100,spot:'VS_RFI_CALLERS'};
const WRONG_CONTEXT={...CONTEXT,spot:'VS_RFI'};
const PROVENANCE={models:{preflop:'fixture-a',postflop:'fixture-b'},code:'fixture-sha',budget:{rollouts_per_action:5000},selection:'NOT_PROMOTED'};

function squeezeDecision(hand='AQs'){
  return D.buildDecision({
    status:'EXPERIMENTAL',
    context_id:`BTN-100-VS_RFI_CALLERS:${hand}`,
    population_id:POP,
    actor_contribution_bb:.5,
    legal_actions:['FOLD','CALL','SQUEEZE'],
    alternatives:[
      {id:'fold',action:'FOLD',target_total_bb:null,incremental_cost_bb:0,ev_bb:0,support:{observations:80,backoff_level:'EXACT',source:'fixture'}},
      {id:'call',action:'CALL',target_total_bb:2,incremental_cost_bb:1.5,ev_bb:.12,support:{observations:80,backoff_level:'EXACT',source:'fixture'}},
      {id:'squeeze-9',action:'SQUEEZE',target_total_bb:9,incremental_cost_bb:8.5,ev_bb:.71,confidence:.76,support:{observations:80,backoff_level:'EXACT',source:'fixture'},uncertainty:{monte_carlo:{standard_error_bb:.02,samples:5000,method:'fixture'},model:{lower_bb:.62,upper_bb:.80,method:'fixture',status:'SUPPORTED'}}}
    ],
    selected_id:'squeeze-9',
    search:{candidate_ids:['fold','call','squeeze-9'],sizing_grid_source:'observed_plus_local_grid',budget:5000,seed:'squeeze-fixture'}
  });
}

function build(row,context=CONTEXT){
  return X.buildCandidate({
    context,
    version:'squeeze-fixture-v1',
    status:'EXPERIMENTAL',
    provenance:PROVENANCE,
    rows:[row],
    require_complete:false
  });
}

{
  const decision=squeezeDecision();
  const candidate=build({hand_class:'AQs',decision});
  assert.equal(X.verifyCandidate(candidate,{require_complete:false}),true);
  assert.equal(candidate.decisions.AQs.action,'SQUEEZE','canonical decision evidence must remain SQUEEZE');
  assert.equal(candidate.decisions.AQs.target_total_bb,9);
  assert.equal(candidate.decisions.AQs.incremental_cost_bb,8.5);
  assert.equal(candidate.decisions.AQs.ev_bb,.71);
  assert.equal(candidate.repository_actions.AQs,'3BET','only the repository representation is projected');

  const strategy=H.getHandStrategy(candidate.repository,CONTEXT,'AQs',{layer:'calculated'});
  assert.deepEqual(strategy.actions,{3BET:1});
  assert.deepEqual(strategy.sizings['3BET'],[{target_total_bb:9,probability:1}]);
  assert.ok(strategy.notes.includes('canonical SQUEEZE'));

  const provenance=candidate.repository.contexts[H.contextKey(CONTEXT)].layers.calculated.provenance;
  assert.ok(provenance.action_projection_semantics.includes('SQUEEZE'));
  assert.ok(provenance.action_projection_semantics.includes('VS_RFI_CALLERS'));

  const repository=X.repositoryDocument(candidate,{require_complete:false});
  const roundTrip=H.importDocument(repository);
  assert.deepEqual(roundTrip,repository,'repository projection must round-trip without changing the 3BET representation');
}

{
  const decision=squeezeDecision('AKs');
  const candidate=build({
    hand_class:'AKs',
    decision,
    policy:{
      actions:{CALL:.25,SQUEEZE:.75},
      sizings:{SQUEEZE:[{target_total_bb:9,probability:1}]},
      notes:'explicit squeeze mix'
    }
  });
  const strategy=H.getHandStrategy(candidate.repository,CONTEXT,'AKs',{layer:'calculated'});
  assert.deepEqual(strategy.actions,{CALL:.25,3BET:.75},'explicit SQUEEZE probability must be preserved under repository projection');
  assert.deepEqual(strategy.sizings['3BET'],[{target_total_bb:9,probability:1}]);
  assert.equal(candidate.policy_origins.AKs,'EXPLICIT_POLICY');
  assert.equal(candidate.decisions.AKs.action,'SQUEEZE');
  assert.equal(candidate.decisions.AKs.ev_bb,.71);
}

assert.throws(()=>build({hand_class:'AQs',decision:squeezeDecision()},WRONG_CONTEXT),/only representable.*VS_RFI_CALLERS/,'SQUEEZE must fail closed outside the exact repository spot');

assert.throws(()=>build({
  hand_class:'AQs',
  decision:squeezeDecision(),
  policy:{
    actions:{SQUEEZE:.6,3BET:.4},
    sizings:{SQUEEZE:[{target_total_bb:9,probability:1}]}
  }
}),/ambiguous explicit policy/,'canonical and projected action keys may not be silently merged');

{
  const candidate=build({hand_class:'AQs',decision:squeezeDecision()});
  const tampered=JSON.parse(JSON.stringify(candidate));
  tampered.repository_actions.AQs='SQUEEZE';
  assert.throws(()=>X.verifyCandidate(tampered,{require_complete:false}),/repository action projection mismatch/);
}

console.log('SQUEEZE Hero range export regression: PASS');
