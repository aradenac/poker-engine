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

    browser.close()

print("Hero compliance browser smoke: PASS")
