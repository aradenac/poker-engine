import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.hand_history_state import replay_public_hand
from tools.repro_preflop_fixture import (
    load_hand_history,
    load_reference_fixture,
    reconstruct_reference,
    verify_reference,
)


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


class KTsIsoReferenceFixtureTests(unittest.TestCase):
    def snapshots_by_id(self):
        fixture = load_reference_fixture(ROOT)
        return fixture, {row["id"]: row for row in fixture["snapshots"]}

    def test_reference_fixture_reconstructs_exactly_through_shared_core_and_hh(self):
        self.assertEqual([], verify_reference(ROOT))
        fixture = load_reference_fixture(ROOT)
        first = reconstruct_reference(fixture, ROOT)
        second = reconstruct_reference(fixture, ROOT)
        self.assertEqual(first, second)
        self.assertEqual(fixture["snapshots"], first["snapshots"])
        self.assertEqual(
            fixture["public_timeline_sha256"],
            "51585a3dc55fd3ffb8aea8961249ddc97c032ebd3c85f566febfe5b5b2bd0b7b",
        )
        self.assertEqual(fixture["public_timeline_sha256"], first["public_timeline_sha256"])

    def test_kts_sb_two_limp_iso4_three_calls_accounting_is_canonical(self):
        fixture, snap = self.snapshots_by_id()
        scenario = fixture["scenario"]
        self.assertEqual(
            scenario["hero"],
            {"player": "Hero", "position": "SB", "hand_class": "KTs"},
        )
        self.assertEqual(scenario["positions"]["CO"], "CO")
        self.assertEqual(scenario["positions"]["BTN"], "BTN")
        hero_action = next(x for x in scenario["actions"] if x["id"] == "hero_iso")
        self.assertEqual(hero_action["target_total_bb"], 4)

        def pot(snapshot_id):
            return sum(snap[snapshot_id]["state"]["total_committed_bb"].values())

        self.assertEqual(pot("before_hero"), 3.5)
        self.assertEqual(pot("after_hero_raise"), 7.0)
        self.assertEqual(pot("after_bb_call"), 10.0)
        self.assertEqual(pot("after_co_call"), 13.0)
        self.assertEqual(pot("after_btn_call_preflop"), 16.0)

        final = snap["after_btn_call_preflop"]["state"]
        self.assertEqual(
            final["total_committed_bb"],
            {"BTN": 4, "Hero": 4, "BB": 4, "UTG": 0, "HJ": 0, "CO": 4},
        )
        self.assertEqual(
            final["stacks_bb"],
            {"BTN": 96, "Hero": 96, "BB": 96, "UTG": 100, "HJ": 100, "CO": 96},
        )
        self.assertEqual(final["pending"], [])
        self.assertTrue(final["folded"]["UTG"])
        self.assertTrue(final["folded"]["HJ"])

    def test_hero_raise_and_all_three_calls_are_legal_with_explicit_price(self):
        _, snap = self.snapshots_by_id()
        before_hero = snap["before_hero"]
        self.assertIn("RAISE", before_hero["legal"]["legal_actions"])
        self.assertEqual(before_hero["legal"]["min_raise_to_bb"], 2)
        self.assertEqual(before_hero["legal"]["max_raise_to_bb"], 100)
        self.assertEqual(before_hero["legal"]["to_call_bb"], 0.5)

        expected = {
            "before_bb_call": (7.0, 3.0, 4.0, 0.428571429),
            "before_co_call": (10.0, 3.0, 4.0, 0.3),
            "before_btn_call": (13.0, 3.0, 4.0, 0.230769231),
        }
        for snapshot_id, (pot, to_call, target, price_to_pot) in expected.items():
            row = snap[snapshot_id]
            self.assertIn("CALL", row["legal"]["legal_actions"])
            self.assertEqual(row["legal"]["pot_before_bb"], pot)
            self.assertEqual(row["pricing"]["to_call_bb"], to_call)
            self.assertEqual(row["pricing"]["call_target_total_bb"], target)
            self.assertEqual(row["pricing"]["price_to_pot"], price_to_pot)

    def test_public_snapshots_are_resumable_and_do_not_leak_future_or_private_cards(self):
        fixture, snap = self.snapshots_by_id()
        for row in fixture["snapshots"]:
            restored = NoLimitHoldemState.from_snapshot(row["state"])
            self.assertEqual(restored.to_snapshot(include_log=False), row["state"])
            if row["legal"] is not None:
                self.assertEqual(restored.legal_view(), row["legal"])
            if row["state"]["street"] == "preflop":
                self.assertEqual(row["state"]["board"], [])
            public_text = json.dumps(row["state"], sort_keys=True)
            self.assertNotIn("Ks", public_text)
            self.assertNotIn("Ts", public_text)
            self.assertNotIn("hole", public_text.lower())

        flop = snap["flop_entry"]["state"]
        self.assertEqual(flop["street"], "flop")
        self.assertEqual(flop["board"], ["2c", "7d", "Qh"])
        self.assertEqual(flop["pending"], ["Hero", "BB", "CO", "BTN"])
        self.assertEqual(
            [p for p, folded in flop["folded"].items() if not folded],
            ["BTN", "Hero", "BB", "CO"],
        )

        raw = load_hand_history(fixture, ROOT)
        self.assertIn("Dealt to Hero [Ks Ts]", raw)
        self.assertEqual(raw.count("Dealt to "), 1)

    def test_public_fingerprints_are_stable_and_duplicate_labels_share_state_identity(self):
        fixture, snap = self.snapshots_by_id()
        expected = {
            "after_co_limp": "f9be75eb811252e39082c676fe238b128f47aa5eebf6be49f3cacd92e4a93dc9",
            "before_hero": "b337ba199b2afa7126b762bd38a8779fa26f5b1c850b3d1e215f56af008aa5fb",
            "after_hero_raise": "634144c235fe7f8f7de9cf451b5a2341dcb4db4e60a124fa429941f034dd3ac3",
            "after_bb_call": "c5d104f40934011dc79e3f5e78e44923b0be8d28af6b26e0b9adcd8570fc8166",
            "after_co_call": "6087a0525dca46b0d9b7fdd0e61a59a3a82690c778563aa07b642c7b5f67441a",
            "after_btn_call_preflop": "cc5d88b31ea91e0b260432e46afded6b0817bbd3fcf839dabe91d6eb028ead48",
            "flop_entry": "58c1c22d4398dc96d59524c943ae0313b2c70441c9ba3e10e76ae085d4e25c01",
        }
        for snapshot_id, digest in expected.items():
            self.assertEqual(snap[snapshot_id]["public_fingerprint_sha256"], digest)

        self.assertEqual(
            snap["after_btn_limp"]["public_fingerprint_sha256"],
            snap["before_hero"]["public_fingerprint_sha256"],
        )
        self.assertEqual(
            snap["after_hero_raise"]["public_fingerprint_sha256"],
            snap["before_bb_call"]["public_fingerprint_sha256"],
        )
        self.assertEqual(
            snap["after_bb_call"]["public_fingerprint_sha256"],
            snap["before_co_call"]["public_fingerprint_sha256"],
        )
        self.assertEqual(
            snap["after_co_call"]["public_fingerprint_sha256"],
            snap["before_btn_call"]["public_fingerprint_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
