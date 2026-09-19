(function(root,factory){
  const Leak=(typeof module==='object'&&module.exports)?require('./leak-analyzer.js'):(root&&root.PokerLeakAnalyzer);
  const Adapter=(typeof module==='object'&&module.exports)?require('./review-score-adapter.js'):(root&&root.PokerReviewLeakAdapter);
  const api=factory(Leak,Adapter);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerAnalysisCoverage=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(Leak,Adapter){
  'use strict';

  const COVERAGE_SCHEMA='poker-analysis-coverage/v1';
  const ROW_SCHEMA='poker-analysis-coverage-row/v1';
  const PREFLOP_EVIDENCE_SCHEMA='poker-analysis-preflop-train-evidence/v1';
  const STATES=['COVERED','LOW_SUPPORT','UNSUPPORTED','NON_COMPARABLE','ANALYSIS_MISSING'];
  const DIMENSIONS=['position','street','spot_family','action_context','sizing_context','jam','overbet','preflop_family','preflop_context'];
  const SCOPE_FIELDS=['population_id','pack_id','pack_version','strategy_id','strategy_version','ev_reference'];
  const TIER_ORDER={UNKNOWN:0,SPARSE:1,LOW:2,MEDIUM:3,HIGH:4,VERY_HIGH:5};
  const GAP_STATE_ORDER={ANALYSIS_MISSING:0,UNSUPPORTED:1,NON_COMPARABLE:2,LOW_SUPPORT:3,COVERED:4};
  const EPS=1e-9;

  function text(v){return v==null?'':String(v).trim();}
  function upper(v){return text(v).toUpperCase();}
  function round(v){return Math.round((Number(v)+Number.EPSILON)*1e9)/1e9;}
  function stableStringify(v){
    if(v===null||typeof v!=='object')return JSON.stringify(v);
    if(Array.isArray(v))return '['+v.map(stableStringify).join(',')+']';
    return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+stableStringify(v[k])).join(',')+'}';
  }
  function hash(s){let h=2166136261>>>0;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)>>>0;}return h.toString(36);}
  function requiredText(v,name){const s=text(v);if(!s)throw new Error(name+' is required');return s;}
  function nonNegativeInt(v,name,def=0){
    if(v==null||v==='')return def;
    const n=Number(v);if(!Number.isInteger(n)||n<0)throw new Error(name+' must be a non-negative integer');return n;
  }
  function asFinite(v){const n=Number(v);return Number.isFinite(n)?n:null;}
  function uniqueSorted(values){return Array.from(new Set(values.filter(v=>v!=null&&String(v)!==''))).sort((a,b)=>String(a).localeCompare(String(b)));}

  function exactScope(input={}){
    return {
      population_id:requiredText(input.population_id,'scope.population_id'),
      pack_id:text(input.pack_id)||null,
      pack_version:text(input.pack_version)||null,
      strategy_id:requiredText(input.strategy_id,'scope.strategy_id'),
      strategy_version:requiredText(input.strategy_version,'scope.strategy_version'),
      ev_reference:requiredText(input.ev_reference,'scope.ev_reference')
    };
  }
  function scopeFrom(raw,normalized){
    return exactScope({
      population_id:normalized.population_id,
      pack_id:normalized.pack_id,
      pack_version:raw&&((raw.pack&&raw.pack.version)||raw.pack_version)||null,
      strategy_id:normalized.strategy_id,
      strategy_version:normalized.strategy_version,
      ev_reference:normalized.ev_reference
    });
  }
  function scopeKey(scope){return SCOPE_FIELDS.map(k=>k+'='+encodeURIComponent(scope[k]==null?'':scope[k])).join('|');}
  function sameScope(a,b){return SCOPE_FIELDS.every(k=>String(a[k]==null?'':a[k])===String(b[k]==null?'':b[k]));}
  function assertSameScope(expected,actual,label='scope'){
    if(!sameScope(expected,actual))throw new Error(label+' mismatch: expected '+scopeKey(expected)+' got '+scopeKey(actual));
  }

  function observationsOf(e){
    const n=e&&e.support?Number(e.support.observations):NaN;
    return Number.isInteger(n)&&n>=0?n:null;
  }
  function observationTier(n){
    if(n==null)return 'UNKNOWN';
    if(n>=1000)return 'VERY_HIGH';
    if(n>=100)return 'HIGH';
    if(n>=20)return 'MEDIUM';
    if(n>=1)return 'LOW';
    return 'SPARSE';
  }
  function normalizeTier(v){const s=upper(v)||'UNKNOWN';return Object.prototype.hasOwnProperty.call(TIER_ORDER,s)?s:'UNKNOWN';}
  function minTier(values){
    const rows=values.map(normalizeTier).filter(Boolean);
    if(!rows.length)return 'UNKNOWN';
    return rows.sort((a,b)=>TIER_ORDER[a]-TIER_ORDER[b]||a.localeCompare(b))[0];
  }
  function eventClass(e,minimumObservations){
    if(!e.support.covered){
      return {state:'UNSUPPORTED',tier:'UNKNOWN',reason:'UNSUPPORTED:'+(e.support.reason||'UNSUPPORTED')};
    }
    if(!e.comparability.comparable){
      return {state:'NON_COMPARABLE',tier:observationTier(observationsOf(e)),reason:'NON_COMPARABLE:'+(e.comparability.reason||'NON_COMPARABLE')};
    }
    const obs=observationsOf(e),tier=observationTier(obs);
    if(obs==null)return {state:'LOW_SUPPORT',tier,reason:'LOW_SUPPORT:MISSING_SUPPORT_OBSERVATIONS'};
    if(obs<minimumObservations)return {state:'LOW_SUPPORT',tier,reason:'LOW_SUPPORT:OBSERVATIONS_BELOW_'+minimumObservations};
    return {state:'COVERED',tier,reason:null};
  }
  function sourceRef(e){return {hand_id:String(e.hand_id),decision_id:String(e.decision_id)};}
  function refKey(r){return String(r.hand_id)+'\u0000'+String(r.decision_id);}
  function normalizeRefs(refs){
    const map=new Map();
    for(const r of refs||[]){if(!r||r.hand_id==null||r.decision_id==null)continue;map.set(refKey(r),{hand_id:String(r.hand_id),decision_id:String(r.decision_id)});}
    return Array.from(map.values()).sort((a,b)=>a.hand_id.localeCompare(b.hand_id)||a.decision_id.localeCompare(b.decision_id));
  }
  function reasonCounts(classes){
    const out={};
    for(const c of classes){if(c.reason)out[c.reason]=(out[c.reason]||0)+1;}
    return Object.fromEntries(Object.entries(out).sort((a,b)=>a[0].localeCompare(b[0])));
  }
  function effectiveState(rows){
    if(!rows.length)return 'ANALYSIS_MISSING';
    const states=rows.map(x=>x._coverage.state);
    if(states.every(x=>x==='COVERED'))return 'COVERED';
    if(states.some(x=>x==='COVERED'||x==='LOW_SUPPORT'))return 'LOW_SUPPORT';
    if(states.some(x=>x==='UNSUPPORTED'))return 'UNSUPPORTED';
    if(states.some(x=>x==='NON_COMPARABLE'))return 'NON_COMPARABLE';
    return 'ANALYSIS_MISSING';
  }
  function sizingContext(e){
    if(e.sizing_error)return 'SIZING_ERROR';
    const a=upper(e.played.action),r=upper(e.recommended.action);
    const sizing=['BET','RAISE','SHOVE','JAM'].includes(a)||['BET','RAISE','SHOVE','JAM'].includes(r)
      ||e.played.target_total_bb!=null||e.recommended.target_total_bb!=null||e.played.size_pot_ratio!=null||e.recommended.size_pot_ratio!=null;
    return sizing?'SIZING_DECISION':'NON_SIZING_DECISION';
  }
  function rawPreflopMeta(raw,e,mapping,evidenceIndex){
    if(upper(e.context.street)!=='PREFLOP')return {family:null,context_id:null};
    const mk=String(e.hand_id)+'\u0000'+String(e.decision_id);
    const mapped=(mapping&&mapping[mk])||(mapping&&mapping[e.decision_id])||null;
    const family=upper(mapped&&mapped.family||raw&&raw.preflop_family||raw&&raw.preflop&&raw.preflop.family||raw&&raw.context&&raw.context.preflop_family);
    const contextId=text(mapped&&mapped.context_id||raw&&raw.preflop_context_id||raw&&raw.preflop&&raw.preflop.context_id||raw&&raw.context&&raw.context.preflop_context_id);
    if(family||contextId)return {family:family||null,context_id:contextId||null};
    const sf=upper(e.context.spot_family);
    if(evidenceIndex.family.has(sf))return {family:sf,context_id:null};
    const families=evidenceIndex.coverage_group.get(sf);
    if(families&&families.size===1)return {family:Array.from(families)[0],context_id:null};
    return {family:null,context_id:null};
  }

  function assertTrainOnlyScope(scope,label){
    if(!scope||scope.split_consumed!=='TRAIN')throw new Error(label+' must consume TRAIN only');
    for(const k of ['validation_consumed','test_consumed','strategy_generated','ev_evaluated']){
      if(scope[k]!==false)throw new Error(label+'.'+k+' must be false');
    }
    if('actions_recommended' in scope&&scope.actions_recommended!==false)throw new Error(label+'.actions_recommended must be false');
    if('sizings_recommended' in scope&&scope.sizings_recommended!==false)throw new Error(label+'.sizings_recommended must be false');
  }
  function auditMatrixKey(row){
    return stableStringify({
      actor_position:row.actor_position||null,
      callers_after_first_raise:Number(row.callers_after_first_raise||0),
      facing_jam:Boolean(row.facing_jam),
      family:row.family||null,
      last_aggressor_position:row.last_aggressor_position||null,
      limpers_before_first_raise:Number(row.limpers_before_first_raise||0),
      opener_position:row.opener_position||null
    });
  }
  function planSourceKey(row){
    const raw=text(row.source_matrix_key);
    if(!raw)return null;
    try{return stableStringify(JSON.parse(raw));}catch(_){return null;}
  }
  function normalizePreflopTrainEvidence(audit,plan){
    if(!audit&&!plan)return {schema:PREFLOP_EVIDENCE_SCHEMA,population_id:null,contexts:[]};
    if(audit){
      if(audit.schema&&audit.schema!=='poker-hero-preflop-coverage-audit/v1')throw new Error('unexpected preflop audit schema '+audit.schema);
      assertTrainOnlyScope(audit.scope,'preflop audit scope');
    }
    if(plan){
      if(plan.schema&&plan.schema!=='poker-hero-preflop-generation-plan/v1')throw new Error('unexpected preflop plan schema '+plan.schema);
      assertTrainOnlyScope(plan.scope,'preflop plan scope');
    }
    const populationId=text(audit&&audit.population_id||plan&&plan.population_id)||null;
    if(audit&&plan&&String(audit.population_id)!==String(plan.population_id))throw new Error('preflop TRAIN population mismatch');

    const auditRows=Array.isArray(audit&&audit.matrix)?audit.matrix:[];
    const auditMap=new Map(auditRows.map(r=>[auditMatrixKey(r),r]));
    const contexts=[];
    if(Array.isArray(plan&&plan.contexts)){
      for(const p of plan.contexts){
        const key=planSourceKey(p),a=key&&auditMap.get(key)||null;
        contexts.push({
          context_id:requiredText(p.context_id,'preflop plan context_id'),
          family:upper(p.family||a&&a.family)||'UNKNOWN',
          coverage_group:upper(p.coverage_group||a&&a.coverage_group)||'UNKNOWN',
          hero_position:upper(p.hero_position||a&&a.actor_position)||'UNKNOWN',
          opener_position:upper(p.opener_position||a&&a.opener_position)||null,
          last_aggressor_position:upper(p.last_aggressor_position||a&&a.last_aggressor_position)||null,
          caller_count:nonNegativeInt(p.caller_count??(a&&a.callers_after_first_raise),'caller_count',0),
          limper_count:nonNegativeInt(p.limper_count??(a&&a.limpers_before_first_raise),'limper_count',0),
          jam_state:Boolean(p.jam_state??(a&&a.facing_jam)),
          train_observations:nonNegativeInt(p.train_observations??(a&&a.observations),'train_observations',0),
          distinct_hands:nonNegativeInt(p.distinct_hands??(a&&a.distinct_hands),'distinct_hands',0),
          support_tier:normalizeTier(p.support_tier||a&&a.support_tier),
          readiness:upper(p.readiness)||null,
          frequency_of_targeted:asFinite((p.frequency&&p.frequency.of_targeted)??(a&&a.frequency_of_targeted)),
          source:'TRAIN_PLAN_AND_AUDIT'
        });
      }
    }else{
      for(const a of auditRows){
        const key=auditMatrixKey(a);
        contexts.push({
          context_id:'train-audit:'+hash(key),
          family:upper(a.family)||'UNKNOWN',
          coverage_group:upper(a.coverage_group)||'UNKNOWN',
          hero_position:upper(a.actor_position)||'UNKNOWN',
          opener_position:upper(a.opener_position)||null,
          last_aggressor_position:upper(a.last_aggressor_position)||null,
          caller_count:nonNegativeInt(a.callers_after_first_raise,'callers_after_first_raise',0),
          limper_count:nonNegativeInt(a.limpers_before_first_raise,'limpers_before_first_raise',0),
          jam_state:Boolean(a.facing_jam),
          train_observations:nonNegativeInt(a.observations,'observations',0),
          distinct_hands:nonNegativeInt(a.distinct_hands,'distinct_hands',0),
          support_tier:normalizeTier(a.support_tier),
          readiness:null,
          frequency_of_targeted:asFinite(a.frequency_of_targeted),
          source:'TRAIN_AUDIT'
        });
      }
    }
    contexts.sort((a,b)=>a.context_id.localeCompare(b.context_id));
    return {schema:PREFLOP_EVIDENCE_SCHEMA,population_id:populationId,contexts};
  }
  function evidenceIndex(evidence){
    const family=new Set(),coverage_group=new Map(),byContext=new Map();
    for(const c of evidence.contexts||[]){
      family.add(upper(c.family));
      const cg=upper(c.coverage_group);if(!coverage_group.has(cg))coverage_group.set(cg,new Set());coverage_group.get(cg).add(upper(c.family));
      byContext.set(c.context_id,c);
    }
    return {family,coverage_group,byContext};
  }
  function trainEvidenceSummary(contexts){
    const rows=contexts||[];
    if(!rows.length)return null;
    return {
      source_schema:PREFLOP_EVIDENCE_SCHEMA,
      context_count:rows.length,
      train_observations:rows.reduce((s,x)=>s+Number(x.train_observations||0),0),
      distinct_hands_max:rows.reduce((m,x)=>Math.max(m,Number(x.distinct_hands||0)),0),
      support_tier:minTier(rows.map(x=>x.support_tier)),
      support_tiers:uniqueSorted(rows.map(x=>x.support_tier)),
      readiness:uniqueSorted(rows.map(x=>x.readiness)),
      context_ids:rows.map(x=>x.context_id).sort(),
      frequency_of_targeted_sum:round(rows.reduce((s,x)=>s+(Number.isFinite(Number(x.frequency_of_targeted))?Number(x.frequency_of_targeted):0),0))
    };
  }
  function supportTierForGroup(rows,trainContexts){
    const runtime=rows.filter(x=>x._coverage.state==='COVERED'||x._coverage.state==='LOW_SUPPORT').map(x=>x._coverage.tier);
    if(runtime.length)return {tier:minTier(runtime),source:'ANALYSIS'};
    if(trainContexts&&trainContexts.length)return {tier:minTier(trainContexts.map(x=>x.support_tier)),source:'TRAIN_ONLY'};
    return {tier:'UNKNOWN',source:'NONE'};
  }
  function buildRow(dimension,key,rows,trainContexts=[]){
    const classes=rows.map(x=>x._coverage),state=effectiveState(rows),refs=normalizeRefs(rows.map(x=>sourceRef(x.event)));
    const hands=uniqueSorted(rows.map(x=>String(x.event.hand_id)));
    const supported=rows.filter(x=>x.event.support.covered).length;
    const comparable=rows.filter(x=>x.event.support.covered&&x.event.comparability.comparable).length;
    const covered=classes.filter(x=>x.state==='COVERED').length;
    const low=classes.filter(x=>x.state==='LOW_SUPPORT').length;
    const unsupported=classes.filter(x=>x.state==='UNSUPPORTED').length;
    const nonComparable=classes.filter(x=>x.state==='NON_COMPARABLE').length;
    const tier=supportTierForGroup(rows,trainContexts);
    const train=trainEvidenceSummary(trainContexts);
    return {
      schema:ROW_SCHEMA,
      row_id:'coverage-row:'+hash(dimension+'\u0000'+String(key)),
      dimension,key:String(key),
      state,
      hand_count:hands.length,
      decision_count:rows.length,
      comparable_count:comparable,
      supported_count:supported,
      covered_count:covered,
      low_support_count:low,
      unsupported_count:unsupported,
      non_comparable_count:nonComparable,
      support_tier:tier.tier,
      support_tier_source:tier.source,
      coverage_ratio:rows.length?round(supported/rows.length):null,
      comparable_ratio:rows.length?round(comparable/rows.length):null,
      distinct_hands:hands,
      source_refs:refs,
      exclusion_reasons:reasonCounts(classes),
      train_evidence:train,
      semantics:{
        ev_loss_aggregated:false,
        usable_as_ev_leak:state==='COVERED',
        training_target_eligible:state==='COVERED'
      }
    };
  }
  function eventDimensionKey(row,dimension){
    const e=row.event,m=row.preflop;
    if(dimension==='position')return e.context.position;
    if(dimension==='street')return e.context.street;
    if(dimension==='spot_family')return e.context.spot_family;
    if(dimension==='action_context')return e.played.action+'->'+e.recommended.action;
    if(dimension==='sizing_context')return sizingContext(e);
    if(dimension==='jam')return e.tags.jam?'JAM':'NO_JAM';
    if(dimension==='overbet')return e.tags.overbet?'OVERBET':'NO_OVERBET';
    if(dimension==='preflop_family')return m.family;
    if(dimension==='preflop_context')return m.context_id;
    throw new Error('unsupported dimension '+dimension);
  }
  function groupRows(eventRows,dimension){
    const map=new Map();
    for(const row of eventRows){
      const key=eventDimensionKey(row,dimension);if(key==null||key==='')continue;
      const k=String(key);if(!map.has(k))map.set(k,[]);map.get(k).push(row);
    }
    return map;
  }
  function aggregateEvidenceByFamily(evidence){
    const map=new Map();
    for(const c of evidence.contexts||[]){const k=upper(c.family)||'UNKNOWN';if(!map.has(k))map.set(k,[]);map.get(k).push(c);}
    return map;
  }
  function reportSummary(eventRows,rows){
    const all=eventRows.map(x=>x._coverage),hands=uniqueSorted(eventRows.map(x=>String(x.event.hand_id)));
    return {
      hand_count:hands.length,
      decision_count:eventRows.length,
      comparable_count:eventRows.filter(x=>x.event.support.covered&&x.event.comparability.comparable).length,
      supported_count:eventRows.filter(x=>x.event.support.covered).length,
      covered_count:all.filter(x=>x.state==='COVERED').length,
      low_support_count:all.filter(x=>x.state==='LOW_SUPPORT').length,
      unsupported_count:all.filter(x=>x.state==='UNSUPPORTED').length,
      non_comparable_count:all.filter(x=>x.state==='NON_COMPARABLE').length,
      analysis_missing_rows:rows.filter(x=>x.state==='ANALYSIS_MISSING').length,
      coverage_ratio:eventRows.length?round(eventRows.filter(x=>x.event.support.covered).length/eventRows.length):null,
      comparable_ratio:eventRows.length?round(eventRows.filter(x=>x.event.support.covered&&x.event.comparability.comparable).length/eventRows.length):null,
      distinct_hands:hands,
      exclusion_reasons:reasonCounts(all)
    };
  }
  function coverageGaps(rows,limit=50){
    const n=nonNegativeInt(limit,'coverage_gap_limit',50);
    return rows.filter(x=>x.state!=='COVERED').map(x=>({
      row_id:x.row_id,dimension:x.dimension,key:x.key,state:x.state,
      decision_count:x.decision_count,hand_count:x.hand_count,support_tier:x.support_tier,
      train_observations:x.train_evidence?x.train_evidence.train_observations:0,
      exclusion_reasons:x.exclusion_reasons
    })).sort((a,b)=>{
      const af=Math.max(a.decision_count,a.train_observations),bf=Math.max(b.decision_count,b.train_observations);
      return bf-af||(GAP_STATE_ORDER[a.state]??9)-(GAP_STATE_ORDER[b.state]??9)||a.dimension.localeCompare(b.dimension)||a.key.localeCompare(b.key);
    }).slice(0,n);
  }

  function analyzeCoverage(input={}){
    if(!Leak)throw new Error('PokerLeakAnalyzer is required');
    const rawEvents=Array.isArray(input.decision_events)?input.decision_events:[];
    const normalized=rawEvents.map((raw,i)=>({raw,event:Leak.normalizeEvent(raw),index:i}));
    const scopes=new Map();
    for(const x of normalized){const s=scopeFrom(x.raw,x.event);scopes.set(scopeKey(s),s);}
    if(scopes.size>1)throw new Error('coverage analysis spans '+scopes.size+' population/pack/strategy/version/EV scopes; select one exact scope');
    const inferred=scopes.size?Array.from(scopes.values())[0]:null;
    const declared=input.scope?exactScope(input.scope):null;
    if(inferred&&declared)assertSameScope(declared,inferred,'declared scope');
    const scope=declared||inferred;
    if(!scope)throw new Error('scope is required when decision_events is empty');

    const evidence=normalizePreflopTrainEvidence(input.preflop_train_audit||null,input.preflop_generation_plan||null);
    if(evidence.population_id&&evidence.population_id!==scope.population_id)throw new Error('preflop TRAIN population does not match analysis scope');
    const eIndex=evidenceIndex(evidence);
    const minimumObservations=nonNegativeInt(input.minimum_supported_observations,'minimum_supported_observations',20);

    const eventRows=normalized.map(x=>{
      const e=x.event;
      return {
        raw:x.raw,event:e,
        _coverage:eventClass(e,minimumObservations),
        preflop:rawPreflopMeta(x.raw,e,input.preflop_context_by_decision||{},eIndex)
      };
    });

    const rows=[];
    const familyEvidence=aggregateEvidenceByFamily(evidence);
    for(const dimension of DIMENSIONS){
      const groups=groupRows(eventRows,dimension);
      if(dimension==='preflop_family'){
        for(const key of familyEvidence.keys())if(!groups.has(key))groups.set(key,[]);
      }
      if(dimension==='preflop_context'){
        for(const c of evidence.contexts)if(!groups.has(c.context_id))groups.set(c.context_id,[]);
      }
      for(const key of Array.from(groups.keys()).sort()){
        let train=[];
        if(dimension==='preflop_family')train=familyEvidence.get(key)||[];
        else if(dimension==='preflop_context'){const c=eIndex.byContext.get(key);train=c?[c]:[];}
        rows.push(buildRow(dimension,key,groups.get(key),train));
      }
    }
    rows.sort((a,b)=>DIMENSIONS.indexOf(a.dimension)-DIMENSIONS.indexOf(b.dimension)||a.key.localeCompare(b.key));
    const matrix={};
    for(const d of DIMENSIONS)matrix[d]=rows.filter(x=>x.dimension===d).map(x=>x.row_id);

    return {
      schema:COVERAGE_SCHEMA,
      event_schema:Leak.EVENT_SCHEMA,
      scope,
      scope_key:scopeKey(scope),
      configuration:{minimum_supported_observations:minimumObservations},
      source_contracts:{
        review_inbox:'poker-review-inbox/v1',
        review_dashboard:'poker-review-dashboard/v1',
        leak_training_target:'poker-leak-training-target/v1',
        leak_training_session_plan:'poker-leak-training-session-plan/v1',
        preflop_train_evidence:evidence.schema
      },
      semantics:{
        coverage_support_is_distinct_from_ev_loss:true,
        ev_loss_aggregated:false,
        states_excluded_from_ev_leaks:['LOW_SUPPORT','UNSUPPORTED','NON_COMPARABLE','ANALYSIS_MISSING'],
        preflop_evidence_split:'TRAIN',
        validation_consumed:false,
        test_consumed:false
      },
      summary:reportSummary(eventRows,rows),
      rows,
      matrix,
      coverage_gaps:coverageGaps(rows,input.coverage_gap_limit==null?50:input.coverage_gap_limit),
      preflop_train_evidence:{
        schema:evidence.schema,
        population_id:evidence.population_id,
        context_count:evidence.contexts.length,
        total_train_observations:evidence.contexts.reduce((s,x)=>s+x.train_observations,0),
        support_tiers:uniqueSorted(evidence.contexts.map(x=>x.support_tier))
      }
    };
  }

  function analyzeCoverageFromPersistedReviewData(input={}){
    if(!Adapter||typeof Adapter.adaptPersistedReviewData!=='function')throw new Error('PokerReviewLeakAdapter is required');
    const adapted=Adapter.adaptPersistedReviewData({reviewScores:input.reviewScores||{},hhSources:input.hhSources||[],scope:input.scope});
    return analyzeCoverage({...input,decision_events:adapted.events});
  }
  function analyzeCoverageByScope(input={}){
    if(!Leak)throw new Error('PokerLeakAnalyzer is required');
    const raw=Array.isArray(input.decision_events)?input.decision_events:[];
    if(!raw.length)return [analyzeCoverage(input)];
    const groups=new Map();
    for(const r of raw){
      const e=Leak.normalizeEvent(r),s=scopeFrom(r,e),k=scopeKey(s);
      if(!groups.has(k))groups.set(k,{scope:s,events:[]});
      groups.get(k).events.push(r);
    }
    return Array.from(groups.keys()).sort().map(k=>analyzeCoverage({...input,scope:groups.get(k).scope,decision_events:groups.get(k).events}));
  }
  function exportCoverageJSON(report,options={}){
    if(!report||report.schema!==COVERAGE_SCHEMA)throw new Error('expected '+COVERAGE_SCHEMA);
    return JSON.stringify(report,null,options.pretty===false?0:2);
  }

  return {
    COVERAGE_SCHEMA,ROW_SCHEMA,PREFLOP_EVIDENCE_SCHEMA,STATES,DIMENSIONS,SCOPE_FIELDS,
    normalizePreflopTrainEvidence,analyzeCoverage,analyzeCoverageFromPersistedReviewData,analyzeCoverageByScope,
    exportCoverageJSON,scopeKey
  };
});
