#!/usr/bin/env node
'use strict';
const c=require('../../site/preflop-contract.js');
const ctx=c.buildContext({
  table_size:6,actor_position:'CO',live_positions:['LJ','HJ','CO','BTN','SB','BB'],
  history:[{position:'LJ',action:'RAISE'},{position:'HJ',action:'CALL'}],raise_level:1,
  contribution_bb_by_position:{LJ:2.5,HJ:2.5,CO:0,BTN:0,SB:.5,BB:1},
  stack_bb_by_position:{LJ:100,HJ:100,CO:100,BTN:100,SB:100,BB:100},
  pot_before_bb:7,current_price_bb:2.5,min_raise_to_bb:4
});
const raw={FOLD:.41,CALL:.37,RAISE:.18,JAM:.04,CHECK:.000123};
const out=c.incumbentV5Passthrough({context:ctx,raw_probabilities:raw,hand_class:'AQs',source:'fixture',backoff_level:'closest',confidence:'medium',support:123});
process.stdout.write(JSON.stringify(out));
