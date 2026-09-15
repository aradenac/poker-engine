#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
URL = "http://127.0.0.1:8765/index.html"
FIXTURE = ROOT / "tests/regression/hand_262024556922.json"
POPULATION_ID = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
STORAGE_KEY = "poker.hero.range.repository.v1"

fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
raw = fixture["raw_hand_history"]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    page = browser.new_page(viewport={"width": 1500, "height": 1000})
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    page.goto(URL, wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_function(
        """
        typeof parsePokerStarsHand === 'function' &&
        typeof makeReplaySteps === 'function' &&
        typeof populationPreflopDecisionTrace === 'function' &&
        typeof replayPreflopDecisionCount === 'function' &&
        typeof cardsToNotation === 'function' &&
        !!window.PokerHeroRanges && !!window.PokerHeroCompliance &&
        !!window.PokerHeroComplianceReplayer
        """,
        timeout=20_000,
    )

    result = page.evaluate(
        """({raw,populationId,storageKey}) => {
          const hand=parsePokerStarsHand(raw,'hero-compliance-real-hh');
          if(!hand)throw new Error('fixture did not parse');
          const replay=makeReplaySteps(hand);
          const heroPreflop=replay.map((step,index)=>({step,index})).filter(x=>
            x.step.activePlayer===hand.heroName &&
            x.step.street==='Préflop' &&
            ['fold','check','call','bet','raise'].includes(x.step.actionType)
          );
          if(heroPreflop.length!==1)throw new Error(`expected one Hero preflop decision, got ${heroPreflop.length}`);
          const {step,index}=heroPreflop[0];
          state.hhMode=true;state.hhHands=[hand];state.selectedHand=hand;state.replaySteps=replay;state.replayIndex=index;

          const count=replayPreflopDecisionCount(index);
          const trace=populationPreflopDecisionTrace(hand).slice(0,count);
          const decision=[...trace].reverse().find(x=>x.player===hand.heroName);
          if(!decision)throw new Error('Hero preflop decision not found');

          const expectedHandClass=cardsToNotation(hand.heroCards);
          const adapterHandClass=window.PokerHeroComplianceReplayer.handClass(hand.heroCards);
          const planned=window.PokerHeroCompliance.plannedActionForDecision(decision);
          const spot=window.PokerHeroCompliance.spotForDecision(decision);
          if(!planned||!spot)throw new Error(`unsupported fixture context planned=${planned} spot=${spot}`);
          const ctx={
            population_id:populationId,
            table_size:Number(decision.preflop_context_v1.table_size),
            position:decision.actor_position,
            effective_stack_bb:Number(decision.preflop_context_v1.effective_stack_bb),
            spot
          };
          const target=Number(decision.action_sizing_v1?.target_total_bb);
          const actions=planned==='FOLD'?{FOLD:1}:{[planned]:.2,FOLD:.8};
          const strategy={actions,notes:'real-HH smoke'};
          if(['OPEN','ISO','3BET','4BET','SHOVE'].includes(planned)&&Number.isFinite(target)){
            strategy.sizings={[planned]:[{target_total_bb:target,probability:1}]};
          }

          const repo=window.PokerHeroRanges.emptyRepository({populationId});
          window.PokerHeroRanges.setLayerMetadata(repo,ctx,'personal',{
            version:'real-hh-smoke-v1',provenance:{kind:'browser-smoke',hand_id:String(hand.id)}
          });
          window.PokerHeroRanges.setHandStrategy(repo,ctx,expectedHandClass,strategy,{layer:'personal'});
          localStorage.setItem(storageKey,JSON.stringify(repo));
          window.PokerHeroComplianceReplayer.invalidate();

          const current=window.PokerHeroComplianceReplayer.currentEvaluation(hand,repo);
          const summary=window.PokerHeroComplianceReplayer.sessionSummary(repo);
          window.PokerHeroComplianceReplayer.render();
          return {
            handId:String(hand.id),heroName:hand.heroName,heroCards:hand.heroCards,
            expectedHandClass,adapterHandClass,planned,spot,context:ctx,target,
            current,summary,panel:document.getElementById('heroCompliancePanel')?.innerText||''
          };
        }""",
        {"raw": raw, "populationId": POPULATION_ID, "storageKey": STORAGE_KEY},
    )

    assert result["handId"] == fixture["hand_id"], result
    assert result["heroName"] == "RoiDePiqueNique", result
    assert all(isinstance(card, int) for card in result["heroCards"]), result
    assert result["expectedHandClass"] == "KTo", result
    assert result["adapterHandClass"] == result["expectedHandClass"], result
    current = result["current"]["result"]
    assert current["context_status"] == "RESOLVED", result
    assert current["hand_class"] == "KTo", result
    assert current["action_status"] == "MIXED_ALLOWED", result
    assert abs(current["action_probability"] - 0.2) < 1e-12, result
    if result["planned"] in {"OPEN", "ISO", "3BET", "4BET", "SHOVE"}:
        assert current["sizing"]["status"] == "MATCHED", result
    assert current["ev_deviation_bb"] is None and current["ev_status"] == "NOT_EVALUATED", result
    assert result["summary"]["judged"] >= 1 and result["summary"]["allowed"] >= 1, result
    assert "KTo" in result["panel"], result
    assert "Action mixée autorisée" in result["panel"], result

    editor_href = current["editor_href"]
    assert "hand=KTo" in editor_href, editor_href
    page.goto(f"http://127.0.0.1:8765/{editor_href.removeprefix('./')}", wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_function("document.querySelectorAll('#heroGrid .hand-cell').length===169", timeout=20_000)
    assert page.locator("#positionSelect").input_value() == result["context"]["position"]
    assert page.locator("#spotSelect").input_value() == result["context"]["spot"]
    assert abs(float(page.locator("#stackInput").input_value()) - float(result["context"]["effective_stack_bb"])) < 1e-9
    selected = page.locator("#heroGrid .hand-cell.selected")
    assert selected.count() == 1
    assert selected.get_attribute("data-hand") == "KTo"

    if page_errors:
        raise AssertionError(page_errors)
    browser.close()

print("Hero compliance real-HH browser smoke: PASS")
