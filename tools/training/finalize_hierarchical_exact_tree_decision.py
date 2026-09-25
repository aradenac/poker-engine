#!/usr/bin/env python3
"""#419: consolidate the terminal decision, the content-addressed bundle and the n8n output block.

This tool is the *only* place where #419 reaches a terminal verdict.  It reads
back the frozen upstream artifacts (T1 sparsity baseline, T2 spec, T4 fit report
and candidate manifest, T5 raise-sizing frontier resolution, T6 protocol, T7
VALIDATION result, T8 exact-tree preflight), re-verifies every byte against each
upstream content-addressed index, and only then decides between

* ``ADMIT_HIERARCHICAL_EXACT_TREE_CANDIDATE`` - permitted *only* when the T8
  preflight reports ``required_tree_complete=true`` without any nearest-*
  substitution *and* the T7 VALIDATION result is ``ADMIT_CANDIDATE`` with every
  frozen gate passing, and
* ``UNRESOLVED_HIERARCHICAL_TREE_GAP`` - the fail-closed outcome, persisted with
  a precise blocker per unmet condition.

Admission is never forced and #367 is never run: the decision only records
evidence, binds the candidate identity and hands ``next_issue=367`` back to the
orchestrator.  The ``N8N_TASK_RESULT`` block is persisted verbatim inside
``DECISION.json``, ``N8N_TASK_RESULT.txt`` and ``SUMMARY.md`` so the terminal
state is machine-readable from the diff alone.

Output bundle (``analysis/issue419_hierarchical_tree/terminal_decision/``):

* ``DECISION.json`` - terminal decision, blockers, evidence bindings, n8n block
* ``SUMMARY.md`` - human-readable terminal summary
* ``N8N_TASK_RESULT.txt`` - the exact n8n output block
* ``ARTIFACTS.json`` - consolidated content-addressed index of the eight required
  artifacts plus the supporting evidence, each bound by byte and canonical
  payload digest

The upstream bundles are frozen inputs: their files, the root ``ARTIFACTS.json``
and the root ``SUMMARY.md`` are byte-pinned here and never rewritten.  No
VALIDATION/TEST hand is parsed, no threshold is relaxed, and no active registry,
model pointer, reference model or frozen protocol byte is mutated.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import sha256_file  # noqa: E402
from tools.preflop import model_a_sizing_hierarchical as H  # noqa: E402
from tools.simulation import issue419_exact_tree_preflight as preflight_tool  # noqa: E402
from tools.training import audit_hierarchical_tree_sparsity as baseline_tool  # noqa: E402
from tools.training import audit_model_a_exact_tree as legacy  # noqa: E402
from tools.training import fit_model_a_preflop_sizing_hierarchical as fit_tool  # noqa: E402
from tools.training import resolve_raise_sizing_frontiers as frontier_tool  # noqa: E402
from tools.training import validate_hierarchical_validation as validation_tool  # noqa: E402
from tools.training import write_frozen_validation_protocol as protocol_tool  # noqa: E402
from tools.training import write_hierarchical_model_spec as spec_tool  # noqa: E402
from tools.training.audit_preflop_sizing_support import stable_hash  # noqa: E402

HERE = ROOT / 'analysis/issue419_hierarchical_tree'
BUNDLE = HERE / 'terminal_decision'
SCHEMA = 'poker-hierarchical-exact-tree-terminal-decision/v1'
DECISION_NAME = 'DECISION.json'
SUMMARY_NAME = 'SUMMARY.md'
INDEX_NAME = 'ARTIFACTS.json'
N8N_NAME = 'N8N_TASK_RESULT.txt'
DIGEST_PATH = BUNDLE / 'DECISION.sha256'
DECISION_RECORD = ROOT / '.project/decisions/20260925-hierarchical-exact-tree-terminal-decision.md'

ISSUE = 419
PARENT_ISSUE = 314
SCENARIO_ISSUE = 321
SOURCE_ISSUE = 388
NEXT_ISSUE = 367

DECISION_ADMIT = 'ADMIT_HIERARCHICAL_EXACT_TREE_CANDIDATE'
DECISION_UNRESOLVED = 'UNRESOLVED_HIERARCHICAL_TREE_GAP'
STATUS_READY = 'READY_FOR_INTEGRATION'
STATUS_BLOCKED = 'BLOCKED_SCIENTIFIC'
STATUS_NEEDS_FIXES = 'NEEDS_FIXES'

BLOCK_REQUIRED_TREE_INCOMPLETE = 'REQUIRED_TREE_INCOMPLETE'
BLOCK_UNRESOLVED_RAISE_SIZING = 'UNRESOLVED_RAISE_SIZING_FRONTIER'
BLOCK_VALIDATION_GATES = 'VALIDATION_GATES_FAILED'
BLOCK_EVIDENCE_INTEGRITY = 'EVIDENCE_INTEGRITY'

# Frozen upstream identities.  Every value is re-verified from the persisted
# bytes; none of these files may be rewritten by this tool.
ROOT_SUMMARY_SHA256 = '737d315c6fde5d4863830952ab5bf396483bbefc47f3a4cdfcc7fe12508616e8'
ROOT_ARTIFACTS_SHA256 = '1650cdd96adb70a47e7711eb44820bc46a9afc46f290b9023c60d101d903d768'
SPEC_BYTE_SHA256 = '5be122e54e9ee07313a7efa0e0a6dbf4e195eceacf78287a9ac5a448964d105c'
BASELINE_BYTE_SHA256 = 'ef3995daaf5bc48a09f0785d574f7494754ad3904b87ecd2aa089b5be1b24a36'
PROTOCOL_BYTE_SHA256 = preflight_tool.PROTOCOL_BYTE_SHA256
REFERENCE_BYTE_SHA256 = protocol_tool.REFERENCE_SHA256
ISSUE352_CANDIDATE_SHA256 = '9115165c3141d16152946dd1ee7a049f219fef1a1d79c0e1c7b1249c45326f19'

# Artifacts: bundle name -> (canonical artefact path, directory holding its content-addressed
# ``sha256/`` object).  The canonical path and the object directory can differ: the T2 spec and the
# T6 protocol keep their frozen copy at the #419 bundle root and their object inside their own
# content-addressed sub-bundle.
REQUIRED_ARTIFACTS: tuple[tuple[str, Path, Path], ...] = (
    (spec_tool.SPEC_NAME, spec_tool.SPEC_PATH, spec_tool.BUNDLE),
    (fit_tool.REPORT_NAME, fit_tool.OUTPUT / fit_tool.REPORT_NAME, fit_tool.OUTPUT),
    (protocol_tool.NAME, protocol_tool.PROTOCOL_PATH, protocol_tool.BUNDLE),
    (fit_tool.MANIFEST_NAME, fit_tool.OUTPUT / fit_tool.MANIFEST_NAME, fit_tool.OUTPUT),
    (validation_tool.RESULT_NAME, validation_tool.OUTPUT / validation_tool.RESULT_NAME,
     validation_tool.OUTPUT),
    (preflight_tool.NAME, preflight_tool.OUTPUT / preflight_tool.NAME, preflight_tool.OUTPUT),
)

# Supporting evidence bound by the decision (T1 sparsity baseline, T5 resolution).
SUPPORTING_ARTIFACTS: tuple[tuple[str, Path, Path], ...] = (
    (baseline_tool.BASELINE_NAME, HERE / baseline_tool.BASELINE_NAME, HERE),
    (frontier_tool.ARTIFACT_NAME, frontier_tool.OUTPUT / frontier_tool.ARTIFACT_NAME,
     frontier_tool.OUTPUT),
)

ARTIFACT_SOURCES: tuple[tuple[str, Path, Path], ...] = REQUIRED_ARTIFACTS + SUPPORTING_ARTIFACTS
REQUIRED_NAMES = tuple(name for name, _s, _o in REQUIRED_ARTIFACTS) + (DECISION_NAME, SUMMARY_NAME)

# The #367 real ISO EV runner must never be imported or executed by this tool.
ISSUE367_RUNNER_SYMBOLS = (
    'run_issue367_real_iso_ev',
    'issue367_real_iso_ev',
    'hero_ev',
    'hero_recommendation',
)

PROTECTED_PATHS: tuple[Path, ...] = (
    ROOT / 'training/registry.json',
    ROOT / 'training/populations/registry.json',
    ROOT / 'training/models/preflop_population_model_v5.json',
    HERE / INDEX_NAME,
    HERE / SUMMARY_NAME,
    HERE / baseline_tool.BASELINE_NAME,
    spec_tool.SPEC_PATH,
    spec_tool.DIGEST_PATH,
    protocol_tool.PROTOCOL_PATH,
    protocol_tool.DIGEST_PATH,
    fit_tool.OUTPUT / fit_tool.CANDIDATE_NAME,
    fit_tool.OUTPUT / fit_tool.REPORT_NAME,
    fit_tool.OUTPUT / fit_tool.MANIFEST_NAME,
    validation_tool.OUTPUT / validation_tool.RESULT_NAME,
    preflight_tool.OUTPUT / preflight_tool.NAME,
    frontier_tool.OUTPUT / frontier_tool.ARTIFACT_NAME,
    legacy.REFERENCE,
)

SOURCE_PATH = Path(__file__).resolve()


class TerminalDecisionError(RuntimeError):
    """Raised when the consolidated evidence is inconsistent or inadmissible."""


def serialize(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


def verify_content_address(bundle: Path, index_name: str = INDEX_NAME) -> dict[str, Any]:
    """Verify a persisted content-addressed bundle before trusting any byte."""
    index = _load(bundle / index_name)
    for name, entry in index.items():
        data = (bundle / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise TerminalDecisionError(f'content-addressed byte hash mismatch: {bundle.name}/{name}')
        if data != (bundle / entry['object']).read_bytes():
            raise TerminalDecisionError(f'content-addressed copy mismatch: {bundle.name}/{name}')
    return index


def verify_no_issue367_runner(source: str | None = None) -> dict[str, Any]:
    """AST tripwire: the decision tool never imports or executes the #367 Hero EV runner."""
    text = SOURCE_PATH.read_text() if source is None else source
    module = ast.parse(text)
    used: set[str] = set()
    imported: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or '')
            imported.extend(alias.name for alias in node.names)
    names = {name.rsplit('.', 1)[-1] for name in imported} | used
    hits = sorted(name for name in names if name in ISSUE367_RUNNER_SYMBOLS)
    if hits:
        raise TerminalDecisionError(f'#367 Hero EV symbols referenced by the decision tool: {hits}')
    bad_imports = sorted(name for name in imported if 'issue367' in name.lower())
    if bad_imports:
        raise TerminalDecisionError(f'#367 runner imported by the decision tool: {bad_imports}')
    return {
        'check': 'self_source_scan_for_issue367_runner',
        'result': 'PASS',
        'forbidden_symbols': list(ISSUE367_RUNNER_SYMBOLS),
        'hits': [],
        'detail': 'AST scan: the #367 real ISO EV runner is neither imported nor executed here',
    }


def load_evidence() -> dict[str, Any]:
    """Load and byte-verify every upstream artifact before any decision is taken."""
    bundle_indexes = {
        'root': verify_content_address(HERE),
        'fit': verify_content_address(fit_tool.OUTPUT),
        'model_spec': verify_content_address(spec_tool.BUNDLE),
        'validation_protocol': verify_content_address(protocol_tool.BUNDLE),
        'validation': verify_content_address(validation_tool.OUTPUT),
        'exact_tree_preflight': verify_content_address(preflight_tool.OUTPUT),
        'raise_sizing_frontiers': verify_content_address(frontier_tool.OUTPUT),
    }
    if sha256_file(HERE / INDEX_NAME) != ROOT_ARTIFACTS_SHA256:
        raise TerminalDecisionError('the root ARTIFACTS.json is a frozen input and must not change')
    if sha256_file(HERE / SUMMARY_NAME) != ROOT_SUMMARY_SHA256:
        raise TerminalDecisionError('the T1 root SUMMARY.md is a frozen input and must not change')
    if sha256_file(spec_tool.SPEC_PATH) != SPEC_BYTE_SHA256:
        raise TerminalDecisionError('the frozen T2 spec bytes moved')
    if sha256_file(protocol_tool.PROTOCOL_PATH) != PROTOCOL_BYTE_SHA256:
        raise TerminalDecisionError('the frozen T6 protocol bytes moved')
    if sha256_file(HERE / baseline_tool.BASELINE_NAME) != BASELINE_BYTE_SHA256:
        raise TerminalDecisionError('the T1 sparsity baseline bytes moved')
    if sha256_file(legacy.REFERENCE) != REFERENCE_BYTE_SHA256:
        raise TerminalDecisionError('the active Model A reference moved')

    spec = _load(spec_tool.SPEC_PATH)
    if spec.get('schema') != H.HIERARCHY_SPEC_SCHEMA or spec.get('status') != 'SPEC_ONLY_NOT_ADMITTED':
        raise TerminalDecisionError('the T2 spec must be the unadmitted hierarchical spec')
    fit_report = _load(fit_tool.OUTPUT / fit_tool.REPORT_NAME)
    manifest = _load(fit_tool.OUTPUT / fit_tool.MANIFEST_NAME)
    frontier = _load(frontier_tool.OUTPUT / frontier_tool.ARTIFACT_NAME)
    protocol = _load(protocol_tool.PROTOCOL_PATH)
    validation = _load(validation_tool.OUTPUT / validation_tool.RESULT_NAME)
    preflight = _load(preflight_tool.OUTPUT / preflight_tool.NAME)
    baseline = _load(HERE / baseline_tool.BASELINE_NAME)

    if protocol.get('schema') != protocol_tool.SCHEMA:
        raise TerminalDecisionError('unexpected frozen VALIDATION protocol schema')
    if validation.get('schema') != validation_tool.SCHEMA:
        raise TerminalDecisionError('unexpected VALIDATION result schema')
    if preflight.get('schema') != preflight_tool.SCHEMA:
        raise TerminalDecisionError('unexpected exact-tree preflight schema')

    candidate_sha = preflight['provider']['candidate_canonical_payload_sha256']
    for name, sha in (
        ('fit report', fit_report['candidate']['canonical_payload_sha256']),
        ('candidate manifest', manifest['candidate']['artifact']['canonical_payload_sha256']),
        ('VALIDATION result', validation['candidate']['canonical_payload_sha256']),
        ('frozen protocol', protocol['candidate']['canonical_payload_sha256']),
    ):
        if sha != candidate_sha:
            raise TerminalDecisionError(f'{name} candidate hash disagrees with the preflight candidate')
    if candidate_sha != preflight_tool.CANDIDATE_CANONICAL_SHA256:
        raise TerminalDecisionError('candidate canonical payload digest moved')
    if candidate_sha == ISSUE352_CANDIDATE_SHA256:
        raise TerminalDecisionError('the hierarchical candidate must stay distinct from #352 v2')
    for name, artifact in (
        (spec_tool.SPEC_NAME, spec), (fit_tool.REPORT_NAME, fit_report),
        (protocol_tool.NAME, protocol), (frontier_tool.ARTIFACT_NAME, frontier),
        (preflight_tool.NAME, preflight),
    ):
        if artifact.get('test_consumed') is True:
            raise TerminalDecisionError(f'{name} declares test_consumed=true')
        if artifact.get('validation_consumed') is True:
            raise TerminalDecisionError(f'{name} must stay TRAIN-only')
    if validation['holdout_boundary']['validation_consumed'] is not True:
        raise TerminalDecisionError('the VALIDATION evaluation must have consumed VALIDATION')
    if validation['holdout_boundary']['test_consumed'] is not False:
        raise TerminalDecisionError('the VALIDATION evaluation must not consume TEST')
    if validation['protocol_byte_sha256'] != PROTOCOL_BYTE_SHA256:
        raise TerminalDecisionError('VALIDATION result protocol byte digest mismatch')
    if preflight['evidence_bindings']['protocol_byte_sha256'] != PROTOCOL_BYTE_SHA256:
        raise TerminalDecisionError('preflight protocol byte digest mismatch')
    if preflight['required_tree']['required_tree_sha256'] != (
        baseline_tool.ISSUE388_REQUIRED_TREE_SHA256
    ):
        raise TerminalDecisionError('preflight required-tree digest mismatch')
    if protocol['requirement_manifest']['required_tree_sha256'] != (
        baseline_tool.ISSUE388_REQUIRED_TREE_SHA256
    ):
        raise TerminalDecisionError('frozen protocol required-tree digest mismatch')
    if preflight['boundary']['hero_ev_executed'] is not False:
        raise TerminalDecisionError('the preflight must not have executed Hero EV')
    if preflight['boundary']['validation_consumed'] is not False:
        raise TerminalDecisionError('the exact-tree preflight must stay TRAIN-only')
    if preflight['boundary']['test_consumed'] is not False:
        raise TerminalDecisionError('the exact-tree preflight must not consume TEST')
    if preflight['boundary']['active_model_pointer_mutated'] is not False:
        raise TerminalDecisionError('the exact-tree preflight must not have mutated the active pointer')
    if preflight['nearest_substitution_audit']['substitutions_applied'] != 0:
        raise TerminalDecisionError('a nearest-* substitution was applied: admission is impossible')
    if frontier['unresolved_count'] != baseline_tool.ISSUE388_UNRESOLVED_FRONTIERS:
        raise TerminalDecisionError('raise-sizing frontier count mismatch')
    if frontier['blocker_persisted'] is not True:
        raise TerminalDecisionError('the unresolved raise-sizing frontier blocker must be persisted')

    return {
        'artifacts': {
            spec_tool.SPEC_NAME: spec,
            fit_tool.REPORT_NAME: fit_report,
            protocol_tool.NAME: protocol,
            fit_tool.MANIFEST_NAME: manifest,
            validation_tool.RESULT_NAME: validation,
            preflight_tool.NAME: preflight,
            baseline_tool.BASELINE_NAME: baseline,
            frontier_tool.ARTIFACT_NAME: frontier,
        },
        'bundle_indexes': bundle_indexes,
        'preflight': preflight,
        'validation': validation,
        'frontier': frontier,
        'protocol': protocol,
    }


def _deepcopy_json(value: Any) -> Any:
    return json.loads(json.dumps(value))


def choose_decision(preflight: Mapping[str, Any], validation: Mapping[str, Any],
                    frontier: Mapping[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    """Apply the frozen admission rule; never force an admission."""
    required_tree_complete = preflight['required_tree_complete'] is True
    substitutions = preflight['nearest_substitution_audit']['substitutions_applied']
    outcome = validation['outcome']
    all_gates_pass = validation['gate']['all_gates_pass'] is True
    admissible = (
        required_tree_complete
        and substitutions == 0
        and outcome == 'ADMIT_CANDIDATE'
        and all_gates_pass
    )
    if admissible:
        return DECISION_ADMIT, STATUS_READY, []

    admissibility = preflight['admissibility']
    blockers: list[dict[str, Any]] = []
    if not required_tree_complete:
        blockers.append({
            'class': 'SCIENTIFIC_DATA',
            'code': BLOCK_REQUIRED_TREE_INCOMPLETE,
            'rule': admissibility['rule'],
            'detail': (
                'the required #388/#419 response tree is not complete: no node carries an '
                'admissible exact answer at hierarchical_exact_key / L0_EXACT_KEY'
            ),
            'required_nodes': preflight['required_tree']['required_node_count'],
            'admissible_exact_nodes': admissibility['admissible_exact_nodes'],
            'blocked_nodes': admissibility['blocked_nodes'],
            'status_counts': _deepcopy_json(admissibility['status_counts']),
            'unresolved_reason_counts': _deepcopy_json(admissibility['unresolved_reason_counts']),
            'failed_admissibility_conditions': sorted(
                name for name, condition in admissibility['conditions'].items()
                if not condition['satisfied']
            ),
        })
    if frontier['unresolved_count']:
        blockers.append({
            'class': 'SCIENTIFIC_STRUCTURAL',
            'code': BLOCK_UNRESOLVED_RAISE_SIZING,
            'detail': (
                'raise-sizing frontiers stay unresolved: no exactly supported raise target exists '
                'at the frozen #367 structural node and no representative price may substitute it'
            ),
            'frontiers_total': frontier['frontiers_total'],
            'unresolved_count': frontier['unresolved_count'],
            'resolved_count': frontier['resolved_count'],
            'unresolved_node_ids': list(frontier['unresolved_node_ids']),
            'independent_of_the_response_model': True,
        })
    if outcome != 'ADMIT_CANDIDATE' or not all_gates_pass:
        blockers.append({
            'class': 'SCIENTIFIC_EVIDENCE',
            'code': BLOCK_VALIDATION_GATES,
            'detail': validation['reason'],
            'outcome': outcome,
            'failing_gates': list(validation['gate']['failing_gates']),
            'identifiable_decisions': validation['coverage']['identifiable_decisions'],
            'identifiable_hands': validation['coverage']['identifiable_hands'],
            'coverage_vs_focus_family': validation['coverage']['coverage_vs_focus_family'],
            'production_effect': validation['production_effect'],
        })
    if substitutions:
        blockers.append({
            'class': 'EVIDENCE_INTEGRITY',
            'code': BLOCK_EVIDENCE_INTEGRITY,
            'detail': 'a forbidden nearest-*/borrowed substitution was applied',
            'substitutions_applied': substitutions,
        })
    status = STATUS_NEEDS_FIXES if any(
        blocker['class'] == 'EVIDENCE_INTEGRITY' for blocker in blockers
    ) else STATUS_BLOCKED
    return DECISION_UNRESOLVED, status, blockers


def build_n8n_block(decision: Mapping[str, Any]) -> dict[str, Any]:
    """The exact n8n output block handed back to the orchestrator."""
    return {
        'type': 'N8N_TASK_RESULT',
        'issue': ISSUE,
        'decision': decision['decision'],
        'status': decision['status'],
        'admitted': decision['admitted'],
        'candidate_id': decision['candidate_id'],
        'candidate_sha256': decision['candidate_sha256'],
        'required_tree_complete': decision['required_tree_complete'],
        'required_tree_sha256': decision['required_tree_sha256'],
        'blockers': [blocker['code'] for blocker in decision['blockers']],
        'primary_blocker': decision['primary_blocker'],
        'validation_outcome': decision['validation_outcome'],
        'validation_consumed': decision['validation_consumed'],
        'test_consumed': decision['test_consumed'],
        'active_pointer_mutated': decision['active_pointer_mutated'],
        'hero_ev_executed': decision['hero_ev_executed'],
        'issue367_run': decision['issue367_run'],
        'next_issue': decision['next_issue'],
    }


def render_n8n_block(block: Mapping[str, Any]) -> str:
    """Deterministic ``key: value`` rendering of the exact n8n block.

    Keys are rendered in sorted order so that a block read back from
    ``DECISION.json`` (whose keys are serialized sorted) renders byte-identically
    to the freshly built block.
    """
    lines = ['N8N_TASK_RESULT']
    for key in sorted(block):
        if key == 'type':
            continue
        value = block[key]
        if isinstance(value, bool):
            rendered = 'true' if value else 'false'
        elif value is None:
            rendered = 'null'
        elif isinstance(value, list):
            rendered = ','.join(str(item) for item in value)
        else:
            rendered = str(value)
        lines.append(f'{key}: {rendered}')
    return '\n'.join(lines) + '\n'


def object_extension(name: str) -> str:
    """Content-addressed object extension for a bundle artifact."""
    return '.md' if name.endswith('.md') else ('.txt' if name.endswith('.txt') else '.json')


def bound_artifact(name: str, source: Path, object_dir: Path) -> dict[str, Any]:
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    object_path = object_dir / 'sha256' / (digest + object_extension(name))
    if not object_path.exists() or object_path.read_bytes() != data:
        raise TerminalDecisionError(
            f'{name} has no matching content-addressed object at {object_path.relative_to(ROOT)}'
        )
    entry: dict[str, Any] = {
        'path': str(source.relative_to(ROOT)),
        'sha256': digest,
        'object': str(object_path.relative_to(ROOT)),
        'bundle': str(object_dir.relative_to(ROOT)) if object_dir != HERE else '.',
    }
    if name.endswith('.json'):
        entry['canonical_payload_sha256'] = stable_hash(json.loads(data))
    return entry


def build() -> tuple[dict[str, Any], str, str]:
    """Build the terminal decision, its summary and the exact n8n block."""
    verify_no_issue367_runner()
    protected_before = {str(p.relative_to(ROOT)): sha256_file(p) for p in PROTECTED_PATHS}
    evidence = load_evidence()
    preflight = evidence['preflight']
    validation = evidence['validation']
    frontier = evidence['frontier']
    protocol = evidence['protocol']

    decision_code, status, blockers = choose_decision(preflight, validation, frontier)
    primary_blocker = blockers[0]['code'] if blockers else None

    requirement_manifest = protocol['requirement_manifest']
    bindings: dict[str, Any] = {}
    for name, source, object_dir in ARTIFACT_SOURCES:
        bindings[name] = bound_artifact(name, source, object_dir)

    candidate = {
        'candidate_id': H.CANDIDATE_ID,
        'candidate_sha256': preflight['provider']['candidate_canonical_payload_sha256'],
        'candidate_instance_id': preflight['provider']['candidate_instance_id'],
        'candidate_byte_sha256': preflight['provider']['candidate_byte_sha256'],
        'identity_granularity': preflight['provider']['identity_granularity'],
        'distinct_from_issue_352': True,
        'issue_352_candidate_id': 'model-a-preflop-sizing-aware-candidate-v2',
        'issue_352_candidate_sha256': ISSUE352_CANDIDATE_SHA256,
        'admitted': decision_code == DECISION_ADMIT,
        'candidate_status_at_freeze': H.CANDIDATE_STATUS,
    }

    protected_after = {str(p.relative_to(ROOT)): sha256_file(p) for p in PROTECTED_PATHS}
    if protected_before != protected_after:
        raise TerminalDecisionError('a protected input was mutated while the decision was built')

    decision: dict[str, Any] = {
        'schema': SCHEMA,
        'issue': ISSUE,
        'parent_issue': PARENT_ISSUE,
        'scenario_issue': SCENARIO_ISSUE,
        'source_issue': SOURCE_ISSUE,
        'kind': 'TERMINAL_HIERARCHICAL_EXACT_TREE_DECISION',
        'bundle_dir': str(BUNDLE.relative_to(ROOT)),
        'decision': decision_code,
        'status': status,
        'admitted': decision_code == DECISION_ADMIT,
        'candidate_id': candidate['candidate_id'],
        'candidate_sha256': candidate['candidate_sha256'],
        'candidate_instance_id': candidate['candidate_instance_id'],
        'candidate': candidate,
        'required_tree_complete': preflight['required_tree_complete'] is True,
        'required_tree_sha256': preflight['required_tree']['required_tree_sha256'],
        'required_tree_byte_sha256': preflight['required_tree']['required_tree_byte_sha256'],
        'required_tree_node_count': preflight['required_tree']['required_node_count'],
        'admissible_exact_node_count': preflight['admissibility']['admissible_exact_nodes'],
        'exact_unresolved_node_count': preflight['admissibility']['status_counts'].get(
            'EXACT_UNRESOLVED', 0
        ),
        'identity_granularity': preflight['provider']['identity_granularity'],
        'support_isolation_rule': requirement_manifest['support_isolation_rule'],
        'unresolved_raise_sizing_frontier_count': frontier['unresolved_count'],
        'validation_outcome': validation['outcome'],
        'validation_failing_gates': list(validation['gate']['failing_gates']),
        'validation_evidence_sha256': validation['evidence_sha256'],
        'validation_consumed': True,
        'test_consumed': False,
        'test_authorized': False,
        'active_pointer_mutated': False,
        'hero_ev_executed': False,
        'hero_recommendation': None,
        'issue367_run': False,
        'issue367_authorized': protocol['issue367_rule']['authorized_at_freeze'],
        'next_issue': NEXT_ISSUE,
        'primary_blocker': primary_blocker,
        'blockers': blockers,
        'decision_rule': {
            'rule_id': protocol['issue367_rule']['rule_id'],
            'question': protocol['issue367_rule']['question'],
            'authorized_when': list(protocol['issue367_rule']['authorized_when']),
            'consequence_when_forbidden': protocol['issue367_rule']['consequence_when_forbidden'],
            'admission_requires': [
                'required_tree_complete=true from the T8 exact-tree preflight',
                'no nearest-price / nearest-context / borrowed-support substitution applied',
                'VALIDATION outcome=ADMIT_CANDIDATE with every frozen gate passing',
            ],
            'observed': {
                'required_tree_complete': preflight['required_tree_complete'] is True,
                'substitutions_applied': (
                    preflight['nearest_substitution_audit']['substitutions_applied']
                ),
                'validation_outcome': validation['outcome'],
                'validation_all_gates_pass': validation['gate']['all_gates_pass'],
                'unresolved_raise_sizing_frontiers': frontier['unresolved_count'],
            },
        },
        'carried_risks': [
            {
                'risk_id': 'RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE',
                'detail': (
                    'the provider runtime key merges distinct public contexts; the exact identity '
                    'granularity stays the fine hierarchical_exact_key'
                ),
                'runtime_keys_merging_exact_states': preflight['required_tree'].get(
                    'runtime_keys_merging_exact_states'
                ),
                'handled_by': 'T2 HIERARCHICAL_MODEL_SPEC.granularity_decision',
                'not_a_substitution': True,
            },
        ],
        'required_artifacts': {
            name: {
                'path': bindings[name]['path'],
                'sha256': bindings[name]['sha256'],
                'canonical_payload_sha256': bindings[name].get('canonical_payload_sha256'),
            }
            for name in REQUIRED_NAMES
            if name in bindings
        },
        'evidence_bindings': bindings,
        'verified_bundles': sorted(evidence['bundle_indexes']),
        'frozen_inputs_untouched': {
            'root_artifacts_sha256': ROOT_ARTIFACTS_SHA256,
            'root_summary_sha256': ROOT_SUMMARY_SHA256,
            'hierarchical_model_spec_sha256': SPEC_BYTE_SHA256,
            'frozen_validation_protocol_sha256': PROTOCOL_BYTE_SHA256,
            'hierarchical_tree_sparsity_baseline_sha256': BASELINE_BYTE_SHA256,
            'active_reference_sha256': REFERENCE_BYTE_SHA256,
        },
        'protected_files_before_after_sha256': {
            'before': protected_before,
            'after': protected_after,
            'unchanged': True,
        },
        'source_files_sha256': {
            str(SOURCE_PATH.relative_to(ROOT)): sha256_file(SOURCE_PATH),
        },
        'reproduction': {
            'build': 'python3 tools/training/finalize_hierarchical_exact_tree_decision.py',
            'check': 'python3 tools/training/finalize_hierarchical_exact_tree_decision.py --check',
        },
        'not_an_admission_by_default': (
            'UNRESOLVED_HIERARCHICAL_TREE_GAP is a valid terminal outcome; admission is never '
            'forced and #367 is never run by this tool'
        ),
    }
    for name in (DECISION_NAME, SUMMARY_NAME):
        decision['required_artifacts'][name] = {
            'path': str((BUNDLE / name).relative_to(ROOT)),
            'sha256_location': str((BUNDLE / INDEX_NAME).relative_to(ROOT)),
            'note': 'self-referential: this artifact digest is recorded by the bundle index, not inside itself',
        }
    decision['n8n_task_result'] = build_n8n_block(decision)
    summary = summary_text(decision)
    n8n_text = render_n8n_block(decision['n8n_task_result'])
    return decision, summary, n8n_text


def persist(decision: dict[str, Any], summary: str) -> dict[str, Any]:
    """Write the terminal bundle: the three generated files, their objects and the index."""
    decision_bytes = serialize(decision)
    summary_bytes = summary.encode()
    n8n_bytes = render_n8n_block(decision['n8n_task_result']).encode()
    generated = {
        DECISION_NAME: decision_bytes,
        SUMMARY_NAME: summary_bytes,
        N8N_NAME: n8n_bytes,
    }

    BUNDLE.mkdir(parents=True, exist_ok=True)
    objects = BUNDLE / 'sha256'
    objects.mkdir(exist_ok=True)
    index: dict[str, Any] = {}
    referenced: set[str] = set()
    for name, data in generated.items():
        extension = object_extension(name)
        digest = hashlib.sha256(data).hexdigest()
        (BUNDLE / name).write_bytes(data)
        (objects / (digest + extension)).write_bytes(data)
        entry: dict[str, Any] = {
            'path': str((BUNDLE / name).relative_to(ROOT)),
            'sha256': digest,
            'object': str((objects / (digest + extension)).relative_to(ROOT)),
        }
        if extension == '.json':
            entry['canonical_payload_sha256'] = stable_hash(json.loads(data))
        index[name] = entry
        referenced.add(digest + extension)

    for name, source, object_dir in ARTIFACT_SOURCES:
        index[name] = bound_artifact(name, source, object_dir)

    for name in REQUIRED_NAMES:
        if name not in index:
            raise TerminalDecisionError(f'required artifact {name} missing from the index')
        if 'sha256' not in index[name]:
            raise TerminalDecisionError(f'required artifact {name} carries no sha256')

    (BUNDLE / INDEX_NAME).write_text(json.dumps(index, sort_keys=True, indent=2) + '\n')
    (DIGEST_PATH).write_text(
        f"{index[DECISION_NAME]['sha256']}  {DECISION_NAME}\n"
        f"# canonical_payload_sha256 {index[DECISION_NAME].get('canonical_payload_sha256')}\n"
    )
    for path in objects.iterdir():
        if path.is_file() and path.name not in referenced:
            path.unlink()
    return index


def summary_text(decision: Mapping[str, Any]) -> str:
    blockers = decision['blockers']
    lines = [
        '# #419 — terminal decision: hierarchical exact-tree candidate',
        '',
        f"**{decision['decision']}** — status `{decision['status']}`, admitted: "
        f"`{'true' if decision['admitted'] else 'false'}`.",
        '',
        f"Candidate `{decision['candidate_id']}` (canonical payload "
        f"`{decision['candidate_sha256']}`) is the frozen TRAIN-fit hierarchical Model-A candidate "
        'of T4. It is **not** admitted and it is **not** wired into #367: admission requires a '
        'complete exact tree *and* an `ADMIT_CANDIDATE` VALIDATION result, and neither holds.',
        '',
        f"T8 preflight: `required_tree_complete={str(decision['required_tree_complete']).lower()}` — "
        f"{decision['admissible_exact_node_count']} of {decision['required_tree_node_count']} required "
        'nodes carry an admissible exact answer at `hierarchical_exact_key` / `L0_EXACT_KEY`, so '
        f"all {decision['exact_unresolved_node_count']} required nodes stay `EXACT_UNRESOLVED`. T5 left "
        f"{decision['unresolved_raise_sizing_frontier_count']} raise-sizing frontiers unresolved. T7 "
        f"VALIDATION returned `{decision['validation_outcome']}` with failing frozen gates "
        f"{decision['validation_failing_gates']}.",
        '',
        '## Blockers',
        '',
    ]
    for blocker in blockers:
        lines.append(f"* `{blocker['code']}` ({blocker['class']}) — {blocker['detail']}")
    lines += [
        '',
        '## Holdout and pointer discipline',
        '',
        'VALIDATION was consumed once, through the frozen T6 protocol, by the T7 evaluation '
        '(`validation_consumed=true`). TEST stays unconsumed and unauthorized '
        '(`test_consumed=false`). No threshold, prior, pooling limit or comparator was changed after '
        'the read. The active Model A pointer (`training/models/preflop_population_model_v5.json`), '
        'the registries, the reference model, the root `ARTIFACTS.json`/`SUMMARY.md` and the frozen '
        'protocol bytes are unchanged (`active_pointer_mutated=false`). The #367 Hero EV runner was '
        'neither imported nor executed (`hero_ev_executed=false`, `issue367_run=false`).',
        '',
        '## Bundle',
        '',
        'This terminal bundle (`analysis/issue419_hierarchical_tree/terminal_decision/`) carries the '
        'decision, this summary, the n8n block and one content-addressed index. `ARTIFACTS.json` '
        'binds every required artifact by byte SHA256, canonical payload SHA256 and content-addressed '
        'object: ' + ', '.join(f'`{name}`' for name in REQUIRED_NAMES) + '. Supporting evidence: '
        + ', '.join(f'`{name}`' for name, _source, _obj in SUPPORTING_ARTIFACTS)
        + '. The upstream bundles '
        'stay in place and are never rewritten (`frozen_inputs_untouched`).',
        '',
        'Reproduce: `python3 tools/training/finalize_hierarchical_exact_tree_decision.py`; verify: '
        '`python3 tools/training/finalize_hierarchical_exact_tree_decision.py --check`.',
        '',
        '## n8n output',
        '',
        '```text',
        render_n8n_block(decision['n8n_task_result']).rstrip('\n'),
        '```',
        '',
    ]
    return '\n'.join(lines)


def decision_record_text(decision: Mapping[str, Any]) -> str:
    blockers = ', '.join(f"`{blocker['code']}`" for blocker in decision['blockers'])
    return '\n'.join([
        '# Décision terminale #419 — arbre exact hiérarchique',
        '',
        f"- Décision : `{decision['decision']}`",
        f"- Statut : `{decision['status']}` (admission forcée : non)",
        f"- Candidat : `{decision['candidate_id']}` (`{decision['candidate_sha256']}`), non admis",
        f"- `required_tree_complete` = `{str(decision['required_tree_complete']).lower()}` "
        f"({decision['admissible_exact_node_count']}/{decision['required_tree_node_count']} nœuds "
        'admissibles, tous les autres `EXACT_UNRESOLVED`)',
        f"- Blockers : {blockers}",
        f"- `validation_consumed` = `true` (une seule lecture, via le protocole gelé T6), "
        '`test_consumed` = `false`, `active_pointer_mutated` = `false`',
        f"- `next_issue` = `{decision['next_issue']}` ; #367 n\u2019est jamais lancé par #419",
        '',
        'Le candidat hiérarchique reste distinct de #352 v2 et n\u2019est pas câblé au provider #367. '
        'Aucun seuil, prior ou limite de pooling n\u2019a été modifié après la lecture VALIDATION, et '
        'les entrées gelées (spec T2, protocole T6, baseline T1, `ARTIFACTS.json`/`SUMMARY.md` '
        'racine, pointer actif) sont inchangées.',
        '',
        'Bundle content-adressé : `analysis/issue419_hierarchical_tree/terminal_decision/` '
        '(`DECISION.json`, `SUMMARY.md`, `N8N_TASK_RESULT.txt`, `ARTIFACTS.json`).',
        '',
        'Reproduce: `python3 tools/training/finalize_hierarchical_exact_tree_decision.py`; verify: '
        '`python3 tools/training/finalize_hierarchical_exact_tree_decision.py --check`.',
        '',
    ])


def check() -> int:
    decision, summary, n8n_text = build()
    problems: list[str] = []
    expected = {
        DECISION_NAME: serialize(decision),
        SUMMARY_NAME: summary.encode(),
        N8N_NAME: n8n_text.encode(),
    }
    for name, data in expected.items():
        path = BUNDLE / name
        if not path.exists():
            problems.append(f'{name} is missing')
        elif path.read_bytes() != data:
            problems.append(f'{name} differs from a fresh terminal decision')
    if (BUNDLE / INDEX_NAME).exists():
        index = _load(BUNDLE / INDEX_NAME)
        for name, entry in index.items():
            path = ROOT / entry['path']
            obj = ROOT / entry['object']
            if not path.exists():
                problems.append(f'{name} is missing at {path}')
                continue
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != entry['sha256']:
                problems.append(f'{name} byte hash does not match {INDEX_NAME}')
            if not obj.exists() or data != obj.read_bytes():
                problems.append(f'{name} content-addressed copy mismatch')
        own_dir = (BUNDLE / 'sha256').relative_to(ROOT)
        own_objects = {
            Path(entry['object']).name for entry in index.values()
            if Path(entry['object']).parent == own_dir
        }
        if {p.name for p in (BUNDLE / 'sha256').iterdir()} != own_objects:
            problems.append(f'{INDEX_NAME} objects and sha256/ directory disagree')
        for name in REQUIRED_NAMES:
            if name not in index:
                problems.append(f'required artifact {name} is absent from {INDEX_NAME}')
            elif 'sha256' not in index[name]:
                problems.append(f'required artifact {name} has no sha256 in {INDEX_NAME}')
    else:
        problems.append(f'{INDEX_NAME} is missing')
    if [b['code'] for b in decision['blockers']] != [
        b['code'] for b in _load(BUNDLE / DECISION_NAME)['blockers']
    ]:
        problems.append('persisted blockers differ from a fresh decision')
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print(json.dumps({
        'schema': SCHEMA,
        'check': 'PASS',
        'artifact_sha256': _load(BUNDLE / INDEX_NAME)[DECISION_NAME]['sha256'],
        'required_artifacts': list(REQUIRED_NAMES),
        'decision': decision['decision'],
        'status': decision['status'],
        'next_issue': decision['next_issue'],
    }, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='verify the persisted bundle instead of rewriting it')
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.check:
        return check()
    decision, summary, n8n_text = build()
    index = persist(decision, summary)
    DECISION_RECORD.parent.mkdir(parents=True, exist_ok=True)
    DECISION_RECORD.write_text(decision_record_text(decision))
    print(render_n8n_block(decision['n8n_task_result']).rstrip('\n'))
    print(json.dumps({
        'schema': SCHEMA,
        'bundle': str(BUNDLE.relative_to(ROOT)),
        'decision': decision['decision'],
        'status': decision['status'],
        'admitted': decision['admitted'],
        'candidate_id': decision['candidate_id'],
        'candidate_sha256': decision['candidate_sha256'],
        'required_tree_complete': decision['required_tree_complete'],
        'blockers': [blocker['code'] for blocker in decision['blockers']],
        'next_issue': decision['next_issue'],
        'validation_consumed': decision['validation_consumed'],
        'test_consumed': decision['test_consumed'],
        'active_pointer_mutated': decision['active_pointer_mutated'],
        'artifact_sha256': index[DECISION_NAME]['sha256'],
        'required_artifacts': list(REQUIRED_NAMES),
    }, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
