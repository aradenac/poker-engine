(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerActionSizingEV=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';

  const SUMMARY_SCHEMA='decision-summary/v1';
  const CANONICAL_SCHEMA='poker-preflop-decision/v1';
  const CANONICAL_PROFILE='CANONICAL_RUNTIME_DECISION_V1';

  function defaultEscape(value){
    return String(value??'').replace(/[&<>"']/g,c=>({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    })[c]);
  }
  function defaultFormatBB(value){
    const n=Number(value);
    return Number.isFinite(n)?`${n.toFixed(2).replace(/\.?0+$/,'')} BB`:'—';
  }
  function clone(value){return value==null?value:JSON.parse(JSON.stringify(value));}
  function rendererOptions(options={}){
    return {
      escapeHtml:typeof options.escapeHtml==='function'?options.escapeHtml:defaultEscape,
      formatBB:typeof options.formatBB==='function'?options.formatBB:defaultFormatBB
    };
  }
  function qualityFromEV(summary){
    const rawLoss=Number(summary?.lossEVBB),effectiveLoss=Number(summary?.effectiveLossEVBB),withinNoise=!!summary?.withinNoise;
    if(!Number.isFinite(rawLoss))return {key:'unknown',label:'Indéterminée',note:'ΔEV indisponible'};
    if(rawLoss<=1e-9)return {key:'good',label:'Bonne',note:'meilleure EV'};
    if(withinNoise||(Number.isFinite(effectiveLoss)&&effectiveLoss<=1e-9))return {key:'close',label:'Proche',note:'écart dans le bruit Monte-Carlo'};
    return {key:'bad',label:'Erreur',note:'perte EV au-delà de l’incertitude'};
  }
  function primarySummaryHtml(summary,options={}){
    if(!summary)return '';
    const {escapeHtml,formatBB}=rendererOptions(options),compact=!!options.compact;
    const p=summary.played||{},r=summary.recommended||{},delta=Number(summary.deltaEVBB),loss=Number(summary.lossEVBB),quality=qualityFromEV(summary);
    const deltaText=Number.isFinite(delta)?formatBB(delta):'—';
    const lossText=Number.isFinite(loss)?formatBB(Math.max(0,loss)):'—';
    const qualityText=quality.note?`${quality.label} · ${quality.note}`:quality.label;
    const card=(k,v,s,cls='')=>`<div class="decision-primary-card ${cls}"><div class="k">${escapeHtml(k)}</div><div class="v">${escapeHtml(v||'—')}</div>${s?`<div class="s">${escapeHtml(s)}</div>`:''}</div>`;
    return `<div class="decision-primary-grid${compact?' compact':''}" data-decision-summary-schema="${SUMMARY_SCHEMA}">
    ${card('Perte EV',lossText,`ΔEV ${deltaText} · ${qualityText}`,`delta quality-${quality.key}`)}
    ${card('Joué',p.label,p.sizing,'played')}
    ${card('Recommandé',r?.label||'—',r?.sizing||'—','recommended')}
    ${card('EV jouée',Number.isFinite(Number(p.evBB))?formatBB(Number(p.evBB)):'—','EV finale retenue')}
    ${card('Meilleure EV',Number.isFinite(Number(r?.evBB))?formatBB(Number(r.evBB)):'—','Meilleure alternative')}
  </div>`;
  }
  function alternativesStripHtml(summary,options={}){
    const {escapeHtml,formatBB}=rendererOptions(options),limit=Math.max(1,Number(options.limit)||3);
    const xs=(summary?.alternatives||[]).slice().sort((a,b)=>Number(b.evBB)-Number(a.evBB)).slice(0,limit);
    if(!xs.length)return '';
    return `<div class="decision-alt-strip"><span class="decision-alt-label">Alternatives</span>${xs.map(a=>`<span class="decision-alt-pill${a.recommended?' best':''}">${escapeHtml(a.label)} · ${escapeHtml(a.sizing||'—')} · EV ${Number.isFinite(Number(a.evBB))?escapeHtml(formatBB(a.evBB)):'—'}</span>`).join('')}</div>`;
  }
  function canonicalSurfaceSnapshot(decision,options={}){
    if(!decision||decision.schema!==CANONICAL_SCHEMA||decision.contract_profile!==CANONICAL_PROFILE){
      throw new Error('expected canonical runtime '+CANONICAL_SCHEMA);
    }
    const surface=String(options.surface||'central-ui');
    return {
      source:{split:null,issue:205,source:`central-ui:${surface}`},
      decision_id:String(decision.decision_id||''),
      identity:clone(decision.identity||null),
      recommended_action:decision.recommended_action==null?null:String(decision.recommended_action),
      recommended_target_sizing:clone(decision.recommended_target_sizing??null),
      incremental_cost_bb:decision.incremental_cost_bb==null?null:Number(decision.incremental_cost_bb),
      recommended_ev_bb:decision.recommended_ev_bb==null?null:Number(decision.recommended_ev_bb)
    };
  }

  return Object.freeze({
    SUMMARY_SCHEMA,CANONICAL_SCHEMA,CANONICAL_PROFILE,
    qualityFromEV,primarySummaryHtml,alternativesStripHtml,canonicalSurfaceSnapshot,
    semantics:Object.freeze({
      selects_action:false,recomputes_ev:false,recomputes_sizing:false,
      recomputes_incremental_cost:false,validator:'#299'
    })
  });
});
