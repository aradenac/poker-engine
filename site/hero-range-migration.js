(function(root,factory){
  const HeroRanges=(typeof module==='object'&&module.exports)?require('./hero-ranges.js'):(root&&root.PokerHeroRanges);
  const api=factory(root,HeroRanges);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerHeroRangeMigration=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(root,HeroRanges){
  'use strict';

  /*
    Runtime contract: additive, reversible migration of the Hero range repository
    persisted under localStorage key `poker.hero.range.repository.v1`.
    Contract: poker-hero-range-migration/v1

    This module is a pure planner plus a thin storage adapter. It never edits a
    range source and it never rewrites the population identity of an existing
    context.

    Invariants (issue #392 / #201 / #305 / #358 / #196):
    - The personal layer is extracted as source PERSONAL_OVERRIDE with an explicit
      contextual provenance (population_id, context key, repository schema and
      version). It is never surfaced as the POPULATION strategy.
    - Migration is additive: existing contexts, layers and the verbatim range
      source are preserved untouched; only a `migration` provenance block is added.
    - Migration is idempotent: applying it twice yields byte-identical repository
      JSON and never re-snapshots the rollback copy.
    - Migration is reversible: the exact pre-migration payload is kept under a
      dedicated previous key and can be restored byte-for-byte.
    - A repository whose explicit population_id differs from the active population
      is never relabelled. Foreign contexts stay verbatim and are reported as
      inherited; `relabeled_population_ids` is always empty.
  */

  const SCHEMA='poker-hero-range-migration/v1';
  const OVERRIDE_SCHEMA='poker-hero-personal-override/v1';
  const OVERRIDE_STATUS_SCHEMA='poker-hero-personal-override-status/v1';
  const REPOSITORY_SCHEMA='poker-hero-range-repository/v1';
  const STORAGE_KEY='poker.hero.range.repository.v1';
  const PREVIOUS_STORAGE_KEY=STORAGE_KEY+'.previous';
  const SOURCES=Object.freeze({POPULATION:'POPULATION',PERSONAL_OVERRIDE:'PERSONAL_OVERRIDE',NONE:'NONE'});
  const STATUSES=Object.freeze({
    MIGRATED:'MIGRATED',
    MIGRATED_IMPORTED:'MIGRATED_IMPORTED',
    UNCHANGED:'UNCHANGED',
    EMPTY:'EMPTY',
    UNAVAILABLE:'UNAVAILABLE',
    ROLLED_BACK:'ROLLED_BACK',
    ROLLBACK_UNAVAILABLE:'ROLLBACK_UNAVAILABLE'
  });

  function text(value){return value==null?'':String(value).trim();}
  function isObject(value){return !!value&&typeof value==='object'&&!Array.isArray(value);}
  function clone(value){return value==null?value:JSON.parse(JSON.stringify(value));}
  function uniqueSorted(values){return Array.from(new Set(values.filter(value=>value!=null&&value!==''))).sort();}

  function contextKey(context){
    if(HeroRanges&&typeof HeroRanges.contextKey==='function')return HeroRanges.contextKey(context);
    const c=context||{};
    return [c.population_id,c.table_size,c.position,c.effective_stack_bb,c.spot].join('|');
  }
  function normalizeContext(context){
    if(HeroRanges&&typeof HeroRanges.normalizeContext==='function')return HeroRanges.normalizeContext(context||{});
    return context;
  }
  function comboMultiplicity(hand){
    if(HeroRanges&&typeof HeroRanges.comboMultiplicity==='function')return HeroRanges.comboMultiplicity(hand);
    return hand.length===2?6:(hand.endsWith('s')?4:12);
  }

  function resolveStorage(storage){
    if(storage&&typeof storage.getItem==='function'&&typeof storage.setItem==='function')return storage;
    if(root&&root.localStorage&&typeof root.localStorage.getItem==='function')return root.localStorage;
    return null;
  }
  function readRaw(storage,key){
    const target=resolveStorage(storage);if(!target)return null;
    try{return target.getItem(key);}catch(_){return null;}
  }
  function writeRaw(storage,key,value){
    const target=resolveStorage(storage);if(!target)throw new Error('no storage available');
    target.setItem(key,value);
  }

  function parsePayload(raw){
    if(raw==null)return {ok:false,value:null,reason:'EMPTY_PAYLOAD'};
    if(isObject(raw))return {ok:true,value:clone(raw),reason:null};
    if(typeof raw!=='string')return {ok:false,value:null,reason:'INVALID_PAYLOAD'};
    try{
      const parsed=JSON.parse(raw);
      if(!isObject(parsed))return {ok:false,value:null,reason:'INVALID_PAYLOAD'};
      return {ok:true,value:parsed,reason:null};
    }catch(_){return {ok:false,value:null,reason:'INVALID_JSON'};}
  }

  function isRepository(value){
    if(!isObject(value)||value.schema!==REPOSITORY_SCHEMA)return false;
    if(HeroRanges&&typeof HeroRanges.validateRepository==='function'){
      try{HeroRanges.validateRepository(value);}catch(_){return false;}
    }
    return true;
  }

  function repositoryVersion(repository){return repository&&repository.version!=null?repository.version:null;}

  function contextView(repository){
    const out=[];
    if(!isObject(repository)||!isObject(repository.contexts))return out;
    for(const [key,node] of Object.entries(repository.contexts)){
      const context=isObject(node)&&isObject(node.context)?node.context:null;
      const personal=isObject(node)&&isObject(node.layers)?node.layers.personal:null;
      const calculated=isObject(node)&&isObject(node.layers)?node.layers.calculated:null;
      out.push({
        key,
        context,
        population_id:context?text(context.population_id):'',
        personal_hands:isObject(personal)&&isObject(personal.hands)?Object.keys(personal.hands):[],
        personal_layer:isObject(personal)?personal:null,
        calculated_defined:isObject(calculated)&&isObject(calculated.hands)?Object.keys(calculated.hands).length:0
      });
    }
    return out.sort((a,b)=>String(a.key).localeCompare(String(b.key)));
  }

  function populationView(repository,activePopulationId){
    const active=text(activePopulationId);
    const groups=new Map();
    const register=(populationId,compatible,inherited)=>{
      const id=text(populationId);if(!id)return;
      if(!groups.has(id))groups.set(id,{population_id:id,contexts:0,personal_hands:0,compatible:false,inherited:false});
      const group=groups.get(id);
      group.compatible=group.compatible||compatible;
      group.inherited=group.inherited||inherited;
    };
    register(repository&&repository.defaults&&repository.defaults.population_id,text(repository&&repository.defaults&&repository.defaults.population_id)===active,!!active&&text(repository&&repository.defaults&&repository.defaults.population_id)!==active);
    for(const entry of contextView(repository)){
      const compatible=text(entry.population_id)===active;
      register(entry.population_id,compatible,!!active&&text(entry.population_id)!==active);
      const group=groups.get(text(entry.population_id));
      if(group){group.contexts++;group.personal_hands+=entry.personal_hands.length;}
    }
    const populations=Array.from(groups.values()).sort((a,b)=>a.population_id.localeCompare(b.population_id));
    const compatible_population_ids=uniqueSorted(populations.filter(p=>p.compatible).map(p=>p.population_id));
    const inherited_population_ids=uniqueSorted(populations.filter(p=>p.inherited).map(p=>p.population_id));
    return {populations,compatible_population_ids,inherited_population_ids};
  }

  function layerVersionOf(layer){
    if(!isObject(layer))return null;
    return layer.version==null?null:String(layer.version);
  }
  function layerProvenanceOf(layer){
    return isObject(layer)&&isObject(layer.provenance)?layer.provenance:null;
  }

  function buildOverride(entry,repository,activePopulationId){
    const populationId=text(entry.population_id);
    const active=text(activePopulationId);
    const populationMatch=!active||populationId===active;
    const hands=entry.personal_layer&&isObject(entry.personal_layer.hands)?clone(entry.personal_layer.hands):{};
    const handNames=Object.keys(hands);
    const comboSlots=handNames.reduce((sum,hand)=>sum+comboMultiplicity(hand),0);
    const provenance={
      origin:SOURCES.PERSONAL_OVERRIDE,
      source:SOURCES.PERSONAL_OVERRIDE,
      layer:'personal',
      population_id:populationId||null,
      context_key:entry.key,
      repository_schema:repository&&repository.schema?String(repository.schema):null,
      repository_version:repositoryVersion(repository),
      layer_version:layerVersionOf(entry.personal_layer),
      active_population_id:active||null,
      population_match:populationMatch,
      inherited:!populationMatch
    };
    return {
      schema:OVERRIDE_SCHEMA,
      source:SOURCES.PERSONAL_OVERRIDE,
      population_id:populationId||null,
      context_key:entry.key,
      context:entry.context?clone(entry.context):null,
      repository_schema:provenance.repository_schema,
      repository_version:provenance.repository_version,
      layer:'personal',
      layer_version:provenance.layer_version,
      layer_provenance:layerProvenanceOf(entry.personal_layer),
      hands,
      hand_count:handNames.length,
      combo_slots:comboSlots,
      active_population_id:active||null,
      population_match:populationMatch,
      inherited:!populationMatch,
      provenance
    };
  }

  function extractPersonalOverride(repository,context,{activePopulationId=null,requireCompatible=false}={}){
    if(!isObject(repository)||!isObject(repository.contexts))return null;
    let key;
    try{key=contextKey(normalizeContext(context));}catch(_){return null;}
    const node=repository.contexts[key];
    if(!isObject(node))return null;
    const personal=isObject(node.layers)?node.layers.personal:null;
    if(!isObject(personal)||!isObject(personal.hands)||Object.keys(personal.hands).length===0)return null;
    const populationId=isObject(node.context)?text(node.context.population_id):'';
    const active=text(activePopulationId);
    const override=buildOverride({key,context:node.context,population_id:populationId,personal_layer:personal},repository,activePopulationId);
    if(requireCompatible&&!override.population_match)return null;
    return override;
  }

  function extractPersonalOverrides(repository,{activePopulationId=null,populationId=null,includeInherited=true}={}){
    const active=text(activePopulationId);
    const wanted=text(populationId);
    const out=[];
    for(const entry of contextView(repository)){
      if(entry.personal_hands.length===0)continue;
      const entryPopulation=text(entry.population_id);
      if(wanted&&entryPopulation!==wanted)continue;
      if(!includeInherited&&active&&entryPopulation!==active)continue;
      out.push(buildOverride(entry,repository,activePopulationId));
    }
    return out.sort((a,b)=>String(a.context_key).localeCompare(String(b.context_key)));
  }

  /*
    Pure contextual status of the personal override layer.

    `available` is true when an override exists somewhere in the requested
    population; it says nothing about the context the user is looking at.
    `active` is true only when an override is actually resolved on the exact
    `context` handed in (via HeroRanges.contextKey). An unresolvable context
    (missing fields, unknown position/spot, invalid stack) is a fail-safe
    inactive state: a global presence is never promoted to an active override,
    and the status is always sourced from PERSONAL_OVERRIDE, never POPULATION.
  */
  function personalOverrideStatus(repository,{populationId=null,activePopulationId=null,context=null}={}){
    const population=text(populationId||activePopulationId)||null;
    if(!population){
      return {
        schema:OVERRIDE_STATUS_SCHEMA,
        source:SOURCES.PERSONAL_OVERRIDE,
        population_id:null,
        available:false,
        active:false,
        active_context_key:null,
        context_keys:[],
        count:0
      };
    }
    const overrides=extractPersonalOverrides(repository,{populationId:population,includeInherited:false});
    const contextKeys=uniqueSorted(overrides.map(override=>override.context_key));
    let activeContextKey=null;
    let active=false;
    if(context){
      try{
        activeContextKey=contextKey(context);
        active=contextKeys.includes(activeContextKey);
      }catch(_){
        activeContextKey=null;
        active=false;
      }
    }
    return {
      schema:OVERRIDE_STATUS_SCHEMA,
      source:SOURCES.PERSONAL_OVERRIDE,
      population_id:population,
      available:contextKeys.length>0,
      active,
      active_context_key:activeContextKey,
      context_keys:contextKeys,
      count:contextKeys.length
    };
  }

  function detectPopulationIds(repository,{activePopulationId=null}={}){
    const view=populationView(repository,activePopulationId);
    return {
      active_population_id:text(activePopulationId)||null,
      populations:view.populations,
      compatible_population_ids:view.compatible_population_ids,
      inherited_population_ids:view.inherited_population_ids,
      relabeled_population_ids:[]
    };
  }

  function migrationBlock(repository,{activePopulationId,migratedAt=null}={}){
    const view=populationView(repository,activePopulationId);
    const overrides=extractPersonalOverrides(repository,{activePopulationId});
    const overrideIndex=overrides.map(override=>({
      context_key:override.context_key,
      population_id:override.population_id,
      source:SOURCES.PERSONAL_OVERRIDE,
      inherited:override.inherited,
      repository_version:override.repository_version,
      hand_count:override.hand_count
    }));
    return {
      schema:SCHEMA,
      status:STATUSES.MIGRATED,
      active_population_id:text(activePopulationId)||null,
      migrated_at:migratedAt==null?null:String(migratedAt),
      idempotent:true,
      source_verbatim_preserved:true,
      storage_key:STORAGE_KEY,
      previous_storage_key:PREVIOUS_STORAGE_KEY,
      compatible_population_ids:view.compatible_population_ids,
      inherited_population_ids:view.inherited_population_ids,
      relabeled_population_ids:[],
      populations:view.populations,
      overrides:overrideIndex
    };
  }

  function migrationOf(repository){
    return isObject(repository)&&isObject(repository.migration)?repository.migration:null;
  }
  function isMigrated(repository){
    return isObject(migrationOf(repository))&&migrationOf(repository).schema===SCHEMA;
  }

  function planMigration(repository,{activePopulationId=null,migratedAt=null}={}){
    const reasons=[];
    const active=text(activePopulationId)||null;
    if(!isObject(repository)){
      reasons.push('REPOSITORY_MISSING');
      return {schema:SCHEMA,status:STATUSES.UNAVAILABLE,active_population_id:active,migrated:false,idempotent:true,repository:clone(repository),source_verbatim:clone(repository),inherited_population_ids:[],compatible_population_ids:[],relabeled_population_ids:[],overrides:[],reason_codes:uniqueSorted(reasons)};
    }
    if(!isRepository(repository)){
      reasons.push('REPOSITORY_INVALID');
      return {schema:SCHEMA,status:STATUSES.UNAVAILABLE,active_population_id:active,migrated:false,idempotent:true,repository:clone(repository),source_verbatim:clone(repository),inherited_population_ids:[],compatible_population_ids:[],relabeled_population_ids:[],overrides:[],reason_codes:uniqueSorted(reasons)};
    }
    const view=populationView(repository,active);
    const overrides=extractPersonalOverrides(repository,{activePopulationId:active});
    if(isMigrated(repository)){
      reasons.push('ALREADY_MIGRATED');
      if(view.inherited_population_ids.length)reasons.push('INHERITED_POPULATION_RETAINED');
      return {
        schema:SCHEMA,status:STATUSES.UNCHANGED,active_population_id:active,migrated:false,idempotent:true,
        repository:clone(repository),source_verbatim:clone(repository),
        migration:migrationOf(repository),
        inherited_population_ids:view.inherited_population_ids,
        compatible_population_ids:view.compatible_population_ids,
        relabeled_population_ids:[],overrides,reason_codes:uniqueSorted(reasons)
      };
    }
    const migrated=clone(repository);
    migrated.migration=migrationBlock(repository,{activePopulationId:active,migratedAt});
    if(HeroRanges&&typeof HeroRanges.validateRepository==='function')HeroRanges.validateRepository(migrated);
    reasons.push('MIGRATION_ADDITIVE');
    if(view.inherited_population_ids.length)reasons.push('INHERITED_POPULATION_RETAINED');
    if(!view.compatible_population_ids.length)reasons.push('NO_COMPATIBLE_POPULATION');
    return {
      schema:SCHEMA,status:STATUSES.MIGRATED,active_population_id:active,migrated:true,idempotent:true,
      repository:migrated,source_verbatim:clone(repository),migration:migrated.migration,
      inherited_population_ids:view.inherited_population_ids,
      compatible_population_ids:view.compatible_population_ids,
      relabeled_population_ids:[],overrides,reason_codes:uniqueSorted(reasons)
    };
  }

  function migrateRepository(repository,{activePopulationId=null,previous=null,migratedAt=null}={}){
    const plan=planMigration(repository,{activePopulationId,migratedAt});
    return {
      ...plan,
      previous:previous==null?null:clone(previous),
      rollback_available:previous!=null
    };
  }

  function importLegacy(raw,{activePopulationId=null}={}){
    if(!isObject(raw))return null;
    if(isRepository(raw))return clone(raw);
    if(HeroRanges&&typeof HeroRanges.importDocument==='function'){
      try{return HeroRanges.importDocument(raw,{populationId:text(activePopulationId)||''});}catch(_){return null;}
    }
    return null;
  }

  function migrateStorage(storage,{activePopulationId=null,storageKey=STORAGE_KEY,previousStorageKey=PREVIOUS_STORAGE_KEY,migratedAt=null}={}){
    const active=text(activePopulationId)||null;
    const raw=readRaw(storage,storageKey);
    if(raw==null){
      const existingPrevious=readRaw(storage,previousStorageKey);
      return {schema:SCHEMA,status:STATUSES.EMPTY,active_population_id:active,migrated:false,idempotent:true,rollback_available:existingPrevious!=null,repository:null,previous_raw:existingPrevious,overrides:[],inherited_population_ids:[],compatible_population_ids:[],relabeled_population_ids:[],reason_codes:['STORAGE_EMPTY']};
    }
    const parsed=parsePayload(raw);
    if(!parsed.ok){
      return {schema:SCHEMA,status:STATUSES.UNAVAILABLE,active_population_id:active,migrated:false,idempotent:true,rollback_available:false,repository:null,previous_raw:null,overrides:[],inherited_population_ids:[],compatible_population_ids:[],relabeled_population_ids:[],reason_codes:uniqueSorted([parsed.reason,'STORAGE_UNAVAILABLE'])};
    }
    let repository=parsed.value;
    let imported=false;
    if(!isRepository(repository)){
      const legacy=importLegacy(repository,{activePopulationId:active});
      if(!legacy){
        return {schema:SCHEMA,status:STATUSES.UNAVAILABLE,active_population_id:active,migrated:false,idempotent:true,rollback_available:false,repository:null,previous_raw:null,overrides:[],inherited_population_ids:[],compatible_population_ids:[],relabeled_population_ids:[],reason_codes:['REPOSITORY_INVALID','STORAGE_UNAVAILABLE']};
      }
      repository=legacy;
      imported=true;
    }

    const existingPrevious=readRaw(storage,previousStorageKey);
    const hadPrevious=existingPrevious!=null;
    const previousRaw=hadPrevious?existingPrevious:raw;
    const plan=planMigration(repository,{activePopulationId:active,migratedAt});
    const status=plan.status===STATUSES.MIGRATED&&imported?STATUSES.MIGRATED_IMPORTED:plan.status;

    if(plan.status===STATUSES.MIGRATED){
      if(!hadPrevious){
        try{writeRaw(storage,previousStorageKey,raw);}catch(err){return {schema:SCHEMA,status:STATUSES.UNAVAILABLE,active_population_id:active,migrated:false,idempotent:true,rollback_available:false,repository:plan.repository,previous_raw:null,overrides:plan.overrides,inherited_population_ids:plan.inherited_population_ids,compatible_population_ids:plan.compatible_population_ids,relabeled_population_ids:[],reason_codes:uniqueSorted(['ROLLBACK_WRITE_FAILED',String(err&&err.message)])};}
      }
      writeRaw(storage,storageKey,JSON.stringify(plan.repository));
    }

    return {
      schema:SCHEMA,
      status,
      active_population_id:active,
      migrated:plan.migrated,
      idempotent:plan.idempotent,
      rollback_available:readRaw(storage,previousStorageKey)!=null,
      repository:plan.repository,
      source_verbatim:plan.source_verbatim,
      previous_raw:previousRaw,
      overrides:plan.overrides,
      inherited_population_ids:plan.inherited_population_ids,
      compatible_population_ids:plan.compatible_population_ids,
      relabeled_population_ids:plan.relabeled_population_ids,
      migration:plan.migration||null,
      reason_codes:uniqueSorted([...plan.reason_codes,imported?'LEGACY_SOURCE_IMPORTED':''])
    };
  }

  function rollbackStorage(storage,{storageKey=STORAGE_KEY,previousStorageKey=PREVIOUS_STORAGE_KEY}={}){
    const previousRaw=readRaw(storage,previousStorageKey);
    if(previousRaw==null){
      return {schema:SCHEMA,status:STATUSES.ROLLBACK_UNAVAILABLE,rollback_available:false,repository:null,reason_codes:['NO_PREVIOUS_COPY']};
    }
    const parsed=parsePayload(previousRaw);
    writeRaw(storage,storageKey,previousRaw);
    return {
      schema:SCHEMA,
      status:STATUSES.ROLLED_BACK,
      rollback_available:true,
      repository:parsed.ok?parsed.value:null,
      restored_raw:previousRaw,
      reason_codes:['PREVIOUS_COPY_RESTORED','PREVIOUS_COPY_RETAINED']
    };
  }

  function loadRepository(storage,{storageKey=STORAGE_KEY}={}){
    const raw=readRaw(storage,storageKey);
    if(raw==null)return null;
    const parsed=parsePayload(raw);
    return parsed.ok?parsed.value:null;
  }

  function persistRepository(storage,repository,{storageKey=STORAGE_KEY}={}){
    if(HeroRanges&&typeof HeroRanges.validateRepository==='function')HeroRanges.validateRepository(repository);
    writeRaw(storage,storageKey,JSON.stringify(repository));
    return repository;
  }

  return {
    SCHEMA,OVERRIDE_SCHEMA,OVERRIDE_STATUS_SCHEMA,REPOSITORY_SCHEMA,STORAGE_KEY,PREVIOUS_STORAGE_KEY,SOURCES,STATUSES,
    contextKey,extractPersonalOverride,extractPersonalOverrides,personalOverrideStatus,detectPopulationIds,
    migrationOf,isMigrated,planMigration,migrateRepository,migrateStorage,rollbackStorage,
    loadRepository,persistRepository
  };
});
