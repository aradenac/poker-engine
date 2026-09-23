#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"


def require(text: str, needle: str, label: str) -> None:
    assert needle in text, f"missing {label}: {needle}"


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
    print("trainer static architecture checks: OK")


if __name__ == "__main__":
    main()
