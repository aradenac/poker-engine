(function(root,factory){
  const HeroRanges=(typeof module==='object'&&module.exports)?require('./hero-ranges.js'):(root&&root.PokerHeroRanges);
  const api=factory(HeroRanges);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerHeroStrategyResolver=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(HeroRanges){
  'use strict';

  /*
    Runtime contract: Population -> Hero strategy resolution.
    Contract: poker-hero-strategy-resolution/v1

    This resolver is a pure, read-only, no-promotion function. It answers a single
    question: "is there a population-bound Hero strategy I am allowed to use right
    now, and what is its exact identity?".

    Fail-closed invariants enforced here (#201/#305/#358/#196):
    - The active population_id must match the repository defaults, every
      materialized calculated context, the pack identity, the trainer manifest,
      the persisted admission set and any retained reference. Otherwise the answer
      is POPULATION_INCOMPATIBLE and no strategy identity is returned.
    - A calculated artifact only becomes ADMISSIBLE_CALCULATED when an explicit
      ADMISSIBLE admission exists AND it is complete (169 hand classes per active
      calculated context). Un-admitted, unresolved, rejected or inactive metadata
      never becomes the active strategy.
    - An inactive candidate (#358 metadata only) is reported as UNAVAILABLE; it is
      never auto-activated.
    - A user personal override is surfaced only as source PERSONAL_OVERRIDE with
      an explicit PARTIAL status. It can never masquerade as the population
      strategy.
    - The literal label "Custom" is never emitted as a strategy identity; such
      tokens are rejected with CUSTOM_LABEL_REJECTED.

    The output is deterministic for a given input: reason codes are unique and
    sorted, context keys are sorted and provenance is built from explicit tokens
    only.
  */

  const SCHEMA='poker-hero-strategy-resolution/v1';
  const STATUSES=Object.freeze({
    ADMISSIBLE_CALCULATED:'ADMISSIBLE_CALCULATED',
    RETAIN_REFERENCE:'RETAIN_REFERENCE',
    PARTIAL:'PARTIAL',
    UNAVAILABLE:'UNAVAILABLE',
    POPULATION_INCOMPATIBLE:'POPULATION_INCOMPATIBLE'
  });
  const SOURCES=Object.freeze({
    POPULATION:'POPULATION',
    PERSONAL_OVERRIDE:'PERSONAL_OVERRIDE',
    NONE:'NONE'
  });
  const ADMISSION_STATUSES=Object.freeze(['ADMISSIBLE','RETAIN_REFERENCE','UNRESOLVED','REJECTED','INCOMPATIBLE']);
  const CANDIDATE_SCHEMA='poker-hero-calculated-range-candidate/v1';
  const REPOSITORY_SCHEMA='poker-hero-range-repository/v1';
  const TRAINER_MANIFEST_SCHEMA='trainer-population-pack/v1';
  const PACK_RUNTIME_SCHEMA='poker-browser-runtime-pack/v1';
  const IMPORT_SCHEMA='poker-hero-preflop-repository-import/v1';
  const GENERATION_MANIFEST_SCHEMA='poker-hero-preflop-generation-manifest/v1';
  const HAND_CLASSES_TOTAL=(HeroRanges&&Array.isArray(HeroRanges.HAND_CLASSES)&&HeroRanges.HAND_CLASSES.length)?HeroRanges.HAND_CLASSES.length:169;
  const HEX64=/^[0-9a-f]{64}$/;
  const CUSTOM_LABEL=/^custom$/i;
  const INACTIVE_ACTIVATION_STATES=new Set([
    'INACTIVE','INACTIVE_CANDIDATE_METADATA_ONLY',
    'SYNTHETIC_PLACEHOLDER','SYNTHETIC_PLACEHOLDER_METADATA_ONLY'
  ]);

  function text(value){return value==null?'':String(value).trim();}
  function upper(value){return text(value).toUpperCase();}
  function clone(value){return value==null?value:JSON.parse(JSON.stringify(value));}
  function uniqueSorted(values){return Array.from(new Set(values.filter(value=>value!=null&&value!==''))).sort();}
  function hex(value){const token=text(value).toLowerCase();return HEX64.test(token)?token:null;}
  function isObject(value){return !!value&&typeof value==='object'&&!Array.isArray(value);}

  function token(value,reasons){
    const valueText=text(value);
    if(!valueText)return null;
    if(CUSTOM_LABEL.test(valueText)){if(reasons)reasons.push('CUSTOM_LABEL_REJECTED');return null;}
    return valueText;
  }
  function scrubCustom(value,reasons){
    if(typeof value==='string'){
      if(CUSTOM_LABEL.test(value.trim())){if(reasons)reasons.push('CUSTOM_LABEL_REJECTED');return null;}
      return value;
    }
    if(Array.isArray(value))return value.map(item=>scrubCustom(item,reasons));
    if(isObject(value)){
      const out={};
      for(const [key,item] of Object.entries(value))out[key]=scrubCustom(item,reasons);
      return out;
    }
    return value;
  }

  function readAdmission(value){
    if(value==null)return {status:null,object:null};
    if(typeof value==='string')return {status:upper(value)||null,object:null};
    if(isObject(value))return {status:upper(value.status||value.admission_status||value.decision)||null,object:value};
    return {status:null,object:null};
  }

  function populationBindings({repository,candidate,trainerManifest,packIdentity,admissionRoot,heroStrategyAdmission,heroRangesAdmission,reference,context}){
    const bindings=[];
    const push=(source,value)=>{const population=text(value);if(population)bindings.push({source,population_id:population});};
    push('REPOSITORY_DEFAULTS',repository&&repository.defaults&&repository.defaults.population_id);
    if(isObject(repository)&&isObject(repository.contexts)){
      for(const node of Object.values(repository.contexts)){
        const calculated=isObject(node)&&isObject(node.layers)?node.layers.calculated:null;
        if(!isObject(calculated))continue;
        const materialized=Object.keys(isObject(calculated.hands)?calculated.hands:{}).length>0||calculated.version!=null||calculated.provenance!=null;
        if(materialized)push('CALCULATED_CONTEXT',isObject(node.context)?node.context.population_id:null);
      }
    }
    push('CANDIDATE',candidate&&candidate.population_id);
    push('CANDIDATE_CONTEXT',candidate&&isObject(candidate.context)?candidate.context.population_id:null);
    push('TRAINER_MANIFEST',trainerManifest&&trainerManifest.population_id);
    push('PACK_IDENTITY',packIdentity&&(packIdentity.population_id||(isObject(packIdentity.entry)?packIdentity.entry.population_id:null)));
    push('ADMISSION',isObject(admissionRoot)?admissionRoot.population_id:null);
    push('ADMISSION_HERO_STRATEGY',heroStrategyAdmission&&heroStrategyAdmission.population_id);
    push('ADMISSION_HERO_RANGES',heroRangesAdmission&&heroRangesAdmission.population_id);
    push('RETAINED_REFERENCE',reference&&reference.population_id);
    push('CONTEXT',context&&context.population_id);
    return bindings;
  }

  function candidateProblemCodes(candidate){
    const out=[];
    if(!isObject(candidate))return out;
    if(candidate.schema&&candidate.schema!==CANDIDATE_SCHEMA)out.push('CANDIDATE_SCHEMA_MISMATCH');
    if(candidate.promotion_authorized===true)out.push('CANDIDATE_PROMOTION_FORBIDDEN');
    if(upper(candidate.status)==='PROMOTED')out.push('CANDIDATE_SELF_PROMOTED');
    return out;
  }

  function calculatedLayers(repository){
    const out=[];
    if(!isObject(repository)||!isObject(repository.contexts))return out;
    for(const [key,node] of Object.entries(repository.contexts)){
      const layer=isObject(node)&&isObject(node.layers)?node.layers.calculated:null;
      if(!isObject(layer))continue;
      const provenance=isObject(layer.provenance)?layer.provenance:null;
      const hands=isObject(layer.hands)?layer.hands:{};
      const defined=Object.keys(hands).length;
      const activation=provenance?upper(provenance.activation_state):'';
      const inactive=INACTIVE_ACTIVATION_STATES.has(activation);
      const materialized=defined>0||layer.version!=null||provenance!=null;
      if(!materialized)continue;
      out.push({
        key,
        layer,
        provenance,
        defined,
        complete:defined===HAND_CLASSES_TOTAL,
        inactive,
        metadata_only:defined===0&&provenance!=null
      });
    }
    return out.sort((a,b)=>String(a.key).localeCompare(String(b.key)));
  }

  function personalLayers(repository,activePopulation){
    const context_keys=[];
    if(!isObject(repository)||!isObject(repository.contexts))return {available:false,context_keys};
    for(const [key,node] of Object.entries(repository.contexts)){
      const population=isObject(node)&&isObject(node.context)?text(node.context.population_id):'';
      if(population&&activePopulation&&population!==activePopulation)continue;
      const layer=isObject(node)&&isObject(node.layers)?node.layers.personal:null;
      if(!isObject(layer)||!isObject(layer.hands))continue;
      if(Object.keys(layer.hands).length>0)context_keys.push(key);
    }
    context_keys.sort();
    return {available:context_keys.length>0,context_keys};
  }

  function calculatedResolution(input,calculated,candidate,activePopulation,admissionStatus,reasons){
    const primary=calculated[0]||{};
    const provenance=isObject(primary.provenance)?primary.provenance:{};
    const layer=isObject(primary.layer)?primary.layer:{};
    const strategyVersion=token(input.strategy_version,reasons)||token(layer.version,reasons)||token(candidate&&candidate.version,reasons);
    const strategySha=hex(input.strategy_sha256)||hex(candidate&&candidate.strategy_sha256)||hex(provenance.manifest_sha256)||hex(provenance.binding_sha256)||hex(provenance.code);
    const strategyId=token(input.strategy_id,reasons)||token(candidate&&candidate.strategy_id,reasons)||token(provenance.candidate_id,reasons)||token(candidate&&candidate.candidate_id,reasons)||(activePopulation?`hero-population:${activePopulation}`:null);
    const coverage={
      contexts:calculated.length,
      defined_hand_classes:calculated.reduce((sum,entry)=>sum+entry.defined,0),
      complete:calculated.every(entry=>entry.complete)
    };
    return {
      identity:{strategy_id:strategyId,strategy_version:strategyVersion,strategy_sha256:strategySha},
      provenance:{
        origin:'CALCULATED_POPULATION',
        population_id:activePopulation,
        admission_status:admissionStatus||null,
        candidate_id:token(candidate&&candidate.candidate_id,reasons)||token(provenance.candidate_id,reasons),
        generation_id:token(provenance.generation_id,reasons),
        layer_schema:token(provenance.schema,reasons),
        layer_status:token(provenance.status,reasons),
        layer_version:token(layer.version,reasons),
        activation_state:token(provenance.activation_state,reasons)||'ACTIVE_MEASURED',
        manifest_sha256:hex(provenance.manifest_sha256),
        binding_sha256:hex(provenance.binding_sha256),
        source_plan_sha256:hex(provenance.source_plan_sha256),
        source_shard_sha256:hex(isObject(provenance.source_shard)?provenance.source_shard.sha256:null),
        context_keys:calculated.map(entry=>entry.key),
        coverage
      }
    };
  }

  function retainedResolution(input,reference,admissionObject,activePopulation,reasons){
    const artifact=isObject(admissionObject)&&isObject(admissionObject.artifact)?admissionObject.artifact:null;
    const decision=isObject(admissionObject)&&isObject(admissionObject.scientific_decision)?admissionObject.scientific_decision:null;
    const strategyId=token(input.strategy_id,reasons)||token(reference&&reference.strategy_id,reasons)||token(admissionObject&&admissionObject.strategy_id,reasons);
    const strategyVersion=token(input.strategy_version,reasons)||token(reference&&reference.strategy_version,reasons)||token(admissionObject&&admissionObject.strategy_version,reasons);
    const strategySha=hex(input.strategy_sha256)||hex(reference&&reference.strategy_sha256)||hex(artifact&&artifact.actual_sha256)||hex(artifact&&artifact.declared_sha256);
    if(!strategyId&&!strategyVersion&&!strategySha)reasons.push('RETAINED_REFERENCE_IDENTITY_MISSING');
    return {
      identity:{strategy_id:strategyId,strategy_version:strategyVersion,strategy_sha256:strategySha},
      provenance:{
        origin:'RETAINED_REFERENCE',
        population_id:activePopulation,
        admission_status:'RETAIN_REFERENCE',
        reference_schema:token(reference&&reference.schema,reasons),
        reference_issue:token(reference&&reference.issue,reasons)||token(decision&&decision.issue,reasons)
      }
    };
  }

  function buildResult({status,source,activePopulation,identity,provenance,failClosed,reasons}){
    const safeIdentity=identity||{};
    return {
      schema:SCHEMA,
      status,
      source,
      population_id:activePopulation||null,
      strategy_id:safeIdentity.strategy_id==null?null:String(safeIdentity.strategy_id),
      strategy_version:safeIdentity.strategy_version==null?null:String(safeIdentity.strategy_version),
      strategy_sha256:safeIdentity.strategy_sha256==null?null:String(safeIdentity.strategy_sha256),
      provenance:provenance==null?null:scrubCustom(clone(provenance),reasons),
      fail_closed:!!failClosed,
      reason_codes:uniqueSorted(reasons)
    };
  }

  // Normalized identity + availability of a resolution. Downstream consumers
  // (Review scope, training target) must derive their strategy identity from
  // this accessor rather than re-reading manifests or inventing a label.
  function identity(resolution){
    const r=isObject(resolution)?resolution:{};
    return {
      population_id:r.population_id==null?null:String(r.population_id),
      strategy_id:r.strategy_id==null?null:String(r.strategy_id),
      strategy_version:r.strategy_version==null?null:String(r.strategy_version),
      strategy_sha256:r.strategy_sha256==null?null:String(r.strategy_sha256),
      status:text(r.status)||STATUSES.UNAVAILABLE,
      source:text(r.source)||SOURCES.NONE,
      fail_closed:r.fail_closed===true,
      reason_codes:uniqueSorted(Array.isArray(r.reason_codes)?r.reason_codes:[])
    };
  }

  function resolveHeroStrategy(input={}){
    const reasons=[];
    const activePopulation=text(input.population_id||input.populationId||input.active_population_id);

    const packIdentity=isObject(input.pack_identity)?input.pack_identity:(isObject(input.packIdentity)?input.packIdentity:(isObject(input.pack)?input.pack:null));
    const trainerManifest=isObject(input.trainer_manifest)?input.trainer_manifest:(isObject(input.population_manifest)?input.population_manifest:null);
    const candidate=isObject(input.candidate)?input.candidate:null;
    const context=isObject(input.context)?input.context:null;
    const reference=isObject(input.retained_reference)?input.retained_reference:(isObject(input.retainedReference)?input.retainedReference:(isObject(input.reference)?input.reference:null));
    let repository=isObject(input.repository)?input.repository:(isObject(input.hero_ranges)?input.hero_ranges:null);
    if(!repository&&candidate&&isObject(candidate.repository))repository=candidate.repository;
    let repositoryUsable=!!repository;
    if(repository&&HeroRanges&&typeof HeroRanges.validateRepository==='function'){
      try{HeroRanges.validateRepository(repository);}
      catch(_){repositoryUsable=false;reasons.push('REPOSITORY_INVALID');}
    }

    const admissionRoot=input.admissions!=null?input.admissions:(input.admission!=null?input.admission:null);
    let rawHeroStrategy=null;
    let rawHeroRanges=null;
    if(isObject(admissionRoot)){
      // Accept either a flat role map ({hero_strategy:...}) or a full
      // poker-scientific-component-admission/v1 document ({admissions:{...}}).
      const roleMap=isObject(admissionRoot.admissions)?admissionRoot.admissions:admissionRoot;
      rawHeroStrategy=roleMap.hero_strategy!=null?roleMap.hero_strategy:(roleMap['hero-strategy']!=null?roleMap['hero-strategy']:roleMap.heroStrategy);
      rawHeroRanges=roleMap.hero_ranges!=null?roleMap.hero_ranges:(roleMap['hero-ranges']!=null?roleMap['hero-ranges']:roleMap.heroRanges);
    }else if(admissionRoot!=null){
      rawHeroStrategy=admissionRoot;
    }
    if(input.hero_strategy_admission!=null)rawHeroStrategy=input.hero_strategy_admission;
    if(input.hero_ranges_admission!=null)rawHeroRanges=input.hero_ranges_admission;
    const heroStrategy=readAdmission(rawHeroStrategy);
    const heroRanges=readAdmission(rawHeroRanges);
    const admissionStatus=heroStrategy.status;

    if(!activePopulation){
      reasons.push('POPULATION_ID_MISSING');
      return buildResult({status:STATUSES.POPULATION_INCOMPATIBLE,source:SOURCES.NONE,activePopulation:null,identity:null,provenance:null,failClosed:true,reasons});
    }

    const bindings=populationBindings({
      repository,candidate,trainerManifest,packIdentity,admissionRoot,
      heroStrategyAdmission:heroStrategy.object,
      heroRangesAdmission:heroRanges.object,
      reference,context
    });
    const mismatches=bindings.filter(binding=>binding.population_id!==activePopulation);
    if(mismatches.length){
      reasons.push('POPULATION_ID_MISMATCH');
      for(const source of uniqueSorted(mismatches.map(mismatch=>mismatch.source)))reasons.push(`${source}_POPULATION_MISMATCH`);
      return buildResult({status:STATUSES.POPULATION_INCOMPATIBLE,source:SOURCES.NONE,activePopulation,identity:null,provenance:null,failClosed:true,reasons});
    }

    if(admissionStatus==='INCOMPATIBLE'||heroRanges.status==='INCOMPATIBLE'){
      reasons.push('ADMISSION_INCOMPATIBLE');
      if(admissionStatus==='INCOMPATIBLE')reasons.push('HERO_STRATEGY_ADMISSION_INCOMPATIBLE');
      if(heroRanges.status==='INCOMPATIBLE')reasons.push('HERO_RANGES_ADMISSION_INCOMPATIBLE');
      return buildResult({status:STATUSES.POPULATION_INCOMPATIBLE,source:SOURCES.NONE,activePopulation,identity:null,provenance:null,failClosed:true,reasons});
    }

    const candidateProblems=candidateProblemCodes(candidate);
    if(candidateProblems.length)reasons.push(...candidateProblems);
    const candidateBlocked=candidateProblems.length>0;

    const calculated=calculatedLayers(repositoryUsable?repository:null);
    const activeCalculated=calculated.filter(entry=>entry.defined>0&&!entry.inactive);
    const inactiveMetadata=calculated.filter(entry=>entry.inactive||entry.metadata_only);
    const allComplete=activeCalculated.length>0&&activeCalculated.every(entry=>entry.complete);
    const admitted=admissionStatus==='ADMISSIBLE';
    const retained=admissionStatus==='RETAIN_REFERENCE';
    const personal=personalLayers(repositoryUsable?repository:null,activePopulation);

    let status=STATUSES.UNAVAILABLE;
    let source=SOURCES.NONE;
    let failClosed=true;
    let identity=null;
    let provenance=null;

    if(admitted&&!candidateBlocked&&activeCalculated.length>0&&allComplete){
      status=STATUSES.ADMISSIBLE_CALCULATED;source=SOURCES.POPULATION;failClosed=false;
      ({identity,provenance}=calculatedResolution(input,activeCalculated,candidate,activePopulation,admissionStatus,reasons));
      reasons.push('ADMITTED_CALCULATED_STRATEGY');
    }else if(admitted&&!candidateBlocked&&activeCalculated.length>0){
      status=STATUSES.PARTIAL;source=SOURCES.POPULATION;failClosed=true;
      ({identity,provenance}=calculatedResolution(input,activeCalculated,candidate,activePopulation,admissionStatus,reasons));
      reasons.push('STRATEGY_PARTIAL_COVERAGE');
    }else if(retained){
      status=STATUSES.RETAIN_REFERENCE;source=SOURCES.POPULATION;failClosed=false;
      ({identity,provenance}=retainedResolution(input,reference,heroStrategy.object,activePopulation,reasons));
      reasons.push('RETAINED_REFERENCE');
    }else if(candidateBlocked||activeCalculated.length>0){
      status=STATUSES.UNAVAILABLE;source=SOURCES.NONE;failClosed=true;
      reasons.push('STRATEGY_NOT_ADMITTED');
      if(admissionStatus==='REJECTED')reasons.push('STRATEGY_REJECTED');
      else if(admissionStatus==='UNRESOLVED')reasons.push('STRATEGY_UNRESOLVED');
      if(!admissionStatus)reasons.push('ADMISSION_MISSING');
    }else if(inactiveMetadata.length){
      status=STATUSES.UNAVAILABLE;source=SOURCES.NONE;failClosed=true;
      reasons.push('INACTIVE_CANDIDATE_NOT_ACTIVATED');
      if(!admissionStatus)reasons.push('ADMISSION_MISSING');
    }else if(personal.available){
      status=STATUSES.PARTIAL;source=SOURCES.PERSONAL_OVERRIDE;failClosed=true;
      provenance={origin:'PERSONAL_OVERRIDE',population_id:activePopulation,context_keys:personal.context_keys};
      reasons.push('PERSONAL_OVERRIDE_NOT_POPULATION_STRATEGY');
    }else{
      status=STATUSES.UNAVAILABLE;source=SOURCES.NONE;failClosed=true;
      if(admissionStatus==='REJECTED')reasons.push('STRATEGY_REJECTED');
      else if(admissionStatus==='UNRESOLVED')reasons.push('STRATEGY_UNRESOLVED');
      else reasons.push('NO_ADMISSIBLE_STRATEGY');
      if(!admissionStatus)reasons.push('ADMISSION_MISSING');
    }

    return buildResult({status,source,activePopulation,identity,provenance,failClosed,reasons});
  }

  return {
    SCHEMA,STATUSES,SOURCES,ADMISSION_STATUSES,CANDIDATE_SCHEMA,REPOSITORY_SCHEMA,
    TRAINER_MANIFEST_SCHEMA,PACK_RUNTIME_SCHEMA,IMPORT_SCHEMA,GENERATION_MANIFEST_SCHEMA,
    identity,resolveHeroStrategy
  };
});
