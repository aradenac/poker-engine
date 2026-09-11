#!/usr/bin/env python3
from pathlib import Path
import sys
src=Path(sys.argv[1]); dst=Path(sys.argv[2]) if len(sys.argv)>2 else src.with_name('poker_range_equity_offline_multiway_v83.html')
s=src.read_text(encoding='utf-8')
def one(old,new,label):
    global s
    n=s.count(old)
    if n!=1: raise SystemExit(f'{label}: expected 1 match, got {n}')
    s=s.replace(old,new,1)
one('<title>Poker Range Equity — Offline v82</title>','<title>Poker Range Equity — Offline v83</title>','title')
one("function postflopActorRemainingBB(stepIndex){const ctx=actionDecisionContext(stepIndex);if(!ctx)return NaN;const st=historyPlayerStackBB(ctx.hand,ctx.actor),paid=Number(ctx.before.state?.[ctx.actor]?.totalPaidBB)||0;return Number.isFinite(st)?Math.max(0,st-paid):NaN;}\nfunction postflopStreetRaiseState(stepIndex){",
"""function postflopActorRemainingBB(stepIndex){const ctx=actionDecisionContext(stepIndex);if(!ctx)return NaN;const st=historyPlayerStackBB(ctx.hand,ctx.actor),paid=Number(ctx.before.state?.[ctx.actor]?.totalPaidBB)||0;return Number.isFinite(st)?Math.max(0,st-paid):NaN;}
function postflopMaxOpponentEffectiveCostBB(stepIndex){
  const ctx=actionDecisionContext(stepIndex);if(!ctx)return NaN;
  const actorPaidStreet=Number(ctx.before.state?.[ctx.actor]?.streetPaidBB)||0;let best=NaN;
  for(const player of ctx.active||[]){
    if(!player||player.name===ctx.actor)continue;
    const start=historyPlayerStackBB(ctx.hand,player.name),paidTotal=Number(ctx.before.state?.[player.name]?.totalPaidBB)||0;
    if(!Number.isFinite(start))continue;
    const remaining=Math.max(0,start-paidTotal),paidStreet=Number(ctx.before.state?.[player.name]?.streetPaidBB)||0;
    if(!(remaining>1e-9))continue;
    const cost=Math.max(0,paidStreet+remaining-actorPaidStreet);
    if(!Number.isFinite(best)||cost>best)best=cost;
  }
  return best;
}
function postflopStreetRaiseState(stepIndex){""",'effective stack helper')
one("""  if(['bet','raise'].includes(ctx.step.actionType))add('action réelle',req.cost,'actual');
  if(Number.isFinite(remaining)&&remaining>0)add('jam',remaining,'jam');
  out.sort((a,b)=>a.costBB-b.costBB);return out.slice(0,9);""",
"""  if(['bet','raise'].includes(ctx.step.actionType))add('action réelle',req.cost,'actual');
  if(Number.isFinite(remaining)&&remaining>0){
    const oppCap=postflopMaxOpponentEffectiveCostBB(stepIndex),effectiveAllIn=Number.isFinite(oppCap)&&oppCap>0?Math.min(remaining,oppCap):remaining;
    const heroAllIn=effectiveAllIn>=remaining-1e-8;
    add(heroAllIn?'jam':'all-in effectif',effectiveAllIn,heroAllIn?'jam':'effective_allin');
  }
  out.sort((a,b)=>a.costBB-b.costBB);return out.slice(0,9);""",'effective all-in candidate')
one("if(l.includes('JAM'))return 'JAM';","if(l.includes('JAM')||l.includes('ALL-IN EFFECTIF'))return 'JAM';",'policy family')
one("'evtree-v82-effectivepot-lowp90-potscaled-finalev'","'evtree-v83-effective-allin-lowp90-finalev'",'cache signature')
one("version:'v82'","version:'v83'",'policy benchmark version')
one('version:"v82"','version:"v83"','AI export version')
one('/* v82 low-confidence extreme local-P90 guard active */','/* v82 low-confidence extreme local-P90 guard active */\n/* v83 effective all-in sizing candidate active */','marker')
for needle in ['postflopMaxOpponentEffectiveCostBB','all-in effectif','effective_allin','evtree-v83-effective-allin','version:"v83"']:
    if needle not in s: raise SystemExit('missing '+needle)
dst.write_text(s,encoding='utf-8'); print(dst)
