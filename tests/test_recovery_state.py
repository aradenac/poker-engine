#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import tools.build_recovery_state as recovery_module
from tools.build_recovery_state import (
    SCHEMA,
    build_recovery_state,
    build_snapshot,
    compare_snapshot_file,
    fetch_live_github_export,
    normalize_github_export,
    render_human,
    stable_json,
    validate_recovery_state,
)


def _contract() -> dict:
    return {
        "lanes": {
            slot: {"conflict_group": f"GROUP-{slot}", "typical_issues": [100 + index]}
            for index, slot in enumerate("ABCDEFGH", start=1)
        }
    }


def _project_report() -> dict:
    return {
        "schema": "poker-project-state-report/v1",
        "status": "PASS",
        "errors": [],
        "warnings": [],
        "capabilities": [
            {"id": "cap", "state": "CONTRACT_READY", "limits": []},
        ],
    }


def _claims_report() -> dict:
    return {
        "schema": "poker-parallel-claims-report/v1",
        "active_claims": [],
        "violations": [],
        "warnings": [],
        "slots": {
            slot: {
                "status": "IDLE",
                "active_issue": None,
                "active_claim_count": 0,
                "branch": None,
                "pr": None,
                "last_worklog": None,
                "last_release": None,
            }
            for slot in "ABCDEFGH"
        },
    }


def _export() -> dict:
    return {
        "schema": "poker-recovery-github-export/v1",
        "coverage": {
            "comments_complete": True,
            "open_issues_complete": True,
            "open_pulls_complete": True,
            "dispatch_issue": 225,
        },
        "comments": [],
        "issues": [],
        "pulls": [],
        "read_errors": [],
    }


def test_normalization_and_json_are_deterministic() -> None:
    value = _export()
    value["issues"] = [
        {"number": 202, "state": "open", "title": "two", "labels": ["z", "a"]},
        {"number": 101, "state": "open", "title": "one", "labels": []},
    ]
    value["pulls"] = [
        {"number": 9, "state": "open", "title": "p9", "head": "h9", "base": "main"},
        {"number": 3, "state": "open", "title": "p3", "head": "h3", "base": "main"},
    ]
    first = normalize_github_export(value)
    reversed_value = copy.deepcopy(value)
    reversed_value["issues"].reverse()
    reversed_value["pulls"].reverse()
    second = normalize_github_export(reversed_value)
    assert stable_json(first) == stable_json(second)
    assert [row["number"] for row in first["issues"]] == [101, 202]
    assert first["issues"][1]["labels"] == ["a", "z"]


def test_incomplete_comment_coverage_never_infers_free() -> None:
    export = _export()
    export["coverage"]["comments_complete"] = False
    snapshot = build_recovery_state(_contract(), _project_report(), True, _claims_report(), export)
    assert all(snapshot["lanes"][slot]["status"] == "UNKNOWN" for slot in "ABCDEFGH")
    assert any(row["code"] == "COMMENTS_COVERAGE_INCOMPLETE" for row in snapshot["warnings"])


def test_active_claim_recovers_branch_pr_and_continue_action() -> None:
    claims = _claims_report()
    claims["slots"]["G"].update({
        "status": "CLAIMED",
        "active_issue": 107,
        "active_claim_count": 1,
        "branch": "agent-G/issue-107-x",
    })
    export = _export()
    export["issues"] = [{"number": 107, "state": "open", "title": "x", "labels": []}]
    export["pulls"] = [{
        "number": 77, "state": "open", "title": "[G][#107] x",
        "head": "agent-G/issue-107-x", "base": "main",
    }]
    snapshot = build_recovery_state(_contract(), _project_report(), True, claims, export)
    lane = snapshot["lanes"]["G"]
    assert lane["status"] == "CLAIMED"
    assert lane["pr"] == 77
    assert lane["next_safe_action"]["kind"] == "CONTINUE_ACTIVE_CLAIM"


def test_open_pr_without_claim_makes_lane_unknown() -> None:
    export = _export()
    export["pulls"] = [{
        "number": 88, "state": "open", "title": "[C][#103] x",
        "head": "agent-C/issue-103-x", "base": "main",
    }]
    snapshot = build_recovery_state(_contract(), _project_report(), True, _claims_report(), export)
    assert snapshot["lanes"]["C"]["status"] == "UNKNOWN"
    assert any(row["code"] == "OPEN_PR_WITHOUT_ACTIVE_CLAIM" and row.get("slot") == "C" for row in snapshot["warnings"])


def test_next_issue_requires_explicit_recovery_ready() -> None:
    export = _export()
    export["issues"] = [{"number": 101, "state": "open", "title": "A", "labels": []}]
    first = build_recovery_state(_contract(), _project_report(), True, _claims_report(), export)
    assert first["lanes"]["A"]["status"] == "FREE"
    assert first["lanes"]["A"]["next_safe_action"]["kind"] == "UNKNOWN"
    export["issues"][0]["recovery_ready"] = True
    second = build_recovery_state(_contract(), _project_report(), True, _claims_report(), export)
    assert second["lanes"]["A"]["next_safe_action"] == {
        "kind": "CLAIM_OPEN_ISSUE",
        "issue": 101,
        "reason": "open issue is explicitly marked recovery_ready in the supplied persistent export",
    }


def test_only_explicit_blockers_are_reported() -> None:
    export = _export()
    export["issues"] = [
        {"number": 101, "state": "open", "title": "A", "labels": ["blocked"], "blocked_by": [999]},
    ]
    snapshot = build_recovery_state(_contract(), _project_report(), True, _claims_report(), export)
    blockers = snapshot["lanes"]["A"]["explicit_blockers"][0]["blockers"]
    assert {row["kind"] for row in blockers} == {"BLOCKED_LABEL", "ISSUE_DEPENDENCY"}


def test_project_and_coordination_failures_propagate_without_invention() -> None:
    project = _project_report()
    project["status"] = "FAIL"
    project["errors"] = ["proof missing"]
    claims = _claims_report()
    claims["violations"] = [{"code": "DOUBLE_ACTIVE_CLAIM", "slot": "B", "issue": 102, "detail": "duplicate"}]
    snapshot = build_recovery_state(_contract(), project, False, claims, _export())
    assert snapshot["status"] == "FAIL"
    assert snapshot["lanes"]["B"]["status"] == "UNKNOWN"
    codes = {row["code"] for row in snapshot["warnings"]}
    assert "STATUS_DOCUMENT_STALE" in codes
    assert "COORDINATION_DOUBLE_ACTIVE_CLAIM" in codes


def test_validator_rejects_claimed_lane_without_branch() -> None:
    snapshot = build_recovery_state(_contract(), _project_report(), True, _claims_report(), _export())
    snapshot["lanes"]["A"]["status"] = "CLAIMED"
    snapshot["lanes"]["A"]["active_issue"] = 101
    snapshot["lanes"]["A"]["branch"] = None
    assert any("CLAIMED requires" in error for error in validate_recovery_state(snapshot))


def test_snapshot_file_compare_exact_and_stale() -> None:
    content = stable_json(build_recovery_state(_contract(), _project_report(), True, _claims_report(), _export()))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "recovery.json"
        path.write_text(content, encoding="utf-8")
        assert compare_snapshot_file(path, content) == (True, "")
        path.write_text(content + "\n", encoding="utf-8")
        current, diff = compare_snapshot_file(path, content)
        assert current is False
        assert "generated-recovery-state" in diff


def test_human_render_has_all_lanes_in_order_and_no_timestamp() -> None:
    snapshot = build_recovery_state(_contract(), _project_report(), True, _claims_report(), _export())
    rendered = render_human(snapshot)
    positions = [rendered.index(f"- {slot} ") for slot in "ABCDEFGH"]
    assert positions == sorted(positions)
    assert "generated_at" not in rendered
    assert "generated_at" not in stable_json(snapshot)
    assert "generated_timestamp" not in stable_json(snapshot)


def test_schema_marker_and_lane_shape() -> None:
    snapshot = build_recovery_state(_contract(), _project_report(), True, _claims_report(), _export())
    assert snapshot["schema"] == SCHEMA
    assert validate_recovery_state(snapshot) == []


def test_repository_snapshot_uses_real_validators_and_parser() -> None:
    fixture = json.loads((ROOT / "tests/fixtures/project-state/recovery/github-export.json").read_text(encoding="utf-8"))
    snapshot = build_snapshot(ROOT, fixture)
    assert snapshot["project_state"]["validation"]["status"] == "WARN"
    assert snapshot["project_state"]["state_counts"]["LIVE"] == 0
    assert snapshot["project_state"]["state_counts"]["SCIENTIFICALLY_SELECTED"] == 0
    assert snapshot["project_state"]["status_document"]["current"] is True
    assert snapshot["lanes"]["A"]["status"] == "CLAIMED"
    assert snapshot["lanes"]["A"]["pr"] == 901
    assert snapshot["lanes"]["G"]["status"] == "CLAIMED"
    assert snapshot["lanes"]["G"]["pr"] == 902
    assert snapshot["lanes"]["H"]["status"] == "CLAIMED"
    assert snapshot["lanes"]["E"]["status"] == "FREE"
    assert snapshot["lanes"]["E"]["explicit_blockers"]
    assert snapshot["coordination"]["violations"] == []


def test_repository_fixture_is_order_independent() -> None:
    fixture = json.loads((ROOT / "tests/fixtures/project-state/recovery/github-export.json").read_text(encoding="utf-8"))
    first = build_snapshot(ROOT, fixture)
    shuffled = copy.deepcopy(fixture)
    shuffled["comments"].reverse()
    shuffled["issues"].reverse()
    shuffled["pulls"].reverse()
    second = build_snapshot(ROOT, shuffled)
    assert stable_json(first) == stable_json(second)


def test_live_adapter_reuses_read_only_comment_reader_and_marks_coverage() -> None:
    page_calls = []
    comment_calls = []
    original_pages = recovery_module._github_get_pages
    original_comments = recovery_module.fetch_github_comments

    def fake_pages(repo: str, resource: str, params: dict) -> list[dict]:
        page_calls.append((repo, resource, dict(params)))
        if resource == "issues":
            return [{"number": 999, "state": "open", "title": "extra", "labels": []}]
        if resource == "pulls":
            return [{"number": 12, "state": "open", "title": "[A][#101] x", "head": {"ref": "agent-A/issue-101-x"}, "base": {"ref": "main"}}]
        raise AssertionError(resource)

    def fake_comments(repo: str, issue: int) -> list[dict]:
        comment_calls.append((repo, issue))
        return []

    recovery_module._github_get_pages = fake_pages
    recovery_module.fetch_github_comments = fake_comments
    try:
        export = fetch_live_github_export("aradenac/poker-engine", _contract(), 225)
    finally:
        recovery_module._github_get_pages = original_pages
        recovery_module.fetch_github_comments = original_comments

    assert [call[1] for call in page_calls] == ["issues", "pulls"]
    expected = {225, 999, *[100 + index for index in range(1, 9)]}
    assert {issue for _, issue in comment_calls} == expected
    assert export["coverage"] == {
        "comments_complete": True,
        "open_issues_complete": True,
        "open_pulls_complete": True,
        "dispatch_issue": 225,
    }


def test_project_state_scope_covers_recovery_files() -> None:
    from tools.check_parallel_scope import check_scope, load_contract
    contract = load_contract(ROOT / ".project/parallel-agents.json")
    report = check_scope(contract, "G", [
        ".project/recovery-state.schema.json",
        ".project/parallel-agents.json",
        "tools/build_recovery_state.py",
        "tests/test_recovery_state.py",
        "tests/fixtures/project-state/recovery/github-export.json",
        "docs/project-state.md",
    ])
    assert report["status"] == "PASS", report


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"recovery state tests: {len(tests)} passed")


if __name__ == "__main__":
    main()
