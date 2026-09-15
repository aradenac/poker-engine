#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import sys
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8765/packs.html"


async def main() -> None:
    page_errors: list[str] = []
    console_errors: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context()
        page = await context.new_page()
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        await page.goto(URL, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_function("window.PokerPopulationPacks && document.querySelector('#catalog .pack-card')", timeout=45_000)
        await page.evaluate("() => navigator.serviceWorker.ready")
        if not await page.evaluate("() => Boolean(navigator.serviceWorker.controller)"):
            await page.reload(wait_until="domcontentloaded")
            await page.wait_for_function("navigator.serviceWorker.controller && document.querySelector('#catalog .pack-card')", timeout=45_000)

        result = await page.evaluate(
            """async () => {
              const P=window.PokerPopulationPacks;
              const catalog=await P.fetchCatalog();
              const entry=structuredClone(catalog.entries[0]);
              const installed=await P.install(entry);
              await P.activate(installed.id);
              const original=(await P.active());
              if(!original || original.id!==installed.id) throw new Error('initial activation failed');

              const served=[];
              for(const asset of entry.assets){
                const response=await fetch(asset.url+'?pack-smoke='+Math.random(),{cache:'no-store'});
                if(!response.ok) throw new Error(`active asset HTTP ${response.status}: ${asset.key}`);
                served.push({key:asset.key,pack:response.headers.get('X-Poker-Pack'),population:response.headers.get('X-Poker-Population')});
              }
              if(served.some(x=>x.pack!==original.id || x.population!==entry.population_id)) throw new Error('mixed or static asset after activation');

              const badHash=structuredClone(entry);
              badHash.runtime_revision='0'.repeat(64);
              badHash.assets[0].sha256='0'.repeat(64);
              let badHashRejected=false;
              try{await P.install(badHash);}catch(_){badHashRejected=true;}
              if(!badHashRejected) throw new Error('bad hash accepted');
              if((await P.active()).id!==original.id) throw new Error('bad hash changed active pack');

              const missing=structuredClone(entry);
              missing.runtime_revision='1'.repeat(64);
              missing.assets[missing.assets.length-1].url='./packs/definitely-missing.json';
              let missingRejected=false;
              try{await P.install(missing);}catch(_){missingRejected=true;}
              if(!missingRejected) throw new Error('interrupted/missing asset accepted');
              if((await P.active()).id!==original.id) throw new Error('missing asset changed active pack');

              const incompatible=structuredClone(entry);
              incompatible.compatibility.engine_version='v999';
              let incompatibleRejected=false;
              try{await P.install(incompatible);}catch(_){incompatibleRejected=true;}
              if(!incompatibleRejected) throw new Error('incompatible engine accepted');
              if((await P.active()).id!==original.id) throw new Error('incompatible pack changed active pack');

              // Build a second valid test generation from reviewed same-origin bytes.
              // Only the contract payload is substituted by another valid JSON asset;
              // the changed content hash makes the generation identity distinct.
              const next=structuredClone(entry);
              next.pack_version=entry.pack_version+'-smoke-next';
              const pop=next.assets.find(x=>x.key==='population_manifest');
              const contract=next.assets.find(x=>x.key==='model_b_contract');
              contract.url=pop.url;contract.sha256=pop.sha256;contract.size_bytes=pop.size_bytes;
              const revisionPayload=JSON.stringify(next.assets.map(x=>({key:x.key,sha256:x.sha256,size_bytes:x.size_bytes})));
              next.runtime_revision=await P.sha256(new TextEncoder().encode(revisionPayload));
              const nextRecord=await P.install(next);
              await P.activate(nextRecord.id);
              if((await P.active()).id!==nextRecord.id) throw new Error('second generation activation failed');
              if((await P.previous()).id!==original.id) throw new Error('previous generation not retained');

              const zip=await P.exportZip(nextRecord.id);
              if(!(zip instanceof Uint8Array) || zip.length<100) throw new Error('offline ZIP export empty');
              await P.rollback();
              if((await P.active()).id!==original.id) throw new Error('rollback did not restore original generation');
              const imported=await P.importZip(zip);
              if(imported.id!==nextRecord.id || imported.source!=='offline_zip') throw new Error('offline ZIP import identity mismatch');
              await P.activate(imported.id);
              if((await P.active()).id!==nextRecord.id) throw new Error('offline imported generation activation failed');

              return {
                catalog_schema:catalog.schema,
                population_id:entry.population_id,
                original_id:original.id,
                next_id:nextRecord.id,
                bad_hash_rejected:badHashRejected,
                missing_rejected:missingRejected,
                incompatible_rejected:incompatibleRejected,
                service_worker_assets:served.length,
                zip_bytes:zip.length,
                installed_count:(await P.installed()).length,
                final_active:(await P.active()).id,
                final_previous:(await P.previous()).id
              };
            }"""
        )
        assert result["bad_hash_rejected"] is True, result
        assert result["missing_rejected"] is True, result
        assert result["incompatible_rejected"] is True, result
        assert result["service_worker_assets"] == 9, result
        assert result["zip_bytes"] > 100, result
        assert result["original_id"] != result["next_id"], result
        assert result["final_active"] == result["next_id"], result
        assert result["final_previous"] == result["original_id"], result
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if page_errors:
            raise AssertionError(f"page errors: {page_errors}")
        if console_errors:
            raise AssertionError(f"console errors: {console_errors}")
        await browser.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"population pack smoke failed: {exc}", file=sys.stderr)
        raise
