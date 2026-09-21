#!/usr/bin/env node
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const H=require('../../site/hero-ranges.js');
globalThis.PokerHeroRanges=H;
const C=require('../../site/hero-compliance.js');
const S=require('../../site/hero-strategy-resolver.js');
require('../../site/hero-compliance-replayer.js');
const R=globalThis.PokerHeroComplianceReplayer;

assert.equal(C.STRATEGY_SOURCE.POPULATION,'POPULATION');
assert.equal(C.STRATEGY_SOURCE.PERSONAL_OVERRIDE,'PERSONAL_OVERRIDE');
assert.equal(R.handClass([11,21]),'KTo','numeric replayer card IDs must map to canonical 169 notation');
assert.equal(R.handClass(['Ks','Th']),'KTo','text card compatibility must be preserved');

const POP='pokerstars_nlhe_100-200_zoom_play_6max_v1';
const OTHER='legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1';
const SHA_MANIFEST='a'.repeat(64);
const SHA_BINDING='b'.repeat(64);
const context={population_id:POP,table_size:6,position:'BTN',effective_stack_bb:100,spot:'UNOPENED'};
function contextFor(populationId){return {...context,population_id:populationId};}
// A fully bound admission: the content hash, candidate/generation identity and
// binding hash all describe the calculated artifact used at runtime (#task-fnc).
function boundAdmission(){
  return {hero_strategy:{
    status:'ADMISSIBLE',role:'hero_strategy',population_id:POP,
    candidate_id:'hero-candidate-196',generation_id:'gen-196',binding_sha256:SHA_BINDING,
    artifact:{declared_sha256:SHA_MANIFEST,actual_sha256:SHA_MANIFEST,hash_kind:'file_sha256',verified:true},
    provenance:{
      source_population_id:POP,
      manifest_sha256:SHA_MANIFEST,
      binding_sha256:SHA_BINDING,
      candidate_id:'hero-candidate-196',
      generation_id:'gen-196'
    }
  }};
}
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
assert.equal(mixed.strategy_source,'POPULATION');
assert.equal(mixed.personal_override,false);
assert.equal(mixed.population_id,POP);

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
assert.equal(missingHand.strategy_source,'NONE');

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

// --- acceptance #1: never evaluate a strategy bound to another population ----
const crossPopulation=C.evaluateDecision({repo,decision:decision('RAISE'),handClass:'AKs',populationId:OTHER});
assert.equal(crossPopulation.action_status,'NO_VERDICT','a requested population that differs from the repository defaults must fail closed');
assert.equal(crossPopulation.context_status,'POPULATION_INCOMPATIBLE');
assert.equal(crossPopulation.strategy_source,'NONE');
assert.equal(crossPopulation.layer,null);
assert.equal(C.populationCompatibility(repo,OTHER).compatible,false);

// The repository itself binds a materialized calculated strategy of another population.
const foreignRepo=H.emptyRepository({populationId:OTHER});
H.setLayerMetadata(foreignRepo,contextFor(OTHER),'calculated',{version:'foreign',provenance:{source:'fixture'}});
H.setHandStrategy(foreignRepo,contextFor(OTHER),'AKs',{actions:{OPEN:1}},{layer:'calculated'});
const foreignContext=C.evaluateDecision({repo:foreignRepo,decision:decision('RAISE'),handClass:'AKs',populationId:POP});
assert.equal(foreignContext.action_status,'NO_VERDICT');
assert.equal(foreignContext.context_status,'POPULATION_INCOMPATIBLE');
assert.equal(foreignContext.strategy_source,'NONE');

// A resolver answer of POPULATION_INCOMPATIBLE is authoritative and fails closed.
const incompatibleResolution=S.resolveHeroStrategy({population_id:POP,repository:foreignRepo,admissions:'ADMISSIBLE'});
assert.equal(incompatibleResolution.status,'POPULATION_INCOMPATIBLE');
const incompatibleVerdict=C.evaluateDecision({repo:foreignRepo,decision:decision('RAISE'),handClass:'AKs',strategyResolution:incompatibleResolution});
assert.equal(incompatibleVerdict.action_status,'NO_VERDICT');
assert.equal(incompatibleVerdict.context_status,'POPULATION_INCOMPATIBLE');
assert.equal(incompatibleVerdict.strategy_source,'NONE');
assert.equal(incompatibleVerdict.strategy_status,'POPULATION_INCOMPATIBLE');

// --- authorized population resolution ---------------------------------------
const admittedRepo=H.emptyRepository({populationId:POP});
H.setLayerMetadata(admittedRepo,context,'calculated',{version:'gen-196',provenance:{source:'fixture',candidate_id:'hero-candidate-196',generation_id:'gen-196',manifest_sha256:SHA_MANIFEST,binding_sha256:SHA_BINDING}});
for(const hand of H.HAND_CLASSES)H.setHandStrategy(admittedRepo,context,hand,{actions:{FOLD:1}},{layer:'calculated'});
H.setHandStrategy(admittedRepo,context,'AKs',{actions:{FOLD:.8,OPEN:.2},sizings:{OPEN:[{target_total_bb:2.5,probability:1}]},notes:'20% open fixture'},{layer:'calculated'});
const admittedResolution=S.resolveHeroStrategy({population_id:POP,repository:admittedRepo,admissions:boundAdmission(),required_context_keys:[H.contextKey(context)]});
assert.equal(admittedResolution.status,'ADMISSIBLE_CALCULATED');

const authorized=C.evaluateDecision({repo:admittedRepo,decision:decision('RAISE'),handClass:'AKs',strategyResolution:admittedResolution});
assert.equal(authorized.action_status,'MIXED_ALLOWED');
assert.equal(authorized.strategy_source,'POPULATION');
assert.equal(authorized.strategy_status,'ADMISSIBLE_CALCULATED');
assert.equal(authorized.layer,'calculated');
assert.equal(authorized.personal_override,false);
assert.equal(authorized.sizing.status,'MATCHED');

// A partial population strategy is not a resolved strategy: explicit NO_VERDICT.
const partialRepo=H.emptyRepository({populationId:POP});
H.setLayerMetadata(partialRepo,context,'calculated',{version:'gen-196-partial',provenance:{source:'fixture',candidate_id:'hero-candidate-196',generation_id:'gen-196',manifest_sha256:SHA_MANIFEST,binding_sha256:SHA_BINDING}});
H.setHandStrategy(partialRepo,context,'AKs',{actions:{OPEN:1}},{layer:'calculated'});
const partialResolution=S.resolveHeroStrategy({population_id:POP,repository:partialRepo,admissions:boundAdmission()});
assert.equal(partialResolution.status,'PARTIAL');
const partialVerdict=C.evaluateDecision({repo:partialRepo,decision:decision('RAISE'),handClass:'AKs',strategyResolution:partialResolution});
assert.equal(partialVerdict.action_status,'NO_VERDICT');
assert.equal(partialVerdict.context_status,'STRATEGY_UNAVAILABLE');
assert.equal(partialVerdict.strategy_source,'POPULATION');

// A retained reference is population-compatible but is not the admitted active
// strategy: it must never authorize a compliance verdict.
const retainedRepo=H.emptyRepository({populationId:POP});
H.setLayerMetadata(retainedRepo,context,'calculated',{version:'retained-v1',provenance:{source:'fixture'}});
H.setHandStrategy(retainedRepo,context,'AKs',{actions:{OPEN:1}},{layer:'calculated'});
const retainedResolution=S.resolveHeroStrategy({population_id:POP,repository:retainedRepo,admissions:{hero_strategy:{status:'RETAIN_REFERENCE',population_id:POP}}});
assert.equal(retainedResolution.status,'RETAIN_REFERENCE');
const retainedVerdict=C.evaluateDecision({repo:retainedRepo,decision:decision('RAISE'),handClass:'AKs',strategyResolution:retainedResolution});
assert.equal(retainedVerdict.action_status,'NO_VERDICT');
assert.equal(retainedVerdict.context_status,'STRATEGY_UNAVAILABLE');
assert.equal(retainedVerdict.strategy_source,'POPULATION');

// A retained reference still never becomes a population verdict, but a personal
// overlay on the same population is reported as an override.
H.setLayerMetadata(retainedRepo,context,'personal',{version:'personal-3',provenance:{author:'user'}});
H.setHandStrategy(retainedRepo,context,'AKs',{actions:{OPEN:1},sizings:{OPEN:[{target_total_bb:2.5,probability:1}]},notes:'personal override'},{layer:'personal'});
const retainedOverride=C.evaluateDecision({repo:retainedRepo,decision:decision('RAISE'),handClass:'AKs',strategyResolution:retainedResolution});
assert.equal(retainedOverride.action_status,'COMPLIANT');
assert.equal(retainedOverride.strategy_source,'PERSONAL_OVERRIDE');
assert.equal(retainedOverride.layer,'personal');

// An unadmitted calculated strategy resolves to UNAVAILABLE and stays fail-closed.
const unavailableResolution=S.resolveHeroStrategy({population_id:POP,repository:admittedRepo});
assert.equal(unavailableResolution.status,'UNAVAILABLE');
const unavailableVerdict=C.evaluateDecision({repo:admittedRepo,decision:decision('RAISE'),handClass:'AKs',strategyResolution:unavailableResolution});
assert.equal(unavailableVerdict.action_status,'NO_VERDICT');
assert.equal(unavailableVerdict.context_status,'STRATEGY_UNAVAILABLE');
assert.equal(unavailableVerdict.strategy_source,'NONE');

// --- acceptance #2: personal override is reported as an override -------------
const personalRepo=H.emptyRepository({populationId:POP});
H.setLayerMetadata(personalRepo,context,'personal',{version:'personal-3',provenance:{author:'user'}});
H.setHandStrategy(personalRepo,context,'AKs',{actions:{OPEN:1},sizings:{OPEN:[{target_total_bb:2.5,probability:1}]},notes:'personal override'},{layer:'personal'});
const personalResolution=S.resolveHeroStrategy({population_id:POP,repository:personalRepo});
assert.equal(personalResolution.status,'PARTIAL');
assert.equal(personalResolution.source,'PERSONAL_OVERRIDE');
const personalVerdict=C.evaluateDecision({repo:personalRepo,decision:decision('RAISE'),handClass:'AKs',strategyResolution:personalResolution});
assert.equal(personalVerdict.action_status,'COMPLIANT');
assert.equal(personalVerdict.layer,'personal');
assert.equal(personalVerdict.layer_version,'personal-3');
assert.deepEqual(personalVerdict.provenance,{author:'user'});
assert.equal(personalVerdict.strategy_source,'PERSONAL_OVERRIDE');
assert.notEqual(personalVerdict.strategy_source,'POPULATION','an override must never be reported as the population strategy');
assert.equal(personalVerdict.strategy_status,'PARTIAL');

// An admissible population strategy wins over a personal overlay, which stays flagged.
H.setLayerMetadata(admittedRepo,context,'personal',{version:'personal-3',provenance:{author:'user'}});
H.setHandStrategy(admittedRepo,context,'AKs',{actions:{OPEN:1},sizings:{OPEN:[{target_total_bb:2.5,probability:1}]},notes:'personal override'},{layer:'personal'});
const overlaid=C.evaluateDecision({repo:admittedRepo,decision:decision('RAISE'),handClass:'AKs',strategyResolution:admittedResolution});
assert.equal(overlaid.strategy_source,'POPULATION','the population strategy must not be replaced by the personal overlay');
assert.equal(overlaid.layer,'calculated');
assert.equal(overlaid.action_status,'MIXED_ALLOWED');
assert.equal(overlaid.personal_override,true,'the personal overlay must still be reported');

// A legacy direct call without a resolution prefers the calculated strategy but
// still surfaces the personal overlay as a distinct flag.
const legacyOverlay=C.evaluateDecision({repo:admittedRepo,decision:decision('RAISE'),handClass:'AKs'});
assert.equal(legacyOverlay.strategy_source,'POPULATION');
assert.equal(legacyOverlay.layer,'calculated');
assert.equal(legacyOverlay.personal_override,true);

// --- replayer wiring: it resolves the population and forwards the verdict ----
globalThis.replayPreflopDecisionCount=()=>1;
globalThis.populationPreflopDecisionTrace=hand=>[decision('RAISE',{player:hand.heroName})];
const heroHand={heroName:'Hero',heroCards:[12,11],id:'h1'};

assert.equal(R.activePopulationId(personalRepo),POP,'the runtime population comes from the repository defaults when no site population is known');
assert.equal(R.activePopulationId({...personalRepo,defaults:{population_id:OTHER}}),OTHER);
const noAdmissionResolution=R.strategyResolutionFor(admittedRepo);
assert.equal(noAdmissionResolution.source,'NONE');
assert.equal(noAdmissionResolution.status,'UNAVAILABLE');
const personalOnlyResolution=R.strategyResolutionFor(personalRepo);
assert.equal(personalOnlyResolution.source,'PERSONAL_OVERRIDE');

const replayerOverride=R.currentEvaluation(heroHand,personalRepo,personalResolution);
assert.equal(replayerOverride.result.strategy_source,'PERSONAL_OVERRIDE');
assert.equal(replayerOverride.result.action_status,'COMPLIANT');
const replayerCross=R.currentEvaluation(heroHand,foreignRepo,incompatibleResolution);
assert.equal(replayerCross.result.action_status,'NO_VERDICT');
assert.equal(replayerCross.result.context_status,'POPULATION_INCOMPATIBLE');
const replayerPopulation=R.currentEvaluation(heroHand,admittedRepo,admittedResolution);
assert.equal(replayerPopulation.result.strategy_source,'POPULATION');
assert.equal(replayerPopulation.result.action_status,'MIXED_ALLOWED');

const token1=C.repositoryVersionToken(repo);
const token2=C.repositoryVersionToken(H.importDocument(JSON.parse(JSON.stringify(repo))));
assert.equal(token1,token2,'the selected repository version must remain reproducible after reload');

const summary=C.summarize([mixed,out,badSize,unknownSize,missingHand,unsupportedAction,missingContext,personalVerdict]);
assert.equal(summary.judged,5);
assert.equal(summary.allowed,4);
assert.equal(summary.out_of_range,1);
assert.equal(summary.uncovered,3);
assert.equal(summary.sizing_out_of_range,1);
assert.equal(summary.frequency_calibration_status,'NOT_EVALUATED_PER_SINGLE_HAND');

console.log('Hero range compliance contract: PASS');
