#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
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

from tools.check_parallel_claims import analyze_comments, fetch_github_comments
from tools.check_parallel_scope import SLOTS, load_contract
from tools.validate_project_state import (
    STATES,
    compare_status_file,
    load_json as load_project_json,
    render_status,
    validate_manifest,
)

SCHEMA = "poker-recovery-state/v1"
EXPORT_SCHEMA = "poker-recovery-github-export/v1"
DEFAULT_DISPATCH_ISSUE = 225
BLOCKED_LABELS = {"blocked", "blocker", "blocked-by-dependency", "blocked by dependency"}


def stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _issue_number(value: Any) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str):
        match = re.search(r"#?(\d+)", value)
        if match:
            return int(match.group(1))
    return None


def _labels(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    labels: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            labels.append(item.strip())
        elif isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip():
            labels.append(item["name"].strip())
    return sorted(set(labels), key=str.casefold)


def _ref_name(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("ref", "label"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return None


def normalize_github_export(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("GitHub recovery export must be a JSON object")
    schema = value.get("schema")
    if schema not in {None, EXPORT_SCHEMA}:
        raise ValueError(f"unsupported GitHub recovery export schema: {schema!r}")

    comments = value.get("comments", [])
    issues = value.get("issues", [])
    pulls = value.get("pulls", value.get("prs", []))
    coverage = value.get("coverage", {})
    read_errors = value.get("read_errors", [])
    if not isinstance(comments, list) or not isinstance(issues, list) or not isinstance(pulls, list):
        raise ValueError("GitHub recovery export comments/issues/pulls must be lists")
    if not isinstance(coverage, dict):
        raise ValueError("GitHub recovery export coverage must be an object")
    if not isinstance(read_errors, list):
        raise ValueError("GitHub recovery export read_errors must be a list")

    normalized_issues: list[dict[str, Any]] = []
    for raw in issues:
        if not isinstance(raw, dict):
            raise ValueError("each GitHub issue export row must be an object")
        number = _issue_number(raw.get("number", raw.get("issue_number")))
        if number is None:
            raise ValueError("each GitHub issue export row requires a positive number")
        state = str(raw.get("state", "UNKNOWN")).upper()
        blocked_by = sorted({n for item in raw.get("blocked_by", []) if (n := _issue_number(item)) is not None}) \
            if isinstance(raw.get("blocked_by", []), list) else []
        normalized_issues.append({
            "number": number,
            "state": state,
            "title": raw.get("title") if isinstance(raw.get("title"), str) else "",
            "labels": _labels(raw.get("labels")),
            "blocked_by": blocked_by,
            "recovery_ready": raw.get("recovery_ready") is True,
        })
    normalized_issues.sort(key=lambda row: row["number"])

    normalized_pulls: list[dict[str, Any]] = []
    for raw in pulls:
        if not isinstance(raw, dict):
            raise ValueError("each GitHub pull export row must be an object")
        number = _issue_number(raw.get("number", raw.get("pr_number")))
        if number is None:
            raise ValueError("each GitHub pull export row requires a positive number")
        normalized_pulls.append({
            "number": number,
            "state": str(raw.get("state", "UNKNOWN")).upper(),
            "title": raw.get("title") if isinstance(raw.get("title"), str) else "",
            "head": _ref_name(raw.get("head")) or _ref_name(raw.get("head_ref")),
            "base": _ref_name(raw.get("base")) or _ref_name(raw.get("base_ref")),
            "draft": raw.get("draft") is True,
        })
    normalized_pulls.sort(key=lambda row: row["number"])

    return {
        "schema": EXPORT_SCHEMA,
        "coverage": {
            "comments_complete": coverage.get("comments_complete") is True,
            "open_issues_complete": coverage.get("open_issues_complete") is True,
            "open_pulls_complete": coverage.get("open_pulls_complete") is True,
            "dispatch_issue": _issue_number(coverage.get("dispatch_issue")) or DEFAULT_DISPATCH_ISSUE,
        },
        "comments": comments,
        "issues": normalized_issues,
        "pulls": normalized_pulls,
        "read_errors": sorted(str(item) for item in read_errors),
    }


def _project_state_summary(project_report: dict[str, Any], status_current: bool) -> dict[str, Any]:
    counts: dict[str, int] = {state: 0 for state in STATES}
    capabilities = []
    capability_blockers = []
    for row in project_report.get("capabilities", []):
        state = row.get("state")
        counts[state] = counts.get(state, 0) + 1
        capabilities.append({"id": row.get("id"), "state": state})
        for limit in row.get("limits", []):
            if limit.get("status") == "PASS":
                capability_blockers.append({
                    "capability": row.get("id"),
                    "id": limit.get("id"),
                    "blocks_state": limit.get("blocks_state"),
                    "message": limit.get("message"),
                })
    capabilities.sort(key=lambda row: str(row.get("id")))
    capability_blockers.sort(key=lambda row: (str(row.get("capability")), str(row.get("id"))))
    return {
        "validation": {
            "schema": project_report.get("schema"),
            "status": project_report.get("status"),
            "errors": list(project_report.get("errors", [])),
            "warnings": list(project_report.get("warnings", [])),
        },
        "status_document": {"path": ".project/STATUS.md", "current": bool(status_current)},
        "state_counts": {key: counts[key] for key in sorted(counts)},
        "capabilities": capabilities,
        "explicit_blockers": capability_blockers,
    }


def _slot_violations(claims_report: dict[str, Any], slot: str) -> list[str]:
    return sorted({
        str(item.get("code")) for item in claims_report.get("violations", [])
        if item.get("slot") == slot and item.get("code")
    })


def _pull_belongs_to_slot(pull: dict[str, Any], slot: str) -> bool:
    head = pull.get("head") or ""
    title = pull.get("title") or ""
    return head.startswith(f"agent-{slot}/") or bool(re.match(rf"^\[{re.escape(slot)}\]", title))


def _explicit_issue_blockers(issue: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [{"kind": "ISSUE_DEPENDENCY", "issue": dep} for dep in issue.get("blocked_by", [])]
    for label in issue.get("labels", []):
        if label.casefold() in BLOCKED_LABELS:
            rows.append({"kind": "BLOCKED_LABEL", "label": label})
    return rows


def _next_safe_action(
    lane_status: str,
    active_issue: int | None,
    branch: str | None,
    typical_issues: list[int],
    open_issue_map: dict[int, dict[str, Any]],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    if lane_status == "CLAIMED" and active_issue is not None:
        return {
            "kind": "CONTINUE_ACTIVE_CLAIM",
            "issue": active_issue,
            "branch": branch,
            "reason": "active claim reconstructed from persistent parallel-claim:v1 events",
        }
    if lane_status != "FREE":
        return {"kind": "UNKNOWN", "reason": "lane is not proven free"}
    if not coverage.get("open_issues_complete"):
        return {"kind": "UNKNOWN", "reason": "open-issue coverage is incomplete"}
    candidates = [number for number in typical_issues if number in open_issue_map]
    ready = [number for number in candidates if open_issue_map[number].get("recovery_ready") is True]
    if ready:
        issue = ready[0]
        return {
            "kind": "CLAIM_OPEN_ISSUE",
            "issue": issue,
            "reason": "open issue is explicitly marked recovery_ready in the supplied persistent export",
        }
    return {
        "kind": "UNKNOWN",
        "candidate_issues": candidates,
        "reason": "no open lane issue is explicitly proven recovery_ready; do not infer readiness",
    }


def build_recovery_state(
    contract: dict[str, Any],
    project_report: dict[str, Any],
    status_current: bool,
    claims_report: dict[str, Any],
    github_export: dict[str, Any],
) -> dict[str, Any]:
    source = normalize_github_export(github_export)
    coverage = source["coverage"]
    open_issues = [row for row in source["issues"] if row["state"] == "OPEN"]
    open_pulls = [row for row in source["pulls"] if row["state"] == "OPEN"]
    issue_map = {row["number"]: row for row in open_issues}
    pull_map = {row["number"]: row for row in open_pulls}

    warnings: list[dict[str, Any]] = []
    if not coverage["comments_complete"]:
        warnings.append({"code": "COMMENTS_COVERAGE_INCOMPLETE", "detail": "absence of a claim cannot prove a lane FREE"})
    if not coverage["open_issues_complete"]:
        warnings.append({"code": "OPEN_ISSUES_COVERAGE_INCOMPLETE", "detail": "next-issue inference is disabled"})
    if not coverage["open_pulls_complete"]:
        warnings.append({"code": "OPEN_PULLS_COVERAGE_INCOMPLETE", "detail": "PR reconciliation may be incomplete"})
    for detail in source["read_errors"]:
        warnings.append({"code": "GITHUB_READ_ERROR", "detail": detail})
    if not status_current:
        warnings.append({"code": "STATUS_DOCUMENT_STALE", "detail": ".project/STATUS.md differs from deterministic project-state rendering"})
    for item in claims_report.get("violations", []):
        warnings.append({
            "code": f"COORDINATION_{item.get('code', 'VIOLATION')}",
            "detail": item.get("detail", "coordination violation"),
            "slot": item.get("slot"),
            "issue": item.get("issue"),
        })

    lanes: dict[str, Any] = {}
    claim_slots = claims_report.get("slots", {})
    for slot in SLOTS:
        contract_lane = contract["lanes"][slot]
        claim_lane = claim_slots.get(slot, {})
        active_issue = _issue_number(claim_lane.get("active_issue"))
        branch = claim_lane.get("branch") if isinstance(claim_lane.get("branch"), str) else None
        violations = _slot_violations(claims_report, slot)
        slot_pulls = [row for row in open_pulls if _pull_belongs_to_slot(row, slot)]
        matching_branch_pulls = [row for row in slot_pulls if branch and row.get("head") == branch]

        if claim_lane.get("status") == "CLAIMED" and claim_lane.get("active_claim_count") == 1:
            lane_status = "CLAIMED"
        elif violations:
            lane_status = "UNKNOWN"
        elif not coverage["comments_complete"]:
            lane_status = "UNKNOWN"
        elif slot_pulls:
            lane_status = "UNKNOWN"
            warnings.append({
                "code": "OPEN_PR_WITHOUT_ACTIVE_CLAIM",
                "slot": slot,
                "detail": "open PR exists for lane but no unique active claim is reconstructed",
                "prs": [row["number"] for row in slot_pulls],
            })
        else:
            lane_status = "FREE"

        pr = _issue_number(claim_lane.get("pr"))
        if pr is None and len(matching_branch_pulls) == 1:
            pr = matching_branch_pulls[0]["number"]
        if pr is not None and coverage["open_pulls_complete"] and pr not in pull_map and lane_status == "CLAIMED":
            warnings.append({
                "code": "CLAIM_PR_NOT_OPEN",
                "slot": slot,
                "issue": active_issue,
                "pr": pr,
                "detail": "active claim references a PR that is not open in the supplied GitHub snapshot",
            })

        relevant_issue_numbers = set(contract_lane.get("typical_issues", []))
        if active_issue is not None:
            relevant_issue_numbers.add(active_issue)
        lane_open_issues = [issue_map[number] for number in sorted(relevant_issue_numbers) if number in issue_map]
        blockers = []
        for issue in lane_open_issues:
            explicit = _explicit_issue_blockers(issue)
            if explicit:
                blockers.append({"issue": issue["number"], "blockers": explicit})

        lanes[slot] = {
            "slot": slot,
            "status": lane_status,
            "conflict_group": contract_lane["conflict_group"],
            "active_issue": active_issue if lane_status == "CLAIMED" else None,
            "branch": branch if lane_status == "CLAIMED" else None,
            "pr": pr if lane_status == "CLAIMED" else None,
            "last_worklog": claim_lane.get("last_worklog"),
            "last_release": claim_lane.get("last_release"),
            "coordination_violations": violations,
            "open_issues": lane_open_issues,
            "open_pulls": slot_pulls,
            "explicit_blockers": blockers,
            "next_safe_action": _next_safe_action(
                lane_status,
                active_issue,
                branch,
                list(contract_lane.get("typical_issues", [])),
                issue_map,
                coverage,
            ),
        }

    project = _project_state_summary(project_report, status_current)
    if project_report.get("status") == "FAIL" or claims_report.get("violations"):
        overall = "FAIL"
    elif warnings or project_report.get("warnings"):
        overall = "WARN"
    else:
        overall = "PASS"

    relevant_issue_numbers = sorted({
        issue["number"] for lane in lanes.values() for issue in lane["open_issues"]
    })
    relevant_pull_numbers = sorted({
        pull["number"] for lane in lanes.values() for pull in lane["open_pulls"]
    })

    return {
        "schema": SCHEMA,
        "status": overall,
        "source_of_truth": {
            "human_dispatch_issue": coverage["dispatch_issue"],
            "capability_manifest": ".project/capabilities.json",
            "lane_contract": ".project/parallel-agents.json",
            "claim_parser": "tools/check_parallel_claims.py",
            "project_state_validator": "tools/validate_project_state.py",
        },
        "coverage": coverage,
        "project_state": project,
        "coordination": {
            "schema": claims_report.get("schema"),
            "active_claims": list(claims_report.get("active_claims", [])),
            "violations": list(claims_report.get("violations", [])),
            "warnings": list(claims_report.get("warnings", [])),
        },
        "github": {
            "relevant_open_issue_numbers": relevant_issue_numbers,
            "relevant_open_pull_numbers": relevant_pull_numbers,
        },
        "lanes": lanes,
        "warnings": sorted(warnings, key=lambda row: (
            str(row.get("code", "")), str(row.get("slot", "")), int(row.get("issue") or -1), str(row.get("detail", ""))
        )),
    }


def validate_recovery_state(snapshot: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(snapshot, dict):
        return ["snapshot must be an object"]
    if snapshot.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA!r}")
    if snapshot.get("status") not in {"PASS", "WARN", "FAIL"}:
        errors.append("status must be PASS, WARN or FAIL")
    lanes = snapshot.get("lanes")
    if not isinstance(lanes, dict) or set(lanes) != set(SLOTS):
        errors.append("lanes must contain exactly A-H")
    else:
        for slot in SLOTS:
            row = lanes[slot]
            if not isinstance(row, dict):
                errors.append(f"lane {slot} must be an object")
                continue
            if row.get("status") not in {"CLAIMED", "FREE", "UNKNOWN"}:
                errors.append(f"lane {slot} has invalid recovery status")
            if row.get("status") == "CLAIMED" and (not row.get("active_issue") or not row.get("branch")):
                errors.append(f"lane {slot} CLAIMED requires active_issue and branch")
            if row.get("status") == "FREE" and (row.get("active_issue") is not None or row.get("branch") is not None):
                errors.append(f"lane {slot} FREE cannot expose active issue/branch")
    return errors


def render_human(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Recovery State",
        "",
        f"Project recovery status: {snapshot['status']}",
        f"Capability validation: {snapshot['project_state']['validation']['status']}",
        f"STATUS.md current: {'yes' if snapshot['project_state']['status_document']['current'] else 'no'}",
        "",
        "## Lanes",
        "",
    ]
    for slot in SLOTS:
        lane = snapshot["lanes"][slot]
        if lane["status"] == "CLAIMED":
            pr = f" PR #{lane['pr']}" if lane.get("pr") else ""
            lines.append(f"- {slot} CLAIMED #{lane['active_issue']} {lane['branch']}{pr} [{lane['conflict_group']}]")
        else:
            lines.append(f"- {slot} {lane['status']} [{lane['conflict_group']}] — {lane['next_safe_action']['kind']}")
    lines.extend(["", "## Warnings", ""])
    if snapshot["warnings"]:
        for row in snapshot["warnings"]:
            locus = f" lane={row['slot']}" if row.get("slot") else ""
            lines.append(f"- {row['code']}{locus}: {row['detail']}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def compare_snapshot_file(path: Path, expected: str) -> tuple[bool, str]:
    if not path.is_file():
        return False, f"missing recovery snapshot: {path}"
    actual = path.read_text(encoding="utf-8")
    if actual == expected:
        return True, ""
    diff = "".join(difflib.unified_diff(
        actual.splitlines(keepends=True), expected.splitlines(keepends=True),
        fromfile=str(path), tofile="generated-recovery-state",
    ))
    return False, diff or "recovery snapshot differs"


def build_snapshot(root: Path, github_export: dict[str, Any], contract_path: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    contract = load_contract((contract_path or root / ".project/parallel-agents.json").resolve())
    manifest = load_project_json(root / ".project/capabilities.json")
    project_report = validate_manifest(manifest, root)
    rendered_status = render_status(manifest, project_report)
    status_current, _ = compare_status_file(root / ".project/STATUS.md", rendered_status)
    normalized = normalize_github_export(github_export)
    claims_report = analyze_comments(normalized["comments"], contract)
    snapshot = build_recovery_state(contract, project_report, status_current, claims_report, normalized)
    errors = validate_recovery_state(snapshot)
    if errors:
        raise ValueError("invalid generated recovery state: " + "; ".join(errors))
    return snapshot


def _github_token_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "poker-engine-recovery-state",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_get_pages(repo: str, resource: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("--repo must use owner/name form")
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        query = dict(params)
        query.update({"per_page": 100, "page": page})
        url = f"https://api.github.com/repos/{repo}/{resource}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(url, headers=_github_token_headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ValueError(f"GitHub read failed for {resource}: {exc}") from exc
        if not isinstance(payload, list):
            raise ValueError(f"GitHub {resource} endpoint returned a non-list payload")
        rows.extend(item for item in payload if isinstance(item, dict))
        if len(payload) < 100:
            break
        page += 1
    return rows


def fetch_live_github_export(repo: str, contract: dict[str, Any], dispatch_issue: int = DEFAULT_DISPATCH_ISSUE) -> dict[str, Any]:
    raw_issues = _github_get_pages(repo, "issues", {"state": "open"})
    raw_pulls = _github_get_pages(repo, "pulls", {"state": "open"})
    issues = [row for row in raw_issues if "pull_request" not in row]
    issue_numbers = {dispatch_issue}
    issue_numbers.update(_issue_number(row.get("number")) for row in issues)
    for lane in contract["lanes"].values():
        issue_numbers.update(_issue_number(number) for number in lane.get("typical_issues", []))
    issue_numbers.discard(None)

    comments: list[dict[str, Any]] = []
    read_errors: list[str] = []
    comments_complete = True
    for number in sorted(issue_numbers):
        try:
            comments.extend(fetch_github_comments(repo, int(number)))
        except ValueError as exc:
            comments_complete = False
            read_errors.append(f"issue #{number} comments: {exc}")

    return normalize_github_export({
        "schema": EXPORT_SCHEMA,
        "coverage": {
            "comments_complete": comments_complete,
            "open_issues_complete": True,
            "open_pulls_complete": True,
            "dispatch_issue": dispatch_issue,
        },
        "comments": comments,
        "issues": issues,
        "pulls": raw_pulls,
        "read_errors": read_errors,
    })


def load_github_export(path: Path) -> dict[str, Any]:
    try:
        return normalize_github_export(json.loads(path.read_text(encoding="utf-8")))
    except OSError as exc:
        raise ValueError(f"cannot read GitHub recovery export {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid GitHub recovery export {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic project recovery state from persistent evidence.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--github-export", type=Path)
    source.add_argument("--repo")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--render", action="store_true")
    modes.add_argument("--human", action="store_true")
    modes.add_argument("--check", type=Path)
    modes.add_argument("--write", type=Path)
    parser.add_argument("--dispatch-issue", type=int, default=DEFAULT_DISPATCH_ISSUE)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--contract", type=Path, default=None)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    try:
        contract_path = (args.contract or root / ".project/parallel-agents.json").resolve()
        contract = load_contract(contract_path)
        export = load_github_export(args.github_export) if args.github_export else fetch_live_github_export(
            args.repo, contract, args.dispatch_issue
        )
        snapshot = build_snapshot(root, export, contract_path)
        rendered = stable_json(snapshot)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"RECOVERY_STATE_ERROR: {exc}", file=sys.stderr)
        return 2

    if args.human:
        print(render_human(snapshot), end="")
        return 1 if snapshot["status"] == "FAIL" else 0
    if args.check:
        current, detail = compare_snapshot_file(args.check, rendered)
        if not current:
            print(f"RECOVERY_STATE_STALE: {args.check}")
            if detail:
                print(detail, end="" if detail.endswith("\n") else "\n")
            return 1
        print(f"RECOVERY_STATE_OK: {args.check}")
        return 1 if snapshot["status"] == "FAIL" else 0
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(rendered, encoding="utf-8")
        print(f"RECOVERY_STATE_WRITTEN: {args.write}")
        return 1 if snapshot["status"] == "FAIL" else 0

    print(rendered, end="")
    return 1 if snapshot["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
