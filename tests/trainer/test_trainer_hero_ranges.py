#!/usr/bin/env python3
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "site/assets/trainer/hero/custom_ranges_v1.json"
PACK = ROOT / "site/assets/trainer/population.json"
JS = (ROOT / "site/trainer.js").read_text(encoding="utf-8")

data = json.loads(ASSET.read_text(encoding="utf-8"))
assert data["schema"] == "trainer-hero-preflop-ranges/v1"
assert data["source"]["folder"] == "Custom"
assert data["source"]["sha256"] == "1248258112562757e49df545e97f9e54b2dde163fdc755adf0029e89e580e8cb"

pack = json.loads(PACK.read_text(encoding="utf-8"))
assert pack["schema"] == "trainer-population-pack/v1"
assert pack["population_id"] == "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1"
assert pack["assets"]["hero"]["ranges"] == "./assets/trainer/hero/custom_ranges_v1.json"
assert ROOT / "site" / pack["assets"]["hero"]["ranges"].removeprefix("./") == ASSET

# The manifest exposes an explicit, population-bound, statuted Hero provenance.
provenance = pack["hero_provenance"]
assert provenance["schema"] == "trainer-hero-provenance/v1"
assert provenance["population_id"] == pack["population_id"]
assert provenance["strategy_id"] == pack["hero_strategy"] == "custom_ranges_v1"
assert provenance["source_type"] == "legacy_range_folder"
assert provenance["source"]["export_type"] == "range-folder"
assert provenance["source"]["folder"] == "Custom"
assert provenance["source"]["sha256"] == data["source"]["sha256"]
assert provenance["ranges_path"] == pack["assets"]["hero"]["ranges"]
assert provenance["sha256"] == hashlib.sha256(ASSET.read_bytes()).hexdigest()
assert provenance["status"] in {"RETAIN_REFERENCE", "PARTIAL"}
assert provenance["coverage_status"] == "PARTIAL"
assert provenance["admissible"] is False
assert provenance["promotable"] is False
# No misleading "Custom" strategy identity and no MIXED -> Zoom relabel.
assert pack["hero_strategy"] != "Custom"
assert provenance["strategy_id"] != "Custom"
assert pack["population_identity"]["format"] == "MIXED_ZOOM_REGULAR"
assert "zoom" not in provenance["population_id"]

expected_positions = {"BTN", "CO", "HJ", "LJ", "SB"}
assert set(data["ranges"]["PFA"]) == expected_positions
assert set(data["ranges"]["CALLER"]) == expected_positions
assert "BB" not in data["ranges"]["PFA"]
assert "BB" not in data["ranges"]["CALLER"]

pfa = data["ranges"]["PFA"]
caller = data["ranges"]["CALLER"]

# Representative source semantics, including mixed frequencies and exclusions.
assert pfa["BTN"]["33"] == 0.6
assert pfa["LJ"]["55"] == 0.3
assert "22" not in pfa["LJ"]
assert pfa["SB"]["A2o"] == 1.0
assert caller["BTN"]["33"] == 0.6
assert "99" not in caller["BTN"]  # 3-bet-only in VS Opening, never an SRP-call deal.
assert caller["CO"]["22"] == 0.1
assert caller["LJ"]["AQo"] == 1.0

# Exact-combo enumeration + class frequency means combo multiplicity is naturally respected.
# Example: BTN PFA 33 contributes 6 combos * 0.6, while A2s contributes 4 combos * 1.0.
assert math.isclose(6 * pfa["BTN"]["33"], 3.6)
assert math.isclose(4 * pfa["BTN"]["A2s"], 4.0)

required = [
    'TRAINER_POPULATION_MANIFEST="./assets/trainer/population.json"',
    'trainerFetchJson(asset.hero.ranges)',
    'function trainerHeroRangeMap(role,position)',
    'function trainerHeroRangeAvailable(role,position)',
    'function trainerSampleHeroRangeCards(role,position,blocked=new Set())',
    'weights.push(weight)',
    '!trainerHeroRangeAvailable(heroRole,heroPos)',
    'heroCards=trainerSampleHeroRangeCards(heroRole,heroPos,blocked)',
    'const deck=trainerShuffle(Array.from({length:52},(_,i)=>i).filter(c=>!blocked.has(c)));',
]
for needle in required:
    assert needle in JS, f"missing Hero-range contract: {needle}"

assert 'hole[heroSeat]=[trainerDraw(deck),trainerDraw(deck)]' not in JS, "uniform Hero deal reintroduced"
assert 'const remaining=deck.filter(c=>!blocked.has(c))' not in JS, "removed Hero deck was reused"
print("trainer Hero custom-range contract: OK")
