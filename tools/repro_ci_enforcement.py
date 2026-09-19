#!/usr/bin/env python3
"""Static fail-closed enforcement for #347 scientific workflow REPRO guards.

This module deliberately does not reimplement lock or environment validation.
Runtime/lock correctness stays owned by the already-merged #203 validators.
It only proves that publication/mutation jobs cannot bypass those validators.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

from tools.audit_github_workflows import parse_workflow

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "reproducibility/scientific-workflow-enforcement.json"
SCHEMA = "poker-repro-scientific-workflow-enforcement/v1"
REPORT_SCHEMA = "poker-repro-scientific-workflow-enforcement-report/v1"


class EnforcementError(ValueError):
    pass


def load_policy(root: Path = ROOT) -> dict[str, Any]:
    path = root / POLICY_PATH.relative_to(ROOT)
    if not path.is_file():
        raise EnforcementError(f"missing enforcement policy: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA:
        raise EnforcementError("unexpected scientific workflow enforcement schema")
    rows = value.get("protected_workflows")
    if not isinstance(rows, list) or not rows:
        raise EnforcementError("protected_workflows must be non-empty")
    return value


def _job_blocks(text: str) -> dict[str, str]:
    lines = text.splitlines()
    try:
        jobs_index = next(i for i, line in enumerate(lines) if line.rstrip() == "jobs:")
    except StopIteration:
        return {}
    starts: list[tuple[int, str]] = []
    for i in range(jobs_index + 1, len(lines)):
        match = re.match(r"^  ([A-Za-z_][\w-]*):\s*$", lines[i])
        if match:
            starts.append((i, match.group(1)))
    blocks: dict[str, str] = {}
    for pos, (start, job_id) in enumerate(starts):
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        blocks[job_id] = "\n".join(lines[start:end])
    return blocks


def audit(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    policy = load_policy(root)
    reusable = str(policy["reusable_workflow"])
    guard_job = str(policy["guard_job"])
    runtime = policy["required_runtime_guard"]
    mutation_signatures = [str(x) for x in policy.get("mutation_signatures") or []]
    violations: list[dict[str, Any]] = []
    checked: list[dict[str, Any]] = []

    reusable_path = root / reusable
    if not reusable_path.is_file():
        violations.append({"rule": "REUSABLE_GUARD_MISSING", "path": reusable})
    else:
        reusable_text = reusable_path.read_text(encoding="utf-8")
        for token in (
            "tools/repro_ci_environment.py verify --require-node",
            "tools/repro_container.py validate",
            "tools/repro_hardening.py validate",
            "tools/repro_lock_update.py plan --candidate-root .",
            "tools/repro_ci_enforcement.py audit",
        ):
            if token not in reusable_text:
                violations.append({
                    "rule": "REUSABLE_GUARD_VALIDATOR_MISSING",
                    "path": reusable,
                    "token": token,
                })

    for row in policy["protected_workflows"]:
        rel = str(row["path"])
        path = root / rel
        if not path.is_file():
            violations.append({"rule": "PROTECTED_WORKFLOW_MISSING", "path": rel})
            continue
        text = path.read_text(encoding="utf-8")
        parsed = parse_workflow(path, root)
        jobs = {job["id"]: job for job in parsed["jobs"]}
        blocks = _job_blocks(text)
        guard = jobs.get(guard_job)
        if not guard or guard.get("uses") != f"./{reusable}":
            violations.append({
                "rule": "REPRO_GUARD_JOB_MISSING",
                "path": rel,
                "expected_uses": f"./{reusable}",
            })

        protected = {str(x) for x in row.get("protected_jobs") or []}
        for job_id in sorted(protected):
            job = jobs.get(job_id)
            block = blocks.get(job_id, "")
            if job is None:
                violations.append({
                    "rule": "PROTECTED_JOB_MISSING",
                    "path": rel,
                    "job": job_id,
                })
                continue
            if guard_job not in set(job.get("needs") or []):
                violations.append({
                    "rule": "GUARD_DEPENDENCY_MISSING",
                    "path": rel,
                    "job": job_id,
                })
            for token in (
                str(runtime["command"]),
                str(runtime["identity_command"]),
                str(runtime["environment_variable"]),
            ):
                if token not in block:
                    violations.append({
                        "rule": "RUNTIME_GUARD_MARKER_MISSING",
                        "path": rel,
                        "job": job_id,
                        "token": token,
                    })
            if "continue-on-error: true" in block and "repro_ci_environment.py" in block:
                violations.append({
                    "rule": "RUNTIME_GUARD_MAY_CONTINUE_ON_ERROR",
                    "path": rel,
                    "job": job_id,
                })

        for job_id, block in blocks.items():
            if any(signature in block for signature in mutation_signatures):
                if job_id not in protected:
                    violations.append({
                        "rule": "UNGUARDED_ARTIFACT_OR_MUTATION_JOB",
                        "path": rel,
                        "job": job_id,
                    })

        checked.append({
            "path": rel,
            "guard_job": guard_job,
            "protected_jobs": sorted(protected),
        })

    limitations = policy.get("explicit_limitations") or {}
    if limitations.get("system_packages_fully_pinned") is not False:
        violations.append({"rule": "SYSTEM_PACKAGE_LIMITATION_ERASED"})
    if limitations.get("browser_archive_sha_pinned") is not False:
        violations.append({"rule": "BROWSER_ARCHIVE_LIMITATION_ERASED"})

    return {
        "schema": REPORT_SCHEMA,
        "status": "FAIL" if violations else "PASS",
        "policy": POLICY_PATH.relative_to(ROOT).as_posix(),
        "reusable_workflow": reusable,
        "checked_workflows": checked,
        "violations": violations,
        "historical_runs_mutated": False,
        "scientific_test_consumed": False,
        "real_upgrade_executed": False,
    }


def audit_changed_paths(paths: list[str], root: Path = ROOT) -> dict[str, Any]:
    policy = load_policy(root)
    historical = policy.get("historical_immutability") or {}
    prefixes = [str(x) for x in historical.get("forbidden_change_prefixes") or []]
    exact = {str(x) for x in historical.get("forbidden_change_exact") or []}
    violations = []
    for raw in paths:
        path = raw.strip()
        if not path:
            continue
        if path in exact or any(path.startswith(prefix) for prefix in prefixes):
            violations.append({"rule": "IMMUTABLE_HISTORY_OR_TEST_LEDGER_CHANGED", "path": path})
    return {
        "schema": REPORT_SCHEMA,
        "status": "FAIL" if violations else "PASS",
        "changed_paths_checked": sorted({x.strip() for x in paths if x.strip()}),
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("audit")
    scope = sub.add_parser("scope")
    scope.add_argument("--paths-file", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "audit":
            result = audit(root)
        else:
            result = audit_changed_paths(
                args.paths_file.read_text(encoding="utf-8").splitlines(),
                root,
            )
    except (EnforcementError, OSError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "schema": REPORT_SCHEMA,
            "status": "FAIL",
            "violations": [{"rule": "ENFORCEMENT_ERROR", "detail": str(exc)}],
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result.get("status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
