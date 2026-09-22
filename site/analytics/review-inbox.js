(function(root,factory){
  const Leak=(typeof module==='object'&&module.exports)?require('./leak-analyzer.js'):(root&&root.PokerLeakAnalyzer);
  const Adapter=(typeof module==='object'&&module.exports)?require('./review-score-adapter.js'):(root&&root.PokerReviewLeakAdapter);
  const State=(typeof module==='object'&&module.exports)?require('./analysis-state.js'):(root&&root.PokerAnalysisState);
  const api=factory(Leak,Adapter,State);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerReviewInbox=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(Leak,Adapter,State){
  'use strict';

  const INBOX_SCHEMA='poker-review-inbox/v1';
  const ITEM_SCHEMA='poker-review-inbox-item/v1';
  const USER_METADATA_SCHEMA='poker-review-inbox-user-metadata/v1';
  const DEEP_LINK_SCHEMA='poker-review-deep-link/v1';
  const ANALYSIS_STATE_SCHEMA=(State&&State.SCHEMA)||'poker-analysis-state/v1';
  const COVERAGE_COMPLETE='COMPLETE';
  const COVERAGE_INCOMPLETE='INCOMPLETE';
  const STATUS={
    TO_REVIEW:'TO_REVIEW',
    REVIEWED:'REVIEWED',
    CORRECT:'CORRECT',
    INCOMPLETE_ANALYSIS:'INCOMPLETE_ANALYSIS'
  };
  const STATUS_LABELS={
    TO_REVIEW:'À revoir',
    REVIEWED:'Revue',
    CORRECT:'Correcte',
    INCOMPLETE_ANALYSIS:'Analyse incomplète'
  };
  // User-facing labels for the six canonical `poker-analysis-state/v1` states
  // (#393). The labels never collapse two causes into one generic message: the
  // detailed reason codes stay available in the secondary/technical view.
  const ANALYSIS_STATE_LABELS={
    ANALYSE_DISPONIBLE:'Analyse disponible',
    ANALYSE_PARTIELLE:'Analyse partielle',
    CALCUL_EN_COURS:'Calcul en cours',
    DONNEES_INSUFFISANTES:'Données insuffisantes',
    SPOT_NON_SUPPORTE:'Spot non supporté',
    ERREUR_CALCUL:'Erreur de calcul'
  };
  const ANALYSIS_DISPONIBLE='ANALYSE_DISPONIBLE';
  // Event `error_type` values emitted by the frozen leak classifier that mark a
  // real computation failure. Their siblings (ACTION_ERROR, SIZING_ERROR,
  // WITHIN_NOISE, NO_ERROR, UNSUPPORTED, NON_COMPARABLE) are scientific
  // classifications, never worker errors.
  const WORKER_ERROR_TYPES=new Set(['WORKER_ERROR','ANALYSIS_ERROR','WORKER_TIMEOUT','CALCULATION_FAILED','TIMEOUT','ERROR']);
  const STREET_ORDER={PREFLOP:0,FLOP:1,TURN:2,RIVER:3,UNKNOWN:9};
  const STATUS_ORDER={[STATUS.INCOMPLETE_ANALYSIS]:0,[STATUS.TO_REVIEW]:1,[STATUS.REVIEWED]:2,[STATUS.CORRECT]:3};
  const EPS=1e-9;

  function text(v){return v==null?'':String(v).trim();}
  function upper(v){return text(v).toUpperCase();}
  function round(v){return Math.round((Number(v)+Number.EPSILON)*1e9)/1e9;}
  function unique(values){return Array.from(new Set(values.filter(v=>v!=null&&String(v)!==''))).sort();}
  function boolFilter(v){if(v==null||v==='')return null;if(v===true||v==='true')return true;if(v===false||v==='false')return false;throw new Error('boolean filter must be true or false');}
  function asSet(v,normalizer=text){if(v==null||v==='')return null;const rows=Array.isArray(v)?v:[v];return new Set(rows.map(normalizer).filter(Boolean));}
  function stepIndex(decisionId){
    const m=String(decisionId||'').match(/:(\d+)$/);return m?Number(m[1]):null;
  }
  function eventOrder(a,b){
    const ai=stepIndex(a.decision_id),bi=stepIndex(b.decision_id);
    if(ai!=null&&bi!=null&&ai!==bi)return ai-bi;
    if(ai!=null&&bi==null)return -1;if(ai==null&&bi!=null)return 1;
    return String(a.decision_id).localeCompare(String(b.decision_id));
  }
  function decisionPriority(a,b){
    const d=Number(b.ev.attributed_loss_bb)-Number(a.ev.attributed_loss_bb);
    return Math.abs(d)>EPS?d:eventOrder(a,b);
  }
  function normalizeUserMetadata(input){
    const src=input&&input.schema===USER_METADATA_SCHEMA?input:(input&&typeof input==='object'?input:{});
    const raw=src.hands&&typeof src.hands==='object'?src.hands:src;
    const hands={};
    for(const [handId,row] of Object.entries(raw||{})){
      if(handId==='schema'||!row||typeof row!=='object')continue;
      const id=text(handId);if(!id)continue;
      const reviewed=Boolean(row.reviewed);
      const reviewedAt=text(row.reviewed_at)||null;
      if(reviewedAt&&!Number.isFinite(Date.parse(reviewedAt)))throw new Error('reviewed_at must be a valid timestamp for hand '+id);
      hands[id]={reviewed,reviewed_at:reviewedAt?new Date(Date.parse(reviewedAt)).toISOString():null};
    }
    return {schema:USER_METADATA_SCHEMA,hands};
  }
  function setReviewed(metadata,handId,reviewed,reviewedAt=null){
    const current=normalizeUserMetadata(metadata),id=text(handId);if(!id)throw new Error('hand_id is required');
    const next={schema:USER_METADATA_SCHEMA,hands:{...current.hands}};
    if(reviewed){
      const at=text(reviewedAt)||null;
      if(at&&!Number.isFinite(Date.parse(at)))throw new Error('reviewed_at must be a valid timestamp');
      next.hands[id]={reviewed:true,reviewed_at:at?new Date(Date.parse(at)).toISOString():null};
    }else{
      next.hands[id]={reviewed:false,reviewed_at:null};
    }
    return next;
  }
  function deriveScope(scope,summary){
    const populationId=text(scope&&scope.population_id);if(!populationId)throw new Error('scope.population_id is required');
    const strategyId=text(scope&&scope.strategy_id);if(!strategyId)throw new Error('scope.strategy_id is required');
    const signature=text(summary&&summary.signature)||text(scope&&scope.strategy_version)||'UNKNOWN_REVIEW_SIGNATURE';
    return {
      population_id:populationId,
      pack_id:text(scope&&scope.pack_id)||null,
      strategy_id:strategyId,
      strategy_version:(text(scope&&scope.strategy_version)?text(scope.strategy_version)+'@':'')+signature,
      ev_reference:text(scope&&scope.ev_reference)||(Adapter&&Adapter.DEFAULT_EV_REFERENCE)||'review_score_policy_adjusted_incremental_bb'
    };
  }
  function scopeKey(scope){
    if(Leak&&typeof Leak.scopeKey==='function')return Leak.scopeKey(scope);
    return ['population_id','pack_id','strategy_id','strategy_version','ev_reference'].map(k=>k+'='+encodeURIComponent(scope[k]==null?'':scope[k])).join('|');
  }
  function deepLink(event,reason){
    if(!event)return null;
    return {schema:DEEP_LINK_SCHEMA,kind:'REVIEW_DECISION',hand_id:String(event.hand_id),decision_id:String(event.decision_id),step_index:stepIndex(event.decision_id),reason};
  }
  function compactDecision(event){
    if(!event)return null;
    return {
      hand_id:String(event.hand_id),decision_id:String(event.decision_id),step_index:stepIndex(event.decision_id),
      loss_bb:round(event.ev.attributed_loss_bb),nominal_loss_bb:round(event.ev.nominal_loss_bb),
      street:event.context.street,position:event.context.position,spot_family:event.context.spot_family,
      action_played:event.played.action,action_recommended:event.recommended.action,
      sizing_error:Boolean(event.sizing_error),jam:Boolean(event.tags&&event.tags.jam),overbet:Boolean(event.tags&&event.tags.overbet),
      covered:Boolean(event.support&&event.support.covered),comparable:Boolean(event.comparability&&event.comparability.comparable),
      within_noise:Boolean(event.within_noise),error_type:event.error_type
    };
  }
  function coverageFor(summary,events,hasHandSource){
    const reasons=[];
    const analyzable=Number(summary&&summary.analyzableDecisions),finished=Number(summary&&summary.finishedDecisions);
    if(!hasHandSource)reasons.push('MISSING_HH_SOURCE');
    if(!summary||typeof summary!=='object')reasons.push('MISSING_REVIEW_SCORE');
    else if(summary.complete!==true)reasons.push('REVIEW_SCORE_INCOMPLETE');
    if(Number.isFinite(analyzable)&&Number.isFinite(finished)&&finished<analyzable)reasons.push('UNFINISHED_DECISIONS');
    if(!events.length)reasons.push('NO_DECISION_EVENTS');
    if(events.some(e=>!e.support.covered))reasons.push('UNSUPPORTED_DECISIONS');
    if(events.some(e=>e.support.covered&&!e.comparability.comparable))reasons.push('NON_COMPARABLE_DECISIONS');
    return {
      state:reasons.length?COVERAGE_INCOMPLETE:COVERAGE_COMPLETE,
      complete:reasons.length===0,
      reasons:unique(reasons),
      decisions_total:events.length,
      decisions_covered:events.filter(e=>e.support.covered).length,
      decisions_comparable:events.filter(e=>e.support.covered&&e.comparability.comparable).length,
      decisions_within_noise:events.filter(e=>e.within_noise).length,
      analyzable_decisions:Number.isFinite(analyzable)?analyzable:null,
      finished_decisions:Number.isFinite(finished)?finished:null
    };
  }
  function workerErrorType(rows){
    for(const e of rows){const t=upper(e&&e.error_type);if(WORKER_ERROR_TYPES.has(t))return t;}
    return null;
  }
  // Translate the legacy coverage reasons + decision events (support,
  // comparability, worker error) into the shared `poker-analysis-state/v1`
  // object. The taxonomy decides the single user-facing state, while the
  // coverage object is retained untouched for backward compatibility.
  function analysisStateFor(coverage,rows){
    if(!State||typeof State.mapAnalysisState!=='function')return null;
    const comparable=rows.filter(e=>e.support&&e.support.covered&&e.comparability&&e.comparability.comparable);
    const allComparable=rows.length>0&&rows.every(e=>e.support&&e.support.covered&&e.comparability&&e.comparability.comparable);
    const reasonCodes=coverage.reasons.slice();
    const workerError=workerErrorType(rows);
    if(workerError&&!reasonCodes.includes(workerError))reasonCodes.push(workerError);
    const input={
      reason_codes:reasonCodes,
      statistical_support:{observations:comparable.length,distinct_hands:comparable.length?1:0}
    };
    if(coverage.complete)input.ev_comparability={comparable:true,reason:null};
    else if(allComparable)input.ev_comparability={comparable:true,reason:null};
    else input.ev_comparability={
      comparable:false,
      reason:reasonCodes.find(c=>c==='NON_COMPARABLE_DECISIONS'||c==='NO_DECISION_EVENTS'||c==='UNSUPPORTED_DECISIONS')||reasonCodes[0]||'NON_COMPARABLE'
    };
    if(workerError)input.error={type:workerError,retryable:true};
    return State.mapAnalysisState(input);
  }
  function analysisStateLabel(state){
    return ANALYSIS_STATE_LABELS[upper(state)]||'Analyse indisponible';
  }
  function deriveStatus(analysisState,userReview,totalLoss,comparableCount){
    // The taxonomy is the single gate: anything other than an available
    // analysis stays visibly incomplete instead of being promoted to a verdict.
    if(!analysisState||analysisState.state!==ANALYSIS_DISPONIBLE)return STATUS.INCOMPLETE_ANALYSIS;
    if(userReview.reviewed)return STATUS.REVIEWED;
    if(comparableCount>0&&totalLoss<=EPS)return STATUS.CORRECT;
    return STATUS.TO_REVIEW;
  }
  function buildItem(handId,summary,events,adapted,userMetadata,scope){
    const rows=(events||[]).map(e=>Leak.normalizeEvent(e)).sort(eventOrder);
    const eligible=rows.filter(e=>e.support.covered&&e.comparability.comparable);
    const totalLoss=round(eligible.reduce((s,e)=>s+Number(e.ev.attributed_loss_bb||0),0));
    const nominalLoss=round(eligible.reduce((s,e)=>s+Number(e.ev.nominal_loss_bb||0),0));
    const costly=eligible.filter(e=>e.ev.attributed_loss_bb>EPS).slice().sort(decisionPriority)[0]||null;
    const firstComparable=eligible[0]||null,firstAvailable=rows[0]||null;
    const primary=costly||firstComparable||firstAvailable;
    const link=costly?deepLink(costly,'COSTLIEST_DECISION'):firstComparable?deepLink(firstComparable,'FIRST_COMPARABLE_DECISION'):firstAvailable?deepLink(firstAvailable,'FIRST_AVAILABLE_DECISION'):null;
    const hand=adapted&&adapted.hands&&adapted.hands.get?adapted.hands.get(String(handId)):null;
    const coverage=coverageFor(summary,rows,Boolean(hand));
    const analysisState=analysisStateFor(coverage,rows);
    const userReview=(userMetadata.hands&&userMetadata.hands[String(handId)])||{reviewed:false,reviewed_at:null};
    const status=deriveStatus(analysisState,userReview,totalLoss,eligible.length);
    const position=(primary&&primary.context.position)||(hand&&hand.heroPosition)||'UNKNOWN';
    const timestamp=(hand&&hand.timestamp)||(rows[0]&&rows[0].timestamp)||null;
    const facets={
      streets:unique(rows.map(e=>e.context.street)),
      positions:unique(rows.map(e=>e.context.position)),
      spot_families:unique(rows.map(e=>e.context.spot_family)),
      played_actions:unique(rows.map(e=>e.played.action)),
      recommended_actions:unique(rows.map(e=>e.recommended.action)),
      sizing_error:rows.some(e=>e.sizing_error),
      jam:rows.some(e=>e.tags&&e.tags.jam),
      overbet:rows.some(e=>e.tags&&e.tags.overbet)
    };
    const sc=scope;
    return {
      schema:ITEM_SCHEMA,hand_id:String(handId),timestamp,scope:{...sc},
      total_loss_bb:totalLoss,nominal_loss_bb:nominalLoss,
      costliest_decision:compactDecision(costly),primary_decision:compactDecision(primary),
      main_street:primary?primary.context.street:'UNKNOWN',position,
      spot_family:primary?primary.context.spot_family:'UNKNOWN',
      action_played:primary?primary.played.action:'UNKNOWN',action_recommended:primary?primary.recommended.action:'UNKNOWN',
      sizing_error:Boolean(primary&&primary.sizing_error),jam:Boolean(primary&&primary.tags&&primary.tags.jam),overbet:Boolean(primary&&primary.tags&&primary.tags.overbet),
      coverage,coverage_state:coverage.state,
      analysis_state:analysisState,analysis_state_label:analysisState?analysisStateLabel(analysisState.state):null,
      user_review:{reviewed:Boolean(userReview.reviewed),reviewed_at:userReview.reviewed_at||null},
      status,status_label:STATUS_LABELS[status],deep_link:link,facets
    };
  }
  function buildReviewInboxes(input={}){
    if(!Leak||!Adapter)throw new Error('PokerLeakAnalyzer and PokerReviewLeakAdapter are required');
    const reviewScores=input.reviewScores&&typeof input.reviewScores==='object'?input.reviewScores:{};
    const metadata=normalizeUserMetadata(input.user_metadata);
    const adapted=Adapter.adaptPersistedReviewData({reviewScores,hhSources:input.hhSources||[],scope:input.scope});
    const eventsByScope=new Map(),eventsByHand=new Map();
    for(const event of adapted.events){
      const k=scopeKey(Leak.scopeOf(event));
      if(!eventsByScope.has(k))eventsByScope.set(k,{scope:Leak.scopeOf(event),events:[]});
      eventsByScope.get(k).events.push(event);
      const hk=String(event.hand_id);if(!eventsByHand.has(hk))eventsByHand.set(hk,[]);eventsByHand.get(hk).push(event);
    }
    const handScope=new Map();
    for(const [handId,summary] of Object.entries(reviewScores)){
      const rows=eventsByHand.get(String(handId))||[];
      const sc=rows.length?Leak.scopeOf(rows[0]):deriveScope(input.scope,summary);
      const k=scopeKey(sc);handScope.set(String(handId),{scope:sc,key:k});
      if(!eventsByScope.has(k))eventsByScope.set(k,{scope:sc,events:[]});
    }
    const inboxes=[];
    for(const [key,bucket] of eventsByScope){
      const handIds=Object.keys(reviewScores).filter(h=>handScope.get(String(h))&&handScope.get(String(h)).key===key).sort();
      const items=handIds.map(handId=>buildItem(handId,reviewScores[handId],eventsByHand.get(String(handId))||[],adapted,metadata,bucket.scope,input.scope));
      inboxes.push({
        schema:INBOX_SCHEMA,event_schema:Leak.EVENT_SCHEMA,adapter_schema:Adapter.ADAPTER_SCHEMA,
        scope:{...bucket.scope},scope_key:key,items:sortInboxItems(items,'EV_LOSS_DESC'),
        warnings:[...adapted.warnings],user_metadata_schema:USER_METADATA_SCHEMA
      });
    }
    return inboxes.sort((a,b)=>a.scope_key.localeCompare(b.scope_key));
  }
  function buildReviewInbox(input={}){
    const inboxes=buildReviewInboxes(input);
    if(input.scope_key){
      const found=inboxes.find(x=>x.scope_key===input.scope_key);if(!found)throw new Error('scope_key not found');
      return found;
    }
    if(inboxes.length>1)throw new Error('review inbox spans '+inboxes.length+' population/pack/strategy/version/EV scopes; select one scope');
    if(inboxes.length===1)return inboxes[0];
    const scope=deriveScope(input.scope,{signature:text(input.scope&&input.scope.signature)||text(input.scope&&input.scope.strategy_version)||'EMPTY'});
    return {schema:INBOX_SCHEMA,event_schema:Leak.EVENT_SCHEMA,adapter_schema:Adapter.ADAPTER_SCHEMA,scope,scope_key:scopeKey(scope),items:[],warnings:[],user_metadata_schema:USER_METADATA_SCHEMA};
  }

  function matchesSet(set,values){return !set||values.some(v=>set.has(v));}
  function filterInboxItems(items,filters={}){
    const streets=asSet(filters.street,upper),positions=asSet(filters.position,upper),spots=asSet(filters.spot_family,upper),
      played=asSet(filters.action_played,upper),recommended=asSet(filters.action_recommended,upper),statuses=asSet(filters.status,upper),
      coverage=asSet(filters.coverage,upper),analysisStates=asSet(filters.analysis_state,upper);
    const sizing=boolFilter(filters.sizing_error),jam=boolFilter(filters.jam),overbet=boolFilter(filters.overbet);
    const minLoss=filters.min_loss_bb==null||filters.min_loss_bb===''?null:Number(filters.min_loss_bb);
    if(minLoss!=null&&(!Number.isFinite(minLoss)||minLoss<0))throw new Error('min_loss_bb must be a non-negative number');
    return (Array.isArray(items)?items:[]).filter(item=>{
      if(minLoss!=null&&item.total_loss_bb+EPS<minLoss)return false;
      if(!matchesSet(streets,item.facets.streets)||!matchesSet(positions,item.facets.positions)||!matchesSet(spots,item.facets.spot_families))return false;
      if(!matchesSet(played,item.facets.played_actions)||!matchesSet(recommended,item.facets.recommended_actions))return false;
      if(statuses&&!statuses.has(item.status))return false;
      if(coverage&&!coverage.has(item.coverage.state))return false;
      if(analysisStates&&!(item.analysis_state&&analysisStates.has(item.analysis_state.state)))return false;
      if(sizing!=null&&item.facets.sizing_error!==sizing)return false;
      if(jam!=null&&item.facets.jam!==jam)return false;
      if(overbet!=null&&item.facets.overbet!==overbet)return false;
      return true;
    });
  }
  function cmpText(a,b){return String(a||'').localeCompare(String(b||''));}
  function sortInboxItems(items,sort='EV_LOSS_DESC'){
    const rows=[...(Array.isArray(items)?items:[])],mode=upper(sort)||'EV_LOSS_DESC';
    const finalTie=(a,b)=>cmpText(a.hand_id,b.hand_id);
    const cmp={
      EV_LOSS_DESC:(a,b)=>b.total_loss_bb-a.total_loss_bb||finalTie(a,b),
      STREET_ASC:(a,b)=>(STREET_ORDER[a.main_street]??9)-(STREET_ORDER[b.main_street]??9)||finalTie(a,b),
      POSITION_ASC:(a,b)=>cmpText(a.position,b.position)||finalTie(a,b),
      SPOT_FAMILY_ASC:(a,b)=>cmpText(a.spot_family,b.spot_family)||finalTie(a,b),
      PLAYED_ACTION_ASC:(a,b)=>cmpText(a.action_played,b.action_played)||finalTie(a,b),
      RECOMMENDED_ACTION_ASC:(a,b)=>cmpText(a.action_recommended,b.action_recommended)||finalTie(a,b),
      STATUS_ASC:(a,b)=>(STATUS_ORDER[a.status]??9)-(STATUS_ORDER[b.status]??9)||finalTie(a,b),
      HAND_ID_ASC:finalTie
    }[mode];
    if(!cmp)throw new Error('unsupported sort '+mode);
    return rows.sort(cmp);
  }
  function queryInbox(inbox,filters={},sort='EV_LOSS_DESC'){
    if(!inbox||inbox.schema!==INBOX_SCHEMA)throw new Error('expected '+INBOX_SCHEMA);
    return {...inbox,items:sortInboxItems(filterInboxItems(inbox.items,filters),sort),filters:{...filters},sort:upper(sort)};
  }

  return {
    INBOX_SCHEMA,ITEM_SCHEMA,USER_METADATA_SCHEMA,DEEP_LINK_SCHEMA,ANALYSIS_STATE_SCHEMA,STATUS,STATUS_LABELS,
    ANALYSIS_STATE_LABELS,ANALYSIS_DISPONIBLE,COVERAGE_COMPLETE,COVERAGE_INCOMPLETE,
    normalizeUserMetadata,setReviewed,buildReviewInboxes,buildReviewInbox,filterInboxItems,sortInboxItems,queryInbox,
    analysisStateFor,analysisStateLabel,stepIndex
  };
});
