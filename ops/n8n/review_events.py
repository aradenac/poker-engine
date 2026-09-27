#!/usr/bin/env python3
"""Collect and acknowledge actionable GitHub pull-request review events.

The ledger is deliberately independent from issue-comment watermarks: GitHub IDs
from reviews, review comments and issue comments are not a shared ordered stream.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any


ACTIONABLE_REVIEW = re.compile(
    r"\b(?:NEEDS[_ -]?FIXES|REQUEST[_ -]?CHANGES|REWORK)\b"
    r"|(?:^|\n)\s*(?:#{1,6}\s*)?(?:VERDICT\s*[:—-]\s*)?(?:BLOCKING|BLOCKER)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _gh_json(args: list[str]) -> Any:
    completed = subprocess.run(
        ["gh", *args], check=True, text=True, capture_output=True
    )
    return json.loads(completed.stdout)


def _fingerprint(event: dict[str, Any]) -> str:
    stable = {
        key: event.get(key)
        for key in (
            "kind",
            "id",
            "state",
            "body",
            "commit_id",
            "updated_at",
            "path",
            "line",
            "thread_id",
            "thread_resolved",
        )
    }
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _load_ledger(path: Path, pr_number: int) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "pr_number": pr_number, "processed": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or data.get("pr_number") != pr_number:
        raise ValueError("review ledger identity mismatch")
    if not isinstance(data.get("processed"), dict):
        raise ValueError("review ledger processed map is invalid")
    return data


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
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


def _reviews(repo: str, pr_number: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_number = 1
    while True:
        page = _gh_json(
            ["api", f"/repos/{repo}/pulls/{pr_number}/reviews?per_page=100&page={page_number}"]
        )
        if not isinstance(page, list):
            raise ValueError("GitHub reviews response is not an array")
        rows.extend(page)
        if len(page) < 100:
            break
        page_number += 1
    events: list[dict[str, Any]] = []
    for row in rows:
        body = str(row.get("body") or "")
        state = str(row.get("state") or "").upper()
        actionable = state == "CHANGES_REQUESTED" or (
            state == "COMMENTED" and bool(ACTIONABLE_REVIEW.search(body))
        )
        event = {
            "kind": "review",
            "id": int(row["id"]),
            "author": ((row.get("user") or {}).get("login") or "unknown"),
            "state": state,
            "body": body,
            "commit_id": row.get("commit_id"),
            "created_at": row.get("submitted_at"),
            "updated_at": row.get("submitted_at"),
            "url": row.get("html_url"),
            "actionable": actionable,
        }
        event["event_key"] = f"review:{event['id']}"
        event["fingerprint"] = _fingerprint(event)
        events.append(event)
    return events


THREAD_QUERY = """
query($owner:String!,$name:String!,$number:Int!,$cursor:String) {
  repository(owner:$owner,name:$name) {
    pullRequest(number:$number) {
      reviewThreads(first:100,after:$cursor) {
        nodes {
          id
          isResolved
          comments(first:100) {
            nodes {
              databaseId
              body
              createdAt
              updatedAt
              url
              path
              line
              author { login }
              commit { oid }
            }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
""".strip()


def _review_comments(repo: str, pr_number: int) -> list[dict[str, Any]]:
    owner, name = repo.split("/", 1)
    cursor: str | None = None
    events: list[dict[str, Any]] = []
    while True:
        args = [
            "api",
            "graphql",
            "-f",
            f"query={THREAD_QUERY}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"number={pr_number}",
        ]
        if cursor:
            args.extend(["-F", f"cursor={cursor}"])
        payload = _gh_json(args)
        threads = payload["data"]["repository"]["pullRequest"]["reviewThreads"]
        for thread in threads.get("nodes") or []:
            resolved = bool(thread.get("isResolved"))
            for row in ((thread.get("comments") or {}).get("nodes") or []):
                body = str(row.get("body") or "")
                event = {
                    "kind": "review_comment",
                    "id": int(row["databaseId"]),
                    "author": ((row.get("author") or {}).get("login") or "unknown"),
                    "state": "RESOLVED" if resolved else "UNRESOLVED",
                    "body": body,
                    "commit_id": ((row.get("commit") or {}).get("oid")),
                    "created_at": row.get("createdAt"),
                    "updated_at": row.get("updatedAt"),
                    "url": row.get("url"),
                    "path": row.get("path"),
                    "line": row.get("line"),
                    "thread_id": thread.get("id"),
                    "thread_resolved": resolved,
                    "actionable": bool(body.strip()) and not resolved,
                }
                event["event_key"] = f"review_comment:{event['id']}"
                event["fingerprint"] = _fingerprint(event)
                events.append(event)
        page = threads.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")
        if not cursor:
            raise RuntimeError("GitHub review thread pagination cursor missing")
    return events


def collect(repo: str, pr_number: int, ledger_path: Path, current_head: str) -> dict[str, Any]:
    ledger = _load_ledger(ledger_path, pr_number)
    processed = ledger["processed"]
    all_events = _reviews(repo, pr_number) + _review_comments(repo, pr_number)
    all_events.sort(key=lambda item: (str(item.get("updated_at") or ""), item["event_key"]))
    pending: list[dict[str, Any]] = []
    ignored_changed = False
    for event in all_events:
        old = processed.get(event["event_key"])
        if old and old.get("fingerprint") == event["fingerprint"]:
            continue
        if event["actionable"]:
            event["targets_current_head"] = bool(
                current_head and event.get("commit_id") == current_head
            )
            pending.append(event)
            continue
        processed[event["event_key"]] = {
            "fingerprint": event["fingerprint"],
            "outcome": "IGNORED_NON_ACTIONABLE",
            "updated_at": event.get("updated_at"),
        }
        ignored_changed = True
    if ignored_changed:
        _atomic_write(ledger_path, ledger)
    return {
        "status": "OK",
        "pr_number": pr_number,
        "current_head": current_head,
        "pending_events": pending,
        "has_actionable_reviews": bool(pending),
        "ledger_path": str(ledger_path),
    }


def acknowledge(ledger_path: Path, pr_number: int, events: list[dict[str, Any]], outcome: str) -> dict[str, Any]:
    ledger = _load_ledger(ledger_path, pr_number)
    for event in events:
        ledger["processed"][event["event_key"]] = {
            "fingerprint": event["fingerprint"],
            "outcome": outcome,
            "updated_at": event.get("updated_at"),
            "commit_id": event.get("commit_id"),
        }
    _atomic_write(ledger_path, ledger)
    return {"status": "OK", "acknowledged": len(events), "outcome": outcome}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("--repo", required=True)
    collect_parser.add_argument("--pr", required=True, type=int)
    collect_parser.add_argument("--ledger", required=True, type=Path)
    collect_parser.add_argument("--current-head", default="")
    ack_parser = sub.add_parser("ack")
    ack_parser.add_argument("--ledger", required=True, type=Path)
    ack_parser.add_argument("--pr", required=True, type=int)
    ack_source = ack_parser.add_mutually_exclusive_group(required=True)
    ack_source.add_argument("--events-file", type=Path)
    ack_source.add_argument("--events-b64")
    ack_parser.add_argument("--outcome", default="PLANNED")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "collect":
            result = collect(args.repo, args.pr, args.ledger, args.current_head)
        else:
            if args.events_b64:
                events = json.loads(base64.b64decode(args.events_b64).decode())
            else:
                events = json.loads(args.events_file.read_text(encoding="utf-8"))
            if not isinstance(events, list):
                raise ValueError("events file must contain a JSON array")
            result = acknowledge(args.ledger, args.pr, events, args.outcome)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "reason": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
