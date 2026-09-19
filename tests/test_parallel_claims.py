#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import tools.check_parallel_claims as claims_module
from tools.check_parallel_claims import (
    analyze_comments,
    human_report,
    parse_events,
    stable_json,
)
from tools.check_parallel_scope import load_contract

CONTRACT = load_contract(ROOT / ".project/parallel-agents.json")
FIXTURE = ROOT / "tests/fixtures/parallel/comments.json"


def comment(body: str, order: int, source_issue: int | None = None) -> dict:
    row = {
        "id": 10000 + order,
        "created_at": f"2026-09-19T01:{order:02d}:00Z",
        "body": body,
    }
    if source_issue is not None:
        row["source_issue"] = source_issue
    return row


def claim(slot: str, issue: int, order: int, *, group: str | None = None, branch: str | None = None,
          files: list[str] | None = None, status: str = "CLAIMED", pr: int | None = None) -> dict:
    if status == "RELEASED":
        return comment(
            "\n".join([
                "<!-- parallel-claim:v1 -->",
                f"AGENT_SLOT: {slot}",
                f"ISSUE: #{issue}",
                "STATUS: RELEASED",
                *( [f"PR: #{pr}"] if pr else [] ),
                "RESULT: ready",
                "NEXT: none",
            ]),
            order,
        )
    lane_group = group or CONTRACT["lanes"][slot]["conflict_group"]
    branch = branch or f"agent-{slot}/issue-{issue}-test"
    files = files or [CONTRACT["lanes"][slot]["reserved_paths"][0]]
    return comment(
        "\n".join([
            "<!-- parallel-claim:v1 -->",
            f"AGENT_SLOT: {slot}",
            f"ISSUE: #{issue}",
            "STATUS: CLAIMED",
            f"BASE: base-{order}",
            f"BRANCH: {branch}",
            f"CONFLICT_GROUP: {lane_group}",
            "FILES_INTENT:",
            *[f"- {path}" for path in files],
            "NOTES: test",
        ]),
        order,
    )


def worklog(slot: str, issue: int, order: int) -> dict:
    return comment(
        "\n".join([
            "<!-- agent-worklog:v1 -->",
            f"AGENT_SLOT: {slot}",
            f"ISSUE: #{issue}",
            f"BASE/HEAD: b{order} / h{order}",
            f"PR: #{400 + order}",
        ]),
        order,
    )


def codes(report: dict, bucket: str = "violations") -> list[str]:
    return [row["code"] for row in report[bucket]]


def test_eight_agents_clean_fixture() -> None:
    report = analyze_comments(json.loads(FIXTURE.read_text(encoding="utf-8")), CONTRACT)
    assert report["violations"] == [], report
    assert report["active_claims"] == []
    assert all(report["slots"][slot]["status"] == "RELEASED" for slot in "ABCDEFGH")
    assert all(report["slots"][slot]["last_worklog"] for slot in "ABCDEFGH")


def test_normal_claim_release() -> None:
    report = analyze_comments([claim("G", 264, 1), worklog("G", 264, 2), claim("G", 264, 3, status="RELEASED", pr=500)], CONTRACT)
    assert report["violations"] == []
    assert report["slots"]["G"]["status"] == "RELEASED"
    assert report["slots"]["G"]["last_release"]["pr"] == 500


def test_active_claim_picks_up_pr_from_worklog() -> None:
    report = analyze_comments([claim("G", 264, 1), worklog("G", 264, 2)], CONTRACT)
    assert report["slots"]["G"]["status"] == "CLAIMED"
    assert report["slots"]["G"]["pr"] == 402


def test_double_claim_detected() -> None:
    report = analyze_comments([claim("G", 264, 1), claim("G", 264, 2)], CONTRACT)
    assert "DOUBLE_ACTIVE_CLAIM" in codes(report)
    assert report["slots"]["G"]["active_claim_count"] == 2


def test_slot_already_claimed_on_other_issue() -> None:
    report = analyze_comments([claim("G", 264, 1), claim("G", 206, 2)], CONTRACT)
    assert "SLOT_ALREADY_CLAIMED" in codes(report)


def test_issue_claimed_by_multiple_slots() -> None:
    report = analyze_comments([
        claim("G", 264, 1),
        claim("C", 264, 2, group="ANALYTICS", files=["src/analytics/review-inbox.js"]),
    ], CONTRACT)
    assert "ISSUE_CLAIMED_BY_MULTIPLE_SLOTS" in codes(report)
    assert "ISSUE_LANE_MISMATCH" in codes(report)


def test_reclaim_after_release_is_clean_warning() -> None:
    report = analyze_comments([
        claim("G", 264, 1),
        claim("G", 264, 2, status="RELEASED"),
        claim("G", 264, 3),
    ], CONTRACT)
    assert "DOUBLE_ACTIVE_CLAIM" not in codes(report)
    assert "SLOT_ALREADY_CLAIMED" not in codes(report)
    assert "CLEAN_RECLAIM_AFTER_RELEASE" in codes(report, "warnings")
    assert report["slots"]["G"]["status"] == "CLAIMED"


def test_wrong_lane_and_conflict_group() -> None:
    report = analyze_comments([
        claim("C", 264, 1, group="PROJECT-STATE", files=["src/analytics/review-inbox.js"])
    ], CONTRACT)
    assert "ISSUE_LANE_MISMATCH" in codes(report)
    assert "CONFLICT_GROUP_MISMATCH" in codes(report)


def test_hotspot_and_files_intent_scope_violation() -> None:
    report = analyze_comments([
        claim("G", 264, 1, files=["site/index.html"])
    ], CONTRACT)
    assert "FILES_INTENT_SCOPE_VIOLATION" in codes(report)
    assert "HOTSPOT_CLAIM_VIOLATION" in codes(report)


def test_incomplete_claim() -> None:
    report = analyze_comments([
        comment("\n".join([
            "<!-- parallel-claim:v1 -->",
            "AGENT_SLOT: G",
            "ISSUE: #264",
            "STATUS: CLAIMED",
        ]), 1)
    ], CONTRACT)
    assert "CLAIM_INCOMPLETE" in codes(report)


def test_orphan_worklog_and_after_release() -> None:
    orphan = analyze_comments([worklog("G", 264, 1)], CONTRACT)
    assert "WORKLOG_WITHOUT_CLAIM" in codes(orphan)
    after = analyze_comments([
        claim("G", 264, 1),
        claim("G", 264, 2, status="RELEASED"),
        worklog("G", 264, 3),
    ], CONTRACT)
    assert "WORKLOG_WITHOUT_CLAIM" in codes(after)
    assert "WORKLOG_AFTER_RELEASE" in codes(after)


def test_release_without_claim() -> None:
    report = analyze_comments([claim("G", 264, 1, status="RELEASED")], CONTRACT)
    assert "RELEASE_WITHOUT_CLAIM" in codes(report)


def test_branch_issue_mismatch() -> None:
    report = analyze_comments([
        claim("G", 264, 1, branch="agent-G/issue-206-wrong")
    ], CONTRACT)
    assert "BRANCH_ISSUE_MISMATCH" in codes(report)


def test_active_claim_reports_claim_without_release_warning() -> None:
    report = analyze_comments([claim("G", 264, 1)], CONTRACT)
    assert "CLAIM_WITHOUT_RELEASE" in codes(report, "warnings")
    assert report["slots"]["G"]["active_issue"] == 264


def test_old_events_do_not_override_newer_events() -> None:
    newer_release = claim("G", 264, 3, status="RELEASED", pr=999)
    older_claim = claim("G", 264, 1)
    newer_worklog = worklog("G", 264, 2)
    report = analyze_comments([newer_release, newer_worklog, older_claim], CONTRACT)
    assert report["slots"]["G"]["status"] == "RELEASED"
    assert report["slots"]["G"]["last_release"]["pr"] == 999
    assert report["events"][0]["order"] == 1
    assert report["events"][-1]["order"] == 3


def test_json_and_human_order_are_deterministic() -> None:
    source = [
        claim("H", 211, 4),
        claim("A", 108, 1),
        claim("A", 108, 2, status="RELEASED"),
        claim("H", 211, 5, status="RELEASED"),
    ]
    first = analyze_comments(source, CONTRACT)
    second = analyze_comments(list(reversed(source)), CONTRACT)
    assert stable_json(first) == stable_json(second)
    human = human_report(first)
    slot_lines = human.splitlines()[:8]
    assert [line.split()[0] for line in slot_lines] == list("ABCDEFGH")


def test_parser_handles_github_wrapper_and_source_issue() -> None:
    wrapped = {"comments": [claim("G", 264, 1)]}
    wrapped["comments"][0]["source_issue"] = 225
    events = parse_events(wrapped)
    assert len(events) == 1
    assert events[0]["source_issue"] == 225


def test_github_adapter_is_read_only_and_tags_source_issue() -> None:
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'[{"id": 7, "created_at": "2026-09-19T00:00:00Z", "body": "hello"}]'

    original = claims_module.urllib.request.urlopen

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, request.get_method(), timeout))
        return FakeResponse()

    claims_module.urllib.request.urlopen = fake_urlopen
    try:
        rows = claims_module.fetch_github_comments("aradenac/poker-engine", 225)
    finally:
        claims_module.urllib.request.urlopen = original

    assert len(calls) == 1
    assert calls[0][1] == "GET"
    assert "/issues/225/comments" in calls[0][0]
    assert rows[0]["source_issue"] == 225


def test_project_state_scope_covers_new_checker_files() -> None:
    from tools.check_parallel_scope import check_scope
    report = check_scope(CONTRACT, "G", [
        "tools/check_parallel_claims.py",
        "tests/test_parallel_claims.py",
        "tests/fixtures/parallel/comments.json",
        ".project/PARALLEL_AGENTS.md",
        ".project/parallel-agents.json",
    ])
    assert report["status"] == "PASS", report


def main() -> None:
    cases = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for case in cases:
        case()
    print(f"parallel claims tests: {len(cases)} passed")


if __name__ == "__main__":
    main()
