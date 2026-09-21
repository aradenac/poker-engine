#!/usr/bin/env node
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const H=require('../../site/hero-ranges.js');
const M=require('../../site/hero-range-migration.js');
const R=require('../../site/hero-strategy-resolver.js');

const ZOOM='pokerstars_nlhe_100-200_zoom_play_6max_v1';
const MIXED='legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1';
const CONTEXT={population_id:ZOOM,table_size:6,position:'BTN',effective_stack_bb:100,spot:'UNOPENED'};
const MIXED_CONTEXT={population_id:MIXED,table_size:6,position:'CO',effective_stack_bb:100,spot:'VS_RFI'};

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

function legacySource(name='Custom'){
  return {folder:{name,folders:[],ranges:[{name:'BTN',positions:[{position:'BTN',hands:[{hand:'AA',actions:[{name:'OPEN',frequency:100}]}]}]}]}};
}

function personalRepository(){
  const source=legacySource('Repository source');
  const repo=H.emptyRepository({populationId:ZOOM});
  repo.source={format:'range-folder',preserved_verbatim:true,meta:{origin:'fixture'},range_folder:source};
  H.setLayerMetadata(repo,CONTEXT,'personal',{version:'personal-v1',provenance:{schema:'poker-hero-preflop-repository-import/v1',import:'fixture'}});
  H.setHandStrategy(repo,CONTEXT,'AA',{
    actions:{OPEN:.5,LIMP:.5},
    sizings:{OPEN:[{target_total_bb:2.5,probability:1}]},
    notes:'personal override'
  },{layer:'personal'});
  return {repo,source};
}

// --- contract surface -------------------------------------------------------
assert.equal(M.SCHEMA,'poker-hero-range-migration/v1');
assert.equal(M.OVERRIDE_SCHEMA,'poker-hero-personal-override/v1');
assert.equal(M.REPOSITORY_SCHEMA,H.SCHEMA);
assert.equal(M.STORAGE_KEY,'poker.hero.range.repository.v1');
assert.equal(M.PREVIOUS_STORAGE_KEY,'poker.hero.range.repository.v1.previous');
assert.deepEqual(Object.values(M.SOURCES).sort(),['NONE','PERSONAL_OVERRIDE','POPULATION']);
assert.equal(M.SOURCES.POPULATION,'POPULATION');
assert.equal(M.SOURCES.PERSONAL_OVERRIDE,'PERSONAL_OVERRIDE');
assert.equal(M.STATUSES.MIGRATED,'MIGRATED');
assert.equal(M.STATUSES.UNCHANGED,'UNCHANGED');
assert.equal(M.STATUSES.ROLLED_BACK,'ROLLED_BACK');

// --- personal override extraction carries contextual provenance -------------
const {repo,source}=personalRepository();
const override=M.extractPersonalOverride(repo,CONTEXT,{activePopulationId:ZOOM});
assert.ok(override,'personal override must be extractable from the personal layer');
assert.equal(override.schema,M.OVERRIDE_SCHEMA);
assert.equal(override.source,M.SOURCES.PERSONAL_OVERRIDE);
assert.notEqual(override.source,M.SOURCES.POPULATION,'override must never be returned as the population source');
assert.equal(override.population_id,ZOOM);
assert.equal(override.context_key,H.contextKey(CONTEXT));
assert.equal(override.repository_schema,H.SCHEMA);
assert.equal(override.repository_version,1);
assert.equal(override.layer,'personal');
assert.equal(override.layer_version,'personal-v1');
assert.equal(override.active_population_id,ZOOM);
assert.equal(override.population_match,true);
assert.equal(override.inherited,false);
assert.equal(override.hand_count,1);
assert.equal(override.combo_slots,6);
assert.deepEqual(Object.keys(override.hands),['AA']);
assert.equal(override.provenance.origin,M.SOURCES.PERSONAL_OVERRIDE);
assert.equal(override.provenance.source,M.SOURCES.PERSONAL_OVERRIDE);
assert.equal(override.provenance.layer,'personal');
assert.equal(override.provenance.population_id,ZOOM);
assert.equal(override.provenance.context_key,H.contextKey(CONTEXT));
assert.equal(override.provenance.repository_schema,H.SCHEMA);
assert.equal(override.provenance.repository_version,1);
assert.equal(override.provenance.layer_version,'personal-v1');
assert.equal(override.provenance.active_population_id,ZOOM);
assert.equal(override.provenance.population_match,true);
assert.equal(override.provenance.inherited,false);

// A context without a personal layer does not invent an override.
assert.equal(M.extractPersonalOverride(H.emptyRepository({populationId:ZOOM}),CONTEXT,{activePopulationId:ZOOM}),null);
const list=M.extractPersonalOverrides(repo,{activePopulationId:ZOOM});
assert.equal(list.length,1);
assert.equal(list[0].context_key,H.contextKey(CONTEXT));

// The extracted override stays distinct from the population strategy even when
// handed to the population resolver contract.
const personalOnly=H.emptyRepository({populationId:ZOOM});
H.setHandStrategy(personalOnly,CONTEXT,'AA',{actions:{OPEN:1}},{layer:'personal'});
const personalResolution=R.resolveHeroStrategy({population_id:ZOOM,repository:personalOnly});
assert.equal(personalResolution.status,R.STATUSES.PARTIAL);
assert.equal(personalResolution.source,R.SOURCES.PERSONAL_OVERRIDE);
assert.equal(M.extractPersonalOverride(personalOnly,CONTEXT,{activePopulationId:ZOOM}).source,M.SOURCES.PERSONAL_OVERRIDE);

// --- contextual personal-override status: available vs active ----------------
// `available` reports the population-wide presence of an override; `active` is
// only true when an override is resolved on the exact current context. The
// status is always sourced from PERSONAL_OVERRIDE, never POPULATION.
const OVERRIDE_CONTEXT={population_id:ZOOM,table_size:6,position:'CO',effective_stack_bb:100,spot:'VS_RFI'};
const OTHER_CONTEXT={population_id:ZOOM,table_size:6,position:'SB',effective_stack_bb:100,spot:'VS_RFI'};
const multi=H.emptyRepository({populationId:ZOOM});
H.setHandStrategy(multi,CONTEXT,'AA',{actions:{OPEN:1}},{layer:'personal'});
H.setHandStrategy(multi,OVERRIDE_CONTEXT,'AKs',{actions:{'3BET':1}},{layer:'personal'});

assert.equal(M.OVERRIDE_STATUS_SCHEMA,'poker-hero-personal-override-status/v1');

// Override present elsewhere in the population but not on the current context.
const elsewhere=M.personalOverrideStatus(multi,{populationId:ZOOM,activePopulationId:ZOOM,context:OTHER_CONTEXT});
assert.equal(elsewhere.schema,M.OVERRIDE_STATUS_SCHEMA);
assert.equal(elsewhere.source,M.SOURCES.PERSONAL_OVERRIDE);
assert.notEqual(elsewhere.source,M.SOURCES.POPULATION,'an override is never reported as the population source');
assert.equal(elsewhere.population_id,ZOOM);
assert.equal(elsewhere.available,true,'an override elsewhere in the population keeps `available` true');
assert.equal(elsewhere.active,false,'an override on another context is not active here');
assert.equal(elsewhere.active_context_key,H.contextKey(OTHER_CONTEXT));
assert.deepEqual(elsewhere.context_keys,[H.contextKey(CONTEXT),H.contextKey(OVERRIDE_CONTEXT)].sort());
assert.equal(elsewhere.count,2);

// Override on the exact current context: both available and active.
const onContext=M.personalOverrideStatus(multi,{populationId:ZOOM,activePopulationId:ZOOM,context:CONTEXT});
assert.equal(onContext.available,true);
assert.equal(onContext.active,true);
assert.equal(onContext.active_context_key,H.contextKey(CONTEXT));
assert.equal(onContext.count,2);

// An unresolvable context is a fail-safe inactive state; available stays true.
const unresolvable=M.personalOverrideStatus(multi,{populationId:ZOOM,activePopulationId:ZOOM,context:{population_id:ZOOM,table_size:6,position:'BTN',effective_stack_bb:100,spot:'NOT_A_SPOT'}});
assert.equal(unresolvable.available,true);
assert.equal(unresolvable.active,false);
assert.equal(unresolvable.active_context_key,null);

// A missing context never activates an override either.
const noContext=M.personalOverrideStatus(multi,{populationId:ZOOM,activePopulationId:ZOOM});
assert.equal(noContext.available,true);
assert.equal(noContext.active,false);
assert.equal(noContext.active_context_key,null);

// Without a resolved population, the reusable helper fails closed instead of
// aggregating overrides belonging to unrelated populations.
const noPopulation=M.personalOverrideStatus(multi,{context:CONTEXT});
assert.equal(noPopulation.population_id,null);
assert.equal(noPopulation.available,false);
assert.equal(noPopulation.active,false);
assert.equal(noPopulation.active_context_key,null);
assert.deepEqual(noPopulation.context_keys,[]);
assert.equal(noPopulation.count,0);

// Exact preflop identifiers participate in HeroRanges.contextKey and must be
// preserved when resolving whether the current override is active.
const PREFLOP_CONTEXT_ID='PFC_0123456789abcdef';
const exactContext={...CONTEXT,preflop_context_id:PREFLOP_CONTEXT_ID};
const exactRepo=H.emptyRepository({populationId:ZOOM});
H.setHandStrategy(exactRepo,exactContext,'AA',{actions:{OPEN:1}},{layer:'personal'});
const exactStatus=M.personalOverrideStatus(exactRepo,{populationId:ZOOM,context:exactContext});
assert.equal(exactStatus.available,true);
assert.equal(exactStatus.active,true);
assert.equal(exactStatus.active_context_key,H.contextKey(exactContext));
const legacyContextStatus=M.personalOverrideStatus(exactRepo,{populationId:ZOOM,context:CONTEXT});
assert.equal(legacyContextStatus.available,true);
assert.equal(legacyContextStatus.active,false,'the legacy key must not activate an exact preflop-context override');

// A foreign-population override is not part of the active population.
const foreignRepo=H.emptyRepository({populationId:MIXED});
H.setHandStrategy(foreignRepo,MIXED_CONTEXT,'AKs',{actions:{'3BET':1}},{layer:'personal'});
const foreignStatus=M.personalOverrideStatus(foreignRepo,{populationId:ZOOM,activePopulationId:ZOOM,context:CONTEXT});
assert.equal(foreignStatus.available,false,'a foreign override is not available in the active population');
assert.equal(foreignStatus.active,false);
assert.equal(foreignStatus.count,0);

// An empty / missing repository never invents an override.
const emptyStatus=M.personalOverrideStatus(H.emptyRepository({populationId:ZOOM}),{populationId:ZOOM,context:CONTEXT});
assert.equal(emptyStatus.available,false);
assert.equal(emptyStatus.active,false);
assert.equal(emptyStatus.count,0);

// --- migration is additive, idempotent, persistent and reversible -----------
const original=clone(repo);
const originalRaw=JSON.stringify(original);
const storage=memoryStorage({[M.STORAGE_KEY]:originalRaw});
const first=M.migrateStorage(storage,{activePopulationId:ZOOM,migratedAt:'2026-09-21T00:00:00.000Z'});
assert.equal(first.status,M.STATUSES.MIGRATED);
assert.equal(first.migrated,true);
assert.equal(first.idempotent,true);
assert.equal(first.rollback_available,true);
assert.deepEqual(first.relabeled_population_ids,[]);
assert.deepEqual(first.source_verbatim,original,'the pre-migration repository must be kept verbatim in the plan');
assert.deepEqual(first.source_verbatim.source.range_folder,source);
assert.equal(storage.getItem(M.PREVIOUS_STORAGE_KEY),originalRaw,'the rollback copy must be the exact pre-migration payload');

const firstActive=storage.getItem(M.STORAGE_KEY);
const firstJson=JSON.parse(firstActive);
assert.deepEqual(H.validateRepository(firstJson),true,'migrated repository must stay schema-valid');
assert.ok(firstJson.migration&&firstJson.migration.schema===M.SCHEMA);
assert.equal(firstJson.migration.status,M.STATUSES.MIGRATED);
assert.equal(firstJson.migration.active_population_id,ZOOM);
assert.equal(firstJson.migration.previous_storage_key,M.PREVIOUS_STORAGE_KEY);
assert.equal(firstJson.migration.idempotent,true);
assert.deepEqual(firstJson.migration.relabeled_population_ids,[]);
assert.equal(firstJson.source.preserved_verbatim,true);
assert.deepEqual(firstJson.source.range_folder,source,'verbatim range source must survive migration byte-for-byte');
assert.ok(M.isMigrated(firstJson));
assert.equal(M.isMigrated(original),false);
const activeOverride=firstJson.migration.overrides.find(o=>o.context_key===H.contextKey(CONTEXT));
assert.ok(activeOverride);
assert.equal(activeOverride.source,M.SOURCES.PERSONAL_OVERRIDE);
assert.equal(activeOverride.population_id,ZOOM);
assert.equal(activeOverride.inherited,false);
assert.equal(activeOverride.repository_version,1);

// Persistence: the migrated repository is what the runtime reloads.
assert.deepEqual(M.loadRepository(storage),firstJson);

// Idempotence: a second migration is a byte-identical no-op and never
// re-snapshots the rollback copy.
const second=M.migrateStorage(storage,{activePopulationId:ZOOM,migratedAt:'2099-01-01T00:00:00.000Z'});
assert.equal(second.status,M.STATUSES.UNCHANGED);
assert.ok(second.reason_codes.includes('ALREADY_MIGRATED'));
assert.equal(storage.getItem(M.STORAGE_KEY),firstActive,'the second migration must not change the stored bytes');
assert.equal(storage.getItem(M.PREVIOUS_STORAGE_KEY),originalRaw,'previous copy must not be re-snapshotted');

// Pure planner idempotence.
const pureA=M.migrateRepository(original,{activePopulationId:ZOOM,migratedAt:'2026-09-21T00:00:00.000Z'});
const pureB=M.migrateRepository(pureA.repository,{activePopulationId:ZOOM});
assert.equal(pureB.status,M.STATUSES.UNCHANGED);
assert.equal(JSON.stringify(pureB.repository),JSON.stringify(pureA.repository));

// Rollback restores the exact pre-migration payload and keeps the previous copy.
const rolled=M.rollbackStorage(storage);
assert.equal(rolled.status,M.STATUSES.ROLLED_BACK);
assert.equal(storage.getItem(M.STORAGE_KEY),originalRaw,'rollback must restore the original bytes');
assert.equal(storage.getItem(M.PREVIOUS_STORAGE_KEY),originalRaw,'previous copy must be retained after rollback');
assert.deepEqual(M.loadRepository(storage),original);
assert.deepEqual(M.rollbackStorage(memoryStorage()).status,M.STATUSES.ROLLBACK_UNAVAILABLE);

// Re-migrating after a rollback reproduces the same repository bytes.
const third=M.migrateStorage(storage,{activePopulationId:ZOOM,migratedAt:'2026-09-21T00:00:00.000Z'});
assert.equal(third.status,M.STATUSES.MIGRATED);
assert.equal(storage.getItem(M.STORAGE_KEY),firstActive,'re-migration must be deterministic');

// Empty and invalid storage never invent a migrated repository.
assert.equal(M.migrateStorage(memoryStorage(),{activePopulationId:ZOOM}).status,M.STATUSES.EMPTY);
const corrupt=memoryStorage({[M.STORAGE_KEY]:'{not json'});
assert.equal(M.migrateStorage(corrupt,{activePopulationId:ZOOM}).status,M.STATUSES.UNAVAILABLE);

// --- a foreign population is never relabelled to the active one --------------
const mixedRepo=H.emptyRepository({populationId:MIXED});
H.setHandStrategy(mixedRepo,MIXED_CONTEXT,'AKs',{
  actions:{'3BET':1},
  sizings:{'3BET':[{target_total_bb:9,probability:1}]},
  notes:'mixed fixture'
},{layer:'personal'});
const mixedKey=H.contextKey(MIXED_CONTEXT);

const detection=M.detectPopulationIds(mixedRepo,{activePopulationId:ZOOM});
assert.deepEqual(detection.inherited_population_ids,[MIXED]);
assert.deepEqual(detection.compatible_population_ids,[]);
assert.deepEqual(detection.relabeled_population_ids,[]);

const mixedPlan=M.planMigration(mixedRepo,{activePopulationId:ZOOM});
assert.equal(mixedPlan.status,M.STATUSES.MIGRATED);
assert.deepEqual(mixedPlan.inherited_population_ids,[MIXED]);
assert.deepEqual(mixedPlan.compatible_population_ids,[]);
assert.deepEqual(mixedPlan.relabeled_population_ids,[]);
assert.ok(mixedPlan.reason_codes.includes('INHERITED_POPULATION_RETAINED'));
assert.equal(mixedPlan.repository.defaults.population_id,MIXED,'repository defaults must not be relabelled');
assert.ok(mixedPlan.repository.contexts[mixedKey],'foreign context key must be preserved verbatim');
assert.equal(mixedPlan.repository.contexts[mixedKey].context.population_id,MIXED);
assert.equal(mixedPlan.repository.contexts[mixedKey].layers.personal.hands.AKs.actions['3BET'],1);
assert.equal(Object.values(mixedPlan.repository.contexts).filter(node=>node.context.population_id===ZOOM).length,0,'no Zoom context may be fabricated from a Mixed override');
assert.deepEqual(mixedPlan.repository.migration.inherited_population_ids,[MIXED]);
assert.deepEqual(mixedPlan.repository.migration.relabeled_population_ids,[]);

const mixedOverride=mixedPlan.overrides.find(o=>o.context_key===mixedKey);
assert.ok(mixedOverride);
assert.equal(mixedOverride.population_id,MIXED);
assert.equal(mixedOverride.population_match,false);
assert.equal(mixedOverride.inherited,true);
assert.equal(mixedOverride.source,M.SOURCES.PERSONAL_OVERRIDE);
assert.notEqual(mixedOverride.source,M.SOURCES.POPULATION);

// Extraction keeps the foreign identity and can be required to fail closed.
const extractedMixed=M.extractPersonalOverride(mixedPlan.repository,MIXED_CONTEXT,{activePopulationId:ZOOM});
assert.ok(extractedMixed);
assert.equal(extractedMixed.population_id,MIXED);
assert.equal(extractedMixed.inherited,true);
assert.equal(extractedMixed.provenance.population_id,MIXED);
assert.equal(extractedMixed.provenance.population_match,false);
assert.equal(extractedMixed.source,M.SOURCES.PERSONAL_OVERRIDE);
assert.equal(M.extractPersonalOverride(mixedPlan.repository,MIXED_CONTEXT,{activePopulationId:ZOOM,requireCompatible:true}),null,'an incompatible override is filtered, never relabelled');

// A repository that carries both populations keeps both, side by side.
const combined=H.emptyRepository({populationId:ZOOM});
H.setHandStrategy(combined,CONTEXT,'AA',{actions:{OPEN:1}},{layer:'personal'});
H.setHandStrategy(combined,MIXED_CONTEXT,'AKs',{actions:{'3BET':1}},{layer:'personal'});
const combinedPlan=M.planMigration(combined,{activePopulationId:ZOOM});
assert.deepEqual(combinedPlan.compatible_population_ids,[ZOOM]);
assert.deepEqual(combinedPlan.inherited_population_ids,[MIXED]);
assert.deepEqual(combinedPlan.relabeled_population_ids,[]);
assert.equal(combinedPlan.overrides.length,2);
assert.equal(combinedPlan.overrides.find(o=>o.population_id===ZOOM).inherited,false);
assert.equal(combinedPlan.overrides.find(o=>o.population_id===MIXED).inherited,true);

// --- legacy range-folder payloads are imported additively and revertibly -----
const legacy=legacySource('Legacy folder');
const legacyStorage=memoryStorage({[M.STORAGE_KEY]:JSON.stringify(legacy)});
const imported=M.migrateStorage(legacyStorage,{activePopulationId:ZOOM});
assert.equal(imported.status,M.STATUSES.MIGRATED_IMPORTED);
assert.ok(imported.reason_codes.includes('LEGACY_SOURCE_IMPORTED'));
const importedRepo=M.loadRepository(legacyStorage);
assert.equal(importedRepo.source.preserved_verbatim,true);
assert.deepEqual(importedRepo.source.range_folder,legacy,'legacy source must be preserved verbatim after import');
assert.equal(importedRepo.defaults.population_id,ZOOM);
assert.equal(legacyStorage.getItem(M.PREVIOUS_STORAGE_KEY),JSON.stringify(legacy));
M.rollbackStorage(legacyStorage);
assert.deepEqual(M.loadRepository(legacyStorage),legacy,'rollback restores the raw legacy payload');

console.log('Hero range storage migration contract: PASS');
