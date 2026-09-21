#!/usr/bin/env node
/*
  End-to-end contract for the population-bound Hero strategy (issue #392).

  This suite orchestrates the three runtime surfaces together, exactly as the
  browser does:

  - `site/hero-ranges.js`            : the population-bound range repository.
  - `site/hero-range-migration.js`   : additive/reversible localStorage migration.
  - `site/hero-strategy-resolver.js` : the pure Population -> Hero strategy resolver
                                       and its shared `identity()` accessor.

  It walks the nine required scenarios and pins the fail-closed invariants of
  #196/#201/#305/#358 across resolver, migration and identity surfaces:

  1. population compatible      -> ADMISSIBLE_CALCULATED, source POPULATION.
  2. population incompatible    -> POPULATION_INCOMPATIBLE, no identity, no relabel.
  3. aucune stratégie           -> explicit UNAVAILABLE, never "Custom".
  4. override personnel         -> PARTIAL/PERSONAL_OVERRIDE, never the population source.
  5. changement de pack         -> pack/manifest binding is enforced at resolution.
  6. rollback                   -> exact pre-migration bytes restored, previous kept.
  7. persistence                -> migrated repository is what the runtime reloads.
  8. provenance                 -> explicit, deterministic identity and origin tokens.
  9. fail-closed                -> rejected/unresolved/invalid/inactive never activate.
*/
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';

const require=createRequire(import.meta.url);
const H=require('../../site/hero-ranges.js');
const M=require('../../site/hero-range-migration.js');
const R=require('../../site/hero-strategy-resolver.js');

const POP='pokerstars_nlhe_100-200_zoom_play_6max_v1';
const OTHER='legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1';
const SHA_MANIFEST='a'.repeat(64);
const SHA_BINDING='b'.repeat(64);
const SHA_PLAN='c'.repeat(64);
const SHA_REFERENCE='d'.repeat(64);
const CONTEXT={population_id:POP,table_size:6,position:'BTN',effective_stack_bb:100,spot:'UNOPENED'};
const OTHER_CONTEXT={population_id:OTHER,table_size:6,position:'CO',effective_stack_bb:100,spot:'VS_RFI'};
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

function contextFor(populationId){return {...CONTEXT,population_id:populationId};}
function clone(value){return JSON.parse(JSON.stringify(value));}
function memoryStorage(seed={}){
  const map=new Map(Object.entries(seed));
  return {
    getItem:key=>(map.has(key)?map.get(key):null),
    setItem:(key,value)=>{map.set(key,String(value));},
    removeItem:key=>{map.delete(key);},
    entries:()=>map
  };
}

// A complete, admitted, population-bound calculated repository (169 hand classes).
function calculatedRepository({populationId=POP,hands=169,version=GENERATION_VERSION,provenance=LAYER_PROVENANCE}={}){
  const repo=H.emptyRepository({populationId});
  H.setLayerMetadata(repo,contextFor(populationId),'calculated',{version,provenance});
  for(const hand of H.HAND_CLASSES.slice(0,hands)){
    H.setHandStrategy(repo,contextFor(populationId),hand,{actions:{FOLD:1}},{layer:'calculated'});
  }
  return repo;
}

// A repository carrying only a personal override for the active population.
function personalRepository({populationId=POP,context=CONTEXT,hand='AA'}={}){
  const repo=H.emptyRepository({populationId});
  H.setHandStrategy(repo,context,hand,{
    actions:{OPEN:.5,LIMP:.5},
    sizings:{OPEN:[{target_total_bb:2.5,probability:1}]},
    notes:'personal override'
  },{layer:'personal'});
  return repo;
}

// A fully bound admission: role, content hash, candidate/generation identity
// and binding_sha256 all describe the calculated artifact of this population
// (#task-fnc). A bare ADMISSIBLE status token never activates a local repository.
const ADMISSIBLE={hero_strategy:{
  status:'ADMISSIBLE',
  role:'hero_strategy',
  population_id:POP,
  candidate_id:'hero-candidate-196',
  generation_id:'gen-196',
  binding_sha256:SHA_BINDING,
  artifact:{
    declared_sha256:SHA_MANIFEST,
    actual_sha256:SHA_MANIFEST,
    hash_kind:'file_sha256',
    source_path:'training/runs/196_hero_candidate/HERO_RANGE_REPOSITORY_PFPC.json',
    verified:true
  },
  provenance:{
    source_population_id:POP,
    manifest_sha256:SHA_MANIFEST,
    binding_sha256:SHA_BINDING,
    candidate_id:'hero-candidate-196',
    generation_id:'gen-196'
  }
}};
function compatibleInput(extra={}){
  return {
    population_id:POP,
    repository:calculatedRepository(),
    admissions:ADMISSIBLE,
    pack_identity:{population_id:POP},
    trainer_manifest:{schema:R.TRAINER_MANIFEST_SCHEMA,population_id:POP},
    ...extra
  };
}

function hasExactCustomLabel(value){
  if(typeof value==='string')return value.trim().toLowerCase()==='custom';
  if(Array.isArray(value))return value.some(hasExactCustomLabel);
  if(value&&typeof value==='object')return Object.values(value).some(hasExactCustomLabel);
  return false;
}
function assertNoCustom(value,message){
  assert.equal(hasExactCustomLabel(value),false,message||'the literal Custom label must never be emitted');
}

const scenarios=[];

// ---------------------------------------------------------------------------
// 1. population compatible: admitted complete calculated strategy.
// ---------------------------------------------------------------------------
scenarios.push(['1. population compatible',()=>{
  const resolved=R.resolveHeroStrategy(compatibleInput());
  assert.equal(resolved.schema,R.SCHEMA);
  assert.equal(resolved.status,R.STATUSES.ADMISSIBLE_CALCULATED);
  assert.equal(resolved.source,R.SOURCES.POPULATION);
  assert.equal(resolved.population_id,POP);
  assert.equal(resolved.fail_closed,false);
  assert.equal(resolved.strategy_id,'hero-candidate-196');
  assert.equal(resolved.strategy_version,GENERATION_VERSION);
  assert.equal(resolved.strategy_sha256,SHA_MANIFEST);
  assert.equal(resolved.provenance.origin,'CALCULATED_POPULATION');
  assert.equal(resolved.provenance.coverage.complete,true);
  assertNoCustom(resolved);

  // The repository itself is population-bound: a compatible context resolves and
  // a foreign one is refused before any strategy is presented.
  const repo=calculatedRepository();
  assert.deepEqual(H.populationBound(repo,CONTEXT),{
    population_id:POP,
    repository_population_id:POP,
    compatible:true
  });
  assert.equal(H.populationBound(repo,contextFor(OTHER)).compatible,false);

  // The shared identity accessor is the single downstream read surface.
  const identity=R.identity(resolved);
  assert.equal(identity.population_id,POP);
  assert.equal(identity.strategy_id,'hero-candidate-196');
  assert.equal(identity.status,R.STATUSES.ADMISSIBLE_CALCULATED);
  assert.equal(identity.source,R.SOURCES.POPULATION);
  assert.equal(identity.fail_closed,false);
}]);

// ---------------------------------------------------------------------------
// 2. population incompatible: fail closed, no identity, no relabel.
// ---------------------------------------------------------------------------
scenarios.push(['2. population incompatible',()=>{
  const repoDefaultsMismatch=R.resolveHeroStrategy({
    population_id:POP,
    repository:H.emptyRepository({populationId:OTHER}),
    admissions:'ADMISSIBLE'
  });
  assert.equal(repoDefaultsMismatch.status,R.STATUSES.POPULATION_INCOMPATIBLE);
  assert.equal(repoDefaultsMismatch.source,R.SOURCES.NONE);
  assert.equal(repoDefaultsMismatch.fail_closed,true);
  assert.equal(repoDefaultsMismatch.strategy_id,null);
  assert.equal(repoDefaultsMismatch.strategy_version,null);
  assert.equal(repoDefaultsMismatch.strategy_sha256,null);
  assert.equal(repoDefaultsMismatch.provenance,null);
  assert.ok(repoDefaultsMismatch.reason_codes.includes('POPULATION_ID_MISMATCH'));
  assert.ok(repoDefaultsMismatch.reason_codes.includes('REPOSITORY_DEFAULTS_POPULATION_MISMATCH'));

  // A materialized calculated context from another population is detected even
  // when the repository defaults look compatible.
  const foreignContext=calculatedRepository({populationId:OTHER});
  const contextMismatch=R.resolveHeroStrategy({population_id:POP,repository:foreignContext,admissions:'ADMISSIBLE'});
  assert.equal(contextMismatch.status,R.STATUSES.POPULATION_INCOMPATIBLE);
  assert.ok(contextMismatch.reason_codes.includes('CALCULATED_CONTEXT_POPULATION_MISMATCH'));

  // A foreign candidate context must not supply the active strategy.
  const candidateMismatch=R.resolveHeroStrategy({
    population_id:POP,
    candidate:{schema:R.CANDIDATE_SCHEMA,population_id:OTHER,version:'candidate-v1',promotion_authorized:false,repository:calculatedRepository()},
    admissions:'ADMISSIBLE'
  });
  assert.equal(candidateMismatch.status,R.STATUSES.POPULATION_INCOMPATIBLE);
  assert.ok(candidateMismatch.reason_codes.includes('CANDIDATE_POPULATION_MISMATCH'));

  // Migration never relabels a foreign population; it is retained verbatim.
  const mixed=H.emptyRepository({populationId:OTHER});
  H.setHandStrategy(mixed,OTHER_CONTEXT,'AKs',{actions:{'3BET':1}},{layer:'personal'});
  const detection=M.detectPopulationIds(mixed,{activePopulationId:POP});
  assert.deepEqual(detection.inherited_population_ids,[OTHER]);
  assert.deepEqual(detection.compatible_population_ids,[]);
  assert.deepEqual(detection.relabeled_population_ids,[]);
  const plan=M.planMigration(mixed,{activePopulationId:POP});
  assert.deepEqual(plan.relabeled_population_ids,[]);
  assert.ok(plan.reason_codes.includes('INHERITED_POPULATION_RETAINED'));
  assert.equal(plan.repository.defaults.population_id,OTHER,'MIXED must never be relabelled to the active Zoom population');

  const identity=R.identity(repoDefaultsMismatch);
  assert.equal(identity.status,R.STATUSES.POPULATION_INCOMPATIBLE);
  assert.equal(identity.source,R.SOURCES.NONE);
  assert.equal(identity.fail_closed,true);
  assertNoCustom(repoDefaultsMismatch);
}]);

// ---------------------------------------------------------------------------
// 3. aucune stratégie: explicit UNAVAILABLE/PARTIAL, never Custom.
// ---------------------------------------------------------------------------
scenarios.push(['3. aucune stratégie',()=>{
  const noAdmission=R.resolveHeroStrategy({population_id:POP,repository:H.emptyRepository({populationId:POP})});
  assert.equal(noAdmission.status,R.STATUSES.UNAVAILABLE);
  assert.equal(noAdmission.source,R.SOURCES.NONE);
  assert.equal(noAdmission.fail_closed,true);
  assert.equal(noAdmission.strategy_id,null);
  assert.ok(noAdmission.reason_codes.includes('NO_ADMISSIBLE_STRATEGY'));
  assertNoCustom(noAdmission);

  // An admission over an empty repository still cannot invent a strategy.
  const admittedEmpty=R.resolveHeroStrategy({population_id:POP,repository:H.emptyRepository({populationId:POP}),admissions:'ADMISSIBLE'});
  assert.equal(admittedEmpty.status,R.STATUSES.UNAVAILABLE);
  assert.equal(admittedEmpty.strategy_id,null);

  // An admitted but incomplete calculated layer is PARTIAL, never admissible.
  const partial=R.resolveHeroStrategy({population_id:POP,repository:calculatedRepository({hands:12}),admissions:ADMISSIBLE});
  assert.equal(partial.status,R.STATUSES.PARTIAL);
  assert.equal(partial.source,R.SOURCES.POPULATION);
  assert.equal(partial.fail_closed,true);
  assert.ok(partial.reason_codes.includes('STRATEGY_PARTIAL_COVERAGE'));
  assertNoCustom(partial);

  // The identity accessor exposes the unavailable state without a fallback label.
  const identity=R.identity(noAdmission);
  assert.equal(identity.strategy_id,null);
  assert.notEqual(String(identity.strategy_id).toLowerCase(),'custom');
  assert.equal(identity.fail_closed,true);
}]);

// ---------------------------------------------------------------------------
// 4. override personnel: distinct from the population strategy.
// ---------------------------------------------------------------------------
scenarios.push(['4. override personnel',()=>{
  const personal=personalRepository();
  const resolved=R.resolveHeroStrategy({population_id:POP,repository:personal});
  assert.equal(resolved.status,R.STATUSES.PARTIAL);
  assert.equal(resolved.source,R.SOURCES.PERSONAL_OVERRIDE);
  assert.notEqual(resolved.source,R.SOURCES.POPULATION,'a personal override must never become the population source');
  assert.equal(resolved.fail_closed,true);
  assert.equal(resolved.strategy_id,null);
  assert.equal(resolved.provenance.origin,'PERSONAL_OVERRIDE');
  assert.ok(resolved.reason_codes.includes('PERSONAL_OVERRIDE_NOT_POPULATION_STRATEGY'));

  // A layered override coexists with the population strategy but does not replace it.
  const layered=calculatedRepository();
  H.setHandStrategy(layered,CONTEXT,'AA',{actions:{LIMP:1}},{layer:'personal'});
  const layeredResolution=R.resolveHeroStrategy({population_id:POP,repository:layered,admissions:ADMISSIBLE});
  assert.equal(layeredResolution.status,R.STATUSES.ADMISSIBLE_CALCULATED);
  assert.equal(layeredResolution.source,R.SOURCES.POPULATION,'the override must not become the population source');

  // The migration surface extracts the override with explicit provenance and
  // keeps the override source distinct from POPULATION.
  const override=M.extractPersonalOverride(personal,CONTEXT,{activePopulationId:POP});
  assert.ok(override);
  assert.equal(override.schema,M.OVERRIDE_SCHEMA);
  assert.equal(override.source,M.SOURCES.PERSONAL_OVERRIDE);
  assert.notEqual(override.source,M.SOURCES.POPULATION);
  assert.equal(override.population_id,POP);
  assert.equal(override.population_match,true);
  assert.equal(override.inherited,false);
  assert.equal(override.provenance.origin,M.SOURCES.PERSONAL_OVERRIDE);
  assert.equal(override.provenance.context_key,H.contextKey(CONTEXT));

  // A foreign override is retained with its own identity and can be filtered out
  // (never relabelled to the active population).
  const mixed=H.emptyRepository({populationId:OTHER});
  H.setHandStrategy(mixed,OTHER_CONTEXT,'AKs',{actions:{'3BET':1}},{layer:'personal'});
  const foreign=M.extractPersonalOverride(mixed,OTHER_CONTEXT,{activePopulationId:POP});
  assert.equal(foreign.population_id,OTHER);
  assert.equal(foreign.inherited,true);
  assert.equal(foreign.provenance.population_match,false);
  assert.equal(M.extractPersonalOverride(mixed,OTHER_CONTEXT,{activePopulationId:POP,requireCompatible:true}),null);
  assertNoCustom(resolved);
}]);

// ---------------------------------------------------------------------------
// 5. changement de pack: pack/manifest binding enforced at resolution.
// ---------------------------------------------------------------------------
scenarios.push(['5. changement de pack',()=>{
  const before=R.resolveHeroStrategy(compatibleInput());
  assert.equal(before.status,R.STATUSES.ADMISSIBLE_CALCULATED);
  assert.equal(before.strategy_id,'hero-candidate-196');

  // Swapping in a pack from another population fails closed with a precise code.
  const packChanged=R.resolveHeroStrategy(compatibleInput({pack_identity:{population_id:OTHER}}));
  assert.equal(packChanged.status,R.STATUSES.POPULATION_INCOMPATIBLE);
  assert.ok(packChanged.reason_codes.includes('PACK_IDENTITY_POPULATION_MISMATCH'));
  assert.equal(packChanged.strategy_id,null);
  assertNoCustom(packChanged);

  const manifestChanged=R.resolveHeroStrategy(compatibleInput({
    trainer_manifest:{schema:R.TRAINER_MANIFEST_SCHEMA,population_id:OTHER}
  }));
  assert.equal(manifestChanged.status,R.STATUSES.POPULATION_INCOMPATIBLE);
  assert.ok(manifestChanged.reason_codes.includes('TRAINER_MANIFEST_POPULATION_MISMATCH'));

  // A pack identity may also be nested under an `entry` descriptor.
  const nestedPack=R.resolveHeroStrategy(compatibleInput({pack_identity:{entry:{population_id:OTHER}}}));
  assert.equal(nestedPack.status,R.STATUSES.POPULATION_INCOMPATIBLE);
  assert.ok(nestedPack.reason_codes.includes('PACK_IDENTITY_POPULATION_MISMATCH'));

  // Restoring a compatible pack yields the exact same identity again.
  const restored=R.resolveHeroStrategy(compatibleInput());
  assert.deepEqual(restored,before);
  assert.equal(restored.strategy_sha256,SHA_MANIFEST);
}]);

// ---------------------------------------------------------------------------
// 6. rollback: exact pre-migration bytes restored, previous copy retained.
// ---------------------------------------------------------------------------
scenarios.push(['6. rollback',()=>{
  const original=personalRepository();
  const originalRaw=JSON.stringify(original);
  const storage=memoryStorage({[M.STORAGE_KEY]:originalRaw});

  const migrated=M.migrateStorage(storage,{activePopulationId:POP,migratedAt:'2026-09-21T00:00:00.000Z'});
  assert.equal(migrated.status,M.STATUSES.MIGRATED);
  assert.equal(migrated.rollback_available,true);
  assert.equal(storage.getItem(M.PREVIOUS_STORAGE_KEY),originalRaw,'rollback copy must be the exact pre-migration payload');
  const migratedResolution=R.resolveHeroStrategy({population_id:POP,repository:M.loadRepository(storage)});
  assert.equal(migratedResolution.status,R.STATUSES.PARTIAL);
  assert.equal(migratedResolution.source,R.SOURCES.PERSONAL_OVERRIDE);

  const rolled=M.rollbackStorage(storage);
  assert.equal(rolled.status,M.STATUSES.ROLLED_BACK);
  assert.equal(storage.getItem(M.STORAGE_KEY),originalRaw,'rollback must restore the original bytes');
  assert.equal(storage.getItem(M.PREVIOUS_STORAGE_KEY),originalRaw,'previous copy must be retained after rollback');
  const restored=M.loadRepository(storage);
  assert.deepEqual(restored,original);
  assert.equal(M.isMigrated(restored),false);

  // The post-rollback runtime resolution is the pre-migration one again.
  const postRollback=R.resolveHeroStrategy({population_id:POP,repository:restored});
  assert.equal(postRollback.status,R.STATUSES.PARTIAL);
  assert.equal(postRollback.source,R.SOURCES.PERSONAL_OVERRIDE);
  assert.deepEqual(postRollback,preMigrationResolution(original));

  // A rollback without a previous copy is explicit, never silent.
  assert.equal(M.rollbackStorage(memoryStorage()).status,M.STATUSES.ROLLBACK_UNAVAILABLE);
}]);

function preMigrationResolution(repository){
  return R.resolveHeroStrategy({population_id:POP,repository});
}

// ---------------------------------------------------------------------------
// 7. persistence: the migrated repository is what the runtime reloads.
// ---------------------------------------------------------------------------
scenarios.push(['7. persistence',()=>{
  const seeded=calculatedRepository();
  H.setHandStrategy(seeded,CONTEXT,'AA',{actions:{OPEN:.5,LIMP:.5}},{layer:'personal'});
  const originalRaw=JSON.stringify(seeded);
  const storage=memoryStorage({[M.STORAGE_KEY]:originalRaw});

  const first=M.migrateStorage(storage,{activePopulationId:POP,migratedAt:'2026-09-21T00:00:00.000Z'});
  assert.equal(first.status,M.STATUSES.MIGRATED);
  const activeBytes=storage.getItem(M.STORAGE_KEY);
  const persisted=M.loadRepository(storage);
  assert.deepEqual(persisted,JSON.parse(activeBytes));
  assert.equal(H.validateRepository(persisted),true,'the persisted migrated repository must stay schema-valid');
  assert.equal(M.isMigrated(persisted),true);

  // The runtime resolves the persisted repository (admission + complete calculated).
  const resolved=R.resolveHeroStrategy({population_id:POP,repository:persisted,admissions:ADMISSIBLE});
  assert.equal(resolved.status,R.STATUSES.ADMISSIBLE_CALCULATED);
  assert.equal(resolved.source,R.SOURCES.POPULATION);
  const override=M.extractPersonalOverride(persisted,CONTEXT,{activePopulationId:POP});
  assert.ok(override,'the personal override must survive migration');
  assert.equal(override.hands.AA.actions.OPEN,.5);

  // Idempotence: a second migration is a byte-identical no-op.
  const second=M.migrateStorage(storage,{activePopulationId:POP,migratedAt:'2099-01-01T00:00:00.000Z'});
  assert.equal(second.status,M.STATUSES.UNCHANGED);
  assert.ok(second.reason_codes.includes('ALREADY_MIGRATED'));
  assert.equal(storage.getItem(M.STORAGE_KEY),activeBytes,'the second migration must not change the stored bytes');

  // Explicit persist/load round-trip is byte-stable.
  M.persistRepository(storage,persisted);
  assert.deepEqual(M.loadRepository(storage),persisted);
}]);

// ---------------------------------------------------------------------------
// 8. provenance: explicit, deterministic identity and origin tokens.
// ---------------------------------------------------------------------------
scenarios.push(['8. provenance',()=>{
  const resolved=R.resolveHeroStrategy(compatibleInput());
  assert.equal(resolved.provenance.origin,'CALCULATED_POPULATION');
  assert.equal(resolved.provenance.population_id,POP);
  assert.equal(resolved.provenance.admission_status,'ADMISSIBLE');
  assert.equal(resolved.provenance.candidate_id,'hero-candidate-196');
  assert.equal(resolved.provenance.generation_id,'gen-196');
  assert.equal(resolved.provenance.layer_schema,R.IMPORT_SCHEMA);
  assert.equal(resolved.provenance.activation_state,'ACTIVE_MEASURED');
  assert.equal(resolved.provenance.manifest_sha256,SHA_MANIFEST);
  assert.equal(resolved.provenance.binding_sha256,SHA_BINDING);
  assert.equal(resolved.provenance.source_plan_sha256,SHA_PLAN);
  assert.deepEqual(resolved.provenance.coverage,{contexts:1,defined_hand_classes:169,complete:true});
  assert.deepEqual(resolved.provenance.context_keys,[H.contextKey(CONTEXT)]);

  // Determinism: identical input -> byte-identical output, sorted unique reasons.
  const again=R.resolveHeroStrategy(compatibleInput());
  assert.deepEqual(resolved,again);
  assert.equal(JSON.stringify(resolved),JSON.stringify(again));
  assert.deepEqual(resolved.reason_codes,[...resolved.reason_codes].sort());
  assert.equal(new Set(resolved.reason_codes).size,resolved.reason_codes.length);

  // Migration provenance is explicit about population compatibility.
  const override=M.extractPersonalOverride(personalRepository(),CONTEXT,{activePopulationId:POP});
  assert.equal(override.provenance.origin,M.SOURCES.PERSONAL_OVERRIDE);
  assert.equal(override.provenance.repository_schema,H.SCHEMA);
  assert.equal(override.provenance.repository_version,1);
  assert.equal(override.provenance.population_match,true);
  assert.equal(override.provenance.inherited,false);

  // An inactive #358 candidate metadata is never auto-activated.
  const inactive=H.emptyRepository({populationId:POP});
  H.setLayerMetadata(inactive,CONTEXT,'calculated',{
    version:'gen-358-inactive',
    provenance:{schema:R.IMPORT_SCHEMA,activation_state:'INACTIVE_CANDIDATE_METADATA_ONLY',candidate_id:'candidate-358'}
  });
  const inactiveResolution=R.resolveHeroStrategy({population_id:POP,repository:inactive,admissions:'ADMISSIBLE'});
  assert.equal(inactiveResolution.status,R.STATUSES.UNAVAILABLE);
  assert.notEqual(inactiveResolution.status,R.STATUSES.ADMISSIBLE_CALCULATED);
  assert.equal(inactiveResolution.strategy_id,null);
  assert.ok(inactiveResolution.reason_codes.includes('INACTIVE_CANDIDATE_NOT_ACTIVATED'));
  assertNoCustom(inactiveResolution);
}]);

// ---------------------------------------------------------------------------
// 9. fail-closed: rejected/unresolved/invalid/inactive never activate.
// ---------------------------------------------------------------------------
scenarios.push(['9. fail-closed',()=>{
  const rejected=R.resolveHeroStrategy({population_id:POP,repository:calculatedRepository(),admissions:'REJECTED'});
  assert.equal(rejected.status,R.STATUSES.UNAVAILABLE);
  assert.equal(rejected.fail_closed,true);
  assert.ok(rejected.reason_codes.includes('STRATEGY_REJECTED'));

  const unresolved=R.resolveHeroStrategy({population_id:POP,repository:calculatedRepository(),admissions:'UNRESOLVED'});
  assert.equal(unresolved.status,R.STATUSES.UNAVAILABLE);
  assert.ok(unresolved.reason_codes.includes('STRATEGY_UNRESOLVED'));

  const incompatible=R.resolveHeroStrategy({population_id:POP,repository:calculatedRepository(),admissions:'INCOMPATIBLE'});
  assert.equal(incompatible.status,R.STATUSES.POPULATION_INCOMPATIBLE);
  assert.equal(incompatible.fail_closed,true);
  assert.ok(incompatible.reason_codes.includes('ADMISSION_INCOMPATIBLE'));

  // A malformed repository fails closed even when an admission claims ADMISSIBLE.
  const malformed=calculatedRepository();
  malformed.schema='not-the-hero-repository-schema';
  const malformedResolution=R.resolveHeroStrategy({population_id:POP,repository:malformed,admissions:'ADMISSIBLE'});
  assert.equal(malformedResolution.status,R.STATUSES.UNAVAILABLE);
  assert.ok(malformedResolution.reason_codes.includes('REPOSITORY_INVALID'));
  assert.equal(malformedResolution.strategy_id,null);

  // Missing active population always fails closed.
  const missingPopulation=R.resolveHeroStrategy({repository:calculatedRepository(),admissions:'ADMISSIBLE'});
  assert.equal(missingPopulation.status,R.STATUSES.POPULATION_INCOMPATIBLE);
  assert.equal(missingPopulation.population_id,null);
  assert.ok(missingPopulation.reason_codes.includes('POPULATION_ID_MISSING'));

  // RETAIN_REFERENCE without an explicit reference identity stays explicit
  // (null identity) rather than falling back to Custom.
  const retainedNoIdentity=R.resolveHeroStrategy({
    population_id:POP,
    repository:H.emptyRepository({populationId:POP}),
    admissions:{hero_strategy:{status:'RETAIN_REFERENCE',population_id:POP}}
  });
  assert.equal(retainedNoIdentity.status,R.STATUSES.RETAIN_REFERENCE);
  assert.notEqual(retainedNoIdentity.status,R.STATUSES.ADMISSIBLE_CALCULATED);
  assert.equal(retainedNoIdentity.strategy_id,null);
  assert.ok(retainedNoIdentity.reason_codes.includes('RETAINED_REFERENCE_IDENTITY_MISSING'));
  assertNoCustom(retainedNoIdentity);

  // A retained reference is a population-bound provenance entry, never an
  // alternative population identity.
  const retained=R.resolveHeroStrategy({
    population_id:POP,
    repository:H.emptyRepository({populationId:POP}),
    admissions:{hero_strategy:{status:'RETAIN_REFERENCE',population_id:POP}},
    retained_reference:{schema:'issue-108-retained-reference',issue:108,population_id:POP,strategy_id:'retained-model-a-v5',strategy_version:'2026-09-19.1',strategy_sha256:SHA_REFERENCE}
  });
  assert.equal(retained.status,R.STATUSES.RETAIN_REFERENCE);
  assert.equal(retained.source,R.SOURCES.POPULATION);
  assert.equal(retained.strategy_id,'retained-model-a-v5');
  assert.equal(retained.provenance.reference_issue,'108');
  assertNoCustom(retained);

  // A candidate that tries to self-promote is rejected, never activated.
  const selfPromoted=R.resolveHeroStrategy({
    population_id:POP,
    candidate:{schema:R.CANDIDATE_SCHEMA,population_id:POP,version:'candidate-v1',promotion_authorized:true,repository:calculatedRepository()},
    admissions:'ADMISSIBLE'
  });
  assert.notEqual(selfPromoted.status,R.STATUSES.ADMISSIBLE_CALCULATED);
  assert.equal(selfPromoted.fail_closed,true);
  assert.ok(selfPromoted.reason_codes.includes('CANDIDATE_PROMOTION_FORBIDDEN'));

  // The literal Custom token is scrubbed from any attempted identity.
  const customAttempt=R.resolveHeroStrategy(compatibleInput({strategy_id:'Custom'}));
  assert.notEqual(String(customAttempt.strategy_id).toLowerCase(),'custom');
  assert.equal(customAttempt.strategy_id,'hero-candidate-196');
  assert.ok(customAttempt.reason_codes.includes('CUSTOM_LABEL_REJECTED'));
  assertNoCustom(customAttempt);
}]);

for(const [name,run] of scenarios){
  try{
    run();
  }catch(error){
    console.error(`population-bound Hero strategy scenario failed: ${name}`);
    throw error;
  }
  console.log(`  ok - ${name}`);
}

console.log(`Population-bound Hero strategy E2E contract: PASS (${scenarios.length} scenarios)`);
