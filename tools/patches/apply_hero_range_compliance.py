#!/usr/bin/env python3
"""Integrate issue #98 Hero-range compliance into the static replayer.

The patch is marker-based and idempotent. The compliance engine remains in
site/hero-compliance.js; this script only wires it to the existing replayer,
adds conservative context coverage, and enables deep links into the range grid.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "site/index.html"
HERO_RANGES = ROOT / "site/hero-ranges.js"
HERO_APP = ROOT / "site/hero-ranges-app.js"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one marker, found {count}")
    return text.replace(old, new, 1)


def patch_repository_contract() -> None:
    text = HERO_RANGES.read_text(encoding="utf-8")
    old = "  const SPOTS=['UNOPENED','VS_LIMPERS','VS_RFI','VS_RFI_CALLERS','VS_3BET','VS_4BET','VS_JAM'];\n"
    new = "  const SPOTS=['UNOPENED','VS_LIMPERS','VS_RFI','VS_RFI_CALLERS','VS_ISO','VS_ISO_CALLERS','VS_3BET','VS_4BET','VS_5BET','VS_6BET_PLUS','VS_JAM'];\n"
    text = replace_once(text, old, new, "Hero repository spot vocabulary")
    HERO_RANGES.write_text(text, encoding="utf-8")


def patch_editor_deep_link() -> None:
    text = HERO_APP.read_text(encoding="utf-8")
    old = "initOptions();renderAll();\n"
    new = '''function applyDeepLink(){
  const q=new URLSearchParams(window.location.search);
  const population=q.get("population"),position=String(q.get("position")||"").toUpperCase(),stack=Number(q.get("stack")),spot=String(q.get("spot")||"").toUpperCase(),hand=String(q.get("hand")||"").toUpperCase();
  if(population)els.population.value=population;
  if(HeroRanges.POSITIONS.includes(position))els.position.value=position;
  if(Number.isFinite(stack)&&stack>0)els.stack.value=String(stack);
  if(HeroRanges.SPOTS.includes(spot))els.spot.value=spot;
  if(HeroRanges.HAND_CLASSES.includes(hand))selectedHand=hand;
}

initOptions();applyDeepLink();renderAll();
'''
    text = replace_once(text, old, new, "Hero editor deep link")
    HERO_APP.write_text(text, encoding="utf-8")


def patch_index() -> None:
    text = INDEX.read_text(encoding="utf-8")

    # Load the repository before the compliance module; both precede the shared
    # preflop contract and the monolithic analyser code.
    old_script = '<script src="./preflop-contract.js"></script>\n'
    new_script = '<script src="./hero-ranges.js"></script>\n<script src="./hero-compliance.js"></script>\n' + old_script
    text = replace_once(text, old_script, new_script, "Hero compliance scripts")

    compliance_helpers = r'''const HERO_RANGE_REPOSITORY_STORAGE_KEY="poker.hero.range.repository.v1";
let heroRangeRepositoryCache={raw:null,repo:null};
function heroRangeRepositorySnapshot(){
  if(!window.PokerHeroRanges)return null;
  try{
    const raw=localStorage.getItem(HERO_RANGE_REPOSITORY_STORAGE_KEY);
    if(!raw)return null;
    if(heroRangeRepositoryCache.raw===raw)return heroRangeRepositoryCache.repo;
    const repo=window.PokerHeroRanges.importDocument(JSON.parse(raw));
    heroRangeRepositoryCache={raw,repo};return repo;
  }catch(err){console.warn('Hero range repository unavailable',err);return null;}
}
function heroRangeComplianceForStep(stepIndex,step){
  if(!window.PokerHeroCompliance||!state.selectedHand||step?.street!=="Préflop"||step?.activePlayer!==state.selectedHand.heroName)return null;
  const count=replayPreflopDecisionCount(stepIndex);if(count<=0)return null;
  const decision=populationPreflopDecisionTrace(state.selectedHand)[count-1];
  if(!decision||decision.player!==state.selectedHand.heroName)return null;
  const handClass=cardsToNotation(state.selectedHand.heroCards||[]),repo=heroRangeRepositorySnapshot();
  return window.PokerHeroCompliance.evaluateDecision({repo,decision,handClass,populationId:repo?.defaults?.population_id||null});
}
function heroRangeComplianceMeta(result){
  if(!result)return null;
  const map={
    COMPLIANT:{label:'Plan conforme',cls:'good'},
    MIXED_ALLOWED:{label:'Mix autorisé',cls:'good'},
    OUT_OF_RANGE:{label:'Hors range',cls:'bad'},
    UNCOVERED_HAND:{label:'Main non couverte',cls:'subtle'},
    UNKNOWN_ACTION:{label:'Action non couverte',cls:'subtle'},
    NO_VERDICT:{label:'Contexte non couvert',cls:'subtle'}
  };
  return map[result.action_status]||{label:'Contexte non couvert',cls:'subtle'};
}
function heroRangeSizingShort(result){
  const s=result?.sizing;if(!s||s.status==='NOT_APPLICABLE')return '';
  if(s.status==='MATCHED')return ` · sizing ✓ ${formatBB(s.observed_target_total_bb)}`;
  if(s.status==='OUT_OF_RANGE')return ` · sizing hors plan ${formatBB(s.observed_target_total_bb)}`;
  if(s.status==='UNKNOWN_OBSERVED_SIZE')return ' · sizing joué inconnu';
  if(s.status==='UNCOVERED')return ' · sizing non couvert';
  return '';
}
function heroRangeCompliancePillHtml(stepIndex,step){
  const result=heroRangeComplianceForStep(stepIndex,step);if(!result)return '';
  const meta=heroRangeComplianceMeta(result),pct=Number.isFinite(result.action_probability)?` · ${(100*result.action_probability).toFixed(result.action_probability>0&&result.action_probability<.1?1:0).replace('.',',')} %`:'';
  const action=result.planned_action?` · ${escapeHtml(result.planned_action)}`:'';
  const title=`${meta.label}${action}${pct}${heroRangeSizingShort(result)} · conformité au plan Hero, distincte de la recommandation moteur`;
  return `<a class="action-mini-pill ${meta.cls} hero-plan-summary" href="${escapeHtml(result.editor_href||'./hero-ranges.html')}" title="${escapeHtml(title)}">Plan ${escapeHtml(meta.label)}${action}${pct}</a>`;
}
function heroRangeExpectedSizingText(result){
  const rows=result?.sizing?.expected||[];if(!rows.length)return 'non couvert';
  return rows.map(x=>`${Number(x.target_total_bb).toFixed(2).replace('.',',')} BB (${(100*Number(x.probability||0)).toFixed(0)} %)`).join(' · ');
}
function heroRangeComplianceDetailHtml(stepIndex,step){
  const result=heroRangeComplianceForStep(stepIndex,step);if(!result)return '';
  const meta=heroRangeComplianceMeta(result),c=result.resolved_context,pct=Number.isFinite(result.action_probability)?`${(100*result.action_probability).toFixed(result.action_probability>0&&result.action_probability<.1?1:0).replace('.',',')} %`:'—';
  const sizing=result.sizing?.status==='MATCHED'?'conforme':result.sizing?.status==='OUT_OF_RANGE'?'hors plan':result.sizing?.status==='UNKNOWN_OBSERVED_SIZE'?'joué inconnu':result.sizing?.status==='UNCOVERED'?'non couvert':'non applicable';
  const context=c?`${c.position} · ${c.effective_stack_bb} BB · ${c.spot}`:(result.context_status||'non couvert');
  const layer=result.layer?`${result.layer}${result.layer_version?` · ${result.layer_version}`:''}`:'—';
  return `<div class="section hero-compliance-detail"><div class="section-title">Conformité au plan Hero</div><div class="action-detail-meta-strip"><span class="action-detail-chip">Verdict <b>${escapeHtml(meta.label)}</b></span><span class="action-detail-chip">Action jouée <b>${escapeHtml(result.planned_action||'—')}</b></span><span class="action-detail-chip">Fréquence prescrite <b>${escapeHtml(pct)}</b></span><span class="action-detail-chip">Sizing <b>${escapeHtml(sizing)}</b></span><span class="action-detail-chip">Couche <b>${escapeHtml(layer)}</b></span></div><div class="action-analysis-meta">Contexte résolu : <b>${escapeHtml(context)}</b> · sizings attendus : <b>${escapeHtml(heroRangeExpectedSizingText(result))}</b> · dépôt <b>${escapeHtml(result.repository_token||'—')}</b>.</div><div class="action-section-note">Ce verdict utilise uniquement l’état préflop <b>avant l’action</b> et la main de Hero. Une action mixée de fréquence positive est autorisée sur cette occurrence ; la calibration de fréquence exige un échantillon adapté. <b>Écart d’EV : non évalué</b> ici — conformité personnelle et recommandation moteur restent deux objets distincts.</div><div class="actions"><a class="secondary" style="display:inline-block;width:auto;text-decoration:none" href="${escapeHtml(result.editor_href||'./hero-ranges.html')}">Ouvrir cette grille Hero</a></div></div>`;
}
function heroRangeComplianceSummaryHtml(){
  if(!state.selectedHand||!window.PokerHeroCompliance)return '';
  const upto=replayPreflopDecisionCount(state.replayIndex),trace=populationPreflopDecisionTrace(state.selectedHand).slice(0,upto),repo=heroRangeRepositorySnapshot(),handClass=cardsToNotation(state.selectedHand.heroCards||[]);
  const results=trace.filter(d=>d.player===state.selectedHand.heroName).map(decision=>window.PokerHeroCompliance.evaluateDecision({repo,decision,handClass,populationId:repo?.defaults?.population_id||null}));
  if(!results.length)return '';
  const s=window.PokerHeroCompliance.summarize(results),groups=(s.groups||[]).map(g=>`${g.position||'?'} / ${g.spot||'?'} : ${g.allowed}/${g.judged} autorisée(s)${g.uncovered?` · ${g.uncovered} non couverte(s)`:''}`).join(' · ');
  const href=results[results.length-1]?.editor_href||'./hero-ranges.html';
  return `<div class="tiny hero-compliance-summary" style="margin:0 0 10px;padding:7px 9px;border:1px solid var(--border);border-radius:8px;background:#0f1729"><b>Plan Hero</b> · ${s.allowed}/${s.judged} décision(s) jugée(s) autorisée(s) · ${s.out_of_range} hors range · ${s.uncovered} non couverte(s)${s.sizing_out_of_range?` · ${s.sizing_out_of_range} sizing hors plan`:''}<br><span>${escapeHtml(groups||'Aucun contexte jugé.')}</span> · <a href="${escapeHtml(href)}">grille</a><br><span>Les fréquences mixtes ne sont pas calibrées sur une occurrence isolée.</span></div>`;
}

'''
    helper_marker = "function actionAnalysisHtml(stepIndex,step){\n"
    if "function heroRangeComplianceForStep(" not in text:
        if text.count(helper_marker) != 1:
            raise SystemExit(f"Hero compliance helper insertion: expected one marker, found {text.count(helper_marker)}")
        text = text.replace(helper_marker, compliance_helpers + helper_marker, 1)

    old_guard = '  if(!isAnyMoneyEvent(step)&&!ctxPostflopCheck(step))return "";\n'
    new_guard = '  const heroPreflopDecision=step?.street==="Préflop"&&step?.activePlayer===state.selectedHand?.heroName&&isAnalyzableDecisionAction(step);\n  if(!isAnyMoneyEvent(step)&&!ctxPostflopCheck(step)&&!heroPreflopDecision)return "";\n'
    text = replace_once(text, old_guard, new_guard, "preflop compliance render guard")

    old_analyzable = '  if(!isAnalyzableDecisionAction(step))return "";\n  const key=actionEquityKey(stepIndex), cached=key?state.actionEquityCache[key]:null, req=requiredEquityInfo(stepIndex);\n'
    new_analyzable = '  if(!isAnalyzableDecisionAction(step))return "";\n  const heroCompliance=heroRangeCompliancePillHtml(stepIndex,step);\n  const key=actionEquityKey(stepIndex), cached=key?state.actionEquityCache[key]:null, req=requiredEquityInfo(stepIndex);\n'
    text = replace_once(text, old_analyzable, new_analyzable, "Hero compliance analysis hook")

    old_no_req = "  if(!req)return `<div class=\"action-analysis na\"><div class=\"action-compact-row\">${actionCompactPillHtml('Verdict —','subtle','primary-summary')}</div></div>`;\n"
    new_no_req = "  if(!req)return `<div class=\"action-analysis na\"><div class=\"action-compact-row\">${actionCompactPillHtml('Verdict —','subtle','primary-summary')}${heroCompliance}</div></div>`;\n"
    text = replace_once(text, old_no_req, new_no_req, "Hero compliance no-EV row")

    old_pending = "  if(!cached||cached.status===\"queued\"||cached.status===\"running\") return `<div class=\"action-analysis pending\"><div class=\"action-analysis-compact\"><div class=\"action-compact-row\">${actionCompactPillHtml('Calcul…','pending','primary-summary')}</div></div></div>`;\n"
    new_pending = "  if(!cached||cached.status===\"queued\"||cached.status===\"running\") return `<div class=\"action-analysis pending\"><div class=\"action-analysis-compact\"><div class=\"action-compact-row\">${actionCompactPillHtml('Calcul…','pending','primary-summary')}${heroCompliance}</div></div></div>`;\n"
    text = replace_once(text, old_pending, new_pending, "Hero compliance pending row")

    old_error = "  if(cached.status===\"error\") return `<div class=\"action-analysis na\"><div class=\"action-analysis-compact\"><div class=\"action-compact-row\">${actionCompactPillHtml('Verdict indispo','bad','primary-summary')}</div></div></div>`;\n"
    new_error = "  if(cached.status===\"error\") return `<div class=\"action-analysis na\"><div class=\"action-analysis-compact\"><div class=\"action-compact-row\">${actionCompactPillHtml('Verdict indispo','bad','primary-summary')}${heroCompliance}</div></div></div>`;\n"
    text = replace_once(text, old_error, new_error, "Hero compliance error row")

    old_final = "  return `<div class=\"action-analysis\"><div class=\"action-analysis-compact\"><div class=\"action-compact-row\">${row.join('')}</div></div></div>`;\n"
    new_final = "  if(heroCompliance)row.push(heroCompliance);\n  return `<div class=\"action-analysis\"><div class=\"action-analysis-compact\"><div class=\"action-compact-row\">${row.join('')}</div></div></div>`;\n"
    text = replace_once(text, old_final, new_final, "Hero compliance final verdict row")

    old_fold_detail = 'function actionDetailModalInnerHtml(stepIndex,step){\n  if(step?.actionType==="fold"&&step.street==="Préflop")return foldRangeAnalysisHtml(stepIndex,null);\n'
    new_fold_detail = 'function actionDetailModalInnerHtml(stepIndex,step){\n  if(step?.actionType==="fold"&&step.street==="Préflop")return heroRangeComplianceDetailHtml(stepIndex,step)+foldRangeAnalysisHtml(stepIndex,null);\n'
    text = replace_once(text, old_fold_detail, new_fold_detail, "Hero compliance preflop fold detail")

    old_detail_return = "  return `${scoreGrid}${chips}\n"
    new_detail_return = "  return `${heroRangeComplianceDetailHtml(stepIndex,step)}${scoreGrid}${chips}\n"
    text = replace_once(text, old_detail_return, new_detail_return, "Hero compliance action detail")

    old_banner = '  ${replayActionBannerHtml(step)}\n  <div class="tiny" style="margin:0 0 10px">${eqCaption}</div>\n'
    new_banner = '  ${replayActionBannerHtml(step)}\n  ${heroRangeComplianceSummaryHtml()}\n  <div class="tiny" style="margin:0 0 10px">${eqCaption}</div>\n'
    text = replace_once(text, old_banner, new_banner, "Hero compliance replay summary")

    INDEX.write_text(text, encoding="utf-8")


def main() -> None:
    patch_repository_contract()
    patch_editor_deep_link()
    patch_index()
    print("Hero range compliance integration patch applied")


if __name__ == "__main__":
    main()
