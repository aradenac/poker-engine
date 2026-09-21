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
const legacyKey='pokerstars_nlhe_100-200_zoom_play_6max_v1|6|BTN|100|UNOPENED';
assert.equal(H.contextKey(context),legacyKey,'legacy context keys must remain byte-for-byte stable');

// The repository is population-bound: the editor may only present or edit the
// population strategy and its personal override for a context whose
// population_id matches the declared binding. A foreign context is never
// silently relabelled.
const FOREIGN='legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1';
assert.equal(H.repositoryPopulationId(repo),context.population_id);
assert.equal(H.repositoryPopulationId(H.emptyRepository({populationId:''})),null);
assert.deepEqual(H.populationBound(repo,context),{
  population_id:context.population_id,
  repository_population_id:context.population_id,
  compatible:true
});
assert.equal(H.populationBound(repo,{...context,population_id:FOREIGN}).compatible,false,'a foreign context must never inherit the repository population binding');
assert.throws(()=>H.populationBound(repo,{...context,population_id:''}),/population_id is required/,'the context population_id stays mandatory');
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

// #107 calculated ranges may share the same human-readable spot while referring
// to different exact public preflop states.  The canonical PFC identity must
// prevent one calculated chart from overwriting another.
const rfiA={...context,spot:'VS_RFI',preflop_context_id:'PFC_0000000000000001'};
const rfiB={...context,spot:'VS_RFI',preflop_context_id:'PFC_0000000000000002'};
assert.notEqual(H.contextKey(rfiA),H.contextKey(rfiB));
assert.equal(H.contextKey(rfiA),`${context.population_id}|6|BTN|100|VS_RFI|PFC_0000000000000001`);
H.setHandStrategy(repo,rfiA,'AQo',{actions:{CALL:1},notes:'LJ-open exact fixture'},{layer:'calculated'});
H.setHandStrategy(repo,rfiB,'AQo',{actions:{'3BET':1},sizings:{'3BET':[{target_total_bb:9,probability:1}]},notes:'CO-open exact fixture'},{layer:'calculated'});
assert.deepEqual(H.getHandStrategy(repo,rfiA,'AQo',{layer:'calculated'}).actions,{CALL:1});
assert.deepEqual(H.getHandStrategy(repo,rfiB,'AQo',{layer:'calculated'}).actions,{'3BET':1});
assert.equal(H.getHandStrategy(repo,{...context,spot:'VS_RFI'},'AQo',{layer:'calculated'}),null,'generic context must not silently resolve an exact-context range');
assert.throws(()=>H.normalizeContext({...rfiA,preflop_context_id:'not-canonical'}),/invalid preflop_context_id/);

const refreshedSource=JSON.parse(JSON.stringify(source));
refreshedSource.__test_refresh_marker='source-v2';
const refreshed=H.importDocument(refreshedSource,{populationId:context.population_id,baseRepository:repo});
assert.equal(refreshed.source.range_folder.__test_refresh_marker,'source-v2');
assert.deepEqual(H.getHandStrategy(refreshed,context,'AKs',{layer:'personal'}).actions,{OPEN:.75,LIMP:.25},'source refresh must preserve personal customization');
assert.deepEqual(H.getHandStrategy(refreshed,context,'AKs',{layer:'calculated'}).actions,{OPEN:1},'source refresh must preserve calculated layer');
assert.deepEqual(H.getHandStrategy(refreshed,rfiA,'AQo',{layer:'calculated'}).actions,{CALL:1},'source refresh must preserve canonical-context calculated range');
assert.equal(canonical(repo.source.range_folder),canonical(source),'base repository source must not be mutated in place');

const exported=H.exportDocument(repo);
assert.equal(canonical(exported.source.range_folder),canonical(source),'editing overlays must not rewrite source range-folder');
const roundtrip=H.importDocument(JSON.parse(JSON.stringify(exported)));
assert.deepEqual(H.getHandStrategy(roundtrip,context,'AKs',{layer:'personal'}).actions,{OPEN:.75,LIMP:.25});
assert.deepEqual(H.getHandStrategy(roundtrip,context,'AKs',{layer:'calculated'}).actions,{OPEN:1});
assert.deepEqual(H.getHandStrategy(roundtrip,rfiA,'AQo',{layer:'calculated'}).actions,{CALL:1});
assert.deepEqual(H.getHandStrategy(roundtrip,rfiB,'AQo',{layer:'calculated'}).actions,{'3BET':1});

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
assert.equal(stats.calculated_defined_hands,3);
assert.equal(stats.personal_combo_slots,4);
assert.equal(stats.contexts,3);
assert.ok(stats.legacy_ranges>0);

console.log(`Hero range repository contract: PASS (${legacy.length} legacy ranges, ${stats.contexts} contexts)`);