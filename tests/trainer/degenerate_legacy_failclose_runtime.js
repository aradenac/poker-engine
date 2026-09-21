'use strict';

// Runtime proof that `rangeEntriesForHistoryPlayer` never substitutes the legacy
// imported range for a degenerate population estimate (#391 · Point 3).
//
// The production function is extracted from `site/index.html` and evaluated with
// stubs for its free variables, so the test observes the real control flow:
//
// - a degenerate estimate (posteriorState === "degenerate") returns [] and the
//   legacy fallback is never called;
// - a non-degenerate estimate returns its entries unchanged;
// - the legacy imported range is returned only when no estimate exists at all
//   (no population model / historical imported path).
//
// No model/fit or equity-consumer surface is touched here.
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

const fnSource = section('function rangeEntriesForHistoryPlayer(', 'function resetSeatEquities(');

let legacyCalls = 0;
const legacySentinel = [{ hand: 'AA', frequency: 100, legacy: true }];
const defaultSentinel = [{ hand: 'KK', frequency: 50, defaultRange: true }];

const makeRangeFn = (estimate) => {
  const state = { replayIndex: 0, selectedHand: { heroName: 'Hero' }, rangeEdition: false, opponents: [] };
  legacyCalls = 0;
  const factory = new Function(
    'state',
    'defaultRangeEntriesForHistoryPlayer',
    'legacyUnderlyingRangeEntriesForOpponent',
    'legacyRangeEntriesForHistoryPlayer',
    'populationRangeEstimateForPlayer',
    `${fnSource}\nreturn rangeEntriesForHistoryPlayer;`,
  );
  return factory(
    state,
    () => defaultSentinel,
    () => {
      legacyCalls += 1;
      return legacySentinel;
    },
    () => {
      legacyCalls += 1;
      return legacySentinel;
    },
    () => estimate,
  );
};

const villain = { name: 'Villain' };

// 1. Degenerate posterior: fail closed, never the legacy imported range.
const degenerate = { posteriorState: 'degenerate', entries: [], gridEntries: [] };
assert.deepEqual(makeRangeFn(degenerate)(villain, 0), [], 'degenerate estimate must return []');
assert.equal(legacyCalls, 0, 'degenerate estimate must not call the legacy fallback');

// 2. Non-degenerate estimate: entries are returned unchanged.
const conditioned = { posteriorState: 'conditioned', entries: [{ hand: 'QQ', frequency: 100 }] };
assert.deepEqual(makeRangeFn(conditioned)(villain, 0), conditioned.entries, 'conditioned estimate must return its entries');

// 3. Defensive: a non-null estimate without entries still fails closed.
const emptyNonDegenerate = { posteriorState: 'conditioned', entries: [] };
assert.deepEqual(makeRangeFn(emptyNonDegenerate)(villain, 0), [], 'entry-less estimate must fail closed with []');
assert.equal(legacyCalls, 0, 'entry-less estimate must not call the legacy fallback');

// 4. No estimate at all (no population model / historical imported path): the
//    legacy imported range is preserved.
assert.deepEqual(makeRangeFn(null)(villain, 0), legacySentinel, 'no estimate must keep the legacy fallback');
assert.equal(legacyCalls, 1, 'the legacy fallback is reached only when no estimate exists');

console.log('degenerate legacy fail-close runtime: PASS');
