'use strict';

const assert=require('node:assert/strict');
const Decision=require('../../src/preflop/decision.js');
const Guidance=require('../../src/preflop/guidance.js');
const Adapter=require('../../src/training/preflop-decision-adapter.js');
const Leak=require('../../src/analytics/leak-analyzer.js');

const POP='pokerstars_nlhe_100-200_zoom_play_6max_v1';
const STRATEGY='hero-preflop-promoted-v1';
const VERSION='release-r1';
const SHA='a'.repeat(64);
const SOURCE_SHA='b'.repeat(64);
const IDENTITY={
  population_id:POP,pack_id:'zoom-pack',pack_version:'pack-v1',
  strategy_id:STRATEGY,strategy_version:VERSION,
  strategy_sha256:SHA,decision_source_sha256:SOURCE_SHA,
  ev_reference:'decision_point_incremental_bb'
};

function uncertainty(se=.05){
  return {
    monte_carlo:{standard_error_bb:se,samples:5000,method:'synthetic'},
    model:{lower_bb:-.2,upper_bb:.3,method:'synthetic',status:'ESTIMATED'}
  };
}
function support(n=150){return {observations:n,backoff_level:'EXACT',source:'SYNTHETIC'};}
function alt(id,action,target,cost,ev,n=150){
  return {id,action,target_total_bb:target,incremental_cost_bb:cost,ev_bb:ev,support:support(n),confidence:.8,uncertainty:uncertainty()};
}
function evidence({context_id,actor_contribution_bb=.5,selected,alternatives}){
  return Decision.buildDecision({
    context_id,population_id:POP,actor_contribution_bb,
    legal_actions:Array.from(new Set(alternatives.map(x=>x.action))),
    selected_id:selected,alternatives,
    search:{candidate_ids:alternatives.map(x=>x.id),sizing_grid_source:'synthetic',budget:1000,seed:'195'}
  });
}
function guidance(decision,state='PROMOTED',overrides={}){
  const strategy={
    state,strategy_id:STRATEGY,strategy_sha256:SHA,population_id:POP,
    source:'synthetic-promotion-registry',decision_source_sha256:SOURCE_SHA,
    ...(overrides.strategy||{})
  };
  return Guidance.buildGuidance({
    decision,
    strategy,
    public_snapshot:{
      street:'PREFLOP',context_id:decision.context_id,population_id:POP,hero_hand_class:'AQs',
      ...(overrides.public_snapshot||{})
    }
  });
}

function publicState(actor='BTN',opts={}){
  const seats=['LJ','HJ','CO','BTN','SB','BB'];
  const stacks=Object.fromEntries(seats.map(p=>[p,100]));
  const total=Object.fromEntries(seats.map(p=>[p,0]));
  const street=Object.fromEntries(seats.map(p=>[p,0]));
  const folded=Object.fromEntries(seats.map(p=>[p,false]));
  const allin=Object.fromEntries(seats.map(p=>[p,false]));
  total.SB=.5; street.SB=.5; stacks.SB=99.5;
  total.BB=1; street.BB=1; stacks.BB=99;
  for(const [p,v] of Object.entries(opts.contributions||{})){
    const old=street[p]||0;
    street[p]=v; total[p]=v; stacks[p]=100-v;
    if(v>=100)allin[p]=true;
    if(old>v)throw new Error('invalid fixture');
  }
  const current=opts.current_bet_bb==null?Math.max(...Object.values(street)):opts.current_bet_bb;
  const pending=opts.pending||[actor];
  const log=opts.action_log||[];
  return {
    snapshot:{
      schema:'nlhe-game-state/v1',seats,button:'BTN',small_blind_player:'SB',big_blind_player:'BB',
      small_blind_bb:.5,big_blind_bb:1,
      starting_stacks_bb:Object.fromEntries(seats.map(p=>[p,100])),
      stacks_bb:stacks,total_committed_bb:total,street_committed_bb:street,
      folded,all_in:allin,street:'preflop',board:[],
      current_bet_bb:current,last_full_raise_bb:opts.last_full_raise_bb==null?1:opts.last_full_raise_bb,
      full_bet_established:true,acted_since_full_raise:opts.acted_since_full_raise||[],
      pending,refunds_bb:Object.fromEntries(seats.map(p=>[p,0])),action_log:log
    },
    legal_view:{
      actor,pot_before_bb:Object.values(total).reduce((a,b)=>a+b,0),
      actor_street_contribution_bb:street[actor],actor_remaining_bb:stacks[actor],
      current_price_bb:current,to_call_bb:Math.max(0,current-street[actor]),
      legal_actions:opts.core_legal_actions||['FOLD','CALL','RAISE'],
      min_raise_to_bb:opts.min_raise_to_bb==null?Math.min(100,current+Math.max(1,opts.last_full_raise_bb||1)):opts.min_raise_to_bb,
      max_raise_to_bb:street[actor]+stacks[actor],raise_reopened:true
    }
  };
}

function buildCase({
  name,actor='BTN',family,context_id,decision,played_action=null,
  state=publicState(actor),coverage={state:'COVERED',support_tier:'HIGH'},
  guidanceState='PROMOTED',identity=IDENTITY,extra={}
}){
  const g=decision?guidance(decision,guidanceState):null;
  return Adapter.buildDecision({
    public_state:state,identity,guidance:g,played_action,coverage,
    preflop_context:{context_id,family,actor_position:actor},
    hand_id:'hand-'+name,timestamp:'2026-09-19T00:30:00Z',
    ...extra
  });
}

const cases=[
  {
    name:'unopened-open',actor:'CO',family:'UNOPENED',context_id:'ctx-unopened-co',
    state:publicState('CO',{core_legal_actions:['FOLD','CALL','RAISE']}),
    decision:evidence({
      context_id:'ctx-unopened-co',actor_contribution_bb:0,selected:'open-2.5',
      alternatives:[alt('fold','FOLD',null,0,0),alt('open-2.5','OPEN',2.5,2.5,1.2),alt('open-3','OPEN',3,3,1.1)]
    }),
    played_action:{action:'OPEN',target_total_bb:2.5}
  },
  {
    name:'limp-iso',actor:'BTN',family:'VS_LIMPERS',context_id:'ctx-limp-iso',
    state:publicState('BTN',{contributions:{CO:1},current_bet_bb:1,action_log:[{street:'preflop',player:'CO',action:'CALL',target_total_bb:1,incremental_cost_bb:1}]}),
    decision:evidence({
      context_id:'ctx-limp-iso',actor_contribution_bb:0,selected:'iso-5',
      alternatives:[alt('fold','FOLD',null,0,0),alt('call','CALL',1,1,.4),alt('iso-5','ISO',5,5,1.5)]
    }),
    played_action:{action:'CALL',target_total_bb:1}
  },
  {
    name:'squeeze',actor:'BB',family:'VS_RFI_CALLERS',context_id:'ctx-squeeze',
    state:publicState('BB',{contributions:{HJ:2.5,CO:2.5},current_bet_bb:2.5,action_log:[
      {street:'preflop',player:'HJ',action:'RAISE',target_total_bb:2.5,incremental_cost_bb:2.5},
      {street:'preflop',player:'CO',action:'CALL',target_total_bb:2.5,incremental_cost_bb:2.5}
    ]}),
    decision:evidence({
      context_id:'ctx-squeeze',actor_contribution_bb:1,selected:'sq-10',
      alternatives:[alt('fold','FOLD',null,0,0),alt('call','CALL',2.5,1.5,.3),alt('sq-10','SQUEEZE',10,9,1.7)]
    }),
    played_action:{action:'SQUEEZE',target_total_bb:10}
  },
  {
    name:'3bet',actor:'BTN',family:'VS_RFI',context_id:'ctx-3bet',
    state:publicState('BTN',{contributions:{HJ:2.5},current_bet_bb:2.5,action_log:[
      {street:'preflop',player:'HJ',action:'RAISE',target_total_bb:2.5,incremental_cost_bb:2.5}
    ]}),
    decision:evidence({
      context_id:'ctx-3bet',actor_contribution_bb:0,selected:'3b-8',
      alternatives:[alt('fold','FOLD',null,0,0),alt('call','CALL',2.5,2.5,.7),alt('3b-8','3BET',8,8,1.6)]
    }),
    played_action:{action:'CALL',target_total_bb:2.5}
  },
  {
    name:'4bet',actor:'CO',family:'OPENER_OR_ISO_VS_3BET',context_id:'ctx-4bet',
    state:publicState('CO',{contributions:{CO:2.5,BTN:8},current_bet_bb:8,action_log:[
      {street:'preflop',player:'CO',action:'RAISE',target_total_bb:2.5,incremental_cost_bb:2.5},
      {street:'preflop',player:'BTN',action:'RAISE',target_total_bb:8,incremental_cost_bb:8}
    ]}),
    decision:evidence({
      context_id:'ctx-4bet',actor_contribution_bb:2.5,selected:'4b-20',
      alternatives:[alt('fold','FOLD',null,0,0),alt('call','CALL',8,5.5,.5),alt('4b-20','4BET',20,17.5,1.8)]
    }),
    played_action:{action:'4BET',target_total_bb:20}
  },
  {
    name:'jam-calljam',actor:'BB',family:'VS_4BET',context_id:'ctx-jam',
    state:publicState('BB',{contributions:{CO:25},current_bet_bb:25,action_log:[
      {street:'preflop',player:'CO',action:'RAISE',target_total_bb:25,incremental_cost_bb:25}
    ]}),
    decision:evidence({
      context_id:'ctx-jam',actor_contribution_bb:1,selected:'calljam',
      alternatives:[alt('fold','FOLD',null,0,0),alt('calljam','CALL_SHOVE',100,99,2.1),alt('jam','SHOVE',100,99,2.0)]
    }),
    played_action:{action:'CALL_SHOVE',target_total_bb:100}
  }
];

for(const c of cases){
  const out=buildCase(c);
  assert.equal(out.schema,'poker-preflop-decision/v1',c.name);
  assert.equal(out.contract_profile,Adapter.ADAPTER_PROFILE,c.name);
  assert.equal(out.street,'PREFLOP',c.name);
  assert.equal(out.context_id,c.context_id,c.name);
  assert.equal(out.facing_context,c.family,c.name);
  assert.equal(out.recommendation_admissibility.admissible,true,c.name);
  assert.ok(out.recommended_action,c.name);
  assert.ok(out.recommended_ev_bb!=null,c.name);
  assert.ok(out.alternatives.length>=2,c.name);
  assert.equal(Adapter.validateRuntimeDecision(out),true,c.name);
}

{
  const out=buildCase(cases[3]);
  assert.equal(out.recommended_action,'3BET');
  assert.equal(out.recommended_target_sizing.target_total_bb,8);
  assert.equal(out.incremental_cost_bb,8);
  assert.equal(out.recommended_ev_bb,1.6);
  assert.equal(out.played_ev_bb,.7);
  assert.equal(out.delta_ev_bb,.9);
  assert.equal(out.ev_comparable,true);
  const a=out.alternatives.find(x=>x.id==='3b-8');
  assert.equal(a.target_sizing.target_total_bb,8);
  assert.equal(a.ev_bb,1.6);
  assert.equal(a.support.observations,150);
  assert.equal(a.uncertainty.monte_carlo.standard_error_bb,.05);
}

{
  const c=cases[0];
  const g=guidance(c.decision,'NO_VERDICT');
  const out=Adapter.buildDecision({
    public_state:c.state,identity:IDENTITY,guidance:g,played_action:c.played_action,
    coverage:{state:'COVERED',support_tier:'HIGH'},
    preflop_context:{context_id:c.context_id,family:c.family,actor_position:c.actor},hand_id:'no-strategy'
  });
  assert.equal(out.recommendation_admissibility.admissible,false);
  assert.ok(out.reason_codes.includes('NO_ADMISSIBLE_STRATEGY'));
  assert.equal(out.recommended_action,null);
  assert.equal(out.recommended_ev_bb,null);
  assert.equal(out.recommended_target_sizing,null);
  assert.equal(out.incremental_cost_bb,null);
  assert.deepEqual(out.alternatives,[]);
  assert.equal(out.played_action,'OPEN','Review played state must survive fail-closed advice');
}

{
  const c=cases[0];
  const out=buildCase({...c,coverage:{state:'UNSUPPORTED',support_tier:'UNKNOWN',reasons:['NO_EXACT_CONTEXT']}});
  assert.equal(out.recommendation_admissibility.admissible,false);
  assert.ok(out.reason_codes.includes('UNCOVERED'));
  assert.equal(out.recommended_action,null);
}

{
  const c=cases[0];
  const out=buildCase({...c,coverage:{state:'LOW_SUPPORT',support_tier:'LOW'}});
  assert.equal(out.recommendation_admissibility.admissible,false);
  assert.ok(out.reason_codes.includes('LOW_SUPPORT'));
  assert.equal(out.recommended_action,null);
}

{
  const c=cases[0];
  const out=buildCase({...c,identity:{...IDENTITY,population_id:'other-pop'}});
  assert.equal(out.recommendation_admissibility.admissible,false);
  assert.ok(out.reason_codes.includes('POPULATION_MISMATCH'));
  assert.equal(out.recommended_action,null);
}

{
  const c=cases[0];
  const out=buildCase({...c,identity:{...IDENTITY,strategy_id:'other-strategy'}});
  assert.equal(out.recommendation_admissibility.admissible,false);
  assert.ok(out.reason_codes.includes('STRATEGY_MISMATCH'));
}

{
  const c=cases[0];
  const out=buildCase({...c,identity:{...IDENTITY,strategy_sha256:'c'.repeat(64)}});
  assert.equal(out.recommendation_admissibility.admissible,false);
  assert.ok(out.reason_codes.includes('ARTIFACT_IDENTITY_MISMATCH'));
}

{
  const c=cases[0];
  const out=Adapter.buildDecision({
    public_state:c.state,identity:IDENTITY,guidance:guidance(c.decision),
    played_action:c.played_action,coverage:{state:'COVERED',support_tier:'HIGH'},
    preflop_context:{family:c.family,actor_position:c.actor},hand_id:'missing-context'
  });
  assert.equal(out.recommendation_admissibility.admissible,true,
    'guidance exact context is sufficient when caller does not redundantly provide context_id');
  assert.equal(out.context_id,c.context_id);
}

{
  const c=cases[0];
  const out=Adapter.buildDecision({
    public_state:c.state,identity:IDENTITY,guidance:guidance(c.decision),
    played_action:c.played_action,coverage:{state:'COVERED',support_tier:'HIGH'},
    preflop_context:{context_id:'other-context',family:c.family,actor_position:c.actor},hand_id:'bad-context'
  });
  assert.equal(out.recommendation_admissibility.admissible,false);
  assert.ok(out.reason_codes.includes('EXACT_CONTEXT_MISMATCH'));
}

{
  const c=cases[3];
  const out=buildCase({...c,extra:{alternative_comparability:{'3b-8':{comparable:false,reason:'MISSING_EXACT_EV'}}}});
  assert.equal(out.recommendation_admissibility.admissible,false);
  assert.ok(out.reason_codes.includes('NON_COMPARABLE_ALTERNATIVES'));
  assert.equal(out.recommended_action,null);
  assert.equal(out.delta_ev_bb,null);
}

{
  const c=cases[3];
  const out=buildCase({...c,played_action:{action:'CALL',target_total_bb:99}});
  assert.equal(out.recommendation_admissibility.admissible,true);
  assert.equal(out.played_ev_bb,null);
  assert.equal(out.delta_ev_bb,null);
  assert.equal(out.ev_comparable,false);
  assert.ok(out.reason_codes.includes('PLAYED_ALTERNATIVE_NOT_EVALUATED'));
}

{
  const c=cases[3];
  const base=buildCase(c);
  const contaminatedState=JSON.parse(JSON.stringify(c.state));
  contaminatedState.snapshot.board=['As','Kd','Qc','2h','3d'];
  contaminatedState.snapshot.future_cards=['4s','5s'];
  contaminatedState.snapshot.opponent_hole_cards={HJ:['Ah','Ad']};
  const contaminated=buildCase({...c,state:contaminatedState,extra:{
    future_cards:['7c','8c'],opponent_hole_cards:{HJ:['Kh','Ks']}
  }});
  assert.equal(contaminated.public_state_fingerprint,base.public_state_fingerprint,
    'future/opponent cards must not alter public-state fingerprint');
  assert.equal(contaminated.recommended_action,base.recommended_action);
  assert.equal(contaminated.recommended_ev_bb,base.recommended_ev_bb);
  assert.deepEqual(contaminated.recommended_target_sizing,base.recommended_target_sizing);
  assert.equal(contaminated.information_boundary.future_cards_consumed,false);
  assert.equal(contaminated.information_boundary.opponent_hole_cards_consumed,false);
  assert.ok(contaminated.information_boundary.ignored_sensitive_fields.some(x=>x.includes('future_cards')));
  assert.ok(contaminated.information_boundary.ignored_sensitive_fields.some(x=>x.includes('opponent_hole_cards')));
}

{
  const c=cases[2];
  const a=buildCase(c),b=buildCase(c);
  assert.deepEqual(a,b,'same canonical inputs must produce deterministic output');
  assert.equal(a.decision_id,b.decision_id);
  assert.equal(a.public_state_fingerprint,b.public_state_fingerprint);
}

{
  const d=buildCase(cases[3]);
  const bundle=Adapter.surfaceBundle(d);
  assert.deepEqual(bundle.feed,d);
  assert.deepEqual(bundle.detail,d);
  assert.deepEqual(bundle.replayer,d);
  assert.deepEqual(bundle.trainer,d);
  assert.deepEqual(bundle.review,d);
}

{
  const d=buildCase(cases[3]);
  const event=Adapter.toLeakDecisionEvent(d);
  assert.equal(event.schema,Leak.EVENT_SCHEMA);
  assert.equal(event.context.street,'PREFLOP');
  assert.equal(event.context.context_id,d.context_id);
  assert.equal(event.played.action,'CALL');
  assert.equal(event.recommended.action,'3BET');
  assert.equal(event.ev.played_bb,.7);
  assert.equal(event.ev.best_bb,1.6);
  assert.equal(event.ev.nominal_loss_bb,.9);
  assert.equal(event.support.covered,true);
  assert.equal(event.comparability.comparable,true);
  assert.deepEqual(Adapter.toCoverageInput(d),event);
  const link=Adapter.toReviewDeepLink(d);
  assert.equal(link.schema,'poker-review-deep-link/v1');
  assert.equal(link.hand_id,d.hand_id);
  assert.equal(link.decision_id,d.decision_id);
}

{
  const c=cases[0];
  const d=buildCase({...c,coverage:{state:'UNSUPPORTED',support_tier:'UNKNOWN'}});
  const event=Adapter.toLeakDecisionEvent(d,{timestamp:'2026-09-19T00:31:00Z'});
  assert.equal(event.support.covered,false);
  assert.equal(event.comparability.comparable,false);
  assert.equal(event.ev.attributed_loss_bb,0,'unsupported preflop must never become an EV leak');
  assert.equal(event.recommended.action,'UNKNOWN');
}

assert.throws(()=>Adapter.buildDecision({
  public_state:{...publicState('BTN').snapshot,street:'flop'},identity:IDENTITY
}),/requires PREFLOP/);

console.log(JSON.stringify({
  status:'PASS',
  schema:Adapter.SCHEMA,
  profile:Adapter.ADAPTER_PROFILE,
  families:cases.map(x=>x.family)
}));
