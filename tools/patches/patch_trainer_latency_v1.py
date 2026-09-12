#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "site" / "trainer.js"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    old_state = '''  pauseAfterDecision:false,busy:false,\n  session:{hands:0,decisions:0,good:0,close:0,poor:0,lossBB:0,breakdown:Object.create(null)},\n  testLog:[]\n};'''
    new_state = '''  pauseAfterDecision:false,busy:false,\n  perf:{evaluations:0,reused:0,totalMs:0,lastMs:0},\n  session:{hands:0,decisions:0,good:0,close:0,poor:0,lossBB:0,breakdown:Object.create(null)},\n  testLog:[]\n};'''
    text = replace_once(text, old_state, new_state, "trainerState perf")

    old_wait = '''async function trainerWaitFor(fn,timeout=30000){const start=Date.now();while(!fn()){if(Date.now()-start>timeout)throw new Error("Timeout du moteur de recommandation.");await trainerSleep(40);}}\nasync function trainerReviewText(text){'''
    new_wait = '''async function trainerWaitFor(fn,timeout=30000){const start=Date.now();while(!fn()){if(Date.now()-start>timeout)throw new Error("Timeout du moteur de recommandation.");await trainerSleep(40);}}\nasync function trainerTimedReviewText(text){\n  const started=performance.now();trainerState.perf.evaluations++;\n  try{return await trainerReviewText(text);}\n  finally{const ms=performance.now()-started;trainerState.perf.lastMs=ms;trainerState.perf.totalMs+=ms;}\n}\nasync function trainerReviewText(text){'''
    text = replace_once(text, old_wait, new_wait, "timed review helper")

    old_compute = '''  try{const ph=trainerPlaceholderLine(hand),detail=await trainerReviewText(trainerBuildReviewHH(hand,ph.line,ph.kind,0));trainerState.recommendation=detail;trainerRenderStatus("À vous de jouer.");}'''
    new_compute = '''  try{const ph=trainerPlaceholderLine(hand),detail=await trainerTimedReviewText(trainerBuildReviewHH(hand,ph.line,ph.kind,0));trainerState.recommendation=detail;trainerRenderStatus(`À vous de jouer · calcul ${trainerState.perf.lastMs.toFixed(0)} ms.`);}'''
    text = replace_once(text, old_compute, new_compute, "guided recommendation timing")

    old_hero = '''async function trainerHeroAction(kind,cost=0){\n  const hand=trainerState.hand;if(!hand||hand.ended||!hand.awaitingHero||trainerState.busy||trainerState.pauseAfterDecision)return;\n  trainerState.busy=true;hand.awaitingHero=false;trainerRenderStatus("Évaluation de votre décision…","busy");trainerRender();\n  let detail=null,row=null,actual=null;\n  try{actual=trainerActualLine(hand,kind,cost);detail=await trainerReviewText(trainerBuildReviewHH(hand,actual.line,actual.kind,actual.cost));row=trainerRecordDecision(detail,actual.kind,actual.cost);}\n  catch(err){trainerRenderStatus(`Décision jouée, mais verdict indisponible : ${err.message}`,"error");}\n  trainerApplyAction(hand,hand.heroSeat,kind,cost);trainerState.feedback=detail?{detail,row}:null;trainerState.busy=false;\n  if(hand.ended){trainerRenderStatus(`Main terminée · ${hand.winner}.`);trainerRender();return;}\n  if(trainerState.mode==="test"){trainerState.feedback=null;trainerRender();await trainerAdvance();}\n  else{trainerState.pauseAfterDecision=true;trainerRenderStatus("Feedback disponible. Continuez lorsque vous êtes prêt.");trainerRender();}\n}'''
    new_hero = '''function trainerRecommendationMatchesAction(rec,actual){\n  if(!rec||rec.error||!actual)return false;\n  const label=String(rec.bestLabel||"").toUpperCase(),kind=String(actual.kind||"").toUpperCase();\n  if(!label.startsWith(kind))return false;\n  if(!["BET","RAISE"].includes(kind))return true;\n  const bestCost=Number(rec.bestCostBB),playedCost=Number(actual.cost);\n  return Number.isFinite(bestCost)&&Number.isFinite(playedCost)&&Math.abs(bestCost-playedCost)<=0.05;\n}\nfunction trainerReuseBestAsPlayed(rec){\n  const d=JSON.parse(JSON.stringify(rec));\n  d.chosenEV=Number(d.bestEV);d.lossBB=0;d.withinNoise=true;\n  trainerState.perf.reused++;return d;\n}\nasync function trainerHeroAction(kind,cost=0){\n  const hand=trainerState.hand;if(!hand||hand.ended||!hand.awaitingHero||trainerState.busy||trainerState.pauseAfterDecision)return;\n  trainerState.busy=true;hand.awaitingHero=false;trainerRenderStatus("Évaluation de votre décision…","busy");trainerRender();\n  let detail=null,row=null,actual=null;\n  try{\n    actual=trainerActualLine(hand,kind,cost);\n    if(trainerState.mode==="guided"&&trainerRecommendationMatchesAction(trainerState.recommendation,actual)){\n      detail=trainerReuseBestAsPlayed(trainerState.recommendation);\n    }else{\n      detail=await trainerTimedReviewText(trainerBuildReviewHH(hand,actual.line,actual.kind,actual.cost));\n    }\n    trainerState.recommendation=detail;row=trainerRecordDecision(detail,actual.kind,actual.cost);\n  }\n  catch(err){trainerRenderStatus(`Décision jouée, mais verdict indisponible : ${err.message}`,"error");}\n  trainerApplyAction(hand,hand.heroSeat,kind,cost);trainerState.feedback=detail?{detail,row}:null;trainerState.busy=false;\n  if(hand.ended){trainerRenderStatus(`Main terminée · ${hand.winner}.`);trainerRender();return;}\n  if(trainerState.mode==="test"){trainerState.feedback=null;trainerRender();await trainerAdvance();}\n  else{trainerState.pauseAfterDecision=true;const suffix=trainerState.perf.lastMs?` · dernier calcul ${trainerState.perf.lastMs.toFixed(0)} ms`:"";trainerRenderStatus(`Feedback disponible${suffix}. Continuez lorsque vous êtes prêt.`);trainerRender();}\n}'''
    text = replace_once(text, old_hero, new_hero, "single-evaluation hero action")

    old_advance = '''    if(seat===hand.heroSeat){hand.awaitingHero=true;hand.decisionNo++;trainerState.feedback=null;trainerState.recommendation=null;trainerRender();await trainerComputeRecommendation();return;}'''
    new_advance = '''    if(seat===hand.heroSeat){\n      hand.awaitingHero=true;hand.decisionNo++;trainerState.feedback=null;trainerState.recommendation=null;\n      trainerRender();\n      if(trainerState.mode==="guided")await trainerComputeRecommendation();\n      else trainerRenderStatus("À vous de jouer · recommandation calculée après votre action.");\n      return;\n    }'''
    text = replace_once(text, old_advance, new_advance, "defer hidden recommendation")

    PATH.write_text(text, encoding="utf-8")
    print("patched trainer latency issue #21")


if __name__ == "__main__":
    main()
