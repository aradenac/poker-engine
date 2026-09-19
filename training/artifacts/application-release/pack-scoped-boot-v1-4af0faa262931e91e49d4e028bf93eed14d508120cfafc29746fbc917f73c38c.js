(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerPackScopedBoot=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';

  const SCHEMA='poker-pack-scoped-boot/v1';
  const RESULT_SCHEMA='poker-pack-scoped-boot-result/v1';
  const TARGET_POPULATION='pokerstars_nlhe_100-200_zoom_play_6max_v1';
  const ENGINE_PATH='training/artifacts/pack-engine/poker-pack-engine-runtime-v1-15bfa1ba78b463b63b5b9b8ee47a98fd9b29c2a9b79fa455b791a9781c7d7e08.js';
  const ENGINE_SHA256='15bfa1ba78b463b63b5b9b8ee47a98fd9b29c2a9b79fa455b791a9781c7d7e08';
  const ADMISSIBLE='ADMISSIBLE_FOR_PACK';
  const REQUIRED_SCIENTIFIC_ROLES=['model_a_preflop','model_a_postflop','model_b','hero_strategy','hero_ranges'];
  const LEGACY_FORBIDDEN_SOURCES=new Set([
    'user/releases/poker_range_equity_offline_multiway_v83.html',
    'training/models/preflop_population_model_v5.json',
    'training/models/postflop_population_model_v5.json'
  ]);

  class PackScopedBootError extends Error{
    constructor(code,message,details={}){
      super(message);this.name='PackScopedBootError';this.code=code;this.details=details;
    }
  }
  const text=v=>v==null?'':String(v).trim();
  const object=v=>v&&typeof v==='object'&&!Array.isArray(v)?v:null;
  function fail(code,message,details){throw new PackScopedBootError(code,message,details);}

  function validateTargetComponent(role,component,{exactEngine=false}={}){
    const row=object(component);
    if(!row)fail('PACK_COMPONENT_MISSING',role+' is required for explicit Zoom pack',{role});
    if(text(row.role)!==role)fail('PACK_COMPONENT_ROLE_MISMATCH',role+' role identity mismatch',{role,actual:row.role});
    if(text(row.population_id)!==TARGET_POPULATION)fail('PACK_COMPONENT_POPULATION_MISMATCH',role+' population mismatch',{role,actual:row.population_id});
    const lineage=object(row.lineage);
    if(!lineage||text(lineage.population_id)!==TARGET_POPULATION||text(lineage.format)!=='ZOOM'){
      fail('PACK_COMPONENT_LINEAGE_MISMATCH',role+' must be target-scoped ZOOM lineage',{role,lineage});
    }
    const provenance=object(row.provenance);
    if(!provenance||text(provenance.source_population_id)!==TARGET_POPULATION){
      fail('PACK_COMPONENT_PROVENANCE_MISMATCH',role+' provenance must be target-scoped',{role,provenance});
    }
    const decision=object(row.decision);
    if(!decision||text(decision.status)!==ADMISSIBLE){
      fail('PACK_COMPONENT_NOT_ADMISSIBLE',role+' must be explicitly ADMISSIBLE_FOR_PACK',{role,status:decision&&decision.status});
    }
    const source=text(row.source_path),sha=text(row.sha256);
    if(!source||!/^[a-f0-9]{64}$/.test(sha))fail('PACK_COMPONENT_IDENTITY_INVALID',role+' requires source_path and sha256',{role});
    if(LEGACY_FORBIDDEN_SOURCES.has(source))fail('LEGACY_FALLBACK_REJECTED',role+' legacy/default source is forbidden in explicit Zoom mode',{role,source_path:source});
    if(exactEngine&&(source!==ENGINE_PATH||sha!==ENGINE_SHA256)){
      fail('ENGINE_BINDING_MISMATCH','explicit Zoom mode requires the exact #370 engine',{expected_path:ENGINE_PATH,expected_sha256:ENGINE_SHA256,actual_path:source,actual_sha256:sha});
    }
    return {
      role,population_id:TARGET_POPULATION,source_path:source,sha256:sha,
      lineage:{population_id:TARGET_POPULATION,format:'ZOOM'},
      decision_status:ADMISSIBLE
    };
  }

  function resolve(options={}){
    const mode=text(options.mode||'LEGACY_DEFAULT').toUpperCase();
    if(mode==='LEGACY_DEFAULT'){
      return {
        schema:RESULT_SCHEMA,mode,status:'LEGACY_PASSTHROUGH',
        population_id:null,use_existing_default_runtime:true,bindings:null,
        fallback_policy:'HISTORICAL_DEFAULTS_OUTSIDE_EXPLICIT_ZOOM_MODE'
      };
    }
    if(mode!=='PACK_SCOPED_ZOOM')fail('BOOT_MODE_INVALID','unsupported boot mode',{mode});
    const pack=object(options.pack);
    if(!pack)fail('PACK_MANIFEST_MISSING','explicit Zoom mode requires a pack manifest');
    if(text(pack.population_id)!==TARGET_POPULATION){
      fail('PACK_POPULATION_MISMATCH','explicit Zoom pack population mismatch',{actual:pack.population_id,expected:TARGET_POPULATION});
    }
    const components=object(pack.components);
    if(!components)fail('PACK_COMPONENTS_MISSING','explicit Zoom pack requires components');
    const bindings={engine:validateTargetComponent('engine',components.engine,{exactEngine:true})};
    for(const role of REQUIRED_SCIENTIFIC_ROLES)bindings[role]=validateTargetComponent(role,components[role]);
    return {
      schema:RESULT_SCHEMA,mode,status:'BOUND',
      population_id:TARGET_POPULATION,use_existing_default_runtime:false,
      bindings,
      fallback_policy:'NONE_FAIL_CLOSED',
      engine_binding:{source_path:ENGINE_PATH,sha256:ENGINE_SHA256},
      missing_or_incompatible_component_behavior:'THROW_EXPLICIT_ERROR'
    };
  }

  return {
    SCHEMA,RESULT_SCHEMA,TARGET_POPULATION,ENGINE_PATH,ENGINE_SHA256,
    REQUIRED_SCIENTIFIC_ROLES,PackScopedBootError,resolve
  };
});
