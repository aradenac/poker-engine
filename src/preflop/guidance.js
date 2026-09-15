(function(root,factory){
  const Decision=(typeof module==='object'&&module.exports)?require('./decision.js'):(root&&root.PokerPreflopDecision);
  const api=factory(Decision);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerPreflopGuidance=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(Decision){
  'use strict';

  const SCHEMA='poker-preflop-guidance/v1';
  const STRATEGY_STATES=['PROMOTED','EXPERIMENTAL','NO_VERDICT'];
  const SHA256=/^[0-9a-f]{64}$/;
  const PREFLOP_STREETS=new Set(['PREFLOP','PRE-FLOP']);

  function requireDecisionModule(){
    if(!Decision||typeof Decision.validateDecision!=='function')throw new Error('PokerPreflopDecision contract is required');
  }

  function text(value){return value==null?'':String(value).trim();}
  function upper(value){return text(value).toUpperCase();}
  function array(value){return Array.isArray(value)?value:[];}
  function canonicalJson(value){
    if(Array.isArray(value))return `[${value.map(canonicalJson).join(',')}]`;
    if(value&&typeof value==='object'){
      return `{${Object.keys(value).sort().map(key=>`${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
    }
    return JSON.stringify(value);
  }
  function sameJson(left,right){return canonicalJson(left)===canonicalJson(right);}

  function normalizeStrategy(input={}){
    const state=upper(input.state||'NO_VERDICT');
    if(!STRATEGY_STATES.includes(state))throw new Error(`unsupported strategy state ${state}`);
    const strategy_id=text(input.strategy_id);
    const strategy_sha256=text(input.strategy_sha256).toLowerCase();
    const population_id=input.population_id==null?null:text(input.population_id);
    if(state!=='NO_VERDICT'){
      if(!strategy_id)throw new Error(`${state} strategy_id is required`);
      if(!SHA256.test(strategy_sha256))throw new Error(`${state} strategy_sha256 must be 64 lowercase hex characters`);
      if(!population_id)throw new Error(`${state} population_id is required`);
    }
    return {
      state,
      strategy_id:strategy_id||null,
      strategy_sha256:strategy_sha256||null,
      population_id,
      source:text(input.source)||null,
      decision_source_sha256:text(input.decision_source_sha256).toLowerCase()||null
    };
  }

  function validatePublicSnapshot(snapshot={},decision){
    if(snapshot==null)return {street:'PREFLOP',context_id:decision.context_id,population_id:decision.population_id||null,hero_hand_class:null};
    if(typeof snapshot!=='object'||Array.isArray(snapshot))throw new Error('public_snapshot must be an object');
    const street=upper(snapshot.street||'PREFLOP');
    if(!PREFLOP_STREETS.has(street))throw new Error('preflop guidance cannot consume a postflop street');
    for(const key of ['board','board_cards','public_cards','future_cards','future_public_cards']){
      if(array(snapshot[key]).length)throw new Error(`preflop guidance forbids ${key}`);
    }
    const context_id=snapshot.context_id==null?decision.context_id:text(snapshot.context_id);
    if(context_id!==decision.context_id)throw new Error('public_snapshot.context_id must match decision.context_id');
    const population_id=snapshot.population_id==null?(decision.population_id||null):text(snapshot.population_id);
    if(decision.population_id!=null&&population_id!==String(decision.population_id))throw new Error('public_snapshot.population_id must match decision.population_id');
    return {
      street:'PREFLOP',
      context_id,
      population_id,
      hero_hand_class:snapshot.hero_hand_class==null?null:text(snapshot.hero_hand_class)
    };
  }

  function decisionPayload(decision){
    return {
      schema:decision.schema,
      status:decision.status,
      context_id:decision.context_id,
      population_id:decision.population_id,
      ev_reference:decision.ev_reference,
      actor_contribution_bb:decision.actor_contribution_bb,
      legal_actions:decision.legal_actions,
      selected_id:decision.selected_id,
      action:decision.action,
      target_total_bb:decision.target_total_bb,
      bet_to_bb:decision.bet_to_bb,
      incremental_cost_bb:decision.incremental_cost_bb,
      ev_bb:decision.ev_bb,
      support:decision.support,
      confidence:decision.confidence,
      uncertainty:decision.uncertainty,
      alternatives:decision.alternatives,
      search:decision.search,
      notes:decision.notes
    };
  }

  function cacheKey({strategy,snapshot,decision}){
    const parts=[
      SCHEMA,
      strategy.state,
      strategy.strategy_id||'NONE',
      strategy.strategy_sha256||'NONE',
      strategy.population_id||snapshot.population_id||'NONE',
      snapshot.context_id,
      snapshot.hero_hand_class||'UNKNOWN_HAND',
      decision.selected_id,
      decision.search?.seed==null?'NO_SEED':String(decision.search.seed)
    ];
    return parts.map(value=>encodeURIComponent(String(value))).join('|');
  }

  function expectedLabel(state){
    return state==='PROMOTED'?'PROMOTED_GUIDANCE':state==='EXPERIMENTAL'?'EXPERIMENTAL_NOT_DEFAULT':'NO_VERDICT';
  }

  function buildGuidance(input={}){
    requireDecisionModule();
    const decision=input.decision;
    Decision.validateDecision(decision);
    const strategy=normalizeStrategy(input.strategy||{});
    const snapshot=validatePublicSnapshot(input.public_snapshot||{},decision);
    if(strategy.population_id&&decision.population_id!=null&&strategy.population_id!==String(decision.population_id))throw new Error('strategy population_id must match decision.population_id');
    if(strategy.population_id&&snapshot.population_id&&strategy.population_id!==snapshot.population_id)throw new Error('strategy population_id must match public_snapshot.population_id');

    const promoted=strategy.state==='PROMOTED';
    const experimental=strategy.state==='EXPERIMENTAL';
    const evidence=promoted||experimental?decisionPayload(decision):null;
    return {
      schema:SCHEMA,
      strategy,
      public_snapshot:snapshot,
      recommendation_state:strategy.state,
      default_advice:promoted,
      advisory_label:expectedLabel(strategy.state),
      evidence_decision:evidence,
      cache_key:cacheKey({strategy,snapshot,decision}),
      source_decision_schema:decision.schema,
      future_cards_consumed:false
    };
  }

  function validateGuidanceEnvelope(guidance){
    requireDecisionModule();
    if(!guidance||typeof guidance!=='object'||Array.isArray(guidance)||guidance.schema!==SCHEMA)throw new Error(`expected ${SCHEMA}`);
    const strategy=normalizeStrategy(guidance.strategy||{});
    if(guidance.recommendation_state!==strategy.state)throw new Error('guidance recommendation_state must match strategy.state');
    const expectedDefault=strategy.state==='PROMOTED';
    if(guidance.default_advice!==expectedDefault)throw new Error('guidance default_advice is inconsistent with strategy.state');
    if(guidance.advisory_label!==expectedLabel(strategy.state))throw new Error('guidance advisory_label is inconsistent with strategy.state');
    if(guidance.future_cards_consumed!==false)throw new Error('guidance must attest future_cards_consumed=false');

    const evidence=guidance.evidence_decision;
    if(strategy.state==='NO_VERDICT'){
      if(evidence!=null)throw new Error('NO_VERDICT guidance must not carry evidence_decision');
      return {strategy,evidence:null,snapshot:guidance.public_snapshot};
    }
    if(!evidence||typeof evidence!=='object'||Array.isArray(evidence))throw new Error(`${strategy.state} guidance requires evidence_decision`);
    Decision.validateDecision(evidence);
    const selected=(evidence.alternatives||[]).find(row=>row&&row.id===evidence.selected_id);
    if(!selected)throw new Error('guidance evidence_decision selected alternative is missing');
    if(!sameJson(evidence.support,selected.support))throw new Error('guidance support does not match selected alternative');
    if(evidence.confidence!==selected.confidence)throw new Error('guidance confidence does not match selected alternative');
    if(!sameJson(evidence.uncertainty,selected.uncertainty))throw new Error('guidance uncertainty does not match selected alternative');
    const snapshot=validatePublicSnapshot(guidance.public_snapshot||{},evidence);
    if(strategy.population_id&&evidence.population_id!=null&&strategy.population_id!==String(evidence.population_id))throw new Error('strategy population_id must match evidence_decision.population_id');
    if(strategy.population_id&&snapshot.population_id&&strategy.population_id!==snapshot.population_id)throw new Error('strategy population_id must match public_snapshot.population_id');
    if(guidance.source_decision_schema!==evidence.schema)throw new Error('guidance source_decision_schema must match evidence_decision.schema');
    const expectedCache=cacheKey({strategy,snapshot,decision:evidence});
    if(guidance.cache_key!==expectedCache)throw new Error('guidance cache_key is inconsistent with validated strategy/snapshot/decision');
    return {strategy,evidence,snapshot};
  }

  function noVerdictPayload(guidance){
    return {
      schema:SCHEMA,
      recommendation_state:guidance.recommendation_state,
      advisory_label:guidance.advisory_label,
      default_advice:false,
      strategy:guidance.strategy,
      context_id:guidance.public_snapshot.context_id,
      population_id:guidance.public_snapshot.population_id,
      hero_hand_class:guidance.public_snapshot.hero_hand_class,
      cache_key:guidance.cache_key,
      action:null,
      target_total_bb:null,
      bet_to_bb:null,
      incremental_cost_bb:null,
      ev_bb:null,
      ev_reference:null,
      selected_id:null,
      alternatives:[],
      support:null,
      confidence:null,
      uncertainty:null,
      search:null,
      notes:'No promoted preflop guidance is available for this state.'
    };
  }

  function surfacePayload(guidance,{allow_experimental=false}={}){
    const validated=validateGuidanceEnvelope(guidance);
    const allowed=validated.strategy.state==='PROMOTED'||(allow_experimental&&validated.strategy.state==='EXPERIMENTAL');
    if(!allowed||!validated.evidence)return noVerdictPayload(guidance);
    const d=validated.evidence;
    return {
      schema:SCHEMA,
      recommendation_state:validated.strategy.state,
      advisory_label:guidance.advisory_label,
      default_advice:guidance.default_advice,
      strategy:validated.strategy,
      context_id:d.context_id,
      population_id:d.population_id,
      hero_hand_class:validated.snapshot.hero_hand_class,
      cache_key:guidance.cache_key,
      action:d.action,
      target_total_bb:d.target_total_bb,
      bet_to_bb:d.bet_to_bb,
      incremental_cost_bb:d.incremental_cost_bb,
      ev_bb:d.ev_bb,
      ev_reference:d.ev_reference,
      selected_id:d.selected_id,
      alternatives:d.alternatives,
      support:d.support,
      confidence:d.confidence,
      uncertainty:d.uncertainty,
      search:d.search,
      notes:d.notes
    };
  }

  function surfaceBundle(guidance,options={}){
    const payload=surfacePayload(guidance,options);
    return {feed:payload,detail:payload,trainer:payload};
  }

  return {SCHEMA,STRATEGY_STATES,normalizeStrategy,validatePublicSnapshot,validateGuidanceEnvelope,buildGuidance,surfacePayload,surfaceBundle,cacheKey};
});
