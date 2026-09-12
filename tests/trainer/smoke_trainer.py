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

        # Wait until Model A has produced the pending Hero recommendation and the action UI is live.
        await page.wait_for_function(
            "document.querySelector('#trainerStatus')?.textContent.includes('À vous de jouer') && document.querySelectorAll('#trainerControls [data-trainer-action]').length > 0",
            timeout=90_000,
        )

        # Default Training mode must hide the answer until Hero acts.
        rec_text = await page.locator("#trainerRecommendation").inner_text()
        assert "réponse masquée" in folded(rec_text), rec_text

        # Mode switching is independent of the current hand.
        await page.click('[data-trainer-mode="guided"]')
        guided = await page.locator("#trainerRecommendation").inner_text()
        assert "action recommandée" in folded(guided), guided
        await page.click('[data-trainer-mode="training"]')

        # Choose a passive legal action first to keep the smoke deterministic enough.
        for action in ("CHECK", "CALL", "FOLD"):
            loc = page.locator(f'#trainerControls [data-trainer-action="{action}"]')
            if await loc.count():
                await loc.first.click()
                break
        else:
            raise AssertionError("no passive Hero action available")

        await page.wait_for_function(
            "document.querySelector('#trainerFeedback .trainer-feedback-title') && !document.querySelector('#trainerFeedback .trainer-feedback-title').textContent.includes('Feedback')",
            timeout=90_000,
        )
        feedback = await page.locator("#trainerFeedback").inner_text()
        assert "recommandé" in folded(feedback) and "perte ev" in folded(feedback), feedback
        stats = await page.locator("#trainerStats").inner_text()
        assert "décisions" in folded(stats)
        decision_value = await page.locator("#trainerStats .trainer-stat").nth(1).locator(".v").inner_text()
        assert int(decision_value.strip()) >= 1

        # Trainer must not destroy the analyser navigation when returning.
        await page.click("#trainerBackBtn")
        assert await page.locator("#mainPage").is_visible()
        assert await page.locator("#trainerPage").is_hidden()

        snapshot = {
            "seats": seats,
            "guided": guided,
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
