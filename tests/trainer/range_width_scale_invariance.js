'use strict';

// Runtime proof that `populationRangeWidthFromEntries` is scale-invariant: the
// displayed “largeur relative” must not change when the same distribution is
// expressed as sum-normalized mass, as a max-normalized relative weight or as
// an a priori inclusion frequency. It also matches `exactComboRangeResult.width`
// (probabilityMass / n / maxWeight), which is 1 for a uniform distribution.
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

const source = section(
  'function populationRangeWidthFromEntries(entries){',
  '\nconst modalFocusOrigins',
);
const widthFromEntries = new Function(`${source}\nreturn populationRangeWidthFromEntries;`)();

// Empty/degenerate input fails closed with no width.
assert.equal(widthFromEntries([]), 0);
assert.equal(widthFromEntries([{ hand: 'AA', frequency: 0 }]), 0);

// A uniform distribution is maximally wide: mean / max = 1.
assert.equal(widthFromEntries([{ hand: 'AA', frequency: 100 }, { hand: 'KK', frequency: 100 }]), 1);

// Scale invariance: multiplying every weight by a constant is a no-op.
const base = [
  { hand: 'AA', frequency: 10 },
  { hand: 'KK', frequency: 30 },
  { hand: 'QQ', frequency: 2 },
];
const w1 = widthFromEntries(base);
const w2 = widthFromEntries(base.map(e => ({ hand: e.hand, frequency: e.frequency * 7.3 })));
const wMass = widthFromEntries(base.map(e => ({ hand: e.hand, frequency: 100 * e.frequency / 42 })));
assert.ok(Math.abs(w1 - w2) < 1e-12, `scale invariance: ${w1} vs ${w2}`);
assert.ok(Math.abs(w1 - wMass) < 1e-12, `mass compatibility: ${w1} vs ${wMass}`);

// It matches the canonical exact-combo width: probabilityMass / n / maxWeight.
const masses = [0.5, 0.25, 0.25];
const expected = 1 / Math.max(1, masses.length) / Math.max(...masses);
const computed = widthFromEntries(masses.map((m, i) => ({ hand: `h${i}`, frequency: 100 * m })));
assert.ok(Math.abs(computed - expected) < 1e-12, `canonical width: ${computed} vs ${expected}`);

// A concentrated distribution is narrower than the uniform one.
assert.ok(widthFromEntries([{ hand: 'AA', frequency: 99 }, { hand: 'KK', frequency: 1 }]) < 1);

console.log('range width scale invariance: PASS');
