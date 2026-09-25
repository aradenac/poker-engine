#!/usr/bin/env node
import assert from 'node:assert/strict';
import childProcess from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
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

// --- Frozen `hero-range-editor` job: patch idempotence ---------------------
// `.github/workflows/hero-range-editor.yml` (frozen, sha256-pinned by
// tests/ci/test_repro_workflow_batch2.py) runs
// `python3 tools/patches/apply_hero_range_editor.py` in place on site/index.html
// and then requires the sha256 to be unchanged: the committed index is already
// patched and a second run is a strict no-op. This is the only test Python step
// of that job whose file may be edited, so it reproduces the contract here — on
// throwaway copies, never in the checkout — and adds the positive control the
// workflow cannot express: remove `#heroRangesOpenBtn`, insert it exactly once,
// then prove the next run touches no byte.
const REPO_ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..','..');
const PATCH_SCRIPT=path.join(REPO_ROOT,'tools/patches/apply_hero_range_editor.py');
const INDEX=path.join(REPO_ROOT,'site/index.html');
const HERO_RANGES_OPEN_BTN=/^[ \t]*<a id="heroRangesOpenBtn"[^\n]*\n/m;
const HERO_RANGES_OPEN_BTN_MARKER='id="heroRangesOpenBtn"';

function sha256(file){return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');}
function occurrences(text,needle){return text.split(needle).length-1;}
function runPatch(indexPath,...args){
  const result=childProcess.spawnSync('python3',[PATCH_SCRIPT,'--index',indexPath,...args],{cwd:REPO_ROOT,encoding:'utf8'});
  const label=`apply_hero_range_editor.py --index ${indexPath} ${args.join(' ')}`.trim();
  const detail=result.error?result.error.message:(result.stderr||result.stdout);
  assert.equal(result.status,0,`${label} must succeed: ${detail}`);
  return result;
}

// Navigation invariants: the Strategy view is an in-app surface and the frozen
// patch must never re-expose the standalone `hero-ranges.html` page as a
// `#quickNav` entry — the nav entry carries `#strategyPage`, and the real
// editor links stay outside the navigation.
const indexText=fs.readFileSync(INDEX,'utf8');
const committedSha=sha256(INDEX);
const quickNav=/<nav id="quickNav"[\s\S]*?<\/nav>/.exec(indexText);
assert.ok(quickNav,'site/index.html must keep the #quickNav block');
assert.equal(quickNav[0].includes('hero-ranges.html'),false,'#quickNav must not re-expose the standalone hero-ranges.html page');
assert.equal(occurrences(quickNav[0],'<a '),5,'#quickNav must keep exactly 5 entries');
assert.equal(occurrences(indexText,HERO_RANGES_OPEN_BTN_MARKER),1,'the index must declare #heroRangesOpenBtn exactly once');

const temp=fs.mkdtempSync(path.join(os.tmpdir(),'hero-range-editor-'));
try{
  // Idempotence: patching an already patched copy changes no byte, and `--check`
  // agrees without writing. Both properties are asserted on the bytes.
  const appliedCopy=path.join(temp,'applied.html');
  fs.copyFileSync(INDEX,appliedCopy);
  const copyBefore=sha256(appliedCopy);
  runPatch(appliedCopy);
  assert.equal(sha256(appliedCopy),copyBefore,'patching an applied index must not change a single byte');
  runPatch(appliedCopy,'--check');
  assert.equal(sha256(appliedCopy),copyBefore,'--check must report the applied index without writing it');

  // Positive control (non-vacuous): with the link stripped the first run inserts
  // it exactly once — rebuilding the committed bytes — and the second run is a
  // strict no-op, so the guard cannot pass by simply doing nothing.
  const linkLine=HERO_RANGES_OPEN_BTN.exec(indexText)[0];
  const strippedText=indexText.replace(HERO_RANGES_OPEN_BTN,'');
  assert.equal(occurrences(strippedText,HERO_RANGES_OPEN_BTN_MARKER),0,'the positive control needs the link actually removed');
  assert.equal(indexText.length-strippedText.length,linkLine.length,'the positive control must strip exactly the link line');
  const controlCopy=path.join(temp,'control.html');
  fs.writeFileSync(controlCopy,strippedText);
  runPatch(controlCopy);
  const insertedText=fs.readFileSync(controlCopy,'utf8');
  assert.equal(occurrences(insertedText,HERO_RANGES_OPEN_BTN_MARKER),1,'the patch must insert #heroRangesOpenBtn exactly once');
  assert.equal(occurrences(insertedText,linkLine),1,'the inserted entry must be the exact committed link line');
  assert.equal(insertedText,indexText,'the patch must rebuild the committed index byte-for-byte');
  const insertedSha=sha256(controlCopy);
  runPatch(controlCopy);
  assert.equal(sha256(controlCopy),insertedSha,'a second run over a freshly patched index must not change bytes');
  runPatch(controlCopy,'--check');
}finally{
  fs.rmSync(temp,{recursive:true,force:true});
}
assert.equal(sha256(INDEX),committedSha,'the patch contract must never write into the checkout');

console.log(`Hero range repository contract: PASS (${legacy.length} legacy ranges, ${stats.contexts} contexts, hero range editor patch idempotent)`);
