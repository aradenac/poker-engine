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

  function text(value){return value==null?'':String(value).trim();}
  function upper(value){return text(value).toUpperCase();}
  function finite(value,name){
    const n=Number(value);
    if(!Number.isFinite(n))throw new Error(`${name} must be finite`);
    return n;
  }
  function optionalFinite(value,name,{min=null}={}){
    if(value==null||value==='')return null;
    const n=finite(value,name);
    if(min!=null&&n<min-EPS)throw new Error(`${name} must be >= ${min}`);
    return n;
  }
  function nonNegativeInteger(value,name){
    const n=finite(value,name);
    if(!Number.isInteger(n)||n<0)throw new Error(`${name} must be a non-negative integer`);
    return n;
  }
  function isoTimestamp(value,name='timestamp'){
    const raw=text(value);
    if(!raw)throw new Error(`${name} is required`);
    const ms=Date.parse(raw);
    if(!Number.isFinite(ms))throw new Error(`${name} must be a valid ISO timestamp`);
    return new Date(ms).toISOString();
  }
  function requiredText(value,name){
    const v=text(value);
    if(!v)throw new Error(`${name} is required`);
    return v;
  }
  function round(value){return Math.round((value+Number.EPSILON)*1e9)/1e9;}
  function stableUnique(values){return Array.from(new Set(values)).sort();}

  function normalizeSupport(input={}){
    const covered=input.covered!==false;
    return {
      covered,
      observations:input.observations==null?null:nonNegativeInteger(input.observations,'support.observations'),
      source:text(input.source)||null,
      reason:covered?null:(text(input.reason)||'UNSUPPORTED')
    };
  }

  function normalizeComparability(input={}){
    const comparable=input.comparable!==false;
    return {
      comparable,
      reason:comparable?null:(text(input.reason)||'NON_COMPARABLE')
    };
  }

  function classify({support,comparability,nominalLossBB,uncertaintyBB,actionPlayed,actionRecommended,playedTargetBB,recommendedTargetBB}){
    if(!support.covered)return 'UNSUPPORTED';
    if(!comparability.comparable)return 'NON_COMPARABLE';
    if(nominalLossBB<=EPS)return 'NO_ERROR';
    if(nominalLossBB<=uncertaintyBB+EPS)return 'WITHIN_NOISE';
    if(actionPlayed!==actionRecommended)return 'ACTION_ERROR';
    if(playedTargetBB!=null&&recommendedTargetBB!=null&&Math.abs(playedTargetBB-recommendedTargetBB)>EPS)return 'SIZING_ERROR';
    return 'ACTION_ERROR';
  }

  function buildDecisionEvent(input={}){
    if(input.schema&&input.schema!==EVENT_SCHEMA)throw new Error(`expected ${EVENT_SCHEMA}`);
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
    const played_ev_bb=finite(input.played_ev_bb,'played_ev_bb');
    const best_ev_bb=finite(input.best_ev_bb,'best_ev_bb');
    const uncertainty_bb=optionalFinite(input.uncertainty_bb,'uncertainty_bb',{min:0})||0;
    const support=normalizeSupport(input.support||{});
    const comparability=normalizeComparability(input.comparability||{});
    const raw_delta_ev_bb=round(best_ev_bb-played_ev_bb);
    const nominal_loss_bb=round(Math.max(0,raw_delta_ev_bb));
    const error_type=classify({
      support,comparability,nominalLossBB:nominal_loss_bb,uncertaintyBB:uncertainty_bb,
      actionPlayed:action_played,actionRecommended:action_recommended,
      playedTargetBB:played_target_total_bb,recommendedTargetBB:recommended_target_total_bb
    });
    const attributed_loss_bb=(support.covered&&comparability.comparable&&error_type!=='WITHIN_NOISE')?nominal_loss_bb:0;
    const is_jam=Boolean(input.played_is_all_in)||action_played==='SHOVE'||action_played==='JAM';
    const is_overbet=played_size_pot_ratio!=null&&played_size_pot_ratio>1+EPS;

    return {
      schema:EVENT_SCHEMA,
      hand_id,decision_id,timestamp,
      population_id,pack_id,strategy_id,strategy_version,ev_reference,
      context:{position,street,spot_family,context_id},
      played:{action:action_played,target_total_bb:played_target_total_bb,size_pot_ratio:played_size_pot_ratio,is_all_in:is_jam},
      recommended:{action:action_recommended,target_total_bb:recommended_target_total_bb,size_pot_ratio:recommended_size_pot_ratio},
      ev:{played_bb:played_ev_bb,best_bb:best_ev_bb,raw_delta_bb:raw_delta_ev_bb,nominal_loss_bb,attributed_loss_bb,uncertainty_bb},
      support,comparability,error_type,
      tags:{jam:is_jam,overbet:is_overbet},
      notes:text(input.notes)
    };
  }

  function normalizeEvent(input){return input&&input.schema===EVENT_SCHEMA?buildDecisionEvent({
    schema:input.schema,
    hand_id:input.hand_id,decision_id:input.decision_id,timestamp:input.timestamp,
    population_id:input.population_id,pack_id:input.pack_id,strategy_id:input.strategy_id,strategy_version:input.strategy_version,ev_reference:input.ev_reference,
    position:input.context?.position,street:input.context?.street,spot_family:input.context?.spot_family,context_id:input.context?.context_id,
    action_played:input.played?.action,played_target_total_bb:input.played?.target_total_bb,played_size_pot_ratio:input.played?.size_pot_ratio,played_is_all_in:input.played?.is_all_in,
    action_recommended:input.recommended?.action,recommended_target_total_bb:input.recommended?.target_total_bb,recommended_size_pot_ratio:input.recommended?.size_pot_ratio,
    played_ev_bb:input.ev?.played_bb,best_ev_bb:input.ev?.best_bb,uncertainty_bb:input.ev?.uncertainty_bb,
    support:input.support,comparability:input.comparability,notes:input.notes
  }):buildDecisionEvent(input);}

  function scopeOf(event){
    return {
      population_id:event.population_id,
      pack_id:event.pack_id,
      strategy_id:event.strategy_id,
      strategy_version:event.strategy_version,
      ev_reference:event.ev_reference
    };
  }
  function scopeKey(scope){return SCOPE_FIELDS.map(k=>`${k}=${encodeURIComponent(scope[k]==null?'':scope[k])}`).join('|');}

  function asSet(value,upperCase=false){
    if(value==null)return null;
    const rows=Array.isArray(value)?value:[value];
    return new Set(rows.map(x=>upperCase?upper(x):text(x)).filter(Boolean));
  }

  function filterEvents(events,filters={}){
    const sets={
      population_id:asSet(filters.population_id),pack_id:asSet(filters.pack_id),strategy_id:asSet(filters.strategy_id),strategy_version:asSet(filters.strategy_version),ev_reference:asSet(filters.ev_reference),
      position:asSet(filters.position,true),street:asSet(filters.street,true),spot_family:asSet(filters.spot_family,true),error_type:asSet(filters.error_type,true)
    };
    const from=filters.from==null?null:Date.parse(filters.from);
    const to=filters.to==null?null:Date.parse(filters.to);
    if(filters.from!=null&&!Number.isFinite(from))throw new Error('filters.from must be a valid timestamp');
    if(filters.to!=null&&!Number.isFinite(to))throw new Error('filters.to must be a valid timestamp');
    if(from!=null&&to!=null&&from>to)throw new Error('filters.from must be <= filters.to');
    const minLoss=filters.min_loss_bb==null?null:optionalFinite(filters.min_loss_bb,'filters.min_loss_bb',{min:0});
    return events.filter(event=>{
      const pairs=[
        ['population_id',event.population_id],['pack_id',event.pack_id],['strategy_id',event.strategy_id],['strategy_version',event.strategy_version],['ev_reference',event.ev_reference],
        ['position',event.context.position],['street',event.context.street],['spot_family',event.context.spot_family],['error_type',event.error_type]
      ];
      for(const [key,value] of pairs)if(sets[key]&&!sets[key].has(value==null?'':String(value)))return false;
      const ms=Date.parse(event.timestamp);
      if(from!=null&&ms<from)return false;
      if(to!=null&&ms>to)return false;
      if(filters.covered!=null&&event.support.covered!==Boolean(filters.covered))return false;
      if(filters.comparable!=null&&event.comparability.comparable!==Boolean(filters.comparable))return false;
      if(filters.jam!=null&&event.tags.jam!==Boolean(filters.jam))return false;
      if(filters.overbet!=null&&event.tags.overbet!==Boolean(filters.overbet))return false;
      if(minLoss!=null&&event.ev.attributed_loss_bb+EPS<minLoss)return false;
      return true;
    });
  }

  function sourceRef(event){return {hand_id:event.hand_id,decision_id:event.decision_id};}
  function groupKey(event,dimension){
    if(dimension==='position')return event.context.position;
    if(dimension==='street')return event.context.street;
    if(dimension==='spot_family')return event.context.spot_family;
    if(dimension==='action_pair')return `${event.played.action}->${event.recommended.action}`;
    if(dimension==='error_type')return event.error_type;
    throw new Error(`unsupported dimension ${dimension}`);
  }

  function summarizeGroup(key,rows,totalLoss,eligibleCount){
    const hands=stableUnique(rows.map(x=>x.hand_id));
    const attributed=round(rows.reduce((s,x)=>s+x.ev.attributed_loss_bb,0));
    const nominal=round(rows.reduce((s,x)=>s+x.ev.nominal_loss_bb,0));
    return {
      key,
      decisions:rows.length,
      hands:hands.length,
      total_loss_bb:attributed,
      nominal_loss_bb:nominal,
      average_loss_bb:rows.length?round(attributed/rows.length):0,
      frequency_pct:eligibleCount?round(rows.length*100/eligibleCount):0,
      loss_share_pct:totalLoss>EPS?round(attributed*100/totalLoss):0,
      source_refs:rows.map(sourceRef)
    };
  }

  function aggregateDimension(events,dimension,totalLoss){
    const groups=new Map();
    for(const event of events){
      const key=groupKey(event,dimension);
      if(!groups.has(key))groups.set(key,[]);
      groups.get(key).push(event);
    }
    return Array.from(groups.entries())
      .map(([key,rows])=>summarizeGroup(key,rows,totalLoss,events.length))
      .sort((a,b)=>b.total_loss_bb-a.total_loss_bb||b.decisions-a.decisions||a.key.localeCompare(b.key));
  }

  function exclusionReason(event){
    if(!event.support.covered)return `UNSUPPORTED:${event.support.reason||'UNSUPPORTED'}`;
    if(!event.comparability.comparable)return `NON_COMPARABLE:${event.comparability.reason||'NON_COMPARABLE'}`;
    return null;
  }

  function summarizeTagged(events,totalLoss){
    const tagged=events.filter(x=>x.tags.jam||x.tags.overbet);
    const jam=events.filter(x=>x.tags.jam);
    const overbet=events.filter(x=>x.tags.overbet);
    return {
      combined:summarizeGroup('JAM_OR_OVERBET',tagged,totalLoss,events.length),
      jam:summarizeGroup('JAM',jam,totalLoss,events.length),
      overbet:summarizeGroup('OVERBET',overbet,totalLoss,events.length)
    };
  }

  function analyzeLeaks(inputEvents,filters={}){
    if(!Array.isArray(inputEvents))throw new Error('inputEvents must be an array');
    const normalized=inputEvents.map(normalizeEvent);
    const selected=filterEvents(normalized,filters);
    const scopes=new Map();
    for(const event of selected){const scope=scopeOf(event);scopes.set(scopeKey(scope),scope);}
    if(scopes.size>1)throw new Error(`analysis spans ${scopes.size} population/pack/strategy/version/EV scopes; filter to one scope before aggregating`);
    const scope=scopes.size?Array.from(scopes.values())[0]:null;
    const eligible=selected.filter(x=>x.support.covered&&x.comparability.comparable);
    const totalLoss=round(eligible.reduce((s,x)=>s+x.ev.attributed_loss_bb,0));
    const nominalLoss=round(eligible.reduce((s,x)=>s+x.ev.nominal_loss_bb,0));
    const hands=stableUnique(eligible.map(x=>x.hand_id));
    const contributing=eligible.filter(x=>x.ev.attributed_loss_bb>EPS);
    const exclusions={};
    for(const event of selected){
      const reason=exclusionReason(event);
      if(reason)exclusions[reason]=(exclusions[reason]||0)+1;
    }
    const by={};
    for(const dimension of DIMENSIONS)by[dimension]=aggregateDimension(eligible,dimension,totalLoss);
    const topDecisions=contributing.slice().sort((a,b)=>
      b.ev.attributed_loss_bb-a.ev.attributed_loss_bb||a.hand_id.localeCompare(b.hand_id)||a.decision_id.localeCompare(b.decision_id)
    ).map(event=>({
      hand_id:event.hand_id,decision_id:event.decision_id,timestamp:event.timestamp,
      position:event.context.position,street:event.context.street,spot_family:event.context.spot_family,
      action_played:event.played.action,action_recommended:event.recommended.action,error_type:event.error_type,
      loss_bb:event.ev.attributed_loss_bb,nominal_loss_bb:event.ev.nominal_loss_bb,uncertainty_bb:event.ev.uncertainty_bb,
      jam:event.tags.jam,overbet:event.tags.overbet
    }));
    const withinNoise=eligible.filter(x=>x.error_type==='WITHIN_NOISE');
    return {
      schema:REPORT_SCHEMA,
      event_schema:EVENT_SCHEMA,
      scope,
      filters:{...filters},
      summary:{
        decisions_selected:selected.length,
        decisions_eligible:eligible.length,
        decisions_contributing:contributing.length,
        hands_analyzed:hands.length,
        total_loss_bb:totalLoss,
        nominal_loss_bb:nominalLoss,
        loss_bb_per_100_hands:hands.length?round(totalLoss*100/hands.length):0,
        loss_bb_per_100_decisions:eligible.length?round(totalLoss*100/eligible.length):0,
        coverage_pct:selected.length?round(eligible.length*100/selected.length):0,
        within_noise_decisions:withinNoise.length,
        exclusions
      },
      leaks:{by,aggressive_sizing:summarizeTagged(eligible,totalLoss),top_decisions:topDecisions},
      decision_events:selected
    };
  }

  function analyzeByScope(inputEvents,filters={}){
    if(!Array.isArray(inputEvents))throw new Error('inputEvents must be an array');
    const normalized=inputEvents.map(normalizeEvent);
    const selected=filterEvents(normalized,filters);
    const groups=new Map();
    for(const event of selected){
      const key=scopeKey(scopeOf(event));
      if(!groups.has(key))groups.set(key,[]);
      groups.get(key).push(event);
    }
    return Array.from(groups.entries()).sort((a,b)=>a[0].localeCompare(b[0])).map(([,rows])=>analyzeLeaks(rows));
  }

  function exportReportJSON(report,{pretty=true}={}){
    if(!report||report.schema!==REPORT_SCHEMA)throw new Error(`expected ${REPORT_SCHEMA}`);
    return JSON.stringify(report,null,pretty?2:0);
  }

  function csvCell(value){
    if(value==null)return '';
    const s=typeof value==='object'?JSON.stringify(value):String(value);
    return /[",\n\r]/.test(s)?`"${s.replace(/"/g,'""')}"`:s;
  }

  function exportReportCSV(report){
    if(!report||report.schema!==REPORT_SCHEMA)throw new Error(`expected ${REPORT_SCHEMA}`);
    const headers=['row_type','dimension','key','hand_id','decision_id','timestamp','position','street','spot_family','action_played','action_recommended','error_type','count','hands','total_loss_bb','nominal_loss_bb','uncertainty_bb','frequency_pct','loss_share_pct','jam','overbet','source_refs'];
    const rows=[];
    const push=obj=>rows.push(headers.map(h=>csvCell(obj[h])).join(','));
    rows.push(headers.join(','));
    push({row_type:'SUMMARY',key:'ALL',count:report.summary.decisions_eligible,hands:report.summary.hands_analyzed,total_loss_bb:report.summary.total_loss_bb,nominal_loss_bb:report.summary.nominal_loss_bb});
    for(const [dimension,groups] of Object.entries(report.leaks.by)){
      for(const group of groups)push({row_type:'GROUP',dimension,key:group.key,count:group.decisions,hands:group.hands,total_loss_bb:group.total_loss_bb,nominal_loss_bb:group.nominal_loss_bb,frequency_pct:group.frequency_pct,loss_share_pct:group.loss_share_pct,source_refs:group.source_refs});
    }
    for(const event of report.decision_events){
      push({
        row_type:'DECISION',hand_id:event.hand_id,decision_id:event.decision_id,timestamp:event.timestamp,
        position:event.context.position,street:event.context.street,spot_family:event.context.spot_family,
        action_played:event.played.action,action_recommended:event.recommended.action,error_type:event.error_type,
        count:1,hands:1,total_loss_bb:event.ev.attributed_loss_bb,nominal_loss_bb:event.ev.nominal_loss_bb,uncertainty_bb:event.ev.uncertainty_bb,
        jam:event.tags.jam,overbet:event.tags.overbet,source_refs:[sourceRef(event)]
      });
    }
    return rows.join('\n')+'\n';
  }

  return {
    EVENT_SCHEMA,REPORT_SCHEMA,SCOPE_FIELDS,DIMENSIONS,
    buildDecisionEvent,normalizeEvent,scopeOf,scopeKey,filterEvents,
    analyzeLeaks,analyzeByScope,exportReportJSON,exportReportCSV
  };
});
