'use strict';

const assert=require('node:assert/strict');
const Leak=require('../../src/analytics/leak-analyzer.js');
const Audit=require('../../src/analytics/hero-recommendation-distribution.js');

const IDENTITY={
  population_id:'pokerstars_nlhe_100-200_zoom_play_6max_v1',
  pack_id:'hero-pack',
  pack_version:'pack-v1',
  strategy_id:'hero-promoted-v1',
  strategy_version:'strategy-v1',
  ev_reference:'decision_point_incremental_bb'
};

function observation(id,recAction,opts={}){
  const covered=opts.covered!==false;
  const comparable=opts.comparable!==false;
  const played=opts.played_action||'CALL';
  const event=Leak.buildDecisionEvent({
    hand_id:'h-'+id,
    decision_id:'d-'+id,
    timestamp:'2026-09-19T01:'+String(Number(id)%60).padStart(2,'0')+':00Z',
    population_id:IDENTITY.population_id,
    pack_id:IDENTITY.pack_id,
    strategy_id:IDENTITY.strategy_id,
    strategy_version:IDENTITY.strategy_version,
    ev_reference:IDENTITY.ev_reference,
    position:opts.position||'BTN',
    street:opts.street||'FLOP',
    spot_family:opts.spot_family||'SINGLE_RAISED_POT',
    context_id:opts.context_id||'ctx-'+id,
    action_played:played,
    played_target_total_bb:opts.played_target_total_bb==null?null:opts.played_target_total_bb,
    played_size_pot_ratio:opts.played_size_pot_ratio==null?null:opts.played_size_pot_ratio,
    played_is_all_in:Boolean(opts.played_is_all_in),
    played_is_overbet:Boolean(opts.played_is_overbet),
    action_recommended:recAction,
    recommended_target_total_bb:opts.recommended_target_total_bb==null?null:opts.recommended_target_total_bb,
    recommended_size_pot_ratio:opts.recommended_size_pot_ratio==null?null:opts.recommended_size_pot_ratio,
    played_ev_bb:-9876.54321,
    best_ev_bb:-9875.54321,
    support:covered
      ?{covered:true,observations:opts.support_observations||100,source:'SYNTHETIC'}
      :{covered:false,observations:0,source:'SYNTHETIC',reason:'NO_COVERAGE'},
    comparability:comparable?{comparable:true}:{comparable:false,reason:'NOT_COMPARABLE'}
  });
  return {
    schema:'poker-hero-recommendation-observation/v1',
    identity:{...IDENTITY,...(opts.identity||{})},
    pack_version:IDENTITY.pack_version,
    decision_event:event,
    recommendation_admissibility:{
      admissible:opts.admissible!==false,
      status:opts.admissible===false?(opts.admissibility_status||'NO_ADMISSIBLE_STRATEGY'):'ADMISSIBLE'
    },
    coverage_state:covered?'COVERED':'UNSUPPORTED',
    support_tier:opts.support_tier||'HIGH',
    observed_spot_frequency_weight:opts.weight,
    source:{split:opts.split||'SYNTHETIC',issue:opts.issue,optimization:Boolean(opts.optimization),promotion:Boolean(opts.promotion),source:'fixture'}
  };
}

function canonicalPreflop(){
  return {
    schema:'poker-preflop-decision/v1',
    contract_profile:'CANONICAL_RUNTIME_DECISION_V1',
    decision_id:'d-6',
    hand_id:'h-6',
    street:'PREFLOP',
    context_id:'ctx-preflop',
    hero_position:'BB',
    facing_context:'VS_RFI',
    played_action:'CALL',
    played_target_sizing:null,
    played_ev_bb:-4321.12345,
    recommended_action:'CALL',
    recommended_target_sizing:null,
    recommended_ev_bb:-4320.12345,
    delta_ev_bb:1,
    coverage_state:'COVERED',
    support_tier:'HIGH',
    recommendation_admissibility:{admissible:true,status:'ADMISSIBLE'},
    identity:{...IDENTITY},
    source:{split:'SYNTHETIC',source:'fixture'}
  };
}

function fixture(){
  return [
    observation('1','RAISE',{
      context_id:'ctx-standard',weight:.4,
      recommended_target_total_bb:6,recommended_size_pot_ratio:.6,
      played_action:'CALL',played_target_total_bb:4,played_size_pot_ratio:.4
    }),
    observation('2','JAM',{
      context_id:'ctx-tail',weight:.1,
      recommended_target_total_bb:100,recommended_size_pot_ratio:2,
      played_action:'CALL',played_target_total_bb:8,played_size_pot_ratio:.5
    }),
    observation('3','BET',{
      street:'TURN',position:'CO',spot_family:'BARREL',context_id:'ctx-tail-turn',weight:.2,
      support_tier:'LOW',
      recommended_target_total_bb:12,recommended_size_pot_ratio:1.2,
      played_action:'CHECK'
    }),
    observation('4','RAISE',{
      street:'TURN',position:'CO',spot_family:'BARREL',context_id:'ctx-uncovered',weight:.2,
      covered:false,comparable:false,
      recommended_target_total_bb:10,recommended_size_pot_ratio:.8,
      played_action:'BET',played_target_total_bb:5,played_size_pot_ratio:.4
    }),
    observation('5','JAM',{
      context_id:'ctx-failclosed',weight:.1,
      admissible:false,admissibility_status:'NO_ADMISSIBLE_STRATEGY',
      recommended_target_total_bb:100,recommended_size_pot_ratio:2,
      played_action:'FOLD'
    }),
    canonicalPreflop(),
    observation('7','CALL',{
      context_id:'ctx-played-jam',weight:.1,
      played_action:'SHOVE',played_target_total_bb:100,played_size_pot_ratio:1.5,
      played_is_all_in:true,played_is_overbet:true
    })
  ];
}

function segment(report,dimension,key){
  const row=report.segments.find(x=>x.dimension===dimension&&x.key===key);
  assert.ok(row,'missing '+dimension+'='+key);
  return row;
}

{
  const report=Audit.analyzeRecommendationDistribution({records:fixture(),identity:IDENTITY});
  assert.equal(report.schema,'poker-hero-recommendation-distribution/v1');
  assert.equal(report.config_schema,'poker-hero-recommendation-distribution-config/v1');
  assert.deepEqual(report.identity,IDENTITY);

  assert.equal(report.exposure.input_decisions,7);
  assert.equal(report.exposure.admissible_recommendations,6);
  assert.equal(report.exposure.fail_closed_decisions,1);
  assert.equal(report.exposure.uncovered_admissible_decisions,1);
  assert.equal(report.exposure.low_support_admissible_decisions,1);
  assert.equal(report.exposure.supported_recommendations,4);
  assert.equal(report.exposure.weighted_recommendations,5);
  assert.equal(report.exposure.fail_closed_reasons.NO_ADMISSIBLE_STRATEGY,1);

  const raw=report.distributions.raw;
  assert.equal(raw.recommendation_count,6);
  assert.equal(raw.action_distribution.actions.RAISE.count,2);
  assert.equal(raw.action_distribution.actions.JAM.count,1,
    'fail-closed JAM must not be counted as a recommendation');
  assert.equal(raw.action_distribution.actions.BET.count,1);
  assert.equal(raw.action_distribution.actions.CALL.count,2);
  assert.equal(raw.tails.jam.count,1);
  assert.equal(raw.tails.overbet.count,2);
  assert.equal(raw.tails.large_sizing.count,2);

  const supported=report.distributions.supported;
  assert.equal(supported.recommendation_count,4);
  assert.equal(supported.action_distribution.actions.JAM.count,1);
  assert.equal(supported.action_distribution.actions.BET.count,0,
    'LOW support recommendation must be excluded from supported view');
  assert.equal(supported.action_distribution.actions.RAISE.count,1,
    'uncovered recommendation must be excluded from supported view');
  assert.equal(supported.tails.overbet.count,1);

  const weighted=report.distributions.observed_frequency_weighted;
  assert.equal(weighted.recommendation_count,5);
  assert.equal(weighted.action_distribution.total_weight,1);
  assert.equal(weighted.action_distribution.actions.JAM.frequency,.1);
  assert.equal(weighted.tails.overbet.frequency,.3);
  assert.equal(weighted.tails.jam.frequency,.1);

  assert.equal(raw.played_comparison.decision_count,6);
  assert.ok(raw.played_comparison.actions.CALL.delta<0);
  assert.equal(raw.played_comparison.sizing_comparable_count,3);

  assert.equal(segment(report,'street','PREFLOP').exposure.admissible_recommendations,1);
  assert.equal(segment(report,'street','TURN').exposure.admissible_recommendations,2);
  assert.equal(segment(report,'position','CO').exposure.admissible_recommendations,2);
  assert.equal(segment(report,'spot_family','BARREL').exposure.admissible_recommendations,2);
  assert.equal(segment(report,'context','ctx-tail').distributions.raw.tails.jam.count,1);
  assert.equal(segment(report,'support','LOW').distributions.raw.tails.overbet.count,1);

  assert.equal(report.aggressive_tail_ranking[0].context.context_id,'ctx-tail');
  assert.equal(report.aggressive_tail_ranking[0].jam_count,1);
  assert.equal(report.aggressive_tail_ranking[0].overbet_count,1);
  assert.deepEqual(report.aggressive_tail_ranking[0].source_refs,[{hand_id:'h-2',decision_id:'d-2'}]);

  assert.deepEqual(report.source_refs,[
    {hand_id:'h-1',decision_id:'d-1'},
    {hand_id:'h-2',decision_id:'d-2'},
    {hand_id:'h-3',decision_id:'d-3'},
    {hand_id:'h-4',decision_id:'d-4'},
    {hand_id:'h-5',decision_id:'d-5'},
    {hand_id:'h-6',decision_id:'d-6'},
    {hand_id:'h-7',decision_id:'d-7'}
  ]);

  assert.equal(report.semantics.support_coverage_separate_from_distribution,true);
  assert.equal(report.semantics.fail_closed_counted_as_recommendation,false);
  assert.equal(report.semantics.test_consumed,false);
  assert.equal(report.semantics.issue_108_consumed,false);
  assert.equal(report.semantics.optimization_performed,false);
  assert.equal(report.semantics.promotion_performed,false);
  assert.equal(report.semantics.automatic_aggressiveness_verdict,false);
  assert.equal(report.semantics.ev_metrics_consumed,false);

  const json=Audit.exportJSON(report,{pretty:false});
  assert.equal(json.includes('9876.54321'),false,'EV must not contaminate the descriptive audit');
  assert.equal(json.includes('4321.12345'),false,'canonical decision EV must not contaminate the descriptive audit');
}

{
  const playedJam=Audit.analyzeRecommendationDistribution({
    records:[observation('7','CALL',{
      context_id:'ctx-played-jam',weight:1,
      played_action:'SHOVE',played_target_total_bb:100,played_size_pot_ratio:1.5,
      played_is_all_in:true,played_is_overbet:true
    })],
    identity:IDENTITY
  });
  assert.equal(playedJam.distributions.raw.tails.jam.count,0,
    '#200 played JAM tag must not be reused as recommended JAM');
  assert.equal(playedJam.distributions.raw.tails.overbet.count,0,
    '#200 played overbet tag must not be reused as recommended overbet');
  assert.equal(playedJam.distributions.raw.action_distribution.actions.CALL.count,1);
}

{
  const records=fixture();
  const a=Audit.analyzeRecommendationDistribution({records,identity:IDENTITY});
  const b=Audit.analyzeRecommendationDistribution({records:[...records].reverse(),identity:IDENTITY});
  assert.deepEqual(a,b,'input order must not alter report');
  assert.equal(a.report_hash,b.report_hash);
  assert.equal(Audit.exportJSON(a,{pretty:false}),Audit.exportJSON(b,{pretty:false}));
}

{
  const rows=fixture();
  rows[0]={
    ...rows[0],
    identity:{...rows[0].identity,strategy_version:'other-version'},
    decision_event:{...rows[0].decision_event,strategy_version:'other-version'}
  };
  assert.throws(()=>Audit.analyzeRecommendationDistribution({records:rows}),/multiple population\/pack\/version\/strategy\/EV identities/);
}

{
  const bad=observation('12','CALL');
  bad.identity={...bad.identity,strategy_version:'other-version'};
  assert.throws(()=>Audit.analyzeRecommendationDistribution({records:[bad]}),/observation identity does not match decision_event/);
}

{
  const bad=observation('8','CALL',{split:'TEST'});
  assert.throws(()=>Audit.analyzeRecommendationDistribution({records:[bad],identity:IDENTITY}),/TEST consumption is forbidden/);
}

{
  const bad=observation('9','CALL',{issue:108});
  assert.throws(()=>Audit.analyzeRecommendationDistribution({records:[bad],identity:IDENTITY}),/#108 consumption is forbidden/);
}

{
  const bad=observation('10','CALL',{optimization:true});
  assert.throws(()=>Audit.analyzeRecommendationDistribution({records:[bad],identity:IDENTITY}),/optimization output is forbidden/);
}

{
  const bad=observation('11','CALL',{promotion:true});
  assert.throws(()=>Audit.analyzeRecommendationDistribution({records:[bad],identity:IDENTITY}),/promotion output is forbidden/);
}

{
  const report=Audit.analyzeRecommendationDistribution({
    records:[],
    identity:IDENTITY,
    config:{
      supported_tiers:['HIGH'],
      large_sizing_pot_ratio:1.25,
      large_sizing_target_bb:30,
      sizing_buckets:{pot_ratio_edges:[.5,1,1.5],target_bb_edges:[3,10,30]},
      ranking_limit:10
    }
  });
  assert.equal(report.exposure.input_decisions,0);
  assert.equal(report.distributions.raw.recommendation_count,0);
  assert.equal(report.report_hash.startsWith('hero-recommendation-distribution:'),true);
  assert.equal(report.config.large_sizing_pot_ratio,1.25);
}

console.log(JSON.stringify({
  status:'PASS',
  schema:Audit.REPORT_SCHEMA,
  config_schema:Audit.CONFIG_SCHEMA,
  dimensions:Audit.DIMENSIONS
}));
