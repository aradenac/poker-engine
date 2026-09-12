#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "site" / "trainer.js").read_text(encoding="utf-8")


def require(needle: str) -> None:
    assert needle in JS, f"missing result-cache contract: {needle}"


require('const TRAINER_REVIEW_CACHE_MAX=96;')
require('const trainerReviewCache={entries:new Map()')
require('function trainerReviewCacheNormalize(text)')
require('replace(/Hand #\\d+/,"Hand #<trainer>")')
require('function trainerReviewCacheEnsureModelIdentity()')
require('trainerReviewCache.preModel===state.populationModel&&trainerReviewCache.postModel===state.postflopModel')
require('trainerReviewCache.entries.clear()')
require('function trainerReviewCacheGet(text)')
require('function trainerReviewCacheSet(text,value)')
require('while(trainerReviewCache.entries.size>TRAINER_REVIEW_CACHE_MAX)')
require('trainerReviewCache.evictions++')
require('const started=performance.now(),cached=trainerReviewCacheGet(text);')
require('trainerState.perf.evaluations++;')
require('trainerReviewCacheSet(text,result)')

# Cached verdicts must be copied so feedback mutation cannot corrupt future hits.
require('function trainerReviewCacheClone(value){return JSON.parse(JSON.stringify(value));}')

print("trainer result-cache contract: OK")
