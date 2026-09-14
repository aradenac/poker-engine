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


def write(path: Path, data: bytes | str = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)


def en_hand(hand_id: str, date: str = "2026/09/14 12:00:00", stake: str = "100/200") -> str:
    return (
        f"PokerStars Hand #{hand_id}: Hold'em No Limit ({stake}) - {date} CET\n"
        "Table 'CycleFixture' 6-max Seat #1 is the button\n"
        "Seat 1: Hero (20000 in chips)\n"
        "*** SUMMARY ***\n"
    )


def make_zip(path: Path, files: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text.encode("utf-8"))


def fixture(root: Path, *, new_unique_hand: bool = True) -> None:
    baseline = "training/datasets/NLHE_100-200/source/baseline.zip"
    registry = {
        "schema_version": 2,
        "active_dataset": "NLHE_100-200",
        "datasets": {"NLHE_100-200": {"baseline_archive": baseline}},
        "promoted_independent_model": {"model_dir": "training/runs/model-b/model"},
    }
    write(root / "training/registry.json", json.dumps(registry))
    make_zip(root / baseline, {"baseline.txt": en_hand("1001", date="2026/09/12 10:00:00")})
    write(root / "training/models/model.json", "{}")
    write(root / "training/runs/model-b/model/model.json", "{}")
    write(root / "user/releases/v83.html", "v83")
    write(root / "site/index.html", "site")
    write(root / "user/artifacts/readme.txt", "artifact")
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


def install_repo_tools(root: Path) -> None:
    (root / "tools").symlink_to(ROOT / "tools", target_is_directory=True)


def write_contract(root: Path, contract: dict) -> Path:
    path = root / "training/automation/generated/test-cycle.json"
    write(path, json.dumps(contract, indent=2, sort_keys=True) + "\n")
    return path


def test_discovers_one_pending_snapshot_without_hardcoded_date() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); fixture(root)
        plan = discover(root)
        assert plan["status"] == "PLANNED"
        assert plan["snapshot_id"] == "new"
        assert plan["stake"] == "100/200"
        assert plan["known_archives"] == [
            "training/datasets/NLHE_100-200/source/baseline.zip",
            "training/datasets/NLHE_100-200/snapshots/old/source/old.zip",
        ]
        archive = root / "training/datasets/NLHE_100-200/snapshots/new/source/new.zip"
        expected = hashlib.sha256(archive.read_bytes()).hexdigest()
        assert plan["candidate_sha256"] == expected
        assert plan["run_id"] == f"new_continuous_{expected[:12]}"


def test_contract_is_validation_only_and_production_protected() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); fixture(root)
        plan = discover(root)
        contract = contract_for(root, plan)
        assert contract["promotion_mode"] == "disabled"
        assert contract["cycle"] == plan["run_id"]
        assert "training/registry.json" in contract["protected_production_paths"]
        assert "training/models" in contract["protected_production_paths"]
        assert "user/releases" in contract["protected_production_paths"]
        assert "site" in contract["protected_production_paths"]
        ids = [x["id"] for x in contract["stages"]]
        assert ids == [
            "audit-snapshot", "build-deterministic-increment", "classify-increment",
            "normalize-decisions", "build-train-overlay", "write-increment-readiness-gate",
        ]
        conditional = {x["id"] for x in contract["stages"] if "when" in x}
        assert conditional == {"normalize-decisions", "build-train-overlay"}


def test_generated_contract_executes_new_increment_without_production_mutation() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); fixture(root, new_unique_hand=True); install_repo_tools(root)
        plan = discover(root)
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
        assert report["gate"]["promotion_ready"] is False
        increment = root / "training/datasets/NLHE_100-200/increments/new/manifest.json"
        manifest = json.loads(increment.read_text(encoding="utf-8"))
        assert manifest["selected_unique_hands"] == 1, manifest
        run = root / "training/runs" / plan["run_id"]
        assert (run / "data/decisions.jsonl").is_file()
        assert (run / "artifacts/population_increment_overlay.json").is_file()
        gate = json.loads((run / "gate.json").read_text(encoding="utf-8"))
        assert gate["outcome"] == "CANDIDATE_PIPELINE_REQUIRED"


def test_zero_new_hands_executes_as_traceable_noop() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); fixture(root, new_unique_hand=False); install_repo_tools(root)
        plan = discover(root)
        contract = contract_for(root, plan)
        config = write_contract(root, contract)
        code, report = execute(root=root, config_path=config)
        assert code == 0, report
        assert report["status"] == "PASS"
        assert report["promotion_applied"] is False
        assert report["gate"]["status"] == "PASS"
        assert report["gate"]["promotion_ready"] is True
        run = root / "training/runs" / plan["run_id"]
        status = json.loads((run / "data/increment_status.json").read_text(encoding="utf-8"))
        gate = json.loads((run / "gate.json").read_text(encoding="utf-8"))
        assert status["selected_unique_hands"] == 0
        assert status["outcome"] == "NO_OP_NO_NEW_HANDS"
        assert gate["outcome"] == "NO_OP_NO_NEW_HANDS"
        assert not (run / "data/decisions.jsonl").exists()
        assert not (run / "artifacts/population_increment_overlay.json").exists()


def test_no_pending_snapshot_is_traceable_noop() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); fixture(root)
        write(root / "training/datasets/NLHE_100-200/increments/new/manifest.json", "{}")
        plan = discover(root)
        assert plan == {"status": "NO_PENDING_SNAPSHOT", "dataset": "NLHE_100-200", "stake": "100/200"}


def test_multiple_pending_snapshots_are_rejected_as_ambiguous() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); fixture(root)
        make_zip(
            root / "training/datasets/NLHE_100-200/snapshots/other/source/other.zip",
            {"other.txt": en_hand("1004")},
        )
        try:
            discover(root)
        except RuntimeError as exc:
            assert "multiple unprocessed snapshots" in str(exc)
        else:
            raise AssertionError("ambiguous pending snapshots must fail")


def test_processed_explicit_snapshot_is_noop() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); fixture(root)
        plan = discover(root, snapshot_id="old")
        assert plan["status"] == "NO_OP_ALREADY_PROCESSED"
        assert plan["snapshot_id"] == "old"


def test_immutable_plan_cannot_be_replaced() -> None:
    with tempfile.TemporaryDirectory() as raw:
        p = Path(raw) / "plan.json"
        assert write_immutable(p, "one\n") == "CREATED"
        assert write_immutable(p, "one\n") == "UNCHANGED"
        try:
            write_immutable(p, "two\n")
        except RuntimeError as exc:
            assert "refusing to replace" in str(exc)
        else:
            raise AssertionError("immutable plan replacement must fail")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"snapshot cycle planner tests: {len(tests)} passed")
