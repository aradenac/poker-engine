#!/usr/bin/env python3
"""Known-hand override contract (#391).

Representation/display contract only. It pins that:

- the entries produced by `effectiveEntriesForOpponent` and
  `exactEntriesFromCards` carry the additive `knownHandOverride` flag;
- the override is the only legitimate single-class 100 % display and is rendered
  as a mechanism separate from the posterior (opponent row + range modal);
- the override is never merged into the posterior mass projection, and
  `useKnownHand` is left untouched.

It does not touch the model/fit or the equity consumers.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")
DOC = (ROOT / "docs/opponent-range-display-contract.md").read_text(encoding="utf-8")


def section(start: str, end: str) -> str:
    return INDEX.split(start, 1)[1].split(end, 1)[0]


def main() -> None:
    producers = section(
        "function exactKnownOverride(index){",
        "function finalPreflopReplayIndex(){",
    )
    effective = section(
        "function effectiveEntriesForOpponent(index){",
        "function updateRangeEditionUi(){",
    )
    exact_from_cards = section(
        "function exactEntriesFromCards(cards){",
        "function defaultRangeEntriesForHistoryPlayer(player){",
    )
    modal = section(
        "function openPopulationRangeModal(",
        "populationRangeModalClose?.addEventListener",
    )
    opponents = section("function renderOpponents(){", "function updateStreetButtons(){")
    grid_fn = section(
        "function gridFreqMapFromEstimate(",
        "function openPopulationRangeModal(",
    )

    # 1. The additive flag is produced by both entry producers.
    assert "knownHandOverride:true" in producers
    assert "function knownHandOverrideEntry(cards){" in producers
    assert "knownHandOverrideEntry(o.knownCards)" in effective
    assert "knownHandOverrideEntry(cards)" in exact_from_cards
    assert "knownHandOverride===true" in producers

    # 2. The UI distinguishes override vs posterior.
    assert "knownHandOverrideCardsForPlayer(player.name)" in modal
    assert "Override main connue · mécanisme séparé du posterior." in modal
    assert "seul cas légitime" in modal
    assert "ne sont pas fusionné" in modal or "n’est pas fusionné" in modal
    assert "override main connue actif" in modal
    assert "override" in opponents.lower()
    assert "mécanisme séparé du posterior" in opponents
    assert "classe unique à 100 %" in opponents

    # 3. No generalized 100 % by this path: the override never feeds the
    # posterior grid map and the explicit posterior-state gating is unchanged.
    assert "knownHandOverride" not in grid_fn
    assert "knownHandOverrideCardsForPlayer" not in grid_fn
    assert 'if(estimate?.posteriorState==="degenerate")return new Map();' in grid_fn
    assert 'if(estimate?.posteriorState==="prior_uninformative")return new Map();' in grid_fn
    assert "const freq=gridFreqMapFromEstimate(estimate,player);" in modal

    # The versioned display contract documents the override as not a posterior.
    assert "known_hand_override:Object.freeze({" in INDEX
    assert 'flag:"knownHandOverride"' in INDEX
    assert "merge_with_posterior:false" in INDEX
    assert "knownHandOverride" in DOC
    assert "separate mechanism" in DOC

    print("known-hand override contract checks: OK")


if __name__ == "__main__":
    main()
