#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.datasets.certify_population import certify  # noqa: E402


def en_hand(
    hand_id: str,
    *,
    zoom: bool = True,
    stake: str = "100/200",
    max_seats: int = 6,
    real_money: bool = False,
) -> str:
    zoom_token = " Zoom" if zoom else ""
    displayed_stake = f"${stake.split('/')[0]}/${stake.split('/')[1]} USD" if real_money else stake
    return (
        f"PokerStars{zoom_token} Hand #{hand_id}: Hold'em No Limit ({displayed_stake}) - 2026/09/14 20:00:00 CET\n"
        f"Table 'Fixture' {max_seats}-max Seat #1 is the button\n"
        "Seat 1: Hero (20000 in chips)\n"
        "*** SUMMARY ***\n"
        "Total pot 400 | Rake 20\n"
    )


def fr_hand(
    hand_id: str,
    *,
    zoom: bool = True,
    stake: str = "100/200",
    max_seats: int = 6,
) -> str:
    zoom_token = " Zoom" if zoom else ""
    return (
        f"Main PokerStars{zoom_token} n°{hand_id} :  Hold'em No Limit ({stake}) - 14/09/2026 20:00:00 CET\n"
        f"Table 'Fixture FR' {max_seats}-max Seat #1 is the button\n"
        "Seat 1: Hero (20000 in chips)\n"
        "*** SUMMARY ***\n"
        "Pot total 400 | Commission 20\n"
    )


def write_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload.encode("utf-8"))


class PopulationCertificationTest(unittest.TestCase):
    def test_target_is_conservative_across_format_money_and_table_size(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "fixture.zip"
            write_zip(
                archive,
                {
                    "EN Zoom - 100-200 - Play Money.txt": en_hand("1001"),
                    "FR Zoom - 100-200 - Argent fictif.txt": fr_hand("1002"),
                    "Classic - 100-200 - Play Money.txt": en_hand("1003", zoom=False),
                    "Real Zoom.txt": en_hand("1004", real_money=True),
                    "Nine max - 100-200 - Play Money.txt": en_hand("1005", max_seats=9),
                    "Unknown money.txt": en_hand("1006"),
                },
            )
            report = certify([archive])

        self.assertEqual(report["unique_hand_ids"], 6)
        self.assertEqual(report["status"]["ADMISSIBLE"]["unique_hands"], 2)
        self.assertEqual(report["status"]["EXCLUDED"]["unique_hands"], 3)
        self.assertEqual(report["status"]["AMBIGUOUS"]["unique_hands"], 1)
        self.assertIn("format:REGULAR!=ZOOM", report["status"]["EXCLUDED"]["reason_counts"])
        self.assertIn("money:REAL!=PLAY", report["status"]["EXCLUDED"]["reason_counts"])
        self.assertIn("max_seats:9!=6", report["status"]["EXCLUDED"]["reason_counts"])
        self.assertIn("money:UNKNOWN", report["status"]["AMBIGUOUS"]["reason_counts"])
        self.assertEqual(
            sum(report["status"]["ADMISSIBLE"]["split_counts"].values()),
            2,
        )

    def test_duplicate_metadata_conflict_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            zoom = td / "zoom.zip"
            regular = td / "regular.zip"
            write_zip(zoom, {"Zoom - Play Money.txt": en_hand("2001", zoom=True)})
            write_zip(regular, {"Regular - Play Money.txt": en_hand("2001", zoom=False)})
            report = certify([zoom, regular])

        self.assertEqual(report["unique_hand_ids"], 1)
        self.assertEqual(report["status"]["AMBIGUOUS"]["unique_hands"], 1)
        self.assertEqual(report["duplicate_diagnostics"]["metadata_conflict_ids"], ["2001"])
        self.assertEqual(
            report["status"]["AMBIGUOUS"]["reason_counts"],
            {"duplicate_metadata_conflict": 1},
        )

    def test_french_regular_header_is_not_mistaken_for_zoom(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "fixture.zip"
            write_zip(
                archive,
                {"FR - Argent fictif.txt": fr_hand("3001", zoom=False)},
            )
            report = certify([archive])

        self.assertEqual(report["field_counts_unique_hands"]["format"], {"REGULAR": 1})
        self.assertEqual(report["status"]["EXCLUDED"]["unique_hands"], 1)


if __name__ == "__main__":
    unittest.main()
