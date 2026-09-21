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
    html_source = (ROOT / "site/hero-ranges.html").read_text(encoding="utf-8")
    app_source = (ROOT / "site/hero-ranges-app.js").read_text(encoding="utf-8")
    visible_sources = html_source + "\n" + app_source
    assert "Ranges Hero" not in visible_sources
    assert ">Range source<" not in html_source
    assert "ranges personnelles" not in visible_sources.casefold()
    assert "range personnelle" not in visible_sources.casefold()
    assert "range calculée" not in visible_sources.casefold()
    assert "Stratégie Hero" in visible_sources
    assert "Stratégie calculée" in visible_sources
    assert "Stratégie personnelle" in visible_sources
    assert "Range source importée" in visible_sources

    # The editor is wired to the population-bound resolver and the safe migration:
    # the shared modules load in contract order before the editor application.
    ordered_scripts = ["./hero-ranges.js", "./hero-range-migration.js", "./hero-strategy-resolver.js", "./hero-ranges-app.js"]
    script_positions = [html_source.index(name) for name in ordered_scripts]
    assert script_positions == sorted(script_positions), "Hero editor dependencies must load before the app"
    assert "PokerHeroRangeMigration" in app_source and "migrateStorage" in app_source
    assert "PokerHeroStrategyResolver" in app_source and "resolveHeroStrategy" in app_source
    assert "PERSONAL_OVERRIDE" in app_source, "the personal layer must be labelled as an override"
    assert "override personnel" in app_source
    source_bytes = archived_custom_bytes()
    source = json.loads(source_bytes)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = await browser.new_page(viewport={"width": 1500, "height": 1100})
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        await page.goto(URL, wait_until="domcontentloaded", timeout=45_000)
        assert await page.locator("#heroGrid .hand-cell").count() == 169
        assert (await page.locator("h1").inner_text()).strip() == "Stratégie Hero"
        assert (await page.locator(".source-panel h2").inner_text()).strip() == "Range source importée"
        assert "Range source importée" in (await page.locator('label:has(#sourceRangeSelect)').inner_text())
        visible_text = await page.locator("body").inner_text()
        assert "Ranges Hero" not in visible_text
        assert "Stratégie calculée" in visible_text
        assert "Stratégie personnelle" in visible_text
        assert "override personnel" in visible_text.casefold()

        # The default repository context is population-bound.
        assert "population liée" in (await page.locator("#populationBindingBadge").inner_text()).casefold()

        # Safe migration at load: a pre-migration payload is upgraded additively,
        # the exact previous bytes are snapshotted, and source/layers survive.
        pre_raw = await page.evaluate(
            f"""() => {{
              const H = window.PokerHeroRanges;
              const repo = H.emptyRepository({{populationId:'pokerstars_nlhe_100-200_zoom_play_6max_v1'}});
              repo.source = {{format:'range-folder',preserved_verbatim:true,meta:null,range_folder:{{folder:{{name:'Seed',folders:[],ranges:[]}}}}}};
              const context = {{population_id:'pokerstars_nlhe_100-200_zoom_play_6max_v1',table_size:6,position:'BTN',effective_stack_bb:100,spot:'UNOPENED'}};
              H.setHandStrategy(repo, context, 'AA', {{actions:{{OPEN:0.5,LIMP:0.5}},notes:'seed override'}}, {{layer:'personal'}});
              localStorage.removeItem('{STORAGE_KEY}.previous');
              const raw = JSON.stringify(repo);
              localStorage.setItem('{STORAGE_KEY}', raw);
              return raw;
            }}"""
        )
        await page.reload(wait_until="domcontentloaded")
        pre = json.loads(pre_raw)
        migrated = await page.evaluate(f"JSON.parse(localStorage.getItem('{STORAGE_KEY}'))")
        assert migrated["migration"]["schema"] == "poker-hero-range-migration/v1"
        assert migrated["migration"]["active_population_id"] == "pokerstars_nlhe_100-200_zoom_play_6max_v1"
        assert migrated["source"] == pre["source"], "migration must preserve the verbatim source"
        assert migrated["contexts"] == pre["contexts"], "migration must preserve contexts and layers"
        previous_raw = await page.evaluate(f"localStorage.getItem('{STORAGE_KEY}.previous')")
        assert previous_raw == pre_raw, "migration must snapshot the exact pre-migration bytes"
        assert (await page.locator('[data-hand="AA"]').get_attribute("data-override")) == "true"
        assert (await page.locator('[data-hand="AA"]').get_attribute("data-source")) == "PERSONAL_OVERRIDE"
        assert "override personnel" in (await page.locator("#handStatus").inner_text()).casefold()

        # A context whose population_id does not match the bound repository fails
        # closed and can never persist an edit.
        before_save = await page.evaluate(f"localStorage.getItem('{STORAGE_KEY}')")
        await page.fill("#populationInput", "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1")
        await page.locator("#populationInput").dispatch_event("change")
        assert "hors population" in (await page.locator("#populationBindingBadge").inner_text()).casefold()
        assert "POPULATION_INCOMPATIBLE" in (await page.locator("#resolutionStatus").inner_text())
        await page.click("#saveHand")
        assert "incompatible" in (await page.locator("#handStatus").inner_text()).casefold()
        after_save = await page.evaluate(f"localStorage.getItem('{STORAGE_KEY}')")
        assert before_save == after_save, "an out-of-population edit must never be persisted"
        await page.fill("#populationInput", "pokerstars_nlhe_100-200_zoom_play_6max_v1")
        await page.locator("#populationInput").dispatch_event("change")
        assert "population liée" in (await page.locator("#populationBindingBadge").inner_text()).casefold()
        assert "stratégie calculée" in (await page.locator("#resolutionStatus").inner_text()).casefold()

        # Seed a calculated strategy and verify that the comparison layer is visible
        # before any personal override is created.
        await page.evaluate(
            f"""() => {{
              const H = window.PokerHeroRanges;
              const repo = H.emptyRepository({{populationId:'pokerstars_nlhe_100-200_zoom_play_6max_v1'}});
              const context = {{population_id:'pokerstars_nlhe_100-200_zoom_play_6max_v1',table_size:6,position:'BTN',effective_stack_bb:100,spot:'UNOPENED'}};
              H.setHandStrategy(repo, context, 'AA', {{
                actions:{{OPEN:1}},
                sizings:{{OPEN:[{{target_total_bb:2.5,probability:1}}]}},
                notes:'calculated fixture'
              }}, {{layer:'calculated'}});
              localStorage.setItem('{STORAGE_KEY}', JSON.stringify(repo));
            }}"""
        )
        await page.reload(wait_until="domcontentloaded")
        assert "calculated-only" in (await page.locator('[data-hand="AA"]').get_attribute("class") or "")

        # Multi-selection + bulk apply: Ctrl adds hands without touching non-selected rows.
        await page.locator('[data-hand="AKs"]').click(modifiers=["Control"])
        await page.locator('[data-hand="AQs"]').click(modifiers=["Control"])
        assert await page.locator("#heroGrid .hand-cell.selected").count() == 3
        assert "3 mains" in (await page.locator("#selectionSummary").inner_text())

        await page.locator("#quickAction").select_option("OPEN")
        await page.click("#quickApply")
        repo = await page.evaluate(f"JSON.parse(localStorage.getItem('{STORAGE_KEY}'))")
        node = next(iter(repo["contexts"].values()))
        for hand in ("AA", "AKs", "AQs"):
            assert node["layers"]["personal"]["hands"][hand]["actions"] == {"OPEN": 1}
        assert "KK" not in node["layers"]["personal"]["hands"]
        assert node["layers"]["calculated"]["hands"]["AA"]["sizings"]["OPEN"] == [
            {"target_total_bb": 2.5, "probability": 1}
        ], "bulk personal edit must not rewrite calculated layer"

        # Return to one hand and edit a mixed strategy with structured sizing rows.
        await page.locator('[data-hand="AA"]').click()
        await page.locator('[data-action-prob="OPEN"]').fill("75")
        await page.locator('[data-action-prob="LIMP"]').fill("25")
        await page.locator('[data-add-size="OPEN"]').click()
        first = page.locator('[data-sizes-for="OPEN"] .sizing-row').nth(0)
        await first.locator('[data-size-target="OPEN"]').fill("2.2")
        await first.locator('[data-size-prob="OPEN"]').fill("40")
        await page.locator('[data-add-size="OPEN"]').click()
        second = page.locator('[data-sizes-for="OPEN"] .sizing-row').nth(1)
        await second.locator('[data-size-target="OPEN"]').fill("2.5")
        await second.locator('[data-size-prob="OPEN"]').fill("60")
        assert "100 %" in (await page.locator("#actionTotal").inner_text())
        assert "100 %" in (await page.locator('[data-sizing-total="OPEN"]').inner_text())
        await page.click("#saveHand")

        repo = await page.evaluate(f"JSON.parse(localStorage.getItem('{STORAGE_KEY}'))")
        node = next(iter(repo["contexts"].values()))
        aa = node["layers"]["personal"]["hands"]["AA"]
        assert aa["actions"] == {"LIMP": 0.25, "OPEN": 0.75} or aa["actions"] == {"OPEN": 0.75, "LIMP": 0.25}
        assert aa["sizings"]["OPEN"] == [
            {"target_total_bb": 2.2, "probability": 0.4},
            {"target_total_bb": 2.5, "probability": 0.6},
        ]
        assert "action-mismatch" in (await page.locator('[data-hand="AA"]').get_attribute("class") or "")
        # The personal layer is explicitly marked as an override, distinct from
        # the calculated strategy, in the grid and in the editor surfaces.
        assert (await page.locator('[data-hand="AA"]').get_attribute("data-override")) == "true"
        assert (await page.locator('[data-hand="AA"]').get_attribute("data-source")) == "PERSONAL_OVERRIDE"
        assert "override personnel" in (await page.locator("#overrideBadge").inner_text()).casefold()
        assert (await page.locator("#overrideBadge").get_attribute("data-source")) == "PERSONAL_OVERRIDE"
        assert "override personnel" in (await page.locator("#handStatus").inner_text()).casefold()
        assert "override personnel" in (await page.locator(".compare-card.personal").inner_text()).casefold()
        assert "stratégie calculée" in (await page.locator("#resolutionStatus").inner_text()).casefold()

        # Category selection gives a fast bulk-selection path while keeping 169 cells.
        await page.locator('[data-select-kind="pairs"]').click()
        assert await page.locator("#heroGrid .hand-cell.selected").count() == 13
        await page.locator('[data-select-kind="single"]').click()
        assert await page.locator("#heroGrid .hand-cell.selected").count() == 1

        await page.locator("#heroRangeImport").set_input_files(
            files={"name": "custom.json", "mimeType": "application/json", "buffer": source_bytes}
        )
        await page.wait_for_function("document.querySelector('#sourceBadge')?.textContent.includes('préservée')")
        assert await page.locator("#sourceRangeSelect option").count() > 0
        assert "range source importée" in (await page.locator("#sourceStatus").inner_text()).casefold()
        imported = await page.evaluate(f"JSON.parse(localStorage.getItem('{STORAGE_KEY}'))")
        assert imported["source"]["preserved_verbatim"] is True
        assert imported["source"]["range_folder"] == source
        imported_node = next(iter(imported["contexts"].values()))
        imported_aa = imported_node["layers"]["personal"]["hands"]["AA"]
        assert imported_aa["actions"] == aa["actions"], "legacy source refresh must preserve personal customization"
        assert imported_aa["sizings"] == aa["sizings"]
        assert imported_node["layers"]["calculated"]["hands"]["AA"]["sizings"]["OPEN"] == [
            {"target_total_bb": 2.5, "probability": 1}
        ]

        await page.locator("#quickAction").select_option("OPEN")
        await page.click("#quickApply")
        edited = await page.evaluate(f"JSON.parse(localStorage.getItem('{STORAGE_KEY}'))")
        assert edited["source"]["range_folder"] == source, "editing must not rewrite imported range-folder"

        await page.click("#undefineHand")
        after_undefine = await page.evaluate(f"JSON.parse(localStorage.getItem('{STORAGE_KEY}'))")
        node = next(iter(after_undefine["contexts"].values()))
        assert "AA" not in node["layers"]["personal"]["hands"]
        assert "calculée seule" in (await page.locator("#selectedHandState").inner_text()).casefold()
        assert "calculated-only" in (await page.locator('[data-hand="AA"]').get_attribute("class") or "")

        async with page.expect_download() as download_info:
            await page.click("#heroRangeExport")
        download = await download_info.value
        assert download.suggested_filename == "hero_ranges_repository_v1.json"
        exported_path = await download.path()
        exported_repo = json.loads(Path(exported_path).read_text(encoding="utf-8"))
        assert exported_repo["schema"] == "poker-hero-range-repository/v1"
        assert exported_repo["source"]["range_folder"] == source
        assert "Stratégie Hero exportée" in (await page.locator("#sourceStatus").inner_text())

        snapshot = {
            "grid_cells": await page.locator("#heroGrid .hand-cell").count(),
            "source_ranges": await page.locator("#sourceRangeSelect option").count(),
            "source_preserved": edited["source"]["preserved_verbatim"],
            "bulk_selection": True,
            "structured_sizings": True,
            "calculated_layer_preserved": True,
            "comparison_states": True,
            "population_bound": "population liée" in (await page.locator("#populationBindingBadge").inner_text()).casefold(),
            "override_labelled": (await page.locator("#overrideBadge").get_attribute("data-source")) == "PERSONAL_OVERRIDE",
            "migration_schema": migrated["migration"]["schema"],
            "migration_source_preserved": migrated["source"] == pre["source"],
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
