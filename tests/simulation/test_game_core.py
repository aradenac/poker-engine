import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.game_core import NoLimitHoldemState, RuleError


def arena_net(gross):
    gross = max(0.0, float(gross))
    return gross - min(13.925, 0.055 * gross)


def finish_public_runout(state):
    for cards in (["2c", "3d", "4h"], ["5s"], ["6c"]):
        state.advance_street(cards)
        while state.next_actor:
            state.apply_action(state.next_actor, "CHECK")


class GameCoreTests(unittest.TestCase):
    def test_bb_option_after_two_limps(self):
        s = NoLimitHoldemState(
            seats=["BTN", "SB", "BB"], button="BTN",
            stacks_bb={"BTN": 100, "SB": 100, "BB": 100},
        )
        self.assertEqual(s.next_actor, "BTN")
        s.apply_action("BTN", "CALL")
        s.apply_action("SB", "CALL")
        view = s.legal_view("BB")
        self.assertEqual(view["legal_actions"], ["CHECK", "RAISE"])
        self.assertEqual(view["to_call_bb"], 0)
        self.assertEqual(view["actor_sunk_total_bb"], 1)
        s.apply_action("BB", "CHECK")
        self.assertEqual(s.pot_bb, 3)
        self.assertTrue(s.betting_complete)

    def test_short_allin_raise_does_not_reopen(self):
        s = NoLimitHoldemState(
            seats=["BTN", "SB", "BB"], button="BTN",
            stacks_bb={"BTN": 100, "SB": 4, "BB": 100},
        )
        s.apply_action("BTN", "RAISE", target_total_bb=3)
        s.apply_action("SB", "RAISE", target_total_bb=4)
        self.assertTrue(s.all_in["SB"])
        self.assertEqual(s.legal_view("BB")["min_raise_to_bb"], 6)
        s.apply_action("BB", "CALL")
        btn = s.legal_view("BTN")
        self.assertFalse(btn["raise_reopened"])
        self.assertEqual(btn["legal_actions"], ["FOLD", "CALL"])
        with self.assertRaises(RuleError):
            s.apply_action("BTN", "RAISE", target_total_bb=10)

    def test_full_raise_after_short_raise_reopens(self):
        s = NoLimitHoldemState(
            seats=["BTN", "SB", "BB", "UTG"], button="BTN",
            stacks_bb={"BTN": 100, "SB": 4, "BB": 100, "UTG": 100},
        )
        s.apply_action("UTG", "RAISE", target_total_bb=3)
        s.apply_action("BTN", "CALL")
        s.apply_action("SB", "RAISE", target_total_bb=4)
        self.assertTrue(s.legal_view("BB")["raise_reopened"])
        s.apply_action("BB", "RAISE", target_total_bb=6)
        self.assertTrue(s.legal_view("UTG")["raise_reopened"])
        self.assertEqual(s.legal_view("UTG")["min_raise_to_bb"], 8)

    def test_preflop_side_pots_and_eligibility(self):
        s = NoLimitHoldemState(
            seats=["BTN", "SB", "BB", "UTG"], button="BTN",
            stacks_bb={"BTN": 100, "SB": 20, "BB": 8, "UTG": 100},
        )
        s.apply_action("UTG", "RAISE", target_total_bb=20)
        s.apply_action("BTN", "CALL")
        s.apply_action("SB", "CALL")
        s.apply_action("BB", "CALL")
        self.assertTrue(s.betting_complete)
        self.assertEqual(s.total_committed_bb, {"BTN": 20, "SB": 20, "BB": 8, "UTG": 20})
        pots = s.pot_layers()
        self.assertEqual([p.amount_bb for p in pots], [32, 36])
        self.assertEqual(pots[0].eligible, ("BTN", "SB", "BB", "UTG"))
        self.assertEqual(pots[1].eligible, ("BTN", "SB", "UTG"))
        finish_public_runout(s)
        out = s.settle_showdown({"UTG": (1,), "BTN": (2,), "SB": (3,), "BB": (4,)})
        self.assertEqual(out.payouts_bb["BB"], 32)
        self.assertEqual(out.payouts_bb["SB"], 36)
        self.assertAlmostEqual(sum(out.net_results_bb.values()), 0)

    def test_folded_player_funds_pot_but_is_ineligible(self):
        s = NoLimitHoldemState(
            seats=["BTN", "SB", "BB", "UTG"], button="BTN",
            stacks_bb={"BTN": 100, "SB": 100, "BB": 100, "UTG": 100},
        )
        s.apply_action("UTG", "RAISE", target_total_bb=5)
        s.apply_action("BTN", "CALL")
        s.apply_action("SB", "FOLD")
        s.apply_action("BB", "CALL")
        s.advance_street(["2c", "3d", "4h"])
        self.assertEqual(s.next_actor, "BB")
        s.apply_action("BB", "CHECK")
        s.apply_action("UTG", "RAISE", target_total_bb=10)
        s.apply_action("BTN", "CALL")
        s.apply_action("BB", "FOLD")
        pots = s.pot_layers()
        self.assertTrue(all("BB" not in p.eligible for p in pots))
        self.assertTrue(any("BB" in p.contributors for p in pots))

    def test_unique_overbet_is_refunded_before_showdown(self):
        s = NoLimitHoldemState(
            seats=["BTN", "BB"], button="BTN",
            stacks_bb={"BTN": 100, "BB": 8},
        )
        s.apply_action("BTN", "RAISE", target_total_bb=100)
        s.apply_action("BB", "CALL")
        finish_public_runout(s)
        out = s.settle_showdown({"BTN": (2,), "BB": (1,)})
        self.assertEqual(out.refunds_bb["BTN"], 92)
        self.assertEqual(out.gross_pot_bb, 16)
        self.assertEqual(out.net_results_bb, {"BTN": 8, "BB": -8})

    def test_tie_splits_each_eligible_layer(self):
        s = NoLimitHoldemState(
            seats=["BTN", "SB", "BB", "UTG"], button="BTN",
            stacks_bb={"BTN": 20, "SB": 20, "BB": 8, "UTG": 20},
        )
        s.apply_action("UTG", "RAISE", target_total_bb=20)
        s.apply_action("BTN", "CALL")
        s.apply_action("SB", "CALL")
        s.apply_action("BB", "CALL")
        finish_public_runout(s)
        out = s.settle_showdown({"BB": (9,), "BTN": (5,), "SB": (5,), "UTG": (4,)})
        self.assertEqual(out.payouts_bb["BB"], 32)
        self.assertEqual(out.payouts_bb["BTN"], 18)
        self.assertEqual(out.payouts_bb["SB"], 18)

    def test_population_rake_preserves_chips_plus_rake(self):
        s = NoLimitHoldemState(
            seats=["BTN", "BB"], button="BTN",
            stacks_bb={"BTN": 100, "BB": 100},
        )
        s.apply_action("BTN", "CALL")
        s.apply_action("BB", "CHECK")
        for cards in (["2c", "3d", "4h"], ["5s"], ["6c"]):
            s.advance_street(cards)
            while s.next_actor:
                s.apply_action(s.next_actor, "CHECK")
        out = s.settle_showdown({"BTN": (1,), "BB": (2,)}, net_pot_fn=arena_net)
        self.assertAlmostEqual(out.rake_bb, 0.11)
        self.assertAlmostEqual(sum(s.stacks_bb.values()) + out.rake_bb, 200)

    def test_snapshot_resume_contains_no_hidden_cards(self):
        s = NoLimitHoldemState(
            seats=["BTN", "SB", "BB"], button="BTN",
            stacks_bb={"BTN": 100, "SB": 100, "BB": 100},
        )
        s.apply_action("BTN", "RAISE", target_total_bb=2.5)
        snap = s.to_snapshot()
        text = repr(snap)
        self.assertNotIn("hole", text.lower())
        self.assertNotIn("hero_cards", text)
        restored = NoLimitHoldemState.from_snapshot(copy.deepcopy(snap))
        self.assertEqual(restored.to_snapshot(), snap)
        self.assertEqual(restored.legal_view(), s.legal_view())
        restored.apply_action("SB", "CALL")
        s.apply_action("SB", "CALL")
        self.assertEqual(restored.to_snapshot(), s.to_snapshot())

    def test_four_street_order_and_public_board(self):
        s = NoLimitHoldemState(
            seats=["BTN", "SB", "BB"], button="BTN",
            stacks_bb={"BTN": 100, "SB": 100, "BB": 100},
        )
        s.apply_action("BTN", "CALL")
        s.apply_action("SB", "CALL")
        s.apply_action("BB", "CHECK")
        self.assertEqual(s.board, [])
        s.advance_street(["As", "Kd", "2c"])
        self.assertEqual(s.next_actor, "SB")
        for street_cards in (["Qh"], ["Jc"]):
            while s.next_actor:
                s.apply_action(s.next_actor, "CHECK")
            s.advance_street(street_cards)
        while s.next_actor:
            s.apply_action(s.next_actor, "CHECK")
        self.assertEqual(s.street, "river")
        self.assertEqual(s.board, ["As", "Kd", "2c", "Qh", "Jc"])
        self.assertTrue(s.betting_complete)

    def test_showdown_cannot_skip_remaining_public_streets(self):
        s = NoLimitHoldemState(
            seats=["BTN", "BB"], button="BTN",
            stacks_bb={"BTN": 8, "BB": 8},
        )
        s.apply_action("BTN", "RAISE", target_total_bb=8)
        s.apply_action("BB", "CALL")
        with self.assertRaisesRegex(RuleError, "through river"):
            s.settle_showdown({"BTN": (2,), "BB": (1,)})
        finish_public_runout(s)
        s.settle_showdown({"BTN": (2,), "BB": (1,)})

    def test_decision_view_separates_sunk_and_incremental_cost(self):
        s = NoLimitHoldemState(
            seats=["BTN", "BB"], button="BTN",
            stacks_bb={"BTN": 100, "BB": 100},
        )
        view = s.legal_view("BTN")
        self.assertEqual(view["actor_sunk_total_bb"], 0.5)
        self.assertEqual(view["to_call_bb"], 0.5)
        self.assertEqual(view["pot_before_bb"], 1.5)

    def test_fold_settlement_refunds_uncalled_raise(self):
        s = NoLimitHoldemState(
            seats=["BTN", "BB"], button="BTN",
            stacks_bb={"BTN": 100, "BB": 100},
        )
        s.apply_action("BTN", "RAISE", target_total_bb=3)
        s.apply_action("BB", "FOLD")
        out = s.settle_by_fold()
        self.assertEqual(out.refunds_bb["BTN"], 2)
        self.assertEqual(out.gross_pot_bb, 2)
        self.assertEqual(out.payouts_bb["BTN"], 2)
        self.assertEqual(out.net_results_bb, {"BTN": 1, "BB": -1})


if __name__ == "__main__":
    unittest.main()
