#!/usr/bin/env python3
"""Rebase a managed issue worktree and resolve bounded conflicts via an agent.

The agent may edit conflict files, but this program alone stages files and
continues the rebase. It never pushes; the workflow's force-with-lease gate
remains responsible for updating the remote branch.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any


def _run(repo: Path, args: list[str], *, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        text=True,
        capture_output=True,
        env=env,
    )


def _paths(repo: Path, args: list[str]) -> set[str]:
    raw = subprocess.run(
        ["git", "-C", str(repo), *args, "-z"],
        check=True,
        capture_output=True,
    ).stdout
    return {part.decode(errors="surrogateescape") for part in raw.split(b"\0") if part}


def _agent(repo: Path, issue_dir: Path, conflict_paths: set[str], attempt: int) -> dict[str, Any]:
    diff = _run(repo, ["diff", "--cc", "--", *sorted(conflict_paths)], check=False).stdout
    prompt = {
        "role": "REBASE_CONFLICT_RESOLVER",
        "instructions": [
            "Resolve the current git rebase conflict semantically.",
            "Edit only the listed conflicted files.",
            "Do not run git add, git commit, git rebase, git reset, git checkout, git push, or git clean.",
            "Preserve valid behavior from both sides and run focused read-only tests when practical.",
            "Remove every conflict marker. Return a concise summary when done.",
        ],
        "conflicted_files": sorted(conflict_paths),
        "conflict_diff": diff[-50000:],
    }
    audit = issue_dir / "run" / "rebase" / f"attempt-{attempt}"
    audit.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        json.dump(prompt, handle, ensure_ascii=False, indent=2)
        prompt_path = Path(handle.name)
    try:
        completed = subprocess.run(
            [
                "python3",
                "/home/abel/.config/poker-engine-orchestrator/run-agent-fallback.py",
                "--manifest",
                "/home/abel/.config/poker-engine-orchestrator/agents.json",
                "--role",
                "worker",
                "--prompt-file",
                str(prompt_path),
                "--cwd",
                str(repo),
                "--audit-dir",
                str(audit),
                "--mode",
                "write",
                "--timeout-seconds",
                "1200",
                "--max-attempts",
                "3",
            ],
            text=True,
            capture_output=True,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout[-12000:],
            "stderr": completed.stderr[-12000:],
        }
    finally:
        prompt_path.unlink(missing_ok=True)


def _has_markers(repo: Path, paths: set[str]) -> list[str]:
    offenders: list[str] = []
    marker = re.compile(r"^(?:<<<<<<<|=======|>>>>>>>)", re.MULTILINE)
    for relative in sorted(paths):
        path = repo / relative
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if marker.search(text):
                offenders.append(relative)
    return offenders


def _changed_paths(repo: Path) -> set[str]:
    return (
        _paths(repo, ["diff", "--name-only"])
        | _paths(repo, ["diff", "--cached", "--name-only"])
        | _paths(repo, ["ls-files", "--others", "--exclude-standard"])
    )


def _content_snapshot(repo: Path, paths: set[str]) -> dict[str, str | None]:
    snapshot: dict[str, str | None] = {}
    for relative in sorted(paths):
        path = repo / relative
        if path.is_symlink():
            snapshot[relative] = "symlink:" + os.readlink(path)
        elif path.is_file():
            snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            snapshot[relative] = None
    return snapshot


def resolve(repo: Path, issue_dir: Path, branch: str, max_conflicts: int, attempts_per_conflict: int) -> dict[str, Any]:
    if _run(repo, ["status", "--porcelain", "--untracked-files=all"]).stdout.strip():
        raise RuntimeError("managed worktree is dirty before rebase")
    current_branch = _run(repo, ["branch", "--show-current"]).stdout.strip()
    if current_branch != branch:
        raise RuntimeError(f"wrong branch: {current_branch!r}, expected {branch!r}")
    _run(repo, ["fetch", "origin", "main", "--quiet"])
    remote = _run(repo, ["ls-remote", "--heads", "origin", branch]).stdout.split()
    expected_remote_head = remote[0] if remote else ""
    if expected_remote_head:
        _run(repo, ["fetch", "origin", branch, "--quiet"])
    original_head = _run(repo, ["rev-parse", "HEAD"]).stdout.strip()
    main_head = _run(repo, ["rev-parse", "origin/main"]).stdout.strip()
    snapshot = "refs/n8n/recovery/" + re.sub(r"[^A-Za-z0-9._/-]", "-", branch) + "-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    _run(repo, ["update-ref", snapshot, original_head])
    if _run(repo, ["merge-base", "origin/main", "HEAD"]).stdout.strip() != main_head:
        started = _run(repo, ["rebase", "origin/main"], check=False)
        if started.returncode != 0:
            for conflict_index in range(1, max_conflicts + 1):
                conflicts = _paths(repo, ["diff", "--name-only", "--diff-filter=U"])
                if not conflicts:
                    _run(repo, ["rebase", "--abort"], check=False)
                    raise RuntimeError("rebase failed without unmerged paths")
                conflict_head = _run(repo, ["rev-parse", "HEAD"]).stdout.strip()
                baseline_changed = _changed_paths(repo)
                baseline_outside = baseline_changed - conflicts
                baseline_outside_content = _content_snapshot(repo, baseline_outside)
                baseline_index = _run(repo, ["diff", "--cached", "--binary"], check=False).stdout
                resolved = False
                diagnostics: list[dict[str, Any]] = []
                for attempt in range(1, attempts_per_conflict + 1):
                    result = _agent(repo, issue_dir, conflicts, conflict_index * 10 + attempt)
                    diagnostics.append(result)
                    if _run(repo, ["rev-parse", "HEAD"]).stdout.strip() != conflict_head:
                        _run(repo, ["rebase", "--abort"], check=False)
                        raise RuntimeError("resolver changed HEAD")
                    outside = _changed_paths(repo) - conflicts
                    outside_changed = (
                        outside != baseline_outside
                        or _content_snapshot(repo, baseline_outside) != baseline_outside_content
                        or _run(repo, ["diff", "--cached", "--binary"], check=False).stdout != baseline_index
                    )
                    markers = _has_markers(repo, conflicts)
                    if result["returncode"] == 0 and not outside_changed and not markers:
                        resolved = True
                        break
                if not resolved:
                    _run(repo, ["rebase", "--abort"], check=False)
                    raise RuntimeError(
                        "conflict resolution exhausted: "
                        + json.dumps({"paths": sorted(conflicts), "diagnostics": diagnostics}, ensure_ascii=False)
                    )
                _run(repo, ["add", "-A", "--", *sorted(conflicts)])
                env = dict(os.environ)
                env["GIT_EDITOR"] = "true"
                continued = _run(repo, ["rebase", "--continue"], check=False, env=env)
                if continued.returncode == 0:
                    break
            else:
                _run(repo, ["rebase", "--abort"], check=False)
                raise RuntimeError("maximum conflict count exceeded")
    reviewed_head = _run(repo, ["rev-parse", "HEAD"]).stdout.strip()
    reviewed_main = _run(repo, ["rev-parse", "origin/main"]).stdout.strip()
    if _run(repo, ["merge-base", "origin/main", "HEAD"]).stdout.strip() != reviewed_main:
        raise RuntimeError("branch is not based on current main after rebase")
    inner = {
        "branch": branch,
        "reviewed_head": reviewed_head,
        "reviewed_main": reviewed_main,
        "expected_remote_head": expected_remote_head,
        "snapshot_ref": snapshot,
    }
    return {"status": "OK", "stage": "REVIEW_SYNC", "exit_code": 0, "stdout": json.dumps(inner), "stderr": ""}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--issue-dir", required=True, type=Path)
    parser.add_argument("--branch")
    parser.add_argument("--max-conflicts", type=int, default=5)
    parser.add_argument("--attempts-per-conflict", type=int, default=2)
    args = parser.parse_args()
    try:
        branch = args.branch or _run(args.repo, ["branch", "--show-current"]).stdout.strip()
        result = resolve(args.repo, args.issue_dir, branch, args.max_conflicts, args.attempts_per_conflict)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "stage": "REVIEW_SYNC", "reason": "REVIEW_SYNC_FAILED", "message": str(exc)}, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
