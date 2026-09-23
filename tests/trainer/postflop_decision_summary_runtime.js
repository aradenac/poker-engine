'use strict';

// Runtime proof for #393 blocker 1 / D6: a complete postflop
// `decision-summary/v1` synthesis must feed the shared
// `poker-analysis-state/v1` taxonomy dimensions so the D6 EV gate opens, and an
// incomplete synthesis must stay fail-safe (taxonomy-labelled, no EV).
//
// The real `decisionSummaryTaxonomyDimensions` / `decisionCanonicalSummary` /
// `decisionPrimarySummaryHtml` / `decisionAlternativesStripHtml` /
// `heroDecisionView` / `replayHeroCommentState` / `actionAnalysisHtml` and
// `actionDetailModalInnerHtml` functions are extracted from `site/index.html`
// and evaluated with the frozen shared module (`src/analytics/analysis-state.js`)
// as `window.PokerAnalysisState` and the shared presentation module
// (`site/action-sizing-ev.js`) as `window.PokerActionSizingEV`.
//
// It proves:
//
//   complete synthesis   -> ANALYSE_DISPONIBLE, show_ev=true,
//                           feed has decision-primary-grid + decision-alt-strip,
//                           modal has the primary EV block.
//   incomplete synthesis -> ANALYSE_PARTIELLE, show_ev=false,
//                           feed/modal expose neither recommendation nor EV.
//   dimension-less object-> fail-safe DONNEES_INSUFFISANTES, show_ev=false.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '../..');
const INDEX = fs.readFileSync(path.join(ROOT, 'site/index.html'), 'utf8');
const State = require(path.join(ROOT, 'src/analytics/analysis-state.js'));
const SizingEV = require(path.join(ROOT, 'site/action-sizing-ev.js'));

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

// The whole feed/modal rendering chain lives between `actionSizingAmountLabel`
// and `safeActionAnalysisHtml`, so a single contiguous extraction keeps the real
// production code (not a copy) under test.
const RENDER_CHAIN = section('function actionSizingAmountLabel(', 'function safeActionAnalysisHtml(');
const source = [
  RENDER_CHAIN,
  'return {decisionSummaryTaxonomyDimensions,decisionCanonicalSummary,decisionPrimarySummaryHtml,decisionAlternativesStripHtml,heroAnalysisStateFromDecision,heroDecisionView,heroCommentView,replayHeroCommentState,actionAnalysisHtml,actionDetailModalInnerHtml};',
].join('\n');

const escapeHtml = (v) => String(v ?? '');
const formatBB = (v) => (Number.isFinite(Number(v)) ? `${Number(v).toFixed(2)} BB` : '—');

function postflopPolicyFamily(label) {
  const s = String(label || '').toUpperCase();
  if (s.includes('FOLD')) return 'FOLD';
  if (s.includes('CHECK')) return 'CHECK';
  if (s.includes('CALL')) return 'CALL';
  if (s.includes('JAM') || s.includes('ALL-IN')) return 'JAM';
  if (s.includes('RAISE')) return 'RAISE';
  if (s.includes('BET') || s.includes('%')) return 'BET';
  return s;
}

function buildChain({ raw }) {
  const step = { street: 'Flop', actionType: 'bet', activePlayer: 'Hero' };
  const cached = { status: 'done', equities: { prior: 0.5, post: 0.5 }, postflopTrees: {}, sizingOptimization: null };
  const req = { kind: 'bet', cost: 3, potBefore: 6, actorRequired: 0.33, rakeBB: 0, rakeRate: 0, grossPotAfter: 12, netPotAfter: 12, actorPaidBefore: 0, toCall: 0, potBeforeBB: 6 };
  const state = {
    selectedHand: { id: 'hand-postflop', heroName: 'Hero' },
    replaySteps: [step],
    actionEquityCache: { k: cached },
  };
  const windowObject = {
    PokerActionSizingEV: SizingEV,
    PokerAnalysisState: State,
    PokerReviewInbox: { analysisStateLabel: (s) => LABELS[s] || s },
    PokerPreflopContract: { SCHEMA: 'poker-preflop-context/v1' },
  };
  const api = new Function(
    'window',
    'state',
    'escapeHtml',
    'formatBB',
    'finalDecisionEV',
    'actionEquityKey',
    'requiredEquityInfo',
    'actionVerdictSourceKeys',
    'postflopDecisionAlternativeSummary',
    'postflopPolicyFamily',
    'isAnyMoneyEvent',
    'isAnalyzableDecisionAction',
    'modelBRobustnessViewForDecision',
    'modelBRobustnessCompactHtml',
    'modelBRobustnessDetailHtml',
    'actionDecisionMetrics',
    'fmtEquityThreshold',
    'fmtEquityDelta',
    'actionScenarioLabel',
    'actionSingleEquityHtml',
    'actionDecisionAlternativesHtml',
    'postflopCheckEV',
    'postflopCallEVAtCurrentPrice',
    source
  )(
    windowObject,
    state,
    escapeHtml,
    formatBB,
    (a) => (Number.isFinite(Number(a?.policyAdjustedEVBB)) ? Number(a.policyAdjustedEVBB) : Number(a?.evBB)),
    () => 'k',
    () => req,
    () => ({ prior: 'prior', post: 'post', actorKnown: true }),
    () => raw,
    postflopPolicyFamily,
    () => true,
    () => true,
    () => null,
    () => '',
    () => '',
    () => ({ evBB: 0 }),
    (x) => (Number.isFinite(Number(x)) ? `${(Number(x) * 100).toFixed(1)} %` : '—'),
    () => ({ cls: 'subtle', text: '' }),
    (k) => String(k || ''),
    () => '',
    () => '<div class="decision-advanced-alternatives" data-advanced="1"></div>',
    () => NaN,
    () => NaN
  );
  return { api, state, step };
}

const completeRaw = () => {
  const chosen = { label: 'BET réel', evBB: 1.0, policyAdjustedEVBB: 1.0, seBB: 0.05, chosen: true, kind: 'chosen', costBB: 3, targetStreetBB: 3 };
  const best = { label: 'BET 0.75 pot', evBB: 1.6, policyAdjustedEVBB: 1.6, seBB: 0.05, chosen: false, kind: 'aggression', costBB: 3.5, targetStreetBB: 3.5 };
  return { alternatives: [chosen, best], best, chosenPolicyEV: 1.0, bestPolicyEV: 1.6, effectiveGap: 0.5, rawGap: 0.6, withinNoise: false, score: 8, potScale: 6, potBeforeBB: 6 };
};

// A synthesis with only the played alternative: the summary exists but no
// comparable counterfactual does, so it must stay fail-safe.
const partialRaw = () => {
  const chosen = { label: 'BET réel', evBB: 1.0, policyAdjustedEVBB: 1.0, seBB: 0.05, chosen: true, kind: 'chosen', costBB: 3, targetStreetBB: 3 };
  return { alternatives: [chosen], best: chosen, chosenPolicyEV: 1.0, bestPolicyEV: 1.0, effectiveGap: 0, rawGap: 0, withinNoise: true, score: 10, potScale: 6, potBeforeBB: 6 };
};

// ---------------------------------------------------------------------------
// 1. Complete synthesis -> taxonomy dimensions + ANALYSE_DISPONIBLE + D6 open.
// ---------------------------------------------------------------------------
{
  const { api, state, step } = buildChain({ raw: completeRaw() });
  const summary = api.decisionCanonicalSummary(0, step, state.actionEquityCache.k);
  assert.equal(summary.schema, 'decision-summary/v1');
  assert.equal(summary.coverage_state, 'COVERED');
  assert.equal(summary.recommendation_admissibility.admissible, true);
  assert.equal(summary.recommendation_admissibility.status, 'ADMISSIBLE');
  assert.deepEqual(summary.recommendation_admissibility.reason_codes, []);
  assert.equal(summary.ev_comparability.comparable, true);
  assert.equal(summary.ev_comparability.reason, null);
  assert.equal(summary.recommended.label, 'BET 0.75 pot');
  assert.ok(Number.isFinite(summary.recommended.evBB));

  const view = api.heroDecisionView(summary);
  assert.equal(view.taxonomy_state, 'ANALYSE_DISPONIBLE');
  assert.equal(view.taxonomy_label, 'Analyse disponible');
  assert.equal(view.show_ev, true);
  const validation = State.validateAnalysisState(view.analysis);
  assert.ok(validation.valid, `analysis must validate: ${validation.errors.join(', ')}`);
  assert.deepEqual(view.analysis.reason_codes, []);

  const heroState = api.replayHeroCommentState(0, step, state.actionEquityCache.k, { canonicalDecision: summary });
  assert.equal(heroState.taxonomy_state, 'ANALYSE_DISPONIBLE');
  assert.equal(heroState.show_ev, true);

  // Feed: the real decision-summary/v1 primary summary + alternatives are shown.
  const feed = api.actionAnalysisHtml(0, step);
  assert.ok(feed.includes('data-comment-state="ANALYSE_DISPONIBLE"'), feed);
  assert.ok(feed.includes('Analyse disponible'), feed);
  assert.ok(feed.includes('class="decision-primary-grid'), feed);
  assert.ok(feed.includes('data-decision-summary-schema="decision-summary/v1"'), feed);
  assert.ok(feed.includes('Recommandé'), feed);
  assert.ok(feed.includes('decision-alt-strip'), feed);
  assert.ok(feed.includes('BET 0.75 pot'), feed);

  // Modal: the primary EV block is rendered.
  const modal = api.actionDetailModalInnerHtml(0, step);
  assert.ok(modal.includes('decision-modal-primary'), modal);
  assert.ok(modal.includes('data-decision-summary-schema="decision-summary/v1"'), modal);
  assert.ok(modal.includes('Recommandé'), modal);
  assert.ok(modal.includes('decision-alt-strip'), modal);
}

// ---------------------------------------------------------------------------
// 2. Incomplete synthesis -> ANALYSE_PARTIELLE + D6 closed (no recommendation/EV).
// ---------------------------------------------------------------------------
{
  const { api, state, step } = buildChain({ raw: partialRaw() });
  const summary = api.decisionCanonicalSummary(0, step, state.actionEquityCache.k);
  assert.equal(summary.recommended, null, 'no recommended action when not comparable');
  assert.equal(summary.recommendation_admissibility.admissible, false);
  assert.equal(summary.ev_comparability.comparable, false);
  assert.equal(summary.ev_comparability.reason, 'NON_COMPARABLE_ALTERNATIVES');

  const view = api.heroDecisionView(summary);
  assert.equal(view.taxonomy_state, 'ANALYSE_PARTIELLE');
  assert.equal(view.taxonomy_label, 'Analyse partielle');
  assert.equal(view.show_ev, false);
  const validation = State.validateAnalysisState(view.analysis);
  assert.ok(validation.valid, `analysis must validate: ${validation.errors.join(', ')}`);
  assert.ok(view.analysis.reason_codes.includes('NON_COMPARABLE_ALTERNATIVES'));

  const feed = api.actionAnalysisHtml(0, step);
  assert.ok(feed.includes('data-comment-state="ANALYSE_PARTIELLE"'), feed);
  assert.ok(feed.includes('Analyse partielle'), feed);
  assert.ok(feed.includes('Aucune recommandation EV validée'), feed);
  assert.ok(!feed.includes('decision-primary-grid'), feed);
  assert.ok(!feed.includes('data-decision-summary-schema'), feed);
  assert.ok(!feed.includes('decision-alt-strip'), feed);

  const modal = api.actionDetailModalInnerHtml(0, step);
  assert.ok(modal.includes('decision-modal-primary'), modal);
  assert.ok(!modal.includes('data-decision-summary-schema'), modal);
  assert.ok(!modal.includes('decision-alt-strip'), modal);
  assert.ok(modal.includes('data-analysis-detail="1"'), modal);
  assert.ok(modal.includes('NON_COMPARABLE_ALTERNATIVES'), modal);
}

// ---------------------------------------------------------------------------
// 3. A `decision-summary/v1` object without explicit taxonomy dimensions keeps
//    the historical fail-safe: DONNEES_INSUFFISANTES, no EV surface.
// ---------------------------------------------------------------------------
{
  const { api, state, step } = buildChain({ raw: completeRaw() });
  const summary = api.decisionCanonicalSummary(0, step, state.actionEquityCache.k);
  const legacy = JSON.parse(JSON.stringify(summary));
  for (const key of ['coverage_state', 'reason_codes', 'recommendation_admissibility', 'ev_comparability']) delete legacy[key];
  const view = api.heroDecisionView(legacy);
  assert.equal(view.taxonomy_state, 'DONNEES_INSUFFISANTES');
  assert.equal(view.show_ev, false);

  const heroState = api.replayHeroCommentState(0, step, state.actionEquityCache.k, { canonicalDecision: legacy });
  assert.equal(heroState.show_ev, false);
  assert.equal(heroState.taxonomy_state, 'DONNEES_INSUFFISANTES');
}

console.log(JSON.stringify({
  status: 'PASS',
  schema: State.SCHEMA,
  surfaces: ['actionAnalysisHtml', 'actionDetailModalInnerHtml'],
  states: ['ANALYSE_DISPONIBLE', 'ANALYSE_PARTIELLE', 'DONNEES_INSUFFISANTES'],
}));
