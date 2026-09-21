#!/usr/bin/env python3
"""Equity/EV scale-invariance smoke for the opponent-range consumers (#391 · task-ytl).

Numeric browser test: it serves ``site/index.html`` locally and drives the real
in-page functions with ``page.evaluate``. It proves that the equity/EV consumers
are invariant under a constant rescaling of every input weight:

* ``buildSeatEquityPlayers`` / ``tableEquitySnapshotForStep`` — the exact
  (deterministic) equity of the seat snapshot is bit-identical after scaling,
  because the table worker normalizes each sampler by its own total weight;
* ``postflopRaiseTreeSnapshot`` — the actor/responder sampling distributions and
  every response probability are identical after scaling, so the Monte-Carlo EV
  and equity agree within their combined standard errors;
* ``aiExportRangeSnapshot`` — the canonical ``grid_169_probability_pct`` stays
  sum-normalized (≈100), the per-combo ``probability_pct`` stays sum-normalized,
  and the diagnostic ``relative_weight_pct`` / ``grid_169_relative_weight_pct``
  remain distinct (max = 100, no probability sum). The probability projection is
  invariant under scaling too.

Two negative controls demonstrate that the test is not vacuous: the same
detector flags an intentionally scale-dependent (raw-weight sum) aggregation and
an injected consumer mutation (a 169 projection without sum-normalization), so a
consumer that introduced such a dependency would fail the test.

Representation/normalization layer only: the model/fit and every equity kernel
are left untouched, and no unrevealed opponent card or future information is
consumed (only public hero/board cards and a priori 169 weights).
"""
from __future__ import annotations

import asyncio
import math
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"

CONFIG = {
    "scale_factor": 7.3,
    "hero_cards": ["3h", "4h"],
    "board": ["2c", "7d", "9h"],
    "hero_entries": [
        {"hand": "AA", "frequency": 100},
        {"hand": "KK", "frequency": 50},
    ],
    "villain_entries": [
        {"hand": "QQ", "frequency": 100},
        {"hand": "AKs", "frequency": 25},
    ],
    "raw_export_entries": [
        {"hand": "AA", "frequency": 40, "relativeWeightPct": 100},
        {"hand": "KK", "frequency": 25, "relativeWeightPct": 62.5},
        {"hand": "QQ", "frequency": 15, "relativeWeightPct": 37.5},
        {"hand": "AKs", "frequency": 20, "relativeWeightPct": 50},
    ],
}

EVAL_JS = r"""
async (cfg) => {
    const R = {};
    const sum = a => (a || []).reduce((x, y) => x + Math.max(0, Number(y) || 0), 0);
    const copyCombos = cs => (cs || []).map(c => ({ cards: [c.cards[0], c.cards[1]], weight: Number(c.weight) || 0 }));
    const maxAbsDiff = (a, b) => {
        let d = 0; const n = Math.max((a || []).length, (b || []).length);
        for (let i = 0; i < n; i++) d = Math.max(d, Math.abs((Number(a?.[i]) || 0) - (Number(b?.[i]) || 0)));
        return d;
    };
    const distOfHands = hands => {
        const t = sum((hands || []).map(h => h.frequency));
        return (hands || []).map(h => ({
            hand: h.hand,
            p: t > 0 ? Math.max(0, Number(h.frequency) || 0) / t : 0
        })).sort((a, b) => a.hand.localeCompare(b.hand));
    };
    const distDiff = (a, b) => {
        const am = new Map((a || []).map(x => [x.hand, x.p]));
        const bm = new Map((b || []).map(x => [x.hand, x.p]));
        let d = 0;
        for (const k of new Set([...am.keys(), ...bm.keys()]))
            d = Math.max(d, Math.abs((am.get(k) || 0) - (bm.get(k) || 0)));
        return d;
    };
    const mapValues = m => Object.values(m || {}).map(Number);
    const mapSum = m => sum(mapValues(m));
    const mapMax = m => Math.max(0, ...mapValues(m));
    const mapMaxDiff = (a, b) => {
        let d = 0;
        for (const k of new Set([...Object.keys(a || {}), ...Object.keys(b || {})]))
            d = Math.max(d, Math.abs(Number(a?.[k] || 0) - Number(b?.[k] || 0)));
        return d;
    };
    // Drive a real production compute worker through the shared scheduler.
    const runCompute = (factory, payload) => new Promise((resolve, reject) => {
        const task = factory({ kind: "explicit" });
        task.onmessage = e => {
            const d = e && e.data;
            if (d && d.type === "progress") return;
            if (d && d.type === "error") { reject(new Error(d.message || "worker error")); return; }
            resolve(d && d.out ? d.out : d);
        };
        task.onerror = e => reject(new Error((e && e.message) || "worker error"));
        task.postMessage(payload);
    });

    const saved = {
        hero: state.hero, board: state.board, opponents: state.opponents,
        selectedHand: state.selectedHand, replaySteps: state.replaySteps,
        replayIndex: state.replayIndex, hhMode: state.hhMode,
        postflopModel: state.postflopModel
    };
    const savedFns = {
        rangeEntriesForHistoryPlayer, actionDecisionContext, requiredEquityInfo,
        postflopDecisionTrace, historyPlayerStackBB, postflopPreflopSummary,
        postflopBoardFeatures, postflopRelativePosition, findClosestPostflopNode,
        postflopTargetFrequencies, postflopLocalFacingSupport, actionRakeInfo,
        populationRangeEstimateForPlayer, projectCombosTo169Mass
    };
    const savedMethod = methodSelect.value, savedTrials = trialsSelect.value;

    try {
        // 50 000 is capped to 16 000 trials by postflopRaiseTreeSnapshot.
        methodSelect.value = "exact"; trialsSelect.value = "50000";
        const factor = Number(cfg.scale_factor);
        const board = cfg.board.map(parseCardCode);
        const heroCards = cfg.hero_cards.map(parseCardCode);
        const heroPlayer = { name: "Hero", knownCards: [], stackBB: 100 };
        const villainPlayer = { name: "Villain", knownCards: [], stackBB: 100 };
        const hand = {
            id: "equity-scale-invariance", heroName: "Hero", heroCards,
            players: [heroPlayer, villainPlayer], bigBlind: 1, rake: 0
        };
        const step = {
            street: "Flop", board,
            state: { Hero: { folded: false }, Villain: { folded: false } }
        };
        state.selectedHand = hand; state.replaySteps = [step];
        state.replayIndex = 0; state.hhMode = true;

        const scaleEntries = (entries, f) => entries.map(e => ({ ...e, frequency: Number(e.frequency) * f }));
        const heroBase = cfg.hero_entries, villainBase = cfg.villain_entries;

        // ---- buildSeatEquityPlayers + tableEquitySnapshotForStep ----------
        let heroSrc = heroBase, villainSrc = villainBase;
        rangeEntriesForHistoryPlayer = player => (player.name === "Villain" ? villainSrc : heroSrc);
        const seatsBase = buildSeatEquityPlayers(step, "range_ranges", 0).map(p => ({
            name: p.name, hands: distOfHands(p.hands), hasRange: p.hasRange
        }));
        const snapBase = tableEquitySnapshotForStep(step, "range_ranges", 0);
        heroSrc = scaleEntries(heroBase, factor); villainSrc = scaleEntries(villainBase, factor);
        const seatsScaled = buildSeatEquityPlayers(step, "range_ranges", 0).map(p => ({
            name: p.name, hands: distOfHands(p.hands), hasRange: p.hasRange
        }));
        const snapScaled = tableEquitySnapshotForStep(step, "range_ranges", 0);
        R.consumers = {
            seatCount: seatsBase.length,
            seatScaleDiff: Math.max(...seatsBase.map((p, i) => distDiff(p.hands, seatsScaled[i]?.hands || []))),
            seatHasRange: seatsBase.map(p => p.hasRange),
            snapshotPresent: !!(snapBase && snapScaled),
            snapshotMethod: snapBase ? snapBase.method : null,
            snapshotPlayerCount: snapBase ? snapBase.players.length : 0
        };
        const eqBase = await runCompute(createTableEquityWorker, snapBase);
        const eqScaled = await runCompute(createTableEquityWorker, snapScaled);
        R.tableEquity = {
            names: eqBase.names, method: eqBase.method, scenarios: eqBase.scenarios,
            base: eqBase.equities, scaled: eqScaled.equities,
            maxDiff: maxAbsDiff(eqBase.equities, eqScaled.equities)
        };

        // ---- postflopRaiseTreeSnapshot ------------------------------------
        const beforeState = {
            Hero: { totalPaidBB: 0, streetPaidBB: 0 },
            Villain: { totalPaidBB: 0, streetPaidBB: 0 }
        };
        const treeCtx = {
            hand, actor: "Hero", active: [heroPlayer, villainPlayer],
            step: { street: "Flop", actionType: "bet", actionText: "bets" },
            before: { state: beforeState, board }
        };
        state.postflopModel = { smoke: true };
        actionDecisionContext = () => treeCtx;
        requiredEquityInfo = () => ({ cost: 2, potBefore: 5 });
        postflopDecisionTrace = () => ([{
            player: "Hero", street: "Flop", street_history: "CHECK",
            street_start_players: 2, pot_type: "SRP"
        }]);
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
        const treeDist = s => s && ({
            actor: distOfHands(s.actor.hands),
            responder: distOfHands(s.responders[0]?.hands || []),
            response: (s.responders[0]?.hands || []).map(h => ({ hand: h.hand, response: h.response }))
                .sort((a, b) => a.hand.localeCompare(b.hand)),
            responderCount: s.responders.length,
            trials: s.trials
        });
        const responseDiff = (a, b) => {
            const bm = new Map((b || []).map(x => [x.hand, x.response]));
            let d = 0;
            for (const x of a || []) {
                const y = bm.get(x.hand);
                if (!x.response || !y) return 999;
                for (const action of ["fold", "call", "raise"])
                    d = Math.max(d, Math.abs(x.response[action] - y[action]));
            }
            return d;
        };
        heroSrc = heroBase; villainSrc = villainBase;
        const snapTreeBase = postflopRaiseTreeSnapshot(0, "range_ranges");
        heroSrc = scaleEntries(heroBase, factor); villainSrc = scaleEntries(villainBase, factor);
        const snapTreeScaled = postflopRaiseTreeSnapshot(0, "range_ranges");
        const treeBase = treeDist(snapTreeBase), treeScaled = treeDist(snapTreeScaled);
        R.raiseTree = {
            present: !!(treeBase && treeScaled),
            actorScaleDiff: treeBase && treeScaled ? distDiff(treeBase.actor, treeScaled.actor) : null,
            responderScaleDiff: treeBase && treeScaled ? distDiff(treeBase.responder, treeScaled.responder) : null,
            responseDiff: treeBase && treeScaled ? responseDiff(treeBase.response, treeScaled.response) : null,
            responderCount: treeBase ? treeBase.responderCount : 0
        };
        const evBase = await runCompute(createPostflopBetRaiseEVWorker, snapTreeBase);
        const evScaled = await runCompute(createPostflopBetRaiseEVWorker, snapTreeScaled);
        R.postflopEV = {
            trials: evBase.trials,
            evStdErr: Number(evBase.evStdErrBB) || 0,
            base: {
                ev: Number(evBase.evBB) || 0,
                equity: Number(evBase.equityWhenCalled) || 0,
                pAllFold: Number(evBase.pAllFold) || 0,
                pCallNoRaise: Number(evBase.pCallNoRaise) || 0,
                pReraise: Number(evBase.pReraise) || 0
            },
            scaled: {
                ev: Number(evScaled.evBB) || 0,
                equity: Number(evScaled.equityWhenCalled) || 0,
                pAllFold: Number(evScaled.pAllFold) || 0,
                pCallNoRaise: Number(evScaled.pCallNoRaise) || 0,
                pReraise: Number(evScaled.pReraise) || 0
            }
        };

        // ---- aiExportRangeSnapshot (canonical 169 projection) --------------
        state.replaySteps = [{ street: "Flop", board: [] }]; state.replayIndex = 0;
        state.rangeEdition = false;
        const newRegistry = () => ({ next: 1, byKey: Object.create(null), snapshots: Object.create(null) });
        const rawEntries = cfg.raw_export_entries.map(e => ({ ...e }));
        const scaledRaw = rawEntries.map(e => ({ ...e, frequency: Number(e.frequency) * factor }));
        const exportFor = (entries, uniformPrior, posteriorState) => {
            populationRangeEstimateForPlayer = () => ({
                entries, uniformPrior, posteriorState, exactComboEngine: true, width: .5
            });
            const reg = newRegistry();
            const id = aiExportRangeSnapshot(villainPlayer, 0, reg, "smoke");
            return reg.snapshots[id];
        };
        const condBase = exportFor(rawEntries, false, "conditioned");
        const condScaled = exportFor(scaledRaw, false, "conditioned");
        const exactMap = snap => new Map((snap.exact_combos || []).map(c => [c.cards.join(""), Number(c.probability_pct) || 0]));
        const relativeMap = snap => new Map((snap.exact_combos || []).map(c => [c.cards.join(""), c.relative_weight_pct === null ? null : Number(c.relative_weight_pct) || 0]));
        const keyedMaxDiff = (a, b) => {
            let d = 0;
            for (const k of new Set([...a.keys(), ...b.keys()])) {
                const av = a.get(k), bv = b.get(k);
                if (av === null || bv === null) { if (av !== bv) return 999; continue; }
                d = Math.max(d, Math.abs((av || 0) - (bv || 0)));
            }
            return d;
        };
        R.exportConditioned = {
            posteriorState: condBase.posterior_state,
            fieldsPresent: Object.prototype.hasOwnProperty.call(condBase, "grid_169_probability_pct")
                && Object.prototype.hasOwnProperty.call(condBase, "grid_169_relative_weight_pct"),
            probabilitySum: mapSum(condBase.grid_169_probability_pct),
            probabilityMax: mapMax(condBase.grid_169_probability_pct),
            exactProbabilitySum: sum((condBase.exact_combos || []).map(c => c.probability_pct)),
            relativeSum: mapSum(condBase.grid_169_relative_weight_pct),
            relativeMax: mapMax(condBase.grid_169_relative_weight_pct),
            relativeNonNull: (condBase.exact_combos || []).every(c => c.relative_weight_pct !== null),
            gridDistinct: mapMaxDiff(condBase.grid_169_probability_pct, condBase.grid_169_relative_weight_pct),
            scaledGridDiff: mapMaxDiff(condBase.grid_169_probability_pct, condScaled.grid_169_probability_pct),
            scaledExactDiff: keyedMaxDiff(exactMap(condBase), exactMap(condScaled)),
            scaledRelativeDiff: keyedMaxDiff(relativeMap(condBase), relativeMap(condScaled))
        };
        // Mutation probe: replace the canonical projection with a scale-dependent
        // one (no /total) and confirm the same detector fires, so a consumer that
        // introduced such a dependency would fail this test.
        const realProjection = projectCombosTo169Mass;
        projectCombosTo169Mass = combos => {
            const mass = Object.create(null);
            for (const c of combos || []) {
                const w = Math.max(0, Number(c.weight) || 0);
                if (!(w > 0)) continue;
                const cls = cardsToNotation(c.cards);
                mass[cls] = (mass[cls] || 0) + w;
            }
            return ALL_NOTATIONS.map(hand => ({ hand, frequency: 100 * (mass[hand] || 0) }));
        };
        const mutantBase = exportFor(rawEntries, false, "conditioned");
        const mutantScaled = exportFor(scaledRaw, false, "conditioned");
        projectCombosTo169Mass = realProjection;
        const mutantGridDiff = mapMaxDiff(
            mutantBase.grid_169_probability_pct, mutantScaled.grid_169_probability_pct
        );

        const uniformEstimate = exactComboRangeResult(copyCombos(uniformExactComboPrior([])), { informativeActions: 0 });
        populationRangeEstimateForPlayer = () => uniformEstimate;
        const regU = newRegistry();
        const idU = aiExportRangeSnapshot(villainPlayer, 0, regU, "smoke-uniform");
        const uni = regU.snapshots[idU];
        R.exportUniform = {
            posteriorState: uni.posterior_state,
            probabilitySum: mapSum(uni.grid_169_probability_pct),
            probabilityMax: mapMax(uni.grid_169_probability_pct),
            at100: mapValues(uni.grid_169_probability_pct).filter(v => Math.abs(v - 100) < 1e-6).length,
            relativeNullAll: (uni.exact_combos || []).every(c => c.relative_weight_pct === null),
            // A uniform prior has no defined relative weight: the diagnostic
            // 169 grid must be absent/empty, never a mass grid.
            relativeGridNull: uni.grid_169_relative_weight_pct === null
                || Object.keys(uni.grid_169_relative_weight_pct || {}).length === 0,
            relativeGridPositive: mapValues(uni.grid_169_relative_weight_pct).filter(v => v > 0).length,
            exactProbabilitySum: sum((uni.exact_combos || []).map(c => c.probability_pct))
        };

        // ---- negative control: the detector is sensitive to scale ----------
        const rawAggregate = es => sum((es || []).map(e => Number(e.frequency) || 0));
        const normalizedDist = es => {
            const t = rawAggregate(es);
            return (es || []).map(e => ({ hand: e.hand, p: t > 0 ? (Number(e.frequency) || 0) / t : 0 }));
        };
        R.negativeControl = {
            badScaleDiff: Math.abs(rawAggregate(rawEntries) - rawAggregate(scaledRaw)),
            goodScaleDiff: distDiff(normalizedDist(rawEntries), normalizedDist(scaledRaw)),
            mutantGridDiff
        };

        return R;
    } finally {
        Object.assign(state, saved);
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
        postflopLocalFacingSupport = savedFns.postflopLocalFacingSupport;
        actionRakeInfo = savedFns.actionRakeInfo;
        populationRangeEstimateForPlayer = savedFns.populationRangeEstimateForPlayer;
        projectCombosTo169Mass = savedFns.projectCombosTo169Mass;
        methodSelect.value = savedMethod; trialsSelect.value = savedTrials;
    }
}
"""


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):  # keep the smoke output clean
        pass


def start_local_server(directory: Path):
    handler = partial(_QuietHandler, directory=str(directory))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/index.html"


def binom_tol(n: int) -> float:
    # A 6-sigma two-sample bound for a proportion with p in [0, 1].
    return 6.0 * math.sqrt(0.25 / max(1, n) * 2) + 1e-9


async def main() -> None:
    httpd, url = start_local_server(SITE)
    page_errors: list[str] = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            page = await browser.new_page(viewport={"width": 1400, "height": 900})
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            await page.wait_for_function(
                "typeof buildSeatEquityPlayers === 'function' && "
                "typeof tableEquitySnapshotForStep === 'function' && "
                "typeof postflopRaiseTreeSnapshot === 'function' && "
                "typeof aiExportRangeSnapshot === 'function' && "
                "typeof createTableEquityWorker === 'function' && "
                "typeof createPostflopBetRaiseEVWorker === 'function' && "
                "!!window.pokerComputeScheduler",
                timeout=20_000,
            )
            result = await page.evaluate(EVAL_JS, CONFIG)
            await browser.close()
        assert page_errors == [], page_errors
    finally:
        httpd.shutdown()

    # ---- 1. buildSeatEquityPlayers is scale-invariant ---------------------
    consumers = result["consumers"]
    assert consumers["seatCount"] == 2, consumers
    assert consumers["seatHasRange"] == [True, True], consumers
    assert consumers["snapshotPresent"] is True, consumers
    assert consumers["snapshotMethod"] == "exact", consumers
    assert consumers["snapshotPlayerCount"] == 2, consumers
    assert consumers["seatScaleDiff"] < 1e-12, consumers

    # ---- 2. tableEquitySnapshotForStep -> exact equity identical ----------
    table = result["tableEquity"]
    assert table["method"] == "Exact", table
    assert table["scenarios"] > 0, table
    assert table["maxDiff"] < 1e-9, table

    # ---- 3. postflopRaiseTreeSnapshot sampling + EV -----------------------
    tree = result["raiseTree"]
    assert tree["present"] is True, tree
    assert tree["responderCount"] == 1, tree
    assert tree["actorScaleDiff"] < 1e-12, tree
    assert tree["responderScaleDiff"] < 1e-12, tree
    assert tree["responseDiff"] < 1e-9, tree

    ev = result["postflopEV"]
    assert ev["trials"] >= 16000, ev
    ev_tol = 6.0 * math.sqrt(2 * ev["evStdErr"] ** 2) + 1e-9
    assert abs(ev["base"]["ev"] - ev["scaled"]["ev"]) <= ev_tol, (ev, ev_tol)
    assert abs(ev["base"]["equity"] - ev["scaled"]["equity"]) <= binom_tol(ev["trials"]), ev
    for key in ("pAllFold", "pCallNoRaise", "pReraise"):
        assert abs(ev["base"][key] - ev["scaled"][key]) <= binom_tol(ev["trials"]), (key, ev)

    # ---- 4. aiExportRangeSnapshot posterior export coherence --------------
    cond = result["exportConditioned"]
    assert cond["posteriorState"] == "conditioned", cond
    assert cond["fieldsPresent"] is True, cond
    assert abs(cond["probabilitySum"] - 100.0) < 1e-3, cond
    assert abs(cond["exactProbabilitySum"] - 100.0) < 1e-3, cond
    assert 0 < cond["probabilityMax"] < 100.0, cond
    # The diagnostic relative weight is a distinct notion: max = 100, no sum.
    assert cond["relativeNonNull"] is True, cond
    assert abs(cond["relativeMax"] - 100.0) < 1e-6, cond
    assert abs(cond["relativeSum"] - 100.0) > 1.0, cond
    assert cond["gridDistinct"] > 1e-6, cond
    # The canonical probability projection is invariant under scaling.
    assert cond["scaledGridDiff"] < 1e-6, cond
    assert cond["scaledExactDiff"] < 1e-6, cond
    assert cond["scaledRelativeDiff"] < 1e-6, cond

    uni = result["exportUniform"]
    assert uni["posteriorState"] == "prior_uninformative", uni
    assert abs(uni["probabilitySum"] - 100.0) < 1e-3, uni
    assert abs(uni["exactProbabilitySum"] - 100.0) < 1e-3, uni
    assert uni["probabilityMax"] < 100.0 and uni["at100"] == 0, uni
    assert uni["relativeNullAll"] is True, uni
    # The undefined relative weight is never derived from the canonical mass:
    # the diagnostic 169 grid is absent/empty with no positive entry.
    assert uni["relativeGridNull"] is True, uni
    assert uni["relativeGridPositive"] == 0, uni

    # ---- 5. the detector would fail a scale-dependent consumer ------------
    neg = result["negativeControl"]
    assert neg["badScaleDiff"] > 1e-9, neg
    assert neg["goodScaleDiff"] < 1e-12, neg
    # An actual consumer mutation (a 169 projection without sum-normalization)
    # is flagged by the very same detector used in the assertions above.
    assert neg["mutantGridDiff"] > 1e-6, neg

    print("equity scale invariance smoke: PASS")
    print(
        "  table exact equity max diff:  %.3e | postflop EV diff: %.3e (tol %.3e)"
        % (table["maxDiff"], abs(ev["base"]["ev"] - ev["scaled"]["ev"]), ev_tol)
    )
    print(
        "  grid_169_probability_pct sum: %.6f | relative_weight max: %.3f | distinct: %.3f"
        % (cond["probabilitySum"], cond["relativeMax"], cond["gridDistinct"])
    )


if __name__ == "__main__":
    asyncio.run(main())
