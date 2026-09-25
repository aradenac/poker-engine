#!/usr/bin/env node
/*
 * Node probe of the #395 T7 Review-inbox large-list fixture.
 *
 * It answers one question: *what does the served application see* in the
 * committed fixture? The probe
 *
 *   1. extracts the real hand-history parser of the served desktop shell
 *      (`parsePokerStarsHand`, `parseHandTimeline`, `computeHeroHandResult`,
 *      `makeReplaySteps`, `handNetBB`, …) out of `site/index.html` — the file
 *      carries those functions verbatim — and evaluates them on the fixture
 *      bytes, so the real net settlement, the real button/position mapping and
 *      the real replay step indices are measured, never re-implemented;
 *   2. replays the same hands through the real `poker-review-inbox/v1`
 *      analytics modules (`src/analytics/*`, byte-identical to their `site/`
 *      mirror) with one injected `review_score` per hand, and reports the built
 *      items (loss, real result, position, deep link) and the orders the five
 *      first-level sorts produce;
 *   3. writes it all as JSON on stdout.
 *
 * `tests/trainer/test_review_inbox_large_list_smoke_contract.py` runs this probe
 * and compares its output with the expectations the browser smoke asserts, so
 * the smoke can never pass by asserting against its own arithmetic.
 *
 * Usage: node tests/trainer/fixtures/review_inbox_large_list_probe.js <fixture> <payload-json>
 *   payload: {"hands":{"<hand_id>":{"loss_bb":<number>}}, ...}
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.resolve(__dirname, '..', '..', '..');
const fixturePath = path.resolve(ROOT, process.argv[2]);
const payload = JSON.parse(process.argv[3]);
const fixtureText = fs.readFileSync(fixturePath, 'utf8');

/* --- exact single-file extraction of the served shell functions ------------ */
const appSource = fs.readFileSync(path.join(ROOT, 'site', 'index.html'), 'utf8');
const REGEX_PREV = new Set(['(', ',', '=', ':', '[', '!', '&', '|', '?', '{', '}', ';', '+', '-', '*', '%', '~', '^', '<', '>']);
const REGEX_KEYWORDS = new Set(['return', 'typeof', 'case', 'instanceof', 'in', 'of', 'new', 'delete', 'void', 'do', 'else', 'yield', 'await']);

function regexStart(text, i) {
  let j = i - 1;
  while (j >= 0 && /\s/.test(text[j])) j--;
  if (j < 0) return true;
  const c = text[j];
  if (REGEX_PREV.has(c)) return true;
  if (/[A-Za-z0-9_$]/.test(c)) {
    let k = j;
    while (k >= 0 && /[A-Za-z0-9_$]/.test(text[k])) k--;
    return REGEX_KEYWORDS.has(text.slice(k + 1, j + 1));
  }
  return false;
}
function regexEnd(text, i) {
  let j = i + 1, inClass = false;
  while (j < text.length) {
    const c = text[j];
    if (c === '\\') { j += 2; continue; }
    if (c === '[') inClass = true;
    else if (c === ']') inClass = false;
    else if (c === '/' && !inClass) { j++; while (j < text.length && /[a-z]/.test(text[j])) j++; return j; }
    else if (c === '\n') return j;
    j++;
  }
  return j;
}
function stringEnd(text, i, quote) {
  let j = i + 1;
  while (j < text.length) {
    if (text[j] === '\\') { j += 2; continue; }
    if (text[j] === quote) return j + 1;
    if (text[j] === '\n') return j + 1;
    j++;
  }
  return j;
}
function scanBraced(text, j) {
  let depth = 1;
  while (j < text.length) {
    const c = text[j];
    if (c === '"' || c === "'" || c === '`') { j = tokenEnd(text, j); continue; }
    if (c === '/' && (text[j + 1] === '/' || text[j + 1] === '*')) { j = tokenEnd(text, j); continue; }
    if (c === '/' && regexStart(text, j)) { j = regexEnd(text, j); continue; }
    if (c === '{') depth++;
    else if (c === '}') { depth--; if (depth === 0) return j + 1; }
    j++;
  }
  return j;
}
function templateEnd(text, i) {
  let j = i + 1;
  while (j < text.length) {
    const c = text[j];
    if (c === '\\') { j += 2; continue; }
    if (c === '`') return j + 1;
    if (c === '$' && text[j + 1] === '{') { j = scanBraced(text, j + 2); continue; }
    j++;
  }
  return j;
}
function tokenEnd(text, i) {
  const c = text[i];
  if (c === '"' || c === "'") return stringEnd(text, i, c);
  if (c === '`') return templateEnd(text, i);
  if (c === '/' && text[i + 1] === '/') { const k = text.indexOf('\n', i); return k < 0 ? text.length : k + 1; }
  if (c === '/' && text[i + 1] === '*') { const k = text.indexOf('*/', i); return k < 0 ? text.length : k + 2; }
  if (c === '/' && regexStart(text, i)) return regexEnd(text, i);
  return i + 1;
}
function braceBlock(text, open) {
  let depth = 0, i = open;
  while (i < text.length) {
    const c = text[i];
    if (c === '"' || c === "'" || c === '`' || c === '/') {
      const next = tokenEnd(text, i);
      if (next !== i + 1) { i = next; continue; }
    }
    if (c === '{') depth++;
    else if (c === '}') { depth--; if (depth === 0) return text.slice(open, i + 1); }
    i++;
  }
  throw new Error('unbalanced block in site/index.html');
}

const definitions = new Map();
for (const match of appSource.matchAll(/^function ([A-Za-z_$][\w$]*)\s*\(/gm)) {
  const start = match.index;
  let j = appSource.indexOf('(', start), depth = 0;
  for (; j < appSource.length; j++) {
    const c = appSource[j];
    if (c === '"' || c === "'" || c === '`' || c === '/') {
      const next = tokenEnd(appSource, j);
      if (next !== j + 1) { j = next - 1; continue; }
    }
    if (c === '(') depth++;
    else if (c === ')') { depth--; if (depth === 0) break; }
  }
  const open = appSource.indexOf('{', j);
  const body = braceBlock(appSource, open);
  definitions.set(match[1], appSource.slice(start, start + (open - start) + body.length));
}
for (const match of appSource.matchAll(/^(?:const|let|var)[ \t]+([A-Za-z_$][\w$]*)[ \t]*=[ \t]*([^\n]*)$/gm)) {
  if (match[0].includes('=>') || definitions.has(match[1])) continue;
  const rhs = match[2].trim();
  if (!(rhs.endsWith('{') || rhs.endsWith('[') || rhs.endsWith('('))) {
    definitions.set(match[1], match[0]);
    continue;
  }
  // Multi-line initializer: capture it with the same token scanner.
  const eq = appSource.indexOf('=', match.index);
  let j = eq + 1, depth = 0;
  while (j < appSource.length) {
    const c = appSource[j];
    if (c === '"' || c === "'" || c === '`' || c === '/') {
      const next = tokenEnd(appSource, j);
      if (next !== j + 1) { j = next; continue; }
    }
    if ('{[('.includes(c)) depth++;
    else if ('}])'.includes(c)) depth--;
    else if (c === ';' && depth === 0) { j++; break; }
    j++;
  }
  definitions.set(match[1], appSource.slice(match.index, j));
}

const ROOTS = [
  'parsePokerStarsHand', 'splitPokerStarsHands', 'makeReplaySteps', 'handNetBB',
  'reviewHeroCardsText', 'reviewActualResult',
];
const wanted = new Set(ROOTS);
const queue = [...ROOTS];
while (queue.length) {
  const name = queue.pop();
  const body = definitions.get(name);
  if (!body) throw new Error('missing served definition: ' + name);
  for (const token of body.matchAll(/(?<![.\w$])([A-Za-z_$][\w$]*)(?![\w$]*\s*:)/g)) {
    const candidate = token[1];
    if (candidate === 'state' || wanted.has(candidate)) continue;
    if (definitions.has(candidate)) { wanted.add(candidate); queue.push(candidate); }
  }
}

const sandbox = {
  console, Math, JSON, Number, String, Object, Array, Set, Map, Intl,
  parseFloat, parseInt, isNaN, NaN, Infinity,
};
vm.createContext(sandbox);
vm.runInContext([...wanted].map(name => definitions.get(name)).join('\n'), sandbox);

/* --- the real analytics contract ------------------------------------------ */
const Leak = require(path.join(ROOT, 'src/analytics/leak-analyzer.js'));
const Adapter = require(path.join(ROOT, 'src/analytics/review-score-adapter.js'));
const Inbox = require(path.join(ROOT, 'src/analytics/review-inbox.js'));

const SCOPE = {
  population_id: 'review-local',
  pack_id: null,
  strategy_id: 'UNAVAILABLE_STRATEGY',
  strategy_version: 'UNAVAILABLE@UNAVAILABLE',
  ev_reference: Adapter.DEFAULT_EV_REFERENCE,
};
const ANALYZABLE = step => (['call', 'bet', 'raise'].includes(step.actionType))
  || (['FLOP', 'TURN', 'RIVER'].includes(step.street) && ['check', 'fold'].includes(step.actionType));

const blocks = sandbox.splitPokerStarsHands(fixtureText);
const reviewScores = {};
const handResults = {};
const hands = [];
for (const block of blocks) {
  const hand = sandbox.parsePokerStarsHand(block, path.basename(fixturePath));
  if (!hand) { hands.push({ hand_id: null, parsed: false }); continue; }
  const steps = sandbox.makeReplaySteps(hand);
  const net = sandbox.handNetBB(hand);
  const decisionStep = steps.findIndex((step, index) => index > 0 && ANALYZABLE(step)
    && step.activePlayer === hand.heroName);
  hands.push({
    hand_id: String(hand.id),
    timestamp: hand.dateText,
    hero_position: hand.players.find(player => player.name === hand.heroName)?.hhPosition || null,
    big_blind: hand.bigBlind,
    hero_net: hand.heroResult.net,
    net_bb: Number.isFinite(net) ? net : null,
    replay_step_index: decisionStep < 0 ? null : decisionStep,
    // The decision the inbox deep-links to must be the Hero's own decision in
    // the served replay, not merely an index that happens to exist.
    replay_step: decisionStep < 0 ? null : {
      street: steps[decisionStep].street,
      actor: steps[decisionStep].activePlayer,
      action_type: steps[decisionStep].actionType,
      action_text: steps[decisionStep].actionText,
    },
    replay_step_count: steps.length,
    hero_cards: sandbox.reviewHeroCardsText(hand),
    result_text: sandbox.reviewActualResult(hand).state,
  });
  const spec = (payload.hands || {})[String(hand.id)] || { loss_bb: 0 };
  const parsed = Adapter.parseStoredHand(block, path.basename(fixturePath));
  const details = [];
  if (spec.loss_bb > 0 && parsed) {
    for (const step of parsed.steps) {
      if (step.player !== parsed.heroName || !ANALYZABLE(step)) continue;
      details.push({
        stepIndex: step.stepIndex,
        bestLabel: 'CALL',
        chosenEV: 0,
        bestEV: spec.loss_bb,
        rawLossBB: spec.loss_bb,
        lossBB: spec.loss_bb,
        comparable: true,
        withinNoise: false,
        simContext: { potType: 'SRP', preflopRole: 'CALLER', relativePosition: 'IP' },
      });
    }
  }
  reviewScores[String(hand.id)] = {
    signature: 'SMOKE',
    complete: details.length > 0,
    analyzableDecisions: details.length,
    finishedDecisions: details.length,
    details,
  };
  handResults[String(hand.id)] = Number.isFinite(net) ? net : null;
}

const inbox = Inbox.buildReviewInbox({
  reviewScores,
  hhSources: [{ name: path.basename(fixturePath), content: fixtureText }],
  scope: SCOPE,
  hand_results: handResults,
});
const items = inbox.items.map(item => ({
  hand_id: item.hand_id,
  timestamp: item.timestamp,
  position: item.position,
  total_loss_bb: item.total_loss_bb,
  result: item.result.state,
  net_bb: item.hero_net_bb,
  status: item.status,
  coverage: item.coverage.state,
  costliest_step: item.costliest_decision ? item.costliest_decision.step_index : null,
  deep_link_step: item.deep_link ? item.deep_link.step_index : null,
  decision_id: item.deep_link ? item.deep_link.decision_id : null,
}));
const orders = {};
for (const mode of ['TIMESTAMP_DESC', 'TIMESTAMP_ASC', 'RESULT_GAIN_DESC', 'RESULT_LOSS_DESC', 'EV_LOSS_DESC']) {
  orders[mode] = Inbox.queryInbox(inbox, {}, mode).items.map(item => item.hand_id);
}
for (const state of ['WIN', 'LOSS', 'EVEN', 'UNKNOWN']) {
  orders['RESULT_' + state] = Inbox.queryInbox(inbox, { result: state }, 'TIMESTAMP_DESC')
    .items.map(item => item.hand_id);
}

process.stdout.write(JSON.stringify({
  schema: 'poker-review-inbox-large-list-probe/v1',
  fixture: path.relative(ROOT, fixturePath).split(path.sep).join('/'),
  block_count: blocks.length,
  warnings: inbox.warnings,
  scope_key: inbox.scope_key,
  hands,
  items,
  orders,
}, null, 1));
