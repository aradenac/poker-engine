'use strict';

const assert=require('node:assert/strict');
const Game=require('../../src/training/nlhe-game-state.js');
const Runtime=require('../../src/training/preflop-runtime.js');

function sixMax(){
  const seats=['BTN','SB','BB','LJ','HJ','CO'];
  return new Game.NoLimitHoldemState({
    seats,button:'BTN',
    stacks_bb:Object.fromEntries(seats.map(x=>[x,100])),
    small_blind_bb:.5,big_blind_bb:1
  });
}

{
  const s=sixMax();
  assert.equal(s.next_actor,'LJ');
  assert.equal(s.pot_bb,1.5);
  assert.equal(s.stacks_bb.SB,99.5);
  assert.equal(s.stacks_bb.BB,99);
  assert.deepEqual(s.board,[]);
  const text=JSON.stringify(s.toSnapshot());
  assert.ok(!/hole|future_cards|opponent_hole/i.test(text),text);
  s.applyAction('LJ','CALL');
  s.applyAction('HJ','FOLD');
  s.applyAction('CO','FOLD');
  s.applyAction('BTN','CALL');
  s.applyAction('SB','CALL');
  const bb=s.legalView('BB');
  assert.equal(bb.to_call_bb,0);
  assert.deepEqual(bb.legal_actions,['CHECK','RAISE']);
  s.applyAction('BB','CHECK');
  assert.equal(s.betting_complete,true);
  s.advanceStreet(['As','Kd','2c']);
  assert.equal(s.street,'flop');
  assert.deepEqual(s.board,['As','Kd','2c']);
  assert.equal(s.next_actor,'SB');
}

{
  const s=sixMax();
  s.applyAction('LJ','FOLD');
  s.applyAction('HJ','RAISE',{target_total_bb:2.5});
  s.applyAction('CO','FOLD');
  assert.equal(s.next_actor,'BTN');
  const state={snapshot:s.toSnapshot(),legal_view:s.legalView('BTN')};
  const d=Runtime.buildCallFold({
    public_state:state,
    context_id:'ctx-covered-vs-rfi',
    preflop_context:{context_id:'ctx-covered-vs-rfi',family:'VS_RFI',actor_position:'BTN'},
    hero_position:'BTN',
    hand_id:'covered-1',
    call_ev_bb:.42,
    played_action:{action:'CALL',target_total_bb:2.5},
    samples:2000
  });
  assert.equal(d.schema,'poker-preflop-decision/v1');
  assert.equal(Runtime.isCovered(d),true);
  assert.equal(d.recommended_action,'CALL');
  assert.equal(d.recommended_target_sizing.target_total_bb,2.5);
  assert.equal(d.incremental_cost_bb,2.5);
  assert.equal(d.recommended_ev_bb,.42);
  assert.equal(d.played_ev_bb,.42);
  assert.equal(d.ev_comparable,true);
  assert.equal(d.identity.strategy_sha256,Runtime.REFERENCE.strategy_sha256);
  assert.equal(Runtime.REFERENCE.decision,'RETAIN_REFERENCE');
  assert.equal(Runtime.REFERENCE.candidate_activated,false);
  assert.equal(Runtime.assertRetainedReference(d),true);
  const bundle=Runtime.surfaceBundle(d);
  assert.strictEqual(bundle.feed,d);
  assert.strictEqual(bundle.detail,d);
  assert.strictEqual(bundle.replayer,d);
  assert.strictEqual(bundle.trainer,d);
  assert.strictEqual(bundle.review,d);
}

{
  const s=sixMax();
  s.applyAction('LJ','FOLD');
  s.applyAction('HJ','CALL');
  s.applyAction('CO','FOLD');
  s.applyAction('BTN','CALL');
  assert.equal(s.next_actor,'SB');
  const state={snapshot:s.toSnapshot(),legal_view:s.legalView('SB')};
  const ctx={context_id:'ctx-kts-sb-two-limp',family:'VS_LIMPERS',actor_position:'SB'};
  const d=Runtime.buildUnsupported({
    public_state:state,context_id:ctx.context_id,preflop_context:ctx,hero_position:'SB',
    hand_id:'uncovered-1',played_action:{action:'RAISE',target_total_bb:4},reason:'SPOT_NON_COUVERT'
  });
  assert.equal(Runtime.isCovered(d),false);
  assert.equal(d.coverage_state,'UNSUPPORTED');
  assert.equal(d.recommended_action,null);
  assert.equal(d.recommended_ev_bb,null);
  assert.equal(d.recommended_target_sizing,null);
  assert.equal(d.incremental_cost_bb,null);
  assert.deepEqual(d.alternatives,[]);
  assert.ok(d.reason_codes.includes('SPOT_NON_COUVERT'));
  assert.throws(()=>Runtime.buildCallFold({
    public_state:state,context_id:ctx.context_id,preflop_context:ctx,hero_position:'SB',call_ev_bb:.1
  }),/does not cover VS_LIMPERS/);
}

console.log(JSON.stringify({
  status:'PASS',
  game_state:Game.SNAPSHOT_SCHEMA,
  runtime_reference:Runtime.REFERENCE,
  covered:'VS_RFI CALL/FOLD',
  unsupported:'VS_LIMPERS'
}));
