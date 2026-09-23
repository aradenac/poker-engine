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

  // Explicit "dimension not supplied by the producer" sentinel shared by the
  // technical dimensions. It is deliberately distinct from every real status so
  // the mapper can tell "not evaluated yet" from "evaluated and negative".
  const NOT_EVALUATED='NOT_EVALUATED';
  const COMPUTATIONAL_STATUSES=['NOT_STARTED','PENDING','RUNNING','COMPLETE','FAILED',NOT_EVALUATED];
  const MODEL_SUPPORT_STATUSES=['SUPPORTED','NODE_ABSENT','CONTEXT_UNSUPPORTED',NOT_EVALUATED];
  const POSTERIOR_AVAILABILITY=['conditioned','prior_uninformative','source_prior_unconditioned','degenerate','unavailable'];
  // Explicit availability signal for the statistical-support dimension. It lets
  // the mapper distinguish a positive model support (`AVAILABLE`) from a
  // dimension the producer did not evaluate (`UNKNOWN`) and from a dimension the
  // model cannot represent at all (`UNAVAILABLE`), instead of reading the
  // fail-safe floor `0` as if it were a decided scientific value.
  const SUPPORT_AVAILABILITY=['AVAILABLE','UNKNOWN','UNAVAILABLE'];

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
      // A `NOT_EVALUATED` status is the explicit "dimension missing" sentinel: it
      // is never a reason code, so it must not resurface in `reason_codes`.
      if(admissibility.admissible===false&&upper(admissibility.status)!==NOT_EVALUATED)pushReasonCode(out,admissibility.status);
    }
    return unique(out);
  }

  // Fail-safe evidence rule (review #408): shipping a dimension container is
  // never proof by itself that the producer evaluated it. A dimension counts as
  // evaluated only when it carries an explicit boolean verdict that is not
  // contradicted by the shared NOT_EVALUATED sentinel; an empty object, a
  // placeholder, or a non-boolean value is treated exactly like an absent
  // dimension (no invented blocker, no induced COMPLETE computation).
  function hasExplicitVerdict(verdict,sentinel){
    return typeof verdict==='boolean'&&upper(sentinel)!==NOT_EVALUATED;
  }
  function normalizeComparability(data){
    if(isPlainObject(data.ev_comparability)){
      const row=data.ev_comparability;
      const reason=text(row.reason)||null;
      const evaluated=hasExplicitVerdict(row.comparable,reason);
      // No explicit boolean verdict (empty object, placeholder, non-boolean or
      // NOT_EVALUATED sentinel) is not a producer statement at all: take the
      // "missing dimension" path and return null instead of a negative-shaped
      // container. It never becomes `negative` nor terminal evidence (#408).
      if(!evaluated)return null;
      return {
        provided:true,
        evaluated,
        comparable:row.comparable===true,
        negative:row.comparable===false,
        reason
      };
    }
    if(typeof data.ev_comparable==='boolean'){
      return {
        provided:true,
        evaluated:true,
        comparable:data.ev_comparable===true,
        negative:data.ev_comparable===false,
        reason:data.ev_comparable?null:(text(data.ev_comparability_reason)||null)
      };
    }
    return null;
  }
  function normalizeAdmissibility(data){
    if(isPlainObject(data.recommendation_admissibility)){
      const row=data.recommendation_admissibility;
      const status=text(row.status)||null;
      // Same fail-safe evidence rule as comparability (#408).
      const evaluated=hasExplicitVerdict(row.admissible,status);
      const reason_codes=Array.isArray(row.reason_codes)?row.reason_codes.map(upper).filter(Boolean):[];
      // No explicit boolean verdict is not a producer statement at all. When the
      // placeholder carries no producer-supplied codes it takes the "missing
      // dimension" path (null); codes, when present, are still preserved
      // verbatim without ever synthesizing a blocking status/reason (#408).
      if(!evaluated&&!reason_codes.length)return null;
      return {
        provided:true,
        evaluated,
        admissible:evaluated&&row.admissible===true,
        negative:evaluated&&row.admissible===false,
        status,
        reason_codes
      };
    }
    if(typeof data.admissible==='boolean'){
      return {
        provided:true,
        evaluated:true,
        admissible:data.admissible===true,
        negative:data.admissible===false,
        status:text(data.admissibility_status)||null,
        reason_codes:[]
      };
    }
    return null;
  }
  // A positive coverage signal is an explicit producer statement that the spot
  // is covered, so it counts as positive evidence for model support/availability.
  function hasCoveredCoverage(data){
    if(upper(data.coverage_state)==='COVERED')return true;
    if(isPlainObject(data.coverage)&&upper(data.coverage.state)==='COVERED')return true;
    return false;
  }
  // Per-dimension extractors. A dimension counts as "supplied" only when it
  // carries a real value; the explicit NOT_EVALUATED sentinel (and any unknown
  // value) means "the producer did not evaluate this dimension".
  function extractComputational(data){
    const raw=upper(data.computational_status);
    if(COMPUTATIONAL_STATUSES.includes(raw)&&raw!==NOT_EVALUATED)return {provided:true,status:raw,pending:PENDING_COMPUTATIONAL.has(raw)};
    return {provided:false,status:null,pending:false};
  }
  function extractModel(data){
    const raw=upper(data.model_support_status);
    if(raw==='SUPPORTED')return {provided:true,status:raw,positive:true,blocker:false};
    if(raw==='NODE_ABSENT'||raw==='CONTEXT_UNSUPPORTED')return {provided:true,status:raw,positive:false,blocker:true};
    return {provided:false,status:null,positive:false,blocker:false};
  }
  function extractPosterior(data){
    const raw=text(data.posterior_availability).toLowerCase();
    if(POSTERIOR_AVAILABILITY.includes(raw))return {provided:true,status:raw,positive:raw==='conditioned'};
    return {provided:false,status:null,positive:false};
  }
  // The statistical-support availability sentinel. A producer may state it
  // explicitly; the mapper otherwise derives a fail-safe value (never a
  // fabricated positive one) from the evidence it actually has.
  function extractSupportAvailability(data){
    const supportStat=isPlainObject(data.statistical_support)?data.statistical_support:{};
    const raw=upper(supportStat.availability);
    if(SUPPORT_AVAILABILITY.includes(raw))return raw;
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
    const hasPositiveCode=knownEntries.some(row=>row.entry===S_DISPONIBLE);

    const errorInput=isPlainObject(data.error)?data.error:null;
    const errorType=text(errorInput&&errorInput.type)||null;
    const computational=extractComputational(data);
    const model=extractModel(data);
    const posterior=extractPosterior(data);
    const supportAvailabilityInput=extractSupportAvailability(data);
    const comparabilityInput=normalizeComparability(data);
    const admissibilityInput=normalizeAdmissibility(data);
    const coveredCoverage=hasCoveredCoverage(data);
    const supportStat=isPlainObject(data.statistical_support)?data.statistical_support:{};
    const supportRow=isPlainObject(data.support)?data.support:{};

    const comparabilityPositive=Boolean(comparabilityInput&&comparabilityInput.evaluated&&comparabilityInput.comparable);
    const admissibilityPositive=Boolean(admissibilityInput&&admissibilityInput.evaluated&&admissibilityInput.admissible);

    // A dimension counts as "supplied" only when the producer actually evaluated
    // it. This drives the fail-safe computational status: a terminal reason code
    // or an evaluated dimension proves the computation already ran, whereas an
    // empty/weak input must stay NOT_EVALUATED (never COMPLETE by default).
    const terminalEvidence=known.length>0||unknown.length>0||coveredCoverage
      ||Boolean(comparabilityInput&&comparabilityInput.evaluated)
      ||Boolean(admissibilityInput&&admissibilityInput.evaluated);

    const candidates=[];
    const add=state=>{if(state&&!candidates.includes(state))candidates.push(state);};
    if(explicitState)add(explicitState);
    knownEntries.forEach(row=>add(row.entry));
    if(errorType)add(S_ERREUR);
    if(computational.pending)add(S_EN_COURS);
    if(model.blocker)add(S_NON_SUPPORTE);
    if(comparabilityInput&&comparabilityInput.negative)add(S_PARTIELLE);
    if(admissibilityInput&&admissibilityInput.negative)add(S_PARTIELLE);
    // ANALYSE_DISPONIBLE is only ever a candidate when the producer supplied an
    // explicit positive signal: a positive reason code, coverage COVERED, or an
    // explicitly evaluated positive comparability/admissibility. Missing
    // dimensions are never treated as positive evidence.
    if(hasPositiveCode||coveredCoverage||comparabilityPositive||admissibilityPositive)add(S_DISPONIBLE);

    let state=null,bestRank=Infinity;
    for(const candidate of candidates){const rank=STATE_RANK[candidate];if(rank!=null&&rank<bestRank){bestRank=rank;state=candidate;}}
    // Fail-safe default: no decisive evidence is never ANALYSE_DISPONIBLE.
    if(!state)state=DEFAULT_UNKNOWN_STATE;
    // An unknown code must never be dropped, and must never leave the object in
    // an optimistic state: fall back to the safe state while keeping the code.
    if(unknown.length&&(state===S_DISPONIBLE||!candidates.length))state=DEFAULT_UNKNOWN_STATE;

    let model_support_status;
    if(state===S_NON_SUPPORTE){
      model_support_status=(model.provided&&model.status!=='SUPPORTED')?model.status:(firstHint(known,'model_support_status')||'NODE_ABSENT');
    }else if(model.provided){
      model_support_status=model.status;
    }else if(coveredCoverage&&(state===S_DISPONIBLE||state===S_PARTIELLE)){
      model_support_status='SUPPORTED';
    }else{
      model_support_status=NOT_EVALUATED;
    }

    let computational_status;
    if(state===S_ERREUR){
      computational_status='FAILED';
    }else if(state===S_EN_COURS){
      computational_status=computational.provided?computational.status:'PENDING';
    }else if(computational.provided){
      computational_status=computational.status;
    }else if(terminalEvidence){
      computational_status='COMPLETE';
    }else{
      computational_status=NOT_EVALUATED;
    }

    const posterior_availability=posterior.provided
      ?posterior.status
      :(firstHint(known,'posterior_availability')||'unavailable');

    const supportObservations=asInt(supportStat.observations!=null?supportStat.observations:(data.observations!=null?data.observations:supportRow.observations),0);
    const supportDistinctHands=asInt(supportStat.distinct_hands!=null?supportStat.distinct_hands:data.distinct_hands,0);
    // Fail-safe availability: a positive count proves support; an unsupported
    // model context (or a SPOT_NON_SUPPORTE conclusion) proves the dimension is
    // unavailable; anything else stays explicitly UNKNOWN. The availability
    // signal never fabricates a positive count and is preserved on re-mapping.
    const supportAvailability=supportAvailabilityInput
      ||(supportObservations>0?'AVAILABLE':((model.blocker||state===S_NON_SUPPORTE)?'UNAVAILABLE':'UNKNOWN'));
    const statistical_support={
      observations:supportObservations,
      distinct_hands:supportDistinctHands,
      availability:supportAvailability
    };

    const comparability_hint=firstHint(known,'comparability_reason');
    let ev_comparability;
    if(comparabilityInput&&comparabilityInput.evaluated){
      const comparable=comparabilityInput.comparable===true;
      ev_comparability={comparable,reason:comparable?null:(comparabilityInput.reason||comparability_hint||firstHint(known,'admissibility_status')||known[0]||state)};
    }else if(comparability_hint){
      // Not evaluated (missing dimension or empty/placeholder object, #408):
      // behaves exactly like an absent dimension. Never a blocker on its own.
      ev_comparability={comparable:false,reason:comparability_hint};
    }else{
      ev_comparability={comparable:false,reason:NOT_EVALUATED};
    }

    const admissibility_hint=firstHint(known,'admissibility_status');
    let admissible,admissibility_status,admissibility_codes;
    if(admissibilityInput&&admissibilityInput.evaluated){
      admissible=admissibilityInput.admissible===true;
      admissibility_status=admissibilityInput.status||(admissible?'ADMISSIBLE':(admissibility_hint||known[0]||state));
      admissibility_codes=admissibilityInput.reason_codes.slice();
    }else{
      // Not evaluated (missing dimension or empty/placeholder object, #408):
      // behaves exactly like an absent dimension. Keep admissibility closed
      // (never admissible) but do not invent a blocking cause.
      admissible=false;
      admissibility_status=admissibility_hint||NOT_EVALUATED;
      // A placeholder may still carry producer-supplied codes; preserve them
      // verbatim (never synthesized) instead of dropping evidence.
      admissibility_codes=admissibilityInput?admissibilityInput.reason_codes.slice():[];
    }
    if(!admissible&&admissibility_status!==NOT_EVALUATED&&!admissibility_codes.length){
      admissibility_codes=known.filter(code=>ADMISSIBILITY_CODE_SET.has(code));
      if(!admissibility_codes.length)admissibility_codes=known.length?[known[0]]:[admissibility_status];
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
      // Optional for backward compatibility: producers that predate the signal
      // stay valid, but a supplied signal must use the explicit vocabulary.
      if(value.statistical_support.availability!=null&&!SUPPORT_AVAILABILITY.includes(value.statistical_support.availability))fail('invalid statistical_support.availability');
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
    SUPPORT_AVAILABILITY,
    COVERAGE_STATES:EMBEDDED_COVERAGE_STATES,
    FAIL_CLOSED_STATES:EMBEDDED_FAIL_CLOSED_STATES,
    mapAnalysisState,
    validateAnalysisState,
    isAnalysisState
  };
});
