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
  assert.equal(noNode.recommendation_admissibility.status,'NODE_ABSENT');
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
  assert.deepEqual(partial.statistical_support,{observations:12,distinct_hands:7});
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
  assert.equal(mapped.posterior_availability,'conditioned');
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

console.log(JSON.stringify({
  status:'PASS',
  schema:State.SCHEMA,
  states:STATES.length,
  mapped_codes:Object.keys(State.REASON_CODE_MAP).length,
  adapter_coverage:Adapter.COVERAGE_STATES.length,
  adapter_fail_closed:Adapter.FAIL_CLOSED_STATES.length
}));
