#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.build_recovery_state as recovery_module
from tools.build_recovery_state import normalize_github_export
from tools.check_parallel_claims import analyze_comments, fetch_github_comments
from tools.check_parallel_scope import SLOTS, load_contract
from tools.validate_project_state import STATE_RANK, load_json as load_project_json, validate_manifest

MANIFEST_SCHEMA = "poker-backlog-evidence/v1"
REPORT_SCHEMA = "poker-backlog-evidence-report/v1"
EXPORT_SCHEMA = "poker-backlog-evidence-github-export/v1"
CATEGORIES = {"CLOSE_CANDIDATE", "KEEP_OPEN", "BLOCKED", "CONTRADICTION", "UNKNOWN"}
BLOCKING_GAP_STATUSES = {"BLOCKED", "DEFERRED"}
OPEN_GAP_STATUSES = {"OPEN", "IN_PROGRESS"}


def stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _issue_number(value: Any) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str):
        value = value.strip().lstrip("#")
        if value.isdigit() and int(value) > 0:
            return int(value)
    return None


def load_manifest(path: Path) -> dict[str, Any]:
    value = load_project_json(path)
    if value.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"manifest.schema must be {MANIFEST_SCHEMA!r}")
    rows = value.get("issues")
    if not isinstance(rows, list):
        raise ValueError("manifest.issues must be a list")
    seen: set[int] = set()
    normalized: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("every backlog issue declaration must be an object")
        issue = _issue_number(raw.get("issue"))
        if issue is None or issue in seen:
            raise ValueError("each backlog issue declaration requires a unique positive issue number")
        seen.add(issue)
        expected = raw.get("expected_state")
        if expected is not None and expected not in STATE_RANK:
            raise ValueError(f"issue #{issue}: invalid expected_state {expected!r}")
        capability = raw.get("capability_id")
        if capability is not None and (not isinstance(capability, str) or not capability):
            raise ValueError(f"issue #{issue}: capability_id must be non-empty when present")
        refs = raw.get("source_refs", [])
        if not isinstance(refs, list) or not all(isinstance(item, str) and item for item in refs):
            raise ValueError(f"issue #{issue}: source_refs must be a list of strings")
        gaps = raw.get("gaps", [])
        if not isinstance(gaps, list):
            raise ValueError(f"issue #{issue}: gaps must be a list")
        normalized_gaps = []
        for gap in gaps:
            if not isinstance(gap, dict):
                raise ValueError(f"issue #{issue}: every gap must be an object")
            gap_id = gap.get("id")
            status = str(gap.get("status", "")).upper()
            source_ref = gap.get("source_ref")
            detail = gap.get("detail")
            if not isinstance(gap_id, str) or not gap_id:
                raise ValueError(f"issue #{issue}: gap id must be non-empty")
            if status not in BLOCKING_GAP_STATUSES | OPEN_GAP_STATUSES:
                raise ValueError(f"issue #{issue}: unsupported gap status {status!r}")
            if not isinstance(source_ref, str) or not source_ref:
                raise ValueError(f"issue #{issue}: gap source_ref must be non-empty")
            if not isinstance(detail, str) or not detail:
                raise ValueError(f"issue #{issue}: gap detail must be non-empty")
            normalized_gaps.append({"id": gap_id, "status": status, "source_ref": source_ref, "detail": detail})
        normalized.append({
            "issue": issue,
            "capability_id": capability,
            "expected_state": expected,
            "source_refs": sorted(set(refs)),
            "gaps": sorted(normalized_gaps, key=lambda item: item["id"]),
        })
    normalized.sort(key=lambda row: row["issue"])
    return {"schema": MANIFEST_SCHEMA, "issues": normalized}


def normalize_backlog_export(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("backlog GitHub export must be an object")
    schema = value.get("schema")
    if schema not in {None, EXPORT_SCHEMA}:
        raise ValueError(f"unsupported GitHub export schema: {schema!r}")
    coverage = value.get("coverage", {})
    if not isinstance(coverage, dict):
        raise ValueError("coverage must be an object")
    branches_raw = value.get("branches", [])
    if not isinstance(branches_raw, list):
        raise ValueError("branches must be a list")
    branches = []
    for item in branches_raw:
        if isinstance(item, str) and item.strip():
            branches.append(item.strip())
        elif isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip():
            branches.append(item["name"].strip())
        else:
            raise ValueError("branch rows must be names or objects with name")

    pulls = []
    for raw in value.get("pulls", value.get("prs", [])):
        if not isinstance(raw, dict):
            raise ValueError("pull rows must be objects")
        item = dict(raw)
        if item.get("merged_at") or item.get("merged") is True:
            item["state"] = "MERGED"
        pulls.append(item)

    normalized = normalize_github_export({
        "schema": recovery_module.EXPORT_SCHEMA,
        "coverage": {
            "comments_complete": coverage.get("comments_complete") is True,
            "open_issues_complete": coverage.get("all_issues_complete") is True,
            "open_pulls_complete": coverage.get("all_pulls_complete") is True,
            "dispatch_issue": coverage.get("dispatch_issue", 225),
        },
        "comments": value.get("comments", []),
        "issues": value.get("issues", []),
        "pulls": pulls,
        "read_errors": value.get("read_errors", []),
    })
    return {
        "schema": EXPORT_SCHEMA,
        "coverage": {
            "comments_complete": normalized["coverage"]["comments_complete"],
            "all_issues_complete": coverage.get("all_issues_complete") is True,
            "all_pulls_complete": coverage.get("all_pulls_complete") is True,
            "branches_complete": coverage.get("branches_complete") is True,
            "dispatch_issue": normalized["coverage"]["dispatch_issue"],
        },
        "comments": normalized["comments"],
        "issues": normalized["issues"],
        "pulls": normalized["pulls"],
        "branches": sorted(set(branches)),
        "read_errors": normalized["read_errors"],
    }


def _relations(manifest: dict[str, Any], capability_manifest: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result = {row["issue"]: dict(row) for row in manifest["issues"]}
    for capability in capability_manifest.get("capabilities", []):
        if not isinstance(capability, dict):
            continue
        administrative = capability.get("administrative")
        if not isinstance(administrative, dict):
            continue
        issue = _issue_number(administrative.get("issue"))
        claimed_state = administrative.get("claimed_state")
        if issue is None or claimed_state not in STATE_RANK:
            continue
        row = result.setdefault(issue, {
            "issue": issue,
            "capability_id": capability.get("id"),
            "expected_state": claimed_state,
            "source_refs": [],
            "gaps": [],
        })
        if row.get("capability_id") is None:
            row["capability_id"] = capability.get("id")
        if row.get("expected_state") is None:
            row["expected_state"] = claimed_state
        row["source_refs"] = sorted(set(row.get("source_refs", [])) | {".project/capabilities.json", f"#{issue}"})
    return result


def _lifecycle_evidence(claims_report: dict[str, Any], issue: int, pulls: dict[int, dict[str, Any]]) -> dict[str, Any]:
    events = [event for event in claims_report.get("events", []) if event.get("issue") == issue]
    worklogs = [event for event in events if event.get("kind") == "worklog"]
    releases = [event for event in events if event.get("kind") == "claim" and event.get("status") == "RELEASED"]
    completed = []
    for release in releases:
        release_pr = _issue_number(release.get("pr"))
        matching = [row for row in worklogs if row.get("slot") == release.get("slot") and (release_pr is None or _issue_number(row.get("pr")) == release_pr)]
        if not matching:
            continue
        pr = pulls.get(release_pr) if release_pr is not None else None
        if pr and pr.get("state") == "MERGED":
            completed.append({
                "slot": release.get("slot"),
                "pr": release_pr,
                "release_order": release.get("order"),
                "worklog_order": matching[-1].get("order"),
            })
    return {"events": events, "completed": completed}


def _active_claim_problems(
    claims_report: dict[str, Any],
    issue: int,
    issue_state: str | None,
    pulls: dict[int, dict[str, Any]],
    branches: set[str],
    coverage: dict[str, Any],
) -> list[dict[str, Any]]:
    problems = []
    releases = [
        event for event in claims_report.get("events", [])
        if event.get("issue") == issue and event.get("kind") == "claim" and event.get("status") == "RELEASED"
    ]
    for claim in claims_report.get("active_claims", []):
        if claim.get("issue") != issue:
            continue
        branch = claim.get("branch")
        pr = _issue_number(claim.get("pr"))
        order = claim.get("claimed_order") or 0
        if issue_state == "CLOSED":
            problems.append({"code": "ACTIVE_CLAIM_ON_CLOSED_ISSUE", "branch": branch, "pr": pr})
        if coverage.get("branches_complete") and branch and branch not in branches:
            problems.append({"code": "ACTIVE_CLAIM_BRANCH_MISSING", "branch": branch, "pr": pr})
        if coverage.get("all_pulls_complete") and pr is not None:
            pull = pulls.get(pr)
            if pull is None:
                problems.append({"code": "ACTIVE_CLAIM_PR_MISSING", "branch": branch, "pr": pr})
            elif pull.get("state") != "OPEN":
                problems.append({"code": "ACTIVE_CLAIM_PR_NOT_OPEN", "branch": branch, "pr": pr, "pr_state": pull.get("state")})
        later = [row for row in releases if (row.get("order") or 0) > order and row.get("slot") == claim.get("slot")]
        if later:
            problems.append({"code": "ACTIVE_CLAIM_AFTER_RELEASE", "branch": branch, "pr": pr, "release_order": later[-1].get("order")})
    return problems


def _capability_map(project_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id")): row for row in project_report.get("capabilities", []) if row.get("id")}


def build_report(
    manifest: dict[str, Any],
    capability_manifest: dict[str, Any],
    project_report: dict[str, Any],
    claims_report: dict[str, Any],
    recovery: dict[str, Any],
    github_export: dict[str, Any],
) -> dict[str, Any]:
    source = normalize_backlog_export(github_export)
    coverage = source["coverage"]
    issues = {row["number"]: row for row in source["issues"]}
    pulls = {row["number"]: row for row in source["pulls"]}
    branches = set(source["branches"])
    relations = _relations(manifest, capability_manifest)
    capabilities = _capability_map(project_report)

    tracked = set(relations)
    tracked.update(_issue_number(row.get("issue")) for row in claims_report.get("active_claims", []))
    tracked.update(_issue_number(event.get("issue")) for event in claims_report.get("events", []))
    tracked.update(_issue_number(item.get("issue")) for item in claims_report.get("violations", []))
    tracked.discard(None)

    suggestions = []
    global_divergences = []
    for item in claims_report.get("violations", []):
        global_divergences.append({"code": f"COORDINATION_{item.get('code')}", "issue": item.get("issue"), "slot": item.get("slot"), "detail": item.get("detail")})
    for slot, lane in recovery.get("lanes", {}).items():
        if lane.get("status") == "UNKNOWN":
            global_divergences.append({"code": "RECOVERY_LANE_UNKNOWN", "slot": slot, "detail": lane.get("next_safe_action", {}).get("reason", "lane state unknown")})

    for issue in sorted(int(number) for number in tracked):
        relation = relations.get(issue, {"issue": issue, "capability_id": None, "expected_state": None, "source_refs": [], "gaps": []})
        gh = issues.get(issue)
        issue_state = gh.get("state") if gh else None
        refs = set(relation.get("source_refs", [])) | {f"#{issue}"}
        evidence = []
        contradictions = []

        if gh:
            evidence.append({"kind": "ISSUE_STATE", "state": issue_state})
        elif coverage.get("all_issues_complete"):
            evidence.append({"kind": "ISSUE_MISSING_FROM_EXPORT"})

        capability_id = relation.get("capability_id")
        expected = relation.get("expected_state")
        current = None
        if capability_id:
            cap = capabilities.get(capability_id)
            if cap:
                current = cap.get("state")
                evidence.append({"kind": "CAPABILITY_STATE", "capability_id": capability_id, "state": current, "expected_state": expected})
                refs.add(".project/capabilities.json")
            else:
                contradictions.append({"code": "CAPABILITY_NOT_FOUND", "capability_id": capability_id})

        lifecycle = _lifecycle_evidence(claims_report, issue, pulls)
        if lifecycle["completed"]:
            evidence.append({"kind": "MERGED_RELEASED_WORKLOG", "records": lifecycle["completed"]})
            refs.update(f"PR #{row['pr']}" for row in lifecycle["completed"])

        active = [row for row in claims_report.get("active_claims", []) if row.get("issue") == issue]
        if active:
            evidence.append({"kind": "ACTIVE_CLAIM", "claims": active})
            refs.update(f"branch:{row.get('branch')}" for row in active if row.get("branch"))

        for item in claims_report.get("violations", []):
            if item.get("issue") == issue:
                contradictions.append({"code": f"COORDINATION_{item.get('code')}", "detail": item.get("detail")})
        contradictions.extend(_active_claim_problems(claims_report, issue, issue_state, pulls, branches, coverage))

        recovery_slots = [
            slot for slot, lane in recovery.get("lanes", {}).items()
            if lane.get("active_issue") == issue and lane.get("status") == "CLAIMED"
        ]
        claim_slots = sorted({str(row.get("slot")) for row in active if row.get("slot")})
        if sorted(recovery_slots) != claim_slots:
            contradictions.append({"code": "RECOVERY_CLAIM_DIVERGENCE", "recovery_slots": sorted(recovery_slots), "claim_slots": claim_slots})

        if issue_state == "CLOSED" and expected and current in STATE_RANK and STATE_RANK[current] < STATE_RANK[expected]:
            contradictions.append({"code": "CLOSED_BELOW_DECLARED_DOD", "current_state": current, "declared_state": expected})

        gaps = relation.get("gaps", [])
        for gap in gaps:
            evidence.append({"kind": "DECLARED_GAP", **gap})
            refs.add(gap["source_ref"])

        if contradictions:
            category = "CONTRADICTION"
            justification = "persistent evidence sources disagree or the administrative state exceeds the proven state"
        elif gh is None:
            category = "UNKNOWN"
            justification = "GitHub issue state is not proven by the supplied export"
        elif issue_state == "OPEN" and active:
            category = "KEEP_OPEN"
            justification = "a unique active claim is still in progress"
        elif issue_state == "OPEN" and gaps and all(gap["status"] in BLOCKING_GAP_STATUSES for gap in gaps):
            category = "BLOCKED"
            justification = "all declared remaining gaps are explicitly BLOCKED or DEFERRED"
        elif issue_state == "OPEN" and any(gap["status"] in OPEN_GAP_STATUSES for gap in gaps):
            category = "KEEP_OPEN"
            justification = "at least one declared gap is still OPEN or IN_PROGRESS"
        elif issue_state == "OPEN" and expected and current in STATE_RANK and STATE_RANK[current] >= STATE_RANK[expected] and project_report.get("status") != "FAIL":
            category = "CLOSE_CANDIDATE"
            justification = "declared machine-verifiable capability state is satisfied and no remaining gap is declared"
        elif issue_state == "OPEN" and lifecycle["completed"] and not gaps:
            category = "CLOSE_CANDIDATE"
            justification = "merged PR + worklog + RELEASED are proven and no explicit remaining gap is declared"
        elif issue_state == "OPEN" and expected and current in STATE_RANK and STATE_RANK[current] < STATE_RANK[expected]:
            category = "KEEP_OPEN"
            justification = "proven capability state remains below the declared issue target"
        elif issue_state == "CLOSED":
            category = "UNKNOWN"
            justification = "issue is already closed and no contradiction requiring follow-up is proven"
        else:
            category = "UNKNOWN"
            justification = "persistent evidence is insufficient for a stronger backlog recommendation"

        suggestions.append({
            "issue": issue,
            "category": category,
            "justification": justification,
            "source_refs": sorted(refs),
            "evidence": evidence,
            "contradictions": sorted(contradictions, key=lambda row: stable_json(row)),
        })

    counts = {category: 0 for category in sorted(CATEGORIES)}
    for row in suggestions:
        counts[row["category"]] += 1
    hard_failure = project_report.get("status") == "FAIL" or bool(claims_report.get("violations"))
    status = "FAIL" if hard_failure else ("WARN" if counts["CONTRADICTION"] or counts["UNKNOWN"] or source["read_errors"] else "PASS")
    return {
        "schema": REPORT_SCHEMA,
        "status": status,
        "categories": counts,
        "coverage": coverage,
        "suggestions": suggestions,
        "divergences": sorted(global_divergences, key=lambda row: stable_json(row)),
        "read_errors": list(source["read_errors"]),
        "source_of_truth": {
            "dispatch_issue": coverage.get("dispatch_issue", 225),
            "capability_manifest": ".project/capabilities.json",
            "backlog_manifest": ".project/backlog-evidence.json",
            "claim_parser": "tools/check_parallel_claims.py",
            "recovery_builder": "tools/build_recovery_state.py",
            "project_state_validator": "tools/validate_project_state.py",
        },
    }


def validate_report(report: Any) -> list[str]:
    errors = []
    if not isinstance(report, dict):
        return ["report must be an object"]
    if report.get("schema") != REPORT_SCHEMA:
        errors.append(f"schema must be {REPORT_SCHEMA!r}")
    if report.get("status") not in {"PASS", "WARN", "FAIL"}:
        errors.append("status must be PASS, WARN or FAIL")
    suggestions = report.get("suggestions")
    if not isinstance(suggestions, list):
        errors.append("suggestions must be a list")
    else:
        for row in suggestions:
            if not isinstance(row, dict) or row.get("category") not in CATEGORIES or _issue_number(row.get("issue")) is None:
                errors.append("every suggestion requires issue and valid category")
    return errors


def render_human(report: dict[str, Any]) -> str:
    lines = ["# Backlog / Evidence Reconciliation", "", f"Status: {report['status']}", ""]
    for row in report["suggestions"]:
        lines.append(f"- #{row['issue']} {row['category']} — {row['justification']}")
    lines.extend(["", "## Divergences", ""])
    if report["divergences"]:
        for row in report["divergences"]:
            locus = f"#{row['issue']}" if row.get("issue") else (row.get("slot") or "-")
            lines.append(f"- {row['code']} [{locus}] — {row.get('detail', '')}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def compare_report_file(path: Path, expected: str) -> tuple[bool, str]:
    if not path.is_file():
        return False, f"missing backlog reconciliation report: {path}"
    actual = path.read_text(encoding="utf-8")
    if actual == expected:
        return True, ""
    diff = "".join(difflib.unified_diff(actual.splitlines(keepends=True), expected.splitlines(keepends=True), fromfile=str(path), tofile="generated-backlog-evidence"))
    return False, diff or "report differs"


def _tracked_issue_numbers(manifest: dict[str, Any], capability_manifest: dict[str, Any], contract: dict[str, Any], dispatch_issue: int) -> set[int]:
    numbers = {dispatch_issue}
    numbers.update(row["issue"] for row in manifest["issues"])
    for capability in capability_manifest.get("capabilities", []):
        administrative = capability.get("administrative") if isinstance(capability, dict) else None
        if isinstance(administrative, dict):
            issue = _issue_number(administrative.get("issue"))
            if issue:
                numbers.add(issue)
    for lane in contract["lanes"].values():
        numbers.update(int(item) for item in lane.get("typical_issues", []) if isinstance(item, int) and item > 0)
    return numbers


def fetch_live_export(repo: str, manifest: dict[str, Any], capability_manifest: dict[str, Any], contract: dict[str, Any], dispatch_issue: int = 225) -> dict[str, Any]:
    issues_raw = recovery_module._github_get_pages(repo, "issues", {"state": "all"})
    pulls_raw = recovery_module._github_get_pages(repo, "pulls", {"state": "all"})
    branches_raw = recovery_module._github_get_pages(repo, "branches", {})
    issues = [row for row in issues_raw if "pull_request" not in row]
    pulls = []
    for raw in pulls_raw:
        item = dict(raw)
        if raw.get("merged_at"):
            item["state"] = "MERGED"
        pulls.append(item)
    comments = []
    read_errors = []
    comments_complete = True
    for issue in sorted(_tracked_issue_numbers(manifest, capability_manifest, contract, dispatch_issue)):
        try:
            comments.extend(fetch_github_comments(repo, issue))
        except ValueError as exc:
            comments_complete = False
            read_errors.append(f"issue #{issue} comments: {exc}")
    return normalize_backlog_export({
        "schema": EXPORT_SCHEMA,
        "coverage": {
            "comments_complete": comments_complete,
            "all_issues_complete": True,
            "all_pulls_complete": True,
            "branches_complete": True,
            "dispatch_issue": dispatch_issue,
        },
        "comments": comments,
        "issues": issues,
        "pulls": pulls,
        "branches": branches_raw,
        "read_errors": read_errors,
    })


def load_export(path: Path) -> dict[str, Any]:
    try:
        return normalize_backlog_export(json.loads(path.read_text(encoding="utf-8")))
    except OSError as exc:
        raise ValueError(f"cannot read backlog GitHub export {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid backlog GitHub export {path}: {exc}") from exc


def build_from_root(root: Path, manifest: dict[str, Any], github_export: dict[str, Any]) -> dict[str, Any]:
    root = root.resolve()
    contract = load_contract(root / ".project/parallel-agents.json")
    capability_manifest = load_project_json(root / ".project/capabilities.json")
    project_report = validate_manifest(capability_manifest, root)
    source = normalize_backlog_export(github_export)
    claims_report = analyze_comments(source["comments"], contract)
    recovery_export = {
        "schema": recovery_module.EXPORT_SCHEMA,
        "coverage": {
            "comments_complete": source["coverage"]["comments_complete"],
            "open_issues_complete": source["coverage"]["all_issues_complete"],
            "open_pulls_complete": source["coverage"]["all_pulls_complete"],
            "dispatch_issue": source["coverage"]["dispatch_issue"],
        },
        "comments": source["comments"],
        "issues": [row for row in source["issues"] if row.get("state") == "OPEN"],
        "pulls": [row for row in source["pulls"] if row.get("state") == "OPEN"],
        "read_errors": source["read_errors"],
    }
    recovery = recovery_module.build_snapshot(root, recovery_export, root / ".project/parallel-agents.json")
    report = build_report(manifest, capability_manifest, project_report, claims_report, recovery, source)
    errors = validate_report(report)
    if errors:
        raise ValueError("invalid generated report: " + "; ".join(errors))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile GitHub backlog state with versioned capability/evidence and coordination history.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--github-export", type=Path)
    source.add_argument("--repo")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--render", action="store_true")
    modes.add_argument("--human", action="store_true")
    modes.add_argument("--check", type=Path)
    modes.add_argument("--write", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--dispatch-issue", type=int, default=225)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    try:
        manifest = load_manifest((args.manifest or root / ".project/backlog-evidence.json").resolve())
        capability_manifest = load_project_json(root / ".project/capabilities.json")
        contract = load_contract(root / ".project/parallel-agents.json")
        source_value = load_export(args.github_export) if args.github_export else fetch_live_export(args.repo, manifest, capability_manifest, contract, args.dispatch_issue)
        report = build_from_root(root, manifest, source_value)
        rendered = stable_json(report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BACKLOG_EVIDENCE_ERROR: {exc}", file=sys.stderr)
        return 2

    if args.human:
        print(render_human(report), end="")
    elif args.check:
        current, detail = compare_report_file(args.check, rendered)
        if not current:
            print(f"BACKLOG_EVIDENCE_STALE: {args.check}")
            if detail:
                print(detail, end="" if detail.endswith("\n") else "\n")
            return 1
        print(f"BACKLOG_EVIDENCE_OK: {args.check}")
    elif args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(rendered, encoding="utf-8")
        print(f"BACKLOG_EVIDENCE_WRITTEN: {args.write}")
    else:
        print(rendered, end="")
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
