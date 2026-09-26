#!/usr/bin/env python3
"""#419: freeze and content-address the hierarchical-candidate VALIDATION protocol.

Writes ``analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.json``
plus a content-addressed bundle under
``analysis/issue419_hierarchical_tree/validation_protocol/``.  The protocol pins,
before a single VALIDATION hand is read:

* the candidate identity (id, canonical payload digest, byte digest) and the
  frozen code digests of the fit/model/guard tools;
* the TRAIN corpus and every consumed TRAIN artifact digest;
* the architecture, hyper-parameters, priors and shrinkage read from the frozen
  spec (never re-selected: no hyper-parameter search path exists here);
* the requirement manifest of the 38 #388 tree nodes, bound to
  ``required_tree_sha256`` and to each node's runtime/audit/node keys;
* the seeds (deterministic, zero stochastic draws), the metrics, the frozen
  thresholds and the acceptable pooling limits;
* the three explicit comparators: the active reference ``active-model-a-preflop-v5``
  (``ff952055...``), the admitted #352 exact-price candidate v2
  (``9115165c...`` with its fit/validation evidence pinning), and the new
  hierarchical candidate under test;
* the calibration and admission rules, the VALIDATION result output schema, and
  the exact rule authorizing or forbidding a #367 consumption.

Scientific boundary
-------------------
The protocol is authored, hashed and timestamped **before** any VALIDATION read.
The order guard lives in ``tools/training/validation_order_guard.py`` and makes
the freeze abort if a VALIDATION result for this candidate already exists.  This
tool parses no hand history at all: it consumes content-addressed evidence
artifacts, fails closed when a consumed TRAIN artifact declares a non-TRAIN
split, and statically refuses the known holdout loaders.

The precedent that #352 already consumed the VALIDATION split for *its own*
exact-price candidate is recorded as evidence, not repaired: it is a different
candidate under a different frozen protocol and it neither reads nor
pre-consumes this candidate's holdout decision.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SOURCE_PATH = Path(__file__).resolve()

from tools.preflop import model_a_sizing_hierarchical as H
from tools.training import audit_hierarchical_tree_sparsity as baseline_tool
from tools.training import validation_order_guard as guard
from tools.training.audit_preflop_sizing_support import stable_hash

HERE = ROOT / 'analysis/issue419_hierarchical_tree'
BUNDLE = HERE / 'validation_protocol'
PROTOCOL_PATH = HERE / 'FROZEN_VALIDATION_PROTOCOL.json'
DIGEST_PATH = HERE / 'FROZEN_VALIDATION_PROTOCOL.sha256'
NAME = 'FROZEN_VALIDATION_PROTOCOL.json'
SCHEMA = guard.PROTOCOL_SCHEMA
RESULT_SCHEMA = guard.RESULT_SCHEMA
FROZEN_STATUS = guard.FROZEN_STATUS
FROZEN_DATE = '2026-09-25'
DEFAULT_FROZEN_AT = '2026-09-25T00:00:00Z'

# Frozen identities this protocol depends on. Every value is re-verified from the
# persisted bytes before the protocol is serialized; nothing is taken on trust.
SPEC_PATH = HERE / 'HIERARCHICAL_MODEL_SPEC.json'
SPEC_NAME = 'HIERARCHICAL_MODEL_SPEC.json'
SPEC_INDEX_PATH = HERE / 'model_spec' / 'ARTIFACTS.json'
SPEC_BYTE_SHA256 = '5be122e54e9ee07313a7efa0e0a6dbf4e195eceacf78287a9ac5a448964d105c'
SPEC_CANONICAL_SHA256 = 'd4885e9d148e3a0246968168e246644d4dc81965383447bc74b3c8ca3c3541d4'
BASELINE_PATH = HERE / baseline_tool.BASELINE_NAME
FIT_INDEX_PATH = HERE / 'fit' / 'ARTIFACTS.json'

CANDIDATE_MANIFEST_PATH = HERE / 'fit' / 'CANDIDATE_MANIFEST.json'
CANDIDATE_PATH = HERE / 'fit' / 'CANDIDATE.json'
TRAIN_REPORT_PATH = HERE / 'fit' / 'TRAIN_FIT_REPORT.json'

REFERENCE_PATH = ROOT / 'training/models/preflop_population_model_v5.json'
REFERENCE_ID = 'active-model-a-preflop-v5'
REFERENCE_SHA256 = 'ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca'

ISSUE352_FIT_PATH = ROOT / 'analysis/model_a_preflop_sizing_v2_fit.json'
ISSUE352_VALIDATION_PATH = ROOT / 'analysis/model_a_preflop_sizing_v2_validation.json'
ISSUE352_VALIDATION_PROTOCOL_PATH = ROOT / 'analysis/model_a_preflop_sizing_v2_validation_protocol.json'
ISSUE352_CANDIDATE_ID = 'model-a-preflop-sizing-aware-candidate-v2'
ISSUE352_CANDIDATE_SHA256 = '9115165c3141d16152946dd1ee7a049f219fef1a1d79c0e1c7b1249c45326f19'
ISSUE352_FIT_BYTE_SHA256 = 'cd2a29a6574ff03ca09a39e3995d6df9fbd9e677e7e63a27e7d2438df1fb260e'
ISSUE352_VALIDATION_PROTOCOL_SHA256 = '5c7432e0f7008d27899d6d5ce33becbdd2ef29528f2aef66cc4373369311d6a2'
# The self-reported canonical evidence digest (the value #367 pins) and the byte
# digest of the persisted file are recorded separately and never conflated.
ISSUE352_VALIDATION_EVIDENCE_SHA256 = '54f6e2affb0a088aa5148c981331abafe705ce7793433f89accbf304dc6f7496'
ISSUE352_VALIDATION_EVIDENCE_BYTE_SHA256 = '0e93640bd56e37d445438c9b663d2cb77b623f33d01dc91836ed12fd4651bf06'
ISSUE352_OUTCOME = 'ADMIT_CANDIDATE'

CODE_INPUTS = (
    ('tools/training/write_frozen_validation_protocol.py', 'PROTOCOL_GENERATOR'),
    ('tools/training/validation_order_guard.py', 'ORDER_GUARD'),
    ('tools/training/fit_model_a_preflop_sizing_hierarchical.py', 'CANDIDATE_FIT_TOOL'),
    ('tools/preflop/model_a_sizing_hierarchical.py', 'CANDIDATE_MODEL'),
    ('tools/preflop/model_a_sizing_likelihood.py', 'RUNTIME_SUPPORT_KEY_CONTRACT'),
    ('tools/training/fit_model_a_preflop_sizing_v2.py', 'COMPARATOR_V2_TOOL'),
    ('tools/training/audit_hierarchical_tree_sparsity.py', 'SPARSITY_BASELINE_TOOL'),
    ('tools/training/audit_model_a_exact_tree.py', 'REQUIRED_TREE_TOOL'),
)

# The generator must name its own output artifacts, whose filenames legitimately
# contain the word "validation".  These literals are exempted from the holdout
# literal scan and the exemption is recorded in the protocol evidence.
SELF_ARTIFACT_LITERALS = (
    NAME,
    'analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.json',
    'analysis/issue419_hierarchical_tree/validation_protocol/ARTIFACTS.json',
    'analysis/issue419_hierarchical_tree/validation_protocol/FROZEN_VALIDATION_PROTOCOL.json',
    'analysis/issue419_hierarchical_tree/validation_protocol/SUMMARY.md',
)
RESULT_PATH = guard.DECLARED_RESULT_LOCATIONS[0]


class ProtocolError(RuntimeError):
    """Raised when the frozen VALIDATION protocol cannot be authored safely."""


def serialize(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _verify_indexed_bundle(directory: Path, index_name: str = 'ARTIFACTS.json') -> dict[str, Any]:
    index = _load(directory / index_name)
    for name, entry in index.items():
        data = (directory / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ProtocolError(f'byte hash mismatch in {directory}/{name}')
        if data != (directory / entry['object']).read_bytes():
            raise ProtocolError(f'content-addressed copy mismatch in {directory}/{name}')
    return index


def _digest_nodes(nodes: Iterable[Mapping[str, Any]]) -> str:
    return stable_hash([dict(row) for row in nodes])


def verify_inputs() -> dict[str, Any]:
    """Re-verify every consumed identity before the protocol is written."""
    spec = _load(SPEC_PATH)
    if stable_hash(spec) != SPEC_CANONICAL_SHA256:
        raise ProtocolError('hierarchical spec canonical payload hash mismatch')
    if sha256_file(SPEC_PATH) != SPEC_BYTE_SHA256:
        raise ProtocolError('hierarchical spec byte hash mismatch')
    spec_index = _verify_indexed_bundle(HERE / 'model_spec')
    if spec_index[SPEC_NAME]['sha256'] != SPEC_BYTE_SHA256:
        raise ProtocolError('hierarchical spec index digest mismatch')

    baseline = _load(BASELINE_PATH)
    guard.assert_train_only_artifact('#419 sparsity baseline', baseline)
    if stable_hash(baseline) != '2d3fccc0a84e130ba483b8766ff96bc6467ad8260cfa64ae8c36e9cf662b6e2f':
        raise ProtocolError('#419 sparsity baseline canonical payload mismatch')

    issue388 = baseline_tool.load_issue388()
    baseline_tool.verify_issue388_boundaries(issue388)
    guard.assert_train_only_artifact('#388 train support', issue388['report'])
    guard.assert_train_only_artifact('#388 decision', issue388['decision'])

    fit_index = _verify_indexed_bundle(HERE / 'fit')
    candidate = _load(CANDIDATE_PATH)
    manifest = _load(CANDIDATE_MANIFEST_PATH)
    report = _load(TRAIN_REPORT_PATH)
    candidate_sha = H.canonical_candidate_sha256(candidate)
    if candidate_sha != guard.CANDIDATE_CANONICAL_SHA256:
        raise ProtocolError('candidate canonical payload hash drifted')
    if sha256_file(CANDIDATE_PATH) != guard.CANDIDATE_BYTE_SHA256:
        raise ProtocolError('candidate byte hash drifted')
    if candidate_sha != fit_index['CANDIDATE.json']['canonical_payload_sha256']:
        raise ProtocolError('candidate canonical hash differs from the fit index')
    if candidate['identity']['candidate_id'] != guard.CANDIDATE_ID:
        raise ProtocolError('candidate contract id drifted')
    if manifest['candidate']['artifact']['canonical_payload_sha256'] != candidate_sha:
        raise ProtocolError('candidate manifest is not bound to the candidate bytes')
    for payload, label in ((report, 'TRAIN fit report'), (manifest, 'candidate manifest')):
        if payload.get('fit', payload).get('split_consumed') != 'TRAIN':
            raise ProtocolError(f'{label} did not consume TRAIN only')
        if payload.get('fit', payload).get('validation_consumed') is not False:
            raise ProtocolError(f'{label} already reports a VALIDATION read')
        if payload.get('fit', payload).get('test_consumed') is not False:
            raise ProtocolError(f'{label} already reports a TEST read')

    if sha256_file(REFERENCE_PATH) != REFERENCE_SHA256:
        raise ProtocolError('active Model A reference hash drifted')

    issue352_fit = _load(ISSUE352_FIT_PATH)
    issue352_protocol = _load(ISSUE352_VALIDATION_PROTOCOL_PATH)
    issue352_validation = _load(ISSUE352_VALIDATION_PATH)
    if sha256_file(ISSUE352_FIT_PATH) != ISSUE352_FIT_BYTE_SHA256:
        raise ProtocolError('#352 fit artifact hash drifted')
    if sha256_file(ISSUE352_VALIDATION_PROTOCOL_PATH) != ISSUE352_VALIDATION_PROTOCOL_SHA256:
        raise ProtocolError('#352 VALIDATION protocol hash drifted')
    if sha256_file(ISSUE352_VALIDATION_PATH) != ISSUE352_VALIDATION_EVIDENCE_BYTE_SHA256:
        raise ProtocolError('#352 VALIDATION evidence byte hash drifted')
    if issue352_protocol.get('status') != 'FROZEN_BEFORE_VALIDATION':
        raise ProtocolError('#352 comparator protocol is not frozen')
    frozen_fit = issue352_protocol.get('frozen_train_fit') or {}
    if frozen_fit.get('candidate_id') != ISSUE352_CANDIDATE_ID:
        raise ProtocolError('#352 comparator candidate id drifted')
    if frozen_fit.get('candidate_sha256') != ISSUE352_CANDIDATE_SHA256:
        raise ProtocolError('#352 comparator candidate hash drifted')
    if issue352_fit.get('candidate_sha256') != ISSUE352_CANDIDATE_SHA256:
        raise ProtocolError('#352 comparator fit evidence drifted')
    if issue352_validation.get('outcome') != ISSUE352_OUTCOME:
        raise ProtocolError('#352 comparator was not admitted')
    if issue352_validation.get('evidence_sha256') != ISSUE352_VALIDATION_EVIDENCE_SHA256:
        raise ProtocolError('#352 comparator evidence digest drifted')
    for flag in ('test_consumed', 'active_model_replaced', 'automatic_promotion'):
        if issue352_validation.get(flag) is not False:
            raise ProtocolError(f'#352 comparator declares {flag}')

    return {
        'spec': spec,
        'baseline': baseline,
        'issue388': issue388,
        'fit_index': fit_index,
        'candidate': candidate,
        'manifest': manifest,
        'report': report,
        'issue352_fit': issue352_fit,
        'issue352_protocol': issue352_protocol,
        'issue352_validation': issue352_validation,
        'candidate_sha256': candidate_sha,
    }


def build(frozen_at: str = DEFAULT_FROZEN_AT) -> dict[str, Any]:
    with guard.dataset_access_tripwire():
        source_check = guard.verify_no_holdout_access(
            SOURCE_PATH.read_text(), allow_literals=SELF_ARTIFACT_LITERALS)
        guard_self_check = guard.verify_guard_is_holdout_free()
        order_guard = guard.assert_validation_not_yet_consumed(ROOT)
        inputs = verify_inputs()
    no_dataset_check = {
        'check': 'no_hand_level_dataset_read',
        'result': 'PASS',
        'detail': (
            'the generator parses no hand-history archive and no decision JSONL; it consumes '
            'content-addressed evidence artifacts only. The build ran with a filesystem tripwire: any '
            'open under the certified dataset tree or of an archive/decision file aborts the build.'
        ),
        'tripwire_id': 'DATASET_ACCESS_TRIPWIRE',
        'filesystem_open_tripwire_enabled': True,
        'dataset_or_holdout_files_opened': [],
    }
    frozen_at_epoch = int(
        dt.datetime.strptime(frozen_at, '%Y-%m-%dT%H:%M:%SZ')
        .replace(tzinfo=dt.timezone.utc)
        .timestamp()
    )
    return build_protocol(
        inputs,
        frozen_at=frozen_at,
        frozen_at_epoch=frozen_at_epoch,
        order_guard=order_guard,
        checks=[source_check, guard_self_check, order_guard, no_dataset_check],
    )


def _code_fingerprints() -> list[dict[str, Any]]:
    rows = []
    for relative, role in CODE_INPUTS:
        path = ROOT / relative
        if not path.is_file():
            raise ProtocolError(f'missing code input {relative}')
        rows.append({'path': relative, 'role': role, 'sha256': sha256_file(path)})
    return rows


def _node_manifest(issue388: Mapping[str, Any]) -> dict[str, Any]:
    rows = []
    for node in issue388['tree']['nodes']:
        edges = node.get('edges') or []
        rows.append({
            'id': node['id'],
            'path': ':'.join(node['path']),
            'runtime_support_context_key': node['runtime_support_context_key'],
            'audit_exact_key': node['audit_exact_key'],
            'runtime_exact_preflop_node_key': node['runtime_exact_preflop_node_key'],
            'actions': sorted({str(edge['action']) for edge in edges}),
            'edge_count': len(edges),
        })
    rows.sort(key=lambda row: row['path'])
    return {
        'manifest_id': 'REQUIRED_TREE_NODES_38',
        'reference_issue': 388,
        'reference_artifact': 'analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json',
        'required_tree_sha256': baseline_tool.ISSUE388_REQUIRED_TREE_SHA256,
        'required_tree_byte_sha256': baseline_tool.ISSUE388_REQUIRED_TREE_BYTE_SHA256,
        'node_count': baseline_tool.ISSUE388_REQUIRED_NODES,
        'unresolved_sizing_frontier_count': baseline_tool.ISSUE388_UNRESOLVED_FRONTIERS,
        'tree_enumeration_complete': bool(issue388['tree']['enumeration_complete']),
        'identity_granularity': 'hierarchical_exact_key',
        'support_isolation_rule': 'SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT',
        'every_node_must_be_answered_or_fail_closed': True,
        'nodes': rows,
        'manifest_canonical_sha256': _digest_nodes(rows),
    }


def build_protocol(
    inputs: Mapping[str, Any],
    *,
    frozen_at: str,
    frozen_at_epoch: int,
    order_guard: Mapping[str, Any],
    checks: list[Mapping[str, Any]],
) -> dict[str, Any]:
    spec = inputs['spec']
    manifest = inputs['manifest']
    report = inputs['report']
    candidate_sha = inputs['candidate_sha256']
    issue352_validation = inputs['issue352_validation']

    code = _code_fingerprints()
    guard_sha = next(row['sha256'] for row in code if row['role'] == 'ORDER_GUARD')
    generator_sha = next(row['sha256'] for row in code if row['role'] == 'PROTOCOL_GENERATOR')

    train_corpus = {
        'population_id': report['population_id'],
        'certification': {
            'path': 'training/datasets/NLHE_100-200/population_certification.json',
            'sha256': manifest['corpus']['certification_sha256'],
            'certified_split_counts': manifest['corpus']['certified_split_counts'],
        },
        'archives': manifest['corpus']['archives'],
        'population_fingerprint_sha256': manifest['corpus']['population_fingerprint_sha256'],
        'train_hands_parsed': manifest['corpus']['train_hands_parsed'],
        'train_decision_rows_parsed': manifest['corpus']['train_decision_rows_parsed'],
        'train_hand_ids_fingerprint_sha256': manifest['corpus']['train_hand_ids_fingerprint_sha256'],
        'consumed_artifacts': [
            {'path': 'analysis/issue419_hierarchical_tree/HIERARCHICAL_MODEL_SPEC.json',
             'role': 'FROZEN_ARCHITECTURE_SPEC', 'sha256': SPEC_BYTE_SHA256,
             'canonical_payload_sha256': SPEC_CANONICAL_SHA256},
            {'path': 'analysis/issue419_hierarchical_tree/HIERARCHICAL_TREE_SPARSITY_BASELINE.json',
             'role': 'TRAIN_SPARSITY_BASELINE',
             'sha256': sha256_file(BASELINE_PATH)},
            {'path': 'analysis/issue419_hierarchical_tree/fit/CANDIDATE.json',
             'role': 'TRAIN_FIT_CANDIDATE',
             'sha256': guard.CANDIDATE_BYTE_SHA256,
             'canonical_payload_sha256': candidate_sha},
            {'path': 'analysis/issue419_hierarchical_tree/fit/CANDIDATE_MANIFEST.json',
             'role': 'TRAIN_FIT_MANIFEST', 'sha256': sha256_file(CANDIDATE_MANIFEST_PATH)},
            {'path': 'analysis/issue419_hierarchical_tree/fit/TRAIN_FIT_REPORT.json',
             'role': 'TRAIN_FIT_REPORT', 'sha256': sha256_file(TRAIN_REPORT_PATH)},
            {'path': 'analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json',
             'role': 'REQUIRED_TREE', 'sha256': baseline_tool.ISSUE388_REQUIRED_TREE_BYTE_SHA256,
             'canonical_payload_sha256': baseline_tool.ISSUE388_REQUIRED_TREE_SHA256},
            {'path': 'analysis/issue388_exact_tree/TRAIN_RESPONSE_TREE_SUPPORT.json',
             'role': 'TRAIN_SUPPORT_MATRIX',
             'sha256': baseline_tool.ISSUE388_TRAIN_SUPPORT_BYTE_SHA256,
             'canonical_payload_sha256': baseline_tool.ISSUE388_TRAIN_SUPPORT_SHA256},
            {'path': 'analysis/issue388_exact_tree/DECISION.json',
             'role': 'FEASIBILITY_DECISION', 'sha256': baseline_tool.ISSUE388_DECISION_BYTE_SHA256,
             'canonical_payload_sha256': baseline_tool.ISSUE388_DECISION_SHA256},
        ],
        'split_consumed_for_authoring': 'TRAIN',
        'validation_consumed_for_authoring': False,
        'test_consumed_for_authoring': False,
    }

    architecture = {
        'model_family': 'MODEL_A_PREFLOP',
        'identity_granularity': 'hierarchical_exact_key',
        'contract_candidate_id': guard.CANDIDATE_ID,
        'candidate_instance_id': guard.CANDIDATE_INSTANCE_ID,
        'estimator': spec['hierarchy_prior_shrinkage']['estimator'],
        'backoff_chain': [
            'EXACT_HAND_CLASS_EXACT_PRICE',
            'EXACT_EXACT_KEY_HIERARCHICAL',
            'POSITIONAL_PRICE_PRIOR',
            'UNRESOLVED',
        ],
        'pooling_levels': [level['level'] for level in spec['hierarchy_prior_shrinkage']['levels']],
        'raise_sizing_policy': 'exact-support-only',
        'nearest_price_fallback': False,
        'nearest_context_fallback': False,
        'representative_price_fallback': False,
        'hidden_hand_imputation': False,
        'pseudo_observation': False,
        'frozen_by_spec': 'analysis/issue419_hierarchical_tree/HIERARCHICAL_MODEL_SPEC.json',
        'spec_canonical_payload_sha256': SPEC_CANONICAL_SHA256,
        'hyperparameters': {
            'hierarchical_strength_kappa0': float(spec['hierarchy_prior_shrinkage']['hierarchical_strength_kappa0']),
            'alpha_per_legal_marginal_action': float(
                spec['hierarchy_prior_shrinkage']['base_prior']['alpha_per_legal_marginal_action']),
            'minimum_marginal_observations': int(spec['decision_thresholds']['minimum_marginal_observations']),
            'minimum_distinct_hands': int(spec['decision_thresholds']['minimum_distinct_hands']),
            'hyperparameter_search_performed': False,
            'validation_used_for_hyperparameters': False,
            'hyperparameters_immutable_after_freeze': True,
        },
    }

    priors_and_shrinkage = {
        'estimator': manifest['priors_and_shrinkage']['estimator'],
        'base_prior': manifest['priors_and_shrinkage']['base_prior'],
        'blend': manifest['priors_and_shrinkage']['blend'],
        'exact_weight': manifest['priors_and_shrinkage']['exact_weight'],
        'kappa0': float(manifest['priors_and_shrinkage']['kappa0']),
        'constraints': manifest['priors_and_shrinkage']['constraints'],
        'no_hidden_hand_imputation': True,
        'no_pseudo_observation': True,
        'frozen': True,
    }

    comparators = {
        'comparator_count': 3,
        'explicitly_listed': True,
        'active_reference': {
            'id': REFERENCE_ID,
            'path': 'training/models/preflop_population_model_v5.json',
            'sha256': REFERENCE_SHA256,
            'role': 'ACTIVE_REFERENCE',
            'is_mutated_by_this_protocol': False,
        },
        'candidate_v2_352': {
            'id': ISSUE352_CANDIDATE_ID,
            'issue': 352,
            'candidate_sha256': ISSUE352_CANDIDATE_SHA256,
            'role': 'ADMITTED_EXACT_PRICE_COMPARATOR',
            'evidence_pinning': {
                'fit_artifact': {
                    'path': 'analysis/model_a_preflop_sizing_v2_fit.json',
                    'sha256': ISSUE352_FIT_BYTE_SHA256,
                    'candidate_sha256': inputs['issue352_fit']['candidate_sha256'],
                    'selected_prior_strength': inputs['issue352_fit']['shrinkage']['selected_prior_strength'],
                },
                'validation_protocol': {
                    'path': 'analysis/model_a_preflop_sizing_v2_validation_protocol.json',
                    'sha256': ISSUE352_VALIDATION_PROTOCOL_SHA256,
                    'status': inputs['issue352_protocol']['status'],
                    'frozen_train_fit_candidate_sha256': inputs['issue352_protocol'][
                        'frozen_train_fit']['candidate_sha256'],
                },
                'validation_evidence': {
                    'path': 'analysis/model_a_preflop_sizing_v2_validation.json',
                    'byte_sha256': ISSUE352_VALIDATION_EVIDENCE_BYTE_SHA256,
                    'self_reported_evidence_sha256': ISSUE352_VALIDATION_EVIDENCE_SHA256,
                    'evidence_sha256': issue352_validation['evidence_sha256'],
                    'outcome': issue352_validation['outcome'],
                    'test_consumed': issue352_validation['test_consumed'],
                    'active_model_replaced': issue352_validation['active_model_replaced'],
                },
            },
            'reused_role': 'DESCRIPTIVE_PREDICTIVE_COMPARATOR_ONLY',
            're_reads_this_candidate_holdout': False,
        },
        'new_candidate': {
            'id': guard.CANDIDATE_ID,
            'candidate_instance_id': guard.CANDIDATE_INSTANCE_ID,
            'path': 'analysis/issue419_hierarchical_tree/fit/CANDIDATE.json',
            'canonical_payload_sha256': candidate_sha,
            'byte_sha256': guard.CANDIDATE_BYTE_SHA256,
            'role': 'CANDIDATE_UNDER_TEST',
            'status': 'CANDIDATE_ONLY_NOT_ACTIVE',
            'distinct_from_issue352_candidate': True,
        },
    }

    metrics = {
        'primary': {
            'name': 'multiclass_log_loss',
            'definition': 'mean over scored decisions of -ln p_hat(observed_action | requested_key)',
            'epsilon_clip': 1e-12,
            'natural_log': True,
        },
        'secondary': [
            {'name': 'brier_score',
             'definition': 'sum over legal actions of (p_hat - 1[observed])^2'},
            {'name': 'ece',
             'definition': 'expected calibration error, 10 equal-count bins per action class'},
            {'name': 'coverage',
             'definition': 'share of in-scope decisions answered with a non-UNRESOLVED reason code'},
            {'name': 'abstain_rate',
             'definition': 'share of in-scope decisions that stay UNRESOLVED and emit no action'},
            {'name': 'mean_effective_sample_size',
             'definition': 'mean effective sample size of answered decisions'},
        ],
        'paired_unit': 'hand_id',
        'pairing_rule': 'a paired delta is computed only on decisions both models answer at the same requested key',
        'bootstrap': {
            'samples': 5000,
            'seed': 419,
            'confidence_level': 0.95,
            'method': 'paired_percentile_bootstrap',
        },
        'stratification': [
            'by reason_code',
            'by pooling.level',
            'by observations bucket',
            'by distinct-hands bucket',
        ],
        'mandatory_reporting': (
            'a pooled estimate is never scored without its pooling level; calibration must not be '
            'reported on pooled support as if it were exact support'
        ),
    }

    thresholds = {
        'frozen': True,
        'immutable_after_freeze': True,
        'minimum_marginal_observations': int(spec['decision_thresholds']['minimum_marginal_observations']),
        'minimum_distinct_hands': int(spec['decision_thresholds']['minimum_distinct_hands']),
        'exact_claim_requires': 'L0_EXACT_KEY meeting both the 20-observation and 20-distinct-hands thresholds',
        'minimum_identifiable_validation_decisions': 200,
        'minimum_identifiable_validation_hands': 100,
        'non_inferiority_ci_upper_bound': 0.0,
        'maximum_absolute_ece': 0.05,
        'maximum_ece_delta_vs_active': 0.02,
        'abstention_is_not_a_failure': True,
        'coverage_is_not_an_admission_gate': (
            'a lower coverage than the active reference never counts as an admission and never '
            'justifies lowering a frozen support threshold; fail-closed abstention is correctness'
        ),
    }

    pooling_limits = {
        'frozen': True,
        'immutable_after_freeze': True,
        'rule_id': 'SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT',
        'statement': (
            'a key A may never be declared supported by observations of a different key B; support '
            'counts are exact and pooling only feeds the prior'
        ),
        'only_support_source_level': 'L0_EXACT_KEY',
        'maximum_pooling_level_for_an_exact_support_claim': 'L0_EXACT_KEY',
        'maximum_pooling_level_for_a_reported_estimate': 'L4_POSITION_PRICE_PRIOR',
        'maximum_pooling_depth': 4,
        'fixed_shrinkage_strength_kappa0': float(manifest['priors_and_shrinkage']['kappa0']),
        'alpha_per_legal_marginal_action': float(
            manifest['priors_and_shrinkage']['base_prior']['alpha_per_legal_marginal_action']),
        'acceptable_levels': [
            {
                'level': level['level'],
                'rank': level['rank'],
                'purpose': level['purpose'],
                'support_source_allowed': level['support_source_allowed'],
                'allowed_in_validation_output': True,
            }
            for level in manifest['hyperparameters']['pooling_levels']
        ],
        'forbidden': [
            'cross-key support borrowing',
            'coarse-key support laundering',
            'support counts smoothed across levels',
            'nearest-price or nearest-context substitution',
            'representative raise price',
            'hidden-hand imputation',
            'pseudo-observations',
            'raising the 20/20 support thresholds after reading VALIDATION',
        ],
        'discipline': (
            'an estimate reported above L0_EXACT_KEY is labelled EXACT_HIERARCHICAL_ESTIMATE, is '
            'never counted as exact support, and never satisfies an exact-support gate'
        ),
    }

    calibration_and_admission = {
        'calibration': {
            'method': 'equal-count reliability bins',
            'bins_per_action_class': 10,
            'minimum_bin_support_for_a_calibration_claim': 20,
            'report_pooling_level_always': True,
        },
        'admission_gates': [
            {'gate': 'split_discipline',
             'rule': 'evaluate VALIDATION only; TEST stays unconsumed and unauthorized'},
            {'gate': 'coverage_floor',
             'rule': 'identifiable VALIDATION decisions >= 200 and distinct hands >= 100'},
            {'gate': 'candidate_not_inferior_to_active',
             'rule': 'paired candidate-minus-active 95% CI upper bound <= 0'},
            {'gate': 'candidate_not_inferior_to_v2',
             'rule': 'paired candidate-minus-#352-v2 95% CI upper bound <= 0'},
            {'gate': 'calibration_absolute',
             'rule': 'pooled ECE <= 0.05'},
            {'gate': 'calibration_delta_vs_active',
             'rule': 'candidate ECE minus active ECE <= 0.02'},
            {'gate': 'pooling_discipline',
             'rule': 'every answered decision carries pooling.level and pooling.source_key == requested_key'},
            {'gate': 'support_isolation',
             'rule': 'support.source_key == requested_key for every answered decision'},
            {'gate': 'exact_claim_discipline',
             'rule': 'EXACT_EMPIRICAL_STRONG is emitted only at L0_EXACT_KEY'},
        ],
        'outcome_rule': (
            'ADMIT_CANDIDATE only when every frozen gate passes; otherwise RETAIN_ACTIVE_REFERENCE'
        ),
        'no_partial_admission': True,
        'automatic_promotion': 'FORBIDDEN',
        'active_pointer_mutation': 'FORBIDDEN',
        'unresolved_nodes_do_not_fail_the_run': (
            'a node that stays EXACT_UNRESOLVED is reported as such; it is neither an admission nor a '
            'defect, and it never blocks the outcome decision'
        ),
    }

    issue367_rule = {
        'rule_id': 'ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE',
        'question': 'is a #367 consumption of the hierarchical candidate authorized or forbidden?',
        'authorized_at_freeze': False,
        'authorized_when': [
            'the frozen VALIDATION evaluation returns outcome=ADMIT_CANDIDATE',
            'every frozen gate passes with the threshold values pinned in this protocol',
            'the VALIDATION result is content-addressed (schema poker-hierarchical-validation-result/v1, '
            'embedded protocol_byte_sha256) and pinned in a new explicit #367 protocol revision',
            'that #367 protocol revision names model_a.candidate_id='
            + guard.CANDIDATE_ID + ' and model_a.candidate_sha256=' + candidate_sha,
        ],
        'forbidden_while': [
            'the outcome is RETAIN_ACTIVE_REFERENCE or the candidate stays UNRESOLVED',
            'no ADMIT_CANDIDATE VALIDATION result exists for this candidate',
            'the candidate SHA differs from the pinned canonical payload digest',
            'a #367 run would change TEST consumption, Model B, Hero EV or the active Model A pointer',
        ],
        'consequence_when_forbidden': (
            'no #367 real ISO EV run, no exact-support grid extension and no provider wiring may consume '
            'this candidate; #367 keeps its current admitted model'
        ),
        'currently_admitted_model_a_for_367': {
            'candidate_id': ISSUE352_CANDIDATE_ID,
            'candidate_sha256': ISSUE352_CANDIDATE_SHA256,
            'admission_decision': issue352_validation['outcome'],
            'validation_evidence_sha256': issue352_validation['evidence_sha256'],
            'fit_evidence_sha256': inputs['issue352_fit']['evidence_sha256'],
            'active_model_pointer_mutation': False,
        },
        'unchanged_by_this_freeze': True,
        'test_consumed': False,
        'model_b_consumed': False,
        'hero_ev_consumed': False,
        'promotion_performed': False,
    }

    output_schema = {
        'schema': RESULT_SCHEMA,
        'path': RESULT_PATH,
        'required_fields': [
            'schema', 'issue', 'phase', 'protocol_byte_sha256', 'protocol_canonical_payload_sha256',
            'candidate', 'comparators', 'split', 'metrics', 'gate', 'outcome', 'coverage',
            'evidence_sha256', 'test_consumed', 'test_authorized', 'production_effect',
            'active_model_replaced', 'automatic_promotion', 'model_b_consumed', 'hero_ev_consumed',
        ],
        'outcome_enum': ['ADMIT_CANDIDATE', 'RETAIN_ACTIVE_REFERENCE'],
        'evidence_digest_rule': (
            'result.evidence_sha256 = canonical sha256 (sorted keys, compact separators) of the result '
            'payload without its own evidence_sha256 field'
        ),
        'every_decision_must_carry': ['requested_key', 'reason_code', 'pooling.level', 'pooling.source_key',
                                      'support.observations', 'support.distinct_hands',
                                      'support.source_key', 'posterior'],
        'fixed_flags': {
            'test_consumed': False,
            'test_authorized': False,
            'production_effect': 'NONE',
            'active_model_replaced': False,
            'automatic_promotion': False,
            'model_b_consumed': False,
            'hero_ev_consumed': False,
        },
        'output_must_not_exist_before_the_freeze': True,
    }

    holdout_boundary = {
        'split_consumed_for_authoring': 'TRAIN',
        'validation_consumed_for_authoring': False,
        'validation_decisions_read': 0,
        'validation_hands_parsed': 0,
        'test_consumed': False,
        'test_decisions_read': 0,
        'protocol_frozen_before_holdout_read': True,
        'validation_read_before_protocol_hash': False,
        'evaluation_split_opened_during_authoring': False,
        'predecessor_validation_reads': [
            {
                'issue': 352,
                'candidate_id': ISSUE352_CANDIDATE_ID,
                'candidate_sha256': ISSUE352_CANDIDATE_SHA256,
                'validation_protocol_sha256': ISSUE352_VALIDATION_PROTOCOL_SHA256,
                'validation_evidence_sha256': ISSUE352_VALIDATION_EVIDENCE_SHA256,
                'validation_evidence_byte_sha256': ISSUE352_VALIDATION_EVIDENCE_BYTE_SHA256,
                'outcome': issue352_validation['outcome'],
                'read_before_this_freeze': True,
                'scope': 'DIFFERENT_CANDIDATE_UNDER_ITS_OWN_FROZEN_PROTOCOL',
                'reads_this_candidate_holdout': False,
                'note': (
                    'recorded as evidence, not repaired: the #352 split consumption belongs to the '
                    'exact-price candidate, so it neither violates nor satisfies this candidate order guard'
                ),
            }
        ],
        'checks': [dict(row) for row in checks],
    }

    evaluation = {
        'split': 'VALIDATION',
        'test_consumed': False,
        'test_authorized': False,
        'population': 'pokerstars_nlhe_100-200_zoom_play_6max_v1',
        'universe': (
            'non-Hero public preflop decisions of the #319/#321 focus families where the candidate and '
            'every comparator both answer the same exact requested key'
        ),
        'unresolved_policy': (
            'fails-closed decisions are reported and excluded from the paired predictive gates; they '
            'never score as correct by defaulting to FOLD'
        ),
        'outcome_rule': calibration_and_admission['outcome_rule'],
        'result_schema': RESULT_SCHEMA,
        'result_path': output_schema['path'],
    }

    publication = {
        'automatic_promotion': 'FORBIDDEN',
        'active_reference_mutation': 'FORBIDDEN',
        'active_model_pointer_mutation': False,
        'production_effect': 'NONE',
        'downstream': (
            'only an ADMIT_CANDIDATE outcome may be consumed downstream; a rejected candidate leaves '
            'the active Model A v5 pointer unchanged'
        ),
    }

    forbidden = [
        'TEST',
        'HERO_EV',
        'MODEL_B',
        'UI',
        'NEAREST_PRICE',
        '#314_REAL_OPTIMIZATION',
        'ACTIVE_POINTER_MUTATION',
        'AUTOMATIC_PROMOTION',
        'HYPERPARAMETER_SEARCH_ON_VALIDATION',
        'THRESHOLD_RELAXATION_AFTER_VALIDATION',
        'POOLING_LIMIT_RELAXATION_AFTER_VALIDATION',
        'CROSS_KEY_SUPPORT_BORROWING',
        'HIDDEN_HAND_IMPUTATION',
        'PSEUDO_OBSERVATION',
    ]

    return {
        'schema': SCHEMA,
        'issue': 419,
        'parent_issue': 314,
        'kind': 'FROZEN_VALIDATION_PROTOCOL',
        'status': FROZEN_STATUS,
        'spec_frozen_date': FROZEN_DATE,
        'frozen_at': frozen_at,
        'frozen_at_epoch': frozen_at_epoch,
        'frozen_at_source': 'explicit_freeze_timestamp_recorded_before_any_validation_read',
        'predecessor_issues': [321, 339, 352, 367, 388],
        'protocol_name': NAME,
        'protocol_byte_sha256_location': (
            'the protocol digest cannot live inside the protocol payload; it is recorded in '
            'FROZEN_VALIDATION_PROTOCOL.sha256 and validation_protocol/ARTIFACTS.json and re-verified '
            'by the evaluation-side order guard'
        ),
        'authoring_order': {
            'protocol_written_and_hashed_before_validation_read': True,
            'validation_read_before_protocol_hash': False,
            'evaluation_split_opened_during_authoring': False,
            'canonical_payload_is_the_frozen_identity': True,
        },
        'candidate': {
            'candidate_id': guard.CANDIDATE_ID,
            'candidate_instance_id': guard.CANDIDATE_INSTANCE_ID,
            'path': 'analysis/issue419_hierarchical_tree/fit/CANDIDATE.json',
            'canonical_payload_sha256': candidate_sha,
            'byte_sha256': guard.CANDIDATE_BYTE_SHA256,
            'manifest_path': 'analysis/issue419_hierarchical_tree/fit/CANDIDATE_MANIFEST.json',
            'manifest_sha256': sha256_file(CANDIDATE_MANIFEST_PATH),
            'status': 'CANDIDATE_ONLY_NOT_ACTIVE',
            'fit_scope': report['fit_scope'],
            'data_scope': report['data_scope'],
        },
        'code': {
            'cluster_id': 'ISSUE419_HIERARCHICAL_VALIDATION_CODE_CLUSTER',
            'inputs': code,
            'protocol_generator_sha256': generator_sha,
            'order_guard_sha256': guard_sha,
            'frozen': True,
        },
        'train_corpus': train_corpus,
        'architecture': architecture,
        'priors_and_shrinkage': priors_and_shrinkage,
        'requirement_manifest': _node_manifest(inputs['issue388']),
        'seeds': manifest['seeds'],
        'metrics': metrics,
        'thresholds': thresholds,
        'pooling_limits': pooling_limits,
        'comparators': comparators,
        'calibration_and_admission': calibration_and_admission,
        'issue367_rule': issue367_rule,
        'output_schema': output_schema,
        'evaluation': evaluation,
        'publication': publication,
        'order_guard': {
            **order_guard_block(guard_sha),
            **dict(order_guard),
            'freeze_authored_before_validation': True,
            'validation_read_before_freeze': False,
        },
        'holdout_boundary': holdout_boundary,
        'forbidden': forbidden,
        'not_an_admission': (
            'this protocol admits nothing by itself: it fixes the rules, the thresholds and the '
            'comparators before the VALIDATION holdout is opened'
        ),
        'reproduction': {
            'command': 'python3 tools/training/write_frozen_validation_protocol.py',
            'check_command': 'python3 tools/training/write_frozen_validation_protocol.py --check',
        },
    }


def order_guard_block(guard_sha: str) -> dict[str, Any]:
    return {
        'guard_id': 'VALIDATION_ORDER_GUARD',
        'enforced_by': 'tools/training/validation_order_guard.py',
        'guard_source_sha256': guard_sha,
        'rule': (
            'the freeze fails closed when a VALIDATION result that references the hierarchical '
            'candidate already exists'
        ),
        'declared_result_locations': [str(x) for x in guard.DECLARED_RESULT_LOCATIONS],
        'detection': (
            'declared result locations first, then a content scan of analysis/**/*.json for '
            'result-shaped payloads that declare a VALIDATION read and reference the candidate'
        ),
        'evaluation_side_rule': (
            'the evaluation command must call assert_protocol_frozen_before_validation() before it '
            'opens a single VALIDATION hand'
        ),
    }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def summarize(protocol: Mapping[str, Any], digest: str) -> str:
    candidate = protocol['candidate']
    comparators = protocol['comparators']
    return (
        '# #419 — frozen VALIDATION protocol (authored before any holdout read)\n\n'
        f'`FROZEN_VALIDATION_PROTOCOL.json` byte SHA256: `{digest}`; frozen at '
        f"`{protocol['frozen_at']}` (`{protocol['status']}`). The canonical payload hash and the "
        'content-addressed copies are in `validation_protocol/ARTIFACTS.json`.\n\n'
        f"Comparators are listed explicitly: the active reference "
        f"`{comparators['active_reference']['id']}` (`{comparators['active_reference']['sha256']}`), the "
        f"admitted #352 exact-price candidate `{comparators['candidate_v2_352']['id']}` "
        f"(`{comparators['candidate_v2_352']['candidate_sha256']}`, fit/validation evidence pinned), and "
        f"the new candidate under test `{candidate['candidate_id']}` "
        f"(`{candidate['canonical_payload_sha256']}`).\n\n"
        f"The requirement manifest pins all "
        f"{protocol['requirement_manifest']['node_count']} #388 tree nodes to "
        f"`{protocol['requirement_manifest']['required_tree_sha256']}`, including the "
        f"{protocol['requirement_manifest']['unresolved_sizing_frontier_count']} unresolved raise-sizing "
        'frontiers. Thresholds (20 observations / 20 distinct hands, non-inferiority CI upper bound <= 0, '
        'ECE <= 0.05) and the acceptable pooling limits (L0 is the only support source, L4 the deepest '
        'parameter prior) are frozen and immutable after the freeze.\n\n'
        'The order guard is enforced by `tools/training/validation_order_guard.py`: the freeze aborts if '
        'a VALIDATION result for this candidate already exists, and the evaluation command must re-verify '
        'the pinned protocol bytes before opening a single VALIDATION hand. The #352 split consumption is '
        'recorded as a different candidate under its own frozen protocol, never repaired or double-counted. '
        'No VALIDATION or TEST decision was parsed while authoring this protocol. It admits nothing.\n\n'
        'Reproduce: `python3 tools/training/write_frozen_validation_protocol.py --check`.\n'
    )


def persist(protocol: Mapping[str, Any]) -> dict[str, Any]:
    BUNDLE.mkdir(parents=True, exist_ok=True)
    objects = BUNDLE / 'sha256'
    objects.mkdir(exist_ok=True)
    payload_bytes = serialize(protocol)
    digest = hashlib.sha256(payload_bytes).hexdigest()
    (BUNDLE / NAME).write_bytes(payload_bytes)
    (objects / (digest + '.json')).write_bytes(payload_bytes)
    summary_bytes = summarize(protocol, digest).encode()
    summary_digest = hashlib.sha256(summary_bytes).hexdigest()
    (BUNDLE / 'SUMMARY.md').write_bytes(summary_bytes)
    (objects / (summary_digest + '.md')).write_bytes(summary_bytes)
    index = {
        NAME: {
            'sha256': digest,
            'canonical_payload_sha256': stable_hash(protocol),
            'object': 'sha256/' + digest + '.json',
        },
        'SUMMARY.md': {'sha256': summary_digest, 'object': 'sha256/' + summary_digest + '.md'},
    }
    (BUNDLE / 'ARTIFACTS.json').write_text(json.dumps(index, sort_keys=True, indent=2) + '\n')
    referenced = {Path(entry['object']).name for entry in index.values()}
    for path in objects.iterdir():
        if path.is_file() and path.name not in referenced:
            path.unlink()
    PROTOCOL_PATH.write_bytes(payload_bytes)
    DIGEST_PATH.write_text(
        f'{digest}  {NAME}\n# canonical_payload_sha256 {stable_hash(protocol)}\n'
        f"# frozen_at {protocol['frozen_at']}\n"
    )
    return index


def _persisted_frozen_at() -> str:
    if PROTOCOL_PATH.is_file():
        try:
            return str(_load(PROTOCOL_PATH).get('frozen_at') or DEFAULT_FROZEN_AT)
        except (OSError, ValueError):
            return DEFAULT_FROZEN_AT
    return DEFAULT_FROZEN_AT


def check() -> int:
    protocol = build(frozen_at=_persisted_frozen_at())
    expected = serialize(protocol)
    expected_digest = hashlib.sha256(expected).hexdigest()
    problems: list[str] = []
    if not PROTOCOL_PATH.is_file() or PROTOCOL_PATH.read_bytes() != expected:
        problems.append('canonical protocol bytes differ from a fresh build')
    index = _load(BUNDLE / 'ARTIFACTS.json')
    entry = index.get(NAME, {})
    if entry.get('sha256') != expected_digest:
        problems.append('protocol index digest mismatch')
    if entry.get('canonical_payload_sha256') != stable_hash(protocol):
        problems.append('protocol canonical payload digest mismatch')
    if (BUNDLE / NAME).read_bytes() != expected:
        problems.append('bundle protocol bytes differ from a fresh build')
    if (BUNDLE / entry.get('object', 'missing')).read_bytes() != expected:
        problems.append('content-addressed protocol object mismatch')
    sidecar = DIGEST_PATH.read_text()
    if not sidecar.startswith(expected_digest + '  ' + NAME):
        problems.append('protocol .sha256 sidecar mismatch')
    for name, row in index.items():
        data = (BUNDLE / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != row['sha256']:
            problems.append(f'byte hash mismatch for {name}')
        if data != (BUNDLE / row['object']).read_bytes():
            problems.append(f'content-addressed copy mismatch for {name}')
    if {p.name for p in (BUNDLE / 'sha256').iterdir()} != {
        Path(row['object']).name for row in index.values()
    }:
        problems.append('unexpected object in validation_protocol/sha256')
    try:
        guard.assert_protocol_frozen_before_validation(PROTOCOL_PATH, expected_byte_sha256=expected_digest)
    except guard.ValidationOrderError as error:
        problems.append(f'order guard rejected the frozen protocol: {error}')
    if problems:
        print(json.dumps({'status': 'MISMATCH', 'problems': problems}, indent=2))
        return 1
    print(json.dumps({
        'status': 'OK',
        'schema': SCHEMA,
        'protocol_sha256': expected_digest,
        'canonical_payload_sha256': stable_hash(protocol),
        'frozen_at': protocol['frozen_at'],
        'comparators': list(protocol['comparators']),
        'required_nodes': protocol['requirement_manifest']['node_count'],
        'validation_consumed': protocol['holdout_boundary']['validation_consumed_for_authoring'],
    }, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='verify the persisted protocol instead of rewriting it')
    parser.add_argument('--frozen-at', default=None,
                        help='explicit ISO-8601 freeze timestamp (defaults to the persisted one)')
    args = parser.parse_args()
    if args.check:
        return check()
    frozen_at = args.frozen_at or _persisted_frozen_at()
    protocol = build(frozen_at=frozen_at)
    index = persist(protocol)
    print(json.dumps({
        'schema': SCHEMA,
        'protocol_path': str(PROTOCOL_PATH.relative_to(ROOT)),
        'bundle': str(BUNDLE.relative_to(ROOT)),
        'protocol_sha256': index[NAME]['sha256'],
        'canonical_payload_sha256': index[NAME]['canonical_payload_sha256'],
        'frozen_at': protocol['frozen_at'],
        'comparators': list(protocol['comparators']),
        'required_nodes': protocol['requirement_manifest']['node_count'],
        'validation_consumed': protocol['holdout_boundary']['validation_consumed_for_authoring'],
        'order_guard': protocol['order_guard']['result'],
    }, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
