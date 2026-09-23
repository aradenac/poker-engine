#!/usr/bin/env python3
"""Cross-surface analysis-state consistency contract (#393 T1, DoD lock).

This is the final "definition of done" lock for the shared
`poker-analysis-state/v1` taxonomy. It proves that the five migrated surfaces

    Review — Inbox        (src/analytics/review-inbox.js + site mirror)
    Review — Dashboard    (src/analytics/review-dashboard.js + site mirror)
    Replayer — Hero       (site/index.html)
    Replayer — adverse    (site/index.html)
    Training              (site/trainer.js)

all derive their user-facing state from the same six-state enum shipped by
`src/analytics/analysis-state.js` (byte-identical to
`site/analytics/analysis-state.js`) and from the same six-entry label table
exposed by the shared review layer (`ANALYSIS_STATE_LABELS`). The label table is
locked independently here so a surface can never introduce a divergent or
generic label.

It locks three things the earlier per-surface contracts do not:

1. An explicit legacy Hero/Villain ``reason_code -> one of the six states``
   table. Every listed code must be a member of the exported ``REASON_CODE_MAP``
   (so the mapping is explicit and never a silent generic fallback) and resolve
   to exactly one canonical state, through the module and through the Hero and
   Training surfaces.
2. A DoD guard that fails when a surface emits a generic
   "aucune analyse/recommandation disponible" message while a more precise
   reason code exists. The guard itself is self-tested, so it provably rejects a
   deliberately generic surface.
3. The D6 (Hero EV only when admissibility AND comparability are explicitly
   true) and D5 (no adverse EV, observed action + support + range before/after)
   invariants at the shared-module, surface and rendered-output levels.

The runtime half extracts the real functions from ``site/index.html`` and
``site/trainer.js`` and drives them with the real shared module; it never edits
the mapper or the surfaces.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

STATE_SRC = ROOT / "src/analytics/analysis-state.js"
STATE_SITE = ROOT / "site/analytics/analysis-state.js"
INBOX_SRC = ROOT / "src/analytics/review-inbox.js"
INBOX_SITE = ROOT / "site/analytics/review-inbox.js"
DASH_SRC = ROOT / "src/analytics/review-dashboard.js"
DASH_SITE = ROOT / "site/analytics/review-dashboard.js"
INDEX = ROOT / "site/index.html"
TRAINER = ROOT / "site/trainer.js"

# The canonical six-state label table. It is asserted against the shared table
# and every surface, so a divergent or generic label fails here.
EXPECTED_LABELS = {
    "ANALYSE_DISPONIBLE": "Analyse disponible",
    "ANALYSE_PARTIELLE": "Analyse partielle",
    "CALCUL_EN_COURS": "Calcul en cours",
    "DONNEES_INSUFFISANTES": "Données insuffisantes",
    "SPOT_NON_SUPPORTE": "Spot non supporté",
    "ERREUR_CALCUL": "Erreur de calcul",
}

SURFACES = [
    "review-inbox",
    "review-dashboard",
    "replayer-hero",
    "replayer-adverse",
    "training",
]


# The runtime harness runs with `node -e` from the repository root, so it loads
# the real shared module and the real review modules, then extracts the real
# Replayer (index.html) and Training (trainer.js) functions.
NODE_CONTRACT = r"""
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = process.cwd();
const State = require('./src/analytics/analysis-state.js');
const Inbox = require('./src/analytics/review-inbox.js');
const Dashboard = require('./src/analytics/review-dashboard.js');
const INDEX = fs.readFileSync(path.join(ROOT, 'site/index.html'), 'utf8');
const TRAINER = fs.readFileSync(path.join(ROOT, 'site/trainer.js'), 'utf8');

function section(src, start, end) {
  const i = src.indexOf(start);
  assert.ok(i >= 0, 'section start not found: ' + start);
  const j = src.indexOf(end, i + start.length);
  assert.ok(j >= 0, 'section end not found: ' + end);
  return src.slice(i, j);
}

const EXPECTED_STATES = ['ANALYSE_DISPONIBLE', 'ANALYSE_PARTIELLE', 'CALCUL_EN_COURS', 'DONNEES_INSUFFISANTES', 'SPOT_NON_SUPPORTE', 'ERREUR_CALCUL'];
const EXPECTED_LABELS = {
  ANALYSE_DISPONIBLE: 'Analyse disponible',
  ANALYSE_PARTIELLE: 'Analyse partielle',
  CALCUL_EN_COURS: 'Calcul en cours',
  DONNEES_INSUFFISANTES: 'Données insuffisantes',
  SPOT_NON_SUPPORTE: 'Spot non supporté',
  ERREUR_CALCUL: 'Erreur de calcul',
};
// Generic user-facing messages that must never replace a precise reason code.
const GENERIC_MESSAGES = ['Aucune analyse disponible', 'Aucune recommandation disponible', 'Analyse indisponible'];

// The DoD guard: emit a generic "no analysis/recommendation available" message
// only when no more precise cause exists. `precise` names the precise reason
// code/status that is being rendered, so any generic message in that context
// fails the contract.
function genericGuard(surface, render, precise) {
  const label = String(render() || '');
  for (const generic of GENERIC_MESSAGES) {
    assert.ok(!label.toLowerCase().includes(generic.toLowerCase()),
      surface + ': generic "' + generic + '" must not be emitted while precise cause "' + precise + '" exists');
  }
  return label;
}

// ---------------------------------------------------------------------------
// 1. One enum + one label table for every surface.
// ---------------------------------------------------------------------------
assert.deepEqual(Object.keys(State.ANALYSIS_STATES).sort(), EXPECTED_STATES.slice().sort());
assert.deepEqual(State.ANALYSIS_STATES, Object.fromEntries(EXPECTED_STATES.map((s) => [s, s])));
assert.deepEqual(Inbox.ANALYSIS_STATE_LABELS, EXPECTED_LABELS);
assert.deepEqual(Object.keys(Inbox.ANALYSIS_STATE_LABELS).sort(), EXPECTED_STATES.slice().sort());
assert.equal(typeof Inbox.analysisStateLabel, 'function');
assert.equal(typeof Dashboard.analysisStateLabel, 'function');

// Self-test: the guard must reject a deliberately generic surface, otherwise a
// regression to a generic message would slip through the contract.
assert.throws(() => genericGuard('self-test', () => 'Aucune analyse disponible', 'LOW_SUPPORT'), /generic/i);
assert.throws(() => genericGuard('self-test', () => 'Aucune recommandation disponible', 'NODE_ABSENT'), /generic/i);

for (const state of EXPECTED_STATES) {
  assert.equal(Inbox.analysisStateLabel(state), EXPECTED_LABELS[state]);
  assert.equal(Dashboard.analysisStateLabel(state), EXPECTED_LABELS[state]);
  genericGuard('Review Inbox', () => Inbox.analysisStateLabel(state), state);
  genericGuard('Review Dashboard', () => Dashboard.analysisStateLabel(state), state);
}

// ---------------------------------------------------------------------------
// 2. Extract the real Replayer + Training surface functions.
// ---------------------------------------------------------------------------
const heroHelpers = section(INDEX, 'const HERO_ACTOR_ANALYSIS_INPUT=', 'function preflopDecisionCompactHtml(');
const replayerBody = section(INDEX, 'function preflopDecisionCompactHtml(', 'function heroCommentView(');
const heroViews = section(INDEX, 'function heroCommentView(', 'function replayOpponentCommentHtml(');
const opponentHtml = section(INDEX, 'function replayOpponentCommentHtml(', 'function actionDetailKeyPointsHtml(');
const replayerSource = [
  heroHelpers, replayerBody, heroViews, opponentHtml,
  'return {HERO_ACTOR_ANALYSIS_INPUT,OPPONENT_ACTOR_ANALYSIS_INPUT,heroTaxonomyLabel,heroAnalysisStateFromActor,heroAnalysisStateFromDecision,heroDecisionView,heroAnalysisDimensionsHtml,preflopDecisionCompactHtml,preflopDecisionDetailHtml,opponentCommentAnalysisState,opponentCommentView,replayOpponentCommentStateFromEvidence,replayOpponentCommentState,replayOpponentCommentHtml,heroCommentView,replayHeroCommentState};',
].join('\n');

const EVIDENCE = { phase: 'PREFLOP', decision: { action: 'RAISE', family: 'VS_LIMPERS', preflop_context_v1: { schema: 'poker-preflop-context/v1', family: 'VS_LIMPERS' } } };
const windowObject = { PokerAnalysisState: State, PokerReviewInbox: Inbox, PokerPreflopContract: { SCHEMA: 'poker-preflop-context/v1' } };
const replayer = new Function(
  'window', 'escapeHtml', 'formatBB', 'actionCompactPillHtml', 'preflopDecisionSizingText', 'finalDecisionEV',
  'replayObservedDecisionEvidence', 'currentHandPlayer', 'populationRangeEstimateForPlayer', 'findClosestPopulationNode', 'findClosestPostflopNode',
  replayerSource
)(
  windowObject,
  (v) => String(v),
  (v) => Number(v).toFixed(2) + ' BB',
  (text, cls, name) => '<pill class="' + cls + '" data-name="' + name + '">' + text + '</pill>',
  () => 'total 0',
  (a) => Number(a && a.evBB),
  () => EVIDENCE,
  () => ({ name: 'BB', hhPosition: 'BB' }),
  (p, idx) => ({ posteriorState: idx === 0 ? 'prior_uninformative' : 'conditioned' }),
  () => ({ quality: 'exact', node: { coverage: { population_decisions: 37 }, context: { family: 'VS_LIMPERS' } } }),
  () => null
);

const trainerHelpers = section(TRAINER, 'function trainerAnalysisModule(', 'function trainerDetailFromPreflopDecision(');
const trainer = new Function(
  'window', 'escapeHtml',
  trainerHelpers + '\nreturn {trainerAnalysisModule,trainerTaxonomyLabel,trainerPreflopAnalysis,trainerPreflopDecisionView,trainerAnalysisDimensionsHtml,trainerPreflopTaxonomyLabel};'
)(windowObject, (v) => String(v));

assert.equal(typeof replayer.heroTaxonomyLabel, 'function');
assert.equal(typeof replayer.opponentCommentView, 'function');
assert.equal(typeof trainer.trainerTaxonomyLabel, 'function');
// The five migrated surfaces, enumerated explicitly: each one must resolve the
// same six-state enum through the same shared label table.
const SURFACES = {
  'review-inbox': (s) => Inbox.analysisStateLabel(s),
  'review-dashboard': (s) => Dashboard.analysisStateLabel(s),
  'replayer-hero': (s) => replayer.heroTaxonomyLabel(s),
  'replayer-adverse': (s) => replayer.heroTaxonomyLabel(s),
  training: (s) => trainer.trainerTaxonomyLabel(s),
};
for (const [name, label] of Object.entries(SURFACES)) {
  for (const state of EXPECTED_STATES) {
    assert.equal(label(state), EXPECTED_LABELS[state], name + ' label ' + state);
    genericGuard(name, () => label(state), state);
  }
}

// ---------------------------------------------------------------------------
// 3. Explicit legacy Hero/Villain reason_code -> one canonical state.
// ---------------------------------------------------------------------------
const MAPPING = {
  CALCUL_EN_COURS: ['CALCULATION_PENDING', 'ANALYSIS_PENDING', 'UNFINISHED_DECISIONS'],
  ERREUR_CALCUL: ['WORKER_ERROR', 'ANALYSIS_ERROR'],
  SPOT_NON_SUPPORTE: ['UNSUPPORTED', 'SPOT_NON_COUVERT', 'CONTEXT_UNSUPPORTED', 'EXACT_CONTEXT_MISMATCH', 'ACTIVE_REFERENCE_SCOPE_UNSUPPORTED', 'UNCOVERED', 'NODE_ABSENT', 'EXACT_CONTEXT_ABSENT'],
  DONNEES_INSUFFISANTES: ['LOW_SUPPORT', 'INSUFFICIENT_SUPPORT', 'MISSING_HH_SOURCE', 'MISSING_REVIEW_SCORE', 'NO_DECISION_EVENTS', 'REVIEW_SCORE_INCOMPLETE', 'NO_HANDS'],
  ANALYSE_PARTIELLE: ['NON_COMPARABLE', 'NON_COMPARABLE_ALTERNATIVES', 'NON_COMPARABLE_DECISIONS', 'MISSING_COMPARABLE_EV', 'NO_COMPARABLE_REVIEW_DETAIL', 'PARTIAL_ANALYSIS', 'ANALYSIS_INCOMPLETE', 'PLAYED_ALTERNATIVE_NOT_EVALUATED', 'RECOMMENDATION_NOT_ADMISSIBLE', 'INVALID_GUIDANCE', 'NO_ADMISSIBLE_STRATEGY'],
  ANALYSE_DISPONIBLE: ['NO_SIGNIFICANT_LOSS', 'READY'],
};
const mapped = {};
for (const [state, codes] of Object.entries(MAPPING)) {
  for (const code of codes) {
    // Explicit membership proves the mapping is not a silent generic fallback.
    assert.ok(Object.prototype.hasOwnProperty.call(State.REASON_CODE_MAP, code), code + ' must be explicitly mapped');
    assert.equal(State.REASON_CODE_MAP[code], state, 'REASON_CODE_MAP[' + code + ']');
    const r = State.mapAnalysisState({ reason_codes: [code] });
    assert.equal(r.state, state, 'module ' + code);
    assert.ok(r.reason_codes.includes(code), code + ' must be preserved');
    // The Hero surface derives the same state from the same code...
    const hero = replayer.heroAnalysisStateFromActor('HERO_RECOMMENDATION_UNAVAILABLE', { reasonCodes: [code] });
    assert.equal(hero.state, state, 'hero ' + code);
    assert.equal(replayer.heroTaxonomyLabel(hero.state), EXPECTED_LABELS[state]);
    genericGuard('Replayer Hero', () => replayer.heroTaxonomyLabel(hero.state), code);
    // ... and so does the Training surface, through the shared label table.
    const view = trainer.trainerPreflopDecisionView({ reason_codes: [code] });
    assert.equal(view.taxonomy_state, state, 'trainer ' + code);
    assert.equal(view.taxonomy_label, EXPECTED_LABELS[state]);
    genericGuard('Training', () => view.taxonomy_label, code);
    mapped[code] = state;
  }
}
// COVERED is a coverage status (never a top-level reason) and resolves to
// ANALYSE_DISPONIBLE only through an explicit coverage signal.
assert.equal(State.REASON_CODE_MAP.COVERED, 'ANALYSE_DISPONIBLE');
assert.equal(State.mapAnalysisState({ coverage_state: 'COVERED' }).state, 'ANALYSE_DISPONIBLE');

// VS_LIMPERS unsupported spot -> SPOT_NON_SUPPORTE (never a generic fallback).
const vsLimpers = replayer.replayHeroCommentState(0, { street: 'Préflop' }, null, {
  req: { kind: 'aggression' }, priorMetrics: {}, observedEvidence: EVIDENCE,
});
assert.equal(vsLimpers.family, 'VS_LIMPERS');
assert.equal(vsLimpers.actor_state, 'SPOT_NON_COUVERT');
assert.equal(vsLimpers.taxonomy_state, 'SPOT_NON_SUPPORTE');
genericGuard('Replayer Hero (VS_LIMPERS)', () => vsLimpers.taxonomy_label, 'SPOT_NON_COUVERT');

// The rendered Hero detail must render the precise taxonomy label, never a
// generic "no analysis/recommendation available" message.
const unsupportedDecision = { coverage_state: 'UNSUPPORTED', reason_codes: ['SPOT_NON_COUVERT'], facing_context: 'VS_LIMPERS', support: {}, alternatives: [] };
const unsupportedDetail = replayer.preflopDecisionDetailHtml(unsupportedDecision);
assert.ok(unsupportedDetail.includes('Spot non supporté'), unsupportedDetail);
assert.ok(unsupportedDetail.includes('SPOT_NON_COUVERT'), unsupportedDetail);
genericGuard('Replayer Hero detail', () => unsupportedDetail, 'SPOT_NON_COUVERT');

// ---------------------------------------------------------------------------
// 4. Review Inbox / Dashboard precise causes (no generic fallback).
// ---------------------------------------------------------------------------
for (const [coverage, state] of [
  [{ reasons: ['CALCULATION_PENDING'], complete: false }, 'CALCUL_EN_COURS'],
  [{ reasons: ['WORKER_ERROR'], complete: false }, 'ERREUR_CALCUL'],
  [{ reasons: ['SPOT_NON_COUVERT'], complete: false }, 'SPOT_NON_SUPPORTE'],
  [{ reasons: ['LOW_SUPPORT'], complete: false }, 'DONNEES_INSUFFISANTES'],
  [{ reasons: ['NON_COMPARABLE_DECISIONS'], complete: false }, 'ANALYSE_PARTIELLE'],
  [{ reasons: [], complete: true }, 'ANALYSE_DISPONIBLE'],
]) {
  const mappedState = Inbox.analysisStateFor(coverage, []);
  assert.equal(mappedState.state, state, 'inbox ' + JSON.stringify(coverage));
  genericGuard('Review Inbox', () => Inbox.analysisStateLabel(mappedState.state), coverage.reasons.join(','));
}
for (const [emptyState, state, metrics] of [
  ['NO_HANDS', 'DONNEES_INSUFFISANTES', {}],
  ['ANALYSIS_PENDING', 'CALCUL_EN_COURS', {}],
  ['ANALYSIS_INCOMPLETE', 'ANALYSE_PARTIELLE', { decisions_analyzed: 3 }],
  ['ANALYSIS_INCOMPLETE', 'DONNEES_INSUFFISANTES', { decisions_analyzed: 0 }],
  ['NO_SIGNIFICANT_LOSS', 'ANALYSE_DISPONIBLE', {}],
  ['READY', 'ANALYSE_DISPONIBLE', {}],
]) {
  const mappedState = Dashboard.analysisStateFor(emptyState, metrics);
  assert.equal(mappedState.state, state, 'dashboard ' + emptyState);
  genericGuard('Review Dashboard', () => Dashboard.analysisStateLabel(mappedState.state), emptyState);
}

// ---------------------------------------------------------------------------
// 5. Replayer adverse precise causes + rule D5.
// ---------------------------------------------------------------------------
const oppPrecise = [
  ['OPPONENT_ANALYZABLE', 'ANALYSE_DISPONIBLE'],
  ['OPPONENT_SUPPORT_INSUFFICIENT', 'DONNEES_INSUFFISANTES'],
  ['OPPONENT_NODE_ABSENT', 'SPOT_NON_SUPPORTE'],
];
for (const [actor, state] of oppPrecise) {
  const view = replayer.opponentCommentView(actor, { observed_action: 'RAISE', support: 37, range: { before: 'prior_uninformative', after: 'conditioned' } });
  assert.equal(view.state, state, 'opponent ' + actor);
  assert.equal(view.taxonomy_label, EXPECTED_LABELS[state]);
  genericGuard('Replayer adverse', () => view.taxonomy_label, actor);
  // The generic adverse message is reserved for a genuinely unknown cause.
  assert.ok(!String(view.text).includes('Analyse adverse non disponible'), actor + ' must not use the generic message');
  for (const forbidden of ['ev', 'evBB', 'recommended_ev_bb', 'recommended_action', 'alternatives', 'optimal_ev']) {
    assert.ok(!(forbidden in view), 'adverse view must not expose ' + forbidden);
  }
  for (const key of ['observed_action', 'support', 'support_status', 'range_before', 'range_after', 'posterior_availability']) {
    assert.ok(key in view, 'adverse view must expose ' + key);
  }
}
// A genuinely unknown cause keeps the generic message and a safe state.
const oppUnknown = replayer.replayOpponentCommentStateFromEvidence(null, { actionType: 'raise' }, null, { rangeAvailability: { before: 'unavailable', after: 'unavailable' } });
assert.equal(oppUnknown.state, 'DONNEES_INSUFFISANTES');
assert.ok(String(oppUnknown.text).includes('Analyse adverse non disponible'));

// D5 at the rendered boundary: observed action + support + range before/after,
// never an "optimal EV".
const oppHtml = replayer.replayOpponentCommentHtml(1, { actionType: 'raise' });
const oppHtmlDetail = replayer.replayOpponentCommentHtml(1, { actionType: 'raise' }, { detail: true });
for (const rendered of [oppHtml, oppHtmlDetail]) {
  assert.ok(rendered.includes('action observée RAISE'), rendered);
  assert.ok(rendered.includes('support 37 obs.'), rendered);
  assert.ok(rendered.includes('range avant prior_uninformative / après conditioned'), rendered);
  assert.ok(!rendered.includes('EV optimale'), rendered);
}
assert.ok(oppHtmlDetail.includes('Aucune recommandation ni alternative EV Hero n’est appliquée'), oppHtmlDetail);

// ---------------------------------------------------------------------------
// 6. Rule D6: Hero/training EV only when admissible AND comparable.
// ---------------------------------------------------------------------------
const d6Cases = [
  [{ recommendation_admissibility: { admissible: true, status: 'ADMISSIBLE' }, ev_comparability: { comparable: true, reason: null } }, true],
  [{ recommendation_admissibility: { admissible: true, status: 'ADMISSIBLE' }, ev_comparability: { comparable: false, reason: 'NON_COMPARABLE' } }, false],
  [{ recommendation_admissibility: { admissible: false, status: 'NO_ADMISSIBLE_STRATEGY' }, ev_comparability: { comparable: true, reason: null } }, false],
  [{ recommendation_admissibility: { admissible: false, status: 'NO_ADMISSIBLE_STRATEGY' }, ev_comparability: { comparable: false, reason: 'NON_COMPARABLE' } }, false],
];
for (const [decision, expected] of d6Cases) {
  const heroView = replayer.heroDecisionView(decision);
  assert.equal(heroView.admissible, decision.recommendation_admissibility.admissible);
  assert.equal(heroView.ev_comparable, decision.ev_comparability.comparable);
  assert.equal(heroView.show_ev, expected);
  assert.equal(heroView.show_ev, heroView.admissible && heroView.ev_comparable);
  const trainView = trainer.trainerPreflopDecisionView(decision);
  assert.equal(trainView.show_ev, expected);
  assert.equal(trainView.show_ev, trainView.admissible && trainView.ev_comparable);
}
const partialDecision = {
  facing_context: 'VS_RFI', recommended_action: '3BET', recommended_ev_bb: 1.6, recommended_target_sizing: { target_total_bb: 8 },
  incremental_cost_bb: 8, support: { observations: 150 }, support_tier: 'HIGH', alternatives: [],
  recommendation_admissibility: { admissible: true, status: 'ADMISSIBLE' },
  ev_comparability: { comparable: false, reason: 'NON_COMPARABLE' },
};
const partialCompact = replayer.preflopDecisionCompactHtml(partialDecision);
assert.ok(!partialCompact.includes('3BET'), partialCompact);
assert.ok(!partialCompact.includes('1.60'), partialCompact);
assert.ok(partialCompact.includes('Analyse partielle'), partialCompact);
const readyCompact = replayer.preflopDecisionCompactHtml({ ...partialDecision, ev_comparability: { comparable: true, reason: null } });
assert.ok(readyCompact.includes('3BET'), readyCompact);

console.log(JSON.stringify({
  status: 'PASS',
  schema: State.SCHEMA,
  states: EXPECTED_STATES,
  labels: EXPECTED_LABELS,
  surfaces: ['review-inbox', 'review-dashboard', 'replayer-hero', 'replayer-adverse', 'training'],
  mapped_codes: mapped,
}));
"""


def _assert_static_wiring() -> None:
    # The edit source and the served mirror must stay byte-identical so every
    # surface consumes the same enum/label layer.
    for src, site in ((STATE_SRC, STATE_SITE), (INBOX_SRC, INBOX_SITE), (DASH_SRC, DASH_SITE)):
        assert src.is_file(), f"missing {src}"
        assert site.is_file(), f"missing {site}"
        assert src.read_bytes() == site.read_bytes(), f"{src} and {site} must be byte-identical"

    inbox = INBOX_SRC.read_text(encoding="utf-8")
    dashboard = DASH_SRC.read_text(encoding="utf-8")
    trainer = TRAINER.read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")

    # Inbox owns the shared six-label table, sourced from the shared enum.
    assert "require('./analysis-state.js')" in inbox
    assert "ANALYSIS_STATE_LABELS={" in inbox
    for state, label in EXPECTED_LABELS.items():
        assert f"{state}:'{label}'" in inbox, state
    assert "analysisStateLabel,stepIndex" in inbox

    # Dashboard delegates its label to the shared Inbox table.
    assert "require('./analysis-state.js')" in dashboard
    assert "Inbox.analysisStateLabel(state)" in dashboard

    # Replayer Hero/adverse and Training load the shared module first.
    module_tag = '<script src="./analytics/analysis-state.js"></script>'
    assert module_tag in index
    assert index.index(module_tag) < index.index('<script src="./analytics/review-inbox.js"></script>')
    assert index.index(module_tag) < index.index('<script src="./trainer.js"></script>')
    assert "window.PokerAnalysisState" in index
    assert "Inbox.analysisStateLabel(state)" in index
    assert "window.PokerAnalysisState" in trainer
    assert "Inbox.ANALYSIS_STATE_LABELS" in trainer


def main() -> None:
    _assert_static_wiring()

    proc = subprocess.run(
        ["node", "-e", NODE_CONTRACT],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["status"] == "PASS", payload
    assert payload["schema"] == "poker-analysis-state/v1", payload
    assert payload["states"] == list(EXPECTED_LABELS), payload
    assert payload["labels"] == EXPECTED_LABELS, payload
    assert payload["surfaces"] == SURFACES, payload

    # Every required legacy code is covered and resolves to exactly one state.
    mapped_codes = payload["mapped_codes"]
    total = 0
    for state, expected_codes in _expected_mapping().items():
        for code in expected_codes:
            assert mapped_codes.get(code) == state, f"{code} -> {mapped_codes.get(code)} != {state}"
            total += 1
    assert total == len(mapped_codes), (total, len(mapped_codes))

    print("analysis-state cross-surface consistency contract: PASS")


def _expected_mapping() -> dict:
    return {
        "CALCUL_EN_COURS": [
            "CALCULATION_PENDING",
            "ANALYSIS_PENDING",
            "UNFINISHED_DECISIONS",
        ],
        "ERREUR_CALCUL": ["WORKER_ERROR", "ANALYSIS_ERROR"],
        "SPOT_NON_SUPPORTE": [
            "UNSUPPORTED",
            "SPOT_NON_COUVERT",
            "CONTEXT_UNSUPPORTED",
            "EXACT_CONTEXT_MISMATCH",
            "ACTIVE_REFERENCE_SCOPE_UNSUPPORTED",
            "UNCOVERED",
            "NODE_ABSENT",
            "EXACT_CONTEXT_ABSENT",
        ],
        "DONNEES_INSUFFISANTES": [
            "LOW_SUPPORT",
            "INSUFFICIENT_SUPPORT",
            "MISSING_HH_SOURCE",
            "MISSING_REVIEW_SCORE",
            "NO_DECISION_EVENTS",
            "REVIEW_SCORE_INCOMPLETE",
            "NO_HANDS",
        ],
        "ANALYSE_PARTIELLE": [
            "NON_COMPARABLE",
            "NON_COMPARABLE_ALTERNATIVES",
            "NON_COMPARABLE_DECISIONS",
            "MISSING_COMPARABLE_EV",
            "NO_COMPARABLE_REVIEW_DETAIL",
            "PARTIAL_ANALYSIS",
            "ANALYSIS_INCOMPLETE",
            "PLAYED_ALTERNATIVE_NOT_EVALUATED",
            "RECOMMENDATION_NOT_ADMISSIBLE",
            "INVALID_GUIDANCE",
            "NO_ADMISSIBLE_STRATEGY",
        ],
        "ANALYSE_DISPONIBLE": ["NO_SIGNIFICANT_LOSS", "READY"],
    }


if __name__ == "__main__":
    main()
