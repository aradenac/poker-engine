(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerProspectiveReport=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';

  const REPORT_SCHEMA='poker-prospective-analytics-report/v1';
  const SECTION_SCHEMA='poker-prospective-analytics-section/v1';
  const PROTOCOL_SCHEMA='poker-prospective-holdout-protocol/v1';
  const MANIFEST_SCHEMA='poker-prospective-holdout/v1';
  const VALIDATION_SCHEMA='poker-prospective-holdout-report/v1';
  const DRIFT_SCHEMA='poker-population-drift/v1';
  const COVERAGE_SCHEMA='poker-analysis-coverage/v1';
  const MODEL_EVIDENCE_SCHEMA='poker-prospective-model-calibration-evidence/v1';
  const PERFORMANCE_EVIDENCE_SCHEMA='poker-prospective-strategy-performance-evidence/v1';
  const SECTION_STATES=[
    'NOT_EVALUATED','INSUFFICIENT_SUPPORT','DRIFT','NO_DRIFT',
    'COVERAGE_GAP','COVERED','PERFORMANCE_RESULT'
  ];
  const PROTOCOL_CLASSIFICATIONS=['PASS','WARN','FAIL','INCONCLUSIVE','NOT_EVALUATED'];
  const REQUIRED_PROTOCOL_RULES=[
    'candidate_frozen_before_admission',
    'candidate_fit_identity_frozen',
    'prospective_hands_must_be_absent_from_candidate_fit',
    'append_only_hands_while_unconsumed',
    'ledger_frozen_during_evaluation',
    'no_train_before_closed',
    'thresholds_frozen_before_admission',
    'future_train_requires_new_cycle',
    'separate_drift_coverage_performance_report',
    'test_or_validation_split_is_not_reused_as_prospective_holdout'
  ];

  function text(v){return v==null?'':String(v).trim();}
  function upper(v){return text(v).toUpperCase();}
  function clone(v){return v==null?v:JSON.parse(JSON.stringify(v));}
  function required(v,name){const s=text(v);if(!s)throw new Error(name+' is required');return s;}
  function stableStringify(v){
    if(v===null||typeof v!=='object')return JSON.stringify(v);
    if(Array.isArray(v))return '['+v.map(stableStringify).join(',')+']';
    return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+stableStringify(v[k])).join(',')+'}';
  }
  function hash32(s){let h=2166136261>>>0;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)>>>0;}return h>>>0;}
  function hashId(prefix,v){return prefix+hash32(stableStringify(v)).toString(36);}
  function uniqueSorted(values){return Array.from(new Set((values||[]).filter(v=>v!=null&&String(v)!==''))).sort((a,b)=>String(a).localeCompare(String(b)));}
  function normalizeRefs(values){
    const map=new Map();
    for(const r of values||[]){
      if(!r||r.hand_id==null||r.decision_id==null)continue;
      const x={hand_id:String(r.hand_id),decision_id:String(r.decision_id)};
      map.set(x.hand_id+'\u0000'+x.decision_id,x);
    }
    return Array.from(map.values()).sort((a,b)=>a.hand_id.localeCompare(b.hand_id)||a.decision_id.localeCompare(b.decision_id));
  }
  function refsFromDrift(report){
    const out=[];
    for(const cell of report&&report.cells||[]){
      out.push(...(cell.baseline&&cell.baseline.source_refs||[]),...(cell.target&&cell.target.source_refs||[]));
    }
    return normalizeRefs(out);
  }
  function refsFromCoverage(report){
    const out=[];
    for(const row of report&&report.rows||[])out.push(...(row.source_refs||[]));
    return normalizeRefs(out);
  }

  function validateProtocol(protocol){
    if(!protocol||protocol.schema!==PROTOCOL_SCHEMA)throw new Error('expected '+PROTOCOL_SCHEMA);
    if(protocol.manifest_schema!==MANIFEST_SCHEMA)throw new Error('protocol manifest_schema mismatch');
    if(!protocol.rules||typeof protocol.rules!=='object')throw new Error('protocol.rules is required');
    for(const name of REQUIRED_PROTOCOL_RULES)if(protocol.rules[name]!==true)throw new Error('protocol.rules.'+name+' must be true');
    if(!protocol.scope||protocol.scope.no_scientific_execution!==true)throw new Error('preparatory analytics requires protocol no_scientific_execution=true');
    return true;
  }

  function validateManifestBinding(manifest,validation){
    if(!manifest||manifest.schema!==MANIFEST_SCHEMA)throw new Error('expected '+MANIFEST_SCHEMA);
    if(upper(manifest.state)==='RELEASED_TO_FUTURE_TRAIN')throw new Error('preparatory analytics must not consume released prospective hands');
    if(!validation||validation.schema!==VALIDATION_SCHEMA||validation.status!=='PASS')throw new Error('prospective manifest requires PASS validation evidence');
    if(text(validation.holdout_id)!==text(manifest.holdout_id))throw new Error('protocol validation holdout_id mismatch');
    if(text(validation.state)!==text(manifest.state))throw new Error('protocol validation state mismatch');
    const handCount=Array.isArray(manifest.hands)?manifest.hands.length:0;
    if(Number(validation.hand_count)!==handCount)throw new Error('protocol validation hand_count mismatch');
    if(!text(validation.manifest_sha256))throw new Error('protocol validation manifest_sha256 is required');
    if(upper(manifest.state)==='CLOSED')throw new Error('preparatory analytics must not consume a completed prospective scientific evaluation');
    return {hand_count:handCount,manifest_sha256:text(validation.manifest_sha256)};
  }

  function candidateIdentity(manifest){
    const p=manifest.precommit||{},c=p.candidate||{};
    return {
      population_id:required(manifest.population_id,'manifest.population_id'),
      candidate_id:required(c.id,'manifest.precommit.candidate.id'),
      candidate_artifact_sha256:required(c.artifact_sha256,'manifest.precommit.candidate.artifact_sha256'),
      pack_sha256:required(c.pack_sha256,'manifest.precommit.candidate.pack_sha256'),
      strategy_sha256:required(p.strategy_sha256,'manifest.precommit.strategy_sha256'),
      models:Object.fromEntries(Object.entries(p.models||{}).sort((a,b)=>a[0].localeCompare(b[0]))),
      metrics_sha256:required(p.metrics_sha256,'manifest.precommit.metrics_sha256'),
      thresholds_sha256:required(p.thresholds_sha256,'manifest.precommit.thresholds_sha256'),
      protocol_sha256:required(p.protocol_sha256,'manifest.precommit.protocol_sha256'),
      source_commit_sha:required(p.source_commit_sha,'manifest.precommit.source_commit_sha'),
      frozen_at:required(p.frozen_at,'manifest.precommit.frozen_at')
    };
  }
  function cohortIdentity(input,manifest,binding){
    const cohort=input||{};
    const id={
      holdout_id:required(cohort.holdout_id,'prospective_cohort.holdout_id'),
      generation:Number(cohort.generation),
      population_id:required(cohort.population_id,'prospective_cohort.population_id'),
      manifest_sha256:required(cohort.manifest_sha256,'prospective_cohort.manifest_sha256'),
      dataset_fingerprint:required(cohort.dataset_fingerprint,'prospective_cohort.dataset_fingerprint'),
      source_fingerprint:required(cohort.source_fingerprint,'prospective_cohort.source_fingerprint'),
      hand_count:Number(cohort.hand_count),
      decision_count:Number(cohort.decision_count)
    };
    if(!Number.isInteger(id.generation)||id.generation<1)throw new Error('prospective_cohort.generation must be >= 1');
    if(!Number.isInteger(id.hand_count)||id.hand_count<0)throw new Error('prospective_cohort.hand_count must be >= 0');
    if(!Number.isInteger(id.decision_count)||id.decision_count<0)throw new Error('prospective_cohort.decision_count must be >= 0');
    if(id.holdout_id!==text(manifest.holdout_id))throw new Error('prospective cohort holdout_id mismatch');
    if(id.generation!==Number(manifest.generation))throw new Error('prospective cohort generation mismatch');
    if(id.population_id!==text(manifest.population_id))throw new Error('prospective cohort population mismatch');
    if(id.manifest_sha256!==binding.manifest_sha256)throw new Error('prospective cohort manifest fingerprint mismatch');
    if(id.hand_count!==binding.hand_count)throw new Error('prospective cohort hand_count mismatch');
    return id;
  }
  function evidenceIdentityExpected(candidate,cohort){
    return {
      population_id:candidate.population_id,
      candidate_id:candidate.candidate_id,
      candidate_artifact_sha256:candidate.candidate_artifact_sha256,
      pack_sha256:candidate.pack_sha256,
      strategy_sha256:candidate.strategy_sha256,
      cohort_manifest_sha256:cohort.manifest_sha256,
      cohort_dataset_fingerprint:cohort.dataset_fingerprint,
      cohort_source_fingerprint:cohort.source_fingerprint,
      metrics_sha256:candidate.metrics_sha256,
      thresholds_sha256:candidate.thresholds_sha256
    };
  }
  function assertEvidenceIdentity(identity,expected,label){
    if(!identity||typeof identity!=='object')throw new Error(label+' identity is required');
    for(const [key,value] of Object.entries(expected)){
      if(text(identity[key])!==text(value))throw new Error(label+' identity mismatch: '+key);
    }
  }

  function section(name,state,classification,evidenceSchema,summary,sourceRefs,reasonCodes,evidenceFingerprint){
    if(!SECTION_STATES.includes(state))throw new Error('unsupported section state '+state);
    if(!PROTOCOL_CLASSIFICATIONS.includes(classification))throw new Error('unsupported protocol classification '+classification);
    return {
      schema:SECTION_SCHEMA,
      name,
      state,
      protocol_classification:classification,
      evidence_schema:evidenceSchema||null,
      evidence_fingerprint:evidenceFingerprint||null,
      summary:summary==null?null:clone(summary),
      source_refs:normalizeRefs(sourceRefs),
      reason_codes:uniqueSorted(reasonCodes),
      semantics:{descriptive_only:true,strategic_verdict:null}
    };
  }
  function notEvaluated(name,reason){
    return section(name,'NOT_EVALUATED','NOT_EVALUATED',null,null,[],[reason||'NO_EVIDENCE'],null);
  }

  function populationDriftSection(evidence,expected,cohort){
    if(!evidence)return notEvaluated('population_drift','POPULATION_DRIFT_NOT_EVALUATED');
    const report=evidence.report;
    if(!report||report.schema!==DRIFT_SCHEMA)throw new Error('population_drift evidence must contain '+DRIFT_SCHEMA);
    assertEvidenceIdentity(evidence.identity,expected,'population_drift');
    if(text(report.population_id)!==expected.population_id)throw new Error('population_drift report population mismatch');
    if(text(report.target_cohort&&report.target_cohort.dataset_fingerprint)!==cohort.dataset_fingerprint)throw new Error('population_drift target dataset fingerprint mismatch');
    if(text(report.target_cohort&&report.target_cohort.source_fingerprint)!==cohort.source_fingerprint)throw new Error('population_drift target source fingerprint mismatch');
    const state=upper(report.state);
    if(state==='DRIFTED')return section('population_drift','DRIFT','WARN',DRIFT_SCHEMA,report.summary,refsFromDrift(report),['POPULATION_DRIFT_DETECTED'],report.report_hash);
    if(state==='LOW_SUPPORT')return section('population_drift','INSUFFICIENT_SUPPORT','INCONCLUSIVE',DRIFT_SCHEMA,report.summary,refsFromDrift(report),['POPULATION_DRIFT_LOW_SUPPORT'],report.report_hash);
    if(state==='STABLE')return section('population_drift','NO_DRIFT','PASS',DRIFT_SCHEMA,report.summary,refsFromDrift(report),[],report.report_hash);
    if(state==='NOT_COMPARABLE')return section('population_drift','NOT_EVALUATED','INCONCLUSIVE',DRIFT_SCHEMA,report.summary,refsFromDrift(report),['POPULATION_DRIFT_NOT_COMPARABLE'],report.report_hash);
    throw new Error('unsupported population drift state '+state);
  }

  function coverageSection(evidence,expected){
    if(!evidence)return notEvaluated('coverage','COVERAGE_NOT_EVALUATED');
    const report=evidence.report;
    if(!report||report.schema!==COVERAGE_SCHEMA)throw new Error('coverage evidence must contain '+COVERAGE_SCHEMA);
    assertEvidenceIdentity(evidence.identity,expected,'coverage');
    if(text(report.scope&&report.scope.population_id)!==expected.population_id)throw new Error('coverage report population mismatch');
    const s=report.summary||{};
    const summary={
      hand_count:Number(s.hand_count||0),
      decision_count:Number(s.decision_count||0),
      comparable_count:Number(s.comparable_count||0),
      supported_count:Number(s.supported_count||0),
      low_support_count:Number(s.low_support_count||0),
      unsupported_count:Number(s.unsupported_count||0),
      non_comparable_count:Number(s.non_comparable_count||0),
      analysis_missing_rows:Number(s.analysis_missing_rows||0),
      coverage_ratio:s.coverage_ratio==null?null:Number(s.coverage_ratio)
    };
    const sourceRefs=refsFromCoverage(report);
    if(summary.decision_count===0)return section('coverage','NOT_EVALUATED','NOT_EVALUATED',COVERAGE_SCHEMA,summary,sourceRefs,['NO_ANALYZED_DECISIONS'],evidence.evidence_fingerprint);
    if(summary.analysis_missing_rows>0||summary.unsupported_count>0)return section('coverage','COVERAGE_GAP','WARN',COVERAGE_SCHEMA,summary,sourceRefs,['COVERAGE_GAP_PRESENT'],evidence.evidence_fingerprint);
    if(summary.low_support_count>0)return section('coverage','INSUFFICIENT_SUPPORT','INCONCLUSIVE',COVERAGE_SCHEMA,summary,sourceRefs,['COVERAGE_LOW_SUPPORT'],evidence.evidence_fingerprint);
    return section('coverage','COVERED','PASS',COVERAGE_SCHEMA,summary,sourceRefs,[],evidence.evidence_fingerprint);
  }

  function genericResultSection(name,evidence,expected,schema){
    if(!evidence)return notEvaluated(name,name.toUpperCase()+'_NOT_EVALUATED');
    if(evidence.schema!==schema)throw new Error(name+' evidence schema mismatch');
    assertEvidenceIdentity(evidence.identity,expected,name);
    const classification=upper(evidence.classification);
    if(!PROTOCOL_CLASSIFICATIONS.includes(classification))throw new Error(name+' classification is invalid');
    const support=upper(evidence.support_state||'SUFFICIENT');
    if(classification==='NOT_EVALUATED')return section(name,'NOT_EVALUATED','NOT_EVALUATED',schema,evidence.summary,evidence.source_refs,[name.toUpperCase()+'_NOT_EVALUATED'],evidence.evidence_fingerprint);
    if(support==='INSUFFICIENT'||classification==='INCONCLUSIVE')return section(name,'INSUFFICIENT_SUPPORT','INCONCLUSIVE',schema,evidence.summary,evidence.source_refs,[name.toUpperCase()+'_INSUFFICIENT_SUPPORT'],evidence.evidence_fingerprint);
    return section(name,'PERFORMANCE_RESULT',classification,schema,evidence.summary,evidence.source_refs,evidence.reason_codes||[],evidence.evidence_fingerprint);
  }

  function aggregateSourceRefs(sections){
    const out=[];for(const s of Object.values(sections))out.push(...s.source_refs);
    return normalizeRefs(out);
  }

  function assembleProspectiveReport(input={}){
    validateProtocol(input.protocol);
    const binding=validateManifestBinding(input.holdout_manifest,input.protocol_validation);
    const candidate=candidateIdentity(input.holdout_manifest);
    const cohort=cohortIdentity(input.prospective_cohort,input.holdout_manifest,binding);
    if(upper(input.prospective_cohort&&input.prospective_cohort.split)==='TEST')throw new Error('TEST cohort consumption is forbidden');
    if(input.prospective_evaluation===true)throw new Error('real prospective evaluation is forbidden in preparatory analytics');
    const expected=evidenceIdentityExpected(candidate,cohort);
    const ev=input.evidence||{};
    const sections={
      population_drift:populationDriftSection(ev.population_drift||null,expected,cohort),
      coverage:coverageSection(ev.coverage||null,expected),
      model_calibration:genericResultSection('model_calibration',ev.model_calibration||null,expected,MODEL_EVIDENCE_SCHEMA),
      strategy_performance:genericResultSection('strategy_performance',ev.strategy_performance||null,expected,PERFORMANCE_EVIDENCE_SCHEMA)
    };
    const protocolClassification={
      population_drift:sections.population_drift.protocol_classification,
      coverage:sections.coverage.protocol_classification,
      performance:sections.strategy_performance.protocol_classification
    };
    const report={
      schema:REPORT_SCHEMA,
      protocol_schema:PROTOCOL_SCHEMA,
      holdout_schema:MANIFEST_SCHEMA,
      holdout_id:text(input.holdout_manifest.holdout_id),
      generation:Number(input.holdout_manifest.generation),
      holdout_state:text(input.holdout_manifest.state),
      population_id:candidate.population_id,
      candidate_identity:candidate,
      prospective_cohort:{...cohort,split:upper(input.prospective_cohort.split||'SYNTHETIC')},
      protocol_validation:{
        schema:VALIDATION_SCHEMA,
        status:'PASS',
        manifest_sha256:binding.manifest_sha256,
        hand_count:binding.hand_count
      },
      sections,
      protocol_classification:protocolClassification,
      source_refs:aggregateSourceRefs(sections),
      strategic_verdict:null,
      semantics:{
        descriptive_only:true,
        test_consumed:false,
        prospective_evaluation:false,
        thresholds_modified:false,
        promotion_performed:false,
        strategy_modified:false,
        model_pointer_modified:false
      }
    };
    report.report_id=hashId('prospective-analytics:',report);
    return report;
  }

  function exportJSON(report,options={}){
    if(!report||report.schema!==REPORT_SCHEMA)throw new Error('expected '+REPORT_SCHEMA);
    return JSON.stringify(report,null,options.pretty===false?0:2);
  }
  function humanSummary(report){
    if(!report||report.schema!==REPORT_SCHEMA)throw new Error('expected '+REPORT_SCHEMA);
    const s=report.sections;
    return [
      'Prospective analytics preparation for '+report.holdout_id+' (generation '+report.generation+').',
      'Population drift: '+s.population_drift.state+'.',
      'Coverage: '+s.coverage.state+'.',
      'Model calibration: '+s.model_calibration.state+'.',
      'Strategy/performance: '+s.strategy_performance.state+'.',
      'No strategic verdict or prospective scientific evaluation was produced.'
    ].join(' ');
  }

  return {
    REPORT_SCHEMA,SECTION_SCHEMA,PROTOCOL_SCHEMA,MANIFEST_SCHEMA,VALIDATION_SCHEMA,
    DRIFT_SCHEMA,COVERAGE_SCHEMA,MODEL_EVIDENCE_SCHEMA,PERFORMANCE_EVIDENCE_SCHEMA,
    SECTION_STATES,PROTOCOL_CLASSIFICATIONS,assembleProspectiveReport,exportJSON,humanSummary
  };
});
