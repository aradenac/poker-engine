#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import sys
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8765/index.html"


def folded(text: str) -> str:
    return text.casefold()


async def main() -> None:
    page_errors: list[str] = []
    console_errors: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = await browser.new_page(viewport={"width": 1500, "height": 1000})
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        await page.goto(URL, wait_until="domcontentloaded", timeout=45_000)

        # Replayer hand-class helper runs in the real assembled browser application.
        hand_classes = await page.evaluate(
            "() => ({suited:replayHandClass(['As','Ks']), offsuit:replayHandClass(['Ah','Kd']), pair:replayHandClass(['7c','7d']), hidden:replayHandClass(null), backs:replayHandClass([null,null])})"
        )
        assert hand_classes == {"suited": "AKs", "offsuit": "AKo", "pair": "77", "hidden": "", "backs": ""}, hand_classes

        await page.wait_for_selector("#trainerOpenBtn", timeout=10_000)
        await page.click("#trainerOpenBtn")

        await page.wait_for_function(
            "document.querySelector('#trainerStatus')?.textContent.includes('Trainer prêt') || document.querySelector('#trainerStatus')?.textContent.includes('À vous de jouer') || document.querySelector('#trainerStatus')?.textContent.includes('Nouvelle main')",
            timeout=90_000,
        )
        await page.wait_for_selector("#trainerPage:not(.mode-hidden)", timeout=10_000)
        await page.wait_for_selector("#trainerTable .poker-table", timeout=30_000)
        seats = await page.locator("#trainerTable .seat").count()
        assert seats == 6, f"expected 6 trainer seats, got {seats}"
        assert await page.locator("#trainerTable .seat.hero").count() == 1

        # Hero must be dealt from the persisted Custom range for this exact role/position.
        hero_range = await page.evaluate(
            "() => { const h=trainerState.hand, p=h.positions[h.heroSeat], n=cardsToNotation(h.hole[h.heroSeat]); return {role:h.heroRole, position:p, notation:n, frequency:Number(trainerState.heroRanges?.ranges?.[h.heroRole]?.[p]?.[n]||0)}; }"
        )
        assert hero_range["frequency"] > 0, hero_range
        assert not (hero_range["role"] == "CALLER" and hero_range["position"] == "BB"), hero_range

        # Wait until Model A has produced the pending Hero recommendation and the action UI is live.
        await page.wait_for_function(
            "document.querySelector('#trainerStatus')?.textContent.includes('À vous de jouer') && document.querySelectorAll('#trainerControls [data-trainer-action]').length > 0",
            timeout=90_000,
        )

        # Default Training mode must hide the answer until Hero acts.
        rec_text = await page.locator("#trainerRecommendation").inner_text()
        assert "réponse masquée" in folded(rec_text), rec_text

        # Switching to Guided mid-decision must compute a real recommendation.
        await page.click('[data-trainer-mode="guided"]')
        await page.wait_for_function(
            "trainerState.recommendation && !trainerState.recommendation.error && trainerRecommendationKind(trainerState.hand, trainerState.recommendation)",
            timeout=90_000,
        )
        guided = await page.locator("#trainerRecommendation").inner_text()
        assert "action recommandée" in folded(guided) and "ev —" not in folded(guided), guided
        guide = await page.evaluate(
            "() => ({label: trainerState.recommendation.bestLabel, cost: Number(trainerState.recommendation.bestCostBB), ev: Number(trainerState.recommendation.bestEV), kind: trainerRecommendationKind(trainerState.hand, trainerState.recommendation)})"
        )
        assert guide["kind"] in {"FOLD", "CHECK", "CALL", "BET", "RAISE"}, guide
        action = page.locator(f'#trainerControls [data-trainer-action="{guide["kind"]}"]')
        assert await action.count(), f"guided action button missing: {guide}"
        await action.first.click()

        await page.wait_for_function(
            "document.querySelector('#trainerFeedback .trainer-feedback-title') && !document.querySelector('#trainerFeedback .trainer-feedback-title').textContent.includes('Feedback')",
            timeout=90_000,
        )
        feedback = await page.locator("#trainerFeedback").inner_text()
        assert "recommandé" in folded(feedback) and "perte ev" in folded(feedback), feedback
        verdict = await page.evaluate(
            "() => ({label: trainerState.feedback?.detail?.bestLabel, cost: Number(trainerState.feedback?.detail?.bestCostBB), ev: Number(trainerState.feedback?.detail?.bestEV), chosen: Number(trainerState.feedback?.detail?.chosenEV), loss: Number(trainerState.feedback?.row?.lossBB), reused: Number(trainerState.perf.reused)})"
        )
        assert verdict["label"] == guide["label"], (guide, verdict)
        if guide["cost"] == guide["cost"]:
            assert abs(verdict["cost"] - guide["cost"]) <= 1e-9, (guide, verdict)
        assert abs(verdict["ev"] - guide["ev"]) <= 1e-9, (guide, verdict)
        assert verdict["loss"] <= 0.15, (guide, verdict, feedback)
        assert verdict["reused"] >= 1, (guide, verdict)
        stats = await page.locator("#trainerStats").inner_text()
        assert "décisions" in folded(stats)
        decision_value = await page.locator("#trainerStats .trainer-stat").nth(1).locator(".v").inner_text()
        assert int(decision_value.strip()) >= 1

        # Trainer must not destroy the analyser navigation when returning.
        await page.click("#trainerBackBtn")
        assert await page.locator("#mainPage").is_visible()
        assert await page.locator("#trainerPage").is_hidden()

        snapshot = {
            "replayer_hand_classes": hand_classes,
            "seats": seats,
            "hero_range": hero_range,
            "guided": guided,
            "guide_state": guide,
            "verdict_state": verdict,
            "feedback": feedback,
            "stats": stats,
            "page_errors": page_errors,
            "console_errors": console_errors,
        }
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        if page_errors:
            raise AssertionError(f"page errors: {page_errors}")
        await browser.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"trainer smoke failed: {exc}", file=sys.stderr)
        raise
