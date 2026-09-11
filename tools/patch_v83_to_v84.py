#!/usr/bin/env python3
from pathlib import Path
import sys
src=Path(sys.argv[1]); dst=Path(sys.argv[2]) if len(sys.argv)>2 else src.with_name('poker_range_equity_offline_multiway_v84.html')
s=src.read_text(encoding='utf-8')
def one(old,new,label):
    global s
    n=s.count(old)
    if n!=1: raise SystemExit(f'{label}: expected 1 match, got {n}')
    s=s.replace(old,new,1)
one('<title>Poker Range Equity — Offline v83</title>','<title>Poker Range Equity — Offline v84</title>','title')
one("""  const remaining=postflopActorRemainingBB(stepIndex),cap=Number.isFinite(remaining)?remaining:Math.max(Math.max(req.cost,1)*8,req.potBefore*4),out=[];
  const add=(label,cost,kind='candidate')=>{cost=Math.max(0,Math.min(cap,Number(cost)||0));if(!(cost>1e-6))return;if(out.some(x=>Math.abs(x.costBB-cost)<Math.max(.03,.015*cost)))return;out.push({label,costBB:cost,kind});};
  if(ctx.step.actionType==='bet'||ctx.step.actionType==='check'){
    const minBet=Math.min(cap,Math.max(1,0.05*req.potBefore));
    for(const f of [.25,.33,.50,.66,.75,1,1.25])add(`${Math.round(f*100)}% pot`,Math.max(minBet,f*req.potBefore));
  }else{""",
"""  const remaining=postflopActorRemainingBB(stepIndex),cap=Number.isFinite(remaining)?remaining:Math.max(Math.max(req.cost,1)*8,req.potBefore*4),out=[];
  const oppCap=postflopMaxOpponentEffectiveCostBB(stepIndex),effectiveAllIn=Number.isFinite(remaining)&&Number.isFinite(oppCap)&&oppCap>0?Math.min(remaining,oppCap):remaining;
  const add=(label,cost,kind='candidate')=>{cost=Math.max(0,Math.min(cap,Number(cost)||0));if(!(cost>1e-6))return;if(out.some(x=>Math.abs(x.costBB-cost)<Math.max(.03,.015*cost)))return;out.push({label,costBB:cost,kind});};
  if(ctx.step.actionType==='bet'||ctx.step.actionType==='check'){
    const minBet=Math.min(cap,Math.max(1,0.05*req.potBefore));
    for(const f of [.25,.33,.50,.66,.75,1,1.25,1.5,2,3])add(`${Math.round(f*100)}% pot`,Math.max(minBet,f*req.potBefore));
    if(Number.isFinite(effectiveAllIn)&&req.potBefore>0&&effectiveAllIn>3*req.potBefore){
      for(const share of [.5,.75]){
        const c=effectiveAllIn*share,r=c/req.potBefore;
        if(r>3.05)add(`${Math.round(r*100)}% pot`,c,'adaptive_overbet');
      }
    }
  }else{""",'overbet grid')
one("""  if(Number.isFinite(remaining)&&remaining>0){
    const oppCap=postflopMaxOpponentEffectiveCostBB(stepIndex),effectiveAllIn=Number.isFinite(oppCap)&&oppCap>0?Math.min(remaining,oppCap):remaining;
    const heroAllIn=effectiveAllIn>=remaining-1e-8;
    add(heroAllIn?'jam':'all-in effectif',effectiveAllIn,heroAllIn?'jam':'effective_allin');
  }
  out.sort((a,b)=>a.costBB-b.costBB);return out.slice(0,9);""",
"""  if(Number.isFinite(remaining)&&remaining>0){
    const allInCost=Number.isFinite(effectiveAllIn)&&effectiveAllIn>0?effectiveAllIn:remaining,heroAllIn=allInCost>=remaining-1e-8;
    add(heroAllIn?'jam':'all-in effectif',allInCost,heroAllIn?'jam':'effective_allin');
  }
  out.sort((a,b)=>a.costBB-b.costBB);return out.slice(0,14);""",'all-in reuse and candidate cap')
one("'evtree-v83-effective-allin-lowp90-finalev'","'evtree-v84-overbet-grid-effective-allin-finalev'",'cache signature')
one("version:'v83'","version:'v84'",'policy benchmark version')
one('version:"v83"','version:"v84"','AI export version')
one('/* v83 effective all-in sizing candidate active */','/* v83 effective all-in sizing candidate active */\n/* v84 intermediate/adaptive overbet grid active */','marker')
for needle in ['adaptive_overbet','for(const f of [.25,.33,.50,.66,.75,1,1.25,1.5,2,3])','evtree-v84-overbet-grid','version:"v84"']:
    if needle not in s: raise SystemExit('missing '+needle)
dst.write_text(s,encoding='utf-8'); print(dst)
