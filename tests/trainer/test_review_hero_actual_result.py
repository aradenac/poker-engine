#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
INDEX=(ROOT/"site/index.html").read_text(encoding="utf-8")


def main() -> int:
    assert "function reviewHeroCardsText(hand)" in INDEX
    assert "function reviewActualResult(hand)" in INDEX
    assert "function reviewHandDisplayMeta(hand)" in INDEX
    assert "const netBB=handNetBB(hand);" in INDEX
    assert "hand?.heroResult?.net" in INDEX
    assert 'label:"Résultat réel indisponible"' in INDEX
    assert 'label:"Gagné"' in INDEX
    assert 'label:"Perdu"' in INDEX
    assert 'class="review-inbox-hand-result"' in INDEX
    assert "Résultat réel ·" in INDEX
    assert "Perte EV<b>" in INDEX
    assert "const prioritySourceHand=hand?(state.hhHands||[]).find" in INDEX
    assert "const priorityMeta=hand?reviewHandDisplayMeta" in INDEX
    assert "perte EV" in INDEX
    assert "const display=reviewHandDisplayMeta(h);" in INDEX
    assert "Hero ${display.hero_cards}" in INDEX
    # Actual settlement must not be derived from recommendation/EV fields.
    helper=INDEX.split("function reviewActualResult(hand)",1)[1].split("function reviewHandDisplayMeta",1)[0]
    for forbidden in ("totalLossBB","lossEVBB","bestEV","chosenEV","recommended"):
        assert forbidden not in helper, forbidden
    print("Review Hero hand + actual result contract: PASS")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
