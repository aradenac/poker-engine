#!/usr/bin/env python3
"""Issue #384: exact Git-bound bootstrap transformation; no scientific execution.

Every byte outside the enumerated bootstrap spans and added action trigger paths
is compared, including YAML keys unknown to the inventory parser. Historical
proofs are read from Git, never regenerated from today's workflows.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from functools import lru_cache

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE_SHA = '571d91b041bad1eef196481148f3eae076a8dcec'
NAMES = ('trainer-smoke', 'hero-range-editor', 'hero-range-compliance',
         'population-pack-catalog', 'dataset-integrity', 'full-hand-arena',
         'full-hand-protocol', 'hero-calculated-range-export',
         'model-b-card-aware-runtime', 'model-b-reveal-aware',
         'postflop-response-refit', 'preflop-grid-evaluator', 'preflop-policy169',
         'preflop-search', 'release-handoff-contract')
WORKFLOWS = tuple(f'.github/workflows/{n}.yml' for n in NAMES)
RUNTIME = '.github/actions/repro-runtime/action.yml'
BROWSER = '.github/actions/repro-browser/action.yml'
EVIDENCE = 'analysis/workflow_audit/repro_composite_factorization_v1.json'
HISTORY = tuple('analysis/workflow_audit/' + n for n in (
    'repro_batch1_before_after.json', 'repro_batch2_before_after.json',
    'repro_population_pack_catalog_before_after.json',
    'repro_current_mixed_batch_before_after.json', 'residual_repro_dag_before_after.json'))
GUARDS = ('tools/audit_repro_workflow_batch1.py', 'tests/ci/test_repro_workflow_batch1.py',
          'tests/ci/test_repro_workflow_batch2.py', 'tests/ci/test_repro_population_pack_catalog.py',
          'tools/audit_repro_current_mixed_batch.py', 'tests/ci/test_repro_current_mixed_batch.py',
          'tools/audit_residual_repro_dag.py', 'tests/ci/test_residual_repro_dag.py')
ALLOWLIST = frozenset((*WORKFLOWS, RUNTIME, BROWSER, EVIDENCE, *GUARDS,
    'tools/audit_repro_composite_factorization.py', 'tests/ci/test_repro_composite_factorization.py',
    'analysis/workflow_audit/active_workflow_dag_v2.json', 'docs/ci-workflow-dag.md',
    'tools/audit_active_workflow_dag.py'))
# Independent reviewed content identities, not values trusted from editable evidence.
ACTION_HASHES = {'.github/actions/repro-runtime/action.yml': '1b90982bdb93f7332a1dd9353afbe8028bcd1e655a9d2ca175e60b1a55e22d42', '.github/actions/repro-browser/action.yml': '50c70f925dc8cb6eaab5c7b0e9a7f647f5eb8d92df22659781ac0f8fa6a64dda'}
GUARD_HASHES = {'tools/audit_repro_workflow_batch1.py': 'a4a01be7c3b52038bf2211163fd6e55a9035bb05d7cb62982322906e668a16a7', 'tests/ci/test_repro_workflow_batch1.py': '3d0112dadf28ece218247f1450ab928902b4240abe084d2c757d5f9e343aa630', 'tests/ci/test_repro_workflow_batch2.py': '095856c51cdbb2fa5c8677a835785cbd7f23d07f696335e66af60cab5902d48a', 'tests/ci/test_repro_population_pack_catalog.py': '4fac6d7f33f21c5c6f8745f8dba18fdda560f24029399d12797a346438bfe1d6', 'tools/audit_repro_current_mixed_batch.py': 'b6d9614b791b4bb612e8f7055c28a252ab3c1a64a40742655721c0b33b9a3481', 'tests/ci/test_repro_current_mixed_batch.py': '39faab8b2b64446b1f9c0ad91ed9b166de17e831a6767b7dcdec64a209ef6fd6', 'tools/audit_residual_repro_dag.py': '397ef8d5d5cc4d10e094929f1d4fce3d95f01b2cf1db890d09480d54b74f48df', 'tests/ci/test_residual_repro_dag.py': '9c2b261082f268ae8eb6471fe810322cd280c29a50c011b79d9ab08ae046e0a8'}

class AuditError(ValueError):
    pass

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True)

@lru_cache(maxsize=None)
def baseline(path):
    return git('show', f'{BASE_SHA}:{path}')

def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()

def blob(text):
    data = text.encode()
    return hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()

def jobs(text):
    body = text.split('\njobs:\n', 1)[1]
    starts = list(re.finditer(r'^  ([\w-]+):\n', body, re.M))
    return {m[1]: body[m.start(): starts[i+1].start() if i+1 < len(starts) else len(body)]
            for i,m in enumerate(starts)}

def steps(body):
    starts = list(re.finditer(r'^      - ', body, re.M))
    return [body[m.start(): starts[i+1].start() if i+1 < len(starts) else len(body)]
            for i,m in enumerate(starts)]

def plan(path, before):
    if path not in WORKFLOWS:
        raise AuditError(f'workflow outside allowlist: {path}')
    result = []
    for jid, body in jobs(before).items():
        blocks = steps(body)
        boot = [s for s in blocks if 'uses: actions/setup-' in s or
                'run: python3 tools/repro_ci_environment.py' in s or
                s.startswith('      - name: Install locked browser runtime\n')]
        browser = any('python3 tools/repro_ci_browser.py install' in s for s in boot)
        business = ''.join(s for s in blocks if s not in boot)
        node = bool(re.search(r'\bnode\s', business))
        # Only the two historical implicit static jobs may insert new runtime steps.
        if not boot and (path, jid) not in ((WORKFLOWS[0], 'static-contract'), (WORKFLOWS[1], 'contract')):
            raise AuditError(f'{path}:{jid}: BLOCKED: unknown implicit bootstrap')
        blocked = bool(boot and ''.join(boot) not in body)
        for block in boot:
            accepted = (
                r"      - uses: actions/setup-python@v5\n        with:\n          python-version(?:-file)?: '(?:3\.11\.9|\.python-version)'\n\s*",
                r"      - uses: actions/setup-node@v4\n        with:\n          node-version(?:-file)?: '(?:22|\.node-version)'\n\s*",
                r"      - name: Verify locked REPRO (?:environment|runtime)\n        run: python3 tools/repro_ci_environment.py verify(?: --require-node)?\n\s*",
                r"      - name: Install locked browser runtime\n        run: \|\n          set -euo pipefail\n          python3 tools/repro_ci_environment.py bootstrap --python-deps > /tmp/repro-ci-environment.json\n          python3 tools/repro_ci_browser.py install > /tmp/repro-ci-browser.json\n\s*",
            )
            if not any(re.fullmatch(rx, block) for rx in accepted):
                raise AuditError(f'{path}:{jid}: BLOCKED: stronger or unknown bootstrap')
        action = BROWSER if browser else RUNTIME
        call = (f"      - uses: ./{action.rsplit('/', 1)[0]}\n"
                f"        with:\n          require-node: '{str(node).lower()}'\n")
        result.append(dict(workflow=path, job=jid, python=True, node=node, browser=browser,
            install_python_deps=browser, install_node_deps=False, inline_steps=boot,
            action=action, inputs={'require-node':str(node).lower()}, replacement=call,
            justification=('Locked browser Python dependencies; no Node command' if browser else
                           'Python and Node business commands; verify only' if node else
                           'Python business commands; verify only') if not blocked else
                           'BLOCKED: site assembly executes between Python setup and dependency installation; moving it would change ordering',
            status='BLOCKED' if blocked else 'MIGRATE'))
    return result

def migrate(path, before):
    after = before
    rows = plan(path, before)
    for row in rows:
        if row['status'] == 'BLOCKED':
            continue
        body = jobs(after)[row['job']]
        old = ''.join(row['inline_steps'])
        if old:
            changed = body.replace(old, row['replacement'], 1)
        else:
            anchor = '      - uses: actions/checkout@v4\n'
            if body.count(anchor) != 1:
                raise AuditError('checkout must precede local composite')
            changed = body.replace(anchor, anchor + row['replacement'], 1)
        after = after.replace(body, changed, 1)
    paths = [RUNTIME] + ([BROWSER] if any(r['browser'] and r['status'] == 'MIGRATE' for r in rows) else [])
    addition = ''.join(f"      - '{p}'\n" for p in paths)
    return after.replace('    paths:\n', '    paths:\n' + addition)

def check_workflow(path, before, after):
    if after != migrate(path, before):
        raise AuditError(f'{path}: difference outside exact bootstrap/trigger transformation')

def check_actions(root=ROOT):
    for path, digest in ACTION_HASHES.items():
        if sha((root / path).read_text()) != digest:
            raise AuditError(f'{path}: composite content differs from reviewed contract')
    if set(ACTION_HASHES) != {RUNTIME, BROWSER}:
        raise AuditError('composite identities missing')

def historical_text(path, text, root=ROOT):
    """Check current composite bytes before exposing their immutable inline parent.

    Inline fixtures are intentionally left intact so original mutation suites
    continue to exercise the historical contracts. Current-consumer tests also
    call check_workflow directly, so removing every composite cannot bypass it.
    """
    if path not in WORKFLOWS or 'uses: ./.github/actions/repro-' not in text:
        return text
    check_actions(root)
    before = baseline(path)
    check_workflow(path, before, text)
    return before

def check_scope(paths):
    extra = set(paths) - ALLOWLIST
    if extra:
        raise AuditError(f'files outside allowlist: {sorted(extra)}')

def changed_files():
    return sorted(set(git('diff', '--name-only', BASE_SHA, '--').splitlines() +
                      git('ls-files', '--others', '--exclude-standard').splitlines()))

def historical_links():
    """Bind each immutable historical after to the transition's Git before."""
    links = []
    for evidence_path in HISTORY:
        evidence = json.loads(baseline(evidence_path))
        rows = evidence.get('workflows') or [dict(evidence, path=evidence['workflow'])]
        for row in rows:
            path = row['path']
            expected = row.get('after_git_blob_sha') or row.get('after_sha256') or row.get('after', {}).get('blob_sha')
            algorithm = 'sha256' if row.get('after_sha256') else 'git_blob_sha1'
            actual = sha(baseline(path)) if algorithm == 'sha256' else blob(baseline(path))
            if expected != actual:
                raise AuditError(f'{evidence_path}:{path}: historical after != transition before')
            links.append(dict(evidence=evidence_path, workflow=path, algorithm=algorithm,
                              historical_after=expected, transition_before=actual))
    return links


def validate(root=ROOT, changed=None):
    violations = []
    def check(fn, *args):
        try:
            fn(*args)
        except (ValueError, OSError) as exc:
            violations.append(str(exc))
    check(check_actions, root)
    check(historical_links)
    for path in WORKFLOWS:
        check(check_workflow, path, baseline(path), (root / path).read_text())
    for path in HISTORY:
        if (root / path).read_text() != baseline(path):
            violations.append(f'{path}: immutable historical evidence rewritten')
    for path, digest in GUARD_HASHES.items():
        if sha((root / path).read_text()) != digest:
            violations.append(f'{path}: historical guard changed outside reviewed adapter')
    check(check_scope, changed_files() if changed is None else changed)
    return violations

def metrics(texts):
    from tools.audit_active_workflow_dag import workflow
    bootstrap = []
    costs = 0
    for path, text in texts.items():
        for body in jobs(text).values():
            bootstrap.extend(s for s in steps(body) if 'uses: actions/setup-' in s or
                'run: python3 tools/repro_ci_environment.py' in s or
                s.startswith('      - name: Install locked browser runtime\n') or
                'uses: ./.github/actions/repro-' in s)
        costs += workflow(path, text, {'role':'contract'})['static_cost_proxy']['score']
    combined = ''.join(texts.values())
    return dict(workflows=len(texts), jobs=sum(len(jobs(t)) for t in texts.values()),
        inline_setup_python=combined.count('uses: actions/setup-python@'),
        inline_setup_node=combined.count('uses: actions/setup-node@'),
        inline_verify=combined.count('python3 tools/repro_ci_environment.py verify'),
        inline_bootstrap=combined.count('python3 tools/repro_ci_environment.py bootstrap'),
        inline_browser_install=combined.count('python3 tools/repro_ci_browser.py install'),
        yaml_bootstrap_lines=sum(len(s.rstrip().splitlines()) for s in bootstrap),
        runtime_jobs=combined.count('uses: ./.github/actions/repro-runtime'),
        browser_jobs=combined.count('uses: ./.github/actions/repro-browser'), static_cost_proxy=costs)

def report():
    from tools.audit_active_workflow_dag import workflow, simulate
    before = {p:baseline(p) for p in WORKFLOWS}
    after = {p:(ROOT / p).read_text() for p in WORKFLOWS}
    matrix = [r for p in WORKFLOWS for r in plan(p, before[p])]
    simulations = []
    for path in (RUNTIME, BROWSER, 'tools/repro_ci_environment.py', '.python-version', '.node-version'):
        for event in ('push', 'pull_request'):
            scenario = (path, event, path, 'main')
            simulations.append({'path':path, 'event':event, **{state:simulate([
                workflow(p,t,{'role':'contract'}) for p,t in texts.items()],scenario)
                for state,texts in [('before',before),('after',after)]}})
    return dict(schema='poker-repro-composite-factorization/v1', base_sha=BASE_SHA,
        planning_matrix=matrix, historical_links=historical_links(),
        jobs_blocked=[r for r in matrix if r['status']=='BLOCKED'],
        measurement_note='Static cost proxy is structural, not billed compute; composite steps still run.',
        workflows=[dict(path=p, before_blob=blob(before[p]),
            after_blob=blob(after[p]), reconstructible=after[p]==migrate(p,before[p])) for p in WORKFLOWS],
        actions={p:dict(sha256=sha((ROOT/p).read_text()),expected_sha256=h) for p,h in ACTION_HASHES.items()},
        historical_evidence=[dict(path=p,expected_blob=blob(baseline(p)),
            observed_blob=blob((ROOT/p).read_text()),unchanged=(ROOT/p).read_text()==baseline(p)) for p in HISTORY],
        metrics={'before':metrics(before),'after':metrics(after)}, simulations=simulations,
        write_surface_expanded=False, scientific_commands_changed=False, test_consumed=False,
        ci={'observed':False,'reason':'Local worker: no push/PR authorized',
            'review_table':[dict(workflow=p, expected_jobs=list(jobs(after[p])), observed_jobs=[],
                result='UNOBSERVED', scientific_job_unchanged=after[p]==migrate(p,before[p]),
                side_effect_unchanged=after[p]==migrate(p,before[p])) for p in WORKFLOWS]},
        claude_review='PENDING_EXTERNAL_REVIEW',
        local_tests=json.loads((ROOT/EVIDENCE).read_text()).get('local_tests', []) if (ROOT/EVIDENCE).exists() else [],
        violations=validate())

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--write',action='store_true')
    args=parser.parse_args()
    try:
        actual=report()
        if args.write:
            (ROOT/EVIDENCE).write_text(json.dumps(actual,indent=2,sort_keys=True)+'\n')
        if args.check and json.loads((ROOT/EVIDENCE).read_text()) != actual:
            actual['violations'].append('stored transition evidence differs from recomputed report')
        if actual['violations']:
            for v in actual['violations']: print('BLOCKED: '+v,file=sys.stderr)
            return 1
        print('REPRO composite factorization: PASS (15 workflows, 20 jobs)')
        return 0
    except (ValueError,OSError,subprocess.CalledProcessError) as exc:
        print(f'REPRO composite factorization: FAIL: {exc}',file=sys.stderr)
        return 1

if __name__=='__main__':
    raise SystemExit(main())
