#!/usr/bin/env python3
"""Trainer preflop analysis-state contract (#393 T5).

The Training preflop surface must derive its user-facing labels from the shared
`poker-analysis-state/v1` module (#393 T2) instead of a local `SPOT_NON_COUVERT`
tag. This contract pins:

- the shared module is loaded before `trainer.js` in `site/index.html`;
- `trainer.js` feeds the canonical preflop decision (coverage/reason codes/
  admissibility/comparability) to `PokerAnalysisState.mapAnalysisState` and
  exposes the canonical taxonomy state as the primary label;
- the raw reason codes only appear in the secondary technical detail
  (`trainerAnalysisDimensionsHtml`), never in the primary recommendation panel;
- the deliberate v1 flop-only Hero-decision boundary (#206) is preserved.

The runtime half below extracts the real helpers from `site/trainer.js` and
proves every transition (available, partial, insufficient, unsupported, running
and worker error) against the shared enum and its label table.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")
TRAINER = (ROOT / "site/trainer.js").read_text(encoding="utf-8")


def section(start: str, end: str) -> str:
    assert start in TRAINER, f"missing trainer section start: {start}"
    body = TRAINER.split(start, 1)[1]
    assert end in body, f"missing trainer section end: {end}"
    return body.split(end, 1)[0]


RUNTIME_BOOTSTRAP = r"""
const fs = require('fs');
const src = fs.readFileSync('site/trainer.js', 'utf8');
const start = src.indexOf('function trainerAnalysisModule(');
const end = src.indexOf('function trainerDetailFromPreflopDecision(');
if (start < 0 || end < 0) throw new Error('trainer analysis helpers missing');
const helpers = src.slice(start, end);
const State = require('./src/analytics/analysis-state.js');
const LABELS = {
  ANALYSE_DISPONIBLE: 'Analyse disponible',
  ANALYSE_PARTIELLE: 'Analyse partielle',
  CALCUL_EN_COURS: 'Calcul en cours',
  DONNEES_INSUFFISANTES: 'Données insuffisantes',
  SPOT_NON_SUPPORTE: 'Spot non supporté',
  ERREUR_CALCUL: 'Erreur de calcul'
};
const window = {
  PokerAnalysisState: State,
  PokerReviewInbox: { analysisStateLabel: state => LABELS[String(state || '').toUpperCase()] || 'Analyse indisponible' }
};
const factory = new Function('window', 'escapeHtml',
  helpers + '\nreturn {trainerPreflopAnalysis,trainerPreflopDecisionView,trainerPreflopTaxonomyLabel,trainerAnalysisDimensionsHtml};');
const api = factory(window, text => String(text));
"""

RUNTIME_CASES = r"""
const cases = [
  ['covered', {coverage_state:'COVERED',reason_codes:[],recommendation_admissibility:{admissible:true,status:'ADMISSIBLE',reason_codes:[]},ev_comparable:true}, 'ANALYSE_DISPONIBLE', true],
  ['partial', {coverage_state:'COVERED',reason_codes:['NON_COMPARABLE_ALTERNATIVES'],recommendation_admissibility:{admissible:true,status:'ADMISSIBLE',reason_codes:[]},ev_comparable:false}, 'ANALYSE_PARTIELLE', false],
  ['low_support', {coverage_state:'LOW_SUPPORT',reason_codes:['LOW_SUPPORT'],recommendation_admissibility:{admissible:false,status:'LOW_SUPPORT',reason_codes:['LOW_SUPPORT']},ev_comparable:false}, 'DONNEES_INSUFFISANTES', false],
  ['unsupported', {coverage_state:'UNSUPPORTED',reason_codes:['SPOT_NON_COUVERT'],recommendation_admissibility:{admissible:false,status:'UNCOVERED',reason_codes:['UNCOVERED']},ev_comparable:false}, 'SPOT_NON_SUPPORTE', false],
  ['scope', {coverage_state:'UNSUPPORTED',reason_codes:['ACTIVE_REFERENCE_SCOPE_UNSUPPORTED'],recommendation_admissibility:{admissible:false,status:'UNCOVERED',reason_codes:['UNCOVERED']},ev_comparable:false}, 'SPOT_NON_SUPPORTE', false],
  ['pending', {coverage_state:'ANALYSIS_MISSING',reason_codes:['CALCULATION_PENDING'],recommendation_admissibility:{admissible:false,status:'NOT_EVALUATED',reason_codes:[]},ev_comparable:false}, 'CALCUL_EN_COURS', false],
  ['error', {coverage_state:'ANALYSIS_MISSING',reason_codes:['WORKER_ERROR'],error:{type:'WORKER_ERROR',retryable:true},recommendation_admissibility:{admissible:false,status:'NOT_EVALUATED',reason_codes:[]},ev_comparable:false}, 'ERREUR_CALCUL', false]
];
const result = {};
for (const [name, decision, expectedState, expectedShowEv] of cases) {
  const view = api.trainerPreflopDecisionView(decision);
  if (view.taxonomy_state !== expectedState) throw new Error(name + ' state ' + view.taxonomy_state + ' != ' + expectedState);
  if (view.taxonomy_label !== LABELS[expectedState]) throw new Error(name + ' label ' + view.taxonomy_label);
  if (view.show_ev !== expectedShowEv) throw new Error(name + ' show_ev ' + view.show_ev);
  result[name] = {state: view.taxonomy_state, label: view.taxonomy_label, show_ev: view.show_ev};
}
const unsupported = api.trainerPreflopDecisionView(cases[3][1]);
const detail = api.trainerAnalysisDimensionsHtml(unsupported.analysis);
if (!detail.includes('SPOT_NON_COUVERT')) throw new Error('secondary detail must expose the reason code');
if (!detail.includes('data-analysis-detail="1"')) throw new Error('secondary detail marker missing');
if (api.trainerPreflopTaxonomyLabel(cases[3][1]) !== 'Spot non supporté') throw new Error('primary label must be taxonomy');
if (api.trainerPreflopTaxonomyLabel(cases[0][1]) !== 'Analyse disponible') throw new Error('covered label must be taxonomy');
// T6: the primary label is always the taxonomy label, never the raw enum code.
if (unsupported.taxonomy_label.toUpperCase() === String(unsupported.taxonomy_state)) throw new Error('primary label must not echo the raw enum code');
console.log(JSON.stringify({status:'PASS', schema: State.SCHEMA, labels: result, detail}));
"""

# #393 T1 (gate `trainerRenderRecommendation` on the canonical `view.show_ev`):
# the rendered primary recommendation panel must expose the recommended action /
# sizing / EV only when D6 is open (`show_ev === true`), and must otherwise stay
# visible with the shared taxonomy label and a precise blocking cause.
RECOMMENDATION_BOOTSTRAP = r"""
const fs = require('fs');
const src = fs.readFileSync('site/trainer.js', 'utf8');
const start = src.indexOf('function trainerAnalysisModule(');
const end = src.indexOf('function trainerRenderFeedback(');
if (start < 0 || end < 0) throw new Error('trainer recommendation helpers missing');
const helpers = src.slice(start, end);
const State = require('./src/analytics/analysis-state.js');
const LABELS = {
  ANALYSE_DISPONIBLE: 'Analyse disponible',
  ANALYSE_PARTIELLE: 'Analyse partielle',
  CALCUL_EN_COURS: 'Calcul en cours',
  DONNEES_INSUFFISANTES: 'Données insuffisantes',
  SPOT_NON_SUPPORTE: 'Spot non supporté',
  ERREUR_CALCUL: 'Erreur de calcul'
};
const element = { className: '', innerHTML: '' };
const trainerState = { hand: {}, mode: 'guided', busy: false, recommendation: null };
const window = {
  PokerAnalysisState: State,
  PokerReviewInbox: { analysisStateLabel: state => LABELS[String(state || '').toUpperCase()] || 'Analyse indisponible' },
  PokerPreflopRuntime: {
    isCovered: d => Boolean(d && d.coverage_state === 'COVERED' && d.recommendation_admissibility && d.recommendation_admissibility.admissible === true)
  }
};
const factory = new Function('window', 'escapeHtml', 'trainerFmtBB', 'trainerRecommendation', 'trainerState',
  helpers + '\nreturn {trainerPreflopDecisionView,trainerPreflopRecommendationCause,trainerRenderRecommendation};');
const api = factory(window, text => String(text), x => String(Number(x).toFixed(2)) + ' BB', element, trainerState);
function render(decision) {
  trainerState.recommendation = { preflopDecision: decision };
  api.trainerRenderRecommendation();
  return { className: element.className, html: element.innerHTML, view: api.trainerPreflopDecisionView(decision) };
}
"""

RECOMMENDATION_CASES = r"""
const cases = {
  admissible_comparable: {
    coverage_state:'COVERED', recommended_action:'CALL', recommended_ev_bb:0.42,
    recommended_target_sizing:{target_total_bb:2.5}, incremental_cost_bb:2.5,
    support:{observations:2000}, played_action:'CALL', ev_comparable:true,
    recommendation_admissibility:{admissible:true,status:'ADMISSIBLE',reason_codes:[]}, reason_codes:[]
  },
  // Covered + admissible but no comparable played EV: `covered` alone must never
  // be enough to expose the recommendation (D6 fail-closed).
  covered_not_comparable: {
    coverage_state:'COVERED', recommended_action:'3BET', recommended_ev_bb:1.6,
    recommended_target_sizing:{target_total_bb:8}, incremental_cost_bb:8,
    support:{observations:150}, ev_comparable:false,
    recommendation_admissibility:{admissible:true,status:'ADMISSIBLE',reason_codes:[]},
    reason_codes:['NON_COMPARABLE_ALTERNATIVES']
  },
  node_absent: { coverage_state:'UNSUPPORTED', reason_codes:['SPOT_NON_COUVERT'], recommendation_admissibility:{admissible:false,status:'UNCOVERED',reason_codes:['UNCOVERED']}, ev_comparable:false },
  context_unsupported: { coverage_state:'UNSUPPORTED', reason_codes:['ACTIVE_REFERENCE_SCOPE_UNSUPPORTED'], recommendation_admissibility:{admissible:false,status:'UNCOVERED',reason_codes:['UNCOVERED']}, ev_comparable:false },
  low_support: { coverage_state:'LOW_SUPPORT', reason_codes:['LOW_SUPPORT'], recommendation_admissibility:{admissible:false,status:'LOW_SUPPORT',reason_codes:['LOW_SUPPORT']}, ev_comparable:false },
  pending: { coverage_state:'ANALYSIS_MISSING', reason_codes:['CALCULATION_PENDING'], recommendation_admissibility:{admissible:false,status:'NOT_EVALUATED',reason_codes:[]}, ev_comparable:false },
  error: { coverage_state:'ANALYSIS_MISSING', reason_codes:['WORKER_ERROR'], error:{type:'WORKER_ERROR',retryable:true}, recommendation_admissibility:{admissible:false,status:'NOT_EVALUATED',reason_codes:[]}, ev_comparable:false },
  inadmissible: { coverage_state:'COVERED', reason_codes:['NO_ADMISSIBLE_STRATEGY'], recommendation_admissibility:{admissible:false,status:'NO_ADMISSIBLE_STRATEGY',reason_codes:['NO_ADMISSIBLE_STRATEGY']}, ev_comparable:false }
};
const rendered = {};
for (const [name, decision] of Object.entries(cases)) rendered[name] = render(decision);
const RECOMMENDED_FIELDS = ['recommended_action','recommended_ev_bb','incremental_cost_bb'];
for (const [name, decision] of Object.entries(cases)) {
  const row = rendered[name];
  if (row.view.show_ev) {
    if (!row.html.includes('Action recommandée') || !row.html.includes(String(decision.recommended_action))) throw new Error(name + ' must expose the recommendation');
  } else {
    if (row.className.includes('hidden-answer')) throw new Error(name + ' panel must stay visible');
    for (const field of RECOMMENDED_FIELDS) if (row.html.includes(field)) throw new Error(name + ' leaked field ' + field);
    if (row.html.includes(String(decision.recommended_action))) throw new Error(name + ' leaked recommended action');
    if (decision.recommended_ev_bb != null && row.html.includes(Number(decision.recommended_ev_bb).toFixed(2))) throw new Error(name + ' leaked recommended EV');
    if (decision.incremental_cost_bb != null && row.html.includes(Number(decision.incremental_cost_bb).toFixed(2))) throw new Error(name + ' leaked incremental cost');
    if (!row.html.includes(LABELS[row.view.taxonomy_state])) throw new Error(name + ' must render the taxonomy label');
  }
}
// Each fail-closed cause is precise and rendered: distinct causes are never
// collapsed into one generic "aucune recommandation" sentence.
const EXPECTED_CAUSES = {
  node_absent:'Absence de node', context_unsupported:'Contexte non supporté',
  low_support:'Support insuffisant', pending:'Calcul en cours',
  error:'Erreur worker', inadmissible:'Recommandation non admise',
  covered_not_comparable:'Analyse partielle'
};
for (const [name, phrase] of Object.entries(EXPECTED_CAUSES)) {
  if (rendered[name].view.show_ev) throw new Error(name + ' must be a fail-closed case');
  const cause = api.trainerPreflopRecommendationCause(rendered[name].view);
  if (!cause.toLowerCase().includes(phrase.toLowerCase())) throw new Error(name + ' cause ' + cause);
  if (!rendered[name].html.includes(cause)) throw new Error(name + ' rendered panel must contain the precise cause');
}
console.log(JSON.stringify({status:'PASS', rendered:Object.fromEntries(Object.entries(rendered).map(([k,v])=>[k,{show_ev:v.view.show_ev,state:v.view.taxonomy_state,className:v.className}]))}));
"""

# #393 T3 (`trainerDetailFromPreflopDecision`): the detail object must expose a
# usable bestLabel/bestEV/recommended-sizing and a non-zero ΔEV only when the
# canonical D6 gate (`view.show_ev`) is open. Case D (admissible && comparable)
# is preserved, Case A (admissible, not comparable) and Case B (not admissible)
# fail closed on the shared taxonomy label.
DETAIL_BOOTSTRAP = r"""
const fs = require('fs');
const src = fs.readFileSync('site/trainer.js', 'utf8');
const start = src.indexOf('function trainerAnalysisModule(');
const end = src.indexOf('async function trainerComputePreflopReference(');
if (start < 0 || end < 0) throw new Error('trainer detail helpers missing');
const helpers = src.slice(start, end);
const State = require('./src/analytics/analysis-state.js');
const LABELS = {
  ANALYSE_DISPONIBLE: 'Analyse disponible',
  ANALYSE_PARTIELLE: 'Analyse partielle',
  CALCUL_EN_COURS: 'Calcul en cours',
  DONNEES_INSUFFISANTES: 'Données insuffisantes',
  SPOT_NON_SUPPORTE: 'Spot non supporté',
  ERREUR_CALCUL: 'Erreur de calcul'
};
const window = {
  PokerAnalysisState: State,
  PokerReviewInbox: { analysisStateLabel: state => LABELS[String(state || '').toUpperCase()] || 'Analyse indisponible' }
};
const factory = new Function('window', helpers + '\nreturn {trainerPreflopDecisionView,trainerDetailFromPreflopDecision};');
const api = factory(window);
"""

DETAIL_CASES = r"""
const base = { schema:'poker-preflop-decision/v1', coverage_state:'COVERED', played_action:'CALL' };
// Case D: admissible && comparable -> the full recommendation evidence survives.
const caseD = api.trainerDetailFromPreflopDecision({
  ...base, recommended_action:'CALL', recommended_ev_bb:0.42, played_ev_bb:0.30,
  incremental_cost_bb:2.5, reason_codes:[],
  recommendation_admissibility:{admissible:true,status:'ADMISSIBLE',reason_codes:[]}, ev_comparable:true
});
if (caseD.showEV !== true || caseD.bestLabel !== 'CALL') throw new Error('case D label ' + JSON.stringify(caseD));
if (caseD.bestEV !== 0.42 || caseD.chosenEV !== 0.30) throw new Error('case D EV ' + JSON.stringify(caseD));
if (caseD.bestCostBB !== 2.5) throw new Error('case D sizing ' + JSON.stringify(caseD));
if (Math.abs(caseD.lossBB - 0.12) > 1e-9 || Math.abs(caseD.rawLossBB - 0.12) > 1e-9) throw new Error('case D loss ' + JSON.stringify(caseD));
// Case A: admissible but not comparable -> no usable recommendation payload.
const caseA = api.trainerDetailFromPreflopDecision({
  ...base, recommended_action:'3BET', recommended_ev_bb:1.6, incremental_cost_bb:8,
  reason_codes:['NON_COMPARABLE_ALTERNATIVES'],
  recommendation_admissibility:{admissible:true,status:'ADMISSIBLE',reason_codes:[]}, ev_comparable:false
});
if (caseA.showEV !== false) throw new Error('case A showEV');
if (caseA.bestLabel !== LABELS.ANALYSE_PARTIELLE || caseA.bestLabel.includes('3BET')) throw new Error('case A label ' + caseA.bestLabel);
if (Number.isFinite(caseA.bestEV) || Number.isFinite(caseA.chosenEV)) throw new Error('case A EV ' + JSON.stringify(caseA));
if (caseA.bestCostBB !== null) throw new Error('case A sizing ' + JSON.stringify(caseA));
if (caseA.lossBB !== 0 || caseA.rawLossBB !== 0) throw new Error('case A loss ' + JSON.stringify(caseA));
// Case B: not admissible -> no recommendation payload, taxonomy label only.
const caseB = api.trainerDetailFromPreflopDecision({
  ...base, coverage_state:'UNSUPPORTED', recommended_action:null, recommended_ev_bb:null,
  reason_codes:['SPOT_NON_COUVERT'],
  recommendation_admissibility:{admissible:false,status:'UNCOVERED',reason_codes:['UNCOVERED']}, ev_comparable:false
});
if (caseB.showEV !== false) throw new Error('case B showEV');
if (caseB.bestLabel !== LABELS.SPOT_NON_SUPPORTE) throw new Error('case B label ' + caseB.bestLabel);
if (Number.isFinite(caseB.bestEV) || Number.isFinite(caseB.chosenEV)) throw new Error('case B EV');
if (caseB.bestCostBB !== null || caseB.lossBB !== 0) throw new Error('case B sizing/loss');
console.log(JSON.stringify({status:'PASS',
  D:{show:caseD.showEV,label:caseD.bestLabel,ev:caseD.bestEV,cost:caseD.bestCostBB,loss:caseD.lossBB},
  A:{show:caseA.showEV,label:caseA.bestLabel,ev:caseA.bestEV,cost:caseA.bestCostBB,loss:caseA.lossBB},
  B:{show:caseB.showEV,label:caseB.bestLabel,ev:caseB.bestEV,cost:caseB.bestCostBB,loss:caseB.lossBB}}));
"""

# #393 T3 (recorded row/log): the persisted Trainer row must not carry a Hero
# recommendation payload (label, sizing, best/chosen EV) when D6 is closed, and
# must keep the canonical flags for the open Case D.
RECORD_BOOTSTRAP = r"""
const fs = require('fs');
const src = fs.readFileSync('site/trainer.js', 'utf8');
const helpers = src.slice(src.indexOf('function trainerAnalysisModule('), src.indexOf('function trainerDetailFromPreflopDecision('));
const record = src.slice(src.indexOf('function trainerDecisionClass('), src.indexOf('function trainerDecisionCanonical('));
const State = require('./src/analytics/analysis-state.js');
const LABELS = {
  ANALYSE_DISPONIBLE: 'Analyse disponible',
  ANALYSE_PARTIELLE: 'Analyse partielle',
  CALCUL_EN_COURS: 'Calcul en cours',
  DONNEES_INSUFFISANTES: 'Données insuffisantes',
  SPOT_NON_SUPPORTE: 'Spot non supporté',
  ERREUR_CALCUL: 'Erreur de calcul'
};
const window = {
  PokerAnalysisState: State,
  PokerReviewInbox: { analysisStateLabel: state => LABELS[String(state || '').toUpperCase()] || 'Analyse indisponible' }
};
const trainerState = { hand: { street: 'preflop', positions: ['BTN'], heroSeat: 0 }, handNo: 1, session: { decisions: 0, lossBB: 0, good: 0, close: 0, poor: 0, breakdown: {} }, testLog: [] };
const TrainerActionSizingEV = { qualityFromEV: () => ({ key: 'good' }) };
const factory = new Function('window', 'trainerState', 'TrainerActionSizingEV', helpers + record + '\nreturn {trainerRecordDecision};');
const api = factory(window, trainerState, TrainerActionSizingEV);
"""

RECORD_CASES = r"""
const gated = {
  preflopDecision: {
    coverage_state:'COVERED', recommended_action:'3BET', recommended_ev_bb:1.6, incremental_cost_bb:8,
    ev_comparable:false, reason_codes:['NON_COMPARABLE_ALTERNATIVES'],
    recommendation_admissibility:{admissible:true,status:'ADMISSIBLE',reason_codes:[]}
  },
  bestLabel:'3BET', bestCostBB:8, bestEV:1.6, chosenEV:0.2, lossBB:0, taxonomy_state:'ANALYSE_PARTIELLE',
  analysis:{reason_codes:['NON_COMPARABLE_ALTERNATIVES']}
};
const rowGated = api.trainerRecordDecision(gated, 'CALL', 2.5);
if (rowGated.bestLabel !== '—') throw new Error('gated row label ' + rowGated.bestLabel);
if (rowGated.bestCostBB !== null) throw new Error('gated row sizing ' + rowGated.bestCostBB);
if (Number.isFinite(rowGated.bestEV) || Number.isFinite(rowGated.chosenEV)) throw new Error('gated row EV ' + JSON.stringify(rowGated));
if (rowGated.comparable !== false || rowGated.covered !== true) throw new Error('gated row flags');
const open = {
  preflopDecision: {
    coverage_state:'COVERED', recommended_action:'CALL', recommended_ev_bb:0.42, played_ev_bb:0.3,
    incremental_cost_bb:2.5, ev_comparable:true, reason_codes:[],
    recommendation_admissibility:{admissible:true,status:'ADMISSIBLE',reason_codes:[]}
  },
  bestLabel:'CALL', bestCostBB:2.5, bestEV:0.42, chosenEV:0.3, lossBB:0, taxonomy_state:'ANALYSE_DISPONIBLE',
  analysis:{reason_codes:[]}
};
const rowOpen = api.trainerRecordDecision(open, 'CALL', 2.5);
if (rowOpen.bestLabel !== 'CALL' || rowOpen.bestCostBB !== 2.5 || rowOpen.bestEV !== 0.42 || rowOpen.chosenEV !== 0.3) throw new Error('open row ' + JSON.stringify(rowOpen));
if (rowOpen.covered !== true || rowOpen.comparable !== true) throw new Error('open row flags');
console.log(JSON.stringify({status:'PASS',
  gated:{label:rowGated.bestLabel,cost:rowGated.bestCostBB,bestEV:rowGated.bestEV,chosenEV:rowGated.chosenEV,comparable:rowGated.comparable,covered:rowGated.covered},
  open:{label:rowOpen.bestLabel,cost:rowOpen.bestCostBB,bestEV:rowOpen.bestEV,covered:rowOpen.covered}}));
"""


def main() -> None:
    # 1. The shared module is loaded before the Trainer.
    module_tag = '<script src="./analytics/analysis-state.js"></script>'
    assert module_tag in INDEX
    assert INDEX.index(module_tag) < INDEX.index('<script src="./trainer.js"></script>')

    helpers = section("function trainerAnalysisModule(", "function trainerDetailFromPreflopDecision(")
    rec = section("function trainerRenderRecommendation(", "function trainerRenderFeedback(")
    feedback = section("function trainerRenderFeedback(", "function trainerSizingValue(")

    # 2. The canonical preflop decision feeds the shared module untouched.
    assert "window.PokerAnalysisState" in helpers
    assert "Module.mapAnalysisState(decision)" in helpers
    assert "function trainerPreflopAnalysis(decision){" in helpers
    assert "function trainerPreflopDecisionView(decision){" in helpers
    assert "taxonomy_state:analysis?.state||null" in helpers
    assert "taxonomy_label:trainerTaxonomyLabel(analysis?.state||\"\")" in helpers
    # D6: EV/recommendation only when admissible AND comparable.
    assert "show_ev:admissible&&comparable" in helpers
    assert "admissible,ev_comparable:comparable" in helpers

    # 3. Primary labels are the taxonomy state; the raw reason codes stay in the
    #    secondary technical detail only.
    assert "trainerPreflopTaxonomyLabel(detail.preflopDecision)" in TRAINER
    assert "trainerPreflopTaxonomyLabel(d)" in rec
    assert "trainerPreflopTaxonomyLabel(d.preflopDecision)" in feedback
    assert "escapeHtml(trainerPreflopTaxonomyLabel(d))" in rec
    assert "view.taxonomy_label" in TRAINER
    # Rule D6: `trainerDetailFromPreflopDecision` populates the
    # recommendation-oriented fields only when the canonical gate
    # (`view.show_ev`) is open; otherwise bestEV/played EV are NaN, the
    # recommended sizing is null and bestLabel degrades to the taxonomy label.
    assert "bestLabel:view.show_ev?String(decision.recommended_action||\"—\"):(view.taxonomy_label" in TRAINER
    assert "bestCostBB:view.show_ev&&Number.isFinite(Number(decision.incremental_cost_bb))" in TRAINER
    assert "bestEV:view.show_ev&&Number.isFinite(bestEV)?bestEV:NaN" in TRAINER
    assert "chosenEV:view.show_ev&&Number.isFinite(playedEV)?playedEV:NaN" in TRAINER
    # One source of truth: no legacy covered-only gate remains in the Trainer.
    assert "isCovered" not in TRAINER, "legacy isCovered gating must not remain in site/trainer.js"
    assert "trainerAnalysisDimensionsHtml(view.analysis)" in TRAINER
    assert "analysis.reason_codes" in helpers
    assert 'data-analysis-detail="1"' in helpers
    # The primary recommendation panel never exposes raw reason codes.
    assert "reason_codes" not in rec, "reason codes must not leak into the primary recommendation panel"
    # The technical dimensions are only rendered through the helper, reached
    # from the secondary feedback summary.
    assert "trainerPreflopDecisionSummaryHtml(d.preflopDecision)" in feedback
    summary = section("function trainerPreflopDecisionSummaryHtml(", "function trainerBestText(")
    assert "trainerAnalysisDimensionsHtml(view.analysis)" in summary
    assert "const technical=trainerAnalysisDimensionsHtml(view.analysis);" in summary

    # T6: the persisted Trainer decision record keeps the canonical taxonomy
    # state as its primary label and only carries the machine-readable reason
    # codes in a dedicated secondary field. The user-facing label never echoes
    # the raw enum code when the shared label table is available.
    assert "analysis_state:detail?.taxonomy_state||null" in TRAINER
    assert "analysis_reason_codes:Array.isArray(detail?.analysis?.reason_codes)" in TRAINER
    assert "ANALYSIS_STATE_LABELS" in helpers
    assert 'return String(state||"")' not in helpers

    # 4a. `trainerRenderRecommendation` is gated on the canonical `view.show_ev`
    #     (D6). `covered` alone is never sufficient to expose the recommended
    #     action / sizing / EV, and the fail-closed panel stays visible.
    assert "function trainerPreflopRecommendationCause(view){" in TRAINER
    cause = section("function trainerPreflopRecommendationCause(", "function trainerRenderRecommendation(")
    assert "const view=trainerPreflopDecisionView(d);" in rec
    assert "if(view.show_ev){" in rec
    assert "isCovered" not in rec, "covered alone must not gate the recommendation panel"
    # The precise causes are distinct and never a raw reason code.
    for phrase in (
        "Erreur worker",
        "Calcul en cours",
        "Contexte non supporté",
        "Absence de node",
        "Support insuffisant",
        "Recommandation non admise",
        "Analyse partielle",
    ):
        assert phrase in cause, phrase
    assert "reason_codes" not in cause, "the primary cause must not read raw reason codes"

    # 4b. The deliberate v1 flop-only Hero-decision boundary (#206) is preserved.
    assert "Hero training decisions begin on the flop" in TRAINER
    assert "#206" in TRAINER

    # 5. Runtime proof against the shared enum and its label table.
    script = RUNTIME_BOOTSTRAP + RUNTIME_CASES
    proc = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["status"] == "PASS", payload
    assert payload["schema"] == "poker-analysis-state/v1", payload
    expected = {
        "covered": "ANALYSE_DISPONIBLE",
        "partial": "ANALYSE_PARTIELLE",
        "low_support": "DONNEES_INSUFFISANTES",
        "unsupported": "SPOT_NON_SUPPORTE",
        "scope": "SPOT_NON_SUPPORTE",
        "pending": "CALCUL_EN_COURS",
        "error": "ERREUR_CALCUL",
    }
    for name, state in expected.items():
        assert payload["labels"][name]["state"] == state, payload
    assert payload["labels"]["unsupported"]["label"] == "Spot non supporté", payload

    # 6. Runtime proof of the D6 gate on the rendered `#trainerRecommendation`
    #    panel: exact recommendation fields only when `show_ev`, precise cause
    #    otherwise, never a raw reason code in the primary panel.
    script = RECOMMENDATION_BOOTSTRAP + RECOMMENDATION_CASES
    proc = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["status"] == "PASS", payload
    assert payload["rendered"]["admissible_comparable"]["show_ev"] is True, payload
    assert payload["rendered"]["covered_not_comparable"]["show_ev"] is False, payload
    assert payload["rendered"]["covered_not_comparable"]["state"] == "ANALYSE_PARTIELLE", payload
    for name in ("node_absent", "context_unsupported", "low_support", "pending", "error", "inadmissible", "covered_not_comparable"):
        assert payload["rendered"][name]["className"] == "trainer-recommendation", payload

    # 7. Runtime proof that `trainerDetailFromPreflopDecision` carries no usable
    #    Hero recommendation when D6 is closed (Cases A/B) and preserves Case D.
    script = DETAIL_BOOTSTRAP + DETAIL_CASES
    proc = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["status"] == "PASS", payload
    assert payload["D"]["show"] is True and payload["D"]["label"] == "CALL", payload
    assert payload["D"]["cost"] == 2.5 and abs(payload["D"]["loss"] - 0.12) < 1e-9, payload
    assert payload["A"]["show"] is False and payload["A"]["label"] == "Analyse partielle", payload
    assert payload["A"]["ev"] is None, payload  # NaN serialized: EV unavailable
    assert payload["A"]["cost"] is None and payload["A"]["loss"] == 0, payload
    assert payload["B"]["show"] is False and payload["B"]["label"] == "Spot non supporté", payload
    assert payload["B"]["ev"] is None and payload["B"]["cost"] is None, payload

    # 8. Runtime proof that the recorded row/log carries no Hero recommendation
    #    payload while D6 is closed, and keeps Case D fields.
    script = RECORD_BOOTSTRAP + RECORD_CASES
    proc = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["status"] == "PASS", payload
    assert payload["gated"]["label"] == "—" and payload["gated"]["cost"] is None, payload
    assert payload["gated"]["bestEV"] is None and payload["gated"]["chosenEV"] is None, payload
    assert payload["gated"]["comparable"] is False and payload["gated"]["covered"] is True, payload
    assert payload["open"]["label"] == "CALL" and payload["open"]["cost"] == 2.5, payload
    assert payload["open"]["bestEV"] == 0.42 and payload["open"]["covered"] is True, payload

    print("trainer analysis-state contract: PASS")


if __name__ == "__main__":
    main()
