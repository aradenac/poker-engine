'use strict';

// Exhaustive mapping + behavior contract for the shared `poker-analysis-state/v1`
// mapper (#393 T2). The module reads the frozen canonical adapter's exported
// enums without modifying it, so this test requires both artifacts.

const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const Decision=require('../../src/preflop/decision.js');
const Guidance=require('../../src/preflop/guidance.js');
const Adapter=require('../../src/training/preflop-decision-adapter.js');
const State=require('../../src/analytics/analysis-state.js');

const ROOT=path.resolve(__dirname,'../..');
const SCHEMA=JSON.parse(fs.readFileSync(path.join(ROOT,'contracts/analytics/analysis-state.schema.json'),'utf8'));

const STATES=Object.values(State.ANALYSIS_STATES);
const STATE_SET=new Set(STATES);

// ---------------------------------------------------------------------------
// 1. Exhaustive mapping over every existing code family.
// ---------------------------------------------------------------------------

// Schema catalog ($defs.reason_code).
for(const code of SCHEMA.$defs.reason_code.enum){
  assert.ok(Object.prototype.hasOwnProperty.call(State.REASON_CODE_MAP,code),'schema code not mapped: '+code);
}
// Coverage enum + fail-closed enum exported by the frozen adapter (#370).
for(const code of Adapter.COVERAGE_STATES){
  assert.ok(Object.prototype.hasOwnProperty.call(State.REASON_CODE_MAP,code),'coverage code not mapped: '+code);
}
for(const code of Adapter.FAIL_CLOSED_STATES){
  assert.ok(Object.prototype.hasOwnProperty.call(State.REASON_CODE_MAP,code),'fail-closed code not mapped: '+code);
}
// Explicit Review / Inbox / Replayer codes from the issue scope.
const REQUIRED_CODES=[
  // coverage_state
  'COVERED','LOW_SUPPORT','UNSUPPORTED','NON_COMPARABLE','ANALYSIS_MISSING','UNCOVERED',
  // preflop / trainer
  'SPOT_NON_COUVERT','ACTIVE_REFERENCE_SCOPE_UNSUPPORTED','PLAYED_ALTERNATIVE_NOT_EVALUATED',
  // Review
  'MISSING_COMPARABLE_EV','NO_COMPARABLE_REVIEW_DETAIL',
  // Inbox
  'MISSING_HH_SOURCE','MISSING_REVIEW_SCORE','REVIEW_SCORE_INCOMPLETE','UNFINISHED_DECISIONS',
  'NO_DECISION_EVENTS','UNSUPPORTED_DECISIONS','NON_COMPARABLE_DECISIONS',
  // Replayer / dashboard EMPTY_STATES
  'NO_HANDS','ANALYSIS_PENDING','ANALYSIS_INCOMPLETE','NO_SIGNIFICANT_LOSS','READY'
];
for(const code of REQUIRED_CODES){
  assert.ok(Object.prototype.hasOwnProperty.call(State.REASON_CODE_MAP,code),'required code not mapped: '+code);
}
// Every mapped state is one of the six canonical states.
for(const [code,state] of Object.entries(State.REASON_CODE_MAP)){
  assert.ok(STATE_SET.has(state),'code '+code+' maps to a non-canonical state '+state);
}
assert.equal(STATES.length,6);

// ---------------------------------------------------------------------------
// 2. Transient computation must never look like a conclusion.
// ---------------------------------------------------------------------------
{
  const pending=State.mapAnalysisState({reason_codes:['CALCULATION_PENDING'],computational_status:'PENDING'});
  assert.equal(pending.state,'CALCUL_EN_COURS');
  assert.equal(pending.computational_status,'PENDING');
  assert.ok(pending.reason_codes.includes('CALCULATION_PENDING'));
  assert.equal(State.isAnalysisState(pending),true);

  const legacy=State.mapAnalysisState({reason_codes:['UNFINISHED_DECISIONS']});
  assert.equal(legacy.state,'CALCUL_EN_COURS');
}

// ---------------------------------------------------------------------------
// 3. Worker error keeps its type and retryability (ERREUR_CALCUL).
// ---------------------------------------------------------------------------
{
  const error=State.mapAnalysisState({reason_codes:['WORKER_ERROR'],error:{type:'WORKER_TIMEOUT',retryable:true}});
  assert.equal(error.state,'ERREUR_CALCUL');
  assert.equal(error.computational_status,'FAILED');
  assert.equal(error.model_support_status,'NOT_EVALUATED');
  assert.equal(error.error.type,'WORKER_TIMEOUT');
  assert.equal(error.error.retryable,true);
  assert.ok(error.reason_codes.includes('WORKER_ERROR'));
  assert.equal(State.isAnalysisState(error),true);

  const fatal=State.mapAnalysisState({reason_codes:['ANALYSIS_ERROR'],error:{type:'DETERMINISTIC_FAILURE',retryable:false}});
  assert.equal(fatal.state,'ERREUR_CALCUL');
  assert.equal(fatal.error.retryable,false);
}

// ---------------------------------------------------------------------------
// 4. VS_LIMPERS unsupported spot -> SPOT_NON_SUPPORTE.
// ---------------------------------------------------------------------------
{
  const unsupported=State.mapAnalysisState({coverage_state:'UNSUPPORTED',reason_codes:['SPOT_NON_COUVERT'],posterior_availability:'unavailable'});
  assert.equal(unsupported.state,'SPOT_NON_SUPPORTE');
  assert.equal(unsupported.model_support_status,'NODE_ABSENT');
  assert.equal(unsupported.posterior_availability,'unavailable');
  assert.ok(unsupported.reason_codes.includes('SPOT_NON_COUVERT'));
  assert.equal(unsupported.recommendation_admissibility.admissible,false);

  // Trainer/replayer active reference scope outside the supported domain.
  const activeScope=State.mapAnalysisState({coverage_state:'UNSUPPORTED',reason_codes:['ACTIVE_REFERENCE_SCOPE_UNSUPPORTED']});
  assert.equal(activeScope.state,'SPOT_NON_SUPPORTE');
  assert.equal(activeScope.model_support_status,'CONTEXT_UNSUPPORTED');
}

// ---------------------------------------------------------------------------
// 4b. Explicit code -> state table (documented mapping).
// ---------------------------------------------------------------------------
{
  const expectations={
    CALCULATION_PENDING:'CALCUL_EN_COURS',
    ANALYSIS_PENDING:'CALCUL_EN_COURS',
    UNFINISHED_DECISIONS:'CALCUL_EN_COURS',
    NODE_ABSENT:'SPOT_NON_SUPPORTE',
    EXACT_CONTEXT_ABSENT:'SPOT_NON_SUPPORTE',
    SPOT_NON_COUVERT:'SPOT_NON_SUPPORTE',
    UNCOVERED:'SPOT_NON_SUPPORTE',
    CONTEXT_UNSUPPORTED:'SPOT_NON_SUPPORTE',
    EXACT_CONTEXT_MISMATCH:'SPOT_NON_SUPPORTE',
    ACTIVE_REFERENCE_SCOPE_UNSUPPORTED:'SPOT_NON_SUPPORTE',
    POPULATION_MISMATCH:'SPOT_NON_SUPPORTE',
    STRATEGY_MISMATCH:'SPOT_NON_SUPPORTE',
    ARTIFACT_IDENTITY_MISMATCH:'SPOT_NON_SUPPORTE',
    INSUFFICIENT_SUPPORT:'DONNEES_INSUFFISANTES',
    LOW_SUPPORT:'DONNEES_INSUFFISANTES',
    MISSING_HH_SOURCE:'DONNEES_INSUFFISANTES',
    MISSING_REVIEW_SCORE:'DONNEES_INSUFFISANTES',
    REVIEW_SCORE_INCOMPLETE:'DONNEES_INSUFFISANTES',
    NO_DECISION_EVENTS:'DONNEES_INSUFFISANTES',
    RECOMMENDATION_NOT_ADMISSIBLE:'ANALYSE_PARTIELLE',
    INVALID_GUIDANCE:'ANALYSE_PARTIELLE',
    NO_ADMISSIBLE_STRATEGY:'ANALYSE_PARTIELLE',
    PLAYED_ALTERNATIVE_NOT_EVALUATED:'ANALYSE_PARTIELLE',
    WORKER_ERROR:'ERREUR_CALCUL',
    ANALYSIS_ERROR:'ERREUR_CALCUL',
    PARTIAL_ANALYSIS:'ANALYSE_PARTIELLE',
    NON_COMPARABLE:'ANALYSE_PARTIELLE',
    NON_COMPARABLE_ALTERNATIVES:'ANALYSE_PARTIELLE',
    NON_COMPARABLE_DECISIONS:'ANALYSE_PARTIELLE',
    MISSING_COMPARABLE_EV:'ANALYSE_PARTIELLE',
    NO_COMPARABLE_REVIEW_DETAIL:'ANALYSE_PARTIELLE',
    ANALYSIS_MISSING:'ANALYSE_PARTIELLE',
    UNSUPPORTED:'SPOT_NON_SUPPORTE',
    UNSUPPORTED_DECISIONS:'SPOT_NON_SUPPORTE',
    NO_HANDS:'DONNEES_INSUFFISANTES',
    ANALYSIS_INCOMPLETE:'ANALYSE_PARTIELLE',
    NO_SIGNIFICANT_LOSS:'ANALYSE_DISPONIBLE',
    READY:'ANALYSE_DISPONIBLE',
    COVERED:'ANALYSE_DISPONIBLE'
  };
  for(const [code,state] of Object.entries(expectations)){
    assert.equal(State.REASON_CODE_MAP[code],state,'unexpected mapping for '+code);
  }
}

// ---------------------------------------------------------------------------
// 5. Absence of an adversary node -> SPOT_NON_SUPPORTE with unavailable posterior.
// ---------------------------------------------------------------------------
{
  const noNode=State.mapAnalysisState({reason_codes:['NODE_ABSENT']});
  assert.equal(noNode.state,'SPOT_NON_SUPPORTE');
  assert.equal(noNode.model_support_status,'NODE_ABSENT');
  assert.equal(noNode.posterior_availability,'unavailable');
  assert.equal(noNode.recommendation_admissibility.admissible,false);
  // The producer supplied no admissibility evidence, so the dimension stays
  // explicitly not evaluated instead of borrowing the node-absence cause.
  assert.equal(noNode.recommendation_admissibility.status,'NOT_EVALUATED');
}

// ---------------------------------------------------------------------------
// 6. Partial posterior / non-comparable analysis -> ANALYSE_PARTIELLE.
// ---------------------------------------------------------------------------
{
  const partial=State.mapAnalysisState({
    coverage_state:'NON_COMPARABLE',
    reason_codes:['MISSING_COMPARABLE_EV'],
    posterior_availability:'source_prior_unconditioned',
    statistical_support:{observations:12,distinct_hands:7}
  });
  assert.equal(partial.state,'ANALYSE_PARTIELLE');
  assert.equal(partial.posterior_availability,'source_prior_unconditioned');
  assert.equal(partial.ev_comparability.comparable,false);
  assert.equal(partial.ev_comparability.reason,'MISSING_COMPARABLE_EV');
  assert.deepEqual(partial.statistical_support,{observations:12,distinct_hands:7,availability:'AVAILABLE'});
  assert.equal(State.isAnalysisState(partial),true);
}

// ---------------------------------------------------------------------------
// 7. Complete admissible Hero decision -> ANALYSE_DISPONIBLE (end-to-end through
//    the frozen adapter, never mutating it).
// ---------------------------------------------------------------------------
const POP='pokerstars_nlhe_100-200_zoom_play_6max_v1';
const STRATEGY='hero-preflop-promoted-v1';
const IDENTITY={
  population_id:POP,pack_id:'zoom-pack',pack_version:'pack-v1',
  strategy_id:STRATEGY,strategy_version:'release-r1',
  strategy_sha256:'a'.repeat(64),decision_source_sha256:'b'.repeat(64),
  ev_reference:'decision_point_incremental_bb'
};
function uncertainty(){return {monte_carlo:{standard_error_bb:.05,samples:5000,method:'synthetic'}};}
function support(n){return {observations:n,backoff_level:'EXACT',source:'SYNTHETIC'};}
function alt(id,action,target,cost,ev,n){return {id,action,target_total_bb:target,incremental_cost_bb:cost,ev_bb:ev,support:support(n),confidence:.8,uncertainty:uncertainty()};}
function publicState(actor){
  const seats=['LJ','HJ','CO','BTN','SB','BB'];
  const stacks=Object.fromEntries(seats.map(p=>[p,100]));
  const total=Object.fromEntries(seats.map(p=>[p,0]));
  const street=Object.fromEntries(seats.map(p=>[p,0]));
  const folded=Object.fromEntries(seats.map(p=>[p,false]));
  const allin=Object.fromEntries(seats.map(p=>[p,false]));
  total.SB=.5;street.SB=.5;stacks.SB=99.5;total.BB=1;street.BB=1;stacks.BB=99;
  street.HJ=2.5;total.HJ=2.5;stacks.HJ=97.5;
  return {
    snapshot:{
      schema:'nlhe-game-state/v1',seats,button:'BTN',small_blind_player:'SB',big_blind_player:'BB',
      small_blind_bb:.5,big_blind_bb:1,starting_stacks_bb:Object.fromEntries(seats.map(p=>[p,100])),
      stacks_bb:stacks,total_committed_bb:total,street_committed_bb:street,folded,all_in:allin,
      street:'preflop',board:[],current_bet_bb:2.5,last_full_raise_bb:1,full_bet_established:true,
      acted_since_full_raise:[],pending:[actor],refunds_bb:Object.fromEntries(seats.map(p=>[p,0])),
      action_log:[{street:'preflop',player:'HJ',action:'RAISE',target_total_bb:2.5,incremental_cost_bb:2.5}]
    },
    legal_view:{actor,pot_before_bb:3.5,actor_street_contribution_bb:0,actor_remaining_bb:100,current_price_bb:2.5,to_call_bb:2.5,
      legal_actions:['FOLD','CALL','RAISE'],min_raise_to_bb:5.5,max_raise_to_bb:100,raise_reopened:true}
  };
}

const completeDecision=(()=>{
  const alternatives=[alt('fold','FOLD',null,0,0,150),alt('call','CALL',2.5,2.5,.7,150),alt('3b-8','3BET',8,8,1.6,150)];
  const decision=Decision.buildDecision({
    context_id:'ctx-3bet',population_id:POP,actor_contribution_bb:0,
    legal_actions:Array.from(new Set(alternatives.map(x=>x.action))),selected_id:'3b-8',alternatives,
    search:{candidate_ids:alternatives.map(x=>x.id),sizing_grid_source:'synthetic',budget:1000,seed:'195'}
  });
  const guidance=Guidance.buildGuidance({
    decision,
    strategy:{state:'PROMOTED',strategy_id:STRATEGY,strategy_sha256:IDENTITY.strategy_sha256,population_id:POP,
      source:'synthetic-promotion-registry',decision_source_sha256:IDENTITY.decision_source_sha256},
    public_snapshot:{street:'PREFLOP',context_id:'ctx-3bet',population_id:POP,hero_hand_class:'AQs'}
  });
  return Adapter.buildDecision({
    public_state:publicState('BTN'),identity:IDENTITY,guidance,played_action:{action:'CALL',target_total_bb:2.5},
    coverage:{state:'COVERED',support_tier:'HIGH'},
    preflop_context:{context_id:'ctx-3bet',family:'VS_RFI',actor_position:'BTN'},
    hand_id:'complete-hero',timestamp:'2026-09-19T00:30:00Z'
  });
})();
{
  assert.equal(completeDecision.recommendation_admissibility.admissible,true);
  assert.equal(completeDecision.coverage_state,'COVERED');
  assert.equal(completeDecision.ev_comparable,true);
  const mapped=State.mapAnalysisState(completeDecision);
  assert.equal(mapped.state,'ANALYSE_DISPONIBLE');
  assert.deepEqual(mapped.reason_codes,[]);
  assert.equal(mapped.recommendation_admissibility.admissible,true);
  assert.equal(mapped.ev_comparability.comparable,true);
  // The canonical adapter supplies no posterior evidence, so the dimension is
  // reported as unavailable (fail-safe) and never inferred from admissibility.
  assert.equal(mapped.posterior_availability,'unavailable');
  assert.equal(mapped.computational_status,'COMPLETE');
  assert.equal(mapped.model_support_status,'SUPPORTED');
  assert.equal(mapped.statistical_support.observations,150);
  assert.equal(State.isAnalysisState(mapped),true);

  // Fail-closed / absent node through the adapter -> SPOT_NON_SUPPORTE.
  const noStrategy=Adapter.buildDecision({
    public_state:publicState('BTN'),identity:IDENTITY,guidance:null,played_action:{action:'CALL',target_total_bb:2.5},
    coverage:{state:'ANALYSIS_MISSING',support_tier:'UNKNOWN'},
    preflop_context:{family:'VS_RFI',actor_position:'BTN'},hand_id:'absent-context'
  });
  const mappedAbsent=State.mapAnalysisState(noStrategy);
  assert.equal(mappedAbsent.state,'SPOT_NON_SUPPORTE');
  assert.ok(mappedAbsent.reason_codes.includes('EXACT_CONTEXT_ABSENT'));
  assert.equal(mappedAbsent.posterior_availability,'unavailable');
}

// ---------------------------------------------------------------------------
// 8. Unknown code: preserved verbatim, safe state, never optimistically available.
// ---------------------------------------------------------------------------
{
  const unknown=State.mapAnalysisState({reason_codes:['FUTURE_TAXONOMY_CODE'],coverage_state:'COVERED'});
  assert.equal(unknown.state,State.DEFAULT_UNKNOWN_STATE);
  assert.ok(unknown.reason_codes.includes('FUTURE_TAXONOMY_CODE'));
  assert.equal(State.isAnalysisState(unknown),true);

  const mixed=State.mapAnalysisState({reason_codes:['NODE_ABSENT','FUTURE_TAXONOMY_CODE']});
  assert.equal(mixed.state,'SPOT_NON_SUPPORTE','known severe code dominates an unknown code');
  assert.ok(mixed.reason_codes.includes('FUTURE_TAXONOMY_CODE'));
}

// ---------------------------------------------------------------------------
// 9. Idempotence + schema conformance for representative inputs.
// ---------------------------------------------------------------------------
{
  const inputs=[
    {},
    {coverage_state:'COVERED'},
    {coverage_state:'LOW_SUPPORT'},
    {coverage_state:'UNSUPPORTED'},
    {reason_codes:['POPULATION_MISMATCH']},
    {reason_codes:['INVALID_GUIDANCE']},
    {reason_codes:['PLAYED_ALTERNATIVE_NOT_EVALUATED']},
    {reason_codes:['ANALYSIS_MISSING']},
    {reason_codes:['NON_COMPARABLE_DECISIONS']},
    {reason_codes:['READY']}
  ];
  for(const input of inputs){
    const mapped=State.mapAnalysisState(input);
    const validation=State.validateAnalysisState(mapped);
    assert.equal(validation.valid,true,JSON.stringify({input,mapped,validation}));
    const twice=State.mapAnalysisState(mapped);
    assert.deepEqual(twice,mapped,'mapAnalysisState must be idempotent');
  }
}

// ---------------------------------------------------------------------------
// 10. Fail-safe + explicit-evidence regression (review #408 blocker 1).
//     A missing/weak input must never fabricate an optimistic dimension, and
//     ANALYSE_DISPONIBLE must require an explicit positive signal.
// ---------------------------------------------------------------------------
{
  // 10a. Empty input is not an available analysis and fabricates nothing.
  const empty=State.mapAnalysisState({});
  assert.notEqual(empty.state,'ANALYSE_DISPONIBLE','empty input must never default to available');
  assert.equal(empty.state,State.DEFAULT_UNKNOWN_STATE);
  assert.equal(empty.computational_status,'NOT_EVALUATED');
  assert.equal(empty.model_support_status,'NOT_EVALUATED');
  assert.equal(empty.ev_comparability.comparable,false);
  assert.equal(empty.ev_comparability.reason,'NOT_EVALUATED');
  assert.equal(empty.recommendation_admissibility.admissible,false);
  assert.equal(empty.recommendation_admissibility.status,'NOT_EVALUATED');
  assert.notEqual(empty.posterior_availability,'conditioned');
  assert.equal(empty.posterior_availability,'unavailable');
  assert.equal(State.validateAnalysisState(empty).valid,true);
  assert.deepEqual(State.mapAnalysisState(empty),empty,'empty mapping must be idempotent');

  // A missing dimension is never inferred from the absence of a blocker: a
  // single evaluated dimension cannot promote the others.
  const onlyComparable=State.mapAnalysisState({ev_comparability:{comparable:true,reason:null}});
  assert.equal(onlyComparable.state,'ANALYSE_DISPONIBLE');
  assert.equal(onlyComparable.ev_comparability.comparable,true);
  assert.equal(onlyComparable.recommendation_admissibility.admissible,false);
  assert.equal(onlyComparable.recommendation_admissibility.status,'NOT_EVALUATED');
  assert.notEqual(onlyComparable.posterior_availability,'conditioned');
  assert.equal(onlyComparable.computational_status,'COMPLETE','an evaluated dimension proves the computation ran');
  assert.equal(State.validateAnalysisState(onlyComparable).valid,true);
  assert.deepEqual(State.mapAnalysisState(onlyComparable),onlyComparable);

  const onlyModel=State.mapAnalysisState({model_support_status:'SUPPORTED'});
  assert.notEqual(onlyModel.state,'ANALYSE_DISPONIBLE','model support alone does not prove a usable answer');
  assert.equal(onlyModel.model_support_status,'SUPPORTED');
  assert.equal(onlyModel.computational_status,'NOT_EVALUATED');
  assert.equal(onlyModel.ev_comparability.comparable,false);
  assert.equal(onlyModel.recommendation_admissibility.admissible,false);
  assert.notEqual(onlyModel.posterior_availability,'conditioned');
  assert.deepEqual(State.mapAnalysisState(onlyModel),onlyModel);

  const onlyPosterior=State.mapAnalysisState({posterior_availability:'conditioned'});
  assert.notEqual(onlyPosterior.state,'ANALYSE_DISPONIBLE');
  assert.equal(onlyPosterior.posterior_availability,'conditioned');
  assert.equal(onlyPosterior.recommendation_admissibility.admissible,false);
  assert.equal(onlyPosterior.ev_comparability.comparable,false);

  const onlyComputational=State.mapAnalysisState({computational_status:'COMPLETE'});
  assert.notEqual(onlyComputational.state,'ANALYSE_DISPONIBLE');
  assert.equal(onlyComputational.computational_status,'COMPLETE');
  assert.equal(onlyComputational.ev_comparability.comparable,false);
  assert.equal(onlyComputational.recommendation_admissibility.admissible,false);
  assert.notEqual(onlyComputational.posterior_availability,'conditioned');

  // 10b. A bare positive explicit state only promotes the state itself.
  const bareState=State.mapAnalysisState({state:'ANALYSE_DISPONIBLE'});
  assert.equal(bareState.state,'ANALYSE_DISPONIBLE');
  assert.equal(bareState.computational_status,'NOT_EVALUATED');
  assert.equal(bareState.model_support_status,'NOT_EVALUATED');
  assert.equal(bareState.ev_comparability.comparable,false);
  assert.equal(bareState.recommendation_admissibility.admissible,false);
  assert.notEqual(bareState.posterior_availability,'conditioned');
  assert.deepEqual(State.mapAnalysisState(bareState),bareState);

  // 10c. Explicit positive evidence maps to ANALYSE_DISPONIBLE and only then.
  const coveragePositive=State.mapAnalysisState({coverage_state:'COVERED'});
  assert.equal(coveragePositive.state,'ANALYSE_DISPONIBLE');
  assert.equal(coveragePositive.model_support_status,'SUPPORTED');
  assert.deepEqual(State.mapAnalysisState(coveragePositive),coveragePositive);

  const admissibilityPositive=State.mapAnalysisState({
    recommendation_admissibility:{admissible:true,status:'ADMISSIBLE'},
    ev_comparability:{comparable:true,reason:null}
  });
  assert.equal(admissibilityPositive.state,'ANALYSE_DISPONIBLE');
  assert.equal(admissibilityPositive.recommendation_admissibility.admissible,true);
  assert.equal(admissibilityPositive.ev_comparability.comparable,true);
  assert.notEqual(admissibilityPositive.posterior_availability,'conditioned','still no posterior evidence');
  assert.deepEqual(State.mapAnalysisState(admissibilityPositive),admissibilityPositive);

  const reasonPositive=State.mapAnalysisState({reason_codes:['READY']});
  assert.equal(reasonPositive.state,'ANALYSE_DISPONIBLE');
  assert.deepEqual(reasonPositive.reason_codes,['READY']);

  // 10d. An explicitly supplied posterior is preserved without contaminating
  //      the other dimensions.
  const explicitPosterior=State.mapAnalysisState({
    posterior_availability:'conditioned',
    ev_comparability:{comparable:true,reason:null}
  });
  assert.equal(explicitPosterior.posterior_availability,'conditioned');
  assert.equal(explicitPosterior.ev_comparability.comparable,true);
  assert.equal(explicitPosterior.recommendation_admissibility.admissible,false);
  assert.deepEqual(State.mapAnalysisState(explicitPosterior),explicitPosterior);

  // 10e. Partially specified input only promotes the proven dimension(s).
  const pending=State.mapAnalysisState({computational_status:'RUNNING'});
  assert.equal(pending.state,'CALCUL_EN_COURS');
  assert.equal(pending.computational_status,'RUNNING');
  assert.equal(pending.model_support_status,'NOT_EVALUATED');
  assert.equal(pending.ev_comparability.comparable,false);
  assert.equal(pending.recommendation_admissibility.admissible,false);
  assert.notEqual(pending.posterior_availability,'conditioned');
  assert.deepEqual(State.mapAnalysisState(pending),pending);

  // 10f. Unknown codes are preserved and force a safe, non-optimistic state.
  const unknownWeak=State.mapAnalysisState({reason_codes:['FUTURE_TAXONOMY_CODE']});
  assert.notEqual(unknownWeak.state,'ANALYSE_DISPONIBLE');
  assert.equal(unknownWeak.state,State.DEFAULT_UNKNOWN_STATE);
  assert.ok(unknownWeak.reason_codes.includes('FUTURE_TAXONOMY_CODE'));
  assert.equal(unknownWeak.recommendation_admissibility.admissible,false);
  assert.deepEqual(State.mapAnalysisState(unknownWeak),unknownWeak);

  // 10g. Idempotence and schema conformance for the fail-safe fixtures.
  for(const input of [{},{state:'ANALYSE_DISPONIBLE'},{model_support_status:'SUPPORTED'},
    {posterior_availability:'conditioned'},{computational_status:'COMPLETE'},
    {ev_comparability:{comparable:true,reason:null}},{coverage_state:'COVERED'},
    {reason_codes:['FUTURE_TAXONOMY_CODE']}]){
    const mapped=State.mapAnalysisState(input);
    assert.equal(State.validateAnalysisState(mapped).valid,true,JSON.stringify({input,mapped}));
    assert.deepEqual(State.mapAnalysisState(mapped),mapped,'mapAnalysisState must be idempotent for '+JSON.stringify(input));
  }
}

// ---------------------------------------------------------------------------
// 11. Explicit statistical-support availability (#393 blocker 1). The support
//     dimension must state whether it was evaluated instead of leaving the
//     fail-safe floor 0 ambiguous.
// ---------------------------------------------------------------------------
{
  // An empty input has no support evidence: UNKNOWN, and never a positive count.
  const empty=State.mapAnalysisState({});
  assert.deepEqual(empty.statistical_support,{observations:0,distinct_hands:0,availability:'UNKNOWN'});
  assert.equal(State.SUPPORT_AVAILABILITY.includes(empty.statistical_support.availability),true);

  // A real positive count proves AVAILABLE.
  const positive=State.mapAnalysisState({statistical_support:{observations:12,distinct_hands:7}});
  assert.equal(positive.statistical_support.availability,'AVAILABLE');
  assert.equal(positive.statistical_support.observations,12);

  // An unsupported model context proves the dimension is UNAVAILABLE.
  const noNode=State.mapAnalysisState({reason_codes:['NODE_ABSENT']});
  assert.equal(noNode.statistical_support.availability,'UNAVAILABLE');
  const unsupported=State.mapAnalysisState({model_support_status:'CONTEXT_UNSUPPORTED'});
  assert.equal(unsupported.statistical_support.availability,'UNAVAILABLE');

  // An explicit producer signal is preserved verbatim and never fabricates a
  // positive count.
  const explicit=State.mapAnalysisState({statistical_support:{observations:0,distinct_hands:0,availability:'UNKNOWN'}});
  assert.equal(explicit.statistical_support.availability,'UNKNOWN');
  assert.equal(State.validateAnalysisState(explicit).valid,true);
  const statedAvailable=State.mapAnalysisState({statistical_support:{observations:0,distinct_hands:0,availability:'AVAILABLE'}});
  assert.equal(statedAvailable.statistical_support.availability,'AVAILABLE');
  assert.equal(statedAvailable.statistical_support.observations,0,'an explicit availability never invents observations');

  // Invalid availability is rejected by the canonical validator.
  const invalid=Object.assign({},empty,{statistical_support:{observations:0,distinct_hands:0,availability:'MAYBE'}});
  assert.equal(State.validateAnalysisState(invalid).valid,false);

  // Idempotence for every availability verdict.
  for(const input of [{},{statistical_support:{observations:5,distinct_hands:2}},
    {reason_codes:['NODE_ABSENT']},{statistical_support:{observations:0,distinct_hands:0,availability:'UNAVAILABLE'}}]){
    const mapped=State.mapAnalysisState(input);
    assert.equal(State.validateAnalysisState(mapped).valid,true,JSON.stringify({input,mapped}));
    assert.deepEqual(State.mapAnalysisState(mapped),mapped,'availability mapping must be idempotent for '+JSON.stringify(input));
  }
}

// ---------------------------------------------------------------------------
// 12. Fail-safe evidence rule for the comparability / admissibility dimensions
//     (review #408 residual blocker). Shipping an empty/placeholder object is
//     NOT proof the dimension was evaluated: it must behave exactly like an
//     absent dimension and must never promote the computation or the state.
// ---------------------------------------------------------------------------
{
  // 12a. Empty comparability object: not evaluated, never partial on its own.
  const emptyComparability=State.mapAnalysisState({ev_comparability:{}});
  assert.notEqual(emptyComparability.state,'ANALYSE_PARTIELLE','an empty ev_comparability object must not create a partial analysis');
  assert.equal(emptyComparability.state,State.DEFAULT_UNKNOWN_STATE);
  assert.equal(emptyComparability.state,'DONNEES_INSUFFISANTES');
  assert.deepEqual(emptyComparability.ev_comparability,{comparable:false,reason:'NOT_EVALUATED'});
  assert.equal(emptyComparability.computational_status,'NOT_EVALUATED','an empty dimension must not prove the computation ran');
  assert.equal(State.validateAnalysisState(emptyComparability).valid,true);
  assert.deepEqual(State.mapAnalysisState(emptyComparability),emptyComparability,'empty comparability mapping must be idempotent');

  // 12b. Empty admissibility object: same fail-safe behavior, no invented cause.
  const emptyAdmissibility=State.mapAnalysisState({recommendation_admissibility:{}});
  assert.notEqual(emptyAdmissibility.state,'ANALYSE_PARTIELLE','an empty admissibility object must not create a partial analysis');
  assert.equal(emptyAdmissibility.state,'DONNEES_INSUFFISANTES');
  assert.equal(emptyAdmissibility.recommendation_admissibility.admissible,false);
  assert.equal(emptyAdmissibility.recommendation_admissibility.status,'NOT_EVALUATED');
  assert.deepEqual(emptyAdmissibility.recommendation_admissibility.reason_codes,[],'no blocking reason code may be synthesized');
  assert.equal(emptyAdmissibility.computational_status,'NOT_EVALUATED');
  assert.equal(State.validateAnalysisState(emptyAdmissibility).valid,true);
  assert.deepEqual(State.mapAnalysisState(emptyAdmissibility),emptyAdmissibility,'empty admissibility mapping must be idempotent');

  // A placeholder that only carries a sentinel reason/status or a non-boolean
  // field is still not evaluated.
  for(const placeholder of [{ev_comparability:{reason:'NOT_EVALUATED'}},
    {ev_comparability:{reason:'MISSING_COMPARABLE_EV'}},{ev_comparability:{comparable:'true'}}]){
    const mapped=State.mapAnalysisState(placeholder);
    assert.notEqual(mapped.state,'ANALYSE_PARTIELLE',JSON.stringify(placeholder));
    assert.deepEqual(mapped.ev_comparability,{comparable:false,reason:'NOT_EVALUATED'},JSON.stringify(placeholder));
    assert.equal(mapped.computational_status,'NOT_EVALUATED',JSON.stringify(placeholder));
    assert.deepEqual(State.mapAnalysisState(mapped),mapped,JSON.stringify(placeholder));
  }
  for(const placeholder of [{recommendation_admissibility:{status:'NOT_EVALUATED'}},
    {recommendation_admissibility:{admissible:'false',status:'ADMISSIBLE'}}]){
    const mapped=State.mapAnalysisState(placeholder);
    assert.notEqual(mapped.state,'ANALYSE_PARTIELLE',JSON.stringify(placeholder));
    assert.equal(mapped.recommendation_admissibility.admissible,false,JSON.stringify(placeholder));
    assert.equal(mapped.recommendation_admissibility.status,'NOT_EVALUATED',JSON.stringify(placeholder));
    assert.deepEqual(State.mapAnalysisState(mapped),mapped,JSON.stringify(placeholder));
  }

  // 12c. Explicit `comparable:false` / `admissible:false` ARE evaluated negative
  //      evidence -> ANALYSE_PARTIELLE (never confused with a placeholder).
  const negativeComparability=State.mapAnalysisState({ev_comparability:{comparable:false}});
  assert.equal(negativeComparability.state,'ANALYSE_PARTIELLE');
  assert.equal(negativeComparability.ev_comparability.comparable,false);
  assert.deepEqual(State.mapAnalysisState(negativeComparability),negativeComparability);

  const negativeAdmissibility=State.mapAnalysisState({recommendation_admissibility:{admissible:false}});
  assert.equal(negativeAdmissibility.state,'ANALYSE_PARTIELLE');
  assert.equal(negativeAdmissibility.recommendation_admissibility.admissible,false);
  assert.deepEqual(State.mapAnalysisState(negativeAdmissibility),negativeAdmissibility);

  // 12d. Explicit positive verdicts keep ANALYSE_DISPONIBLE.
  const positiveComparability=State.mapAnalysisState({ev_comparability:{comparable:true}});
  assert.equal(positiveComparability.state,'ANALYSE_DISPONIBLE');
  assert.equal(positiveComparability.ev_comparability.comparable,true);
  assert.deepEqual(State.mapAnalysisState(positiveComparability),positiveComparability);

  const positiveAdmissibility=State.mapAnalysisState({recommendation_admissibility:{admissible:true,status:'ADMISSIBLE'}});
  assert.equal(positiveAdmissibility.state,'ANALYSE_DISPONIBLE');
  assert.equal(positiveAdmissibility.recommendation_admissibility.admissible,true);
  assert.deepEqual(State.mapAnalysisState(positiveAdmissibility),positiveAdmissibility);

  // 12e. A placeholder never masks a legitimate top-level code: it behaves like
  //      an absent dimension (the code still drives the state/reason).
  const placeholderWithCode=State.mapAnalysisState({reason_codes:['NON_COMPARABLE'],ev_comparability:{}});
  assert.equal(placeholderWithCode.state,'ANALYSE_PARTIELLE');
  assert.deepEqual(placeholderWithCode.ev_comparability,{comparable:false,reason:'NON_COMPARABLE'});
  assert.deepEqual(State.mapAnalysisState(placeholderWithCode),placeholderWithCode);

  // 12f. Idempotence + schema conformance across the new fixtures.
  for(const input of [{ev_comparability:{}},{recommendation_admissibility:{}},
    {ev_comparability:{comparable:false}},{recommendation_admissibility:{admissible:false}},
    {ev_comparability:{comparable:true}},{recommendation_admissibility:{admissible:true,status:'ADMISSIBLE'}}]){
    const mapped=State.mapAnalysisState(input);
    assert.equal(State.validateAnalysisState(mapped).valid,true,JSON.stringify({input,mapped}));
    assert.deepEqual(State.mapAnalysisState(mapped),mapped,'placeholder evidence mapping must be idempotent for '+JSON.stringify(input));
  }

  // 12g. The NOT_EVALUATED sentinel always wins, even over an explicit boolean:
  //      a verdict cannot be treated as evaluated when the producer also states
  //      the dimension was not evaluated. It behaves like an absent dimension.
  const sentinelComparable=State.mapAnalysisState({ev_comparability:{comparable:true,reason:'NOT_EVALUATED'}});
  assert.notEqual(sentinelComparable.state,'ANALYSE_DISPONIBLE');
  assert.equal(sentinelComparable.state,State.DEFAULT_UNKNOWN_STATE);
  assert.deepEqual(sentinelComparable.ev_comparability,{comparable:false,reason:'NOT_EVALUATED'});
  assert.equal(sentinelComparable.computational_status,'NOT_EVALUATED');
  assert.equal(State.validateAnalysisState(sentinelComparable).valid,true);
  assert.deepEqual(State.mapAnalysisState(sentinelComparable),sentinelComparable);

  const sentinelAdmissible=State.mapAnalysisState({recommendation_admissibility:{admissible:true,status:'NOT_EVALUATED'}});
  assert.notEqual(sentinelAdmissible.state,'ANALYSE_DISPONIBLE');
  assert.equal(sentinelAdmissible.state,State.DEFAULT_UNKNOWN_STATE);
  assert.equal(sentinelAdmissible.recommendation_admissibility.admissible,false);
  assert.equal(sentinelAdmissible.recommendation_admissibility.status,'NOT_EVALUATED');
  assert.deepEqual(sentinelAdmissible.recommendation_admissibility.reason_codes,[]);
  assert.equal(sentinelAdmissible.computational_status,'NOT_EVALUATED');
  assert.equal(State.validateAnalysisState(sentinelAdmissible).valid,true);
  assert.deepEqual(State.mapAnalysisState(sentinelAdmissible),sentinelAdmissible);

  // 12h. The sentinel also neutralises an explicit negative verdict: a
  //      `comparable:false` / `admissible:false` paired with NOT_EVALUATED is
  //      not an evaluated negative, so it must not create ANALYSE_PARTIELLE.
  const sentinelNegativeComparable=State.mapAnalysisState({ev_comparability:{comparable:false,reason:'NOT_EVALUATED'}});
  assert.notEqual(sentinelNegativeComparable.state,'ANALYSE_PARTIELLE');
  assert.deepEqual(sentinelNegativeComparable.ev_comparability,{comparable:false,reason:'NOT_EVALUATED'});
  assert.equal(State.validateAnalysisState(sentinelNegativeComparable).valid,true);
  assert.deepEqual(State.mapAnalysisState(sentinelNegativeComparable),sentinelNegativeComparable);

  const sentinelNegativeAdmissible=State.mapAnalysisState({recommendation_admissibility:{admissible:false,status:'NOT_EVALUATED'}});
  assert.notEqual(sentinelNegativeAdmissible.state,'ANALYSE_PARTIELLE');
  assert.equal(sentinelNegativeAdmissible.recommendation_admissibility.admissible,false);
  assert.equal(sentinelNegativeAdmissible.recommendation_admissibility.status,'NOT_EVALUATED');
  assert.deepEqual(sentinelNegativeAdmissible.recommendation_admissibility.reason_codes,[]);
  assert.equal(State.validateAnalysisState(sentinelNegativeAdmissible).valid,true);
  assert.deepEqual(State.mapAnalysisState(sentinelNegativeAdmissible),sentinelNegativeAdmissible);

  // 12i. A placeholder that carries producer-supplied codes preserves them
  //      verbatim (never synthesized) and still invents no blocking status.
  const placeholderCodes=State.mapAnalysisState({recommendation_admissibility:{reason_codes:['FUTURE_TAXONOMY_CODE']}});
  assert.equal(placeholderCodes.recommendation_admissibility.status,'NOT_EVALUATED');
  assert.deepEqual(placeholderCodes.recommendation_admissibility.reason_codes,['FUTURE_TAXONOMY_CODE']);
  assert.ok(placeholderCodes.reason_codes.includes('FUTURE_TAXONOMY_CODE'));
  assert.equal(State.validateAnalysisState(placeholderCodes).valid,true);
  assert.deepEqual(State.mapAnalysisState(placeholderCodes),placeholderCodes);
}

// ---------------------------------------------------------------------------
// 13. Empty containers are inert even next to unknown evidence, and the edit
//     source stays byte-identical to the served mirror (review #408 residual
//     acceptance items 3/5/6/7).
// ---------------------------------------------------------------------------
{
  // 13a. An empty container alone synthesizes no top-level reason code and never
  //      promotes the computation: it stays the safe DONNEES_INSUFFISANTES.
  for(const input of [{ev_comparability:{}},{recommendation_admissibility:{}}]){
    const mapped=State.mapAnalysisState(input);
    assert.deepEqual(mapped.reason_codes,[],'an empty container must not synthesize a top-level reason code');
    assert.equal(mapped.state,'DONNEES_INSUFFISANTES');
    assert.equal(mapped.computational_status,'NOT_EVALUATED');
    assert.equal(State.validateAnalysisState(mapped).valid,true,JSON.stringify({input,mapped}));
    assert.deepEqual(State.mapAnalysisState(mapped),mapped);
  }

  // 13b. Combined with an unknown code, the empty container stays inert and the
  //      unknown code is preserved verbatim (never dropped, never optimistic),
  //      with a schema-valid and idempotent result.
  for(const input of [{ev_comparability:{},reason_codes:['FUTURE_TAXONOMY_CODE']},
    {recommendation_admissibility:{},reason_codes:['FUTURE_TAXONOMY_CODE']}]){
    const mapped=State.mapAnalysisState(input);
    assert.deepEqual(mapped.reason_codes,['FUTURE_TAXONOMY_CODE'],'unknown code must be preserved');
    assert.equal(mapped.state,State.DEFAULT_UNKNOWN_STATE);
    assert.deepEqual(mapped.ev_comparability,{comparable:false,reason:'NOT_EVALUATED'});
    assert.equal(mapped.recommendation_admissibility.admissible,false);
    assert.equal(mapped.recommendation_admissibility.status,'NOT_EVALUATED');
    assert.deepEqual(mapped.recommendation_admissibility.reason_codes,[],'no blocking reason code may be synthesized');
    assert.equal(State.validateAnalysisState(mapped).valid,true,JSON.stringify({input,mapped}));
    assert.deepEqual(State.mapAnalysisState(mapped),mapped,'unknown code + empty container must be idempotent');
  }

  // 13c. The edit source and the served site mirror must never drift.
  const source=fs.readFileSync(path.join(ROOT,'src/analytics/analysis-state.js'));
  const mirror=fs.readFileSync(path.join(ROOT,'site/analytics/analysis-state.js'));
  assert.equal(Buffer.compare(source,mirror),0,'src/analytics/analysis-state.js and site/analytics/analysis-state.js must be byte-identical');
}

// ---------------------------------------------------------------------------
// 14. Review #408 explicit-evidence regression matrix. Consolidated lock for the
//     exact fixtures required by the review: an empty container is un-evaluated
//     (never a partial analysis, never COMPLETE), an explicit negative verdict
//     carrying a real blocking code stays ANALYSE_PARTIELLE, and an explicit
//     positive verdict keeps ANALYSE_DISPONIBLE. Every fixture also asserts
//     idempotence and schema validity, and the edit source is re-checked against
//     the served mirror so this block is self-contained.
// ---------------------------------------------------------------------------
{
  // 14a. Empty container: absence of evidence, never an evaluated negative.
  const UN_EVALUATED={comparable:false,reason:'NOT_EVALUATED'};
  for(const {label,input} of [
    {label:'ev_comparability:{}',input:{ev_comparability:{}}},
    {label:'recommendation_admissibility:{}',input:{recommendation_admissibility:{}}}
  ]){
    const mapped=State.mapAnalysisState(input);
    assert.notEqual(mapped.state,'ANALYSE_PARTIELLE',label+': an empty container must not create a partial analysis');
    assert.equal(mapped.state,'DONNEES_INSUFFISANTES',label+': an empty container falls back to the safe state');
    assert.deepEqual(mapped.ev_comparability,UN_EVALUATED,label+': comparability stays explicitly un-evaluated');
    assert.equal(mapped.recommendation_admissibility.admissible,false,label+': admissibility stays closed');
    assert.equal(mapped.recommendation_admissibility.status,'NOT_EVALUATED',label+': admissibility stays explicitly un-evaluated');
    assert.deepEqual(mapped.recommendation_admissibility.reason_codes,[],label+': no blocking reason code may be synthesized');
    assert.notEqual(mapped.computational_status,'COMPLETE',label+': an empty container must not prove the computation ran');
    assert.equal(mapped.computational_status,'NOT_EVALUATED',label+': computation stays un-evaluated');
    assert.equal(State.validateAnalysisState(mapped).valid,true,label+': mapped object must be schema-valid');
    assert.deepEqual(State.mapAnalysisState(mapped),mapped,label+': mapping must be idempotent');
  }

  // 14b. Explicit evaluated negative verdicts paired with a real blocking code
  //      are verified evidence -> ANALYSE_PARTIELLE, not placeholders.
  const negativeComparability=State.mapAnalysisState({ev_comparability:{comparable:false,reason:'MISSING_COMPARABLE_EV'}});
  assert.equal(negativeComparability.state,'ANALYSE_PARTIELLE');
  assert.equal(negativeComparability.ev_comparability.comparable,false);
  assert.equal(negativeComparability.ev_comparability.reason,'MISSING_COMPARABLE_EV','the real blocking code must be preserved verbatim');
  assert.equal(State.validateAnalysisState(negativeComparability).valid,true);
  assert.deepEqual(State.mapAnalysisState(negativeComparability),negativeComparability,'negative comparability must be idempotent');

  const negativeAdmissibility=State.mapAnalysisState({recommendation_admissibility:{admissible:false,status:'RECOMMENDATION_NOT_ADMISSIBLE'}});
  assert.equal(negativeAdmissibility.state,'ANALYSE_PARTIELLE');
  assert.equal(negativeAdmissibility.recommendation_admissibility.admissible,false);
  assert.equal(negativeAdmissibility.recommendation_admissibility.status,'RECOMMENDATION_NOT_ADMISSIBLE','the real blocking status must be preserved verbatim');
  assert.ok(negativeAdmissibility.recommendation_admissibility.reason_codes.includes('RECOMMENDATION_NOT_ADMISSIBLE'));
  assert.equal(State.validateAnalysisState(negativeAdmissibility).valid,true);
  assert.deepEqual(State.mapAnalysisState(negativeAdmissibility),negativeAdmissibility,'negative admissibility must be idempotent');

  // 14c. Explicit evaluated positive verdicts keep ANALYSE_DISPONIBLE.
  const positiveComparability=State.mapAnalysisState({ev_comparability:{comparable:true,reason:null}});
  assert.equal(positiveComparability.state,'ANALYSE_DISPONIBLE');
  assert.equal(positiveComparability.ev_comparability.comparable,true);
  assert.equal(positiveComparability.ev_comparability.reason,null);
  assert.equal(State.validateAnalysisState(positiveComparability).valid,true);
  assert.deepEqual(State.mapAnalysisState(positiveComparability),positiveComparability,'positive comparability must be idempotent');

  const positiveAdmissibility=State.mapAnalysisState({recommendation_admissibility:{admissible:true,status:'ADMISSIBLE'}});
  assert.equal(positiveAdmissibility.state,'ANALYSE_DISPONIBLE');
  assert.equal(positiveAdmissibility.recommendation_admissibility.admissible,true);
  assert.equal(positiveAdmissibility.recommendation_admissibility.status,'ADMISSIBLE');
  assert.equal(State.validateAnalysisState(positiveAdmissibility).valid,true);
  assert.deepEqual(State.mapAnalysisState(positiveAdmissibility),positiveAdmissibility,'positive admissibility must be idempotent');

  // 14d. The edit source and the served mirror stay byte-identical.
  const source=fs.readFileSync(path.join(ROOT,'src/analytics/analysis-state.js'));
  const mirror=fs.readFileSync(path.join(ROOT,'site/analytics/analysis-state.js'));
  assert.equal(Buffer.compare(source,mirror),0,'src/analytics/analysis-state.js and site/analytics/analysis-state.js must be byte-identical');
}

// ---------------------------------------------------------------------------
// 15. Strict absent-dimension equivalence (review #408 residual, strengthened).
//     The strongest possible statement of requirement (3): an empty / placeholder
//     / non-boolean container must be *indistinguishable* from an absent
//     dimension. The mapped object is deep-equal to `mapAnalysisState({})`, no
//     blocker is synthesized, `computational_status` never becomes COMPLETE from
//     the container alone, and adding the container next to unrelated evidence is
//     inert. Only an explicit boolean verdict (without a NOT_EVALUATED sentinel)
//     discriminates: negatives -> ANALYSE_PARTIELLE, positives ->
//     ANALYSE_DISPONIBLE.
// ---------------------------------------------------------------------------
{
  const absent=State.mapAnalysisState({});

  // 15a. Every empty/non-boolean container maps to exactly the same object as a
  //      completely absent dimension.
  const inertContainers=[
    {ev_comparability:{}},
    {recommendation_admissibility:{}},
    {ev_comparability:{},recommendation_admissibility:{}},
    {ev_comparability:{comparable:1}},
    {ev_comparability:{comparable:0}},
    {ev_comparability:{comparable:null}},
    {ev_comparability:{comparable:'true'}},
    {ev_comparability:{reason:'NOT_EVALUATED'}},
    {recommendation_admissibility:{admissible:1}},
    {recommendation_admissibility:{admissible:0}},
    {recommendation_admissibility:{admissible:null}},
    {recommendation_admissibility:{admissible:'true'}},
    {recommendation_admissibility:{status:'NOT_EVALUATED'}},
    {recommendation_admissibility:{reason_codes:[]}}
  ];
  for(const input of inertContainers){
    const mapped=State.mapAnalysisState(input);
    assert.deepEqual(mapped,absent,'an inert container must map exactly like an absent dimension: '+JSON.stringify(input));
    assert.equal(mapped.state,'DONNEES_INSUFFISANTES',JSON.stringify(input));
    assert.notEqual(mapped.state,'ANALYSE_PARTIELLE',JSON.stringify(input));
    assert.equal(mapped.computational_status,'NOT_EVALUATED',JSON.stringify(input));
    assert.deepEqual(mapped.reason_codes,[],JSON.stringify(input));
    assert.equal(State.validateAnalysisState(mapped).valid,true,JSON.stringify(input));
    assert.deepEqual(State.mapAnalysisState(mapped),mapped,JSON.stringify(input));
  }

  // 15b. The NOT_EVALUATED sentinel is recognised case-insensitively and after
  //      trimming, and neutralises an explicit boolean verdict so the dimension
  //      still behaves like an absent one.
  for(const input of [
    {ev_comparability:{comparable:true,reason:'not_evaluated'}},
    {ev_comparability:{comparable:true,reason:'  NOT_EVALUATED  '}},
    {ev_comparability:{comparable:false,reason:'not_evaluated'}},
    {recommendation_admissibility:{admissible:true,status:'not_evaluated'}},
    {recommendation_admissibility:{admissible:true,status:'  NOT_EVALUATED  '}},
    {recommendation_admissibility:{admissible:false,status:'not_evaluated'}}
  ]){
    const mapped=State.mapAnalysisState(input);
    assert.deepEqual(mapped,absent,'a sentinel verdict must behave like an absent dimension: '+JSON.stringify(input));
    assert.notEqual(mapped.state,'ANALYSE_PARTIELLE',JSON.stringify(input));
    assert.notEqual(mapped.state,'ANALYSE_DISPONIBLE',JSON.stringify(input));
    assert.equal(State.validateAnalysisState(mapped).valid,true,JSON.stringify(input));
    assert.deepEqual(State.mapAnalysisState(mapped),mapped,JSON.stringify(input));
  }

  // 15c. An empty container is inert next to unrelated evidence: adding it never
  //      changes the mapping of an unknown code (preserved verbatim, safe state)
  //      nor the mapping of an explicit standalone signal.
  const unknownOnly={reason_codes:['FUTURE_TAXONOMY_CODE']};
  for(const extra of [{ev_comparability:{}},{recommendation_admissibility:{}},
    {ev_comparability:{},recommendation_admissibility:{}}]){
    const mapped=State.mapAnalysisState(Object.assign({},unknownOnly,extra));
    assert.deepEqual(mapped,State.mapAnalysisState(unknownOnly),'an empty container must be inert next to an unknown code: '+JSON.stringify(extra));
    assert.ok(mapped.reason_codes.includes('FUTURE_TAXONOMY_CODE'),JSON.stringify(extra));
    assert.equal(State.validateAnalysisState(mapped).valid,true,JSON.stringify(extra));
    assert.deepEqual(State.mapAnalysisState(mapped),mapped,JSON.stringify(extra));
  }
  for(const input of [
    {posterior_availability:'conditioned',ev_comparability:{}},
    {model_support_status:'SUPPORTED',recommendation_admissibility:{}},
    {computational_status:'COMPLETE',ev_comparability:{},recommendation_admissibility:{}}
  ]){
    const without=Object.assign({},input);
    delete without.ev_comparability;
    delete without.recommendation_admissibility;
    assert.deepEqual(State.mapAnalysisState(input),State.mapAnalysisState(without),'an empty container must not perturb an explicit standalone signal: '+JSON.stringify(input));
  }

  // 15d. Explicit boolean verdicts remain the only discrimination point:
  //      negatives are evaluated evidence (ANALYSE_PARTIELLE), positives keep
  //      ANALYSE_DISPONIBLE, and none is degraded to the absent dimension.
  const negativeComparability=State.mapAnalysisState({ev_comparability:{comparable:false}});
  assert.equal(negativeComparability.state,'ANALYSE_PARTIELLE');
  assert.equal(negativeComparability.computational_status,'COMPLETE');
  assert.equal(State.validateAnalysisState(negativeComparability).valid,true);
  assert.deepEqual(State.mapAnalysisState(negativeComparability),negativeComparability);

  const negativeAdmissibility=State.mapAnalysisState({recommendation_admissibility:{admissible:false}});
  assert.equal(negativeAdmissibility.state,'ANALYSE_PARTIELLE');
  assert.equal(negativeAdmissibility.recommendation_admissibility.admissible,false);
  assert.equal(State.validateAnalysisState(negativeAdmissibility).valid,true);
  assert.deepEqual(State.mapAnalysisState(negativeAdmissibility),negativeAdmissibility);

  const positiveComparability=State.mapAnalysisState({ev_comparability:{comparable:true}});
  assert.equal(positiveComparability.state,'ANALYSE_DISPONIBLE');
  assert.equal(positiveComparability.ev_comparability.comparable,true);
  assert.equal(State.validateAnalysisState(positiveComparability).valid,true);
  assert.deepEqual(State.mapAnalysisState(positiveComparability),positiveComparability);

  const positiveAdmissibility=State.mapAnalysisState({recommendation_admissibility:{admissible:true,status:'ADMISSIBLE'}});
  assert.equal(positiveAdmissibility.state,'ANALYSE_DISPONIBLE');
  assert.equal(positiveAdmissibility.recommendation_admissibility.admissible,true);
  assert.equal(State.validateAnalysisState(positiveAdmissibility).valid,true);
  assert.deepEqual(State.mapAnalysisState(positiveAdmissibility),positiveAdmissibility);

  // 15e. The edit source and the served mirror stay byte-identical.
  const source=fs.readFileSync(path.join(ROOT,'src/analytics/analysis-state.js'));
  const mirror=fs.readFileSync(path.join(ROOT,'site/analytics/analysis-state.js'));
  assert.equal(Buffer.compare(source,mirror),0,'src/analytics/analysis-state.js and site/analytics/analysis-state.js must be byte-identical');
}

console.log(JSON.stringify({
  status:'PASS',
  schema:State.SCHEMA,
  states:STATES.length,
  mapped_codes:Object.keys(State.REASON_CODE_MAP).length,
  adapter_coverage:Adapter.COVERAGE_STATES.length,
  adapter_fail_closed:Adapter.FAIL_CLOSED_STATES.length
}));
