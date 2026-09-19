(function(root,factory){
  const Decision=(typeof module==='object'&&module.exports)?require('../preflop/decision.js'):(root&&root.PokerPreflopDecision);
  const Guidance=(typeof module==='object'&&module.exports)?require('../preflop/guidance.js'):(root&&root.PokerPreflopGuidance);
  const Adapter=(typeof module==='object'&&module.exports)?require('./preflop-decision-adapter.js'):(root&&root.PokerPreflopDecisionAdapter);
  const api=factory(Decision,Guidance,Adapter);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerPreflopRuntime=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(Decision,Guidance,Adapter){
  'use strict';
  const REFERENCE=Object.freeze({
    decision:'RETAIN_REFERENCE',
    issue:108,
    candidate_activated:false,
    population_id:'pokerstars_nlhe_100-200_zoom_play_6max_v1',
    strategy_id:'retained-model-a-v5-preflop-call-fold-reference',
    strategy_version:'2026-09-19.1',
    strategy_sha256:'ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca',
    source:'issue-108-retained-reference',
    scope:'PREFLOP_CALL_FOLD_ONLY'
  });
  const EPS=1e-9;
  const clone=v=>v==null?v:JSON.parse(JSON.stringify(v));
  const finite=(v,name)=>{const n=Number(v);if(!Number.isFinite(n))throw new Error(name+' must be finite');return n;};
  function requireContracts(){
    if(!Decision||!Guidance||!Adapter)throw new Error('canonical preflop contracts are required');
  }
  function identity(){
    return {population_id:REFERENCE.population_id,pack_id:'issue-108-retained-reference',pack_version:REFERENCE.strategy_version,
      strategy_id:REFERENCE.strategy_id,strategy_version:REFERENCE.strategy_version,strategy_sha256:REFERENCE.strategy_sha256,
      decision_source_sha256:null,ev_reference:Decision.EV_REFERENCE};
  }
  function support(samples,source){
    const n=Math.max(0,Math.round(Number(samples)||0));
    return {observations:n,backoff_level:'EXACT_RUNTIME',source:source||'active-reference-call-fold'};
  }
  function uncertainty(samples){
    return {monte_carlo:{standard_error_bb:null,samples:Math.max(0,Math.round(Number(samples)||0)),method:'browser-equity-runtime'},model:{lower_bb:null,upper_bb:null,method:null,status:'REFERENCE'}};
  }
  function normalizePublicState(public_state){
    if(!public_state)throw new Error('public_state is required');
    const wrapper=public_state.snapshot?public_state:{snapshot:public_state};
    const snap=wrapper.snapshot||{};
    const actor=wrapper.legal_view?.actor||(snap.pending||[])[0];
    if(!actor)throw new Error('public_state has no actor');
    return {wrapper,snap,actor};
  }
  function buildCallFold(input={}){
    requireContracts();
    const {wrapper,snap,actor}=normalizePublicState(input.public_state);
    if(String(snap.street||'').toLowerCase()!=='preflop')throw new Error('call/fold reference is preflop-only');
    const legal=wrapper.legal_view||{};
    const toCall=finite(legal.to_call_bb??Math.max(0,Number(snap.current_bet_bb||0)-Number(snap.street_committed_bb?.[actor]||0)),'to_call_bb');
    if(!(toCall>EPS))throw new Error('call/fold reference requires a positive price');
    const actorPaid=finite(legal.actor_street_contribution_bb??snap.street_committed_bb?.[actor]??0,'actor contribution');
    const currentPrice=finite(legal.current_price_bb??snap.current_bet_bb,'current price');
    const callTarget=actorPaid+toCall;
    const callEV=finite(input.call_ev_bb,'call_ev_bb');
    const samples=Math.max(0,Math.round(Number(input.samples)||0)),sup=support(samples,input.support_source);
    const common={support:sup,confidence:samples>=1000?.95:samples>=100?.8:.6,uncertainty:uncertainty(samples)};
    const alternatives=[
      {id:'fold',action:'FOLD',target_total_bb:null,incremental_cost_bb:0,ev_bb:0,...common,sizing_origin:'zero-cost-baseline',notes:'Fold is the zero-EV incremental baseline.'},
      {id:'call',action:'CALL',target_total_bb:callTarget,incremental_cost_bb:toCall,ev_bb:callEV,...common,sizing_origin:'live-price',notes:'Call EV from the retained active reference runtime at the decision point.'}
    ];
    const selected=callEV>0?'call':'fold';
    const contextId=String(input.context_id||input.preflop_context?.context_id||'').trim();
    if(!contextId)throw new Error('exact preflop context_id is required for covered guidance');
    const evidence=Decision.buildDecision({status:'PROMOTED',context_id:contextId,population_id:REFERENCE.population_id,
      actor_contribution_bb:actorPaid,legal_actions:['FOLD','CALL'],alternatives,selected_id:selected,
      search:{candidate_ids:['fold','call'],sizing_grid_source:'retained-reference-live-price',budget:2,seed:null,notes:'No strategy optimization in #341.'},
      notes:'Narrow call/fold surface of the active reference retained by #108.'});
    const strategy={state:'PROMOTED',strategy_id:REFERENCE.strategy_id,strategy_sha256:REFERENCE.strategy_sha256,population_id:REFERENCE.population_id,source:REFERENCE.source,decision_source_sha256:null};
    const guidance=Guidance.buildGuidance({decision:evidence,strategy,public_snapshot:{street:'PREFLOP',context_id:contextId,population_id:REFERENCE.population_id,hero_hand_class:input.hero_hand_class||null}});
    const played=normalizePlayed(input.played_action,{actorPaid,currentPrice,callTarget,callEV});
    return Adapter.buildDecision({identity:identity(),public_state:wrapper,guidance,hand_id:input.hand_id||null,decision_id:input.decision_id||null,
      hero_position:input.hero_position||input.preflop_context?.actor_position||null,preflop_context:input.preflop_context||{context_id:contextId,family:input.facing_context||'UNKNOWN'},
      coverage:{state:'COVERED',support_tier:samples>=1000?'HIGH':samples>=100?'MEDIUM':'LOW',supported_count:2,decision_count:2,coverage_ratio:1,reasons:['ACTIVE_REFERENCE_RETAINED_AFTER_108']},
      alternative_comparability:{fold:{comparable:true},call:{comparable:true}},played_action:played});
  }
  function normalizePlayed(value,{actorPaid=0,currentPrice=0,callTarget=null,callEV=null}={}){
    if(value==null)return null;
    const raw=typeof value==='string'?{action:value}:value,action=String(raw.action||'').toUpperCase();
    if(!action)return null;
    if(action==='FOLD')return {action:'FOLD',target_total_bb:null,alternative_id:'fold',ev_bb:0};
    if(action==='CALL'||action==='LIMP')return {action:'CALL',target_total_bb:raw.target_total_bb??callTarget??currentPrice,alternative_id:'call',ev_bb:raw.ev_bb??callEV};
    return {action,target_total_bb:raw.target_total_bb??null,alternative_id:raw.alternative_id??null,ev_bb:raw.ev_bb??null};
  }
  function buildUnsupported(input={}){
    requireContracts();
    normalizePublicState(input.public_state);
    const contextId=String(input.context_id||input.preflop_context?.context_id||'').trim()||null;
    return Adapter.buildDecision({identity:identity(),public_state:input.public_state,guidance:null,hand_id:input.hand_id||null,decision_id:input.decision_id||null,
      hero_position:input.hero_position||input.preflop_context?.actor_position||null,preflop_context:input.preflop_context||{context_id:contextId,family:input.facing_context||'UNKNOWN'},
      coverage:{state:'UNSUPPORTED',support_tier:'UNKNOWN',supported_count:0,decision_count:0,coverage_ratio:0,reasons:[input.reason||'SPOT_NON_COUVERT']},
      played_action:input.played_action||null});
  }
  function surfaceBundle(decision){requireContracts();return Adapter.surfaceBundle(decision);}
  function isCovered(decision){return !!decision&&decision.schema===Adapter.SCHEMA&&decision.coverage_state==='COVERED'&&decision.recommendation_admissibility?.admissible===true;}
  function assertRetainedReference(decision){
    Adapter.validateRuntimeDecision(decision);
    if(decision.identity?.strategy_id!==REFERENCE.strategy_id||decision.identity?.strategy_sha256!==REFERENCE.strategy_sha256)throw new Error('unexpected preflop strategy identity');
    if(REFERENCE.candidate_activated)throw new Error('#108 candidate must never be active');
    return true;
  }
  return {REFERENCE,identity,buildCallFold,buildUnsupported,surfaceBundle,isCovered,assertRetainedReference};
});