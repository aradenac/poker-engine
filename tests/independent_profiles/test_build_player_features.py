#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import split_for  # noqa: E402
from tools.training.independent_profiles.build_player_features import (  # noqa: E402
    build_output,
    merge_archives,
)


def id_for(split: str, start: int) -> str:
    value = start
    while split_for(str(value)) != split:
        value += 1
    return str(value)


def english_hand(hand_id: str, villain: str, actions: list[str], stake: str = "100/200") -> str:
    return "\n".join([
        f"PokerStars Hand #{hand_id}: Hold'em No Limit ({stake}) - 2026/09/10 12:00:00 CET",
        "Table 'Test' 6-max Seat #1 is the button",
        "Seat 1: Hero (20000 in chips)",
        f"Seat 2: {villain} (20000 in chips)",
        "*** HOLE CARDS ***",
        *actions,
        "*** SUMMARY ***",
        "",
    ])


def french_hand(hand_id: str, villain: str, actions: list[str], stake: str = "100/200") -> str:
    return "\n".join([
        f"Main PokerStars n°{hand_id} :  Hold'em No Limit ({stake}) - 10/09/2026 12:00:00 CET [10/09/2026 6:00:00 ET]",
        "Table 'Test' 6-max Seat #1 is the button",
        "Siège 1: Hero (20000 en jetons)",
        f"Siège 2: {villain} (20000 en jetons)",
        "*** CARTES FERMÉES ***",
        *actions,
        "*** RÉSUMÉ ***",
        "",
    ])


def legacy_french_hand(hand_id: str, villain: str, actions: list[str], stake: str = "100/200") -> str:
    return "\n".join([
        f"Main PokerStars n°{hand_id} :  Hold'em No Limit ({stake}) - 10/09/2026 12:00:00 CET [10/09/2026 6:00:00 ET]",
        "Table 'Test' 6-max Seat #1 is the button",
        "Place 1: Hero (20000 en jetons)",
        f"Place 2: {villain} (20000 en jetons)",
        "Hero: met 100",
        f"{villain}: met 200",
        "*** CARTES FERMÉES ***",
        *actions,
        "*** RÉSUMÉ ***",
        "",
    ])


def write_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text.encode("utf-8"))


class PlayerFeatureBuilderTest(unittest.TestCase):
    def test_train_only_features_support_en_and_fr(self):
        h1 = id_for("TRAIN", 10000)
        h2 = id_for("TRAIN", int(h1) + 1)
        h3 = id_for("TEST", int(h2) + 1)
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "hands.zip"
            write_zip(archive, {
                "en.txt": english_hand(h1, "Villain", [
                    "Hero: calls 100",
                    "Villain: raises 200 to 400",
                    "Hero: folds",
                    "*** FLOP *** [2c 7d Jh]",
                ]),
                "fr.txt": french_hand(h2, "Villain", [
                    "Hero: suit 100",
                    "Villain: relance 200 à 400",
                    "Hero: se couche",
                    "*** FLOP *** [2c 7d Jh]",
                    "Villain: mise 300",
                ]),
                "test.txt": english_hand(h3, "Villain", ["Villain: folds"]),
            })
            by_id, provenance = merge_archives([archive], {"100/200"})
            out = build_output(by_id, provenance, {"Hero"}, min_hands=1, prior_strength=10.0)
            players = {p["player"]: p for p in out["players"]}
            self.assertNotIn("Hero", players)
            self.assertIn("Villain", players)
            v = players["Villain"]["counts"]
            self.assertEqual(v["appearances"], 2)
            self.assertEqual(v["pfr_hands"], 2)
            self.assertEqual(v["vpip_hands"], 2)
            self.assertEqual(v["post_bet"], 1)
            self.assertEqual(out["train_unique_hands"], 2)
            self.assertEqual(out["train_language_counts"], {"en": 1, "fr": 1})

    def test_legacy_french_place_and_passe_are_parsed(self):
        hid = id_for("TRAIN", 15000)
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "legacy-fr.zip"
            write_zip(archive, {
                "fr.txt": legacy_french_hand(hid, "Villain", [
                    "Hero: suit 100",
                    "Villain: relance 200 à 400",
                    "Hero: passe.",
                    "*** FLOP *** [2c 7d Jh]",
                    "Villain: parole",
                ]),
            })
            by_id, provenance = merge_archives([archive], {"100/200"})
            out = build_output(by_id, provenance, {"Hero"}, min_hands=1, prior_strength=10.0)
            villain = next(p for p in out["players"] if p["player"] == "Villain")
            self.assertEqual(villain["counts"]["appearances"], 1)
            self.assertEqual(villain["counts"]["pfr_hands"], 1)
            self.assertEqual(villain["counts"]["vpip_hands"], 1)
            self.assertEqual(villain["counts"]["post_check"], 1)
            self.assertEqual(out["parser_audit"]["counts"].get("fr|hands_without_seats", 0), 0)
            self.assertEqual(out["parser_audit"]["counts"].get("fr|unmatched_actor_lines", 0), 0)

    def test_mixed_stake_archive_is_scoped_before_fit(self):
        h1 = id_for("TRAIN", 20000)
        h2 = id_for("TRAIN", int(h1) + 1)
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "mixed.zip"
            write_zip(archive, {
                "a.txt": english_hand(h1, "A", ["A: calls 200"], "100/200"),
                "b.txt": english_hand(h2, "B", ["B: calls 500"], "250/500"),
            })
            by_id, provenance = merge_archives([archive], {"100/200"})
            out = build_output(by_id, provenance, set(), min_hands=1, prior_strength=10.0)
            names = {p["player"] for p in out["players"]}
            self.assertIn("A", names)
            self.assertNotIn("B", names)
            self.assertEqual(provenance["unique_scoped_hands"], 1)

    def test_duplicate_id_prefers_english_representation(self):
        hid = id_for("TRAIN", 30000)
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            first = td / "fr.zip"
            second = td / "en.zip"
            write_zip(first, {"fr.txt": french_hand(hid, "Villain", ["Villain: suit 200"])})
            write_zip(second, {"en.txt": english_hand(hid, "Villain", ["Villain: raises 200 to 400"])})
            by_id, provenance = merge_archives([first, second], {"100/200"})
            self.assertEqual(by_id[hid].language, "en")
            self.assertEqual(provenance["overlap_occurrences"], 1)
            self.assertEqual(provenance["english_preferred_replacements"], 1)
            out = build_output(by_id, provenance, set(), min_hands=1, prior_strength=10.0)
            villain = next(p for p in out["players"] if p["player"] == "Villain")
            self.assertEqual(villain["counts"]["pfr_hands"], 1)

    def test_output_is_json_serializable(self):
        hid = id_for("TRAIN", 40000)
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "hands.zip"
            write_zip(archive, {"a.txt": english_hand(hid, "V", ["V: checks"])})
            by_id, provenance = merge_archives([archive], {"100/200"})
            out = build_output(by_id, provenance, set(), min_hands=1, prior_strength=10.0)
            json.dumps(out)


if __name__ == "__main__":
    unittest.main()
