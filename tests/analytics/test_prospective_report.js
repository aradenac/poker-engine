'use strict';

const assert=require('node:assert/strict');
const Leak=require('../../src/analytics/leak-analyzer.js');
const Coverage=require('../../src/analytics/analysis-coverage.js');
const Drift=require('../../src/analytics/population-drift.js');
const Prospective=require('../../src/analytics/prospective-report.js');

const POP='pokerstars_nlhe_100-200_zoom_play_6max_v1';
const A='a'.repeat(64),B='b'.repeat(64),C='c'.repeat(64),D='d'.repeat(64),E='e'.repeat(64),F='f'.repeat(64);
const COMMIT='1'.repeat(40);

function protocol(){
  return {
    schema:'poker-prospective-holdout-protocol/v1',
    protocol_version:'fixture-v1',
    manifest_schema:'poker-prospective-holdout/v1',
    rules:{
      candidate_frozen_before_admission:true,
      candidate_fit_identity_frozen:true,
      prospective_hands_must_be_absent_from_candidate_fit:true,
      append_only_hands_while_unconsumed:true,
      ledger_frozen_during_evaluation:true,
      no_train_before_closed:true,
      thresholds_frozen_before_admission:true,
      future_train_requires_new_cycle:true,
      separate_drift_coverage_performance_report:true,
      test_or_validation_split_is_not_reused_as_prospective_holdout:true,
      historical_holdout_ledgers_are_not_rewritten:true
    },
    scope:{phase:'PROTOCOL_ONLY',issue:202,no_scientific_execution:true}
  };
}
function manifest(){
  return {
    schema:'poker-prospective-holdout/v1',
    holdout_id:'synthetic-holdout-1',
    generation:1,
    parent_holdout_id:null,
    population_id:POP,
    state:'UNCONSUMED',
    previous_manifest_sha256:null,
    precommit:{
      frozen_at:'2026-09-19T00:00:00Z',
      source_commit_sha:COMMIT,
      prior_hand_ids_sha256:F,
      fit:{completed_at:'2026-09-18T23:00:00Z',training_dataset_sha256:A,training_hand_ids_sha256:B},
      candidate:{id:'synthetic-candidate',artifact_sha256:C,pack_sha256:D},
      models:{model_a_sha256:D,model_b_sha256:E},
      strategy_sha256:C,
      protocol_sha256:A,
      metrics_sha256:B,
      thresholds_sha256:D
    },
    temporal_boundary:{cutoff_utc:'2026-09-19T00:00:00Z',admission_not_before_utc:'2026-09-20T00:00:00Z'},
    hands:[
      {hand_id:'t-h1',sha256:A,observed_at:'2026-09-20T00:01:00Z',first_seen_at:'2026-09-20T00:02:00Z',train_eligible:false},
      {hand_id:'t-h2',sha256:B,observed_at:'2026-09-20T00:03:00Z',first_seen_at:'2026-09-20T00:04:00Z',train_eligible:false}
    ],
    evaluation:null,
    training_transition:null
  };
}
function validation(m=manifest(),status='PASS'){
  return {
    schema:'poker-prospective-holdout-report/v1',
    status,
    errors:[],warnings:[],
    holdout_id:m.holdout_id,state:m.state,hand_count:m.hands.length,
    manifest_sha256:E
  };
}
function cohort(split='SYNTHETIC'){
  return {
    holdout_id:'synthetic-holdout-1',generation:1,population_id:POP,
    manifest_sha256:E,dataset_fingerprint:'target-dataset-fp',source_fingerprint:'target-source-fp',
    hand_count:2,decision_count:4,split
  };
}
function identity(){
  return {
    population_id:POP,candidate_id:'synthetic-candidate',candidate_artifact_sha256:C,
    pack_sha256:D,strategy_sha256:C,cohort_manifest_sha256:E,
    cohort_dataset_fingerprint:'target-dataset-fp',cohort_source_fingerprint:'target-source-fp',
    metrics_sha256:B,thresholds_sha256:D
  };
}

function event(hand,decision,action,target=null,ratio=null,opts={}){
  return Leak.buildDecisionEvent({
    hand_id:hand,decision_id:decision,timestamp:'2026-09-20T00:10:00Z',
    population_id:POP,pack_id:'analysis-pack',strategy_id:'observed-population',
    strategy_version:'v1',ev_reference:'review_score_policy_adjusted_incremental_bb',
    position:'BTN',street:'PREFLOP',spot_family:'UNOPENED',context_id:'ctx-btn-unopened',
    action_played:action,played_target_total_bb:target,played_size_pot_ratio:ratio,
    played_is_all_in:Boolean(opts.jam),played_is_overbet:Boolean(opts.overbet),
    action_recommended:'CHECK',
    played_ev_bb:-12345.6789,best_ev_bb:0,
    support:{covered:true,observations:100,source:'SYNTHETIC'},
    comparability:{comparable:true}
  });
}
function baselineEvents(){
  return [
    event('b-h1','b-d1','FOLD'),
    event('b-h1','b-d2','CALL',1),
    event('b-h2','b-d3','RAISE',2.5,.5),
    event('b-h2','b-d4','RAISE',3,.6)
  ];
}
function targetStable(){
  return [
    event('t-h1','t-d1','FOLD'),
    event('t-h1','t-d2','CALL',1),
    event('t-h2','t-d3','RAISE',2.5,.5),
    event('t-h2','t-d4','RAISE',3,.6)
  ];
}
function targetDrifted(){
  return [
    event('t-h1','t-d1','CALL',1),
    event('t-h1','t-d2','RAISE',8,1.2,{overbet:true}),
    event('t-h2','t-d3','SHOVE',100,2,{jam:true,overbet:true}),
    event('t-h2','t-d4','SHOVE',100,2,{jam:true,overbet:true})
  ];
}
function driftReport(target=targetStable(),low=false){
  return Drift.analyzePopulationDrift({
    population_id:POP,
    baseline_cohort:{
      cohort_id:'historical',source:'synthetic',split:'TRAIN',window:null,hand_count:2,decision_count:4,
      dataset_fingerprint:'baseline-dataset-fp',source_fingerprint:'baseline-source-fp'
    },
    target_cohort:{
      cohort_id:'prospective-fixture',source:'synthetic',split:'SYNTHETIC',window:null,hand_count:2,decision_count:4,
      dataset_fingerprint:'target-dataset-fp',source_fingerprint:'target-source-fp'
    },
    baseline_events:baselineEvents(),target_events:target,
    config:{
      minimum_decisions_per_cohort:low?10:1,
      minimum_distinct_hands_per_cohort:low?10:1,
      minimum_supported_decisions_per_cohort:low?10:1,
      minimum_supported_ratio:.5,
      absolute_frequency_delta_threshold:.2,
      relative_frequency_delta_threshold:.5,
      relative_delta_min_baseline_frequency:.05,
      js_divergence_threshold:.04,
      sizing_js_divergence_threshold:.04,
      bootstrap_min_decisions_per_cohort:10,
      bootstrap_iterations:20,
      bootstrap_confidence:.9,
      bootstrap_seed:'prospective-fixture',
      sizing_buckets:{pot_ratio_edges:[.33,.66,1],target_bb_edges:[2.5,4,8,20]}
    }
  });
}
function coverageReport({gap=false,low=false}={}){
  let events=targetStable();
  if(gap){
    const raw=events[0];
    events=[{
      ...raw,
      support:{covered:false,observations:0,source:'SYNTHETIC',reason:'NO_MODEL_SUPPORT'},
      comparability:{comparable:false,reason:'NO_MODEL_SUPPORT'},
      ev:{...raw.ev,played_bb:null,best_bb:null,raw_delta_bb:0,nominal_loss_bb:0,attributed_loss_bb:0}
    },...events.slice(1)];
  }
  if(low){
    events=events.map(e=>({...e,support:{...e.support,observations:1}}));
  }
  return Coverage.analyzeCoverage({
    decision_events:events,
    scope:{
      population_id:POP,pack_id:'analysis-pack',pack_version:null,
      strategy_id:'observed-population',strategy_version:'v1',
      ev_reference:'review_score_policy_adjusted_incremental_bb'
    },
    minimum_supported_observations:low?20:1
  });
}
function generic(schema,classification='PASS',support_state='SUFFICIENT',refs=[{hand_id:'t-h1',decision_id:'t-d1'}]){
  return {
    schema,identity:identity(),classification,support_state,
    summary:{metric:'synthetic_metric',value:.42},
    source_refs:refs,reason_codes:[],
    evidence_fingerprint:schema+'-fixture-fingerprint'
  };
}
function input(evidence={}){
  const m=manifest();
  return {
    protocol:protocol(),
    holdout_manifest:m,
    protocol_validation:validation(m),
    prospective_cohort:cohort(),
    evidence,
    prospective_evaluation:false
  };
}

{
  const report=Prospective.assembleProspectiveReport(input());
  assert.equal(report.schema,'poker-prospective-analytics-report/v1');
  assert.equal(report.holdout_id,'synthetic-holdout-1');
  assert.equal(report.sections.population_drift.state,'NOT_EVALUATED');
  assert.equal(report.sections.coverage.state,'NOT_EVALUATED');
  assert.equal(report.sections.model_calibration.state,'NOT_EVALUATED');
  assert.equal(report.sections.strategy_performance.state,'NOT_EVALUATED');
  assert.deepEqual(report.protocol_classification,{
    population_drift:'NOT_EVALUATED',coverage:'NOT_EVALUATED',performance:'NOT_EVALUATED'
  });
  assert.equal(report.strategic_verdict,null);
  assert.equal(report.semantics.test_consumed,false);
  assert.equal(report.semantics.prospective_evaluation,false);
  assert.equal(report.semantics.thresholds_modified,false);
  assert.equal(report.semantics.promotion_performed,false);
  assert.match(Prospective.humanSummary(report),/No strategic verdict/);
}

{
  const report=Prospective.assembleProspectiveReport(input({
    population_drift:{report:driftReport(targetStable()),identity:identity()},
    coverage:{report:coverageReport(),identity:identity(),evidence_fingerprint:'coverage-fp'},
    model_calibration:generic('poker-prospective-model-calibration-evidence/v1','PASS'),
    strategy_performance:generic('poker-prospective-strategy-performance-evidence/v1','PASS')
  }));
  assert.equal(report.sections.population_drift.state,'NO_DRIFT');
  assert.equal(report.sections.population_drift.protocol_classification,'PASS');
  assert.equal(report.sections.coverage.state,'COVERED');
  assert.equal(report.sections.coverage.protocol_classification,'PASS');
  assert.equal(report.sections.model_calibration.state,'PERFORMANCE_RESULT');
  assert.equal(report.sections.strategy_performance.state,'PERFORMANCE_RESULT');
  assert.deepEqual(report.protocol_classification,{population_drift:'PASS',coverage:'PASS',performance:'PASS'});
  assert.equal(report.strategic_verdict,null);
  assert.ok(report.source_refs.some(x=>x.hand_id==='t-h1'&&x.decision_id==='t-d1'));
  assert.ok(report.source_refs.some(x=>x.hand_id==='t-h2'&&x.decision_id==='t-d4'));
}

{
  const report=Prospective.assembleProspectiveReport(input({
    population_drift:{report:driftReport(targetDrifted()),identity:identity()},
    coverage:{report:coverageReport(),identity:identity(),evidence_fingerprint:'coverage-fp'},
    strategy_performance:generic('poker-prospective-strategy-performance-evidence/v1','PASS')
  }));
  assert.equal(report.sections.population_drift.state,'DRIFT');
  assert.equal(report.protocol_classification.population_drift,'WARN');
  assert.equal(report.protocol_classification.coverage,'PASS');
  assert.equal(report.protocol_classification.performance,'PASS',
    'population drift must not be converted into a strategy/performance verdict');
  assert.equal(report.strategic_verdict,null);
  assert.equal(report.sections.strategy_performance.protocol_classification,'PASS');
}

{
  const report=Prospective.assembleProspectiveReport(input({
    coverage:{report:coverageReport({gap:true}),identity:identity(),evidence_fingerprint:'coverage-gap-fp'}
  }));
  assert.equal(report.sections.coverage.state,'COVERAGE_GAP');
  assert.equal(report.sections.coverage.protocol_classification,'WARN');
  assert.equal(report.sections.strategy_performance.state,'NOT_EVALUATED');
  assert.equal(report.protocol_classification.performance,'NOT_EVALUATED',
    'coverage gap must not become a performance verdict');
}

{
  const report=Prospective.assembleProspectiveReport(input({
    population_drift:{report:driftReport(targetStable(),true),identity:identity()},
    coverage:{report:coverageReport({low:true}),identity:identity(),evidence_fingerprint:'coverage-low-fp'},
    model_calibration:generic('poker-prospective-model-calibration-evidence/v1','INCONCLUSIVE','INSUFFICIENT'),
    strategy_performance:generic('poker-prospective-strategy-performance-evidence/v1','INCONCLUSIVE','INSUFFICIENT')
  }));
  assert.equal(report.sections.population_drift.state,'INSUFFICIENT_SUPPORT');
  assert.equal(report.sections.coverage.state,'INSUFFICIENT_SUPPORT');
  assert.equal(report.sections.model_calibration.state,'INSUFFICIENT_SUPPORT');
  assert.equal(report.sections.strategy_performance.state,'INSUFFICIENT_SUPPORT');
  assert.deepEqual(report.protocol_classification,{
    population_drift:'INCONCLUSIVE',coverage:'INCONCLUSIVE',performance:'INCONCLUSIVE'
  });
}

{
  const one=Prospective.assembleProspectiveReport(input({
    population_drift:{report:driftReport(targetDrifted()),identity:identity()},
    coverage:{report:coverageReport(),identity:identity(),evidence_fingerprint:'coverage-fp'},
    model_calibration:generic('poker-prospective-model-calibration-evidence/v1','WARN','SUFFICIENT',[
      {hand_id:'t-h2',decision_id:'t-d4'},{hand_id:'t-h1',decision_id:'t-d1'}
    ]),
    strategy_performance:generic('poker-prospective-strategy-performance-evidence/v1','FAIL','SUFFICIENT',[
      {hand_id:'t-h2',decision_id:'t-d4'}
    ])
  }));
  const two=Prospective.assembleProspectiveReport(input({
    strategy_performance:generic('poker-prospective-strategy-performance-evidence/v1','FAIL','SUFFICIENT',[
      {hand_id:'t-h2',decision_id:'t-d4'}
    ]),
    model_calibration:generic('poker-prospective-model-calibration-evidence/v1','WARN','SUFFICIENT',[
      {hand_id:'t-h1',decision_id:'t-d1'},{hand_id:'t-h2',decision_id:'t-d4'}
    ]),
    coverage:{report:coverageReport(),identity:identity(),evidence_fingerprint:'coverage-fp'},
    population_drift:{report:driftReport(targetDrifted()),identity:identity()}
  }));
  assert.deepEqual(one,two);
  assert.equal(one.report_id,two.report_id);
  assert.equal(Prospective.exportJSON(one,{pretty:false}),Prospective.exportJSON(two,{pretty:false}));
  assert.deepEqual(one.source_refs,[...one.source_refs].sort((a,b)=>a.hand_id.localeCompare(b.hand_id)||a.decision_id.localeCompare(b.decision_id)));
  assert.equal(one.protocol_classification.performance,'FAIL');
  assert.equal(one.strategic_verdict,null,'even a persisted FAIL result is descriptive here, not a promotion verdict');
}

{
  const bad=input({strategy_performance:generic('poker-prospective-strategy-performance-evidence/v1','PASS')});
  bad.evidence.strategy_performance.identity={...identity(),pack_sha256:F};
  assert.throws(()=>Prospective.assembleProspectiveReport(bad),/identity mismatch: pack_sha256/);
}

{
  const bad=input({population_drift:{report:driftReport(),identity:identity()}});
  bad.prospective_cohort={...bad.prospective_cohort,dataset_fingerprint:'other-dataset'};
  assert.throws(()=>Prospective.assembleProspectiveReport(bad),/target dataset fingerprint mismatch|identity mismatch/);
}

{
  const bad=input();
  bad.protocol_validation={...bad.protocol_validation,status:'FAIL'};
  assert.throws(()=>Prospective.assembleProspectiveReport(bad),/requires PASS validation evidence/);
}

{
  const bad=input();
  bad.protocol={...bad.protocol,rules:{...bad.protocol.rules,no_train_before_closed:false}};
  assert.throws(()=>Prospective.assembleProspectiveReport(bad),/no_train_before_closed must be true/);
}

{
  const bad=input();
  bad.prospective_cohort={...bad.prospective_cohort,split:'TEST'};
  assert.throws(()=>Prospective.assembleProspectiveReport(bad),/TEST cohort consumption is forbidden/);
}

{
  const bad=input();
  bad.prospective_evaluation=true;
  assert.throws(()=>Prospective.assembleProspectiveReport(bad),/real prospective evaluation is forbidden/);
}

{
  const bad=input();
  bad.holdout_manifest={...bad.holdout_manifest,state:'CLOSED'};
  bad.protocol_validation={...bad.protocol_validation,state:'CLOSED'};
  assert.throws(()=>Prospective.assembleProspectiveReport(bad),/must not consume a completed prospective scientific evaluation/);
}

{
  const report=Prospective.assembleProspectiveReport(input({
    population_drift:{report:driftReport(targetDrifted()),identity:identity()},
    coverage:{report:coverageReport(),identity:identity(),evidence_fingerprint:'coverage-fp'}
  }));
  const json=Prospective.exportJSON(report,{pretty:false});
  assert.equal(json.includes('12345.6789'),false,'EV values must not contaminate preparatory report');
  assert.equal(json.includes('"test_consumed":false'),true);
  assert.equal(json.includes('"prospective_evaluation":false'),true);
  assert.equal(json.includes('"promotion_performed":false'),true);
}

console.log(JSON.stringify({
  status:'PASS',
  schema:Prospective.REPORT_SCHEMA,
  section_schema:Prospective.SECTION_SCHEMA,
  states:Prospective.SECTION_STATES
}));
