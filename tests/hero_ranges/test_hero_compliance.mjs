#!/usr/bin/env node
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const H=require('../../site/hero-ranges.js');
globalThis.PokerHeroRanges=H;
const C=require('../../site/hero-compliance.js');
require('../../site/hero-compliance-replayer.js');
const R=globalThis.PokerHeroComplianceReplayer;

assert.equal(R.handClass([11,21]),'KTo','numeric replayer card IDs must map to canonical 169 notation');
assert.equal(R.handClass(['Ks','Th']),'KTo','text card compatibility must be preserved');

const POP='pokerstars_nlhe_100-200_zoom_play_6max_v1';
const context={population_id:POP,table_size:6,position:'BTN',effective_stack_bb:100,spot:'UNOPENED'};
const repo=H.emptyRepository({populationId:POP});
H.setLayerMetadata(repo,context,'calculated',{version:'calc-7',provenance:{source:'fixture'}});
H.setHandStrategy(repo,context,'AKs',{actions:{FOLD:.8,OPEN:.2},sizings:{OPEN:[{target_total_bb:2.5,probability:1}]},notes:'20% open fixture'},{layer:'calculated'});

function decision(action='RAISE',extra={}){
  return {
    player:'Hero',action,
    actor_position:'BTN',table_size:6,raise_level:0,family:'UNOPENED',history:[],
    actor_start_stack_bb:100,
    preflop_context_v1:{
      table_size:6,actor_position:'BTN',raise_level:0,family:'UNOPENED',history:[],
      live_positions:['BTN','SB','BB'],all_in_positions:[],to_call_bb:1,
      effective_stack_bb:100,actor_remaining_bb:100
    },
    action_sizing_v1:{incremental_cost_bb:2.5,target_total_bb:2.5},
    ...extra
  };
}

// A 20% action is allowed on an isolated occurrence; this is not a frequency-calibration failure.
const mixed=C.evaluateDecision({repo,decision:decision('RAISE'),handClass:'AKs'});
assert.equal(mixed.context_status,'RESOLVED');
assert.equal(mixed.depth_match,'exact');
assert.equal(mixed.planned_action,'OPEN');
assert.equal(mixed.action_probability,.2);
assert.equal(mixed.action_status,'MIXED_ALLOWED');
assert.equal(mixed.frequency_calibration_status,'NOT_EVALUATED_PER_SINGLE_DECISION');
assert.equal(mixed.sizing.status,'MATCHED');
assert.equal(mixed.ev_deviation_bb,null);
assert.equal(mixed.ev_status,'NOT_EVALUATED');
assert.equal(mixed.layer,'calculated');
assert.equal(mixed.layer_version,'calc-7');

const out=C.evaluateDecision({repo,decision:decision('LIMP'),handClass:'AKs'});
assert.equal(out.planned_action,'LIMP');
assert.equal(out.action_status,'OUT_OF_RANGE');
assert.equal(out.sizing.status,'NOT_APPLICABLE');

const badSize=C.evaluateDecision({repo,decision:decision('RAISE',{action_sizing_v1:{target_total_bb:4}}),handClass:'AKs'});
assert.equal(badSize.action_status,'MIXED_ALLOWED');
assert.equal(badSize.sizing.status,'OUT_OF_RANGE','sizing is audited independently from action compliance');

const unknownSize=C.evaluateDecision({repo,decision:decision('RAISE',{action_sizing_v1:null}),handClass:'AKs'});
assert.equal(unknownSize.action_status,'MIXED_ALLOWED');
assert.equal(unknownSize.sizing.status,'UNKNOWN_OBSERVED_SIZE','missing sizing must not fabricate a verdict');

const missingHand=C.evaluateDecision({repo,decision:decision('RAISE'),handClass:'AQs'});
assert.equal(missingHand.action_status,'UNCOVERED_HAND');
assert.equal(missingHand.action_probability,null);

const unsupportedAction=C.evaluateDecision({repo,decision:decision('BET'),handClass:'AKs'});
assert.equal(unsupportedAction.action_status,'UNKNOWN_ACTION');
assert.equal(unsupportedAction.action_probability,null);

const missingContext=C.evaluateDecision({repo,decision:{action:'RAISE',actor_position:'BTN',family:'VS_5BET',raise_level:4,actor_start_stack_bb:100},handClass:'AKs'});
assert.equal(missingContext.action_status,'NO_VERDICT');
assert.equal(missingContext.context_status,'UNSUPPORTED_CONTEXT');

// #97 owns exact stack contexts. A nearby context may be shown diagnostically but
// must never authorize a compliance verdict without an explicit repository bucket policy.
const depth99=decision('RAISE');
depth99.preflop_context_v1.effective_stack_bb=99;
depth99.preflop_context_v1.actor_remaining_bb=99;
const uncoveredDepth=C.evaluateDecision({repo,decision:depth99,handClass:'AKs'});
assert.equal(uncoveredDepth.context_status,'UNCOVERED_DEPTH');
assert.equal(uncoveredDepth.action_status,'NO_VERDICT');
assert.equal(uncoveredDepth.action_probability,null);
assert.equal(uncoveredDepth.resolved_context.effective_stack_bb,99);
assert.equal(uncoveredDepth.nearest_context.effective_stack_bb,100);
assert.equal(uncoveredDepth.depth_delta_bb,1);

// Missing canonical effective_stack_bb is not repaired from actor remaining/start stack.
const noCanonicalDepth=decision('RAISE');
delete noCanonicalDepth.preflop_context_v1.effective_stack_bb;
noCanonicalDepth.preflop_context_v1.actor_remaining_bb=99;
noCanonicalDepth.actor_start_stack_bb=100;
const missingDepth=C.evaluateDecision({repo,decision:noCanonicalDepth,handClass:'AKs'});
assert.equal(missingDepth.context_status,'UNSUPPORTED_CONTEXT');
assert.equal(missingDepth.action_status,'NO_VERDICT');
assert.equal(missingDepth.resolved_context,null);

// ISO-facing families are projected only onto spots that the #97 repository can actually represent.
const isoFacing=decision('CALL',{family:'VS_ISO',preflop_context_v1:{...decision().preflop_context_v1,family:'VS_ISO',history:[{position:'HJ',action:'LIMP'},{position:'CO',action:'RAISE'}],raise_level:1,to_call_bb:2}});
assert.equal(C.spotForDecision(isoFacing),'VS_RFI');

// Personal overlays remain authoritative and carry their own version/provenance.
H.setLayerMetadata(repo,context,'personal',{version:'personal-3',provenance:{author:'user'}});
H.setHandStrategy(repo,context,'AKs',{actions:{OPEN:1},sizings:{OPEN:[{target_total_bb:2.5,probability:1}]},notes:'personal override'},{layer:'personal'});
const personal=C.evaluateDecision({repo,decision:decision('RAISE'),handClass:'AKs'});
assert.equal(personal.action_status,'COMPLIANT');
assert.equal(personal.layer,'personal');
assert.equal(personal.layer_version,'personal-3');
assert.deepEqual(personal.provenance,{author:'user'});

const token1=C.repositoryVersionToken(repo);
const token2=C.repositoryVersionToken(H.importDocument(JSON.parse(JSON.stringify(repo))));
assert.equal(token1,token2,'the selected repository version must remain reproducible after reload');

const summary=C.summarize([mixed,out,badSize,unknownSize,missingHand,unsupportedAction,missingContext,personal]);
assert.equal(summary.judged,5);
assert.equal(summary.allowed,4);
assert.equal(summary.out_of_range,1);
assert.equal(summary.uncovered,3);
assert.equal(summary.sizing_out_of_range,1);
assert.equal(summary.frequency_calibration_status,'NOT_EVALUATED_PER_SINGLE_HAND');

console.log('Hero range compliance contract: PASS');
