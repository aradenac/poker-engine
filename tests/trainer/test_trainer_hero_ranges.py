#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "site/assets/trainer/hero/custom_ranges_v1.json"
JS = (ROOT / "site/trainer.js").read_text(encoding="utf-8")

data = json.loads(ASSET.read_text(encoding="utf-8"))
assert data["schema"] == "trainer-hero-preflop-ranges/v1"
assert data["source"]["folder"] == "Custom"
assert data["source"]["sha256"] == "1248258112562757e49df545e97f9e54b2dde163fdc755adf0029e89e580e8cb"

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
assert 6 * pfa["BTN"]["33"] == 3.6
assert 4 * pfa["BTN"]["A2s"] == 4.0

required = [
    'hero:{ranges:"./assets/trainer/hero/custom_ranges_v1.json"}',
    'function trainerHeroRangeMap(role,position)',
    'function trainerHeroRangeAvailable(role,position)',
    'function trainerSampleHeroRangeCards(role,position,blocked=new Set())',
    'weights.push(weight)',
    '!trainerHeroRangeAvailable(heroRole,heroPos)',
    'heroCards=trainerSampleHeroRangeCards(heroRole,heroPos,blocked)',
]
for needle in required:
    assert needle in JS, f"missing Hero-range contract: {needle}"

assert 'hole[heroSeat]=[trainerDraw(deck),trainerDraw(deck)]' not in JS, "uniform Hero deal reintroduced"
print("trainer Hero custom-range contract: OK")
