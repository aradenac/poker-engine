#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.plan_snapshot_cycle import contract_for, discover, write_immutable  # noqa: E402
from tools.training.run_continuous_cycle import execute  # noqa: E402

POP_A = "fixture_nlhe_100-200_zoom_play_6max_v1"
POP_B = "fixture_nlhe_250-500_zoom_play_6max_v1"


def write(path: Path, data: bytes | str = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)


def en_hand(hand_id: str, date: str = "2026/09/14 12:00:00", stake: str = "100/200") -> str:
    return (
        f"PokerStars Zoom Hand #{hand_id}: Hold'em No Limit ({stake}) - {date} CET\n"
        "Table 'CycleFixture' 6-max Seat #1 is the button\n"
        "Seat 1: Hero (20000 in chips)\n"
        "*** SUMMARY ***\n"
    )


def make_zip(path: Path, files: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text.encode("utf-8"))


def population_spec(*, dataset: str, stake: str, runs_root: str, model_suffix: str) -> dict:
    root = f"training/datasets/{dataset}"
    return {
        "status": "PROMOTED_FIXTURE",
        "identity": {
            "platform": "PokerStars",
            "variant": "NLHE",
            "game_kind": "cash",
            "stake": stake,
            "money": "play",
            "currency": "PLAY_CHIPS",
            "format": "ZOOM",
            "max_seats": 6,
            "rake": {"policy": "FIXTURE"},
        },
        "data": {
            "dataset_id": dataset,
            "root": root,
            "baseline_archive": f"{root}/source/baseline.zip",
            "snapshots_root": f"{root}/snapshots",
            "increments_root": f"{root}/increments",
        },
        "artifacts": {
            "model_a_preflop": f"training/models/{model_suffix}-pre.json",
            "model_a_postflop": f"training/models/{model_suffix}-post.json",
            "model_b": f"training/runs/{model_suffix}-b/model",
            "hero_strategy": f"user/releases/{model_suffix}.html",
            "engine": "fixture-engine",
            "pack": f"user/artifacts/{model_suffix}/bundle.json",
        },
        "storage": {
            "runs_root": runs_root,
            "cache_namespace": f"cache-{model_suffix}",
        },
        "compatibility": {"legacy_unscoped_artifacts_allowed": True},
        "promotion_history": [],
    }


def write_population_registry(root: Path, *, include_b: bool = False) -> None:
    populations = {
        POP_A: population_spec(
            dataset="NLHE_100-200",
            stake="100/200",
            runs_root=f"training/populations/{POP_A}/runs",
            model_suffix="a",
        )
    }
    if include_b:
        populations[POP_B] = population_spec(
            dataset="NLHE_250-500",
            stake="250/500",
            runs_root=f"training/populations/{POP_B}/runs",
            model_suffix="b",
        )
    registry = {
        "schema": "poker-population-registry/v1",
        "default_population": POP_A,
        "legacy_registry": {"path": "training/registry.json"},
        "populations": populations,
    }
    write(root / "training/populations/registry.json", json.dumps(registry, indent=2))


def install_artifacts(root: Path, suffix: str) -> None:
    write(root / f"training/models/{suffix}-pre.json", "{}")
    write(root / f"training/models/{suffix}-post.json", "{}")
    write(root / f"training/runs/{suffix}-b/model/model.json", "{}")
    write(root / f"user/releases/{suffix}.html", suffix)
    write(root / f"user/artifacts/{suffix}/bundle.json", "{}")


def fixture(root: Path, *, new_unique_hand: bool = True, include_b: bool = False) -> None:
    # Closed-cycle legacy registry remains present/protected but is deliberately not
    # used as an implicit population selector by the new planner.
    write(root / "training/registry.json", json.dumps({"schema_version": 2, "active_dataset": "legacy"}))
    write_population_registry(root, include_b=include_b)
    install_artifacts(root, "a")
    write(root / "site/index.html", "site")

    make_zip(
        root / "training/datasets/NLHE_100-200/source/baseline.zip",
        {"baseline.txt": en_hand("1001", date="2026/09/12 10:00:00")},
    )
    make_zip(
        root / "training/datasets/NLHE_100-200/snapshots/old/source/old.zip",
        {"old.txt": en_hand("1002", date="2026/09/13 10:00:00")},
    )
    write(root / "training/datasets/NLHE_100-200/increments/old/manifest.json", "{}")
    new_payload = en_hand("1002", date="2026/09/13 10:00:00")
    if new_unique_hand:
        new_payload += en_hand("1003", date="2026/09/14 12:00:00")
    else:
        new_payload += en_hand("1001", date="2026/09/12 10:00:00")
    make_zip(
        root / "training/datasets/NLHE_100-200/snapshots/new/source/new.zip",
        {"new.txt": new_payload},
    )

    if include_b:
        install_artifacts(root, "b")
        make_zip(
            root / "training/datasets/NLHE_250-500/source/baseline.zip",
            {"baseline.txt": en_hand("5001", date="2026/09/12 10:00:00", stake="250/500")},
        )
        make_zip(
            root / "training/datasets/NLHE_250-500/snapshots/new/source/new.zip",
            {"new.txt": en_hand("5002", stake="250/500")},
        )


def install_repo_tools(root: Path) -> None:
    (root / "tools").symlink_to(ROOT / "tools", target_is_directory=True)


def write_contract(root: Path, contract: dict) -> Path:
    path = root / "training/automation/generated/test-cycle.json"
    write(path, json.dumps(contract, indent=2, sort_keys=True) + "\n")
    return path


def tree_fingerprint(path: Path) -> str:
    rows = []
    for child in sorted(p for p in path.rglob("*") if p.is_file()):
        rows.append((child.relative_to(path).as_posix(), hashlib.sha256(child.read_bytes()).hexdigest()))
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def test_discovers_one_pending_snapshot_with_explicit_population() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); fixture(root)
        plan = discover(root, population_id=POP_A)
        assert plan["status"] == "PLANNED"
        assert plan["population_id"] == POP_A
        assert plan["snapshot_id"] == "new"
        assert plan["stake"] == "100/200"
        assert plan["cache_namespace"] == "cache-a"
        assert plan["runs_root"] == f"training/populations/{POP_A}/runs"
        assert plan["known_archives"] == [
            "training/datasets/NLHE_100-200/source/baseline.zip",
            "training/datasets/NLHE_100-200/snapshots/old/source/old.zip",
        ]
        archive = root / "training/datasets/NLHE_100-200/snapshots/new/source/new.zip"
        expected = hashlib.sha256(archive.read_bytes()).hexdigest()
        assert plan["candidate_sha256"] == expected
        assert plan["run_id"] == f"new_continuous_{expected[:12]}"


def test_contract_is_population_scoped_validation_only_and_protected() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); fixture(root)
        plan = discover(root, population_id=POP_A)
        contract = contract_for(root, plan)
        assert contract["population_id"] == POP_A
        assert contract["dataset_id"] == "NLHE_100-200"
        assert contract["cache_namespace"] == "cache-a"
        assert contract["promotion_mode"] == "disabled"
        assert contract["cycle"] == plan["run_id"]
        assert "training/populations/registry.json" in contract["protected_production_paths"]
        assert "training/registry.json" in contract["protected_production_paths"]
        assert "training/models/a-pre.json" in contract["protected_production_paths"]
        assert "user/releases/a.html" in contract["protected_production_paths"]
        assert "site" in contract["protected_production_paths"]
        ids = [x["id"] for x in contract["stages"]]
        assert ids == [
            "audit-snapshot", "build-deterministic-increment", "classify-increment",
            "normalize-decisions", "build-train-overlay", "write-increment-readiness-gate",
        ]


def test_generated_contract_executes_new_increment_without_production_mutation() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); fixture(root, new_unique_hand=True); install_repo_tools(root)
        plan = discover(root, population_id=POP_A)
        contract = contract_for(root, plan)
        config = write_contract(root, contract)
        report_path = root / "execution.json"
        code, report = execute(root=root, config_path=config, report_path=report_path)
        assert code == 0, report
        assert report["status"] == "PASS", report
        assert report["promotion_applied"] is False
        assert report["production_before"] == report["production_after"]
        assert report["production_changed_paths_detected"] == []
        assert report["gate"]["status"] == "BLOCKED"
        increment = root / "training/datasets/NLHE_100-200/increments/new/manifest.json"
        manifest = json.loads(increment.read_text(encoding="utf-8"))
        assert manifest["selected_unique_hands"] == 1, manifest
        run = root / plan["runs_root"] / plan["run_id"]
        assert (run / "data/decisions.jsonl").is_file()
        assert (run / "artifacts/population_increment_overlay.json").is_file()


def test_cycle_on_population_a_does_not_touch_population_b() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); fixture(root, include_b=True); install_repo_tools(root)
        b_root = root / "training/datasets/NLHE_250-500"
        b_before = tree_fingerprint(b_root)
        b_plan_before = discover(root, population_id=POP_B)
        assert b_plan_before["stake"] == "250/500"

        plan = discover(root, population_id=POP_A)
        config = write_contract(root, contract_for(root, plan))
        code, report = execute(root=root, config_path=config)
        assert code == 0, report

        assert tree_fingerprint(b_root) == b_before
        b_plan_after = discover(root, population_id=POP_B)
        assert b_plan_after == b_plan_before
        assert not (root / f"training/populations/{POP_B}/runs").exists()


def test_zero_new_hands_executes_as_traceable_noop() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); fixture(root, new_unique_hand=False); install_repo_tools(root)
        plan = discover(root, population_id=POP_A)
        config = write_contract(root, contract_for(root, plan))
        code, report = execute(root=root, config_path=config)
        assert code == 0, report
        assert report["status"] == "PASS"
        assert report["promotion_applied"] is False
        assert report["gate"]["status"] == "PASS"
        run = root / plan["runs_root"] / plan["run_id"]
        status = json.loads((run / "data/increment_status.json").read_text(encoding="utf-8"))
        assert status["selected_unique_hands"] == 0
        assert status["outcome"] == "NO_OP_NO_NEW_HANDS"
        assert not (run / "data/decisions.jsonl").exists()


def test_no_pending_snapshot_is_population_scoped_noop() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); fixture(root)
        write(root / "training/datasets/NLHE_100-200/increments/new/manifest.json", "{}")
        plan = discover(root, population_id=POP_A)
        assert plan == {
            "status": "NO_PENDING_SNAPSHOT",
            "population_id": POP_A,
            "dataset": "NLHE_100-200",
            "stake": "100/200",
        }


def test_multiple_pending_snapshots_are_rejected_per_population() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); fixture(root)
        make_zip(
            root / "training/datasets/NLHE_100-200/snapshots/other/source/other.zip",
            {"other.txt": en_hand("1004")},
        )
        try:
            discover(root, population_id=POP_A)
        except RuntimeError as exc:
            assert "multiple unprocessed snapshots" in str(exc)
            assert POP_A in str(exc)
        else:
            raise AssertionError("ambiguous pending snapshots must fail")


def test_processed_explicit_snapshot_is_noop() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); fixture(root)
        plan = discover(root, population_id=POP_A, snapshot_id="old")
        assert plan["status"] == "NO_OP_ALREADY_PROCESSED"
        assert plan["population_id"] == POP_A
        assert plan["snapshot_id"] == "old"


def test_immutable_plan_cannot_be_replaced() -> None:
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "plan.json"
        assert write_immutable(path, "one\n") == "CREATED"
        assert write_immutable(path, "one\n") == "UNCHANGED"
        try:
            write_immutable(path, "two\n")
        except RuntimeError as exc:
            assert "refusing to replace" in str(exc)
        else:
            raise AssertionError("immutable plan replacement must fail")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"snapshot cycle planner tests: {len(tests)} passed")
