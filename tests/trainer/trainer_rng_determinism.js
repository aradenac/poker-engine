'use strict';

// Runtime non-regression for the #409 seedable randomness source of the Trainer.
//
// The RNG surface (`trainerMulberry32`, `trainerNormalizeSeed`,
// `trainerDefaultRandom`, `trainerRandom`, `trainerSetRandomSource`,
// `trainerSetSeed`, `trainerResetRandomSource`, `trainerRandomSeed` and the
// matching `window.trainer*` exports) is extracted verbatim from
// `site/trainer.js` between the explicit `#409-RNG-BLOCK-START` /
// `#409-RNG-BLOCK-END` markers used by `test_trainer_rng_determinism.py`. No DOM
// is loaded: only the isolated randomness block is evaluated, exactly like
// `range_width_scale_invariance.js` / `source_prior_unconditioned_runtime.js`.
//
// What is proven here:
// 1. Same seed  => byte-identical sequence.
// 2. Different seeds => different sequences.
// 3. `trainerSetRandomSource(fn)` installs an injected deterministic source and
//    rejects a non-function without clobbering the active source.
// 4. `trainerResetRandomSource()` restores the production default (identical to
//    `trainerDefaultRandom`, i.e. `Math.random`) and clears the seed.
//
// The default source is identified by identity (`currentSource() ===
// trainerDefaultRandom`); the global `Math.random` is never monkey-patched.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const TRAINER = fs.readFileSync(path.join(__dirname, '../../site/trainer.js'), 'utf8');

const START = '/* #409-RNG-BLOCK-START */';
const END = '/* #409-RNG-BLOCK-END */';

const start = TRAINER.indexOf(START);
assert.ok(start >= 0, `RNG block start marker not found: ${START}`);
const end = TRAINER.indexOf(END, start + START.length);
assert.ok(end >= 0, `RNG block end marker not found: ${END}`);
const block = TRAINER.slice(start, end + END.length);

// The block exposes the functions through `window.*`. Provide a minimal stub so
// the verbatim production lines run in Node; no other DOM global is needed.
globalThis.window = globalThis.window || {};

const api = new Function(
  `${block}\nreturn {trainerRandom,trainerSetRandomSource,trainerSetSeed,` +
    `trainerResetRandomSource,trainerRandomSeed,trainerMulberry32,trainerNormalizeSeed,` +
    `trainerDefaultRandom,currentSource(){return trainerRandomSource;}};`
)();

// The extracted block registers the documented #409 API on `window`.
for (const name of [
  'trainerSetRandomSource',
  'trainerSetSeed',
  'trainerResetRandomSource',
  'trainerRandomSeed',
]) {
  assert.equal(typeof globalThis.window[name], 'function', `window.${name} must be exported`);
  assert.equal(globalThis.window[name], api[name], `window.${name} must wrap the local API`);
}

const draw = (n) => Array.from({ length: n }, () => api.trainerRandom());

// ---- 0. Initial state: the production default source, no explicit seed ------
assert.equal(api.currentSource(), api.trainerDefaultRandom, 'initial source must be the default');
assert.equal(api.trainerRandomSeed(), null, 'initial seed must be null');

// ---- 1. Same seed => same sequence -----------------------------------------
api.trainerSetSeed(409);
assert.equal(api.trainerRandomSeed(), api.trainerNormalizeSeed(409), 'seed must be recorded');
assert.notEqual(api.currentSource(), api.trainerDefaultRandom, 'a seeded source must replace the default');
const seededA = draw(10);

api.trainerSetSeed(409);
const seededB = draw(10);
assert.deepEqual(seededA, seededB, 'same seed must reproduce the same sequence');

// No drift across a longer stream, and the values stay in the [0,1) contract.
api.trainerSetSeed(409);
const seededLong = draw(64);
assert.deepEqual(seededLong.slice(0, 10), seededA, 'the first draws must be stable');
for (const v of seededLong) {
  assert.equal(Number.isFinite(v), true, `random value must be finite: ${v}`);
  assert.ok(v >= 0 && v < 1, `random value must be in [0,1): ${v}`);
}

// A string seed is supported and just as deterministic (it hashes to its own
// normalized integer, which is distinct from the numeric seed).
api.trainerSetSeed('409');
const stringSeed1 = draw(10);
api.trainerSetSeed('409');
const stringSeed2 = draw(10);
assert.deepEqual(stringSeed1, stringSeed2, 'a string seed must be reproducible');
assert.equal(api.trainerRandomSeed(), api.trainerNormalizeSeed('409'), 'the string seed must be recorded');
assert.notDeepEqual(stringSeed1, seededA, 'a string seed normalizes to its own integer seed');

// ---- 2. Different seeds => different sequences -----------------------------
api.trainerSetSeed(410);
const seededC = draw(10);
assert.notDeepEqual(seededA, seededC, 'distinct seeds must produce distinct sequences');

const seeds = [0, 1, 2, 123456, 'issue-409', 'trainer'];
const streams = seeds.map((seed) => {
  api.trainerSetSeed(seed);
  return draw(12).join(',');
});
assert.equal(new Set(streams).size, seeds.length, 'every distinct seed must yield a distinct stream');

// The raw mulberry32 generator is itself seed-stable and bounded.
const g1 = api.trainerMulberry32(409);
const g2 = api.trainerMulberry32(409);
for (let i = 0; i < 32; i += 1) {
  assert.equal(g1(), g2(), 'mulberry32 must be deterministic per seed');
}
assert.notEqual(api.trainerMulberry32(1)(), api.trainerMulberry32(2)(), 'distinct mulberry32 seeds differ');

// ---- 3. trainerSetRandomSource installs an injected deterministic source ----
let cursor = 0;
const injectedSequence = [0.11, 0.22, 0.33, 0.44];
const injected = () => injectedSequence[cursor++ % injectedSequence.length];
api.trainerSetRandomSource(injected);
assert.equal(api.currentSource(), injected, 'the injected function must become the active source');
assert.equal(api.trainerRandomSeed(), null, 'an injected raw source clears the explicit seed');
assert.deepEqual(draw(4), injectedSequence, 'draws must reproduce the injected sequence');
assert.deepEqual(draw(4), injectedSequence, 'the injected source must keep driving the draws');

// A non-function is rejected without clobbering the active source.
assert.throws(() => api.trainerSetRandomSource(42), TypeError);
assert.throws(() => api.trainerSetRandomSource(null), TypeError);
assert.equal(api.currentSource(), injected, 'a rejected injection must not change the source');

// A constant injected source is fully deterministic (e.g. a fixed policy probe).
api.trainerSetRandomSource(() => 0.5);
assert.deepEqual(draw(3), [0.5, 0.5, 0.5], 'a constant injected source must return the constant');

// ---- 4. trainerResetRandomSource restores the production default -----------
api.trainerSetSeed(7);
assert.notEqual(api.currentSource(), api.trainerDefaultRandom);
api.trainerResetRandomSource();
assert.equal(api.currentSource(), api.trainerDefaultRandom, 'reset must restore the default source');
assert.equal(api.trainerRandomSeed(), null, 'reset must clear the explicit seed');

// The restored default no longer replays the seeded stream.
api.trainerSetSeed(409);
const seededBeforeReset = draw(16);
api.trainerResetRandomSource();
const afterReset = draw(16);
assert.notDeepEqual(afterReset, seededBeforeReset, 'reset must stop replaying the seeded stream');
for (const v of afterReset) {
  assert.equal(Number.isFinite(v), true, `default random value must be finite: ${v}`);
  assert.ok(v >= 0 && v < 1, `default random value must be in [0,1): ${v}`);
}

console.log('trainer rng determinism: PASS');
