#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import fingerprint, split_for  # noqa: E402
from tools.datasets.materialize_certified_population import materialize  # noqa: E402

POP = "fixture_zoom_100_200"


def hand(hand_id: str, *, hour: int) -> str:
    return (
        f"PokerStars Zoom Hand #{hand_id}: Hold'em No Limit (100/200) - 2026/09/01 {hour:02d}:00:00 ET\n"
        "Table 'Fixture' 6-max Seat #1 is the button\n"
        "Seat 1: Hero (10000 in chips)\n"
        "Seat 2: Villain (10000 in chips)\n"
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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root: Path, *, ambiguous: int = 0) -> tuple[Path, Path]:
    source = root / "sources/source.zip"
    write_zip(source, [hand("1001", hour=1), hand("1002", hour=2), hand("1003", hour=3)])
    admissible_ids = ["1001", "1002"]
    split_counts = Counter(split_for(value) for value in admissible_ids)
    cert = {
        "schema": "poker-population-certification/v1",
        "target": {
            "platform": "POKERSTARS",
            "variant": "NLHE",
            "game_kind": "CASH",
            "stake": "100/200",
            "format": "ZOOM",
            "money": "PLAY",
            "max_seats": 6,
        },
        "archives": [{"path": "sources/source.zip", "sha256": sha256(source)}],
        "status": {
            "ADMISSIBLE": {
                "unique_hands": 2,
                "fingerprint_sha256": fingerprint(admissible_ids),
                "split_counts": {
                    "TRAIN": split_counts.get("TRAIN", 0),
                    "VALIDATION": split_counts.get("VALIDATION", 0),
                    "TEST": split_counts.get("TEST", 0),
                },
            },
            "EXCLUDED": {"unique_hands": 1, "hand_ids": ["1003"]},
            "AMBIGUOUS": {"unique_hands": ambiguous, "hand_ids": ["9999"] if ambiguous else []},
        },
    }
    cert_path = root / "certification.json"
    cert_path.write_text(json.dumps(cert, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    registry = {
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
                    "root": "pop/data",
                    "source_certification": "certification.json",
                    "source_hand_ids_sha256": fingerprint(admissible_ids),
                    "source_unique_hands": 2,
                    "snapshots_root": "pop/data/snapshots",
                    "increments_root": "pop/data/increments",
                },
                "artifacts": {
                    "model_a_preflop": None,
                    "model_a_postflop": None,
                    "model_b": None,
                    "hero_strategy": None,
                    "engine": None,
                    "pack": None,
                },
                "storage": {"runs_root": "pop/runs", "cache_namespace": POP},
                "compatibility": {"legacy_unscoped_artifacts_allowed": False},
                "promotion_history": [],
            }
        },
    }
    registry_path = root / "registry.json"
    registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return registry_path, source


def test_materializes_exact_admissible_set_and_binds_registry() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        registry_path, _ = fixture(root)
        result = materialize(
            root=root,
            registry_path=registry_path,
            population_id=POP,
            bind_registry=True,
        )
        assert result["status"] == "PASS"
        assert result["baseline"]["unique_hands"] == 2
        assert result["baseline"]["hand_ids_fingerprint_sha256"] == fingerprint(["1001", "1002"])
        baseline = root / "pop/data/baseline/certified_population.zip"
        manifest = json.loads((root / "pop/data/baseline/manifest.json").read_text())
        assert baseline.is_file()
        assert manifest["baseline"]["sha256"] == sha256(baseline)
        assert manifest["sources"]["archives"][0]["path"] == "sources/source.zip"
        registry = json.loads(registry_path.read_text())
        data = registry["populations"][POP]["data"]
        assert data["baseline_archive"] == "pop/data/baseline/certified_population.zip"
        assert data["baseline_manifest"] == "pop/data/baseline/manifest.json"
        assert data["baseline_archive_sha256"] == sha256(baseline)
        assert data["baseline_hand_ids_sha256"] == fingerprint(["1001", "1002"])


def test_rebuild_is_byte_deterministic_and_idempotent() -> None:
    outputs = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            registry_path, _ = fixture(root)
            first = materialize(root=root, registry_path=registry_path, population_id=POP, bind_registry=True)
            second = materialize(root=root, registry_path=registry_path, population_id=POP, bind_registry=True)
            assert second["writes"] == {
                "baseline_zip": "UNCHANGED",
                "manifest": "UNCHANGED",
                "registry": "UNCHANGED",
            }
            outputs.append((
                (root / "pop/data/baseline/certified_population.zip").read_bytes(),
                (root / "pop/data/baseline/manifest.json").read_bytes(),
            ))
            assert first["baseline"]["sha256"] == second["baseline"]["sha256"]
    assert outputs[0] == outputs[1]


def test_source_archive_hash_drift_fails_before_materialization() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        registry_path, source = fixture(root)
        source.write_bytes(source.read_bytes() + b"tamper")
        try:
            materialize(root=root, registry_path=registry_path, population_id=POP)
        except ValueError as exc:
            assert "source archive drifted" in str(exc)
        else:
            raise AssertionError("source archive drift must fail closed")
        assert not (root / "pop/data/baseline/certified_population.zip").exists()


def test_ambiguous_certification_cannot_be_materialized() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        registry_path, _ = fixture(root, ambiguous=1)
        try:
            materialize(root=root, registry_path=registry_path, population_id=POP)
        except ValueError as exc:
            assert "ambiguous" in str(exc).lower()
        else:
            raise AssertionError("ambiguous certification must fail closed")


def test_existing_different_baseline_is_never_overwritten() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        registry_path, _ = fixture(root)
        baseline = root / "pop/data/baseline/certified_population.zip"
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_bytes(b"historical baseline")
        try:
            materialize(root=root, registry_path=registry_path, population_id=POP)
        except ValueError as exc:
            assert "refusing to replace" in str(exc)
        else:
            raise AssertionError("existing baseline must be immutable")
        assert baseline.read_bytes() == b"historical baseline"


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"certified population materialization tests: {len(tests)} passed")


if __name__ == "__main__":
    main()
