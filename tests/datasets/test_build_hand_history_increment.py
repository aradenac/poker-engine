#!/usr/bin/env python3
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
    read_archive,
    split_for,
    write_selected_zip,
)


def en_hand(hand_id: str, date: str = "2026/09/10 12:00:00", stake: str = "100/200") -> str:
    return (
        f"PokerStars Hand #{hand_id}: Hold'em No Limit ({stake}) - {date} CET\n"
        "Table 'Test' 6-max Seat #1 is the button\n"
        "Seat 1: Hero (20000 in chips)\n"
        "*** SUMMARY ***\n"
    )


def fr_hand(hand_id: str, date: str = "10/09/2026 12:00:00", stake: str = "100/200") -> str:
    return (
        f"Main PokerStars n°{hand_id} :  Hold'em No Limit ({stake}) - {date} CET [10/09/2026 6:00:00 ET]\n"
        "Table 'Test' 6-max Seat #1 is the button\n"
        "Seat 1: Hero (20000 in chips)\n"
        "*** SUMMARY ***\n"
    )


def make_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text.encode("utf-8"))


class IncrementBuilderTest(unittest.TestCase):
    def test_selected_zip_has_fixed_metadata_and_bytes(self):
        from unittest.mock import patch
        records = parse_hand_blocks(en_hand("123"), "hands.txt")
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td) / "a.zip", Path(td) / "b.zip"
            with patch("zipfile.time.localtime", side_effect=AssertionError("wall clock used")):
                write_selected_zip(a, records)
                write_selected_zip(b, records)
            self.assertEqual(a.read_bytes(), b.read_bytes())
            with zipfile.ZipFile(a) as archive:
                self.assertEqual(archive.infolist()[0].date_time, (1980, 1, 1, 0, 0, 0))


    def test_parser_supports_english_and_french_headers(self):
        records = parse_hand_blocks(en_hand("1001") + "\n" + fr_hand("1002"), "mixed.txt")
        self.assertEqual([r.hand_id for r in records], ["1001", "1002"])
        self.assertEqual([r.language for r in records], ["en", "fr"])
        self.assertEqual([r.stake for r in records], ["100/200", "100/200"])
        self.assertEqual(records[0].timestamp, "2026-09-10 12:00:00")
        self.assertEqual(records[1].timestamp, "2026-09-10 12:00:00")

    def test_overlap_is_deduplicated_by_hand_id(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            known = td / "known.zip"
            candidate = td / "candidate.zip"
            make_zip(known, {"known.txt": en_hand("2001") + en_hand("2002")})
            make_zip(candidate, {"new.txt": en_hand("2002") + fr_hand("2003") + en_hand("2004")})
            manifest, selected = build_increment([known], candidate, {"100/200"})
            self.assertEqual([r.hand_id for r in selected], ["2003", "2004"])
            self.assertEqual(manifest["selected_unique_hands"], 2)
            self.assertEqual(sum(manifest["split_counts"].values()), 2)
            self.assertEqual(manifest["language_counts"], {"en": 1, "fr": 1})
            self.assertEqual(manifest["stake_counts"], {"100/200": 2})

    def test_stake_filter_excludes_other_limits(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            known = td / "known.zip"
            candidate = td / "candidate.zip"
            make_zip(known, {"known.txt": en_hand("2101")})
            make_zip(candidate, {
                "mixed.txt": en_hand("2102", stake="100/200") + en_hand("2103", stake="250/500")
            })
            manifest, selected = build_increment([known], candidate, {"100/200"})
            self.assertEqual([r.hand_id for r in selected], ["2102"])
            self.assertEqual(manifest["scope"], {"stakes": ["100/200"]})
            self.assertEqual(manifest["stake_counts"], {"100/200": 1})

    def test_reimport_of_known_archive_selects_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            archive = td / "same.zip"
            make_zip(archive, {"same.txt": en_hand("3001") + fr_hand("3002")})
            manifest, selected = build_increment([archive], archive, {"100/200"})
            self.assertEqual(selected, [])
            self.assertEqual(manifest["selected_unique_hands"], 0)
            self.assertEqual(manifest["split_counts"], {"TRAIN": 0, "VALIDATION": 0, "TEST": 0})

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
            _, selected = build_increment([known], candidate, {"100/200"})
            write_selected_zip(output, selected)
            with zipfile.ZipFile(output) as zf:
                payload = zf.read("session.txt").decode("utf-8")
            self.assertNotIn("#5001", payload)
            self.assertIn("#5002", payload)

    def test_real_20260909_snapshot_preserves_previous_delta_and_finds_more_evidence(self):
        baseline = ROOT / "training/datasets/NLHE_100-200/source/NLHE 100-200.zip"
        snapshot = ROOT / "training/datasets/NLHE_100-200/snapshots/20260909/source/RoiDePiqueNique_training2.zip"
        old_delta = ROOT / "training/runs/20260909_population_increment_v2/source/RoiDePiqueNique_training2_delta_after_v4v5.zip"
        if not baseline.exists() or not snapshot.exists() or not old_delta.exists():
            self.skipTest("persisted NLHE archives not present")

        manifest, selected = build_increment([baseline], snapshot, {"100/200"})
        self.assertEqual(manifest["scope"], {"stakes": ["100/200"]})
        new = manifest["chronological_new"]
        self.assertEqual(new["unique_hands"], 1175)
        self.assertEqual(new["split_counts"], {"TRAIN": 929, "VALIDATION": 123, "TEST": 123})
        self.assertEqual(new["stake_counts"], {"100/200": 1175})
        self.assertEqual(
            new["hand_ids_fingerprint_sha256"],
            "6142a129292d486c7dedd2aec951b98ed180302d598d38508f45e222f7544bc0",
        )
        self.assertEqual(new["earliest_local_timestamp"], "2026-09-07 23:10:38")
        self.assertEqual(new["latest_local_timestamp"], "2026-09-09 17:48:16")
        self.assertEqual(manifest["undated_unseen"]["unique_hands"], 0)

        old_records, _ = read_archive(old_delta)
        old_ids = {r.hand_id for r in old_records if r.stake == "100/200"}
        new_ids = set(manifest["selected_hand_ids"])
        chronological_ids = {
            r.hand_id for r in selected
            if r.timestamp and r.timestamp > manifest["known_latest_local_timestamp"]
        }
        self.assertEqual(len(old_ids), 1000)
        self.assertTrue(old_ids <= chronological_ids)
        self.assertEqual(len(chronological_ids - old_ids), 175)
        self.assertTrue(chronological_ids <= new_ids)
        print(
            "100/200 ID ingestion: selected=%d backfill=%d chronological=%d; old delta is a 1000-hand subset with 175 additional chronological hands discovered"
            % (manifest["selected_unique_hands"], manifest["historical_backfill"]["unique_hands"], new["unique_hands"])
        )


if __name__ == "__main__":
    unittest.main()

