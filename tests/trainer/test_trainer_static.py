#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
DESKTOP_MIN_WIDTH = 901


def require(text: str, needle: str, label: str) -> None:
    assert needle in text, f"missing {label}: {needle}"


def css_rules(css: str, media: str | None = None) -> list[tuple[str | None, str, str]]:
    """Flatten `@media` blocks so every rule keeps the media condition guarding it."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules: list[tuple[str | None, str, str]] = []
    index = 0
    buffer = ""
    while index < len(css):
        char = css[index]
        if char == "{":
            prelude = buffer.strip()
            buffer = ""
            depth = 1
            cursor = index + 1
            while cursor < len(css) and depth > 0:
                if css[cursor] == "{":
                    depth += 1
                elif css[cursor] == "}":
                    depth -= 1
                cursor += 1
            body = css[index + 1:cursor - 1]
            if prelude.startswith("@"):
                if prelude.lower().startswith("@media"):
                    rules.extend(css_rules(body, prelude[len("@media"):].strip()))
            else:
                rules.append((media, prelude, body))
            index = cursor
            continue
        if char == "}":
            buffer = ""
            index += 1
            continue
        buffer += char
        index += 1
    return rules


def applies_at_desktop(media: str | None) -> bool:
    """True when the rule can apply at the >= 901px desktop shell."""
    if not media:
        return True
    return all(int(value) >= DESKTOP_MIN_WIDTH for value in re.findall(r"max-width\s*:\s*(\d+)px", media))


def desktop_declarations(css: str, selector: str) -> dict[str, str]:
    """Effective desktop-scope declarations for `selector`, in cascade order."""
    declarations: dict[str, str] = {}
    for media, rule_selector, body in css_rules(css):
        if not applies_at_desktop(media) or rule_selector != selector:
            continue
        for part in body.split(";"):
            name, separator, value = part.partition(":")
            if separator:
                declarations[name.strip()] = value.strip()
    return declarations


def check_training_fixed_height_view(index: str, js: str, css: str) -> None:
    """#394 T5 — the Training view is a dedicated full-height shell.

    `#trainerPage` is opened from Home and returns to Home; the document never
    scrolls, so the view itself has to hold at the reference screen (1500x1000)
    with a constrained body: fixed header, bounded table canvas and bounded side
    rail sub-views. The scheduler hold of the `training` lane is taken on entry
    and released on exit.
    """
    # The view is one of the mounted app shells, reachable from Home.
    assert 'id="trainerPage" class="trainer-page mode-hidden" data-view-shell="training"' in index
    assert 'data-app-view="training"' in index, "the Home mode card must open the Training view"
    assert 'training:"training", trainerPage:"training"' in index, "the #trainerPage deep link must map to training"
    assert 'if(view==="training")' in index, "openAppView('training') must route through the Trainer bootstrap"

    trainer = index.split('<div id="trainerPage"', 1)[1].split('<div id="replayerPage"', 1)[0]
    # Retour vers l'Accueil, with the shared return-control chrome.
    assert 'id="trainerBackBtn"' in trainer and 'class="secondary app-view-back"' in trainer
    assert "trainerBackBtn?.addEventListener(\"click\",trainerClose);" in js
    assert '← Accueil</button>' in trainer
    # Bounded body: the table is the allow-listed canvas pane, the rail is a set
    # of allow-listed sub-view panels.
    assert 'id="trainerTable" class="app-canvas-pane"' in trainer
    for panel, subview in (
        ("trainerCoachPanel", "trainer-coaching"),
        ("trainerSessionPanel", "trainer-session"),
        ("trainerProfilesPanel", "trainer-profiles"),
        ("trainerTestPanel", "trainer-test"),
    ):
        assert f'id="{panel}" class="trainer-rail-panel app-subview-panel app-scroll-zone"' in trainer, panel
        assert f'data-app-subview-panel="{subview}"' in trainer, subview

    # The shared desktop shell pins the document to 100dvh with no global scroll.
    assert "html,body{height:100dvh;max-height:100dvh;overflow:hidden}" in index

    # The Training shell absorbs the remaining height instead of forcing the
    # page taller than the viewport (`min-height:100vh` used to push the decision
    # controls out of an unscrollable document).
    page = desktop_declarations(css, ".trainer-page")
    assert page.get("display") == "flex", page
    assert page.get("flex-direction") == "column", page
    assert page.get("height") == "100dvh", page
    assert page.get("max-height") == "100dvh", page
    assert page.get("min-height") == "0", page
    assert page.get("overflow") == "hidden", page

    shell = desktop_declarations(css, ".trainer-shell")
    assert shell.get("flex") == "1 1 auto" and shell.get("min-height") == "0", shell
    grid = desktop_declarations(css, ".trainer-grid")
    assert grid.get("flex") == "1 1 auto" and grid.get("min-height") == "0", grid
    assert grid.get("grid-template-columns") == "minmax(0,1fr) 330px", grid
    main = desktop_declarations(css, ".trainer-main")
    assert main.get("display") == "flex" and main.get("min-height") == "0" and main.get("overflow") == "hidden", main
    table = desktop_declarations(css, "#trainerTable")
    assert table.get("flex") == "1 1 auto" and table.get("min-height") == "0", table
    rail = desktop_declarations(css, ".trainer-side")
    assert rail.get("min-height") == "0" and rail.get("overflow") == "hidden", rail
    wrap = desktop_declarations(css, ".trainer-table-wrap")
    assert wrap.get("min-height") == "0", wrap
    poker = desktop_declarations(css, ".trainer-table-wrap .poker-table")
    assert "clamp(" in (poker.get("height") or ""), poker

    # The excess travels through the declared bounded zones, never through a
    # scrolling view shell.
    for selector in (".trainer-page", ".trainer-grid", ".trainer-main", ".trainer-side"):
        overflow = desktop_declarations(css, selector).get("overflow", "visible")
        assert overflow in ("hidden", "visible", "clip"), (selector, overflow)

    # Scheduler hold: taken for as long as the Training view is mounted, released
    # on the way back to the Accueil. The app shell mirrors the same hold from the
    # mounted view, so no exit path can leave the lane held.
    opened = js.split("async function trainerOpen(options={}){", 1)[1].split("\n}", 1)[0]
    assert "window.pokerComputeScheduler.hold('training',true)" in opened, opened
    assert 'state.appView="training"' in opened, opened
    closed = js.split("function trainerClose(){", 1)[1].split("\n}", 1)[0]
    assert "window.pokerComputeScheduler.hold('training',false)" in closed, closed
    assert "trainerState.open=false" in closed, closed
    assert 'state.appView="home"' in closed, closed
    assert "window.pokerComputeScheduler.hold('training',mount==='training');" in index


def main() -> None:
    index = (SITE / "index.html").read_text(encoding="utf-8")
    js = (SITE / "trainer.js").read_text(encoding="utf-8")
    css = (SITE / "trainer.css").read_text(encoding="utf-8")

    for needle in (
        'id="trainerOpenBtn"', 'id="trainerNavLink"', 'id="trainerPage"',
        'id="trainerTable"', 'id="trainerControls"', 'id="trainerRecommendation"',
        'id="trainerFeedback"', 'data-trainer-mode="guided"',
        'data-trainer-mode="training"', 'data-trainer-mode="test"',
        'href="./trainer.css"', 'src="./trainer.js"',
    ):
        require(index, needle, "trainer integration")

    # Trainer must call the existing analyser rather than fork Model A EV logic.
    for needle in (
        "buildReviewBatchPlan(hand,lastHeroStep??-1)", 'runReviewBatchPlan(plan,{kind:"explicit"})',
        "applyPopulationModelSnapshot", "applyPostflopModelSnapshot",
        "parsePokerStarsHand", "reviewScores",
    ):
        require(js, needle, "existing analyser reuse")

    # Visual table primitives are reused from the existing analyser/replayer CSS.
    for needle in ("poker-table", "seat seat", "board-card", "hole-card", "replayDealerButtonHtml"):
        require(js, needle, "table primitive reuse")

    # Avoid reviving historical environment dependencies or a second analyser EV implementation.
    assert "/mnt/data" not in js
    assert "policyAdjustedEVBB=" not in js
    assert "postflopRaiseTreeSnapshot(" not in js
    require(index, 'src="./training/preflop-runtime.js"', "canonical preflop runtime module")
    require(js, 'trainerComputePreflopReference', "canonical Trainer preflop bridge")
    require(js, 'SPOT_NON_COUVERT', "fail-closed preflop state")

    # #393 T5: the Trainer derives its preflop primary labels from the shared
    # poker-analysis-state/v1 module, which must be loaded before trainer.js.
    require(index, 'src="./analytics/analysis-state.js"', "shared analysis-state module")
    assert index.index('src="./analytics/analysis-state.js"') < index.index('src="./trainer.js"'), \
        "analysis-state must load before trainer.js"
    require(js, 'window.PokerAnalysisState', "shared analysis-state runtime")
    require(js, 'mapAnalysisState', "shared taxonomy mapping")
    require(js, 'trainerAnalysisDimensionsHtml', "secondary technical detail panel")

    # Forced blinds and action order now come from the real public NLHE game state.
    require(index, 'src="./training/nlhe-game-state.js"', "browser NLHE game-state module")
    require(js, 'new Game.NoLimitHoldemState', "real blind/game-state construction")
    require(js, 'hand.core.legalView', "real action legality")
    assert 'stacks[sb]-=.5;stacks[bb]-=1;' not in js, "manual synthetic blind accounting reintroduced"

    require(js, 'TRAINER_POPULATION_MANIFEST="./assets/trainer/population.json"', "population pack selector")
    assert "TRAINER_ASSETS=" not in js, "trainer model paths must come from the population pack"
    manifest = json.loads((SITE / "assets/trainer/population.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "trainer-population-pack/v1"
    assert manifest["population_id"] == "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1"
    assert manifest["population_identity"]["format"] == "MIXED_ZOOM_REGULAR"
    expected_assets = [
        manifest["assets"]["modelA"]["preflop"],
        manifest["assets"]["modelA"]["postflop"],
        manifest["assets"]["modelB"]["profiles"],
        manifest["assets"]["modelB"]["ranges"],
        manifest["assets"]["modelB"]["actions"],
        manifest["assets"]["modelB"]["sizing"],
        manifest["assets"]["modelB"]["contract"],
        manifest["assets"]["hero"]["ranges"],
    ]
    for rel in expected_assets:
        assert (SITE / rel.removeprefix("./")).is_file(), f"missing trainer asset: {rel}"

    profiles = json.loads((SITE / "assets/trainer/model_b/profiles.json").read_text(encoding="utf-8"))
    assert profiles["schema"] == "independent-opponent-profiles/v2"
    assert profiles["k"] == 3
    weights = [float(x["appearance_weight"]) for x in profiles["profiles"]]
    assert abs(sum(weights) - 1.0) < 1e-9

    ranges = json.loads((SITE / "assets/trainer/model_b/preflop_ranges.json").read_text(encoding="utf-8"))
    assert ranges["schema"] == "independent-preflop-ranges/v2"
    assert sum(int(v) for v in ranges["multiplicity"].values()) == 1326

    assert ".trainer-page" in css and ".trainer-decision-box" in css
    check_training_fixed_height_view(index, js, css)
    print("trainer static architecture checks: OK")


if __name__ == "__main__":
    main()
