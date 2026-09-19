#!/usr/bin/env python3
"""Structural mutation tests; never execute scientific workflow commands."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import audit_historical_workflow_quarantine as audit  # noqa: E402

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

    def test_real_evidence_is_deterministic_and_git_bound(self):
        persisted = (ROOT / audit.EVIDENCE).read_text()
        base = json.loads(persisted)['base_sha']
        result = audit.build_report(ROOT, base)
        self.assertEqual(audit.serialize(result), persisted)
        self.assertEqual(result['aggregate']['workflows_migrated_manual_only'], 15)
        self.assertEqual(result['aggregate']['automatic_triggers_removed'],
                         {'push': 15, 'pull_request': 1, 'workflow_run': 0})

    def test_report_recomputation_rejects_tampered_workflow(self):
        base = json.loads((ROOT / audit.EVIDENCE).read_text())['base_sha']
        real_git = audit.git
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in audit.ALLOWLIST:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / path).read_bytes())
            target = root / audit.ALLOWLIST[0]
            target.write_bytes(target.read_bytes().replace(b'contents: write', b'contents: read'))
            # Supply real immutable base objects without creating commits or
            # copying the repository's scientific data into the fixture tree.
            with patch.object(audit, 'git', side_effect=lambda _root, *args: real_git(ROOT, *args)):
                with self.assertRaisesRegex(audit.AuditError, 'non-trigger bytes changed'):
                    audit.build_report(root, base)

    def test_scope_guard_rejects_unallowlisted_workflow(self):
        base = json.loads((ROOT / audit.EVIDENCE).read_text())['base_sha']
        real_git = audit.git
        def fake_git(root, *args):
            if args[:2] == ('diff', '--name-only'):
                return b'.github/workflows/current.yml\n'
            return real_git(root, *args)
        with patch.object(audit, 'git', side_effect=fake_git):
            with self.assertRaisesRegex(audit.AuditError, 'outside issue scope'):
                audit.build_report(ROOT, base)

    def test_inventory_divergence_blocks_untouched_candidate(self):
        base = json.loads((ROOT / audit.EVIDENCE).read_text())['base_sha']
        real_git = audit.git
        for lifecycle in ('current', 'frozen_current', 'historical_candidate'):
            with self.subTest(lifecycle=lifecycle), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for path in audit.ALLOWLIST:
                    target = root / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes((ROOT / path).read_bytes())
                target = root / audit.ALLOWLIST[0]
                target.write_bytes(real_git(ROOT, 'show', f'{base}:{audit.ALLOWLIST[0]}'))
                def fake_git(_root, *args):
                    data = real_git(ROOT, *args)
                    if args == ('show', f'{base}:{audit.INVENTORY}'):
                        inv = json.loads(data)
                        row = next(r for r in inv['workflows'] if r['path'] == audit.ALLOWLIST[0])
                        row['lifecycle'] = lifecycle
                        if lifecycle == 'historical_candidate':
                            row['triggers'] = ['schedule']
                        return json.dumps(inv).encode()
                    return data
                with patch.object(audit, 'git', side_effect=fake_git):
                    report = audit.build_report(root, base)
                self.assertEqual(report['workflows'][0]['disposition'], 'BLOCKED_AMBIGUOUS')
                self.assertEqual(report['aggregate']['workflows_migrated_manual_only'], 14)


if __name__ == '__main__':
    unittest.main(verbosity=2)
