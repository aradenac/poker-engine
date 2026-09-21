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
      ADMISSIBLE admission exists AND the admission is explicitly bound to the
      exact runtime calculated artifact (role, SHA-256 content identity, explicit
      provenance, candidate_id/generation_id and binding_sha256) AND its coverage
      is bounded by an explicit, authoritative required context set
      (`required_context_keys` and/or a
      poker-hero-preflop-generation-manifest/v1 with `expected_context_ids` /
      `plan_projection.ready_context_count`) that is fully covered by complete
      (169 hand classes) calculated contexts. Completeness is never inferred from
      the artifact itself: without an authoritative bound the answer is PARTIAL,
      never ADMISSIBLE_CALCULATED. A bare ADMISSIBLE token never authorizes an
      arbitrary local repository. Un-admitted, unresolved, rejected, unbound or
      inactive metadata never becomes the active strategy.
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

  function populationBindings({repository,candidate,trainerManifest,packIdentity,admissionRoot,heroStrategyAdmission,heroRangesAdmission,reference,context,generationManifest}){
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
    push('GENERATION_MANIFEST',generationManifest&&generationManifest.population_id);
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

  // #task-ewo: a repository context is only ever identified by its canonical
  // repository key, its explicit preflop_context_id and the exact generation
  // source context id recorded in the calculated layer provenance (when the
  // layer was imported from a generation). A required/authoritative context set
  // is matched against these tokens only: nothing is inferred from a "near"
  // context (fail-closed lookup).
  function contextIdentityTokens(key,node,provenance){
    const tokens=[String(key)];
    const context=isObject(node)&&isObject(node.context)?node.context:null;
    if(context){
      const preflopId=text(context.preflop_context_id);
      if(preflopId)tokens.push(preflopId);
      if(HeroRanges&&typeof HeroRanges.contextKey==='function'){
        try{tokens.push(String(HeroRanges.contextKey(context)));}catch(_){/* fall back to the raw key */}
      }
    }
    if(isObject(provenance)){
      const exact=isObject(provenance.exact_context)?provenance.exact_context:null;
      if(exact){
        const sourceContextId=text(exact.context_id);
        if(sourceContextId)tokens.push(sourceContextId);
      }
      const projection=isObject(provenance.repository_projection)?provenance.repository_projection:null;
      if(projection){
        const projectedPreflopId=text(projection.preflop_context_id);
        if(projectedPreflopId)tokens.push(projectedPreflopId);
      }
    }
    return uniqueSorted(tokens);
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
        context:isObject(node)&&isObject(node.context)?node.context:null,
        identity_tokens:contextIdentityTokens(key,node,provenance),
        defined,
        complete:defined===HAND_CLASSES_TOTAL,
        inactive,
        metadata_only:defined===0&&provenance!=null
      });
    }
    return out.sort((a,b)=>String(a.key).localeCompare(String(b.key)));
  }

  // A required context set is authoritative when it is declared explicitly
  // (`required_context_keys`) and/or derived from a
  // poker-hero-preflop-generation-manifest/v1 (`expected_context_ids` and
  // `plan_projection.ready_context_count`). Without such a bound nothing may be
  // inferred from the calculated artifact itself.
  const REQUIRED_CONTEXT_SOURCES=Object.freeze({
    UNKNOWN:'UNKNOWN',
    REQUIRED_CONTEXT_KEYS:'REQUIRED_CONTEXT_KEYS',
    GENERATION_MANIFEST:'GENERATION_MANIFEST',
    REQUIRED_CONTEXT_KEYS_AND_GENERATION_MANIFEST:'REQUIRED_CONTEXT_KEYS+GENERATION_MANIFEST'
  });

  function normalizeRequiredContextKeys(value){
    const out=[];
    const push=item=>{const normalized=text(item);if(normalized)out.push(normalized);};
    if(value==null)return out;
    if(Array.isArray(value)){for(const item of value)push(item);}
    else if(typeof value==='string'){for(const part of value.split(','))push(part);}
    return uniqueSorted(out);
  }

  function generationManifestRequirement(manifest){
    const requirement={present:false,schema:null,population_id:null,expected_context_ids:[],ready_context_count:null,reason:null};
    if(manifest==null)return requirement;
    requirement.present=true;
    if(!isObject(manifest)){requirement.reason='GENERATION_MANIFEST_INVALID';return requirement;}
    requirement.schema=text(manifest.schema)||null;
    requirement.population_id=text(manifest.population_id)||null;
    if(requirement.schema!==GENERATION_MANIFEST_SCHEMA){requirement.reason='GENERATION_MANIFEST_SCHEMA_MISMATCH';return requirement;}
    if(Array.isArray(manifest.expected_context_ids)){
      requirement.expected_context_ids=uniqueSorted(manifest.expected_context_ids.map(value=>text(value)));
    }
    const projection=isObject(manifest.plan_projection)?manifest.plan_projection:null;
    const ready=projection?Number(projection.ready_context_count):NaN;
    if(Number.isInteger(ready)&&ready>0)requirement.ready_context_count=ready;
    if(!requirement.expected_context_ids.length&&requirement.ready_context_count==null){
      requirement.reason='GENERATION_MANIFEST_COVERAGE_MISSING';
    }
    return requirement;
  }

  // Compare the active calculated contexts against the authoritative required
  // set. Only complete (169 hand classes) contexts cover a required context.
  // Without an explicit authoritative set the result is never complete; a
  // required set that is not fully covered is incomplete.
  function requiredCoverage(input,generationManifest,activeCalculated,reasons){
    const explicitKeys=normalizeRequiredContextKeys(
      input.required_context_keys!=null?input.required_context_keys:input.requiredContextKeys
    );
    const requirement=generationManifestRequirement(generationManifest);
    if(requirement.reason)reasons.push(requirement.reason);
    const manifestIds=requirement.schema===GENERATION_MANIFEST_SCHEMA?requirement.expected_context_ids:[];
    const readyContextCount=requirement.schema===GENERATION_MANIFEST_SCHEMA?requirement.ready_context_count:null;

    const requiredContextKeys=uniqueSorted([...explicitKeys,...manifestIds]);
    const requiredSetKnown=requiredContextKeys.length>0||(readyContextCount!=null&&readyContextCount>0);
    const completeContexts=activeCalculated.filter(entry=>entry.complete);

    const coveredContextKeys=[];
    const missingContextKeys=[];
    const incompleteContextKeys=[];
    for(const requiredKey of requiredContextKeys){
      const covered=completeContexts.some(entry=>entry.identity_tokens.includes(requiredKey));
      if(covered){
        coveredContextKeys.push(requiredKey);
      }else{
        missingContextKeys.push(requiredKey);
        if(activeCalculated.some(entry=>entry.identity_tokens.includes(requiredKey)))incompleteContextKeys.push(requiredKey);
      }
    }

    let required=0;
    let covered=0;
    let missing=0;
    if(requiredSetKnown){
      if(requiredContextKeys.length>0){
        required=Math.max(requiredContextKeys.length,readyContextCount||0);
        covered=coveredContextKeys.length;
      }else{
        required=readyContextCount||0;
        covered=Math.min(completeContexts.length,required);
      }
      missing=Math.max(0,required-covered);
    }

    const complete=requiredSetKnown&&missing===0&&
      missingContextKeys.length===0&&incompleteContextKeys.length===0&&
      completeContexts.length>0;

    if(!requiredSetKnown)reasons.push('REQUIRED_CONTEXT_SET_UNKNOWN');
    if(requiredSetKnown&&missingContextKeys.length)reasons.push('REQUIRED_CONTEXT_MISSING');
    if(!complete)reasons.push('COVERAGE_INCOMPLETE');

    let source=REQUIRED_CONTEXT_SOURCES.UNKNOWN;
    if(explicitKeys.length&&manifestIds.length)source=REQUIRED_CONTEXT_SOURCES.REQUIRED_CONTEXT_KEYS_AND_GENERATION_MANIFEST;
    else if(manifestIds.length||(readyContextCount!=null&&readyContextCount>0))source=REQUIRED_CONTEXT_SOURCES.GENERATION_MANIFEST;
    else if(explicitKeys.length)source=REQUIRED_CONTEXT_SOURCES.REQUIRED_CONTEXT_KEYS;

    return {
      authoritative:requiredSetKnown,
      complete,
      required,
      covered,
      missing,
      contexts:activeCalculated.length,
      defined_hand_classes:activeCalculated.reduce((sum,entry)=>sum+entry.defined,0),
      required_context_keys:requiredContextKeys,
      covered_context_keys:coveredContextKeys,
      missing_context_keys:missingContextKeys,
      incomplete_context_keys:incompleteContextKeys,
      expected_context_ids:manifestIds,
      ready_context_count:readyContextCount,
      source
    };
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

  function calculatedResolution(input,calculated,candidate,activePopulation,admissionStatus,coverage,reasons){
    const primary=calculated[0]||{};
    const provenance=isObject(primary.provenance)?primary.provenance:{};
    const layer=isObject(primary.layer)?primary.layer:{};
    const strategyVersion=token(input.strategy_version,reasons)||token(layer.version,reasons)||token(candidate&&candidate.version,reasons);
    const strategySha=hex(input.strategy_sha256)||hex(candidate&&candidate.strategy_sha256)||hex(provenance.manifest_sha256)||hex(provenance.binding_sha256)||hex(provenance.code);
    const strategyId=token(input.strategy_id,reasons)||token(candidate&&candidate.strategy_id,reasons)||token(provenance.candidate_id,reasons)||token(candidate&&candidate.candidate_id,reasons)||(activePopulation?`hero-population:${activePopulation}`:null);
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

  // #task-fnc: an ADMISSIBLE admission only authorizes the calculated strategy
  // when it is explicitly bound to the exact runtime artifact. Role, content
  // hash, candidate/generation identity, explicit provenance and binding hash
  // must all agree with the active calculated layer; otherwise the resolver
  // fails closed with a precise, deterministic reason code. A bare ADMISSIBLE
  // status token can never authorize an arbitrary local repository.
  function declaredValues(entries){
    const values=[];
    for(const [owner,key] of entries){
      if(isObject(owner)&&Object.prototype.hasOwnProperty.call(owner,key))values.push(owner[key]);
    }
    return values;
  }

  function admissionArtifactIdentity(admissionObject,reasons){
    if(!isObject(admissionObject))return null;
    const artifact=isObject(admissionObject.artifact)?admissionObject.artifact:null;
    const lineage=isObject(admissionObject.lineage)?admissionObject.lineage:null;
    const provenance=isObject(admissionObject.provenance)?admissionObject.provenance:null;
    const hashValues=declaredValues([
      [artifact,'actual_sha256'],[artifact,'declared_sha256'],
      [admissionObject,'artifact_sha256']
    ]);
    const bindingValues=declaredValues([
      [artifact,'binding_sha256'],[admissionObject,'binding_sha256']
    ]);
    const candidateValues=declaredValues([
      [admissionObject,'candidate_id'],[artifact,'candidate_id'],
      [lineage,'candidate_id']
    ]);
    const generationValues=declaredValues([
      [admissionObject,'generation_id'],[artifact,'generation_id'],
      [lineage,'generation_id']
    ]);
    return {
      role:upper(admissionObject.role).replace(/-/g,'_')||null,
      artifact,
      provenance,
      hash_values:hashValues,
      hashes:hashValues.map(hex).filter(Boolean),
      binding_values:bindingValues,
      binding_hashes:bindingValues.map(hex).filter(Boolean),
      candidate_values:candidateValues,
      candidate_ids:candidateValues.map(value=>token(value,reasons)).filter(Boolean),
      generation_values:generationValues,
      generation_ids:generationValues.map(value=>token(value,reasons)).filter(Boolean)
    };
  }

  function bindAdmittedArtifact(admissionObject,candidate,activeCalculated,input,activePopulation,reasons){
    let bound=true;
    const fail=code=>{reasons.push(code);bound=false;};
    if(!isObject(admissionObject)){fail('ADMISSION_ARTIFACT_MISSING');return false;}
    const admitted=admissionArtifactIdentity(admissionObject,reasons);
    // (a) role identity, (b) content/hash identity.
    if(!admitted.artifact&&hex(admissionObject.artifact_sha256)==null)fail('ADMISSION_ARTIFACT_MISSING');
    if(admitted.role!=='HERO_STRATEGY')fail('ADMISSION_ROLE_MISMATCH');
    if(admitted.hash_values.length===0||admitted.hash_values.some(value=>!hex(value)))fail('ADMISSION_HASH_MISSING');
    const admittedHashes=new Set(admitted.hashes);
    if(admittedHashes.size>1)fail('ADMISSION_HASH_MISMATCH');
    const admittedHash=admittedHashes.size===1?[...admittedHashes][0]:null;
    const admittedBindings=new Set(admitted.binding_hashes);
    const admittedCandidates=new Set(admitted.candidate_ids);
    const admittedGenerations=new Set(admitted.generation_ids);

    // (c) Admission provenance is mandatory and must bind both the source
    // population and the same exact artifact identities declared by the
    // admission. Merely attaching an unrelated provenance object is not enough.
    if(!admitted.provenance){
      fail('ADMISSION_PROVENANCE_MISSING');
    }else{
      const populationValues=declaredValues([
        [admitted.provenance,'source_population_id'],
        [admitted.provenance,'population_id']
      ]).map(text).filter(Boolean);
      const populations=new Set(populationValues);
      const provenanceManifest=hex(admitted.provenance.manifest_sha256);
      const provenanceBinding=hex(admitted.provenance.binding_sha256);
      const provenanceCandidate=token(admitted.provenance.candidate_id,reasons);
      const provenanceGeneration=token(admitted.provenance.generation_id,reasons);
      if(
        populations.size!==1||[...populations][0]!==activePopulation||
        !provenanceManifest||provenanceManifest!==admittedHash||
        !provenanceBinding||admittedBindings.size!==1||provenanceBinding!==[...admittedBindings][0]||
        !provenanceCandidate||admittedCandidates.size!==1||provenanceCandidate!==[...admittedCandidates][0]||
        !provenanceGeneration||admittedGenerations.size!==1||provenanceGeneration!==[...admittedGenerations][0]
      )fail('ADMISSION_PROVENANCE_MISMATCH');
    }

    // Runtime artifact identity, derived from every active calculated layer.
    const manifestHashes=new Set();
    const bindingHashes=new Set();
    const layerCandidates=new Set();
    const layerGenerations=new Set();
    let unbound=false;
    let layerCandidateMissing=false;
    let layerGenerationMissing=false;
    for(const entry of activeCalculated){
      const provenance=isObject(entry.provenance)?entry.provenance:null;
      const manifest=hex(provenance&&provenance.manifest_sha256);
      if(!provenance){unbound=true;layerCandidateMissing=true;layerGenerationMissing=true;continue;}
      if(manifest)manifestHashes.add(manifest);
      else unbound=true;
      const binding=hex(provenance.binding_sha256);
      if(binding)bindingHashes.add(binding);
      else unbound=true;
      const layerCandidate=token(provenance.candidate_id,reasons);
      if(layerCandidate)layerCandidates.add(layerCandidate);
      else layerCandidateMissing=true;
      const layerGeneration=token(provenance.generation_id,reasons);
      if(layerGeneration)layerGenerations.add(layerGeneration);
      else layerGenerationMissing=true;
    }
    if(unbound||manifestHashes.size===0)fail('REPOSITORY_NOT_BOUND_TO_ADMISSION');
    if(manifestHashes.size>1)fail('ADMISSION_HASH_MISMATCH');
    const layerManifest=manifestHashes.size===1?[...manifestHashes][0]:null;

    // (b) The admitted content hash must equal the runtime calculated hash and
    // any explicit candidate/input hash token. Otherwise the admission is bound
    // to a different artifact than the one used at runtime.
    if(admittedHash&&layerManifest&&admittedHash!==layerManifest)fail('ADMISSION_HASH_MISMATCH');
    if(isObject(candidate)&&Object.prototype.hasOwnProperty.call(candidate,'strategy_sha256')&&!hex(candidate.strategy_sha256))fail('ADMISSION_HASH_MISMATCH');
    for(const observed of [hex(candidate&&candidate.strategy_sha256),hex(input&&input.strategy_sha256)]){
      if(observed&&admittedHash&&observed!==admittedHash)fail('ADMISSION_HASH_MISMATCH');
      if(observed&&layerManifest&&observed!==layerManifest)fail('ADMISSION_HASH_MISMATCH');
    }

    // (e) The relevant binding hash must be present on both sides and agree.
    if(bindingHashes.size>1)fail('ADMISSION_BINDING_MISMATCH');
    const layerBinding=bindingHashes.size===1?[...bindingHashes][0]:null;
    if(!layerBinding)fail('REPOSITORY_NOT_BOUND_TO_ADMISSION');
    if(admitted.binding_values.length===0||admitted.binding_values.some(value=>!hex(value)))fail('ADMISSION_BINDING_MISMATCH');
    if(admittedBindings.size!==1)fail('ADMISSION_BINDING_MISMATCH');
    const admittedBinding=admittedBindings.size===1?[...admittedBindings][0]:null;
    if(layerBinding&&admittedBinding&&admittedBinding!==layerBinding)fail('ADMISSION_BINDING_MISMATCH');

    // (d) candidate_id / generation_id must identify the calculated layer.
    if(layerCandidateMissing||layerCandidates.size>1)fail('ADMISSION_CANDIDATE_MISMATCH');
    const layerCandidate=layerCandidates.size===1?[...layerCandidates][0]:null;
    const candidateObjectId=token(candidate&&candidate.candidate_id,reasons);
    if(admitted.candidate_values.length===0||admittedCandidates.size!==1)fail('ADMISSION_CANDIDATE_MISMATCH');
    const admittedCandidate=admittedCandidates.size===1?[...admittedCandidates][0]:null;
    if(!layerCandidate||admittedCandidate!==layerCandidate)fail('ADMISSION_CANDIDATE_MISMATCH');
    if(candidate&&text(candidate.candidate_id)&&(!candidateObjectId||candidateObjectId!==layerCandidate))fail('ADMISSION_CANDIDATE_MISMATCH');

    if(layerGenerationMissing||layerGenerations.size>1)fail('ADMISSION_GENERATION_MISMATCH');
    const layerGeneration=layerGenerations.size===1?[...layerGenerations][0]:null;
    if(admitted.generation_values.length===0||admittedGenerations.size!==1)fail('ADMISSION_GENERATION_MISMATCH');
    const admittedGeneration=admittedGenerations.size===1?[...admittedGenerations][0]:null;
    if(!layerGeneration||admittedGeneration!==layerGeneration)fail('ADMISSION_GENERATION_MISMATCH');
    const candidateGeneration=token(candidate&&candidate.generation_id,reasons);
    if(candidate&&text(candidate.generation_id)&&(!candidateGeneration||candidateGeneration!==layerGeneration))fail('ADMISSION_GENERATION_MISMATCH');

    return bound;
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
    const generationManifest=isObject(input.generation_manifest)?input.generation_manifest:(isObject(input.generationManifest)?input.generationManifest:null);
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
      reference,context,generationManifest
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
    const admitted=admissionStatus==='ADMISSIBLE';
    const retained=admissionStatus==='RETAIN_REFERENCE';
    const personal=personalLayers(repositoryUsable?repository:null,activePopulation);

    // #task-fnc: an ADMISSIBLE status only authorizes the calculated branch when
    // the admission is explicitly bound to the exact runtime calculated artifact.
    // A bare status token (or a divergent hash/candidate/generation/binding) fails
    // closed and never yields a strategy identity.
    const admissionBound=admitted&&activeCalculated.length>0
      ?bindAdmittedArtifact(heroStrategy.object,candidate,activeCalculated,input,activePopulation,reasons)
      :false;
    const admittedBound=admitted&&admissionBound;

    let status=STATUSES.UNAVAILABLE;
    let source=SOURCES.NONE;
    let failClosed=true;
    let identity=null;
    let provenance=null;

    if(admittedBound&&!candidateBlocked&&activeCalculated.length>0){
      // #task-ewo: completeness is never self-referential. The calculated
      // artifact is only complete when an explicit authoritative required
      // context set is fully covered by complete (169 hand classes) contexts.
      const coverage=requiredCoverage(input,generationManifest,activeCalculated,reasons);
      ({identity,provenance}=calculatedResolution(input,activeCalculated,candidate,activePopulation,admissionStatus,coverage,reasons));
      if(coverage.complete){
        status=STATUSES.ADMISSIBLE_CALCULATED;source=SOURCES.POPULATION;failClosed=false;
        reasons.push('ADMITTED_CALCULATED_STRATEGY');
      }else{
        status=STATUSES.PARTIAL;source=SOURCES.POPULATION;failClosed=true;
        reasons.push('STRATEGY_PARTIAL_COVERAGE');
      }
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
