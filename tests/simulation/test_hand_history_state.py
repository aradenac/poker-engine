import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.hand_history_state import replay_public_hand


ENGLISH_HAND = """PokerStars Hand #1001: Hold'em No Limit (100/200) - 2026/09/15 08:00:00 CET
Table 'Core EN' 3-max Seat #1 is the button
Seat 1: Hero (20000 in chips)
Seat 2: VillainSB (20000 in chips)
Seat 3: VillainBB (20000 in chips)
VillainSB: posts small blind 100
VillainBB: posts big blind 200
*** HOLE CARDS ***
Dealt to Hero [As Kd]
Hero: calls 200
VillainSB: calls 100
VillainBB: checks
*** FLOP *** [2c 3d 4h]
VillainSB: checks
VillainBB: checks
Hero: bets 400
VillainSB: folds
VillainBB: calls 400
*** TURN *** [2c 3d 4h] [5s]
VillainBB: checks
Hero: checks
*** RIVER *** [2c 3d 4h 5s] [6c]
VillainBB: checks
Hero: checks
*** SHOW DOWN ***
"""

FRENCH_HAND = """PokerStars Partie #1001: Hold'em No Limit (100/200) - 2026/09/15 08:00:00 CET
Table 'Core FR' 3-max Place #1 est le bouton
Place 1: Hero (20 000 en jetons)
Place 2: VillainSB (20 000 en jetons)
Place 3: VillainBB (20 000 en jetons)
VillainSB : met la petite blind. 100
VillainBB : met la grosse blind. 200
*** CARTES FERMÉES ***
Distribuées à Hero [As Kd]
Hero : suit. 200
VillainSB : suit. 100
VillainBB : parole.
*** FLOP *** [2c 3d 4h]
VillainSB : parole.
VillainBB : parole.
Hero : mise. 400
VillainSB : se couche.
VillainBB : suit. 400
*** TOURNANT *** [2c 3d 4h] [5s]
VillainBB : parole.
Hero : parole.
*** RIVIÈRE *** [2c 3d 4h 5s] [6c]
VillainBB : parole.
Hero : parole.
*** RÉSUMÉ ***
"""

FRENCH_RAISE_HAND = """PokerStars Partie #1002: Hold'em No Limit (100/200) - 2026/09/15 08:01:00 CET
Table 'Raise FR' 3-max Siège #1 est au bouton
Siège 1: Hero (20000 en jetons)
Siège 2: VillainSB (20000 en jetons)
Siège 3: VillainBB (20000 en jetons)
VillainSB : met la petite blind. 100
VillainBB : met la grosse blind. 200
*** CARTES FERMÉES ***
Hero : relance. 400 à 600
VillainSB : se couche.
VillainBB : suit. 400
*** FLOP *** [2c 3d 4h]
VillainBB : parole.
Hero : parole.
*** TURN *** [2c 3d 4h] [5s]
VillainBB : parole.
Hero : parole.
*** RIVER *** [2c 3d 4h 5s] [6c]
VillainBB : parole.
Hero : parole.
*** ABATTAGE ***
"""

SHORT_BIG_BLIND_HAND = """PokerStars Hand #1003: Hold'em No Limit (100/200) - 2026/09/15 08:02:00 CET
Table 'Short blind' 3-max Seat #1 is the button
Seat 1: Hero (20000 in chips)
Seat 2: VillainSB (20000 in chips)
Seat 3: VillainBB (120 in chips)
VillainSB: posts small blind 100
VillainBB: posts big blind 120 and is all-in
*** HOLE CARDS ***
Hero: calls 200
VillainSB: calls 100
*** FLOP *** [2c 3d 4h]
VillainSB: checks
Hero: checks
*** TURN *** [2c 3d 4h] [5s]
VillainSB: checks
Hero: checks
*** RIVER *** [2c 3d 4h 5s] [6c]
VillainSB: checks
Hero: checks
*** SHOW DOWN ***
"""


class HandHistoryStateTests(unittest.TestCase):
    def test_english_and_french_reconstruct_identical_before_action_states(self):
        en = replay_public_hand(ENGLISH_HAND)
        fr = replay_public_hand(FRENCH_HAND)
        self.assertEqual(en["language"], "en")
        self.assertEqual(fr["language"], "fr")
        self.assertEqual(len(en["trace"]), 12)
        self.assertEqual(len(fr["trace"]), 12)
        for left, right in zip(en["trace"], fr["trace"]):
            self.assertEqual(left["street"], right["street"])
            self.assertEqual(left["player"], right["player"])
            self.assertEqual(left["action"], right["action"])
            self.assertEqual(left["state_before"], right["state_before"])
            self.assertEqual(left["legal_before"], right["legal_before"])
        self.assertEqual(en["final_state"], fr["final_state"])

    def test_snapshots_reveal_board_only_when_public(self):
        replay = replay_public_hand(ENGLISH_HAND)
        preflop = [x for x in replay["trace"] if x["street"] == "preflop"]
        flop = [x for x in replay["trace"] if x["street"] == "flop"]
        turn = [x for x in replay["trace"] if x["street"] == "turn"]
        river = [x for x in replay["trace"] if x["street"] == "river"]
        self.assertTrue(all(x["state_before"]["board"] == [] for x in preflop))
        self.assertTrue(all(x["state_before"]["board"] == ["2c", "3d", "4h"] for x in flop))
        self.assertTrue(all(len(x["state_before"]["board"]) == 4 for x in turn))
        self.assertTrue(all(len(x["state_before"]["board"]) == 5 for x in river))
        serialized = json.dumps([x["state_before"] for x in replay["trace"]])
        self.assertNotIn("As", serialized)
        self.assertNotIn("Kd", serialized)

    def test_french_raise_amount_is_raise_increment_not_actor_commitment(self):
        replay = replay_public_hand(FRENCH_RAISE_HAND)
        first = replay["trace"][0]
        self.assertEqual(first["action"], "raise")
        self.assertEqual(first["legal_before"]["current_price_bb"], 1.0)
        self.assertEqual(replay["trace"][1]["state_before"]["current_bet_bb"], 3.0)
        self.assertEqual(replay["trace"][1]["state_before"]["total_committed_bb"]["Hero"], 3.0)

    def test_header_nominal_blind_keeps_units_when_big_blind_is_short_allin(self):
        replay = replay_public_hand(SHORT_BIG_BLIND_HAND)
        self.assertEqual(replay["big_blind_chips"], 200)
        first = replay["trace"][0]
        self.assertEqual(first["legal_before"]["pot_before_bb"], 1.1)
        self.assertEqual(first["legal_before"]["current_price_bb"], 1.0)
        self.assertEqual(first["legal_before"]["to_call_bb"], 1.0)


if __name__ == "__main__":
    unittest.main()
