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

print("Hero compliance replayer integration: PASS")
