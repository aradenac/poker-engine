#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import base64
import gzip
import json
import sys
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
URL = "http://127.0.0.1:8765/hero-ranges.html"
STORAGE_KEY = "poker.hero.range.repository.v1"


def archived_custom_bytes() -> bytes:
    encoded = (ROOT / "user/artifacts/NLHE_100-200/custom.json.gz.b64").read_text(encoding="utf-8").strip()
    return gzip.decompress(base64.b64decode(encoded))


async def main() -> None:
    errors: list[str] = []
    source_bytes = archived_custom_bytes()
    source = json.loads(source_bytes)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = await browser.new_page(viewport={"width": 1500, "height": 1100})
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        await page.goto(URL, wait_until="domcontentloaded", timeout=45_000)
        assert await page.locator("#heroGrid .hand-cell").count() == 169

        await page.locator("#quickAction").select_option("OPEN")
        await page.click("#quickApply")
        repo = await page.evaluate(f"JSON.parse(localStorage.getItem('{STORAGE_KEY}'))")
        assert len(repo["contexts"]) == 1
        node = next(iter(repo["contexts"].values()))
        assert node["layers"]["personal"]["hands"]["AA"]["actions"] == {"OPEN": 1}

        await page.locator('[data-action-prob="OPEN"]').fill("75")
        await page.locator('[data-action-prob="LIMP"]').fill("25")
        await page.locator('[data-action-size="OPEN"]').fill("2.2:40%, 2.5:60%")
        await page.click("#saveHand")
        repo = await page.evaluate(f"JSON.parse(localStorage.getItem('{STORAGE_KEY}'))")
        node = next(iter(repo["contexts"].values()))
        aa = node["layers"]["personal"]["hands"]["AA"]
        assert aa["actions"] == {"LIMP": 0.25, "OPEN": 0.75} or aa["actions"] == {"OPEN": 0.75, "LIMP": 0.25}
        assert aa["sizings"]["OPEN"] == [
            {"target_total_bb": 2.2, "probability": 0.4},
            {"target_total_bb": 2.5, "probability": 0.6},
        ]

        await page.locator("#heroRangeImport").set_input_files(
            files={"name": "custom.json", "mimeType": "application/json", "buffer": source_bytes}
        )
        await page.wait_for_function("document.querySelector('#sourceBadge')?.textContent.includes('préservée')")
        assert await page.locator("#sourceRangeSelect option").count() > 0
        imported = await page.evaluate(f"JSON.parse(localStorage.getItem('{STORAGE_KEY}'))")
        assert imported["source"]["preserved_verbatim"] is True
        assert imported["source"]["range_folder"] == source
        imported_node = next(iter(imported["contexts"].values()))
        imported_aa = imported_node["layers"]["personal"]["hands"]["AA"]
        assert imported_aa["actions"] == aa["actions"], "legacy source refresh must preserve personal customization"
        assert imported_aa["sizings"] == aa["sizings"]

        await page.locator("#quickAction").select_option("OPEN")
        await page.click("#quickApply")
        edited = await page.evaluate(f"JSON.parse(localStorage.getItem('{STORAGE_KEY}'))")
        assert edited["source"]["range_folder"] == source, "editing must not rewrite imported range-folder"

        await page.click("#undefineHand")
        after_undefine = await page.evaluate(f"JSON.parse(localStorage.getItem('{STORAGE_KEY}'))")
        node = next(iter(after_undefine["contexts"].values()))
        assert "AA" not in node["layers"]["personal"]["hands"]
        assert "non défini" in (await page.locator("#selectedHandState").inner_text()).casefold()

        snapshot = {
            "grid_cells": await page.locator("#heroGrid .hand-cell").count(),
            "source_ranges": await page.locator("#sourceRangeSelect option").count(),
            "source_preserved": edited["source"]["preserved_verbatim"],
            "customization_survived_source_refresh": True,
            "errors": errors,
        }
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        if errors:
            raise AssertionError(errors)
        await browser.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"Hero range editor smoke failed: {exc}", file=sys.stderr)
        raise
