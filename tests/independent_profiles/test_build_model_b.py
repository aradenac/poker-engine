#!/usr/bin/env python3
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import HandRecord  # noqa: E402
from tools.training.independent_profiles.build_model_b import (  # noqa: E402
    FEATURE_KEYS,
    build_behavior_tables,
    fit_profiles,
    hand_notations,
    parse_action_line,
    parse_hand,
)


def player(name: str, values: list[float], appearances: int = 60) -> dict:
    return {
        "player": name,
        "eligible_default": True,
        "counts": {"appearances": appearances},
        "rates": dict(zip(FEATURE_KEYS, values)),
        "shrunk_rates": dict(zip(FEATURE_KEYS, values)),
    }


def feature_doc() -> dict:
    # Three deliberately separated behavioural groups, four players each.
    rows = []
    groups = [
        [0.18, 0.05, 0.08, 0.03, 0.12, 0.58],
        [0.42, 0.08, 0.28, 0.05, 0.19, 0.48],
        [0.68, 0.18, 0.36, 0.11, 0.34, 0.35],
    ]
    for g, base in enumerate(groups):
        for i in range(4):
            values = [max(0.0, min(1.0, x + (i - 1.5) * 0.002)) for x in base]
            rows.append(player(f"G{g}_{i}", values, 50 + i * 5))
    return {"players": rows, "split_used_for_fit": "TRAIN"}


def english_record() -> HandRecord:
    text = "\n".join([
        "PokerStars Hand #900001: Hold'em No Limit (100/200) - 2026/09/10 12:00:00 CET",
        "Table 'Test' 2-max Seat #1 is the button",
        "Seat 1: Hero (20000 in chips)",
        "Seat 2: Villain (20000 in chips)",
        "Hero: posts small blind 100",
        "Villain: posts big blind 200",
        "*** HOLE CARDS ***",
        "Dealt to Hero [Qs Qh]",
        "Hero: calls 100",
        "Villain: checks",
        "*** FLOP *** [2c 7d Jh]",
        "Villain: checks",
        "Hero: bets 200",
        "Villain: calls 200",
        "*** TURN *** [2c 7d Jh] [9s]",
        "Villain: bets 400",
        "Hero: calls 400",
        "*** RIVER *** [2c 7d Jh 9s] [3c]",
        "Villain: checks",
        "Hero: checks",
        "*** SHOW DOWN ***",
        "Villain: shows [As Kd]",
        "*** SUMMARY ***",
        "",
    ])
    return HandRecord("900001", "synthetic.txt", text, "2026-09-10 12:00:00", "en", "100/200")


class ModelBBuilderTest(unittest.TestCase):
    def test_hand_notation_contract_is_complete(self):
        names, multiplicity = hand_notations()
        self.assertEqual(len(names), 169)
        self.assertEqual(len(set(names)), 169)
        self.assertEqual(multiplicity["AA"], 6)
        self.assertEqual(multiplicity["AKs"], 4)
        self.assertEqual(multiplicity["AKo"], 12)
        self.assertEqual(sum(multiplicity.values()), 1326)

    def test_profile_fit_is_deterministic_and_canonical(self):
        doc = feature_doc()
        a = fit_profiles(doc, 3)
        b = fit_profiles(doc, 3)
        self.assertEqual(a["player_profile"], b["player_profile"])
        self.assertEqual(a["profiles"], b["profiles"])
        self.assertEqual(len(a["profiles"]), 3)
        self.assertAlmostEqual(sum(p["appearance_weight"] for p in a["profiles"]), 1.0)
        vpips = [p["centroid"]["vpip"] for p in a["profiles"]]
        self.assertEqual(vpips, sorted(vpips))

    def test_postflop_tables_and_preflop_range_are_empirical(self):
        record = english_record()
        parsed = parse_hand(record)
        self.assertIsNotNone(parsed)
        ranges, actions, sizings, audit = build_behavior_tables(
            [record], {"Villain": 0}, {"Hero"}
        )
        self.assertEqual(audit["known_preflop_hands"], 1)
        self.assertEqual(audit["postflop_decisions"], 4)  # check/call/bet/check
        self.assertEqual(audit["sizing_observations"], 1)

        all_ranges = ranges["levels"][-1]["data"]["ALL"]
        self.assertEqual(all_ranges["n"], 1)
        self.assertEqual(all_ranges["counts"], {"AKo": 1})

        all_actions = actions["levels"][-1]["data"]["ALL"]
        self.assertEqual(all_actions["n"], 4)
        self.assertEqual(all_actions["counts"]["CHECK"], 2)
        self.assertEqual(all_actions["counts"]["CALL"], 1)
        self.assertEqual(all_actions["counts"]["BET"], 1)

        all_sizing = sizings["levels"][-1]["data"]["ALL"]
        self.assertEqual(all_sizing["n"], 1)
        self.assertTrue(math.isfinite(all_sizing["p50"]))
        self.assertGreater(all_sizing["p50"], 0)
        json.dumps((ranges, actions, sizings))

    def test_legacy_french_action_grammar(self):
        players = {"Hero", "Villain"}
        raise_ev = parse_action_line("Villain: relance 200 à 400", players)
        fold_ev = parse_action_line("Hero: passe.", players)
        post_ev = parse_action_line("Villain: met 200", players)
        self.assertEqual(raise_ev["type"], "raise")
        self.assertEqual(raise_ev["amount"], 200)
        self.assertEqual(raise_ev["to"], 400)
        self.assertEqual(fold_ev["type"], "fold")
        self.assertEqual(post_ev["type"], "post")


if __name__ == "__main__":
    unittest.main()
