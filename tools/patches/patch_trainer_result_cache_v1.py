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

    old_constants = '''const TRAINER_DELAYS={street:20,opponentThink:35,opponentSettle:25};\nconst trainerWarmAssets={started:false,promise:null,modelA:null,modelB:null,startedAt:0,finishedAt:0,error:null};'''
    new_constants = '''const TRAINER_DELAYS={street:20,opponentThink:35,opponentSettle:25};\nconst TRAINER_REVIEW_CACHE_MAX=96;\nconst trainerWarmAssets={started:false,promise:null,modelA:null,modelB:null,startedAt:0,finishedAt:0,error:null};\nconst trainerReviewCache={entries:new Map(),preModel:null,postModel:null,hits:0,misses:0,evictions:0};'''
    text = replace_once(text, old_constants, new_constants, "cache constants")

    old_perf = '''  perf:{evaluations:0,reused:0,totalMs:0,lastMs:0,modelLoadMs:0,warmupMs:0,warmHit:false},'''
    new_perf = '''  perf:{evaluations:0,reused:0,totalMs:0,lastMs:0,modelLoadMs:0,warmupMs:0,warmHit:false,cacheHits:0,cacheMisses:0},'''
    text = replace_once(text, old_perf, new_perf, "cache perf metrics")

    old_timed = '''async function trainerTimedReviewText(text){\n  const started=performance.now();trainerState.perf.evaluations++;\n  try{return await trainerReviewText(text);}\n  finally{const ms=performance.now()-started;trainerState.perf.lastMs=ms;trainerState.perf.totalMs+=ms;}\n}\nasync function trainerReviewText(text){'''
    new_timed = '''function trainerReviewCacheClone(value){return JSON.parse(JSON.stringify(value));}\nfunction trainerReviewCacheNormalize(text){return String(text||"").replace(/Hand #\\d+/,"Hand #<trainer>");}\nfunction trainerReviewCacheEnsureModelIdentity(){\n  if(trainerReviewCache.preModel===state.populationModel&&trainerReviewCache.postModel===state.postflopModel)return;\n  trainerReviewCache.entries.clear();trainerReviewCache.preModel=state.populationModel;trainerReviewCache.postModel=state.postflopModel;\n}\nfunction trainerReviewCacheGet(text){\n  trainerReviewCacheEnsureModelIdentity();const key=trainerReviewCacheNormalize(text);\n  if(!trainerReviewCache.entries.has(key)){trainerReviewCache.misses++;trainerState.perf.cacheMisses++;return null;}\n  const value=trainerReviewCache.entries.get(key);trainerReviewCache.entries.delete(key);trainerReviewCache.entries.set(key,value);\n  trainerReviewCache.hits++;trainerState.perf.cacheHits++;return trainerReviewCacheClone(value);\n}\nfunction trainerReviewCacheSet(text,value){\n  trainerReviewCacheEnsureModelIdentity();const key=trainerReviewCacheNormalize(text),copy=trainerReviewCacheClone(value);\n  trainerReviewCache.entries.delete(key);trainerReviewCache.entries.set(key,copy);\n  while(trainerReviewCache.entries.size>TRAINER_REVIEW_CACHE_MAX){const oldest=trainerReviewCache.entries.keys().next().value;trainerReviewCache.entries.delete(oldest);trainerReviewCache.evictions++;}\n}\nasync function trainerTimedReviewText(text){\n  const started=performance.now(),cached=trainerReviewCacheGet(text);\n  if(cached){const ms=performance.now()-started;trainerState.perf.lastMs=ms;trainerState.perf.totalMs+=ms;return cached;}\n  trainerState.perf.evaluations++;\n  try{const result=await trainerReviewText(text);trainerReviewCacheSet(text,result);return result;}\n  finally{const ms=performance.now()-started;trainerState.perf.lastMs=ms;trainerState.perf.totalMs+=ms;}\n}\nasync function trainerReviewText(text){'''
    text = replace_once(text, old_timed, new_timed, "bounded exact-result cache")

    PATH.write_text(text, encoding="utf-8")
    print("patched trainer exact result cache issue #22")


if __name__ == "__main__":
    main()
