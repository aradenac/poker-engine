#!/usr/bin/env python3
"""Numeric browser smoke for the opponent-range representation layer (#391 · task-tn5).

It serves `site/index.html` through the same static HTTP shape as the trainer
smoke and drives the real in-page functions with `page.evaluate`. Ten
scenarios are exercised at the numeric level:

1.  non-informative/uniform prior;
2.  one informative preflop action;
3.  several sequential conditioning actions;
4.  postflop conditioning plus public hero/board blockers;
5.  known-hand override (a separate mechanism, not a posterior);
6.  no exploitable action (prior preserved, never degenerate);
7.  degenerate / zero-mass posterior, fail-closed;
8.  mass sums and the 169 class projection are coherent;
9.  no generalized 100 % cell without justification;
10. a deliberately non-uniform imported/source range with zero matched public
    action derives the distinct `source_prior_unconditioned` state (neither
    `prior_uninformative` nor `degenerate`, no 100 % cell, no numeric grid),
    while a public board that removes all of its mass fails closed as
    `degenerate` and `rangeEntriesForHistoryPlayer` never substitutes the
    legacy imported range.

Representation/display only: it never changes the model/fit, and it never reads
an unrevealed opponent card or any future information (public hero/board
blockers only).

The anti-regression assertion block verifies that the canonical posterior
output must stay **sum-normalized** (`normalizeComboWeightsToMass`, entries sum
to 100, max < 100 for a non-uniform distribution). If the max normalization
`normalizeComboWeightsInPlace` is reintroduced as the canonical output, the sum
check and the max check both fail, and the in-page source check fails.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8765/index.html"
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/opponent-range/numeric_scenarios.json"
INDEX = ROOT / "site/index.html"


def approx(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(float(a) - float(b)) <= tol


# ---- static side of the anti-regression guard --------------------------------
def static_guards() -> None:
    source = INDEX.read_text(encoding="utf-8")
    assert "function normalizeComboWeightsToMass(combos){" in source
    assert "function normalizeComboWeightsInPlace(combos){" in source
    result_fn = source.split("function exactComboRangeResult(combos,meta={}){", 1)[1].split(
        "/* Fail-closed posterior result", 1
    )[0]
    assert "normalizeComboWeightsToMass(combos)" in result_fn, (
        "exactComboRangeResult must normalize by the retained mass"
    )
    assert "normalizeComboWeightsInPlace" not in result_fn, (
        "max normalization must never be the canonical posterior output"
    )


async def main() -> None:
    cfg = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert cfg["schema"] == "poker-opponent-range-numeric-scenarios/v1", cfg.get("schema")
    static_guards()

    page_errors: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        await page.goto(URL, wait_until="domcontentloaded", timeout=45_000)

        result = await page.evaluate(
            """(cfg) => {
                const sum = a => a.reduce((x, y) => x + Math.max(0, Number(y) || 0), 0);
                const entriesSum = es => sum((es || []).map(e => e.frequency));
                const gridSum = gs => sum((gs || []).map(e => e.frequency));
                const gridMax = gs => Math.max(0, ...(gs || []).map(e => Number(e.frequency) || 0));
                const countAt100 = gs => (gs || []).filter(e => Math.abs(Number(e.frequency) - 100) < 1e-6).length;
                const copyCombos = cs => (cs || []).map(c => ({ cards: [c.cards[0], c.cards[1]], weight: Number(c.weight) || 0 }));
                const policyFor = (policy, hand) => Object.prototype.hasOwnProperty.call(policy, hand)
                    ? Number(policy[hand])
                    : Number(policy.__default__ ?? 1);
                const conditionOnce = (base, policy, informativeActions) => {
                    const cs = copyCombos(base);
                    for (const c of cs) c.weight *= Math.max(0, policyFor(policy, cardsToNotation(c.cards)));
                    const ok = normalizeComboWeightsToMass(cs);
                    const out = ok ? exactComboRangeResult(cs, { informativeActions }) : null;
                    return { combos: cs, ok, result: out };
                };
                // Independent 169 projection: group the normalized exact-combo
                // probabilities by class and sum them (never a mean, never a max).
                const classMassFromCombos = combos => {
                    let total = 0;
                    for (const c of combos) total += Math.max(0, Number(c.weight) || 0);
                    const mass = Object.create(null);
                    if (total > 0) {
                        for (const c of combos) {
                            const key = cardsToNotation(c.cards);
                            mass[key] = (mass[key] || 0) + Math.max(0, Number(c.weight) || 0) / total;
                        }
                    }
                    return new Map(ALL_NOTATIONS.map(h => [h, 100 * (mass[h] || 0)]));
                };
                const gridMap = gs => new Map((gs || []).map(e => [e.hand, Number(e.frequency) || 0]));
                const mapDiff = (a, b) => {
                    const keys = new Set([...a.keys(), ...b.keys()]);
                    let d = 0;
                    for (const k of keys) d = Math.max(d, Math.abs((a.get(k) || 0) - (b.get(k) || 0)));
                    return d;
                };
                const mapL1 = (a, b) => {
                    const keys = new Set([...a.keys(), ...b.keys()]);
                    let d = 0;
                    for (const k of keys) d += Math.abs((a.get(k) || 0) - (b.get(k) || 0));
                    return d;
                };

                const R = {};

                // ---- 1. non-informative / uniform prior --------------------
                const priorCombos = uniformExactComboPrior([]);
                const prior = exactComboRangeResult(copyCombos(priorCombos), { informativeActions: 0 });
                R.sc1 = {
                    state: prior.posteriorState,
                    uniformPrior: prior.uniformPrior,
                    informativeActions: prior.informativeActions,
                    comboCount: prior.comboCount,
                    entriesSum: entriesSum(prior.entries),
                    gridSum: gridSum(prior.gridEntries),
                    gridLen: prior.gridEntries.length,
                    gridMax: gridMax(prior.gridEntries),
                    grid100: countAt100(prior.gridEntries),
                    relativeNull: (prior.entries || []).every(e => e.relativeWeightPct === null),
                    width: prior.width,
                    probabilityMass: prior.probabilityMass,
                    gridMapSize: gridFreqMapFromEstimate(prior, null).size
                };

                // ---- 2. one informative preflop action ---------------------
                const s2 = conditionOnce(priorCombos, cfg.preflop_policy, 1);
                const aaMass = (s2.result.gridEntries.find(e => e.hand === "AA") || {}).frequency || 0;
                const massMap2 = massGridFreqMapFromEstimate(s2.result);
                R.sc2 = {
                    state: s2.result.posteriorState,
                    informativeActions: s2.result.informativeActions,
                    uniformPrior: s2.result.uniformPrior,
                    entriesSum: entriesSum(s2.result.entries),
                    gridSum: gridSum(s2.result.gridEntries),
                    gridMax: gridMax(s2.result.gridEntries),
                    relativeMax: Math.max(0, ...s2.result.entries.map(e => Number(e.relativeWeightPct) || 0)),
                    relativeNullCount: s2.result.entries.filter(e => e.relativeWeightPct === null).length,
                    width: s2.result.width,
                    aaMass,
                    massMapAAA: Number(massMap2.get("AA") || 0),
                    massMapSize: massMap2.size
                };

                // ---- 3. several sequential conditioning actions ------------
                const s3a = conditionOnce(priorCombos, cfg.preflop_policy, 1);
                const s3b = conditionOnce(s3a.combos, cfg.second_policy, 2);
                R.sc3 = {
                    state: s3b.result.posteriorState,
                    informativeActions: s3b.result.informativeActions,
                    entriesSum: entriesSum(s3b.result.entries),
                    gridSum: gridSum(s3b.result.gridEntries),
                    gridMax: gridMax(s3b.result.gridEntries),
                    l1Between: mapL1(gridMap(s3a.result.gridEntries), gridMap(s3b.result.gridEntries)),
                    width1: s3a.result.width,
                    width2: s3b.result.width
                };

                // ---- 4. postflop conditioning plus public blockers ---------
                const heroCards = cfg.hero_cards.map(parseCardCode);
                const board = cfg.flop_board.map(parseCardCode);
                const blockedSet = new Set([...heroCards, ...board]);
                const pre4 = conditionOnce(priorCombos, cfg.preflop_policy, 1);
                const filtered = filterComboBlockers(copyCombos(pre4.combos), [...heroCards, ...board]);
                const ok4 = normalizeComboWeightsToMass(filtered);
                const post4 = ok4 ? exactComboRangeResult(filtered, { informativeActions: 2, posteriorState: "conditioned" }) : null;
                R.sc4 = {
                    ok: ok4,
                    state: post4 ? post4.posteriorState : null,
                    blockedFree: filtered.every(c => !blockedSet.has(c.cards[0]) && !blockedSet.has(c.cards[1])),
                    comboCount: filtered.length,
                    beforeCount: pre4.combos.length,
                    entriesSum: entriesSum(post4.entries),
                    gridSum: gridSum(post4.gridEntries),
                    gridMax: gridMax(post4.gridEntries),
                    classDiff: mapDiff(classMassFromCombos(filtered), gridMap(post4.gridEntries))
                };

                // ---- 5. known-hand override (separate mechanism) -----------
                const knownCards = cfg.known_opponent_cards.map(parseCardCode);
                const override = exactEntriesFromCards(knownCards);
                const newEntry = knownHandOverrideEntry(knownCards);
                R.sc5 = {
                    count: override.length,
                    isArray: Array.isArray(override),
                    newEntryIsArray: Array.isArray(newEntry),
                    sameHand: override.length === 1 && newEntry.length === 1
                        && override[0].hand === newEntry[0].hand && override[0].frequency === newEntry[0].frequency,
                    hand: override[0] ? override[0].hand : null,
                    expectedHand: exactHandCode(knownCards),
                    frequency: override[0] ? override[0].frequency : null,
                    flagged: !!(override[0] && override[0].knownHandOverride === true),
                    isOverride: entriesAreKnownHandOverride(override),
                    explicitEmpty: exactEntriesFromCards([]).length,
                    newEntryEmpty: knownHandOverrideEntry([]).length,
                    posteriorState: override[0] && override[0].posteriorState ? override[0].posteriorState : null,
                    priorGridSize: gridFreqMapFromEstimate(prior, null).size
                };

                // ---- 6. no exploitable action (prior preserved) ------------
                const noAction = exactComboRangeResult(copyCombos(priorCombos), {
                    informativeActions: 0, matchedActions: 0, totalActions: 3
                });
                R.sc6 = {
                    state: noAction.posteriorState,
                    isDegenerate: noAction.posteriorState === "degenerate",
                    gridMapSize: gridFreqMapFromEstimate(noAction, null).size,
                    entriesSum: entriesSum(noAction.entries),
                    probabilityMass: noAction.probabilityMass
                };

                // ---- 7. degenerate / zero-mass posterior, fail-closed ------
                const dc = cfg.degenerate_single_combo.map(parseCardCode);
                const zeroCombos = [{ cards: [dc[0], dc[1]], weight: 0 }];
                const normZero = normalizeComboWeightsToMass(copyCombos(zeroCombos));
                const single = [{ cards: [dc[0], dc[1]], weight: 5 }];
                const removed = filterComboBlockers(single, [parseCardCode(cfg.degenerate_blocker)]);
                const normBlocked = normalizeComboWeightsToMass(copyCombos(removed));
                const deg = degenerateComboRangeResult({
                    degenerateReason: "postflop_blockers_zero_mass", informativeActions: 3
                });
                R.sc7 = {
                    normZero,
                    normBlocked,
                    surviving: removed.length,
                    state: deg.posteriorState,
                    entriesLen: deg.entries.length,
                    gridLen: deg.gridEntries.length,
                    mass: deg.probabilityMass,
                    width: deg.width,
                    reason: deg.degenerateReason,
                    gridMapSize: gridFreqMapFromEstimate(deg, null).size,
                    emptyResultNull: exactComboRangeResult([], {}) === null
                };

                // ---- 8. mass sum and 169 projection coherence --------------
                const projCheck = (combos, res) => ({
                    entriesSum: entriesSum(res.entries),
                    gridSum: gridSum(res.gridEntries),
                    probabilityMass: res.probabilityMass,
                    classDiff: mapDiff(classMassFromCombos(combos), gridMap(res.gridEntries)),
                    projectDiff: mapDiff(gridMap(projectCombosTo169Mass(copyCombos(combos))), gridMap(res.gridEntries))
                });
                R.sc8 = {
                    uniform: projCheck(priorCombos, prior),
                    preflop: projCheck(s2.combos, s2.result),
                    sequential: projCheck(s3b.combos, s3b.result),
                    postflop: projCheck(filtered, post4)
                };

                // ---- 9. no generalized 100 % without justification ---------
                R.sc9 = {
                    uniformGridMax: gridMax(prior.gridEntries),
                    uniformAt100: countAt100(prior.gridEntries),
                    uniformAllAt100: prior.gridEntries.length > 0
                        && prior.gridEntries.every(e => Math.abs(Number(e.frequency) - 100) < 1e-6),
                    conditionedGridMax: gridMax(s2.result.gridEntries),
                    conditionedAt100: countAt100(s2.result.gridEntries),
                    conditionedRelativeMax: Math.max(0, ...s2.result.entries.map(e => Number(e.relativeWeightPct) || 0)),
                    degenerateGridLen: deg.gridEntries.length,
                    overrideHand: override[0] ? override[0].hand : null,
                    overrideFrequency: override[0] ? override[0].frequency : null,
                    overrideFlagged: !!(override[0] && override[0].knownHandOverride === true),
                    priorRelativeNull: (prior.entries || []).every(e => e.relativeWeightPct === null)
                };

                // ---- 10. imported non-uniform source prior + degenerate fail-close
                // A deliberately non-uniform imported/source range with zero
                // matched public action must derive to the distinct
                // `source_prior_unconditioned` state: neither the uniform
                // `prior_uninformative` nor `degenerate`, rendered as an explicit
                // state (no numeric grid) and never any 100 % cell. Then a public
                // board that removes all of its surviving mass must fail closed as
                // `degenerate` and `rangeEntriesForHistoryPlayer` must return []
                // instead of silently substituting the legacy imported range.
                const sourcePosition = { position: cfg.source_range.position, hands: cfg.source_range.hands };
                const sourceOpponents = [{
                    playerName: "Villain", rangeIndex: 0, positionIndex: 0,
                    knownCards: [], useKnownHand: false
                }];
                const sourcePlayer = { name: "Villain", hhPosition: cfg.source_range.position };
                const buildSourceHand = id => ({
                    id, heroName: "Hero", heroCards: cfg.hero_cards.map(parseCardCode),
                    players: [
                        { name: "Hero", knownCards: [], stackBB: 100 },
                        { name: "Villain", knownCards: [], stackBB: 100 }
                    ],
                    bigBlind: 1, rake: 0, timeline: []
                });
                const savedSourceState = {
                    selectedHand: state.selectedHand, replaySteps: state.replaySteps,
                    replayIndex: state.replayIndex, hhMode: state.hhMode,
                    populationModel: state.populationModel, postflopModel: state.postflopModel,
                    opponents: state.opponents, ranges: state.ranges, rangeEdition: state.rangeEdition,
                    postflopRangeCache: state.postflopRangeCache
                };
                try {
                    state.ranges = [{ name: "Openings", positions: [sourcePosition] }];
                    state.opponents = sourceOpponents;
                    state.rangeEdition = false;
                    state.populationModel = null;
                    state.postflopModel = null;
                    state.postflopRangeCache = Object.create(null);

                    // (a) non-uniform imported range, zero matched action.
                    state.selectedHand = buildSourceHand("source-prior-browser");
                    state.replaySteps = [{ street: "Flop", board: [] }];
                    state.replayIndex = 0;
                    state.hhMode = true;
                    const sourceEstimate = populationRangeEstimateForPlayer(sourcePlayer, 0);
                    const sourceResolved = rangeEntriesForHistoryPlayer(sourcePlayer, 0);
                    const sourceLegacyCount = legacyRangeEntriesForHistoryPlayer(sourcePlayer).length;

                    // (b) a public board removes every surviving combo => fail closed.
                    state.selectedHand = buildSourceHand("degenerate-source-browser");
                    state.replaySteps = [{ street: "Flop", board: cfg.degenerate_board.map(parseCardCode) }];
                    state.replayIndex = 0;
                    state.ranges = [{
                        name: "Openings",
                        positions: [{ position: cfg.source_range.position, hands: [cfg.degenerate_source_hand] }]
                    }];
                    const degenerateEstimate = populationRangeEstimateForPlayer(sourcePlayer, 0);
                    const degenerateResolved = rangeEntriesForHistoryPlayer(sourcePlayer, 0);
                    const degenerateLegacyCount = legacyRangeEntriesForHistoryPlayer(sourcePlayer).length;

                    R.sc10 = {
                        source: {
                            state: sourceEstimate?.posteriorState || null,
                            uniformPrior: sourceEstimate?.uniformPrior === true,
                            informativeActions: Number(sourceEstimate?.informativeActions) || 0,
                            entriesSum: entriesSum(sourceEstimate?.entries),
                            gridSum: gridSum(sourceEstimate?.gridEntries),
                            gridMax: gridMax(sourceEstimate?.gridEntries),
                            grid100: countAt100(sourceEstimate?.gridEntries),
                            gridMapSize: gridFreqMapFromEstimate(sourceEstimate, null).size,
                            legacyEntryCount: sourceLegacyCount,
                            resolvedEntryCount: sourceResolved.length,
                            resolvedIsEstimateEntries: sourceResolved === (sourceEstimate?.entries || null)
                        },
                        degenerate: {
                            state: degenerateEstimate?.posteriorState || null,
                            entriesLen: degenerateEstimate?.entries?.length || 0,
                            gridLen: degenerateEstimate?.gridEntries?.length || 0,
                            mass: Number(degenerateEstimate?.probabilityMass) || 0,
                            reason: degenerateEstimate?.degenerateReason || null,
                            legacyEntryCount: degenerateLegacyCount,
                            resolvedEntryCount: degenerateResolved.length
                        }
                    };
                } finally {
                    Object.assign(state, savedSourceState);
                }

                // ---- anti-regression: max normalization is not canonical ---
                const diagnostic = copyCombos(priorCombos);
                normalizeComboWeightsInPlace(diagnostic);
                R.antiMax = {
                    entriesSum: entriesSum(s2.result.entries),
                    entriesMax: Math.max(0, ...s2.result.entries.map(e => Number(e.frequency) || 0)),
                    entriesMin: Math.min(...s2.result.entries.map(e => Number(e.frequency) || 0)),
                    entriesCount: s2.result.entries.length,
                    massSum: gridSum(s2.result.gridEntries),
                    diagnosticMaxWeight: Math.max(0, ...diagnostic.map(c => Number(c.weight) || 0)),
                    diagnosticSum: sum(diagnostic.map(c => Number(c.weight) || 0)),
                    callsMass: String(exactComboRangeResult).includes("normalizeComboWeightsToMass(combos)"),
                    callsInPlace: String(exactComboRangeResult).includes("normalizeComboWeightsInPlace"),
                    sourceExposesInPlace: String(normalizeComboWeightsInPlace).includes("max")
                };

                // ---- scale invariance of the canonical consumers -----------
                const scaled = copyCombos(s2.combos);
                for (const c of scaled) c.weight *= 7.3;
                normalizeComboWeightsToMass(scaled);
                R.scaleInvariant = {
                    classDiff: mapDiff(classMassFromCombos(s2.combos), classMassFromCombos(scaled)),
                    widthDiff: Math.abs(
                        populationRangeWidthFromEntries(s2.result.entries)
                        - populationRangeWidthFromEntries(
                            s2.result.entries.map(e => ({ hand: e.hand, frequency: Number(e.frequency) * 7.3 }))
                        )
                    )
                };

                // Runtime proof for the three equity consumers called out by
                // the representation contract.  Their raw weights may use any
                // positive common scale; compare the distributions they feed
                // to samplers/workers after dividing by their own total.
                const normalizedHands = hands => {
                    const total = sum((hands || []).map(h => h.frequency));
                    return (hands || []).map(h => ({
                        hand: h.hand,
                        p: total > 0 ? Math.max(0, Number(h.frequency) || 0) / total : 0,
                        override: h.knownHandOverride === true,
                        response: h.response ? {
                            fold: Number(h.response.fold) || 0,
                            call: Number(h.response.call) || 0,
                            raise: Number(h.response.raise) || 0
                        } : null
                    })).sort((a, b) => a.hand.localeCompare(b.hand));
                };
                const normalizedCombos = combos => {
                    const total = sum((combos || []).map(c => c.weight));
                    return (combos || []).map(c => ({
                        key: [...c.cards].sort((a, b) => a - b).join(":"),
                        p: total > 0 ? Math.max(0, Number(c.weight) || 0) / total : 0
                    })).sort((a, b) => a.key.localeCompare(b.key));
                };
                const distributionDiff = (a, b, key = "hand") => {
                    const am = new Map((a || []).map(x => [x[key], Number(x.p) || 0]));
                    const bm = new Map((b || []).map(x => [x[key], Number(x.p) || 0]));
                    return mapDiff(am, bm);
                };
                const responseDiff = (a, b) => {
                    const bm = new Map((b || []).map(x => [x.hand, x.response]));
                    let diff = 0;
                    for (const x of a || []) {
                        const y = bm.get(x.hand);
                        if (!x.response || !y) return Infinity;
                        for (const action of ["fold", "call", "raise"])
                            diff = Math.max(diff, Math.abs(x.response[action] - y[action]));
                    }
                    return diff;
                };
                const scaleEntries = (entries, factor) => (entries || []).map(e => ({
                    ...e, frequency: Number(e.frequency) * factor
                }));
                const consumerEntries = [
                    { hand: "AA", frequency: 2 },
                    { hand: "KQs", frequency: 1 }
                ];
                const scaleFactor = Number(cfg.consumer_scale_factor);

                const savedState = {
                    hero: state.hero, board: state.board, opponents: state.opponents,
                    selectedHand: state.selectedHand, replaySteps: state.replaySteps,
                    replayIndex: state.replayIndex, hhMode: state.hhMode,
                    postflopModel: state.postflopModel
                };
                const savedFns = {
                    effectiveEntriesForOpponent, rangeEntriesForHistoryPlayer,
                    actionDecisionContext, requiredEquityInfo, postflopDecisionTrace,
                    historyPlayerStackBB, postflopPreflopSummary, postflopBoardFeatures,
                    postflopRelativePosition, findClosestPostflopNode,
                    postflopTargetFrequencies, calibratedPostflopActionMatrix,
                    postflopLocalFacingSupport, actionRakeInfo
                };
                try {
                    // combos/sampler: exercise buildComboSets ->
                    // legalCombosForOpponent -> makeSampler, not a replica.
                    state.hero = [];
                    state.board = [];
                    state.opponents = [{ playerName: "Villain", knownCards: knownCards, useKnownHand: false }];
                    let comboSource = consumerEntries;
                    effectiveEntriesForOpponent = () => comboSource;
                    const comboRun = () => {
                        const combos = buildComboSets()[0];
                        const sampler = makeSampler(combos);
                        return {
                            distribution: normalizedCombos(combos),
                            finalCdf: sampler.total > 0
                                ? sampler.cum[sampler.cum.length - 1] / sampler.total : 0,
                            count: combos.length
                        };
                    };
                    const comboBase = comboRun();
                    comboSource = scaleEntries(consumerEntries, scaleFactor);
                    const comboScaled = comboRun();
                    comboSource = knownHandOverrideEntry(knownCards);
                    const comboKnown = comboRun();

                    // buildSeatEquityPlayers: run both range and exact-real
                    // scenarios through the production consumer.
                    const heroPlayer = { name: "Hero", knownCards: [], stackBB: 100 };
                    const villainPlayer = { name: "Villain", knownCards: knownCards, stackBB: 100 };
                    const hand = {
                        id: "opponent-range-consumers", heroName: "Hero",
                        heroCards: cfg.hero_cards.map(parseCardCode),
                        players: [heroPlayer, villainPlayer], bigBlind: 1, rake: 0
                    };
                    const step = {
                        street: "Flop", board: cfg.flop_board.map(parseCardCode),
                        state: { Hero: { folded: false }, Villain: { folded: false } }
                    };
                    state.selectedHand = hand;
                    state.replaySteps = [step];
                    state.replayIndex = 0;
                    state.hhMode = true;
                    let seatSource = consumerEntries;
                    rangeEntriesForHistoryPlayer = () => seatSource;
                    const seatRun = scenario => buildSeatEquityPlayers(step, scenario, 0).map(p => ({
                        name: p.name, hands: normalizedHands(p.hands),
                        hasRange: p.hasRange, hasReal: p.hasReal
                    }));
                    const seatsBase = seatRun("range_ranges");
                    seatSource = scaleEntries(consumerEntries, scaleFactor);
                    const seatsScaled = seatRun("range_ranges");
                    const seatsKnown = seatRun("hand_real");

                    // postflopRaiseTreeSnapshot needs contextual services. Stub
                    // only those services; the production snapshot still builds
                    // exact combos, response ranges and worker-facing weights.
                    const beforeState = {
                        Hero: { totalPaidBB: 0, streetPaidBB: 0 },
                        Villain: { totalPaidBB: 0, streetPaidBB: 0 }
                    };
                    const treeCtx = {
                        hand, actor: "Hero", active: [heroPlayer, villainPlayer],
                        step: { street: "Flop", actionType: "bet", actionText: "bets" },
                        before: { state: beforeState, board: step.board }
                    };
                    state.postflopModel = { smoke: true };
                    actionDecisionContext = () => treeCtx;
                    requiredEquityInfo = () => ({ cost: 2, potBefore: 5 });
                    postflopDecisionTrace = () => [{
                        player: "Hero", street: "Flop", street_history: "CHECK",
                        street_start_players: 2, pot_type: "SRP"
                    }];
                    historyPlayerStackBB = () => 100;
                    postflopPreflopSummary = () => ({ roles: { Hero: "PFR", Villain: "CALLER" } });
                    postflopBoardFeatures = () => ({});
                    postflopRelativePosition = () => "IP";
                    findClosestPostflopNode = () => ({
                        node: { id: "smoke-node", coverage: { population_decisions: 100 }, context: {} },
                        quality: "exact", exact: true
                    });
                    postflopTargetFrequencies = () => ({ FOLD: .4, CALL: .5, RAISE: .1 });
                    postflopLocalFacingSupport = () => ({});
                    actionRakeInfo = () => ({ effectiveRate: 0 });
                    const treeShape = snap => snap && ({
                        actor: normalizedHands(snap.actor.hands),
                        responder: normalizedHands(snap.responders[0]?.hands || []),
                        responderCount: snap.responders.length,
                        responseMetaCount: snap.responseMeta.length
                    });
                    seatSource = consumerEntries;
                    const treeBase = treeShape(postflopRaiseTreeSnapshot(0, "range_ranges"));
                    seatSource = scaleEntries(consumerEntries, scaleFactor);
                    const treeScaled = treeShape(postflopRaiseTreeSnapshot(0, "range_ranges"));
                    const treeKnown = treeShape(postflopRaiseTreeSnapshot(0, "hand_real"));

                    R.equityConsumers = {
                        combosSampler: {
                            count: comboBase.count,
                            scaleDiff: distributionDiff(comboBase.distribution, comboScaled.distribution, "key"),
                            baseFinalCdf: comboBase.finalCdf,
                            scaledFinalCdf: comboScaled.finalCdf,
                            knownCount: comboKnown.count,
                            knownFinalCdf: comboKnown.finalCdf
                        },
                        seatPlayers: {
                            count: seatsBase.length,
                            scaleDiff: Math.max(...seatsBase.map((p, i) =>
                                distributionDiff(p.hands, seatsScaled[i]?.hands || [])
                            )),
                            knownCounts: seatsKnown.map(p => p.hands.length),
                            knownFlags: seatsKnown.map(p => p.hands.every(h => h.override)),
                            hasReal: seatsKnown.map(p => p.hasReal)
                        },
                        raiseTree: {
                            present: !!treeBase && !!treeScaled && !!treeKnown,
                            actorScaleDiff: treeBase && treeScaled
                                ? distributionDiff(treeBase.actor, treeScaled.actor) : null,
                            responderScaleDiff: treeBase && treeScaled
                                ? distributionDiff(treeBase.responder, treeScaled.responder) : null,
                            responderResponseDiff: treeBase && treeScaled
                                ? responseDiff(treeBase.responder, treeScaled.responder) : null,
                            responderCount: treeBase?.responderCount || 0,
                            responseMetaCount: treeBase?.responseMetaCount || 0,
                            knownActorCount: treeKnown?.actor.length || 0,
                            knownResponderCount: treeKnown?.responder.length || 0,
                            knownActorFlagged: !!treeKnown?.actor.every(h => h.override),
                            // The tree expands responder entries into worker-facing
                            // exact combos; metadata is intentionally not part of
                            // that payload, but the single exact combo must survive.
                            knownResponderMass: sum((treeKnown?.responder || []).map(h => h.p))
                        }
                    };
                } finally {
                    Object.assign(state, savedState);
                    effectiveEntriesForOpponent = savedFns.effectiveEntriesForOpponent;
                    rangeEntriesForHistoryPlayer = savedFns.rangeEntriesForHistoryPlayer;
                    actionDecisionContext = savedFns.actionDecisionContext;
                    requiredEquityInfo = savedFns.requiredEquityInfo;
                    postflopDecisionTrace = savedFns.postflopDecisionTrace;
                    historyPlayerStackBB = savedFns.historyPlayerStackBB;
                    postflopPreflopSummary = savedFns.postflopPreflopSummary;
                    postflopBoardFeatures = savedFns.postflopBoardFeatures;
                    postflopRelativePosition = savedFns.postflopRelativePosition;
                    findClosestPostflopNode = savedFns.findClosestPostflopNode;
                    postflopTargetFrequencies = savedFns.postflopTargetFrequencies;
                    calibratedPostflopActionMatrix = savedFns.calibratedPostflopActionMatrix;
                    postflopLocalFacingSupport = savedFns.postflopLocalFacingSupport;
                    actionRakeInfo = savedFns.actionRakeInfo;
                }

                return R;
            }""",
            cfg,
        )

        assert page_errors == [], page_errors

        # ---- scenario 1: non-informative / uniform prior ----------------------
        sc1 = result["sc1"]
        assert sc1["state"] == "prior_uninformative", sc1
        assert sc1["uniformPrior"] is True and sc1["informativeActions"] == 0, sc1
        assert sc1["comboCount"] == 1326, sc1
        assert approx(sc1["entriesSum"], 100.0) and approx(sc1["gridSum"], 100.0), sc1
        assert sc1["gridLen"] == 169, sc1
        assert sc1["gridMax"] < 1.0 and sc1["grid100"] == 0, sc1
        assert sc1["relativeNull"] is True, sc1
        assert approx(sc1["width"], 1.0, 1e-9) and approx(sc1["probabilityMass"], 1.0, 1e-9), sc1
        assert sc1["gridMapSize"] == 0, sc1

        # ---- scenario 2: one informative preflop action -----------------------
        sc2 = result["sc2"]
        assert sc2["state"] == "conditioned" and sc2["informativeActions"] == 1, sc2
        assert sc2["uniformPrior"] is False, sc2
        assert approx(sc2["entriesSum"], 100.0) and approx(sc2["gridSum"], 100.0), sc2
        assert 0 < sc2["gridMax"] < 100.0, sc2
        assert sc2["relativeNullCount"] == 0 and approx(sc2["relativeMax"], 100.0, 1e-6), sc2
        assert sc2["massMapSize"] > 0 and approx(sc2["massMapAAA"], sc2["aaMass"]), sc2

        # ---- scenario 3: several sequential conditioning actions --------------
        sc3 = result["sc3"]
        assert sc3["state"] == "conditioned" and sc3["informativeActions"] == 2, sc3
        assert approx(sc3["entriesSum"], 100.0) and approx(sc3["gridSum"], 100.0), sc3
        assert sc3["l1Between"] > 0.5, sc3
        assert sc3["gridMax"] < 100.0, sc3

        # ---- scenario 4: postflop + public blockers ---------------------------
        sc4 = result["sc4"]
        assert sc4["ok"] is True and sc4["state"] == "conditioned", sc4
        assert sc4["blockedFree"] is True, sc4
        assert 0 < sc4["comboCount"] < sc4["beforeCount"], sc4
        assert approx(sc4["entriesSum"], 100.0) and approx(sc4["gridSum"], 100.0), sc4
        assert sc4["classDiff"] < 1e-6 and sc4["gridMax"] < 100.0, sc4

        # ---- scenario 5: known-hand override is a separate mechanism ----------
        sc5 = result["sc5"]
        assert sc5["count"] == 1 and sc5["frequency"] == 100, sc5
        assert sc5["isArray"] is True and sc5["newEntryIsArray"] is True, sc5
        assert sc5["sameHand"] is True, sc5
        assert sc5["hand"] == sc5["expectedHand"], sc5
        assert sc5["flagged"] is True and sc5["isOverride"] is True, sc5
        assert sc5["explicitEmpty"] == 0 and sc5["newEntryEmpty"] == 0, sc5
        assert sc5["posteriorState"] is None and sc5["priorGridSize"] == 0, sc5

        # ---- scenario 6: no exploitable action --------------------------------
        sc6 = result["sc6"]
        assert sc6["state"] == "prior_uninformative" and sc6["isDegenerate"] is False, sc6
        assert sc6["gridMapSize"] == 0, sc6
        assert approx(sc6["entriesSum"], 100.0) and approx(sc6["probabilityMass"], 1.0, 1e-9), sc6

        # ---- scenario 7: degenerate / zero-mass posterior, fail-closed --------
        sc7 = result["sc7"]
        assert sc7["normZero"] is False and sc7["normBlocked"] is False, sc7
        assert sc7["surviving"] == 0 and sc7["emptyResultNull"] is True, sc7
        assert sc7["state"] == "degenerate", sc7
        assert sc7["entriesLen"] == 0 and sc7["gridLen"] == 0, sc7
        assert sc7["mass"] == 0 and sc7["width"] == 0, sc7
        assert sc7["reason"] == "postflop_blockers_zero_mass", sc7
        assert sc7["gridMapSize"] == 0, sc7

        # ---- scenario 8: mass sum and 169 projection coherence ----------------
        for name, check in result["sc8"].items():
            assert approx(check["entriesSum"], 100.0), (name, check)
            assert approx(check["gridSum"], 100.0), (name, check)
            assert approx(check["probabilityMass"], 1.0, 1e-9), (name, check)
            assert check["classDiff"] < 1e-6, (name, check)
            assert check["projectDiff"] < 1e-6, (name, check)

        # ---- scenario 9: no generalized 100 % without justification -----------
        sc9 = result["sc9"]
        assert sc9["uniformGridMax"] < 1.0 and sc9["uniformAt100"] == 0, sc9
        assert sc9["uniformAllAt100"] is False, sc9
        assert sc9["conditionedGridMax"] < 100.0 and sc9["conditionedAt100"] == 0, sc9
        assert approx(sc9["conditionedRelativeMax"], 100.0, 1e-6), sc9
        assert sc9["degenerateGridLen"] == 0, sc9
        assert sc9["overrideFrequency"] == 100 and sc9["overrideFlagged"] is True, sc9
        assert sc9["priorRelativeNull"] is True, sc9

        # ---- scenario 10: non-uniform imported source prior + degenerate -------
        sc10 = result["sc10"]
        source_prior = sc10["source"]
        # Distinct explicit state, never assimilated to the two neighbours.
        assert source_prior["state"] == "source_prior_unconditioned", sc10
        assert source_prior["state"] != "prior_uninformative", sc10
        assert source_prior["state"] != "degenerate", sc10
        assert source_prior["uniformPrior"] is False, sc10
        assert source_prior["informativeActions"] == 0, sc10
        # Canonical mass projection sums to 100 with no 100 % cell...
        assert approx(source_prior["entriesSum"], 100.0) and approx(source_prior["gridSum"], 100.0), sc10
        assert 0 < source_prior["gridMax"] < 100.0 and source_prior["grid100"] == 0, sc10
        # ...and the UI renders no numeric grid for this explicit state.
        assert source_prior["gridMapSize"] == 0, sc10
        # The source prior is still exposed to the equity consumers (the legacy
        # imported range the estimate was derived from is non-empty).
        assert source_prior["legacyEntryCount"] == 3, sc10
        assert source_prior["resolvedEntryCount"] == 16, sc10
        assert source_prior["resolvedIsEstimateEntries"] is True, sc10

        degenerate = sc10["degenerate"]
        assert degenerate["state"] == "degenerate", sc10
        assert degenerate["entriesLen"] == 0 and degenerate["gridLen"] == 0, sc10
        assert degenerate["mass"] == 0, sc10
        assert degenerate["reason"] == "public_blockers_removed_all_mass", sc10
        # Fail-closed: the legacy imported range exists but is never substituted.
        assert degenerate["legacyEntryCount"] == 1, sc10
        assert degenerate["resolvedEntryCount"] == 0, sc10

        # ---- anti-regression: max normalization is not the canonical output ---
        anti = result["antiMax"]
        assert anti["callsMass"] is True and anti["callsInPlace"] is False, anti
        assert approx(anti["entriesSum"], 100.0), anti
        assert anti["entriesCount"] > 1, anti
        assert 0 < anti["entriesMin"] < anti["entriesMax"] < 99.999, anti
        assert approx(anti["massSum"], 100.0), anti
        # The diagnostic max normalization is a different notion: max = 1 but the
        # values do not sum to 1 (they are not a probability distribution).
        assert approx(anti["diagnosticMaxWeight"], 1.0, 1e-9), anti
        assert anti["diagnosticSum"] > 1.5, anti
        # If the canonical output had been max-normalized, the strongest entry
        # would be exactly 100 and the distribution would not sum to 100.
        assert not (approx(anti["entriesMax"], 100.0) and not approx(anti["entriesSum"], 100.0)), anti

        # ---- scale invariance of the canonical consumers ----------------------
        scale = result["scaleInvariant"]
        assert scale["classDiff"] < 1e-6, scale
        assert scale["widthDiff"] < 1e-9, scale

        # ---- required equity consumers: scale + known-hand override ---------
        consumers = result["equityConsumers"]
        combo_consumer = consumers["combosSampler"]
        assert combo_consumer["count"] > 1, combo_consumer
        assert combo_consumer["scaleDiff"] < 1e-12, combo_consumer
        assert approx(combo_consumer["baseFinalCdf"], 1.0, 1e-12), combo_consumer
        assert approx(combo_consumer["scaledFinalCdf"], 1.0, 1e-12), combo_consumer
        assert combo_consumer["knownCount"] == 1, combo_consumer
        assert approx(combo_consumer["knownFinalCdf"], 1.0, 1e-12), combo_consumer

        seat_consumer = consumers["seatPlayers"]
        assert seat_consumer["count"] == 2, seat_consumer
        assert seat_consumer["scaleDiff"] < 1e-12, seat_consumer
        assert seat_consumer["knownCounts"] == [1, 1], seat_consumer
        assert seat_consumer["knownFlags"] == [True, True], seat_consumer
        assert seat_consumer["hasReal"] == [True, True], seat_consumer

        tree_consumer = consumers["raiseTree"]
        assert tree_consumer["present"] is True, tree_consumer
        assert tree_consumer["actorScaleDiff"] < 1e-12, tree_consumer
        assert tree_consumer["responderScaleDiff"] < 1e-12, tree_consumer
        assert tree_consumer["responderResponseDiff"] < 1e-9, tree_consumer
        assert tree_consumer["responderCount"] == 1, tree_consumer
        assert tree_consumer["responseMetaCount"] == 1, tree_consumer
        assert tree_consumer["knownActorCount"] == 1, tree_consumer
        assert tree_consumer["knownResponderCount"] == 1, tree_consumer
        assert tree_consumer["knownActorFlagged"] is True, tree_consumer
        assert approx(tree_consumer["knownResponderMass"], 1.0, 1e-12), tree_consumer

        await browser.close()

    print(json.dumps({
        "scenarios": 10,
        "uniformPrior": result["sc1"],
        "conditioned": result["sc2"],
        "sourcePriorUnconditioned": result["sc10"]["source"],
        "antiMax": {k: v for k, v in result["antiMax"].items() if k != "sourceExposesInPlace"},
    }, indent=2, ensure_ascii=False))
    print("opponent range numeric smoke: PASS (10 scenarios)")


if __name__ == "__main__":
    asyncio.run(main())
