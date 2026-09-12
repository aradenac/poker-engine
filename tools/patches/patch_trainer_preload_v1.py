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

    old_constants = '''const TRAINER_HERO="Hero";\n\nconst trainerState={'''
    new_constants = '''const TRAINER_HERO="Hero";\nconst TRAINER_DELAYS={street:20,opponentThink:35,opponentSettle:25};\nconst trainerWarmAssets={started:false,promise:null,modelA:null,modelB:null,startedAt:0,finishedAt:0,error:null};\n\nconst trainerState={'''
    text = replace_once(text, old_constants, new_constants, "preload constants")

    old_perf = '''  perf:{evaluations:0,reused:0,totalMs:0,lastMs:0},'''
    new_perf = '''  perf:{evaluations:0,reused:0,totalMs:0,lastMs:0,modelLoadMs:0,warmupMs:0,warmHit:false},'''
    text = replace_once(text, old_perf, new_perf, "performance metrics")

    old_fetch = '''async function trainerFetchText(url){\n  const r=await fetch(url,{cache:"force-cache"});\n  if(!r.ok)throw new Error(`${url} : HTTP ${r.status}`);\n  return r.text();\n}\n\nasync function trainerEnsureModels(){'''
    new_fetch = '''async function trainerFetchText(url){\n  const r=await fetch(url,{cache:"force-cache"});\n  if(!r.ok)throw new Error(`${url} : HTTP ${r.status}`);\n  return r.text();\n}\nasync function trainerLoadWarmAssets(){\n  if(trainerWarmAssets.promise)return trainerWarmAssets.promise;\n  trainerWarmAssets.started=true;trainerWarmAssets.startedAt=performance.now();\n  trainerWarmAssets.promise=(async()=>{\n    try{\n      const [profiles,ranges,actions,sizing,contract,preflop,postflop]=await Promise.all([\n        trainerFetchJson(TRAINER_ASSETS.modelB.profiles),trainerFetchJson(TRAINER_ASSETS.modelB.ranges),\n        trainerFetchJson(TRAINER_ASSETS.modelB.actions),trainerFetchJson(TRAINER_ASSETS.modelB.sizing),\n        trainerFetchJson(TRAINER_ASSETS.modelB.contract),trainerFetchText(TRAINER_ASSETS.modelA.preflop),\n        trainerFetchText(TRAINER_ASSETS.modelA.postflop)\n      ]);\n      trainerWarmAssets.modelB={profiles,ranges,actions,sizing,contract};\n      trainerWarmAssets.modelA={preflop,postflop};\n      trainerWarmAssets.finishedAt=performance.now();\n      trainerState.perf.warmupMs=trainerWarmAssets.finishedAt-trainerWarmAssets.startedAt;\n      return {modelA:trainerWarmAssets.modelA,modelB:trainerWarmAssets.modelB};\n    }catch(err){trainerWarmAssets.error=err;trainerWarmAssets.promise=null;throw err;}\n  })();\n  return trainerWarmAssets.promise;\n}\nfunction trainerScheduleWarmup(){\n  const start=()=>{if(!trainerWarmAssets.started)trainerLoadWarmAssets().catch(()=>{});};\n  if("requestIdleCallback" in window)window.requestIdleCallback(start,{timeout:2500});\n  else window.setTimeout(start,1200);\n}\n\nasync function trainerEnsureModels(){'''
    text = replace_once(text, old_fetch, new_fetch, "warm asset loader")

    old_ensure_prefix = '''  trainerState.loading=true;trainerState.error="";trainerRenderStatus("Chargement des modèles promus A/B…","busy");\n  try{\n    const [profiles,ranges,actions,sizing,contract]=await Promise.all([\n      trainerFetchJson(TRAINER_ASSETS.modelB.profiles),trainerFetchJson(TRAINER_ASSETS.modelB.ranges),\n      trainerFetchJson(TRAINER_ASSETS.modelB.actions),trainerFetchJson(TRAINER_ASSETS.modelB.sizing),\n      trainerFetchJson(TRAINER_ASSETS.modelB.contract)\n    ]);\n    if(profiles.schema!=="independent-opponent-profiles/v2"||ranges.schema!=="independent-preflop-ranges/v2"||actions.schema!=="independent-postflop-actions/v2"||sizing.schema!=="independent-postflop-sizing/v2")throw new Error("Model B : schéma inattendu.");\n    trainerState.modelB={profiles,ranges,actions,sizing,contract};\n\n    if(!state.populationModel){\n      const content=await trainerFetchText(TRAINER_ASSETS.modelA.preflop);\n      const ok=await applyPopulationModelSnapshot({name:"preflop_population_model_v5.json",content,size:content.length},{persist:false,restored:true});\n      if(!ok)throw new Error("Impossible d'initialiser Model A préflop.");\n    }\n    if(!state.postflopModel){\n      const content=await trainerFetchText(TRAINER_ASSETS.modelA.postflop);\n      const ok=await applyPostflopModelSnapshot({name:"postflop_population_model_v5.json",content,size:content.length},{persist:false,restored:true});\n      if(!ok)throw new Error("Impossible d'initialiser Model A postflop.");\n    }\n    trainerState.ready=true;\n    trainerRenderStatus("Trainer prêt · Model A v5 + Model B v2 chargés.");'''
    new_ensure_prefix = '''  trainerState.loading=true;trainerState.error="";trainerRenderStatus("Chargement des modèles promus A/B…","busy");\n  const loadStarted=performance.now();\n  try{\n    const alreadyWarm=!!(trainerWarmAssets.modelA&&trainerWarmAssets.modelB),assets=await trainerLoadWarmAssets();\n    trainerState.perf.warmHit=alreadyWarm;\n    const {profiles,ranges,actions,sizing,contract}=assets.modelB;\n    if(profiles.schema!=="independent-opponent-profiles/v2"||ranges.schema!=="independent-preflop-ranges/v2"||actions.schema!=="independent-postflop-actions/v2"||sizing.schema!=="independent-postflop-sizing/v2")throw new Error("Model B : schéma inattendu.");\n    trainerState.modelB=assets.modelB;\n\n    if(!state.populationModel){\n      const content=assets.modelA.preflop;\n      const ok=await applyPopulationModelSnapshot({name:"preflop_population_model_v5.json",content,size:content.length},{persist:false,restored:true});\n      if(!ok)throw new Error("Impossible d'initialiser Model A préflop.");\n    }\n    if(!state.postflopModel){\n      const content=assets.modelA.postflop;\n      const ok=await applyPostflopModelSnapshot({name:"postflop_population_model_v5.json",content,size:content.length},{persist:false,restored:true});\n      if(!ok)throw new Error("Impossible d'initialiser Model A postflop.");\n    }\n    trainerState.perf.modelLoadMs=performance.now()-loadStarted;\n    trainerState.ready=true;\n    trainerRenderStatus(`Trainer prêt · Model A v5 + Model B v2 · init ${trainerState.perf.modelLoadMs.toFixed(0)} ms${trainerState.perf.warmHit?" · assets préchargés":""}.`);'''
    text = replace_once(text, old_ensure_prefix, new_ensure_prefix, "ensure warm assets")

    text = text.replace('await trainerSleep(160);continue;', 'await trainerSleep(TRAINER_DELAYS.street);continue;', 1)
    text = text.replace('await trainerSleep(220);trainerOpponentAct(hand);trainerRender();await trainerSleep(180);', 'await trainerSleep(TRAINER_DELAYS.opponentThink);trainerOpponentAct(hand);trainerRender();await trainerSleep(TRAINER_DELAYS.opponentSettle);', 1)

    old_tail = '''document.querySelectorAll("[data-trainer-mode]").forEach(b=>b.addEventListener("click",()=>trainerSetMode(b.dataset.trainerMode)));\ntrainerRenderStatus("Ouvrez une session pour charger les modèles promus.");trainerRender();'''
    new_tail = '''document.querySelectorAll("[data-trainer-mode]").forEach(b=>b.addEventListener("click",()=>trainerSetMode(b.dataset.trainerMode)));\ntrainerScheduleWarmup();\ntrainerRenderStatus("Ouvrez une session pour charger les modèles promus.");trainerRender();'''
    text = replace_once(text, old_tail, new_tail, "idle warmup scheduling")

    PATH.write_text(text, encoding="utf-8")
    print("patched trainer preload/streamline issue #24")


if __name__ == "__main__":
    main()
