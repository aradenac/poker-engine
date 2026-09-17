#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "regression" / "hand_262024556922.json"
URL = "http://127.0.0.1:8765/index.html"
POPULATION = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
STORAGE_KEY = "poker.hero.range.repository.v1"

fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
raw_hand = fixture["raw_hand_history"]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    page = browser.new_page(viewport={"width": 1400, "height": 1000})
    page.goto(URL, wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_function(
        "typeof parsePokerStarsHand === 'function' && typeof makeReplaySteps === 'function' && "
        "typeof populationPreflopDecisionTrace === 'function' && !!window.PokerHeroRanges && "
        "!!window.PokerHeroCompliance && !!window.PokerHeroComplianceReplayer",
        timeout=15_000,
    )

    setup = page.evaluate(
        """({raw, population, storageKey}) => {
          const hand = parsePokerStarsHand(raw, 'issue-140-fixture');
          if (!hand) throw new Error('fixture hand did not parse');
          const R = window.PokerHeroComplianceReplayer;
          const H = window.PokerHeroRanges;
          const C = window.PokerHeroCompliance;
          const handClass = R.handClass(hand.heroCards);
          const trace = populationPreflopDecisionTrace(hand);
          const decision = trace.find(d => d.player === hand.heroName);
          if (!decision) throw new Error('Hero preflop decision missing');
          const ctx0 = decision.preflop_context_v1;
          const spot = C.spotForDecision(decision);
          const context = {
            population_id: population,
            table_size: ctx0.table_size,
            position: ctx0.actor_position,
            effective_stack_bb: ctx0.effective_stack_bb,
            spot
          };
          const repo = H.emptyRepository({populationId: population});
          H.setLayerMetadata(repo, context, 'personal', {version:'issue-140-fixture', provenance:{fixture:'262024556922'}});
          H.setHandStrategy(repo, context, handClass, {
            actions:{OPEN:1},
            sizings:{OPEN:[{target_total_bb:Number(decision.action_sizing_v1.target_total_bb), probability:1}]},
            notes:'real HH smoke'
          }, {layer:'personal'});
          localStorage.setItem(storageKey, JSON.stringify(repo));

          state.hhHands = [hand];
          state.hhMode = true;
          state.selectedHand = hand;
          state.replaySteps = makeReplaySteps(hand);
          const stepIndex = state.replaySteps.findIndex(s => s.activePlayer === hand.heroName && s.street === 'Préflop' && s.actionType === 'raise');
          if (stepIndex < 0) throw new Error('Hero replay decision missing');
          state.replayIndex = stepIndex;
          state.appView = 'replayer';
          if (typeof updateAppView === 'function') updateAppView();
          R.invalidate();
          const evaluated = R.currentEvaluation(hand, repo).result;
          return {
            handId:String(hand.id),
            heroCards:[...hand.heroCards],
            handClass,
            spot,
            position:context.position,
            stack:context.effective_stack_bb,
            stepIndex,
            actionStatus:evaluated?.action_status || null,
            sizingStatus:evaluated?.sizing?.status || null,
            editorHref:evaluated?.editor_href || null,
            contextStatus:evaluated?.context_status || null
          };
        }""",
        {"raw": raw_hand, "population": POPULATION, "storageKey": STORAGE_KEY},
    )

    assert setup["handId"] == fixture["hand_id"], setup
    assert all(isinstance(card, int) for card in setup["heroCards"]), setup
    assert setup["handClass"] == "KTo", setup
    assert setup["spot"] == "UNOPENED", setup
    assert setup["actionStatus"] == "COMPLIANT", setup
    assert setup["sizingStatus"] == "MATCHED", setup
    assert setup["contextStatus"] == "RESOLVED", setup
    assert "hand=KTo" in setup["editorHref"], setup

    panel = page.locator("#heroCompliancePanel")
    panel.wait_for(state="visible", timeout=10_000)
    text = panel.inner_text()
    assert "Conforme" in text, text
    assert "KTo" in text, text
    assert "OPEN" in text, text
    link = panel.locator("a.hc-link")
    href = link.get_attribute("href") or ""
    assert "hand=KTo" in href, href
    link.click()
    page.wait_for_url("**/hero-ranges.html?**", timeout=15_000)
    page.locator("#selectedHandTitle").wait_for(state="visible", timeout=10_000)
    assert page.locator("#selectedHandTitle").inner_text() == "KTo"
    assert page.locator('[data-hand="KTo"].selected').count() == 1
    assert page.locator("#positionSelect").input_value() == setup["position"]
    assert page.locator("#spotSelect").input_value() == setup["spot"]
    assert abs(float(page.locator("#stackInput").input_value()) - float(setup["stack"])) < 1e-9
    assert page.locator("#populationInput").input_value() == POPULATION

    # The editor also canonicalizes an uppercase suffix from an external/deprecated link.
    upper_url = page.url.replace("hand=KTo", "hand=KTO")
    page.goto(upper_url, wait_until="domcontentloaded", timeout=15_000)
    assert page.locator("#selectedHandTitle").inner_text() == "KTo"
    assert page.locator('[data-hand="KTo"].selected').count() == 1

    print(json.dumps(setup, ensure_ascii=False, indent=2))
    browser.close()

print("Hero compliance real-HH browser smoke: PASS")
