#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
trainer = (ROOT / "site" / "trainer.js").read_text(encoding="utf-8")
contract = (ROOT / "site" / "hero-compliance.js").read_text(encoding="utf-8")
adapter = (ROOT / "site" / "hero-compliance-replayer.js").read_text(encoding="utf-8")
editor = (ROOT / "site" / "hero-ranges-app.js").read_text(encoding="utf-8")

marker = "/* Hero range compliance replayer bootstrap (#98) */"
assert marker in trainer, "replayer bundle does not load Hero compliance"
ordered = ["./hero-ranges.js", "./hero-compliance.js", "./hero-compliance-replayer.js"]
positions = [trainer.index(x, trainer.index(marker)) for x in ordered]
assert positions == sorted(positions), "Hero compliance dependencies must load in contract order"

storage_key = 'poker.hero.range.repository.v1'
assert storage_key in editor
assert storage_key in adapter, "replayer must consume the exact repository persisted by the editor"
assert "populationPreflopDecisionTrace" in adapter, "adapter must use the canonical before-action preflop trace"
assert "replayPreflopDecisionCount" in adapter, "adapter must respect current replay position"
assert "state.hhHands" in adapter and "summarize(rows)" in adapter, "session position/context summary is required"
assert "hand?.heroCards" in adapter, "only Hero hole cards known from the start may identify the Hero hand class"
assert "board" not in adapter.lower(), "Hero compliance adapter must not depend on future board cards"

assert "frequency_calibration_status:'NOT_EVALUATED_PER_SINGLE_DECISION'" in contract
assert "ev_deviation_bb:null" in contract and "ev_status:'NOT_EVALUATED'" in contract
assert "MIXED_ALLOWED" in contract
assert "UNCOVERED_HAND" in contract and "NO_VERDICT" in contract
assert "sizingCompliance" in contract

# The verdict is population-bound and fail-closed: it never evaluates a strategy
# from another population and it distinguishes a personal override from the
# calculated population strategy it is allowed to score.
assert "populationCompatibility" in contract, "compliance must gate on population compatibility"
assert "POPULATION_INCOMPATIBLE" in contract, "a foreign population must fail closed explicitly"
assert "STRATEGY_UNAVAILABLE" in contract, "an unresolved strategy must fail closed explicitly"
assert "PERSONAL_OVERRIDE" in contract and "STRATEGY_SOURCE" in contract, "override vs calculated source must be explicit"
assert "strategyResolution" in contract, "evaluateDecision must accept the resolved population strategy"

assert "PokerHeroStrategyResolver" in adapter and "resolveHeroStrategy" in adapter, "replayer must resolve the population strategy at runtime"
assert "strategyResolutionFor" in adapter, "replayer must expose its population-bound resolution"
assert "strategyResolution:resolution" in adapter, "replayer must forward the resolution to evaluateDecision"
assert "Origine de la stratégie" in adapter and "override personnel" in adapter, "the panel must report the personal override distinctly"

# #task-0jt: the replayer must forward the complete admission binding
# (role/hash/provenance/candidate/generation/binding) and the authoritative
# coverage bound when one is declared, instead of a bare {status,population_id}.
for marker in (
    "heroAdmissionFromProvenance",
    "role:'hero_strategy'",
    "declared_sha256",
    "actual_sha256",
    "source_path",
    "binding_sha256",
    "candidate_id",
    "generation_id",
    "artifact:{",
    "provenance:{",
    "required_context_keys",
    "generation_manifest",
):
    assert marker in adapter, f"replayer must transmit the admission binding: {marker}"
assert "status:provenance.status,population_id:provenance.population_id" not in adapter, (
    "the replayer must not forward a bare admission status token"
)
# The legacy reference declares its non-promotable binding tokens as explicit
# null: it is never fabricated into an admissible calculated strategy.
assert "provenance.candidate_id||null" in adapter
assert "provenance.generation_id||null" in adapter
assert "provenance.binding_sha256||null" in adapter

print("Hero compliance replayer integration: PASS")
