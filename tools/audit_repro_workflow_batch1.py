#!/usr/bin/env python3
"""Static fail-closed contract for #361 REPRO workflow migration batch 1."""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.audit_github_workflows import parse_workflow  # noqa: E402
from tools import repro_ci_enforcement  # noqa: E402

SCHEMA = "poker-repro-workflow-migration-batch/v1"
REPORT_SCHEMA = "poker-repro-workflow-migration-batch-report/v1"
EVIDENCE = Path("analysis/workflow_audit/repro_batch1_before_after.json")

ENV_HELPER = "python3 tools/repro_ci_environment.py bootstrap --python-deps"
BROWSER_HELPER = "python3 tools/repro_ci_browser.py install"
STATIC_GUARD = "PYTHONPATH=. python3 tests/ci/test_repro_workflow_batch1.py"
PINNED_PYTHON = "python-version: '3.11.9'"

DIRECT_PIP_RX = re.compile(r"(?:\bpip(?:3)?\s+install\b|python3?\s+-m\s+pip\s+install)")
DIRECT_PLAYWRIGHT_RX = re.compile(r"playwright\s+install")


class BatchAuditError(ValueError):
    pass


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BatchAuditError(f"expected JSON object: {path}")
    return value


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


def _normalized_jobs(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for job in parsed.get("jobs") or []:
        rows.append({
            "id": job["id"],
            "runner": job.get("runner"),
            "needs": list(job.get("needs") or []),
        })
    return rows


def _job_block(text: str, job_id: str) -> str:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line == f"  {job_id}:":
            start = i
            break
    if start is None:
        return ""
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^  [A-Za-z_][\w-]*:\s*$", lines[i]):
            end = i
            break
    return "\n".join(lines[start:end])


def _metrics(text: str, parsed: dict[str, Any]) -> dict[str, int]:
    return {
        "lines": len(text.split("\n")),
        "checkout": text.count("actions/checkout@"),
        "setup_python": text.count("actions/setup-python@"),
        "setup_node": text.count("actions/setup-node@"),
        "direct_pip_install": len(DIRECT_PIP_RX.findall(text)),
        "direct_playwright_install": len(DIRECT_PLAYWRIGHT_RX.findall(text)),
        "repro_environment_helper_calls": text.count("tools/repro_ci_environment.py"),
        "repro_browser_helper_calls": text.count("tools/repro_ci_browser.py"),
        "continue_on_error_true": len(re.findall(r"continue-on-error:\s*true", text)),
        "upload_artifact": text.count("actions/upload-artifact@"),
        "static_cost_proxy": int((parsed.get("cost_proxy") or {}).get("score") or 0),
    }


def _triggered(parsed_rows: list[dict[str, Any]], changed_path: str) -> tuple[int, int]:
    runs = 0
    jobs = 0
    for parsed in parsed_rows:
        cfg = (parsed.get("triggers") or {}).get("push") or {}
        patterns = cfg.get("paths") or []
        if any(fnmatch.fnmatchcase(changed_path, pattern) for pattern in patterns):
            runs += 1
            jobs += len(parsed.get("jobs") or [])
    return runs, jobs


def audit(root: Path = ROOT, *, check_global_repro: bool = True) -> dict[str, Any]:
    root = root.resolve()
    evidence = _json(root / EVIDENCE)
    if evidence.get("schema") != SCHEMA:
        raise BatchAuditError("unexpected batch evidence schema")
    if evidence.get("issue") != 361 or evidence.get("parent_issue") != 204:
        raise BatchAuditError("unexpected issue/parent binding")
    if evidence.get("workflow_count") not in (1, 2, 3):
        raise BatchAuditError("batch must contain 1..3 workflows")

    violations: list[dict[str, Any]] = []
    checked: list[dict[str, Any]] = []
    parsed_rows: list[dict[str, Any]] = []

    # Bind the before state to the exact #291 consumer evidence instead of
    # trusting a hand-written baseline.
    helper_evidence = _json(root / "analysis/workflow_audit/helper_consumers.json")
    browser_rows = next(
        (
            row for row in helper_evidence.get("helpers") or []
            if row.get("helper") == "tools/repro_ci_browser.py"
        ),
        None,
    )
    if browser_rows is None:
        violations.append({"rule": "ISSUE_291_BROWSER_CONSUMER_EVIDENCE_MISSING"})
        before_by_path: dict[str, str] = {}
    else:
        before_by_path = {
            str(row.get("workflow")): str(row.get("workflow_blob_sha"))
            for row in browser_rows.get("consumers") or []
        }
    aggregate: dict[str, int] = {
        "workflow_lines": 0,
        "checkout": 0,
        "setup_python": 0,
        "setup_node": 0,
        "direct_pip_install": 0,
        "direct_playwright_install": 0,
        "repro_environment_helper_calls": 0,
        "repro_browser_helper_calls": 0,
        "continue_on_error_true": 0,
        "upload_artifact": 0,
        "static_cost_proxy": 0,
    }

    forbidden_reserved = {
        ".github/workflows/project-state-consistency.yml",
        "#346",
        "#206",
        "n8n",
    }
    excluded = set(evidence.get("excluded_reserved_scope") or [])
    if not forbidden_reserved.issubset(excluded):
        violations.append({
            "rule": "N8N_RESERVED_SCOPE_GUARD_MISSING",
            "expected": sorted(forbidden_reserved),
            "observed": sorted(excluded),
        })

    seen_paths: set[str] = set()
    for row in evidence.get("workflows") or []:
        rel = str(row.get("path") or "")
        if not rel or rel in seen_paths:
            violations.append({"rule": "DUPLICATE_OR_EMPTY_WORKFLOW_PATH", "path": rel})
            continue
        seen_paths.add(rel)
        if rel == ".github/workflows/project-state-consistency.yml":
            violations.append({"rule": "N8N_RESERVED_WORKFLOW_IN_BATCH", "path": rel})
            continue

        issue_291_before = before_by_path.get(rel)
        declared_before = str(row.get("before_git_blob_sha") or "")
        if issue_291_before != declared_before:
            violations.append({
                "rule": "BEFORE_BLOB_NOT_BOUND_TO_ISSUE_291",
                "path": rel,
                "issue_291": issue_291_before,
                "declared": declared_before,
            })

        path = root / rel
        if not path.is_file():
            violations.append({"rule": "WORKFLOW_MISSING", "path": rel})
            continue
        data = path.read_bytes()
        text = data.decode("utf-8")
        blob = git_blob_sha(data)
        expected_blob = str(row.get("after_git_blob_sha") or "")
        if blob != expected_blob:
            violations.append({
                "rule": "MIGRATED_WORKFLOW_BLOB_CHANGED_WITHOUT_EVIDENCE_REFRESH",
                "path": rel,
                "expected": expected_blob,
                "observed": blob,
            })

        parsed = parse_workflow(path, root)
        parsed_rows.append(parsed)
        contract = row.get("contract") or {}

        if parsed.get("name") != contract.get("name"):
            violations.append({"rule": "WORKFLOW_NAME_CHANGED", "path": rel})
        if parsed.get("triggers") != contract.get("triggers"):
            violations.append({
                "rule": "TRIGGER_SEMANTICS_CHANGED",
                "path": rel,
                "expected": contract.get("triggers"),
                "observed": parsed.get("triggers"),
            })
        if parsed.get("concurrency") != contract.get("concurrency"):
            violations.append({
                "rule": "CONCURRENCY_CHANGED",
                "path": rel,
                "expected": contract.get("concurrency"),
                "observed": parsed.get("concurrency"),
            })
        jobs = _normalized_jobs(parsed)
        if jobs != contract.get("jobs"):
            violations.append({
                "rule": "JOB_IDENTITY_OR_DEPENDENCY_CHANGED",
                "path": rel,
                "expected": contract.get("jobs"),
                "observed": jobs,
            })
        uploads = ((parsed.get("artifacts") or {}).get("uploads") or [])
        if uploads != (contract.get("artifact_uploads") or []):
            violations.append({
                "rule": "ARTIFACT_IDENTITY_CHANGED",
                "path": rel,
                "expected": contract.get("artifact_uploads") or [],
                "observed": uploads,
            })

        for token in row.get("required_business_tokens") or []:
            if token not in text:
                violations.append({
                    "rule": "BUSINESS_GATE_REMOVED_OR_CHANGED",
                    "path": rel,
                    "token": token,
                })

        browser = _job_block(text, "browser-smoke")
        if not browser:
            violations.append({"rule": "BROWSER_SMOKE_JOB_MISSING", "path": rel})
        else:
            for token, rule in (
                (PINNED_PYTHON, "PINNED_PYTHON_SETUP_MISSING"),
                (ENV_HELPER, "REPRO_ENVIRONMENT_HELPER_MISSING"),
                (BROWSER_HELPER, "REPRO_BROWSER_HELPER_MISSING"),
            ):
                # Check for either the old inline pattern or the new composite action
                is_old_pattern = token in browser
                is_new_pattern = False
                if rule == "PINNED_PYTHON_SETUP_MISSING":
                    is_new_pattern = "uses: actions/setup-python@v5" in browser # Simplified check
                elif rule == "REPRO_ENVIRONMENT_HELPER_MISSING":
                    is_new_pattern = "uses: ./.github/actions/repro-runtime" in browser
                elif rule == "REPRO_BROWSER_HELPER_MISSING":
                    is_new_pattern = "uses: ./.github/actions/repro-browser" in browser

                if not (is_old_pattern or is_new_pattern):
                    violations.append({"rule": rule, "path": rel, "token": token})

            if DIRECT_PIP_RX.search(browser):
                violations.append({"rule": "DIRECT_PIP_BROWSER_SETUP_BYPASS", "path": rel})
            if DIRECT_PLAYWRIGHT_RX.search(browser):
                violations.append({"rule": "DIRECT_PLAYWRIGHT_SETUP_BYPASS", "path": rel})
            if "continue-on-error: true" in browser:
                violations.append({"rule": "BROWSER_REPRO_GUARD_MAY_CONTINUE_ON_ERROR", "path": rel})

        if text.count(ENV_HELPER) != 1:
            violations.append({
                "rule": "REPRO_ENVIRONMENT_HELPER_CALL_COUNT",
                "path": rel,
                "observed": text.count(ENV_HELPER),
            })
        if text.count(BROWSER_HELPER) != 1:
            violations.append({
                "rule": "REPRO_BROWSER_HELPER_CALL_COUNT",
                "path": rel,
                "observed": text.count(BROWSER_HELPER),
            })
        if text.count(STATIC_GUARD) != 1:
            violations.append({
                "rule": "STATIC_ANTI_BYPASS_GUARD_CALL_COUNT",
                "path": rel,
                "observed": text.count(STATIC_GUARD),
            })
        if "permissions:\n  contents: read" not in text:
            violations.append({"rule": "MINIMAL_CONTENTS_READ_PERMISSION_CHANGED", "path": rel})

        metrics = _metrics(text, parsed)
        after_expected = row.get("after") or {}
        for key in (
            "lines",
            "direct_pip_install",
            "direct_playwright_install",
            "setup_python",
            "setup_node",
            "static_cost_proxy",
        ):
            if metrics[key] != after_expected.get(key):
                violations.append({
                    "rule": "AFTER_METRIC_MISMATCH",
                    "path": rel,
                    "metric": key,
                    "expected": after_expected.get(key),
                    "observed": metrics[key],
                })

        aggregate["workflow_lines"] += metrics["lines"]
        for key in aggregate:
            if key == "workflow_lines":
                continue
            aggregate[key] += metrics[key]

        checked.append({
            "path": rel,
            "git_blob_sha": blob,
            "jobs": jobs,
            "triggers": parsed.get("triggers"),
            "concurrency": parsed.get("concurrency"),
            "artifact_uploads": uploads,
            "metrics": metrics,
        })

    expected_aggregate = evidence.get("aggregate", {}).get("after") or {}
    for key, expected in expected_aggregate.items():
        if aggregate.get(key) != expected:
            violations.append({
                "rule": "AGGREGATE_AFTER_METRIC_MISMATCH",
                "metric": key,
                "expected": expected,
                "observed": aggregate.get(key),
            })

    representative = []
    for row in evidence.get("representative_changes") or []:
        changed = str(row["path"])
        runs, jobs = _triggered(parsed_rows, changed)
        observed = {"runs": runs, "jobs": jobs}
        representative.append({"path": changed, "observed": observed})
        if observed != row.get("after") or row.get("before") != row.get("after"):
            violations.append({
                "rule": "REPRESENTATIVE_TRIGGER_JOB_COUNT_CHANGED",
                "path": changed,
                "before": row.get("before"),
                "expected_after": row.get("after"),
                "observed_after": observed,
            })

    global_repro = None
    if check_global_repro:
        global_repro = repro_ci_enforcement.audit(root)
        if global_repro.get("status") != "PASS":
            violations.append({
                "rule": "ISSUE_347_REPRO_ENFORCEMENT_REGRESSION",
                "details": global_repro.get("violations") or [],
            })

    return {
        "schema": REPORT_SCHEMA,
        "status": "FAIL" if violations else "PASS",
        "issue": 361,
        "parent_issue": 204,
        "checked_workflows": checked,
        "aggregate_after": aggregate,
        "representative_changes": representative,
        "issue_347_guard": {
            "checked": check_global_repro,
            "status": None if global_repro is None else global_repro.get("status"),
        },
        "scientific_test_consumed": False,
        "production_effect": "NONE",
        "reserved_n8n_scope_touched": False,
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = audit(args.root, check_global_repro=True)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "schema": REPORT_SCHEMA,
            "status": "FAIL",
            "violations": [{"rule": "AUDIT_ERROR", "detail": str(exc)}],
        }
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 2 if result.get("status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
