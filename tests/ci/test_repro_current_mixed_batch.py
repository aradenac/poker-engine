#!/usr/bin/env python3
"""Static mutation tests; never execute a workflow or consume scientific data."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import audit_repro_current_mixed_batch as audit


class MixedBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = {p: audit.baseline(p) for p in audit.WORKFLOWS}
        cls.after = {p: (ROOT / p).read_text() for p in audit.WORKFLOWS}

    def reject(self, path, old, new, *, before=None, after=None):
        source = self.after[path] if after is None else after
        self.assertIn(old, source, 'mutation must actually apply')
        mutated = source.replace(old, new, 1)
        self.assertNotEqual(mutated, source)
        with self.assertRaises(audit.AuditError):
            audit.check_workflow(path, self.before[path] if before is None else before, mutated)

    def test_seven_workflows_exact_migration(self):
        self.assertEqual(len(self.before), 7)
        for path in audit.WORKFLOWS:
            with self.subTest(path=path):
                audit.check_workflow(path, self.before[path], self.after[path])
                b = audit.snapshot(path, self.before[path])
                a = audit.snapshot(path, self.after[path])
                self.assertEqual(b['command_fingerprint'], a['command_fingerprint'])
                self.assertEqual(b['artifact_fingerprint'], a['artifact_fingerprint'])
                for key in ('name', 'permissions', 'concurrency', 'env', 'write_jobs',
                            'pr_executable_write_jobs'):
                    self.assertEqual(b[key], a[key])
                for jid in b['jobs']:
                    self.assertEqual(b['jobs'][jid]['metadata_raw'], a['jobs'][jid]['metadata_raw'])
                self.assertEqual(a['python_floating'], 0)
                self.assertEqual(a['node_floating'], 0)
                for event, cfg in b['triggers'].items():
                    expected = dict(cfg)
                    if 'paths' in cfg:
                        expected['paths'] = list(audit.paths_for(path)) + cfg['paths']
                    self.assertEqual(expected, a['triggers'][event])

    def test_existing_commands_and_tests_cannot_change_or_disappear(self):
        for path in audit.WORKFLOWS:
            before = audit.snapshot(path, self.after[path])
            command_step = next(s for blocks in before['business_steps'].values()
                                for s in blocks if '        run:' in s)
            with self.subTest(path=path, mutation='delete'):
                self.reject(path, command_step, '')
            with self.subTest(path=path, mutation='change'):
                self.reject(path, command_step, command_step.replace('python3', 'python3 -O', 1))
        self.reject(audit.WORKFLOWS[0],
                    '          python3 tests/datasets/test_persisted_snapshot.py\n', '')

    def test_seed_split_dataset(self):
        path = audit.WORKFLOWS[0]
        self.reject(path, "row['split']=='TRAIN'", "row['split']=='TEST'")
        self.reject(path, 'selected_100_200.zip', 'other_dataset.zip')
        # No explicit seed flag in this batch. Exercise the same guard using a
        # historical fixture containing seed/split/dataset and artifact settings.
        before = self.before[path] + ('      - name: Seed fixture\n'
            '        run: python3 fixture.py --seed 17 --split TRAIN --dataset frozen\n')
        after = audit.migrate(path, before)
        for old, new in (('--seed 17', '--seed 18'), ('--split TRAIN', '--split TEST'),
                         ('--dataset frozen', '--dataset other')):
            with self.subTest(token=old):
                self.reject(path, old, new, before=before, after=after)

    def test_artifact_name_path_retention_and_semantics(self):
        # These seven workflows have no upload/download actions. Synthetic
        # baseline proves the comparator freezes all artifact step attributes.
        path = audit.WORKFLOWS[1]
        before = self.before[path] + ("      - uses: actions/upload-artifact@v4\n"
            "        with:\n          name: frozen-evidence\n          path: /tmp/frozen.json\n"
            "          retention-days: 7\n          if-no-files-found: error\n"
            "      - uses: actions/download-artifact@v4\n"
            "        with:\n          name: frozen-evidence\n")
        after = audit.migrate(path, before)
        audit.check_workflow(path, before, after)
        for old, new in (('name: frozen-evidence', 'name: other'),
                         ('path: /tmp/frozen.json', 'path: /tmp/other.json'),
                         ('retention-days: 7', 'retention-days: 1'),
                         ('if-no-files-found: error', 'if-no-files-found: ignore'),
                         ('download-artifact@v4', 'download-artifact@v3')):
            with self.subTest(token=old):
                self.reject(path, old, new, before=before, after=after)

    def test_job_needs_if_env_matrix_timeout_permissions_concurrency(self):
        path = audit.WORKFLOWS[-1]
        for old, new in (
            ('  contract:', '  renamed:'),
            ('    runs-on: ubuntu-24.04', '    needs: prove-no-publication\n    runs-on: ubuntu-24.04'),
            ("if: github.event_name == 'pull_request'", 'if: false'),
            ('contents: read', 'contents: write'),
            ('contents: write', 'contents: read'),
            ('cancel-in-progress: false', 'cancel-in-progress: true'),
            ('timeout-minutes: 20', 'timeout-minutes: 25'),
            ('RESULT_RUN_ID: 20260918_release_no_pending_snapshot_v1', 'RESULT_RUN_ID: other'),
            ('    steps:', '    strategy:\n      matrix:\n        seed: [1, 2]\n    steps:'),
        ):
            with self.subTest(token=old):
                self.reject(path, old, new)

    def test_write_job_must_never_run_on_pr(self):
        path = audit.WORKFLOWS[-1]
        for guard in ("github.event_name == 'pull_request'", 'true',
                      "github.event_name != 'workflow_dispatch'"):
            with self.subTest(guard=guard):
                self.reject(path, "github.event_name == 'push'", guard)
        mutated = self.after[path].replace("github.event_name == 'push'", 'true')
        self.assertEqual(audit.snapshot(path, mutated)['pr_executable_write_jobs'],
                         ['prove-no-publication'])

    def test_trigger_and_historical_path_removal(self):
        for path in audit.WORKFLOWS:
            triggers = audit.snapshot(path, self.before[path])['triggers']
            old_path = next(cfg['paths'][0] for cfg in triggers.values() if 'paths' in cfg)
            with self.subTest(path=path):
                self.reject(path, f"      - '{old_path}'\n", '')
                self.reject(path, '  pull_request:', '  pull_request_target:')
        self.reject(audit.WORKFLOWS[-1],
                    "      - 'execute/issue-113-no-pending-release-20260918'\n", '')

    def test_python_node_verify_cannot_float_disappear_or_be_masked(self):
        for path in audit.WORKFLOWS:
            for old, new in ((audit.PYTHON, audit.OLD_PYTHON),
                             (audit.PYTHON, ''),
                             (audit.verify_step(path), ''),
                             (audit.VERIFY, audit.VERIFY + ' || true'),
                             (audit.VERIFY, audit.VERIFY + ' ; exit 0'),
                             ('      - name: Verify locked REPRO environment',
                              '      - name: Verify locked REPRO environment\n        if: false'),
                             ('      - name: Verify locked REPRO environment',
                              '      - name: Verify locked REPRO environment\n        continue-on-error: true')):
                with self.subTest(path=path, mutation=new):
                    self.reject(path, old, new)
        for path in audit.NODE:
            self.reject(path, audit.NEW_NODE, audit.OLD_NODE)
            self.reject(path, audit.NEW_NODE, '')
            self.reject(path, 'verify --require-node', 'verify')
        for path in set(audit.WORKFLOWS) - audit.NODE:
            self.reject(path, audit.PYTHON, audit.PYTHON + audit.NEW_NODE)

    def test_business_step_masking(self):
        path = audit.WORKFLOWS[3]
        for addition in ('        continue-on-error: true\n', '        if: false\n',
                         '        env:\n          PYTHONOPTIMIZE: 1\n'):
            self.reject(path, '      - name: Syntax\n', '      - name: Syntax\n' + addition)
        self.reject(path, 'run: PYTHONPATH=. python3 tests/simulation/test_preflop_grid_evaluator.py',
                    'run: PYTHONPATH=. python3 tests/simulation/test_preflop_grid_evaluator.py || true')

    def test_scope_guard_including_untracked(self):
        audit.check_scope(list(audit.ALLOWLIST))
        for forbidden in ('.github/workflows/game-core.yml',
                          '.github/workflows/sequential-arena.yml', 'requirements.lock.txt',
                          'tools/new_side_effect.py'):
            with self.subTest(path=forbidden), self.assertRaises(audit.AuditError):
                audit.check_scope([*audit.ALLOWLIST, forbidden])
        with patch.object(audit, 'git', side_effect=['', 'tools/outside.py\nlocal/__pycache__/x.pyc\n']):
            with self.assertRaises(audit.AuditError):
                audit.check_scope(audit.changed_files())
        audit.check_scope(audit.changed_files())


if __name__ == '__main__':
    unittest.main()
