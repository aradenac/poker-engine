#!/usr/bin/env python3
"""Static mutations and mocked shell execution; no scientific/network execution."""
from pathlib import Path
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import audit_repro_composite_factorization as audit

INSTALL_BROWSER_STEP = re.compile(
    r'      - name: Install locked browser runtime\n        run: \|\n(?:          .*\n)+')


def install_step_of(text):
    """Exact inline browser bootstrap step of a workflow, for mutation fixtures."""
    match = INSTALL_BROWSER_STEP.search(text)
    if not match:
        raise AssertionError('inline browser bootstrap step not found')
    return match.group(0)


class CompositeTests(unittest.TestCase):
    def tearDown(self):
        audit.baseline.cache_clear()

    def test_shallow_baselines_remain_cryptographically_bound(self):
        evidence = json.loads((ROOT / audit.EVIDENCE).read_text())
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / audit.EVIDENCE
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(evidence))
            for path in audit.HISTORY:
                (root / path).write_text((ROOT / path).read_text())
            with patch.object(audit, 'ROOT', root), patch.object(audit, 'git', return_value='true\n'), \
                    patch.object(audit.subprocess, 'check_output', side_effect=subprocess.CalledProcessError(128, 'git')):
                audit.baseline.cache_clear()
                for path in (*audit.WORKFLOWS, *audit.HISTORY):
                    self.assertEqual(audit.sha(audit.baseline(path)), audit.BASELINE_HASHES[path])
                path = audit.WORKFLOWS[0]
                evidence['baseline_workflows'][path] += '\n# forged baseline\n'
                target.write_text(json.dumps(evidence))
                audit.baseline.cache_clear()
                with self.assertRaises(audit.AuditError):
                    audit.baseline(path)
                evidence['base_sha'] = '0' * 40
                target.write_text(json.dumps(evidence))
                with self.assertRaises(audit.AuditError):
                    audit.baseline(path)
                historical = audit.HISTORY[0]
                (root / historical).write_text('{}\n')
                with self.assertRaises(audit.AuditError):
                    audit.baseline(historical)
                with patch.object(audit, 'git', return_value='false\n'):
                    with self.assertRaises(audit.AuditError):
                        audit.baseline(path)

    def test_historical_consumer_guards_without_base_git_objects(self):
        # Exercise the actual entry points called by depth-one workflow jobs.
        # Other Git commands still run normally; no repository is mutated.
        with tempfile.TemporaryDirectory() as td:
            wrapper = Path(td) / 'git'
            wrapper.write_text(
                '#!' + sys.executable + '\nimport os, sys\n'
                'args = sys.argv[1:]\n'
                f'if args[:1] == ["show"] and args[1].startswith({audit.BASE_SHA!r} + ":"):\n'
                '    sys.exit(128)\n'
                'if args == ["rev-parse", "--is-shallow-repository"]:\n'
                '    print("true"); sys.exit(0)\n'
                f'os.execv({shutil.which("git")!r}, ["git", *args])\n')
            wrapper.chmod(0o755)
            env = {**os.environ, 'PATH': td + os.pathsep + os.environ['PATH']}
            for name in ('test_repro_workflow_batch1.py', 'test_repro_workflow_batch2.py',
                         'test_repro_population_pack_catalog.py'):
                with self.subTest(guard=name):
                    result = subprocess.run([sys.executable, str(ROOT / 'tests/ci' / name)],
                                            cwd=ROOT, env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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
            self.adoption_fixture(root)
            self.assertEqual(audit.validate(root,changed=[]),[])
            for path in (*audit.HISTORY,*audit.GUARD_HASHES,audit.EVIDENCE,audit.ADOPTION_EVIDENCE,
                         '.github/workflows/hero-population-strategy.yml'):
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

    # --- backlog-887: composite adoption of every REPRO consumer at HEAD ------
    def adoption_fixture(self, root):
        """Copy the adoption surface into a mutation fixture and bind its evidence.

        The fixture is complete enough for audit.validate(): every consumer
        workflow, both composite actions, the immutable historical proofs, the
        guarded tools/tests, the v1 transition evidence and the additive
        adoption evidence.
        """
        for path in (*audit.CONSUMER_WORKFLOWS, *audit.ACTION_HASHES, *audit.HISTORY,
                     *audit.GUARD_HASHES, audit.EVIDENCE):
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(audit.baseline(path) if path in audit.HISTORY else (ROOT / path).read_text())
        (root / audit.ADOPTION_EVIDENCE).write_text(
            json.dumps(audit.adoption_report(root), indent=2, sort_keys=True) + '\n')

    def test_composite_adoption_covers_every_consumer_at_head(self):
        summary = audit.check_composite_adoption()
        self.assertEqual(set(audit.CONSUMER_WORKFLOWS), {
            '.github/workflows/dataset-integrity.yml', '.github/workflows/full-hand-arena.yml',
            '.github/workflows/full-hand-protocol.yml', '.github/workflows/hero-calculated-range-export.yml',
            '.github/workflows/hero-population-strategy.yml', '.github/workflows/hero-range-compliance.yml',
            '.github/workflows/hero-range-editor.yml', '.github/workflows/model-b-card-aware-runtime.yml',
            '.github/workflows/model-b-reveal-aware.yml', '.github/workflows/population-pack-catalog.yml',
            '.github/workflows/postflop-response-refit.yml', '.github/workflows/preflop-grid-evaluator.yml',
            '.github/workflows/preflop-policy169.yml', '.github/workflows/preflop-search.yml',
            '.github/workflows/release-handoff-contract.yml', '.github/workflows/trainer-smoke.yml'})
        self.assertTrue(set(audit.WORKFLOWS).issubset(set(audit.CONSUMER_WORKFLOWS)))
        self.assertEqual(1, len(audit.CONSUMER_EXTRA_WORKFLOWS))
        self.assertEqual(summary['consumer_count'], len(audit.CONSUMER_WORKFLOWS))
        self.assertEqual(16, summary['runtime_consumer_count'])
        self.assertEqual(3, summary['browser_consumer_count'])
        self.assertEqual(summary['jobs_total'],
                         summary['jobs_with_composite'] + summary['jobs_recorded_exception'])
        self.assertEqual(0, summary['jobs_without_repro_signal'])
        self.assertEqual(0, summary['inline_bootstrap_in_composite_jobs'])
        self.assertEqual([r['job'] for r in summary['recorded_exceptions']], ['browser-smoke'])
        for row in summary['consumers']:
            with self.subTest(path=row['path']):
                text = (ROOT / row['path']).read_text()
                self.assertIn(audit.RUNTIME_CALL, text)
                self.assertTrue(row['references_runtime'])
                self.assertGreaterEqual(row['runtime_calls'], 1)
                self.assertEqual(row['references_browser'], audit.BROWSER_CALL in text)
                if audit.BROWSER_CALL in text:
                    self.assertGreaterEqual(row['browser_calls'], 1)
                self.assertTrue(row['composite_jobs'])
                self.assertEqual(audit.sha(text), row['sha256'])
        self.assertEqual(sum(row['runtime_calls'] for row in summary['consumers']),
                         summary['runtime_call_total'])
        self.assertEqual(sum(row['browser_calls'] for row in summary['consumers']),
                         summary['browser_call_total'])
        self.assertEqual(sum(1 for row in summary['consumers'] if row['references_browser']),
                         summary['browser_consumer_count'])
        browser_jobs = {(row['workflow'], row['job']) for row in
                        json.loads((ROOT / audit.EVIDENCE).read_text())['planning_matrix'] if row['browser']}
        self.assertEqual(4, len(browser_jobs))
        for path, job in browser_jobs:
            body = audit.jobs((ROOT / path).read_text())[job]
            if (path, job) in audit.INLINE_BOOTSTRAP_EXCEPTIONS:
                self.assertNotIn(audit.BROWSER_CALL, body)
            else:
                self.assertIn(audit.BROWSER_CALL, body, f'{path}:{job}')

    def test_adoption_check_is_fail_closed_on_regressions(self):
        regressions = (
            ('.github/workflows/trainer-smoke.yml', '      - name: JavaScript syntax\n',
             '      - uses: actions/setup-python@v5\n      - name: JavaScript syntax\n'),
            ('.github/workflows/trainer-smoke.yml',
             "      - uses: ./.github/actions/repro-runtime\n        with:\n          require-node: 'true'\n", ''),
            ('.github/workflows/preflop-search.yml', "require-node: 'true'", "require-node: 'false'"),
            ('.github/workflows/hero-population-strategy.yml',
             "      - '.github/actions/repro-runtime/action.yml'\n", ''),
            ('.github/workflows/population-pack-catalog.yml', '      - name: Assemble static site\n',
             '      - uses: actions/setup-node@v4\n      - name: Assemble static site\n'),
            ('.github/workflows/population-pack-catalog.yml',
             '          python3 tools/repro_ci_browser.py install > /tmp/repro-ci-browser.json\n', ''),
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.adoption_fixture(root)
            self.assertEqual(audit.validate(root, changed=[]), [])
            self.assertEqual(audit.check_composite_adoption(root), audit.check_composite_adoption(root))
            for path, old, new in regressions:
                with self.subTest(path=path, mutation=new):
                    target = root / path
                    original = target.read_text()
                    self.assertIn(old, original)
                    try:
                        target.write_text(original.replace(old, new, 1))
                        with self.assertRaises(audit.AuditError):
                            audit.check_composite_adoption(root)
                    finally:
                        target.write_text(original)
            self.assertEqual(audit.validate(root, changed=[]), [])

    def test_adoption_check_rejects_unregistered_consumer_and_migrated_exception(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.adoption_fixture(root)
            rogue = root / '.github/workflows/rogue-consumer.yml'
            rogue.write_text('name: Rogue\n\non:\n  workflow_dispatch:\n\njobs:\n  contract:\n'
                             '    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n'
                             f'      {audit.RUNTIME_CALL}\n')
            with self.assertRaises(audit.AuditError):
                audit.check_composite_adoption(root)
            rogue.unlink()
            exception = root / '.github/workflows/population-pack-catalog.yml'
            text = exception.read_text()
            head = ("      - uses: actions/setup-python@v5\n"
                    "        with:\n          python-version-file: '.python-version'\n")
            self.assertIn(head, text)
            self.assertIn(install_step_of(text), text)
            migrated = text.replace(head, f"      {audit.RUNTIME_CALL}\n        with:\n          require-node: 'false'\n", 1)
            migrated = migrated.replace(install_step_of(migrated), '', 1)
            try:
                exception.write_text(migrated)
                with self.assertRaises(audit.AuditError):
                    audit.check_composite_adoption(root)
            finally:
                exception.write_text(text)
            self.assertEqual(audit.validate(root, changed=[]), [])

    def test_adoption_evidence_is_measured_and_additive(self):
        stored = json.loads((ROOT / audit.ADOPTION_EVIDENCE).read_text())
        self.assertEqual(audit.adoption_report(), stored)
        self.assertEqual('poker-repro-composite-adoption/v1', stored['schema'])
        self.assertTrue(stored['additive'])
        self.assertFalse(stored['rewrites_v1_evidence'])
        self.assertEqual([], stored['workflow_files_modified'])
        self.assertFalse(stored['write_surface_expanded'])
        self.assertFalse(stored['scientific_commands_changed'])
        self.assertEqual(audit.EVIDENCE_SHA256, stored['source_evidence']['sha256'])
        self.assertNotEqual(audit.EVIDENCE_SHA256,
                            audit.file_sha256(ROOT / audit.ADOPTION_EVIDENCE))
        self.assertEqual(204, stored['issue'])
        # Residual duplication is measured, never assumed: the counters are
        # recomputed from the workflows and cross-checked against the workflow
        # inventory patterns used by tools/audit_github_workflows.py.
        counters = stored['residual_duplicates']
        for name, pattern in audit.DUPLICATE_PATTERNS.items():
            expected = sum(len(re.findall(pattern, (ROOT / path).read_text()))
                           for path in audit.CONSUMER_WORKFLOWS)
            self.assertEqual(expected, counters['consumer_totals'][name], name)
        self.assertEqual(counters['workflow_inventory_pattern_totals'],
                         {k: v for k, v in counters['repository_totals'].items()
                          if k in counters['workflow_inventory_pattern_totals']})
        # The composite action is the single home of each bootstrap primitive.
        for primitive in ('setup_python', 'setup_node', 'inline_environment', 'inline_browser'):
            self.assertEqual(1, counters['composite_totals'][primitive], primitive)
        # Inside the consumers only the recorded exception still holds a
        # bootstrap primitive; Node/pip/npm/playwright duplicates are gone.
        exceptions = stored['adoption']['recorded_exceptions']
        self.assertEqual(1, len(exceptions))
        for primitive, count in exceptions[0]['primitives'].items():
            self.assertEqual(count, counters['consumer_totals'][primitive], primitive)
        self.assertEqual(counters['consumer_totals']['checkout'], stored['adoption']['jobs_total'])
        self.assertEqual(counters['consumer_totals']['setup_node'], 0)
        self.assertEqual(counters['consumer_totals']['playwright_install'], 0)
        self.assertEqual(counters['consumer_totals']['pip_install'], 0)
        self.assertEqual(counters['consumer_totals']['npm_install'], 0)
        self.assertEqual(set(exceptions[0]['primitives']),
                         {name for name in ('setup_python', 'setup_node', 'inline_environment', 'inline_browser')
                          if counters['consumer_totals'][name]})
        self.assertEqual(stored['inline_bootstrap']['consumer_matches'],
                         stored['adoption']['inline_bootstrap_primitives'])
        self.assertEqual([], stored['adoption']['runtime_delegated_via_browser'])
        # Artifact fan-in/fan-out are static measurements with explicit unknowns.
        flow = stored['artifact_flow']
        self.assertEqual(len(flow['producers']), flow['fan_out_total'])
        self.assertEqual(len(flow['consumers']), flow['fan_in_total'])
        self.assertTrue(flow['edges'])
        self.assertEqual(len(flow['edges']), len({(e['artifact'], e['producer'], e['producer_job'],
                                                   e['consumer'], e['consumer_job'], e['kind'])
                                                  for e in flow['edges']}))
        self.assertTrue(any(row['kind'] == 'gh-run-download' for row in flow['consumers']))
        self.assertEqual({'ci_observation', 'artifact_retention_after_run',
                          'cross_run_artifact_availability', 'dynamic_artifact_names',
                          'github_billed_minutes'},
                         {row['id'] for row in stored['unknowns']})
        self.assertEqual(
            [dict(workflow=row['path'], job=row['job'], migratable=row['migratable'],
                  reason=row['reason'], recorded_by=row['evidence'], primitives=row['primitives'])
             for row in stored['adoption']['recorded_exceptions']],
            stored['deferred_migrations'])
        self.assertFalse(stored['adoption']['recorded_exceptions'][0]['migratable'])

    def test_adoption_evidence_and_transition_evidence_are_hash_bound(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.adoption_fixture(root)
            self.assertEqual(audit.validate(root, changed=[]), [])
            forged = json.loads((root / audit.ADOPTION_EVIDENCE).read_text())
            original = json.dumps(forged, indent=2, sort_keys=True) + '\n'
            for mutation in (lambda row: row['residual_duplicates']['consumer_totals'].update({'checkout': 99}),
                             lambda row: row['consumers'].pop(),
                             lambda row: row.update({'workflow_files_modified': ['.github/workflows/trainer-smoke.yml']})):
                with self.subTest(mutation=mutation):
                    forged = json.loads(original)
                    mutation(forged)
                    (root / audit.ADOPTION_EVIDENCE).write_text(json.dumps(forged, indent=2, sort_keys=True) + '\n')
                    with self.assertRaises(audit.AuditError):
                        audit.check_adoption_evidence(root)
                    self.assertTrue(audit.validate(root, changed=[]))
            (root / audit.ADOPTION_EVIDENCE).write_text(original)
            transition = root / audit.EVIDENCE
            transition.write_text(transition.read_text() + '\n')
            with self.assertRaises(audit.AuditError):
                audit.check_transition_evidence(root)

if __name__=='__main__':
    unittest.main()
