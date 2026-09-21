(function(root,factory){
  const Leak=(typeof module==='object'&&module.exports)?require('./leak-analyzer.js'):(root&&root.PokerLeakAnalyzer);
  const api=factory(Leak);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerReviewLeakAdapter=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(Leak){
  'use strict';

  const ADAPTER_SCHEMA='poker-review-leak-adapter/v1';
  const RESOLUTION_SCOPE_SCHEMA='poker-review-resolution-scope/v1';
  const DEFAULT_EV_REFERENCE='review_score_policy_adjusted_incremental_bb';
  const UNAVAILABLE_STRATEGY_ID='UNAVAILABLE_STRATEGY';
  const UNAVAILABLE_STRATEGY_VERSION='UNAVAILABLE';
  const ADMISSIBLE_RESOLUTION_STATUSES=Object.freeze(['ADMISSIBLE_CALCULATED']);
  const CUSTOM_LABEL=/^custom$/i;
  const OVERRIDE_STATUS_SCHEMA='poker-hero-personal-override-status/v1';
  const OVERRIDE_SOURCE='PERSONAL_OVERRIDE';

  function text(v){return v==null?'':String(v).trim();}
  function upper(v){return text(v).toUpperCase();}
  function isCustomStrategyId(v){return CUSTOM_LABEL.test(text(v));}
  function uniqueSorted(values){return Array.from(new Set((Array.isArray(values)?values:[]).map(text).filter(Boolean))).sort();}
  function num(v){const n=Number(v);return Number.isFinite(n)?n:null;}
  function parseAmount(raw){
    let s=text(raw).replace(/\s+/g,'').replace(/[€$£]/g,'');
    if(!s)return null;
    if(s.includes(',')&&s.includes('.'))s=s.lastIndexOf(',')>s.lastIndexOf('.')?s.replace(/\./g,'').replace(',','.'):s.replace(/,/g,'');
    else if(s.includes(','))s=s.replace(',','.');
    const n=Number(s);return Number.isFinite(n)?n:null;
  }
  function parseBigBlind(header){
    const m=String(header||'').match(/\((?:[€$£]?\s*)?([\d.,]+)\s*\/\s*(?:[€$£]?\s*)?([\d.,]+)\)/);
    return m?parseAmount(m[2]):null;
  }
  function normalizeStreet(v){
    const s=upper(v);
    if(s==='PRÉFLOP'||s==='PREFLOP'||s==='PRE-FLOP')return 'PREFLOP';
    return s||'UNKNOWN';
  }
  function normalizeAction(v){
    const s=upper(v);
    if(!s)return 'UNKNOWN';
    if(s.startsWith('FOLD'))return 'FOLD';
    if(s.startsWith('CHECK'))return 'CHECK';
    if(s.startsWith('CALL'))return 'CALL';
    if(s.startsWith('BET'))return 'BET';
    if(s.startsWith('RAISE'))return 'RAISE';
    if(s.startsWith('SHOVE')||s.startsWith('JAM')||s.includes('ALL-IN'))return 'SHOVE';
    return s.split(/\s+/)[0]||'UNKNOWN';
  }
  function splitHands(value){return String(value||'').replace(/\r/g,'').trim().split(/(?=^PokerStars(?: Zoom)? Hand #\d+:)/m).filter(Boolean);}
  function positions(seats,buttonSeat){
    const out=Object.create(null);if(!seats.length||buttonSeat==null)return out;
    const sorted=[...seats].sort((a,b)=>a.seat-b.seat),bi=sorted.findIndex(x=>x.seat===buttonSeat);if(bi<0)return out;
    const ordered=Array.from({length:sorted.length},(_,i)=>sorted[(bi+i)%sorted.length]);
    const templates={2:['BTN','BB'],3:['BTN','SB','BB'],4:['BTN','SB','BB','CO'],5:['BTN','SB','BB','HJ','CO'],6:['BTN','SB','BB','LJ','HJ','CO']};
    (templates[ordered.length]||[]).forEach((p,i)=>{if(ordered[i])out[ordered[i].name]=p;});return out;
  }
  function timestampFromHeader(header){
    const m=String(header||'').match(/ - (\d{4})\/(\d{2})\/(\d{2}) (\d{1,2}):(\d{2}):(\d{2})(?: ([A-Z]+))?/);
    if(!m)return null;
    return m[1]+'-'+m[2]+'-'+m[3]+'T'+m[4].padStart(2,'0')+':'+m[5]+':'+m[6]+'Z';
  }
  function parseStoredHand(raw,sourceName=''){
    const normalized=String(raw||'').replace(/^\uFEFF/,'').replace(/\r/g,'');
    const lines=normalized.split('\n'),header=lines[0]||'';
    const hm=header.match(/^PokerStars(?: Zoom)? Hand #(\d+):/);if(!hm)return null;
    const handId=hm[1],timestamp=timestampFromHeader(header);if(!timestamp)return null;
    const bigBlind=parseBigBlind(header);
    const seats=[];
    for(const line of lines){const m=line.match(/^Seat (\d+): (.+?) \(([^)]+?) in chips\)\s*$/);if(m)seats.push({seat:Number(m[1]),name:m[2]});}
    const bm=normalized.match(/Seat #(\d+) is the button/),buttonSeat=bm?Number(bm[1]):null,pos=positions(seats,buttonSeat);
    const dealt=normalized.match(/^Dealt to (.+?) \[([^\]]+)\]/m),heroName=dealt?dealt[1]:'';
    const steps=[{stepIndex:0,street:'DEAL',actionType:'deal',player:'',actionAmountBB:null,actionStreetPaidBB:null,actorPaidBeforeBB:null,potBeforeBB:0,potAfterBB:0,allIn:false,rawLine:''}];
    let street='PREFLOP',pot=0,streetPaid=Object.create(null);
    const paid=name=>Number(streetPaid[name]||0),setPaid=(name,v)=>{streetPaid[name]=Math.max(0,Number(v)||0);};
    const bb=n=>bigBlind&&Number.isFinite(n)?n/bigBlind:null;
    const push=(player,type,rawAmount,allIn,line,toTotal=null)=>{
      const beforePot=bb(pot),beforePaid=bb(paid(player));
      if(['post','call','bet'].includes(type)&&Number.isFinite(rawAmount)){pot+=rawAmount;setPaid(player,paid(player)+rawAmount);}
      else if(type==='raise'&&Number.isFinite(toTotal)){const add=Math.max(0,toTotal-paid(player));pot+=add;setPaid(player,toTotal);rawAmount=add;}
      else if(type==='return'&&Number.isFinite(rawAmount)){pot=Math.max(0,pot-rawAmount);setPaid(player,paid(player)-rawAmount);}
      steps.push({stepIndex:steps.length,street,actionType:type,player,actionAmountBB:bb(rawAmount),actionStreetPaidBB:bb(paid(player)),actorPaidBeforeBB:beforePaid,potBeforeBB:beforePot,potAfterBB:bb(pot),allIn:!!allIn,rawLine:line});
    };
    for(const line of lines){
      if(line.startsWith('*** FLOP ***')){streetPaid=Object.create(null);street='FLOP';steps.push({stepIndex:steps.length,street,actionType:'deal',player:'',actionAmountBB:null,actionStreetPaidBB:null,actorPaidBeforeBB:null,potBeforeBB:bb(pot),potAfterBB:bb(pot),allIn:false,rawLine:line});continue;}
      if(line.startsWith('*** TURN ***')){streetPaid=Object.create(null);street='TURN';steps.push({stepIndex:steps.length,street,actionType:'deal',player:'',actionAmountBB:null,actionStreetPaidBB:null,actorPaidBeforeBB:null,potBeforeBB:bb(pot),potAfterBB:bb(pot),allIn:false,rawLine:line});continue;}
      if(line.startsWith('*** RIVER ***')){streetPaid=Object.create(null);street='RIVER';steps.push({stepIndex:steps.length,street,actionType:'deal',player:'',actionAmountBB:null,actionStreetPaidBB:null,actorPaidBeforeBB:null,potBeforeBB:bb(pot),potAfterBB:bb(pot),allIn:false,rawLine:line});continue;}
      if(line.startsWith('*** SHOW DOWN ***')||line.startsWith('*** SUMMARY ***')){if(line.startsWith('*** SUMMARY ***'))break;continue;}
      let m=line.match(/^Uncalled bet \(([^)]+)\) returned to (.+)$/);if(m){const a=parseAmount(m[1]);if(a!=null)push(m[2].trim(),'return',a,false,line);continue;}
      m=line.match(/^(.+?): posts (.+?) ([€$£]?\s*[\d.,]+)(?: and is all-in)?$/);if(m){const a=parseAmount(m[3]);if(a!=null)push(m[1],'post',a,/and is all-in$/.test(line),line);continue;}
      m=line.match(/^(.+?): calls ([€$£]?\s*[\d.,]+)(?: and is all-in)?$/);if(m){const a=parseAmount(m[2]);if(a!=null)push(m[1],'call',a,/and is all-in$/.test(line),line);continue;}
      m=line.match(/^(.+?): bets ([€$£]?\s*[\d.,]+)(?: and is all-in)?$/);if(m){const a=parseAmount(m[2]);if(a!=null)push(m[1],'bet',a,/and is all-in$/.test(line),line);continue;}
      m=line.match(/^(.+?): raises ([€$£]?\s*[\d.,]+) to ([€$£]?\s*[\d.,]+)(?: and is all-in)?$/);if(m){const to=parseAmount(m[3]);if(to!=null)push(m[1],'raise',null,/and is all-in$/.test(line),line,to);continue;}
      m=line.match(/^(.+?): checks\b/);if(m){push(m[1],'check',null,false,line);continue;}
      m=line.match(/^(.+?): folds\b/);if(m){push(m[1],'fold',null,false,line);continue;}
    }
    return {id:handId,timestamp,sourceName,heroName,heroPosition:pos[heroName]||'UNKNOWN',positions:pos,bigBlind,steps,raw:normalized};
  }
  function parseStoredHandHistories(sources){
    const hands=new Map();
    for(const source of Array.isArray(sources)?sources:[]){
      for(const raw of splitHands(source&&source.content)){
        const h=parseStoredHand(raw,source&&source.name||'');if(h)hands.set(String(h.id),h);
      }
    }
    return hands;
  }
  function analyzable(step){return !!step&&(['call','bet','raise'].includes(step.actionType)||(['FLOP','TURN','RIVER'].includes(step.street)&&['check','fold'].includes(step.actionType)));}
  function spotFamily(detail,step){
    const s=detail&&detail.simContext||{},parts=[s.potType,s.preflopRole,s.relativePosition].map(upper).filter(Boolean);
    return parts.length?parts.join('|'):(normalizeStreet(step&&step.street)+'|'+normalizeAction(step&&step.actionType));
  }
  function recommendedAction(detail,played){const a=normalizeAction(detail&&detail.bestLabel);return a==='UNKNOWN'?played:a;}
  function reviewScopeAvailability(resolution,available){
    const r=resolution&&typeof resolution==='object'&&!Array.isArray(resolution)?resolution:{};
    return {
      available:!!available,
      status:text(r.status)||'UNAVAILABLE',
      source:text(r.source)||'NONE',
      fail_closed:available?false:true,
      reason_codes:Array.isArray(r.reason_codes)?Array.from(new Set(r.reason_codes.map(text).filter(Boolean))).sort():[]
    };
  }
  // Normalized identity of a Hero strategy resolution. This mirrors the
  // Resolver.identity() accessor (#392) so every downstream surface (Review,
  // Replayer/Compliance, Trainer/header) reads the exact same population-bound
  // population/strategy token instead of re-reading a manifest or inventing a
  // label. A resolution passed through Resolver.identity() is idempotent here.
  function reviewResolutionIdentity(resolution){
    const r=resolution&&typeof resolution==='object'&&!Array.isArray(resolution)?resolution:{};
    const reasons=Array.isArray(r.reason_codes)?Array.from(r.reason_codes):[];
    const rejectCustom=value=>{
      if(!isCustomStrategyId(value))return value==null?null:text(value);
      reasons.push('CUSTOM_LABEL_REJECTED');
      return null;
    };
    const strategy_id=rejectCustom(r.strategy_id);
    const strategy_version=rejectCustom(r.strategy_version);
    return {
      population_id:r.population_id==null?null:text(r.population_id),
      strategy_id,
      strategy_version,
      strategy_sha256:r.strategy_sha256==null?null:text(r.strategy_sha256),
      status:text(r.status)||'UNAVAILABLE',
      source:text(r.source)||'NONE',
      fail_closed:r.fail_closed===true,
      reason_codes:uniqueSorted(reasons)
    };
  }
  // Normalized contextual personal-override status (#task-8zr). `available`
  // reports the presence of an override somewhere in the active population;
  // `active` is only true when the override is actually resolved on the context
  // handed in. A missing population or an unresolvable context is a fail-safe
  // inactive state: the global presence is never promoted to an active override
  // and the status is always sourced from PERSONAL_OVERRIDE, never POPULATION.
  // Literal "Custom" tokens are scrubbed instead of being surfaced.
  function normalizeOverrideStatus(status,options={}){
    const s=status&&typeof status==='object'&&!Array.isArray(status)?status:{};
    const population_id=text(s.population_id)||text(options.population_id)||null;
    const context_keys=uniqueSorted((Array.isArray(s.context_keys)?s.context_keys:[]).filter(key=>!isCustomStrategyId(key)));
    const rawActiveKey=isCustomStrategyId(s.active_context_key)?null:(text(s.active_context_key)||null);
    const available=!!population_id&&(s.available===true||context_keys.length>0);
    const active=available&&s.active===true&&!!rawActiveKey;
    return {
      schema:OVERRIDE_STATUS_SCHEMA,
      source:OVERRIDE_SOURCE,
      population_id,
      available,
      active,
      active_context_key:active?rawActiveKey:null,
      context_keys,
      count:context_keys.length
    };
  }
  // Bridges the population-bound Hero strategy resolver output (#392) into a
  // Review analytics scope. The strategy identity is only ever taken from an
  // admitted calculated resolution; every other state stays explicit as an
  // UNAVAILABLE strategy token that still carries the population/pack identity,
  // so the scope remains selectable/filterable and never falls back to "Custom".
  // The contextual override status is attached verbatim (normalized) so the
  // Review surface reports the same active/inactive state as the Trainer/header.
  function reviewScopeFromResolution(resolution,options={}){
    const raw=resolution&&typeof resolution==='object'&&!Array.isArray(resolution)?resolution:{};
    const normalized=reviewResolutionIdentity(raw);
    const population_id=normalized.population_id||text(options.population_id);
    if(!population_id)throw new Error('resolution.population_id is required');
    const status=normalized.status;
    const resolvedId=normalized.strategy_id||'';
    const resolvedVersion=normalized.strategy_version||'';
    const available=ADMISSIBLE_RESOLUTION_STATUSES.includes(status)&&normalized.fail_closed!==true&&
      !!resolvedId&&!!resolvedVersion&&!isCustomStrategyId(resolvedId)&&!isCustomStrategyId(resolvedVersion);
    const override=normalizeOverrideStatus(options.override!=null?options.override:raw.override,{population_id});
    return {
      schema:RESOLUTION_SCOPE_SCHEMA,
      population_id,
      pack_id:text(options.pack_id)||text(raw.pack_id)||null,
      strategy_id:available?resolvedId:UNAVAILABLE_STRATEGY_ID,
      strategy_version:available?resolvedVersion:(UNAVAILABLE_STRATEGY_VERSION+'@'+status),
      ev_reference:text(options.ev_reference)||text(raw.ev_reference)||DEFAULT_EV_REFERENCE,
      identity:{...normalized,population_id},
      override,
      availability:reviewScopeAvailability(normalized,available)
    };
  }
  function deriveScope(scope,summary){
    if(!scope||!text(scope.population_id))throw new Error('scope.population_id is required');
    const rawStrategyId=text(scope.strategy_id);if(!rawStrategyId)throw new Error('scope.strategy_id is required');
    const custom=isCustomStrategyId(rawStrategyId);
    const strategyId=custom?UNAVAILABLE_STRATEGY_ID:rawStrategyId;
    const rawVersion=text(scope.strategy_version);
    const signature=text(summary&&summary.signature)||rawVersion||'UNKNOWN_REVIEW_SIGNATURE';
    const versionPrefix=custom?UNAVAILABLE_STRATEGY_VERSION+'@':(rawVersion?rawVersion+'@':'');
    return {
      population_id:text(scope.population_id),pack_id:text(scope.pack_id)||null,strategy_id:strategyId,
      strategy_version:versionPrefix+signature,
      ev_reference:text(scope.ev_reference)||DEFAULT_EV_REFERENCE
    };
  }
  function eventFromDetail(hand,summary,detail,scope){
    const step=hand.steps[Number(detail.stepIndex)],sc=deriveScope(scope,summary);
    if(!step||!analyzable(step)||step.player!==hand.heroName)return null;
    const played=normalizeAction(step.actionType),recommended=recommendedAction(detail,played);
    const playedAmount=num(step.actionAmountBB),potBefore=num(step.potBeforeBB),bestCost=num(detail.bestCostBB);
    const playedRatio=(['BET','RAISE','SHOVE'].includes(played)&&playedAmount!=null&&potBefore>0)?playedAmount/potBefore:null;
    const recommendedRatio=(bestCost!=null&&potBefore>0&&['BET','RAISE','SHOVE'].includes(recommended))?bestCost/potBefore:null;
    const sizingError=played===recommended&&bestCost!=null&&playedAmount!=null&&Math.abs(bestCost-playedAmount)>.05;
    const chosen=num(detail.chosenEV),best=num(detail.bestEV),raw=num(detail.rawLossBB),loss=num(detail.lossBB);
    const comparable=detail.comparable!==false&&chosen!=null&&best!=null;
    const uncertainty=(raw!=null&&loss!=null)?Math.max(0,raw-loss):0;
    return Leak.buildDecisionEvent({
      hand_id:String(hand.id),decision_id:'review:'+hand.id+':'+step.stepIndex,timestamp:hand.timestamp,
      population_id:sc.population_id,pack_id:sc.pack_id,strategy_id:sc.strategy_id,strategy_version:sc.strategy_version,ev_reference:sc.ev_reference,
      position:hand.heroPosition,street:normalizeStreet(step.street),spot_family:spotFamily(detail,step),context_id:text(summary.signature)||null,
      action_played:played,action_recommended:recommended,played_target_total_bb:num(step.actionStreetPaidBB),
      recommended_target_total_bb:bestCost==null?null:(num(step.actorPaidBeforeBB)||0)+bestCost,
      played_size_pot_ratio:playedRatio,recommended_size_pot_ratio:recommendedRatio,played_is_all_in:!!step.allIn,
      played_is_overbet:playedRatio!=null&&playedRatio>1,played_ev_bb:comparable?chosen:null,best_ev_bb:comparable?best:null,
      uncertainty_bb:uncertainty,attributed_loss_bb:comparable&&loss!=null?Math.max(0,loss):null,within_noise:!!detail.withinNoise,sizing_error:sizingError,
      support:{covered:true,source:'reviewScores.details'},comparability:{comparable,reason:comparable?null:'MISSING_COMPARABLE_EV'},
      notes:step.rawLine
    });
  }
  function unsupportedEvent(hand,summary,step,scope,reason){
    const sc=deriveScope(scope,summary),played=normalizeAction(step.actionType),ratio=(['BET','RAISE','SHOVE'].includes(played)&&num(step.actionAmountBB)!=null&&num(step.potBeforeBB)>0)?num(step.actionAmountBB)/num(step.potBeforeBB):null;
    return Leak.buildDecisionEvent({
      hand_id:String(hand.id),decision_id:'review:'+hand.id+':'+step.stepIndex,timestamp:hand.timestamp,
      population_id:sc.population_id,pack_id:sc.pack_id,strategy_id:sc.strategy_id,strategy_version:sc.strategy_version,ev_reference:sc.ev_reference,
      position:hand.heroPosition,street:normalizeStreet(step.street),spot_family:normalizeStreet(step.street)+'|'+played,context_id:text(summary.signature)||null,
      action_played:played,action_recommended:'UNKNOWN',played_target_total_bb:num(step.actionStreetPaidBB),played_size_pot_ratio:ratio,
      played_is_all_in:!!step.allIn,played_is_overbet:ratio!=null&&ratio>1,played_ev_bb:null,best_ev_bb:null,
      support:{covered:false,source:'reviewScores',reason:reason||'NO_COMPARABLE_REVIEW_DETAIL'},comparability:{comparable:false,reason:'NO_COMPARABLE_REVIEW_DETAIL'},
      notes:step.rawLine
    });
  }
  function adaptPersistedReviewData(input={}){
    if(!Leak||typeof Leak.buildDecisionEvent!=='function')throw new Error('PokerLeakAnalyzer is required');
    const reviewScores=input.reviewScores&&typeof input.reviewScores==='object'?input.reviewScores:{};
    const hands=parseStoredHandHistories(input.hhSources||[]),events=[],warnings=[];
    for(const [handId,summary] of Object.entries(reviewScores)){
      const hand=hands.get(String(handId));if(!hand){warnings.push('Missing HH source for review score '+handId);continue;}
      const details=Array.isArray(summary&&summary.details)?summary.details:[],byStep=new Map(details.map(d=>[Number(d.stepIndex),d]));
      for(const step of hand.steps){
        if(!analyzable(step)||step.player!==hand.heroName)continue;
        const detail=byStep.get(step.stepIndex),ev=detail?eventFromDetail(hand,summary,detail,input.scope):unsupportedEvent(hand,summary,step,input.scope,'NO_COMPARABLE_REVIEW_DETAIL');
        if(ev)events.push(ev);
      }
    }
    return {schema:ADAPTER_SCHEMA,events,hands,warnings,scope_keys:Array.from(new Set(events.map(e=>Leak.scopeKey(Leak.scopeOf(e))))).sort()};
  }
  function handSource(result,handId,decisionId){
    const hand=result&&result.hands&&result.hands.get?result.hands.get(String(handId)):null;if(!hand)return null;
    const m=String(decisionId||'').match(/:(\d+)$/),step=m?hand.steps[Number(m[1])]:null;
    return {hand_id:String(hand.id),decision_id:String(decisionId||''),source_name:hand.sourceName,timestamp:hand.timestamp,hero_name:hand.heroName,hero_position:hand.heroPosition,action_line:step&&step.rawLine||'',raw_hand_history:hand.raw};
  }

  return {ADAPTER_SCHEMA,RESOLUTION_SCOPE_SCHEMA,OVERRIDE_STATUS_SCHEMA,OVERRIDE_SOURCE,DEFAULT_EV_REFERENCE,UNAVAILABLE_STRATEGY_ID,UNAVAILABLE_STRATEGY_VERSION,splitHands,parseStoredHand,parseStoredHandHistories,adaptPersistedReviewData,handSource,normalizeAction,normalizeStreet,reviewResolutionIdentity,normalizeOverrideStatus,reviewScopeFromResolution};
});
