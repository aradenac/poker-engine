(function(root,factory){
  const Decision=(typeof module==='object'&&module.exports)?require('../preflop/decision.js'):(root&&root.PokerPreflopDecision);
  const Guidance=(typeof module==='object'&&module.exports)?require('../preflop/guidance.js'):(root&&root.PokerPreflopGuidance);
  const Leak=(typeof module==='object'&&module.exports)?require('../analytics/leak-analyzer.js'):(root&&root.PokerLeakAnalyzer);
  const api=factory(Decision,Guidance,Leak);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerPreflopDecisionAdapter=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(Decision,Guidance,Leak){
  'use strict';

  const SCHEMA='poker-preflop-decision/v1';
  const ADAPTER_PROFILE='CANONICAL_RUNTIME_DECISION_V1';
  const SNAPSHOT_SCHEMA='nlhe-game-state/v1';
  const GUIDANCE_SCHEMA='poker-preflop-guidance/v1';
  const COVERAGE_STATES=['COVERED','LOW_SUPPORT','UNSUPPORTED','NON_COMPARABLE','ANALYSIS_MISSING','UNCOVERED'];
  const FAIL_CLOSED_STATES=[
    'NO_ADMISSIBLE_STRATEGY','EXACT_CONTEXT_ABSENT','EXACT_CONTEXT_MISMATCH','POPULATION_MISMATCH',
    'STRATEGY_MISMATCH','ARTIFACT_IDENTITY_MISMATCH','LOW_SUPPORT','UNCOVERED',
    'NON_COMPARABLE_ALTERNATIVES','INVALID_GUIDANCE'
  ];
  const POSITION_NAMES=new Set(['LJ','HJ','CO','BTN','SB','BB','SB_BTN']);
  const LOW_TIERS=new Set(['LOW','SPARSE','UNKNOWN']);
  const EPS=1e-9;
  const SENSITIVE_KEYS=[
    'hole_cards','opponent_hole_cards','opponents_hole_cards','villain_hole_cards','private_cards',
    'future_cards','future_board','future_public_cards','runout','showdown_cards'
  ];

  function text(v){return v==null?'':String(v).trim();}
  function upper(v){return text(v).toUpperCase();}
  function finiteOrNull(v){if(v==null||v==='')return null;const n=Number(v);return Number.isFinite(n)?n:null;}
  function round(v){return Math.round((Number(v)+Number.EPSILON)*1e9)/1e9;}
  function stableStringify(v){
    if(v===null||typeof v!=='object')return JSON.stringify(v);
    if(Array.isArray(v))return '['+v.map(stableStringify).join(',')+']';
    return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+stableStringify(v[k])).join(',')+'}';
  }
  function hash(s){let h=2166136261>>>0;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)>>>0;}return h.toString(36);}
  function clone(v){return v==null?v:JSON.parse(JSON.stringify(v));}
  function unique(values){return Array.from(new Set(values.filter(Boolean))).sort();}
  function required(v,name){const s=text(v);if(!s)throw new Error(name+' is required');return s;}

  function normalizeIdentity(input={}){
    return {
      population_id:required(input.population_id,'identity.population_id'),
      pack_id:text(input.pack_id)||null,
      pack_version:text(input.pack_version)||null,
      strategy_id:required(input.strategy_id,'identity.strategy_id'),
      strategy_version:required(input.strategy_version,'identity.strategy_version'),
      strategy_sha256:text(input.strategy_sha256||input.artifact_sha256).toLowerCase()||null,
      decision_source_sha256:text(input.decision_source_sha256).toLowerCase()||null,
      ev_reference:text(input.ev_reference)||(Decision&&Decision.EV_REFERENCE)||'decision_point_incremental_bb'
    };
  }

  function normalizeSnapshot(publicState){
    const wrapper=publicState&&publicState.snapshot?publicState:{snapshot:publicState};
    const snapshot=wrapper.snapshot;
    if(!snapshot||typeof snapshot!=='object'||Array.isArray(snapshot))throw new Error('public_state snapshot is required');
    if(snapshot.schema!==SNAPSHOT_SCHEMA)throw new Error('expected '+SNAPSHOT_SCHEMA);
    if(upper(snapshot.street)!=='PREFLOP')throw new Error('preflop decision adapter requires PREFLOP public state');
    const seats=Array.isArray(snapshot.seats)?snapshot.seats.map(String):[];
    if(!seats.length)throw new Error('public_state.seats must not be empty');
    const pending=Array.isArray(snapshot.pending)?snapshot.pending.map(String):[];
    const actor=text(wrapper.legal_view&&wrapper.legal_view.actor)||pending[0]||'';
    if(!actor)throw new Error('public_state has no pending actor');
    if(!seats.includes(actor))throw new Error('public_state actor must be seated');

    const numericMap=(obj)=>Object.fromEntries(Object.entries(obj||{}).sort((a,b)=>a[0].localeCompare(b[0])).map(([k,v])=>[String(k),round(Number(v)||0)]));
    const boolMap=(obj)=>Object.fromEntries(Object.entries(obj||{}).sort((a,b)=>a[0].localeCompare(b[0])).map(([k,v])=>[String(k),Boolean(v)]));
    const total=numericMap(snapshot.total_committed_bb),street=numericMap(snapshot.street_committed_bb),remaining=numericMap(snapshot.stacks_bb);
    const folded=boolMap(snapshot.folded),allIn=boolMap(snapshot.all_in),refunds=numericMap(snapshot.refunds_bb);
    const preflopLog=(Array.isArray(snapshot.action_log)?snapshot.action_log:[])
      .filter(x=>upper(x&&x.street)==='PREFLOP')
      .map(x=>({player:text(x.player),action:upper(x.action),target_total_bb:finiteOrNull(x.target_total_bb),incremental_cost_bb:finiteOrNull(x.incremental_cost_bb)}));
    const pot=round(Object.values(total).reduce((s,x)=>s+Number(x||0),0));
    const actorPaid=Number(street[actor]||0),actorRemaining=Number(remaining[actor]||0);
    const currentPrice=finiteOrNull(snapshot.current_bet_bb)??Math.max(0,...Object.values(street).map(Number));
    const toCall=round(Math.max(0,currentPrice-actorPaid));
    const liveOpponents=seats.filter(p=>p!==actor&&!folded[p]);
    const actorTotal=actorRemaining+Number(total[actor]||0);
    const oppTotals=liveOpponents.map(p=>Number(remaining[p]||0)+Number(total[p]||0));
    const effective=round(Math.min(actorTotal,oppTotals.length?Math.max(...oppTotals):actorTotal));
    const legalView=wrapper.legal_view&&typeof wrapper.legal_view==='object'?wrapper.legal_view:{};
    const legalActions=Array.isArray(legalView.legal_actions)?legalView.legal_actions.map(upper):deriveCoreLegalActions({toCall,actorRemaining,currentPrice,actorPaid});
    const canonical={
      schema:SNAPSHOT_SCHEMA,
      seats:[...seats],
      button:text(snapshot.button)||null,
      small_blind_player:text(snapshot.small_blind_player)||null,
      big_blind_player:text(snapshot.big_blind_player)||null,
      small_blind_bb:finiteOrNull(snapshot.small_blind_bb),
      big_blind_bb:finiteOrNull(snapshot.big_blind_bb),
      stacks_bb:remaining,
      total_committed_bb:total,
      street_committed_bb:street,
      folded,all_in:allIn,
      street:'PREFLOP',
      current_bet_bb:round(currentPrice),
      last_full_raise_bb:finiteOrNull(snapshot.last_full_raise_bb),
      full_bet_established:Boolean(snapshot.full_bet_established),
      acted_since_full_raise:Array.isArray(snapshot.acted_since_full_raise)?snapshot.acted_since_full_raise.map(String).sort():[],
      pending,
      refunds_bb:refunds,
      preflop_action_log:preflopLog,
      actor,
      pot_before_action_bb:pot,
      actor_contribution_bb:round(actorPaid),
      actor_remaining_bb:round(actorRemaining),
      to_call_bb:toCall,
      effective_stack_bb:effective,
      legal_actions:legalActions,
      min_raise_to_bb:finiteOrNull(legalView.min_raise_to_bb),
      max_raise_to_bb:finiteOrNull(legalView.max_raise_to_bb),
      raise_reopened:legalView.raise_reopened==null?null:Boolean(legalView.raise_reopened)
    };
    return {canonical,wrapper,snapshot};
  }
  function deriveCoreLegalActions({toCall,actorRemaining,currentPrice,actorPaid}){
    const out=toCall>EPS?['FOLD','CALL']:['CHECK'];
    if(actorRemaining>toCall+EPS&&actorPaid+actorRemaining>currentPrice+EPS)out.push('RAISE');
    return out;
  }
  function sensitiveFieldsPresent(input,publicState){
    const found=[];
    const inspect=(obj,prefix)=>{
      if(!obj||typeof obj!=='object')return;
      for(const key of SENSITIVE_KEYS)if(Object.prototype.hasOwnProperty.call(obj,key)&&obj[key]!=null)found.push(prefix+key);
    };
    inspect(input,'input.');
    inspect(publicState,'public_state.');
    if(publicState&&publicState.snapshot)inspect(publicState.snapshot,'public_state.snapshot.');
    return unique(found);
  }

  function normalizeContext(input,guidance,publicNorm){
    const pc=input.preflop_context&&typeof input.preflop_context==='object'?input.preflop_context:{};
    const candidates=[
      text(input.context_id),text(pc.context_id),
      text(guidance&&guidance.public_snapshot&&guidance.public_snapshot.context_id),
      text(guidance&&guidance.evidence_decision&&guidance.evidence_decision.context_id)
    ].filter(Boolean);
    const uniqueIds=unique(candidates);
    const context_id=uniqueIds[0]||null;
    const mismatch=uniqueIds.length>1;
    const actor=publicNorm.canonical.actor;
    const heroPosition=upper(input.hero_position||pc.actor_position||pc.hero_position||(POSITION_NAMES.has(upper(actor))?actor:null))||'UNKNOWN';
    const family=upper(pc.family||input.facing_context)||'UNKNOWN';
    const facingAction=upper(input.facing_action||pc.facing_action)||deriveFacingAction(publicNorm.canonical);
    return {context_id,mismatch,hero_position:heroPosition,facing_context:family,facing_action:facingAction};
  }
  function deriveFacingAction(state){
    if(state.to_call_bb<=EPS)return state.preflop_action_log.length?'CHECK_OPTION':'UNOPENED';
    const rows=state.preflop_action_log.filter(x=>x.player!==state.actor);
    const last=rows.length?rows[rows.length-1]:null;
    if(!last)return 'PRICE';
    if(last.action==='RAISE')return 'RAISE';
    if(last.action==='CALL')return state.current_bet_bb<=Number(state.big_blind_bb||1)+EPS?'LIMP_OR_CALL':'CALL';
    return last.action||'PRICE';
  }

  function normalizeCoverage(input={}){
    const state=upper(input.state||input.coverage_state)||'ANALYSIS_MISSING';
    const tier=upper(input.support_tier||input.tier)||'UNKNOWN';
    const reasons=Array.isArray(input.reasons)?input.reasons.map(x=>text(x)).filter(Boolean):[];
    return {
      state:COVERAGE_STATES.includes(state)?state:'ANALYSIS_MISSING',
      support_tier:tier,
      supported_count:Number.isInteger(Number(input.supported_count))?Number(input.supported_count):null,
      decision_count:Number.isInteger(Number(input.decision_count))?Number(input.decision_count):null,
      coverage_ratio:finiteOrNull(input.coverage_ratio),
      reasons
    };
  }
  function observedTier(support){
    const n=support&&Number.isInteger(Number(support.observations))?Number(support.observations):null;
    if(n==null)return 'UNKNOWN';
    if(n>=1000)return 'VERY_HIGH';
    if(n>=100)return 'HIGH';
    if(n>=20)return 'MEDIUM';
    if(n>=1)return 'LOW';
    return 'SPARSE';
  }
  function tierFromSupport(support,tier){
    const declared=upper(tier)||'UNKNOWN',observed=observedTier(support);
    const rank={UNKNOWN:0,SPARSE:1,LOW:2,MEDIUM:3,HIGH:4,VERY_HIGH:5};
    if(declared==='UNKNOWN'||observed==='UNKNOWN')return 'UNKNOWN';
    return (rank[declared]??0)<=(rank[observed]??0)?declared:observed;
  }

  function validateGuidanceEvidence(evidence){
    if(!evidence||typeof evidence!=='object')throw new Error('guidance evidence_decision is required');
    if(evidence.schema!==SCHEMA)throw new Error('guidance evidence_decision schema mismatch');
    const alternatives=Array.isArray(evidence.alternatives)?evidence.alternatives:[];
    if(!alternatives.length)throw new Error('guidance evidence_decision alternatives are required');
    const selected=alternatives.find(x=>String(x.id)===String(evidence.selected_id));
    if(!selected)throw new Error('guidance selected_id was not evaluated');
    const scalar=[
      ['action',upper],['target_total_bb',finiteOrNull],['incremental_cost_bb',finiteOrNull],['ev_bb',finiteOrNull]
    ];
    for(const [key,norm] of scalar){
      const a=norm(evidence[key]),b=norm(selected[key]);
      if(typeof a==='number'||typeof b==='number'){
        if(a==null||b==null||Math.abs(a-b)>1e-6)throw new Error('guidance '+key+' does not match selected alternative');
      }else if(a!==b)throw new Error('guidance '+key+' does not match selected alternative');
    }
    const evs=alternatives.map(x=>finiteOrNull(x.ev_bb));
    if(evs.some(x=>x==null))throw new Error('guidance alternative EV is missing');
    if(finiteOrNull(selected.ev_bb)<Math.max(...evs)-EPS)throw new Error('guidance selected alternative is not maximal EV');
    if(text(evidence.ev_reference)!==(Decision&&Decision.EV_REFERENCE||'decision_point_incremental_bb'))throw new Error('guidance EV reference mismatch');
    return true;
  }

  function validateGuidanceForAdapter(guidance,identity,context,coverage,altComparability){
    const reasons=[];
    if(!guidance){
      reasons.push('NO_ADMISSIBLE_STRATEGY');
      if(!context.context_id)reasons.push('EXACT_CONTEXT_ABSENT');
      const status=!context.context_id?'EXACT_CONTEXT_ABSENT':'NO_ADMISSIBLE_STRATEGY';
      return {admissible:false,reasons:unique(reasons),surface:null,tier:coverage.support_tier||'UNKNOWN',status};
    }
    if(guidance.schema!==GUIDANCE_SCHEMA){
      reasons.push('INVALID_GUIDANCE');
      return {admissible:false,reasons,surface:null,status:'INVALID_GUIDANCE'};
    }
    const strategy=guidance.strategy||{};
    if(guidance.recommendation_state!=='PROMOTED'||strategy.state!=='PROMOTED'||guidance.default_advice!==true){
      reasons.push('NO_ADMISSIBLE_STRATEGY');
    }
    if(guidance.future_cards_consumed!==false)reasons.push('INVALID_GUIDANCE');
    if(text(strategy.population_id)&&text(strategy.population_id)!==identity.population_id)reasons.push('POPULATION_MISMATCH');
    if(text(guidance.public_snapshot&&guidance.public_snapshot.population_id)&&text(guidance.public_snapshot.population_id)!==identity.population_id)reasons.push('POPULATION_MISMATCH');
    if(text(strategy.strategy_id)&&text(strategy.strategy_id)!==identity.strategy_id)reasons.push('STRATEGY_MISMATCH');
    if(identity.strategy_sha256&&text(strategy.strategy_sha256).toLowerCase()!==identity.strategy_sha256)reasons.push('ARTIFACT_IDENTITY_MISMATCH');
    if(identity.decision_source_sha256&&text(strategy.decision_source_sha256).toLowerCase()!==identity.decision_source_sha256)reasons.push('ARTIFACT_IDENTITY_MISMATCH');
    if(!context.context_id)reasons.push('EXACT_CONTEXT_ABSENT');
    if(context.mismatch)reasons.push('EXACT_CONTEXT_MISMATCH');

    if(coverage.state!=='COVERED'){
      if(coverage.state==='LOW_SUPPORT')reasons.push('LOW_SUPPORT');
      else if(coverage.state==='UNSUPPORTED'||coverage.state==='UNCOVERED'||coverage.state==='ANALYSIS_MISSING')reasons.push('UNCOVERED');
      else if(coverage.state==='NON_COMPARABLE')reasons.push('NON_COMPARABLE_ALTERNATIVES');
    }

    let surface=null;
    try{
      validateGuidanceEvidence(guidance.evidence_decision);
      surface=Guidance.surfacePayload(guidance);
    }catch(_){reasons.push('INVALID_GUIDANCE');}
    if(surface&&surface.action==null)reasons.push('NO_ADMISSIBLE_STRATEGY');
    if(surface&&text(surface.ev_reference)&&text(surface.ev_reference)!==identity.ev_reference)reasons.push('ARTIFACT_IDENTITY_MISMATCH');
    const tier=tierFromSupport(surface&&surface.support,coverage.support_tier);
    if(LOW_TIERS.has(tier))reasons.push('LOW_SUPPORT');

    if(surface&&Array.isArray(surface.alternatives)){
      for(const alt of surface.alternatives){
        const meta=altComparability&&altComparability[alt.id];
        if(meta&&meta.comparable===false){reasons.push('NON_COMPARABLE_ALTERNATIVES');break;}
      }
    }
    const uniqueReasons=unique(reasons);
    const priority=[
      'INVALID_GUIDANCE','POPULATION_MISMATCH','STRATEGY_MISMATCH','ARTIFACT_IDENTITY_MISMATCH',
      'EXACT_CONTEXT_ABSENT','EXACT_CONTEXT_MISMATCH','LOW_SUPPORT','UNCOVERED',
      'NON_COMPARABLE_ALTERNATIVES','NO_ADMISSIBLE_STRATEGY'
    ];
    const status=uniqueReasons.length?(priority.find(x=>uniqueReasons.includes(x))||uniqueReasons[0]):'ADMISSIBLE';
    return {admissible:uniqueReasons.length===0,reasons:uniqueReasons,surface,tier,status};
  }

  function targetSizing(target){return target==null?null:{target_total_bb:round(target),bet_to_bb:round(target)};}
  function normalizePlayed(input){
    if(input==null)return {action:null,target_total_bb:null,alternative_id:null,ev_bb:null};
    if(typeof input==='string')return {action:upper(input),target_total_bb:null,alternative_id:null,ev_bb:null};
    return {
      action:upper(input.action)||null,
      target_total_bb:finiteOrNull(input.target_total_bb??input.bet_to_bb),
      alternative_id:text(input.alternative_id||input.id)||null,
      ev_bb:finiteOrNull(input.ev_bb)
    };
  }
  function sameSizing(a,b){
    if(a==null&&b==null)return true;
    if(a==null||b==null)return false;
    return Math.abs(Number(a)-Number(b))<=1e-6;
  }
  function alternativeRows(surface,altComparability){
    if(!surface||!Array.isArray(surface.alternatives))return [];
    return surface.alternatives.map(alt=>{
      const meta=altComparability&&altComparability[alt.id]||{};
      return {
        id:String(alt.id),
        action:upper(alt.action),
        target_sizing:targetSizing(alt.target_total_bb),
        incremental_cost_bb:finiteOrNull(alt.incremental_cost_bb),
        ev_bb:finiteOrNull(alt.ev_bb),
        uncertainty:clone(alt.uncertainty)||null,
        support:clone(alt.support)||null,
        confidence:finiteOrNull(alt.confidence),
        comparable:meta.comparable!==false,
        comparability_reason:meta.comparable===false?(text(meta.reason)||'NON_COMPARABLE'):null
      };
    });
  }
  function findPlayedAlternative(played,alternatives){
    if(!played.action)return null;
    if(played.alternative_id){
      const x=alternatives.find(a=>a.id===played.alternative_id);
      if(x&&x.action===played.action&&sameSizing(x.target_sizing&&x.target_sizing.target_total_bb,played.target_total_bb))return x;
    }
    const exact=alternatives.filter(a=>a.action===played.action&&sameSizing(a.target_sizing&&a.target_sizing.target_total_bb,played.target_total_bb));
    if(exact.length===1)return exact[0];
    if(played.target_total_bb==null){
      const sameAction=alternatives.filter(a=>a.action===played.action);
      if(sameAction.length===1)return sameAction[0];
    }
    return null;
  }

  function buildDecision(input={}){
    if(!Decision||!Guidance)throw new Error('preflop decision and guidance contracts are required');
    const identity=normalizeIdentity(input.identity||{});
    const publicNorm=normalizeSnapshot(input.public_state);
    const guidance=input.guidance||null;
    const context=normalizeContext(input,guidance,publicNorm);
    const coverage=normalizeCoverage(input.coverage||{});
    const checked=validateGuidanceForAdapter(guidance,identity,context,coverage,input.alternative_comparability||{});
    const sensitive=sensitiveFieldsPresent(input,input.public_state);
    const fingerprintBasis={
      public_state:publicNorm.canonical,
      context_id:context.context_id,
      hero_position:context.hero_position,
      facing_context:context.facing_context,
      facing_action:context.facing_action
    };
    const publicFingerprint='preflop-public:'+hash(stableStringify(fingerprintBasis));
    const played=normalizePlayed(input.played_action);
    const evidenceAlternatives=checked.admissible?alternativeRows(checked.surface,input.alternative_comparability||{}):[];
    const playedAlt=findPlayedAlternative(played,evidenceAlternatives);
    const playedEV=played.ev_bb!=null?played.ev_bb:(playedAlt&&playedAlt.comparable?playedAlt.ev_bb:null);
    const recommendedEV=checked.admissible?finiteOrNull(checked.surface.ev_bb):null;
    const comparable=Boolean(checked.admissible&&played.action&&playedAlt&&playedAlt.comparable&&playedEV!=null&&recommendedEV!=null);
    const delta=comparable?round(recommendedEV-playedEV):null;
    const supportTier=checked.tier||tierFromSupport(checked.surface&&checked.surface.support,coverage.support_tier);
    const recommendationReasons=[...checked.reasons];
    if(checked.admissible&&played.action&&!playedAlt)recommendationReasons.push('PLAYED_ALTERNATIVE_NOT_EVALUATED');
    const handId=text(input.hand_id)||null;
    const decisionId=text(input.decision_id)||('preflop-decision:'+hash(stableStringify({hand_id:handId,actor:publicNorm.canonical.actor,context_id:context.context_id,fingerprint:publicFingerprint})));
    const recommendedTarget=checked.admissible?finiteOrNull(checked.surface.target_total_bb):null;
    const selected=checked.admissible?evidenceAlternatives.find(x=>x.id===String(checked.surface.selected_id))||null:null;

    return {
      schema:SCHEMA,
      contract_profile:ADAPTER_PROFILE,
      decision_id:decisionId,
      hand_id:handId,
      timestamp:text(input.timestamp)||null,
      street:'PREFLOP',
      public_state_fingerprint:publicFingerprint,
      public_state:{
        actor:publicNorm.canonical.actor,
        legal_actions:[...publicNorm.canonical.legal_actions],
        to_call_bb:publicNorm.canonical.to_call_bb,
        current_bet_bb:publicNorm.canonical.current_bet_bb,
        actor_contribution_bb:publicNorm.canonical.actor_contribution_bb,
        actor_remaining_bb:publicNorm.canonical.actor_remaining_bb
      },
      context_id:context.context_id,
      hero_position:context.hero_position,
      effective_stack_bb:publicNorm.canonical.effective_stack_bb,
      pot_before_action_bb:publicNorm.canonical.pot_before_action_bb,
      facing_action:context.facing_action,
      facing_context:context.facing_context,
      played_action:played.action,
      played_target_sizing:targetSizing(played.target_total_bb),
      recommended_action:checked.admissible?upper(checked.surface.action):null,
      recommended_target_sizing:targetSizing(recommendedTarget),
      incremental_cost_bb:checked.admissible?finiteOrNull(checked.surface.incremental_cost_bb):null,
      recommended_ev_bb:recommendedEV,
      played_ev_bb:playedEV,
      delta_ev_bb:delta,
      ev_comparable:comparable,
      alternatives:evidenceAlternatives,
      coverage_state:coverage.state,
      support_tier:supportTier,
      support:checked.admissible?clone(checked.surface.support):null,
      recommendation_admissibility:{
        admissible:checked.admissible,
        status:checked.status,
        default_advice:checked.admissible,
        reason_codes:unique(recommendationReasons),
        source_guidance_schema:guidance&&guidance.schema||null,
        source_recommendation_state:guidance&&guidance.recommendation_state||null,
        selected_alternative_id:selected&&selected.id||null
      },
      reason_codes:unique(recommendationReasons),
      identity:{
        population_id:identity.population_id,
        pack_id:identity.pack_id,
        pack_version:identity.pack_version,
        strategy_id:identity.strategy_id,
        strategy_version:identity.strategy_version,
        strategy_sha256:identity.strategy_sha256,
        decision_source_sha256:identity.decision_source_sha256,
        ev_reference:identity.ev_reference
      },
      information_boundary:{
        public_only_fingerprint:true,
        future_cards_consumed:false,
        opponent_hole_cards_consumed:false,
        ignored_sensitive_fields:sensitive,
        fingerprint_excludes_board_and_private_cards:true
      }
    };
  }

  function surfaceBundle(decision){
    validateRuntimeDecision(decision);
    return {feed:decision,detail:decision,replayer:decision,trainer:decision,review:decision};
  }
  function validateRuntimeDecision(d){
    if(!d||d.schema!==SCHEMA||d.contract_profile!==ADAPTER_PROFILE)throw new Error('expected canonical runtime '+SCHEMA);
    if(d.street!=='PREFLOP')throw new Error('runtime decision street must be PREFLOP');
    if(d.recommendation_admissibility.admissible){
      if(!d.recommended_action||d.recommended_ev_bb==null)throw new Error('admissible decision requires recommendation and EV');
      if(d.coverage_state!=='COVERED')throw new Error('admissible decision must be COVERED');
    }else{
      if(d.recommended_action!=null||d.recommended_ev_bb!=null||d.recommended_target_sizing!=null||d.incremental_cost_bb!=null||d.alternatives.length)throw new Error('inadmissible decision must not expose recommendation evidence');
    }
    if(d.delta_ev_bb!=null&&!d.ev_comparable)throw new Error('delta_ev_bb requires comparable EVs');
    return true;
  }

  function toLeakDecisionEvent(decision,options={}){
    validateRuntimeDecision(decision);
    if(!Leak||typeof Leak.buildDecisionEvent!=='function')throw new Error('PokerLeakAnalyzer is required');
    const handId=text(decision.hand_id);if(!handId)throw new Error('hand_id is required for leak decision event');
    const timestamp=text(options.timestamp||decision.timestamp);if(!timestamp)throw new Error('timestamp is required for leak decision event');
    const covered=decision.recommendation_admissibility.admissible&&decision.coverage_state==='COVERED';
    const comparable=covered&&decision.ev_comparable;
    const playedTarget=decision.played_target_sizing&&decision.played_target_sizing.target_total_bb;
    const recTarget=decision.recommended_target_sizing&&decision.recommended_target_sizing.target_total_bb;
    return Leak.buildDecisionEvent({
      hand_id:handId,decision_id:decision.decision_id,timestamp,
      population_id:decision.identity.population_id,pack_id:decision.identity.pack_id,
      strategy_id:decision.identity.strategy_id,strategy_version:decision.identity.strategy_version,
      ev_reference:decision.identity.ev_reference,
      position:decision.hero_position,street:'PREFLOP',spot_family:decision.facing_context,context_id:decision.context_id,
      action_played:decision.played_action||'UNKNOWN',played_target_total_bb:playedTarget,
      action_recommended:decision.recommended_action||'UNKNOWN',recommended_target_total_bb:recTarget,
      played_ev_bb:comparable?decision.played_ev_bb:null,best_ev_bb:comparable?decision.recommended_ev_bb:null,
      uncertainty_bb:0,
      support:{covered,observations:decision.support&&decision.support.observations,source:'poker-preflop-decision/v1',reason:covered?null:decision.recommendation_admissibility.status},
      comparability:{comparable,reason:comparable?null:(covered?'NO_COMPARABLE_PLAYED_EV':decision.recommendation_admissibility.status)},
      played_is_all_in:['SHOVE','JAM'].includes(upper(decision.played_action)),
      notes:'canonical preflop decision adapter'
    });
  }
  function toCoverageInput(decision,options={}){
    return toLeakDecisionEvent(decision,options);
  }
  function toReviewDeepLink(decision){
    validateRuntimeDecision(decision);
    if(!decision.hand_id)return null;
    return {schema:'poker-review-deep-link/v1',kind:'REVIEW_DECISION',hand_id:decision.hand_id,decision_id:decision.decision_id,step_index:null,reason:'PREFLOP_DECISION'};
  }

  return {
    SCHEMA,ADAPTER_PROFILE,SNAPSHOT_SCHEMA,GUIDANCE_SCHEMA,COVERAGE_STATES,FAIL_CLOSED_STATES,
    buildDecision,validateRuntimeDecision,surfaceBundle,toLeakDecisionEvent,toCoverageInput,toReviewDeepLink
  };
});
