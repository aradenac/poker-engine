#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_parallel_scope import (
    SLOTS,
    check_scope,
    glob_match,
    load_contract,
)

REPORT_SCHEMA = "poker-parallel-claims-report/v1"
CLAIM_MARKER = "<!-- parallel-claim:v1 -->"
WORKLOG_MARKER = "<!-- agent-worklog:v1 -->"
CLAIM_STATUSES = {"CLAIMED", "RELEASED"}


def _issue_number(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    match = re.search(r"#?(\d+)", value.strip())
    return int(match.group(1)) if match else None


def _pr_number(value: Any) -> int | None:
    return _issue_number(value)


def _scalar(lines: list[str], key: str) -> str | None:
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.*)$")
    for raw in lines:
        match = pattern.match(raw.strip())
        if match:
            value = match.group(1).strip()
            return value or None
    return None


def _bullet_block(lines: list[str], key: str) -> list[str]:
    start = None
    for index, raw in enumerate(lines):
        if raw.strip() == f"{key}:":
            start = index + 1
            break
    if start is None:
        return []
    items: list[str] = []
    for raw in lines[start:]:
        stripped = raw.strip()
        if not stripped:
            if items:
                break
            continue
        if re.match(r"^[A-Z][A-Z0-9_ /-]*:\s*", stripped):
            break
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
            continue
        if items:
            break
    return items


def _base_head(value: str | None) -> dict[str, str | None]:
    if not value:
        return {"base": None, "head": None}
    if "/" in value:
        base, head = value.split("/", 1)
        return {"base": base.strip() or None, "head": head.strip() or None}
    return {"base": value.strip() or None, "head": None}


def _comment_key(comment: dict[str, Any], index: int) -> tuple[str, int, int]:
    created = comment.get("created_at")
    created_key = created if isinstance(created, str) else ""
    raw_id = comment.get("id")
    try:
        id_key = int(raw_id)
    except (TypeError, ValueError):
        id_key = index
    return created_key, id_key, index


def normalize_comments(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("comments"), list):
            value = value["comments"]
        elif isinstance(value.get("items"), list):
            value = value["items"]
    if not isinstance(value, list):
        raise ValueError("comments JSON must be a list or an object containing a comments/items list")
    comments = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"comment #{index} must be an object")
        body = item.get("body")
        if body is None:
            body = ""
        if not isinstance(body, str):
            raise ValueError(f"comment #{index}.body must be a string")
        normalized = dict(item)
        normalized["body"] = body
        normalized["_input_index"] = index
        comments.append(normalized)
    comments.sort(key=lambda row: _comment_key(row, row["_input_index"]))
    return comments


def parse_comment_events(comment: dict[str, Any], order: int) -> list[dict[str, Any]]:
    body = comment.get("body", "")
    lines = body.splitlines()
    events: list[dict[str, Any]] = []
    common = {
        "order": order,
        "timestamp": comment.get("created_at"),
        "comment_id": comment.get("id"),
        "source_issue": _issue_number(comment.get("source_issue") or comment.get("issue_number")),
    }
    if CLAIM_MARKER in body:
        status = _scalar(lines, "STATUS")
        event = {
            **common,
            "kind": "claim",
            "slot": (_scalar(lines, "AGENT_SLOT") or "").upper() or None,
            "issue": _issue_number(_scalar(lines, "ISSUE")),
            "status": status.upper() if status else None,
            "base": _scalar(lines, "BASE"),
            "branch": _scalar(lines, "BRANCH"),
            "conflict_group": _scalar(lines, "CONFLICT_GROUP"),
            "files_intent": _bullet_block(lines, "FILES_INTENT"),
            "pr": _pr_number(_scalar(lines, "PR")),
            "result": _scalar(lines, "RESULT"),
            "next": _scalar(lines, "NEXT"),
            "notes": _scalar(lines, "NOTES"),
            "body": body,
        }
        events.append(event)
    if WORKLOG_MARKER in body:
        event = {
            **common,
            "kind": "worklog",
            "slot": (_scalar(lines, "AGENT_SLOT") or "").upper() or None,
            "issue": _issue_number(_scalar(lines, "ISSUE")),
            "pr": _pr_number(_scalar(lines, "PR")),
            **_base_head(_scalar(lines, "BASE/HEAD")),
            "body": body,
        }
        events.append(event)
    return events


def parse_events(comments: Any) -> list[dict[str, Any]]:
    normalized = normalize_comments(comments)
    events: list[dict[str, Any]] = []
    for order, comment in enumerate(normalized, start=1):
        events.extend(parse_comment_events(comment, order))
    kind_rank = {"claim": 0, "worklog": 1}
    events.sort(key=lambda event: (event["order"], kind_rank[event["kind"]]))
    return events


def _event_ref(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": event.get("kind"),
        "order": event.get("order"),
        "timestamp": event.get("timestamp"),
        "comment_id": event.get("comment_id"),
        "slot": event.get("slot"),
        "issue": event.get("issue"),
        "status": event.get("status"),
        "branch": event.get("branch"),
        "pr": event.get("pr"),
    }


def _violation(code: str, event: dict[str, Any], detail: str, **extra: Any) -> dict[str, Any]:
    row = {
        "code": code,
        "order": event.get("order"),
        "timestamp": event.get("timestamp"),
        "comment_id": event.get("comment_id"),
        "slot": event.get("slot"),
        "issue": event.get("issue"),
        "detail": detail,
    }
    row.update(extra)
    return row


def _warning(code: str, event: dict[str, Any], detail: str, **extra: Any) -> dict[str, Any]:
    return _violation(code, event, detail, **extra)


def _expected_issue_slots(contract: dict[str, Any], issue: int) -> list[str]:
    return sorted(
        slot
        for slot, lane in contract["lanes"].items()
        if issue in lane.get("typical_issues", [])
    )


def _branch_matches_issue(branch: str, issue: int) -> bool:
    return bool(re.search(rf"(?:^|[/_-])issue[-_/]?{issue}(?:$|[/_-])", branch, re.IGNORECASE))


def _other_lane_hotspots(contract: dict[str, Any], slot: str, path: str) -> list[dict[str, Any]]:
    return sorted(
        [
            item
            for item in contract.get("exclusive_hotspots", [])
            if item.get("owner") != slot
            and isinstance(item.get("glob"), str)
            and glob_match(path, item["glob"])
        ],
        key=lambda row: (row.get("owner", ""), row.get("glob", "")),
    )


def _claim_completeness(event: dict[str, Any]) -> list[str]:
    if event.get("status") == "CLAIMED":
        required = ("slot", "issue", "base", "branch", "conflict_group")
        missing = [name for name in required if not event.get(name)]
        if not event.get("files_intent"):
            missing.append("files_intent")
        return missing
    if event.get("status") == "RELEASED":
        return [name for name in ("slot", "issue") if not event.get(name)]
    return ["status"]


def _claim_record(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "slot": event.get("slot"),
        "issue": event.get("issue"),
        "status": "CLAIMED",
        "base": event.get("base"),
        "branch": event.get("branch"),
        "conflict_group": event.get("conflict_group"),
        "files_intent": list(event.get("files_intent") or []),
        "pr": event.get("pr"),
        "claimed_order": event.get("order"),
        "claimed_timestamp": event.get("timestamp"),
        "claimed_comment_id": event.get("comment_id"),
        "released": False,
        "release": None,
    }


def analyze_comments(comments: Any, contract: dict[str, Any]) -> dict[str, Any]:
    events = parse_events(comments)
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    last_worklog: dict[str, dict[str, Any]] = {}
    last_release: dict[str, dict[str, Any]] = {}
    last_released_pair: dict[tuple[str, int], dict[str, Any]] = {}

    def active_claims(slot: str | None = None, issue: int | None = None) -> list[dict[str, Any]]:
        rows = [claim for claim in claims if not claim["released"]]
        if slot is not None:
            rows = [claim for claim in rows if claim.get("slot") == slot]
        if issue is not None:
            rows = [claim for claim in rows if claim.get("issue") == issue]
        return rows

    for event in events:
        slot = event.get("slot")
        issue = event.get("issue")

        if event["kind"] == "worklog":
            if slot not in SLOTS or issue is None:
                violations.append(_violation(
                    "WORKLOG_INCOMPLETE", event,
                    "agent-worklog:v1 requires a valid AGENT_SLOT A-H and ISSUE",
                ))
                continue
            last_worklog[slot] = _event_ref(event)
            matching = active_claims(slot, issue)
            if matching and event.get("pr") is not None:
                matching[-1]["pr"] = event["pr"]
            if not matching:
                violations.append(_violation(
                    "WORKLOG_WITHOUT_CLAIM", event,
                    f"worklog for slot {slot} issue #{issue} has no corresponding active claim",
                ))
                if (slot, issue) in last_released_pair:
                    violations.append(_violation(
                        "WORKLOG_AFTER_RELEASE", event,
                        f"worklog appears after RELEASED for slot {slot} issue #{issue} without a new claim",
                    ))
            continue

        status = event.get("status")
        missing = _claim_completeness(event)
        if missing:
            violations.append(_violation(
                "CLAIM_INCOMPLETE", event,
                "parallel-claim:v1 missing/invalid fields: " + ", ".join(sorted(missing)),
                missing_fields=sorted(missing),
            ))

        if slot not in SLOTS or issue is None or status not in CLAIM_STATUSES:
            continue

        lane = contract["lanes"][slot]
        expected_group = lane["conflict_group"]

        if status == "CLAIMED":
            if event.get("conflict_group") and event["conflict_group"] != expected_group:
                violations.append(_violation(
                    "CONFLICT_GROUP_MISMATCH", event,
                    f"slot {slot} expects conflict group {expected_group}, got {event['conflict_group']}",
                    expected_conflict_group=expected_group,
                    actual_conflict_group=event.get("conflict_group"),
                ))

            expected_slots = _expected_issue_slots(contract, issue)
            if expected_slots and slot not in expected_slots:
                violations.append(_violation(
                    "ISSUE_LANE_MISMATCH", event,
                    f"issue #{issue} is assigned in the machine-readable mirror to {','.join(expected_slots)}, not {slot}",
                    expected_slots=expected_slots,
                ))
            elif not expected_slots:
                warnings.append(_warning(
                    "ISSUE_NOT_IN_LANE_CONTRACT", event,
                    f"issue #{issue} is not listed in any lane typical_issues; verify against live #225",
                ))

            branch = event.get("branch")
            if branch and not _branch_matches_issue(branch, issue):
                violations.append(_violation(
                    "BRANCH_ISSUE_MISMATCH", event,
                    f"branch {branch!r} does not encode issue #{issue}",
                    branch=branch,
                ))

            slot_active = active_claims(slot=slot)
            same_pair = [claim for claim in slot_active if claim.get("issue") == issue]
            if same_pair:
                violations.append(_violation(
                    "DOUBLE_ACTIVE_CLAIM", event,
                    f"slot {slot} already has an active claim for issue #{issue}",
                    previous_claim_order=same_pair[-1]["claimed_order"],
                ))
            if slot_active and not same_pair:
                violations.append(_violation(
                    "SLOT_ALREADY_CLAIMED", event,
                    f"slot {slot} is already active on issue(s) "
                    + ", ".join(f"#{row['issue']}" for row in slot_active),
                    active_issues=sorted({row["issue"] for row in slot_active}),
                ))

            other_slots = [
                claim for claim in active_claims(issue=issue)
                if claim.get("slot") != slot
            ]
            if other_slots:
                violations.append(_violation(
                    "ISSUE_CLAIMED_BY_MULTIPLE_SLOTS", event,
                    f"issue #{issue} is already actively claimed by "
                    + ", ".join(sorted({str(row['slot']) for row in other_slots})),
                    other_slots=sorted({str(row["slot"]) for row in other_slots}),
                ))

            files_intent = event.get("files_intent") or []
            if files_intent:
                scope = check_scope(contract, slot, files_intent)
                for item in scope["violations"]:
                    violations.append(_violation(
                        "FILES_INTENT_SCOPE_VIOLATION", event,
                        f"{item['file']}: {item['rule']} ({item['detail']})",
                        file=item["file"],
                        scope_rule=item["rule"],
                        expected_owner=item.get("expected_owner"),
                    ))
                for item in scope["warnings"]:
                    warnings.append(_warning(
                        "FILES_INTENT_UNCLASSIFIED", event,
                        f"{item['file']}: {item['detail']}",
                        file=item["file"],
                        scope_rule=item["rule"],
                    ))
                for path in sorted(set(files_intent)):
                    for hotspot in _other_lane_hotspots(contract, slot, path):
                        violations.append(_violation(
                            "HOTSPOT_CLAIM_VIOLATION", event,
                            f"{path} is an exclusive hotspot of lane {hotspot['owner']}",
                            file=path,
                            expected_owner=hotspot["owner"],
                            hotspot_rule=hotspot.get("rule"),
                        ))

            pair = (slot, issue)
            if pair in last_released_pair:
                warnings.append(_warning(
                    "CLEAN_RECLAIM_AFTER_RELEASE", event,
                    f"slot {slot} cleanly reclaims issue #{issue} after a prior release",
                    prior_release_order=last_released_pair[pair]["order"],
                ))

            claims.append(_claim_record(event))
            continue

        matching = active_claims(slot=slot, issue=issue)
        if not matching:
            violations.append(_violation(
                "RELEASE_WITHOUT_CLAIM", event,
                f"release for slot {slot} issue #{issue} has no corresponding active claim",
            ))
            last_release[slot] = _event_ref(event)
            last_released_pair[(slot, issue)] = _event_ref(event)
            continue

        claim = matching[-1]
        claim["released"] = True
        claim["release"] = _event_ref(event)
        if event.get("pr") is not None:
            claim["pr"] = event.get("pr")
        last_release[slot] = _event_ref(event)
        last_released_pair[(slot, issue)] = _event_ref(event)

    active = [claim for claim in claims if not claim["released"]]
    for claim in active:
        synthetic = {
            "order": claim["claimed_order"],
            "timestamp": claim["claimed_timestamp"],
            "comment_id": claim["claimed_comment_id"],
            "slot": claim["slot"],
            "issue": claim["issue"],
        }
        warnings.append(_warning(
            "CLAIM_WITHOUT_RELEASE", synthetic,
            f"slot {claim['slot']} issue #{claim['issue']} is currently active and has no RELEASED event yet",
            branch=claim.get("branch"),
        ))

    slots: dict[str, Any] = {}
    for slot in SLOTS:
        slot_active = sorted(
            [claim for claim in active if claim.get("slot") == slot],
            key=lambda row: (row["claimed_order"], row.get("issue") or -1),
        )
        latest = slot_active[-1] if slot_active else None
        release = last_release.get(slot)
        if latest:
            status = "CLAIMED"
        elif release:
            status = "RELEASED"
        else:
            status = "IDLE"
        slots[slot] = {
            "slot": slot,
            "conflict_group": contract["lanes"][slot]["conflict_group"],
            "status": status,
            "active_issue": latest.get("issue") if latest else None,
            "active_claim_count": len(slot_active),
            "base": latest.get("base") if latest else None,
            "branch": latest.get("branch") if latest else None,
            "files_intent": latest.get("files_intent") if latest else [],
            "pr": latest.get("pr") if latest else (release.get("pr") if release else None),
            "last_worklog": last_worklog.get(slot),
            "last_release": release,
        }

    active_claim_rows = [
        {
            key: claim.get(key)
            for key in (
                "slot", "issue", "base", "branch", "conflict_group",
                "files_intent", "pr", "claimed_order", "claimed_timestamp",
            )
        }
        for claim in active
    ]
    active_claim_rows.sort(key=lambda row: (row["slot"] or "", row["issue"] or -1, row["claimed_order"] or -1))

    violations.sort(key=lambda row: (
        row.get("order") or 0, row["code"], row.get("slot") or "",
        row.get("issue") or -1, row.get("file") or "",
    ))
    warnings.sort(key=lambda row: (
        row.get("order") or 0, row["code"], row.get("slot") or "",
        row.get("issue") or -1, row.get("file") or "",
    ))

    return {
        "schema": REPORT_SCHEMA,
        "source_of_truth": "#225",
        "slots": slots,
        "active_claims": active_claim_rows,
        "violations": violations,
        "warnings": warnings,
        "events": [_event_ref(event) for event in events],
    }


def stable_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def human_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    for slot in SLOTS:
        row = report["slots"][slot]
        if row["status"] == "CLAIMED":
            issue = f"#{row['active_issue']}" if row["active_issue"] is not None else "-"
            branch = row["branch"] or "-"
            suffix = f" active_claims={row['active_claim_count']}" if row["active_claim_count"] > 1 else ""
            lines.append(f"{slot}  CLAIMED   {issue:<6} {branch}{suffix}")
        elif row["status"] == "RELEASED":
            release = row.get("last_release") or {}
            issue = f"#{release.get('issue')}" if release.get("issue") is not None else "-"
            pr = f" PR #{release['pr']}" if release.get("pr") is not None else ""
            lines.append(f"{slot}  RELEASED  {issue:<6}{pr}")
        else:
            lines.append(f"{slot}  IDLE      -")

    lines.append("")
    lines.append(f"VIOLATIONS ({len(report['violations'])})")
    if report["violations"]:
        for item in report["violations"]:
            locus = f"{item.get('slot') or '-'}"
            if item.get("issue") is not None:
                locus += f"/#{item['issue']}"
            lines.append(f"- {item['code']} [{locus}] order={item.get('order')}: {item['detail']}")
    else:
        lines.append("- none")

    lines.append("")
    lines.append(f"WARNINGS ({len(report['warnings'])})")
    if report["warnings"]:
        for item in report["warnings"]:
            locus = f"{item.get('slot') or '-'}"
            if item.get("issue") is not None:
                locus += f"/#{item['issue']}"
            lines.append(f"- {item['code']} [{locus}] order={item.get('order')}: {item['detail']}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def load_comments_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read comments JSON {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid comments JSON {path}: {exc}") from exc


def fetch_github_comments(repo: str, issue: int) -> list[dict[str, Any]]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("--repo must use owner/name form")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({"per_page": 100, "page": page})
        url = f"https://api.github.com/repos/{repo}/issues/{issue}/comments?{query}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "poker-engine-parallel-claims-checker",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ValueError(f"GitHub comments read failed: {exc}") from exc
        if not isinstance(payload, list):
            raise ValueError("GitHub comments API returned a non-list payload")
        for row in payload:
            if isinstance(row, dict):
                item = dict(row)
                item["source_issue"] = issue
                comments.append(item)
        if len(payload) < 100:
            break
        page += 1
    return comments


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reconstruct #225 parallel-agent claim state from GitHub comments without mutation."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--comments-json", type=Path)
    source.add_argument("--repo")
    parser.add_argument("--issue", type=int)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--contract", type=Path, default=ROOT / ".project/parallel-agents.json")
    args = parser.parse_args(argv)

    try:
        contract = load_contract(args.contract.resolve())
        if args.comments_json:
            if args.issue is not None:
                raise ValueError("--issue is only valid with --repo")
            comments = load_comments_file(args.comments_json)
        else:
            if args.issue is None:
                raise ValueError("--repo requires --issue")
            comments = fetch_github_comments(args.repo, args.issue)
        report = analyze_comments(comments, contract)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        error_report = {
            "schema": REPORT_SCHEMA,
            "source_of_truth": "#225",
            "slots": {},
            "active_claims": [],
            "violations": [{
                "code": "CHECKER_ERROR", "order": 0, "timestamp": None,
                "comment_id": None, "slot": None, "issue": None, "detail": str(exc),
            }],
            "warnings": [],
            "events": [],
        }
        print(stable_json(error_report) if args.json_output else f"CHECKER_ERROR: {exc}\n", end="")
        return 2

    print(stable_json(report) if args.json_output else human_report(report), end="")
    return 1 if report["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
