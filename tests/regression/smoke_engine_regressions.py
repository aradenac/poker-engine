#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8765/index.html"
FIXTURE = Path(__file__).with_name("hand_262024556922.json")


async def main() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["schema"] == "poker-engine-regression-case/v1"
    assert fixture["hand_id"] == "262024556922"
    required = set(fixture.get("required_invariants") or [])
    assert any("turn check" in x for x in required)
    assert any("river check" in x for x in required)
    assert any("river fold" in x for x in required)
    assert any("sizingOptimizationSummary" in x for x in required)
    assert any("same final EV" in x for x in required)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto(URL, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_function(
            "typeof parsePokerStarsHand === 'function' && typeof makeReplaySteps === 'function' && "
            "typeof postflopSizingCandidates === 'function' && typeof sizingOptimizationSummary === 'function' && "
            "typeof finalDecisionEV === 'function' && typeof postflopDecisionAlternativeSummary === 'function' && "
            "typeof reviewBatchRegret === 'function'",
            timeout=15_000,
        )

        result = await page.evaluate(
            """raw => {
                const hand = parsePokerStarsHand(raw, 'regression-fixture');
                if (!hand) throw new Error('fixture hand did not parse');
                const replay = makeReplaySteps(hand);
                const targets = [
                  {id:'turn_check', street:'Turn', actionType:'check'},
                  {id:'river_check', street:'River', actionType:'check'},
                  {id:'river_fold', street:'River', actionType:'fold'}
                ];

                const saved = {
                  hhMode: state.hhMode,
                  selectedHand: state.selectedHand,
                  replaySteps: state.replaySteps,
                  replayIndex: state.replayIndex
                };
                state.hhMode = true;
                state.selectedHand = hand;
                state.replaySteps = replay;

                const decisions = [];
                try {
                  for (const target of targets) {
                    const matches = replay
                      .map((step, index) => ({step, index}))
                      .filter(x => x.step.activePlayer === hand.heroName && x.step.street === target.street && x.step.actionType === target.actionType);
                    if (matches.length !== 1) throw new Error(`${target.id}: expected one Hero decision, got ${matches.length}`);
                    const {step, index} = matches[0];
                    state.replayIndex = index;
                    const candidates = postflopSizingCandidates(index).map(c => ({label:c.label, kind:c.kind, costBB:Number(c.costBB)}));
                    decisions.push({id:target.id, index, actionText:step.actionText, candidates});
                  }
                } finally {
                  state.hhMode = saved.hhMode;
                  state.selectedHand = saved.selectedHand;
                  state.replaySteps = saved.replaySteps;
                  state.replayIndex = saved.replayIndex;
                }

                const summary = sizingOptimizationSummary([
                  {label:'action réelle', kind:'actual', costBB:1, tree:{evBB:1, evStdErrBB:0}},
                  {label:'125% pot', kind:'candidate', costBB:2, tree:{evBB:2, evStdErrBB:0}},
                  {label:'jam', kind:'jam', costBB:40, tree:{evBB:999, evStdErrBB:0, sanityInvalid:true, sanityReason:'regression sentinel'}}
                ], {evBB:1, evStdErrBB:0}, 4);

                const rankingProbe = [
                  {label:'jam', evBB:10, policyAdjustedEVBB:-2},
                  {label:'CALL', evBB:1, policyAdjustedEVBB:1}
                ].sort((a,b) => finalDecisionEV(b)-finalDecisionEV(a));

                return {
                  handId:String(hand.id),
                  heroName:hand.heroName,
                  decisions,
                  sanityBest:summary?.best?.label || null,
                  sanityBestInvalid:!!summary?.best?.tree?.sanityInvalid,
                  finalEvBest:rankingProbe[0]?.label || null,
                  interactiveUsesFinalEV:String(postflopDecisionAlternativeSummary).includes('finalDecisionEV'),
                  backgroundUsesFinalEV:String(reviewBatchRegret).includes('finalDecisionEV')
                };
            }""",
            fixture["raw_hand_history"],
        )

        assert result["handId"] == fixture["hand_id"], result
        assert result["heroName"] == "RoiDePiqueNique", result
        for decision in result["decisions"]:
            kinds = {str(c["kind"]) for c in decision["candidates"]}
            assert "jam" not in kinds, decision
            assert "effective_allin" in kinds, decision
        assert result["sanityBest"] == "125% pot", result
        assert not result["sanityBestInvalid"], result
        assert result["finalEvBest"] == "CALL", result
        assert result["interactiveUsesFinalEV"], result
        assert result["backgroundUsesFinalEV"], result

        print(json.dumps(result, ensure_ascii=False, indent=2))
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
