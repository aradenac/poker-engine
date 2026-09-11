#!/usr/bin/env python3
from pathlib import Path
import sys

src=Path(sys.argv[1]); dst=Path(sys.argv[2]) if len(sys.argv)>2 else src.with_name('poker_range_equity_offline_multiway_v80.html')
s=src.read_text(encoding='utf-8')

def one(old,new):
    global s
    if s.count(old)!=1: raise SystemExit(f'expected one match: {old[:80]}')
    s=s.replace(old,new,1)

one('<title>Poker Range Equity — Offline v79</title>','<title>Poker Range Equity — Offline v80</title>')
one('"all_aggression_penalty_bb":0}', '"all_aggression_penalty_bb":0,"pot_scale_mode":"capped_linear_to_training_mean","reference_pot_mean_bb":{"Flop":12.440409978741135,"Turn":15.728986141560712,"River":21.600333606037303}}')
one("  z+=Number(POSTFLOP_POLICY_CALIBRATION_V3.coefficients?.[key])||0;\n  const fam=postflopPolicyFamily(canonical),pot=Math.max(.01,Number(potBeforeBB)||.01),cost=Number(costBB),ratio=Number.isFinite(cost)?cost/pot:0;",
    "  const fam=postflopPolicyFamily(canonical),pot=Math.max(.01,Number(potBeforeBB)||.01),cost=Number(costBB),ratio=Number.isFinite(cost)?cost/pot:0;\n  const coeff=Number(POSTFLOP_POLICY_CALIBRATION_V3.coefficients?.[key])||0,refPot=Number(p.reference_pot_mean_bb?.[street]);\n  const coeffScale=Number.isFinite(refPot)&&refPot>0?Math.min(1,pot/refPot):1;\n  z+=coeff*coeffScale;")
one("'evtree-v79-finalev-sparse5-extreme10-p90-nojambonus'", "'evtree-v80-potscaled-finalev-sparse5-extreme10-p90'")
one('application:{name:"Poker Range Equity Offline",version:"v79"','application:{name:"Poker Range Equity Offline",version:"v80"')
one('/* v79 final-EV recommendation guard active */','/* v79 final-EV recommendation guard active */\n/* v80 pot-scaled residual calibration active */')
for needle in ['reference_pot_mean_bb','Math.min(1,pot/refPot)','version:"v80"']:
    if needle not in s: raise SystemExit(f'missing {needle}')
dst.write_text(s,encoding='utf-8')
print(dst)
