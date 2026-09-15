#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
URL = "http://127.0.0.1:8765/index.html"
FIXTURE = ROOT / "tests/regression/hand_262024556922.json"
POPULATION_ID = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
STORAGE_KEY = "poker.hero.range.repository.v1"


async def main() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw = fixture["raw_hand_history"]
    errors: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = await browser.new_page(viewport={"width": 1500, "height": 1000})
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        await page.goto(URL, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_function(
            """
            typeof parsePokerStarsHand === 'function' &&
            typeof makeReplaySteps === 'function' &&
            typeof populationPreflopDecisionTrace === 'function' &&
            typeof replayPreflopDecisionCount === 'function' &&
            typeof heroRangeComplianceForStep === 'function' &&
            typeof heroRangeCompliancePillHtml === 'function' &&
            typeof heroRangeComplianceDetailHtml === 'function' &&
            typeof heroRangeComplianceSummaryHtml === 'function' &&
            !!window.PokerHeroRanges && !!window.PokerHeroCompliance
            """,
            timeout=20_000,
        )

        result = await page.evaluate(
            """({raw,populationId,storageKey}) => {
              const hand=parsePokerStarsHand(raw,'hero-compliance-fixture');
              if(!hand)throw new Error('fixture did not parse');
              const replay=makeReplaySteps(hand);
              const saved={
                hhMode:state.hhMode, selectedHand:state.selectedHand,
                replaySteps:state.replaySteps, replayIndex:state.replayIndex
              };
              try{
                state.hhMode=true;state.selectedHand=hand;state.replaySteps=replay;
                const heroPreflop=replay.map((step,index)=>({step,index})).filter(x=>
                  x.step.activePlayer===hand.heroName &&
                  x.step.street==='Préflop' &&
                  ['fold','check','call','bet','raise'].includes(x.step.actionType)
                );
                if(heroPreflop.length!==1)throw new Error(`expected one Hero preflop decision, got ${heroPreflop.length}`);
                const {step,index}=heroPreflop[0];state.replayIndex=index;

                const count=replayPreflopDecisionCount(index);
                const trace=populationPreflopDecisionTrace(hand).slice(0,count);
                const decision=[...trace].reverse().find(x=>x.player===hand.heroName);
                if(!decision)throw new Error('Hero preflop decision not found');
                const handClass=cardsToNotation(hand.heroCards);
                const planned=window.PokerHeroCompliance.plannedActionForDecision(decision);
                const spot=window.PokerHeroCompliance.spotForDecision(decision);
                const ctx={
                  population_id:populationId,
                  table_size:Number(decision.preflop_context_v1.table_size),
                  position:decision.actor_position,
                  effective_stack_bb:Number(decision.preflop_context_v1.effective_stack_bb),
                  spot
                };
                const observedTarget=Number(decision.action_sizing_v1?.target_total_bb);
                if(!Number.isFinite(observedTarget))throw new Error('fixture aggressive sizing target missing');

                const repo=window.PokerHeroRanges.emptyRepository({populationId});
                window.PokerHeroRanges.setLayerMetadata(repo,ctx,'personal',{
                  version:'smoke-personal-v1',provenance:{kind:'browser-smoke'}
                });
                window.PokerHeroRanges.setHandStrategy(repo,ctx,handClass,{
                  actions:{[planned]:.2,FOLD:.8},
                  sizings:{[planned]:[{target_total_bb:observedTarget,probability:1}]},
                  notes:'smoke 20% mixed action'
                },{layer:'personal'});
                localStorage.setItem(storageKey,JSON.stringify(repo));

                const mixed=heroRangeComplianceForStep(index,step);
                const pill=heroRangeCompliancePillHtml(index,step);
                const detail=heroRangeComplianceDetailHtml(index,step);
                const summary=heroRangeComplianceSummaryHtml();
                const mixedToken=mixed?.repository_token||null;

                window.PokerHeroRanges.setHandStrategy(repo,ctx,handClass,{
                  actions:{FOLD:1},notes:'smoke fold only'
                },{layer:'personal'});
                localStorage.setItem(storageKey,JSON.stringify(repo));
                const out=heroRangeComplianceForStep(index,step);

                return {
                  handId:String(hand.id),heroName:hand.heroName,handClass,index,
                  planned,spot,context:ctx,observedTarget,
                  mixed,out,mixedToken,outToken:out?.repository_token||null,
                  pill,detail,summary,
                  wiring:{
                    feed:String(actionAnalysisHtml).includes('heroRangeCompliance'),
                    detail:String(actionDetailModalInnerHtml).includes('heroRangeComplianceDetailHtml'),
                    summary:String(renderVisualReplay).includes('heroRangeComplianceSummaryHtml')
                  }
                };
              }finally{
                state.hhMode=saved.hhMode;state.selectedHand=saved.selectedHand;
                state.replaySteps=saved.replaySteps;state.replayIndex=saved.replayIndex;
              }
            }""",
            {"raw": raw, "populationId": POPULATION_ID, "storageKey": STORAGE_KEY},
        )

        assert result["handId"] == fixture["hand_id"], result
        assert result["heroName"] == "RoiDePiqueNique", result
        assert result["handClass"] == "KTo", result
        assert result["planned"] in {"OPEN", "ISO", "3BET", "4BET", "SHOVE"}, result
        assert result["mixed"]["action_status"] == "MIXED_ALLOWED", result
        assert abs(result["mixed"]["action_probability"] - 0.2) < 1e-12, result
        assert result["mixed"]["sizing"]["status"] == "MATCHED", result
        assert result["mixed"]["ev_deviation_bb"] is None, result
        assert result["mixed"]["ev_status"] == "NOT_EVALUATED", result
        assert result["mixed"]["frequency_calibration_status"] == "SAMPLE_REQUIRED", result
        assert result["out"]["action_status"] == "OUT_OF_RANGE", result
        assert result["mixedToken"] != result["outToken"], result
        assert "Mix autorisé" in result["pill"], result
        assert "Écart d’EV : non évalué" in result["detail"], result
        assert "Plan Hero" in result["summary"], result
        assert all(result["wiring"].values()), result
        serialized = json.dumps(result["mixed"], ensure_ascii=False)
        assert "board" not in result["mixed"], result
        assert "4d" not in serialized and "8h" not in serialized and "Ah" not in serialized, result

        editor_href = result["mixed"]["editor_href"]
        await page.goto(
            f"http://127.0.0.1:8765/{editor_href.removeprefix('./')}",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        await page.wait_for_function("document.querySelectorAll('#heroGrid .hand-cell').length===169")
        assert await page.locator("#positionSelect").input_value() == result["context"]["position"]
        assert await page.locator("#spotSelect").input_value() == result["context"]["spot"]
        assert abs(float(await page.locator("#stackInput").input_value()) - float(result["context"]["effective_stack_bb"])) < 1e-9
        selected = page.locator("#heroGrid .hand-cell.selected")
        assert await selected.count() == 1
        assert await selected.get_attribute("data-hand") == result["handClass"]

        if errors:
            raise AssertionError(errors)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
