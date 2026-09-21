#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "regression" / "hand_262024556922.json"
MANIFEST = ROOT / "site" / "assets" / "trainer" / "population.json"
URL = "http://127.0.0.1:8765/index.html"
# The analyser's active population is the served trainer population manifest.
# A repository bound to any other population must fail closed.
POPULATION = json.loads(MANIFEST.read_text(encoding="utf-8"))["population_id"]
FOREIGN_POPULATION = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
assert FOREIGN_POPULATION != POPULATION, "the foreign fixture population must differ from the active one"
STORAGE_KEY = "poker.hero.range.repository.v1"

fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
raw_hand = fixture["raw_hand_history"]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    page = browser.new_page(viewport={"width": 1400, "height": 1000})
    page.goto(URL, wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_function(
        "typeof parsePokerStarsHand === 'function' && typeof makeReplaySteps === 'function' && "
        "typeof populationPreflopDecisionTrace === 'function' && typeof trainerState !== 'undefined' && "
        "!!window.PokerHeroRanges && !!window.PokerHeroCompliance && !!window.PokerHeroComplianceReplayer && "
        "!!window.PokerHeroStrategyResolver",
        timeout=15_000,
    )
    # The application restores models/ranges asynchronously after DOMContentLoaded.
    # Manipulating the global state before those fetches settle can be overwritten by
    # the final initialization render and spuriously hide the compliance panel.
    page.wait_for_load_state("networkidle", timeout=20_000)

    setup = page.evaluate(
        """({raw, activePopulation, foreignPopulation, storageKey}) => {
          const hand = parsePokerStarsHand(raw, 'issue-392-fixture');
          if (!hand) throw new Error('fixture hand did not parse');
          const R = window.PokerHeroComplianceReplayer;
          const H = window.PokerHeroRanges;
          const C = window.PokerHeroCompliance;
          const Resolver = window.PokerHeroStrategyResolver;
          const handClass = R.handClass(hand.heroCards);
          const trace = populationPreflopDecisionTrace(hand);
          const decision = trace.find(d => d.player === hand.heroName);
          if (!decision) throw new Error('Hero preflop decision missing');
          const ctx0 = decision.preflop_context_v1;
          const spot = C.spotForDecision(decision);
          const targetTotalBb = Number(decision.action_sizing_v1.target_total_bb);
          const contextFor = population => ({
            population_id: population,
            table_size: ctx0.table_size,
            position: ctx0.actor_position,
            effective_stack_bb: ctx0.effective_stack_bb,
            spot
          });

          // The active population is the scope the compliance verdict must obey.
          trainerState.populationId = activePopulation;
          trainerState.heroStrategyResolution = null;

          state.hhHands = [hand];
          state.hhMode = true;
          state.selectedHand = hand;
          state.replaySteps = makeReplaySteps(hand);
          const stepIndex = state.replaySteps.findIndex(s => s.activePlayer === hand.heroName && s.street === 'Préflop' && s.actionType === 'raise');
          if (stepIndex < 0) throw new Error('Hero replay decision missing');
          state.replayIndex = stepIndex;
          state.appView = 'replayer';
          if (typeof updateAppView === 'function') updateAppView();

          const panel = () => document.getElementById('heroCompliancePanel');
          const strategy = () => ({
            actions: {OPEN: 1},
            sizings: {OPEN: [{target_total_bb: targetTotalBb, probability: 1}]},
            notes: 'issue-392 fixture'
          });

          // --- 1. a repository bound to another population fails closed --------
          const foreign = H.emptyRepository({populationId: foreignPopulation});
          H.setLayerMetadata(foreign, contextFor(foreignPopulation), 'personal', {version: 'issue-392-foreign', provenance: {fixture: 'cross-population'}});
          H.setHandStrategy(foreign, contextFor(foreignPopulation), handClass, strategy(), {layer: 'personal'});
          localStorage.setItem(storageKey, JSON.stringify(foreign));
          R.invalidate();
          const foreignEvaluation = R.currentEvaluation(hand, foreign).result;
          const foreignPanel = panel().innerText;

          // --- 2. a personal override is reported as override ------------------
          const personal = H.emptyRepository({populationId: activePopulation});
          H.setLayerMetadata(personal, contextFor(activePopulation), 'personal', {version: 'issue-392-override', provenance: {fixture: 'personal-override'}});
          H.setHandStrategy(personal, contextFor(activePopulation), handClass, strategy(), {layer: 'personal'});
          localStorage.setItem(storageKey, JSON.stringify(personal));
          R.invalidate();
          const personalEvaluation = R.currentEvaluation(hand, personal).result;
          const personalPanel = panel().innerText;

          // --- 3. an admitted calculated population strategy authorizes a verdict
          const admitted = H.emptyRepository({populationId: activePopulation});
          const admittedSha = 'a'.repeat(64);
          const admittedBinding = 'b'.repeat(64);
          H.setLayerMetadata(admitted, contextFor(activePopulation), 'calculated', {
            version: 'gen-196',
            provenance: {
              source: 'fixture',
              candidate_id: 'hero-candidate-196',
              generation_id: 'gen-196',
              manifest_sha256: admittedSha,
              binding_sha256: admittedBinding
            }
          });
          for (const hc of H.HAND_CLASSES) H.setHandStrategy(admitted, contextFor(activePopulation), hc, {actions: {FOLD: 1}}, {layer: 'calculated'});
          H.setHandStrategy(admitted, contextFor(activePopulation), handClass, strategy(), {layer: 'calculated'});
          const admittedResolution = Resolver.resolveHeroStrategy({
            population_id: activePopulation,
            repository: admitted,
            // #task-ewo: completeness must be bounded by an explicit
            // authoritative required context set.
            required_context_keys: [H.contextKey(contextFor(activePopulation))],
            admissions: {hero_strategy: {
              status: 'ADMISSIBLE',
              role: 'hero_strategy',
              population_id: activePopulation,
              candidate_id: 'hero-candidate-196',
              generation_id: 'gen-196',
              binding_sha256: admittedBinding,
              artifact: {declared_sha256: admittedSha, actual_sha256: admittedSha, hash_kind: 'file_sha256', verified: true},
              provenance: {
                source_population_id: activePopulation,
                manifest_sha256: admittedSha,
                binding_sha256: admittedBinding,
                candidate_id: 'hero-candidate-196',
                generation_id: 'gen-196'
              }
            }}
          });
          const admittedEvaluation = R.currentEvaluation(hand, admitted, admittedResolution).result;

          return {
            handId: String(hand.id),
            heroCards: [...hand.heroCards],
            handClass,
            spot,
            position: contextFor(activePopulation).position,
            stack: contextFor(activePopulation).effective_stack_bb,
            stepIndex,
            foreignAction: foreignEvaluation && foreignEvaluation.action_status,
            foreignContext: foreignEvaluation && foreignEvaluation.context_status,
            foreignSource: foreignEvaluation && foreignEvaluation.strategy_source,
            foreignPanel,
            personalAction: personalEvaluation && personalEvaluation.action_status,
            personalStrategySource: personalEvaluation && personalEvaluation.strategy_source,
            personalLayer: personalEvaluation && personalEvaluation.layer,
            personalEditorHref: personalEvaluation && personalEvaluation.editor_href,
            personalPanel,
            admittedStatus: admittedResolution && admittedResolution.status,
            admittedAction: admittedEvaluation && admittedEvaluation.action_status,
            admittedSource: admittedEvaluation && admittedEvaluation.strategy_source,
            admittedSizing: admittedEvaluation && admittedEvaluation.sizing && admittedEvaluation.sizing.status
          };
        }""",
        {
            "raw": raw_hand,
            "activePopulation": POPULATION,
            "foreignPopulation": FOREIGN_POPULATION,
            "storageKey": STORAGE_KEY,
        },
    )

    assert setup["handId"] == fixture["hand_id"], setup
    assert all(isinstance(card, int) for card in setup["heroCards"]), setup
    assert setup["handClass"] == "KTo", setup
    assert setup["spot"] == "UNOPENED", setup

    # 1. The compliance never evaluates a strategy from another population.
    assert setup["foreignContext"] == "POPULATION_INCOMPATIBLE", setup
    assert setup["foreignAction"] == "NO_VERDICT", setup
    assert setup["foreignSource"] == "NONE", setup
    assert "Hors population" in setup["foreignPanel"], setup["foreignPanel"]
    assert "Conforme" not in setup["foreignPanel"], setup["foreignPanel"]

    # 2. The personal override is reported as an override, never as the population strategy.
    assert setup["personalAction"] == "COMPLIANT", setup
    assert setup["personalStrategySource"] == "PERSONAL_OVERRIDE", setup
    assert setup["personalLayer"] == "personal", setup
    assert "override personnel" in setup["personalPanel"], setup["personalPanel"]
    assert "Conforme" in setup["personalPanel"], setup["personalPanel"]
    assert "KTo" in setup["personalPanel"], setup["personalPanel"]
    assert "OPEN" in setup["personalPanel"], setup["personalPanel"]
    assert "hand=KTo" in (setup["personalEditorHref"] or ""), setup
    assert f"population={POPULATION}" in (setup["personalEditorHref"] or ""), setup

    # 3. An admitted calculated population strategy is the only population verdict.
    assert setup["admittedStatus"] == "ADMISSIBLE_CALCULATED", setup
    assert setup["admittedSource"] == "POPULATION", setup
    assert setup["admittedAction"] == "COMPLIANT", setup
    assert setup["admittedSizing"] == "MATCHED", setup

    # The panel still deep-links the personal override into the Hero range editor.
    panel = page.locator("#heroCompliancePanel")
    panel.wait_for(state="visible", timeout=10_000)
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
