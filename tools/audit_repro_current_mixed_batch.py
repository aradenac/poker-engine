#!/usr/bin/env python3
"""Git-bound, fail-closed migration contract for issue #380 (stdlib only).

The accepted language is the exact historical file plus a deterministic runtime
migration. We do not use a lossy YAML parser to authorize changes: all bytes outside
specified setup/path additions stay frozen, including unrecognized YAML keys.
The existing inventory parser is used only for human-readable evidence.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.audit_github_workflows import parse_triggers, parse_concurrency, section
from tools.repro_ci_environment import contract
from tools.repro_environment_identity import materialize_identity

BASE_SHA = '938c4af948f3246b04c8b211f834c26e16ea6fef'
NAMES = ('dataset-integrity', 'full-hand-protocol', 'hero-range-pfc-context',
         'preflop-grid-evaluator', 'preflop-policy169', 'release-handoff-contract',
         'release-no-pending-snapshot-proof')
WORKFLOWS = tuple(f'.github/workflows/{name}.yml' for name in NAMES)
NODE = frozenset(WORKFLOWS[2:4])
EVIDENCE = 'analysis/workflow_audit/repro_current_mixed_batch_before_after.json'
ALLOWLIST = frozenset((*WORKFLOWS, EVIDENCE,
                      'tools/audit_repro_current_mixed_batch.py',
                      'tests/ci/test_repro_current_mixed_batch.py'))
CHAIN_BASE_SHA = '571d91b041bad1eef196481148f3eae076a8dcec'
ISSUE_384_ALLOWLIST = frozenset((
    '.github/actions/repro-browser/action.yml',
    '.github/actions/repro-runtime/action.yml',
    '.github/workflows/dataset-integrity.yml',
    '.github/workflows/full-hand-arena.yml',
    '.github/workflows/full-hand-protocol.yml',
    '.github/workflows/hero-calculated-range-export.yml',
    '.github/workflows/hero-range-compliance.yml',
    '.github/workflows/hero-range-editor.yml',
    '.github/workflows/model-b-card-aware-runtime.yml',
    '.github/workflows/model-b-reveal-aware.yml',
    '.github/workflows/population-pack-catalog.yml',
    '.github/workflows/postflop-response-refit.yml',
    '.github/workflows/preflop-grid-evaluator.yml',
    '.github/workflows/preflop-policy169.yml',
    '.github/workflows/preflop-search.yml',
    '.github/workflows/release-handoff-contract.yml',
    '.github/workflows/trainer-smoke.yml',
    'analysis/workflow_audit/active_workflow_dag_v2.json',
    'analysis/workflow_audit/repro_composite_factorization_v1.json',
    'docs/ci-workflow-dag.md',
    'tests/ci/test_repro_composite_factorization.py',
    'tests/ci/test_repro_current_mixed_batch.py',
    'tests/ci/test_repro_population_pack_catalog.py',
    'tests/ci/test_repro_workflow_batch1.py',
    'tests/ci/test_repro_workflow_batch2.py',
    'tests/ci/test_residual_repro_dag.py',
    'tools/audit_active_workflow_dag.py',
    'tools/audit_repro_composite_factorization.py',
    'tools/audit_repro_current_mixed_batch.py',
    'tools/audit_repro_workflow_batch1.py',
    'tools/audit_residual_repro_dag.py',
))
INVENTORY = 'analysis/workflow_audit/workflows.json'
# Same transitive identity inputs as #366. .node-version is deliberately a
# trigger only for Node consumers, per #380, although contract() reads it globally.
REPRO_PATHS = (
    '.python-version', 'tools/repro_ci_environment.py',
    'tools/repro_environment_identity.py', 'tools/repro_container.py',
    'tools/repro_hardening.py', 'tools/repro_environment.py',
    'reproducibility/environment.lock.json', 'requirements.lock.txt',
    'package-lock.json', 'reproducibility/os-base.lock.json',
    'reproducibility/container-base.lock.json', 'reproducibility/Dockerfile.science',
    'reproducibility/system-packages.apt.txt', 'reproducibility/apt-snapshot.lock.json',
    'reproducibility/system-packages.resolution.lock.json',
    'reproducibility/browser-identity.lock.json', 'reproducibility/ubuntu-snapshot.sources',
)
OLD_PYTHON = "      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.11'\n"
PYTHON = OLD_PYTHON.replace("python-version: '3.11'", "python-version-file: '.python-version'")
OLD_NODE = "      - uses: actions/setup-node@v4\n        with:\n          node-version: '22'\n"
NEW_NODE = OLD_NODE.replace("node-version: '22'", "node-version-file: '.node-version'")
VERIFY = 'python3 tools/repro_ci_environment.py verify'


class AuditError(ValueError):
    pass


def git(*args: str) -> str:
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True)


def baseline(path: str) -> str:
    return git('show', f'{BASE_SHA}:{path}')


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def blob(text: str) -> str:
    data = text.encode()
    return hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()


def paths_for(path: str) -> tuple[str, ...]:
    return REPRO_PATHS + (('.node-version',) if path in NODE else ())


def verify_step(path: str) -> str:
    return ('      - name: Verify locked REPRO environment\n'
            f'        run: {VERIFY}' + (' --require-node' if path in NODE else '') + '\n')


def migrate(path: str, before: str) -> str:
    """Only approved edits; preserve every other byte, including blank lines."""
    if path not in WORKFLOWS:
        raise AuditError(f'workflow outside allowlist: {path}')
    after = before.replace('    paths:\n', '    paths:\n' + ''.join(
        f"      - '{p}'\n" for p in paths_for(path)))
    if path == WORKFLOWS[0]:
        anchor = '      - uses: actions/checkout@v4\n'
        if before.count(anchor) != 1 or 'actions/setup-python@' in before:
            raise AuditError('unexpected implicit Python baseline')
        after = after.replace(anchor, anchor + PYTHON + verify_step(path))
    elif path == WORKFLOWS[2]:
        after = after.replace(OLD_PYTHON, PYTHON + NEW_NODE + verify_step(path))
    elif path == WORKFLOWS[3]:
        after = after.replace(OLD_PYTHON + OLD_NODE, PYTHON + NEW_NODE + verify_step(path))
    else:
        after = after.replace(OLD_PYTHON, PYTHON + verify_step(path))
    return after


def check_workflow(path: str, before: str, after: str) -> None:
    from tools.audit_repro_composite_factorization import historical_text, AuditError as TransitionError
    try:
        after = historical_text(path, after)
    except TransitionError as exc:
        raise AuditError(str(exc)) from exc
    if after != migrate(path, before):
        raise AuditError(f'{path}: difference outside exact authorized REPRO migration')
    jobs = job_blocks(after)
    for job_id, body in jobs.items():
        if body.count(PYTHON) != 1 or body.count(verify_step(path)) != 1:
            raise AuditError(f'{path}:{job_id}: missing exact Python setup/verify')
        if body.count(NEW_NODE) != int(path in NODE):
            raise AuditError(f'{path}:{job_id}: unexpected Node setup')


@lru_cache(maxsize=1)
def inherited_scope() -> frozenset[str]:
    """Files already changed on main before the #384 transition base."""
    return frozenset(git('diff', '--name-only', BASE_SHA, CHAIN_BASE_SHA, '--').splitlines())


def check_scope(paths: list[str]) -> None:
    extra = set(paths) - ALLOWLIST - inherited_scope() - ISSUE_384_ALLOWLIST
    if extra:
        raise AuditError(f'files outside allowlist: {sorted(extra)}')


def changed_files() -> list[str]:
    tracked = git('diff', '--name-only', BASE_SHA, '--').splitlines()
    untracked = git('ls-files', '--others', '--exclude-standard').splitlines()
    return sorted({p for p in tracked + untracked
                   if '__pycache__' not in Path(p).parts and not p.endswith('.pyc')})


def job_blocks(text: str) -> dict[str, str]:
    body = '\n'.join(section(text.splitlines(), 'jobs')) + '\n'
    starts = list(re.finditer(r'^  ([\w-]+):\s*\n', body, re.M))
    return {m[1]: body[m.start(): starts[i+1].start() if i+1 < len(starts) else len(body)]
            for i, m in enumerate(starts)}


def steps(body: str) -> list[str]:
    starts = list(re.finditer(r'^      - ', body, re.M))
    return [body[m.start(): starts[i+1].start() if i+1 < len(starts) else len(body)].rstrip()
            for i, m in enumerate(starts)]


def field(body: str, name: str, indent: int) -> str | None:
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(' ' * indent + name + ':'):
            end = i + 1
            while end < len(lines) and (not lines[end].strip() or
                    len(lines[end]) - len(lines[end].lstrip()) > indent):
                end += 1
            return '\n'.join(lines[i:end]).rstrip()
    return None


def snapshot(path: str, text: str) -> dict:
    jobs = {}
    commands = {}
    artifacts = {}
    for jid, body in job_blocks(text).items():
        blocks = steps(body)
        runtime = [s for s in blocks if re.search(r'^      - uses: actions/setup-(python|node)@', s)]
        helpers = [s for s in blocks if f'        run: {VERIFY}' in s]
        business = [s for s in blocks if s not in runtime + helpers]
        commands[jid] = business
        artifacts[jid] = [s for s in business if re.search(r'actions/(upload|download)-artifact@', s)]
        jobs[jid] = {
            'metadata_raw': body.split('    steps:', 1)[0].rstrip(),
            **{key: field(body, key, 4) for key in
               ('needs', 'if', 'permissions', 'env', 'strategy', 'timeout-minutes', 'runs-on')},
            'python_setup': [s for s in runtime if 'setup-python@' in s],
            'node_setup': [s for s in runtime if 'setup-node@' in s],
            'helper_calls': helpers,
            'runtime_versions': {
                'python': '.python-version' if PYTHON.rstrip() in runtime else
                          ('3.11' if OLD_PYTHON.rstrip() in runtime else 'implicit'),
                'node': ('.node-version' if NEW_NODE.rstrip() in runtime else
                         ('22' if OLD_NODE.rstrip() in runtime else 'implicit')) if path in NODE else None,
            },
            'python_floating': int(PYTHON.rstrip() not in runtime),
            'node_floating': int(path in NODE and NEW_NODE.rstrip() not in runtime),
        }
    write = [jid for jid, j in jobs.items() if re.search(r':\s*write\b',
             j['permissions'] or field(text, 'permissions', 0) or '')]
    # Fail closed: only the exact existing push guard is classified as PR-safe.
    safe = "    if: >-\n      github.event_name == 'push' &&\n      github.ref_name == 'execute/issue-113-no-pending-release-20260918'"
    pr_write = [jid for jid in write if jobs[jid]['if'] != safe]
    encode = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'))
    return {
        'blob_sha': blob(text), 'name': field(text, 'name', 0),
        'triggers': parse_triggers(text.splitlines()),
        'permissions': field(text, 'permissions', 0),
        'concurrency': parse_concurrency(text.splitlines()), 'env': field(text, 'env', 0),
        'jobs': jobs, 'business_steps': commands, 'artifact_identities': artifacts,
        'command_fingerprint': sha(encode(commands)),
        'artifact_fingerprint': sha(encode(artifacts)),
        'write_jobs': write, 'pr_executable_write_jobs': pr_write,
        'python_floating_setups': sum(bool(j['python_setup']) and j['python_floating'] for j in jobs.values()),
        'python_implicit_jobs': sum(not j['python_setup'] for j in jobs.values()),
        'node_floating_setups': sum(bool(j['node_setup']) and j['node_floating'] for j in jobs.values()),
        'node_implicit_jobs': sum(path in NODE and not j['node_setup'] for j in jobs.values()),
        'python_floating': sum(j['python_floating'] for j in jobs.values()),
        'node_floating': sum(j['node_floating'] for j in jobs.values()),
    }


def report(tests: list[dict]) -> dict:
    changed = changed_files()
    check_scope(changed)
    changed = sorted(set(changed) | {EVIDENCE})
    inventory_text = baseline(INVENTORY)
    inventory = json.loads(inventory_text)
    lifecycle = {row['path']: row['lifecycle'] for row in inventory['workflows']}
    spec = contract(ROOT)
    materialize_identity(ROOT)  # Existing helper validates all transitive locks.
    rows = []
    for path in WORKFLOWS:
        if lifecycle.get(path) != 'current':
            raise AuditError(f'{path}: not current in Git-bound inventory')
        before, after = baseline(path), (ROOT / path).read_text()
        check_workflow(path, before, after)
        b, a = snapshot(path, before), snapshot(path, after)
        if b['command_fingerprint'] != a['command_fingerprint']:
            raise AuditError(f'{path}: business commands changed')
        rows.append({'path': path, 'before': b, 'after': a,
                     'added_repro_paths': {event: [
                         {'path': p, 'justification':
                          'Exact runtime version selector' if p.startswith('.') else
                          'Transitive verify/identity source; no dependency installation'}
                         for p in paths_for(path)]
                         for event, cfg in b['triggers'].items() if 'paths' in cfg}})
    totals = {state: {key: sum(row[state][key] for row in rows)
                     for key in ('python_floating', 'node_floating', 'python_floating_setups',
                                 'python_implicit_jobs', 'node_floating_setups', 'node_implicit_jobs')} for state in ('before', 'after')}
    for state in totals:
        for key in ('write_jobs', 'pr_executable_write_jobs'):
            totals[state][key] = [f"{r['path']}:{jid}" for r in rows for jid in r[state][key]]
    return {
        'schema': 'poker-repro-current-mixed-batch/v1', 'issue': 380, 'base_sha': BASE_SHA,
        'inventory_source': INVENTORY, 'inventory_source_sha': blob(inventory_text),
        'inventory_snapshot_base_sha': inventory['snapshot_base_sha'],
        'workflow_paths': list(WORKFLOWS), 'workflows': rows, 'totals': totals,
        'runtime_versions': spec['expected'],
        'lock_sha256_consumed': {p: sha((ROOT / p).read_text()) for p in REPRO_PATHS
                                if p.endswith(('.json', '.txt', '.sources')) or 'Dockerfile' in p},
        'scientific_commands_changed': False, 'scientific_gate_changed': False,
        'write_surface_expanded': False, 'test_consumed': False,
        'files_changed': changed, 'local_tests': tests,
        'local_tests_environment': {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': '.'},
        'local_execution_observations': {
            'scientific_test_or_validation_executed': False,
            'test_consumed': False,
            'production_effect': 'NONE',
            'disposition': 'PASS: contract and static audit validation only; no scientific '
                'TEST/VALIDATION command was executed.',
        },
        'permissions_assessment': 'Write-job counts describe explicit workflow/job grants. '
            'Hero has no permissions declaration: repository defaults are unknown and unchanged.',
        'local_tests_excluded': {
            'tests/datasets/test_persisted_snapshot.py':
                'Reads real persisted scientific snapshots and runs coverage audits; '
                'not needed to verify this runtime-only migration.',
            'dataset-integrity reconstruction commands':
                'Preserved byte-for-byte; not executed to avoid new scientific work.',
        },
        'ci': {'observed': False, 'claude_review': 'PENDING_ORCHESTRATOR',
               'expected_pr_jobs': {r['path']: {
                   jid: ('SKIPPED' if jid == 'prove-no-publication' else 'RUN')
                   for jid in r['after']['jobs']} for r in rows},
               'scientific_job_review': {
                   'dataset-integrity:integrity': 'Existing dataset/candidate reconstructions run on PR.',
                   'hero-range-pfc-context:contract': 'Existing context test reruns TRAIN/VALIDATION #339.',
                   'preflop-grid-evaluator:preflop-grid': 'Existing test imports VALIDATION benchmark #338.',
               },
               'note': 'Existing dataset reconstruction steps remain unchanged; not executed locally. '
                       'No PR or remote CI created by this worker.'},
        'node_version_trigger_exception': '.node-version is read by the shared identity helper '
            'for all jobs, but only the two Node workflows trigger on it, as required by #380.',
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--write', action='store_true')
    parser.add_argument('--results', type=Path, help='Actual local command results recorded by the worker')
    args = parser.parse_args()
    try:
        stored = json.loads((ROOT / EVIDENCE).read_text()) if (ROOT / EVIDENCE).exists() else {}
        tests = json.loads(args.results.read_text()) if args.results else stored.get('local_tests', [])
        actual = report(tests)
        if args.check:
            if actual != stored:
                raise AuditError('evidence differs from recomputed Git/worktree contract')
        else:
            (ROOT / EVIDENCE).write_text(json.dumps(actual, indent=2, sort_keys=True) + '\n')
        print('REPRO current mixed batch: PASS (7 workflows; immutable business steps)')
        return 0
    except (AuditError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'REPRO current mixed batch: FAIL: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
