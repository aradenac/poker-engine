#!/usr/bin/env python3
"""Structural mutation tests; never execute scientific workflow commands."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import audit_historical_workflow_quarantine as audit  # noqa: E402

# Captured before any test patches ``audit.git``.
REAL_GIT = audit.git

BEFORE = b'''name: Historical fixture
on:
  push:
    paths:
      - 'tools/**'
  workflow_dispatch:
    inputs:
      seed:
        description: 'Keep TRAIN / VALIDATION / TEST unchanged'
        required: true
        type: string
        default: '42'

permissions:
  contents: read
concurrency:
  group: historical-${{ github.ref }}
  cancel-in-progress: false
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - run: python3 tools/scientific_gate.py --seed 42
      - uses: actions/upload-artifact@v4
        with:
          name: scientific-evidence
          path: evidence/result.json
          retention-days: 30
  dependent:
    needs: gate
    runs-on: ubuntu-latest
    steps:
      - run: echo protected
'''


def fixture_root(temporary: Path) -> Path:
    """Full checkout slice the auditor needs: every workflow plus the #373 artefacts."""
    root = temporary / "checkout"
    shutil.copytree(ROOT / ".github/workflows", root / ".github/workflows")
    (root / "analysis/workflow_audit").mkdir(parents=True, exist_ok=True)
    for name in ("workflows.json", "historical_workflow_quarantine_v1.json", "baseline_metrics.json"):
        shutil.copy2(ROOT / "analysis/workflow_audit" / name, root / "analysis/workflow_audit" / name)
    return root


def real_git(root: Path, *args: str) -> bytes:
    """Fixture trees inherit Git objects from the real checkout."""
    return REAL_GIT(ROOT, *args)


def current_base_sha() -> str:
    return json.loads((ROOT / audit.EVIDENCE).read_text())["base_sha"]


class QuarantineTests(unittest.TestCase):
    def setUp(self):
        self.after = audit.manual_only(BEFORE)

    def test_manual_inputs_preserved_exactly(self):
        audit.compare(BEFORE, self.after, "historical_candidate")
        self.assertIn(b"default: '42'", self.after)
        self.assertEqual(audit.trigger_parts(BEFORE)[1]['workflow_dispatch'],
                         audit.trigger_parts(self.after)[1]['workflow_dispatch'])

    def test_add_bare_dispatch_and_all_automatic_event_types(self):
        for event in ('push', 'pull_request', 'workflow_run', 'schedule', 'repository_dispatch', 'workflow_call'):
            with self.subTest(event=event):
                before = f'on:\n  {event}:\n\njobs:\n  gate:\n    runs-on: ubuntu-latest\n'.encode()
                after = audit.manual_only(before)
                audit.compare(before, after, 'historical_candidate')
                self.assertEqual(audit.trigger_parts(after)[1], {'workflow_dispatch': b'  workflow_dispatch:\n'})
                audit.require_manual_only('fixture.yml', after)

    def test_required_mutations_fail_closed(self):
        mutations = {
            'job_removed': self.after[:self.after.index(b'  dependent:')],
            'command_changed': self.after.replace(b'--seed 42', b'--seed 43'),
            'artifact_name_changed': self.after.replace(b'name: scientific-evidence', b'name: other-evidence'),
            'concurrency_changed': self.after.replace(b'cancel-in-progress: false', b'cancel-in-progress: true'),
            'permission_changed': self.after.replace(b'contents: read', b'contents: write'),
            'automatic_trigger_remaining': self.after.replace(b'on:\n', b'on:\n  push:\n'),
            'dispatch_missing': self.after.replace(b'  workflow_dispatch:', b'  pull_request:'),
            'on_block_removed': self.after[:audit.sections(self.after)['on'][0]] + self.after[audit.sections(self.after)['on'][1]:],
            'dispatch_input_changed': self.after.replace(b"default: '42'", b"default: '43'"),
            'gate_changed': self.after.replace(b'needs: gate', b'needs: []'),
            'artifact_path_changed': self.after.replace(b'path: evidence/result.json', b'path: other/result.json'),
            'artifact_retention_changed': self.after.replace(b'retention-days: 30', b'retention-days: 1'),
        }
        for name, after in mutations.items():
            with self.subTest(mutation=name), self.assertRaises(audit.AuditError):
                audit.compare(BEFORE, after, 'historical_candidate')
        for lifecycle in ('current', 'frozen_current', '', None):
            with self.subTest(lifecycle=lifecycle), self.assertRaises(audit.AuditError):
                audit.compare(BEFORE, self.after, lifecycle)

    def test_unsupported_and_duplicate_yaml_fail_closed(self):
        for data in (
            BEFORE.replace(b'on:\n', b'on: [push, workflow_dispatch]\n'),
            BEFORE.replace(b'on:\n', b'"on":\n'),
            BEFORE + b'on:\n  push:\n',
            BEFORE.replace(b'  push:\n', b'  push:\n  push:\n'),
            BEFORE.replace(b'  push:\n', b'  push: *automatic\n'),
            BEFORE.replace(b"      - 'tools/**'", b'    <<: *automatic'),
            BEFORE.replace(b'  push:\n', b'   push:\n'),
        ):
            with self.subTest(data=data[:100]), self.assertRaises(audit.AuditError):
                audit.manual_only(data)

    def test_non_ascii_bytes_and_trigger_location(self):
        before = BEFORE.replace(b'name: Historical fixture', 'name: Historique épreuve'.encode())
        on_start, on_end = audit.sections(before)['on']
        # Top-level on need not be the first block; block-like script content
        # must never be mistaken for a top-level trigger.
        before = before[:on_start] + before[on_end:] + before[on_start:on_end]
        audit.compare(before, audit.manual_only(before), 'historical_candidate')

    def test_real_evidence_is_rebound_to_current_main_sha(self):
        persisted = (ROOT / audit.EVIDENCE).read_text()
        base = current_base_sha()
        # Raises CalledProcessError when the recorded SHA is not on the current history.
        audit.git(ROOT, "merge-base", "--is-ancestor", base, "HEAD")
        result = audit.build_report(ROOT, base)
        self.assertEqual(audit.serialize(result), persisted)
        self.assertEqual(result["schema"], "poker-engine-historical-workflow-quarantine/v2")
        self.assertNotEqual(result["schema"], audit.SCHEMA_V1)
        aggregate = result["aggregate"]
        self.assertEqual(aggregate["allowlist_size"], 15)
        self.assertEqual(aggregate["workflows_confirmed_manual_only"], 15)
        self.assertEqual(aggregate["historical_candidates_confirmed"], 15)
        self.assertEqual(aggregate["workflows_with_automatic_triggers"], 0)
        self.assertEqual(aggregate["automatic_triggers_present"],
                         {"push": 0, "pull_request": 0, "schedule": 0, "workflow_run": 0})
        self.assertEqual(aggregate["non_trigger_bytes_identical_to_quarantine_reference"], 15)
        self.assertEqual(aggregate["non_trigger_bytes_identical_to_pre_migration"], 15)
        self.assertEqual(aggregate["trigger_only_delta_reproduces_current"], 15)
        self.assertEqual(aggregate["bytes_identical_to_quarantine_reference"], 15)
        self.assertEqual(aggregate["dispatch_configuration_preserved"], 15)
        self.assertTrue(aggregate["evidence_v1_unchanged"])
        self.assertEqual(result["evidence_v1"]["sha256"], audit.EVIDENCE_V1_SHA256)
        self.assertEqual(result["aggregate"]["automatic_triggers_removed_vs_pre_migration"],
                         {"push": 15, "pull_request": 1})
        for row in result["workflows"]:
            self.assertEqual(row["triggers"], ["workflow_dispatch"])
            self.assertEqual(row["automatic_triggers"], [])
            self.assertEqual(row["disposition"], "CONFIRMED_MANUAL_ONLY")
            self.assertTrue(row["quarantine_reference"]["bytes_identical"])
            self.assertTrue(row["pre_migration"]["non_trigger_bytes_identical"])
            self.assertTrue(row["pre_migration"]["requarantine_reproduces_current"])
            self.assertTrue(row["evidence_v1"]["after_fingerprints_match"])

    def test_fifteen_historical_workflows_are_manual_only_at_head(self):
        self.assertEqual(len(audit.ALLOWLIST), 15)
        for path in audit.ALLOWLIST:
            with self.subTest(path=path):
                data = (ROOT / path).read_bytes()
                audit.require_manual_only(path, data)
                self.assertEqual(sorted(audit.trigger_parts(data)[1]), ["workflow_dispatch"])
                self.assertEqual(audit.automatic_events(data), [])
                reference = audit.git(ROOT, "show", f"{audit.QUARANTINE_REFERENCE_SHA}:{path}")
                self.assertEqual(data, reference)
                pre_migration = audit.git(ROOT, "show", f"{audit.PRE_MIGRATION_REFERENCE_SHA}:{path}")
                with tempfile.TemporaryDirectory() as temporary:
                    tmp = Path(temporary)
                    now = audit.parsed_state(Path(path), data, tmp)
                    pre = audit.parsed_state(Path(path), pre_migration, tmp)
                for key in audit.FINGERPRINT_KEYS:
                    self.assertEqual(now[key], pre[key], f"{path}: {key} changed outside the trigger block")

    def test_guard_fails_when_historical_workflow_gains_automatic_trigger(self):
        """Mutation test: every real historical workflow, every forbidden automatic event."""
        events = list(audit.FORBIDDEN_TRIGGER_EVENTS) + ["repository_dispatch", "workflow_call"]
        for path in audit.ALLOWLIST:
            original = (ROOT / path).read_bytes()
            for event in events:
                mutated = original.replace(b"on:\n", f"on:\n  {event}:\n".encode(), 1)
                self.assertNotEqual(mutated, original, f"{path}: mutation did not apply")
                self.assertEqual(audit.automatic_events(mutated), [event])
                with self.subTest(path=path, event=event), self.assertRaises(audit.AuditError):
                    audit.require_manual_only(path, mutated)
                with self.subTest(path=path, event=event, stage='compare'), self.assertRaises(audit.AuditError):
                    audit.compare(original, mutated, "historical_candidate")
                # Re-quarantining the mutated bytes is the only accepted repair.
                audit.require_manual_only(path, audit.manual_only(mutated))

    def test_report_recomputation_rejects_automatic_trigger_mutation(self):
        base = current_base_sha()
        for event in audit.FORBIDDEN_TRIGGER_EVENTS:
            with self.subTest(event=event), tempfile.TemporaryDirectory() as temporary:
                root = fixture_root(Path(temporary))
                target = root / audit.ALLOWLIST[0]
                target.write_bytes(target.read_bytes().replace(b"on:\n", f"on:\n  {event}:\n".encode(), 1))
                with patch.object(audit, 'git', side_effect=real_git):
                    with self.assertRaisesRegex(audit.AuditError, 'automatic trigger'):
                        audit.build_report(root, base)

    def test_report_recomputation_rejects_tampered_workflow(self):
        base = current_base_sha()
        tampering = {
            'permissions': (b'contents: write', b'contents: read'),
            'command': (b'--require-ready', b'--require-not-ready'),
            'concurrency': (b'cancel-in-progress: true', b'cancel-in-progress: false'),
            'artifact_or_gate_block': (b'Persist final state', b'Persist final state (tampered)'),
            'trailing_bytes': (b'git push origin HEAD:${GITHUB_REF_NAME}\n',
                               b'git push origin HEAD:${GITHUB_REF_NAME}\n# tampered outside the trigger block\n'),
        }
        for name, (old, new) in tampering.items():
            with self.subTest(tamper=name), tempfile.TemporaryDirectory() as temporary:
                root = fixture_root(Path(temporary))
                target = root / audit.ALLOWLIST[0]
                target.write_bytes(target.read_bytes().replace(old, new))
                with patch.object(audit, 'git', side_effect=real_git):
                    with self.assertRaisesRegex(audit.AuditError, 'non-trigger bytes changed'):
                        audit.build_report(root, base)

    def test_scope_guard_rejects_unallowlisted_change(self):
        base = current_base_sha()
        def fake_git(root, *args):
            if args[:2] == ('diff', '--name-only'):
                return b'.github/workflows/current.yml\n'
            return real_git(root, *args)
        with patch.object(audit, 'git', side_effect=fake_git):
            with self.assertRaisesRegex(audit.AuditError, 'outside issue scope'):
                audit.build_report(ROOT, base)

    def test_stale_inventory_is_rejected(self):
        base = current_base_sha()
        with tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            inventory_path = root / audit.INVENTORY
            inventory = json.loads(inventory_path.read_text())
            row = next(r for r in inventory["workflows"] if r["path"] == audit.ALLOWLIST[0])
            # Bookkeeping drift only: the workflow bytes still satisfy every guard,
            # so the freshness check is what has to fail closed.
            row["cost_proxy"]["score"] += 1
            inventory_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
            with patch.object(audit, 'git', side_effect=real_git):
                with self.assertRaisesRegex(audit.AuditError, 'inventory is stale'):
                    audit.build_report(root, base)

    def test_edition_v1_evidence_frozen_and_still_reproducible(self):
        raw = (ROOT / audit.EVIDENCE_V1).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), audit.EVIDENCE_V1_SHA256)
        persisted = raw.decode()
        report = audit.build_v1_report(ROOT, json.loads(persisted)["base_sha"])
        self.assertEqual(audit.serialize(report), persisted)
        self.assertEqual(report["issue"], 373)
        self.assertEqual(report["aggregate"]["workflows_migrated_manual_only"], 15)

    def test_edition_v1_rewrite_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(Path(temporary))
            target = root / audit.EVIDENCE_V1
            target.write_bytes(target.read_bytes().replace(b'"issue": 373', b'"issue": 374'))
            with patch.object(audit, 'git', side_effect=real_git):
                with self.assertRaisesRegex(audit.AuditError, 'was rewritten'):
                    audit.build_report(root, current_base_sha())


if __name__ == '__main__':
    unittest.main(verbosity=2)
