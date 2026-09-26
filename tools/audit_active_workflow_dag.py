#!/usr/bin/env python3
"""Build the current-workflow DAG and statically simulate representative changes."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.audit_github_workflows import (MANUAL_ONLY_LIFECYCLE, automatic, parse_concurrency,
    parse_jobs, parse_triggers)

BASE_SHA = "4559315b08fd224409c5469a4073e07ee89225b3"
INVENTORY = "analysis/workflow_audit/workflows.json"
OUTPUT = "analysis/workflow_audit/active_workflow_dag_v2.json"
DECISION = "analysis/workflow_audit/consolidation_decision_v1.json"
DECISION_SCHEMA = "poker-workflow-concurrency-consolidation-decision/v1"
DECISION_VALUES = ("NO_FURTHER_CONSOLIDATION_JUSTIFIED", "MINIMAL_FAIL_CLOSED_CHANGE_APPLIED")
UNSAFE_SIDE_EFFECT_CLASSES = ("REPOSITORY_WRITE", "PUBLICATION_CAPABLE", "UNKNOWN")
SAFE_SIDE_EFFECT_CLASSES = ("READ_ONLY", "ARTIFACT_ONLY")
FROZEN_OUT_OF_SCOPE_WORKFLOWS = (".github/workflows/project-state-consistency.yml",)
# Planner key T4 estimate recorded on the parent issue; reconciled against the HEAD measurements below.
PLANNER_ESTIMATE = {"active_automatic": 53, "manual_only": 15,
                    "without_concurrency": 19, "cancel_in_progress_true": 37}
DECLARED_CHANGE_SCOPE = ("tools/audit_active_workflow_dag.py",
                         "analysis/workflow_audit/consolidation_decision_v1.json",
                         "docs/ci-workflow-dag.md", "docs/ci-workflow-audit.md",
                         "tests/ci/test_consolidation_decision.py")
BLOCKER_CATALOG = {
    "FAIL_CLOSED_UNSAFE_SIDE_EFFECT":
        "fail-closed: repository-write, publication or unknown capability is never cancellation-safe",
    "NO_MEASURED_IMPROVEMENT":
        "no measured improvement: the authorized method is a static structural proxy that is blind to queue/cancel "
        "semantics, so a concurrency-only change leaves runs/jobs/cost byte-identical by construction",
    "FROZEN_TELEMETRY_PREDATES_HEAD":
        "the only queue telemetry is the frozen #242 sample (100 runs) which predates this HEAD, so no per-workflow "
        "queue delta can be attributed to a new change",
    "ARTIFACT_DISCARD_RISK":
        "cancel-in-progress could discard produced artifacts that downstream consumers still read",
    "OUT_OF_SCOPE_CHANGE_SURFACE":
        "explicitly excluded from this task's change surface",
}
DOC = "docs/ci-workflow-dag.md"
SCENARIOS = (
    ("repro_runtime_composite", "pull_request", ".github/actions/repro-runtime/action.yml", "main"),
    ("repro_browser_composite", "pull_request", ".github/actions/repro-browser/action.yml", "main"),
    ("trainer_js", "pull_request", "site/trainer.js", "main"),
    ("game_core", "pull_request", "tools/simulation/game_core.py", "main"),
    ("preflop_decision", "pull_request", "src/preflop/decision.js", "main"),
    ("dataset_nlhe_100_200", "push", "training/datasets/NLHE_100-200/source/NLHE 100-200.zip", "main"),
    ("preflop_model", "pull_request", "training/models/preflop_population_model_v5.json", "main"),
    ("repro_helper", "push", "tools/repro_ci_environment.py", "main"),
    ("python_version", "pull_request", ".python-version", "main"),
    ("node_version", "pull_request", ".node-version", "main"),
    ("release_handoff_tooling", "pull_request", "tools/training/build_release_handoff.py", "main"),
    ("model_b_training", "push", "tools/training/independent_profiles/card_aware_behavior_fit.py", "main"),
    ("docs_only", "pull_request", "docs/README.md", "main"),
    ("historical_manual_workflow", "pull_request", ".github/workflows/finalize-training-cycle.yml", "main"),
)


class AuditError(ValueError):
    pass


def git(*args: str, stderr: int | None = None) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=stderr)


def base_text(path: str) -> str:
    try:
        # A workflow added after the pinned base is expected (#419); keep the probe quiet.
        return git("show", f"{BASE_SHA}:{path}", stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        # A workflow may be newer than the pinned base; fall back to the checkout text.
        return (ROOT / path).read_text()


def _top_block(text: str, key: str) -> str | None:
    lines = text.splitlines()
    try:
        start = lines.index(key + ":")
    except ValueError:
        return None
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end].startswith(" ")):
        end += 1
    return "\n".join(lines[start:end]).rstrip()


def _job_blocks(text: str) -> dict[str, str]:
    jobs = re.search(r"^jobs:\s*$", text, re.M)
    if not jobs:
        raise AuditError("jobs section missing")
    body = text[jobs.end():]
    starts = list(re.finditer(r"^  ([A-Za-z_][\w-]*):\s*$", body, re.M))
    if not starts:
        raise AuditError("job parser found no jobs")
    return {m.group(1): body[m.start(): starts[i + 1].start() if i + 1 < len(starts) else len(body)]
            for i, m in enumerate(starts)}


def _field(block: str, name: str, indent: int = 4) -> str | None:
    lines = block.splitlines()
    for i, line in enumerate(lines):
        if re.match(rf"^\s{{{indent}}}{re.escape(name)}:", line):
            end = i + 1
            while end < len(lines) and (not lines[end].strip() or
                    len(lines[end]) - len(lines[end].lstrip()) > indent):
                end += 1
            return "\n".join(lines[i:end]).rstrip()
    return None


def _permission_map(raw: str | None) -> dict[str, str] | None:
    if raw is None:
        return None
    values: dict[str, str] = {}
    for line in raw.splitlines()[1:]:
        if not line.strip():
            continue
        match = re.match(r"^\s+(\S+):\s*(read|write|none)\s*$", line)
        if not match:
            raise AuditError(f"unsupported permissions syntax: {line.strip()}")
        values[match.group(1)] = match.group(2)
    return values


def _artifact_steps(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    rows = []
    for i, line in enumerate(lines):
        match = re.search(r"actions/(upload|download)-artifact@([^\s]+)", line)
        if not match:
            continue
        indent = len(line) - len(line.lstrip())
        end = i + 1
        while end < len(lines):
            level = len(lines[end]) - len(lines[end].lstrip())
            if lines[end].strip().startswith("- ") and level <= indent:
                break
            end += 1
        block = "\n".join(lines[i:end])
        def value(key: str) -> str | None:
            found = re.search(rf"^\s+{re.escape(key)}:\s*(.+?)\s*$", block, re.M)
            return found.group(1).strip("'\"") if found else None
        rows.append({"kind": match.group(1), "version": match.group(2),
                     "name": value("name"), "path": value("path"),
                     "retention_days": value("retention-days"), "raw": block})
    return rows


COST_PATTERNS = {"checkout": r"actions/checkout@", "setup_python": r"actions/setup-python@",
    "setup_node": r"actions/setup-node@", "pip_install": r"(?:\bpip(?:3)?\s+install\b|python3?\s+-m\s+pip\s+install)",
    "playwright_install": r"playwright\s+install", "npm_install": r"\bnpm\s+(?:ci|install)\b",
    "upload_artifact": r"actions/upload-artifact@", "download_artifact": r"(?:actions/download-artifact@|\bgh\s+run\s+download\b)"}


def _cost(text: str, path: str, name: str, jobs: list[dict]) -> dict[str, Any]:
    patterns = COST_PATTERNS
    counts = {key: len(re.findall(rx, text)) for key, rx in patterns.items()}
    score = (len(jobs) + 2 * counts["checkout"] + 2 * counts["setup_python"] +
             2 * counts["setup_node"] + 2 * counts["pip_install"] +
             5 * counts["playwright_install"] + 2 * counts["npm_install"] +
             2 * counts["upload_artifact"] + 2 * counts["download_artifact"] +
             (2 if re.search(r"train|benchmark|simulation|arena|fit|evaluation|candidate|strategy", path + " " + name, re.I) else 0))
    return {"score": score, "band": "high" if score >= 18 else "medium" if score >= 8 else "low",
            "method": "static structural proxy; not GitHub-billed minutes", "components": counts}


def _repro_status(path: str, text: str) -> str:
    if "uses: ./.github/actions/repro-" in text:
        from tools.audit_repro_composite_factorization import WORKFLOWS, baseline, check_actions, check_workflow, AuditError as TransitionError
        try:
            check_actions()
            if path not in WORKFLOWS:
                raise TransitionError(f"{path}: composite consumer outside transition allowlist")
            check_workflow(path, baseline(path), text)
        except TransitionError:
            return "REPRO_INCOMPLETE"
        return "REPRO_COMPOSITE_VERIFIED"
    if "repro-scientific-environment.yml" in text and "REPRO_ENVIRONMENT_IDENTITY_SHA256" in text:
        return "REPRO_STRONG_IDENTITY_BOUND"
    if "tools/repro_ci_environment.py verify" in text:
        if "python-version-file: '.python-version'" not in text:
            return "REPRO_INCOMPLETE"
        if "actions/setup-node@" in text and ("node-version-file: '.node-version'" not in text or "--require-node" not in text):
            return "REPRO_INCOMPLETE"
        return "REPRO_HELPER_VERIFIED"
    return "REPRO_NOT_VERIFIED"


def _side_effect(text: str, top: dict[str, str] | None,
                 job_permissions: list[dict[str, str] | None], artifacts: list[dict]) -> str:
    publication = bool(re.search(r"^\s*(?:gh release create|wrangler deploy|npm publish)\b", text, re.M))
    writable = any(p and any(v == "write" for v in p.values()) for p in [top, *job_permissions])
    if publication:
        return "PUBLICATION_CAPABLE"
    if writable or re.search(r"^\s*git push(?:\s|$)", text, re.M):
        return "REPOSITORY_WRITE"
    if top is None and all(p is None for p in job_permissions):
        return "UNKNOWN"
    if artifacts:
        return "ARTIFACT_ONLY"
    return "READ_ONLY"


def workflow(path: str, text: str, inventory: dict[str, Any]) -> dict[str, Any]:
    lines = text.splitlines()
    name_match = re.search(r"^name:\s*(.+?)\s*$", text, re.M)
    if not name_match:
        raise AuditError(f"{path}: name missing")
    name = name_match.group(1).strip("'\"")
    triggers = parse_triggers(lines)
    if not triggers:
        raise AuditError(f"{path}: trigger syntax not understood")
    parsed_jobs = parse_jobs(lines)
    blocks = _job_blocks(text)
    if {j["id"] for j in parsed_jobs} != set(blocks):
        raise AuditError(f"{path}: job syntax not fully understood")
    top_raw = _top_block(text, "permissions")
    top_permissions = _permission_map(top_raw)
    job_rows = []
    permission_rows = []
    for parsed in parsed_jobs:
        body = blocks[parsed["id"]]
        raw_permissions = _field(body, "permissions")
        permissions = _permission_map("permissions:\n" + "\n".join(
            line[4:] for line in raw_permissions.splitlines()[1:])) if raw_permissions else top_permissions
        permission_rows.append(permissions)
        if_raw = _field(body, "if")
        job_rows.append({**parsed, "if": if_raw, "permissions": permissions,
                         "write_capable": bool(permissions and any(v == "write" for v in permissions.values()))})
    artifacts = _artifact_steps(text)
    side_effect = _side_effect(text, top_permissions, permission_rows, artifacts)
    scientific = {boundary: bool(re.search(rf"\b{boundary}\b", text))
                  for boundary in ("TRAIN", "VALIDATION", "TEST")}
    dependencies = sorted({source for cfg in triggers.values() for source in cfg.get("workflows", [])})
    concurrency = parse_concurrency(lines)
    if concurrency and "group" not in concurrency:
        raise AuditError(f"{path}: concurrency group not understood")
    safe = side_effect in {"READ_ONLY", "ARTIFACT_ONLY"}
    blockers = [] if safe else ["write/publication or unknown permission surface"]
    return {
        "path": path, "name": name, "lifecycle": inventory.get("lifecycle", "current"), "role": inventory["role"],
        "triggers": triggers,
        "path_filters": {event: {k: v for k, v in cfg.items() if k in ("paths", "paths_ignore")}
                         for event, cfg in triggers.items() if any(k in cfg for k in ("paths", "paths_ignore"))},
        "workflow_run_dependencies": dependencies, "jobs": job_rows,
        "permissions": {"workflow": top_permissions, "raw": top_raw},
        "concurrency": concurrency, "artifacts": artifacts,
        "static_cost_proxy": _cost(text, path, name, parsed_jobs),
        "side_effect_class": side_effect, "repro_status": _repro_status(path, text),
        "scientific_boundaries": scientific,
        "concurrency_recommendation": {"has_concurrency": bool(concurrency),
            "group": concurrency.get("group"), "cancel_in_progress": concurrency.get("cancel_in_progress"),
            "side_effect_class": side_effect, "safe_candidate_for_future_cancellation_change": safe,
            "justification": ("No repository/publication capability detected; cancellation may be evaluated separately."
                              if safe else "Fail-closed: cancellation safety is not asserted for this side-effect class."),
            "blockers": blockers},
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def _glob(pattern: str, path: str) -> bool:
    """Supported GitHub subset: literals plus * and **; everything else fails closed."""
    if any(char in pattern for char in "!?[]{}"):
        raise AuditError(f"unsupported path glob: {pattern}")
    result = ""
    i = 0
    while i < len(pattern):
        if pattern[i:i + 3] == "**/":
            result += "(?:.*/)?"; i += 3
        elif pattern[i:i + 2] == "**":
            result += ".*"; i += 2
        elif pattern[i] == "*":
            result += "[^/]*"; i += 1
        else:
            result += re.escape(pattern[i]); i += 1
    return bool(re.fullmatch(result, path))


def _branch_match(cfg: dict[str, Any], branch: str) -> bool:
    branches = cfg.get("branches", [])
    ignored = cfg.get("branches_ignore", [])
    if branches and not any(_glob(p, branch) for p in branches):
        return False
    if ignored and any(_glob(p, branch) for p in ignored):
        return False
    return True


def _event_match(row: dict[str, Any], event: str, path: str, branch: str) -> tuple[bool, str]:
    if event not in row["triggers"]:
        return False, "event not subscribed"
    cfg = row["triggers"][event]
    if not _branch_match(cfg, branch):
        return False, "branch filter excluded"
    patterns = cfg.get("paths", [])
    ignored = cfg.get("paths_ignore", [])
    if patterns and not any(_glob(p, path) for p in patterns):
        return False, "no path filter matched"
    if ignored and any(_glob(p, path) for p in ignored):
        return False, "paths-ignore excluded"
    return True, "event/branch matched; " + ("path filter matched" if patterns else "no path filter")


def _job_reachability(job: dict[str, Any], event: str) -> str:
    raw = job.get("if")
    if not raw:
        return "POTENTIAL"
    expression = raw.replace("if:", "", 1).strip().replace(">-", "").strip()
    tests = re.findall(r"github\.event_name\s*(==|!=)\s*'([^']+)'", expression)
    if not tests:
        return "UNKNOWN"
    values = [(event == value) if op == "==" else (event != value) for op, value in tests]
    if "&&" in expression and not all(values):
        return "EXCLUDED"
    if len(values) == 1 and not values[0]:
        return "EXCLUDED"
    return "UNKNOWN" if any(token in expression for token in ("github.", "needs.", "steps.")) else "POTENTIAL"


def simulate(rows: list[dict[str, Any]], scenario: tuple[str, str, str, str]) -> dict[str, Any]:
    sid, event, path, branch = scenario
    matched: dict[str, dict[str, Any]] = {}
    for row in rows:
        yes, reason = _event_match(row, event, path, branch)
        if yes:
            matched[row["path"]] = {"workflow": row, "event": event, "reason": reason}
    # One or more successful direct workflows may activate workflow_run subscribers.
    changed = True
    while changed:
        changed = False
        names = {entry["workflow"]["name"] for entry in matched.values()}
        for row in rows:
            if row["path"] in matched or "workflow_run" not in row["triggers"]:
                continue
            sources = set(row["workflow_run_dependencies"])
            hit = sorted(sources & names)
            if hit:
                matched[row["path"]] = {"workflow": row, "event": "workflow_run",
                    "reason": "workflow_run after: " + ", ".join(hit)}
                changed = True
    details = []
    total_jobs = total_cost = 0
    write_jobs = []
    unknown = []
    for path_key in sorted(matched):
        entry = matched[path_key]; row = entry["workflow"]
        reachable = []
        for job in row["jobs"]:
            state = _job_reachability(job, entry["event"])
            if state != "EXCLUDED":
                reachable.append({"id": job["id"], "reachability": state})
                if state == "UNKNOWN":
                    unknown.append(f"{path_key}:{job['id']}")
                if job["write_capable"] or row["side_effect_class"] == "PUBLICATION_CAPABLE":
                    write_jobs.append({"workflow": path_key, "job": job["id"], "reachability": state})
        total_jobs += len(reachable); total_cost += row["static_cost_proxy"]["score"]
        details.append({"path": path_key, "reason": entry["reason"], "activation_event": entry["event"],
                        "jobs": reachable, "cost_proxy": row["static_cost_proxy"]["score"],
                        "side_effect_class": row["side_effect_class"]})
    return {"id": sid, "event": event, "branch": branch, "changed_paths": [path],
            "matched_workflows": [d["path"] for d in details], "workflow_count": len(details),
            "job_count": total_jobs, "cost_proxy": total_cost,
            "write_capable_jobs_potentially_reachable": write_jobs,
            "unknown_job_conditions": unknown, "matches": details,
            "simulation_disposition": "UNKNOWN" if unknown else "SUPPORTED_STATIC_SUBSET"}


def split_active(rows: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Active = every workflow that is not one of the #373 manual-only historical workflows."""
    manual_only = sorted(path for path, row in rows.items() if row.get("lifecycle") == MANUAL_ONLY_LIFECYCLE)
    excluded = set(manual_only)
    return sorted(path for path in rows if path not in excluded), manual_only


def _same_ref_duplicate_exposure(row: dict[str, Any]) -> bool:
    """True when push and pull_request can both fire for the same ref (duplicate-run exposure)."""
    triggers = row["triggers"]
    if "push" not in triggers or "pull_request" not in triggers:
        return False
    push_branches = set(triggers["push"].get("branches", []))
    pr_branches = set(triggers["pull_request"].get("branches", []))
    if not push_branches or not pr_branches:
        # An unbounded trigger on either side can overlap; this is a conservative exposure signal.
        return True
    return bool(push_branches & pr_branches)


def _unapplied_blockers(row: dict[str, Any], safe: bool) -> list[str]:
    """Why a concurrency recommendation is deliberately not applied by this tranche (codes from BLOCKER_CATALOG)."""
    if not safe:
        return ["FAIL_CLOSED_UNSAFE_SIDE_EFFECT"]
    blockers = ["NO_MEASURED_IMPROVEMENT", "FROZEN_TELEMETRY_PREDATES_HEAD"]
    if row["artifacts"]:
        blockers.append("ARTIFACT_DISCARD_RISK")
    if row["path"] in FROZEN_OUT_OF_SCOPE_WORKFLOWS:
        blockers.append("OUT_OF_SCOPE_CHANGE_SURFACE")
    return blockers


def _proposed_change(row: dict[str, Any]) -> str:
    if not row["concurrency"]:
        return "add a concurrency group with cancel-in-progress: true"
    if row["concurrency"].get("cancel_in_progress") is not True:
        return "keep the existing group and set cancel-in-progress: true"
    return "none: cancel-in-progress is already true"


def _decision_row(row: dict[str, Any]) -> dict[str, Any]:
    recommendation = row["concurrency_recommendation"]
    concurrency = row["concurrency"]
    cancel = concurrency.get("cancel_in_progress")
    safe = bool(recommendation["safe_candidate_for_future_cancellation_change"])
    if cancel is True:
        state, blockers = "ALREADY_CANCEL_IN_PROGRESS", []
    elif safe:
        state, blockers = "SAFE_CANDIDATE_NOT_APPLIED", _unapplied_blockers(row, safe)
    else:
        state, blockers = "BLOCKED_NOT_APPLIED", _unapplied_blockers(row, safe)
    return {"path": row["path"], "name": row["name"], "role": row["role"],
            "triggers": sorted(row["triggers"]),
            "event_filters": {event: cfg for event, cfg in sorted(row["triggers"].items())},
            "has_concurrency": bool(concurrency), "concurrency_group": concurrency.get("group"),
            "cancel_in_progress": cancel,
            "duplicate_push_and_pull_request_exposure": _same_ref_duplicate_exposure(row),
            "side_effect_class": row["side_effect_class"], "fail_closed_safe": safe,
            "proposed_change": _proposed_change(row), "recommendation_state": state,
            "blockers": blockers, "job_ids": [job["id"] for job in row["jobs"]],
            "artifact_names": [artifact["name"] for artifact in row["artifacts"]],
            "static_cost_proxy": row["static_cost_proxy"]["score"]}


def _name_digest(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps({row["path"]: {"job_ids": [job["id"] for job in row["jobs"]],
                                        "artifact_names": [artifact["name"] for artifact in row["artifacts"]]}
                          for row in rows}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _scenario_row(simulation: dict[str, Any]) -> dict[str, Any]:
    before, after = simulation["before"], simulation["after"]
    return {"scenario": simulation["scenario"], "event": after["event"],
            "changed_paths": after["changed_paths"],
            "before": {"runs": before["workflow_count"], "jobs": before["job_count"],
                       "cost_proxy": before["cost_proxy"]},
            "after": {"runs": after["workflow_count"], "jobs": after["job_count"],
                      "cost_proxy": after["cost_proxy"]},
            "delta": {"runs": after["workflow_count"] - before["workflow_count"],
                      "jobs": after["job_count"] - before["job_count"],
                      "cost_proxy": after["cost_proxy"] - before["cost_proxy"]},
            "method": "static structural proxy", "billed": False,
            "write_capable_jobs_potentially_reachable": len(after["write_capable_jobs_potentially_reachable"]),
            "simulation_disposition": after["simulation_disposition"]}


def build_decision(data: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed trigger/concurrency decision for the active DAG."""
    rows = [_decision_row(row) for row in data["workflows"]]
    unapplied = [row for row in rows if row["recommendation_state"] != "ALREADY_CANCEL_IN_PROGRESS"]
    safe_candidates = [row for row in unapplied if row["fail_closed_safe"]]
    blocked = [row for row in unapplied if not row["fail_closed_safe"]]
    scenarios = [_scenario_row(item) for item in data["representative_scenarios"]]
    before_totals = {key: sum(item["before"][key] for item in scenarios) for key in ("runs", "jobs", "cost_proxy")}
    after_totals = {key: sum(item["after"][key] for item in scenarios) for key in ("runs", "jobs", "cost_proxy")}
    counts = {"inventory_workflow_count": data["inventory_workflow_count"],
              "active_automatic_workflow_count": data["active_workflow_count"],
              "manual_only_count": data["manual_only_count"],
              "without_concurrency_count": sum(1 for row in rows if not row["has_concurrency"]),
              "cancel_in_progress_true_count": sum(1 for row in rows if row["cancel_in_progress"] is True),
              "cancel_in_progress_false_count": sum(1 for row in rows if row["cancel_in_progress"] is False),
              "duplicate_push_and_pull_request_exposure_count":
                  sum(1 for row in rows if row["duplicate_push_and_pull_request_exposure"]),
              "safe_candidate_not_applied_count": len(safe_candidates),
              "blocked_not_applied_count": len(blocked)}
    measured = {"active_automatic": counts["active_automatic_workflow_count"],
                "manual_only": counts["manual_only_count"],
                "without_concurrency": counts["without_concurrency_count"],
                "cancel_in_progress_true": counts["cancel_in_progress_true_count"]}
    decision = {
        "schema": DECISION_SCHEMA, "issue": data["issue"], "parent_issue": data["parent_issue"],
        "task": "backlog-85b", "base_sha": data["base_sha"],
        "inventory_source": data["inventory_source"], "inventory_sha256": data["inventory_sha256"],
        "dag_evidence": OUTPUT, "doc": DOC,
        "decision": "NO_FURTHER_CONSOLIDATION_JUSTIFIED",
        "decision_statement": ("No safe trigger/concurrency consolidation is demonstrated for the active DAG at "
                               "HEAD, so no workflow file is modified: every recommendation stays unapplied and "
                               "carries an explicit blocker."),
        "measurement_method": {"kind": "static structural proxy", "billed": False,
                               "statement": ("Every run/job/cost figure here is a static structural proxy, not "
                                             "GitHub-billed minutes; the pinned base and HEAD carry byte-identical "
                                             "workflow definitions, so each before/after pair coincides by "
                                             "construction.")},
        "method_sensitivity": {
            "proxy_inputs": sorted(COST_PATTERNS),
            "concurrency_sensitive_inputs": [],
            "statement": ("the proxy is a function of job/checkout/setup/install/artifact counts only, so a "
                          "trigger/concurrency-only edit cannot move the measured runs/jobs/cost figures; the "
                          "decision therefore cannot claim a measured improvement")},
        "counts": counts, "planner_estimate": dict(PLANNER_ESTIMATE),
        "planner_estimate_delta": {key: measured[key] - value for key, value in PLANNER_ESTIMATE.items()},
        "planner_estimate_notes": [
            "the planner counted concurrency across all 69 workflow files, including the 15 manual-only ones, "
            "which yields 19 files without a concurrency block and 38 files with cancel-in-progress: true; this "
            "decision counts only the 54 active workflows, which yields 16 and 28, hence the -3 and -9 deltas",
            "the planner's 53 automatic workflows predates the HEAD measurement of 54",
            "no reconciliation delta changes the decision: it is taken on the active set only",
        ],
        "totals": {"before": before_totals, "after": after_totals,
                   "delta": {key: after_totals[key] - before_totals[key] for key in before_totals},
                   "method": "static structural proxy", "billed": False},
        "scenarios": scenarios, "scenario_count": len(scenarios),
        "workflows": rows,
        "recommendations": {"applied": [],
                            "safe_candidates_not_applied": [row["path"] for row in safe_candidates],
                            "blocked_not_applied": [row["path"] for row in blocked],
                            "unapplied_count": len(unapplied)},
        "blocker_catalog": dict(BLOCKER_CATALOG),
        "fail_closed_invariants": [
            "a recommendation is marked fail-closed safe only when its side-effect class is READ_ONLY or "
            "ARTIFACT_ONLY",
            "REPOSITORY_WRITE, PUBLICATION_CAPABLE and UNKNOWN are never marked safe",
            "every unapplied recommendation carries at least one blocker",
            "no change is applied while the decision is NO_FURTHER_CONSOLIDATION_JUSTIFIED",
            f"{FROZEN_OUT_OF_SCOPE_WORKFLOWS[0]} is never modified",
            "job and artifact names are preserved and digest-pinned for every workflow",
        ],
        "frozen_name_digest": _name_digest(data["workflows"]),
        "change_surface": {"workflow_files_modified": False, "repository_write_surface_expanded": False,
                           "publication_surface_expanded": False, "scientific_surface_expanded": False,
                           "cancellation_surface_changed": False,
                           "project_state_consistency_modified": False,
                           "declared_change_scope": list(DECLARED_CHANGE_SCOPE),
                           "declared_workflow_changes": [],
                           "unchanged_frozen_evidence": [OUTPUT]},
    }
    validate_decision(decision)
    return decision


def validate_decision(decision: dict[str, Any]) -> None:
    """Fail-closed validator; every mutation test in tests/ci/test_residual_repro_dag.py targets this."""
    if decision.get("schema") != DECISION_SCHEMA:
        raise AuditError("decision schema mismatch")
    if decision.get("decision") not in DECISION_VALUES:
        raise AuditError("unknown consolidation decision")
    rows = decision.get("workflows", [])
    paths = [row.get("path") for row in rows]
    if len(paths) != len(set(paths)) or not paths:
        raise AuditError("decision workflow table is empty or duplicated")
    seen = set()
    for row in rows:
        side_effect = row.get("side_effect_class")
        safe = row.get("fail_closed_safe")
        if not isinstance(safe, bool):
            raise AuditError(f"{row.get('path')}: fail-closed status must be an explicit boolean")
        if side_effect not in SAFE_SIDE_EFFECT_CLASSES + UNSAFE_SIDE_EFFECT_CLASSES:
            raise AuditError(f"{row.get('path')}: unsupported side-effect class {side_effect}")
        if safe != (side_effect in SAFE_SIDE_EFFECT_CLASSES):
            raise AuditError(f"{row.get('path')}: fail-closed status contradicts the side-effect class")
        if side_effect in UNSAFE_SIDE_EFFECT_CLASSES and safe:
            raise AuditError(f"unsafe concurrency recommendation: {row.get('path')}")
        if safe and side_effect not in SAFE_SIDE_EFFECT_CLASSES:
            raise AuditError(f"{row.get('path')}: safe status outside the artifact/read-only surface")
        state = row.get("recommendation_state")
        if state == "ALREADY_CANCEL_IN_PROGRESS":
            if row.get("cancel_in_progress") is not True:
                raise AuditError(f"{row.get('path')}: applied state without cancel-in-progress: true")
        elif state in {"SAFE_CANDIDATE_NOT_APPLIED", "BLOCKED_NOT_APPLIED"}:
            if row.get("cancel_in_progress") is True:
                raise AuditError(f"{row.get('path')}: unapplied recommendation already applied")
            if not row.get("blockers"):
                raise AuditError(f"{row.get('path')}: unapplied recommendation without a blocker")
            unknown = set(row["blockers"]) - set(decision.get("blocker_catalog", {}))
            if unknown:
                raise AuditError(f"{row.get('path')}: blocker outside the catalog: {sorted(unknown)}")
        else:
            raise AuditError(f"{row.get('path')}: unknown recommendation state {state}")
        seen.add(row.get("path"))
    applied = decision.get("recommendations", {}).get("applied", [])
    for change in applied:
        if not change.get("fail_closed_safe") or change.get("path") not in seen:
            raise AuditError(f"applied change is not fail-closed: {change.get('path')}")
        if not change.get("mutation_test") or not change.get("job_and_artifact_names_preserved"):
            raise AuditError(f"applied change lacks mutation/name-preservation evidence: {change.get('path')}")
        if change.get("path") in FROZEN_OUT_OF_SCOPE_WORKFLOWS:
            raise AuditError(f"frozen out-of-scope workflow cannot be changed: {change.get('path')}")
    if decision["decision"] == "NO_FURTHER_CONSOLIDATION_JUSTIFIED" and applied:
        raise AuditError("no-further-consolidation decision must not apply any change")
    if decision["decision"] == "MINIMAL_FAIL_CLOSED_CHANGE_APPLIED" and not applied:
        raise AuditError("minimal-change decision must apply at least one change")
    if decision.get("scenario_count") != len(SCENARIOS):
        raise AuditError("representative scenario set is incomplete")
    scenarios = decision.get("scenarios", [])
    if len(scenarios) != len(SCENARIOS):
        raise AuditError("representative scenario rows are incomplete")
    for item in scenarios:
        expected = {key: item["after"][key] - item["before"][key] for key in ("runs", "jobs", "cost_proxy")}
        if item["delta"] != expected or item["billed"] is not False:
            raise AuditError(f"scenario delta is inconsistent: {item.get('scenario')}")
    for key in ("runs", "jobs", "cost_proxy"):
        if decision["totals"]["before"][key] != sum(item["before"][key] for item in scenarios):
            raise AuditError(f"before totals are inconsistent: {key}")
        if decision["totals"]["after"][key] != sum(item["after"][key] for item in scenarios):
            raise AuditError(f"after totals are inconsistent: {key}")
    counts = decision["counts"]
    sensitivity = decision.get("method_sensitivity", {})
    if sorted(sensitivity.get("proxy_inputs", [])) != sorted(COST_PATTERNS):
        raise AuditError("method sensitivity does not match the static proxy inputs")
    if sensitivity.get("concurrency_sensitive_inputs"):
        raise AuditError("method sensitivity claims a concurrency-sensitive input")
    if any(token in name for name in COST_PATTERNS for token in ("concurrency", "cancel", "trigger")):
        raise AuditError("the static proxy unexpectedly depends on triggers/concurrency")
    if counts["without_concurrency_count"] != sum(1 for row in rows if not row["has_concurrency"]):
        raise AuditError("concurrency counts are inconsistent")
    if counts["cancel_in_progress_true_count"] != sum(1 for row in rows if row["cancel_in_progress"] is True):
        raise AuditError("cancel-in-progress counts are inconsistent")
    if counts["duplicate_push_and_pull_request_exposure_count"] != sum(
            1 for row in rows if row["duplicate_push_and_pull_request_exposure"]):
        raise AuditError("duplicate-trigger exposure count is inconsistent")
    if counts["active_automatic_workflow_count"] != len(rows):
        raise AuditError("decision table does not cover the active workflows")
    surface = decision["change_surface"]
    for key in ("repository_write_surface_expanded", "publication_surface_expanded",
                "scientific_surface_expanded", "project_state_consistency_modified"):
        if surface.get(key) is not False:
            raise AuditError(f"change surface widened: {key}")
    changed = bool(applied)
    for key in ("workflow_files_modified", "cancellation_surface_changed"):
        if surface.get(key) is not changed:
            raise AuditError(f"change surface flag does not match the applied change set: {key}")
    declared_workflows = surface.get("declared_workflow_changes", [])
    if declared_workflows != [change["path"] for change in applied]:
        raise AuditError("declared workflow changes do not match the applied change set")
    for path in declared_workflows:
        row = next((item for item in rows if item["path"] == path), None)
        if row is None or not row["fail_closed_safe"] or row["side_effect_class"] not in SAFE_SIDE_EFFECT_CLASSES:
            raise AuditError(f"declared workflow change is not fail-closed: {path}")
        if path in FROZEN_OUT_OF_SCOPE_WORKFLOWS:
            raise AuditError(f"frozen out-of-scope workflow cannot be declared: {path}")
        if row["recommendation_state"] != "SAFE_CANDIDATE_NOT_APPLIED":
            raise AuditError(f"declared workflow change was not an unapplied safe candidate: {path}")
    if not changed and any(path.startswith(".github/workflows/")
                           for path in surface.get("declared_change_scope", [])):
        raise AuditError("declared scope widens the workflow surface without an applied change")


def build() -> dict[str, Any]:
    inventory_text = (ROOT / INVENTORY).read_text()
    document = json.loads(inventory_text)
    rows = {r["path"]: r for r in document["workflows"]}
    present = {p.relative_to(ROOT).as_posix() for p in (ROOT / ".github/workflows").glob("*.y*ml")}
    missing = set(rows) - present
    if missing:
        raise AuditError(f"inventory workflows missing from checkout: {sorted(missing)}")
    absent = present - set(rows)
    if absent:
        raise AuditError(f"workflows absent from the regenerated inventory: {sorted(absent)}")
    active, manual_only = split_active(rows)
    for path in active:
        triggers = parse_triggers((ROOT / path).read_text().splitlines())
        if not automatic(triggers):
            raise AuditError(f"{path}: active workflow has no automatic trigger")
    for path in manual_only:
        triggers = parse_triggers((ROOT / path).read_text().splitlines())
        if set(triggers) != {"workflow_dispatch"}:
            raise AuditError(f"{path}: manual-only workflow declares non-manual triggers")
    before = [workflow(path, base_text(path), rows[path]) for path in active]
    after = [workflow(path, (ROOT / path).read_text(), rows[path]) for path in active]
    edges = []
    by_name = {row["name"]: row["path"] for row in after}
    if len(by_name) != len(after):
        raise AuditError("duplicate current workflow name makes workflow_run ambiguous")
    for row in after:
        for source in row["workflow_run_dependencies"]:
            if source not in by_name:
                raise AuditError(f"unresolved current workflow_run source: {source}")
            edges.append({"type": "workflow_run", "from_name": source,
                          "from_path": by_name[source], "to_path": row["path"]})
    simulations = [{"scenario": s[0], "before": simulate(before, s), "after": simulate(after, s)}
                   for s in SCENARIOS]
    data = {"schema": "poker-active-workflow-dag/v2", "issue": 382, "parent_issue": 204,
            "base_sha": BASE_SHA, "inventory_source": INVENTORY,
            "inventory_sha256": hashlib.sha256(inventory_text.encode()).hexdigest(),
            "inventory_snapshot_base_sha": document.get("snapshot_base_sha"),
            "inventory_workflow_count": len(rows),
            "active_definition": ("workflow file present at HEAD with at least one automatic trigger; "
                                  "the #373 manual-only historical workflows are excluded explicitly"),
            "active_workflow_count": len(after), "workflows": after,
            "excluded_manual_only_workflows": manual_only, "manual_only_count": len(manual_only),
            "workflow_run_edges": edges, "representative_scenario_count": len(simulations),
            "representative_scenarios": simulations,
            "aggregate": {"side_effect_classes": dict(Counter(r["side_effect_class"] for r in after)),
                "repro_statuses": dict(Counter(r["repro_status"] for r in after)),
                "job_count": sum(len(r["jobs"]) for r in after),
                "static_cost_proxy": sum(r["static_cost_proxy"]["score"] for r in after)},
            "simulation_contract": {"supported": "single-path push/pull_request filters, literal/*/** globs, branch filters, workflow_run name cascade",
                "unsupported": "arbitrary GitHub expressions are marked UNKNOWN; UNKNOWN side effects are never cancellation-safe"}}
    validate_data(data, set(active))
    return data


def validate_data(data: dict[str, Any], expected_current: set[str]) -> None:
    paths = [row.get("path") for row in data.get("workflows", [])]
    if len(paths) != len(set(paths)) or set(paths) != expected_current:
        raise AuditError("DAG omits, duplicates, or invents a lifecycle=current workflow")
    if data.get("active_workflow_count") != len(expected_current):
        raise AuditError("active workflow count is inconsistent")
    excluded = data.get("excluded_manual_only_workflows", [])
    if data.get("manual_only_count") != len(excluded) or set(excluded) & expected_current:
        raise AuditError("manual-only exclusion set is inconsistent")
    if data.get("inventory_workflow_count") != len(expected_current) + len(excluded):
        raise AuditError("active + manual-only does not cover the regenerated inventory")
    if data.get("representative_scenario_count") != len(SCENARIOS):
        raise AuditError("representative scenario set is incomplete")
    for row in data["workflows"]:
        recommendation = row.get("concurrency_recommendation", {})
        if (row.get("side_effect_class") in {"UNKNOWN", "REPOSITORY_WRITE", "PUBLICATION_CAPABLE"}
                and recommendation.get("safe_candidate_for_future_cancellation_change") is not False):
            raise AuditError(f"unsafe concurrency recommendation: {row.get('path')}")


def markdown(data: dict[str, Any], decision: dict[str, Any] | None = None) -> str:
    decision = decision if decision is not None else build_decision(data)
    out = ["# Active CI workflow DAG", "",
        f"Generated for issue #204 (DAG v2, originally #382) from base `{data['base_sha']}` against inventory snapshot "
        f"`{data.get('inventory_snapshot_base_sha')}`. This is a static model, not billed-minute telemetry.", "",
        f"Active workflows: **{data['active_workflow_count']}** (automatic triggers); manual-only excluded: "
        f"**{data['manual_only_count']}**; jobs: **{data['aggregate']['job_count']}**; "
        f"cost proxy: **{data['aggregate']['static_cost_proxy']}**.", "",
        "The active DAG is exactly the set of workflows carrying at least one automatic trigger "
        "(`push`, `pull_request`, `workflow_run`, ...). The #373 historical quarantine migrated the "
        "`workflow_dispatch`-only workflows to manual-only; they are listed as excluded below and never "
        "contribute to the active runs/jobs/cost counts.", "",
        "## Workflows", "",
        "| Workflow | Role | Triggers | Jobs | Side effect | REPRO | Concurrency |", "|---|---|---|---:|---|---|---|"]
    for row in data["workflows"]:
        conc = row["concurrency"]
        conc_text = (f"`{conc.get('group')}` / cancel={str(conc.get('cancel_in_progress')).lower()}"
                     if conc else "none")
        out.append(f"| `{row['path']}` | {row['role']} | {', '.join(row['triggers'])} | {len(row['jobs'])} | {row['side_effect_class']} | {row['repro_status']} | {conc_text} |")
    out += ["", "## Manual-only workflows excluded", "",
            "These workflows subscribe to `workflow_dispatch` only (historical evidence, quarantined by #373). "
            "They are outside the active DAG by construction.", ""]
    if data["excluded_manual_only_workflows"]:
        out += [f"- `{path}`" for path in data["excluded_manual_only_workflows"]]
    else:
        out.append("- None")
    out += ["", "## workflow_run edges", ""]
    if data["workflow_run_edges"]:
        out += [f"- `{e['from_path']}` → `{e['to_path']}`" for e in data["workflow_run_edges"]]
    else:
        out.append("- None")
    out += ["", "## Representative change simulations", "",
            "| Scenario | Event | Before runs/jobs/cost | After runs/jobs/cost | Write-capable jobs after | Status |",
            "|---|---|---:|---:|---:|---|"]
    for item in data["representative_scenarios"]:
        b, a = item["before"], item["after"]
        out.append(f"| {item['scenario']} | {a['event']} | {b['workflow_count']}/{b['job_count']}/{b['cost_proxy']} | {a['workflow_count']}/{a['job_count']}/{a['cost_proxy']} | {len(a['write_capable_jobs_potentially_reachable'])} | {a['simulation_disposition']} |")
    out += ["", "This tranche is audit-only: the pinned base and HEAD carry byte-identical workflow definitions, so the",
            "`before`/`after` columns coincide by construction. The scenario model itself is unchanged and stays fail-closed;",
            "a future tranche that edits triggers or concurrency must re-pin the base to observe a delta."]
    out += ["", "## Concurrency recommendations", "",
            "Recommendations are read-only. `UNKNOWN`, repository-write, and publication-capable workflows are never marked safe.", "",
            "| Workflow | Has concurrency | Concurrency group | Cancel now | Fail-closed safe (yes/no) | Recommendation state | Blockers |",
            "|---|---:|---|---:|---:|---|---|"]
    for row in decision["workflows"]:
        group = row["concurrency_group"]
        group_text = f"`{group}`" if group else "none"
        blockers = "; ".join(row["blockers"]) or "none"
        out.append(f"| `{row['path']}` | {str(row['has_concurrency']).lower()} | {group_text} | "
                   f"{row['cancel_in_progress']} | {'yes' if row['fail_closed_safe'] else 'no'} | "
                   f"{row['recommendation_state']} | {blockers} |")
    out += ["", "## Concurrency consolidation decision", "",
            f"Decision: **{decision['decision']}** (fail-closed; no workflow file is modified in this tranche).",
            "", decision["decision_statement"], "",
            f"Method: {decision['measurement_method']['statement']}", "",
            "| Measure | Value |", "|---|---:|",
            f"| Inventory workflows | {decision['counts']['inventory_workflow_count']} |",
            f"| Active automatic workflows | {decision['counts']['active_automatic_workflow_count']} |",
            f"| Manual-only workflows excluded | {decision['counts']['manual_only_count']} |",
            f"| Active workflows without a concurrency block | {decision['counts']['without_concurrency_count']} |",
            f"| Active workflows with `cancel-in-progress: true` | {decision['counts']['cancel_in_progress_true_count']} |",
            f"| Active workflows with `cancel-in-progress: false` | {decision['counts']['cancel_in_progress_false_count']} |",
            f"| Active workflows exposed to a same-ref push+pull_request duplicate | "
            f"{decision['counts']['duplicate_push_and_pull_request_exposure_count']} |",
            f"| Fail-closed safe candidates left unapplied | {decision['counts']['safe_candidate_not_applied_count']} |",
            f"| Blocked recommendations left unapplied | {decision['counts']['blocked_not_applied_count']} |",
            "", "### Planner estimate reconciliation", "",
            "The planner key T4 estimate is reconciled against the HEAD measurements; no delta changes the decision.", "",
            "| Measure | Planner estimate | Measured at HEAD | Delta |", "|---|---:|---:|---:|"]
    measured_key = {"active_automatic": "active_automatic_workflow_count", "manual_only": "manual_only_count",
                    "without_concurrency": "without_concurrency_count",
                    "cancel_in_progress_true": "cancel_in_progress_true_count"}
    for key, value in decision["planner_estimate"].items():
        out.append(f"| {key} | {value} | {decision['counts'][measured_key[key]]} | "
                   f"{decision['planner_estimate_delta'][key]} |")
    out += ["", "Notes:", ""]
    out += [f"- {note}" for note in decision["planner_estimate_notes"]]
    out += ["", "### Unapplied recommendations and blockers", "",
            "Every concurrency recommendation stays unapplied. `safe=yes` means only that the workflow has no "
            "repository-write, publication or unknown capability; it is not an asserted improvement.", ""]
    unapplied = [row for row in decision["workflows"]
                 if row["recommendation_state"] != "ALREADY_CANCEL_IN_PROGRESS"]
    if unapplied:
        out += ["| Workflow | Proposed change | Safe (yes/no) | Blockers |", "|---|---|---:|---|"]
        for row in unapplied:
            out.append(f"| `{row['path']}` | {row['proposed_change']} | "
                       f"{'yes' if row['fail_closed_safe'] else 'no'} | "
                       f"{', '.join(f'`{code}`' for code in row['blockers'])} |")
        out += ["", "Blocker catalog:", "", "| Code | Meaning |", "|---|---|"]
        out += [f"| `{code}` | {text} |" for code, text in sorted(decision["blocker_catalog"].items())]
    else:
        out.append("- None")
    out += ["", "### Representative before/after totals", "",
            f"Scenario-set sums across the {decision['scenario_count']} representative scenarios (a workflow may be "
            f"matched by several scenarios): before "
            f"{decision['totals']['before']['runs']}/{decision['totals']['before']['jobs']}/"
            f"{decision['totals']['before']['cost_proxy']} vs after "
            f"{decision['totals']['after']['runs']}/{decision['totals']['after']['jobs']}/"
            f"{decision['totals']['after']['cost_proxy']} runs/jobs/cost proxy "
            f"(delta {decision['totals']['delta']['runs']}/{decision['totals']['delta']['jobs']}/"
            f"{decision['totals']['delta']['cost_proxy']}). Static structural proxy, not GitHub-billed minutes.", "",
            f"Method sensitivity: the proxy inputs are `{', '.join(decision['method_sensitivity']['proxy_inputs'])}`; "
            f"concurrency-sensitive inputs: `{decision['method_sensitivity']['concurrency_sensitive_inputs']}`. "
            "A concurrency-only edit therefore cannot move the measured figures, which is why no improvement is "
            "claimed and no change is applied.", "",
            f"Job and artifact names are preserved and digest-pinned (`{decision['frozen_name_digest']}`); the "
            "declared change surface contains no `.github/workflows/**` file, no write/publication/scientific "
            f"widening, and never touches `{FROZEN_OUT_OF_SCOPE_WORKFLOWS[0]}`.", ""]
    out += ["## Static-model boundary", "",
            "Path and branch filtering uses the documented literal/`*`/`**` subset. Complex job expressions are reported as `UNKNOWN`; they are retained as potentially reachable and never used to claim safety.", ""]
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        data = build(); decision = build_decision(data); doc = markdown(data, decision)
        if args.check:
            stored = json.loads((ROOT / OUTPUT).read_text())
            stored_decision = json.loads((ROOT / DECISION).read_text())
            if stored != data or stored_decision != decision or (ROOT / DOC).read_text() != doc:
                raise AuditError("generated DAG evidence/docs are stale")
        else:
            (ROOT / OUTPUT).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
            (ROOT / DECISION).write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n")
            (ROOT / DOC).write_text(doc)
        print(f"Active workflow DAG: PASS ({data['active_workflow_count']} workflows; {len(SCENARIOS)} scenarios; "
              f"decision={decision['decision']})")
        return 0
    except (AuditError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Active workflow DAG: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
