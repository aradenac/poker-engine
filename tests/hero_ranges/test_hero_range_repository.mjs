#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs';
import zlib from 'node:zlib';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const H=require('../../site/hero-ranges.js');

function loadArchivedCustom(){
  const encoded=fs.readFileSync('user/artifacts/NLHE_100-200/custom.json.gz.b64','utf8').trim();
  return JSON.parse(zlib.gunzipSync(Buffer.from(encoded,'base64')).toString('utf8'));
}

function canonical(v){return JSON.stringify(v);}

const source=loadArchivedCustom();
const repo=H.importDocument(source,{populationId:'pokerstars_nlhe_100-200_zoom_play_6max_v1'});
assert.equal(repo.schema,H.SCHEMA);
assert.equal(repo.source.preserved_verbatim,true);
assert.equal(canonical(repo.source.range_folder),canonical(source),'range-folder source must remain structurally identical after import');

const context={population_id:'pokerstars_nlhe_100-200_zoom_play_6max_v1',table_size:6,position:'BTN',effective_stack_bb:100,spot:'UNOPENED'};
H.setHandStrategy(repo,context,'AKs',{
  actions:{OPEN:.75,LIMP:.25},
  sizings:{OPEN:[{target_total_bb:2.2,probability:.4},{target_total_bb:2.5,probability:.6}]},
  notes:'personal fixture'
},{layer:'personal'});
H.setHandStrategy(repo,context,'AKs',{
  actions:{OPEN:1},
  sizings:{OPEN:[{target_total_bb:2.5,probability:1}]},
  notes:'calculated fixture'
},{layer:'calculated'});
assert.equal(H.resolvedLayer(repo,context,'AKs'),'personal');
assert.deepEqual(H.getHandStrategy(repo,context,'AKs',{layer:'resolved'}).actions,{OPEN:.75,LIMP:.25});
assert.deepEqual(H.getHandStrategy(repo,context,'AKs',{layer:'calculated'}).actions,{OPEN:1});

const refreshedSource=JSON.parse(JSON.stringify(source));
refreshedSource.__test_refresh_marker='source-v2';
const refreshed=H.importDocument(refreshedSource,{populationId:context.population_id,baseRepository:repo});
assert.equal(refreshed.source.range_folder.__test_refresh_marker,'source-v2');
assert.deepEqual(H.getHandStrategy(refreshed,context,'AKs',{layer:'personal'}).actions,{OPEN:.75,LIMP:.25},'source refresh must preserve personal customization');
assert.deepEqual(H.getHandStrategy(refreshed,context,'AKs',{layer:'calculated'}).actions,{OPEN:1},'source refresh must preserve calculated layer');
assert.equal(canonical(repo.source.range_folder),canonical(source),'base repository source must not be mutated in place');

const exported=H.exportDocument(repo);
assert.equal(canonical(exported.source.range_folder),canonical(source),'editing overlays must not rewrite source range-folder');
const roundtrip=H.importDocument(JSON.parse(JSON.stringify(exported)));
assert.deepEqual(H.getHandStrategy(roundtrip,context,'AKs',{layer:'personal'}).actions,{OPEN:.75,LIMP:.25});
assert.deepEqual(H.getHandStrategy(roundtrip,context,'AKs',{layer:'calculated'}).actions,{OPEN:1});

H.setHandStrategy(roundtrip,context,'AKs',null,{layer:'personal'});
assert.equal(H.resolvedLayer(roundtrip,context,'AKs'),'calculated','removing customization must reveal calculated layer');
assert.deepEqual(H.getHandStrategy(roundtrip,context,'AKs',{layer:'resolved'}).actions,{OPEN:1});

assert.throws(()=>H.setHandStrategy(roundtrip,context,'AQs',{actions:{OPEN:.6,CALL:.3}},{layer:'personal'}),/sum to 1/);
assert.equal(H.getHandStrategy(roundtrip,context,'AQs',{layer:'personal'}),null,'invalid strategy must not become implicit fold');

assert.deepEqual(H.ACTIONS,['FOLD','CHECK','LIMP','OVERLIMP','CALL','OPEN','ISO','3BET','4BET','SHOVE','CALL_SHOVE']);
assert.equal(H.HAND_CLASSES.length,169);
const comboTotal=H.HAND_CLASSES.reduce((s,h)=>s+H.comboMultiplicity(h),0);
assert.equal(comboTotal,1326,'169 grid must retain 6/4/12 combo multiplicity');
assert.equal(H.comboMultiplicity('AA'),6);
assert.equal(H.comboMultiplicity('AKs'),4);
assert.equal(H.comboMultiplicity('AKo'),12);

const legacy=H.legacyRanges(source);
assert.ok(legacy.length>0,'archived custom range-folder must expose browseable ranges');
const stats=H.repositoryStats(exported);
assert.equal(stats.personal_defined_hands,1);
assert.equal(stats.calculated_defined_hands,1);
assert.equal(stats.personal_combo_slots,4);
assert.ok(stats.legacy_ranges>0);

console.log(`Hero range repository contract: PASS (${legacy.length} legacy ranges, ${stats.contexts} context)`);
