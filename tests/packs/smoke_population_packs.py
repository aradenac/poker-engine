#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import base64
import json
import sys
from playwright.async_api import async_playwright

from tests.packs.synthetic_pack_fixture import runtime_entry

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
              const missingFetch=(url,opts)=>String(url).includes('definitely-missing.json')
                ? Promise.resolve(new Response('',{status:503,statusText:'simulated interrupted download'}))
                : fetch(url,opts);
              let missingRejected=false;
              try{await P.install(missing,{fetchImpl:missingFetch});}catch(_){missingRejected=true;}
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

        test_entry, test_payloads_raw = runtime_entry()
        test_payloads = {
            key: base64.b64encode(value).decode("ascii")
            for key, value in test_payloads_raw.items()
        }
        synthetic = await page.evaluate(
            """async ({entry,payloads}) => {
              const P=window.PokerPopulationPacks;
              const decode=b64=>Uint8Array.from(atob(b64),c=>c.charCodeAt(0));
              const payloadBytes=Object.fromEntries(Object.entries(payloads).map(([k,v])=>[k,decode(v)]));
              const makeFetch=overrides=>(url,opts)=>{
                const key=String(url), data=overrides[key]||payloadBytes[key];
                if(data)return Promise.resolve(new Response(data,{status:200,headers:{'Content-Type':'application/json'}}));
                return fetch(url,opts);
              };
              const testFetch=makeFetch({});
              const prodBefore=await P.active();
              if(!prodBefore)throw new Error('production pack unexpectedly inactive before TEST_ONLY smoke');
              const prodHeroBefore=prodBefore.files.hero_ranges.sha256;
              const prodCountBefore=(await P.installed()).length;

              let productionInstallRejected=false;
              try{await P.install(entry,{fetchImpl:testFetch});}catch(_){productionInstallRejected=true;}
              if(!productionInstallRejected)throw new Error('TEST_ONLY accepted by production install');

              const first=await P.installTestOnly(entry,{fetchImpl:testFetch});
              let productionActivateRejected=false;
              try{await P.activate(first.id,{fetchImpl:testFetch});}catch(_){productionActivateRejected=true;}
              if(!productionActivateRejected)throw new Error('TEST_ONLY activated through production pointer');

              await P.activateTestOnly(first.id,{fetchImpl:testFetch});
              const firstActive=await P.testActive();
              if(!firstActive||firstActive.id!==first.id)throw new Error('TEST_ONLY first activation failed');
              if(Object.keys(firstActive.files).length!==entry.assets.length)throw new Error('partial TEST_ONLY activation');
              if((await P.active()).id!==prodBefore.id)throw new Error('TEST_ONLY activation changed production pointer');

              const badHash=structuredClone(entry);
              badHash.pack_version=entry.pack_version+'-bad-hash';
              badHash.runtime_revision='a'.repeat(64);
              badHash.assets[0].sha256='0'.repeat(64);
              let badHashRejected=false;
              try{await P.installTestOnly(badHash,{fetchImpl:testFetch});}catch(_){badHashRejected=true;}
              if(!badHashRejected)throw new Error('TEST_ONLY bad hash accepted');
              if((await P.testActive()).id!==first.id)throw new Error('failed TEST_ONLY install changed test active pointer');

              const badEngine=structuredClone(entry);
              badEngine.pack_version=entry.pack_version+'-bad-engine';
              badEngine.runtime_revision='b'.repeat(64);
              badEngine.compatibility.engine_version='wrong-test-engine';
              let badEngineRejected=false;
              try{await P.installTestOnly(badEngine,{fetchImpl:testFetch});}catch(_){badEngineRejected=true;}
              if(!badEngineRejected)throw new Error('TEST_ONLY wrong engine accepted');
              if((await P.testActive()).id!==first.id)throw new Error('engine rejection changed test active pointer');

              const badPopulation=structuredClone(entry);
              badPopulation.pack_version=entry.pack_version+'-bad-population';
              badPopulation.runtime_revision='c'.repeat(64);
              badPopulation.population_id='wrong_population';
              let badPopulationRejected=false;
              try{await P.installTestOnly(badPopulation,{fetchImpl:testFetch});}catch(_){badPopulationRejected=true;}
              if(!badPopulationRejected)throw new Error('TEST_ONLY population mismatch accepted');

              const next=structuredClone(entry);
              next.pack_version=entry.pack_version+'-next';
              const nextOverrides={};
              const hero=next.assets.find(x=>x.key==='hero_strategy');
              const heroBytes=new TextEncoder().encode(JSON.stringify({
                schema:'test-only-hero-strategy/v1',
                artifact_class:'TEST_ONLY',
                non_publishable:true,
                role:'hero_strategy',
                population_id:entry.population_id,
                strategy:{AA:'raise',KK:'raise'},
                synthetic_generation:2
              })+'\n');
              hero.sha256=await P.sha256(heroBytes);
              hero.size_bytes=heroBytes.length;
              nextOverrides[hero.url]=heroBytes;
              const revPayload=JSON.stringify(next.assets.map(x=>({key:x.key,sha256:x.sha256,size_bytes:x.size_bytes})));
              next.runtime_revision=await P.sha256(new TextEncoder().encode(revPayload+next.pack_version));
              const nextFetch=makeFetch(nextOverrides);

              const second=await P.installTestOnly(next,{fetchImpl:nextFetch});
              await P.activateTestOnly(second.id,{fetchImpl:nextFetch});
              if((await P.testActive()).id!==second.id)throw new Error('TEST_ONLY atomic second activation failed');
              if((await P.testPrevious()).id!==first.id)throw new Error('TEST_ONLY previous identity lost');
              if((await P.active()).id!==prodBefore.id)throw new Error('TEST_ONLY second activation changed production pointer');

              await P.rollbackTestOnly({fetchImpl:testFetch});
              if((await P.testActive()).id!==first.id)throw new Error('TEST_ONLY rollback failed');
              if((await P.testPrevious()).id!==second.id)throw new Error('TEST_ONLY rollback did not preserve previous identity');

              const zip=await P.exportTestOnlyZip(second.id);
              const imported=await P.importTestOnlyZip(zip,{fetchImpl:nextFetch});
              if(imported.id!==second.id||imported.source!=='test_offline_zip')throw new Error('TEST_ONLY ZIP round-trip identity mismatch');
              for(const [key,file] of Object.entries(second.files)){
                if(imported.files[key].sha256!==file.sha256)throw new Error('TEST_ONLY ZIP round-trip lost component '+key);
              }

              let productionImportRejected=false;
              try{await P.importZip(zip,{fetchImpl:nextFetch});}catch(_){productionImportRejected=true;}
              if(!productionImportRejected)throw new Error('TEST_ONLY ZIP imported into production store');

              const zipFiles=await P.readZip(zip);
              const corruptFiles={...zipFiles};
              const corruptKey=Object.keys(corruptFiles).find(k=>k.startsWith('assets/hero_strategy'));
              const corrupt=corruptFiles[corruptKey].slice();
              corrupt[0]^=1;
              corruptFiles[corruptKey]=corrupt;
              let corruptRejected=false;
              try{await P.importTestOnlyZip(P.makeStoredZip(corruptFiles),{fetchImpl:nextFetch});}catch(_){corruptRejected=true;}
              if(!corruptRejected)throw new Error('corrupt TEST_ONLY ZIP accepted');

              const missingFiles={...zipFiles};
              const missingKey=Object.keys(missingFiles).find(k=>k.startsWith('assets/model_a_postflop'));
              delete missingFiles[missingKey];
              let missingRejected=false;
              try{await P.importTestOnlyZip(P.makeStoredZip(missingFiles),{fetchImpl:nextFetch});}catch(_){missingRejected=true;}
              if(!missingRejected)throw new Error('TEST_ONLY ZIP with missing component accepted');

              const prodAfter=await P.active();
              if(prodAfter.id!==prodBefore.id)throw new Error('production active identity contaminated');
              if(prodAfter.files.hero_ranges.sha256!==prodHeroBefore)throw new Error('production Hero ranges contaminated');
              if((await P.installed()).length!==prodCountBefore)throw new Error('production installed set contaminated');
              const testIds=(await P.testInstalled()).map(x=>x.id);
              if(!testIds.includes(first.id)||!testIds.includes(second.id))throw new Error('TEST_ONLY store incomplete');
              const idPrefix=entry.population_id+'::'+entry.pack_id+'::'+entry.pack_version+'::';
              if(!first.id.startsWith(idPrefix))throw new Error('cache/storage key lacks population/pack/version');
              if(first.id===prodBefore.id)throw new Error('TEST_ONLY cache/storage key collides with production');

              const probe=entry.assets[0];
              const prodProbe=await fetch((await P.fetchCatalog()).entries[0].assets[0].url+'?after-test-only='+Math.random(),{cache:'no-store'});
              if(prodProbe.headers.get('X-Poker-Pack')!==prodBefore.id)throw new Error('service worker served TEST_ONLY data as production');
              if(prodProbe.headers.get('X-Poker-Population')===entry.population_id)throw new Error('legacy cache contaminated by Zoom TEST_ONLY');

              return {
                production_install_rejected:productionInstallRejected,
                production_activate_rejected:productionActivateRejected,
                bad_hash_rejected:badHashRejected,
                bad_engine_rejected:badEngineRejected,
                bad_population_rejected:badPopulationRejected,
                production_import_rejected:productionImportRejected,
                corrupt_zip_rejected:corruptRejected,
                missing_zip_rejected:missingRejected,
                production_active_unchanged:prodAfter.id===prodBefore.id,
                hero_ranges_unchanged:prodAfter.files.hero_ranges.sha256===prodHeroBefore,
                test_first:first.id,
                test_second:second.id,
                test_active:(await P.testActive()).id,
                test_previous:(await P.testPrevious()).id,
                test_store_count:(await P.testInstalled()).length,
                production_store_count:(await P.installed()).length,
                zip_bytes:zip.length
              };
            }""",
            {"entry": test_entry, "payloads": test_payloads},
        )
        assert synthetic["production_install_rejected"] is True, synthetic
        assert synthetic["production_activate_rejected"] is True, synthetic
        assert synthetic["bad_hash_rejected"] is True, synthetic
        assert synthetic["bad_engine_rejected"] is True, synthetic
        assert synthetic["bad_population_rejected"] is True, synthetic
        assert synthetic["production_import_rejected"] is True, synthetic
        assert synthetic["corrupt_zip_rejected"] is True, synthetic
        assert synthetic["missing_zip_rejected"] is True, synthetic
        assert synthetic["production_active_unchanged"] is True, synthetic
        assert synthetic["hero_ranges_unchanged"] is True, synthetic
        assert synthetic["test_first"] != synthetic["test_second"], synthetic
        assert synthetic["test_active"] == synthetic["test_first"], synthetic
        assert synthetic["test_previous"] == synthetic["test_second"], synthetic
        assert synthetic["zip_bytes"] > 100, synthetic

        print(json.dumps({"production": result, "synthetic_test_only": synthetic}, ensure_ascii=False, indent=2))
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