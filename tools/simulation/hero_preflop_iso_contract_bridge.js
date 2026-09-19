#!/usr/bin/env node
'use strict';

const fs=require('node:fs');
const Core=require('../../src/training/nlhe-game-state.js');
const Alternatives=require('../../src/preflop/hero-preflop-alternatives.js');
const Diagnostics=require('../../src/preflop/iso-sizing-diagnostics.js');

function readInput(){
  const raw=fs.readFileSync(0,'utf8');
  return raw.trim()?JSON.parse(raw):{};
}
function clone(value){return value==null?value:JSON.parse(JSON.stringify(value));}

function hydrateState(snapshot){
  if(!snapshot||snapshot.schema!==Core.SNAPSHOT_SCHEMA)throw new Error('expected '+Core.SNAPSHOT_SCHEMA);
  const state=new Core.NoLimitHoldemState({
    seats:snapshot.seats,
    button:snapshot.button,
    stacks_bb:snapshot.starting_stacks_bb,
    small_blind_bb:snapshot.small_blind_bb,
    big_blind_bb:snapshot.big_blind_bb
  });
  state.small_blind_player=snapshot.small_blind_player;
  state.big_blind_player=snapshot.big_blind_player;
  state.starting_stacks_bb={...snapshot.starting_stacks_bb};
  state.stacks_bb={...snapshot.stacks_bb};
  state.total_committed_bb={...snapshot.total_committed_bb};
  state.street_committed_bb={...snapshot.street_committed_bb};
  state.folded={...snapshot.folded};
  state.all_in={...snapshot.all_in};
  state.street=String(snapshot.street);
  state.board=[...(snapshot.board||[])];
  state.current_bet_bb=Number(snapshot.current_bet_bb);
  state.last_full_raise_bb=Number(snapshot.last_full_raise_bb);
  state.full_bet_established=Boolean(snapshot.full_bet_established);
  state.acted_since_full_raise=new Set(snapshot.acted_since_full_raise||[]);
  state.pending=[...(snapshot.pending||[])];
  state.refunds_bb={...snapshot.refunds_bb};
  state.action_log=(snapshot.action_log||[]).map(row=>({...row}));
  return state;
}

function enumerate(input){
  const state=hydrateState(input.state_snapshot);
  let support=input.exact_support;
  if(!support&&input.issue319_report){
    support=Alternatives.supportViewFromIssue319Kts(input.issue319_report);
  }
  return Alternatives.enumerateHeroAlternatives({
    state,
    position_by_player:input.position_by_player||{},
    requested_raise_targets_bb:input.requested_raise_targets_bb||[],
    exact_support:support
  });
}

function diagnostics(input){
  const full=clone(input.decision);
  const evaluatedIds=new Set(input.evaluated_ids||[]);
  if(!full||!Array.isArray(full.alternatives))throw new Error('decision.alternatives required');
  if(!evaluatedIds.size)throw new Error('evaluated_ids required');
  if(!evaluatedIds.has(full.selected_id))throw new Error('selected_id must be evaluated');

  const reduced=clone(full);
  reduced.alternatives=full.alternatives.filter(row=>evaluatedIds.has(row.id));
  const base=Diagnostics.bridgePairedResult({
    decision:reduced,
    paired_result:input.paired_result,
    diagnostic_worlds:input.diagnostic_worlds
  });

  const rows=new Map(base.alternatives.map(row=>[row.alternative_id,row]));
  for(const alt of full.alternatives){
    if(rows.has(alt.id))continue;
    if(alt.action!=='ISO'||alt.support?.status!=='LEGAL_BUT_UNSUPPORTED'){
      throw new Error('non-evaluated alternative is not explicit LEGAL_BUT_UNSUPPORTED ISO: '+alt.id);
    }
    rows.set(alt.id,{
      alternative_id:alt.id,
      status:'UNSUPPORTED',
      caller_partition:null,
      expected_callers:null,
      p_3bet_or_jam:null,
      continuing_positions:null,
      posterior_refs:null,
      sample_count:0,
      world_count:0,
      support:clone(alt.support),
      provenance:{
        scientific_effect:Diagnostics.SCIENTIFIC_EFFECT,
        same_worlds_as_ev:false,
        source_mode:String(input.paired_result.mode||''),
        sample_indices:[],
        synthetic_fixture:Boolean(input.diagnostic_worlds.synthetic_fixture)
      }
    });
  }
  base.alternatives=full.alternatives.map(alt=>rows.get(alt.id));
  Diagnostics.validateArtifact(base,full);
  return {
    artifact:base,
    resolved:Diagnostics.resolveAgainstDecision(base,full)
  };
}

function main(){
  const command=process.argv[2];
  const input=readInput();
  let output;
  if(command==='enumerate')output=enumerate(input);
  else if(command==='diagnostics')output=diagnostics(input);
  else throw new Error('unknown command '+command);
  process.stdout.write(JSON.stringify(output));
}

try{main();}
catch(err){
  process.stderr.write((err&&err.stack?err.stack:String(err))+'\n');
  process.exit(2);
}
