'use strict';

// #392 task-4uk: the Review analytics scope identity must be derived from the
// population-bound Hero strategy resolver. When the final #196 strategy is not
// admissible the scope stays explicit and filterable, and never falls back to a
// "Custom" label.

const assert=require('node:assert/strict');
const Leak=require('../../src/analytics/leak-analyzer.js');
const Adapter=require('../../src/analytics/review-score-adapter.js');
const Resolver=require('../../site/hero-strategy-resolver.js');

const POP='pokerstars_nlhe_100-200_zoom_play_6max_v1';

function hasExactCustomLabel(value){
  if(typeof value==='string')return value.trim().toLowerCase()==='custom';
  if(Array.isArray(value))return value.some(hasExactCustomLabel);
  if(value&&typeof value==='object')return Object.values(value).some(hasExactCustomLabel);
  return false;
}

// --- the bridge surface -----------------------------------------------------
assert.equal(Adapter.RESOLUTION_SCOPE_SCHEMA,'poker-review-resolution-scope/v1');
assert.equal(typeof Adapter.reviewScopeFromResolution,'function');
assert.equal(Adapter.UNAVAILABLE_STRATEGY_ID,'UNAVAILABLE_STRATEGY');
assert.equal(Adapter.UNAVAILABLE_STRATEGY_VERSION,'UNAVAILABLE');

// The resolver exposes the normalized identity the Review scope derives from.
assert.equal(typeof Resolver.identity,'function');
assert.deepEqual(
  Resolver.identity({population_id:POP,status:'ADMISSIBLE_CALCULATED',source:'POPULATION',fail_closed:false,strategy_id:'hero-x',strategy_version:'v1'}),
  {population_id:POP,strategy_id:'hero-x',strategy_version:'v1',strategy_sha256:null,status:'ADMISSIBLE_CALCULATED',source:'POPULATION',fail_closed:false,reason_codes:[]}
);
assert.equal(Resolver.identity({}).strategy_id,null);
assert.equal(Resolver.identity({}).status,'UNAVAILABLE');

// --- admitted calculated strategy: the resolver identity is used verbatim ----
{
  const resolution={
    population_id:POP,status:Resolver.STATUSES.ADMISSIBLE_CALCULATED,source:Resolver.SOURCES.POPULATION,
    fail_closed:false,strategy_id:'hero-candidate-196',strategy_version:'gen-196',
    strategy_sha256:'a'.repeat(64),reason_codes:['ADMITTED_CALCULATED_STRATEGY']
  };
  const scope=Adapter.reviewScopeFromResolution(resolution,{pack_id:'zoom-pack@1'});
  assert.equal(scope.schema,Adapter.RESOLUTION_SCOPE_SCHEMA);
  assert.equal(scope.population_id,POP);
  assert.equal(scope.pack_id,'zoom-pack@1');
  assert.equal(scope.strategy_id,'hero-candidate-196');
  assert.equal(scope.strategy_version,'gen-196');
  assert.equal(scope.ev_reference,Adapter.DEFAULT_EV_REFERENCE);
  assert.equal(scope.availability.available,true);
  assert.equal(scope.availability.fail_closed,false);
  assert.equal(scope.availability.status,'ADMISSIBLE_CALCULATED');
  assert.equal(hasExactCustomLabel(scope),false);
}

// --- retained reference is provenance only, never the active strategy --------
{
  const resolution=Resolver.resolveHeroStrategy({
    population_id:POP,
    admissions:{hero_strategy:{status:'RETAIN_REFERENCE',population_id:POP}},
    retained_reference:{population_id:POP,strategy_id:'legacy-ranges-v1',strategy_version:'2026-09-19.1'}
  });
  assert.equal(resolution.status,Resolver.STATUSES.RETAIN_REFERENCE);
  assert.equal(resolution.strategy_id,'legacy-ranges-v1');
  const scope=Adapter.reviewScopeFromResolution(resolution,{pack_id:'zoom-pack@1'});
  assert.equal(scope.strategy_id,Adapter.UNAVAILABLE_STRATEGY_ID);
  assert.equal(scope.strategy_version,'UNAVAILABLE@RETAIN_REFERENCE');
  assert.equal(scope.availability.available,false);
  assert.equal(scope.availability.fail_closed,true);
  assert.equal(scope.availability.source,'POPULATION');
  assert.ok(scope.availability.reason_codes.includes('RETAINED_REFERENCE'));
}

// --- unresolved / rejected / unavailable and incompatible stay explicit ------
{
  const unavailable=Resolver.resolveHeroStrategy({population_id:POP});
  assert.equal(unavailable.status,Resolver.STATUSES.UNAVAILABLE);
  const scope=Adapter.reviewScopeFromResolution(unavailable,{pack_id:'zoom-pack@1'});
  assert.equal(scope.strategy_id,Adapter.UNAVAILABLE_STRATEGY_ID);
  assert.equal(scope.strategy_version,'UNAVAILABLE@UNAVAILABLE');
  assert.equal(scope.availability.available,false);
}
{
  const scope=Adapter.reviewScopeFromResolution(
    {status:'POPULATION_INCOMPATIBLE',source:'NONE',fail_closed:true,reason_codes:['POPULATION_ID_MISMATCH']},
    {population_id:POP,pack_id:'zoom-pack@1'}
  );
  assert.equal(scope.population_id,POP);
  assert.equal(scope.strategy_id,Adapter.UNAVAILABLE_STRATEGY_ID);
  assert.equal(scope.strategy_version,'UNAVAILABLE@POPULATION_INCOMPATIBLE');
  assert.equal(scope.availability.available,false);
  assert.deepEqual(scope.availability.reason_codes,['POPULATION_ID_MISMATCH']);
}

// --- the literal Custom token is never emitted as a strategy identity --------
{
  const scope=Adapter.reviewScopeFromResolution({
    population_id:POP,status:'ADMISSIBLE_CALCULATED',source:'POPULATION',fail_closed:false,
    strategy_id:'Custom',strategy_version:'v1'
  });
  assert.notEqual(String(scope.strategy_id).toLowerCase(),'custom');
  assert.equal(scope.strategy_id,Adapter.UNAVAILABLE_STRATEGY_ID);
  assert.equal(hasExactCustomLabel(scope),false);
}

// A missing population cannot silently degrade into an anonymous scope.
assert.throws(()=>Adapter.reviewScopeFromResolution({status:'UNAVAILABLE'}),/resolution.population_id is required/);

// --- unavailable scopes remain distinct and filterable -----------------------
{
  const retained=Adapter.reviewScopeFromResolution({population_id:POP,status:'RETAIN_REFERENCE'},{pack_id:'zoom-pack@1'});
  const unresolved=Adapter.reviewScopeFromResolution({population_id:POP,status:'UNAVAILABLE'},{pack_id:'zoom-pack@1'});
  assert.notEqual(Leak.scopeKey(retained),Leak.scopeKey(unresolved),'distinct resolver states must stay filterable');
}

// --- end-to-end: adapted events carry the explicit unavailable scope ---------
const HH=`PokerStars Zoom Hand #1: Hold'em No Limit (100/200) - 2026/09/18 21:15:00 CET
Table 'Scope' 6-max Seat #6 is the button
Seat 1: A (20000 in chips)
Seat 2: B (20000 in chips)
Seat 3: C (20000 in chips)
Seat 4: D (20000 in chips)
Seat 5: E (20000 in chips)
Seat 6: Hero (20000 in chips)
A: posts small blind 100
B: posts big blind 200
*** HOLE CARDS ***
Dealt to Hero [As Kd]
C: folds
D: folds
E: folds
Hero: raises 400 to 600
*** SUMMARY ***
Total pot 900 | Rake 0
`;
{
  const baseScope=Adapter.reviewScopeFromResolution(
    {population_id:POP,status:'RETAIN_REFERENCE',source:'POPULATION',fail_closed:false,strategy_id:'legacy-ranges-v1',strategy_version:'2026-09-19.1',reason_codes:['RETAINED_REFERENCE']},
    {pack_id:'zoom-pack@1'}
  );
  const adapted=Adapter.adaptPersistedReviewData({
    reviewScores:{'1':{handId:'1',signature:'sig-Z',complete:false,details:[]}},
    hhSources:[{name:'scope.txt',content:HH}],scope:baseScope
  });
  assert.equal(adapted.events.length,1);
  const event=adapted.events[0];
  assert.equal(event.strategy_id,Adapter.UNAVAILABLE_STRATEGY_ID);
  assert.equal(event.strategy_version,'UNAVAILABLE@RETAIN_REFERENCE@sig-Z');
  assert.equal(hasExactCustomLabel(Leak.scopeOf(event)),false);
  const report=Leak.analyzeLeaks(adapted.events);
  assert.equal(report.scope.strategy_id,Adapter.UNAVAILABLE_STRATEGY_ID);
  assert.equal(hasExactCustomLabel(report.scope),false);
}

console.log(JSON.stringify({status:'PASS',schema:Adapter.RESOLUTION_SCOPE_SCHEMA,states:['ADMISSIBLE_CALCULATED','RETAIN_REFERENCE','UNAVAILABLE','POPULATION_INCOMPATIBLE']}));
