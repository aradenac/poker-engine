#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_recovery_state import (
    DEFAULT_DISPATCH_ISSUE,
    _github_get_pages,
    build_snapshot,
    fetch_live_github_export,
    normalize_github_export,
)
from tools.check_parallel_claims import (
    _bullet_block,
    _scalar,
    analyze_comments,
    parse_events,
)
from tools.check_parallel_scope import SLOTS, load_contract
from tools.validate_project_state import STATES, load_json as load_project_json, validate_manifest

SCHEMA = "poker-backlog-evidence-report/v1"
EXPORT_SCHEMA = "poker-backlog-evidence-github-export/v1"
CATEGORIES = ("CLOSE_CANDIDATE", "KEEP_OPEN", "BLOCKED", "CONTRADICTION", "UNKNOWN")
CATEGORY_PRIORITY = {
    "UNKNOWN": 0,
    "KEEP_OPEN": 1,
    "BLOCKED": 2,
    "CLOSE_CANDIDATE": 3,
    "CONTRADICTION": 4,
}
BLOCKED_LABELS = {"blocked", "blocker", "blocked-by-dependency", "blocked by dependency"}
NONE_GAP_PREFIXES = ("none", "aucun", "aucune", "no remaining", "nothing remaining")
BLOCKED_GAP_TOKENS = ("blocked", "deferred", "bloqué", "bloquee", "bloquée", "différé", "differee", "différée")


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


def normalize_audit_export(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("backlog/evidence GitHub export must be a JSON object")
    schema = value.get("schema")
    if schema not in {None, EXPORT_SCHEMA}:
        raise ValueError(f"unsupported backlog/evidence export schema: {schema!r}")

    comments = value.get("comments", [])
    issues = value.get("issues", [])
    pulls = value.get("pulls", value.get("prs", []))
    branches = value.get("branches", [])
    coverage = value.get("coverage", {})
    read_errors = value.get("read_errors", [])
    if not all(isinstance(rows, list) for rows in (comments, issues, pulls, branches, read_errors)):
        raise ValueError("comments/issues/pulls/branches/read_errors must be lists")
    if not isinstance(coverage, dict):
        raise ValueError("coverage must be an object")

    normalized_issues: list[dict[str, Any]] = []
    for raw in issues:
        if not isinstance(raw, dict):
            raise ValueError("each issue row must be an object")
        number = _issue_number(raw.get("number", raw.get("issue_number")))
        if number is None:
            raise ValueError("each issue row requires a positive number")
        blocked_by = []
        if isinstance(raw.get("blocked_by"), list):
            blocked_by = sorted({n for item in raw["blocked_by"] if (n := _issue_number(item)) is not None})
        normalized_issues.append({
            "number": number,
            "state": str(raw.get("state", "UNKNOWN")).upper(),
            "title": raw.get("title") if isinstance(raw.get("title"), str) else "",
            "body": raw.get("body") if isinstance(raw.get("body"), str) else "",
            "labels": _labels(raw.get("labels")),
            "blocked_by": blocked_by,
        })
    normalized_issues.sort(key=lambda row: row["number"])

    normalized_pulls: list[dict[str, Any]] = []
    for raw in pulls:
        if not isinstance(raw, dict):
            raise ValueError("each pull row must be an object")
        number = _issue_number(raw.get("number", raw.get("pr_number")))
        if number is None:
            raise ValueError("each pull row requires a positive number")
        normalized_pulls.append({
            "number": number,
            "state": str(raw.get("state", "UNKNOWN")).upper(),
            "merged": raw.get("merged") is True or bool(raw.get("merged_at")),
            "title": raw.get("title") if isinstance(raw.get("title"), str) else "",
            "body": raw.get("body") if isinstance(raw.get("body"), str) else "",
            "head": _ref_name(raw.get("head")) or _ref_name(raw.get("head_ref")),
            "base": _ref_name(raw.get("base")) or _ref_name(raw.get("base_ref")),
        })
    normalized_pulls.sort(key=lambda row: row["number"])

    branch_names: list[str] = []
    for raw in branches:
        name = raw if isinstance(raw, str) else raw.get("name") if isinstance(raw, dict) else None
        if isinstance(name, str) and name.strip():
            branch_names.append(name.strip())

    return {
        "schema": EXPORT_SCHEMA,
        "coverage": {
            "comments_complete": coverage.get("comments_complete") is True,
            "issues_complete": coverage.get("issues_complete") is True,
            "pulls_complete": coverage.get("pulls_complete") is True,
            "branches_complete": coverage.get("branches_complete") is True,
            "dispatch_issue": _issue_number(coverage.get("dispatch_issue")) or DEFAULT_DISPATCH_ISSUE,
        },
        "comments": comments,
        "issues": normalized_issues,
        "pulls": normalized_pulls,
        "branches": sorted(set(branch_names)),
        "read_errors": sorted(str(item) for item in read_errors),
    }


def fetch_live_audit_export(repo: str, contract: dict[str, Any], dispatch_issue: int = DEFAULT_DISPATCH_ISSUE) -> dict[str, Any]:
    recovery = fetch_live_github_export(repo, contract, dispatch_issue)
    read_errors = list(recovery.get("read_errors", []))
    coverage = {
        "comments_complete": recovery["coverage"]["comments_complete"],
        "issues_complete": False,
        "pulls_complete": False,
        "branches_complete": False,
        "dispatch_issue": dispatch_issue,
    }
    issues: list[dict[str, Any]] = []
    pulls: list[dict[str, Any]] = []
    branches: list[dict[str, Any]] = []
    try:
        issues = [row for row in _github_get_pages(repo, "issues", {"state": "all"}) if "pull_request" not in row]
        coverage["issues_complete"] = True
    except ValueError as exc:
        read_errors.append(f"issues: {exc}")
    try:
        pulls = _github_get_pages(repo, "pulls", {"state": "all"})
        coverage["pulls_complete"] = True
    except ValueError as exc:
        read_errors.append(f"pulls: {exc}")
    try:
        branches = _github_get_pages(repo, "branches", {})
        coverage["branches_complete"] = True
    except ValueError as exc:
        read_errors.append(f"branches: {exc}")
    return normalize_audit_export({
        "schema": EXPORT_SCHEMA,
        "coverage": coverage,
        "comments": recovery["comments"],
        "issues": issues,
        "pulls": pulls,
        "branches": branches,
        "read_errors": read_errors,
    })


def _recovery_export(source: dict[str, Any]) -> dict[str, Any]:
    coverage = source["coverage"]
    return normalize_github_export({
        "coverage": {
            "comments_complete": coverage["comments_complete"],
            "open_issues_complete": coverage["issues_complete"],
            "open_pulls_complete": coverage["pulls_complete"],
            "dispatch_issue": coverage["dispatch_issue"],
        },
        "comments": source["comments"],
        "issues": [row for row in source["issues"] if row["state"] == "OPEN"],
        "pulls": [row for row in source["pulls"] if row["state"] == "OPEN"],
        "read_errors": source["read_errors"],
    })


def _worklog_gap_state(event: dict[str, Any] | None) -> dict[str, Any]:
    if not event:
        return {"state": "UNKNOWN", "items": []}
    lines = str(event.get("body") or "").splitlines()
    items = _bullet_block(lines, "REMAINING_GAPS")
    if not items:
        scalar = _scalar(lines, "REMAINING_GAPS")
        if scalar:
            items = [scalar]
    cleaned = [item.strip() for item in items if item.strip()]
    if not cleaned:
        return {"state": "UNKNOWN", "items": []}
    lowered = [re.sub(r"^[^a-z0-9à-ÿ]+", "", item.casefold()) for item in cleaned]
    if all(any(item.startswith(prefix) for prefix in NONE_GAP_PREFIXES) for item in lowered):
        return {"state": "NONE", "items": cleaned}
    if all(any(token in item for token in BLOCKED_GAP_TOKENS) for item in lowered):
        return {"state": "BLOCKED", "items": cleaned}
    return {"state": "ACTIVE", "items": cleaned}


def _explicit_issue_blockers(issue: dict[str, Any]) -> list[dict[str, Any]]:
    blockers = [{"kind": "ISSUE_DEPENDENCY", "issue": number} for number in issue.get("blocked_by", [])]
    for label in issue.get("labels", []):
        if label.casefold() in BLOCKED_LABELS:
            blockers.append({"kind": "BLOCKED_LABEL", "label": label})
    return blockers


def _source_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("kind", "")), stable_json(row)


def _add_finding(
    findings: dict[tuple[str, str], dict[str, Any]],
    subject: dict[str, Any],
    category: str,
    code: str,
    justification: str,
    source_refs: list[dict[str, Any]],
) -> None:
    if category not in CATEGORIES:
        raise ValueError(f"invalid finding category {category}")
    key = (subject["kind"], str(subject.get("issue", subject.get("slot", ""))))
    row = findings.get(key)
    if row is None:
        row = {
            "subject": dict(subject),
            "category": category,
            "codes": [],
            "justification": [],
            "source_refs": [],
        }
        findings[key] = row
    if CATEGORY_PRIORITY[category] > CATEGORY_PRIORITY[row["category"]]:
        row["category"] = category
    if code not in row["codes"]:
        row["codes"].append(code)
    if justification not in row["justification"]:
        row["justification"].append(justification)
    existing = {stable_json(ref) for ref in row["source_refs"]}
    for ref in source_refs:
        marker = stable_json(ref)
        if marker not in existing:
            row["source_refs"].append(ref)
            existing.add(marker)


def _capability_admin_rows(manifest: dict[str, Any], project_report: dict[str, Any]) -> list[dict[str, Any]]:
    proven = {row.get("id"): row.get("state") for row in project_report.get("capabilities", [])}
    rows = []
    for capability in manifest.get("capabilities", []):
        admin = capability.get("administrative")
        if not isinstance(admin, dict):
            continue
        issue = _issue_number(admin.get("issue"))
        claimed = admin.get("claimed_state")
        if issue is None or claimed not in STATES:
            continue
        rows.append({
            "issue": issue,
            "capability": capability.get("id"),
            "state": proven.get(capability.get("id"), capability.get("state")),
            "claimed_state": claimed,
            "declared_status": str(admin.get("status", "")).upper() or None,
            "successor_issue": _issue_number(admin.get("successor_issue")),
            "known_mismatch_reason": admin.get("known_mismatch_reason"),
        })
    return sorted(rows, key=lambda row: (row["issue"], str(row["capability"])))


def build_backlog_report(
    contract: dict[str, Any],
    manifest: dict[str, Any],
    project_report: dict[str, Any],
    claims_report: dict[str, Any],
    recovery_state: dict[str, Any],
    github_export: dict[str, Any],
) -> dict[str, Any]:
    source = normalize_audit_export(github_export)
    coverage = source["coverage"]
    issue_map = {row["number"]: row for row in source["issues"]}
    pull_map = {row["number"]: row for row in source["pulls"]}
    branches = set(source["branches"])
    events = parse_events(source["comments"])
    worklogs: dict[int, dict[str, Any]] = {}
    releases: dict[int, dict[str, Any]] = {}
    for event in events:
        issue = event.get("issue")
        if issue is None:
            continue
        if event["kind"] == "worklog":
            worklogs[issue] = event
        elif event["kind"] == "claim" and event.get("status") == "RELEASED":
            releases[issue] = event

    findings: dict[tuple[str, str], dict[str, Any]] = {}
    state_index = {state: index for index, state in enumerate(STATES)}

    # Capability/admin reconciliation is the only place where a closed issue can be
    # compared to a declared delivery state without interpreting prose DoD.
    for row in _capability_admin_rows(manifest, project_report):
        issue = issue_map.get(row["issue"])
        refs = [
            {"kind": "capability", "id": row["capability"], "path": ".project/capabilities.json", "state": row["state"], "claimed_state": row["claimed_state"]},
            {"kind": "issue", "issue": row["issue"], "state": issue.get("state") if issue else row["declared_status"]},
        ]
        actual_rank = state_index.get(row["state"], -1)
        claimed_rank = state_index.get(row["claimed_state"], len(STATES))
        live_state = issue.get("state") if issue else row["declared_status"]
        if live_state == "CLOSED" and actual_rank < claimed_rank:
            _add_finding(
                findings, {"kind": "ISSUE", "issue": row["issue"]}, "CONTRADICTION",
                "CLOSED_BELOW_DECLARED_CAPABILITY_STATE",
                f"issue is CLOSED but capability {row['capability']} is {row['state']}, below declared {row['claimed_state']}",
                refs,
            )
        elif live_state == "OPEN" and actual_rank >= claimed_rank:
            _add_finding(
                findings, {"kind": "ISSUE", "issue": row["issue"]}, "CLOSE_CANDIDATE",
                "OPEN_CAPABILITY_EVIDENCE_SATISFIED",
                f"versioned capability evidence reaches declared {row['claimed_state']}",
                refs,
            )
        elif live_state == "OPEN" and actual_rank < claimed_rank:
            _add_finding(
                findings, {"kind": "ISSUE", "issue": row["issue"]}, "KEEP_OPEN",
                "OPEN_CAPABILITY_EVIDENCE_INCOMPLETE",
                f"capability {row['capability']} remains {row['state']} below declared {row['claimed_state']}",
                refs,
            )

    active_by_issue = {claim["issue"]: claim for claim in claims_report.get("active_claims", []) if claim.get("issue")}
    for issue_number, claim in sorted(active_by_issue.items()):
        issue = issue_map.get(issue_number)
        slot = claim.get("slot")
        refs = [
            {"kind": "claim", "issue": issue_number, "slot": slot, "comment_id": claim.get("claimed_comment_id"), "branch": claim.get("branch"), "pr": claim.get("pr")},
            {"kind": "recovery_lane", "slot": slot, "status": recovery_state.get("lanes", {}).get(slot, {}).get("status"), "issue": recovery_state.get("lanes", {}).get(slot, {}).get("active_issue")},
            {"kind": "dispatch_issue", "issue": coverage["dispatch_issue"]},
        ]
        contradictions: list[str] = []
        if coverage["issues_complete"] and (issue is None or issue.get("state") != "OPEN"):
            contradictions.append("active claim references an issue that is not OPEN in the complete issue export")
        branch = claim.get("branch")
        if coverage["branches_complete"] and branch and branch not in branches:
            contradictions.append(f"active claim branch {branch!r} is absent from the complete branch export")
        pr_number = _issue_number(claim.get("pr"))
        if coverage["pulls_complete"] and pr_number is not None:
            pull = pull_map.get(pr_number)
            if pull is None or pull.get("state") != "OPEN":
                contradictions.append(f"active claim PR #{pr_number} is not OPEN in the complete PR export")
        recovery_lane = recovery_state.get("lanes", {}).get(slot, {})
        if recovery_lane.get("status") != "CLAIMED" or recovery_lane.get("active_issue") != issue_number:
            contradictions.append("claim parser and recovery-state lane disagree on the active issue")
        latest_release = releases.get(issue_number)
        if latest_release and int(latest_release.get("order") or 0) > int(claim.get("claimed_order") or 0):
            contradictions.append("a RELEASED event exists after the claim still reported active")
        if contradictions:
            for detail in contradictions:
                _add_finding(
                    findings, {"kind": "ISSUE", "issue": issue_number}, "CONTRADICTION",
                    "ACTIVE_CLAIM_RECONCILIATION_FAILED", detail, refs,
                )
        else:
            _add_finding(
                findings, {"kind": "ISSUE", "issue": issue_number}, "KEEP_OPEN",
                "ACTIVE_CLAIM", f"lane {slot} has a valid active claim", refs,
            )

    # Translate recovery-state coordination warnings into explicit reconciliation findings.
    for warning in recovery_state.get("warnings", []):
        code = str(warning.get("code") or "")
        if code not in {"OPEN_PR_WITHOUT_ACTIVE_CLAIM", "CLAIM_PR_NOT_OPEN"} and not code.startswith("COORDINATION_"):
            continue
        slot = warning.get("slot")
        subject = {"kind": "LANE", "slot": slot} if slot in SLOTS else {"kind": "LANE", "slot": "UNKNOWN"}
        _add_finding(
            findings, subject, "CONTRADICTION", f"RECOVERY_{code}",
            str(warning.get("detail") or "recovery-state coordination warning"),
            [{"kind": "recovery_warning", **{k: v for k, v in warning.items() if k in {"code", "slot", "issue", "pr", "prs", "detail"}}},
             {"kind": "dispatch_issue", "issue": coverage["dispatch_issue"]}],
        )

    # Open backlog issue reconciliation from persistent worklog/release/PR evidence.
    for issue_number, issue in sorted(issue_map.items()):
        if issue["state"] != "OPEN":
            continue
        release = releases.get(issue_number)
        worklog = worklogs.get(issue_number)
        gap = _worklog_gap_state(worklog)
        blockers = _explicit_issue_blockers(issue)
        refs = [{"kind": "issue", "issue": issue_number, "state": "OPEN"}]
        if worklog:
            refs.append({"kind": "worklog", "issue": issue_number, "comment_id": worklog.get("comment_id"), "remaining_gaps": gap})
        if release:
            refs.append({"kind": "release", "issue": issue_number, "comment_id": release.get("comment_id"), "pr": release.get("pr")})
        if blockers:
            refs.extend({"kind": "blocker", **row} for row in blockers)

        if issue_number in active_by_issue:
            continue

        release_pr = _issue_number(release.get("pr")) if release else None
        if release_pr is None and worklog:
            release_pr = _issue_number(worklog.get("pr"))
        pull = pull_map.get(release_pr) if release_pr is not None else None
        if pull:
            refs.append({"kind": "pr", "pr": release_pr, "state": pull["state"], "merged": pull["merged"]})

        if release and pull and pull["merged"]:
            if gap["state"] == "NONE":
                _add_finding(
                    findings, {"kind": "ISSUE", "issue": issue_number}, "CLOSE_CANDIDATE",
                    "MERGED_RELEASED_NO_REMAINING_GAP",
                    f"PR #{release_pr} is merged, RELEASED is persisted and latest worklog declares no remaining gap",
                    refs,
                )
                continue
            if gap["state"] == "BLOCKED":
                _add_finding(
                    findings, {"kind": "ISSUE", "issue": issue_number}, "BLOCKED",
                    "MERGED_RELEASED_ONLY_DEFERRED_GAPS",
                    "delivered tranche is RELEASED but every declared remaining gap is explicitly BLOCKED/DEFERRED",
                    refs,
                )
                continue
            if gap["state"] == "ACTIVE":
                _add_finding(
                    findings, {"kind": "ISSUE", "issue": issue_number}, "KEEP_OPEN",
                    "MERGED_RELEASED_WITH_ACTIVE_GAPS",
                    "latest worklog still declares an actionable remaining gap",
                    refs,
                )
                continue
            _add_finding(
                findings, {"kind": "ISSUE", "issue": issue_number}, "UNKNOWN",
                "MERGED_RELEASED_GAPS_UNKNOWN",
                "merged RELEASED evidence exists but remaining-gap state is not explicitly machine-readable",
                refs,
            )
            continue

        if blockers or gap["state"] == "BLOCKED":
            _add_finding(
                findings, {"kind": "ISSUE", "issue": issue_number}, "BLOCKED",
                "OPEN_ISSUE_EXPLICITLY_BLOCKED",
                "all machine-readable remaining blocker evidence is explicit; no readiness is inferred",
                refs,
            )
        elif gap["state"] == "ACTIVE":
            _add_finding(
                findings, {"kind": "ISSUE", "issue": issue_number}, "KEEP_OPEN",
                "OPEN_ISSUE_ACTIVE_GAPS",
                "latest worklog declares an actionable remaining gap",
                refs,
            )
        elif ("ISSUE", str(issue_number)) not in findings:
            _add_finding(
                findings, {"kind": "ISSUE", "issue": issue_number}, "UNKNOWN",
                "OPEN_ISSUE_INSUFFICIENT_MACHINE_EVIDENCE",
                "no positive machine-verifiable close/block/active-gap conclusion is proven",
                refs,
            )

    # Coverage failures never become positive suggestions.
    warnings: list[dict[str, Any]] = []
    for key in ("comments_complete", "issues_complete", "pulls_complete", "branches_complete"):
        if not coverage[key]:
            warnings.append({"code": f"{key.upper()}_FALSE", "detail": f"{key} is false; affected conclusions remain conservative"})
    for detail in source["read_errors"]:
        warnings.append({"code": "GITHUB_READ_ERROR", "detail": detail})

    rows = list(findings.values())
    for row in rows:
        row["codes"].sort()
        row["justification"].sort()
        row["source_refs"].sort(key=_source_key)
    rows.sort(key=lambda row: (
        row["subject"]["kind"],
        int(row["subject"].get("issue") or 10**9),
        str(row["subject"].get("slot") or ""),
    ))
    counts = {category: sum(1 for row in rows if row["category"] == category) for category in CATEGORIES}
    status = "WARN" if counts["CONTRADICTION"] or counts["UNKNOWN"] or warnings else "PASS"

    return {
        "schema": SCHEMA,
        "status": status,
        "source_of_truth": {
            "human_dispatch_issue": coverage["dispatch_issue"],
            "capability_manifest": ".project/capabilities.json",
            "project_state_validator": "tools/validate_project_state.py",
            "claim_parser": "tools/check_parallel_claims.py",
            "recovery_builder": "tools/build_recovery_state.py",
        },
        "coverage": coverage,
        "counts": counts,
        "findings": rows,
        "warnings": sorted(warnings, key=lambda row: (row["code"], row["detail"])),
        "policy": {
            "github_mutation": False,
            "automatic_close_reopen_merge": False,
            "missing_proof": "UNKNOWN",
        },
    }


def validate_report(report: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["report must be an object"]
    if report.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if report.get("status") not in {"PASS", "WARN"}:
        errors.append("status must be PASS or WARN")
    findings = report.get("findings")
    if not isinstance(findings, list):
        errors.append("findings must be a list")
    else:
        for index, row in enumerate(findings):
            if not isinstance(row, dict):
                errors.append(f"finding {index} must be an object")
                continue
            if row.get("category") not in CATEGORIES:
                errors.append(f"finding {index} has invalid category")
            subject = row.get("subject")
            if not isinstance(subject, dict) or subject.get("kind") not in {"ISSUE", "LANE"}:
                errors.append(f"finding {index} has invalid subject")
    return errors


def build_report(root: Path, github_export: dict[str, Any], contract_path: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    contract_path = (contract_path or root / ".project/parallel-agents.json").resolve()
    contract = load_contract(contract_path)
    source = normalize_audit_export(github_export)
    manifest = load_project_json(root / ".project/capabilities.json")
    project_report = validate_manifest(manifest, root)
    claims_report = analyze_comments(source["comments"], contract)
    recovery_state = build_snapshot(root, _recovery_export(source), contract_path)
    report = build_backlog_report(contract, manifest, project_report, claims_report, recovery_state, source)
    errors = validate_report(report)
    if errors:
        raise ValueError("invalid backlog/evidence report: " + "; ".join(errors))
    return report


def render_human(report: dict[str, Any]) -> str:
    lines = [
        "# Backlog / Evidence Reconciliation",
        "",
        f"Status: {report['status']}",
        " ".join(f"{category}={report['counts'][category]}" for category in CATEGORIES),
        "",
    ]
    for row in report["findings"]:
        subject = row["subject"]
        label = f"#{subject['issue']}" if subject["kind"] == "ISSUE" else f"lane {subject['slot']}"
        lines.append(f"- {row['category']} {label}: {'; '.join(row['justification'])}")
    if report["warnings"]:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {row['code']}: {row['detail']}" for row in report["warnings"])
    return "\n".join(lines) + "\n"


def compare_report_file(path: Path, expected: str) -> tuple[bool, str]:
    if not path.is_file():
        return False, f"missing backlog/evidence report: {path}"
    actual = path.read_text(encoding="utf-8")
    if actual == expected:
        return True, ""
    diff = "".join(difflib.unified_diff(
        actual.splitlines(keepends=True), expected.splitlines(keepends=True),
        fromfile=str(path), tofile="generated-backlog-evidence-report",
    ))
    return False, diff or "backlog/evidence report differs"


def load_audit_export(path: Path) -> dict[str, Any]:
    try:
        return normalize_audit_export(json.loads(path.read_text(encoding="utf-8")))
    except OSError as exc:
        raise ValueError(f"cannot read backlog/evidence export {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid backlog/evidence export {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit backlog status against versioned capability/evidence and read-only GitHub state.")
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
        source_value = load_audit_export(args.github_export) if args.github_export else fetch_live_audit_export(
            args.repo, contract, args.dispatch_issue
        )
        report = build_report(root, source_value, contract_path)
        rendered = stable_json(report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BACKLOG_EVIDENCE_ERROR: {exc}", file=sys.stderr)
        return 2

    if args.human:
        print(render_human(report), end="")
        return 0
    if args.check:
        current, detail = compare_report_file(args.check, rendered)
        if not current:
            print(f"BACKLOG_EVIDENCE_STALE: {args.check}")
            if detail:
                print(detail, end="" if detail.endswith("\n") else "\n")
            return 1
        print(f"BACKLOG_EVIDENCE_OK: {args.check}")
        return 0
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(rendered, encoding="utf-8")
        print(f"BACKLOG_EVIDENCE_WRITTEN: {args.write}")
        return 0

    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
