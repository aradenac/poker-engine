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
from tools.audit_github_workflows import parse_concurrency, parse_jobs, parse_triggers

BASE_SHA = "ac208d26cbf3f16b498fd5333ad3b7c4fa58355b"
INVENTORY = "analysis/workflow_audit/workflows.json"
OUTPUT = "analysis/workflow_audit/active_workflow_dag_v2.json"
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


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True)


def base_text(path: str) -> str:
    return git("show", f"{BASE_SHA}:{path}")


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


def _cost(text: str, path: str, name: str, jobs: list[dict]) -> dict[str, Any]:
    patterns = {"checkout": r"actions/checkout@", "setup_python": r"actions/setup-python@",
        "setup_node": r"actions/setup-node@", "pip_install": r"(?:\bpip(?:3)?\s+install\b|python3?\s+-m\s+pip\s+install)",
        "playwright_install": r"playwright\s+install", "npm_install": r"\bnpm\s+(?:ci|install)\b",
        "upload_artifact": r"actions/upload-artifact@", "download_artifact": r"(?:actions/download-artifact@|\bgh\s+run\s+download\b)"}
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
        "path": path, "name": name, "lifecycle": "current", "role": inventory["role"],
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


def build() -> dict[str, Any]:
    inventory_text = base_text(INVENTORY)
    inventory = json.loads(inventory_text)
    current = {r["path"]: r for r in inventory["workflows"] if r["lifecycle"] == "current"}
    present = {p.relative_to(ROOT).as_posix() for p in (ROOT / ".github/workflows").glob("*.y*ml")}
    missing = set(current) - present
    if missing:
        raise AuditError(f"current workflows missing from checkout: {sorted(missing)}")
    before = [workflow(path, base_text(path), current[path]) for path in sorted(current)]
    after = [workflow(path, (ROOT / path).read_text(), current[path]) for path in sorted(current)]
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
    data = {"schema": "poker-active-workflow-dag/v2", "issue": 382,
            "base_sha": BASE_SHA, "inventory_source": INVENTORY,
            "inventory_sha256": hashlib.sha256(inventory_text.encode()).hexdigest(),
            "active_definition": "lifecycle=current in the Git-bound #242 inventory and file present",
            "active_workflow_count": len(after), "workflows": after,
            "workflow_run_edges": edges, "representative_scenario_count": len(simulations),
            "representative_scenarios": simulations,
            "aggregate": {"side_effect_classes": dict(Counter(r["side_effect_class"] for r in after)),
                "repro_statuses": dict(Counter(r["repro_status"] for r in after)),
                "job_count": sum(len(r["jobs"]) for r in after),
                "static_cost_proxy": sum(r["static_cost_proxy"]["score"] for r in after)},
            "simulation_contract": {"supported": "single-path push/pull_request filters, literal/*/** globs, branch filters, workflow_run name cascade",
                "unsupported": "arbitrary GitHub expressions are marked UNKNOWN; UNKNOWN side effects are never cancellation-safe"}}
    validate_data(data, set(current))
    return data


def validate_data(data: dict[str, Any], expected_current: set[str]) -> None:
    paths = [row.get("path") for row in data.get("workflows", [])]
    if len(paths) != len(set(paths)) or set(paths) != expected_current:
        raise AuditError("DAG omits, duplicates, or invents a lifecycle=current workflow")
    if data.get("active_workflow_count") != len(expected_current):
        raise AuditError("active workflow count is inconsistent")
    if data.get("representative_scenario_count") != len(SCENARIOS):
        raise AuditError("representative scenario set is incomplete")
    for row in data["workflows"]:
        recommendation = row.get("concurrency_recommendation", {})
        if (row.get("side_effect_class") in {"UNKNOWN", "REPOSITORY_WRITE", "PUBLICATION_CAPABLE"}
                and recommendation.get("safe_candidate_for_future_cancellation_change") is not False):
            raise AuditError(f"unsafe concurrency recommendation: {row.get('path')}")


def markdown(data: dict[str, Any]) -> str:
    out = ["# Active CI workflow DAG", "",
        f"Generated for issue #382 from base `{data['base_sha']}`. This is a static model, not billed-minute telemetry.", "",
        f"Active workflows: **{data['active_workflow_count']}**; jobs: **{data['aggregate']['job_count']}**; cost proxy: **{data['aggregate']['static_cost_proxy']}**.", "",
        "## Workflows", "",
        "| Workflow | Role | Triggers | Jobs | Side effect | REPRO | Concurrency |", "|---|---|---|---:|---|---|---|"]
    for row in data["workflows"]:
        conc = row["concurrency"]
        conc_text = (f"`{conc.get('group')}` / cancel={str(conc.get('cancel_in_progress')).lower()}"
                     if conc else "none")
        out.append(f"| `{row['path']}` | {row['role']} | {', '.join(row['triggers'])} | {len(row['jobs'])} | {row['side_effect_class']} | {row['repro_status']} | {conc_text} |")
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
    out += ["", "## Concurrency recommendations", "",
            "Recommendations are read-only. `UNKNOWN`, repository-write, and publication-capable workflows are never marked safe.", "",
            "| Workflow | Has concurrency | Cancel now | Safe future candidate | Blockers |", "|---|---:|---:|---:|---|"]
    for row in data["workflows"]:
        c = row["concurrency_recommendation"]
        out.append(f"| `{row['path']}` | {str(c['has_concurrency']).lower()} | {c['cancel_in_progress']} | {str(c['safe_candidate_for_future_cancellation_change']).lower()} | {', '.join(c['blockers']) or 'none'} |")
    out += ["", "## Static-model boundary", "",
            "Path and branch filtering uses the documented literal/`*`/`**` subset. Complex job expressions are reported as `UNKNOWN`; they are retained as potentially reachable and never used to claim safety.", ""]
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        data = build(); doc = markdown(data)
        if args.check:
            stored = json.loads((ROOT / OUTPUT).read_text())
            if stored != data or (ROOT / DOC).read_text() != doc:
                raise AuditError("generated DAG evidence/docs are stale")
        else:
            (ROOT / OUTPUT).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
            (ROOT / DOC).write_text(doc)
        print(f"Active workflow DAG: PASS ({data['active_workflow_count']} workflows; {len(SCENARIOS)} scenarios)")
        return 0
    except (AuditError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Active workflow DAG: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
