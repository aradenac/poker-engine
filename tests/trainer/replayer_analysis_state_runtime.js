'use strict';

// Runtime proof for the #393 T5 Replayer Hero taxonomy.
//
// The real `replayHeroCommentState`/`preflopDecisionCompactHtml`/
// `preflopDecisionDetailHtml` functions are extracted from `site/index.html` and
// evaluated with the frozen shared module (`src/analytics/analysis-state.js`) as
// `window.PokerAnalysisState`. Every Hero transition is therefore proven to be
// derived from the shared `poker-analysis-state/v1` enum:
//
//   HERO_COVERED / HERO_BASELINE_VALIDATED -> ANALYSE_DISPONIBLE
//   HERO_ALTERNATIVES_NON_COMPARABLES      -> ANALYSE_PARTIELLE
//   SPOT_NON_COUVERT                       -> SPOT_NON_SUPPORTE
//   HERO_RECOMMENDATION_UNAVAILABLE        -> SPOT_NON_SUPPORTE | DONNEES_INSUFFISANTES
//   HERO_PENDING                           -> CALCUL_EN_COURS
//   HERO_ANALYSIS_ERROR                    -> ERREUR_CALCUL (retryable)
//
// It also pins rule D6: the rendered Hero EV/recommendation fields disappear as
// soon as admissibility or EV comparability is false, and the reason codes are
// only emitted by the secondary/detail renderer.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '../..');
const INDEX = fs.readFileSync(path.join(ROOT, 'site/index.html'), 'utf8');
const State = require(path.join(ROOT, 'src/analytics/analysis-state.js'));
const Decision = require(path.join(ROOT, 'src/preflop/decision.js'));
const Guidance = require(path.join(ROOT, 'src/preflop/guidance.js'));
const Adapter = require(path.join(ROOT, 'src/training/preflop-decision-adapter.js'));

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

const helpers = section('const HERO_ACTOR_ANALYSIS_INPUT=', 'function preflopDecisionCompactHtml(');
const renderers = section('function preflopDecisionCompactHtml(', 'function replayOpponentCommentStateFromEvidence(');
const heroComment = section('function heroCommentView(', 'function replayOpponentCommentHtml(');

const source = [
  helpers,
  renderers,
  heroComment,
  'return {HERO_ACTOR_ANALYSIS_INPUT,heroAnalysisStateFromActor,heroAnalysisStateFromDecision,heroTaxonomyLabel,heroDecisionView,heroAnalysisDimensionsHtml,preflopDecisionCompactHtml,preflopDecisionDetailHtml,heroCommentView,replayHeroCommentState};',
].join('\n');

const windowObject = {
  PokerAnalysisState: State,
  PokerReviewInbox: { analysisStateLabel: (s) => LABELS[s] || s },
  PokerPreflopContract: { SCHEMA: 'poker-preflop-context/v1' },
};

const api = new Function(
  'window',
  'escapeHtml',
  'formatBB',
  'actionCompactPillHtml',
  'preflopDecisionSizingText',
  'finalDecisionEV',
  'replayObservedDecisionEvidence',
  source
)(
  windowObject,
  (v) => String(v),
  (v) => `${Number(v).toFixed(2)} BB`,
  (text, cls, name) => `<pill class="${cls}" data-name="${name}">${text}</pill>`,
  (target) => (Number.isFinite(Number(target?.target_total_bb)) ? `total ${Number(target.target_total_bb).toFixed(2)}` : '0 BB'),
  (a) => Number(a?.evBB),
  () => null
);

const STATES = new Set(Object.values(State.ANALYSIS_STATES));

// ---------------------------------------------------------------------------
// Fixtures: real canonical decisions through the frozen adapter/runtime.
// ---------------------------------------------------------------------------
const POP = 'pokerstars_nlhe_100-200_zoom_play_6max_v1';
const STRATEGY = 'hero-preflop-promoted-v1';
const IDENTITY = {
  population_id: POP,
  pack_id: 'zoom-pack',
  pack_version: 'pack-v1',
  strategy_id: STRATEGY,
  strategy_version: 'release-r1',
  strategy_sha256: 'a'.repeat(64),
  decision_source_sha256: 'b'.repeat(64),
  ev_reference: 'decision_point_incremental_bb',
};
const uncertainty = () => ({ monte_carlo: { standard_error_bb: 0.05, samples: 5000, method: 'synthetic' } });
const support = (n) => ({ observations: n, backoff_level: 'EXACT', source: 'SYNTHETIC' });
const alt = (id, action, target, cost, ev, n) => ({
  id, action, target_total_bb: target, incremental_cost_bb: cost, ev_bb: ev,
  support: support(n), confidence: 0.8, uncertainty: uncertainty(),
});
function publicState(actor) {
  const seats = ['LJ', 'HJ', 'CO', 'BTN', 'SB', 'BB'];
  const stacks = Object.fromEntries(seats.map((p) => [p, 100]));
  const total = Object.fromEntries(seats.map((p) => [p, 0]));
  const street = Object.fromEntries(seats.map((p) => [p, 0]));
  const folded = Object.fromEntries(seats.map((p) => [p, false]));
  const allin = Object.fromEntries(seats.map((p) => [p, false]));
  total.SB = 0.5; street.SB = 0.5; stacks.SB = 99.5; total.BB = 1; street.BB = 1; stacks.BB = 99;
  street.HJ = 2.5; total.HJ = 2.5; stacks.HJ = 97.5;
  return {
    snapshot: {
      schema: 'nlhe-game-state/v1', seats, button: 'BTN', small_blind_player: 'SB', big_blind_player: 'BB',
      small_blind_bb: 0.5, big_blind_bb: 1, starting_stacks_bb: Object.fromEntries(seats.map((p) => [p, 100])),
      stacks_bb: stacks, total_committed_bb: total, street_committed_bb: street, folded, all_in: allin,
      street: 'preflop', board: [], current_bet_bb: 2.5, last_full_raise_bb: 1, full_bet_established: true,
      acted_since_full_raise: [], pending: [actor], refunds_bb: Object.fromEntries(seats.map((p) => [p, 0])),
      action_log: [{ street: 'preflop', player: 'HJ', action: 'RAISE', target_total_bb: 2.5, incremental_cost_bb: 2.5 }],
    },
    legal_view: {
      actor, pot_before_bb: 3.5, actor_street_contribution_bb: 0, actor_remaining_bb: 100, current_price_bb: 2.5,
      to_call_bb: 2.5, legal_actions: ['FOLD', 'CALL', 'RAISE'], min_raise_to_bb: 5.5, max_raise_to_bb: 100, reopen: true,
      raise_reopened: true,
    },
  };
}
const completeDecision = (() => {
  const alternatives = [alt('fold', 'FOLD', null, 0, 0, 150), alt('call', 'CALL', 2.5, 2.5, 0.7, 150), alt('3b-8', '3BET', 8, 8, 1.6, 150)];
  const decision = Decision.buildDecision({
    context_id: 'ctx-3bet', population_id: POP, actor_contribution_bb: 0,
    legal_actions: Array.from(new Set(alternatives.map((x) => x.action))), selected_id: '3b-8', alternatives,
    search: { candidate_ids: alternatives.map((x) => x.id), sizing_grid_source: 'synthetic', budget: 1000, seed: '195' },
  });
  const guidance = Guidance.buildGuidance({
    decision,
    strategy: {
      state: 'PROMOTED', strategy_id: STRATEGY, strategy_sha256: IDENTITY.strategy_sha256, population_id: POP,
      source: 'synthetic-promotion-registry', decision_source_sha256: IDENTITY.decision_source_sha256,
    },
    public_snapshot: { street: 'PREFLOP', context_id: 'ctx-3bet', population_id: POP, hero_hand_class: 'AQs' },
  });
  return Adapter.buildDecision({
    public_state: publicState('BTN'), identity: IDENTITY, guidance, played_action: { action: 'CALL', target_total_bb: 2.5 },
    coverage: { state: 'COVERED', support_tier: 'HIGH' },
    preflop_context: { context_id: 'ctx-3bet', family: 'VS_RFI', actor_position: 'BTN' },
    hand_id: 'complete-hero', timestamp: '2026-09-19T00:30:00Z',
  });
})();
const unsupportedDecision = Adapter.buildDecision({
  public_state: publicState('BTN'), identity: IDENTITY, guidance: null, played_action: { action: 'CALL', target_total_bb: 2.5 },
  coverage: { state: 'ANALYSIS_MISSING', support_tier: 'UNKNOWN' },
  preflop_context: { family: 'VS_LIMPERS', actor_position: 'BTN' }, hand_id: 'unsupported-hero',
});

function assertTransition(view, expectedState) {
  assert.ok(STATES.has(view.state), `state ${view.state} is not part of the shared enum`);
  assert.equal(view.state, expectedState);
  assert.equal(view.analysis_state.state, expectedState);
  assert.ok(STATES.has(view.analysis_state.state));
}

// ---------------------------------------------------------------------------
// 1. Admissible & comparable canonical decision -> ANALYSE_DISPONIBLE. D6 opens.
// ---------------------------------------------------------------------------
{
  const view = api.replayHeroCommentState(0, { street: 'Préflop' }, null, { canonicalDecision: completeDecision });
  assert.equal(view.actor_role, 'HERO');
  assert.equal(view.actor_state, 'HERO_COVERED');
  assertTransition(view, 'ANALYSE_DISPONIBLE');
  assert.equal(view.admissible, true);
  assert.equal(view.ev_comparable, true);
  assert.equal(view.show_ev, true);
  assert.equal(view.taxonomy_label, 'Analyse disponible');
}

// ---------------------------------------------------------------------------
// 2. HERO_BASELINE_VALIDATED (restricted CALL/FOLD surface) -> ANALYSE_DISPONIBLE.
// ---------------------------------------------------------------------------
{
  const view = api.replayHeroCommentState(0, { street: 'Préflop' }, null, { req: { kind: 'call' }, priorMetrics: { evBB: 0.42 } });
  assert.equal(view.actor_state, 'HERO_BASELINE_VALIDATED');
  assertTransition(view, 'ANALYSE_DISPONIBLE');
  assert.equal(view.show_ev, true);
  assert.equal(view.source_contract, 'preflop-call-fold-baseline');
}

// ---------------------------------------------------------------------------
// 3. HERO_ALTERNATIVES_NON_COMPARABLES -> ANALYSE_PARTIELLE. D6 closed.
// ---------------------------------------------------------------------------
{
  const view = api.replayHeroCommentState(0, { street: 'Flop' }, null, { decisionSummary: { alternatives: [{ evBB: 0.5 }] } });
  assert.equal(view.actor_state, 'HERO_ALTERNATIVES_NON_COMPARABLES');
  assertTransition(view, 'ANALYSE_PARTIELLE');
  assert.equal(view.show_ev, false);
}

// ---------------------------------------------------------------------------
// 4. SPOT_NON_COUVERT / VS_LIMPERS -> SPOT_NON_SUPPORTE.
// ---------------------------------------------------------------------------
{
  const evidence = { phase: 'PREFLOP', decision: { action: 'RAISE', family: 'VS_LIMPERS', preflop_context_v1: { schema: 'poker-preflop-context/v1', family: 'VS_LIMPERS' } } };
  const view = api.replayHeroCommentState(0, { street: 'Préflop' }, null, { req: { kind: 'aggression' }, priorMetrics: {}, observedEvidence: evidence });
  assert.equal(view.actor_state, 'SPOT_NON_COUVERT');
  assert.equal(view.family, 'VS_LIMPERS');
  assertTransition(view, 'SPOT_NON_SUPPORTE');
  assert.equal(view.show_ev, false);

  // The canonical unsupported decision (VS_LIMPERS) derives from the same module.
  const canonical = api.replayHeroCommentState(0, { street: 'Préflop' }, null, { canonicalDecision: unsupportedDecision });
  assert.equal(canonical.actor_state, 'SPOT_NON_COUVERT');
  assertTransition(canonical, 'SPOT_NON_SUPPORTE');
  assert.equal(canonical.show_ev, false);
}

// ---------------------------------------------------------------------------
// 5. HERO_RECOMMENDATION_UNAVAILABLE -> DONNEES_INSUFFISANTES or SPOT_NON_SUPPORTE
//    according to the concrete cause carried by the reason code.
// ---------------------------------------------------------------------------
{
  const insufficient = api.replayHeroCommentState(0, { street: 'River' }, { status: 'done' });
  assert.equal(insufficient.actor_state, 'HERO_RECOMMENDATION_UNAVAILABLE');
  assertTransition(insufficient, 'DONNEES_INSUFFISANTES');

  const unsupported = api.heroAnalysisStateFromActor('HERO_RECOMMENDATION_UNAVAILABLE', { reasonCodes: ['NODE_ABSENT'] });
  assert.equal(unsupported.state, 'SPOT_NON_SUPPORTE');
  assert.equal(unsupported.model_support_status, 'NODE_ABSENT');
}

// ---------------------------------------------------------------------------
// 6. HERO_PENDING -> CALCUL_EN_COURS (never a scientific conclusion).
// ---------------------------------------------------------------------------
{
  const view = api.replayHeroCommentState(0, { street: 'Flop' }, { status: 'running' }, { actorState: 'HERO_PENDING' });
  assert.equal(view.actor_state, 'HERO_PENDING');
  assertTransition(view, 'CALCUL_EN_COURS');
  assert.equal(view.analysis_state.computational_status, 'PENDING');
  assert.equal(view.show_ev, false);
}

// ---------------------------------------------------------------------------
// 7. HERO_ANALYSIS_ERROR -> ERREUR_CALCUL, retryable.
// ---------------------------------------------------------------------------
{
  const view = api.replayHeroCommentState(0, { street: 'Flop' }, { status: 'error', error: 'worker timeout' }, { actorState: 'HERO_ANALYSIS_ERROR', reasonCodes: ['WORKER_ERROR'] });
  assert.equal(view.actor_state, 'HERO_ANALYSIS_ERROR');
  assertTransition(view, 'ERREUR_CALCUL');
  assert.equal(view.analysis_state.error.type, 'WORKER_ERROR');
  assert.equal(view.analysis_state.error.retryable, true);
  assert.equal(view.show_ev, false);
}

// ---------------------------------------------------------------------------
// 8. D6 at the rendering boundary: EV/recommendation only when admissible AND
//    comparable; reason codes only in the secondary detail.
// ---------------------------------------------------------------------------
{
  const compact = api.preflopDecisionCompactHtml(completeDecision);
  assert.ok(compact.includes('Analyse disponible'), compact);
  assert.ok(compact.includes('3BET'), compact);
  assert.ok(compact.includes('EV'), compact);

  // Force admissible=true but ev_comparable=false through the module.
  const partial = { ...completeDecision, ev_comparable: false };
  const partialView = api.heroDecisionView(partial);
  assert.equal(partialView.admissible, true);
  assert.equal(partialView.ev_comparable, false);
  assert.equal(partialView.show_ev, false);
  assert.equal(partialView.taxonomy_state, 'ANALYSE_PARTIELLE');
  const partialCompact = api.preflopDecisionCompactHtml(partial);
  assert.ok(partialCompact.includes('Analyse partielle'), partialCompact);
  assert.ok(!partialCompact.includes('3BET'), 'D6: recommended action must be absent');
  assert.ok(!partialCompact.includes('1.60'), 'D6: EV must be absent');

  // Unsupported: no EV/recommendation either.
  const unsupportedCompact = api.preflopDecisionCompactHtml(unsupportedDecision);
  assert.ok(unsupportedCompact.includes('Spot non supporté'), unsupportedCompact);
  assert.ok(!unsupportedCompact.includes('CALL') && !unsupportedCompact.includes('1.60'), unsupportedCompact);

  // The reason codes/dimensions only appear in the secondary detail view.
  assert.ok(!compact.includes('data-analysis-detail'), compact);
  const detail = api.preflopDecisionDetailHtml(completeDecision);
  assert.ok(detail.includes('data-analysis-detail="1"'), detail);
  assert.ok(detail.includes('raisons'), detail);

  const unsupportedDetail = api.preflopDecisionDetailHtml(unsupportedDecision);
  assert.ok(unsupportedDetail.includes('data-analysis-detail="1"'), unsupportedDetail);
  for (const code of unsupportedDecision.reason_codes) {
    assert.ok(unsupportedDetail.includes(code), `detail must expose reason code ${code}`);
  }
}

console.log(JSON.stringify({
  status: 'PASS',
  schema: State.SCHEMA,
  states: Object.keys(State.ANALYSIS_STATES).length,
  transitions: ['ANALYSE_DISPONIBLE', 'ANALYSE_PARTIELLE', 'CALCUL_EN_COURS', 'DONNEES_INSUFFISANTES', 'SPOT_NON_SUPPORTE', 'ERREUR_CALCUL'],
}));
