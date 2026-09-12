#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import (  # noqa: E402
    build_increment,
    parse_hand_blocks,
    split_for,
    write_selected_zip,
)


def en_hand(hand_id: str, date: str = "2026/09/10 12:00:00") -> str:
    return (
        f"PokerStars Hand #{hand_id}: Hold'em No Limit (100/200) - {date} CET\n"
        "Table 'Test' 6-max Seat #1 is the button\n"
        "Seat 1: Hero (20000 in chips)\n"
        "*** SUMMARY ***\n"
    )


def fr_hand(hand_id: str, date: str = "10/09/2026 12:00:00") -> str:
    return (
        f"Main PokerStars n°{hand_id} :  Hold'em No Limit (100/200) - {date} CET [10/09/2026 6:00:00 ET]\n"
        "Table 'Test' 6-max Seat #1 is the button\n"
        "Seat 1: Hero (20000 in chips)\n"
        "*** SUMMARY ***\n"
    )


def make_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text.encode("utf-8"))


class IncrementBuilderTest(unittest.TestCase):
    def test_parser_supports_english_and_french_headers(self):
        records = parse_hand_blocks(en_hand("1001") + "\n" + fr_hand("1002"), "mixed.txt")
        self.assertEqual([r.hand_id for r in records], ["1001", "1002"])
        self.assertEqual([r.language for r in records], ["en", "fr"])
        self.assertEqual(records[0].timestamp, "2026-09-10 12:00:00")
        self.assertEqual(records[1].timestamp, "2026-09-10 12:00:00")

    def test_overlap_is_deduplicated_by_hand_id(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            known = td / "known.zip"
            candidate = td / "candidate.zip"
            make_zip(known, {"known.txt": en_hand("2001") + en_hand("2002")})
            make_zip(candidate, {
                "new.txt": en_hand("2002") + fr_hand("2003") + en_hand("2004")
            })

            manifest, selected = build_increment([known], candidate)
            self.assertEqual([r.hand_id for r in selected], ["2003", "2004"])
            self.assertEqual(manifest["selected_unique_hands"], 2)
            self.assertEqual(sum(manifest["split_counts"].values()), 2)
            self.assertEqual(manifest["language_counts"], {"en": 1, "fr": 1})

    def test_reimport_of_known_archive_selects_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            archive = td / "same.zip"
            make_zip(archive, {"same.txt": en_hand("3001") + fr_hand("3002")})
            manifest, selected = build_increment([archive], archive)
            self.assertEqual(selected, [])
            self.assertEqual(manifest["selected_unique_hands"], 0)
            self.assertEqual(manifest["split_counts"], {
                "TRAIN": 0, "VALIDATION": 0, "TEST": 0
            })

    def test_split_is_stable(self):
        ids = ["4001", "4002", "4003", "262007260864"]
        first = [split_for(x) for x in ids]
        second = [split_for(x) for x in ids]
        self.assertEqual(first, second)
        self.assertTrue(all(x in {"TRAIN", "VALIDATION", "TEST"} for x in first))

    def test_materialized_zip_contains_only_selected_hands(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            known = td / "known.zip"
            candidate = td / "candidate.zip"
            output = td / "delta.zip"
            make_zip(known, {"known.txt": en_hand("5001")})
            make_zip(candidate, {"session.txt": en_hand("5001") + en_hand("5002")})
            _, selected = build_increment([known], candidate)
            write_selected_zip(output, selected)
            with zipfile.ZipFile(output) as zf:
                payload = zf.read("session.txt").decode("utf-8")
            self.assertNotIn("#5001", payload)
            self.assertIn("#5002", payload)


if __name__ == "__main__":
    unittest.main()
