'use strict';

// Runtime proof for the #393 T6 Replayer opponent taxonomy (rule D5).
//
// The real `replayOpponentCommentStateFromEvidence` / `replayOpponentCommentState`
// / `replayOpponentRangeAvailability` functions are extracted from
// `site/index.html` and evaluated with the frozen shared module
// (`src/analytics/analysis-state.js`) as `window.PokerAnalysisState`.
//
// It proves that the three precise opponent causes are distinct and mapped onto
// the shared `poker-analysis-state/v1` taxonomy:
//
//   OPPONENT_ANALYZABLE          -> ANALYSE_DISPONIBLE
//   OPPONENT_SUPPORT_INSUFFICIENT-> DONNEES_INSUFFISANTES
//   OPPONENT_NODE_ABSENT         -> SPOT_NON_SUPPORTE
//   OPPONENT_ANALYSIS_UNAVAILABLE-> safe fallback, generic message only when no
//                                   more precise cause exists
//
// Every returned view must expose the observed action, the support/likelihood
// (`statistical_support` + `model_support_status`) and the opponent range
// availability before/after the action (the #391 posterior states), and must
// never promise an EV alternative or a Hero EV recommendation.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '../..');
const INDEX = fs.readFileSync(path.join(ROOT, 'site/index.html'), 'utf8');
const State = require(path.join(ROOT, 'src/analytics/analysis-state.js'));

function section(start, end) {
  const i = INDEX.indexOf(start);
  assert.ok(i >= 0, `section start not found: ${start}`);
  const j = INDEX.indexOf(end, i + start.length);
  assert.ok(j >= 0, `section end not found: ${end}`);
  return INDEX.slice(i, j);
}

const LABELS = {
  ANALYSE_DISPONIBLE: 'Analyse disponible',
  ANALYSE_PARTIELLE: 'Analyse partielle',
  CALCUL_EN_COURS: 'Calcul en cours',
  DONNEES_INSUFFISANTES: 'Données insuffisantes',
  SPOT_NON_SUPPORTE: 'Spot non supporté',
  ERREUR_CALCUL: 'Erreur de calcul',
};

const heroHelpers = section('const HERO_ACTOR_ANALYSIS_INPUT=', 'function preflopDecisionCompactHtml(');
const opponent = section('const OPPONENT_ACTOR_ANALYSIS_INPUT=', 'function heroCommentView(');
const opponentHtml = section('function replayOpponentCommentHtml(', 'function actionDetailKeyPointsHtml(');

const source = [
  heroHelpers,
  opponent,
  opponentHtml,
  'return {OPPONENT_ACTOR_ANALYSIS_INPUT,opponentCommentAnalysisState,opponentCommentView,replayOpponentRangeAvailability,replayOpponentCommentStateFromEvidence,replayOpponentCommentState,replayOpponentCommentHtml};',
].join('\n');

const windowObject = {
  PokerAnalysisState: State,
  PokerReviewInbox: { analysisStateLabel: (s) => LABELS[s] || s },
  PokerPreflopContract: { SCHEMA: 'poker-preflop-context/v1' },
};
const escapeHtml = (v) => String(v);
const actionCompactPillHtml = (text, cls, name) => `<pill class="${cls}" data-name="${name}">${text}</pill>`;

const api = new Function(
  'window',
  'currentHandPlayer',
  'populationRangeEstimateForPlayer',
  'replayObservedDecisionEvidence',
  'findClosestPopulationNode',
  'findClosestPostflopNode',
  'escapeHtml',
  'actionCompactPillHtml',
  source
)(
  windowObject,
  () => ({ name: 'BB', hhPosition: 'BB' }),
  () => null,
  () => null,
  () => null,
  () => null,
  escapeHtml,
  actionCompactPillHtml
);

const STATES = new Set(Object.values(State.ANALYSIS_STATES));

function assertExposed(view, actorState, expectedState, expectedRange) {
  assert.ok(STATES.has(view.state), `state ${view.state} is not part of the shared enum`);
  assert.equal(view.state, expectedState);
  assert.equal(view.actor_state, actorState);
  assert.equal(view.analysis_state.state, expectedState);
  assert.equal(view.taxonomy_state, expectedState);
  assert.equal(view.taxonomy_label, LABELS[expectedState]);
  const validation = State.validateAnalysisState(view.analysis_state);
  assert.ok(validation.valid, `analysis_state must validate: ${validation.errors.join(', ')}`);
  assert.equal(view.range_before, expectedRange.before);
  assert.equal(view.range_after, expectedRange.after);
  assert.equal(view.analysis_state.posterior_availability, expectedRange.after);
  assert.ok(view.observed_action, 'the observed action must be exposed');
  assert.ok('support' in view, 'the support must be exposed');
  assert.ok(view.support_status, 'the support/likelihood status must be exposed');
  // Rule D5: no EV field is ever attached to an opponent view.
  for (const forbidden of ['ev', 'evBB', 'recommended_ev_bb', 'alternative', 'alternatives', 'recommended_action']) {
    assert.ok(!(forbidden in view), `opponent view must not expose ${forbidden}`);
  }
  return view;
}

const evidence = {
  phase: 'PREFLOP',
  decision: { action: 'RAISE', family: 'VS_LIMPERS', preflop_context_v1: { schema: 'poker-preflop-context/v1', family: 'VS_LIMPERS' } },
};
const step = { actionType: 'raise' };
const range = { before: 'prior_uninformative', after: 'conditioned' };

// ---------------------------------------------------------------------------
// 1. A matched node with positive support -> ANALYSE_DISPONIBLE.
// ---------------------------------------------------------------------------
{
  const match = { quality: 'exact', node: { coverage: { population_decisions: 37 }, context: { family: 'VS_LIMPERS' } } };
  const view = api.replayOpponentCommentStateFromEvidence(evidence, step, match, { rangeAvailability: range });
  assertExposed(view, 'OPPONENT_ANALYZABLE', 'ANALYSE_DISPONIBLE', range);
  assert.equal(view.support, 37);
  assert.equal(view.analysis_state.statistical_support.observations, 37);
  assert.equal(view.observed_action, 'RAISE');
  assert.equal(view.family, 'VS_LIMPERS');
}

// ---------------------------------------------------------------------------
// 2. A matched node without usable support -> DONNEES_INSUFFISANTES.
// ---------------------------------------------------------------------------
{
  const match = { quality: 'exact', node: { coverage: { population_decisions: 0 }, context: { family: 'VS_LIMPERS' } } };
  const view = api.replayOpponentCommentStateFromEvidence(evidence, step, match, { rangeAvailability: range });
  assertExposed(view, 'OPPONENT_SUPPORT_INSUFFICIENT', 'DONNEES_INSUFFISANTES', range);
  assert.equal(view.support, 0);
  assert.ok(view.analysis_state.reason_codes.includes('INSUFFICIENT_SUPPORT'));
  assert.ok(view.text.includes('Support insuffisant'));
}

// ---------------------------------------------------------------------------
// 3. No node -> SPOT_NON_SUPPORTE (never the generic unavailable fallback).
// ---------------------------------------------------------------------------
{
  const view = api.replayOpponentCommentStateFromEvidence(evidence, step, null, { rangeAvailability: { before: 'unavailable', after: 'unavailable' } });
  assertExposed(view, 'OPPONENT_NODE_ABSENT', 'SPOT_NON_SUPPORTE', { before: 'unavailable', after: 'unavailable' });
  assert.ok(view.analysis_state.reason_codes.includes('NODE_ABSENT'));
  assert.equal(view.analysis_state.model_support_status, 'NODE_ABSENT');
  assert.ok(view.text.includes('Aucun nœud'));
  assert.ok(!view.text.includes('Analyse adverse non disponible'), 'no-node must not use the generic message');
}

// ---------------------------------------------------------------------------
// 4. No evidence at all -> the generic message, cause genuinely unknown, and a
//    safe non-optimistic state.
// ---------------------------------------------------------------------------
{
  const view = api.replayOpponentCommentStateFromEvidence(null, step, null, { rangeAvailability: { before: 'unavailable', after: 'unavailable' } });
  assertExposed(view, 'OPPONENT_ANALYSIS_UNAVAILABLE', 'DONNEES_INSUFFISANTES', { before: 'unavailable', after: 'unavailable' });
  assert.ok(view.text.includes('Analyse adverse non disponible'));
  assert.ok(view.analysis_state.reason_codes.includes('OPPONENT_ANALYSIS_UNAVAILABLE'));
}

// ---------------------------------------------------------------------------
// 5. The caller derives the range availability before/after from the #391
//    posterior representation (index-1 vs index) via the injected estimate.
// ---------------------------------------------------------------------------
{
  const byIndex = new Map([[4, 'prior_uninformative'], [5, 'conditioned']]);
  const seen = [];
  const callerApi = new Function(
    'window',
    'currentHandPlayer',
    'populationRangeEstimateForPlayer',
    'replayObservedDecisionEvidence',
    'findClosestPopulationNode',
    'findClosestPostflopNode',
    'escapeHtml',
    'actionCompactPillHtml',
    source
  )(
    windowObject,
    () => ({ name: 'BB', hhPosition: 'BB' }),
    (player, idx) => { seen.push(idx); return { posteriorState: byIndex.get(idx) || 'unavailable' }; },
    () => evidence,
    () => ({ quality: 'exact', node: { coverage: { population_decisions: 12 }, context: { family: 'VS_LIMPERS' } } }),
    () => null,
    escapeHtml,
    actionCompactPillHtml
  );
  const view = callerApi.replayOpponentCommentState(5, step);
  assert.equal(view.range_before, 'prior_uninformative');
  assert.equal(view.range_after, 'conditioned');
  assert.equal(view.analysis_state.posterior_availability, 'conditioned');
  assert.deepEqual(seen, [4, 5], 'the range is read at the step index before and after the action');

  // 6. The rendered feed/detail message always exposes the observed action, the
  //    support and the range availability before/after, and never promises an
  //    "optimal EV alternative" nor a Hero EV recommendation.
  const feed = callerApi.replayOpponentCommentHtml(5, step);
  const detail = callerApi.replayOpponentCommentHtml(5, step, { detail: true });
  for (const rendered of [feed, detail]) {
    assert.ok(rendered.includes('action observée RAISE'), rendered);
    assert.ok(rendered.includes('support 12 obs.'), rendered);
    assert.ok(rendered.includes('range avant prior_uninformative / après conditioned'), rendered);
    assert.ok(!rendered.includes('EV optimale'), rendered);
    assert.ok(!rendered.includes('recommandation EV pour l’adversaire'), rendered);
  }
  assert.ok(feed.includes('data-comment-state="ANALYSE_DISPONIBLE"'), feed);
  assert.ok(detail.includes('Aucune recommandation ni alternative EV Hero n’est appliquée'), detail);
}

console.log(JSON.stringify({
  status: 'PASS',
  schema: State.SCHEMA,
  transitions: ['ANALYSE_DISPONIBLE', 'DONNEES_INSUFFISANTES', 'SPOT_NON_SUPPORTE'],
}));
