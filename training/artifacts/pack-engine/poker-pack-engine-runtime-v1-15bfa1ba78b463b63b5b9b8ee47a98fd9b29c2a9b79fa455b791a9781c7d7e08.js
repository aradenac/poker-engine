/*! poker-pack-engine-runtime/v1
 * issue: #370
 * source-proof: #360
 * source-commit: 5058c463cd5ed07596115153c2e95b2d7d8c949e
 * source-subset-sha256: b7f61710817e7bfa391d269bc1452242601c9a4bf10e8f4823e358bd6136b81b
 * legacy-mixed-bytes-reused: false
 * deterministic: true
 */
(function(root){
  'use strict';
  (function(){
    const module=undefined;
    const require=undefined;

/* BEGIN src/analytics/leak-analyzer.js | blob 8e86e78d42413bba07a485c4e1d09a579f8838cd | sha256 08b14372da7d47d6ede188725b67b7068dea500c0f511c30b50a9c0c6e041d01 */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerLeakAnalyzer=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';

  const EVENT_SCHEMA='poker-leak-decision-event/v1';
  const REPORT_SCHEMA='poker-leak-analysis/v1';
  const EPS=1e-9;
  const SCOPE_FIELDS=['population_id','pack_id','strategy_id','strategy_version','ev_reference'];
  const DIMENSIONS=['position','street','spot_family','action_pair','error_type'];

  function text(v){return v==null?'':String(v).trim();}
  function upper(v){return text(v).toUpperCase();}
  function finite(v,name){const n=Number(v);if(!Number.isFinite(n))throw new Error(name+' must be finite');return n;}
  function optionalFinite(v,name,opts={}){
    if(v==null||v==='')return null;
    const n=finite(v,name);
    if(opts.min!=null&&n<opts.min-EPS)throw new Error(name+' must be >= '+opts.min);
    if(opts.max!=null&&n>opts.max+EPS)throw new Error(name+' must be <= '+opts.max);
    return n;
  }
  function nonNegativeInteger(v,name){const n=finite(v,name);if(!Number.isInteger(n)||n<0)throw new Error(name+' must be a non-negative integer');return n;}
  function isoTimestamp(v,name='timestamp'){const raw=text(v);if(!raw)throw new Error(name+' is required');const ms=Date.parse(raw);if(!Number.isFinite(ms))throw new Error(name+' must be a valid ISO timestamp');return new Date(ms).toISOString();}
  function requiredText(v,name){const s=text(v);if(!s)throw new Error(name+' is required');return s;}
  function round(v){return Math.round((v+Number.EPSILON)*1e9)/1e9;}
  function stableUnique(values){return Array.from(new Set(values)).sort();}

  function normalizeSupport(input={}){
    const covered=input.covered!==false;
    return {covered,observations:input.observations==null?null:nonNegativeInteger(input.observations,'support.observations'),source:text(input.source)||null,reason:covered?null:(text(input.reason)||'UNSUPPORTED')};
  }
  function normalizeComparability(input={}){
    const comparable=input.comparable!==false;
    return {comparable,reason:comparable?null:(text(input.reason)||'NON_COMPARABLE')};
  }
  function classify(args){
    if(!args.support.covered)return 'UNSUPPORTED';
    if(!args.comparability.comparable)return 'NON_COMPARABLE';
    if(args.nominalLossBB<=EPS)return 'NO_ERROR';
    if(args.withinNoise)return 'WITHIN_NOISE';
    if(args.actionPlayed!==args.actionRecommended)return 'ACTION_ERROR';
    if(args.sizingError)return 'SIZING_ERROR';
    if(args.playedTargetBB!=null&&args.recommendedTargetBB!=null&&Math.abs(args.playedTargetBB-args.recommendedTargetBB)>EPS)return 'SIZING_ERROR';
    return 'ACTION_ERROR';
  }

  function buildDecisionEvent(input={}){
    if(input.schema&&input.schema!==EVENT_SCHEMA)throw new Error('expected '+EVENT_SCHEMA);
    const support=normalizeSupport(input.support||{});
    const comparability=normalizeComparability(input.comparability||{});
    const hand_id=requiredText(input.hand_id,'hand_id');
    const decision_id=requiredText(input.decision_id,'decision_id');
    const timestamp=isoTimestamp(input.timestamp);
    const population_id=requiredText(input.population_id,'population_id');
    const strategy_id=requiredText(input.strategy_id,'strategy_id');
    const strategy_version=requiredText(input.strategy_version,'strategy_version');
    const ev_reference=requiredText(input.ev_reference,'ev_reference');
    const pack_id=text(input.pack_id)||null;
    const position=upper(input.position)||'UNKNOWN';
    const street=upper(input.street)||'UNKNOWN';
    const spot_family=upper(input.spot_family)||'UNKNOWN';
    const context_id=text(input.context_id)||null;
    const action_played=upper(input.action_played)||'UNKNOWN';
    const action_recommended=upper(input.action_recommended)||'UNKNOWN';
    const played_target_total_bb=optionalFinite(input.played_target_total_bb,'played_target_total_bb',{min:0});
    const recommended_target_total_bb=optionalFinite(input.recommended_target_total_bb,'recommended_target_total_bb',{min:0});
    const played_size_pot_ratio=optionalFinite(input.played_size_pot_ratio,'played_size_pot_ratio',{min:0});
    const recommended_size_pot_ratio=optionalFinite(input.recommended_size_pot_ratio,'recommended_size_pot_ratio',{min:0});
    const played_ev_bb=input.played_ev_bb==null?null:finite(input.played_ev_bb,'played_ev_bb');
    const best_ev_bb=input.best_ev_bb==null?null:finite(input.best_ev_bb,'best_ev_bb');
    if(support.covered&&comparability.comparable&&(played_ev_bb==null||best_ev_bb==null))throw new Error('covered comparable decisions require played_ev_bb and best_ev_bb');
    const uncertainty_bb=optionalFinite(input.uncertainty_bb,'uncertainty_bb',{min:0})||0;
    const raw_delta_ev_bb=played_ev_bb==null||best_ev_bb==null?0:round(best_ev_bb-played_ev_bb);
    const nominal_loss_bb=round(Math.max(0,raw_delta_ev_bb));
    const within_noise=Boolean(input.within_noise);
    const sizing_error=Boolean(input.sizing_error);
    const error_type=classify({
      support,comparability,nominalLossBB:nominal_loss_bb,withinNoise:within_noise,sizingError:sizing_error,
      actionPlayed:action_played,actionRecommended:action_recommended,
      playedTargetBB:played_target_total_bb,recommendedTargetBB:recommended_target_total_bb
    });
    const override=input.attributed_loss_bb==null?null:optionalFinite(input.attributed_loss_bb,'attributed_loss_bb',{min:0});
    if(override!=null&&override>nominal_loss_bb+EPS)throw new Error('attributed_loss_bb must be <= nominal EV loss');
    const attributed_loss_bb=(support.covered&&comparability.comparable&&!within_noise)?round(override==null?nominal_loss_bb:override):0;
    const is_jam=Boolean(input.played_is_all_in)||action_played==='SHOVE'||action_played==='JAM';
    const is_overbet=Boolean(input.played_is_overbet)||(played_size_pot_ratio!=null&&played_size_pot_ratio>1+EPS);

    return {
      schema:EVENT_SCHEMA,hand_id,decision_id,timestamp,
      population_id,pack_id,strategy_id,strategy_version,ev_reference,
      context:{position,street,spot_family,context_id},
      played:{action:action_played,target_total_bb:played_target_total_bb,size_pot_ratio:played_size_pot_ratio,is_all_in:is_jam},
      recommended:{action:action_recommended,target_total_bb:recommended_target_total_bb,size_pot_ratio:recommended_size_pot_ratio},
      ev:{played_bb:played_ev_bb,best_bb:best_ev_bb,raw_delta_bb:raw_delta_ev_bb,nominal_loss_bb,attributed_loss_bb,uncertainty_bb},
      support,comparability,error_type,within_noise,sizing_error,
      tags:{jam:is_jam,overbet:is_overbet},notes:text(input.notes)
    };
  }

  function normalizeEvent(input){
    if(!input||input.schema!==EVENT_SCHEMA)return buildDecisionEvent(input);
    return buildDecisionEvent({
      schema:input.schema,hand_id:input.hand_id,decision_id:input.decision_id,timestamp:input.timestamp,
      population_id:input.population_id,pack_id:input.pack_id,strategy_id:input.strategy_id,strategy_version:input.strategy_version,ev_reference:input.ev_reference,
      position:input.context&&input.context.position,street:input.context&&input.context.street,spot_family:input.context&&input.context.spot_family,context_id:input.context&&input.context.context_id,
      action_played:input.played&&input.played.action,played_target_total_bb:input.played&&input.played.target_total_bb,played_size_pot_ratio:input.played&&input.played.size_pot_ratio,
      played_is_all_in:input.played&&input.played.is_all_in,played_is_overbet:input.tags&&input.tags.overbet,
      action_recommended:input.recommended&&input.recommended.action,recommended_target_total_bb:input.recommended&&input.recommended.target_total_bb,recommended_size_pot_ratio:input.recommended&&input.recommended.size_pot_ratio,
      played_ev_bb:input.ev&&input.ev.played_bb,best_ev_bb:input.ev&&input.ev.best_bb,uncertainty_bb:input.ev&&input.ev.uncertainty_bb,attributed_loss_bb:input.ev&&input.ev.attributed_loss_bb,
      support:input.support,comparability:input.comparability,within_noise:input.within_noise,sizing_error:input.sizing_error,notes:input.notes
    });
  }

  function scopeOf(e){return {population_id:e.population_id,pack_id:e.pack_id,strategy_id:e.strategy_id,strategy_version:e.strategy_version,ev_reference:e.ev_reference};}
  function scopeKey(scope){return SCOPE_FIELDS.map(k=>k+'='+encodeURIComponent(scope[k]==null?'':scope[k])).join('|');}
  function asSet(value,upperCase=false){if(value==null)return null;const rows=Array.isArray(value)?value:[value];return new Set(rows.map(x=>upperCase?upper(x):text(x)).filter(Boolean));}

  function filterEvents(events,filters={}){
    const sets={
      population_id:asSet(filters.population_id),pack_id:asSet(filters.pack_id),strategy_id:asSet(filters.strategy_id),strategy_version:asSet(filters.strategy_version),ev_reference:asSet(filters.ev_reference),
      position:asSet(filters.position,true),street:asSet(filters.street,true),spot_family:asSet(filters.spot_family,true),error_type:asSet(filters.error_type,true),
      action_played:asSet(filters.action_played,true),action_recommended:asSet(filters.action_recommended,true)
    };
    const from=filters.from==null||filters.from===''?null:Date.parse(filters.from);
    const to=filters.to==null||filters.to===''?null:Date.parse(filters.to);
    if(filters.from!=null&&filters.from!==''&&!Number.isFinite(from))throw new Error('filters.from must be a valid timestamp');
    if(filters.to!=null&&filters.to!==''&&!Number.isFinite(to))throw new Error('filters.to must be a valid timestamp');
    if(from!=null&&to!=null&&from>to)throw new Error('filters.from must be <= filters.to');
    const minLoss=filters.min_loss_bb==null||filters.min_loss_bb===''?null:optionalFinite(filters.min_loss_bb,'filters.min_loss_bb',{min:0});
    const minSize=filters.min_played_size_pot_ratio==null||filters.min_played_size_pot_ratio===''?null:optionalFinite(filters.min_played_size_pot_ratio,'filters.min_played_size_pot_ratio',{min:0});
    const maxSize=filters.max_played_size_pot_ratio==null||filters.max_played_size_pot_ratio===''?null:optionalFinite(filters.max_played_size_pot_ratio,'filters.max_played_size_pot_ratio',{min:0});
    return events.filter(e=>{
      const pairs=[
        ['population_id',e.population_id],['pack_id',e.pack_id],['strategy_id',e.strategy_id],['strategy_version',e.strategy_version],['ev_reference',e.ev_reference],
        ['position',e.context.position],['street',e.context.street],['spot_family',e.context.spot_family],['error_type',e.error_type],
        ['action_played',e.played.action],['action_recommended',e.recommended.action]
      ];
      for(const [k,v] of pairs)if(sets[k]&&!sets[k].has(v==null?'':String(v)))return false;
      const ms=Date.parse(e.timestamp);if(from!=null&&ms<from)return false;if(to!=null&&ms>to)return false;
      if(filters.covered!=null&&filters.covered!==''&&e.support.covered!==Boolean(filters.covered))return false;
      if(filters.comparable!=null&&filters.comparable!==''&&e.comparability.comparable!==Boolean(filters.comparable))return false;
      if(filters.within_noise!=null&&filters.within_noise!==''&&e.within_noise!==Boolean(filters.within_noise))return false;
      if(filters.sizing_error!=null&&filters.sizing_error!==''&&e.sizing_error!==Boolean(filters.sizing_error))return false;
      if(filters.jam!=null&&filters.jam!==''&&e.tags.jam!==Boolean(filters.jam))return false;
      if(filters.overbet!=null&&filters.overbet!==''&&e.tags.overbet!==Boolean(filters.overbet))return false;
      if(minLoss!=null&&e.ev.attributed_loss_bb+EPS<minLoss)return false;
      const ratio=e.played.size_pot_ratio;
      if(minSize!=null&&(ratio==null||ratio+EPS<minSize))return false;
      if(maxSize!=null&&(ratio==null||ratio-EPS>maxSize))return false;
      return true;
    });
  }

  function sourceRef(e){return {hand_id:e.hand_id,decision_id:e.decision_id};}
  function groupKey(e,d){
    if(d==='position')return e.context.position;
    if(d==='street')return e.context.street;
    if(d==='spot_family')return e.context.spot_family;
    if(d==='action_pair')return e.played.action+'->'+e.recommended.action;
    if(d==='error_type')return e.error_type;
    throw new Error('unsupported dimension '+d);
  }
  function summarizeGroup(key,rows,totalLoss,eligibleCount){
    const hands=stableUnique(rows.map(x=>x.hand_id)),attributed=round(rows.reduce((s,x)=>s+x.ev.attributed_loss_bb,0)),nominal=round(rows.reduce((s,x)=>s+x.ev.nominal_loss_bb,0));
    return {key,decisions:rows.length,hands:hands.length,total_loss_bb:attributed,nominal_loss_bb:nominal,average_loss_bb:rows.length?round(attributed/rows.length):0,
      frequency_pct:eligibleCount?round(rows.length*100/eligibleCount):0,loss_share_pct:totalLoss>EPS?round(attributed*100/totalLoss):0,source_refs:rows.map(sourceRef)};
  }
  function aggregateDimension(events,dimension,totalLoss){
    const groups=new Map();for(const e of events){const key=groupKey(e,dimension);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(e);}
    return Array.from(groups.entries()).map(([k,rows])=>summarizeGroup(k,rows,totalLoss,events.length))
      .sort((a,b)=>b.total_loss_bb-a.total_loss_bb||b.decisions-a.decisions||a.key.localeCompare(b.key));
  }
  function exclusionReason(e){if(!e.support.covered)return 'UNSUPPORTED:'+(e.support.reason||'UNSUPPORTED');if(!e.comparability.comparable)return 'NON_COMPARABLE:'+(e.comparability.reason||'NON_COMPARABLE');return null;}
  function summarizeTagged(events,totalLoss){
    const both=events.filter(x=>x.tags.jam||x.tags.overbet),jam=events.filter(x=>x.tags.jam),overbet=events.filter(x=>x.tags.overbet);
    return {combined:summarizeGroup('JAM_OR_OVERBET',both,totalLoss,events.length),jam:summarizeGroup('JAM',jam,totalLoss,events.length),overbet:summarizeGroup('OVERBET',overbet,totalLoss,events.length)};
  }

  function analyzeLeaks(inputEvents,filters={}){
    if(!Array.isArray(inputEvents))throw new Error('inputEvents must be an array');
    const normalized=inputEvents.map(normalizeEvent),selected=filterEvents(normalized,filters),scopes=new Map();
    for(const e of selected){const s=scopeOf(e);scopes.set(scopeKey(s),s);}
    if(scopes.size>1)throw new Error('analysis spans '+scopes.size+' population/pack/strategy/version/EV scopes; filter to one scope before aggregating');
    const scope=scopes.size?Array.from(scopes.values())[0]:null;
    const eligible=selected.filter(x=>x.support.covered&&x.comparability.comparable);
    const totalLoss=round(eligible.reduce((s,x)=>s+x.ev.attributed_loss_bb,0)),nominalLoss=round(eligible.reduce((s,x)=>s+x.ev.nominal_loss_bb,0));
    const hands=stableUnique(eligible.map(x=>x.hand_id)),contributing=eligible.filter(x=>x.ev.attributed_loss_bb>EPS),exclusions={};
    for(const e of selected){const reason=exclusionReason(e);if(reason)exclusions[reason]=(exclusions[reason]||0)+1;}
    const by={};for(const d of DIMENSIONS)by[d]=aggregateDimension(eligible,d,totalLoss);
    const topDecisions=contributing.slice().sort((a,b)=>b.ev.attributed_loss_bb-a.ev.attributed_loss_bb||a.hand_id.localeCompare(b.hand_id)||a.decision_id.localeCompare(b.decision_id)).map(e=>({
      hand_id:e.hand_id,decision_id:e.decision_id,timestamp:e.timestamp,position:e.context.position,street:e.context.street,spot_family:e.context.spot_family,
      action_played:e.played.action,action_recommended:e.recommended.action,error_type:e.error_type,loss_bb:e.ev.attributed_loss_bb,nominal_loss_bb:e.ev.nominal_loss_bb,
      uncertainty_bb:e.ev.uncertainty_bb,played_size_pot_ratio:e.played.size_pot_ratio,jam:e.tags.jam,overbet:e.tags.overbet
    }));
    const withinNoise=eligible.filter(x=>x.within_noise),noiseNominal=round(withinNoise.reduce((s,x)=>s+x.ev.nominal_loss_bb,0));
    return {schema:REPORT_SCHEMA,event_schema:EVENT_SCHEMA,scope,filters:{...filters},summary:{
      decisions_selected:selected.length,decisions_eligible:eligible.length,decisions_contributing:contributing.length,hands_analyzed:hands.length,
      total_loss_bb:totalLoss,nominal_loss_bb:nominalLoss,within_noise_nominal_loss_bb:noiseNominal,
      loss_bb_per_100_hands:hands.length?round(totalLoss*100/hands.length):null,loss_bb_per_100_decisions:eligible.length?round(totalLoss*100/eligible.length):null,
      coverage_pct:selected.length?round(eligible.length*100/selected.length):null,within_noise_decisions:withinNoise.length,unsupported_decisions:selected.filter(x=>!x.support.covered).length,
      non_comparable_decisions:selected.filter(x=>x.support.covered&&!x.comparability.comparable).length,exclusions
    },leaks:{by,aggressive_sizing:summarizeTagged(eligible,totalLoss),top_decisions:topDecisions},decision_events:selected};
  }

  function analyzeByScope(inputEvents,filters={}){
    if(!Array.isArray(inputEvents))throw new Error('inputEvents must be an array');
    const normalized=inputEvents.map(normalizeEvent),selected=filterEvents(normalized,filters),groups=new Map();
    for(const e of selected){const k=scopeKey(scopeOf(e));if(!groups.has(k))groups.set(k,[]);groups.get(k).push(e);}
    return Array.from(groups.entries()).sort((a,b)=>a[0].localeCompare(b[0])).map(([,rows])=>analyzeLeaks(rows));
  }
  function exportReportJSON(report,opts={}){if(!report||report.schema!==REPORT_SCHEMA)throw new Error('expected '+REPORT_SCHEMA);return JSON.stringify(report,null,opts.pretty===false?0:2);}
  function csvCell(v){if(v==null)return '';const s=typeof v==='object'?JSON.stringify(v):String(v);return /[",\n\r]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;}
  function exportReportCSV(report){
    if(!report||report.schema!==REPORT_SCHEMA)throw new Error('expected '+REPORT_SCHEMA);
    const h=['row_type','dimension','key','hand_id','decision_id','timestamp','position','street','spot_family','action_played','action_recommended','error_type','count','hands','total_loss_bb','nominal_loss_bb','uncertainty_bb','played_size_pot_ratio','frequency_pct','loss_share_pct','jam','overbet','source_refs'];
    const rows=[h.join(',')],push=o=>rows.push(h.map(k=>csvCell(o[k])).join(','));
    push({row_type:'SUMMARY',key:'ALL',count:report.summary.decisions_eligible,hands:report.summary.hands_analyzed,total_loss_bb:report.summary.total_loss_bb,nominal_loss_bb:report.summary.nominal_loss_bb});
    for(const [d,groups] of Object.entries(report.leaks.by))for(const g of groups)push({row_type:'GROUP',dimension:d,key:g.key,count:g.decisions,hands:g.hands,total_loss_bb:g.total_loss_bb,nominal_loss_bb:g.nominal_loss_bb,frequency_pct:g.frequency_pct,loss_share_pct:g.loss_share_pct,source_refs:g.source_refs});
    for(const e of report.decision_events)push({row_type:'DECISION',hand_id:e.hand_id,decision_id:e.decision_id,timestamp:e.timestamp,position:e.context.position,street:e.context.street,spot_family:e.context.spot_family,
      action_played:e.played.action,action_recommended:e.recommended.action,error_type:e.error_type,count:1,hands:1,total_loss_bb:e.ev.attributed_loss_bb,nominal_loss_bb:e.ev.nominal_loss_bb,
      uncertainty_bb:e.ev.uncertainty_bb,played_size_pot_ratio:e.played.size_pot_ratio,jam:e.tags.jam,overbet:e.tags.overbet,source_refs:[sourceRef(e)]});
    return rows.join('\n')+'\n';
  }

  return {EVENT_SCHEMA,REPORT_SCHEMA,SCOPE_FIELDS,DIMENSIONS,buildDecisionEvent,normalizeEvent,scopeOf,scopeKey,filterEvents,analyzeLeaks,analyzeByScope,exportReportJSON,exportReportCSV};
});

/* END src/analytics/leak-analyzer.js */

/* BEGIN src/training/nlhe-game-state.js | blob 57a30094f3e4082c8b5cb990b9d9562cc2ce789e | sha256 ddb509a37ba3eb6b96fd12f6048e765bdfa2fb8ffe4dc3ef048133fe575a3245 */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerNlheGameState=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const EPS=1e-9,STREETS=['preflop','flop','turn','river'],SNAPSHOT_SCHEMA='nlhe-game-state/v1';
  const r=v=>Math.round((Number(v)+Number.EPSILON)*1e9)/1e9;
  const nonnegative=(v,name)=>{const n=Number(v);if(!Number.isFinite(n)||n<-EPS)throw new Error(name+' must be finite and non-negative');return Math.max(0,n);};
  class RuleError extends Error{constructor(message){super(message);this.name='RuleError';}}
  class NoLimitHoldemState{
    constructor({seats,button,stacks_bb,small_blind_bb=.5,big_blind_bb=1}={}){
      if(!Array.isArray(seats)||seats.length<2)throw new Error('at least two seats are required');
      if(new Set(seats).size!==seats.length)throw new Error('seat names must be unique');
      if(!seats.includes(button))throw new Error('button must be seated');
      if(!stacks_bb||Object.keys(stacks_bb).length!==seats.length||seats.some(p=>!Object.prototype.hasOwnProperty.call(stacks_bb,p)))throw new Error('stacks_bb must cover exactly the seated players');
      this.seats=[...seats];this.button=String(button);
      this.small_blind_bb=nonnegative(small_blind_bb,'small_blind_bb');this.big_blind_bb=nonnegative(big_blind_bb,'big_blind_bb');
      if(this.big_blind_bb<=EPS)throw new Error('big blind must be positive');
      if(this.small_blind_bb>this.big_blind_bb+EPS)throw new Error('small blind cannot exceed big blind');
      this.starting_stacks_bb=Object.fromEntries(this.seats.map(p=>[p,nonnegative(stacks_bb[p],`stack[${p}]`)]));
      this.stacks_bb={...this.starting_stacks_bb};
      this.total_committed_bb=Object.fromEntries(this.seats.map(p=>[p,0]));
      this.street_committed_bb=Object.fromEntries(this.seats.map(p=>[p,0]));
      this.folded=Object.fromEntries(this.seats.map(p=>[p,false]));
      this.all_in=Object.fromEntries(this.seats.map(p=>[p,false]));
      this.street='preflop';this.board=[];this.current_bet_bb=0;this.last_full_raise_bb=this.big_blind_bb;this.full_bet_established=false;
      this.acted_since_full_raise=new Set();this.pending=[];this.action_log=[];this.refunds_bb=Object.fromEntries(this.seats.map(p=>[p,0]));
      if(this.seats.length===2){this.small_blind_player=this.button;this.big_blind_player=this.nextSeat(this.button);}
      else{this.small_blind_player=this.nextSeat(this.button);this.big_blind_player=this.nextSeat(this.small_blind_player);}
      this.commit(this.small_blind_player,Math.min(this.small_blind_bb,this.stacks_bb[this.small_blind_player]));
      this.commit(this.big_blind_player,Math.min(this.big_blind_bb,this.stacks_bb[this.big_blind_player]));
      this.current_bet_bb=this.big_blind_bb;this.full_bet_established=true;this.last_full_raise_bb=this.big_blind_bb;
      this.pending=this.orderedFrom(this.nextSeat(this.big_blind_player),true);this.autoCloseDryAction();
    }
    get pot_bb(){return r(Object.values(this.total_committed_bb).reduce((a,b)=>a+Number(b||0),0));}
    get live_players(){return this.seats.filter(p=>!this.folded[p]);}
    get betting_complete(){return this.pending.length===0;}
    get next_actor(){return this.pending[0]||null;}
    nextSeat(player){const i=this.seats.indexOf(player);if(i<0)throw new Error('unknown seat '+player);return this.seats[(i+1)%this.seats.length];}
    orderedFrom(first,actionableOnly=false,exclude=new Set()){
      const i=this.seats.indexOf(first),ordered=[...this.seats.slice(i),...this.seats.slice(0,i)];
      return actionableOnly?ordered.filter(p=>!exclude.has(p)&&!this.folded[p]&&!this.all_in[p]&&this.stacks_bb[p]>EPS):ordered;
    }
    commit(player,amount){amount=nonnegative(amount,'commit amount');if(amount>this.stacks_bb[player]+EPS)throw new RuleError('cannot commit more than remaining stack');amount=Math.min(amount,this.stacks_bb[player]);this.stacks_bb[player]-=amount;this.total_committed_bb[player]+=amount;this.street_committed_bb[player]+=amount;if(this.stacks_bb[player]<=EPS){this.stacks_bb[player]=0;this.all_in[player]=true;}}
    legalView(player=this.next_actor){
      if(!player)throw new RuleError('no player is pending');if(!this.seats.includes(player))throw new Error('unknown player '+player);
      if(this.folded[player]||this.all_in[player])throw new RuleError('folded/all-in player cannot act');
      if(this.pending.length&&player!==this.pending[0])throw new RuleError(player+' is not next to act');
      const paid=this.street_committed_bb[player],remaining=this.stacks_bb[player],toCallFull=Math.max(0,this.current_bet_bb-paid),callCost=Math.min(toCallFull,remaining),maxTo=paid+remaining;
      const opponentsCanRespond=this.seats.some(q=>q!==player&&!this.folded[q]&&!this.all_in[q]&&this.stacks_bb[q]>EPS);
      const raiseReopened=!this.acted_since_full_raise.has(player)||toCallFull+EPS>=this.last_full_raise_bb;
      const canRaise=raiseReopened&&maxTo>this.current_bet_bb+EPS&&opponentsCanRespond;
      const minRaiseTo=canRaise?(this.full_bet_established?this.current_bet_bb+this.last_full_raise_bb:this.big_blind_bb):null;
      const legal=toCallFull>EPS?['FOLD','CALL']:['CHECK'];if(canRaise)legal.push('RAISE');
      return {street:this.street,actor:player,pot_before_bb:this.pot_bb,actor_sunk_total_bb:r(this.total_committed_bb[player]),actor_street_contribution_bb:r(paid),actor_remaining_bb:r(remaining),current_price_bb:r(this.current_bet_bb),to_call_bb:r(callCost),full_to_call_bb:r(toCallFull),free_check:toCallFull<=EPS,legal_actions:legal,raise_reopened:raiseReopened,min_raise_to_bb:minRaiseTo==null?null:r(minRaiseTo),max_raise_to_bb:r(maxTo),remaining_to_act:this.pending[0]===player?this.pending.slice(1):[]};
    }
    applyAction(player,action,{target_total_bb=null}={}){
      const view=this.legalView(player);action=String(action||'').toUpperCase();if(!view.legal_actions.includes(action))throw new RuleError(action+' is not legal for '+player);
      const beforeTotal=this.total_committed_bb[player];
      if(action==='FOLD'){this.folded[player]=true;this.acted_since_full_raise.add(player);this.pending.shift();}
      else if(action==='CHECK'){this.acted_since_full_raise.add(player);this.pending.shift();}
      else if(action==='CALL'){this.commit(player,view.to_call_bb);this.acted_since_full_raise.add(player);this.pending.shift();}
      else{
        if(target_total_bb==null)throw new RuleError('RAISE requires target_total_bb');
        const target=Number(target_total_bb),maxTo=Number(view.max_raise_to_bb);
        if(!Number.isFinite(target)||target>maxTo+EPS)throw new RuleError('raise target exceeds actor stack');
        if(target<=this.current_bet_bb+EPS)throw new RuleError('raise target must increase the current price');
        const isAllIn=Math.abs(target-maxTo)<=EPS,minTo=view.min_raise_to_bb;
        if(minTo!=null&&target+EPS<Number(minTo)&&!isAllIn)throw new RuleError('raise target below minimum '+minTo);
        const oldPrice=this.current_bet_bb,incremental=target-this.street_committed_bb[player];this.commit(player,incremental);
        const newPrice=this.street_committed_bb[player],raiseInc=newPrice-oldPrice;
        let fullRaise=false;
        if(!this.full_bet_established){fullRaise=newPrice+EPS>=this.big_blind_bb;if(fullRaise){this.full_bet_established=true;this.last_full_raise_bb=newPrice;}}
        else{fullRaise=raiseInc+EPS>=this.last_full_raise_bb;if(fullRaise)this.last_full_raise_bb=raiseInc;}
        this.current_bet_bb=Math.max(this.current_bet_bb,newPrice);
        if(fullRaise)this.acted_since_full_raise=new Set([player]);else this.acted_since_full_raise.add(player);
        this.pending=this.orderedFrom(this.nextSeat(player),true,new Set([player]));
      }
      this.autoCloseDryAction();
      const record={index:this.action_log.length,street:this.street,player,action,target_total_bb:target_total_bb==null?null:r(Number(target_total_bb)),incremental_cost_bb:r(this.total_committed_bb[player]-beforeTotal)};
      this.action_log.push(record);return record;
    }
    advanceStreet(board_cards){
      if(!this.betting_complete)throw new RuleError('cannot advance while betting is pending');if(this.live_players.length<=1)throw new RuleError('hand ended by folds');
      const i=STREETS.indexOf(this.street);if(i<0||i>=STREETS.length-1)throw new RuleError('river is the final street');
      const expected=this.street==='preflop'?3:1;if(!Array.isArray(board_cards)||board_cards.length!==expected)throw new Error('invalid board-card count');
      const cards=board_cards.map(String);if(new Set([...this.board,...cards]).size!==this.board.length+cards.length)throw new Error('duplicate board card');
      this.board.push(...cards);this.street=STREETS[i+1];this.street_committed_bb=Object.fromEntries(this.seats.map(p=>[p,0]));this.current_bet_bb=0;this.last_full_raise_bb=this.big_blind_bb;this.full_bet_established=false;this.acted_since_full_raise=new Set();
      this.pending=this.orderedFrom(this.nextSeat(this.button),true);this.autoCloseDryAction();
    }
    autoCloseDryAction(){
      this.pending=this.pending.filter(p=>!this.folded[p]&&!this.all_in[p]);
      const live=this.live_players;if(live.length<=1){this.pending=[];return;}
      const actionable=live.filter(p=>!this.all_in[p]&&this.stacks_bb[p]>EPS);
      if(actionable.length===1){const p=actionable[0];if(Math.max(0,this.current_bet_bb-this.street_committed_bb[p])<=EPS)this.pending=[];else if(!this.pending.includes(p))this.pending=[p];}
      else if(!actionable.length)this.pending=[];
    }
    toSnapshot({include_log=true}={}){
      const data={schema:SNAPSHOT_SCHEMA,seats:[...this.seats],button:this.button,small_blind_player:this.small_blind_player,big_blind_player:this.big_blind_player,small_blind_bb:r(this.small_blind_bb),big_blind_bb:r(this.big_blind_bb),starting_stacks_bb:{...this.starting_stacks_bb},stacks_bb:Object.fromEntries(this.seats.map(p=>[p,r(this.stacks_bb[p])])),total_committed_bb:Object.fromEntries(this.seats.map(p=>[p,r(this.total_committed_bb[p])])),street_committed_bb:Object.fromEntries(this.seats.map(p=>[p,r(this.street_committed_bb[p])])),folded:{...this.folded},all_in:{...this.all_in},street:this.street,board:[...this.board],current_bet_bb:r(this.current_bet_bb),last_full_raise_bb:r(this.last_full_raise_bb),full_bet_established:!!this.full_bet_established,acted_since_full_raise:this.seats.filter(p=>this.acted_since_full_raise.has(p)),pending:[...this.pending],refunds_bb:{...this.refunds_bb}};
      if(include_log)data.action_log=this.action_log.map(x=>({...x}));return data;
    }
  }
  return {EPS,STREETS,SNAPSHOT_SCHEMA,RuleError,NoLimitHoldemState};
});
/* END src/training/nlhe-game-state.js */

/* BEGIN src/preflop/contract.js | blob 14f0767d909b1919be01053e5c02363a21ec9ab9 | sha256 62d2a718b25111c6ab69e103be43d7676ce4cc409da0afbc5adec140f482ab34 */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerPreflopContract=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const SCHEMA='poker-preflop-context/v1';
  const PROBABILITY_SCHEMA='poker-preflop-action-probabilities/v1';
  const STATE_TIMING='BEFORE_ACTION';
  const EPS=1e-9;
  const LEGACY_ORDER=['LJ','HJ','CO','BTN','SB','BB','SB_BTN'];
  const ACTION_ORDER6=['LJ','HJ','CO','BTN','SB','BB'];
  const ACTION_ORDERHU=['SB_BTN','BB'];
  const normPos=(position,tableSize)=>{
    let p=String(position||'').toUpperCase();
    if(p==='UTG')p='LJ';
    return Number(tableSize)===2&&p==='BTN'?'SB_BTN':p;
  };
  const legacyOrder=()=>LEGACY_ORDER;
  const actionOrder=tableSize=>Number(tableSize)===2?ACTION_ORDERHU:ACTION_ORDER6;
  const sortPositions=(positions,tableSize)=>{
    const order=legacyOrder(),rank=new Map(order.map((p,i)=>[p,i]));
    const xs=[...new Set((positions||[]).filter(Boolean).map(p=>normPos(p,tableSize)))];
    xs.sort((a,b)=>(rank.get(a)??999)-(rank.get(b)??999)||a.localeCompare(b));
    return xs;
  };
  const normalizeHistory=history=>{
    if(history==null)return [];
    if(typeof history==='string'){
      return history.split(/[>,]/).map(x=>x.trim()).filter(Boolean).map(token=>{
        const i=token.indexOf(':');
        if(i<1)throw new Error(`invalid preflop history token: ${token}`);
        return {position:token.slice(0,i).trim().toUpperCase(),action:token.slice(i+1).trim().toUpperCase()};
      });
    }
    if(!Array.isArray(history))throw new TypeError('history must be a string or array');
    return history.map(item=>{
      if(!item||typeof item!=='object')throw new TypeError('history items must be objects');
      const position=String(item.position||'').trim().toUpperCase(),action=String(item.action||'').trim().toUpperCase();
      if(!position||!action)throw new Error('invalid preflop history item');
      return {position,action};
    });
  };
  const historyToken=history=>normalizeHistory(history).map(x=>`${x.position}:${x.action}`).join('>');
  const deriveRemainingToAct=({live_positions,all_in_positions=[],history,actor_position,table_size})=>{
    const actor=normPos(actor_position,table_size),live=new Set((live_positions||[]).map(p=>normPos(p,table_size))),allin=new Set((all_in_positions||[]).map(p=>normPos(p,table_size)));
    const hist=normalizeHistory(history).map(x=>({position:normPos(x.position,table_size),action:x.action}));
    let lastRaise=-1;hist.forEach((x,i)=>{if(['RAISE','JAM'].includes(x.action))lastRaise=i;});
    const acted=new Set();
    if(lastRaise>=0){acted.add(hist[lastRaise].position);for(const x of hist.slice(lastRaise+1))acted.add(x.position);}
    else for(const x of hist)acted.add(x.position);
    return actionOrder(table_size).filter(p=>live.has(p)&&!allin.has(p)&&!acted.has(p)&&p!==actor);
  };
  const familyFromHistory=(history,actorPosition)=>{
    const hist=normalizeHistory(history),actor=String(actorPosition||'').toUpperCase();
    if(!hist.length)return 'UNOPENED';
    const raises=[];hist.forEach((x,i)=>{if(['RAISE','JAM'].includes(x.action))raises.push(i);});
    const limps=hist.filter(x=>x.action==='LIMP');
    if(!raises.length)return 'VS_LIMPERS';
    const first=raises[0],callers=hist.slice(first+1).filter(x=>x.action==='CALL');
    const actorRaised=hist.some(x=>x.position===actor&&['RAISE','JAM'].includes(x.action));
    const actorCalled=hist.some(x=>x.position===actor&&['CALL','LIMP'].includes(x.action));
    if(raises.length===1){
      if(limps.length&&first>0){
        const actorLimped=hist.some(x=>x.position===actor&&x.action==='LIMP');
        if(actorLimped)return callers.length?'LIMPER_VS_ISO_CALLERS':'LIMPER_VS_ISO';
        return callers.length?'VS_ISO_CALLERS':'VS_ISO';
      }
      return callers.length?'VS_RFI_CALLERS':'VS_RFI';
    }
    if(raises.length===2)return actorRaised?'OPENER_OR_ISO_VS_3BET':(actorCalled?'CALLER_VS_SQUEEZE_OR_3BET':'COLD_VS_3BET');
    if(raises.length===3)return actorRaised?'AGGRESSOR_VS_4BET':(actorCalled?'CALLER_VS_4BET':'COLD_VS_4BET');
    if(raises.length===4)return 'VS_5BET';
    return 'VS_6BET_PLUS';
  };
  const finiteNonnegative=(value,field)=>{
    const v=Number(value||0);if(!Number.isFinite(v)||v<-EPS)throw new Error(`${field} must be finite and non-negative`);return Math.max(0,v);
  };
  const roundBB=value=>Number(Number(value).toFixed(9));
  const legalActionsForState=({to_call_bb,actor_contribution_bb,actor_remaining_bb,min_raise_to_bb,max_raise_to_bb,raise_reopened=true,raise_level=0})=>{
    const toCall=Math.max(0,Number(to_call_bb)||0),remaining=Math.max(0,Number(actor_remaining_bb)||0),actorPaid=Math.max(0,Number(actor_contribution_bb)||0),maxTo=Math.max(actorPaid,Number(max_raise_to_bb)||0),rl=Number(raise_level)||0;
    const legal=[];
    if(toCall>EPS){legal.push('FOLD');if(remaining>EPS)legal.push(rl===0?'LIMP':'CALL');}
    else legal.push('CHECK');
    const canIncrease=remaining>toCall+EPS&&maxTo>actorPaid+toCall+EPS;
    if(raise_reopened&&canIncrease){if(min_raise_to_bb!=null&&maxTo+EPS>=Number(min_raise_to_bb))legal.push('RAISE');legal.push('JAM');}
    return legal;
  };
  const canonicalKey=context=>{
    const hist=historyToken(context.history||[]),live=(context.live_positions||[]).join(','),allin=(context.all_in_positions||[]).join(','),remaining=(context.remaining_to_act_positions||[]).join(',');
    return `${Number(context.table_size)||0}|${context.actor_position||''}|family=${context.family||''}|rl=${Number(context.raise_level)||0}|free=${context.free_check?1:0}|live=${live}|allin=${allin}|remaining=${remaining}|hist=${hist}`;
  };
  // FNV-1a is used only as a deterministic browser identifier. Scientific
  // equality is defined by canonical fields/key, not by this short id.
  const contextId=context=>{
    const keys=['schema','state_timing','table_size','actor_position','family','raise_level','live_positions','all_in_positions','remaining_to_act_positions','history','limper_positions','caller_positions','contribution_bb_by_position','actor_contribution_bb','current_price_bb','to_call_bb','free_check','pot_before_bb','actor_remaining_bb','effective_stack_bb','legal_actions','min_raise_to_bb','max_raise_to_bb','raise_reopened'];
    const structural={};for(const k of keys)if(Object.prototype.hasOwnProperty.call(context,k))structural[k]=context[k];
    const text=JSON.stringify(structural,Object.keys(structural).sort());let h=2166136261>>>0;for(let i=0;i<text.length;i++){h^=text.charCodeAt(i);h=Math.imul(h,16777619)>>>0;}return `PFCJS_${h.toString(16).padStart(8,'0')}`;
  };
  const buildContext=args=>{
    const n=Number(args.table_size);if(!Number.isInteger(n)||n<2)throw new Error('table_size must be at least 2');
    const actor=normPos(args.actor_position,n),hist=normalizeHistory(args.history).map(x=>({position:normPos(x.position,n),action:x.action}));
    const live=sortPositions(args.live_positions,n),allin=sortPositions(args.all_in_positions||[],n);if(!live.includes(actor))throw new Error('actor must be live');if(allin.includes(actor))throw new Error('all-in actor cannot act');
    const cin=args.contribution_bb_by_position||{},contrib={};for(const p of [...new Set([...live,...allin])])contrib[p]=roundBB(finiteNonnegative(cin[p]||0,`contribution[${p}]`));
    const actorPaid=contrib[actor]||0,price=finiteNonnegative(args.current_price_bb==null?Math.max(0,...Object.values(contrib)):args.current_price_bb,'current_price_bb'),toCall=Math.max(0,price-actorPaid);
    const sin=args.stack_bb_by_position||{},actorStack=finiteNonnegative(sin[actor]??actorPaid,'actor stack');if(actorStack+EPS<actorPaid)throw new Error('actor stack below contribution');
    const actorRemaining=Math.max(0,actorStack-actorPaid),oppStacks=live.filter(p=>p!==actor).map(p=>finiteNonnegative(sin[p]??contrib[p]??0,`stack[${p}]`)),effectiveStack=Math.min(actorStack,oppStacks.length?Math.max(...oppStacks):actorStack),maxRaiseTo=actorStack;
    const rl=args.raise_level==null?hist.filter(x=>['RAISE','JAM'].includes(x.action)).length:Number(args.raise_level);if(rl<0)throw new Error('negative raise level');
    let minRaiseTo=args.min_raise_to_bb==null?price+1:finiteNonnegative(args.min_raise_to_bb,'min_raise_to_bb');
    let pending;if(args.pending_positions==null)pending=deriveRemainingToAct({live_positions:live,all_in_positions:allin,history:hist,actor_position:actor,table_size:n});else pending=args.pending_positions.map(p=>normPos(p,n)).filter(p=>live.includes(p)&&!allin.includes(p)&&p!==actor);
    const firstRaise=hist.findIndex(x=>['RAISE','JAM'].includes(x.action)),prefix=firstRaise<0?hist:hist.slice(0,firstRaise),limpers=prefix.filter(x=>x.action==='LIMP').map(x=>x.position),callers=firstRaise<0?[]:hist.slice(firstRaise+1).filter(x=>x.action==='CALL').map(x=>x.position);
    const legal=legalActionsForState({to_call_bb:toCall,actor_contribution_bb:actorPaid,actor_remaining_bb:actorRemaining,min_raise_to_bb:minRaiseTo,max_raise_to_bb:maxRaiseTo,raise_reopened:args.raise_reopened!==false,raise_level:rl});
    const result={schema:SCHEMA,state_timing:STATE_TIMING,table_size:n,actor_position:actor,family:familyFromHistory(hist,actor),raise_level:rl,live_positions:live,all_in_positions:allin,remaining_to_act_positions:pending,history:hist,limper_positions:sortPositions(limpers,n),caller_positions:sortPositions(callers,n),contribution_bb_by_position:Object.fromEntries(sortPositions(Object.keys(contrib),n).map(p=>[p,contrib[p]])),actor_contribution_bb:roundBB(actorPaid),current_price_bb:roundBB(price),to_call_bb:roundBB(toCall),free_check:toCall<=EPS,pot_before_bb:roundBB(finiteNonnegative(args.pot_before_bb||0,'pot_before_bb')),actor_remaining_bb:roundBB(actorRemaining),effective_stack_bb:roundBB(effectiveStack),legal_actions:legal,min_raise_to_bb:minRaiseTo<=maxRaiseTo+EPS?roundBB(minRaiseTo):null,max_raise_to_bb:roundBB(maxRaiseTo),raise_reopened:args.raise_reopened!==false,amount_semantics:{call_or_bet_cost:'incremental_cost_bb',raise_cost:'incremental_cost_bb',raise_target:'target_total_bb',check_and_fold_cost_bb:0}};
    result.canonical_key=canonicalKey(result);result.context_id=contextId(result);return result;
  };
  const v5RuntimeSignature=context=>JSON.stringify([String(context.actor_position||''),Number(context.table_size)||0,Number(context.raise_level)||0,String(context.family||''),context.live_positions||[],context.all_in_positions||[],normalizeHistory(context.history||[]).map(x=>[x.position,x.action])]);
  const normalizeActionProbabilities=({context,raw_probabilities,hand_class=null,sizing=null,source,backoff_level,confidence,support})=>{
    const legal=(context.legal_actions||[]).map(x=>String(x).toUpperCase());if(!legal.length)throw new Error('context has no legal actions');const weights={};let total=0;for(const action of legal){const v=Number((raw_probabilities||{})[action]||0);if(!Number.isFinite(v)||v<0)throw new Error(`invalid probability weight for ${action}`);weights[action]=v;total+=v;}if(total<=EPS)throw new Error('zero legal probability mass');const probabilities={};for(const action of legal)probabilities[action]=weights[action]/total;return {schema:PROBABILITY_SCHEMA,behavior_mode:'strict_legal_normalized',context_id:String(context.context_id||contextId(context)),hand_class,legal_actions:legal,probabilities,sizing:sizing==null?null:{...sizing},source:String(source),backoff_level:String(backoff_level),confidence:String(confidence),support:Number(support)||0,incumbent_compatibility:{matcher:'v5/v83',runtime_signature_ignores_free_check:true}};
  };
  const incumbentV5Passthrough=({context,raw_probabilities,hand_class=null,sizing=null,source,backoff_level,confidence,support})=>{
    const probabilities={},raw=raw_probabilities||{};let total=0;for(const [action,valueRaw] of Object.entries(raw)){const actionName=String(action).toUpperCase(),value=Number(valueRaw||0);if(!Number.isFinite(value)||value<0)throw new Error(`invalid incumbent probability for ${actionName}`);probabilities[actionName]=value;total+=value;}if(!Object.keys(probabilities).length)throw new Error('incumbent probability response is empty');if(total<=EPS)throw new Error('incumbent probability mass is zero');const legal=(context.legal_actions||[]).map(x=>String(x).toUpperCase()),legalSet=new Set(legal),positiveIllegal=Object.entries(probabilities).filter(([,p])=>p>EPS).map(([a])=>a).filter(a=>legal.length&&!legalSet.has(a)),missing=legal.filter(a=>!Object.prototype.hasOwnProperty.call(probabilities,a));return {schema:PROBABILITY_SCHEMA,behavior_mode:'incumbent_v5_passthrough',context_id:String(context.context_id||contextId(context)),hand_class,legal_actions:legal,model_actions:Object.keys(probabilities),probabilities,probability_sum:total,action_set_compatible:positiveIllegal.length===0,positive_illegal_model_actions:positiveIllegal,missing_legal_model_actions:missing,sizing:sizing==null?null:{...sizing},source:String(source),backoff_level:String(backoff_level),confidence:String(confidence),support:Number(support)||0,incumbent_compatibility:{matcher:'v5/v83',probabilities_preserved_without_renormalization:true,runtime_signature_ignores_free_check:true}};
  };
  return {SCHEMA,PROBABILITY_SCHEMA,STATE_TIMING,normalizePosition:normPos,sortPositions,normalizeHistory,historyToken,deriveRemainingToAct,familyFromHistory,legalActionsForState,canonicalKey,contextId,buildContext,v5RuntimeSignature,normalizeActionProbabilities,incumbentV5Passthrough};
});

/* END src/preflop/contract.js */

/* BEGIN src/preflop/decision.js | blob 1b2a49c7b2305a53468e36acd3eb687a09514654 | sha256 5eff67b68541b66c3cc0c812e685f6a8ff9d725f0a3e570d9af805c46d44541a */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerPreflopDecision=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';

  const SCHEMA='poker-preflop-decision/v1';
  const EV_REFERENCE='decision_point_incremental_bb';
  const ACTIONS=['FOLD','CHECK','LIMP','OVERLIMP','CALL','OPEN','ISO','SQUEEZE','3BET','4BET','SHOVE','CALL_SHOVE'];
  const ZERO_COST_ACTIONS=new Set(['FOLD','CHECK']);
  const CHIP_ACTIONS=new Set(ACTIONS.filter(a=>!ZERO_COST_ACTIONS.has(a)));
  const EPS=1e-9;

  function finite(value,name){
    const n=Number(value);
    if(!Number.isFinite(n))throw new Error(`${name} must be finite`);
    return n;
  }

  function nonNegativeInteger(value,name){
    const n=finite(value,name);
    if(!Number.isInteger(n)||n<0)throw new Error(`${name} must be a non-negative integer`);
    return n;
  }

  function optionalFinite(value,name,{min=null,max=null}={}){
    if(value==null)return null;
    const n=finite(value,name);
    if(min!=null&&n<min-EPS)throw new Error(`${name} must be >= ${min}`);
    if(max!=null&&n>max+EPS)throw new Error(`${name} must be <= ${max}`);
    return n;
  }

  function normalizeUncertainty(input={}){
    const monteCarlo=input.monte_carlo||{};
    const model=input.model||{};
    const lower=optionalFinite(model.lower_bb,'uncertainty.model.lower_bb');
    const upper=optionalFinite(model.upper_bb,'uncertainty.model.upper_bb');
    if(lower!=null&&upper!=null&&lower>upper+EPS)throw new Error('uncertainty.model.lower_bb must be <= upper_bb');
    return {
      monte_carlo:{
        standard_error_bb:optionalFinite(monteCarlo.standard_error_bb,'uncertainty.monte_carlo.standard_error_bb',{min:0}),
        samples:monteCarlo.samples==null?null:nonNegativeInteger(monteCarlo.samples,'uncertainty.monte_carlo.samples'),
        method:String(monteCarlo.method||'').trim()||null
      },
      model:{
        lower_bb:lower,
        upper_bb:upper,
        method:String(model.method||'').trim()||null,
        status:String(model.status||'UNKNOWN').toUpperCase()
      }
    };
  }

  function normalizeSupport(input={}){
    return {
      observations:input.observations==null?null:nonNegativeInteger(input.observations,'support.observations'),
      backoff_level:String(input.backoff_level||'UNKNOWN').toUpperCase(),
      source:String(input.source||'').trim()||null
    };
  }

  function normalizeAlternative(input,{actorContributionBB,legalActions}={}){
    if(!input||typeof input!=='object')throw new Error('alternative must be an object');
    const id=String(input.id||'').trim();
    if(!id)throw new Error('alternative.id is required');
    const action=String(input.action||'').toUpperCase();
    if(!ACTIONS.includes(action))throw new Error(`unsupported preflop action ${action}`);
    if(legalActions&&legalActions.size&&!legalActions.has(action))throw new Error(`alternative ${id} uses illegal action ${action}`);

    const ev_bb=finite(input.ev_bb,`alternative ${id}.ev_bb`);
    const confidence=optionalFinite(input.confidence,`alternative ${id}.confidence`,{min:0,max:1});
    let target_total_bb=input.target_total_bb==null?null:finite(input.target_total_bb,`alternative ${id}.target_total_bb`);
    let incremental_cost_bb=finite(input.incremental_cost_bb,`alternative ${id}.incremental_cost_bb`);
    if(incremental_cost_bb<-EPS)throw new Error(`alternative ${id}.incremental_cost_bb must be >= 0`);

    if(ZERO_COST_ACTIONS.has(action)){
      if(Math.abs(incremental_cost_bb)>EPS)throw new Error(`${action} must have zero incremental cost`);
      if(target_total_bb!=null)throw new Error(`${action} must not advertise a target_total_bb`);
      if(action==='FOLD'&&Math.abs(ev_bb)>EPS)throw new Error('FOLD EV must be 0 under decision_point_incremental_bb reference');
      incremental_cost_bb=0;
      target_total_bb=null;
    }else if(CHIP_ACTIONS.has(action)){
      if(target_total_bb==null||target_total_bb<actorContributionBB-EPS)throw new Error(`${action} requires target_total_bb >= actor contribution`);
      const expected=target_total_bb-actorContributionBB;
      if(Math.abs(expected-incremental_cost_bb)>1e-6)throw new Error(`alternative ${id} incremental cost ${incremental_cost_bb} does not match target_total_bb - actor_contribution_bb (${expected})`);
    }

    return {
      id,action,target_total_bb,incremental_cost_bb,ev_bb,
      support:normalizeSupport(input.support||{}),
      confidence,
      uncertainty:normalizeUncertainty(input.uncertainty||{}),
      sizing_origin:String(input.sizing_origin||'').trim()||null,
      notes:String(input.notes||'')
    };
  }

  function buildDecision(input={}){
    const context_id=String(input.context_id||'').trim();
    if(!context_id)throw new Error('context_id is required');
    const actor_contribution_bb=optionalFinite(input.actor_contribution_bb,'actor_contribution_bb',{min:0});
    if(actor_contribution_bb==null)throw new Error('actor_contribution_bb is required');
    const legal_actions=Array.from(new Set((input.legal_actions||[]).map(a=>String(a).toUpperCase())));
    if(!legal_actions.length)throw new Error('legal_actions must not be empty');
    for(const action of legal_actions)if(!ACTIONS.includes(action))throw new Error(`unsupported legal action ${action}`);
    const legalSet=new Set(legal_actions);
    if(!Array.isArray(input.alternatives)||!input.alternatives.length)throw new Error('at least one evaluated alternative is required');
    const alternatives=input.alternatives.map(row=>normalizeAlternative(row,{actorContributionBB:actor_contribution_bb,legalActions:legalSet}));
    const ids=new Set();
    for(const row of alternatives){if(ids.has(row.id))throw new Error(`duplicate alternative id ${row.id}`);ids.add(row.id);}

    const selected_id=String(input.selected_id||'').trim();
    const selected=alternatives.find(row=>row.id===selected_id);
    if(!selected)throw new Error(`selected_id ${selected_id||'<empty>'} was not evaluated`);
    const bestEV=Math.max(...alternatives.map(row=>row.ev_bb));
    if(selected.ev_bb<bestEV-EPS)throw new Error(`selected alternative ${selected.id} is not maximal EV (${selected.ev_bb} < ${bestEV})`);

    const search=input.search||{};
    const budget=search.budget==null?null:nonNegativeInteger(search.budget,'search.budget');
    const candidate_ids=Array.isArray(search.candidate_ids)?search.candidate_ids.map(String):alternatives.map(row=>row.id);
    const candidateSet=new Set(candidate_ids);
    if(candidateSet.size!==candidate_ids.length)throw new Error('search.candidate_ids contains duplicates');
    for(const id of candidate_ids)if(!ids.has(id))throw new Error(`search references unevaluated alternative ${id}`);
    if(!candidateSet.has(selected.id))throw new Error('selected alternative must belong to search.candidate_ids');

    return {
      schema:SCHEMA,
      status:String(input.status||'EXPERIMENTAL').toUpperCase(),
      context_id,
      population_id:input.population_id==null?null:String(input.population_id),
      ev_reference:EV_REFERENCE,
      actor_contribution_bb,
      legal_actions,
      selected_id:selected.id,
      action:selected.action,
      target_total_bb:selected.target_total_bb,
      bet_to_bb:selected.target_total_bb,
      incremental_cost_bb:selected.incremental_cost_bb,
      ev_bb:selected.ev_bb,
      support:selected.support,
      confidence:selected.confidence,
      uncertainty:selected.uncertainty,
      alternatives,
      search:{
        candidate_ids,
        sizing_grid_source:String(search.sizing_grid_source||'').trim()||null,
        budget,
        seed:search.seed==null?null:String(search.seed),
        notes:String(search.notes||'')
      },
      notes:String(input.notes||'')
    };
  }

  function validateDecision(decision){
    if(!decision||decision.schema!==SCHEMA)throw new Error(`expected ${SCHEMA}`);
    const rebuilt=buildDecision({
      status:decision.status,
      context_id:decision.context_id,
      population_id:decision.population_id,
      actor_contribution_bb:decision.actor_contribution_bb,
      legal_actions:decision.legal_actions,
      selected_id:decision.selected_id,
      alternatives:decision.alternatives,
      search:decision.search,
      notes:decision.notes
    });
    const scalar=['action','target_total_bb','bet_to_bb','incremental_cost_bb','ev_bb','ev_reference'];
    for(const key of scalar){
      const a=decision[key],b=rebuilt[key];
      if(typeof a==='number'||typeof b==='number'){
        if(a==null||b==null||Math.abs(Number(a)-Number(b))>EPS)throw new Error(`decision ${key} does not match selected alternative`);
      }else if(a!==b)throw new Error(`decision ${key} does not match selected alternative`);
    }
    return true;
  }

  return {SCHEMA,EV_REFERENCE,ACTIONS,buildDecision,validateDecision,normalizeAlternative};
});

/* END src/preflop/decision.js */

/* BEGIN src/preflop/search.js | blob 354d3afff68afebce394b8ec7803c4d51ea1ea95 | sha256 94a5e40c5d312523ef7404bb4cdd3e4719030f5a6d14b4eceba0c1944b8eaed8 */
(function(root,factory){
  'use strict';
  if(typeof module==='object'&&module.exports){
    module.exports=factory(require('./decision.js'));
    return;
  }
  if(root)root.PokerPreflopSearch=factory(root.PokerPreflopDecision);
})(typeof globalThis!=='undefined'?globalThis:this,function(Decision){
  'use strict';

  if(!Decision||typeof Decision.buildDecision!=='function')throw new Error('PokerPreflopDecision contract is required');

  const SCHEMA='poker-preflop-search/v1';
  const EPS=1e-9;
  const AGGRESSIVE=new Set(['OPEN','ISO','SQUEEZE','3BET','4BET']);
  const SUPPORTED_STRUCTURAL=new Set(['FOLD','CHECK','LIMP','CALL','RAISE','JAM']);

  class UncoveredPreflopSearchError extends Error{
    constructor(message,details={}){super(message);this.name='UncoveredPreflopSearchError';this.details=details;}
  }

  const finite=(value,name)=>{
    const n=Number(value);if(!Number.isFinite(n))throw new Error(`${name} must be finite`);return n;
  };
  const nonnegative=(value,name)=>{const n=finite(value,name);if(n<-EPS)throw new Error(`${name} must be non-negative`);return Math.max(0,n);};
  const roundBB=value=>Number(Number(value).toFixed(9));
  const fmt=value=>{
    const n=roundBB(value);return Number.isInteger(n)?String(n):String(n).replace(/0+$/,'').replace(/\.$/,'');
  };
  const history=context=>Array.isArray(context?.history)?context.history:[];
  const lastAggression=context=>{
    const xs=history(context);for(let i=xs.length-1;i>=0;i--){const a=String(xs[i]?.action||'').toUpperCase();if(a==='RAISE'||a==='JAM')return {...xs[i],action:a};}return null;
  };

  function semanticRaiseAction(context){
    const raiseLevel=Number(context?.raise_level)||0;
    const family=String(context?.family||'').toUpperCase();
    if(raiseLevel===0)return (context?.limper_positions||[]).length||family==='VS_LIMPERS'?'ISO':'OPEN';
    if(raiseLevel===1)return family==='VS_RFI_CALLERS'||family==='VS_ISO_CALLERS'?'SQUEEZE':'3BET';
    if(raiseLevel===2)return '4BET';
    return null;
  }

  function semanticAction(structural,context){
    const action=String(structural||'').toUpperCase();
    if(!SUPPORTED_STRUCTURAL.has(action))throw new UncoveredPreflopSearchError(`unsupported structural preflop action ${action||'<empty>'}`,{action});
    if(action==='FOLD'||action==='CHECK')return action;
    if(action==='LIMP')return (context?.limper_positions||[]).length?'OVERLIMP':'LIMP';
    if(action==='CALL')return lastAggression(context)?.action==='JAM'?'CALL_SHOVE':'CALL';
    if(action==='JAM')return 'SHOVE';
    const mapped=semanticRaiseAction(context);
    if(!mapped)throw new UncoveredPreflopSearchError('non-all-in raise beyond the supported 4-bet semantic vocabulary',{raise_level:Number(context?.raise_level)||0,family:context?.family||null});
    return mapped;
  }

  function semanticLegalActions(context){
    if(!context||context.schema!=='poker-preflop-context/v1')throw new Error('expected poker-preflop-context/v1');
    const out=[];
    for(const structural of context.legal_actions||[]){
      const action=semanticAction(structural,context);
      if(!out.includes(action))out.push(action);
    }
    if(!out.length)throw new UncoveredPreflopSearchError('preflop context has no supported legal action',{context_id:context.context_id||null});
    return out;
  }

  function normalizeSizingGrid(context,values,{source='explicit_observed_grid'}={}){
    const min=context.min_raise_to_bb==null?null:finite(context.min_raise_to_bb,'min_raise_to_bb');
    const max=finite(context.max_raise_to_bb,'max_raise_to_bb');
    const current=finite(context.current_price_bb,'current_price_bb');
    const unique=[];
    for(const raw of values||[]){
      const target=roundBB(finite(raw,'sizing_grid target'));
      if(target<=current+EPS)continue;
      if(min!=null&&target<min-EPS)continue;
      if(target>=max-EPS)continue;
      if(!unique.some(x=>Math.abs(x-target)<=EPS))unique.push(target);
    }
    unique.sort((a,b)=>a-b);
    return {source:String(source||'explicit_observed_grid'),targets_bb:unique};
  }

  function buildCandidates(context,{sizing_grid_bb=[],sizing_grid_source='explicit_observed_grid'}={}){
    const actorPaid=nonnegative(context.actor_contribution_bb,'actor_contribution_bb');
    const current=nonnegative(context.current_price_bb,'current_price_bb');
    const max=nonnegative(context.max_raise_to_bb,'max_raise_to_bb');
    const grid=normalizeSizingGrid(context,sizing_grid_bb,{source:sizing_grid_source});
    const candidates=[];
    const push=(action,target,origin)=>{
      const targetTotal=target==null?null:roundBB(target);
      const cost=targetTotal==null?0:roundBB(Math.max(0,targetTotal-actorPaid));
      const id=targetTotal==null?action:`${action}@${fmt(targetTotal)}`;
      if(!candidates.some(row=>row.id===id))candidates.push({id,action,target_total_bb:targetTotal,incremental_cost_bb:cost,sizing_origin:origin});
    };

    for(const structuralRaw of context.legal_actions||[]){
      const structural=String(structuralRaw).toUpperCase(),action=semanticAction(structural,context);
      if(structural==='FOLD'||structural==='CHECK')push(action,null,'no_chips');
      else if(structural==='LIMP'||structural==='CALL')push(action,current,structural==='CALL'?'price_to_call':'blind_or_limp_price');
      else if(structural==='JAM')push('SHOVE',max,'stack_cap');
      else if(structural==='RAISE'){
        if(!grid.targets_bb.length){
          throw new UncoveredPreflopSearchError('RAISE is legal but no explicit in-bounds sizing candidate was supplied',{
            context_id:context.context_id||null,
            semantic_action:action,
            min_raise_to_bb:context.min_raise_to_bb,
            max_raise_to_bb:max,
            sizing_grid_source:grid.source
          });
        }
        for(const target of grid.targets_bb)push(action,target,grid.source);
      }
    }
    if(!candidates.length)throw new UncoveredPreflopSearchError('no evaluable preflop candidate',{context_id:context.context_id||null});
    return {schema:'poker-preflop-search-candidates/v1',context_id:context.context_id||null,sizing_grid:grid,candidates};
  }

  function normalizeEvaluation(candidate,result){
    if(!result||typeof result!=='object')throw new Error(`evaluator returned no result for ${candidate.id}`);
    const ev=finite(result.ev_bb,`${candidate.id}.ev_bb`);
    const confidence=result.confidence==null?null:finite(result.confidence,`${candidate.id}.confidence`);
    if(confidence!=null&&(confidence<-EPS||confidence>1+EPS))throw new Error(`${candidate.id}.confidence must be 0..1`);
    return {
      ...candidate,
      ev_bb:ev,
      support:result.support||{observations:null,backoff_level:'UNKNOWN',source:null},
      confidence,
      uncertainty:result.uncertainty||{monte_carlo:{standard_error_bb:null,samples:null,method:null},model:{lower_bb:null,upper_bb:null,method:null,status:'UNKNOWN'}},
      notes:String(result.notes||'')
    };
  }

  function chooseBest(alternatives){
    if(!alternatives.length)throw new Error('cannot select from empty alternatives');
    return [...alternatives].sort((a,b)=>{
      const ev=b.ev_bb-a.ev_bb;if(Math.abs(ev)>EPS)return ev;
      const cost=a.incremental_cost_bb-b.incremental_cost_bb;if(Math.abs(cost)>EPS)return cost;
      return a.id.localeCompare(b.id);
    })[0];
  }

  async function searchPreflopDecision({
    context,
    population_id=null,
    hand_class=null,
    sizing_grid_bb=[],
    sizing_grid_source='explicit_observed_grid',
    evaluate_alternative,
    budget,
    seed,
    status='EXPERIMENTAL',
    notes=''
  }={}){
    if(typeof evaluate_alternative!=='function')throw new TypeError('evaluate_alternative callback is required');
    const totalBudget=Number(budget);
    if(!Number.isInteger(totalBudget)||totalBudget<0)throw new Error('budget must be a non-negative integer');
    const built=buildCandidates(context,{sizing_grid_bb,sizing_grid_source});
    const evaluated=[];
    const spendable=built.candidates.filter(row=>row.action!=='FOLD');
    const base=spendable.length?Math.floor(totalBudget/spendable.length):0;
    let remainder=spendable.length?totalBudget-base*spendable.length:0;
    let evalIndex=0;

    for(const candidate of built.candidates){
      if(candidate.action==='FOLD'){
        evaluated.push({
          ...candidate,ev_bb:0,
          support:{observations:null,backoff_level:'DETERMINISTIC',source:'decision_point_fold_reference'},
          confidence:1,
          uncertainty:{monte_carlo:{standard_error_bb:0,samples:0,method:'deterministic'},model:{lower_bb:0,upper_bb:0,method:'deterministic',status:'KNOWN'}},
          notes:'Fold is the zero-EV reference at the current decision point.'
        });
        continue;
      }
      const candidateBudget=base+(remainder>0?1:0);if(remainder>0)remainder--;
      const evaluation=await evaluate_alternative(Object.freeze({
        schema:SCHEMA,
        context,
        population_id,
        hand_class,
        candidate:Object.freeze({...candidate}),
        candidate_index:evalIndex++,
        candidate_budget:candidateBudget,
        total_budget:totalBudget,
        seed:seed==null?null:String(seed),
        remaining_to_act_positions:[...(context.remaining_to_act_positions||[])]
      }));
      evaluated.push(normalizeEvaluation(candidate,evaluation));
    }

    const selected=chooseBest(evaluated);
    return Decision.buildDecision({
      status,
      context_id:String(context.context_id||''),
      population_id,
      actor_contribution_bb:context.actor_contribution_bb,
      legal_actions:semanticLegalActions(context),
      selected_id:selected.id,
      alternatives:evaluated,
      search:{
        candidate_ids:evaluated.map(row=>row.id),
        sizing_grid_source:built.sizing_grid.source,
        budget:totalBudget,
        seed:seed==null?null:String(seed),
        notes:`${built.sizing_grid.targets_bb.length} explicit raise sizing(s); ${notes}`.trim()
      },
      notes
    });
  }

  return {SCHEMA,UncoveredPreflopSearchError,semanticRaiseAction,semanticAction,semanticLegalActions,normalizeSizingGrid,buildCandidates,chooseBest,searchPreflopDecision};
});

/* END src/preflop/search.js */

/* BEGIN src/preflop/guidance.js | blob 8541cf75b27afbeba2580864ef744da3a9b40457 | sha256 af0ee5aaedeabc7edd80efbe0eb2c59b1104e9d39922f6780864a89c5311f79e */
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
      context_id:decision.context_id,
      population_id:decision.population_id,
      ev_reference:decision.ev_reference,
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
      advisory_label:promoted?'PROMOTED_GUIDANCE':experimental?'EXPERIMENTAL_NOT_DEFAULT':'NO_VERDICT',
      evidence_decision:evidence,
      cache_key:cacheKey({strategy,snapshot,decision}),
      source_decision_schema:decision.schema,
      future_cards_consumed:false
    };
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
    if(!guidance||guidance.schema!==SCHEMA)throw new Error(`expected ${SCHEMA}`);
    const allowed=guidance.recommendation_state==='PROMOTED'||(allow_experimental&&guidance.recommendation_state==='EXPERIMENTAL');
    if(!allowed||!guidance.evidence_decision)return noVerdictPayload(guidance);
    const d=guidance.evidence_decision;
    return {
      schema:SCHEMA,
      recommendation_state:guidance.recommendation_state,
      advisory_label:guidance.advisory_label,
      default_advice:guidance.default_advice,
      strategy:guidance.strategy,
      context_id:d.context_id,
      population_id:d.population_id,
      hero_hand_class:guidance.public_snapshot.hero_hand_class,
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

  return {SCHEMA,STRATEGY_STATES,normalizeStrategy,validatePublicSnapshot,buildGuidance,surfacePayload,surfaceBundle,cacheKey};
});

/* END src/preflop/guidance.js */

/* BEGIN src/training/preflop-decision-adapter.js | blob d5cebf63370ce3d49ccedbcb43bed44f1a55b926 | sha256 186c87788458a4711798dfca8746620c002253999fea24aa234ef44b4636768a */
(function(root,factory){
  const Decision=(typeof module==='object'&&module.exports)?require('../preflop/decision.js'):(root&&root.PokerPreflopDecision);
  const Guidance=(typeof module==='object'&&module.exports)?require('../preflop/guidance.js'):(root&&root.PokerPreflopGuidance);
  const Leak=(typeof module==='object'&&module.exports)?require('../analytics/leak-analyzer.js'):(root&&root.PokerLeakAnalyzer);
  const api=factory(Decision,Guidance,Leak);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerPreflopDecisionAdapter=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(Decision,Guidance,Leak){
  'use strict';

  const SCHEMA='poker-preflop-decision/v1';
  const ADAPTER_PROFILE='CANONICAL_RUNTIME_DECISION_V1';
  const SNAPSHOT_SCHEMA='nlhe-game-state/v1';
  const GUIDANCE_SCHEMA='poker-preflop-guidance/v1';
  const COVERAGE_STATES=['COVERED','LOW_SUPPORT','UNSUPPORTED','NON_COMPARABLE','ANALYSIS_MISSING','UNCOVERED'];
  const FAIL_CLOSED_STATES=[
    'NO_ADMISSIBLE_STRATEGY','EXACT_CONTEXT_ABSENT','EXACT_CONTEXT_MISMATCH','POPULATION_MISMATCH',
    'STRATEGY_MISMATCH','ARTIFACT_IDENTITY_MISMATCH','LOW_SUPPORT','UNCOVERED',
    'NON_COMPARABLE_ALTERNATIVES','INVALID_GUIDANCE'
  ];
  const POSITION_NAMES=new Set(['LJ','HJ','CO','BTN','SB','BB','SB_BTN']);
  const LOW_TIERS=new Set(['LOW','SPARSE','UNKNOWN']);
  const EPS=1e-9;
  const SENSITIVE_KEYS=[
    'hole_cards','opponent_hole_cards','opponents_hole_cards','villain_hole_cards','private_cards',
    'future_cards','future_board','future_public_cards','runout','showdown_cards'
  ];

  function text(v){return v==null?'':String(v).trim();}
  function upper(v){return text(v).toUpperCase();}
  function finiteOrNull(v){if(v==null||v==='')return null;const n=Number(v);return Number.isFinite(n)?n:null;}
  function round(v){return Math.round((Number(v)+Number.EPSILON)*1e9)/1e9;}
  function stableStringify(v){
    if(v===null||typeof v!=='object')return JSON.stringify(v);
    if(Array.isArray(v))return '['+v.map(stableStringify).join(',')+']';
    return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+stableStringify(v[k])).join(',')+'}';
  }
  function hash(s){let h=2166136261>>>0;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)>>>0;}return h.toString(36);}
  function clone(v){return v==null?v:JSON.parse(JSON.stringify(v));}
  function unique(values){return Array.from(new Set(values.filter(Boolean))).sort();}
  function required(v,name){const s=text(v);if(!s)throw new Error(name+' is required');return s;}

  function normalizeIdentity(input={}){
    return {
      population_id:required(input.population_id,'identity.population_id'),
      pack_id:text(input.pack_id)||null,
      pack_version:text(input.pack_version)||null,
      strategy_id:required(input.strategy_id,'identity.strategy_id'),
      strategy_version:required(input.strategy_version,'identity.strategy_version'),
      strategy_sha256:text(input.strategy_sha256||input.artifact_sha256).toLowerCase()||null,
      decision_source_sha256:text(input.decision_source_sha256).toLowerCase()||null,
      ev_reference:text(input.ev_reference)||(Decision&&Decision.EV_REFERENCE)||'decision_point_incremental_bb'
    };
  }

  function normalizeSnapshot(publicState){
    const wrapper=publicState&&publicState.snapshot?publicState:{snapshot:publicState};
    const snapshot=wrapper.snapshot;
    if(!snapshot||typeof snapshot!=='object'||Array.isArray(snapshot))throw new Error('public_state snapshot is required');
    if(snapshot.schema!==SNAPSHOT_SCHEMA)throw new Error('expected '+SNAPSHOT_SCHEMA);
    if(upper(snapshot.street)!=='PREFLOP')throw new Error('preflop decision adapter requires PREFLOP public state');
    const seats=Array.isArray(snapshot.seats)?snapshot.seats.map(String):[];
    if(!seats.length)throw new Error('public_state.seats must not be empty');
    const pending=Array.isArray(snapshot.pending)?snapshot.pending.map(String):[];
    const actor=text(wrapper.legal_view&&wrapper.legal_view.actor)||pending[0]||'';
    if(!actor)throw new Error('public_state has no pending actor');
    if(!seats.includes(actor))throw new Error('public_state actor must be seated');

    const numericMap=(obj)=>Object.fromEntries(Object.entries(obj||{}).sort((a,b)=>a[0].localeCompare(b[0])).map(([k,v])=>[String(k),round(Number(v)||0)]));
    const boolMap=(obj)=>Object.fromEntries(Object.entries(obj||{}).sort((a,b)=>a[0].localeCompare(b[0])).map(([k,v])=>[String(k),Boolean(v)]));
    const total=numericMap(snapshot.total_committed_bb),street=numericMap(snapshot.street_committed_bb),remaining=numericMap(snapshot.stacks_bb);
    const folded=boolMap(snapshot.folded),allIn=boolMap(snapshot.all_in),refunds=numericMap(snapshot.refunds_bb);
    const preflopLog=(Array.isArray(snapshot.action_log)?snapshot.action_log:[])
      .filter(x=>upper(x&&x.street)==='PREFLOP')
      .map(x=>({player:text(x.player),action:upper(x.action),target_total_bb:finiteOrNull(x.target_total_bb),incremental_cost_bb:finiteOrNull(x.incremental_cost_bb)}));
    const pot=round(Object.values(total).reduce((s,x)=>s+Number(x||0),0));
    const actorPaid=Number(street[actor]||0),actorRemaining=Number(remaining[actor]||0);
    const currentPrice=finiteOrNull(snapshot.current_bet_bb)??Math.max(0,...Object.values(street).map(Number));
    const toCall=round(Math.max(0,currentPrice-actorPaid));
    const liveOpponents=seats.filter(p=>p!==actor&&!folded[p]);
    const actorTotal=actorRemaining+Number(total[actor]||0);
    const oppTotals=liveOpponents.map(p=>Number(remaining[p]||0)+Number(total[p]||0));
    const effective=round(Math.min(actorTotal,oppTotals.length?Math.max(...oppTotals):actorTotal));
    const legalView=wrapper.legal_view&&typeof wrapper.legal_view==='object'?wrapper.legal_view:{};
    const legalActions=Array.isArray(legalView.legal_actions)?legalView.legal_actions.map(upper):deriveCoreLegalActions({toCall,actorRemaining,currentPrice,actorPaid});
    const canonical={
      schema:SNAPSHOT_SCHEMA,
      seats:[...seats],
      button:text(snapshot.button)||null,
      small_blind_player:text(snapshot.small_blind_player)||null,
      big_blind_player:text(snapshot.big_blind_player)||null,
      small_blind_bb:finiteOrNull(snapshot.small_blind_bb),
      big_blind_bb:finiteOrNull(snapshot.big_blind_bb),
      stacks_bb:remaining,
      total_committed_bb:total,
      street_committed_bb:street,
      folded,all_in:allIn,
      street:'PREFLOP',
      current_bet_bb:round(currentPrice),
      last_full_raise_bb:finiteOrNull(snapshot.last_full_raise_bb),
      full_bet_established:Boolean(snapshot.full_bet_established),
      acted_since_full_raise:Array.isArray(snapshot.acted_since_full_raise)?snapshot.acted_since_full_raise.map(String).sort():[],
      pending,
      refunds_bb:refunds,
      preflop_action_log:preflopLog,
      actor,
      pot_before_action_bb:pot,
      actor_contribution_bb:round(actorPaid),
      actor_remaining_bb:round(actorRemaining),
      to_call_bb:toCall,
      effective_stack_bb:effective,
      legal_actions:legalActions,
      min_raise_to_bb:finiteOrNull(legalView.min_raise_to_bb),
      max_raise_to_bb:finiteOrNull(legalView.max_raise_to_bb),
      raise_reopened:legalView.raise_reopened==null?null:Boolean(legalView.raise_reopened)
    };
    return {canonical,wrapper,snapshot};
  }
  function deriveCoreLegalActions({toCall,actorRemaining,currentPrice,actorPaid}){
    const out=toCall>EPS?['FOLD','CALL']:['CHECK'];
    if(actorRemaining>toCall+EPS&&actorPaid+actorRemaining>currentPrice+EPS)out.push('RAISE');
    return out;
  }
  function sensitiveFieldsPresent(input,publicState){
    const found=[];
    const inspect=(obj,prefix)=>{
      if(!obj||typeof obj!=='object')return;
      for(const key of SENSITIVE_KEYS)if(Object.prototype.hasOwnProperty.call(obj,key)&&obj[key]!=null)found.push(prefix+key);
    };
    inspect(input,'input.');
    inspect(publicState,'public_state.');
    if(publicState&&publicState.snapshot)inspect(publicState.snapshot,'public_state.snapshot.');
    return unique(found);
  }

  function normalizeContext(input,guidance,publicNorm){
    const pc=input.preflop_context&&typeof input.preflop_context==='object'?input.preflop_context:{};
    const candidates=[
      text(input.context_id),text(pc.context_id),
      text(guidance&&guidance.public_snapshot&&guidance.public_snapshot.context_id),
      text(guidance&&guidance.evidence_decision&&guidance.evidence_decision.context_id)
    ].filter(Boolean);
    const uniqueIds=unique(candidates);
    const context_id=uniqueIds[0]||null;
    const mismatch=uniqueIds.length>1;
    const actor=publicNorm.canonical.actor;
    const heroPosition=upper(input.hero_position||pc.actor_position||pc.hero_position||(POSITION_NAMES.has(upper(actor))?actor:null))||'UNKNOWN';
    const family=upper(pc.family||input.facing_context)||'UNKNOWN';
    const facingAction=upper(input.facing_action||pc.facing_action)||deriveFacingAction(publicNorm.canonical);
    return {context_id,mismatch,hero_position:heroPosition,facing_context:family,facing_action:facingAction};
  }
  function deriveFacingAction(state){
    if(state.to_call_bb<=EPS)return state.preflop_action_log.length?'CHECK_OPTION':'UNOPENED';
    const rows=state.preflop_action_log.filter(x=>x.player!==state.actor);
    const last=rows.length?rows[rows.length-1]:null;
    if(!last)return 'PRICE';
    if(last.action==='RAISE')return 'RAISE';
    if(last.action==='CALL')return state.current_bet_bb<=Number(state.big_blind_bb||1)+EPS?'LIMP_OR_CALL':'CALL';
    return last.action||'PRICE';
  }

  function normalizeCoverage(input={}){
    const state=upper(input.state||input.coverage_state)||'ANALYSIS_MISSING';
    const tier=upper(input.support_tier||input.tier)||'UNKNOWN';
    const reasons=Array.isArray(input.reasons)?input.reasons.map(x=>text(x)).filter(Boolean):[];
    return {
      state:COVERAGE_STATES.includes(state)?state:'ANALYSIS_MISSING',
      support_tier:tier,
      supported_count:Number.isInteger(Number(input.supported_count))?Number(input.supported_count):null,
      decision_count:Number.isInteger(Number(input.decision_count))?Number(input.decision_count):null,
      coverage_ratio:finiteOrNull(input.coverage_ratio),
      reasons
    };
  }
  function observedTier(support){
    const n=support&&Number.isInteger(Number(support.observations))?Number(support.observations):null;
    if(n==null)return 'UNKNOWN';
    if(n>=1000)return 'VERY_HIGH';
    if(n>=100)return 'HIGH';
    if(n>=20)return 'MEDIUM';
    if(n>=1)return 'LOW';
    return 'SPARSE';
  }
  function tierFromSupport(support,tier){
    const declared=upper(tier)||'UNKNOWN',observed=observedTier(support);
    const rank={UNKNOWN:0,SPARSE:1,LOW:2,MEDIUM:3,HIGH:4,VERY_HIGH:5};
    if(declared==='UNKNOWN'||observed==='UNKNOWN')return 'UNKNOWN';
    return (rank[declared]??0)<=(rank[observed]??0)?declared:observed;
  }

  function validateGuidanceEvidence(evidence){
    if(!evidence||typeof evidence!=='object')throw new Error('guidance evidence_decision is required');
    if(evidence.schema!==SCHEMA)throw new Error('guidance evidence_decision schema mismatch');
    const alternatives=Array.isArray(evidence.alternatives)?evidence.alternatives:[];
    if(!alternatives.length)throw new Error('guidance evidence_decision alternatives are required');
    const selected=alternatives.find(x=>String(x.id)===String(evidence.selected_id));
    if(!selected)throw new Error('guidance selected_id was not evaluated');
    const scalar=[
      ['action',upper],['target_total_bb',finiteOrNull],['incremental_cost_bb',finiteOrNull],['ev_bb',finiteOrNull]
    ];
    for(const [key,norm] of scalar){
      const a=norm(evidence[key]),b=norm(selected[key]);
      if(typeof a==='number'||typeof b==='number'){
        if(a==null||b==null||Math.abs(a-b)>1e-6)throw new Error('guidance '+key+' does not match selected alternative');
      }else if(a!==b)throw new Error('guidance '+key+' does not match selected alternative');
    }
    const evs=alternatives.map(x=>finiteOrNull(x.ev_bb));
    if(evs.some(x=>x==null))throw new Error('guidance alternative EV is missing');
    if(finiteOrNull(selected.ev_bb)<Math.max(...evs)-EPS)throw new Error('guidance selected alternative is not maximal EV');
    if(text(evidence.ev_reference)!==(Decision&&Decision.EV_REFERENCE||'decision_point_incremental_bb'))throw new Error('guidance EV reference mismatch');
    return true;
  }

  function validateGuidanceForAdapter(guidance,identity,context,coverage,altComparability){
    const reasons=[];
    if(!guidance){
      reasons.push('NO_ADMISSIBLE_STRATEGY');
      if(!context.context_id)reasons.push('EXACT_CONTEXT_ABSENT');
      const status=!context.context_id?'EXACT_CONTEXT_ABSENT':'NO_ADMISSIBLE_STRATEGY';
      return {admissible:false,reasons:unique(reasons),surface:null,tier:coverage.support_tier||'UNKNOWN',status};
    }
    if(guidance.schema!==GUIDANCE_SCHEMA){
      reasons.push('INVALID_GUIDANCE');
      return {admissible:false,reasons,surface:null,status:'INVALID_GUIDANCE'};
    }
    const strategy=guidance.strategy||{};
    if(guidance.recommendation_state!=='PROMOTED'||strategy.state!=='PROMOTED'||guidance.default_advice!==true){
      reasons.push('NO_ADMISSIBLE_STRATEGY');
    }
    if(guidance.future_cards_consumed!==false)reasons.push('INVALID_GUIDANCE');
    if(text(strategy.population_id)&&text(strategy.population_id)!==identity.population_id)reasons.push('POPULATION_MISMATCH');
    if(text(guidance.public_snapshot&&guidance.public_snapshot.population_id)&&text(guidance.public_snapshot.population_id)!==identity.population_id)reasons.push('POPULATION_MISMATCH');
    if(text(strategy.strategy_id)&&text(strategy.strategy_id)!==identity.strategy_id)reasons.push('STRATEGY_MISMATCH');
    if(identity.strategy_sha256&&text(strategy.strategy_sha256).toLowerCase()!==identity.strategy_sha256)reasons.push('ARTIFACT_IDENTITY_MISMATCH');
    if(identity.decision_source_sha256&&text(strategy.decision_source_sha256).toLowerCase()!==identity.decision_source_sha256)reasons.push('ARTIFACT_IDENTITY_MISMATCH');
    if(!context.context_id)reasons.push('EXACT_CONTEXT_ABSENT');
    if(context.mismatch)reasons.push('EXACT_CONTEXT_MISMATCH');

    if(coverage.state!=='COVERED'){
      if(coverage.state==='LOW_SUPPORT')reasons.push('LOW_SUPPORT');
      else if(coverage.state==='UNSUPPORTED'||coverage.state==='UNCOVERED'||coverage.state==='ANALYSIS_MISSING')reasons.push('UNCOVERED');
      else if(coverage.state==='NON_COMPARABLE')reasons.push('NON_COMPARABLE_ALTERNATIVES');
    }

    let surface=null;
    try{
      validateGuidanceEvidence(guidance.evidence_decision);
      surface=Guidance.surfacePayload(guidance);
    }catch(_){reasons.push('INVALID_GUIDANCE');}
    if(surface&&surface.action==null)reasons.push('NO_ADMISSIBLE_STRATEGY');
    if(surface&&text(surface.ev_reference)&&text(surface.ev_reference)!==identity.ev_reference)reasons.push('ARTIFACT_IDENTITY_MISMATCH');
    const tier=tierFromSupport(surface&&surface.support,coverage.support_tier);
    if(LOW_TIERS.has(tier))reasons.push('LOW_SUPPORT');

    if(surface&&Array.isArray(surface.alternatives)){
      for(const alt of surface.alternatives){
        const meta=altComparability&&altComparability[alt.id];
        if(meta&&meta.comparable===false){reasons.push('NON_COMPARABLE_ALTERNATIVES');break;}
      }
    }
    const uniqueReasons=unique(reasons);
    const priority=[
      'INVALID_GUIDANCE','POPULATION_MISMATCH','STRATEGY_MISMATCH','ARTIFACT_IDENTITY_MISMATCH',
      'EXACT_CONTEXT_ABSENT','EXACT_CONTEXT_MISMATCH','LOW_SUPPORT','UNCOVERED',
      'NON_COMPARABLE_ALTERNATIVES','NO_ADMISSIBLE_STRATEGY'
    ];
    const status=uniqueReasons.length?(priority.find(x=>uniqueReasons.includes(x))||uniqueReasons[0]):'ADMISSIBLE';
    return {admissible:uniqueReasons.length===0,reasons:uniqueReasons,surface,tier,status};
  }

  function targetSizing(target){return target==null?null:{target_total_bb:round(target),bet_to_bb:round(target)};}
  function normalizePlayed(input){
    if(input==null)return {action:null,target_total_bb:null,alternative_id:null,ev_bb:null};
    if(typeof input==='string')return {action:upper(input),target_total_bb:null,alternative_id:null,ev_bb:null};
    return {
      action:upper(input.action)||null,
      target_total_bb:finiteOrNull(input.target_total_bb??input.bet_to_bb),
      alternative_id:text(input.alternative_id||input.id)||null,
      ev_bb:finiteOrNull(input.ev_bb)
    };
  }
  function sameSizing(a,b){
    if(a==null&&b==null)return true;
    if(a==null||b==null)return false;
    return Math.abs(Number(a)-Number(b))<=1e-6;
  }
  function alternativeRows(surface,altComparability){
    if(!surface||!Array.isArray(surface.alternatives))return [];
    return surface.alternatives.map(alt=>{
      const meta=altComparability&&altComparability[alt.id]||{};
      return {
        id:String(alt.id),
        action:upper(alt.action),
        target_sizing:targetSizing(alt.target_total_bb),
        incremental_cost_bb:finiteOrNull(alt.incremental_cost_bb),
        ev_bb:finiteOrNull(alt.ev_bb),
        uncertainty:clone(alt.uncertainty)||null,
        support:clone(alt.support)||null,
        confidence:finiteOrNull(alt.confidence),
        comparable:meta.comparable!==false,
        comparability_reason:meta.comparable===false?(text(meta.reason)||'NON_COMPARABLE'):null
      };
    });
  }
  function findPlayedAlternative(played,alternatives){
    if(!played.action)return null;
    if(played.alternative_id){
      const x=alternatives.find(a=>a.id===played.alternative_id);
      if(x&&x.action===played.action&&sameSizing(x.target_sizing&&x.target_sizing.target_total_bb,played.target_total_bb))return x;
    }
    const exact=alternatives.filter(a=>a.action===played.action&&sameSizing(a.target_sizing&&a.target_sizing.target_total_bb,played.target_total_bb));
    if(exact.length===1)return exact[0];
    if(played.target_total_bb==null){
      const sameAction=alternatives.filter(a=>a.action===played.action);
      if(sameAction.length===1)return sameAction[0];
    }
    return null;
  }

  function buildDecision(input={}){
    if(!Decision||!Guidance)throw new Error('preflop decision and guidance contracts are required');
    const identity=normalizeIdentity(input.identity||{});
    const publicNorm=normalizeSnapshot(input.public_state);
    const guidance=input.guidance||null;
    const context=normalizeContext(input,guidance,publicNorm);
    const coverage=normalizeCoverage(input.coverage||{});
    const checked=validateGuidanceForAdapter(guidance,identity,context,coverage,input.alternative_comparability||{});
    const sensitive=sensitiveFieldsPresent(input,input.public_state);
    const fingerprintBasis={
      public_state:publicNorm.canonical,
      context_id:context.context_id,
      hero_position:context.hero_position,
      facing_context:context.facing_context,
      facing_action:context.facing_action
    };
    const publicFingerprint='preflop-public:'+hash(stableStringify(fingerprintBasis));
    const played=normalizePlayed(input.played_action);
    const evidenceAlternatives=checked.admissible?alternativeRows(checked.surface,input.alternative_comparability||{}):[];
    const playedAlt=findPlayedAlternative(played,evidenceAlternatives);
    const playedEV=played.ev_bb!=null?played.ev_bb:(playedAlt&&playedAlt.comparable?playedAlt.ev_bb:null);
    const recommendedEV=checked.admissible?finiteOrNull(checked.surface.ev_bb):null;
    const comparable=Boolean(checked.admissible&&played.action&&playedAlt&&playedAlt.comparable&&playedEV!=null&&recommendedEV!=null);
    const delta=comparable?round(recommendedEV-playedEV):null;
    const supportTier=checked.tier||tierFromSupport(checked.surface&&checked.surface.support,coverage.support_tier);
    const recommendationReasons=[...checked.reasons];
    if(checked.admissible&&played.action&&!playedAlt)recommendationReasons.push('PLAYED_ALTERNATIVE_NOT_EVALUATED');
    const handId=text(input.hand_id)||null;
    const decisionId=text(input.decision_id)||('preflop-decision:'+hash(stableStringify({hand_id:handId,actor:publicNorm.canonical.actor,context_id:context.context_id,fingerprint:publicFingerprint})));
    const recommendedTarget=checked.admissible?finiteOrNull(checked.surface.target_total_bb):null;
    const selected=checked.admissible?evidenceAlternatives.find(x=>x.id===String(checked.surface.selected_id))||null:null;

    return {
      schema:SCHEMA,
      contract_profile:ADAPTER_PROFILE,
      decision_id:decisionId,
      hand_id:handId,
      timestamp:text(input.timestamp)||null,
      street:'PREFLOP',
      public_state_fingerprint:publicFingerprint,
      public_state:{
        actor:publicNorm.canonical.actor,
        legal_actions:[...publicNorm.canonical.legal_actions],
        to_call_bb:publicNorm.canonical.to_call_bb,
        current_bet_bb:publicNorm.canonical.current_bet_bb,
        actor_contribution_bb:publicNorm.canonical.actor_contribution_bb,
        actor_remaining_bb:publicNorm.canonical.actor_remaining_bb
      },
      context_id:context.context_id,
      hero_position:context.hero_position,
      effective_stack_bb:publicNorm.canonical.effective_stack_bb,
      pot_before_action_bb:publicNorm.canonical.pot_before_action_bb,
      facing_action:context.facing_action,
      facing_context:context.facing_context,
      played_action:played.action,
      played_target_sizing:targetSizing(played.target_total_bb),
      recommended_action:checked.admissible?upper(checked.surface.action):null,
      recommended_target_sizing:targetSizing(recommendedTarget),
      incremental_cost_bb:checked.admissible?finiteOrNull(checked.surface.incremental_cost_bb):null,
      recommended_ev_bb:recommendedEV,
      played_ev_bb:playedEV,
      delta_ev_bb:delta,
      ev_comparable:comparable,
      alternatives:evidenceAlternatives,
      coverage_state:coverage.state,
      support_tier:supportTier,
      support:checked.admissible?clone(checked.surface.support):null,
      recommendation_admissibility:{
        admissible:checked.admissible,
        status:checked.status,
        default_advice:checked.admissible,
        reason_codes:unique(recommendationReasons),
        source_guidance_schema:guidance&&guidance.schema||null,
        source_recommendation_state:guidance&&guidance.recommendation_state||null,
        selected_alternative_id:selected&&selected.id||null
      },
      reason_codes:unique(recommendationReasons),
      identity:{
        population_id:identity.population_id,
        pack_id:identity.pack_id,
        pack_version:identity.pack_version,
        strategy_id:identity.strategy_id,
        strategy_version:identity.strategy_version,
        strategy_sha256:identity.strategy_sha256,
        decision_source_sha256:identity.decision_source_sha256,
        ev_reference:identity.ev_reference
      },
      information_boundary:{
        public_only_fingerprint:true,
        future_cards_consumed:false,
        opponent_hole_cards_consumed:false,
        ignored_sensitive_fields:sensitive,
        fingerprint_excludes_board_and_private_cards:true
      }
    };
  }

  function surfaceBundle(decision){
    validateRuntimeDecision(decision);
    return {feed:decision,detail:decision,replayer:decision,trainer:decision,review:decision};
  }
  function validateRuntimeDecision(d){
    if(!d||d.schema!==SCHEMA||d.contract_profile!==ADAPTER_PROFILE)throw new Error('expected canonical runtime '+SCHEMA);
    if(d.street!=='PREFLOP')throw new Error('runtime decision street must be PREFLOP');
    if(d.recommendation_admissibility.admissible){
      if(!d.recommended_action||d.recommended_ev_bb==null)throw new Error('admissible decision requires recommendation and EV');
      if(d.coverage_state!=='COVERED')throw new Error('admissible decision must be COVERED');
    }else{
      if(d.recommended_action!=null||d.recommended_ev_bb!=null||d.recommended_target_sizing!=null||d.incremental_cost_bb!=null||d.alternatives.length)throw new Error('inadmissible decision must not expose recommendation evidence');
    }
    if(d.delta_ev_bb!=null&&!d.ev_comparable)throw new Error('delta_ev_bb requires comparable EVs');
    return true;
  }

  function toLeakDecisionEvent(decision,options={}){
    validateRuntimeDecision(decision);
    if(!Leak||typeof Leak.buildDecisionEvent!=='function')throw new Error('PokerLeakAnalyzer is required');
    const handId=text(decision.hand_id);if(!handId)throw new Error('hand_id is required for leak decision event');
    const timestamp=text(options.timestamp||decision.timestamp);if(!timestamp)throw new Error('timestamp is required for leak decision event');
    const covered=decision.recommendation_admissibility.admissible&&decision.coverage_state==='COVERED';
    const comparable=covered&&decision.ev_comparable;
    const playedTarget=decision.played_target_sizing&&decision.played_target_sizing.target_total_bb;
    const recTarget=decision.recommended_target_sizing&&decision.recommended_target_sizing.target_total_bb;
    return Leak.buildDecisionEvent({
      hand_id:handId,decision_id:decision.decision_id,timestamp,
      population_id:decision.identity.population_id,pack_id:decision.identity.pack_id,
      strategy_id:decision.identity.strategy_id,strategy_version:decision.identity.strategy_version,
      ev_reference:decision.identity.ev_reference,
      position:decision.hero_position,street:'PREFLOP',spot_family:decision.facing_context,context_id:decision.context_id,
      action_played:decision.played_action||'UNKNOWN',played_target_total_bb:playedTarget,
      action_recommended:decision.recommended_action||'UNKNOWN',recommended_target_total_bb:recTarget,
      played_ev_bb:comparable?decision.played_ev_bb:null,best_ev_bb:comparable?decision.recommended_ev_bb:null,
      uncertainty_bb:0,
      support:{covered,observations:decision.support&&decision.support.observations,source:'poker-preflop-decision/v1',reason:covered?null:decision.recommendation_admissibility.status},
      comparability:{comparable,reason:comparable?null:(covered?'NO_COMPARABLE_PLAYED_EV':decision.recommendation_admissibility.status)},
      played_is_all_in:['SHOVE','JAM'].includes(upper(decision.played_action)),
      notes:'canonical preflop decision adapter'
    });
  }
  function toCoverageInput(decision,options={}){
    return toLeakDecisionEvent(decision,options);
  }
  function toReviewDeepLink(decision){
    validateRuntimeDecision(decision);
    if(!decision.hand_id)return null;
    return {schema:'poker-review-deep-link/v1',kind:'REVIEW_DECISION',hand_id:decision.hand_id,decision_id:decision.decision_id,step_index:null,reason:'PREFLOP_DECISION'};
  }

  return {
    SCHEMA,ADAPTER_PROFILE,SNAPSHOT_SCHEMA,GUIDANCE_SCHEMA,COVERAGE_STATES,FAIL_CLOSED_STATES,
    buildDecision,validateRuntimeDecision,surfaceBundle,toLeakDecisionEvent,toCoverageInput,toReviewDeepLink
  };
});

/* END src/training/preflop-decision-adapter.js */

/* BEGIN src/preflop/hero-preflop-alternatives.js | blob df44f83c0fe1cd8341851b137f8943d849f70483 | sha256 11612abce016d73f7f77a60d3a08fb4154dd1112fbbf64ffb89e2b34d96cb8d2 */
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

/* END src/preflop/hero-preflop-alternatives.js */

/* BEGIN src/preflop/iso-sizing-diagnostics.js | blob d78c2b5cdc3c8f8144e61c7c2fa723e52099ed46 | sha256 d7b5246e8203a11fc1baf31fe921a2493b1763c5d646ec606432400d8c23fe86 */
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

/* END src/preflop/iso-sizing-diagnostics.js */
  })();
  const names=["PokerLeakAnalyzer","PokerNlheGameState","PokerPreflopContract","PokerPreflopDecision","PokerPreflopSearch","PokerPreflopGuidance","PokerPreflopDecisionAdapter","PokerHeroPreflopAlternatives","PokerIsoSizingDiagnostics"];
  const modules={};
  for(const name of names){
    if(!root||!root[name])throw new Error('pack-engine module missing after materialization: '+name);
    modules[name]=root[name];
  }
  const api=Object.freeze({
    schema:'poker-pack-engine-artifact/v1',
    artifact_class:'DISTRIBUTABLE_POPULATION_AGNOSTIC_ENGINE_CORE',
    build_identity:'source-set:b7f61710817e7bfa391d269bc1452242601c9a4bf10e8f4823e358bd6136b81b',
    source_commit:'5058c463cd5ed07596115153c2e95b2d7d8c949e',
    source_subset_sha256:'b7f61710817e7bfa391d269bc1452242601c9a4bf10e8f4823e358bd6136b81b',
    population_agnostic:true,
    legacy_mixed_bytes_reused:false,
    runtime_dependency_closure:'SELF_CONTAINED',
    modules:Object.freeze(modules)
  });
  root.PokerPackEngineArtifact=api;
  if(typeof module==='object'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
