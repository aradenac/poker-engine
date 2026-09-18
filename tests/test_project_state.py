#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.validate_project_state import STATES, exit_code, load_json, validate_manifest  # noqa: E402


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _fixture_manifest() -> dict:
    return {
        "schema": "poker-project-capabilities/v1",
        "state_order": STATES,
        "capabilities": [
            {
                "id": "feature",
                "state": "CONTRACT_READY",
                "evidence": [
                    {
                        "id": "contract",
                        "proves": "CONTRACT_READY",
                        "kind": "path_exists",
                        "path": "docs/contract.md",
                        "type": "file",
                    }
                ],
                "limits": [
                    {
                        "id": "runtime-boundary",
                        "blocks_state": "PRODUCT_INTEGRATED",
                        "check": {
                            "kind": "file_contains",
                            "path": "runtime.js",
                            "text": "not integrated",
                        },
                    }
                ],
            }
        ],
    }


def test_repository_manifest_is_self_consistent() -> None:
    report = validate_manifest(load_json(ROOT / ".project" / "capabilities.json"), ROOT)
    assert report["status"] == "WARN", report
    assert report["errors"] == [], report
    by_id = {row["id"]: row for row in report["capabilities"]}
    assert by_id["trainer_preflop_guidance"]["state"] == "CONTRACT_READY"
    assert by_id["legacy_mixed_population_engine_v83"]["state"] == "PROMOTED"
    assert by_id["assembled_static_application"]["state"] == "PROMOTED"
    assert report["warnings"] and "#109" in report["warnings"][0]


def test_missing_versioned_evidence_fails() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manifest = _fixture_manifest()
        _write(root, "runtime.js", "not integrated")
        report = validate_manifest(manifest, root)
        assert report["status"] == "FAIL", report
        assert any("missing path" in error for error in report["errors"])


def test_json_pointer_and_file_contains_checks_pass() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "docs/contract.md", "contract")
        _write(root, "runtime.js", "still not integrated")
        _write(root, "state.json", json.dumps({"nested": {"value": "READY"}}))
        manifest = _fixture_manifest()
        manifest["capabilities"][0]["evidence"].append(
            {
                "id": "json",
                "proves": "CONTRACT_READY",
                "kind": "json_equals",
                "path": "state.json",
                "pointer": "/nested/value",
                "equals": "READY",
            }
        )
        report = validate_manifest(manifest, root)
        assert report["status"] == "PASS", report


def test_unacknowledged_closed_issue_gap_is_a_failure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "docs/contract.md", "contract")
        _write(root, "runtime.js", "not integrated")
        manifest = _fixture_manifest()
        manifest["capabilities"][0]["administrative"] = {
            "issue": 999,
            "status": "CLOSED",
            "claimed_state": "PRODUCT_INTEGRATED",
        }
        report = validate_manifest(manifest, root)
        assert report["status"] == "FAIL", report
        assert any("not traceably acknowledged" in error for error in report["errors"])


def test_acknowledged_gap_warns_and_can_be_strict() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "docs/contract.md", "contract")
        _write(root, "runtime.js", "not integrated")
        manifest = _fixture_manifest()
        manifest["capabilities"][0]["administrative"] = {
            "issue": 999,
            "status": "CLOSED",
            "claimed_state": "PRODUCT_INTEGRATED",
            "successor_issue": 1000,
            "known_mismatch_reason": "runtime evidence is intentionally authoritative",
        }
        report = validate_manifest(manifest, root)
        assert report["status"] == "WARN", report
        assert exit_code(report) == 0
        assert exit_code(report, strict_warnings=True) == 2


def test_evidence_cannot_claim_a_state_above_declared_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "docs/contract.md", "contract")
        _write(root, "runtime.js", "not integrated")
        manifest = _fixture_manifest()
        manifest["capabilities"][0]["evidence"].append(
            {
                "id": "too-high",
                "proves": "LIVE",
                "kind": "path_exists",
                "path": "docs/contract.md",
            }
        )
        report = validate_manifest(manifest, root)
        assert report["status"] == "FAIL", report
        assert any("above declared state" in error for error in report["errors"])


def main() -> None:
    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"project state tests: {len(tests)} passed")


if __name__ == "__main__":
    main()
