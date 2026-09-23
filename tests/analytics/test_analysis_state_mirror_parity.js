'use strict';

// Durable non-regression guard for the versioned `poker-analysis-state/v1`
// taxonomy (issue #393, task backlog-kll).
//
// Six independent invariants are pinned here:
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
//   4. Schema coherence: the produced dimensions must respect the schema
//      enum/type vocabulary, `computational_status` must admit `NOT_EVALUATED`,
//      the empty/placeholder rule must be documented in the schema, and the
//      mapped object must expose exactly the schema dimensions (no synthetic
//      one).
//   5. Consumer delegation: Inbox, Replayer (Hero/opponent) and Training must
//      produce their `analysis_state` through the shared module, so no surface
//      can synthesize a dimension of its own.
//   6. CI wiring: `.github/workflows/analysis-state-contract.yml` must execute
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
// 4. Schema coherence: the produced dimensions must respect the enum/type
//    vocabulary declared by the canonical schema, and `computational_status`
//    must admit the explicit `NOT_EVALUATED` sentinel. The empty/placeholder
//    ("not an evaluated negative conclusion") rule is also encoded normatively
//    in the schema descriptions.
// ---------------------------------------------------------------------------
const SCHEMA=JSON.parse(fs.readFileSync(path.join(ROOT,'contracts/analytics/analysis-state.schema.json'),'utf8'));
const PROPS=SCHEMA.properties;

assert.ok(Array.isArray(PROPS.computational_status.enum),'schema must declare computational_status as an enum');
assert.ok(PROPS.computational_status.enum.includes('NOT_EVALUATED'),
  'schema computational_status must admit NOT_EVALUATED');
assert.equal(PROPS.state.enum.length,6,'schema must declare exactly six canonical states');
assert.deepEqual([...SCHEMA.required].sort(),Object.keys(PROPS).sort(),
  'every schema property must be required so no dimension can be silently omitted');
for(const dimension of ['ev_comparability','recommendation_admissibility','computational_status']){
  assert.match(PROPS[dimension].description||'',/placeholder|empty|vide/i,
    dimension+' must document the empty/placeholder (not-a-negative-conclusion) rule');
}

function assertSchemaConformant(value,label){
  assert.ok(PROPS.state.enum.includes(value.state),label+': state must be a schema enum value');
  assert.ok(PROPS.computational_status.enum.includes(value.computational_status),label+': computational_status must be a schema enum value');
  assert.ok(PROPS.model_support_status.enum.includes(value.model_support_status),label+': model_support_status must be a schema enum value');
  assert.ok(PROPS.posterior_availability.enum.includes(value.posterior_availability),label+': posterior_availability must be a schema enum value');
  assert.ok(Number.isInteger(value.statistical_support.observations)&&value.statistical_support.observations>=0,label+': observations must be an integer >= 0');
  assert.ok(Number.isInteger(value.statistical_support.distinct_hands)&&value.statistical_support.distinct_hands>=0,label+': distinct_hands must be an integer >= 0');
  if(value.statistical_support.availability!=null)
    assert.ok(PROPS.statistical_support.properties.availability.enum.includes(value.statistical_support.availability),label+': availability must be a schema enum value');
  assert.equal(typeof value.ev_comparability.comparable,'boolean',label+': comparable must be a boolean');
  assert.ok(value.ev_comparability.reason==null||typeof value.ev_comparability.reason==='string',label+': reason must be a string or null');
  assert.equal(typeof value.recommendation_admissibility.admissible,'boolean',label+': admissible must be a boolean');
  assert.ok(Array.isArray(value.recommendation_admissibility.reason_codes),label+': admissibility reason_codes must be an array');
  assert.equal(typeof value.error.retryable,'boolean',label+': error.retryable must be a boolean');
  assert.ok(value.error.type==null||typeof value.error.type==='string',label+': error.type must be a string or null');
  // No synthetic dimension: the emitted object exposes exactly the schema keys.
  assert.deepEqual(Object.keys(value).sort(),[...SCHEMA.required].sort(),
    label+': the mapped object must expose exactly the schema dimensions');
}

const SCHEMA_CONFORMANCE_FIXTURES=[
  {label:'{}',input:{}},
  {label:'ev_comparability:{}',input:{ev_comparability:{}}},
  {label:'recommendation_admissibility:{}',input:{recommendation_admissibility:{}}},
  {label:'ev_comparability:{reason:NOT_EVALUATED}',input:{ev_comparability:{reason:'NOT_EVALUATED'}}},
  {label:'recommendation_admissibility:{status:NOT_EVALUATED}',input:{recommendation_admissibility:{status:'NOT_EVALUATED'}}}
];

for(const {label,input} of SCHEMA_CONFORMANCE_FIXTURES){
  const mapped=State.mapAnalysisState(input);
  assertSchemaConformant(mapped,label);
  // An empty/placeholder container is un-evaluated, never an evaluated negative.
  assert.notEqual(mapped.state,'ANALYSE_PARTIELLE',label+': an empty container must not synthesize a negative verdict');
  assert.equal(mapped.computational_status,'NOT_EVALUATED',label+': computational_status must stay NOT_EVALUATED');
  assert.deepEqual(mapped.recommendation_admissibility.reason_codes,[],label+': no blocking reason code may be synthesized');
  assert.deepEqual(State.mapAnalysisState(mapped),mapped,label+': mapping must be idempotent');
}

// ---------------------------------------------------------------------------
// 5. Consumer surfaces must expose no synthetic dimension: every migrated
//    surface delegates the canonical dimensions to the shared module instead of
//    fabricating one locally. Guarding the delegation keeps Inbox, Replayer
//    (Hero/opponent) and Training on the single schema-bound producer.
// ---------------------------------------------------------------------------
const CONSUMER_SURFACES=[
  {label:'Review Inbox',file:'src/analytics/review-inbox.js',module:'./analysis-state.js'},
  {label:'Replayer Hero/opponent',file:'site/index.html',module:'analytics/analysis-state.js'},
  {label:'Training',file:'site/trainer.js',module:'window.PokerAnalysisState'}
];
for(const {label,file,module} of CONSUMER_SURFACES){
  const full=path.join(ROOT,file);
  assert.ok(fs.existsSync(full),label+': missing consumer surface '+file);
  const source=fs.readFileSync(full,'utf8');
  assert.ok(source.includes(module),label+': must load the shared module (expected `'+module+'` in '+file+')');
  assert.ok(source.includes('mapAnalysisState'),label+': must produce analysis_state through the shared mapAnalysisState');
}

// ---------------------------------------------------------------------------
// 6. CI wiring: the dedicated analytics test configuration must actually
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
  schema_conformance_fixtures:SCHEMA_CONFORMANCE_FIXTURES.map(fixture=>fixture.label),
  computational_status_admits_not_evaluated:PROPS.computational_status.enum.includes('NOT_EVALUATED'),
  consumer_surfaces:CONSUMER_SURFACES.map(surface=>surface.label),
  ci_workflow:path.relative(ROOT,CI_WORKFLOW).split(path.sep).join('/')
}));
