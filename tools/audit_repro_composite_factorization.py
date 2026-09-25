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
# Additive proof for issue #204 / backlog-887. The v1 transition evidence above is
# immutable and is never rewritten by this file.
ADOPTION_EVIDENCE = 'analysis/workflow_audit/repro_composite_adoption_v1.json'
ADOPTION_SCHEMA = 'poker-repro-composite-adoption/v1'
EVIDENCE_SHA256 = 'c06120b8b7d45dd3a4201a2e94fa3e6e3c7f29a335546651a867a2ba009f4ccf'
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
# ---------------------------------------------------------------------------
# Issue #204 / backlog-887: composite adoption of every REPRO consumer.
# ---------------------------------------------------------------------------
# Every workflow that calls a REPRO composite action at this SHA. The v1
# transition covers the first 15; hero-population-strategy was authored after the
# transition with the composite already applied, so it only has this proof.
CONSUMER_NAMES = (*NAMES, 'hero-population-strategy')
CONSUMER_WORKFLOWS = tuple(f'.github/workflows/{n}.yml' for n in CONSUMER_NAMES)
CONSUMER_EXTRA_WORKFLOWS = tuple(p for p in CONSUMER_WORKFLOWS if p not in WORKFLOWS)
ALLOWLIST = frozenset((*ALLOWLIST, ADOPTION_EVIDENCE, *CONSUMER_EXTRA_WORKFLOWS))
RUNTIME_CALL = 'uses: ./.github/actions/repro-runtime'
BROWSER_CALL = 'uses: ./.github/actions/repro-browser'
# Inline REPRO bootstrap primitives. Their single home is the composite action;
# any occurrence inside a consumer job is a residual duplicate or a recorded
# exception.
INLINE_BOOTSTRAP_PATTERNS = (
    ('setup_python', 'uses: actions/setup-python@'),
    ('setup_node', 'uses: actions/setup-node@'),
    ('inline_environment', 'python3 tools/repro_ci_environment.py'),
    ('inline_browser', 'python3 tools/repro_ci_browser.py'),
)
# Same regular expressions as tools/audit_github_workflows.py so residual
# counters stay comparable with analysis/workflow_audit/workflows.json.
DUPLICATE_PATTERNS = {
    'checkout': r'actions/checkout@',
    'setup_python': r'actions/setup-python@',
    'setup_node': r'actions/setup-node@',
    'pip_install': r'(?:\bpip(?:3)?\s+install\b|python3?\s+-m\s+pip\s+install)',
    'playwright_install': r'playwright\s+install',
    'npm_install': r'\bnpm\s+(?:ci|install)\b',
    'upload_artifact': r'actions/upload-artifact@',
    'download_artifact': r'(?:actions/download-artifact@|\bgh\s+run\s+download\b)',
    'inline_environment': r'python3 tools/repro_ci_environment\.py',
    'inline_browser': r'python3 tools/repro_ci_browser\.py',
}
NODE_COMMAND = re.compile(r'\bnode\s+(?:--[\w-]+|[\w./-]+\.(?:m?js|cjs))')
PYTHON_COMMAND = re.compile(r'\bpython3(?:\.\d+)?\s')
REQUIRE_NODE_INPUT = re.compile(r"require-node:\s*'(\w+)'")
# Frozen, non-migratable residual: the v1 planning matrix records this job
# BLOCKED because static site assembly runs between Python setup and the locked
# dependency install. Inserting the composite would reorder the assembly and
# re-baseline immutable v1 evidence, which is outside backlog-887.
INLINE_BOOTSTRAP_EXCEPTIONS = {
    ('.github/workflows/population-pack-catalog.yml', 'browser-smoke'): dict(
        primitives={'setup_python': 1, 'inline_environment': 1, 'inline_browser': 1},
        migratable=False,
        blocked_status='BLOCKED',
        reason=('static site assembly runs between Python setup and the locked '
                'dependency install; the composite cannot be inserted without '
                'reordering the assembly and re-baselining immutable v1 evidence'),
        evidence=EVIDENCE),
}
UNKNOWN_MEASUREMENTS = (
    dict(id='ci_observation', detail='no run was observed at this SHA; adoption is proven statically only'),
    dict(id='artifact_retention_after_run', detail='retention-days are declared in YAML; actual retention and expiry are runtime state and are not measurable from a checkout'),
    dict(id='cross_run_artifact_availability', detail='gh run download targets artifacts of other runs; their existence is not verifiable locally'),
    dict(id='dynamic_artifact_names', detail='artifact names containing ${{ ... }} are matched as shapes, so name-level fan-in/fan-out edges are partial'),
    dict(id='github_billed_minutes', detail='cost proxies are structural; no billed minutes were measured'),
)
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


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def transition_evidence(root=ROOT):
    """Expose the immutable v1 matrix, refusing a rewritten transition payload."""
    path = Path(root) / EVIDENCE
    if not path.exists():
        raise AuditError(f'{EVIDENCE}: transition evidence missing')
    digest = file_sha256(path)
    if digest != EVIDENCE_SHA256:
        raise AuditError(f'{EVIDENCE}: immutable transition evidence rewritten ({digest})')
    return json.loads(path.read_text())


def check_transition_evidence(root=ROOT):
    """Backlog-887 proof that the v1 factorization payload stayed byte-identical."""
    transition_evidence(root)


def workflow_texts(root=ROOT):
    directory = Path(root) / '.github/workflows'
    if not directory.is_dir():
        raise AuditError(f'{root}: no .github/workflows directory to enumerate consumers')
    return {f'.github/workflows/{p.name}': p.read_text() for p in sorted(directory.glob('*.yml'))}


def nonzero(counts):
    return {name: value for name, value in counts.items() if value}


def inline_bootstrap_counts(body):
    return {name: body.count(pattern) for name, pattern in INLINE_BOOTSTRAP_PATTERNS}


def composite_calls(body):
    return {'runtime': body.count(RUNTIME_CALL), 'browser': body.count(BROWSER_CALL)}


def is_repro_relevant(body):
    """True when a job performs REPRO-visible work and therefore needs the composite."""
    if any(pattern in body for _, pattern in INLINE_BOOTSTRAP_PATTERNS):
        return True
    return bool(PYTHON_COMMAND.search(body) or NODE_COMMAND.search(body) or
                re.search(r'\bnpm\s+(?:ci|install)\b', body))


def composite_consumers(text):
    """Jobs that call a REPRO composite action, keyed by job id."""
    if '\njobs:\n' not in text:
        raise AuditError('workflow has no jobs block to scan for composite consumers')
    rows = {}
    for jid, body in jobs(text).items():
        calls = composite_calls(body)
        if calls['runtime'] or calls['browser']:
            rows[jid] = calls
    return rows


def check_composite_adoption(root=ROOT):
    """Fail closed unless every REPRO consumer uses the composite actions.

    Proves, per consumer job: (a) the composite action is called instead of an
    inline REPRO bootstrap block, (b) no inline bootstrap block was reintroduced,
    (c) the `require-node` input matches the job's real Node usage, (d) browser
    jobs recorded by the v1 matrix call the browser composite, and (e) trigger
    path filters still include the composite action they depend on.
    """
    evidence = transition_evidence(root)
    texts = workflow_texts(root)
    observed = {path: composite_consumers(text) for path, text in texts.items()}
    observed = {path: rows for path, rows in observed.items() if rows}
    if set(observed) != set(CONSUMER_WORKFLOWS):
        raise AuditError('composite consumer set changed: missing=%s unregistered=%s' % (
            sorted(set(CONSUMER_WORKFLOWS) - set(observed)),
            sorted(set(observed) - set(CONSUMER_WORKFLOWS))))
    matrix = {(row['workflow'], row['job']): row for row in evidence['planning_matrix']}
    summary = dict(consumer_count=len(CONSUMER_WORKFLOWS), runtime_consumer_count=0,
                   browser_consumer_count=0, runtime_call_total=0, browser_call_total=0,
                   jobs_total=0, jobs_with_composite=0, jobs_recorded_exception=0,
                   jobs_without_repro_signal=0, inline_bootstrap_jobs=0,
                   inline_bootstrap_primitives=0, inline_bootstrap_in_composite_jobs=0,
                   runtime_delegated_via_browser=[],
                   consumers=[], recorded_exceptions=[])
    for path in CONSUMER_WORKFLOWS:
        bodies = jobs(texts[path])
        calls = observed[path]
        runtime_calls = sum(1 for row in calls.values() if row['runtime'])
        browser_calls = sum(1 for row in calls.values() if row['browser'])
        summary['runtime_consumer_count'] += int(runtime_calls > 0)
        summary['browser_consumer_count'] += int(browser_calls > 0)
        summary['runtime_call_total'] += sum(row['runtime'] for row in calls.values())
        summary['browser_call_total'] += sum(row['browser'] for row in calls.values())
        if runtime_calls == 0:
            if browser_calls == 0:
                raise AuditError(f'{path}: consumer without a REPRO composite call')
            summary['runtime_delegated_via_browser'].append(path)
        summary['jobs_total'] += len(bodies)
        summary['consumers'].append(dict(path=path, jobs=sorted(bodies),
            composite_jobs=sorted(calls), runtime_calls=runtime_calls,
            browser_calls=browser_calls, references_runtime=runtime_calls > 0,
            references_browser=browser_calls > 0,
            sha256=sha(texts[path]), blob_sha1=blob(texts[path])))
        for jid, body in bodies.items():
            key = (path, jid)
            call = calls.get(jid)
            primitives = nonzero(inline_bootstrap_counts(body))
            exception = INLINE_BOOTSTRAP_EXCEPTIONS.get(key)
            if call:
                summary['jobs_with_composite'] += 1
                summary['inline_bootstrap_in_composite_jobs'] += int(bool(primitives))
                if primitives:
                    raise AuditError(f'{path}:{jid}: inline REPRO bootstrap reintroduced next to the composite action: {primitives}')
                if exception is not None:
                    raise AuditError(f'{path}:{jid}: stale inline exception; the job now uses the composite action')
                require = REQUIRE_NODE_INPUT.findall(body)
                expected = 'true' if NODE_COMMAND.search(body) else 'false'
                if require != [expected]:
                    raise AuditError(f'{path}:{jid}: composite require-node={require} does not match observed Node usage ({expected})')
                continue
            if exception is None:
                if primitives or is_repro_relevant(body):
                    raise AuditError(f'{path}:{jid}: REPRO work without the composite action and without a recorded exception: {primitives}')
                summary['jobs_without_repro_signal'] += 1
                continue
            if primitives != exception['primitives']:
                raise AuditError(f'{path}:{jid}: recorded inline exception primitives changed: {primitives}')
            if exception['migratable']:
                raise AuditError(f'{path}:{jid}: migratable exception must be migrated, not documented')
            row = matrix.get(key)
            if row is None or row['status'] != exception['blocked_status']:
                raise AuditError(f'{path}:{jid}: inline exception is not the v1 {exception["blocked_status"]} row')
            summary['jobs_recorded_exception'] += 1
            summary['inline_bootstrap_jobs'] += 1
            summary['inline_bootstrap_primitives'] += sum(primitives.values())
            summary['recorded_exceptions'].append(dict(path=path, job=jid,
                primitives=primitives, migratable=False, reason=exception['reason'],
                evidence=exception['evidence']))
    if summary['jobs_with_composite'] + summary['jobs_recorded_exception'] + summary['jobs_without_repro_signal'] != summary['jobs_total']:
        raise AuditError('composite adoption job accounting does not close')
    for row in evidence['planning_matrix']:
        if not row['browser']:
            continue
        key = (row['workflow'], row['job'])
        body = jobs(texts[row['workflow']]).get(row['job'])
        if body is None:
            raise AuditError(f'{row["workflow"]}:{row["job"]}: browser job from the v1 matrix disappeared')
        if row['status'] == 'MIGRATE':
            if BROWSER_CALL not in body:
                raise AuditError(f'{row["workflow"]}:{row["job"]}: browser job does not call {BROWSER}')
        elif key not in INLINE_BOOTSTRAP_EXCEPTIONS:
            raise AuditError(f'{row["workflow"]}:{row["job"]}: unresolved browser bootstrap without a recorded exception')
    from tools.audit_github_workflows import parse_triggers
    for path in CONSUMER_WORKFLOWS:
        triggers = parse_triggers(texts[path].splitlines())
        needs = [RUNTIME] + ([BROWSER] if BROWSER_CALL in texts[path] else [])
        for event, config in sorted(triggers.items()):
            filters = config.get('paths') or []
            for action in needs:
                if filters and action not in filters:
                    raise AuditError(f'{path}:{event}: path filter no longer includes {action}')
    return summary


def duplicate_counters(text):
    return {name: len(re.findall(pattern, text)) for name, pattern in DUPLICATE_PATTERNS.items()}


def residual_duplicates(root=ROOT):
    """Measure the duplication that is still real at this SHA; no value is assumed."""
    texts = workflow_texts(root)
    consumer_rows = [dict(workflow=path, **duplicate_counters(texts[path])) for path in CONSUMER_WORKFLOWS]
    actions = {path: duplicate_counters((Path(root) / path).read_text()) for path in (RUNTIME, BROWSER)}
    repository_rows = [dict(workflow=path, **duplicate_counters(text)) for path, text in sorted(texts.items())]
    def totals(rows):
        return {name: sum(row[name] for row in rows) for name in DUPLICATE_PATTERNS}
    shared = {name: pattern for name, pattern in DUPLICATE_PATTERNS.items()
              if name not in ('inline_environment', 'inline_browser')}
    shared_totals = {name: sum(len(re.findall(pattern, (Path(root) / path).read_text()))
                              for path in sorted(texts)) for name, pattern in shared.items()}
    return dict(consumers=consumer_rows, consumer_totals=totals(consumer_rows),
        composite_actions=actions, composite_totals=totals([actions[RUNTIME], actions[BROWSER]]),
        repository_totals=totals(repository_rows), repository_rows=repository_rows,
        workflow_inventory_pattern_totals=shared_totals,
        measurement_note=('counters are measured by textual scan of each workflow at this SHA; '
                          'setup-python/setup-node/verify/bootstrap now live once per composite action'))


def _step_field(step, field):
    for match in re.finditer(r'(?m)^(\s+)' + re.escape(field) + r':\s*(.+?)\s*$', step):
        if len(match.group(1)) >= 10:
            value = match.group(2)
            return value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in '\'"' else value
    return None


def _artifact_shape(name):
    if name is None:
        return None
    shaped = re.sub(r'\$\{\{[^}]*\}\}', '*', name)
    return re.sub(r'\*+', '*', shaped).strip()


def artifact_flow(root=ROOT):
    """Static fan-out/fan-in of GitHub artifacts; runtime retention stays UNKNOWN."""
    producers, consumers, unparsed = [], [], []
    for path, text in sorted(workflow_texts(root).items()):
        for jid, body in jobs(text).items():
            for step in steps(body):
                if 'actions/upload-artifact@' in step:
                    name = _step_field(step, 'name')
                    if name is None:
                        unparsed.append(dict(workflow=path, job=jid, kind='upload-artifact'))
                    producers.append(dict(workflow=path, job=jid, name=name, shape=_artifact_shape(name),
                                          dynamic=bool(name and '${{' in name)))
                elif 'actions/download-artifact@' in step:
                    name, pattern = _step_field(step, 'name'), _step_field(step, 'pattern')
                    if name is None and pattern is None:
                        unparsed.append(dict(workflow=path, job=jid, kind='download-artifact'))
                    consumers.append(dict(workflow=path, job=jid, kind='download-artifact', name=name,
                                          pattern=pattern, shape=_artifact_shape(name or pattern),
                                          dynamic=bool('${{' in (name or pattern or '')),
                                          scope='same-run' if 'run-id:' not in step else 'cross-run'))
                elif re.search(r'\bgh\s+run\s+download\b', step):
                    match = re.search(r'--name\s+(\S+)', step)
                    name = match.group(1).strip('\'"') if match else None
                    if name is None:
                        unparsed.append(dict(workflow=path, job=jid, kind='gh-run-download'))
                    consumers.append(dict(workflow=path, job=jid, kind='gh-run-download', name=name,
                                          pattern=None, shape=_artifact_shape(name),
                                          dynamic=bool(name and '${{' in name), scope='cross-run'))
    edges = []
    for consumer in consumers:
        for producer in producers:
            if producer['shape'] is None or consumer['shape'] is None:
                continue
            if consumer['kind'] == 'download-artifact' and consumer['pattern']:
                matched = re.fullmatch(re.escape(consumer['shape']).replace(r'\*', '.*'), producer['shape']) is not None
            else:
                matched = consumer['shape'] == producer['shape']
            if matched:
                edges.append(dict(artifact=producer['shape'], producer=producer['workflow'],
                                  producer_job=producer['job'], consumer=consumer['workflow'],
                                  consumer_job=consumer['job'], kind=consumer['kind'], scope=consumer['scope']))
    producer_shapes = {row['shape'] for row in producers if row['shape']}
    consumer_shapes = {row['shape'] for row in consumers if row['shape']}
    edge_artifacts = {edge['artifact'] for edge in edges}
    return dict(producers=producers, consumers=consumers, unparsed=unparsed, edges=edges,
        fan_out_total=len(producers), fan_in_total=len(consumers),
        fan_out_by_workflow={path: sum(1 for row in producers if row['workflow'] == path) for path in sorted({row['workflow'] for row in producers})},
        fan_in_by_workflow={path: sum(1 for row in consumers if row['workflow'] == path) for path in sorted({row['workflow'] for row in consumers})},
        producers_without_consumer=sorted(producer_shapes - edge_artifacts),
        consumers_without_producer=sorted(consumer_shapes - edge_artifacts),
        measurement_note=('fan-in/fan-out are static counts of upload/download steps and of artifact-name '
                          'shape matches at this SHA; runtime retention and cross-run availability stay UNKNOWN'))


def adoption_report(root=ROOT):
    """Recompute the additive adoption proof for the current checkout."""
    summary = check_composite_adoption(root)
    texts = workflow_texts(root)
    matches = {}
    for path in CONSUMER_WORKFLOWS:
        for jid, body in jobs(texts[path]).items():
            primitives = nonzero(inline_bootstrap_counts(body))
            if primitives:
                matches.setdefault(path, {})[jid] = primitives
    verified = {path: dict(row) for path, row in
                ((row['path'], row) for row in summary['consumers'])}
    return dict(schema=ADOPTION_SCHEMA, issue=204, task='backlog-887', additive=True,
        rewrites_v1_evidence=False,
        source_evidence=dict(path=EVIDENCE, sha256=EVIDENCE_SHA256, rewritten=False),
        composite_actions={path: dict(sha256=file_sha256(Path(root) / path),
            blob_sha1=blob((Path(root) / path).read_text())) for path in (RUNTIME, BROWSER)},
        consumers=[verified[path] for path in CONSUMER_WORKFLOWS],
        adoption={k: v for k, v in summary.items() if k not in ('consumers',)},
        inline_bootstrap=dict(patterns=dict(INLINE_BOOTSTRAP_PATTERNS),
            matches=matches,
            consumer_matches=sum(sum(counts.values()) for count_rows in matches.values() for counts in count_rows.values()),
            recorded_exceptions=summary['recorded_exceptions']),
        residual_duplicates=residual_duplicates(root),
        artifact_flow=artifact_flow(root),
        deferred_migrations=[dict(workflow=row['path'], job=row['job'], migratable=False,
            reason=row['reason'], recorded_by=row['evidence'],
            primitives=row['primitives']) for row in summary['recorded_exceptions']],
        unknowns=list(UNKNOWN_MEASUREMENTS),
        workflow_files_modified=[], write_surface_expanded=False, scientific_commands_changed=False,
        ci=dict(observed=False, reason='Local worker: no push/PR authorized at this SHA'),
        local_test_commands=['python3 tests/ci/test_repro_composite_factorization.py',
                             'python3 tools/audit_repro_composite_factorization.py --check-adoption'])


def check_adoption_evidence(root=ROOT):
    path = Path(root) / ADOPTION_EVIDENCE
    if not path.exists():
        raise AuditError(f'{ADOPTION_EVIDENCE}: additive adoption evidence missing')
    stored = json.loads(path.read_text())
    actual = adoption_report(root)
    if stored != actual:
        raise AuditError(f'{ADOPTION_EVIDENCE}: stored adoption evidence differs from the recomputed report; '
                         'regenerate with --write-adoption')


def validate(root=ROOT, changed=None):
    violations = []
    def check(fn, *args):
        try:
            fn(*args)
        except (ValueError, OSError) as exc:
            violations.append(str(exc))
    check(check_actions, root)
    check(check_transition_evidence, root)
    check(check_composite_adoption, root)
    check(check_adoption_evidence, root)
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
    parser.add_argument('--check-adoption',action='store_true',dest='check_adoption',
                        help='verify composite adoption plus the additive evidence file')
    parser.add_argument('--write-adoption',action='store_true',dest='write_adoption',
                        help=f'regenerate {ADOPTION_EVIDENCE} from the current checkout')
    args=parser.parse_args()
    try:
        if args.write_adoption:
            (ROOT/ADOPTION_EVIDENCE).write_text(json.dumps(adoption_report(),indent=2,sort_keys=True)+'\n')
            print(f'REPRO composite adoption: wrote {ADOPTION_EVIDENCE}')
        if args.check_adoption:
            check_transition_evidence()
            summary=check_composite_adoption()
            check_adoption_evidence()
            print('REPRO composite adoption: PASS '
                  f'({summary["consumer_count"]} consumers, '
                  f'{summary["jobs_with_composite"]}/{summary["jobs_total"]} jobs on the composite, '
                  f'{summary["jobs_recorded_exception"]} recorded exception)')
            return 0
        if args.write_adoption and not (args.check or args.write):
            return 0
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
