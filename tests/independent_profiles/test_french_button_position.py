#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import HandRecord  # noqa: E402
from tools.training.independent_profiles.build_model_b import parse_hand  # noqa: E402


def record(button_phrase: str) -> HandRecord:
    text = "\n".join([
        "PokerStars Hand #999001: Hold'em No Limit (100/200) - 2026/09/13 20:00:00 CET",
        f"Table 'Synthetic' 2-max (argent fictif) Siège #1 {button_phrase}.",
        "Siège 1: Hero (20000 en jetons)",
        "Siège 2: Villain (20000 en jetons)",
        "Hero: met la petite blind. 100",
        "Villain: met la grosse blind. 200",
        "*** CARTES FERMÉES ***",
        "Distribuées à Hero [Th 7h]",
        "Hero: relance. 400 à 600",
        "Villain: suit. 400",
        "*** FLOP *** [Tc 3d 8c]",
        "Villain: parole.",
        "Hero: parole.",
        "*** RÉSUMÉ ***",
        "",
    ])
    return HandRecord("999001", "synthetic-fr.txt", text, "2026-09-13 20:00:00", "fr", "100/200")


class FrenchButtonPositionTest(unittest.TestCase):
    def test_current_french_est_au_bouton_grammar(self) -> None:
        hand = parse_hand(record("est au bouton"))
        self.assertIsNotNone(hand)
        self.assertEqual(hand["button"], 1)
        self.assertEqual(hand["positions"]["Hero"], "SB_BTN")
        self.assertEqual(hand["positions"]["Villain"], "BB")

    def test_legacy_french_est_le_bouton_grammar_remains_supported(self) -> None:
        hand = parse_hand(record("est le bouton"))
        self.assertIsNotNone(hand)
        self.assertEqual(hand["button"], 1)
        self.assertEqual(hand["positions"]["Hero"], "SB_BTN")
        self.assertEqual(hand["positions"]["Villain"], "BB")


if __name__ == "__main__":
    unittest.main()
