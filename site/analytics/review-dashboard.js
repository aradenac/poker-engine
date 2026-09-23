(function(root,factory){
  const Leak=(typeof module==='object'&&module.exports)?require('./leak-analyzer.js'):(root&&root.PokerLeakAnalyzer);
  const Adapter=(typeof module==='object'&&module.exports)?require('./review-score-adapter.js'):(root&&root.PokerReviewLeakAdapter);
  const Inbox=(typeof module==='object'&&module.exports)?require('./review-inbox.js'):(root&&root.PokerReviewInbox);
  const Target=(typeof module==='object'&&module.exports)?require('./leak-training-target.js'):(root&&root.PokerLeakTrainingTarget);
  const State=(typeof module==='object'&&module.exports)?require('./analysis-state.js'):(root&&root.PokerAnalysisState);
  const api=factory(Leak,Adapter,Inbox,Target,State);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerReviewDashboard=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(Leak,Adapter,Inbox,Target,State){
  'use strict';

  const DASHBOARD_SCHEMA='poker-review-dashboard/v1';
  const CTA_SCHEMA='poker-review-dashboard-cta/v1';
  const EMPTY_STATES={
    NO_HANDS:'NO_HANDS',
    ANALYSIS_PENDING:'ANALYSIS_PENDING',
    ANALYSIS_INCOMPLETE:'ANALYSIS_INCOMPLETE',
    NO_SIGNIFICANT_LOSS:'NO_SIGNIFICANT_LOSS',
    READY:'READY'
  };
  const EPS=1e-9;

  function text(v){return v==null?'':String(v).trim();}
  function round(v){return Math.round((Number(v)+Number.EPSILON)*1e9)/1e9;}
  function sourceRef(e){return {hand_id:String(e.hand_id),decision_id:String(e.decision_id)};}
  function exactScope(e,scope){
    if(!e||!scope)return false;
    return ['population_id','pack_id','strategy_id','strategy_version','ev_reference'].every(k=>
      String(e[k]==null?'':e[k])===String(scope[k]==null?'':scope[k])
    );
  }
  function baseScope(input={}){
    const population_id=text(input.population_id);if(!population_id)throw new Error('scope.population_id is required');
    const strategy_id=text(input.strategy_id);if(!strategy_id)throw new Error('scope.strategy_id is required');
    return {
      population_id,pack_id:text(input.pack_id)||null,strategy_id,
      strategy_version:text(input.strategy_version)||'UNKNOWN_RUNTIME',
      ev_reference:text(input.ev_reference)||(Adapter&&Adapter.DEFAULT_EV_REFERENCE)||'review_score_policy_adjusted_incremental_bb'
    };
  }
  function emptyReport(scope){
    return {
      schema:Leak.REPORT_SCHEMA,event_schema:Leak.EVENT_SCHEMA,scope:{...scope},filters:{},
      summary:{
        decisions_selected:0,decisions_eligible:0,decisions_contributing:0,hands_analyzed:0,
        total_loss_bb:0,nominal_loss_bb:0,within_noise_nominal_loss_bb:0,
        loss_bb_per_100_hands:null,loss_bb_per_100_decisions:null,coverage_pct:null,
        within_noise_decisions:0,unsupported_decisions:0,non_comparable_decisions:0,exclusions:{}
      },
      leaks:{by:{position:[],street:[],spot_family:[],action_pair:[],error_type:[]},aggressive_sizing:{combined:null,jam:null,overbet:null},top_decisions:[]},
      decision_events:[]
    };
  }
  function topLeaks(report,limit){
    const n=Number.isInteger(Number(limit))&&Number(limit)>0?Number(limit):5;
    const rows=(report.leaks&&report.leaks.by&&report.leaks.by.spot_family)||[];
    return rows.filter(x=>Number(x.total_loss_bb)>EPS).slice(0,n).map(x=>({
      dimension:'spot_family',key:x.key,decisions:x.decisions,hands:x.hands,
      total_loss_bb:x.total_loss_bb,frequency_pct:x.frequency_pct,loss_share_pct:x.loss_share_pct,
      source_refs:(x.source_refs||[]).map(r=>({hand_id:String(r.hand_id),decision_id:String(r.decision_id)}))
    }));
  }
  function choosePriorityItem(items){
    const rows=Array.isArray(items)?items:[];
    return rows.find(x=>x.total_loss_bb>EPS)
      ||rows.find(x=>x.status===Inbox.STATUS.INCOMPLETE_ANALYSIS)
      ||rows[0]||null;
  }
  function reviewCta(priority){
    if(!priority||!priority.deep_link)return {schema:CTA_SCHEMA,kind:'REVIEW',enabled:false,reason:'NO_REVIEW_TARGET',target:null};
    return {
      schema:CTA_SCHEMA,kind:'REVIEW',enabled:true,
      reason:priority.total_loss_bb>EPS?'PRIORITY_EV_LOSS':priority.status===Inbox.STATUS.INCOMPLETE_ANALYSIS?'INCOMPLETE_ANALYSIS':'FIRST_AVAILABLE_HAND',
      target:{...priority.deep_link}
    };
  }
  function leakCta(inbox,leaks){
    const top=leaks[0]||null;
    if(!top)return {schema:CTA_SCHEMA,kind:'LEAK',enabled:false,reason:'NO_SIGNIFICANT_LEAK',target:null};
    return {
      schema:CTA_SCHEMA,kind:'LEAK',enabled:true,reason:'TOP_EV_LEAK',
      target:{scope_key:inbox.scope_key,dimension:top.dimension,key:top.key,source_refs:top.source_refs}
    };
  }
  function trainingCta(report,leaks,options){
    const top=leaks[0]||null;
    if(!top||!Target)return {schema:CTA_SCHEMA,kind:'TRAINING',enabled:false,reason:'NO_TRAINING_TARGET',target:null};
    try{
      const target=Target.targetFromLeakReport(report,{
        dimension:top.dimension,key:top.key,
        minimum_decisions:options.training_min_decisions==null?1:options.training_min_decisions,
        minimum_scenarios:options.training_min_scenarios==null?1:options.training_min_scenarios
      });
      return {
        schema:CTA_SCHEMA,kind:'TRAINING',enabled:Boolean(target.source_support&&target.source_support.sufficient),
        reason:target.source_support&&target.source_support.sufficient?'TOP_LEAK_TARGET':'INSUFFICIENT_SOURCE_SUPPORT',
        target
      };
    }catch(err){
      return {schema:CTA_SCHEMA,kind:'TRAINING',enabled:false,reason:'TARGET_BUILD_FAILED',target:null,error:text(err&&err.message||err)};
    }
  }
  function emptyState(metrics,inbox){
    if(metrics.hands_loaded===0)return EMPTY_STATES.NO_HANDS;
    if(metrics.hands_with_review_score===0||inbox.items.length===0)return EMPTY_STATES.ANALYSIS_PENDING;
    if(metrics.decisions_analyzed===0||metrics.hands_incomplete>0&&metrics.decisions_to_review===0)return EMPTY_STATES.ANALYSIS_INCOMPLETE;
    if(metrics.total_ev_loss_bb<=EPS)return EMPTY_STATES.NO_SIGNIFICANT_LOSS;
    return EMPTY_STATES.READY;
  }
  // #393 T4: derive the dominant scope state from the shared
  // `poker-analysis-state/v1` taxonomy instead of exposing the legacy empty
  // state as the only user-facing label. The legacy EMPTY_STATES code stays the
  // technical input; the taxonomy `analysis_state.state` plus its French label
  // are the primary surface, while the technical reason codes only live in the
  // secondary `analysis_state.reason_codes` field consumed by the details view.
  // The shared mapper applies its own precedence, so a scope carrying several
  // causes still resolves to exactly one dominant state. ANALYSIS_INCOMPLETE is
  // disambiguated by cause: a scope without any analyzable decision is a support
  // shortage (DONNEES_INSUFFISANTES), otherwise it is a partial analysis
  // (ANALYSE_PARTIELLE).
  function analysisStateReasonCodes(state,metrics){
    if(state!==EMPTY_STATES.ANALYSIS_INCOMPLETE)return [state];
    return Number(metrics.decisions_analyzed)>0
      ?[EMPTY_STATES.ANALYSIS_INCOMPLETE]
      :[EMPTY_STATES.ANALYSIS_INCOMPLETE,'INSUFFICIENT_SUPPORT'];
  }
  function analysisStateFor(state,metrics){
    if(!State||typeof State.mapAnalysisState!=='function')return null;
    return State.mapAnalysisState({reason_codes:analysisStateReasonCodes(state,metrics)});
  }
  function analysisStateLabel(state){
    if(Inbox&&typeof Inbox.analysisStateLabel==='function')return Inbox.analysisStateLabel(state);
    return text(state)||null;
  }
  function dashboardFrom(inbox,adapted,reviewScores,options={}){
    const scopedEvents=(adapted.events||[]).filter(e=>exactScope(e,inbox.scope));
    const report=scopedEvents.length?Leak.analyzeLeaks(scopedEvents):emptyReport(inbox.scope);
    const leaks=topLeaks(report,options.top_leaks_limit);
    const priority=choosePriorityItem(inbox.items);
    const contributing=report.decision_events.filter(e=>e.support.covered&&e.comparability.comparable&&e.ev.attributed_loss_bb>EPS);
    const incomplete=inbox.items.filter(x=>x.coverage.state===Inbox.COVERAGE_INCOMPLETE);
    const metrics={
      hands_loaded:adapted.hands&&typeof adapted.hands.size==='number'?adapted.hands.size:0,
      hands_with_review_score:Object.keys(reviewScores||{}).length,
      hands_in_scope:inbox.items.length,
      hands_incomplete:incomplete.length,
      decisions_analyzed:report.summary.decisions_eligible,
      decisions_to_review:report.summary.decisions_contributing,
      total_ev_loss_bb:report.summary.total_loss_bb,
      nominal_ev_loss_bb:report.summary.nominal_loss_bb,
      review_coverage_pct:report.summary.coverage_pct,
      source_refs:contributing.map(sourceRef)
    };
    const ctas={
      review:reviewCta(priority),
      leak:leakCta(inbox,leaks),
      training:trainingCta(report,leaks,options)
    };
    const emptyStateName=emptyState(metrics,inbox);
    const analysisState=analysisStateFor(emptyStateName,metrics);
    return {
      schema:DASHBOARD_SCHEMA,
      scope:{...inbox.scope},scope_key:inbox.scope_key,
      state:emptyStateName,
      analysis_state:analysisState,
      analysis_state_label:analysisState?analysisStateLabel(analysisState.state):null,
      metrics,
      top_leaks:leaks,
      priority:{
        hand:priority?{
          hand_id:priority.hand_id,total_loss_bb:priority.total_loss_bb,status:priority.status,
          status_label:priority.status_label,coverage:priority.coverage.state,deep_link:priority.deep_link
        }:null,
        decision:priority&&priority.costliest_decision?{...priority.costliest_decision}:priority&&priority.primary_decision?{...priority.primary_decision}:null
      },
      ctas,
      traceability:{
        inbox_schema:Inbox.INBOX_SCHEMA,
        leak_report_schema:Leak.REPORT_SCHEMA,
        event_schema:Leak.EVENT_SCHEMA,
        adapter_schema:Adapter.ADAPTER_SCHEMA,
        training_target_schema:Target&&Target.TARGET_SCHEMA||null
      }
    };
  }

  function buildReviewDashboards(input={}){
    if(!Leak||!Adapter||!Inbox)throw new Error('Leak Analyzer, Review adapter and Review Inbox are required');
    const reviewScores=input.reviewScores&&typeof input.reviewScores==='object'?input.reviewScores:{};
    const adapted=Adapter.adaptPersistedReviewData({reviewScores,hhSources:input.hhSources||[],scope:input.scope});
    const inboxes=Inbox.buildReviewInboxes({
      reviewScores,hhSources:input.hhSources||[],scope:input.scope,user_metadata:input.user_metadata
    });
    return inboxes.map(inbox=>dashboardFrom(inbox,adapted,reviewScores,input)).sort((a,b)=>a.scope_key.localeCompare(b.scope_key));
  }
  function buildReviewDashboard(input={}){
    const dashboards=buildReviewDashboards(input);
    if(input.scope_key){
      const found=dashboards.find(x=>x.scope_key===input.scope_key);if(!found)throw new Error('scope_key not found');
      return found;
    }
    if(dashboards.length>1)throw new Error('review dashboard spans '+dashboards.length+' population/pack/strategy/version/EV scopes; select one scope');
    if(dashboards.length===1)return dashboards[0];

    const adapted=Adapter.adaptPersistedReviewData({reviewScores:input.reviewScores||{},hhSources:input.hhSources||[],scope:input.scope});
    const scope=baseScope(input.scope||{});
    const inbox={
      schema:Inbox.INBOX_SCHEMA,event_schema:Leak.EVENT_SCHEMA,adapter_schema:Adapter.ADAPTER_SCHEMA,
      scope,scope_key:Leak.scopeKey(scope),items:[],warnings:[...adapted.warnings],user_metadata_schema:Inbox.USER_METADATA_SCHEMA
    };
    return dashboardFrom(inbox,adapted,input.reviewScores||{},input);
  }

  return {DASHBOARD_SCHEMA,CTA_SCHEMA,EMPTY_STATES,buildReviewDashboard,buildReviewDashboards};
});
