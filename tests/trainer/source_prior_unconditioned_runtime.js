'use strict';

// Runtime proof for the distinct `source_prior_unconditioned` posterior state.
//
// A non-uniform imported/source prior kept with zero matched public action must
// derive to `source_prior_unconditioned`, never to `prior_uninformative` (which
// is reserved for a uniform legal-combo prior) and never to `degenerate`. It is
// rendered as an explicit state, so `gridFreqMapFromEstimate` returns no numeric
// grid and the canonical mass projection can never read as a 100 % range.
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
  'return {exactComboRangeResult,gridFreqMapFromEstimate,comboWeightsAreUniform,uniformExactComboPrior,projectCombosTo169Mass};',
].join('\n');

const api = new Function(source)();
const copyCombos = (combos) => combos.map((c) => ({ cards: [c.cards[0], c.cards[1]], weight: Number(c.weight) || 0 }));

// 1. Uniform legal-combo prior with no matched action stays `prior_uninformative`.
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

console.log('source prior unconditioned runtime: PASS');
