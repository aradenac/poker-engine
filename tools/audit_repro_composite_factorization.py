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
GUARD_HASHES = {'tools/audit_repro_workflow_batch1.py': 'a4a01be7c3b52038bf2211163fd6e55a9035bb05d7cb62982322906e668a16a7', 'tests/ci/test_repro_workflow_batch1.py': '648604cdcd1326680e93df63d7295b5cf04cbe42dc5f02c58b04c2a0395ae7db', 'tests/ci/test_repro_workflow_batch2.py': '8d529bff8497130989461df46153757853896174a21e4f8be2bac61ddfff3e5b', 'tests/ci/test_repro_population_pack_catalog.py': '4fac6d7f33f21c5c6f8745f8dba18fdda560f24029399d12797a346438bfe1d6', 'tools/audit_repro_current_mixed_batch.py': 'a08b85f7c2664bcc0ac96aadf3d15e8113456b6198d749b47cbc3a5175e90487', 'tests/ci/test_repro_current_mixed_batch.py': 'ff7324e98417091debb46ae51c6247bb9661e5cb77fa9afb6e15ae29798562d5', 'tools/audit_residual_repro_dag.py': 'd41a0e56b44a17955d6f4616bb4aff81c7f25942f0a313c930762eb13618470f', 'tests/ci/test_residual_repro_dag.py': 'b682f70939f6b7b9a84c9c586f971f7639721b33feaf504ac220bc6df6f5111a'}

# Content identities captured from BASE_SHA, independently of editable evidence.
# Unchanged historical sources need no duplicate payload; workflow before texts
# are carried in the new transition evidence for depth-one consumer checkouts.
BASELINE_HASHES = {'.github/workflows/continuous-training-cycle.yml': '9516dc6252f51fd7429ed24a415866d1f45ea74050223ad2c39c2f4b739588c5',
 '.github/workflows/dataset-integrity.yml': 'dc61294edc71f5551c7ecdc0a645b298b1d9a7eed94dc7d4f295048684aa17d3',
 '.github/workflows/full-hand-arena.yml': '6997be3eae49b673e792dddb740bf6c5b8bf0230197f52f9476feae2744bc187',
 '.github/workflows/full-hand-protocol.yml': '178c43ba383d865d29f8520b4effbab5c925d2ac02522504da8119e24ea82b99',
 '.github/workflows/hero-calculated-range-export.yml': 'd8cb95b363e273c8cee78ff206e4a0ea40ba8254e455873b3f0bab23cdcf66c5',
 '.github/workflows/hero-range-compliance.yml': '30285d84a72f4a9e985ecbc935955229905010e461b28e01ab31bfe8faf78e5d',
 '.github/workflows/hero-range-editor.yml': '8f47e3b352b2b6c98d3ae6e48afb4feb5ee45dd426fd857316510b64259ba2d2',
 '.github/workflows/hero-range-pfc-context.yml': '98974ef953442d925c6876abd5968286e6a27d31c1f533c6826f0a7c0308206c',
 '.github/workflows/ingest-artifacts.yml': 'fca6c2941d017ec3785469d3bcef445fae376c234edfaf10f760747c6e3d0ffc',
 '.github/workflows/materialize-certified-population.yml': 'b560e997c20b5f2e43ceb0a800695ac135691a0f96f4566a5da3aeccbd088efa',
 '.github/workflows/model-b-card-aware-runtime.yml': 'eebb7aaac40596f6ae53daa1432aa7682b68423b1afa245bfbd8272a5157bd0b',
 '.github/workflows/model-b-reveal-aware.yml': 'c44861b492ff485993e9ce244fb21ced855f61883d8227857a522ebaceb17c00',
 '.github/workflows/plan-ingested-cycle.yml': '0b1d9816a17604f4f76e46390a4aeb11522947e8977b31a854322435a00f4de8',
 '.github/workflows/population-certification.yml': 'a1d0ce23c35f5240a6d8b97446994574e62711f55a40a030cd518d7939bd10b1',
 '.github/workflows/population-pack-catalog.yml': 'dc5f481fabfaadb27b39af15f3e2f10e600888bcb9de5138afbda7084c68bab2',
 '.github/workflows/postflop-response-refit.yml': 'c3f541a99755ff3c98fd59ca76d06429a743ff3fabafb0bce452d15c37b6a914',
 '.github/workflows/preflop-grid-evaluator.yml': 'c415a1db1b746910aec92aa975bb01a80cc8a49bb738492cedd77102cc1b6478',
 '.github/workflows/preflop-policy169.yml': '498a26bb9506cd490382de72acf3b6ed684073f09477117ad550f3a5f9589075',
 '.github/workflows/preflop-search.yml': '4b3264cd7ef5204bc8de32da0817c197a59cff4e62501a81b603dcc383503fb5',
 '.github/workflows/release-handoff-contract.yml': 'a0c1172d254eb023d389dc9d7b436f77861d5e21968927a2e81804aaf1ff5a50',
 '.github/workflows/release-no-pending-snapshot-proof.yml': 'a692be020f2104cd7612b52a2964b80b2d43db54955a3396f1d455cd01a9a34d',
 '.github/workflows/trainer-smoke.yml': 'df5c3226c697515daace3cd4c5484195ba5b85f3111e36061b5220d2df8d0b1d',
 '.github/workflows/user-artifact-bundle.yml': 'ef0c0b6c53e77752b20a264618c4618ebee987f794b8503eacb7e6b9a2072ee8',
 'analysis/workflow_audit/repro_batch1_before_after.json': '2cd38d637a803835b50af2b42fa3610fe6ae39fea229a211ef920547ae020f98',
 'analysis/workflow_audit/repro_batch2_before_after.json': '5c0836494e65e5bf1c4d9d5763026fa9a137a12f8dc9087e971b914295005b13',
 'analysis/workflow_audit/repro_current_mixed_batch_before_after.json': '5f0024073daa06c711ddca9fb8b46aae875ab7a0f1448d0b32c84fcfe1eb7e5f',
 'analysis/workflow_audit/repro_population_pack_catalog_before_after.json': 'fceb4051f190aa73a2435d430016982a2e55630d1fc1cf5874b16f7ab13de8f1',
 'analysis/workflow_audit/residual_repro_dag_before_after.json': '20f7421fec174f074764685ccad6d37e16c241c1e1f747ad2dc05c0be4933021'}

class AuditError(ValueError):
    pass

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True)

@lru_cache(maxsize=None)
def baseline(path):
    if path not in BASELINE_HASHES:
        raise AuditError(f'{path}: unbound transition baseline')
    try:
        text = subprocess.check_output(
            ['git', 'show', f'{BASE_SHA}:{path}'], cwd=ROOT,
            text=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        # GitHub checkout defaults to depth one. Do not fetch over the network,
        # change checkout settings, or accept an unverified evidence payload.
        if git('rev-parse', '--is-shallow-repository').strip() != 'true':
            raise AuditError(f'{path}: base Git object unavailable in full checkout')
        if path in WORKFLOWS:
            evidence = json.loads((ROOT / EVIDENCE).read_text())
            if evidence.get('base_sha') != BASE_SHA:
                raise AuditError('transition evidence base SHA changed')
            text = evidence.get('baseline_workflows', {}).get(path)
        else:
            text = (ROOT / path).read_text()
    if not isinstance(text, str) or sha(text) != BASELINE_HASHES[path]:
        raise AuditError(f'{path}: transition baseline content identity mismatch')
    return text

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
        baseline_workflows=before, planning_matrix=matrix, historical_links=historical_links(),
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
