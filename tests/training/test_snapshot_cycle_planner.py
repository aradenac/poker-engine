#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.plan_snapshot_cycle import contract_for, discover, write_immutable  # noqa: E402


def write(path: Path, data: bytes | str = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)


def fixture(root: Path) -> None:
    baseline = "training/datasets/NLHE_100-200/source/baseline.zip"
    registry = {
        "schema_version": 2,
        "active_dataset": "NLHE_100-200",
        "datasets": {"NLHE_100-200": {"baseline_archive": baseline}},
        "promoted_independent_model": {"model_dir": "training/runs/model-b/model"},
    }
    write(root / "training/registry.json", json.dumps(registry))
    write(root / baseline, b"baseline")
    write(root / "training/runs/model-b/model/model.json", "{}")
    write(root / "user/releases/v83.html", "v83")
    write(root / "site/index.html", "site")
    write(root / "user/artifacts/readme.txt", "artifact")
    write(root / "training/datasets/NLHE_100-200/snapshots/old/source/old.zip", b"old")
    write(root / "training/datasets/NLHE_100-200/increments/old/manifest.json", "{}")
    write(root / "training/datasets/NLHE_100-200/snapshots/new/source/new.zip", b"new snapshot")


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
        expected = hashlib.sha256(b"new snapshot").hexdigest()
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


def test_no_pending_snapshot_is_traceable_noop() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); fixture(root)
        write(root / "training/datasets/NLHE_100-200/increments/new/manifest.json", "{}")
        plan = discover(root)
        assert plan == {"status": "NO_PENDING_SNAPSHOT", "dataset": "NLHE_100-200", "stake": "100/200"}


def test_multiple_pending_snapshots_are_rejected_as_ambiguous() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); fixture(root)
        write(root / "training/datasets/NLHE_100-200/snapshots/other/source/other.zip", b"other")
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
