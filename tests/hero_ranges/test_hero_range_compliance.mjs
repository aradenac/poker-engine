#!/usr/bin/env node
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const H=require('../../site/hero-ranges.js');
globalThis.PokerHeroRanges=H;
const C=require('../../site/hero-compliance.js');

const POP='pokerstars_nlhe_100-200_zoom_play_6max_v1';
const repo=H.emptyRepository({populationId:POP});
const openCtx={population_id:POP,table_size:6,position:'BTN',effective_stack_bb:100,spot:'UNOPENED'};
H.setLayerMetadata(repo,openCtx,'calculated',{version:'calc-v1',provenance:{kind:'candidate'}});
H.setHandStrategy(repo,openCtx,'AKs',{actions:{OPEN:1},sizings:{OPEN:[{target_total_bb:2.5,probability:1}]},notes:'calculated fallback'},{layer:'calculated'});
H.setLayerMetadata(repo,openCtx,'personal',{version:'personal-v7',provenance:{kind:'user'}});
H.setHandStrategy(repo,openCtx,'AKs',{actions:{OPEN:.2,FOLD:.8},sizings:{OPEN:[{target_total_bb:2.5,probability:1}]},notes:'20% open mix'},{layer:'personal'});
H.setHandStrategy(repo,openCtx,'AKo',{actions:{FOLD:1},notes:'fold only'},{layer:'personal'});

function decision({action='RAISE',family='UNOPENED',history=[],position='BTN',stack=100,raiseLevel=0,target=2.5,toCall=0}={}){
  const context={schema:'poker-preflop-context/v1',state_timing:'BEFORE_ACTION',table_size:6,actor_position:position,family,raise_level:raiseLevel,history,live_positions:['LJ','HJ','CO','BTN','SB','BB'],all_in_positions:[],remaining_to_act_positions:[],effective_stack_bb:stack,to_call_bb:toCall};
  return {actor_position:position,table_size:6,family,raise_level:raiseLevel,history,action,to_call_bb:toCall,preflop_context_v1:context,action_sizing_v1:{incremental_cost_bb:target,target_total_bb:target}};
}

const mixed=C.evaluateDecision({repo,decision:decision(),handClass:'AKs'});
assert.equal(mixed.action_status,'MIXED_ALLOWED','a positive 20% action is allowed on a single occurrence');
assert.equal(mixed.action_probability,.2);
assert.equal(mixed.sizing.status,'MATCHED');
assert.equal(mixed.layer,'personal');
assert.equal(mixed.layer_version,'personal-v7');
assert.equal(mixed.ev_deviation_bb,null);
assert.equal(mixed.ev_status,'NOT_EVALUATED');
assert.equal(mixed.frequency_calibration_status,'SAMPLE_REQUIRED');
assert.match(mixed.editor_href,/population=/);
assert.match(mixed.editor_href,/hand=AKs/);

const sizingMiss=C.evaluateDecision({repo,decision:decision({target:3.2}),handClass:'AKs'});
assert.equal(sizingMiss.action_status,'MIXED_ALLOWED','sizing mismatch must not rewrite the action verdict');
assert.equal(sizingMiss.sizing.status,'OUT_OF_RANGE');

const out=C.evaluateDecision({repo,decision:decision(),handClass:'AKo'});
assert.equal(out.action_status,'OUT_OF_RANGE');
assert.equal(out.action_probability,0);
assert.equal(out.sizing.status,'NOT_APPLICABLE');

const missingHand=C.evaluateDecision({repo,decision:decision(),handClass:'AQs'});
assert.equal(missingHand.action_status,'UNCOVERED_HAND');

const uncoveredDepth=C.evaluateDecision({repo,decision:decision({stack:80}),handClass:'AKs'});
assert.equal(uncoveredDepth.action_status,'NO_VERDICT');
assert.equal(uncoveredDepth.context_status,'UNCOVERED_DEPTH','80 BB must not silently reuse the 100 BB plan');
assert.equal(uncoveredDepth.nearest_context.effective_stack_bb,100);

const nearDepth=C.evaluateDecision({repo,decision:decision({stack:98.5}),handClass:'AKs'});
assert.equal(nearDepth.context_status,'RESOLVED');
assert.equal(nearDepth.depth_match,'nearest');
assert.equal(nearDepth.action_status,'MIXED_ALLOWED');

const missingContext=C.evaluateDecision({repo,decision:decision({family:'VS_RFI',history:[{position:'CO',action:'RAISE'}],raiseLevel:1,toCall:2.5}),handClass:'AKs'});
assert.equal(missingContext.action_status,'NO_VERDICT');
assert.equal(missingContext.context_status,'UNCOVERED_CONTEXT');

const jamCtx={population_id:POP,table_size:6,position:'SB',effective_stack_bb:100,spot:'VS_JAM'};
H.setHandStrategy(repo,jamCtx,'QQ',{actions:{CALL_SHOVE:1},notes:'call jam'},{layer:'personal'});
const jamHistory=[{position:'CO',action:'JAM'},{position:'BTN',action:'CALL'}];
const jamDecision=decision({action:'CALL',family:'VS_RFI_CALLERS',history:jamHistory,position:'SB',raiseLevel:1,toCall:99,target:null});
jamDecision.action_sizing_v1={incremental_cost_bb:99,target_total_bb:null};
assert.equal(C.spotForDecision(jamDecision),'VS_JAM','an intervening caller must not hide the prior jam');
assert.equal(C.plannedActionForDecision(jamDecision),'CALL_SHOVE');
const callJam=C.evaluateDecision({repo,decision:jamDecision,handClass:'QQ'});
assert.equal(callJam.action_status,'COMPLIANT');
assert.equal(callJam.planned_action,'CALL_SHOVE');

const token1=C.repositoryVersionToken(repo);
const copy=JSON.parse(JSON.stringify(repo));
copy.source={format:'range-folder',preserved_verbatim:true,meta:null,range_folder:{folder:{name:'different raw source'}}};
const token2=C.repositoryVersionToken(copy);
assert.equal(token1,token2,'raw range-folder provenance must not change the decision-bearing strategy token');
H.setHandStrategy(copy,openCtx,'AKo',{actions:{OPEN:1}},{layer:'personal'});
assert.notEqual(token1,C.repositoryVersionToken(copy),'strategy edits must change the reproducibility token');

const summary=C.summarize([mixed,sizingMiss,out,missingHand,uncoveredDepth,callJam]);
assert.equal(summary.decisions,6);
assert.equal(summary.judged,4);
assert.equal(summary.allowed,3);
assert.equal(summary.out_of_range,1);
assert.equal(summary.uncovered,2);
assert.equal(summary.sizing_out_of_range,1);
assert.equal(summary.frequency_calibration_status,'SAMPLE_REQUIRED');
assert.ok(summary.groups.some(g=>g.position==='BTN'&&g.spot==='UNOPENED'));
assert.ok(summary.groups.some(g=>g.position==='SB'&&g.spot==='VS_JAM'));

console.log(JSON.stringify({schema:C.SCHEMA,token:token1,mixed_status:mixed.action_status,mixed_probability:mixed.action_probability,sizing_miss:sizingMiss.sizing.status,depth_80:uncoveredDepth.context_status,summary},null,2));
