#!/usr/bin/env python3
"""Issue #373 historical-workflow quarantine, re-proved at the current main SHA.

Edition 1 (``historical_workflow_quarantine_v1.json``, issue #373) proved the
one-shot migration from its pre-migration base SHA. This module keeps that frozen
proof reproducible and adds edition 2, which re-runs the same byte-level
investigation against the current main SHA:

* the trigger block of each allowlisted historical workflow is ``workflow_dispatch``
  only; ``push``/``pull_request``/``schedule``/``workflow_run`` or any other
  automatic event fails closed;
* every byte outside the trigger block (jobs, permissions, concurrency, artifacts,
  commands, gates) is identical to the #373 manual-only reference and to the
  pre-migration reference outside that block;
* the proof is bound to a full main SHA, and the only paths changed since that SHA
  are this issue's allowlisted scope.

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
from tools.audit_github_workflows import inventory as workflow_inventory  # noqa: E402
from tools.audit_github_workflows import parse_workflow  # noqa: E402

SCHEMA = "poker-engine-historical-workflow-quarantine/v2"
SCHEMA_V1 = "poker-engine-historical-workflow-quarantine/v1"
ISSUE = 373
INVENTORY = "analysis/workflow_audit/workflows.json"
INVENTORY_SCHEMA = "poker-engine-workflow-inventory/v1"
EVIDENCE_V1 = "analysis/workflow_audit/historical_workflow_quarantine_v1.json"
EVIDENCE = "analysis/workflow_audit/historical_workflow_quarantine_v2.json"
# Frozen digest of edition 1: the historical proof is never rewritten in place.
EVIDENCE_V1_SHA256 = "8bd8477533fa07bd30ccf16a62baa7c83a1ed5ba20afcf0b7dff1eb94f481ac8"
# Post-quarantine reference: the manual-only bytes materialized by the #373 commit.
QUARANTINE_REFERENCE_SHA = "938c4af948f3246b04c8b211f834c26e16ea6fef"
QUARANTINE_REFERENCE_SHA_ROLE = (
    "post-#373 manual-only reference; every allowlisted historical workflow must stay byte-identical to it")
# Pre-quarantine reference: edition 1's own base SHA, and the byte source proving that
# the quarantine touched the trigger block and nothing else.
PRE_MIGRATION_REFERENCE_SHA = "f8ec90b2ae293a22a65db9dd6874168eec0745d3"
PRE_MIGRATION_REFERENCE_SHA_ROLE = (
    "pre-#373 bytes recorded as edition 1's base SHA; only the trigger block may differ")
# A quarantined workflow may only be started by hand.
MANUAL_ONLY_EVENT = "workflow_dispatch"
# The automatic subscriptions the guard is explicitly required to catch.
FORBIDDEN_TRIGGER_EVENTS = ("push", "pull_request", "schedule", "workflow_run")
# Every field hashed on both sides of the comparison; hashing the whole job block
# covers commands, gates, artifacts and job wiring at once.
FINGERPRINT_KEYS = ("trigger_insensitive_sha", "workflow_dispatch_inputs_fingerprint",
    "permissions_fingerprint", "concurrency_fingerprint", "jobs_fingerprint",
    "artifacts_fingerprint")
# Ticket authority is independent of the official auditor's lifecycle list.
ALLOWLIST = tuple(".github/workflows/" + name + ".yml" for name in (
    "finalize-training-cycle", "model-b-build", "model-b-conditioned-runtime",
    "model-b-evaluation", "model-b-features", "model-b-profile-selection",
    "model-b-response-v3", "preflop-strategy-support-closed",
    "preflop-strategy-validation-support-closed", "preflop-strategy-validation-v2",
    "promotion-gate-final", "strategic-benchmark-v3", "strategy-candidate-v84",
    "unseen-preflop-context-audit", "v84-strategy-candidate",
))
# The re-bound edition-2 proof is anchored to the #204 final tranche base recorded in
# its own evidence, so the whole tranche's additive audit surface is in scope. Every
# sibling artefact is enumerated explicitly; any path outside this union still fails.
TRANCHE_FILES = {
    "analysis/workflow_audit/baseline_metrics.json",
    "analysis/workflow_audit/consolidation_decision_v1.json",
    "analysis/workflow_audit/repro_composite_adoption_v1.json",
    "docs/ci-workflow-audit.md",
    "docs/ci-workflow-audit-closure.md",
    "docs/ci-workflow-dag.md",
    "tests/ci/test_consolidation_decision.py",
    "tests/ci/test_historical_workflow_quarantine.py",
    "tests/ci/test_repro_composite_factorization.py",
    "tools/audit_active_workflow_dag.py",
    "tools/audit_historical_workflow_quarantine.py",
    "tools/audit_repro_composite_factorization.py",
}
ALLOWED_FILES = set(ALLOWLIST) | {EVIDENCE, EVIDENCE_V1, INVENTORY} | TRANCHE_FILES


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


def automatic_events(data: bytes) -> list[str]:
    """Every trigger event the quarantine forbids, sorted, for one workflow."""
    return sorted(set(trigger_parts(data)[1]) - {MANUAL_ONLY_EVENT})


def require_manual_only(path: str, data: bytes) -> None:
    """Fail closed when a historical workflow gains any automatic trigger."""
    events = set(trigger_parts(data)[1])
    automatic = sorted(events - {MANUAL_ONLY_EVENT})
    require(not automatic, f"{path}: automatic trigger(s) present, quarantine violated: {automatic}")
    require(MANUAL_ONLY_EVENT in events, f"{path}: missing {MANUAL_ONLY_EVENT} trigger")


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


def parsed_state(path: Path, data: bytes, temporary: Path) -> dict:
    """Parse-and-hash arbitrary bytes without writing inside the audited checkout."""
    target = temporary / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return state(data, parse_workflow(target, temporary))


def compare(before: bytes, after: bytes, lifecycle: str) -> None:
    require(lifecycle == "historical_candidate", "non-historical workflow included")
    old_outside, old_events = trigger_parts(before)
    new_outside, new_events = trigger_parts(after)
    require(set(new_events) == {MANUAL_ONLY_EVENT}, f"must have only {MANUAL_ONLY_EVENT}")
    require(old_outside == new_outside, "non-trigger bytes changed (jobs/commands/gates/permissions/concurrency/artifacts)")
    if MANUAL_ONLY_EVENT in old_events:
        require(old_events[MANUAL_ONLY_EVENT] == new_events[MANUAL_ONLY_EVENT], "dispatch configuration/inputs changed")
    else:
        require(new_events[MANUAL_ONLY_EVENT] == b"  workflow_dispatch:\n", "new dispatch must be bare")


def full_sha(root: Path, ref: str) -> str:
    resolved = git(root, "rev-parse", ref + "^{commit}").decode().strip()
    require(resolved == ref, f"reference {ref} does not resolve to a full commit SHA")
    return resolved


def scope_guard(root: Path, base_sha: str) -> list[str]:
    """No tracked or untracked path outside the issue scope may change since the base SHA.

    The edition-2 evidence file itself is excluded: it is this command's own output,
    so its presence must not make the regenerated payload self-referential.
    """
    changed = set(git(root, "diff", "--name-only", base_sha, "--").decode().splitlines())
    changed.update(git(root, "ls-files", "--others", "--exclude-standard").decode().splitlines())
    changed.discard(EVIDENCE)
    outside = sorted(changed - ALLOWED_FILES)
    require(not outside, f"changes outside issue scope: {outside}")
    return sorted(changed)


def load_inventory(root: Path) -> tuple[dict[str, dict], bytes]:
    """Read and parse the committed inventory; freshness is verified after the byte proof."""
    raw = (root / INVENTORY).read_bytes()
    inventory = json.loads(raw)
    require(inventory["schema"] == INVENTORY_SCHEMA, "unknown inventory schema")
    rows = inventory["workflows"]
    require(len({row["path"] for row in rows}) == len(rows), "duplicate inventory path")
    return {row["path"]: row for row in rows}, raw


def verify_inventory_freshness(root: Path, raw: bytes) -> None:
    """The committed inventory must be the byte-exact regeneration of this checkout."""
    regenerated = json.dumps(workflow_inventory(root), indent=2, sort_keys=True) + "\n"
    require(regenerated.encode() == raw, "committed workflow inventory is stale versus the current checkout")


def v1_payload(root: Path) -> tuple[dict[str, dict], str]:
    """Read the frozen edition-1 evidence; claims are re-bound after the byte proof."""
    raw = (root / EVIDENCE_V1).read_bytes()
    digest = sha(raw)
    require(digest == EVIDENCE_V1_SHA256,
            f"{EVIDENCE_V1} was rewritten: {digest} != {EVIDENCE_V1_SHA256}")
    report = json.loads(raw)
    require(report["schema"] == SCHEMA_V1, "unknown edition-1 schema")
    require(report["issue"] == ISSUE, "unexpected edition-1 issue")
    require(report["base_sha"] == PRE_MIGRATION_REFERENCE_SHA, "unexpected edition-1 base SHA")
    indexed = {row["path"]: row for row in report["workflows"]}
    for path in ALLOWLIST:
        require(path in indexed, f"edition 1 does not cover {path}")
        require(indexed[path]["disposition"] == "MIGRATED_MANUAL_ONLY", f"edition-1 disposition changed: {path}")
    return indexed, digest


def verify_v1_rebind(root: Path, rows: dict[str, dict]) -> None:
    """Re-bind the frozen edition-1 fingerprints to the current checkout."""
    with tempfile.TemporaryDirectory(prefix="v1-rebind-") as temporary:
        tmp = Path(temporary)
        for path in ALLOWLIST:
            row = rows[path]
            before = git(root, "show", f"{PRE_MIGRATION_REFERENCE_SHA}:{path}")
            before_state = parsed_state(Path(path), before, tmp)
            after_state = parsed_state(Path(path), (root / path).read_bytes(), tmp)
            require(before_state == row["before"], f"{path}: edition-1 pre-migration fingerprints no longer reproduce")
            require(after_state == row["after"], f"{path}: edition-1 manual-only fingerprints no longer reproduce")


def build_report(root: Path, base_sha: str) -> dict:
    """Edition-2 evidence: same byte-level invariants, bound to the current main SHA."""
    require(re.fullmatch(r"[0-9a-f]{40}", base_sha) is not None, "base must be full commit SHA")
    require(full_sha(root, base_sha) == base_sha, "invalid base")
    git(root, "merge-base", "--is-ancestor", base_sha, "HEAD")
    full_sha(root, QUARANTINE_REFERENCE_SHA)
    full_sha(root, PRE_MIGRATION_REFERENCE_SHA)
    changed = scope_guard(root, base_sha)
    indexed, inventory_raw = load_inventory(root)
    inventory_sha256 = sha(inventory_raw)
    v1_rows, v1_sha256 = v1_payload(root)
    rows = []
    removed: Counter = Counter()
    confirmed = 0
    with tempfile.TemporaryDirectory(prefix="historical-quarantine-") as temporary:
        tmp = Path(temporary)
        for path in ALLOWLIST:
            current = (root / path).read_bytes()
            require_manual_only(path, current)
            current_state = parsed_state(Path(path), current, tmp)
            reference = git(root, "show", f"{QUARANTINE_REFERENCE_SHA}:{path}")
            pre_migration = git(root, "show", f"{PRE_MIGRATION_REFERENCE_SHA}:{path}")
            reference_state = parsed_state(Path(path), reference, tmp)
            pre_state = parsed_state(Path(path), pre_migration, tmp)
            source_row = indexed.get(path)
            lifecycle = source_row.get("lifecycle") if source_row else None
            require(lifecycle == "historical_candidate", f"{path}: lifecycle is {lifecycle!r}, not historical_candidate")
            require(current_state["triggers"] == sorted(source_row["triggers"]),
                    f"{path}: inventory trigger set diverges from the checkout")
            require_manual_only(path, reference)
            compare(pre_migration, current, "historical_candidate")
            # Strongest form of "only the trigger block changed": replaying the
            # quarantine on the pre-migration bytes must rebuild the file byte for byte.
            require(manual_only(pre_migration) == current,
                    f"{path}: re-applying the quarantine to the pre-migration bytes does not reproduce the current file")
            require(current == reference,
                    f"{path}: bytes diverge from the #373 manual-only reference {QUARANTINE_REFERENCE_SHA}")
            for key in FINGERPRINT_KEYS:
                require(current_state[key] == reference_state[key], f"{path}: {key} changed vs the #373 reference")
                require(current_state[key] == pre_state[key], f"{path}: {key} changed vs the pre-migration reference")
            require(current_state["blob_sha"] == v1_rows[path]["after"]["blob_sha"],
                    f"{path}: blob diverges from edition-1 evidence")
            removed.update(set(pre_state["triggers"]) - {MANUAL_ONLY_EVENT})
            confirmed += 1
            rows.append({
                "path": path,
                "lifecycle": lifecycle,
                "disposition": "CONFIRMED_MANUAL_ONLY",
                "content_sha256": sha(current),
                "blob_sha": current_state["blob_sha"],
                "triggers": current_state["triggers"],
                "automatic_triggers": automatic_events(current),
                "forbidden_triggers_present": {event: event in current_state["triggers"]
                                               for event in FORBIDDEN_TRIGGER_EVENTS},
                "trigger_configuration": current_state["trigger_configuration"],
                "trigger_insensitive_sha": current_state["trigger_insensitive_sha"],
                "workflow_dispatch_inputs_fingerprint": current_state["workflow_dispatch_inputs_fingerprint"],
                "permissions_fingerprint": current_state["permissions_fingerprint"],
                "concurrency_fingerprint": current_state["concurrency_fingerprint"],
                "jobs_fingerprint": current_state["jobs_fingerprint"],
                "artifacts_fingerprint": current_state["artifacts_fingerprint"],
                "pre_migration": {
                    "sha": PRE_MIGRATION_REFERENCE_SHA,
                    "content_sha256": sha(pre_migration),
                    "triggers": pre_state["triggers"],
                    "automatic_triggers_removed": sorted(set(pre_state["triggers"]) - {MANUAL_ONLY_EVENT}),
                    "non_trigger_bytes_identical": pre_state["trigger_insensitive_sha"] == current_state["trigger_insensitive_sha"],
                    "dispatch_configuration_identical": pre_state["workflow_dispatch_inputs_fingerprint"] == current_state["workflow_dispatch_inputs_fingerprint"],
                    "requarantine_reproduces_current": manual_only(pre_migration) == current},
                "quarantine_reference": {
                    "sha": QUARANTINE_REFERENCE_SHA,
                    "content_sha256": sha(reference),
                    "bytes_identical": reference == current,
                    "non_trigger_bytes_identical": reference_state["trigger_insensitive_sha"] == current_state["trigger_insensitive_sha"]},
                "evidence_v1": {
                    "path": EVIDENCE_V1,
                    "sha256": v1_sha256,
                    "after_blob_sha": v1_rows[path]["after"]["blob_sha"],
                    "after_fingerprints_match": all(current_state[key] == v1_rows[path]["after"][key]
                                                    for key in FINGERPRINT_KEYS)},
            })
    # Bookkeeping checks run last so that a workflow-level violation always wins
    # the error message: bytes first, then the derived artefacts.
    verify_inventory_freshness(root, inventory_raw)
    verify_v1_rebind(root, v1_rows)
    return {
        "schema": SCHEMA, "issue": ISSUE, "base_sha": base_sha,
        "base_sha_role": "current main SHA this proof is re-bound to; the only paths changed since it are this issue's allowlisted scope",
        "references": {
            "quarantine_reference_sha": QUARANTINE_REFERENCE_SHA,
            "quarantine_reference_sha_role": QUARANTINE_REFERENCE_SHA_ROLE,
            "pre_migration_reference_sha": PRE_MIGRATION_REFERENCE_SHA,
            "pre_migration_reference_sha_role": PRE_MIGRATION_REFERENCE_SHA_ROLE},
        "trigger_guard": {
            "manual_only_event": MANUAL_ONLY_EVENT,
            "forbidden_events": list(FORBIDDEN_TRIGGER_EVENTS),
            "rule": "every allowlisted historical workflow must declare workflow_dispatch and no other event; any listed or unlisted automatic event fails the audit",
            "enforced_by": "tools/audit_historical_workflow_quarantine.py:require_manual_only"},
        "evidence_v1": {"path": EVIDENCE_V1, "sha256": v1_sha256,
                        "expected_sha256": EVIDENCE_V1_SHA256, "unchanged": v1_sha256 == EVIDENCE_V1_SHA256,
                        "rebind": "edition-1 per-workflow fingerprints recomputed from Git objects and the current checkout"},
        "source_inventory": {"path": INVENTORY, "sha256": inventory_sha256,
                             "regenerated_sha256": inventory_sha256,
                             "matches_regenerated": True},
        "scope": {"changed_since_base": changed,
                  "allowed_paths": sorted(ALLOWED_FILES), "outside_scope": []},
        "allowlist": list(ALLOWLIST),
        "workflows": rows,
        "aggregate": {
            "allowlist_size": len(ALLOWLIST),
            "workflows_confirmed_manual_only": confirmed,
            "historical_candidates_confirmed": confirmed,
            "workflows_with_automatic_triggers": sum(bool(row["automatic_triggers"]) for row in rows),
            "automatic_triggers_present": {event: sum(row["forbidden_triggers_present"][event]
                                                      for row in rows) for event in FORBIDDEN_TRIGGER_EVENTS},
            "automatic_triggers_removed_vs_pre_migration": dict(sorted(removed.items())),
            "non_trigger_bytes_identical_to_pre_migration": sum(row["pre_migration"]["non_trigger_bytes_identical"]
                                                               for row in rows),
            "trigger_only_delta_reproduces_current": sum(row["pre_migration"]["requarantine_reproduces_current"]
                                                         for row in rows),
            "non_trigger_bytes_identical_to_quarantine_reference": sum(row["quarantine_reference"]["non_trigger_bytes_identical"]
                                                                      for row in rows),
            "bytes_identical_to_quarantine_reference": sum(row["quarantine_reference"]["bytes_identical"]
                                                          for row in rows),
            "dispatch_configuration_preserved": sum(row["pre_migration"]["dispatch_configuration_identical"]
                                                    for row in rows),
            "evidence_v1_unchanged": v1_sha256 == EVIDENCE_V1_SHA256,
            "source_inventory_matches_regenerated": True,
            "current_or_frozen_workflows_modified": 0,
            "scientific_commands_changed": False, "artifact_identity_changed": False},
    }


def build_v1_report(root: Path, base_sha: str) -> dict:
    """Frozen edition-1 algorithm, kept executable to re-prove issue #373 on demand.

    Only the scope guard differs from edition 2: edition 1 proved its own diff at its
    own base SHA, so re-running it now must not re-interpret later main drift as a
    violation. The byte-level workflow claims are unchanged.
    """
    require(re.fullmatch(r"[0-9a-f]{40}", base_sha) is not None, "base must be full commit SHA")
    require(full_sha(root, base_sha) == base_sha, "invalid base")
    git(root, "merge-base", "--is-ancestor", base_sha, "HEAD")
    source = git(root, "show", f"{base_sha}:{INVENTORY}")
    inventory = json.loads(source)
    require(inventory["schema"] == INVENTORY_SCHEMA, "unknown inventory schema")
    rows = inventory["workflows"]
    require(len({r['path'] for r in rows}) == len(rows), "duplicate inventory path")
    indexed = {r["path"]: r for r in rows}
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
                for key in FINGERPRINT_KEYS:
                    require(before[key] == after[key], f"{path}: {key} changed")
                removed.update(set(before["triggers"]) - {MANUAL_ONLY_EVENT})
                migrated += 1
                costs += source_row["cost_proxy"]["score"]
                jobs += len(source_row["jobs"])
            else:
                require(original == current, f"excluded workflow modified: {path}")
            report_rows.append({"path": path, "lifecycle_before": lifecycle,
                "before": before, "after": after, "disposition": disposition, "reason": reason})
    return {
        "schema": SCHEMA_V1, "issue": ISSUE, "base_sha": base_sha,
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


def check_v1(root: Path) -> int:
    persisted = (root / EVIDENCE_V1).read_text()
    base = json.loads(persisted)["base_sha"]
    report = build_v1_report(root, base)
    require(persisted == serialize(report), "edition-1 evidence differs from recomputed Git-bound report")
    print("PASS: edition-1 evidence frozen and still reproducible at the current checkout")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="recompute edition 2 and require byte-identical evidence")
    mode.add_argument("--base-sha", help="write edition-2 evidence bound to this full Git commit SHA")
    mode.add_argument("--check-v1", action="store_true", help="re-prove the frozen edition-1 evidence")
    args = parser.parse_args()
    try:
        if args.check_v1:
            return check_v1(args.root)
        target = args.root / EVIDENCE
        persisted = target.read_text() if args.check else None
        base = json.loads(persisted)["base_sha"] if args.check else args.base_sha
        report = build_report(args.root, base)
        payload = serialize(report)
        if args.check:
            require(persisted == payload, "evidence differs from recomputed Git-bound report")
        else:
            target.write_text(payload)
        require(report["aggregate"]["workflows_confirmed_manual_only"] == len(ALLOWLIST),
                "not every allowlisted workflow could be confirmed manual-only")
        require(report["aggregate"]["workflows_with_automatic_triggers"] == 0,
                "a historical workflow carries an automatic trigger")
        print(f"PASS: {report['aggregate']['workflows_confirmed_manual_only']} manual-only workflows; "
              "non-trigger bytes identical to the #373 reference")
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
