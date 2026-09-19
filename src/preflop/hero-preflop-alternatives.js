(function(root,factory){
  'use strict';
  if(typeof module==='object'&&module.exports){
    module.exports=factory(
      require('../training/nlhe-game-state.js'),
      require('./contract.js'),
      require('./search.js')
    );
    return;
  }
  if(root)root.PokerHeroPreflopAlternatives=factory(
    root.PokerNlheGameState,
    root.PokerPreflopContract,
    root.PokerPreflopSearch
  );
})(typeof globalThis!=='undefined'?globalThis:this,function(GameCore,Contract,Search){
  'use strict';

  const SCHEMA='poker-hero-preflop-legal-alternatives/v1';
  const SUPPORT_VIEW_SCHEMA='poker-preflop-exact-support-view/v1';
  const ISSUE319_SUMMARY_SCHEMA='poker-preflop-sizing-support-audit-summary/v1';
  const EXACT_SUPPORTED='EXACT_SUPPORTED';
  const LEGAL_BUT_UNSUPPORTED='LEGAL_BUT_UNSUPPORTED';
  const STRUCTURAL_LEGAL='STRUCTURAL_LEGAL';
  const EPS=1e-9;
  const POSITIONS_6=['BTN','SB','BB','LJ','HJ','CO'];
  const POSITIONS_HU=['SB_BTN','BB'];

  class HeroPreflopAlternativesError extends Error{
    constructor(code,message,details={}){super(message);this.name='HeroPreflopAlternativesError';this.code=code;this.details=details;}
  }
  const fail=(code,message,details={})=>{throw new HeroPreflopAlternativesError(code,message,details);};
  const round=value=>Number(Number(value).toFixed(9));
  const finite=(value,name)=>{const n=Number(value);if(!Number.isFinite(n))fail('INVALID_NUMBER',name+' must be finite');return n;};
  const nonnegative=(value,name)=>{const n=finite(value,name);if(n<-EPS)fail('INVALID_NUMBER',name+' must be non-negative');return Math.max(0,n);};
  const text=value=>value==null?'':String(value).trim();
  const fmt=value=>{const n=round(value);return Number.isInteger(n)?String(n):String(n).replace(/0+$/,'').replace(/\.$/,'');};
  const clone=value=>value==null?value:JSON.parse(JSON.stringify(value));

  function assertCoreState(state){
    if(!state||typeof state.legalView!=='function'||typeof state.toSnapshot!=='function')fail('GAME_CORE_REQUIRED','NoLimitHoldemState-compatible state is required');
    if(GameCore&&GameCore.NoLimitHoldemState&&!(state instanceof GameCore.NoLimitHoldemState))fail('GAME_CORE_REQUIRED','state must be a NoLimitHoldemState');
    if(String(state.street||'').toLowerCase()!=='preflop')fail('PREFLOP_ONLY','Hero alternative enumeration is preflop-only');
    if(!state.next_actor)fail('NO_PENDING_ACTOR','state has no pending actor');
    return state;
  }

  function derivePositionMap(state,overrides={}){
    assertCoreState(state);
    const seats=[...state.seats],buttonIndex=seats.indexOf(state.button);
    if(buttonIndex<0)fail('POSITION_MAP_INVALID','button is not seated');
    const clockwise=[...seats.slice(buttonIndex),...seats.slice(0,buttonIndex)];
    const labels=seats.length===6?POSITIONS_6:(seats.length===2?POSITIONS_HU:null);
    if(!labels)fail('POSITION_MAP_REQUIRED','automatic position mapping supports 6-max and heads-up only');
    const out=Object.fromEntries(clockwise.map((player,index)=>[player,labels[index]]));
    for(const [player,position] of Object.entries(overrides||{})){
      if(!seats.includes(player))fail('POSITION_MAP_INVALID','unknown player '+player);
      out[player]=Contract.normalizePosition(position,seats.length);
    }
    return out;
  }

  function publicHistory(state,positionByPlayer){
    let aggressionCount=0;
    const out=[];
    for(const row of state.action_log||[]){
      if(String(row.street||'').toLowerCase()!=='preflop')continue;
      const position=positionByPlayer[row.player];
      if(!position)fail('POSITION_MAP_INVALID','missing public position for '+row.player);
      const raw=String(row.action||'').toUpperCase();
      let action=raw;
      if(raw==='CALL')action=aggressionCount===0?'LIMP':'CALL';
      else if(raw==='RAISE'){
        const target=row.target_total_bb==null?null:Number(row.target_total_bb);
        const stack=Number(state.starting_stacks_bb[row.player]);
        action=(target!=null&&Number.isFinite(target)&&Number.isFinite(stack)&&Math.abs(target-stack)<=EPS)?'JAM':'RAISE';
        aggressionCount++;
      }
      out.push({position,action});
    }
    return out;
  }

  function contextFromState(state,{position_by_player={}}={}){
    assertCoreState(state);
    const legal=state.legalView();
    const positionByPlayer=derivePositionMap(state,position_by_player);
    const history=publicHistory(state,positionByPlayer);
    const livePlayers=state.seats.filter(player=>!state.folded[player]);
    const allInPlayers=livePlayers.filter(player=>state.all_in[player]);
    const contribution={},stack={};
    for(const player of livePlayers){
      const position=positionByPlayer[player];
      contribution[position]=round(Number(state.street_committed_bb[player]||0));
      stack[position]=round(Number(state.street_committed_bb[player]||0)+Number(state.stacks_bb[player]||0));
    }
    const context=Contract.buildContext({
      table_size:state.seats.length,
      actor_position:positionByPlayer[legal.actor],
      live_positions:livePlayers.map(player=>positionByPlayer[player]),
      all_in_positions:allInPlayers.map(player=>positionByPlayer[player]),
      history,
      contribution_bb_by_position:contribution,
      stack_bb_by_position:stack,
      current_price_bb:legal.current_price_bb,
      min_raise_to_bb:legal.min_raise_to_bb,
      raise_level:history.filter(row=>row.action==='RAISE'||row.action==='JAM').length,
      pot_before_bb:legal.pot_before_bb,
      pending_positions:(legal.remaining_to_act||[]).map(player=>positionByPlayer[player]),
      raise_reopened:legal.raise_reopened
    });
    const hasAggression=history.some(row=>row.action==='RAISE'||row.action==='JAM');
    const hasLimp=history.some(row=>row.action==='LIMP');
    if(!hasAggression&&!hasLimp&&context.family!=='UNOPENED'){
      context.family='UNOPENED';
      context.canonical_key=Contract.canonicalKey(context);
      context.context_id=Contract.contextId(context);
    }
    return {context,legal,position_by_player:positionByPlayer};
  }

  function normalizeExactSupportView(view){
    if(!view||view.schema!==SUPPORT_VIEW_SCHEMA)fail('SUPPORT_VIEW_INVALID','expected '+SUPPORT_VIEW_SCHEMA);
    if(view.exact_price_only!==true||view.no_silent_nearest_price!==true)fail('SUPPORT_VIEW_INVALID','support view must be exact-price only and forbid nearest-price');
    if(!Array.isArray(view.exact_target_support))fail('SUPPORT_VIEW_INVALID','exact_target_support must be an array');
    const byKey=new Map();
    const rows=view.exact_target_support.map((row,index)=>{
      const target=round(nonnegative(row.target_total_bb,'support target '+index));
      const observations=Math.round(nonnegative(row.observations,'support observations '+index));
      const key=fmt(target);
      if(byKey.has(key))fail('SUPPORT_VIEW_INVALID','duplicate exact target '+key);
      const normalized={target_total_bb:target,observations,support_tier:text(row.support_tier)||null,identifiability:text(row.identifiability)||null};
      byKey.set(key,normalized);
      return normalized;
    }).sort((a,b)=>a.target_total_bb-b.target_total_bb);
    return {
      schema:SUPPORT_VIEW_SCHEMA,
      source_schema:text(view.source_schema)||null,
      source_id:text(view.source_id)||null,
      source_hash:text(view.source_hash)||null,
      exact_price_only:true,
      no_silent_nearest_price:true,
      exact_target_support:rows,
      by_key:byKey
    };
  }

  function supportViewFromIssue319Kts(report){
    if(!report||report.schema!==ISSUE319_SUMMARY_SCHEMA)fail('ISSUE319_REPORT_INVALID','expected '+ISSUE319_SUMMARY_SCHEMA);
    if(report.backoff_contract?.exact_price_first!==true||report.backoff_contract?.no_silent_nearest_price!==true)fail('ISSUE319_REPORT_INVALID','#319 exact-price/no-nearest contract is required');
    const rows=report.kts_sb_two_limpers_projection?.hero_public_context_support?.observed_iso_targets;
    if(!Array.isArray(rows)||!rows.length)fail('ISSUE319_REPORT_INVALID','#319 KTs SB/two-limpers exact iso targets are missing');
    const reportHash=text(report.full_report?.report_hash);
    return normalizeExactSupportView({
      schema:SUPPORT_VIEW_SCHEMA,
      source_schema:report.schema,
      source_id:'issue-319:kts-sb-two-limpers:hero-observed-iso-targets',
      source_hash:reportHash||null,
      exact_price_only:true,
      no_silent_nearest_price:true,
      exact_target_support:rows.map(row=>{
        const n=Number(row.observations)||0;
        return {
          target_total_bb:row.target_total_bb,
          observations:n,
          support_tier:n>=50?'MEDIUM':'LOW',
          identifiability:n>=50?'IDENTIFIABLE_MARGINAL':(n>=20?'BACKOFF_RECOMMENDED':(n>0?'LOW_SUPPORT':'NO_SUPPORT'))
        };
      })
    });
  }

  function structuralSupport(legalSource){
    return {
      status:STRUCTURAL_LEGAL,
      observations:null,
      effective_sample_size:null,
      backoff_level:'LEGALITY_ONLY',
      quality:'UNKNOWN',
      source:legalSource
    };
  }

  function exactSupport(view,row,target){
    const source=[view.source_id,view.source_hash].filter(Boolean).join('@')||view.source_schema||SUPPORT_VIEW_SCHEMA;
    if(!row)return {
      status:LEGAL_BUT_UNSUPPORTED,
      observations:0,
      effective_sample_size:0,
      backoff_level:'UNSUPPORTED',
      quality:'UNSUPPORTED',
      source,
      exact_target_total_bb:target
    };
    return {
      status:EXACT_SUPPORTED,
      observations:row.observations,
      effective_sample_size:row.observations,
      backoff_level:'EXACT',
      quality:row.support_tier||'UNKNOWN',
      source,
      exact_target_total_bb:target,
      identifiability:row.identifiability||null
    };
  }

  function canonicalAlternative({id,action,target_total_bb,incremental_cost_bb,support,comparability_reason}){
    const target=target_total_bb==null?null:round(target_total_bb);
    return {
      id:String(id),
      action:String(action).toUpperCase(),
      target_sizing:target==null?null:{target_total_bb:target,bet_to_bb:target},
      incremental_cost_bb:round(incremental_cost_bb),
      ev_bb:null,
      uncertainty:null,
      support:clone(support),
      confidence:null,
      comparable:false,
      comparability_reason:String(comparability_reason||'EV_NOT_EVALUATED')
    };
  }

  function legalRaiseTarget(target,legal){
    const x=round(finite(target,'raise target'));
    const current=Number(legal.current_price_bb),max=Number(legal.max_raise_to_bb),min=legal.min_raise_to_bb==null?null:Number(legal.min_raise_to_bb);
    if(!(legal.legal_actions||[]).includes('RAISE'))return {legal:false,reason:'RAISE_NOT_LEGAL'};
    if(x<=current+EPS)return {legal:false,reason:'NOT_ABOVE_CURRENT_PRICE'};
    if(x>max+EPS)return {legal:false,reason:'ABOVE_MAX'};
    const isAllIn=Math.abs(x-max)<=EPS;
    if(min!=null&&x<min-EPS&&!isAllIn)return {legal:false,reason:'BELOW_MIN'};
    return {legal:true,is_all_in:isAllIn};
  }

  function enumerateHeroAlternatives({
    state,
    position_by_player={},
    requested_raise_targets_bb=[],
    exact_support
  }={}){
    const {context,legal,position_by_player:positions}=contextFromState(state,{position_by_player});
    const support=normalizeExactSupportView(exact_support||{
      schema:SUPPORT_VIEW_SCHEMA,source_schema:null,source_id:'no-support-declared',source_hash:null,
      exact_price_only:true,no_silent_nearest_price:true,exact_target_support:[]
    });
    const alternatives=[],rejectedTargets=[];
    const legalSource='NoLimitHoldemState.legalView';
    const actorPaid=round(Number(legal.actor_street_contribution_bb||0));
    const coreActions=(legal.legal_actions||[]).map(action=>String(action).toUpperCase());

    if(coreActions.includes('FOLD')){
      alternatives.push(canonicalAlternative({id:'FOLD',action:'FOLD',target_total_bb:null,incremental_cost_bb:0,support:structuralSupport(legalSource)}));
    }
    if(coreActions.includes('CHECK')){
      alternatives.push(canonicalAlternative({id:'CHECK',action:'CHECK',target_total_bb:null,incremental_cost_bb:0,support:structuralSupport(legalSource)}));
    }
    if(coreActions.includes('CALL')){
      const semantic=context.raise_level===0?Search.semanticAction('LIMP',context):Search.semanticAction('CALL',context);
      const target=round(actorPaid+Number(legal.to_call_bb||0));
      alternatives.push(canonicalAlternative({
        id:semantic+'@'+fmt(target),
        action:semantic,
        target_total_bb:target,
        incremental_cost_bb:Number(legal.to_call_bb||0),
        support:structuralSupport(legalSource),
        comparability_reason:'EV_NOT_EVALUATED_STRUCTURAL_LEGAL'
      }));
    }

    let targets=(requested_raise_targets_bb||[]).map(value=>round(finite(value,'requested raise target')));
    if(!targets.length)targets=support.exact_target_support.map(row=>row.target_total_bb);
    targets=[...new Set(targets.map(fmt))].map(Number).sort((a,b)=>a-b);

    if(coreActions.includes('RAISE')){
      const semantic=Search.semanticAction('RAISE',context);
      for(const target of targets){
        const legality=legalRaiseTarget(target,legal);
        if(!legality.legal){
          rejectedTargets.push({target_total_bb:target,status:'ILLEGAL',reason:legality.reason});
          continue;
        }
        const row=support.by_key.get(fmt(target))||null;
        const exact=exactSupport(support,row,target);
        alternatives.push(canonicalAlternative({
          id:semantic+'@'+fmt(target),
          action:semantic,
          target_total_bb:target,
          incremental_cost_bb:round(target-actorPaid),
          support:exact,
          comparability_reason:row?'EV_NOT_EVALUATED_EXACT_SUPPORTED':'LEGAL_BUT_UNSUPPORTED_NO_EV'
        }));
      }
    }else{
      for(const target of targets)rejectedTargets.push({target_total_bb:target,status:'ILLEGAL',reason:'RAISE_NOT_LEGAL'});
    }

    const unsupported=alternatives.filter(row=>row.support?.status===LEGAL_BUT_UNSUPPORTED).map(row=>row.id);
    return {
      schema:SCHEMA,
      canonical_alternative_schema:'poker-preflop-decision/v1#/$defs/alternative',
      diagnostics_contract:'poker-preflop-iso-sizing-diagnostics/v1',
      context_id:context.context_id,
      hero_position:context.actor_position,
      family:context.family,
      raise_level:context.raise_level,
      public_context:clone(context),
      core_legal_view:{
        actor:legal.actor,
        legal_actions:[...coreActions],
        current_price_bb:round(legal.current_price_bb),
        to_call_bb:round(legal.to_call_bb),
        actor_contribution_bb:actorPaid,
        min_raise_to_bb:legal.min_raise_to_bb==null?null:round(legal.min_raise_to_bb),
        max_raise_to_bb:round(legal.max_raise_to_bb)
      },
      exact_support:{
        source_schema:support.source_schema,
        source_id:support.source_id,
        source_hash:support.source_hash,
        exact_price_only:true,
        nearest_price_used:false,
        no_silent_nearest_price:true
      },
      alternatives,
      legal_but_unsupported_ids:unsupported,
      rejected_targets:rejectedTargets,
      information_boundary:{
        future_cards_consumed:false,
        opponent_hole_cards_consumed:false,
        recommendation_consumed:false
      },
      scientific_boundary:{
        ev_computed:false,
        model_a_fit:false,
        model_b_fit:false,
        test_consumed:false
      },
      position_by_player:positions
    };
  }

  return {
    SCHEMA,SUPPORT_VIEW_SCHEMA,ISSUE319_SUMMARY_SCHEMA,
    EXACT_SUPPORTED,LEGAL_BUT_UNSUPPORTED,STRUCTURAL_LEGAL,
    HeroPreflopAlternativesError,
    derivePositionMap,publicHistory,contextFromState,normalizeExactSupportView,
    supportViewFromIssue319Kts,legalRaiseTarget,enumerateHeroAlternatives
  };
});
