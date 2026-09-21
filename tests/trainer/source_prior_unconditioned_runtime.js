'use strict';

// Runtime proof for the distinct `source_prior_unconditioned` posterior state.
//
// A non-uniform imported/source prior kept with zero matched public action must
// derive to `source_prior_unconditioned`, never to `prior_uninformative` (which
// is reserved for a uniform prior over the FULL legal support) and never to
// `degenerate`. The same holds for a uniform imported/source prior over a strict
// subset of the legal exact combos (a single class, an imported sub-range, or a
// support reduced by public blockers): uniform weights alone are not enough, the
// support must cover every legal combo. It is rendered as an explicit state, so
// `gridFreqMapFromEstimate` returns no numeric grid and the canonical mass
// projection can never read as a 100 % range.
//
// The functions are extracted from `site/index.html` and evaluated in isolation,
// exactly like `range_width_scale_invariance.js`; no model/fit surface is touched.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const INDEX = fs.readFileSync(path.join(__dirname, '../../site/index.html'), 'utf8');

function section(start, end) {
  const i = INDEX.indexOf(start);
  assert.ok(i >= 0, `section start not found: ${start}`);
  const j = INDEX.indexOf(end, i + start.length);
  assert.ok(j >= 0, `section end not found: ${end}`);
  return INDEX.slice(i, j);
}

const source = [
  'const RANKS=["2","3","4","5","6","7","8","9","T","J","Q","K","A"];',
  'const SUITS=[{c:"s"},{c:"h"},{c:"d"},{c:"c"}];',
  section('function cardCode(id){', 'function cardLabel(id){'),
  section('function cardsToNotation(cards){', 'function exactHandCode(cards){'),
  section('function matrixNotations(){', 'function rangeEditKey(index){'),
  section('function normalizeComboWeightsToMass(combos){', '/* Diagnostic-only'),
  section('function normalizeComboWeightsInPlace(combos){', '/* A non-informative prior'),
  section('function comboWeightsAreUniform(combos){', '/* Canonical 169 projection'),
  section('function projectCombosTo169Mass(combos){', 'function uniformExactComboPrior('),
  section('function uniformExactComboPrior(', 'function exactComboRangeResult('),
  section('function exactComboRangeResult(combos,meta={}){', '/* Fail-closed posterior result'),
  section('function massGridFreqMapFromEstimate(estimate){', 'function gridFreqMapFromEstimate('),
  section('function gridFreqMapFromEstimate(estimate,player){', 'function openPopulationRangeModal('),
  'return {exactComboRangeResult,gridFreqMapFromEstimate,comboWeightsAreUniform,priorIsNonInformative,uniformExactComboPrior,projectCombosTo169Mass,cardsToNotation};',
].join('\n');

const api = new Function(source)();
const copyCombos = (combos) => combos.map((c) => ({ cards: [c.cards[0], c.cards[1]], weight: Number(c.weight) || 0 }));

// 1. Full-support uniform legal-combo prior with no matched action stays
//    `prior_uninformative`.
const uniform = api.exactComboRangeResult(copyCombos(api.uniformExactComboPrior([])), { informativeActions: 0 });
assert.equal(uniform.posteriorState, 'prior_uninformative', 'uniform prior must stay prior_uninformative');
assert.equal(uniform.uniformPrior, true);

// 2. Non-uniform imported/source prior with zero matched action is the distinct
//    `source_prior_unconditioned`, never assimilated to the two other states.
const imported = api.uniformExactComboPrior([]).map((c) => ({
  cards: [c.cards[0], c.cards[1]],
  // Deterministic non-uniform a priori weights (all strictly positive).
  weight: ((c.cards[0] % 13) + 1) * 1.5 + (c.cards[1] % 7),
}));
assert.equal(api.comboWeightsAreUniform(imported), false, 'fixture must be non-uniform');
const sourcePrior = api.exactComboRangeResult(imported, { informativeActions: 0 });
assert.equal(sourcePrior.posteriorState, 'source_prior_unconditioned', 'non-uniform prior must be source_prior_unconditioned');
assert.notEqual(sourcePrior.posteriorState, 'prior_uninformative');
assert.notEqual(sourcePrior.posteriorState, 'degenerate');
assert.equal(sourcePrior.uniformPrior, false);
assert.equal(sourcePrior.informativeActions, 0);

// 3. The UI fails closed for this state: no numeric grid, and the canonical mass
//    projection never reads as a 100 % range.
assert.equal(api.gridFreqMapFromEstimate(sourcePrior, null).size, 0, 'source prior must not render a numeric grid');
const massMax = Math.max(0, ...(sourcePrior.gridEntries || []).map((e) => Number(e.frequency) || 0));
const massSum = (sourcePrior.gridEntries || []).reduce((s, e) => s + (Number(e.frequency) || 0), 0);
assert.ok(massMax < 100, `source prior mass must stay below 100 %, got ${massMax}`);
assert.ok(Math.abs(massSum - 100) < 1e-6, `source prior mass must sum to 100, got ${massSum}`);

// 4. One matched action conditions the same distribution: the state becomes
//    `conditioned` (only the action count decides, not the prior shape).
const conditioned = api.exactComboRangeResult(copyCombos(imported), { informativeActions: 1 });
assert.equal(conditioned.posteriorState, 'conditioned');
assert.equal(api.gridFreqMapFromEstimate(conditioned, null).size > 0, true);

// 5. A uniform imported/source prior over a strict subset (here every combo of a
//    single hand class) is NOT the non-informative prior: the weights are
//    uniform but the support does not cover all legal exact combos, so the state
//    must be the distinct `source_prior_unconditioned`, never
//    `prior_uninformative` and never `degenerate`.
const singleClassCombos = api.uniformExactComboPrior([]).filter(
  (c) => api.cardsToNotation(c.cards) === 'AA'
);
assert.ok(singleClassCombos.length > 0 && singleClassCombos.length < 1326, 'fixture must be a strict subset');
assert.equal(api.comboWeightsAreUniform(singleClassCombos), true, 'fixture must be uniform');
assert.equal(api.priorIsNonInformative(singleClassCombos, []), false, 'strict subset is not full support');
const subsetPrior = api.exactComboRangeResult(copyCombos(singleClassCombos), { informativeActions: 0 });
assert.equal(subsetPrior.posteriorState, 'source_prior_unconditioned', 'uniform strict subset must be source_prior_unconditioned');
assert.notEqual(subsetPrior.posteriorState, 'prior_uninformative');
assert.notEqual(subsetPrior.posteriorState, 'degenerate');
assert.equal(subsetPrior.uniformPrior, true, 'weights are still uniform; only the full-support state is withheld');
assert.equal(api.gridFreqMapFromEstimate(subsetPrior, null).size, 0, 'uniform subset must not render a numeric grid');

// 6. The full-support test counts the PUBLIC blockers: the same uniform combos
//    are the non-informative prior for their own blocker set, but a support
//    reduced by blockers (a strict subset of the unblocked legal set) is a source
//    prior, never `prior_uninformative` and never `degenerate`.
const heroBlock = [0, 1, 2, 3];
const legalUniform = api.uniformExactComboPrior(heroBlock);
assert.ok(legalUniform.length < 1326, 'fixture must remove some legal combos');
assert.equal(api.priorIsNonInformative(legalUniform, heroBlock), true, 'full support after blockers is non-informative');
assert.equal(api.priorIsNonInformative(legalUniform, []), false, 'a strict subset of the unblocked legal combos is not full support');
const legalEstimate = api.exactComboRangeResult(copyCombos(legalUniform), { informativeActions: 0, blockedCards: heroBlock });
assert.equal(legalEstimate.posteriorState, 'prior_uninformative', 'full-support uniform after blockers stays prior_uninformative');
const blockedEstimate = api.exactComboRangeResult(copyCombos(legalUniform), { informativeActions: 0 });
assert.equal(blockedEstimate.posteriorState, 'source_prior_unconditioned', 'support reduced by blockers is a source prior');
assert.notEqual(blockedEstimate.posteriorState, 'prior_uninformative');
assert.notEqual(blockedEstimate.posteriorState, 'degenerate');

console.log('source prior unconditioned runtime: PASS');
