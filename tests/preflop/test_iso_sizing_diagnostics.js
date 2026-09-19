#!/usr/bin/env node
'use strict';

const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const childProcess=require('node:child_process');
const Decision=require('../../src/preflop/decision.js');
const D=require('../../src/preflop/iso-sizing-diagnostics.js');

const FIX=path.resolve(__dirname,'../fixtures/iso-sizing-diagnostics');
const read=name=>JSON.parse(fs.readFileSync(path.join(FIX,name),'utf8'));
const decision=()=>read('canonical_decision.json');
const paired=()=>read('paired_result.json');
const worlds=()=>read('diagnostic_worlds.json');

function build(){
  return D.bridgePairedResult({decision:decision(),paired_result:paired(),diagnostic_worlds:worlds()});
}
function byId(artifact,id){return artifact.alternatives.find(x=>x.alternative_id===id);}

function testCanonicalDecisionFixture(){
  assert.equal(Decision.validateDecision(decision()),true);
  assert.equal(decision().selected_id,'ISO@5');
  assert.equal(decision().ev_bb,.36);
}
function testContractDoesNotDuplicateCanonicalActionSizingEv(){
  const artifact=build();
  assert.equal(D.validateArtifact(artifact,decision()).canonical.selected_id,'ISO@5');
  for(const row of artifact.alternatives){
    for(const key of ['action','target_total_bb','target_sizing','incremental_cost_bb','ev_bb','uncertainty']){
      assert.equal(Object.prototype.hasOwnProperty.call(row,key),false,key+' must stay canonical-only');
    }
  }
  assert.deepEqual(artifact.selection_contract,{mode:'CANONICAL_MAX_EV_ONLY',diagnostics_can_select:false});
}
function testResolvedViewUsesCanonicalFieldsAndSelection(){
  const resolved=D.resolveAgainstDecision(build(),decision());
  assert.equal(resolved.schema,D.RESOLVED_SCHEMA);
  assert.equal(resolved.selection_source,'CANONICAL_DECISION_ONLY');
  assert.equal(resolved.selected_alternative_id,'ISO@5');
  const iso5=resolved.alternatives.find(x=>x.alternative_id==='ISO@5');
  assert.equal(iso5.action,'ISO');
  assert.equal(iso5.target_total_bb,5);
  assert.equal(iso5.incremental_cost_bb,4.5);
  assert.equal(iso5.ev_bb,.36);
  assert.equal(iso5.diagnostic.expected_callers,1.25);
  const iso6=resolved.alternatives.find(x=>x.alternative_id==='ISO@6');
  assert.equal(iso6.diagnostic.expected_callers,.875);
  assert.equal(resolved.selected_alternative_id,'ISO@5','lower caller count must not select ISO@6 over max-EV ISO@5');
}
function testFoldAndOverlimpAreExplicitlyNotApplicable(){
  const artifact=build();
  for(const id of ['FOLD','OVERLIMP@1']){
    const row=byId(artifact,id);
    assert.equal(row.status,'NOT_APPLICABLE');
    assert.equal(row.caller_partition,null);
    assert.equal(row.expected_callers,null);
    assert.equal(row.sample_count,0);
  }
}
function testCallerPartitionsAndExpectedCallers(){
  const artifact=build();
  const expected={
    'ISO@4':{partition:[1/8,4/8,2/8,1/8],callers:11/8},
    'ISO@5':{partition:[1/8,5/8,1/8,1/8],callers:10/8},
    'ISO@6':{partition:[2/8,5/8,1/8,0],callers:7/8}
  };
  for(const [id,e] of Object.entries(expected)){
    const row=byId(artifact,id);
    assert.equal(row.status,'AVAILABLE');
    assert.deepEqual(Object.values(row.caller_partition),e.partition);
    assert.equal(row.expected_callers,e.callers);
    assert.equal(row.p_3bet_or_jam,1/8);
    assert.equal(row.sample_count,8);
    assert.equal(row.world_count,8);
    assert.equal(row.continuing_positions.reduce((s,x)=>s+x.probability,0),row.expected_callers);
  }
}
function testPosteriorReferencesBindFinalIssue320Identity(){
  const artifact=build();
  const row=byId(artifact,'ISO@5');
  assert(row.posterior_refs.length>=4);
  for(const entry of row.posterior_refs){
    const ref=entry.ref;
    assert.equal(ref.schema,'poker-opponent-posterior-range/v1');
    for(const key of ['hand_id','step_id','public_state_fingerprint','player','position','identity','moment','public_action','status','distribution_fingerprint','source_fingerprint']){
      assert.notEqual(ref[key],undefined,key+' required for final #320 reference');
    }
    assert.deepEqual(Object.keys(ref.identity).sort(),['model_id','model_version','population_id','source_id']);
    assert.equal(ref.moment,'AFTER_ACTION');
    assert.match(ref.public_state_fingerprint,/^preflop-public:/);
    assert.match(ref.distribution_fingerprint,/^sha256:[a-f0-9]{64}$/);
    assert.equal(ref.position,entry.position);
    assert.equal(ref.public_action.action,entry.response);
  }
}
function testFinalPosterior320ValidatorBinding(){
  childProcess.execFileSync(
    'python3',
    [path.resolve(__dirname,'test_iso_sizing_posterior_binding.py')],
    {cwd:path.resolve(__dirname,'../..'),stdio:'inherit'}
  );
}
function testBridgeRequiresExactSamePairedWorldFingerprint(){
  const bad=worlds();
  bad.alternatives['ISO@5'][3].world_fingerprint_sha256='0'.repeat(64);
  assert.throws(
    ()=>D.bridgePairedResult({decision:decision(),paired_result:paired(),diagnostic_worlds:bad}),
    err=>err.code==='WORLD_FINGERPRINT_MISMATCH'
  );
}
function testBridgeRequiresSameCanonicalAndPairedEv(){
  const bad=paired();
  bad.alternatives['ISO@5'].ev_bb=.99;
  assert.throws(
    ()=>D.bridgePairedResult({decision:decision(),paired_result:bad,diagnostic_worlds:worlds()}),
    err=>err.code==='PAIRED_EV_MISMATCH'
  );
}
function testPartitionAndPosteriorTamperingFailsClosed(){
  const artifact=build();
  byId(artifact,'ISO@4').caller_partition.all_fold=.5;
  assert.throws(()=>D.validateArtifact(artifact,decision()),err=>err.code==='CALLER_PARTITION_INVALID');

  const artifact2=build();
  byId(artifact2,'ISO@5').posterior_refs[0].response_probability=.99;
  assert.throws(()=>D.validateArtifact(artifact2,decision()),err=>err.code==='POSTERIOR_REF_INVALID');
}
function testDiagnosticsCannotSelect(){
  const artifact=build();
  artifact.selection_contract.diagnostics_can_select=true;
  assert.throws(()=>D.validateArtifact(artifact,decision()),err=>err.code==='SELECTION_CONTRACT_INVALID');
  const artifact2=build();
  artifact2.selected_id='ISO@6';
  assert.throws(()=>D.validateArtifact(artifact2,decision()),err=>err.code==='DIAGNOSTIC_SELECTION_FORBIDDEN');
}
function testScientificWorldsRequireExplicitAdmission(){
  const bad=worlds();
  bad.synthetic_fixture=false;
  bad.provenance.synthetic_fixture=false;
  bad.execution_boundary={
    mode:'SCIENTIFIC',
    model_a_admission_status:'NON_SCIENTIFIC_SYNTHETIC'
  };
  assert.throws(
    ()=>D.bridgePairedResult({decision:decision(),paired_result:paired(),diagnostic_worlds:bad}),
    err=>err.code==='SCIENTIFIC_PROVIDER_NOT_ADMITTED'
  );
}

function testDeterministicBridgeOutput(){
  assert.deepEqual(build(),build());
}

const tests=[
  testCanonicalDecisionFixture,
  testContractDoesNotDuplicateCanonicalActionSizingEv,
  testResolvedViewUsesCanonicalFieldsAndSelection,
  testFoldAndOverlimpAreExplicitlyNotApplicable,
  testCallerPartitionsAndExpectedCallers,
  testPosteriorReferencesBindFinalIssue320Identity,
  testFinalPosterior320ValidatorBinding,
  testBridgeRequiresExactSamePairedWorldFingerprint,
  testBridgeRequiresSameCanonicalAndPairedEv,
  testPartitionAndPosteriorTamperingFailsClosed,
  testDiagnosticsCannotSelect,
  testScientificWorldsRequireExplicitAdmission,
  testDeterministicBridgeOutput
];
for(const test of tests)test();
console.log('iso-sizing diagnostics contract tests: '+tests.length+' passed');
