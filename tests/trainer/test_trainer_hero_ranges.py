#!/usr/bin/env python3
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "site/assets/trainer/hero/custom_ranges_v1.json"
PACK = ROOT / "site/assets/trainer/population.json"
JS = (ROOT / "site/trainer.js").read_text(encoding="utf-8")
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")
HERO_HTML = (ROOT / "site/hero-ranges.html").read_text(encoding="utf-8")
HERO_APP = (ROOT / "site/hero-ranges-app.js").read_text(encoding="utf-8")

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


def check_hero_ranges_mode_contract() -> None:
    """#394 T6 — the standalone editor is the Stratégie Hero mode of the Accueil.

    The mode entry opens `hero-ranges.html` with a stable deep link built from
    the active population, the editor offers a coherent return to the Accueil and
    keeps its own deep link current, and the Home banner still carries the
    compact active-strategy/source identity.
    """
    home = INDEX.split('<div id="homePage"', 1)[1].split('<div id="mainPage"', 1)[0]

    # 1. Home exposes Stratégie Hero as a mode whose surface is the editor page.
    mode_card = '<a class="mode-card" data-app-view="strategy" data-hero-ranges-entry href="./hero-ranges.html">'
    assert mode_card in home, "the Stratégie Hero mode card must open hero-ranges.html"
    assert '<span class="mode-card-title">Stratégie Hero</span>' in home
    assert home.count('class="mode-card"') == 5, home
    # The in-app view switch must not swallow the editor navigation.
    cards_handler = INDEX.split('document.querySelectorAll(".mode-card[data-app-view]").forEach', 1)[1].split(
        'document.querySelectorAll("[data-home-back]")', 1
    )[0]
    assert 'if(card.tagName==="A"&&card.getAttribute("href")) return;' in cards_handler, cards_handler
    assert "openAppView(view,{scrollTop:true});" in cards_handler, cards_handler

    # 2. Every Accueil entry point carries a deep link derived from the active
    # population instead of the editor's own default population.
    assert "function heroRangesDeepLinkHref()" in INDEX
    assert "function syncHeroRangesDeepLinks()" in INDEX
    assert 'params.set("population",population)' in INDEX
    assert 'document.querySelectorAll("[data-hero-ranges-entry]")' in INDEX
    assert "heroRangesOpenBtn,strategyPageEditorLink" in INDEX
    assert 'params.set("position"' in INDEX and 'params.set("stack"' in INDEX
    assert 'params.set("spot"' in INDEX and "window.PokerHeroRanges?.SPOTS" in INDEX
    assert 'return query?`./hero-ranges.html?${query}`:"./hero-ranges.html";' in INDEX
    identity_ui = INDEX.split("function updateProductIdentityUi(){", 1)[1].split("\nasync function", 1)[0]
    assert "syncHeroRangesDeepLinks();" in identity_ui, "identity refresh must refresh the deep links"
    strategy_page = INDEX.split('<div id="strategyPage"', 1)[1].split('<div id="trainerPage"', 1)[0]
    assert 'id="strategyPageEditorLink"' in strategy_page and 'href="./hero-ranges.html"' in strategy_page, strategy_page

    # 3. The Accueil banner keeps the compact active strategy + source identity.
    banner = INDEX.split('<div class="home-banner"', 1)[1].split('<div class="mode-cards"', 1)[0]
    for element_id in ("activePopulationIdentity", "activeStrategyIdentity", "activeStrategySourceIdentity"):
        assert f'id="{element_id}"' in banner, element_id
    assert "const strategy=productHeroStrategyIdentityText(resolution);" in INDEX
    assert "activeStrategySourceIdentity.textContent=`${strategy.source} · version ${strategy.version}`" in INDEX

    # 4. The editor has a coherent return to the Accueil, not a dangling label.
    assert '<a id="heroRangesBack" class="back" href="./index.html" data-return-view="home"' in HERO_HTML
    assert 'aria-label="Retour à l’Accueil">← Accueil</a>' in HERO_HTML
    assert "← Strategy</a>" not in HERO_HTML
    assert 'data-app-mode="strategy"' in HERO_HTML

    # 5. Autonomy: the page loads directly from its own relative assets only.
    scripts = re.findall(r'<script src="([^"]+)"', HERO_HTML)
    assert scripts == ["./hero-ranges.js", "./hero-range-migration.js", "./hero-strategy-resolver.js", "./hero-ranges-app.js"], scripts
    styles = re.findall(r'<link rel="stylesheet" href="([^"]+)"', HERO_HTML)
    assert styles == ["./hero-ranges.css"], styles
    for ref in scripts + styles:
        assert ref.startswith("./") and "index.html" not in ref, ref
        assert (ROOT / "site" / ref[2:]).is_file(), ref
    assert "http://" not in HERO_HTML and "https://" not in HERO_HTML, "the editor must not depend on remote assets"
    for element_id in ("heroGrid", "sourceBadge", "positionSelect", "strategySourceBadge"):
        assert f'id="{element_id}"' in HERO_HTML, element_id

    # 6. The editor honours the deep link and keeps it stable across renders.
    assert 'new URLSearchParams(location.search||"").get("population")' in HERO_APP
    assert "function applyDeepLink()" in HERO_APP and "applyDeepLink();" in HERO_APP
    assert "function syncDeepLink()" in HERO_APP
    assert 'history.replaceState(null,"",href)' in HERO_APP
    for key in ("population", "position", "spot", "stack", "hand"):
        assert f'params.set("{key}"' in HERO_APP, key
    assert "function renderAll(){syncDeepLink();" in HERO_APP, "every render must re-sync the deep link"


check_hero_ranges_mode_contract()
print("trainer Hero custom-range contract: OK")
print("trainer Hero mode / deep link contract: OK")
