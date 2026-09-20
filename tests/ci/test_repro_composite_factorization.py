#!/usr/bin/env python3
"""Static mutations and mocked shell execution; no scientific/network execution."""
from pathlib import Path
import itertools
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import audit_repro_composite_factorization as audit


class CompositeTests(unittest.TestCase):
    def reject(self, path, old, new, before=None):
        before = audit.baseline(path) if before is None else before
        after = audit.migrate(path, before)
        self.assertIn(old, after, 'mutation must apply')
        mutant = after.replace(old, new, 1)
        self.assertNotEqual(after, mutant)
        with self.assertRaises(audit.AuditError):
            audit.check_workflow(path, before, mutant)

    def test_exact_current_migrations(self):
        for path in audit.WORKFLOWS:
            with self.subTest(path=path):
                audit.check_workflow(path, audit.baseline(path), (ROOT / path).read_text())
        matrix = [r for p in audit.WORKFLOWS for r in audit.plan(p, audit.baseline(p))]
        self.assertEqual(len(matrix), 20)
        self.assertEqual(sum(r['status']=='BLOCKED' for r in matrix), 1)
        self.assertEqual(sum(r['status']=='MIGRATE' and r['browser'] for r in matrix), 3)
        self.assertEqual(sum(r['status']=='MIGRATE' and not r['browser'] for r in matrix), 16)
        before = audit.metrics({p:audit.baseline(p) for p in audit.WORKFLOWS})
        after = audit.metrics({p:(ROOT/p).read_text() for p in audit.WORKFLOWS})
        self.assertLess(after['yaml_bootstrap_lines'],before['yaml_bootstrap_lines'])

    def test_action_contract_mutations(self):
        audit.check_actions()
        mutations = (
            (audit.RUNTIME, "python-version-file: '.python-version'", "python-version: '3.11'"),
            (audit.RUNTIME, "node-version-file: '.node-version'", "node-version: 'latest'"),
            (audit.RUNTIME, "inputs.require-node == 'true'", 'false'),
            (audit.RUNTIME, 'args=(verify)', 'args=()'),
            (audit.RUNTIME, 'args=(bootstrap)', 'args=(verify)'),
            (audit.RUNTIME, 'python3 tools/repro_ci_environment.py "${args[@]}"', 'echo skipped'),
            (audit.RUNTIME, 'python3 tools/repro_ci_environment.py "${args[@]}"', 'pip install unlocked'),
            (audit.RUNTIME, 'set -euo pipefail', 'set +e'),
            (audit.RUNTIME, '      shell: bash', '      continue-on-error: true\n      shell: bash'),
            (audit.RUNTIME, 'args=(verify)', 'args=(verify) || true'),
            (audit.RUNTIME, 'inputs:', "permissions:\n  contents: write\ninputs:"),
            (audit.RUNTIME, 'inputs:', "inputs:\n  unknown:\n    default: 'true'"),
            (audit.RUNTIME, "default: 'false'", "default: 'true'"),
            (audit.RUNTIME, 'args=(verify)', 'echo "${{ secrets.TOKEN }}"'),
            (audit.RUNTIME, 'args=(verify)', 'git push'),
            (audit.BROWSER, 'python3 tools/repro_ci_browser.py install', 'echo skipped'),
            (audit.BROWSER, 'python3 tools/repro_ci_browser.py install', 'python3 -m playwright install'),
            (audit.BROWSER, 'uses: ./.github/actions/repro-runtime', 'uses: other/action@main'),
        )
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for path in audit.ACTION_HASHES:
                (root/path).parent.mkdir(parents=True,exist_ok=True)
                (root/path).write_text((ROOT/path).read_text())
            for path,old,new in mutations:
                with self.subTest(path=path,mutation=new):
                    original=(ROOT/path).read_text()
                    self.assertIn(old,original)
                    (root/path).write_text(original.replace(old,new,1))
                    with self.assertRaises(audit.AuditError): audit.check_actions(root)
                    (root/path).write_text(original)

    def test_runtime_shell_all_boolean_combinations_and_failure_propagation(self):
        text=(ROOT/audit.RUNTIME).read_text()
        scripts=re.findall(r'      run: \|\n((?:        .*\n|\n)+)',text)
        self.assertEqual(len(scripts),2)
        scripts=['\n'.join(line[8:] for line in s.splitlines()) for s in scripts]
        with tempfile.TemporaryDirectory() as td:
            exe=Path(td)/'python3'
            exe.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\nexit "${MOCK_EXIT:-0}"\n')
            exe.chmod(0o755)
            for node,pydeps,ndeps in itertools.product(('false','true'),repeat=3):
                env={**os.environ,'PATH':td+':'+os.environ['PATH'],'REQUIRE_NODE':node,
                     'PYTHON_DEPS':pydeps,'NODE_DEPS':ndeps}
                result=subprocess.run(['bash','-c','\n'.join(scripts)],env=env,text=True,capture_output=True)
                if ndeps=='true' and node=='false':
                    self.assertNotEqual(result.returncode,0)
                    continue
                self.assertEqual(result.returncode,0,result.stderr)
                expected=['tools/repro_ci_environment.py','bootstrap' if 'true' in (pydeps,ndeps) else 'verify']
                if pydeps=='true':expected+=['--python-deps']
                if ndeps=='true':expected+=['--node-deps']
                if node=='true':expected+=['--require-node']
                self.assertEqual(result.stdout.splitlines(),expected)
                failed=subprocess.run(['bash','-c','\n'.join(scripts)],env={**env,'MOCK_EXIT':'17'},capture_output=True)
                self.assertEqual(failed.returncode,17)
            for invalid in ('', 'TRUE', 'false; echo injected', '$(touch bad)'):
                env={**os.environ,'REQUIRE_NODE':invalid,'PYTHON_DEPS':'false','NODE_DEPS':'false'}
                result=subprocess.run(['bash','-c',scripts[0]],env=env,capture_output=True)
                self.assertNotEqual(result.returncode,0)

    def test_node_inputs_trigger_paths_and_unknown_inputs(self):
        for path in audit.WORKFLOWS:
            for row in audit.plan(path,audit.baseline(path)):
                if row['status']=='BLOCKED': continue
                self.reject(path,row['replacement'],row['replacement'].replace("'true'","'false'") if row['node'] else row['replacement'].replace("'false'","'true'"))
            self.reject(path,f"      - '{audit.RUNTIME}'\n",'')
            self.reject(path,'        with:\n','        with:\n          unexpected: true\n')
            if 'uses: ./.github/actions/repro-browser' in audit.migrate(path,audit.baseline(path)):
                self.reject(path,f"      - '{audit.BROWSER}'\n",'')

    def test_every_business_surface_is_frozen(self):
        path='.github/workflows/model-b-reveal-aware.yml'
        for old,new in (('--seed 20260915','--seed 1'),('--split VALIDATION','--split TEST'),
                        ('NLHE 100-200.zip','other.zip'),('  validation:','  renamed:'),
                        ('    steps:','    needs: another\n    steps:'),
                        ('    steps:','    if: false\n    steps:'),
                        ('    steps:','    env:\n      TEST: true\n    steps:'),
                        ('    steps:','    strategy:\n      matrix:\n        seed: [1, 2]\n    steps:'),
                        ('    steps:','    timeout-minutes: 1\n    steps:'),
                        ('    steps:','    permissions:\n      contents: write\n    steps:'),
                        ('  pull_request:','  pull_request_target:'),
                        ("      - '.python-version'\n",'')):
            with self.subTest(mutation=new): self.reject(path,old,new)
        path='.github/workflows/hero-calculated-range-export.yml'
        for old,new in (('name: issue-107-real-generation-smoke-${{ github.sha }}','name: other'),
                        ('/tmp/issue-107-aa-run.json','/tmp/other.json'),('retention-days: 14','retention-days: 1')):
            self.reject(path,old,new)
        path=audit.WORKFLOWS[0]
        for old,new in (('contents: read','contents: write'),('cancel-in-progress: true','cancel-in-progress: false'),
                        ('node --check site/trainer.js','node --check site/other.js'),
                        ('    steps:','    steps:\n      - run: git push'),
                        ('    steps:','    steps:\n      - run: echo TEST VALIDATION')):
            self.reject(path,old,new)

    def test_immutable_proof_guard_and_scope_mutations(self):
        # A fixture isolates mutations from pre-existing checkout scope blockers.
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            paths=(*audit.WORKFLOWS,*audit.ACTION_HASHES,*audit.HISTORY,*audit.GUARD_HASHES)
            for path in paths:
                target=root/path;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(audit.baseline(path) if path in audit.HISTORY else (ROOT/path).read_text())
            self.assertEqual(audit.validate(root,changed=[]),[])
            for path in (*audit.HISTORY,*audit.GUARD_HASHES):
                with self.subTest(path=path):
                    original=(root/path).read_text()
                    (root/path).write_text(original+'\n# neutralized or rewritten\n')
                    self.assertTrue(audit.validate(root,changed=[]))
                    (root/path).write_text(original)
            for path in ('.github/workflows/game-core.yml','.github/workflows/sequential-arena.yml',
                         'training/models/other.json','requirements.lock.txt'):
                self.assertTrue(audit.validate(root,changed=[path]))

    def test_historical_after_is_transition_before(self):
        batch=json.loads(audit.baseline(audit.HISTORY[0]))
        for row in batch['workflows']:
            self.assertEqual(row['after_git_blob_sha'],audit.blob(audit.baseline(row['path'])))
        population=json.loads(audit.baseline(audit.HISTORY[2]))
        self.assertEqual(population['after_git_blob_sha'],audit.blob(audit.baseline(audit.WORKFLOWS[3])))
        for path in audit.HISTORY[3:]:
            data=json.loads(audit.baseline(path))
            for row in data['workflows']:
                self.assertEqual(row['after']['blob_sha'],audit.blob(audit.baseline(row['path'])))

if __name__=='__main__':
    unittest.main()
