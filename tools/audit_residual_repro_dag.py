#!/usr/bin/env python3
"""Git-bound, fail-closed contract for issue #382 (stdlib only)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = "ac208d26cbf3f16b498fd5333ad3b7c4fa58355b"
INVENTORY = "analysis/workflow_audit/workflows.json"
EVIDENCE = "analysis/workflow_audit/residual_repro_dag_before_after.json"
ACTIVE_EVIDENCE = "analysis/workflow_audit/active_workflow_dag_v2.json"
DOC = "docs/ci-workflow-dag.md"

DISPOSITIONS = {
    ".github/workflows/continuous-training-cycle.yml": "ALREADY_REPRO_STRONG",
    ".github/workflows/ingest-artifacts.yml": "MIGRATE_PYTHON_REPRO",
    ".github/workflows/materialize-certified-population.yml": "ALREADY_REPRO_STRONG",
    ".github/workflows/plan-ingested-cycle.yml": "ALREADY_REPRO_STRONG",
    ".github/workflows/population-certification.yml": "ALREADY_REPRO_STRONG",
    ".github/workflows/postflop-response-refit.yml": "MIGRATE_PYTHON_REPRO",
    ".github/workflows/preflop-search.yml": "MIGRATE_PYTHON_NODE_REPRO",
    ".github/workflows/user-artifact-bundle.yml": "ALREADY_REPRO_STRONG",
    ".github/workflows/hero-calculated-range-export.yml": "MIGRATE_PYTHON_NODE_REPRO",
    ".github/workflows/model-b-reveal-aware.yml": "MIGRATE_PYTHON_REPRO",
}
MIGRATED = tuple(p for p, d in DISPOSITIONS.items() if d.startswith("MIGRATE_"))
STRONG = tuple(p for p, d in DISPOSITIONS.items() if d == "ALREADY_REPRO_STRONG")
NODE = frozenset(p for p, d in DISPOSITIONS.items() if "NODE" in d)
ALLOWLIST = frozenset((*MIGRATED, "tools/audit_active_workflow_dag.py",
    "tools/audit_residual_repro_dag.py", "tests/ci/test_residual_repro_dag.py",
    ACTIVE_EVIDENCE, EVIDENCE, DOC))

# These are the versioned sources traversed by verify -> identity -> container.
REPRO_PATHS = (
    ".python-version", ".node-version", "tools/repro_ci_environment.py",
    "tools/repro_environment_identity.py", "tools/repro_container.py",
    "tools/repro_hardening.py", "tools/repro_environment.py",
    "reproducibility/environment.lock.json", "requirements.lock.txt",
    "package-lock.json", "reproducibility/os-base.lock.json",
    "reproducibility/container-base.lock.json",
    "reproducibility/Dockerfile.science",
    "reproducibility/system-packages.apt.txt",
    "reproducibility/apt-snapshot.lock.json",
    "reproducibility/system-packages.resolution.lock.json",
    "reproducibility/browser-identity.lock.json",
    "reproducibility/ubuntu-snapshot.sources",
)
PYTHON = "      - uses: actions/setup-python@v5\n        with:\n          python-version-file: '.python-version'\n"
NODE_SETUP = "      - uses: actions/setup-node@v4\n        with:\n          node-version-file: '.node-version'\n"
VERIFY = "python3 tools/repro_ci_environment.py verify"
OLD_PYTHON_311 = "      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.11'\n"
OLD_NODE_22 = "      - uses: actions/setup-node@v4\n        with:\n          node-version: '22'\n"


class AuditError(ValueError):
    pass


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True)


def baseline(path: str) -> str:
    return git("show", f"{BASE_SHA}:{path}")


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def blob(value: str) -> str:
    data = value.encode()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def paths_for(path: str) -> tuple[str, ...]:
    return REPRO_PATHS


def verify_step(path: str) -> str:
    suffix = " --require-node" if path in NODE else ""
    return f"      - name: Verify locked REPRO environment\n        run: {VERIFY}{suffix}\n"


def migrate(path: str, before: str) -> str:
    """Reconstruct the sole authorized byte transformation."""
    if path not in MIGRATED:
        raise AuditError(f"workflow is not migratable: {path}")
    addition = "".join(f"      - '{p}'\n" for p in paths_for(path))
    count = before.count("    paths:\n")
    if count == 0:
        raise AuditError(f"{path}: no path-filtered trigger")
    after = before.replace("    paths:\n", "    paths:\n" + addition)
    if path.endswith("ingest-artifacts.yml"):
        anchor = ("      - name: Checkout\n        uses: actions/checkout@v4\n"
                  "        with:\n          fetch-depth: 0\n")
        replacement = anchor + "\n" + PYTHON + "\n" + verify_step(path).rstrip("\n") + "\n"
        if before.count(anchor) != 1:
            raise AuditError(f"{path}: unexpected checkout anchor")
        after = after.replace(anchor, replacement)
    elif path.endswith("postflop-response-refit.yml"):
        anchor = "      - uses: actions/checkout@v4\n"
        after = after.replace(anchor, anchor + "\n" + PYTHON + "\n" + verify_step(path), 1)
    elif path.endswith("preflop-search.yml"):
        old = "      - uses: actions/setup-node@v4\n        with:\n          node-version: '22'\n"
        after = after.replace(old, PYTHON + NODE_SETUP + verify_step(path), 1)
    elif path.endswith("hero-calculated-range-export.yml"):
        old = ("      - uses: actions/setup-node@v4\n        with:\n          node-version: '22'\n"
               "      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.11'\n")
        after = after.replace(old, NODE_SETUP + PYTHON + verify_step(path), 1)
    elif path.endswith("model-b-reveal-aware.yml"):
        old = "      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.11'\n"
        after = after.replace(old, PYTHON + "\n" + verify_step(path), 1)
    if after == before:
        raise AuditError(f"{path}: migration was a no-op")
    return after


def check_workflow(path: str, before: str, after: str) -> None:
    disposition = DISPOSITIONS.get(path)
    if disposition is None:
        raise AuditError(f"workflow outside ten-workflow audit: {path}")
    expected = migrate(path, before) if path in MIGRATED else before
    if after != expected:
        raise AuditError(f"{path}: difference outside exact authorized migration")
    if path in STRONG:
        if "repro-scientific-environment.yml" not in after or "REPRO_ENVIRONMENT_IDENTITY_SHA256" not in after:
            raise AuditError(f"{path}: strong REPRO binding missing")
        return
    if after.count(PYTHON.rstrip()) != 1 or after.count(verify_step(path).rstrip()) != 1:
        raise AuditError(f"{path}: exact Python setup/verify missing")
    if after.count(NODE_SETUP.rstrip()) != int(path in NODE):
        raise AuditError(f"{path}: unexpected Node setup count")
    for token in ("continue-on-error: true", "|| true", "if: false"):
        if after.count(token) != before.count(token):
            raise AuditError(f"{path}: bypass surface changed: {token}")


def changed_files() -> list[str]:
    tracked = git("diff", "--name-only", BASE_SHA, "--").splitlines()
    untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
    return sorted({p for p in tracked + untracked
                   if "__pycache__" not in Path(p).parts and not p.endswith(".pyc")})


def check_scope(paths: list[str]) -> None:
    extra = set(paths) - ALLOWLIST
    if extra:
        raise AuditError(f"files outside exact allowlist: {sorted(extra)}")


def _job_blocks(text: str) -> dict[str, str]:
    match = re.search(r"^jobs:\s*$", text, re.M)
    if not match:
        raise AuditError("jobs section missing")
    body = text[match.end():]
    starts = list(re.finditer(r"^  ([A-Za-z_][\w-]*):\s*$", body, re.M))
    if not starts:
        raise AuditError("job parser found no jobs")
    return {m.group(1): body[m.start(): starts[i + 1].start() if i + 1 < len(starts) else len(body)]
            for i, m in enumerate(starts)}


def _strip_authorized(text: str, path: str) -> str:
    for p in paths_for(path):
        text = text.replace(f"      - '{p}'\n", "")
    text = text.replace(PYTHON, "").replace(NODE_SETUP, "").replace(verify_step(path), "")
    text = text.replace(OLD_PYTHON_311, "").replace(OLD_NODE_22, "")
    return "\n".join(line for line in text.splitlines() if line.strip()) + "\n"


def snapshot(path: str, text: str, *, migrated_view: bool) -> dict:
    normalized = _strip_authorized(text, path) if path in MIGRATED else text
    jobs = _job_blocks(text)
    top_permissions = re.search(r"^permissions:\n((?:  .+\n)+)", text, re.M)
    write_jobs = []
    for jid, body in jobs.items():
        effective = body if re.search(r"^    permissions:", body, re.M) else (top_permissions.group(0) if top_permissions else "")
        if re.search(r"contents:\s*write", effective):
            write_jobs.append(jid)
    artifacts = [line.strip() for line in text.splitlines()
                 if "actions/upload-artifact@" in line or "actions/download-artifact@" in line]
    return {
        "blob_sha": blob(text),
        "normalized_scientific_sha256": sha(normalized),
        "jobs": list(jobs),
        "permissions_raw": top_permissions.group(0).rstrip() if top_permissions else None,
        "concurrency_raw": _top_block(text, "concurrency"),
        "artifact_actions": artifacts,
        "write_jobs": write_jobs,
        "has_pull_request": bool(re.search(r"^  pull_request:", text, re.M)),
        "pr_reachable_write_jobs": _pr_write_jobs(path, text, write_jobs),
        "setup_python": text.count("actions/setup-python@"),
        "setup_node": text.count("actions/setup-node@"),
        "verify_calls": text.count(VERIFY),
    }


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


def _pr_write_jobs(path: str, text: str, write_jobs: list[str]) -> list[str]:
    if not re.search(r"^  pull_request:", text, re.M):
        return []
    reachable = []
    for jid in write_jobs:
        body = _job_blocks(text)[jid]
        # Only the two exact existing push/workflow_run guards are understood.
        if ("github.event_name == 'push'" in body or
                "github.event_name == 'workflow_run'" in body):
            continue
        reachable.append(jid)
    return reachable


def report(local_tests: list[dict] | None = None) -> dict:
    changed = sorted(set(changed_files()) | {EVIDENCE})
    check_scope(changed)
    inventory_text = baseline(INVENTORY)
    inventory = json.loads(inventory_text)
    lifecycle = {r["path"]: r["lifecycle"] for r in inventory["workflows"]}
    rows = []
    for path, disposition in DISPOSITIONS.items():
        if lifecycle.get(path) != "current":
            raise AuditError(f"{path}: not lifecycle=current at base")
        before = baseline(path)
        after = (ROOT / path).read_text()
        check_workflow(path, before, after)
        b = snapshot(path, before, migrated_view=False)
        a = snapshot(path, after, migrated_view=True)
        if b["normalized_scientific_sha256"] != a["normalized_scientific_sha256"]:
            raise AuditError(f"{path}: scientific/business surface changed")
        for key in ("jobs", "permissions_raw", "concurrency_raw", "artifact_actions",
                    "write_jobs", "pr_reachable_write_jobs"):
            if b[key] != a[key]:
                raise AuditError(f"{path}: invariant changed: {key}")
        rows.append({"path": path, "disposition": disposition, "before": b, "after": a,
                     "added_trigger_paths": list(paths_for(path)) if path in MIGRATED else []})
    return {
        "schema": "poker-residual-repro-dag-audit/v1", "issue": 382,
        "parent_issue": 204, "base_sha": BASE_SHA,
        "inventory_source": INVENTORY, "inventory_base_blob_sha": blob(inventory_text),
        "workflows_audited": len(rows), "workflows_migrated": len(MIGRATED),
        "already_repro_strong": len(STRONG), "blocked": 0,
        "allowlist": sorted(ALLOWLIST), "workflows": rows,
        "write_surface_expanded": False, "scientific_behavior_unchanged": True,
        "test_consumed": False, "files_changed": changed,
        "local_tests": local_tests or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--results", type=Path)
    args = parser.parse_args()
    try:
        stored = json.loads((ROOT / EVIDENCE).read_text()) if (ROOT / EVIDENCE).exists() else {}
        tests = json.loads(args.results.read_text()) if args.results else stored.get("local_tests", [])
        actual = report(tests)
        if args.check:
            if actual != stored:
                raise AuditError("evidence differs from recomputed Git/worktree contract")
        else:
            (ROOT / EVIDENCE).write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n")
        print("Residual REPRO DAG contract: PASS (10 audited; 5 exact migrations)")
        return 0
    except (AuditError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Residual REPRO DAG contract: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
