#!/usr/bin/env python3
"""Fail-closed validation for the deployed n8n review hardening."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys


DB = Path("/home/abel/.n8n/database.sqlite")
IDS = {
    "planning": "wQvUWKRWFjwQvVEd",
    "integration": "qoLuUYV7PeiAJpxn",
    "ci": "B8Hxpq5HCUKjhnwQ",
    "dispatcher": "7U3ji3e7qXSAw9Go",
    "pipeline": "1AbV6ckDpTZLPvm0",
}


def main() -> int:
    errors: list[str] = []
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    workflows: dict[str, dict] = {}
    for label, workflow_id in IDS.items():
        row = con.execute(
            "select name,active,versionId,activeVersionId,nodes,connections from workflow_entity where id=?",
            (workflow_id,),
        ).fetchone()
        if not row:
            errors.append(f"{label}: workflow missing")
            continue
        if not row["active"]:
            errors.append(f"{label}: workflow inactive")
        if row["versionId"] != row["activeVersionId"]:
            errors.append(f"{label}: current version is not active")
        workflows[label] = {
            "nodes": {node["name"]: node for node in json.loads(row["nodes"])},
            "connections": json.loads(row["connections"]),
        }
    con.close()

    if "ci" in workflows:
        nodes = workflows["ci"]["nodes"]
        collect = nodes.get("Build comment watch", {}).get("parameters", {}).get("jsCode", "")
        for marker in ("review_events.py collect", "review-events.json", "--current-head"):
            if marker not in collect:
                errors.append(f"ci: review collector missing {marker}")
        if "/issues/$pr/comments" in collect or "/issues/$issue/comments" in collect:
            errors.append("ci: legacy issue-comment corrective watcher remains")
        for required in (
            "Validate corrective review coverage",
            "Build review acknowledgement",
            "Acknowledge review events",
            "Parse review acknowledgement",
        ):
            if required not in nodes:
                errors.append(f"ci: node {required} missing")
        coverage = nodes.get("Validate corrective review coverage", {}).get("parameters", {}).get("jsCode", "")
        if "CORRECTIVE_COVERAGE_EMPTY" not in coverage:
            errors.append("ci: empty corrective plans do not fail closed")

    if "planning" in workflows:
        planner = workflows["planning"]["nodes"].get("Plan task / rework resolution", {}).get("parameters", {}).get("jsCode", "")
        if "corrective_review_events est autoritatif" not in planner or "[ALREADY_SATISFIED]" not in planner:
            errors.append("planning: review coverage contract missing")

    if "integration" in workflows:
        nodes = workflows["integration"]["nodes"]
        sync = nodes.get("Build sync", {}).get("parameters", {}).get("jsCode", "")
        if "rebase_resolver.py" not in sync:
            errors.append("integration: bounded rebase resolver missing")
        push = nodes.get("Build safe PR push", {}).get("parameters", {}).get("jsCode", "")
        if "--force-with-lease=" not in push or "REMOTE_BRANCH_MOVED_AFTER_REVIEW" not in push:
            errors.append("integration: protected force push guard missing")
        needs_human = nodes.get("Build NEEDS_HUMAN update", {}).get("parameters", {}).get("jsCode", "")
        if "state_ops.py mark-needs-human" not in needs_human or "Buffer.from" not in needs_human:
            errors.append("integration: shell-safe state transition missing")

    for label in ("dispatcher", "pipeline", "integration", "ci"):
        if label not in workflows:
            continue
        raw = json.dumps(workflows[label]["nodes"], ensure_ascii=False)
        if "sed -n '/<!-- n8n-claim:v1" in raw:
            errors.append(f"{label}: delimiter-fragile claim parser remains")

    for helper in ("review_events.py", "state_ops.py", "rebase_resolver.py"):
        path = Path("/home/abel/.config/poker-engine-orchestrator") / helper
        if not path.is_file():
            errors.append(f"installed helper missing: {path}")

    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
