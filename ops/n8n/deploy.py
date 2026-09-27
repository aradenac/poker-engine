#!/usr/bin/env python3
"""Idempotently deploy the review-event and rebase hardening to n8n v8."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import urllib.request
import uuid


N8N = "http://localhost:5678/api/v1"
CI_GATE = "B8Hxpq5HCUKjhnwQ"
ISSUE_PLANNING = "wQvUWKRWFjwQvVEd"
ISSUE_INTEGRATION = "qoLuUYV7PeiAJpxn"
DISPATCHER = "7U3ji3e7qXSAw9Go"
ISSUE_PIPELINE = "1AbV6ckDpTZLPvm0"
INSTALL_DIR = Path("/home/abel/.config/poker-engine-orchestrator")
HELPERS = ("review_events.py", "state_ops.py", "rebase_resolver.py")


def request(key: str, method: str, path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        N8N + path,
        data=body,
        method=method,
        headers={"X-N8N-API-KEY": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def node(workflow: dict, name: str) -> dict:
    found = [item for item in workflow["nodes"] if item["name"] == name]
    if len(found) != 1:
        raise RuntimeError(f"expected exactly one node {name!r}, found {len(found)}")
    return found[0]


def code_node(template: dict, name: str, js_code: str, position: list[int]) -> dict:
    result = copy.deepcopy(template)
    result.update({"id": str(uuid.uuid4()), "name": name, "position": position})
    result["parameters"] = {"jsCode": js_code}
    return result


def execute_node(template: dict, name: str, position: list[int]) -> dict:
    result = copy.deepcopy(template)
    result.update({"id": str(uuid.uuid4()), "name": name, "position": position})
    result["parameters"] = {"command": "={{ $json.command }}", "jsCode": ""}
    return result


COLLECT_CODE = r"""const ctx = { ...$json };
const q = s => JSON.stringify(String(s));
const ledger = ctx.issue_dir + '/review-events.json';
const command = `python3 /home/abel/.config/poker-engine-orchestrator/review_events.py collect --repo aradenac/poker-engine --pr ${Number(ctx.pr_number)} --ledger ${q(ledger)} --current-head ${q(ctx.reviewed_head_sha || '')}`;
return [{ json: { ...ctx, review_ledger_path: ledger, command } }];"""

PARSE_COLLECT_CODE = r"""const ctx = $('Build comment watch').item.json;
if (Number($json.exitCode || 0) !== 0) throw new Error('REVIEW_EVENT_QUERY_FAILED: ' + String($json.stderr || $json.stdout || ''));
let result;
try { result = JSON.parse(String($json.stdout || '').trim()); } catch (_) { throw new Error('REVIEW_EVENT_OUTPUT_INVALID'); }
if (result.status !== 'OK' || !Array.isArray(result.pending_events)) throw new Error('REVIEW_EVENT_QUERY_INVALID');
const events = result.pending_events;
const comments = events.map(e => ({body:e.body || '', author:{login:e.author || 'unknown'}, createdAt:e.created_at || e.updated_at, url:e.url || '', review_event:e}));
return [{ json: { ...ctx, review_watch: result, has_new_comment: events.length > 0, new_comments: comments, corrective_review_events: events } }];"""

BUILD_CORRECTIVE_CODE = r"""const ctx = $json;
const events = Array.isArray(ctx.corrective_review_events) ? ctx.corrective_review_events : [];
const comments = events.map(e => ({ body: e.body || '', author: e.author || 'human', createdAt: e.created_at || e.updated_at || new Date().toISOString(), url:e.url || '', kind:e.kind, event_key:e.event_key, commit_id:e.commit_id || null, path:e.path || null, line:e.line || null }));
return [{ json: { issue_number: ctx.issue_number, run_id: ctx.run_id, backlog_dir: ctx.backlog_dir, worktree_root: ctx.worktree_root, claim_comment_id: ctx.claim_comment_id || 0, branch_template: ctx.branch_template || '', corrective: true, corrective_comments: comments, corrective_review_events: events, review_ledger_path:ctx.review_ledger_path, pr_number:ctx.pr_number, reviewed_head_sha:ctx.reviewed_head_sha } }];"""

VALIDATE_PLAN_CODE = r"""const plan = { ...$json };
const source = $('Build corrective plan call (from comment)').isExecuted ? $('Build corrective plan call (from comment)').item.json : {};
const events = Array.isArray(source.corrective_review_events) ? source.corrective_review_events : [];
const tasks = Array.isArray(plan.tasks) ? plan.tasks : [];
const anchored = events.some(e => e.targets_current_head === true);
const satisfied = String(plan.summary || '').includes('[ALREADY_SATISFIED]');
if (events.length && anchored && tasks.length === 0 && !satisfied) {
  plan.status = 'BLOCKED';
  plan.summary = 'CORRECTIVE_COVERAGE_EMPTY: actionable review targets current HEAD but planner produced no task or ALREADY_SATISFIED evidence';
}
return [{ json: { ...source, ...plan, corrective_review_events: events } }];"""

BUILD_ACK_CODE = r"""const ctx = { ...$json };
const events = Array.isArray(ctx.corrective_review_events) ? ctx.corrective_review_events : [];
if (!events.length) return [{json:{...ctx,command:"printf '%s' '{\"status\":\"OK\",\"acknowledged\":0}'"}}];
const encoded = Buffer.from(JSON.stringify(events), 'utf8').toString('base64');
const q = s => JSON.stringify(String(s));
const command = `python3 /home/abel/.config/poker-engine-orchestrator/review_events.py ack --ledger ${q(ctx.review_ledger_path)} --pr ${Number(ctx.pr_number)} --events-b64 ${q(encoded)} --outcome PLANNED`;
return [{json:{...ctx,command}}];"""

PARSE_ACK_CODE = r"""const ctx = $('Build review acknowledgement').item.json;
if (Number($json.exitCode || 0) !== 0) throw new Error('REVIEW_EVENT_ACK_FAILED: ' + String($json.stderr || $json.stdout || ''));
let ack; try { ack=JSON.parse(String($json.stdout || '').trim()); } catch (_) { throw new Error('REVIEW_EVENT_ACK_INVALID'); }
if (ack.status !== 'OK') throw new Error('REVIEW_EVENT_ACK_REJECTED');
return [{json:{...ctx,review_ack:ack}}];"""


def patch_ci_gate(workflow: dict) -> list[str]:
    changed: list[str] = []
    replacements = {
        "Build comment watch": COLLECT_CODE,
        "Parse comment watch": PARSE_COLLECT_CODE,
        "Build corrective plan call (from comment)": BUILD_CORRECTIVE_CODE,
    }
    for name, value in replacements.items():
        target = node(workflow, name)
        if target["parameters"].get("jsCode") != value:
            target["parameters"]["jsCode"] = value
            changed.append(name)

    names = {item["name"] for item in workflow["nodes"]}
    code_template = node(workflow, "Parse comment watch")
    exec_template = node(workflow, "Check for new comments")
    additions = [
        ("Validate corrective review coverage", code_node(code_template, "Validate corrective review coverage", VALIDATE_PLAN_CODE, [12320, 720])),
        ("Build review acknowledgement", code_node(code_template, "Build review acknowledgement", BUILD_ACK_CODE, [12720, 720])),
        ("Acknowledge review events", execute_node(exec_template, "Acknowledge review events", [12960, 720])),
        ("Parse review acknowledgement", code_node(code_template, "Parse review acknowledgement", PARSE_ACK_CODE, [13200, 720])),
    ]
    for name, item in additions:
        if name not in names:
            workflow["nodes"].append(item)
            changed.append(name)
    node(workflow, "Validate corrective review coverage")["parameters"]["jsCode"] = VALIDATE_PLAN_CODE
    node(workflow, "Build review acknowledgement")["parameters"]["jsCode"] = BUILD_ACK_CODE
    node(workflow, "Parse review acknowledgement")["parameters"]["jsCode"] = PARSE_ACK_CODE

    connections = workflow["connections"]
    connections["Call Issue Planning v8 (rework)"] = {"main": [[{"node": "Validate corrective review coverage", "type": "main", "index": 0}]]}
    connections["Validate corrective review coverage"] = {"main": [[{"node": "Replan READY?", "type": "main", "index": 0}]]}
    ready_outputs = connections["Replan READY?"]["main"]
    ready_outputs[0] = [{"node": "Build review acknowledgement", "type": "main", "index": 0}]
    connections["Build review acknowledgement"] = {"main": [[{"node": "Acknowledge review events", "type": "main", "index": 0}]]}
    connections["Acknowledge review events"] = {"main": [[{"node": "Parse review acknowledgement", "type": "main", "index": 0}]]}
    connections["Parse review acknowledgement"] = {"main": [[{"node": "Build re-fire Worker Dispatch payload", "type": "main", "index": 0}]]}
    return changed


PLANNER_RULES = """- En mode correctif de review PR, corrective_review_events est autoritatif. Chaque demande actionnable doit être couverte par au moins une tâche, ou par une preuve vérifiable dans summary préfixée [ALREADY_SATISFIED].\n- Une review visant le HEAD courant ne peut jamais produire tasks=[] avec [INTEGRATION_HANDOFF].\n- Référence event_key dans chaque tâche corrective afin de garantir la traçabilité.\n"""


def patch_planning(workflow: dict) -> list[str]:
    target = node(workflow, "Plan task / rework resolution")
    code = target["parameters"]["jsCode"]
    if "corrective_review_events est autoritatif" in code:
        return []
    marker = "Règles:\\n"
    if marker not in code:
        raise RuntimeError("Issue Planning prompt rules marker missing")
    target["parameters"]["jsCode"] = code.replace(marker, marker + PLANNER_RULES.replace("\n", "\\n"), 1)
    return [target["name"]]


SYNC_CODE = r"""const ctx = { ...$json };
const q = s => JSON.stringify(String(s));
const command = `python3 /home/abel/.config/poker-engine-orchestrator/rebase_resolver.py --repo ${q(ctx.issue_worktree)} --issue-dir ${q(ctx.issue_dir)} --max-conflicts 5 --attempts-per-conflict 2`;
return [{ json: { ...ctx, command } }];"""

NEEDS_HUMAN_CODE = r"""const ctx = { ...$json };
const blockedStage = ctx.review && ctx.review.status === 'BLOCKED' ? 'REVIEW' : (ctx.sync && ctx.sync.status !== 'OK' ? 'REVIEW_SYNC' : (ctx.evidence && ctx.evidence.status !== 'OK' ? 'EVIDENCE' : (ctx.push && ctx.push.status !== 'OK' ? 'PUSH' : (ctx.pr_result && ctx.pr_result.status !== 'OK' ? 'PR_OPERATION' : 'PLAN'))));
const payload = {repo:'aradenac/poker-engine',issue_number:Number(ctx.issue_number),pointer:String(ctx.issue_dir)+'/active_run.json',stage:blockedStage,reason:String(ctx.review?.summary || ctx.sync?.message || blockedStage),claim_comment_id:Number(ctx.claim_comment_id || 0)};
const encoded = Buffer.from(JSON.stringify(payload), 'utf8').toString('base64');
const command = `python3 /home/abel/.config/poker-engine-orchestrator/state_ops.py mark-needs-human --payload-b64 ${JSON.stringify(encoded)}`;
return [{ json: { ...ctx, command } }];"""


def patch_integration(workflow: dict) -> list[str]:
    changed: list[str] = []
    for name, value in (("Build sync", SYNC_CODE), ("Build NEEDS_HUMAN update", NEEDS_HUMAN_CODE)):
        target = node(workflow, name)
        if target["parameters"].get("jsCode") != value:
            target["parameters"]["jsCode"] = value
            changed.append(name)
    return changed


SED_CLAIM = "sed -n '/<!-- n8n-claim:v1 -->/,/<!-- \\/n8n-claim:v1 -->/p' | sed '1d;$d'"
AWK_CLAIM = "awk 'index($0,\"<!-- n8n-claim:v1 -->\"){inside=1;next} index($0,\"<!-- /n8n-claim:v1 -->\"){inside=0;exit} inside{print}'"


def patch_claim_parsers(workflow: dict) -> list[str]:
    changed: list[str] = []
    for item in workflow["nodes"]:
        parameters = item.get("parameters") or {}
        for key, value in list(parameters.items()):
            if isinstance(value, str) and SED_CLAIM in value:
                parameters[key] = value.replace(SED_CLAIM, AWK_CLAIM)
                changed.append(item["name"])
    return changed


def payload(workflow: dict) -> dict:
    return {
        "name": workflow["name"],
        "nodes": workflow["nodes"],
        "connections": workflow["connections"],
        "settings": workflow.get("settings", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-root", type=Path)
    args = parser.parse_args()
    key = os.environ.get("N8N_API_KEY")
    if not key:
        raise SystemExit("N8N_API_KEY is required")
    root = Path(__file__).resolve().parent
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = args.backup_root or Path(f"/home/abel/n8n-backups/review-hardening-{stamp}")
    specs = (
        (ISSUE_PLANNING, patch_planning),
        (ISSUE_INTEGRATION, patch_integration),
        (CI_GATE, patch_ci_gate),
        (DISPATCHER, patch_claim_parsers),
        (ISSUE_PIPELINE, patch_claim_parsers),
    )
    updated: list[dict] = []
    if args.apply:
        INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        for helper in HELPERS:
            shutil.copy2(root / helper, INSTALL_DIR / helper)
            (INSTALL_DIR / helper).chmod(0o755)
    for workflow_id, patcher in specs:
        before = request(key, "GET", f"/workflows/{workflow_id}")
        after = copy.deepcopy(before)
        changed = patcher(after)
        updated.append({"id": workflow_id, "name": before["name"], "changed_nodes": changed})
        if args.apply and changed:
            backup_root.mkdir(parents=True, exist_ok=True)
            (backup_root / f"{workflow_id}.before.json").write_text(json.dumps(before, ensure_ascii=False, indent=2) + "\n")
            result = request(key, "PUT", f"/workflows/{workflow_id}", payload(after))
            if before.get("active") and not result.get("active"):
                request(key, "POST", f"/workflows/{workflow_id}/activate")
            (backup_root / f"{workflow_id}.after.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "APPLIED" if args.apply else "DRY_RUN", "workflows": updated, "backup_root": str(backup_root)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
