'use strict';

const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const Presentation=require('../../site/action-sizing-ev.js');
const Audit=require('../../src/analytics/recommendation-consistency.js');

const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'../fixtures/central-ui/action_sizing_ev_parity_v1.json'),'utf8'));
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
const fmt=value=>Number.isFinite(Number(value))?`${Number(value).toFixed(2)} BB`:'—';

function legacyQuality(summary){
  const rawLoss=Number(summary?.lossEVBB),effectiveLoss=Number(summary?.effectiveLossEVBB),withinNoise=!!summary?.withinNoise;
  if(!Number.isFinite(rawLoss))return {key:'unknown',label:'Indéterminée',note:'ΔEV indisponible'};
  if(rawLoss<=1e-9)return {key:'good',label:'Bonne',note:'meilleure EV'};
  if(withinNoise||(Number.isFinite(effectiveLoss)&&effectiveLoss<=1e-9))return {key:'close',label:'Proche',note:'écart dans le bruit Monte-Carlo'};
  return {key:'bad',label:'Erreur',note:'perte EV au-delà de l’incertitude'};
}
function legacyPrimary(summary,{compact=false}={}){
  if(!summary)return '';
  const p=summary.played||{},r=summary.recommended||{},delta=Number(summary.deltaEVBB),loss=Number(summary.lossEVBB),quality=legacyQuality(summary);
  const deltaText=Number.isFinite(delta)?fmt(delta):'—',lossText=Number.isFinite(loss)?fmt(Math.max(0,loss)):'—';
  const qualityText=quality.note?`${quality.label} · ${quality.note}`:quality.label;
  const card=(k,v,s,cls='')=>`<div class="decision-primary-card ${cls}"><div class="k">${esc(k)}</div><div class="v">${esc(v||'—')}</div>${s?`<div class="s">${esc(s)}</div>`:''}</div>`;
  return `<div class="decision-primary-grid${compact?' compact':''}" data-decision-summary-schema="decision-summary/v1">
    ${card('Perte EV',lossText,`ΔEV ${deltaText} · ${qualityText}`,`delta quality-${quality.key}`)}
    ${card('Joué',p.label,p.sizing,'played')}
    ${card('Recommandé',r?.label||'—',r?.sizing||'—','recommended')}
    ${card('EV jouée',Number.isFinite(Number(p.evBB))?fmt(Number(p.evBB)):'—','EV finale retenue')}
    ${card('Meilleure EV',Number.isFinite(Number(r?.evBB))?fmt(Number(r.evBB)):'—','Meilleure alternative')}
  </div>`;
}
function legacyAlternatives(summary,limit=3){
  const xs=(summary?.alternatives||[]).slice().sort((a,b)=>Number(b.evBB)-Number(a.evBB)).slice(0,Math.max(1,limit));
  if(!xs.length)return '';
  return `<div class="decision-alt-strip"><span class="decision-alt-label">Alternatives</span>${xs.map(a=>`<span class="decision-alt-pill${a.recommended?' best':''}">${esc(a.label)} · ${esc(a.sizing||'—')} · EV ${Number.isFinite(Number(a.evBB))?esc(fmt(a.evBB)):'—'}</span>`).join('')}</div>`;
}

const summary=fixture.summary;
assert.deepEqual(Presentation.qualityFromEV(summary),legacyQuality(summary));
assert.equal(Presentation.primarySummaryHtml(summary,{compact:true,escapeHtml:esc,formatBB:fmt}),legacyPrimary(summary,{compact:true}));
assert.equal(Presentation.alternativesStripHtml(summary,{limit:3,escapeHtml:esc,formatBB:fmt}),legacyAlternatives(summary,3));

const decision=fixture.canonical_decision;
const surfaces=Object.fromEntries(Audit.SURFACES.map(name=>[name,Presentation.canonicalSurfaceSnapshot(decision,{surface:name})]));
let row=Audit.auditDecision({decision,surfaces,source:{split:'SYNTHETIC',source:'issue-205-parity'}});
assert.equal(row.status,'PASS');
assert.equal(row.surface_parity.complete,true);
assert.equal(row.recommendation_tuple.action,'CALL');
assert.equal(row.recommendation_tuple.sizing.target_total_bb,3);
assert.equal(row.recommendation_tuple.incremental_cost_bb,2);
assert.equal(row.recommendation_tuple.ev_bb,2);

const jamFeed=JSON.parse(JSON.stringify(surfaces));
jamFeed.feed.recommended_action='JAM';
jamFeed.feed.recommended_target_sizing={target_total_bb:100,bet_to_bb:100};
jamFeed.feed.incremental_cost_bb=99;
jamFeed.feed.recommended_ev_bb=1.2;
row=Audit.auditDecision({decision,surfaces:jamFeed,source:{split:'SYNTHETIC',source:'issue-205-jam-regression'}});
assert.equal(row.status,'FAIL');
const violations=row.violations.map(x=>x.type);
assert.ok(violations.includes('SURFACE_DIVERGENCE'));
assert.ok(violations.includes('NON_MAX_EV_RECOMMENDATION'));

const closed={...decision,coverage_state:'LOW_SUPPORT',recommended_action:null,recommended_target_sizing:null,incremental_cost_bb:null,recommended_ev_bb:null,alternatives:[],recommendation_admissibility:{...decision.recommendation_admissibility,admissible:false,status:'LOW_SUPPORT',default_advice:false,selected_alternative_id:null}};
const closedSurfaces=Object.fromEntries(Audit.SURFACES.map(name=>[name,Presentation.canonicalSurfaceSnapshot(closed,{surface:name})]));
row=Audit.auditDecision({decision:closed,surfaces:closedSurfaces,source:{split:'SYNTHETIC',source:'issue-205-fail-closed'}});
assert.equal(row.status,'PASS');
assert.equal(Presentation.semantics.selects_action,false);
assert.equal(Presentation.semantics.recomputes_ev,false);
assert.equal(Presentation.semantics.recomputes_sizing,false);
assert.equal(Presentation.semantics.recomputes_incremental_cost,false);
assert.equal(Presentation.semantics.validator,'#299');

console.log('action+sizing+EV presentation parity: PASS');
