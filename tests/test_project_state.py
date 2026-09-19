#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.validate_project_state import (  # noqa: E402
    STATES,
    compare_status_file,
    exit_code,
    load_json,
    render_status,
    validate_manifest,
)


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
                "summary": "Fixture capability.",
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


def _valid_fixture(root: Path) -> dict:
    _write(root, "docs/contract.md", "contract")
    _write(root, "runtime.js", "still not integrated")
    return _fixture_manifest()


def test_repository_manifest_is_self_consistent() -> None:
    report = validate_manifest(load_json(ROOT / ".project" / "capabilities.json"), ROOT)
    assert report["status"] == "WARN", report
    assert report["errors"] == [], report
    by_id = {row["id"]: row for row in report["capabilities"]}
    assert by_id["target_zoom_population_data"]["state"] == "CONTRACT_READY"
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
        manifest = _valid_fixture(root)
        _write(root, "state.json", json.dumps({"nested": {"value": "READY"}}))
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
        manifest = _valid_fixture(root)
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
        manifest = _valid_fixture(root)
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
        manifest = _valid_fixture(root)
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


def test_status_render_is_deterministic_and_lists_every_delivery_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manifest = _valid_fixture(root)
        report = validate_manifest(manifest, root)
        first = render_status(manifest, report)
        second = render_status(manifest, report)
        assert first == second
        assert "Last update:" not in first
        for state in STATES:
            assert f"`{state}`" in first


def test_status_render_keeps_historical_contradiction_visible() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manifest = _valid_fixture(root)
        manifest["capabilities"][0]["administrative"] = {
            "issue": 999,
            "status": "CLOSED",
            "claimed_state": "PRODUCT_INTEGRATED",
            "successor_issue": 1000,
            "known_mismatch_reason": "runtime evidence is authoritative",
        }
        report = validate_manifest(manifest, root)
        rendered = render_status(manifest, report)
        assert "Historical contradictions" in rendered
        assert "issue #999 is CLOSED" in rendered
        assert "successor issue #1000" in rendered


def test_status_check_accepts_exact_and_rejects_stale_content() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manifest = _valid_fixture(root)
        report = validate_manifest(manifest, root)
        rendered = render_status(manifest, report)
        status_path = root / "STATUS.md"
        status_path.write_text(rendered, encoding="utf-8")
        current, detail = compare_status_file(status_path, rendered)
        assert current is True
        assert detail == ""
        status_path.write_text(rendered + "\nmanual stale line\n", encoding="utf-8")
        current, detail = compare_status_file(status_path, rendered)
        assert current is False
        assert "manual stale line" in detail


def test_repository_status_is_exact_generated_view() -> None:
    manifest = load_json(ROOT / ".project" / "capabilities.json")
    report = validate_manifest(manifest, ROOT)
    rendered = render_status(manifest, report)
    current, detail = compare_status_file(ROOT / ".project" / "STATUS.md", rendered)
    assert current is True, detail


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
