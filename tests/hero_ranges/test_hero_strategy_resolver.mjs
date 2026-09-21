#!/usr/bin/env node
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';

const require=createRequire(import.meta.url);
const H=require('../../site/hero-ranges.js');
const R=require('../../site/hero-strategy-resolver.js');

const POP='pokerstars_nlhe_100-200_zoom_play_6max_v1';
const OTHER='legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1';
const SHA_MANIFEST='a'.repeat(64);
const SHA_BINDING='b'.repeat(64);
const SHA_PLAN='c'.repeat(64);
const SHA_REFERENCE='d'.repeat(64);
const CONTEXT={population_id:POP,table_size:6,position:'BTN',effective_stack_bb:100,spot:'UNOPENED'};
const GENERATION_VERSION='gen-196::hero-candidate-196::'+SHA_MANIFEST.slice(0,16);
const LAYER_PROVENANCE={
  schema:R.IMPORT_SCHEMA,
  activation_state:'ACTIVE_MEASURED',
  candidate_id:'hero-candidate-196',
  generation_id:'gen-196',
  manifest_sha256:SHA_MANIFEST,
  binding_sha256:SHA_BINDING,
  source_plan_sha256:SHA_PLAN
};

// A fully bound admission: role, content hash, explicit provenance,
// candidate_id/generation_id and binding_sha256 all describe the calculated
// artifact above (#task-fnc). A bare status token is never enough.
function boundAdmission({
  status='ADMISSIBLE',populationId=POP,role='hero_strategy',
  sha=SHA_MANIFEST,declaredSha,actualSha,admissionSha,
  artifact=true,binding=SHA_BINDING,
  candidateId='hero-candidate-196',generationId='gen-196',provenance=true
}={}){
  const admission={status,role,population_id:populationId};
  if(artifact){
    admission.artifact={
      declared_sha256:declaredSha===undefined?sha:declaredSha,
      actual_sha256:actualSha===undefined?sha:actualSha,
      hash_kind:'file_sha256',
      source_path:'training/runs/196_hero_candidate/HERO_RANGE_REPOSITORY_PFPC.json',
      verified:true
    };
  }
  if(admissionSha!==undefined)admission.artifact_sha256=admissionSha;
  if(candidateId!=null)admission.candidate_id=candidateId;
  if(generationId!=null)admission.generation_id=generationId;
  if(binding!=null)admission.binding_sha256=binding;
  if(provenance===true)admission.provenance={
    source_population_id:populationId,
    manifest_sha256:sha,
    binding_sha256:binding,
    candidate_id:candidateId,
    generation_id:generationId
  };
  else if(provenance)admission.provenance=provenance;
  return admission;
}

function contextFor(populationId){return {...CONTEXT,population_id:populationId};}
function contextAt(spot){return {...CONTEXT,spot};}

// #task-ewo: completeness must be bounded by an authoritative required context
// set. `required_context_keys` is the explicit form; a generation manifest is
// the derived form. Either one is required before ADMISSIBLE_CALCULATED.
const REQUIRED_CONTEXT_KEYS=[H.contextKey(CONTEXT)];
function requiredContextKeys(...spots){return spots.map(spot=>H.contextKey(contextAt(spot)));}

function repository({populationId=POP,hands=169,spot=CONTEXT.spot,version=GENERATION_VERSION,provenance=LAYER_PROVENANCE}={}){
  const repo=H.emptyRepository({populationId});
  const context={...CONTEXT,population_id:populationId,spot};
  H.setLayerMetadata(repo,context,'calculated',{version,provenance});
  for(const hand of H.HAND_CLASSES.slice(0,hands)){
    H.setHandStrategy(repo,context,hand,{actions:{FOLD:1}},{layer:'calculated'});
  }
  return repo;
}

function hasExactCustomLabel(value){
  if(typeof value==='string')return value.trim().toLowerCase()==='custom';
  if(Array.isArray(value))return value.some(hasExactCustomLabel);
  if(value&&typeof value==='object')return Object.values(value).some(hasExactCustomLabel);
  return false;
}
function schemaHasNoCustom(value){
  return !hasExactCustomLabel(value);
}

// --- contract surface -------------------------------------------------------
assert.equal(R.SCHEMA,'poker-hero-strategy-resolution/v1');
assert.deepEqual(Object.values(R.STATUSES).sort(),[
  'ADMISSIBLE_CALCULATED','PARTIAL','POPULATION_INCOMPATIBLE','RETAIN_REFERENCE','UNAVAILABLE'
]);
assert.deepEqual(Object.values(R.SOURCES).sort(),['NONE','PERSONAL_OVERRIDE','POPULATION']);
assert.deepEqual(R.ADMISSION_STATUSES,['ADMISSIBLE','RETAIN_REFERENCE','UNRESOLVED','REJECTED','INCOMPATIBLE']);

// --- population compatible: admitted complete calculated strategy -----------
const compatibleInput={
  population_id:POP,
  repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission()},
  pack_identity:{population_id:POP},
  trainer_manifest:{schema:R.TRAINER_MANIFEST_SCHEMA,population_id:POP},
  required_context_keys:REQUIRED_CONTEXT_KEYS
};
const compatible=R.resolveHeroStrategy(compatibleInput);
assert.equal(compatible.schema,R.SCHEMA);
assert.equal(compatible.status,R.STATUSES.ADMISSIBLE_CALCULATED);
assert.equal(compatible.source,R.SOURCES.POPULATION);
assert.equal(compatible.population_id,POP);
assert.equal(compatible.fail_closed,false);
assert.equal(compatible.strategy_id,'hero-candidate-196');
assert.equal(compatible.strategy_version,GENERATION_VERSION);
assert.equal(compatible.strategy_sha256,SHA_MANIFEST);
assert.equal(compatible.provenance.origin,'CALCULATED_POPULATION');
assert.equal(compatible.provenance.generation_id,'gen-196');
assert.equal(compatible.provenance.manifest_sha256,SHA_MANIFEST);
assert.equal(compatible.provenance.coverage.complete,true);
assert.equal(compatible.provenance.coverage.authoritative,true);
assert.equal(compatible.provenance.coverage.required,1);
assert.equal(compatible.provenance.coverage.covered,1);
assert.equal(compatible.provenance.coverage.missing,0);
assert.deepEqual(compatible.provenance.coverage.required_context_keys,REQUIRED_CONTEXT_KEYS);
assert.deepEqual(compatible.provenance.coverage.covered_context_keys,REQUIRED_CONTEXT_KEYS);
assert.deepEqual(compatible.provenance.coverage.missing_context_keys,[]);
assert.ok(compatible.reason_codes.includes('ADMITTED_CALCULATED_STRATEGY'));
assert.ok(!compatible.reason_codes.includes('COVERAGE_INCOMPLETE'));
assert.ok(!compatible.reason_codes.includes('REQUIRED_CONTEXT_SET_UNKNOWN'));
assert.ok(schemaHasNoCustom(compatible),'resolution must never contain the Custom label');

// A full poker-scientific-component-admission/v1 document nests the role map.
const nestedAdmission=R.resolveHeroStrategy({
  population_id:POP,
  repository:repository({hands:169}),
  admissions:{population_id:POP,admissions:{
    hero_strategy:boundAdmission(),
    hero_ranges:{status:'ADMISSIBLE',population_id:POP}
  }},
  required_context_keys:REQUIRED_CONTEXT_KEYS
});
assert.equal(nestedAdmission.status,R.STATUSES.ADMISSIBLE_CALCULATED);
assert.equal(nestedAdmission.source,R.SOURCES.POPULATION);

// --- deterministic output for the same input --------------------------------
const deterministicA=R.resolveHeroStrategy(compatibleInput);
const deterministicB=R.resolveHeroStrategy({
  ...compatibleInput,
  repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission()}
});
assert.deepEqual(deterministicA,deterministicB);
assert.equal(JSON.stringify(deterministicA),JSON.stringify(deterministicB));
assert.deepEqual(deterministicA.reason_codes,[...deterministicA.reason_codes].sort());
assert.equal(new Set(deterministicA.reason_codes).size,deterministicA.reason_codes.length);

// --- explicit provenance/version token overrides ----------------------------
const overridden=R.resolveHeroStrategy({
  population_id:POP,
  repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission()},
  strategy_id:'hero-strategy-token',
  strategy_version:'2026-09-21.1',
  strategy_sha256:SHA_MANIFEST,
  required_context_keys:REQUIRED_CONTEXT_KEYS
});
assert.equal(overridden.status,R.STATUSES.ADMISSIBLE_CALCULATED);
assert.equal(overridden.strategy_id,'hero-strategy-token');
assert.equal(overridden.strategy_version,'2026-09-21.1');
assert.equal(overridden.strategy_sha256,SHA_MANIFEST);
assert.ok(schemaHasNoCustom(overridden));

// An invalid explicit sha is ignored rather than echoed as a fake identity.
const invalidSha=R.resolveHeroStrategy({
  population_id:POP,
  repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission()},
  strategy_sha256:'not-a-sha'
});
assert.equal(invalidSha.strategy_sha256,SHA_MANIFEST);

// --- population incompatible: fail closed, no strategy ----------------------
const defaultsMismatch=R.resolveHeroStrategy({
  population_id:POP,
  repository:H.emptyRepository({populationId:OTHER}),
  admissions:'ADMISSIBLE'
});
assert.equal(defaultsMismatch.status,R.STATUSES.POPULATION_INCOMPATIBLE);
assert.equal(defaultsMismatch.source,R.SOURCES.NONE);
assert.equal(defaultsMismatch.fail_closed,true);
assert.equal(defaultsMismatch.strategy_id,null);
assert.equal(defaultsMismatch.strategy_version,null);
assert.equal(defaultsMismatch.strategy_sha256,null);
assert.equal(defaultsMismatch.provenance,null);
assert.ok(defaultsMismatch.reason_codes.includes('POPULATION_ID_MISMATCH'));
assert.ok(defaultsMismatch.reason_codes.includes('REPOSITORY_DEFAULTS_POPULATION_MISMATCH'));

const calculatedContextMismatch=repository({hands:169});
H.setLayerMetadata(calculatedContextMismatch,contextFor(OTHER),'calculated',{version:'foreign',provenance:{schema:R.IMPORT_SCHEMA}});
H.setHandStrategy(calculatedContextMismatch,contextFor(OTHER),'AA',{actions:{FOLD:1}},{layer:'calculated'});
const calculatedMismatch=R.resolveHeroStrategy({population_id:POP,repository:calculatedContextMismatch,admissions:'ADMISSIBLE'});
assert.equal(calculatedMismatch.status,R.STATUSES.POPULATION_INCOMPATIBLE);
assert.ok(calculatedMismatch.reason_codes.includes('CALCULATED_CONTEXT_POPULATION_MISMATCH'));

const candidateMismatch=R.resolveHeroStrategy({
  population_id:POP,
  candidate:{schema:R.CANDIDATE_SCHEMA,population_id:OTHER,version:'candidate-v1',promotion_authorized:false,repository:repository({hands:169})},
  admissions:'ADMISSIBLE'
});
assert.equal(candidateMismatch.status,R.STATUSES.POPULATION_INCOMPATIBLE);
assert.ok(candidateMismatch.reason_codes.includes('CANDIDATE_POPULATION_MISMATCH'));

const packMismatch=R.resolveHeroStrategy({
  population_id:POP,
  repository:repository({hands:169}),
  pack_identity:{population_id:OTHER},
  admissions:'ADMISSIBLE'
});
assert.equal(packMismatch.status,R.STATUSES.POPULATION_INCOMPATIBLE);
assert.ok(packMismatch.reason_codes.includes('PACK_IDENTITY_POPULATION_MISMATCH'));

const manifestMismatch=R.resolveHeroStrategy({
  population_id:POP,
  repository:repository({hands:169}),
  trainer_manifest:{schema:R.TRAINER_MANIFEST_SCHEMA,population_id:OTHER},
  admissions:'ADMISSIBLE'
});
assert.equal(manifestMismatch.status,R.STATUSES.POPULATION_INCOMPATIBLE);
assert.ok(manifestMismatch.reason_codes.includes('TRAINER_MANIFEST_POPULATION_MISMATCH'));

const admissionIncompatible=R.resolveHeroStrategy({
  population_id:POP,
  repository:repository({hands:169}),
  admissions:{hero_strategy:{status:'INCOMPATIBLE',population_id:POP}}
});
assert.equal(admissionIncompatible.status,R.STATUSES.POPULATION_INCOMPATIBLE);
assert.equal(admissionIncompatible.fail_closed,true);
assert.ok(admissionIncompatible.reason_codes.includes('ADMISSION_INCOMPATIBLE'));

// Both admission roles are population-bound: a foreign hero_ranges admission
// must fail closed even when hero_strategy itself is admissible and compatible.
const heroRangesAdmissionMismatch=R.resolveHeroStrategy({
  population_id:POP,
  repository:repository({hands:169}),
  admissions:{admissions:{
    hero_strategy:{status:'ADMISSIBLE',population_id:POP},
    hero_ranges:{status:'ADMISSIBLE',population_id:OTHER}
  }}
});
assert.equal(heroRangesAdmissionMismatch.status,R.STATUSES.POPULATION_INCOMPATIBLE);
assert.equal(heroRangesAdmissionMismatch.source,R.SOURCES.NONE);
assert.equal(heroRangesAdmissionMismatch.fail_closed,true);
assert.equal(heroRangesAdmissionMismatch.strategy_id,null);
assert.equal(heroRangesAdmissionMismatch.strategy_version,null);
assert.equal(heroRangesAdmissionMismatch.strategy_sha256,null);
assert.equal(heroRangesAdmissionMismatch.provenance,null);
assert.ok(heroRangesAdmissionMismatch.reason_codes.includes('POPULATION_ID_MISMATCH'));
assert.ok(heroRangesAdmissionMismatch.reason_codes.includes('ADMISSION_HERO_RANGES_POPULATION_MISMATCH'));

const missingPopulation=R.resolveHeroStrategy({repository:repository({hands:169}),admissions:'ADMISSIBLE'});
assert.equal(missingPopulation.status,R.STATUSES.POPULATION_INCOMPATIBLE);
assert.equal(missingPopulation.population_id,null);
assert.ok(missingPopulation.reason_codes.includes('POPULATION_ID_MISSING'));

// --- no admissible strategy: explicit UNAVAILABLE/PARTIAL, never Custom ------
const empty=R.resolveHeroStrategy({population_id:POP,repository:H.emptyRepository({populationId:POP})});
assert.equal(empty.status,R.STATUSES.UNAVAILABLE);
assert.equal(empty.source,R.SOURCES.NONE);
assert.equal(empty.fail_closed,true);
assert.equal(empty.strategy_id,null);
assert.ok(empty.reason_codes.includes('NO_ADMISSIBLE_STRATEGY'));
assert.ok(schemaHasNoCustom(empty));

// A malformed repository fails closed even when an admission claims ADMISSIBLE.
const malformed=repository({hands:169});
malformed.schema='not-the-hero-repository-schema';
const malformedResolution=R.resolveHeroStrategy({population_id:POP,repository:malformed,admissions:'ADMISSIBLE'});
assert.equal(malformedResolution.status,R.STATUSES.UNAVAILABLE);
assert.notEqual(malformedResolution.status,R.STATUSES.ADMISSIBLE_CALCULATED);
assert.ok(malformedResolution.reason_codes.includes('REPOSITORY_INVALID'));
assert.equal(malformedResolution.strategy_id,null);

const completeNotAdmitted=R.resolveHeroStrategy({population_id:POP,repository:repository({hands:169})});
assert.equal(completeNotAdmitted.status,R.STATUSES.UNAVAILABLE);
assert.ok(completeNotAdmitted.reason_codes.includes('STRATEGY_NOT_ADMITTED'));

const rejected=R.resolveHeroStrategy({population_id:POP,repository:repository({hands:169}),admissions:'REJECTED'});
assert.equal(rejected.status,R.STATUSES.UNAVAILABLE);
assert.ok(rejected.reason_codes.includes('STRATEGY_REJECTED'));

const unresolved=R.resolveHeroStrategy({population_id:POP,repository:repository({hands:169}),admissions:'UNRESOLVED'});
assert.equal(unresolved.status,R.STATUSES.UNAVAILABLE);
assert.ok(unresolved.reason_codes.includes('STRATEGY_UNRESOLVED'));

const admittedIncomplete=R.resolveHeroStrategy({population_id:POP,repository:repository({hands:12}),admissions:{hero_strategy:boundAdmission()}});
assert.equal(admittedIncomplete.status,R.STATUSES.PARTIAL);
assert.equal(admittedIncomplete.source,R.SOURCES.POPULATION);
assert.equal(admittedIncomplete.fail_closed,true);
assert.notEqual(admittedIncomplete.status,R.STATUSES.ADMISSIBLE_CALCULATED);
assert.ok(admittedIncomplete.reason_codes.includes('STRATEGY_PARTIAL_COVERAGE'));
assert.ok(schemaHasNoCustom(admittedIncomplete));

// --- #task-ewo: completeness is bounded by an authoritative required set -----
// A hand-complete calculated context alone is not evidence of completeness: the
// resolver refuses to infer coverage from the artifact itself.

// (1) A single 169-hand context, validly admitted, but without any required set
//     is not complete. It must be PARTIAL, never ADMISSIBLE_CALCULATED.
const unboundedComplete=R.resolveHeroStrategy({
  population_id:POP,
  repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission()}
});
assert.equal(unboundedComplete.status,R.STATUSES.PARTIAL);
assert.notEqual(unboundedComplete.status,R.STATUSES.ADMISSIBLE_CALCULATED);
assert.equal(unboundedComplete.fail_closed,true);
assert.equal(unboundedComplete.provenance.coverage.authoritative,false);
assert.equal(unboundedComplete.provenance.coverage.complete,false);
assert.equal(unboundedComplete.provenance.coverage.required,0);
assert.equal(unboundedComplete.provenance.coverage.covered,0);
assert.equal(unboundedComplete.provenance.coverage.missing,0);
assert.ok(unboundedComplete.reason_codes.includes('REQUIRED_CONTEXT_SET_UNKNOWN'));
assert.ok(unboundedComplete.reason_codes.includes('COVERAGE_INCOMPLETE'));
assert.ok(unboundedComplete.reason_codes.includes('STRATEGY_PARTIAL_COVERAGE'));

// (2) Partial coverage (#358-like): VS_LIMPERS is present but the required
//     VS_ISO/VS_RFI context is missing. A valid admission cannot make this
//     complete.
const partialCoverageRepo=repository({hands:169,spot:'VS_LIMPERS'});
const partialCoverage=R.resolveHeroStrategy({
  population_id:POP,
  repository:partialCoverageRepo,
  admissions:{hero_strategy:boundAdmission()},
  required_context_keys:requiredContextKeys('VS_LIMPERS','VS_RFI')
});
assert.equal(partialCoverage.status,R.STATUSES.PARTIAL);
assert.notEqual(partialCoverage.status,R.STATUSES.ADMISSIBLE_CALCULATED);
assert.equal(partialCoverage.provenance.coverage.authoritative,true);
assert.equal(partialCoverage.provenance.coverage.complete,false);
assert.equal(partialCoverage.provenance.coverage.required,2);
assert.equal(partialCoverage.provenance.coverage.covered,1);
assert.equal(partialCoverage.provenance.coverage.missing,1);
assert.deepEqual(partialCoverage.provenance.coverage.covered_context_keys,requiredContextKeys('VS_LIMPERS'));
assert.deepEqual(partialCoverage.provenance.coverage.missing_context_keys,requiredContextKeys('VS_RFI'));
assert.ok(partialCoverage.reason_codes.includes('REQUIRED_CONTEXT_MISSING'));
assert.ok(partialCoverage.reason_codes.includes('COVERAGE_INCOMPLETE'));

// The same partial state is detected when the required set comes from a
// poker-hero-preflop-generation-manifest/v1 instead of explicit keys.
const manifestPartial=R.resolveHeroStrategy({
  population_id:POP,
  repository:partialCoverageRepo,
  admissions:{hero_strategy:boundAdmission()},
  generation_manifest:{
    schema:R.GENERATION_MANIFEST_SCHEMA,
    population_id:POP,
    expected_context_ids:requiredContextKeys('VS_LIMPERS','VS_RFI'),
    plan_projection:{ready_context_count:2}
  }
});
assert.equal(manifestPartial.status,R.STATUSES.PARTIAL);
assert.equal(manifestPartial.provenance.coverage.source,'GENERATION_MANIFEST');
assert.equal(manifestPartial.provenance.coverage.required,2);
assert.equal(manifestPartial.provenance.coverage.covered,1);
assert.equal(manifestPartial.provenance.coverage.missing,1);
assert.ok(manifestPartial.reason_codes.includes('REQUIRED_CONTEXT_MISSING'));

// A required context present but only partially defined (12 hands) is not
// covered by a complete context.
const incompleteRequired=R.resolveHeroStrategy({
  population_id:POP,
  repository:repository({hands:12}),
  admissions:{hero_strategy:boundAdmission()},
  required_context_keys:REQUIRED_CONTEXT_KEYS
});
assert.equal(incompleteRequired.status,R.STATUSES.PARTIAL);
assert.notEqual(incompleteRequired.status,R.STATUSES.ADMISSIBLE_CALCULATED);
assert.equal(incompleteRequired.provenance.coverage.covered,0);
assert.equal(incompleteRequired.provenance.coverage.missing,1);
assert.deepEqual(incompleteRequired.provenance.coverage.incomplete_context_keys,REQUIRED_CONTEXT_KEYS);
assert.ok(incompleteRequired.reason_codes.includes('REQUIRED_CONTEXT_MISSING'));

// (3) An authoritative required set fully covered by complete contexts is
//     ADMISSIBLE_CALCULATED.
const boundedComplete=R.resolveHeroStrategy({
  population_id:POP,
  repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission()},
  required_context_keys:REQUIRED_CONTEXT_KEYS
});
assert.equal(boundedComplete.status,R.STATUSES.ADMISSIBLE_CALCULATED);
assert.equal(boundedComplete.source,R.SOURCES.POPULATION);
assert.equal(boundedComplete.fail_closed,false);
assert.equal(boundedComplete.provenance.coverage.authoritative,true);
assert.equal(boundedComplete.provenance.coverage.complete,true);
assert.equal(boundedComplete.provenance.coverage.required,1);
assert.equal(boundedComplete.provenance.coverage.covered,1);
assert.equal(boundedComplete.provenance.coverage.missing,0);
assert.deepEqual(boundedComplete.provenance.coverage.missing_context_keys,[]);
assert.deepEqual(boundedComplete.reason_codes,[...boundedComplete.reason_codes].sort());
assert.ok(schemaHasNoCustom(boundedComplete));

// Completeness is scoped to the authoritative required set. An incomplete
// calculated context outside that set must not make a fully covered required
// set incomplete.
const boundedWithIncompleteExtraRepo=repository({hands:169});
const incompleteExtraContext=contextAt('VS_LIMPERS');
H.setLayerMetadata(boundedWithIncompleteExtraRepo,incompleteExtraContext,'calculated',{
  version:GENERATION_VERSION,
  provenance:LAYER_PROVENANCE
});
for(const hand of H.HAND_CLASSES.slice(0,12)){
  H.setHandStrategy(boundedWithIncompleteExtraRepo,incompleteExtraContext,hand,{actions:{FOLD:1}},{layer:'calculated'});
}
const boundedWithIncompleteExtra=R.resolveHeroStrategy({
  population_id:POP,
  repository:boundedWithIncompleteExtraRepo,
  admissions:{hero_strategy:boundAdmission()},
  required_context_keys:REQUIRED_CONTEXT_KEYS
});
assert.equal(boundedWithIncompleteExtra.status,R.STATUSES.ADMISSIBLE_CALCULATED);
assert.equal(boundedWithIncompleteExtra.provenance.coverage.complete,true);
assert.equal(boundedWithIncompleteExtra.provenance.coverage.required,1);
assert.equal(boundedWithIncompleteExtra.provenance.coverage.covered,1);
assert.equal(boundedWithIncompleteExtra.provenance.coverage.missing,0);
assert.equal(boundedWithIncompleteExtra.provenance.coverage.contexts,2);
assert.ok(!boundedWithIncompleteExtra.reason_codes.includes('COVERAGE_INCOMPLETE'));

// The generation manifest path also accepts expected_context_ids expressed as
// the repository preflop_context_id token.
const PFC_ID='PFC_0123456789abcdef';
const pfcContext={...CONTEXT,preflop_context_id:PFC_ID};
const pfcRepo=H.emptyRepository({populationId:POP});
H.setLayerMetadata(pfcRepo,pfcContext,'calculated',{version:GENERATION_VERSION,provenance:LAYER_PROVENANCE});
for(const hand of H.HAND_CLASSES)H.setHandStrategy(pfcRepo,pfcContext,hand,{actions:{FOLD:1}},{layer:'calculated'});
const manifestComplete=R.resolveHeroStrategy({
  population_id:POP,
  repository:pfcRepo,
  admissions:{hero_strategy:boundAdmission()},
  generation_manifest:{
    schema:R.GENERATION_MANIFEST_SCHEMA,
    population_id:POP,
    expected_context_ids:[PFC_ID],
    plan_projection:{ready_context_count:1}
  }
});
assert.equal(manifestComplete.status,R.STATUSES.ADMISSIBLE_CALCULATED);
assert.equal(manifestComplete.provenance.coverage.source,'GENERATION_MANIFEST');
assert.deepEqual(manifestComplete.provenance.coverage.expected_context_ids,[PFC_ID]);
assert.equal(manifestComplete.provenance.coverage.ready_context_count,1);
assert.equal(manifestComplete.provenance.coverage.covered,1);
assert.equal(manifestComplete.provenance.coverage.missing,0);

// A real generation manifest lists the generation source context id, which the
// imported calculated layer records under provenance.exact_context.context_id.
const SOURCE_CONTEXT_ID='pfgen:v1:family=VS_LIMPERS:hero=CO:opener=NONE:lastagg=NONE:callers=0:limpers=1:jam=0:stack=B3_P50_P75';
const sourceProvenance={...LAYER_PROVENANCE,exact_context:{context_id:SOURCE_CONTEXT_ID}};
const sourceRepo=H.emptyRepository({populationId:POP});
H.setLayerMetadata(sourceRepo,CONTEXT,'calculated',{version:GENERATION_VERSION,provenance:sourceProvenance});
for(const hand of H.HAND_CLASSES)H.setHandStrategy(sourceRepo,CONTEXT,hand,{actions:{FOLD:1}},{layer:'calculated'});
const manifestSourceId=R.resolveHeroStrategy({
  population_id:POP,
  repository:sourceRepo,
  admissions:{hero_strategy:boundAdmission()},
  generation_manifest:{
    schema:R.GENERATION_MANIFEST_SCHEMA,
    population_id:POP,
    expected_context_ids:[SOURCE_CONTEXT_ID],
    plan_projection:{ready_context_count:1}
  }
});
assert.equal(manifestSourceId.status,R.STATUSES.ADMISSIBLE_CALCULATED);
assert.equal(manifestSourceId.provenance.coverage.covered,1);
assert.equal(manifestSourceId.provenance.coverage.missing,0);

// A manifest that announces more ready contexts than are covered stays PARTIAL.
const manifestOverclaim=R.resolveHeroStrategy({
  population_id:POP,
  repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission()},
  generation_manifest:{
    schema:R.GENERATION_MANIFEST_SCHEMA,
    population_id:POP,
    expected_context_ids:REQUIRED_CONTEXT_KEYS,
    plan_projection:{ready_context_count:2}
  }
});
assert.equal(manifestOverclaim.status,R.STATUSES.PARTIAL);
assert.equal(manifestOverclaim.provenance.coverage.required,2);
assert.equal(manifestOverclaim.provenance.coverage.covered,1);
assert.equal(manifestOverclaim.provenance.coverage.missing,1);
assert.ok(manifestOverclaim.reason_codes.includes('COVERAGE_INCOMPLETE'));

// A generation manifest bound to another population fails closed.
const manifestForeign=R.resolveHeroStrategy({
  population_id:POP,
  repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission()},
  generation_manifest:{
    schema:R.GENERATION_MANIFEST_SCHEMA,
    population_id:OTHER,
    expected_context_ids:REQUIRED_CONTEXT_KEYS,
    plan_projection:{ready_context_count:1}
  }
});
assert.equal(manifestForeign.status,R.STATUSES.POPULATION_INCOMPATIBLE);
assert.ok(manifestForeign.reason_codes.includes('GENERATION_MANIFEST_POPULATION_MISMATCH'));

// Inactive #358 candidate metadata must never be auto-activated.
const inactive=H.emptyRepository({populationId:POP});
H.setLayerMetadata(inactive,CONTEXT,'calculated',{
  version:'gen-358-inactive',
  provenance:{schema:R.IMPORT_SCHEMA,activation_state:'INACTIVE_CANDIDATE_METADATA_ONLY',candidate_id:'candidate-358'}
});
const inactiveResolution=R.resolveHeroStrategy({population_id:POP,repository:inactive,admissions:'ADMISSIBLE'});
assert.equal(inactiveResolution.status,R.STATUSES.UNAVAILABLE);
assert.notEqual(inactiveResolution.status,R.STATUSES.ADMISSIBLE_CALCULATED);
assert.ok(inactiveResolution.reason_codes.includes('INACTIVE_CANDIDATE_NOT_ACTIVATED'));
assert.equal(inactiveResolution.strategy_id,null);

// --- personal override is never presented as the population strategy ---------
const personalOnly=H.emptyRepository({populationId:POP});
H.setHandStrategy(personalOnly,CONTEXT,'AA',{actions:{OPEN:1}},{layer:'personal'});
const personalResolution=R.resolveHeroStrategy({population_id:POP,repository:personalOnly});
assert.equal(personalResolution.status,R.STATUSES.PARTIAL);
assert.equal(personalResolution.source,R.SOURCES.PERSONAL_OVERRIDE);
assert.equal(personalResolution.fail_closed,true);
assert.equal(personalResolution.strategy_id,null);
assert.equal(personalResolution.provenance.origin,'PERSONAL_OVERRIDE');
assert.ok(personalResolution.reason_codes.includes('PERSONAL_OVERRIDE_NOT_POPULATION_STRATEGY'));

const layeredOverride=repository({hands:169});
H.setHandStrategy(layeredOverride,CONTEXT,'AA',{actions:{LIMP:1}},{layer:'personal'});
const layeredResolution=R.resolveHeroStrategy({population_id:POP,repository:layeredOverride,admissions:{hero_strategy:boundAdmission()},required_context_keys:REQUIRED_CONTEXT_KEYS});
assert.equal(layeredResolution.status,R.STATUSES.ADMISSIBLE_CALCULATED);
assert.equal(layeredResolution.source,R.SOURCES.POPULATION,'personal override must not become the population source');

// --- retained reference contract --------------------------------------------
const retained=R.resolveHeroStrategy({
  population_id:POP,
  repository:H.emptyRepository({populationId:POP}),
  admissions:{hero_strategy:{status:'RETAIN_REFERENCE',population_id:POP}},
  retained_reference:{schema:'issue-108-retained-reference',issue:108,population_id:POP,strategy_id:'retained-model-a-v5',strategy_version:'2026-09-19.1',strategy_sha256:SHA_REFERENCE}
});
assert.equal(retained.status,R.STATUSES.RETAIN_REFERENCE);
assert.equal(retained.source,R.SOURCES.POPULATION);
assert.equal(retained.fail_closed,false);
assert.equal(retained.strategy_id,'retained-model-a-v5');
assert.equal(retained.strategy_version,'2026-09-19.1');
assert.equal(retained.strategy_sha256,SHA_REFERENCE);
assert.equal(retained.provenance.origin,'RETAINED_REFERENCE');
assert.equal(retained.provenance.reference_issue,'108');

const retainedWithoutIdentity=R.resolveHeroStrategy({
  population_id:POP,
  repository:H.emptyRepository({populationId:POP}),
  admissions:{hero_strategy:{status:'RETAIN_REFERENCE',population_id:POP}}
});
assert.equal(retainedWithoutIdentity.status,R.STATUSES.RETAIN_REFERENCE);
assert.equal(retainedWithoutIdentity.strategy_id,null);
assert.ok(retainedWithoutIdentity.reason_codes.includes('RETAINED_REFERENCE_IDENTITY_MISSING'));

// --- candidate self-promotion is rejected -----------------------------------
const selfPromoted=R.resolveHeroStrategy({
  population_id:POP,
  candidate:{schema:R.CANDIDATE_SCHEMA,population_id:POP,version:'candidate-v1',promotion_authorized:true,repository:repository({hands:169})},
  admissions:'ADMISSIBLE'
});
assert.notEqual(selfPromoted.status,R.STATUSES.ADMISSIBLE_CALCULATED);
assert.equal(selfPromoted.fail_closed,true);
assert.ok(selfPromoted.reason_codes.includes('CANDIDATE_PROMOTION_FORBIDDEN'));

// --- the literal Custom label is never emitted ------------------------------
const customOverride=R.resolveHeroStrategy({
  population_id:POP,
  repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission()},
  strategy_id:'Custom',
  required_context_keys:REQUIRED_CONTEXT_KEYS
});
assert.notEqual(String(customOverride.strategy_id).toLowerCase(),'custom');
assert.equal(customOverride.strategy_id,'hero-candidate-196');
assert.ok(customOverride.reason_codes.includes('CUSTOM_LABEL_REJECTED'));
assert.ok(schemaHasNoCustom(customOverride));

const customLayer=H.emptyRepository({populationId:POP});
H.setLayerMetadata(customLayer,CONTEXT,'calculated',{
  version:'custom-version',
  provenance:{schema:R.IMPORT_SCHEMA,activation_state:'ACTIVE_MEASURED',candidate_id:'Custom',generation_id:'Custom',manifest_sha256:SHA_MANIFEST,binding_sha256:SHA_BINDING}
});
for(const hand of H.HAND_CLASSES)H.setHandStrategy(customLayer,CONTEXT,hand,{actions:{FOLD:1}},{layer:'calculated'});
const customResolution=R.resolveHeroStrategy({
  population_id:POP,
  repository:customLayer,
  admissions:{hero_strategy:boundAdmission({candidateId:'Custom',generationId:'Custom'})}
});
assert.ok(schemaHasNoCustom(customResolution));
assert.notEqual(customResolution.status,R.STATUSES.ADMISSIBLE_CALCULATED);
assert.equal(customResolution.provenance,null);
assert.equal(customResolution.strategy_id,null);
assert.equal(customResolution.fail_closed,true);
assert.ok(customResolution.reason_codes.includes('CUSTOM_LABEL_REJECTED'));
assert.ok(customResolution.reason_codes.includes('ADMISSION_CANDIDATE_MISMATCH'));
assert.ok(customResolution.reason_codes.includes('ADMISSION_GENERATION_MISMATCH'));

// --- #task-fnc: ADMISSIBLE must be bound to the exact runtime artifact -------
function assertFailClosed(resolution,code){
  assert.notEqual(resolution.status,R.STATUSES.ADMISSIBLE_CALCULATED,'an unbound admission must never be ADMISSIBLE_CALCULATED');
  assert.equal(resolution.strategy_id,null,'an unbound admission must never yield a strategy identity');
  assert.equal(resolution.fail_closed,true);
  assert.ok(resolution.reason_codes.includes(code),`expected ${code} in ${resolution.reason_codes.join(',')}`);
  assert.deepEqual(resolution.reason_codes,[...resolution.reason_codes].sort());
  assert.equal(new Set(resolution.reason_codes).size,resolution.reason_codes.length);
  assert.ok(schemaHasNoCustom(resolution));
}

// 1. A bare ADMISSIBLE status token alone authorizes nothing.
assertFailClosed(R.resolveHeroStrategy({
  population_id:POP,repository:repository({hands:169}),admissions:'ADMISSIBLE'
}),'ADMISSION_ARTIFACT_MISSING');

// 2. An admission object without any artifact identity authorizes nothing.
assertFailClosed(R.resolveHeroStrategy({
  population_id:POP,repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission({artifact:false})}
}),'ADMISSION_ARTIFACT_MISSING');

// 3. An admission artifact without a usable SHA-256 is missing its identity.
assertFailClosed(R.resolveHeroStrategy({
  population_id:POP,repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission({declaredSha:null,actualSha:null})}
}),'ADMISSION_HASH_MISSING');

// 4. A divergent content hash does not describe the runtime artifact.
assertFailClosed(R.resolveHeroStrategy({
  population_id:POP,repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission({sha:'f'.repeat(64)})}
}),'ADMISSION_HASH_MISMATCH');

// 4a. No declared hash may hide behind a matching higher-priority hash.
assertFailClosed(R.resolveHeroStrategy({
  population_id:POP,repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission({actualSha:SHA_MANIFEST,declaredSha:'f'.repeat(64)})}
}),'ADMISSION_HASH_MISMATCH');

// 4b. A contradictory root artifact hash also invalidates the admission.
assertFailClosed(R.resolveHeroStrategy({
  population_id:POP,repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission({admissionSha:'f'.repeat(64)})}
}),'ADMISSION_HASH_MISMATCH');

// 4c. An explicit divergent SHA-256 token is a mismatch, not an override.
assertFailClosed(R.resolveHeroStrategy({
  population_id:POP,repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission()},
  strategy_sha256:'f'.repeat(64)
}),'ADMISSION_HASH_MISMATCH');

// 4d. Candidate metadata cannot declare a different calculated artifact hash.
assertFailClosed(R.resolveHeroStrategy({
  population_id:POP,repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission()},
  candidate:{candidate_id:'hero-candidate-196',strategy_sha256:'f'.repeat(64)}
}),'ADMISSION_HASH_MISMATCH');

// 5. A divergent candidate_id does not identify the calculated layer.
assertFailClosed(R.resolveHeroStrategy({
  population_id:POP,repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission({candidateId:'other-candidate'})}
}),'ADMISSION_CANDIDATE_MISMATCH');

// 6. A divergent generation_id does not identify the calculated layer.
assertFailClosed(R.resolveHeroStrategy({
  population_id:POP,repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission({generationId:'other-generation'})}
}),'ADMISSION_GENERATION_MISMATCH');

// 7. A divergent binding_sha256 is not the binding used at runtime.
assertFailClosed(R.resolveHeroStrategy({
  population_id:POP,repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission({binding:'e'.repeat(64)})}
}),'ADMISSION_BINDING_MISMATCH');

// 8. A wrong admission role is not the hero_strategy admission.
assertFailClosed(R.resolveHeroStrategy({
  population_id:POP,repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission({role:'hero_ranges'})}
}),'ADMISSION_ROLE_MISMATCH');

// 9. Admission provenance is mandatory and population-bound.
assertFailClosed(R.resolveHeroStrategy({
  population_id:POP,repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission({provenance:false})}
}),'ADMISSION_PROVENANCE_MISSING');

assertFailClosed(R.resolveHeroStrategy({
  population_id:POP,repository:repository({hands:169}),
  admissions:{hero_strategy:boundAdmission({provenance:{
    source_population_id:POP,
    manifest_sha256:'f'.repeat(64),
    binding_sha256:SHA_BINDING,
    candidate_id:'hero-candidate-196',
    generation_id:'gen-196'
  }})}
}),'ADMISSION_PROVENANCE_MISMATCH');

// 10. A calculated layer with no provenance/hash is not bound to any admission.
const unboundLayer=H.emptyRepository({populationId:POP});
H.setLayerMetadata(unboundLayer,CONTEXT,'calculated',{
  version:'unbound-v1',
  provenance:{schema:R.IMPORT_SCHEMA,activation_state:'ACTIVE_MEASURED'}
});
for(const hand of H.HAND_CLASSES)H.setHandStrategy(unboundLayer,CONTEXT,hand,{actions:{FOLD:1}},{layer:'calculated'});
assertFailClosed(R.resolveHeroStrategy({
  population_id:POP,repository:unboundLayer,
  admissions:{hero_strategy:boundAdmission()}
}),'REPOSITORY_NOT_BOUND_TO_ADMISSION');

// The bare-token fail-close is deterministic and never PARTIAL either.
const bareComplete=R.resolveHeroStrategy({population_id:POP,repository:repository({hands:169}),admissions:'ADMISSIBLE'});
const bareCompleteAgain=R.resolveHeroStrategy({population_id:POP,repository:repository({hands:169}),admissions:'ADMISSIBLE'});
assert.deepEqual(bareComplete,bareCompleteAgain);
assert.equal(JSON.stringify(bareComplete),JSON.stringify(bareCompleteAgain));
assert.notEqual(bareComplete.status,R.STATUSES.PARTIAL);

console.log('Hero strategy resolution contract: PASS');
