#!/usr/bin/env node
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';

const require=createRequire(import.meta.url);
const H=require('../../site/hero-ranges.js');
const D=require('../../src/preflop/decision.js');
const X=require('../../src/preflop/hero_range_export.js');

const POP='pokerstars_nlhe_100-200_zoom_play_6max_v1';
const CONTEXT={population_id:POP,table_size:6,position:'BB',effective_stack_bb:100,spot:'VS_RFI_CALLERS'};
const PROVENANCE={
  models:{preflop:'fixture-a',postflop:'fixture-b'},
  code:'issue-154-fixture',
  budget:{rollouts_per_action:5000},
  selection:'NOT_PROMOTED'
};

function squeezeDecision({size=11,ev=.4}={}){
  return D.buildDecision({
    status:'EXPERIMENTAL',
    context_id:'BB-100-VS_RFI_CALLERS:AKs',
    population_id:POP,
    actor_contribution_bb:1,
    legal_actions:['FOLD','CALL','SQUEEZE'],
    alternatives:[
      {id:'fold',action:'FOLD',target_total_bb:null,incremental_cost_bb:0,ev_bb:0,support:{observations:120,backoff_level:'EXACT',source:'fixture'}},
      {id:'call',action:'CALL',target_total_bb:2.5,incremental_cost_bb:1.5,ev_bb:.05,support:{observations:120,backoff_level:'EXACT',source:'fixture'}},
      {id:`squeeze-${size}`,action:'SQUEEZE',target_total_bb:size,incremental_cost_bb:size-1,ev_bb:ev,confidence:.8,support:{observations:120,backoff_level:'EXACT',source:'fixture'}}
    ],
    selected_id:`squeeze-${size}`,
    search:{candidate_ids:['fold','call',`squeeze-${size}`],sizing_grid_source:'fixture',budget:5000,seed:'squeeze-seed'}
  });
}

function build(row,context=CONTEXT){
  return X.buildCandidate({
    context,
    version:'issue-154-candidate',
    status:'EXPERIMENTAL',
    provenance:PROVENANCE,
    rows:[row],
    require_complete:false
  });
}

const decision=squeezeDecision();
assert.equal(decision.action,'SQUEEZE');
assert.equal(X.rangeActionForDecision('SQUEEZE',CONTEXT),'3BET');
assert.equal(X.rangeActionForDecision('OPEN',{...CONTEXT,spot:'UNOPENED'}),'OPEN','unrelated actions must not change');

// One-hot #106 decision: range representation changes, canonical evidence does not.
const oneHot=build({hand_class:'AKs',decision});
assert.equal(X.verifyCandidate(oneHot,{require_complete:false}),true);
const oneHotStrategy=H.getHandStrategy(oneHot.repository,CONTEXT,'AKs',{layer:'calculated'});
assert.deepEqual(oneHotStrategy.actions,{'3BET':1});
assert.deepEqual(oneHotStrategy.sizings['3BET'],[{target_total_bb:11,probability:1}]);
assert.equal(oneHot.decisions.AKs.action,'SQUEEZE','canonical decision family must remain SQUEEZE');
assert.equal(oneHot.decisions.AKs.target_total_bb,11);
assert.equal(oneHot.decisions.AKs.ev_bb,.4,'EV evidence must remain attached to the canonical decision');
assert.equal(oneHot.policy_origins.AKs,'SELECTED_DECISION_ONE_HOT');

// An explicit decision-domain policy using SQUEEZE is projected losslessly.
const explicit=build({
  hand_class:'AKs',
  decision,
  policy:{
    actions:{FOLD:.7,SQUEEZE:.3},
    sizings:{SQUEEZE:[{target_total_bb:11,probability:1}]},
    notes:'decision-domain squeeze mix'
  }
});
const explicitStrategy=H.getHandStrategy(explicit.repository,CONTEXT,'AKs',{layer:'calculated'});
assert.deepEqual(explicitStrategy.actions,{FOLD:.7,'3BET':.3});
assert.deepEqual(explicitStrategy.sizings['3BET'],[{target_total_bb:11,probability:1}]);
assert.equal(X.selectedSizingProbability(explicitStrategy,decision,CONTEXT),1);
assert.equal(explicit.decisions.AKs.action,'SQUEEZE');
assert.equal(X.verifyCandidate(explicit,{require_complete:false}),true);

// A caller may already provide the repository-domain alias; it is accepted.
const repositoryDomain=build({
  hand_class:'AKs',
  decision,
  policy:{actions:{FOLD:.7,'3BET':.3},sizings:{'3BET':[{target_total_bb:11,probability:1}]}}
});
assert.deepEqual(H.getHandStrategy(repositoryDomain.repository,CONTEXT,'AKs',{layer:'calculated'}).actions,{FOLD:.7,'3BET':.3});
assert.equal(repositoryDomain.decisions.AKs.action,'SQUEEZE');

// Never silently project a squeeze outside the one repository spot that owns this alias.
const wrongContext={...CONTEXT,spot:'VS_RFI'};
assert.throws(()=>build({hand_class:'AKs',decision},wrongContext),/SQUEEZE requires Hero range context VS_RFI_CALLERS/);
assert.throws(()=>X.rangeActionForDecision('SQUEEZE',{...CONTEXT,spot:'UNOPENED'}),/VS_RFI_CALLERS/);

// Two aliases in the same explicit policy are ambiguous and must fail closed.
assert.throws(()=>build({
  hand_class:'AKs',
  decision,
  policy:{actions:{SQUEEZE:.5,'3BET':.5},sizings:{SQUEEZE:[{target_total_bb:11,probability:1}]}}
}),/must not contain both SQUEEZE and 3BET aliases/);

console.log('SQUEEZE -> Hero 3BET export contract: PASS');
