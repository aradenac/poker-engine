#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation import v83_hh_compat as compat  # noqa: E402
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

REAL_MIXED_FRENCH_HAND = """Main PokerStars n°261415379202 :  Hold'em No Limit (100/200) - 12/07/2026 18:25:06 CET [12/07/2026 12:25:06 ET]
Table 'Vladimir VII' 6-max (argent fictif) Seat #1 is the button
Seat 1: Edntambosi (15510 in chips)
Seat 2: thank777 (29041 in chips)
Seat 3: Fredmag45 (19500 in chips)
Seat 4: RoiDePiqueNique (19800 in chips)
Seat 5: SuperDog782 (21073 in chips)
Seat 6: bard211 (15037 in chips)
thank777 : posts small blind 100
Fredmag45 : posts big blind 200
*** HOLE CARDS ***
Dealt to RoiDePiqueNique [Th 7h]
RoiDePiqueNique : calls 200
SuperDog782 : folds
bard211 : folds
Edntambosi : raises 700 to 900
thank777 : folds
Fredmag45 : folds
RoiDePiqueNique : calls 700
*** FLOP *** [Tc 3d 8c]
RoiDePiqueNique : checks
"""


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


def test_real_french_header_and_nbsp_are_v83_compatible() -> None:
    base_prefix = preflop_prefix_for_v83(REAL_MIXED_FRENCH_HAND)
    prefix = compat.normalize_prefix_text_for_v83(base_prefix)
    lines = prefix.splitlines()
    assert lines[0].startswith(
        "PokerStars Hand #261415379202: Hold'em No Limit (100/200) - 2026/07/12 18:25:06 CET"
    )
    assert "thank777: posts small blind 100" in lines
    assert "Fredmag45: posts big blind 200" in lines
    assert "RoiDePiqueNique: calls 200" in lines
    assert "Edntambosi: raises 700 to 900" in lines
    assert "RoiDePiqueNique: calls 700" in lines
    assert "\u00a0:" not in prefix
    assert "\u202f:" not in prefix
    assert "*** FLOP ***" not in prefix


def test_french_synthetic_action_serialization() -> None:
    assert localized_action_line("Hero", "CHECK", 0, 0, 0, 50, 200, "fr") == "Hero: parole."
    assert localized_action_line("Hero", "FOLD", 0, 0, 2, 50, 200, "fr") == "Hero: passe."
    assert localized_action_line("Hero", "CALL", 2, 0, 2, 50, 200, "fr") == "Hero: suit. 400"
    assert localized_action_line("Hero", "AGG", 3, 0, 0, 50, 200, "fr") == "Hero: mise. 600"
    assert localized_action_line("Hero", "AGG", 6, 2, 4, 50, 200, "fr") == "Hero: relance. 800 à 1600"


def test_v83_synthetic_actions_are_always_english() -> None:
    assert compat.action_line_for_v83("Hero", "CHECK", 0, 0, 0, 50, 200, "fr") == "Hero: checks"
    assert compat.action_line_for_v83("Hero", "FOLD", 0, 0, 2, 50, 200, "fr") == "Hero: folds"
    assert compat.action_line_for_v83("Hero", "CALL", 2, 0, 2, 50, 200, "fr") == "Hero: calls 400"
    assert compat.action_line_for_v83("Hero", "AGG", 3, 0, 0, 50, 200, "fr") == "Hero: bets 600"
    assert compat.action_line_for_v83("Hero", "AGG", 6, 2, 4, 50, 200, "fr") == "Hero: raises 800 to 1600"


def test_localized_street_markers() -> None:
    board = ["As", "Kd", "2c", "Jh", "9s"]
    assert street_marker("flop", board, "fr") == "*** FLOP *** [As Kd 2c]"
    assert street_marker("turn", board, "fr") == "*** TOURNANT *** [As Kd 2c] [Jh]"
    assert street_marker("river", board, "fr") == "*** RIVIÈRE *** [As Kd 2c Jh] [9s]"
    assert street_marker("turn", board, "en") == "*** TURN *** [As Kd 2c] [Jh]"


def test_v83_street_markers_are_always_english() -> None:
    board = ["As", "Kd", "2c", "Jh", "9s"]
    assert compat.street_marker_for_v83("flop", board, "fr") == "*** FLOP *** [As Kd 2c]"
    assert compat.street_marker_for_v83("turn", board, "fr") == "*** TURN *** [As Kd 2c] [Jh]"
    assert compat.street_marker_for_v83("river", board, "fr") == "*** RIVER *** [As Kd 2c Jh] [9s]"


def test_exact_failing_first_decision_shell_is_english_v83_grammar() -> None:
    prefix = compat.normalize_prefix_text_for_v83(preflop_prefix_for_v83(REAL_MIXED_FRENCH_HAND))
    synthetic = (
        prefix
        + "\n"
        + compat.street_marker_for_v83("flop", ["Tc", "3d", "8c"], "fr")
        + "\n"
        + compat.action_line_for_v83("RoiDePiqueNique", "CHECK", 0, 0, 0, 94.5, 200, "fr")
        + "\n"
    )
    assert synthetic.startswith("PokerStars Hand #261415379202:")
    assert "*** FLOP *** [Tc 3d 8c]\nRoiDePiqueNique: checks\n" in synthetic
    for token in ("Main PokerStars", "parole.", "TOURNANT", "RIVIÈRE", "\u00a0:", "\u202f:"):
        assert token not in synthetic


def test_summary_and_uncalled_bet_are_terminal_boundaries() -> None:
    assert preflop_prefix_for_v83(HEADER + "\n*** SUMMARY ***\nTotal pot 400 | Rake 0\n") == HEADER
    assert preflop_prefix_for_v83(HEADER + "\nUncalled bet (400) returned to Hero\n") == HEADER


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"conditioned history compatibility tests: {len(tests)} passed")
