(function(root,factory){
  const Adapter=(typeof module==='object'&&module.exports)?require('../training/preflop-decision-adapter.js'):(root&&root.PokerPreflopDecisionAdapter);
  const api=factory(Adapter);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerAnalysisState=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(Adapter){
  'use strict';

  // Shared mapper for the versioned `poker-analysis-state/v1` taxonomy
  // (contract: contracts/analytics/analysis-state.schema.json).
  //
  // The module is the single source of truth for turning an existing
  // coverage/fail-closed/Review/Inbox/Replayer code into exactly one of the six
  // user-facing states while keeping every technical dimension separate. It
  // reads the frozen canonical adapter's exported COVERAGE_STATES /
  // FAIL_CLOSED_STATES (issue #370) and never mutates it. Every legacy code is
  // mapped explicitly; an unknown code is preserved verbatim and its state falls
  // back to a safe, non-optimistic state.

  const SCHEMA='poker-analysis-state/v1';

  const ANALYSIS_STATES={
    ANALYSE_DISPONIBLE:'ANALYSE_DISPONIBLE',
    ANALYSE_PARTIELLE:'ANALYSE_PARTIELLE',
    CALCUL_EN_COURS:'CALCUL_EN_COURS',
    DONNEES_INSUFFISANTES:'DONNEES_INSUFFISANTES',
    SPOT_NON_SUPPORTE:'SPOT_NON_SUPPORTE',
    ERREUR_CALCUL:'ERREUR_CALCUL'
  };

  const COMPUTATIONAL_STATUSES=['NOT_STARTED','PENDING','RUNNING','COMPLETE','FAILED'];
  const MODEL_SUPPORT_STATUSES=['SUPPORTED','NODE_ABSENT','CONTEXT_UNSUPPORTED','NOT_EVALUATED'];
  const POSTERIOR_AVAILABILITY=['conditioned','prior_uninformative','source_prior_unconditioned','degenerate','unavailable'];

  const S_DISPONIBLE=ANALYSIS_STATES.ANALYSE_DISPONIBLE;
  const S_PARTIELLE=ANALYSIS_STATES.ANALYSE_PARTIELLE;
  const S_EN_COURS=ANALYSIS_STATES.CALCUL_EN_COURS;
  const S_INSUFFISANTES=ANALYSIS_STATES.DONNEES_INSUFFISANTES;
  const S_NON_SUPPORTE=ANALYSIS_STATES.SPOT_NON_SUPPORTE;
  const S_ERREUR=ANALYSIS_STATES.ERREUR_CALCUL;

  // Highest priority first: a worker error is never downgraded by a softer code,
  // a pending computation is never reported as a scientific conclusion, and an
  // unsupported model context dominates an admissibility/comparability nuance.
  const STATE_PRECEDENCE=[S_ERREUR,S_EN_COURS,S_NON_SUPPORTE,S_INSUFFISANTES,S_PARTIELLE,S_DISPONIBLE];
  const STATE_RANK=Object.fromEntries(STATE_PRECEDENCE.map((state,index)=>[state,index]));

  // The safe fallback used when a code is not part of the canonical table: keep
  // the code, but never claim the analysis is available.
  const DEFAULT_UNKNOWN_STATE=S_INSUFFISANTES;

  // Coverage enum shipped by the frozen adapter. Kept embedded so the mapper
  // stays usable in the browser before the adapter boots; the adapter value is
  // merged on top when available.
  const EMBEDDED_COVERAGE_STATES=['COVERED','LOW_SUPPORT','UNSUPPORTED','NON_COMPARABLE','ANALYSIS_MISSING','UNCOVERED'];
  // Fail-closed enum shipped by the frozen adapter (issue #370).
  const EMBEDDED_FAIL_CLOSED_STATES=[
    'NO_ADMISSIBLE_STRATEGY','EXACT_CONTEXT_ABSENT','EXACT_CONTEXT_MISMATCH','POPULATION_MISMATCH',
    'STRATEGY_MISMATCH','ARTIFACT_IDENTITY_MISMATCH','LOW_SUPPORT','UNCOVERED',
    'NON_COMPARABLE_ALTERNATIVES','INVALID_GUIDANCE'
  ];

  // Canonical `code -> state` table. It covers the explicit coverage_state enum
  // and FAIL_CLOSED_STATES (issue #370), the Review/Inbox codes, the Replayer /
  // dashboard EMPTY_STATES and the complete `$defs.reason_code` catalog. Each
  // code resolves to exactly one state.
  const REASON_CODE_MAP={
    // 1. Calcul non terminé -> CALCUL_EN_COURS
    CALCULATION_PENDING:S_EN_COURS,
    ANALYSIS_PENDING:S_EN_COURS,
    UNFINISHED_DECISIONS:S_EN_COURS,
    // 2. Absence de node -> SPOT_NON_SUPPORTE (NODE_ABSENT)
    NODE_ABSENT:S_NON_SUPPORTE,
    EXACT_CONTEXT_ABSENT:S_NON_SUPPORTE,
    SPOT_NON_COUVERT:S_NON_SUPPORTE,
    UNCOVERED:S_NON_SUPPORTE,
    UNSUPPORTED:S_NON_SUPPORTE,
    // 3. Support insuffisant -> DONNEES_INSUFFISANTES
    INSUFFICIENT_SUPPORT:S_INSUFFISANTES,
    LOW_SUPPORT:S_INSUFFISANTES,
    MISSING_HH_SOURCE:S_INSUFFISANTES,
    MISSING_REVIEW_SCORE:S_INSUFFISANTES,
    REVIEW_SCORE_INCOMPLETE:S_INSUFFISANTES,
    NO_DECISION_EVENTS:S_INSUFFISANTES,
    // 4. Contexte non supporté -> SPOT_NON_SUPPORTE (CONTEXT_UNSUPPORTED)
    CONTEXT_UNSUPPORTED:S_NON_SUPPORTE,
    EXACT_CONTEXT_MISMATCH:S_NON_SUPPORTE,
    ACTIVE_REFERENCE_SCOPE_UNSUPPORTED:S_NON_SUPPORTE,
    POPULATION_MISMATCH:S_NON_SUPPORTE,
    STRATEGY_MISMATCH:S_NON_SUPPORTE,
    ARTIFACT_IDENTITY_MISMATCH:S_NON_SUPPORTE,
    UNSUPPORTED_DECISIONS:S_NON_SUPPORTE,
    // 5. Recommandation non admise -> ANALYSE_PARTIELLE
    RECOMMENDATION_NOT_ADMISSIBLE:S_PARTIELLE,
    INVALID_GUIDANCE:S_PARTIELLE,
    NO_ADMISSIBLE_STRATEGY:S_PARTIELLE,
    PLAYED_ALTERNATIVE_NOT_EVALUATED:S_PARTIELLE,
    // 6. Erreur worker -> ERREUR_CALCUL
    WORKER_ERROR:S_ERREUR,
    ANALYSIS_ERROR:S_ERREUR,
    // 7. Analyse partielle -> ANALYSE_PARTIELLE
    PARTIAL_ANALYSIS:S_PARTIELLE,
    NON_COMPARABLE:S_PARTIELLE,
    NON_COMPARABLE_ALTERNATIVES:S_PARTIELLE,
    NON_COMPARABLE_DECISIONS:S_PARTIELLE,
    MISSING_COMPARABLE_EV:S_PARTIELLE,
    NO_COMPARABLE_REVIEW_DETAIL:S_PARTIELLE,
    ANALYSIS_MISSING:S_PARTIELLE,
    // Coverage state emitted with the canonical "available" status.
    COVERED:S_DISPONIBLE,
    // Review dashboard EMPTY_STATES / Replayer empty states.
    NO_HANDS:S_INSUFFISANTES,
    ANALYSIS_INCOMPLETE:S_PARTIELLE,
    NO_SIGNIFICANT_LOSS:S_DISPONIBLE,
    READY:S_DISPONIBLE
  };

  // Dimension hints attached to a canonical code. They never replace the
  // explicit dimensions supplied by the caller; they only fill gaps so a mapped
  // object stays schema-consistent even when only a raw code is known.
  const REASON_CODE_DIMENSIONS={
    NODE_ABSENT:{model_support_status:'NODE_ABSENT',posterior_availability:'unavailable'},
    EXACT_CONTEXT_ABSENT:{model_support_status:'NODE_ABSENT',posterior_availability:'unavailable'},
    SPOT_NON_COUVERT:{model_support_status:'NODE_ABSENT',posterior_availability:'unavailable'},
    UNCOVERED:{model_support_status:'NODE_ABSENT',posterior_availability:'unavailable'},
    UNSUPPORTED:{model_support_status:'NODE_ABSENT',posterior_availability:'unavailable'},
    CONTEXT_UNSUPPORTED:{model_support_status:'CONTEXT_UNSUPPORTED'},
    EXACT_CONTEXT_MISMATCH:{model_support_status:'CONTEXT_UNSUPPORTED'},
    ACTIVE_REFERENCE_SCOPE_UNSUPPORTED:{model_support_status:'CONTEXT_UNSUPPORTED'},
    POPULATION_MISMATCH:{model_support_status:'CONTEXT_UNSUPPORTED'},
    STRATEGY_MISMATCH:{model_support_status:'CONTEXT_UNSUPPORTED'},
    ARTIFACT_IDENTITY_MISMATCH:{model_support_status:'CONTEXT_UNSUPPORTED'},
    UNSUPPORTED_DECISIONS:{model_support_status:'CONTEXT_UNSUPPORTED'},
    RECOMMENDATION_NOT_ADMISSIBLE:{admissibility_status:'RECOMMENDATION_NOT_ADMISSIBLE'},
    INVALID_GUIDANCE:{admissibility_status:'INVALID_GUIDANCE'},
    NO_ADMISSIBLE_STRATEGY:{admissibility_status:'NO_ADMISSIBLE_STRATEGY'},
    PLAYED_ALTERNATIVE_NOT_EVALUATED:{comparability_reason:'PLAYED_ALTERNATIVE_NOT_EVALUATED',admissibility_status:'PLAYED_ALTERNATIVE_NOT_EVALUATED'},
    NON_COMPARABLE:{comparability_reason:'NON_COMPARABLE'},
    NON_COMPARABLE_ALTERNATIVES:{comparability_reason:'NON_COMPARABLE_ALTERNATIVES'},
    NON_COMPARABLE_DECISIONS:{comparability_reason:'NON_COMPARABLE_DECISIONS'},
    MISSING_COMPARABLE_EV:{comparability_reason:'MISSING_COMPARABLE_EV'},
    NO_COMPARABLE_REVIEW_DETAIL:{comparability_reason:'NO_COMPARABLE_REVIEW_DETAIL'},
    WORKER_ERROR:{error_type:'WORKER_ERROR'},
    ANALYSIS_ERROR:{error_type:'ANALYSIS_ERROR'}
  };

  // Codes that directly describe recommendation admissibility (distinction #5).
  const ADMISSIBILITY_CODES=[
    'RECOMMENDATION_NOT_ADMISSIBLE','INVALID_GUIDANCE','NO_ADMISSIBLE_STRATEGY',
    'PLAYED_ALTERNATIVE_NOT_EVALUATED','REVIEW_SCORE_INCOMPLETE','NO_DECISION_EVENTS','UNSUPPORTED_DECISIONS'
  ];
  const ADMISSIBILITY_CODE_SET=new Set(ADMISSIBILITY_CODES);
  const COMPARABILITY_CODES=[
    'PARTIAL_ANALYSIS','NON_COMPARABLE','NON_COMPARABLE_ALTERNATIVES','NON_COMPARABLE_DECISIONS',
    'MISSING_COMPARABLE_EV','NO_COMPARABLE_REVIEW_DETAIL','PLAYED_ALTERNATIVE_NOT_EVALUATED'
  ];
  const COMPARABILITY_CODE_SET=new Set(COMPARABILITY_CODES);
  const PENDING_COMPUTATIONAL=new Set(['NOT_STARTED','PENDING','RUNNING']);

  function text(v){return v==null?'':String(v).trim();}
  function upper(v){return text(v).toUpperCase();}
  function isPlainObject(v){return Boolean(v)&&typeof v==='object'&&!Array.isArray(v);}
  function asInt(v,def){const n=Number(v);return Number.isInteger(n)&&n>=0?n:def;}
  function unique(values){return Array.from(new Set(values.filter(v=>v!=null&&String(v)!=='')));}
  function coverageFallback(code){
    if(code==='COVERED')return S_DISPONIBLE;
    if(code==='LOW_SUPPORT')return S_INSUFFISANTES;
    if(code==='NON_COMPARABLE'||code==='ANALYSIS_MISSING')return S_PARTIELLE;
    if(code==='UNSUPPORTED'||code==='UNCOVERED')return S_NON_SUPPORTE;
    return S_INSUFFISANTES;
  }
  function failClosedFallback(code){
    if(code==='NO_ADMISSIBLE_STRATEGY'||code==='INVALID_GUIDANCE'||code==='NON_COMPARABLE_ALTERNATIVES')return S_PARTIELLE;
    if(code==='LOW_SUPPORT')return S_INSUFFISANTES;
    return S_NON_SUPPORTE;
  }

  // Merge the frozen adapter enum into the canonical table so a future adapter
  // code is still mapped deterministically (to a safe state) instead of being
  // silently dropped.
  function buildReasonCodeMap(){
    const map={};
    for(const [code,state] of Object.entries(REASON_CODE_MAP))map[code]=state;
    const coverage=(Adapter&&Array.isArray(Adapter.COVERAGE_STATES)&&Adapter.COVERAGE_STATES.length?Adapter.COVERAGE_STATES:EMBEDDED_COVERAGE_STATES)
      .map(upper).filter(Boolean);
    const failClosed=(Adapter&&Array.isArray(Adapter.FAIL_CLOSED_STATES)&&Adapter.FAIL_CLOSED_STATES.length?Adapter.FAIL_CLOSED_STATES:EMBEDDED_FAIL_CLOSED_STATES)
      .map(upper).filter(Boolean);
    for(const code of coverage)if(!Object.prototype.hasOwnProperty.call(map,code))map[code]=coverageFallback(code);
    for(const code of failClosed)if(!Object.prototype.hasOwnProperty.call(map,code))map[code]=failClosedFallback(code);
    return map;
  }
  // Exported table kept immutable so callers cannot corrupt the shared mapping.
  const REASON_CODE_MAP_FROZEN=Object.freeze(buildReasonCodeMap());

  const CANONICAL_STATE_VALUES=new Set(Object.values(ANALYSIS_STATES));

  function pushReasonCode(out,v){
    const code=upper(v);
    if(!code)return;
    if(code==='COVERED')return;              // coverage state, not a reason
    if(CANONICAL_STATE_VALUES.has(code))return; // canonical state, not a reason
    out.push(code);
  }
  function collectCodes(input){
    const out=[];
    if(typeof input==='string'){pushReasonCode(out,input);return unique(out);}
    if(!isPlainObject(input))return out;
    if(Array.isArray(input.reason_codes))input.reason_codes.forEach(c=>pushReasonCode(out,c));
    else pushReasonCode(out,input.reason_codes);
    pushReasonCode(out,input.code);
    pushReasonCode(out,input.reason);
    pushReasonCode(out,input.error_code);
    if(input.state)pushReasonCode(out,input.state);
    if(input.coverage_state)pushReasonCode(out,input.coverage_state);
    if(isPlainObject(input.coverage))pushReasonCode(out,input.coverage.state);
    const admissibility=input.recommendation_admissibility;
    if(isPlainObject(admissibility)){
      if(Array.isArray(admissibility.reason_codes))admissibility.reason_codes.forEach(c=>pushReasonCode(out,c));
      if(admissibility.admissible===false)pushReasonCode(out,admissibility.status);
    }
    return unique(out);
  }

  function normalizeComparability(data){
    if(isPlainObject(data.ev_comparability)){
      return {comparable:Boolean(data.ev_comparability.comparable),reason:text(data.ev_comparability.reason)||null};
    }
    if(typeof data.ev_comparable==='boolean'){
      return {comparable:data.ev_comparable,reason:data.ev_comparable?null:(text(data.ev_comparability_reason)||null)};
    }
    return null;
  }
  function normalizeAdmissibility(data){
    if(isPlainObject(data.recommendation_admissibility)){
      const row=data.recommendation_admissibility;
      return {admissible:Boolean(row.admissible),status:text(row.status)||null,...row};
    }
    if(typeof data.admissible==='boolean')return {admissible:data.admissible,status:text(data.admissibility_status)||null};
    return null;
  }
  function firstHint(codes,key){
    for(const code of codes){const hints=REASON_CODE_DIMENSIONS[code];if(hints&&text(hints[key]))return text(hints[key]);}
    return null;
  }
  function findCodeState(code){return Object.prototype.hasOwnProperty.call(REASON_CODE_MAP_FROZEN,code)?REASON_CODE_MAP_FROZEN[code]:null;}

  function mapAnalysisState(input={}){
    const data=typeof input==='string'?{}:(isPlainObject(input)?input:{});
    const stateInput=typeof input==='string'?null:upper(data.state);
    const explicitState=CANONICAL_STATE_VALUES.has(stateInput)?stateInput:null;
    const codes=collectCodes(input);
    const known=[],unknown=[];
    for(const code of codes)(findCodeState(code)?known:unknown).push(code);
    const knownEntries=known.map(code=>({code,entry:findCodeState(code)}));

    const errorInput=isPlainObject(data.error)?data.error:null;
    const errorType=text(errorInput&&errorInput.type)||null;
    const computationalInput=COMPUTATIONAL_STATUSES.includes(upper(data.computational_status))?upper(data.computational_status):null;
    const modelInput=MODEL_SUPPORT_STATUSES.includes(upper(data.model_support_status))?upper(data.model_support_status):null;
    const posteriorRaw=text(data.posterior_availability).toLowerCase();
    const posteriorInput=POSTERIOR_AVAILABILITY.includes(posteriorRaw)?posteriorRaw:null;
    const comparabilityInput=normalizeComparability(data);
    const admissibilityInput=normalizeAdmissibility(data);
    const supportStat=isPlainObject(data.statistical_support)?data.statistical_support:{};
    const supportRow=isPlainObject(data.support)?data.support:{};

    const candidates=[];
    const add=state=>{if(state&&!candidates.includes(state))candidates.push(state);};
    if(explicitState)add(explicitState);
    knownEntries.forEach(row=>add(row.entry));
    if(errorType)add(S_ERREUR);
    if(computationalInput&&PENDING_COMPUTATIONAL.has(computationalInput))add(S_EN_COURS);
    if(modelInput==='NODE_ABSENT'||modelInput==='CONTEXT_UNSUPPORTED')add(S_NON_SUPPORTE);
    if(comparabilityInput&&comparabilityInput.comparable===false)add(S_PARTIELLE);
    if(admissibilityInput&&admissibilityInput.admissible===false)add(S_PARTIELLE);

    let state=null,bestRank=Infinity;
    for(const candidate of candidates){const rank=STATE_RANK[candidate];if(rank!=null&&rank<bestRank){bestRank=rank;state=candidate;}}
    if(!state)state=S_DISPONIBLE;
    // An unknown code must never be dropped, and must never leave the object in
    // an optimistic state: fall back to the safe state while keeping the code.
    if(unknown.length&&(state===S_DISPONIBLE||!candidates.length))state=DEFAULT_UNKNOWN_STATE;

    let model_support_status;
    if(state===S_NON_SUPPORTE){
      model_support_status=(modelInput&&modelInput!=='SUPPORTED')?modelInput:(firstHint(known,'model_support_status')||'NODE_ABSENT');
    }else if(modelInput){
      model_support_status=modelInput;
    }else if(state===S_ERREUR||state===S_EN_COURS){
      model_support_status='NOT_EVALUATED';
    }else{
      model_support_status='SUPPORTED';
    }

    let computational_status;
    if(state===S_ERREUR){
      computational_status='FAILED';
    }else if(state===S_EN_COURS){
      computational_status=(computationalInput&&PENDING_COMPUTATIONAL.has(computationalInput))?computationalInput:'PENDING';
    }else if(computationalInput){
      computational_status=computationalInput;
    }else{
      computational_status='COMPLETE';
    }

    const posterior_availability=posteriorInput
      ||firstHint(known,'posterior_availability')
      ||((state===S_NON_SUPPORTE||state===S_ERREUR||state===S_EN_COURS)?'unavailable':(state===S_DISPONIBLE?'conditioned':'unavailable'));

    const statistical_support={
      observations:asInt(supportStat.observations!=null?supportStat.observations:(data.observations!=null?data.observations:supportRow.observations),0),
      distinct_hands:asInt(supportStat.distinct_hands!=null?supportStat.distinct_hands:data.distinct_hands,0)
    };

    let ev_comparability;
    if(comparabilityInput){
      ev_comparability={comparable:comparabilityInput.comparable,reason:comparabilityInput.comparable?null:(comparabilityInput.reason||firstHint(known,'comparability_reason')||known[0]||state)};
    }else if(state===S_DISPONIBLE){
      ev_comparability={comparable:true,reason:null};
    }else{
      ev_comparability={comparable:false,reason:firstHint(known,'comparability_reason')||firstHint(known,'admissibility_status')||(known[0])||state};
    }

    let admissible,admissibility_status,admissibility_codes;
    if(admissibilityInput){
      admissible=admissibilityInput.admissible;
      admissibility_status=admissibilityInput.status||(admissible?'ADMISSIBLE':(firstHint(known,'admissibility_status')||known[0]||state));
      admissibility_codes=Array.isArray(admissibilityInput.reason_codes)?unique(admissibilityInput.reason_codes.map(upper).filter(Boolean)):[];
    }else{
      admissible=state===S_DISPONIBLE;
      admissibility_status=admissible?'ADMISSIBLE':(firstHint(known,'admissibility_status')||(known[0])||state);
      admissibility_codes=[];
    }
    if(!admissible&&!admissibility_codes.length){
      admissibility_codes=known.filter(code=>ADMISSIBILITY_CODE_SET.has(code));
      if(!admissibility_codes.length)admissibility_codes=known.length?[known[0]]:[state];
    }

    let error;
    if(state===S_ERREUR){
      error={type:errorType||firstHint(known,'error_type')||'WORKER_ERROR',retryable:errorInput&&errorInput.retryable!=null?Boolean(errorInput.retryable):true};
    }else{
      error={type:null,retryable:false};
    }

    const reason_codes=unique([...known,...unknown]);

    return {
      schema:SCHEMA,
      state,
      reason_codes,
      computational_status,
      model_support_status,
      statistical_support,
      ev_comparability,
      recommendation_admissibility:{admissible,status:admissibility_status,reason_codes:admissibility_codes},
      posterior_availability,
      error
    };
  }

  // Structural validator mirroring contracts/analytics/analysis-state.schema.json
  // (no JSON-Schema runtime required) so callers/tests can assert conformance.
  const CODE_PATTERN=/^[A-Z][A-Z0-9_]*$/;
  function validateAnalysisState(value){
    const errors=[];
    const fail=message=>errors.push(message);
    if(!isPlainObject(value))return {valid:false,errors:['analysis state must be an object']};
    if(value.schema!==SCHEMA)fail('schema must be '+SCHEMA);
    if(!CANONICAL_STATE_VALUES.has(value.state))fail('state must be one of the six canonical states');
    if(!Array.isArray(value.reason_codes)||value.reason_codes.some(c=>typeof c!=='string'||!CODE_PATTERN.test(c)))fail('reason_codes must be a canonical string array');
    else if(new Set(value.reason_codes).size!==value.reason_codes.length)fail('reason_codes must be unique');
    if(!COMPUTATIONAL_STATUSES.includes(value.computational_status))fail('invalid computational_status');
    if(!MODEL_SUPPORT_STATUSES.includes(value.model_support_status))fail('invalid model_support_status');
    if(!isPlainObject(value.statistical_support))fail('statistical_support must be an object');
    else{
      if(!Number.isInteger(value.statistical_support.observations)||value.statistical_support.observations<0)fail('invalid observations');
      if(!Number.isInteger(value.statistical_support.distinct_hands)||value.statistical_support.distinct_hands<0)fail('invalid distinct_hands');
    }
    if(!isPlainObject(value.ev_comparability)||typeof value.ev_comparability.comparable!=='boolean')fail('invalid ev_comparability');
    else if(value.ev_comparability.reason!=null&&typeof value.ev_comparability.reason!=='string')fail('invalid ev_comparability.reason');
    if(!isPlainObject(value.recommendation_admissibility)||typeof value.recommendation_admissibility.admissible!=='boolean')fail('invalid recommendation_admissibility');
    else if(!Array.isArray(value.recommendation_admissibility.reason_codes)||value.recommendation_admissibility.reason_codes.some(c=>typeof c!=='string'||!CODE_PATTERN.test(c)))fail('invalid recommendation_admissibility.reason_codes');
    if(!POSTERIOR_AVAILABILITY.includes(value.posterior_availability))fail('invalid posterior_availability');
    if(!isPlainObject(value.error)||typeof value.error.retryable!=='boolean')fail('invalid error');
    else if(value.error.type!=null&&typeof value.error.type!=='string')fail('invalid error.type');
    const allowed=['schema','state','reason_codes','computational_status','model_support_status','statistical_support','ev_comparability','recommendation_admissibility','posterior_availability','error'];
    for(const key of Object.keys(value))if(!allowed.includes(key))fail('unexpected property '+key);
    return {valid:errors.length===0,errors};
  }
  function isAnalysisState(value){return validateAnalysisState(value).valid;}

  return {
    SCHEMA,
    ANALYSIS_STATES,
    REASON_CODE_MAP:REASON_CODE_MAP_FROZEN,
    REASON_CODE_DIMENSIONS,
    DEFAULT_UNKNOWN_STATE,
    COVERAGE_STATES:EMBEDDED_COVERAGE_STATES,
    FAIL_CLOSED_STATES:EMBEDDED_FAIL_CLOSED_STATES,
    mapAnalysisState,
    validateAnalysisState,
    isAnalysisState
  };
});
