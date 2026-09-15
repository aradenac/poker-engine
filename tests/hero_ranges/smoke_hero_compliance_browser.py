#!/usr/bin/env python3
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8765/index.html"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(URL, wait_until="domcontentloaded")
    panel = page.locator("#heroCompliancePanel")
    panel.wait_for(state="attached", timeout=10_000)
    text = panel.inner_text()
    assert "Conformité range Hero" in text
    assert "Pas de range" in text or "Pas de verdict" in text
    link = panel.locator("a[href*='hero-ranges.html']")
    assert link.count() >= 1

    # The loader must have resolved the three contracts on the real static page.
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

    # Browser-loaded contracts must fail closed when exact canonical depth is absent.
    depth = page.evaluate("""() => {
      const H=window.PokerHeroRanges,C=window.PokerHeroCompliance;
      const population='pokerstars_nlhe_100-200_zoom_play_6max_v1';
      const context={population_id:population,table_size:6,position:'BTN',effective_stack_bb:100,spot:'UNOPENED'};
      const repo=H.emptyRepository({populationId:population});
      H.setHandStrategy(repo,context,'AKs',{actions:{OPEN:1},sizings:{OPEN:[{target_total_bb:2.5,probability:1}]}},{layer:'calculated'});
      const make=(stack,includeDepth=true)=>{
        const ctx={table_size:6,actor_position:'BTN',raise_level:0,family:'UNOPENED',history:[],to_call_bb:1,actor_remaining_bb:100};
        if(includeDepth)ctx.effective_stack_bb=stack;
        return {action:'RAISE',actor_position:'BTN',table_size:6,raise_level:0,family:'UNOPENED',history:[],actor_start_stack_bb:100,preflop_context_v1:ctx,action_sizing_v1:{target_total_bb:2.5}};
      };
      const exact=C.evaluateDecision({repo,decision:make(100),handClass:'AKs'});
      const near=C.evaluateDecision({repo,decision:make(99),handClass:'AKs'});
      const missing=C.evaluateDecision({repo,decision:make(null,false),handClass:'AKs'});
      return {
        exact:{context:exact.context_status,action:exact.action_status,depth:exact.depth_match},
        near:{context:near.context_status,action:near.action_status,nearest:near.nearest_context?.effective_stack_bb||null},
        missing:{context:missing.context_status,action:missing.action_status}
      };
    }""")
    assert depth == {
        "exact": {"context": "RESOLVED", "action": "COMPLIANT", "depth": "exact"},
        "near": {"context": "UNCOVERED_DEPTH", "action": "NO_VERDICT", "nearest": 100},
        "missing": {"context": "UNSUPPORTED_CONTEXT", "action": "NO_VERDICT"},
    }

    browser.close()

print("Hero compliance browser smoke: PASS")
