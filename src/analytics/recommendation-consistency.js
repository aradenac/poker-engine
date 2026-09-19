(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerRecommendationConsistency=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';

  const REPORT_SCHEMA='poker-recommendation-consistency-report/v1';
  const DECISION_SCHEMA='poker-recommendation-consistency-decision/v1';
  const POLICY_SCHEMA='poker-recommendation-consistency-policy/v1';
  const CANONICAL_SCHEMA='poker-preflop-decision/v1';
  const CANONICAL_PROFILE='CANONICAL_RUNTIME_DECISION_V1';
  const SURFACES=['feed','detail','replayer','trainer','review'];
  const VIOLATION_TYPES=[
    'ACTION_EV_MISMATCH','SIZING_EV_MISMATCH','RECOMMENDED_EV_MISMATCH',
    'NON_MAX_EV_RECOMMENDATION','SURFACE_DIVERGENCE','INCREMENTAL_COST_MISMATCH',
    'IDENTITY_MISMATCH','FAIL_CLOSED_RECOMMENDATION_PRESENT','TIE_POLICY_MISMATCH',
    'SELECTED_ALTERNATIVE_MISSING'
  ];
  const DEFAULT_POLICY=Object.freeze({
    schema:POLICY_SCHEMA,
    ev_tolerance_bb:1e-6,
    numeric_tolerance_bb:1e-6,
    within_noise_standard_error_multiplier:2,
    tie_break:'ALTERNATIVE_ID_ASC',
    comparable_only_for_max_ev:true,
    fail_closed_requires_null_recommendation:true
  });
  const ZERO_COST_ACTIONS=new Set(['FOLD','CHECK']);

  function text(v){return v==null?'':String(v).trim();}
  function upper(v){return text(v).toUpperCase();}
  function finiteOrNull(v){if(v==null||v==='')return null;const n=Number(v);return Number.isFinite(n)?n:null;}
  function round(v){return Math.round((Number(v)+Number.EPSILON)*1e9)/1e9;}
  function stableStringify(v){
    if(v===null||typeof v!=='object')return JSON.stringify(v);
    if(Array.isArray(v))return '['+v.map(stableStringify).join(',')+']';
    return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+stableStringify(v[k])).join(',')+'}';
  }
  function hash32(s){let h=2166136261>>>0;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)>>>0;}return h>>>0;}
  function hashId(prefix,v){return prefix+hash32(stableStringify(v)).toString(36);}
  function uniqueSorted(values){return Array.from(new Set((values||[]).filter(v=>v!=null&&String(v)!==''))).sort((a,b)=>String(a).localeCompare(String(b)));}
  function near(a,b,tol){
    if(a==null&&b==null)return true;
    if(a==null||b==null)return false;
    return Math.abs(Number(a)-Number(b))<=tol;
  }
  function normalizePolicy(input={}){
    const p={...DEFAULT_POLICY,...(input||{})};
    for(const k of ['ev_tolerance_bb','numeric_tolerance_bb','within_noise_standard_error_multiplier']){
      const n=Number(p[k]);if(!Number.isFinite(n)||n<0)throw new Error(k+' must be finite and >= 0');p[k]=n;
    }
    if(p.tie_break!=='ALTERNATIVE_ID_ASC')throw new Error('unsupported tie_break');
    p.comparable_only_for_max_ev=p.comparable_only_for_max_ev!==false;
    p.fail_closed_requires_null_recommendation=p.fail_closed_requires_null_recommendation!==false;
    p.schema=POLICY_SCHEMA;
    return p;
  }
  function sourceGuard(source){
    const s=source&&typeof source==='object'?source:{};
    if(upper(s.split)==='TEST')throw new Error('TEST consumption is forbidden');
    if(Number(s.issue)===108)throw new Error('#108 consumption is forbidden');
    if(s.optimization===true)throw new Error('optimization output is forbidden');
    return {split:upper(s.split)||null,issue:s.issue==null?null:Number(s.issue),source:text(s.source)||null};
  }
  function identityOf(d){
    const i=d&&d.identity||{};
    const out={
      population_id:text(i.population_id),
      pack_id:text(i.pack_id)||null,
      pack_version:text(i.pack_version)||null,
      strategy_id:text(i.strategy_id),
      strategy_version:text(i.strategy_version),
      strategy_sha256:text(i.strategy_sha256).toLowerCase()||null,
      decision_source_sha256:text(i.decision_source_sha256).toLowerCase()||null,
      ev_reference:text(i.ev_reference)
    };
    for(const k of ['population_id','strategy_id','strategy_version','ev_reference'])if(!out[k])throw new Error('decision.identity.'+k+' is required');
    return out;
  }
  function identityKey(i){
    return ['population_id','pack_id','pack_version','strategy_id','strategy_version','strategy_sha256','decision_source_sha256','ev_reference']
      .map(k=>k+'='+encodeURIComponent(i[k]==null?'':i[k])).join('|');
  }
  function sameIdentity(a,b){return identityKey(a)===identityKey(b);}
  function sourceRef(d){
    return {hand_id:d.hand_id==null?null:String(d.hand_id),decision_id:String(d.decision_id)};
  }

  function normalizeSizing(v){
    if(v==null)return {target_total_bb:null,bet_to_bb:null};
    if(typeof v==='number')return {target_total_bb:finiteOrNull(v),bet_to_bb:finiteOrNull(v)};
    return {
      target_total_bb:finiteOrNull(v.target_total_bb??v.bet_to_bb),
      bet_to_bb:finiteOrNull(v.bet_to_bb??v.target_total_bb)
    };
  }
  function recommendationTuple(d){
    return {
      action:d.recommended_action==null?null:upper(d.recommended_action),
      sizing:normalizeSizing(d.recommended_target_sizing),
      incremental_cost_bb:finiteOrNull(d.incremental_cost_bb),
      ev_bb:finiteOrNull(d.recommended_ev_bb)
    };
  }
  function alternativeTuple(a){
    return {
      id:String(a.id),
      action:upper(a.action),
      sizing:normalizeSizing(a.target_sizing||a.target_total_bb),
      incremental_cost_bb:finiteOrNull(a.incremental_cost_bb),
      ev_bb:finiteOrNull(a.ev_bb),
      comparable:a.comparable!==false,
      comparability_reason:a.comparable===false?(text(a.comparability_reason)||'NON_COMPARABLE'):null,
      uncertainty:a.uncertainty||null
    };
  }
  function tupleEqual(a,b,p){
    return a.action===b.action&&
      near(a.sizing.target_total_bb,b.sizing.target_total_bb,p.numeric_tolerance_bb)&&
      near(a.sizing.bet_to_bb,b.sizing.bet_to_bb,p.numeric_tolerance_bb)&&
      near(a.incremental_cost_bb,b.incremental_cost_bb,p.numeric_tolerance_bb)&&
      near(a.ev_bb,b.ev_bb,p.ev_tolerance_bb);
  }
  function tupleForSurface(s){
    return {
      decision_id:text(s&&s.decision_id),
      identity:s&&s.identity?identityOf(s):null,
      tuple:recommendationTuple(s||{})
    };
  }
  function selectedId(d){return text(d&&d.recommendation_admissibility&&d.recommendation_admissibility.selected_alternative_id)||null;}
  function seOf(a){
    const v=finiteOrNull(a&&a.uncertainty&&a.uncertainty.monte_carlo&&a.uncertainty.monte_carlo.standard_error_bb);
    return v!=null&&v>=0?v:null;
  }
  function combinedNoise(a,b,multiplier){
    const sa=seOf(a),sb=seOf(b);
    if(sa==null&&sb==null)return null;
    return multiplier*Math.sqrt((sa||0)*(sa||0)+(sb||0)*(sb||0));
  }
  function expectedIncrementalCost(action,target,publicState){
    if(ZERO_COST_ACTIONS.has(action))return target==null?0:null;
    const contrib=finiteOrNull(publicState&&publicState.actor_contribution_bb);
    if(target==null||contrib==null)return null;
    return round(target-contrib);
  }
  function addFinding(arr,type,certainty,message,details={}){
    arr.push({type,certainty,message,details});
  }

  function auditTupleAgainstSelection(tuple,decision,alts,selected,policy,findings,scope){
    if(!selected){
      addFinding(findings,'SELECTED_ALTERNATIVE_MISSING','CERTAIN',scope+': selected alternative is absent',{selected_alternative_id:selectedId(decision)});
      return;
    }
    if(tuple.action!==selected.action){
      addFinding(findings,'ACTION_EV_MISMATCH','CERTAIN',scope+': recommended action does not match selected alternative',{recommended_action:tuple.action,selected_action:selected.action,selected_alternative_id:selected.id});
    }
    if(!near(tuple.sizing.target_total_bb,selected.sizing.target_total_bb,policy.numeric_tolerance_bb)||
       !near(tuple.sizing.bet_to_bb,selected.sizing.bet_to_bb,policy.numeric_tolerance_bb)){
      addFinding(findings,'SIZING_EV_MISMATCH','CERTAIN',scope+': recommended sizing does not match selected alternative',{recommended_sizing:tuple.sizing,selected_sizing:selected.sizing,selected_alternative_id:selected.id});
    }
    if(!near(tuple.ev_bb,selected.ev_bb,policy.ev_tolerance_bb)){
      addFinding(findings,'RECOMMENDED_EV_MISMATCH','CERTAIN',scope+': recommended EV does not match selected alternative',{recommended_ev_bb:tuple.ev_bb,selected_ev_bb:selected.ev_bb,selected_alternative_id:selected.id});
    }
    if(!near(tuple.incremental_cost_bb,selected.incremental_cost_bb,policy.numeric_tolerance_bb)){
      addFinding(findings,'INCREMENTAL_COST_MISMATCH','CERTAIN',scope+': top-level incremental cost does not match selected alternative',{recommended_incremental_cost_bb:tuple.incremental_cost_bb,selected_incremental_cost_bb:selected.incremental_cost_bb,selected_alternative_id:selected.id});
    }
    const expected=expectedIncrementalCost(tuple.action,tuple.sizing.target_total_bb,decision.public_state);
    if(expected==null||!near(tuple.incremental_cost_bb,expected,policy.numeric_tolerance_bb)){
      addFinding(findings,'INCREMENTAL_COST_MISMATCH','CERTAIN',scope+': incremental cost is not coherent with action+sizing+public state',{action:tuple.action,target_total_bb:tuple.sizing.target_total_bb,actor_contribution_bb:decision.public_state&&decision.public_state.actor_contribution_bb,expected_incremental_cost_bb:expected,actual_incremental_cost_bb:tuple.incremental_cost_bb});
    }
    if(!near(tuple.sizing.target_total_bb,tuple.sizing.bet_to_bb,policy.numeric_tolerance_bb)){
      addFinding(findings,'SIZING_EV_MISMATCH','CERTAIN',scope+': target_total_bb and bet_to_bb diverge',{recommended_sizing:tuple.sizing});
    }

    const comparable=alts.filter(a=>a.comparable&&a.ev_bb!=null);
    if(!selected.comparable){
      addFinding(findings,'NON_MAX_EV_RECOMMENDATION','NOT_COMPARABLE',scope+': selected alternative is not comparable',{selected_alternative_id:selected.id,reason:selected.comparability_reason});
      return;
    }
    if(!comparable.length)return;
    const bestEV=Math.max(...comparable.map(a=>a.ev_bb));
    const best=comparable.filter(a=>bestEV-a.ev_bb<=policy.ev_tolerance_bb).sort((a,b)=>a.id.localeCompare(b.id));
    const deterministicBest=best[0];
    const gap=bestEV-selected.ev_bb;
    if(gap>policy.ev_tolerance_bb){
      const bestAlt=comparable.slice().sort((a,b)=>b.ev_bb-a.ev_bb||a.id.localeCompare(b.id))[0];
      const noise=combinedNoise(selected,bestAlt,policy.within_noise_standard_error_multiplier);
      const certainty=noise!=null&&gap<=noise+policy.ev_tolerance_bb?'WITHIN_NOISE':'CERTAIN';
      addFinding(findings,'NON_MAX_EV_RECOMMENDATION',certainty,scope+': selected alternative is below a higher comparable EV',{selected_alternative_id:selected.id,selected_ev_bb:selected.ev_bb,best_alternative_id:bestAlt.id,best_ev_bb:bestAlt.ev_bb,ev_gap_bb:round(gap),noise_tolerance_bb:noise==null?null:round(noise)});
    }else if(best.length>1&&selected.id!==deterministicBest.id){
      addFinding(findings,'TIE_POLICY_MISMATCH','CERTAIN',scope+': selected alternative violates deterministic tie-break',{selected_alternative_id:selected.id,expected_alternative_id:deterministicBest.id,tied_alternative_ids:best.map(a=>a.id),tie_break:policy.tie_break});
    }
  }

  function surfaceAudit(decision,surfaces,canonicalTuple,alts,policy,findings){
    const evaluated={};
    const present=[];
    for(const name of SURFACES){
      const s=surfaces&&surfaces[name];
      if(!s){evaluated[name]={present:false};continue;}
      sourceGuard(s.source||{});
      const n=tupleForSurface(s);
      present.push(name);
      const local=[];
      if(n.decision_id!==String(decision.decision_id)){
        addFinding(local,'SURFACE_DIVERGENCE','CERTAIN',name+': decision_id diverges',{expected_decision_id:String(decision.decision_id),actual_decision_id:n.decision_id});
      }
      if(!n.identity||!sameIdentity(n.identity,identityOf(decision))){
        addFinding(local,'IDENTITY_MISMATCH','CERTAIN',name+': identity diverges',{expected_identity:identityOf(decision),actual_identity:n.identity});
      }
      if(!tupleEqual(n.tuple,canonicalTuple,policy)){
        addFinding(local,'SURFACE_DIVERGENCE','CERTAIN',name+': recommendation tuple diverges',{expected:canonicalTuple,actual:n.tuple});
      }
      const matched=alts.filter(a=>a.action===n.tuple.action&&near(a.sizing.target_total_bb,n.tuple.sizing.target_total_bb,policy.numeric_tolerance_bb));
      if(matched.length===1){
        auditTupleAgainstSelection(n.tuple,decision,alts,matched[0],policy,local,'surface '+name);
      }
      findings.push(...local);
      evaluated[name]={present:true,decision_id:n.decision_id,tuple:n.tuple,violations:local.map(x=>x.type)};
    }
    return {
      required_surfaces:[...SURFACES],
      present_surfaces:present,
      complete:present.length===SURFACES.length,
      surfaces:evaluated
    };
  }

  function auditDecision(record={},policyInput={}){
    const policy=normalizePolicy(policyInput);
    const decision=record.decision||record;
    sourceGuard(record.source||decision.source||{});
    if(!decision||decision.schema!==CANONICAL_SCHEMA||decision.contract_profile!==CANONICAL_PROFILE)throw new Error('expected canonical runtime '+CANONICAL_SCHEMA);
    if(!text(decision.decision_id))throw new Error('decision_id is required');
    const identity=identityOf(decision);
    const alts=(Array.isArray(decision.alternatives)?decision.alternatives:[]).map(alternativeTuple);
    const findings=[];
    const admissible=Boolean(decision.recommendation_admissibility&&decision.recommendation_admissibility.admissible);
    const tuple=recommendationTuple(decision);
    const selId=selectedId(decision);
    const selected=selId?alts.find(a=>a.id===selId)||null:null;

    if(!admissible){
      const present=tuple.action!=null||tuple.sizing.target_total_bb!=null||tuple.sizing.bet_to_bb!=null||tuple.incremental_cost_bb!=null||tuple.ev_bb!=null||alts.length>0;
      if(policy.fail_closed_requires_null_recommendation&&present){
        addFinding(findings,'FAIL_CLOSED_RECOMMENDATION_PRESENT','CERTAIN','fail-closed decision exposes recommendation evidence',{tuple,alternative_count:alts.length,status:decision.recommendation_admissibility&&decision.recommendation_admissibility.status});
      }
    }else{
      auditTupleAgainstSelection(tuple,decision,alts,selected,policy,findings,'canonical decision');
    }

    const surfaces=surfaceAudit(decision,record.surfaces||null,tuple,alts,policy,findings);
    const unique=[];
    const seen=new Set();
    for(const f of findings){
      const k=stableStringify(f);
      if(!seen.has(k)){seen.add(k);unique.push(f);}
    }
    unique.sort((a,b)=>a.type.localeCompare(b.type)||a.certainty.localeCompare(b.certainty)||a.message.localeCompare(b.message)||stableStringify(a.details).localeCompare(stableStringify(b.details)));
    const certain=unique.filter(x=>x.certainty==='CERTAIN');
    const within=unique.filter(x=>x.certainty==='WITHIN_NOISE');
    const noncomp=unique.filter(x=>x.certainty==='NOT_COMPARABLE');
    const status=certain.length?'FAIL':((within.length||noncomp.length||!surfaces.complete)?'INCONCLUSIVE':'PASS');
    return {
      schema:DECISION_SCHEMA,
      decision_id:String(decision.decision_id),
      hand_id:decision.hand_id==null?null:String(decision.hand_id),
      status,
      street:upper(decision.street)||'UNKNOWN',
      spot_family:upper(decision.facing_context)||'UNKNOWN',
      context_id:text(decision.context_id)||null,
      identity,
      recommendation_admissible:admissible,
      recommendation_tuple:tuple,
      selected_alternative_id:selId,
      tie_policy:{tie_break:policy.tie_break,ev_tolerance_bb:policy.ev_tolerance_bb,within_noise_standard_error_multiplier:policy.within_noise_standard_error_multiplier},
      surface_parity:surfaces,
      violations:unique,
      counts:{certain:certain.length,within_noise:within.length,not_comparable:noncomp.length},
      source_refs:[sourceRef(decision)],
      semantics:{validation_only:true,strategy_mutated:false,promotion_performed:false,optimization_performed:false}
    };
  }

  function aggregate(rows,keyFn){
    const m=new Map();
    for(const row of rows){
      for(const v of row.violations){
        if(v.certainty!=='CERTAIN')continue;
        const key=keyFn(row,v);
        if(!m.has(key))m.set(key,{key,count:0,decision_ids:new Set(),source_refs:[]});
        const x=m.get(key);x.count++;x.decision_ids.add(row.decision_id);x.source_refs.push(...row.source_refs);
      }
    }
    return Array.from(m.values()).map(x=>({
      key:x.key,count:x.count,decision_count:x.decision_ids.size,
      source_refs:normalizeRefs(x.source_refs)
    })).sort((a,b)=>b.count-a.count||b.decision_count-a.decision_count||a.key.localeCompare(b.key));
  }
  function normalizeRefs(values){
    const m=new Map();
    for(const r of values||[]){
      if(!r||r.decision_id==null)continue;
      const x={hand_id:r.hand_id==null?null:String(r.hand_id),decision_id:String(r.decision_id)};
      m.set((x.hand_id||'')+'\u0000'+x.decision_id,x);
    }
    return Array.from(m.values()).sort((a,b)=>(a.hand_id||'').localeCompare(b.hand_id||'')||a.decision_id.localeCompare(b.decision_id));
  }

  function analyzeConsistency(input={}){
    const policy=normalizePolicy(input.policy||{});
    const records=Array.isArray(input.records)?input.records:[];
    const rows=records.map(r=>auditDecision(r,policy));
    rows.sort((a,b)=>(a.hand_id||'').localeCompare(b.hand_id||'')||a.decision_id.localeCompare(b.decision_id));
    const identities=new Map();for(const r of rows)identities.set(identityKey(r.identity),r.identity);
    if(identities.size>1){
      for(const row of rows)addFinding(row.violations,'IDENTITY_MISMATCH','CERTAIN','report spans multiple exact identities',{});
      for(const row of rows){row.status='FAIL';row.counts.certain=row.violations.filter(x=>x.certainty==='CERTAIN').length;}
    }
    const report={
      schema:REPORT_SCHEMA,
      policy_schema:POLICY_SCHEMA,
      policy,
      identity:identities.size===1?Array.from(identities.values())[0]:null,
      summary:{
        decision_count:rows.length,
        pass_count:rows.filter(r=>r.status==='PASS').length,
        fail_count:rows.filter(r=>r.status==='FAIL').length,
        inconclusive_count:rows.filter(r=>r.status==='INCONCLUSIVE').length,
        certain_violation_count:rows.reduce((s,r)=>s+r.counts.certain,0),
        within_noise_count:rows.reduce((s,r)=>s+r.counts.within_noise,0),
        not_comparable_count:rows.reduce((s,r)=>s+r.counts.not_comparable,0)
      },
      decisions:rows,
      violations:{
        by_type:aggregate(rows,(r,v)=>v.type),
        by_street:aggregate(rows,(r)=>r.street),
        by_spot_family:aggregate(rows,(r)=>r.spot_family),
        by_context:aggregate(rows,(r)=>r.context_id||'NO_CONTEXT')
      },
      source_refs:normalizeRefs(rows.flatMap(r=>r.source_refs)),
      semantics:{
        validation_only:true,
        scientific_effect:'NONE_VALIDATION_ONLY',
        test_consumed:false,
        issue_108_consumed:false,
        optimization_performed:false,
        promotion_performed:false,
        strategy_mutated:false,
        central_ui_modified:false
      }
    };
    report.report_hash=hashId('recommendation-consistency:',report);
    return report;
  }

  function exportJSON(report,options={}){
    if(!report||report.schema!==REPORT_SCHEMA)throw new Error('expected '+REPORT_SCHEMA);
    return JSON.stringify(report,null,options.pretty===false?0:2);
  }

  return {
    REPORT_SCHEMA,DECISION_SCHEMA,POLICY_SCHEMA,CANONICAL_SCHEMA,CANONICAL_PROFILE,
    SURFACES,VIOLATION_TYPES,DEFAULT_POLICY,normalizePolicy,auditDecision,analyzeConsistency,exportJSON
  };
});
