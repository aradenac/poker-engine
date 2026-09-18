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
