#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.datasets.build_population_increment import build_population_increment  # noqa: E402
from tools.datasets.build_hand_history_increment import read_archive  # noqa: E402

POP = "fixture_zoom_play_100_200"


def hand(
    hand_id: str,
    *,
    zoom: bool = True,
    max_seats: int | None = 6,
    play: bool = True,
    stake: str = "100/200",
    hour: int = 12,
) -> str:
    zoom_token = " Zoom" if zoom else ""
    money = " Play Money" if play else ""
    table = "Table 'Fixture'"
    if max_seats is not None:
        table += f" {max_seats}-max"
    return (
        f"PokerStars{zoom_token} Hand #{hand_id}: Hold'em No Limit ({stake}) - 2026/09/17 {hour:02d}:00:00 ET{money}\n"
        f"{table} Seat #1 is the button\n"
        "Seat 1: Hero (20000 in chips)\n"
        "Seat 2: Villain (20000 in chips)\n"
        "*** HOLE CARDS ***\n"
        "Hero: folds\n"
        "*** SUMMARY ***\n"
        "Total pot 300 | Rake 0\n"
    )


def write_zip(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    info = zipfile.ZipInfo("hands.txt", date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr(info, "\n".join(rows).encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def registry(root: Path) -> Path:
    value = {
        "schema": "poker-population-registry/v1",
        "default_population": POP,
        "populations": {
            POP: {
                "status": "CERTIFIED_DATA_ONLY",
                "identity": {
                    "platform": "PokerStars",
                    "variant": "NLHE",
                    "game_kind": "cash",
                    "stake": "100/200",
                    "money": "play",
                    "currency": "PLAY_CHIPS",
                    "format": "ZOOM",
                    "max_seats": 6,
                    "rake": {"policy": "FIXTURE"},
                },
                "data": {
                    "dataset_id": POP,
                    "root": "population/data",
                    "baseline_archive": "population/data/baseline.zip",
                    "snapshots_root": "population/data/snapshots",
                    "increments_root": "population/data/increments",
                },
                "artifacts": {
                    "model_a_preflop": None,
                    "model_a_postflop": None,
                    "model_b": None,
                    "hero_strategy": None,
                    "engine": None,
                    "pack": None,
                },
                "storage": {"runs_root": "population/runs", "cache_namespace": POP},
                "compatibility": {"legacy_unscoped_artifacts_allowed": False},
                "promotion_history": [],
            }
        },
    }
    path = root / "registry.json"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def setup(root: Path) -> tuple[Path, Path]:
    reg = registry(root)
    baseline = root / "population/data/baseline.zip"
    write_zip(baseline, [hand("1001", hour=8)])
    return reg, baseline


def test_same_stake_regular_hand_is_excluded_from_zoom_increment() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        reg, baseline = setup(root)
        candidate = root / "candidate.zip"
        write_zip(candidate, [
            hand("1002", zoom=True, hour=9),
            hand("1003", zoom=False, hour=10),
        ])
        manifest_path = root / "increment/manifest.json"
        selected_zip = root / "increment/selected.zip"
        manifest, selected = build_population_increment(
            root=root,
            population_id=POP,
            known_archives=[baseline],
            candidate=candidate,
            registry_path=reg,
            manifest_path=manifest_path,
            output_zip=selected_zip,
        )
        assert [row.hand_id for row in selected] == ["1002"]
        assert manifest["selected_unique_hands"] == 1
        admission = manifest["population_admission"]
        assert admission["admissible_unique_hands"] == 1
        assert admission["excluded_unique_hands"] == 1
        assert admission["excluded_reason_counts"] == {"format:REGULAR!=ZOOM": 1}
        assert admission["ambiguous_unique_hands"] == 0
        persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert persisted["population_id"] == POP
        records, _ = read_archive(selected_zip)
        assert [row.hand_id for row in records] == ["1002"]


def test_known_admissible_hand_is_deduplicated_after_population_filter() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        reg, baseline = setup(root)
        candidate = root / "candidate.zip"
        write_zip(candidate, [hand("1001", hour=8), hand("1004", hour=11)])
        manifest, selected = build_population_increment(
            root=root,
            population_id=POP,
            known_archives=[baseline],
            candidate=candidate,
            registry_path=reg,
        )
        assert [row.hand_id for row in selected] == ["1004"]
        assert manifest["candidate_overlap_known_hands"] == 1
        assert manifest["selected_unique_hands"] == 1


def test_ambiguous_target_identity_blocks_entire_snapshot() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        reg, baseline = setup(root)
        candidate = root / "candidate.zip"
        write_zip(candidate, [
            hand("1002", hour=9),
            hand("1005", max_seats=None, hour=10),
        ])
        output = root / "increment/selected.zip"
        try:
            build_population_increment(
                root=root,
                population_id=POP,
                known_archives=[baseline],
                candidate=candidate,
                registry_path=reg,
                output_zip=output,
            )
        except ValueError as exc:
            assert "ambiguous population identity" in str(exc)
        else:
            raise AssertionError("ambiguous candidate must fail closed")
        assert not output.exists()


def test_wrong_stake_and_regular_hands_can_yield_traceable_zero_increment() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        reg, baseline = setup(root)
        candidate = root / "candidate.zip"
        write_zip(candidate, [
            hand("1006", zoom=True, stake="250/500", hour=9),
            hand("1007", zoom=False, stake="100/200", hour=10),
        ])
        manifest, selected = build_population_increment(
            root=root,
            population_id=POP,
            known_archives=[baseline],
            candidate=candidate,
            registry_path=reg,
        )
        assert selected == []
        assert manifest["selected_unique_hands"] == 0
        assert manifest["population_admission"]["admissible_unique_hands"] == 0
        assert manifest["population_admission"]["excluded_unique_hands"] == 2
        reasons = manifest["population_admission"]["excluded_reason_counts"]
        assert reasons["format:REGULAR!=ZOOM"] == 1
        assert reasons["stake:250/500!=100/200"] == 1


def test_unknown_money_is_ambiguous_and_never_admitted() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        reg, baseline = setup(root)
        candidate = root / "candidate.zip"
        write_zip(candidate, [hand("1008", play=False)])
        try:
            build_population_increment(
                root=root,
                population_id=POP,
                known_archives=[baseline],
                candidate=candidate,
                registry_path=reg,
            )
        except ValueError as exc:
            assert "ambiguous population identity" in str(exc)
            assert "money:UNKNOWN" in str(exc)
        else:
            raise AssertionError("unknown money identity must fail closed")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"population increment admission tests: {len(tests)} passed")
