#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.sequential_postflop_conditioned import (  # noqa: E402
    localized_action_line,
    preflop_prefix_for_v83,
    street_marker,
)


HEADER = """PokerStars Hand #999: Hold'em No Limit (100/200) - 2026/09/12 20:00:00 CET
Table 'Synthetic' 6-max Seat #1 is the button
Seat 1: Hero (20000 in chips)
Seat 2: Villain (20000 in chips)
Hero: posts small blind 100
Villain: posts big blind 200
*** HOLE CARDS ***
Dealt to Hero [Th 7h]
Hero: raises 400 to 600
Villain: calls 400"""

FRENCH_HEADER = """PokerStars Hand #999: Hold'em No Limit (100/200) - 2026/09/12 20:00:00 CET
Table 'Synthetic' 6-max (argent fictif) Siège #1 est au bouton.
Siège 1: Hero (20000 en jetons)
Siège 2: Villain (20000 en jetons)
Hero: met la petite blind. 100
Villain: met la grosse blind. 200
*** CARTES FERMÉES ***
Distribuées Hero [Th 7h]
Hero: relance. 400 à 600
Villain: suit. 400"""


def test_preflop_ended_hand_drops_settlement_before_synthetic_flop() -> None:
    raw = HEADER + """
Uncalled bet (400) returned to Hero
Hero collected 400 from pot
*** SUMMARY ***
Total pot 400 | Rake 0
"""
    prefix = preflop_prefix_for_v83(raw)
    assert prefix == HEADER
    synthetic = prefix + "\n*** FLOP *** [Tc 3d 8c]\nHero: checks\n"
    assert "collected" not in synthetic
    assert "*** SUMMARY ***" not in synthetic


def test_english_flop_source_hand_keeps_same_preflop_prefix() -> None:
    raw = HEADER + "\n*** FLOP *** [As Kd 2c]\nHero: checks\n"
    assert preflop_prefix_for_v83(raw) == HEADER


def test_french_prefix_is_normalized_to_v83_english_grammar() -> None:
    raw = FRENCH_HEADER + "\n*** FLOP *** [As Kd 2c]\nHero: parole.\n"
    prefix = preflop_prefix_for_v83(raw)
    assert "Seat #1 is the button" in prefix
    assert "Seat 1: Hero (20000 in chips)" in prefix
    assert "Seat 2: Villain (20000 in chips)" in prefix
    assert "Hero: posts small blind 100" in prefix
    assert "Villain: posts big blind 200" in prefix
    assert "*** HOLE CARDS ***" in prefix
    assert "Dealt to Hero [Th 7h]" in prefix
    assert "Hero: raises 400 to 600" in prefix
    assert "Villain: calls 400" in prefix
    for token in ("Siège", "en jetons", "CARTES FERMÉES", "Distribuées", "relance.", "suit."):
        assert token not in prefix


def test_french_synthetic_action_serialization() -> None:
    assert localized_action_line("Hero", "CHECK", 0, 0, 0, 50, 200, "fr") == "Hero: parole."
    assert localized_action_line("Hero", "FOLD", 0, 0, 2, 50, 200, "fr") == "Hero: passe."
    assert localized_action_line("Hero", "CALL", 2, 0, 2, 50, 200, "fr") == "Hero: suit. 400"
    assert localized_action_line("Hero", "AGG", 3, 0, 0, 50, 200, "fr") == "Hero: mise. 600"
    assert localized_action_line("Hero", "AGG", 6, 2, 4, 50, 200, "fr") == "Hero: relance. 800 à 1600"


def test_localized_street_markers() -> None:
    board = ["As", "Kd", "2c", "Jh", "9s"]
    assert street_marker("flop", board, "fr") == "*** FLOP *** [As Kd 2c]"
    assert street_marker("turn", board, "fr") == "*** TOURNANT *** [As Kd 2c] [Jh]"
    assert street_marker("river", board, "fr") == "*** RIVIÈRE *** [As Kd 2c Jh] [9s]"
    assert street_marker("turn", board, "en") == "*** TURN *** [As Kd 2c] [Jh]"


def test_summary_and_uncalled_bet_are_terminal_boundaries() -> None:
    assert preflop_prefix_for_v83(HEADER + "\n*** SUMMARY ***\nTotal pot 400 | Rake 0\n") == HEADER
    assert preflop_prefix_for_v83(HEADER + "\nUncalled bet (400) returned to Hero\n") == HEADER


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"conditioned history compatibility tests: {len(tests)} passed")
