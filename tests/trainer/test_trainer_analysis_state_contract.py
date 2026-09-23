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
    assert "bestLabel:covered?String(decision.recommended_action||\"—\"):(view.taxonomy_label" in TRAINER
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

    # 4. The deliberate v1 flop-only Hero-decision boundary (#206) is preserved.
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

    print("trainer analysis-state contract: PASS")


if __name__ == "__main__":
    main()
