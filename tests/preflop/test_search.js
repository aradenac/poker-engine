#!/usr/bin/env node
'use strict';

const assert=require('node:assert/strict');
const Contract=require('../../src/preflop/contract.js');
const Decision=require('../../src/preflop/decision.js');
const Search=require('../../src/preflop/search.js');

const POS=['LJ','HJ','CO','BTN','SB','BB'];
const stacks=Object.fromEntries(POS.map(p=>[p,100]));

function context({actor='BTN',history=[],contrib={},current=1,minRaise=2,raiseLevel=null,pot=1.5,allIn=[]}={}){
  return Contract.buildContext({
    table_size:6,
    actor_position:actor,
    live_positions:POS,
    all_in_positions:allIn,
    history,
    contribution_bb_by_position:{LJ:0,HJ:0,CO:0,BTN:0,SB:.5,BB:1,...contrib},
    stack_bb_by_position:stacks,
    current_price_bb:current,
    min_raise_to_bb:minRaise,
    raise_level:raiseLevel,
    pot_before_bb:pot
  });
}

function actions(built){return built.candidates.map(x=>x.action);}
function ids(built){return built.candidates.map(x=>x.id);}

function testUnopenedAndSizingGrid(){
  const c=context();
  assert.equal(c.family,'UNOPENED');
  assert.deepEqual(Search.semanticLegalActions(c),['FOLD','LIMP','OPEN','SHOVE']);
  const built=Search.buildCandidates(c,{sizing_grid_bb:[1.5,2.5,3,100,3],sizing_grid_source:'observed_train_sizes'});
  assert.deepEqual(ids(built),['FOLD','LIMP@1','OPEN@2.5','OPEN@3','SHOVE@100']);
  assert.deepEqual(built.sizing_grid,{source:'observed_train_sizes',targets_bb:[2.5,3]});
  assert.equal(built.candidates.find(x=>x.id==='OPEN@3').incremental_cost_bb,3);
}

function testLimpers(){
  const cases=[
    [{position:'HJ',action:'LIMP'}],
    [{position:'LJ',action:'LIMP'},{position:'HJ',action:'LIMP'}],
    [{position:'LJ',action:'LIMP'},{position:'HJ',action:'LIMP'},{position:'CO',action:'LIMP'}]
  ];
  for(const [index,hist] of cases.entries()){
    const actor=index===2?'BTN':'CO';
    const contrib=Object.fromEntries(hist.map(x=>[x.position,1]));
    const c=context({actor,history:hist,contrib,pot:1.5+hist.length});
    assert.equal(c.family,'VS_LIMPERS');
    const built=Search.buildCandidates(c,{sizing_grid_bb:[4+hist.length]});
    assert(actions(built).includes('OVERLIMP'));
    assert(actions(built).includes('ISO'));
    assert.equal(built.candidates.find(x=>x.action==='ISO').target_total_bb,4+hist.length);
  }
}

function testSqueezeAndThreeBet(){
  const squeeze=context({
    actor:'BTN',
    history:[{position:'LJ',action:'RAISE'},{position:'HJ',action:'CALL'},{position:'CO',action:'CALL'}],
    contrib:{LJ:2.5,HJ:2.5,CO:2.5},current:2.5,minRaise:4,pot:9
  });
  assert.equal(squeeze.family,'VS_RFI_CALLERS');
  assert.deepEqual(Search.semanticLegalActions(squeeze),['FOLD','CALL','SQUEEZE','SHOVE']);
  assert(actions(Search.buildCandidates(squeeze,{sizing_grid_bb:[8,10]})).includes('SQUEEZE'));

  const threeBet=context({
    actor:'BTN',history:[{position:'CO',action:'RAISE'}],contrib:{CO:2.5},current:2.5,minRaise:4,pot:4
  });
  assert.equal(threeBet.family,'VS_RFI');
  assert.deepEqual(Search.semanticLegalActions(threeBet),['FOLD','CALL','3BET','SHOVE']);
}

function testFourBetAndFreeCheck(){
  const fourBet=context({
    actor:'CO',
    history:[{position:'CO',action:'RAISE'},{position:'BTN',action:'RAISE'}],
    contrib:{CO:2.5,BTN:8},current:8,minRaise:13.5,pot:12
  });
  assert.equal(fourBet.raise_level,2);
  assert(actions(Search.buildCandidates(fourBet,{sizing_grid_bb:[20,22]})).includes('4BET'));

  const free=context({
    actor:'BB',
    history:[
      {position:'LJ',action:'LIMP'},{position:'HJ',action:'LIMP'},{position:'CO',action:'LIMP'},
      {position:'BTN',action:'LIMP'},{position:'SB',action:'LIMP'}
    ],
    contrib:{LJ:1,HJ:1,CO:1,BTN:1,SB:1,BB:1},current:1,minRaise:2,pot:6
  });
  assert.equal(free.free_check,true);
  assert.deepEqual(Search.semanticLegalActions(free),['CHECK','ISO','SHOVE']);
  const built=Search.buildCandidates(free,{sizing_grid_bb:[4,5]});
  assert.equal(built.candidates.find(x=>x.id==='CHECK').incremental_cost_bb,0);
  assert.equal(built.candidates.find(x=>x.id==='ISO@4').incremental_cost_bb,3);
}

function testCallShoveAfterCaller(){
  const c=context({
    actor:'BB',
    history:[
      {position:'CO',action:'RAISE'},
      {position:'BTN',action:'JAM'},
      {position:'SB',action:'CALL'}
    ],
    contrib:{CO:2.5,BTN:50,SB:50,BB:1},current:50,minRaise:97.5,pot:103.5
  });
  assert.equal(Search.semanticAction('CALL',c),'CALL_SHOVE','a caller after the jam must not hide CALL_SHOVE semantics');
}

function testFailClosedSizingAndUnsupportedHighRaise(){
  const c=context();
  assert.throws(
    ()=>Search.buildCandidates(c,{sizing_grid_bb:[]}),
    err=>err instanceof Search.UncoveredPreflopSearchError&&/no explicit/.test(err.message)
  );
  const high={...c,raise_level:3,family:'AGGRESSOR_VS_4BET',legal_actions:['FOLD','CALL','RAISE','JAM']};
  assert.throws(
    ()=>Search.buildCandidates(high,{sizing_grid_bb:[30]}),
    err=>err instanceof Search.UncoveredPreflopSearchError&&/beyond/.test(err.message)
  );
}

async function testSearchBindsEvToExactSizingAndBudget(){
  const c=context();
  const scores={'LIMP@1':.10,'OPEN@2.5':.35,'OPEN@3':.72,'SHOVE@100':-.4};
  const calls=[];
  const decision=await Search.searchPreflopDecision({
    context:c,
    population_id:'fixture-pop',
    hand_class:'A5s',
    sizing_grid_bb:[2.5,3],
    sizing_grid_source:'observed_train_sizes_sha256:abc',
    budget:40,
    seed:'seed-106',
    evaluate_alternative:async request=>{
      calls.push({id:request.candidate.id,target:request.candidate.target_total_bb,budget:request.candidate_budget,remaining:[...request.remaining_to_act_positions]});
      return {
        ev_bb:scores[request.candidate.id],
        support:{observations:120,backoff_level:'EXACT',source:'synthetic-continuation-oracle'},
        confidence:.8,
        uncertainty:{
          monte_carlo:{standard_error_bb:.02,samples:request.candidate_budget,method:'fixture'},
          model:{lower_bb:scores[request.candidate.id]-.1,upper_bb:scores[request.candidate.id]+.1,method:'fixture-band',status:'ESTIMATED'}
        }
      };
    }
  });
  assert.equal(Decision.validateDecision(decision),true);
  assert.equal(decision.action,'OPEN');
  assert.equal(decision.target_total_bb,3);
  assert.equal(decision.incremental_cost_bb,3);
  assert.equal(decision.ev_bb,.72);
  assert.equal(decision.ev_reference,'decision_point_incremental_bb');
  assert.equal(decision.alternatives.find(x=>x.id==='OPEN@2.5').ev_bb,.35);
  assert.equal(decision.alternatives.find(x=>x.id==='OPEN@3').ev_bb,.72);
  assert.equal(decision.alternatives.find(x=>x.id==='FOLD').ev_bb,0);
  assert.equal(calls.length,4,'fold is deterministic and must not spend continuation budget');
  assert.equal(calls.reduce((s,x)=>s+x.budget,0),40);
  assert.deepEqual(calls.map(x=>x.budget),[10,10,10,10]);
  assert.deepEqual(calls.filter(x=>x.id.startsWith('OPEN')).map(x=>[x.id,x.target]),[['OPEN@2.5',2.5],['OPEN@3',3]]);
  assert.equal(decision.search.sizing_grid_source,'observed_train_sizes_sha256:abc');
  assert.equal(decision.search.seed,'seed-106');
}

async function testTieBreakIsDeterministicAndConservative(){
  const c=context();
  const decision=await Search.searchPreflopDecision({
    context:c,sizing_grid_bb:[2.5,3],budget:0,seed:'tie',
    evaluate_alternative:async request=>({ev_bb:request.candidate.action==='SHOVE'?-1:0,support:{backoff_level:'FIXTURE'}})
  });
  // FOLD, LIMP and both OPEN sizes all tie at 0 EV. Lower incremental cost wins: FOLD.
  assert.equal(decision.selected_id,'FOLD');
  assert.equal(decision.action,'FOLD');
}

(async()=>{
  testUnopenedAndSizingGrid();
  testLimpers();
  testSqueezeAndThreeBet();
  testFourBetAndFreeCheck();
  testCallShoveAfterCaller();
  testFailClosedSizingAndUnsupportedHighRaise();
  await testSearchBindsEvToExactSizingAndBudget();
  await testTieBreakIsDeterministicAndConservative();
  console.log('preflop search orchestrator tests: PASS');
})().catch(err=>{console.error(err);process.exit(1);});
