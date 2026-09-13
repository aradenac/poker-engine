#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.analyze_unseen_preflop_contexts import audit  # noqa: E402


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_audit_separates_seen_and_unseen_support() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        baseline = root / "baseline.json"
        overlay = root / "overlay.json"
        write_json(
            baseline,
            {
                "model_version": "v5",
                "nodes": [
                    {"canonical_key": "seen-a"},
                    {"canonical_key": "seen-b"},
                ],
            },
        )
        write_json(
            overlay,
            {
                "summary": {"train_population_rows": 30},
                "preflop_nodes": [
                    {"canonical_key": "seen-a", "n_delta": 10, "actions": {"call": 10}, "context": {}},
                    {
                        "canonical_key": "new-1",
                        "n_delta": 20,
                        "actions": {"raise": 12, "call": 8},
                        "context": {"table_size": 6, "actor_position": "CO", "family": "open", "raise_level": 0, "history": []},
                    },
                ],
            },
        )
        report = audit(baseline=baseline, overlay=overlay)
        assert report["coverage"]["seen_rows"] == 10
        assert report["coverage"]["unseen_rows"] == 20
        assert report["coverage"]["unseen_exact_nodes"] == 1
        assert report["support"]["nodes_ge_20"] == 1
        assert report["weighted_distribution"]["actor_position"] == {"CO": 20}
        assert report["weighted_distribution"]["action"] == {"raise": 12, "call": 8}
        assert report["interpretation_contract"]["diagnostic_only"] is True
        assert report["interpretation_contract"]["test_used"] is False


def test_sparse_support_buckets_are_counted_by_rows_and_nodes() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        baseline = root / "baseline.json"
        overlay = root / "overlay.json"
        write_json(baseline, {"nodes": []})
        write_json(
            overlay,
            {
                "summary": {"train_population_rows": 8},
                "preflop_nodes": [
                    {"canonical_key": "a", "n_delta": 1, "actions": {"fold": 1}, "context": {}},
                    {"canonical_key": "b", "n_delta": 2, "actions": {"call": 2}, "context": {}},
                    {"canonical_key": "c", "n_delta": 5, "actions": {"raise": 5}, "context": {}},
                ],
            },
        )
        report = audit(baseline=baseline, overlay=overlay)
        assert report["support"]["node_buckets"] == {"1": 1, "2_4": 1, "5_9": 1}
        assert report["support"]["row_buckets"] == {"1": 1, "2_4": 2, "5_9": 5}
        assert report["support"]["singleton_rows"] == 1
        assert report["support"]["sparse_rows_n_le_4"] == 3


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"unseen preflop audit tests: {len(tests)} passed")
