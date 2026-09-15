#!/usr/bin/env python3
import json
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8765/index.html"
FIXTURE = Path(__file__).parents[1] / "regression" / "hand_262024556922.json"
POPULATION = "pokerstars_nlhe_100-200_zoom_play_6max_v1"

fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
raw = fixture["raw_hand_history"]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(URL, wait_until="domcontentloaded")
    panel = page.locator("#heroCompliancePanel")
    panel.wait_for(state="attached", timeout=10_000)
    text = panel.inner_text()
    assert "Conformité range Hero" in text
    assert "Pas de range" in text or "Pas de verdict" in text

    loaded = page.evaluate("""() => ({
      ranges: !!window.PokerHeroRanges,
      compliance: !!window.PokerHeroCompliance,
      adapter: !!window.PokerHeroComplianceReplayer,
      storageKey: window.PokerHeroComplianceReplayer?.STORAGE_KEY || null
    })""")
    assert loaded == {
        "ranges": True,
        "compliance": True,
        "adapter": True,
        "storageKey": "poker.hero.range.repository.v1",
    }

    result = page.evaluate(
        """({raw,population}) => {
          const H=window.PokerHeroRanges,C=window.PokerHeroCompliance,R=window.PokerHeroComplianceReplayer;
          const hand=parsePokerStarsHand(raw,'issue-140-real-hh');
          if(!hand)throw new Error('real PokerStars fixture did not parse');
          const replay=makeReplaySteps(hand);
          const trace=populationPreflopDecisionTrace(hand);
          const hero=trace.find(d=>d.player===hand.heroName);
          if(!hero)throw new Error('Hero preflop decision missing');
          const heroClass=R.handClass(hand.heroCards);
          const explicitNumericClass=R.handClass([8,24]); // Ts, Kh under suit*13+rank encoding.
          if(heroClass!=='KTo'||explicitNumericClass!=='KTo')throw new Error(`numeric hand decode failed: ${heroClass}/${explicitNumericClass}`);
          const ctx=hero.preflop_context_v1||hero;
          const spot=C.spotForDecision(hero);
          const rangeContext=H.normalizeContext({
            population_id:population,
            table_size:Number(ctx.table_size),
            position:String(ctx.actor_position),
            effective_stack_bb:Number(ctx.effective_stack_bb),
            spot
          });
          const repo=H.emptyRepository({populationId:population});
          H.setHandStrategy(repo,rangeContext,'KTo',{
            actions:{OPEN:1},
            sizings:{OPEN:[{target_total_bb:3,probability:1}]},
            notes:'issue #140 real HH smoke'
          },{layer:'personal'});
          localStorage.setItem(R.STORAGE_KEY,JSON.stringify(repo));
          state.hhHands=[hand];
          state.selectedHand=hand;
          state.replaySteps=replay;
          const index=replay.findIndex(step=>step.activePlayer===hand.heroName&&step.street==='Préflop'&&step.actionType==='raise');
          if(index<0)throw new Error('Hero preflop replay step missing');
          state.replayIndex=index;
          R.invalidate();
          return {
            handId:String(hand.id),heroCards:hand.heroCards,heroClass,spot,index,
            position:rangeContext.position,stack:rangeContext.effective_stack_bb
          };
        }""",
        {"raw": raw, "population": POPULATION},
    )
    assert result["handId"] == fixture["hand_id"]
    assert result["heroClass"] == "KTo"
    assert all(isinstance(card, int) for card in result["heroCards"]), result

    page.wait_for_function(
        "document.querySelector('#heroCompliancePanel')?.innerText.includes('Conforme') && "
        "document.querySelector('#heroCompliancePanel')?.innerText.includes('KTo · OPEN')",
        timeout=10_000,
    )
    panel_text = panel.inner_text()
    assert "Conforme" in panel_text
    assert "KTo · OPEN" in panel_text
    assert "conforme" in panel_text.lower()  # sizing is judged too.

    href = panel.locator("a[href*='hero-ranges.html?']").get_attribute("href")
    assert href, panel_text
    assert "hand=KTo" in href, href
    assert f"position={result['position']}" in href, href
    assert f"spot={result['spot']}" in href, href

    page.goto(urljoin(URL, href), wait_until="domcontentloaded")
    page.locator("#selectedHandTitle").wait_for(state="visible", timeout=10_000)
    assert page.locator("#selectedHandTitle").inner_text() == "KTo"
    assert page.locator("#positionSelect").input_value() == result["position"]
    assert page.locator("#spotSelect").input_value() == result["spot"]
    assert abs(float(page.locator("#stackInput").input_value()) - float(result["stack"])) < 1e-6
    assert page.locator('[data-hand="KTo"]').get_attribute("class").find("selected") >= 0

    browser.close()

print("Hero compliance real-HH browser smoke: PASS")
