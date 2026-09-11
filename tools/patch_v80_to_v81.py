#!/usr/bin/env python3
from pathlib import Path
import sys

src=Path(sys.argv[1]); dst=Path(sys.argv[2]) if len(sys.argv)>2 else src.with_name('poker_range_equity_offline_multiway_v81.html')
s=src.read_text(encoding='utf-8')

def one(old,new,label):
    global s
    n=s.count(old)
    if n!=1: raise SystemExit(f'{label}: expected 1 match, got {n}')
    s=s.replace(old,new,1)

one('<title>Poker Range Equity — Offline v80</title>','<title>Poker Range Equity — Offline v81</title>','title')
old="""    const responderCannotRaise=Number.isFinite(remaining)&&rawCall>=remaining-1e-8,effectiveActorCostBB=Math.max(0,Math.min(cost,paidStreet+callAmountBB-actorPaidBefore));
    const activePlayers=Math.max(1,liveNames.length),decision={player:player.name,street:current.street,street_start_players:current.street_start_players,active_players:activePlayers,relative_position:postflopRelativePosition(player.name,liveNames,ctx.hand),pot_type:current.pot_type,preflop_role:pf.roles[player.name]||'OTHER',street_history:history,mode:'FACING',action:'FOLD',board,board_features:bf,pot_before_bb:grossPotAfter,to_call_bb:callAmountBB,facing_price_pot:grossPotAfter>0?callAmountBB/grossPotAfter:0,facing_size_pot_original:potBefore>0?callAmountBB/potBefore:0,aggressor_size_pot_original:potBefore>0?cost/potBefore:0,own_size_pot:null,spr:grossPotAfter>0?remaining/grossPotAfter:0};"""
new="""    const responderCannotRaise=Number.isFinite(remaining)&&rawCall>=remaining-1e-8,effectiveActorCostBB=Math.max(0,Math.min(cost,paidStreet+callAmountBB-actorPaidBefore)),effectivePotAfter=potBefore+effectiveActorCostBB;
    const activePlayers=Math.max(1,liveNames.length),decision={player:player.name,street:current.street,street_start_players:current.street_start_players,active_players:activePlayers,relative_position:postflopRelativePosition(player.name,liveNames,ctx.hand),pot_type:current.pot_type,preflop_role:pf.roles[player.name]||'OTHER',street_history:history,mode:'FACING',action:'FOLD',board,board_features:bf,pot_before_bb:effectivePotAfter,to_call_bb:callAmountBB,facing_price_pot:effectivePotAfter>0?callAmountBB/effectivePotAfter:0,facing_size_pot_original:potBefore>0?callAmountBB/potBefore:0,aggressor_size_pot_original:potBefore>0?effectiveActorCostBB/potBefore:0,own_size_pot:null,spr:effectivePotAfter>0?remaining/effectivePotAfter:0};"""
one(old,new,'effective response pot')
one("responseMeta.push({name:player.name,nodeId:match.node.id,quality:match.quality,exact:match.exact,observations:Number(match.node.coverage?.population_decisions)||0,callAmountBB,effectiveActorCostBB,responderCannotRaise,facingSizePotOriginal:decision.facing_size_pot_original,facingPricePot:decision.facing_price_pot,",
    "responseMeta.push({name:player.name,nodeId:match.node.id,quality:match.quality,exact:match.exact,observations:Number(match.node.coverage?.population_decisions)||0,callAmountBB,effectiveActorCostBB,nominalActorCostBB:cost,effectiveAggressorSizePot:potBefore>0?effectiveActorCostBB/potBefore:0,responderCannotRaise,facingSizePotOriginal:decision.facing_size_pot_original,facingPricePot:decision.facing_price_pot,",'response diagnostics')
one("potType:current.pot_type,aggressorSizePot:potBefore>0?cost/potBefore:0};",
    "potType:current.pot_type,aggressorSizePot:potBefore>0?Math.min(cost,maxEffectiveCostBB)/potBefore:0,nominalAggressorSizePot:potBefore>0?cost/potBefore:0};",'effective support ratio')
one("'evtree-v80-potscaled-finalev-sparse5-extreme10-p90'","'evtree-v81-effectivepot-potscaled-finalev-sparse5-extreme10-p90'",'cache signature')
one("version:'v78'","version:'v81'",'policy benchmark version')
one('version:"v80"','version:"v81"','AI export version')
one('/* v80 pot-scaled residual calibration active */','/* v80 pot-scaled residual calibration active */\n/* v81 effective-stack response-pot correction active */','marker')
for needle in ['effectivePotAfter=potBefore+effectiveActorCostBB','nominalAggressorSizePot','evtree-v81-effectivepot','version:"v81"']:
    if needle not in s: raise SystemExit('missing '+needle)
dst.write_text(s,encoding='utf-8')
print(dst)
