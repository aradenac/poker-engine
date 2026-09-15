import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.full_hand_core import (
    HoldemState,
    IllegalAction,
    replay_normalized_actions,
)
from tools.simulation.pokerstars_prefix import state_from_pokerstars_prefix


def state3(stacks=None):
    return HoldemState.new_hand(
        stacks_bb=stacks or {"BTN": 100, "SB": 100, "BB": 100},
        seat_order=["BTN", "SB", "BB"],
        button="BTN",
        hole_cards={"BTN": ["As", "Ah"], "SB": ["Ks", "Kh"], "BB": ["Qs", "Qh"]},
        board_runout=["2c", "3d", "7h", "8s", "9c"],
    )


def reference_hh_fixture() -> dict:
    path = ROOT / "tests" / "fixtures" / "full_hand_core_reference_hh.json"
    return json.loads(path.read_text(encoding="utf-8"))


class FullHandCoreTests(unittest.TestCase):
    def test_blinds_and_bb_option_after_limps(self):
        s = state3()
        self.assertEqual(s.next_actor, "BTN")
        s.apply_action("BTN", "CALL")
        s.apply_action("SB", "CALL")
        self.assertEqual(s.next_actor, "BB")
        self.assertEqual(s.to_call_bb("BB"), 0)
        self.assertIn("CHECK", s.legal_actions("BB")["actions"])
        s.apply_action("BB", "CHECK")
        self.assertTrue(s.betting_round_complete())
        self.assertAlmostEqual(sum(p.total_contribution_bb for p in s.players.values()), 3.0)

    def test_preflop_raise_and_minimum_reraise(self):
        s = state3()
        s.apply_action("BTN", "RAISE", to_bb=3)
        self.assertAlmostEqual(s.last_full_raise_bb, 2)
        s.apply_action("SB", "CALL")
        with self.assertRaisesRegex(IllegalAction, "minimum raise"):
            s.apply_action("BB", "RAISE", to_bb=4)
        s.apply_action("BB", "RAISE", to_bb=5)
        self.assertAlmostEqual(s.last_full_raise_bb, 2)

    def test_short_allin_raise_does_not_reopen_but_cumulative_can(self):
        # UTG opens 3; short stacks make sub-minimum all-in raises. UTG may not
        # reraise after the first short raise, but cumulative increases can reopen.
        s = HoldemState.new_hand(
            stacks_bb={"BTN": 100, "SB": 3.5, "BB": 4.5, "UTG": 100},
            seat_order=["BTN", "SB", "BB", "UTG"],
            button="BTN",
        )
        self.assertEqual(s.next_actor, "UTG")
        s.apply_action("UTG", "RAISE", to_bb=3)
        s.apply_action("BTN", "CALL")
        s.apply_action("SB", "ALL_IN")  # to 3.5, +0.5
        s.apply_action("BB", "ALL_IN")  # to 4.5, +1.0, cumulative +1.5 vs UTG
        self.assertEqual(s.next_actor, "UTG")
        self.assertFalse(s.legal_actions("UTG")["raise_reopened"])
        s.apply_action("UTG", "CALL")
        self.assertEqual(s.next_actor, "BTN")
        self.assertFalse(s.legal_actions("BTN")["raise_reopened"])

    def test_full_short_raise_cumulative_reopens(self):
        s = HoldemState.new_hand(
            stacks_bb={"BTN": 100, "SB": 4, "BB": 5, "UTG": 100},
            seat_order=["BTN", "SB", "BB", "UTG"],
            button="BTN",
        )
        s.apply_action("UTG", "RAISE", to_bb=3)  # last full raise = 2
        s.apply_action("BTN", "CALL")
        s.apply_action("SB", "ALL_IN")  # to 4, +1
        s.apply_action("BB", "ALL_IN")  # to 5, +1; cumulative +2 => reopen UTG
        self.assertEqual(s.next_actor, "UTG")
        self.assertTrue(s.legal_actions("UTG")["raise_reopened"])
        s.apply_action("UTG", "RAISE", to_bb=7)
        self.assertEqual(s.next_actor, "BTN")

    def test_side_pots_refund_and_ties_conserve_chips(self):
        s = state3({"BTN": 100, "SB": 60, "BB": 20})
        # Directly model a completed all-in accounting state. Contributions are
        # 100/60/20: 40 BB is uncalled and must be refunded to BTN.
        for name, contrib in {"BTN": 100, "SB": 60, "BB": 20}.items():
            p = s.players[name]
            p.stack_bb = 0
            p.total_contribution_bb = contrib
            p.street_contribution_bb = contrib
            p.all_in = True
        settlement = s.settle({"BTN": 10, "SB": 20, "BB": 20}, rake_net=lambda x: x - 3)
        self.assertAlmostEqual(settlement.refunds_bb["BTN"], 40)
        self.assertEqual([round(p.amount_bb, 6) for p in settlement.pots], [60, 80])
        # Main pot: SB/BB tie; side pot: SB wins; rake is applied once globally.
        self.assertAlmostEqual(settlement.gross_pot_bb, 180)
        self.assertAlmostEqual(settlement.contested_pot_bb, 140)
        self.assertAlmostEqual(settlement.rake_bb, 3)
        total_out = sum(settlement.payouts_bb.values()) + sum(settlement.refunds_bb.values()) + settlement.rake_bb
        self.assertAlmostEqual(total_out, 180)

    def test_folded_money_stays_in_pot_but_player_not_eligible(self):
        s = state3()
        for name, contrib in {"BTN": 10, "SB": 10, "BB": 10}.items():
            p = s.players[name]
            p.total_contribution_bb = contrib
            p.stack_bb = 90
        s.players["SB"].folded = True
        settlement = s.settle({"BTN": 5, "BB": 4})
        self.assertAlmostEqual(settlement.payouts_bb["BTN"], 30)
        self.assertNotIn("SB", settlement.payouts_bb)

    def test_uncontested_overbet_is_refunded(self):
        s = state3()
        for name, contrib in {"BTN": 50, "SB": 20, "BB": 20}.items():
            p = s.players[name]
            p.total_contribution_bb = contrib
        s.players["SB"].folded = True
        s.players["BB"].folded = True
        settlement = s.settle({"BTN": 1})
        self.assertAlmostEqual(settlement.refunds_bb["BTN"], 30)
        self.assertAlmostEqual(settlement.payouts_bb["BTN"], 60)
        self.assertAlmostEqual(settlement.net_by_player_bb["BTN"], 40)

    def test_snapshot_resume_and_hidden_information(self):
        s = state3()
        view = s.player_view("BTN")
        self.assertEqual(view["hero_cards"], ["As", "Ah"])
        self.assertEqual(view["board"], [])
        text = json.dumps(view)
        self.assertNotIn("Ks", text)
        self.assertNotIn("2c", text)
        checkpoint = s.checkpoint()
        restored = HoldemState.from_checkpoint(json.loads(json.dumps(checkpoint)))
        self.assertEqual(restored.checkpoint(), checkpoint)
        restored.apply_action("BTN", "CALL")
        s.apply_action("BTN", "CALL")
        self.assertEqual(restored.checkpoint(), s.checkpoint())

    def test_street_reveals_only_public_runout(self):
        s = state3()
        s.apply_action("BTN", "CALL")
        s.apply_action("SB", "CALL")
        s.apply_action("BB", "CHECK")
        s.advance_street()
        self.assertEqual(s.player_view("BTN")["board"], ["2c", "3d", "7h"])
        self.assertEqual(s.next_actor, "SB")

    def test_incremental_decision_cost_excludes_sunk_blinds(self):
        s = state3()
        self.assertAlmostEqual(s.players["BB"].total_contribution_bb, 1)
        self.assertAlmostEqual(s.incremental_cost_to_bb("BB", 3), 2)

    def test_full_hand_result_includes_blinds(self):
        s = state3()
        s.apply_action("BTN", "FOLD")
        s.apply_action("SB", "FOLD")
        self.assertEqual(s.terminal_reason, "uncontested")
        settlement = s.settle({})
        self.assertAlmostEqual(settlement.net_by_player_bb["BTN"], 0.0)
        self.assertAlmostEqual(settlement.net_by_player_bb["SB"], -0.5)
        self.assertAlmostEqual(settlement.net_by_player_bb["BB"], 0.5)

    def test_incomplete_postflop_allin_can_be_completed_to_full_bet(self):
        s = state3({"BTN": 100, "SB": 1.5, "BB": 100})
        s.apply_action("BTN", "CALL")
        s.apply_action("SB", "CALL")
        s.apply_action("BB", "CHECK")
        s.advance_street()
        self.assertEqual(s.next_actor, "SB")
        s.apply_action("SB", "ALL_IN")  # 0.5 BB, below the 1 BB minimum bet
        self.assertEqual(s.next_actor, "BB")
        self.assertAlmostEqual(s.legal_actions("BB")["min_raise_to_bb"], 1.0)
        s.apply_action("BB", "RAISE", to_bb=1.0)
        self.assertEqual(s.next_actor, "BTN")

    def test_short_big_blind_keeps_nominal_bring_in(self):
        s = state3({"BTN": 100, "SB": 100, "BB": 0.3})
        self.assertAlmostEqual(s.current_bet_bb, 1.0)
        self.assertAlmostEqual(s.to_call_bb("BTN"), 1.0)
        s.apply_action("BTN", "CALL")
        s.apply_action("SB", "CALL")
        self.assertTrue(s.betting_round_complete())
        self.assertAlmostEqual(s.players["BB"].total_contribution_bb, 0.3)

    def test_preflop_multiway_allin_builds_main_side_pots_and_refund(self):
        s = state3({"BTN": 100, "SB": 60, "BB": 20})
        s.apply_action("BTN", "ALL_IN")
        s.apply_action("SB", "ALL_IN")
        s.apply_action("BB", "ALL_IN")
        self.assertTrue(s.betting_round_complete())
        pots, refunds = s.build_pots()
        self.assertEqual([round(p.amount_bb, 6) for p in pots], [60, 80])
        self.assertAlmostEqual(refunds["BTN"], 40)
        s.runout_to_showdown()
        settlement = s.settle({"BTN": 10, "SB": 20, "BB": 20})
        self.assertAlmostEqual(sum(settlement.payouts_bb.values()) + sum(settlement.refunds_bb.values()), 180)

    def test_reference_en_fr_hh_prefixes_match_before_every_decision(self):
        fixture = reference_hh_fixture()
        en, fr = fixture["english_lines"], fixture["french_lines"]
        # Every decision boundary is reconstructed independently from a strict prefix.
        for end, actor in zip(fixture["decision_prefix_line_counts"], fixture["expected_next_actor"]):
            a = state_from_pokerstars_prefix("\n".join(en[:end]))
            b = state_from_pokerstars_prefix("\n".join(fr[:end]))
            self.assertEqual(a.checkpoint(), b.checkpoint(), f"language mismatch at line {end}")
            self.assertEqual(a.next_actor, actor)
        preflop = state_from_pokerstars_prefix("\n".join(en[:9]))
        self.assertEqual(preflop.next_actor, "BTN")
        self.assertNotIn("2c", json.dumps(preflop.decision_snapshot("BTN")))
        facing_bet = state_from_pokerstars_prefix("\n".join(en[:15]))
        self.assertEqual(facing_bet.next_actor, "BB")
        self.assertAlmostEqual(facing_bet.to_call_bb("BB"), 4.0)
        self.assertEqual(facing_bet.decision_snapshot("BB")["board"], ["2c", "3d", "7h"])

    def test_normalized_en_fr_prefixes_reconstruct_same_state(self):
        en = [
            {"street": "preflop", "player": "BTN", "action": "RAISE", "to_bb": 3},
            {"street": "preflop", "player": "SB", "action": "FOLD"},
        ]
        fr = [
            # A French parser produces the same normalized semantics.
            {"street": "preflop", "player": "BTN", "action": "RAISE", "to_bb": 3},
            {"street": "preflop", "player": "SB", "action": "FOLD"},
        ]
        a = replay_normalized_actions(state3(), en)
        b = replay_normalized_actions(state3(), fr)
        self.assertEqual(a.checkpoint(), b.checkpoint())
        self.assertEqual(a.next_actor, "BB")
        self.assertAlmostEqual(a.to_call_bb("BB"), 2)

    def test_allin_call_finishes_betting_and_runout(self):
        s = state3({"BTN": 10, "SB": 10, "BB": 10})
        s.apply_action("BTN", "ALL_IN")
        s.apply_action("SB", "ALL_IN")
        s.apply_action("BB", "ALL_IN")
        self.assertFalse(s.needs_action)
        s.runout_to_showdown()
        self.assertEqual(s.street, "river")
        self.assertEqual(s.terminal_reason, "showdown")
        self.assertEqual(s.revealed_board_count, 5)


if __name__ == "__main__":
    unittest.main()
