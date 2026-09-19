#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "site" / "trainer.js").read_text(encoding="utf-8")


def require(needle: str) -> None:
    assert needle in JS, f"missing latency contract: {needle}"


# Hidden-answer modes must not block Hero on a pre-action Model A run.
require('if(trainerState.mode==="guided")await trainerComputeRecommendation();')
require('else trainerRenderStatus("À vous de jouer · recommandation calculée après votre action.");')

# All heavy trainer evaluations go through the instrumented wrapper.
require('async function trainerTimedReviewText(text)')
require('trainerState.perf.evaluations++')
require('await trainerTimedReviewText(')
require('trainerComputePreflopReference')
require('referenceCallEV')

# Guided mode can reuse the already-computed best result for an exact matching action/sizing.
# The matcher is now context-aware because sizing-only labels such as "25% pot" need the
# current decision context to resolve to BET vs RAISE.
require('function trainerRecommendationKind(hand,rec)')
require('function trainerRecommendationMatchesAction(rec,actual,hand=trainerState.hand)')
require('function trainerReuseBestAsPlayed(rec)')
require('trainerState.perf.reused++')

# Prevent reintroduction of the old unconditional pre-action calculation.
old = 'trainerRender();await trainerComputeRecommendation();return;'
assert old not in JS, "unconditional pre-action Model A evaluation reintroduced"

print("trainer latency contract: OK")
