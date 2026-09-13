// Exercise the production worker source through the arena's actual Blob/Worker hooks.
const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const html = fs.readFileSync(path.join(root, 'site/index.html'), 'utf8');
const start = html.indexOf('function createPostflopBetRaiseEVWorker(){');
const end = html.indexOf('\n}', start) + 2;
const runtime = fs.readFileSync(path.join(root, 'tools/simulation/oracle_runtime.js'), 'utf8');
function run(seed, trials) {
  class Blob { constructor(parts) { this.source = parts.join(''); } }
  class Worker {
    constructor(blob) {
      this.listeners = [];
      const handlers = [];
      this.context = vm.createContext({});
      this.context.self = this.context;
      this.context.addEventListener = (_, fn) => handlers.push(fn);
      this.context.postMessage = data => this.listeners.forEach(fn => fn({data}));
      vm.runInContext(blob.source, this.context);
      this.handlers = handlers;
    }
    addEventListener(_, fn) { this.listeners.push(fn); }
    postMessage(data) {
      for (const fn of this.handlers) fn({data});
      this.context.onmessage({data});
    }
  }
  const context = vm.createContext({Blob, Worker, URL: {createObjectURL: x => x}});
  context.window = context;
  vm.runInContext(`(${runtime})`, context)({trials});
  context.__arenaReset(seed);
  vm.runInContext(html.slice(start, end), context);
  const worker = context.createPostflopBetRaiseEVWorker();
  let result;
  worker.addEventListener('message', e => result = e.data);
  worker.postMessage({actor: {hands: [{hand: 'AKs', frequency: 100}]},
    responders: [{hands: [{hand: 'QQ', frequency: 100, response: {fold: .2, call: .8, raise: 0}}],
      callAmountBB: 10, effectiveActorCostBB: 10}],
    board: [0, 18, 34], potBeforeBB: 10, costBB: 10, actorAllIn: true, trials: 6000});
  assert.equal(result.type, 'result');
  assert.equal(result.out.trials, trials);
  assert.equal(context.__arena.errors.length, 0);
  return JSON.stringify(result);
}
assert.equal(run(123, 1200), run(123, 1200));
assert.notEqual(run(123, 1200), run(124, 1200));
assert.notEqual(run(123, 1200), run(123, 2400));
console.log('Production worker: fixed seed reproduces, changed seed changes output, 1200/2400 effective trials verified.');
