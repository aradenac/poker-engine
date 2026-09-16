#!/usr/bin/env node
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';

const require=createRequire(import.meta.url);
const H=require('../../site/hero-ranges.js');
const D=require('../../src/preflop/decision.js');
const X=require('../../src/preflop/hero_range_export.js');

const POP='pokerstars_nlhe_100-200_zoom_play_6max_v1';
const CONTEXT={population_id:POP,table_size:6,position:'BTN',effective_stack_bb:100,spot:'UNOPENED'};
const PROVENANCE={
  models:{preflop:'fixture-a',postflop:'fixture-b'},
  code:'fixture-sha',
  budget:{hands:169,rollouts_per_action:5000},
  selection:'NOT_PROMOTED'
};

function buildCandidate(input){return X.buildCandidate({provenance:PROVENANCE,...input});}

function foldDecision(hand){
  return D.buildDecision({
    status:'EXPERIMENTAL',
    context_id:`BTN-100-UNOPENED:${hand}`,
    population_id:POP,
    actor_contribution_bb:.5,
    legal_actions:['FOLD','OPEN'],
    alternatives:[
      {id:'fold',action:'FOLD',target_total_bb:null,incremental_cost_bb:0,ev_bb:0,support:{observations:40,backoff_level:'EXACT',source:'fixture'}},
      {id:'open-2.5',action:'OPEN',target_total_bb:2.5,incremental_cost_bb:2,ev_bb:-.2,support:{observations:40,backoff_level:'EXACT',source:'fixture'}}
    ],
    selected_id:'fold',
    search:{candidate_ids:['fold','open-2.5'],sizing_grid_source:'fixture',budget:1000,seed:'fold-seed'}
  });
}

function openDecision(hand,{size=2.5,ev=.3}={}){
  return D.buildDecision({
    status:'EXPERIMENTAL',
    context_id:`BTN-100-UNOPENED:${hand}`,
    population_id:POP,
    actor_contribution_bb:.5,
    legal_actions:['FOLD','OPEN'],
    alternatives:[
      {id:'fold',action:'FOLD',target_total_bb:null,incremental_cost_bb:0,ev_bb:0,support:{observations:80,backoff_level:'EXACT',source:'fixture'}},
      {id:`open-${size}`,action:'OPEN',target_total_bb:size,incremental_cost_bb:size-.5,ev_bb:ev,confidence:.8,support:{observations:80,backoff_level:'EXACT',source:'fixture'},uncertainty:{monte_carlo:{standard_error_bb:.01,samples:5000,method:'fixture'},model:{lower_bb:ev-.05,upper_bb:ev+.05,method:'fixture',status:'SUPPORTED'}}}
    ],
    selected_id:`open-${size}`,
    search:{candidate_ids:['fold',`open-${size}`],sizing_grid_source:'observed_fixture',budget:5000,seed:'open-seed'}
  });
}

function completeRows(){
  return H.HAND_CLASSES.map((hand,index)=>({
    hand_class:hand,
    decision:index%3===0?openDecision(hand):foldDecision(hand)
  }));
}

const base=H.emptyRepository({populationId:POP});
H.setLayerMetadata(base,CONTEXT,'personal',{version:'user-1',provenance:{author:'fixture'}});
H.setHandStrategy(base,CONTEXT,'AKs',{actions:{OPEN:1},sizings:{OPEN:[{target_total_bb:3,probability:1}]},notes:'personal survives'},{layer:'personal'});
H.setLayerMetadata(base,CONTEXT,'calculated',{version:'stale',provenance:{source:'old'}});
H.setHandStrategy(base,CONTEXT,'AQs',{actions:{FOLD:1},notes:'stale calculated row must be replaced'},{layer:'calculated'});

const rows=completeRows();
const aks=rows.find(row=>row.hand_class==='AKs');
aks.decision=openDecision('AKs');
aks.policy={
  actions:{FOLD:.8,OPEN:.2},
  sizings:{OPEN:[{target_total_bb:2.5,probability:1}]},
  notes:'explicit justified mix fixture'
};

const candidate=buildCandidate({
  context:CONTEXT,
  version:'hero-candidate-fixture-1',
  status:'EXPERIMENTAL',
  base_repository:base,
  rows
});

assert.equal(X.verifyCandidate(candidate),true);
assert.equal(candidate.schema,X.SCHEMA);
assert.equal(candidate.promotion_authorized,false);
assert.deepEqual(candidate.coverage,{defined_hand_classes:169,required_hand_classes:169,complete:true});
assert.deepEqual(candidate.provenance,PROVENANCE);
const calculatedLayer=candidate.repository.contexts[H.contextKey(CONTEXT)].layers.calculated;
assert.equal(calculatedLayer.version,'hero-candidate-fixture-1');
assert.equal(calculatedLayer.provenance.schema,X.SCHEMA);
assert.equal(calculatedLayer.provenance.code,PROVENANCE.code);
assert.deepEqual(calculatedLayer.provenance.models,PROVENANCE.models);
assert.deepEqual(calculatedLayer.provenance.budget,PROVENANCE.budget);
assert.equal(calculatedLayer.provenance.selection,PROVENANCE.selection);
assert.equal(candidate.repository.contexts[H.contextKey(CONTEXT)].layers.personal.version,'user-1','personal layer must survive calculated generation');
assert.equal(H.getHandStrategy(candidate.repository,CONTEXT,'AKs',{layer:'personal'}).sizings.OPEN[0].target_total_bb,3);
assert.equal(H.getHandStrategy(candidate.repository,CONTEXT,'AQs',{layer:'calculated'}).notes.includes('stale'),false,'calculated layer must be replaced rather than merged with stale rows');

const exportedAKs=H.getHandStrategy(candidate.repository,CONTEXT,'AKs',{layer:'calculated'});
assert.deepEqual(exportedAKs.actions,{FOLD:.8,OPEN:.2},'explicit mix must be preserved exactly');
assert.equal(exportedAKs.sizings.OPEN[0].target_total_bb,2.5);
assert.equal(candidate.policy_origins.AKs,'EXPLICIT_POLICY');
assert.equal(candidate.decisions.AKs.ev_bb,aks.decision.ev_bb,'EV evidence remains attached to the exact decision, not invented in the range layer');
assert.equal(candidate.decisions.AKs.support.observations,80);
assert.equal(candidate.decisions.AKs.uncertainty.monte_carlo.samples,5000);

const aaDecision=candidate.decisions.AA;
const exportedAA=H.getHandStrategy(candidate.repository,CONTEXT,'AA',{layer:'calculated'});
assert.equal(candidate.policy_origins.AA,'SELECTED_DECISION_ONE_HOT');
assert.deepEqual(exportedAA.actions,{[aaDecision.action]:1},'no synthetic mix may be introduced when the engine supplies only one selected action');
if(aaDecision.target_total_bb!=null){
  assert.deepEqual(exportedAA.sizings[aaDecision.action],[{target_total_bb:aaDecision.target_total_bb,probability:1}]);
}

const repositoryOnly=X.repositoryDocument(candidate);
assert.equal(H.validateRepository(repositoryOnly),true);
assert.deepEqual(repositoryOnly,candidate.repository);

assert.throws(()=>buildCandidate({
  context:CONTEXT,version:'missing-one',rows:rows.slice(0,-1)
}),/requires all 169 hand classes/);

const partial=buildCandidate({
  context:CONTEXT,version:'partial-diagnostic',rows:rows.slice(0,2),require_complete:false
});
assert.equal(partial.coverage.complete,false);
assert.equal(partial.coverage.defined_hand_classes,2);
assert.equal(X.verifyCandidate(partial,{require_complete:false}),true);
assert.throws(()=>X.verifyCandidate(partial),/not complete/);

assert.throws(()=>buildCandidate({
  context:CONTEXT,version:'bad-policy',rows:[{hand_class:'AKs',decision:openDecision('AKs'),policy:{actions:{FOLD:1}}}],require_complete:false
}),/excludes selected decision action/);

assert.throws(()=>buildCandidate({
  context:CONTEXT,version:'bad-size',rows:[{hand_class:'AKs',decision:openDecision('AKs'),policy:{actions:{OPEN:1},sizings:{OPEN:[{target_total_bb:3,probability:1}]}}}],require_complete:false
}),/does not contain selected sizing/);

const wrongPopulation=openDecision('AKs');
wrongPopulation.population_id='other-population';
assert.throws(()=>buildCandidate({
  context:CONTEXT,version:'bad-pop',rows:[{hand_class:'AKs',decision:wrongPopulation}],require_complete:false
}),/does not match context population/);

assert.throws(()=>buildCandidate({
  context:CONTEXT,version:'self-promote',status:'PROMOTED',rows
}),/cannot self-promote/);

assert.throws(()=>X.buildCandidate({
  context:CONTEXT,version:'missing-provenance',rows
}),/provenance object is required/);
assert.throws(()=>X.buildCandidate({
  context:CONTEXT,version:'missing-models',rows,provenance:{code:'sha',budget:{hands:169},selection:'NOT_PROMOTED'}
}),/provenance.models/);
assert.throws(()=>X.buildCandidate({
  context:CONTEXT,version:'missing-budget',rows,provenance:{code:'sha',models:{preflop:'a'},selection:'NOT_PROMOTED'}
}),/provenance.budget/);

const overrideAttempt=buildCandidate({
  context:CONTEXT,
  version:'override-attempt',
  rows,
  provenance:{...PROVENANCE,schema:'evil',status:'PROMOTED',source_decision_schema:'evil'}
});
const overrideLayer=overrideAttempt.repository.contexts[H.contextKey(CONTEXT)].layers.calculated;
assert.equal(overrideLayer.provenance.schema,X.SCHEMA,'caller provenance must not override technical schema');
assert.equal(overrideLayer.provenance.status,'EXPERIMENTAL','caller provenance must not self-promote layer status');
assert.equal(overrideLayer.provenance.source_decision_schema,D.SCHEMA);

const tampered=JSON.parse(JSON.stringify(candidate));
const tamperedAKs=tampered.repository.contexts[H.contextKey(CONTEXT)].layers.calculated.hands.AKs;
tamperedAKs.actions={FOLD:1};
tamperedAKs.sizings={};
assert.throws(()=>X.verifyCandidate(tampered),/selected action OPEN .*absent from calculated strategy/);

const tamperedSize=JSON.parse(JSON.stringify(candidate));
tamperedSize.repository.contexts[H.contextKey(CONTEXT)].layers.calculated.hands.AKs.sizings.OPEN=[{target_total_bb:4,probability:1}];
assert.throws(()=>X.verifyCandidate(tamperedSize),/selected sizing 2.5 BB absent/);

const tamperedProvenance=JSON.parse(JSON.stringify(candidate));
tamperedProvenance.repository.contexts[H.contextKey(CONTEXT)].layers.calculated.provenance.code='other-sha';
assert.throws(()=>X.verifyCandidate(tamperedProvenance),/provenance code mismatch/);

const tamperedStatus=JSON.parse(JSON.stringify(candidate));
tamperedStatus.status='PROMOTED';
tamperedStatus.repository.contexts[H.contextKey(CONTEXT)].layers.calculated.provenance.status='PROMOTED';
assert.throws(()=>X.verifyCandidate(tamperedStatus),/rejects self-promoted/);

const tamperedLayer=JSON.parse(JSON.stringify(candidate));
tamperedLayer.layer='personal';
assert.throws(()=>X.verifyCandidate(tamperedLayer),/layer must be calculated/);

const tamperedVersion=JSON.parse(JSON.stringify(candidate));
tamperedVersion.version='';
tamperedVersion.repository.contexts[H.contextKey(CONTEXT)].layers.calculated.version='';
assert.throws(()=>X.verifyCandidate(tamperedVersion),/candidate.version is required/);

console.log('Calculated Hero range candidate export contract: PASS');
