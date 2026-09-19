#!/usr/bin/env python3
"""Issue #373: deterministic, Git-bound, trigger-only quarantine evidence.

Only the block-mapping YAML subset used by the allowlist is accepted. Unsupported
trigger syntax fails closed; this is not a general YAML parser. All bytes outside
that block and the entire existing dispatch stanza are compared, so even fields
not understood by the official inventory parser remain protected.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.audit_github_workflows import parse_workflow  # noqa: E402

SCHEMA = "poker-engine-historical-workflow-quarantine/v1"
INVENTORY = "analysis/workflow_audit/workflows.json"
EVIDENCE = "analysis/workflow_audit/historical_workflow_quarantine_v1.json"
# Ticket authority is independent of the official auditor's lifecycle list.
ALLOWLIST = tuple(".github/workflows/" + name + ".yml" for name in (
    "finalize-training-cycle", "model-b-build", "model-b-conditioned-runtime",
    "model-b-evaluation", "model-b-features", "model-b-profile-selection",
    "model-b-response-v3", "preflop-strategy-support-closed",
    "preflop-strategy-validation-support-closed", "preflop-strategy-validation-v2",
    "promotion-gate-final", "strategic-benchmark-v3", "strategy-candidate-v84",
    "unseen-preflop-context-audit", "v84-strategy-candidate",
))
ALLOWED_FILES = set(ALLOWLIST) | {EVIDENCE, INVENTORY,
    "analysis/workflow_audit/baseline_metrics.json",
    "tools/audit_historical_workflow_quarantine.py",
    "tests/ci/test_historical_workflow_quarantine.py"}


class AuditError(ValueError):
    """Ambiguous syntax or violated migration invariant."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(value: object) -> str:
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def sections(data: bytes) -> dict[str, tuple[int, int]]:
    """Find plain top-level mapping blocks, excluding trailing blank/comment lines."""
    lines = data.decode("utf-8").splitlines(keepends=True)
    starts = []
    for i, line in enumerate(lines):
        if not line.strip() or line.startswith("#") or line.startswith(" "):
            continue
        match = re.fullmatch(r"([A-Za-z_][\w-]*):[^\r\n]*\r?\n?", line)
        require(match is not None, f"unsupported top-level syntax at line {i + 1}")
        starts.append((i, match[1]))
    result = {}
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line.encode("utf-8")))
    for pos, (start, key) in enumerate(starts):
        require(key not in result, f"duplicate top-level key: {key}")
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        while end > start + 1 and (not lines[end - 1].strip() or lines[end - 1].startswith("#")):
            end -= 1
        result[key] = (offsets[start], offsets[end])
    return result


def trigger_parts(data: bytes) -> tuple[bytes, dict[str, bytes]]:
    bounds = sections(data)
    require("on" in bounds, "missing on block")
    start, end = bounds["on"]
    lines = data[start:end].splitlines(keepends=True)
    require(lines[0].strip() == b"on:", "unsupported inline on syntax")
    events = {}
    event = None
    for line in lines[1:]:
        if not line.strip() or line.lstrip().startswith(b"#"):
            if event is not None:
                events[event] += line
            continue
        match = re.fullmatch(rb"  ([A-Za-z_][\w-]*):[ \t]*(?:#[^\r\n]*)?\r?\n?", line)
        if match:
            event = match[1].decode()
            require(event not in events, f"duplicate trigger: {event}")
            events[event] = line
        else:
            require(event is not None and line.startswith(b"    "), "unsupported trigger mapping")
            # Reject YAML aliases, anchors and merge keys in trigger configuration.
            require(not re.search(rb"(?:^|\s)[&*][\w-]+|<<:", line), "unsupported trigger alias/merge")
            events[event] += line
    require(bool(events), "empty on block")
    return data[:start] + data[end:], events


def manual_only(data: bytes) -> bytes:
    _, events = trigger_parts(data)
    start, end = sections(data)["on"]
    return data[:start] + b"on:\n" + events.get("workflow_dispatch", b"  workflow_dispatch:\n") + data[end:]


def state(data: bytes, parsed: dict) -> dict:
    outside, events = trigger_parts(data)
    bounds = sections(data)
    def block(key: str) -> bytes:
        return data[slice(*bounds[key])] if key in bounds else b""
    dispatch = events.get("workflow_dispatch")
    # Hash all dispatch configuration (including inputs) instead of partially
    # parsing YAML defaults, types, descriptions, required flags, etc.
    inputs = dispatch.split(b"\n", 1)[1] if dispatch else b""
    return {
        "blob_sha": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest(),
        "triggers": sorted(events),
        "trigger_configuration": parsed["triggers"],
        "workflow_dispatch_inputs_fingerprint": sha(inputs),
        "trigger_insensitive_sha": sha(outside),
        "permissions_fingerprint": sha(block("permissions")),
        "concurrency_fingerprint": sha(block("concurrency")),
        "jobs_fingerprint": sha(block("jobs")),
        "artifacts_fingerprint": fingerprint(parsed["artifacts"]),
    }


def compare(before: bytes, after: bytes, lifecycle: str) -> None:
    require(lifecycle == "historical_candidate", "non-historical workflow included")
    old_outside, old_events = trigger_parts(before)
    new_outside, new_events = trigger_parts(after)
    require(set(new_events) == {"workflow_dispatch"}, "must have only workflow_dispatch")
    require(old_outside == new_outside, "non-trigger bytes changed (jobs/commands/gates/permissions/concurrency/artifacts)")
    if "workflow_dispatch" in old_events:
        require(old_events["workflow_dispatch"] == new_events["workflow_dispatch"], "dispatch configuration/inputs changed")
    else:
        require(new_events["workflow_dispatch"] == b"  workflow_dispatch:\n", "new dispatch must be bare")


def build_report(root: Path, base_sha: str) -> dict:
    require(re.fullmatch(r"[0-9a-f]{40}", base_sha) is not None, "base must be full commit SHA")
    require(git(root, "rev-parse", base_sha + "^{commit}").decode().strip() == base_sha, "invalid base")
    git(root, "merge-base", "--is-ancestor", base_sha, "HEAD")
    source = git(root, "show", f"{base_sha}:{INVENTORY}")
    inventory = json.loads(source)
    require(inventory["schema"] == "poker-engine-workflow-inventory/v1", "unknown inventory schema")
    rows = inventory["workflows"]
    require(len({r['path'] for r in rows}) == len(rows), "duplicate inventory path")
    indexed = {r["path"]: r for r in rows}
    changed = set(git(root, "diff", "--name-only", base_sha, "--").decode().splitlines())
    changed.update(git(root, "ls-files", "--others", "--exclude-standard",
                       "--", ".github/workflows").decode().splitlines())
    require(not changed - ALLOWED_FILES, f"changes outside issue scope: {sorted(changed - ALLOWED_FILES)}")
    report_rows = []
    removed = Counter({"push": 0, "pull_request": 0, "workflow_run": 0})
    costs = jobs = migrated = examined = 0
    with tempfile.TemporaryDirectory(prefix="historical-quarantine-") as temporary:
        before_root = Path(temporary)
        for path in ALLOWLIST:
            original = git(root, "show", f"{base_sha}:{path}")
            current = (root / path).read_bytes()
            before_path = before_root / path
            before_path.parent.mkdir(parents=True, exist_ok=True)
            before_path.write_bytes(original)
            before_parsed = parse_workflow(before_path, before_root)
            after_parsed = parse_workflow(root / path, root)
            source_row = indexed.get(path)
            lifecycle = source_row.get("lifecycle") if source_row else None
            examined += lifecycle == "historical_candidate"
            reason = "Only automatic triggers removed; all non-trigger bytes and existing dispatch configuration preserved."
            disposition = "MIGRATED_MANUAL_ONLY"
            try:
                before = state(original, before_parsed)
                after = state(current, after_parsed)
            except AuditError as exc:
                require(original == current, f"ambiguous workflow modified: {path}: {exc}")
                before = after = None
                disposition, reason = "BLOCKED_AMBIGUOUS", str(exc)
            if source_row is None or lifecycle != before_parsed["lifecycle"]:
                disposition, reason = "BLOCKED_AMBIGUOUS", "Inventory missing or lifecycle differs from official auditor."
            elif lifecycle != "historical_candidate":
                disposition, reason = "SKIPPED_NOT_HISTORICAL", "Inventory and official auditor no longer classify as historical_candidate."
            elif before is not None and sorted(source_row["triggers"]) != before["triggers"]:
                disposition, reason = "BLOCKED_AMBIGUOUS", "Source inventory and base trigger sets diverge."
            if disposition == "MIGRATED_MANUAL_ONLY":
                compare(original, current, lifecycle)
                require(after_parsed["lifecycle"] == lifecycle, f"lifecycle changed: {path}")
                for key in ("trigger_insensitive_sha", "workflow_dispatch_inputs_fingerprint", "permissions_fingerprint", "concurrency_fingerprint", "jobs_fingerprint", "artifacts_fingerprint"):
                    require(before[key] == after[key], f"{path}: {key} changed")
                removed.update(set(before["triggers"]) - {"workflow_dispatch"})
                migrated += 1
                costs += source_row["cost_proxy"]["score"]
                jobs += len(source_row["jobs"])
            else:
                require(original == current, f"excluded workflow modified: {path}")
            report_rows.append({"path": path, "lifecycle_before": lifecycle,
                "before": before, "after": after, "disposition": disposition, "reason": reason})
    return {
        "schema": SCHEMA, "issue": 373, "base_sha": base_sha,
        "source_inventory_sha": git(root, "rev-parse", f"{base_sha}:{INVENTORY}").decode().strip(),
        "source_inventory_sha256": sha(source), "allowlist": list(ALLOWLIST),
        "workflows": report_rows,
        "aggregate": {"historical_candidates_examined": examined,
            "workflows_migrated_manual_only": migrated,
            "automatic_triggers_removed": dict(sorted(removed.items())),
            "estimated_avoided_run_candidates": {
                "workflow_event_subscriptions": sum(removed.values()),
                "distinct_workflows": migrated, "snapshot_jobs": jobs,
                "snapshot_structural_cost_proxy": costs,
                "method": "#242 snapshot job counts and cost scores summed once per migrated workflow; event subscriptions are potential runs, not observed runs or billed minutes. Branch/path filters still limit matching events."},
            "current_or_frozen_workflows_modified": 0,
            "scientific_commands_changed": False, "artifact_identity_changed": False},
    }


def serialize(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--base-sha", help="Generate evidence against this full Git commit SHA")
    args = parser.parse_args()
    try:
        target = args.root / EVIDENCE
        persisted = target.read_text() if args.check else None
        base = json.loads(persisted)["base_sha"] if args.check else args.base_sha
        report = build_report(args.root, base)
        payload = serialize(report)
        if args.check:
            require(persisted == payload, "evidence differs from recomputed Git-bound report")
        else:
            target.write_text(payload)
        blocked = any(row["disposition"] == "BLOCKED_AMBIGUOUS" for row in report["workflows"])
        require(not blocked, "ambiguous workflow(s); see evidence dispositions")
        print(f"PASS: {report['aggregate']['workflows_migrated_manual_only']} manual-only workflows; non-trigger content unchanged")
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
