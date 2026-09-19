#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "audit_backlog_evidence.py"
SPEC = importlib.util.spec_from_file_location("audit_backlog_evidence", TOOL)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)

from tools.check_parallel_scope import check_scope, load_contract


def _project_report(state: str = "CONTRACT_READY") -> dict:
    return {
        "schema": "poker-project-state-report/v1",
        "status": "PASS",
        "errors": [],
        "warnings": [],
        "capabilities": [{"id": "cap", "state": state, "limits": []}],
    }


def _manifest(claimed_state: str = "PRODUCT_INTEGRATED", issue: int = 10) -> dict:
    return {
        "schema": "poker-project-capabilities/v1",
        "state_order": list(audit.STATES),
        "capabilities": [{
            "id": "cap",
            "summary": "fixture",
            "state": "CONTRACT_READY",
            "evidence": [],
            "administrative": {
                "issue": issue,
                "status": "OPEN",
                "claimed_state": claimed_state,
            },
        }],
    }


def _claims(active: list[dict] | None = None) -> dict:
    return {
        "schema": "poker-parallel-claims-report/v1",
        "active_claims": active or [],
        "violations": [],
        "warnings": [],
        "slots": {},
    }


def _recovery() -> dict:
    return {
        "schema": "poker-recovery-state/v1",
        "status": "PASS",
        "lanes": {
            slot: {
                "slot": slot,
                "status": "FREE",
                "active_issue": None,
                "branch": None,
                "pr": None,
            }
            for slot in "ABCDEFGH"
        },
        "warnings": [],
    }


def _export() -> dict:
    return {
        "schema": audit.EXPORT_SCHEMA,
        "coverage": {
            "comments_complete": True,
            "issues_complete": True,
            "pulls_complete": True,
            "branches_complete": True,
            "dispatch_issue": 225,
        },
        "comments": [],
        "issues": [],
        "pulls": [],
        "branches": [],
        "read_errors": [],
    }


def _finding(report: dict, issue: int) -> dict:
    return next(row for row in report["findings"] if row["subject"] == {"kind": "ISSUE", "issue": issue})


def test_normalization_and_render_are_order_independent() -> None:
    value = _export()
    value["issues"] = [
        {"number": 2, "state": "open", "title": "b", "labels": ["z", "a"]},
        {"number": 1, "state": "closed", "title": "a", "labels": []},
    ]
    value["pulls"] = [
        {"number": 20, "state": "closed", "merged": True, "head": "b"},
        {"number": 10, "state": "open", "head": "a"},
    ]
    value["branches"] = [{"name": "z"}, {"name": "a"}]
    first = audit.normalize_audit_export(value)
    shuffled = copy.deepcopy(value)
    shuffled["issues"].reverse()
    shuffled["pulls"].reverse()
    shuffled["branches"].reverse()
    second = audit.normalize_audit_export(shuffled)
    assert audit.stable_json(first) == audit.stable_json(second)
    assert first["branches"] == ["a", "z"]
    assert first["issues"][1]["labels"] == ["a", "z"]


def test_closed_issue_below_declared_capability_is_contradiction() -> None:
    export = _export()
    export["issues"] = [{"number": 10, "state": "closed", "title": "done"}]
    report = audit.build_backlog_report({}, _manifest(), _project_report("CONTRACT_READY"), _claims(), _recovery(), export)
    row = _finding(report, 10)
    assert row["category"] == "CONTRADICTION"
    assert "CLOSED_BELOW_DECLARED_CAPABILITY_STATE" in row["codes"]


def test_open_issue_with_satisfied_capability_is_close_candidate() -> None:
    export = _export()
    export["issues"] = [{"number": 10, "state": "open", "title": "ready"}]
    report = audit.build_backlog_report({}, _manifest(), _project_report("PRODUCT_INTEGRATED"), _claims(), _recovery(), export)
    row = _finding(report, 10)
    assert row["category"] == "CLOSE_CANDIDATE"
    assert "OPEN_CAPABILITY_EVIDENCE_SATISFIED" in row["codes"]


def test_merged_released_no_gaps_is_close_candidate() -> None:
    export = _export()
    export["issues"] = [{"number": 20, "state": "open", "title": "ready"}]
    export["pulls"] = [{"number": 120, "state": "closed", "merged": True, "head": "agent-G/issue-20-x"}]
    export["comments"] = [
        {"id": 1, "created_at": "2026-09-19T00:00:00Z", "source_issue": 20,
         "body": "<!-- agent-worklog:v1 -->\nAGENT_SLOT: G\nISSUE: #20\nBASE/HEAD: a / b\nPR: #120\nREMAINING_GAPS:\n- None"},
        {"id": 2, "created_at": "2026-09-19T00:01:00Z", "source_issue": 20,
         "body": "<!-- parallel-claim:v1 -->\nAGENT_SLOT: G\nISSUE: #20\nSTATUS: RELEASED\nPR: #120"},
    ]
    report = audit.build_backlog_report({}, {"capabilities": []}, _project_report(), _claims(), _recovery(), export)
    row = _finding(report, 20)
    assert row["category"] == "CLOSE_CANDIDATE"
    assert "MERGED_RELEASED_NO_REMAINING_GAP" in row["codes"]


def test_merged_released_only_deferred_gaps_is_blocked() -> None:
    export = _export()
    export["issues"] = [{"number": 21, "state": "open", "title": "blocked"}]
    export["pulls"] = [{"number": 121, "state": "closed", "merged": True}]
    export["comments"] = [
        {"id": 1, "created_at": "2026-09-19T00:00:00Z", "source_issue": 21,
         "body": "<!-- agent-worklog:v1 -->\nAGENT_SLOT: G\nISSUE: #21\nBASE/HEAD: a / b\nPR: #121\nREMAINING_GAPS:\n- mandatory CI wiring remains deferred"},
        {"id": 2, "created_at": "2026-09-19T00:01:00Z", "source_issue": 21,
         "body": "<!-- parallel-claim:v1 -->\nAGENT_SLOT: G\nISSUE: #21\nSTATUS: RELEASED\nPR: #121"},
    ]
    report = audit.build_backlog_report({}, {"capabilities": []}, _project_report(), _claims(), _recovery(), export)
    row = _finding(report, 21)
    assert row["category"] == "BLOCKED"
    assert "MERGED_RELEASED_ONLY_DEFERRED_GAPS" in row["codes"]


def test_active_claim_missing_branch_is_contradiction() -> None:
    export = _export()
    export["issues"] = [{"number": 30, "state": "open", "title": "active"}]
    active = [{
        "slot": "G", "issue": 30, "branch": "agent-G/issue-30-missing", "pr": None,
        "claimed_comment_id": 3, "claimed_order": 3,
    }]
    recovery = _recovery()
    recovery["lanes"]["G"].update({"status": "CLAIMED", "active_issue": 30, "branch": "agent-G/issue-30-missing"})
    report = audit.build_backlog_report({}, {"capabilities": []}, _project_report(), _claims(active), recovery, export)
    row = _finding(report, 30)
    assert row["category"] == "CONTRADICTION"
    assert any("branch" in detail for detail in row["justification"])


def test_valid_active_claim_is_keep_open() -> None:
    export = _export()
    export["issues"] = [{"number": 31, "state": "open", "title": "active"}]
    export["branches"] = ["agent-G/issue-31-active"]
    export["pulls"] = [{"number": 131, "state": "open", "merged": False, "head": "agent-G/issue-31-active"}]
    active = [{
        "slot": "G", "issue": 31, "branch": "agent-G/issue-31-active", "pr": 131,
        "claimed_comment_id": 4, "claimed_order": 4,
    }]
    recovery = _recovery()
    recovery["lanes"]["G"].update({"status": "CLAIMED", "active_issue": 31, "branch": "agent-G/issue-31-active", "pr": 131})
    report = audit.build_backlog_report({}, {"capabilities": []}, _project_report(), _claims(active), recovery, export)
    row = _finding(report, 31)
    assert row["category"] == "KEEP_OPEN"
    assert "ACTIVE_CLAIM" in row["codes"]


def test_active_or_blocked_evidence_overrides_close_candidate() -> None:
    manifest = _manifest()
    project = _project_report("PRODUCT_INTEGRATED")

    active_export = _export()
    active_export["issues"] = [{"number": 10, "state": "open", "title": "active"}]
    active_export["branches"] = ["agent-G/issue-10-active"]
    active = [{
        "slot": "G", "issue": 10, "branch": "agent-G/issue-10-active", "pr": None,
        "claimed_comment_id": 9, "claimed_order": 9,
    }]
    recovery = _recovery()
    recovery["lanes"]["G"].update({"status": "CLAIMED", "active_issue": 10, "branch": "agent-G/issue-10-active"})
    active_report = audit.build_backlog_report({}, manifest, project, _claims(active), recovery, active_export)
    assert _finding(active_report, 10)["category"] == "KEEP_OPEN"

    blocked_export = _export()
    blocked_export["issues"] = [{"number": 10, "state": "open", "title": "blocked", "labels": ["blocked"]}]
    blocked_report = audit.build_backlog_report({}, manifest, project, _claims(), _recovery(), blocked_export)
    assert _finding(blocked_report, 10)["category"] == "BLOCKED"


def test_recovery_warning_becomes_lane_contradiction() -> None:
    recovery = _recovery()
    recovery["warnings"] = [{
        "code": "OPEN_PR_WITHOUT_ACTIVE_CLAIM",
        "slot": "C",
        "detail": "open PR exists without active claim",
        "prs": [55],
    }]
    report = audit.build_backlog_report({}, {"capabilities": []}, _project_report(), _claims(), recovery, _export())
    row = next(item for item in report["findings"] if item["subject"] == {"kind": "LANE", "slot": "C"})
    assert row["category"] == "CONTRADICTION"
    assert "RECOVERY_OPEN_PR_WITHOUT_ACTIVE_CLAIM" in row["codes"]


def test_incomplete_coverage_never_creates_positive_conclusion() -> None:
    export = _export()
    export["coverage"]["pulls_complete"] = False
    export["issues"] = [{"number": 40, "state": "open", "title": "unknown"}]
    report = audit.build_backlog_report({}, {"capabilities": []}, _project_report(), _claims(), _recovery(), export)
    assert _finding(report, 40)["category"] == "UNKNOWN"
    assert any(row["code"] == "PULLS_COMPLETE_FALSE" for row in report["warnings"])


def test_report_file_compare_exact_and_stale() -> None:
    report = audit.build_backlog_report({}, {"capabilities": []}, _project_report(), _claims(), _recovery(), _export())
    rendered = audit.stable_json(report)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "report.json"
        path.write_text(rendered, encoding="utf-8")
        assert audit.compare_report_file(path, rendered) == (True, "")
        path.write_text(rendered + "\n", encoding="utf-8")
        current, diff = audit.compare_report_file(path, rendered)
        assert current is False
        assert "generated-backlog-evidence-report" in diff


def test_repository_fixture_reuses_real_project_and_claim_validators() -> None:
    fixture = json.loads((ROOT / "tests/fixtures/project-state/backlog/github-export.json").read_text(encoding="utf-8"))
    report = audit.build_report(ROOT, fixture)
    by_issue = {
        row["subject"]["issue"]: row
        for row in report["findings"]
        if row["subject"]["kind"] == "ISSUE"
    }
    assert by_issue[109]["category"] == "CONTRADICTION"
    assert "CLOSED_BELOW_DECLARED_CAPABILITY_STATE" in by_issue[109]["codes"]
    assert by_issue[216]["category"] == "CLOSE_CANDIDATE"
    assert by_issue[203]["category"] == "BLOCKED"
    assert by_issue[206]["category"] == "BLOCKED"
    assert report["policy"] == {
        "github_mutation": False,
        "automatic_close_reopen_merge": False,
        "missing_proof": "UNKNOWN",
    }


def test_repository_fixture_is_deterministic() -> None:
    fixture = json.loads((ROOT / "tests/fixtures/project-state/backlog/github-export.json").read_text(encoding="utf-8"))
    first = audit.build_report(ROOT, fixture)
    shuffled = copy.deepcopy(fixture)
    shuffled["comments"].reverse()
    shuffled["issues"].reverse()
    shuffled["pulls"].reverse()
    second = audit.build_report(ROOT, shuffled)
    assert audit.stable_json(first) == audit.stable_json(second)


def test_live_adapter_uses_only_existing_get_readers() -> None:
    calls = []
    original_recovery = audit.fetch_live_github_export
    original_pages = audit._github_get_pages

    def fake_recovery(repo: str, contract: dict, dispatch_issue: int) -> dict:
        return {
            "schema": "poker-recovery-github-export/v1",
            "coverage": {
                "comments_complete": True,
                "open_issues_complete": True,
                "open_pulls_complete": True,
                "dispatch_issue": dispatch_issue,
            },
            "comments": [],
            "issues": [],
            "pulls": [],
            "read_errors": [],
        }

    def fake_pages(repo: str, resource: str, params: dict) -> list[dict]:
        calls.append((resource, dict(params)))
        if resource == "issues":
            return [{"number": 206, "state": "open", "title": "state"}]
        if resource == "pulls":
            return []
        if resource == "branches":
            return [{"name": "main"}]
        raise AssertionError(resource)

    audit.fetch_live_github_export = fake_recovery
    audit._github_get_pages = fake_pages
    try:
        result = audit.fetch_live_audit_export("aradenac/poker-engine", {}, 225)
    finally:
        audit.fetch_live_github_export = original_recovery
        audit._github_get_pages = original_pages

    assert [row[0] for row in calls] == ["issues", "pulls", "branches"]
    assert all(row[1].get("state") == "all" for row in calls[:2])
    assert result["coverage"] == {
        "comments_complete": True,
        "issues_complete": True,
        "pulls_complete": True,
        "branches_complete": True,
        "dispatch_issue": 225,
    }
    source = TOOL.read_text(encoding="utf-8")
    assert "method=\"POST\"" not in source
    assert "method=\"PATCH\"" not in source
    assert "method=\"DELETE\"" not in source


def test_project_state_scope_covers_backlog_audit_files() -> None:
    contract = load_contract(ROOT / ".project/parallel-agents.json")
    report = check_scope(contract, "G", [
        ".project/backlog-evidence-report.schema.json",
        ".project/parallel-agents.json",
        "tools/audit_backlog_evidence.py",
        "tests/test_backlog_evidence.py",
        "tests/fixtures/project-state/backlog/github-export.json",
        "docs/project-state.md",
    ])
    assert report["status"] == "PASS", report


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"backlog evidence tests: {len(tests)} passed")


if __name__ == "__main__":
    main()
