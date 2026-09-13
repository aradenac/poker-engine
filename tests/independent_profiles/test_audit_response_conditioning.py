#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.independent_profiles.audit_response_conditioning import (  # noqa: E402
    board_by_street, board_texture, price_bucket, spr_bucket, starting_stacks, strength_bucket,
)

HAND = """PokerStars Hand #1: Hold'em No Limit (100/200) - 2026/09/10 12:00:00 CET
Table 'T' 2-max Seat #1 is the button
Seat 1: Hero (20000 in chips)
Seat 2: Villain (12500 in chips)
*** FLOP *** [2c 7d Jh]
*** TURN *** [2c 7d Jh] [9s]
*** RIVER *** [2c 7d Jh 9s] [3c]
"""

class ResponseAuditHelperTest(unittest.TestCase):
    def test_board_and_stack_parsing(self):
        boards = board_by_street(HAND)
        self.assertEqual(boards["flop"], ["2c", "7d", "Jh"])
        self.assertEqual(boards["turn"], ["2c", "7d", "Jh", "9s"])
        self.assertEqual(boards["river"], ["2c", "7d", "Jh", "9s", "3c"])
        self.assertEqual(starting_stacks(HAND, {"Hero", "Villain"}), {"Hero": 20000.0, "Villain": 12500.0})

    def test_bucket_boundaries(self):
        self.assertEqual(price_bucket(0.25), "P00_25")
        self.assertEqual(price_bucket(0.7), "P50_75")
        self.assertEqual(price_bucket(2.0), "P150_PLUS")
        self.assertEqual(spr_bucket(0.9), "SPR_LT1")
        self.assertEqual(spr_bucket(4.0), "SPR_3_6")
        self.assertEqual(spr_bucket(20.0), "SPR_12_PLUS")

    def test_strength_and_texture(self):
        flop = ["2c", "7d", "Jh"]
        self.assertEqual(strength_bucket(["Js", "Td"], flop), "ONE_PAIR")
        self.assertEqual(strength_bucket(["As", "Kd"], flop), "HIGH_CARD")
        self.assertEqual(board_texture(flop), "UNPAIRED_RAINBOW")
        self.assertTrue(board_texture(["2c", "2d", "Jh"]).startswith("PAIRED_"))

if __name__ == "__main__":
    unittest.main()
