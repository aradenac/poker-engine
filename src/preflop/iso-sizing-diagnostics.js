(function(root,factory){
  const Decision=(typeof module==='object'&&module.exports)?require('./decision.js'):(root&&root.PokerPreflopDecision);
  const api=factory(Decision);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerIsoSizingDiagnostics=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(Decision){
  'use strict';

  const SCHEMA='poker-preflop-iso-sizing-diagnostics/v1';
  const RESOLVED_SCHEMA='poker-preflop-iso-sizing-diagnostics-resolved/v1';
  const WORLDS_SCHEMA='poker-preflop-iso-sizing-diagnostic-worlds/v1';
  const PAIRED_SCHEMA='paired-adaptive-preflop-ev/v1';
  const POSTERIOR_SCHEMA='poker-opponent-posterior-range/v1';
  const PAIRING_CONTRACT='DECISION_SAMPLE_COMMON_RANDOM_NUMBERS_V1';
  const SELECTION_POLICY='CANONICAL_MAX_EV_ONLY';
  const SCIENTIFIC_EFFECT='NONE_INTEGRATION_CONTRACT_ONLY';
  const EPS=1e-9;
  const POSITIONS=['LJ','HJ','CO','BTN','SB','BB','SB_BTN'];
  const RESPONSES=['CALL','3BET','JAM'];
  const AVAILABLE='AVAILABLE', NOT_APPLICABLE='NOT_APPLICABLE', UNSUPPORTED='UNSUPPORTED';
  const BACKOFF_LEVELS=['EXACT','POSITION','FAMILY','POPULATION','UNSUPPORTED'];
  const QUALITY=['HIGH','MEDIUM','LOW','UNSUPPORTED'];

  class IsoSizingDiagnosticsError extends Error{
    constructor(code,message){super(message);this.name='IsoSizingDiagnosticsError';this.code=code;}
  }
  const fail=(code,message)=>{throw new IsoSizingDiagnosticsError(code,message);};
  const clone=v=>v==null?v:JSON.parse(JSON.stringify(v));
  const text=v=>v==null?'':String(v).trim();
  const finite=(v,name)=>{const n=Number(v);if(!Number.isFinite(n))fail('INVALID_NUMBER',name+' must be finite');return n;};
  const nonneg=(v,name)=>{const n=finite(v,name);if(n<-EPS)fail('INVALID_NUMBER',name+' must be >= 0');return Math.max(0,n);};
  const integer=(v,name)=>{const n=Number(v);if(!Number.isInteger(n)||n<0)fail('INVALID_COUNT',name+' must be a non-negative integer');return n;};
  const probability=(v,name)=>{const n=finite(v,name);if(n<-EPS||n>1+EPS)fail('INVALID_PROBABILITY',name+' must be within [0,1]');return Math.min(1,Math.max(0,n));};
  const approx=(a,b,tol=1e-9)=>Math.abs(Number(a)-Number(b))<=tol;
  function stableStringify(v){
    if(v===null||typeof v!=='object')return JSON.stringify(v);
    if(Array.isArray(v))return '['+v.map(stableStringify).join(',')+']';
    return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+stableStringify(v[k])).join(',')+'}';
  }

  function normalizeCanonicalAlternative(row){
    if(!row||typeof row!=='object')fail('CANONICAL_DECISION_INVALID','alternative must be an object');
    const id=text(row.id);if(!id)fail('CANONICAL_DECISION_INVALID','alternative.id is required');
    const action=text(row.action).toUpperCase();if(!action)fail('CANONICAL_DECISION_INVALID',id+' action is required');
    const target=(row.target_total_bb!=null)
      ?finite(row.target_total_bb,id+'.target_total_bb')
      :(row.target_sizing&&row.target_sizing.target_total_bb!=null?finite(row.target_sizing.target_total_bb,id+'.target_sizing.target_total_bb'):null);
    const incremental=row.incremental_cost_bb==null?null:finite(row.incremental_cost_bb,id+'.incremental_cost_bb');
    const ev=row.ev_bb==null?null:finite(row.ev_bb,id+'.ev_bb');
    return {
      id,action,target_total_bb:target,incremental_cost_bb:incremental,ev_bb:ev,
      uncertainty:clone(row.uncertainty==null?null:row.uncertainty),
      support:clone(row.support==null?null:row.support),
      comparable:row.comparable==null?true:Boolean(row.comparable)
    };
  }

  function canonicalDecision(decision){
    if(!decision||decision.schema!=='poker-preflop-decision/v1')fail('CANONICAL_DECISION_INVALID','expected poker-preflop-decision/v1');
    if(!Array.isArray(decision.alternatives)||!decision.alternatives.length)fail('CANONICAL_DECISION_INVALID','alternatives are required');
    const alternatives=decision.alternatives.map(normalizeCanonicalAlternative);
    const ids=new Set();
    for(const row of alternatives){if(ids.has(row.id))fail('CANONICAL_DECISION_INVALID','duplicate alternative '+row.id);ids.add(row.id);}
    if(Decision&&typeof Decision.validateDecision==='function'&&!decision.contract_profile){
      try{Decision.validateDecision(decision);}catch(err){fail('CANONICAL_DECISION_INVALID',err.message);}
    }
    const selectedId=text(decision.selected_id)||text(decision.recommendation_admissibility&&decision.recommendation_admissibility.selected_alternative_id)||null;
    if(selectedId&&!ids.has(selectedId))fail('CANONICAL_DECISION_INVALID','selected alternative is absent');
    return {
      schema:decision.schema,
      decision_id:text(decision.decision_id)||null,
      context_id:text(decision.context_id)||null,
      public_state_fingerprint:text(decision.public_state_fingerprint)||null,
      selected_id:selectedId,
      alternatives,
      by_id:Object.fromEntries(alternatives.map(x=>[x.id,x]))
    };
  }

  function validateSupport(value,status,name){
    if(status===NOT_APPLICABLE){
      if(value!==null)fail('SUPPORT_NOT_APPLICABLE',name+' support must be null');
      return null;
    }
    if(!value||typeof value!=='object')fail('SUPPORT_INVALID',name+' support is required');
    const observations=integer(value.observations,name+'.support.observations');
    const ess=nonneg(value.effective_sample_size,name+'.support.effective_sample_size');
    const backoff=text(value.backoff_level).toUpperCase();
    const quality=text(value.quality).toUpperCase();
    const source=text(value.source);
    if(!BACKOFF_LEVELS.includes(backoff))fail('SUPPORT_INVALID',name+' invalid backoff_level');
    if(!QUALITY.includes(quality))fail('SUPPORT_INVALID',name+' invalid quality');
    if(!source)fail('SUPPORT_INVALID',name+' support.source is required');
    if(status===AVAILABLE&&(backoff==='UNSUPPORTED'||quality==='UNSUPPORTED'))fail('SUPPORT_INVALID',name+' AVAILABLE cannot have unsupported support');
    if(status===UNSUPPORTED&&(backoff!=='UNSUPPORTED'||quality!=='UNSUPPORTED'))fail('SUPPORT_INVALID',name+' UNSUPPORTED must expose unsupported support');
    return {observations,effective_sample_size:ess,backoff_level:backoff,quality,source};
  }

  function validatePosteriorRef(ref,{position,response,name}){
    if(!ref||typeof ref!=='object')fail('POSTERIOR_REF_INVALID',name+' posterior reference is required');
    const required=['ref_id','schema','hand_id','step_id','public_state_fingerprint','player','position','identity','moment','public_action','status','distribution_fingerprint','source_fingerprint'];
    for(const key of required)if(!Object.prototype.hasOwnProperty.call(ref,key))fail('POSTERIOR_REF_INVALID',name+' posterior.'+key+' is required');
    if(!text(ref.ref_id)||ref.schema!==POSTERIOR_SCHEMA)fail('POSTERIOR_REF_INVALID',name+' posterior must bind '+POSTERIOR_SCHEMA);
    if(!text(ref.hand_id)||ref.step_id==null||!text(ref.public_state_fingerprint)||!text(ref.player)||!text(ref.position))fail('POSTERIOR_REF_INVALID',name+' posterior runtime identity is incomplete');
    const identity=ref.identity;
    if(!identity||typeof identity!=='object')fail('POSTERIOR_REF_INVALID',name+' posterior.identity is required');
    const identityKeys=['population_id','model_id','model_version','source_id'];
    if(Object.keys(identity).sort().join('|')!==identityKeys.sort().join('|')||identityKeys.some(key=>!text(identity[key])))fail('POSTERIOR_REF_INVALID',name+' posterior identity must match #320 population/model/source identity');
    if(text(ref.position).toUpperCase()!==position)fail('POSTERIOR_REF_INVALID',name+' posterior position mismatch');
    if(text(ref.moment).toUpperCase()!=='AFTER_ACTION')fail('POSTERIOR_REF_INVALID',name+' posterior moment must be AFTER_ACTION');
    if(!ref.public_action||typeof ref.public_action!=='object'||text(ref.public_action.action).toUpperCase()!==response)fail('POSTERIOR_REF_INVALID',name+' posterior public_action mismatch');
    if(!text(ref.public_state_fingerprint).startsWith('preflop-public:'))fail('POSTERIOR_REF_INVALID',name+' posterior must bind a public-state fingerprint');
    const status=text(ref.status).toUpperCase();
    if(!['AVAILABLE','UNSUPPORTED','INVALID'].includes(status))fail('POSTERIOR_REF_INVALID',name+' posterior status invalid');
    if(status==='AVAILABLE'&&!/^sha256:[a-f0-9]{64}$/.test(text(ref.distribution_fingerprint)))fail('POSTERIOR_REF_INVALID',name+' AVAILABLE posterior distribution_fingerprint must be sha256');
    if(status!=='AVAILABLE'&&ref.distribution_fingerprint!==null)fail('POSTERIOR_REF_INVALID',name+' fail-closed posterior distribution_fingerprint must be null');
    if(!text(ref.source_fingerprint))fail('POSTERIOR_REF_INVALID',name+' posterior source_fingerprint is required');
    return clone(ref);
  }

  function validateAvailable(row,name){
    const p=row.caller_partition;
    if(!p||typeof p!=='object')fail('CALLER_PARTITION_INVALID',name+' caller_partition is required');
    const partition={
      all_fold:probability(p.all_fold,name+'.caller_partition.all_fold'),
      exactly_1_caller:probability(p.exactly_1_caller,name+'.caller_partition.exactly_1_caller'),
      exactly_2_callers:probability(p.exactly_2_callers,name+'.caller_partition.exactly_2_callers'),
      three_plus_callers:probability(p.three_plus_callers,name+'.caller_partition.three_plus_callers')
    };
    const total=Object.values(partition).reduce((s,x)=>s+x,0);
    if(!approx(total,1,1e-9))fail('CALLER_PARTITION_INVALID',name+' caller probabilities must sum to 1, got '+total);
    const expected=nonneg(row.expected_callers,name+'.expected_callers');
    const pAgg=probability(row.p_3bet_or_jam,name+'.p_3bet_or_jam');
    if(pAgg>1-partition.all_fold+EPS)fail('CALLER_PARTITION_INVALID',name+' p_3bet_or_jam cannot exceed P(any continuer)');
    const sampleCount=integer(row.sample_count,name+'.sample_count');
    const worldCount=integer(row.world_count,name+'.world_count');
    if(sampleCount<1||worldCount<1||sampleCount!==worldCount)fail('WORLD_ACCOUNTING_INVALID',name+' AVAILABLE requires equal positive sample/world counts');

    if(!Array.isArray(row.continuing_positions))fail('CONTINUING_POSITIONS_INVALID',name+' continuing_positions must be an array');
    const seenPos=new Set();
    let positionSum=0;
    const positions=row.continuing_positions.map((entry,index)=>{
      const position=text(entry&&entry.position).toUpperCase();
      if(!POSITIONS.includes(position)||seenPos.has(position))fail('CONTINUING_POSITIONS_INVALID',name+' invalid/duplicate position '+position);
      seenPos.add(position);
      const prob=probability(entry.probability,name+'.continuing_positions['+index+'].probability');
      positionSum+=prob;
      return {position,probability:prob};
    });
    if(!approx(positionSum,expected,1e-9))fail('CONTINUING_POSITIONS_INVALID',name+' sum(position probabilities) must equal expected_callers');

    if(!Array.isArray(row.posterior_refs))fail('POSTERIOR_REF_INVALID',name+' posterior_refs must be an array');
    const seenPosterior=new Set();
    const posteriorRefs=row.posterior_refs.map((entry,index)=>{
      const position=text(entry&&entry.position).toUpperCase();
      const response=text(entry&&entry.response).toUpperCase();
      if(!POSITIONS.includes(position)||!RESPONSES.includes(response))fail('POSTERIOR_REF_INVALID',name+' invalid posterior response identity');
      const key=position+'|'+response;if(seenPosterior.has(key))fail('POSTERIOR_REF_INVALID',name+' duplicate posterior '+key);seenPosterior.add(key);
      const responseProbability=probability(entry.response_probability,name+'.posterior_refs['+index+'].response_probability');
      const ref=validatePosteriorRef(entry.ref,{position,response,name});
      return {position,response,response_probability:responseProbability,ref};
    });

    for(const pos of positions){
      const sum=posteriorRefs.filter(x=>x.position===pos.position).reduce((s,x)=>s+x.response_probability,0);
      if(!approx(sum,pos.probability,1e-9))fail('POSTERIOR_REF_INVALID',name+' posterior response probabilities must sum to position continuation probability for '+pos.position);
    }
    const agg=posteriorRefs.filter(x=>x.response==='3BET'||x.response==='JAM').reduce((s,x)=>s+x.response_probability,0);
    if(agg+EPS<pAgg)fail('POSTERIOR_REF_INVALID',name+' posterior 3bet/jam marginals cannot be below event probability');

    return {partition,expected,pAgg,sampleCount,worldCount,positions,posteriorRefs};
  }

  function validateArtifact(artifact,decision){
    if(!artifact||artifact.schema!==SCHEMA)fail('SCHEMA_MISMATCH','expected '+SCHEMA);
    if(artifact.selection_contract==null||artifact.selection_contract.mode!==SELECTION_POLICY||artifact.selection_contract.diagnostics_can_select!==false){
      fail('SELECTION_CONTRACT_INVALID','diagnostics must be explanatory and canonical max-EV selection only');
    }
    if(artifact.information_boundary==null||artifact.information_boundary.future_cards_consumed!==false||artifact.information_boundary.opponent_hole_cards_consumed!==false){
      fail('INFORMATION_BOUNDARY_INVALID','future/private information must be false');
    }
    const canonical=canonicalDecision(decision);
    const ref=artifact.decision_ref||{};
    if(ref.canonical_schema!=='poker-preflop-decision/v1')fail('DECISION_REF_MISMATCH','canonical schema mismatch');
    if((ref.context_id||null)!==(canonical.context_id||null))fail('DECISION_REF_MISMATCH','context_id mismatch');
    if(ref.decision_id!=null&&(ref.decision_id||null)!==(canonical.decision_id||null))fail('DECISION_REF_MISMATCH','decision_id mismatch');

    const forbidden=['selected_id','recommended_alternative_id','best_alternative_id','ranking','scores'];
    for(const key of forbidden)if(Object.prototype.hasOwnProperty.call(artifact,key))fail('DIAGNOSTIC_SELECTION_FORBIDDEN','artifact must not contain '+key);

    if(!Array.isArray(artifact.alternatives))fail('ALTERNATIVES_INVALID','alternatives must be an array');
    const rows=new Map();
    for(const raw of artifact.alternatives){
      const id=text(raw&&raw.alternative_id);if(!id||rows.has(id))fail('ALTERNATIVES_INVALID','invalid/duplicate diagnostic alternative '+id);
      const alt=canonical.by_id[id];if(!alt)fail('ALTERNATIVE_REF_MISMATCH','diagnostic alternative '+id+' absent from canonical decision');
      const status=text(raw.status).toUpperCase();
      if(![AVAILABLE,NOT_APPLICABLE,UNSUPPORTED].includes(status))fail('ALTERNATIVE_STATUS_INVALID',id+' invalid status');
      if(alt.action==='ISO'){
        if(status===NOT_APPLICABLE)fail('ALTERNATIVE_STATUS_INVALID',id+' ISO diagnostics cannot be NOT_APPLICABLE');
      }else if(status!==NOT_APPLICABLE){
        fail('ALTERNATIVE_STATUS_INVALID',id+' non-ISO diagnostic must be NOT_APPLICABLE');
      }

      for(const key of ['action','target_total_bb','target_sizing','incremental_cost_bb','ev_bb','uncertainty']){
        if(Object.prototype.hasOwnProperty.call(raw,key))fail('CANONICAL_FIELD_DUPLICATION',id+' diagnostics must not duplicate '+key);
      }

      const support=validateSupport(raw.support===undefined?null:raw.support,status,id);
      let normalized;
      if(status===AVAILABLE){
        const v=validateAvailable(raw,id);
        normalized={
          alternative_id:id,status,
          caller_partition:v.partition,
          expected_callers:v.expected,
          p_3bet_or_jam:v.pAgg,
          continuing_positions:v.positions,
          posterior_refs:v.posteriorRefs,
          sample_count:v.sampleCount,world_count:v.worldCount,
          support,
          provenance:clone(raw.provenance||{})
        };
      }else{
        for(const key of ['caller_partition','expected_callers','p_3bet_or_jam','continuing_positions','posterior_refs']){
          if(raw[key]!==null)fail('NON_AVAILABLE_METRICS_INVALID',id+' '+key+' must be null for '+status);
        }
        if(integer(raw.sample_count,id+'.sample_count')!==0||integer(raw.world_count,id+'.world_count')!==0)fail('WORLD_ACCOUNTING_INVALID',id+' non-available diagnostics require zero counts');
        normalized={
          alternative_id:id,status,
          caller_partition:null,expected_callers:null,p_3bet_or_jam:null,
          continuing_positions:null,posterior_refs:null,
          sample_count:0,world_count:0,
          support,
          provenance:clone(raw.provenance||{})
        };
      }
      if(normalized.provenance.scientific_effect!==SCIENTIFIC_EFFECT)fail('PROVENANCE_INVALID',id+' scientific_effect mismatch');
      if(normalized.provenance.same_worlds_as_ev!==true&&status===AVAILABLE)fail('PROVENANCE_INVALID',id+' AVAILABLE must assert same_worlds_as_ev');
      rows.set(id,normalized);
    }
    const expectedIds=canonical.alternatives.map(x=>x.id);
    if(rows.size!==expectedIds.length||expectedIds.some(id=>!rows.has(id)))fail('ALTERNATIVES_INVALID','diagnostics must cover every canonical alternative exactly once');
    return {canonical,rows};
  }

  function resolveAgainstDecision(artifact,decision){
    const {canonical,rows}=validateArtifact(artifact,decision);
    return {
      schema:RESOLVED_SCHEMA,
      canonical_decision_schema:'poker-preflop-decision/v1',
      selection_source:'CANONICAL_DECISION_ONLY',
      selected_alternative_id:canonical.selected_id,
      alternatives:canonical.alternatives.map(alt=>({
        alternative_id:alt.id,
        action:alt.action,
        target_total_bb:alt.target_total_bb,
        incremental_cost_bb:alt.incremental_cost_bb,
        ev_bb:alt.ev_bb,
        uncertainty:clone(alt.uncertainty),
        diagnostic:clone(rows.get(alt.id))
      }))
    };
  }

  function validateWorlds(worlds){
    if(!worlds||worlds.schema!==WORLDS_SCHEMA)fail('WORLDS_SCHEMA_MISMATCH','expected '+WORLDS_SCHEMA);
    const synthetic=worlds.synthetic_fixture===true;
    const scientific=worlds.synthetic_fixture===false;
    if(!synthetic&&!scientific)fail('EXECUTION_BOUNDARY_INVALID','synthetic_fixture must be explicit');
    if(!worlds.support_by_alternative||typeof worlds.support_by_alternative!=='object')fail('SUPPORT_INVALID','support_by_alternative is required');
    if(!worlds.alternatives||typeof worlds.alternatives!=='object')fail('WORLDS_INVALID','alternatives observations are required');
    if(!worlds.posterior_catalog||typeof worlds.posterior_catalog!=='object')fail('POSTERIOR_REF_INVALID','posterior_catalog is required');
    if(!worlds.provenance||worlds.provenance.scientific_effect!==SCIENTIFIC_EFFECT||worlds.provenance.synthetic_fixture!==synthetic)fail('PROVENANCE_INVALID','integration-contract provenance mismatch');
    const boundary=worlds.execution_boundary||{};
    if(scientific){
      if(text(boundary.mode).toUpperCase()!=='SCIENTIFIC'||text(boundary.model_a_admission_status).toUpperCase()!=='ADMITTED_FOR_SIZING_EV'){
        fail('SCIENTIFIC_PROVIDER_NOT_ADMITTED','non-synthetic diagnostics require ADMITTED_FOR_SIZING_EV');
      }
    }else if(text(boundary.mode).toUpperCase()!=='NON_SCIENTIFIC'){
      fail('EXECUTION_BOUNDARY_INVALID','synthetic diagnostics require NON_SCIENTIFIC execution mode');
    }
    return worlds;
  }

  function bridgePairedResult({decision,paired_result,diagnostic_worlds}={}){
    const canonical=canonicalDecision(decision);
    if(!paired_result||paired_result.schema!==PAIRED_SCHEMA)fail('PAIRED_SCHEMA_MISMATCH','expected '+PAIRED_SCHEMA);
    if(!paired_result.search||paired_result.search.pairing_contract!==PAIRING_CONTRACT)fail('PAIRING_CONTRACT_MISMATCH','paired CRN contract is required');
    if(!paired_result.alternatives||typeof paired_result.alternatives!=='object')fail('PAIRED_RESULT_INVALID','paired alternatives are required');
    const worlds=validateWorlds(diagnostic_worlds);
    const fingerprints=paired_result.search.world_fingerprints_sha256||{};
    const pairedDecisionId=text(paired_result.search.decision_id);
    if(!pairedDecisionId)fail('PAIRED_RESULT_INVALID','paired decision_id is required');

    const artifact={
      schema:SCHEMA,
      decision_ref:{
        canonical_schema:'poker-preflop-decision/v1',
        decision_id:canonical.decision_id,
        context_id:canonical.context_id
      },
      selection_contract:{mode:SELECTION_POLICY,diagnostics_can_select:false},
      bridge:{
        source_schema:PAIRED_SCHEMA,
        source_mode:text(paired_result.mode),
        pairing_contract:PAIRING_CONTRACT,
        paired_decision_id:pairedDecisionId,
        same_worlds_for_ev_and_diagnostics:true,
        world_fingerprint_match:'EXACT_SAMPLE_INDEX_AND_SHA256'
      },
      information_boundary:{future_cards_consumed:false,opponent_hole_cards_consumed:false},
      alternatives:[]
    };

    for(const alt of canonical.alternatives){
      const paired=paired_result.alternatives[alt.id];
      if(!paired)fail('PAIRED_ALTERNATIVE_MISSING',alt.id);
      if(alt.ev_bb!=null&&!approx(alt.ev_bb,finite(paired.ev_bb,alt.id+'.paired.ev_bb'),1e-9))fail('PAIRED_EV_MISMATCH',alt.id+' canonical EV differs from paired EV');

      if(alt.action!=='ISO'){
        if(Object.prototype.hasOwnProperty.call(worlds.alternatives,alt.id)&&Array.isArray(worlds.alternatives[alt.id])&&worlds.alternatives[alt.id].length){
          fail('NON_ISO_WORLD_OBSERVATIONS',alt.id+' must not carry iso-sizing world observations');
        }
        artifact.alternatives.push({
          alternative_id:alt.id,status:NOT_APPLICABLE,
          caller_partition:null,expected_callers:null,p_3bet_or_jam:null,
          continuing_positions:null,posterior_refs:null,
          sample_count:0,world_count:0,support:null,
          provenance:{scientific_effect:SCIENTIFIC_EFFECT,same_worlds_as_ev:false,source_mode:text(paired_result.mode),sample_indices:[]}
        });
        continue;
      }

      const observations=worlds.alternatives[alt.id];
      if(!Array.isArray(observations)||!observations.length)fail('ISO_WORLD_OBSERVATIONS_MISSING',alt.id);
      const expectedSamples=integer(paired.samples,alt.id+'.paired.samples');
      const rollouts=integer(paired.rollouts,alt.id+'.paired.rollouts');
      if(expectedSamples!==rollouts||observations.length!==rollouts||rollouts<1)fail('WORLD_ACCOUNTING_INVALID',alt.id+' observations must equal positive paired samples/rollouts');
      const seenIndices=new Set(), positionCounts=new Map(), responseCounts=new Map();
      let allFold=0,one=0,two=0,threePlus=0,totalCallers=0,aggressiveSamples=0;
      const perAltFingerprints={};

      for(const obs of observations){
        const index=integer(obs.sample_index,alt.id+'.sample_index');
        if(seenIndices.has(index))fail('WORLD_ACCOUNTING_INVALID',alt.id+' duplicate sample_index '+index);seenIndices.add(index);
        const actual=text(obs.world_fingerprint_sha256);
        const expected=text(fingerprints[String(index)]);
        if(!expected||actual!==expected)fail('WORLD_FINGERPRINT_MISMATCH',alt.id+' sample '+index);
        perAltFingerprints[String(index)]=actual;
        if(!Array.isArray(obs.continuers))fail('WORLDS_INVALID',alt.id+' continuers must be an array');
        const seenPositions=new Set();
        let aggressive=false;
        for(const continuer of obs.continuers){
          const position=text(continuer.position).toUpperCase();
          const response=text(continuer.response).toUpperCase();
          const refId=text(continuer.posterior_ref_id);
          if(!POSITIONS.includes(position)||!RESPONSES.includes(response)||seenPositions.has(position))fail('WORLDS_INVALID',alt.id+' invalid/duplicate continuer '+position);
          seenPositions.add(position);
          const ref=worlds.posterior_catalog[refId];
          validatePosteriorRef(ref,{position,response,name:alt.id});
          positionCounts.set(position,(positionCounts.get(position)||0)+1);
          const key=position+'|'+response;
          const old=responseCounts.get(key);
          if(old&&stableStringify(old.ref)!==stableStringify(ref))fail('POSTERIOR_REF_DRIFT',alt.id+' '+key+' posterior changed across paired worlds');
          responseCounts.set(key,{count:(old?old.count:0)+1,ref:clone(ref)});
          if(response==='3BET'||response==='JAM')aggressive=true;
        }
        const n=obs.continuers.length;totalCallers+=n;
        if(n===0)allFold++;else if(n===1)one++;else if(n===2)two++;else threePlus++;
        if(aggressive)aggressiveSamples++;
      }

      const n=observations.length;
      const continuingPositions=[...positionCounts.entries()].sort((a,b)=>POSITIONS.indexOf(a[0])-POSITIONS.indexOf(b[0])).map(([position,count])=>({position,probability:count/n}));
      const posteriorRefs=[...responseCounts.entries()].sort((a,b)=>a[0].localeCompare(b[0])).map(([key,value])=>{
        const [position,response]=key.split('|');
        return {position,response,response_probability:value.count/n,ref:value.ref};
      });
      artifact.alternatives.push({
        alternative_id:alt.id,status:AVAILABLE,
        caller_partition:{all_fold:allFold/n,exactly_1_caller:one/n,exactly_2_callers:two/n,three_plus_callers:threePlus/n},
        expected_callers:totalCallers/n,
        p_3bet_or_jam:aggressiveSamples/n,
        continuing_positions:continuingPositions,
        posterior_refs:posteriorRefs,
        sample_count:n,world_count:n,
        support:clone(worlds.support_by_alternative[alt.id]),
        provenance:{
          scientific_effect:SCIENTIFIC_EFFECT,
          same_worlds_as_ev:true,
          source_mode:text(paired_result.mode),
          sample_indices:[...seenIndices].sort((a,b)=>a-b),
          world_fingerprints_sha256:perAltFingerprints,
          synthetic_fixture:worlds.synthetic_fixture
        }
      });
    }

    validateArtifact(artifact,decision);
    return artifact;
  }

  return {
    SCHEMA,RESOLVED_SCHEMA,WORLDS_SCHEMA,PAIRED_SCHEMA,POSTERIOR_SCHEMA,PAIRING_CONTRACT,SELECTION_POLICY,SCIENTIFIC_EFFECT,
    IsoSizingDiagnosticsError,canonicalDecision,validateArtifact,resolveAgainstDecision,bridgePairedResult
  };
});
