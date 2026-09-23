'use strict';

// Durable non-regression guard for the versioned `poker-analysis-state/v1`
// taxonomy (issue #393, task backlog-kll).
//
// Four independent invariants are pinned here:
//   1. Byte-for-byte parity: the edit source `src/analytics/analysis-state.js`
//      and the served mirror `site/analytics/analysis-state.js` must never
//      drift, so the browser bundle cannot silently diverge from its source of
//      truth.
//   2. Fail-safe un-evaluated dimensions: replaying the empty-container
//      fixtures (`{ev_comparability:{}}`, `{recommendation_admissibility:{}}`)
//      must keep the explicit non-evaluated sentinels instead of fabricating a
//      positive verdict.
//   3. Schema validity: every produced object must pass
//      `validateAnalysisState(...).valid`.
//   4. CI wiring: `.github/workflows/analysis-state-contract.yml` must execute
//      this guard, so the contract cannot be silently dropped from CI.
//
// Executed in CI by `.github/workflows/analysis-state-contract.yml`; run
// locally with `node tests/analytics/test_analysis_state_mirror_parity.js`.

const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

const ROOT=path.resolve(__dirname,'../..');
const SOURCE=path.join(ROOT,'src/analytics/analysis-state.js');
const MIRROR=path.join(ROOT,'site/analytics/analysis-state.js');

const State=require(SOURCE);

// ---------------------------------------------------------------------------
// 1. Byte-for-byte edit source <-> served mirror parity.
// ---------------------------------------------------------------------------
function assertMirrorParity(){
  assert.ok(fs.existsSync(SOURCE),'missing edit source: '+SOURCE);
  assert.ok(fs.existsSync(MIRROR),'missing served mirror: '+MIRROR);
  const source=fs.readFileSync(SOURCE);
  const mirror=fs.readFileSync(MIRROR);
  assert.equal(source.length,mirror.length,
    'analysis-state source and mirror must have the same byte length ('+SOURCE+' vs '+MIRROR+')');
  assert.equal(Buffer.compare(source,mirror),0,
    'src/analytics/analysis-state.js and site/analytics/analysis-state.js must be byte-identical');
}
assertMirrorParity();

// ---------------------------------------------------------------------------
// 2. Empty containers never claim a dimension was evaluated, and 3. every
//    produced object stays schema-valid.
// ---------------------------------------------------------------------------
const EMPTY_CONTAINER_FIXTURES=[
  {label:'ev_comparability:{}',input:{ev_comparability:{}}},
  {label:'recommendation_admissibility:{}',input:{recommendation_admissibility:{}}}
];

for(const {label,input} of EMPTY_CONTAINER_FIXTURES){
  const mapped=State.mapAnalysisState(input);

  // Un-evaluated comparability keeps the explicit NOT_EVALUATED sentinel.
  assert.deepEqual(mapped.ev_comparability,{comparable:false,reason:'NOT_EVALUATED'},
    label+': an un-evaluated ev_comparability must stay {comparable:false, reason:"NOT_EVALUATED"}');
  // Un-evaluated admissibility stays closed but never invents a blocking cause.
  assert.equal(mapped.recommendation_admissibility.admissible,false,
    label+': an un-evaluated recommendation_admissibility must stay admissible=false');
  assert.equal(mapped.recommendation_admissibility.status,'NOT_EVALUATED',
    label+': an un-evaluated recommendation_admissibility must keep status="NOT_EVALUATED"');
  assert.deepEqual(mapped.recommendation_admissibility.reason_codes,[],
    label+': no blocking reason code may be synthesized');
  // The remaining dimensions must not be promoted either.
  assert.equal(mapped.computational_status,'NOT_EVALUATED',label+': computational_status must stay NOT_EVALUATED');
  assert.equal(mapped.model_support_status,'NOT_EVALUATED',label+': model_support_status must stay NOT_EVALUATED');
  assert.equal(mapped.state,'DONNEES_INSUFFISANTES',label+': an empty container must not promote the analysis state');
  assert.deepEqual(mapped.reason_codes,[],label+': an empty container must not synthesize a reason code');

  // Schema validity of the produced object.
  const validation=State.validateAnalysisState(mapped);
  assert.equal(validation.valid,true,
    label+': mapped analysis state must validate: '+JSON.stringify({input,mapped,errors:validation.errors}));
  assert.deepEqual(validation.errors,[],label+': a valid mapping must report no errors');

  // The fail-safe mapping must be stable (idempotent).
  assert.deepEqual(State.mapAnalysisState(mapped),mapped,label+': mapping must be idempotent');
}

// ---------------------------------------------------------------------------
// 4. CI wiring: the dedicated analytics test configuration must actually
//    execute this file, otherwise the parity/non-regression contract is never
//    enforced. Asserting the reference here keeps the guard honest if the
//    workflow is ever dropped or renamed without moving the step.
// ---------------------------------------------------------------------------
const CI_WORKFLOW=path.join(ROOT,'.github/workflows/analysis-state-contract.yml');
const SELF=path.relative(ROOT,__filename).split(path.sep).join('/');
assert.ok(fs.existsSync(CI_WORKFLOW),'missing CI configuration: '+CI_WORKFLOW);
const ciConfig=fs.readFileSync(CI_WORKFLOW,'utf8');
assert.ok(ciConfig.includes('node '+SELF),
  'CI configuration must execute `node '+SELF+'` (got '+CI_WORKFLOW+')');

console.log(JSON.stringify({
  status:'PASS',
  schema:State.SCHEMA,
  mirror_parity:true,
  un_evaluated_fixtures:EMPTY_CONTAINER_FIXTURES.map(fixture=>fixture.label),
  ci_workflow:path.relative(ROOT,CI_WORKFLOW).split(path.sep).join('/')
}));
