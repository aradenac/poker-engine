import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.game_core import NoLimitHoldemState, RuleError


class ConsolidatedGameCoreRegressionTests(unittest.TestCase):
    def test_short_postflop_opening_allin_can_be_completed_to_full_bet_multiway(self):
        """A sub-1-BB opening all-in may be completed to one full bet when action remains."""
        s = NoLimitHoldemState(
            seats=["BTN", "SB", "BB"],
            button="BTN",
            stacks_bb={"BTN": 100, "SB": 100, "BB": 1.4},
        )
        s.apply_action("BTN", "CALL")
        s.apply_action("SB", "CALL")
        s.apply_action("BB", "CHECK")
        s.advance_street(["2c", "3d", "4h"])

        s.apply_action("SB", "CHECK")
        bb = s.legal_view("BB")
        self.assertEqual(bb["min_raise_to_bb"], 1.0)
        self.assertEqual(bb["max_raise_to_bb"], 0.4)
        s.apply_action("BB", "RAISE", target_total_bb=0.4)
        self.assertTrue(s.all_in["BB"])

        btn = s.legal_view("BTN")
        self.assertTrue(btn["raise_reopened"])
        self.assertEqual(btn["current_price_bb"], 0.4)
        self.assertEqual(btn["min_raise_to_bb"], 1.0)
        self.assertIn("RAISE", btn["legal_actions"])
        s.apply_action("BTN", "RAISE", target_total_bb=1.0)

        sb = s.legal_view("SB")
        self.assertEqual(sb["to_call_bb"], 1.0)
        self.assertEqual(sb["min_raise_to_bb"], 2.0)

    def test_no_raise_into_uncontestable_heads_up_allin_pot(self):
        """Once the only opponent is all-in, extra chips cannot create a contested pot."""
        s = NoLimitHoldemState(
            seats=["BTN", "BB"],
            button="BTN",
            stacks_bb={"BTN": 100, "BB": 1.4},
        )
        s.apply_action("BTN", "CALL")
        s.apply_action("BB", "CHECK")
        s.advance_street(["2c", "3d", "4h"])

        s.apply_action("BB", "RAISE", target_total_bb=0.4)
        view = s.legal_view("BTN")
        self.assertEqual(view["legal_actions"], ["FOLD", "CALL"])
        self.assertNotIn("RAISE", view["legal_actions"])
        with self.assertRaises(RuleError):
            s.apply_action("BTN", "RAISE", target_total_bb=1.0)


if __name__ == "__main__":
    unittest.main()
