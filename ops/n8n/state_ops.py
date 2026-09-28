#!/usr/bin/env python3
"""Safe state transitions and GitHub worklog updates for n8n workflows."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any


OPEN = "<!-- n8n-claim:v1 -->"
CLOSE = "<!-- /n8n-claim:v1 -->"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _gh(args: list[str], stdin: str | None = None) -> str:
    return subprocess.run(
        ["gh", *args], input=stdin, text=True, capture_output=True, check=True
    ).stdout


def _update_claim(repo: str, claim_id: int, now: str) -> None:
    if claim_id <= 0:
        return
    body = _gh(["api", f"/repos/{repo}/issues/comments/{claim_id}", "--jq", ".body"])
    start = body.find(OPEN)
    end = body.find(CLOSE, start + len(OPEN))
    if start < 0 or end < 0:
        raise ValueError("claim comment delimiters missing")
    claim = json.loads(body[start + len(OPEN) : end].strip())
    claim.update({"status": "NEEDS_HUMAN", "phase": "NEEDS_HUMAN", "heartbeat_at": now})
    new_body = f"{OPEN}\n{json.dumps(claim, ensure_ascii=False, indent=2)}\n{CLOSE}\n"
    _gh(
        ["api", "--method", "PATCH", f"/repos/{repo}/issues/comments/{claim_id}", "--input", "-"],
        json.dumps({"body": new_body}, ensure_ascii=False),
    )


def mark_needs_human(payload: dict[str, Any]) -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    pointer = Path(payload["pointer"])
    current = json.loads(pointer.read_text(encoding="utf-8")) if pointer.exists() else {}
    phase = str(payload.get("phase") or "INTEGRATION_FAILED_NEEDS_HUMAN")
    current.update(
        {
            "phase": phase,
            "phase_updated_at": now,
            "terminal_reason": str(payload["reason"]),
        }
    )
    if isinstance(payload.get("merge_gate_context"), dict):
        current["merge_gate_context"] = payload["merge_gate_context"]
    _atomic_json(pointer, current)
    body = (
        "agent-worklog:v1\n\n"
        f"Issue Integration v8 could not complete integration (blocked at stage: {payload['stage']}). "
        "Left for human triage.\n\nNEEDS_HUMAN"
    )
    _gh(["issue", "comment", str(int(payload["issue_number"])), "--repo", payload["repo"], "--body", body])
    claim_error = None
    try:
        _update_claim(payload["repo"], int(payload.get("claim_comment_id") or 0), now)
    except Exception as exc:  # state is durable even if the advisory claim update fails
        claim_error = str(exc)
    return {"status": "OK", "phase": current["phase"], "claim_warning": claim_error}


def resume(payload: dict[str, Any]) -> dict[str, Any]:
    pointer = Path(payload["pointer"])
    if not pointer.exists():
        raise FileNotFoundError(pointer)
    current = json.loads(pointer.read_text(encoding="utf-8"))
    mode = payload["mode"]
    if mode == "ci" and not isinstance(current.get("merge_gate_context"), dict):
        raise ValueError("CI resume requires merge_gate_context")
    phase = "CI_PENDING" if mode == "ci" else "INTEGRATION_RETRY"
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    current.update(
        {
            "phase": phase,
            "phase_updated_at": now,
            "terminal_reason": None,
            "recovery_attempt": 0,
            "active_task_id": None,
            "active_execution_id": None,
        }
    )
    _atomic_json(pointer, current)
    return {"status": "OK", "phase": phase, "pointer": str(pointer)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["mark-needs-human", "resume"])
    parser.add_argument("--payload-b64", required=True)
    args = parser.parse_args()
    try:
        payload = json.loads(base64.b64decode(args.payload_b64).decode())
        result = mark_needs_human(payload) if args.command == "mark-needs-human" else resume(payload)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "reason": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
