#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "site" / "trainer.js").read_text(encoding="utf-8")


def require(needle: str) -> None:
    assert needle in JS, f"missing preload contract: {needle}"


require('const TRAINER_DELAYS={street:20,opponentThink:35,opponentSettle:25};')
require('const TRAINER_POPULATION_MANIFEST="./assets/trainer/population.json";')
require('const trainerWarmAssets={started:false,promise:null,population:null')
require('async function trainerLoadWarmAssets()')
require('function trainerScheduleWarmup()')
require('requestIdleCallback')
require('trainerScheduleWarmup();')
require('const population=await trainerFetchJson(TRAINER_POPULATION_MANIFEST);')
require('trainerFetchJson(asset.hero.ranges)')
require('trainerWarmAssets.population=population')
require('trainerWarmAssets.heroRanges=heroRanges')
require('const alreadyWarm=!!(trainerWarmAssets.modelA&&trainerWarmAssets.modelB&&trainerWarmAssets.heroRanges),assets=await trainerLoadWarmAssets();')
require('trainerState.perf.warmHit=alreadyWarm;')
require('trainerState.perf.modelLoadMs=performance.now()-loadStarted;')
require('await trainerSleep(TRAINER_DELAYS.street);')
require('await trainerSleep(TRAINER_DELAYS.opponentThink);')
require('await trainerSleep(TRAINER_DELAYS.opponentSettle);')

# Old deliberate UI waits must not come back.
for old in ('trainerSleep(160)', 'trainerSleep(220)', 'trainerSleep(180)'):
    assert old not in JS, f"old artificial delay reintroduced: {old}"

# Warmup may fetch/parse the population pack and its assets, including the
# static Hero range, but must not eagerly mutate analyser Model A state.
warm_start = JS.index('async function trainerLoadWarmAssets()')
warm_end = JS.index('function trainerScheduleWarmup()', warm_start)
warm = JS[warm_start:warm_end]
assert 'applyPopulationModelSnapshot' not in warm
assert 'applyPostflopModelSnapshot' not in warm

print("trainer preload contract: OK")
