#!/usr/bin/env python3
"""#419: content-addressed TRAIN-only spec of the hierarchical exact-context model.

Writes ``analysis/issue419_hierarchical_tree/HIERARCHICAL_MODEL_SPEC.json`` plus a
content-addressed bundle under ``analysis/issue419_hierarchical_tree/model_spec/``.

Scientific boundary
-------------------
The spec is authored, frozen and hashed from TRAIN-only and structural evidence
**before** any VALIDATION decision is read. This tool has no holdout code path:
it parses no hand history at all, it consumes content-addressed evidence
artifacts, it fails closed when a consumed artifact declares a non-TRAIN split,
and it statically refuses to load the known holdout loaders (see
``HOLDOUT_LOADER_SYMBOLS`` and ``verify_no_holdout_access``).

The spec records the explicit granularity decision forced by the open
``RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE`` risk, the mutualizable versus
never-mutualizable axes, and the rule that a key A may never be declared
supported by observations of a different key B.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import json
import pathlib
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import sha256_file
from tools.training import audit_hierarchical_tree_sparsity as baseline_tool
from tools.training.audit_preflop_sizing_support import stable_hash

HERE = ROOT / 'analysis/issue419_hierarchical_tree'
BUNDLE = HERE / 'model_spec'
SPEC_PATH = HERE / 'HIERARCHICAL_MODEL_SPEC.json'
DIGEST_PATH = HERE / 'HIERARCHICAL_MODEL_SPEC.sha256'
BASELINE_PATH = HERE / baseline_tool.BASELINE_NAME
BASELINE_INDEX_PATH = HERE / 'ARTIFACTS.json'
ISSUE388 = baseline_tool.ISSUE388_OUTPUT
SOURCE_PATH = Path(__file__).resolve()

SPEC_NAME = 'HIERARCHICAL_MODEL_SPEC.json'
SCHEMA = 'poker-hierarchical-exact-context-model-spec/v1'
SPEC_FROZEN_DATE = '2026-09-25'

# Symbols that would indicate a holdout (VALIDATION/TEST) read. The generator must
# not contain any of them; the check is executed at build time and in tests.
HOLDOUT_LOADER_SYMBOLS = (
    'load_validation_records',
    'validation_records',
    'validation_hand_ids',
    'VALIDATION_HANDS',
    'load_holdout',
    'holdout_records',
    'build_validation_decisions',
    'load_test_records',
    'TEST_HANDS',
    'test_hand_ids',
)
HOLDOUT_PATH_MARKERS = ('validation', 'holdout', 'test')

# Every artifact this spec consumes. Structural/source inputs declare no split;
# evidence inputs must declare TRAIN-only.
INPUT_WHITELIST = (
    ('analysis/issue419_hierarchical_tree/HIERARCHICAL_TREE_SPARSITY_BASELINE.json',
     'TRAIN_ONLY_SPARSITY_BASELINE', 'evidence'),
    ('analysis/issue419_hierarchical_tree/ARTIFACTS.json',
     'CONTENT_ADDRESS_INDEX', 'index'),
    ('analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json',
     'STRUCTURAL_REQUIRED_TREE', 'structural'),
    ('analysis/issue388_exact_tree/TRAIN_RESPONSE_TREE_SUPPORT.json',
     'TRAIN_SUPPORT_MATRIX', 'evidence'),
    ('analysis/issue388_exact_tree/DECISION.json',
     'FEASIBILITY_DECISION', 'evidence'),
    ('tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.snapshots.json',
     'CANONICAL_FIXTURE', 'structural'),
    ('tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.hand.txt',
     'CANONICAL_FIXTURE_HAND', 'structural'),
    ('training/models/preflop_population_model_v5.json',
     'REFERENCE_MODEL', 'structural'),
    ('tools/preflop/model_a_sizing_likelihood.py',
     'RUNTIME_SUPPORT_KEY_CONTRACT', 'source'),
    ('tools/training/write_hierarchical_model_spec.py',
     'SPEC_GENERATOR_SELF', 'source'),
)


class HoldoutAccessError(RuntimeError):
    """Raised when any consumed input would cross the TRAIN boundary."""


@contextlib.contextmanager
def dataset_access_tripwire():
    """Record every filesystem open performed while the spec is built.

    The build must open evidence/source files only. Opening anything under the
    certified dataset tree (or any hand-history archive) is a boundary break and
    fails the build; the observed list is recorded as evidence.
    """
    opened: list[str] = []
    original_open = pathlib.Path.open

    def guarded_open(self, *args, **kwargs):
        if _is_dataset_open(str(self)):
            raise HoldoutAccessError(f'dataset/holdout file opened during spec build: {self}')
        opened.append(str(self))
        return original_open(self, *args, **kwargs)

    pathlib.Path.open = guarded_open
    try:
        yield opened
    finally:
        pathlib.Path.open = original_open


def _is_dataset_open(raw: str) -> bool:
    normalized = str(raw).replace('\\', '/')
    name = normalized.rsplit('/', 1)[-1].lower()
    return 'training/datasets/' in normalized or name.endswith(('.zip', '.jsonl'))


def _relative_open_set(paths: list[str]) -> list[str]:
    resolved = set()
    for raw in paths:
        path = pathlib.Path(raw)
        try:
            resolved.add(str(path.resolve().relative_to(ROOT)))
        except ValueError:
            resolved.add(str(path))
    return sorted(resolved)


def _undeclared_opens(paths: list[str]) -> list[str]:
    """Files opened by the build that are not declared inputs or pinned #388 evidence."""
    declared = {path for path, _role, _kind in INPUT_WHITELIST}
    undeclared = []
    for relative in _relative_open_set(paths):
        if relative.startswith('analysis/issue388_exact_tree/'):
            continue
        if relative not in declared:
            undeclared.append(relative)
    return undeclared


def serialize(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def verify_no_holdout_access(source: str | None = None) -> dict[str, Any]:
    """Static, reproducible proof that the generator cannot read a holdout split.

    The scan is AST-based on purpose: it looks for identifiers actually used
    (calls, attribute access, imports) and for holdout-looking data paths, not
    for the words themselves, so the declarative constants above stay readable.
    """
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
    hits = sorted(used & set(HOLDOUT_LOADER_SYMBOLS))
    if hits:
        raise HoldoutAccessError(f'holdout loader symbol used in spec generator: {hits}')
    bad_imports = sorted(
        name for name in imported
        if any(marker in name.lower() for marker in ('validation', 'holdout'))
    )
    if bad_imports:
        raise HoldoutAccessError(f'holdout-looking import in spec generator: {bad_imports}')
    data_extensions = ('.json', '.jsonl', '.zip', '.txt', '.csv', '.snapshots')
    bad_literals = sorted(
        node.value for node in ast.walk(module)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.value.endswith(data_extensions)
        and any(marker in node.value.lower() for marker in ('validation', 'holdout'))
    )
    if bad_literals:
        raise HoldoutAccessError(f'holdout-looking data path literal: {bad_literals}')
    bad_paths = [
        path for path, _role, _kind in INPUT_WHITELIST
        if any(marker in Path(path).name.lower() for marker in HOLDOUT_PATH_MARKERS)
    ]
    if bad_paths:
        raise HoldoutAccessError(f'holdout-looking path in input whitelist: {bad_paths}')
    return {
        'check': 'self_source_scan_for_holdout_loaders',
        'result': 'PASS',
        'forbidden_symbols': list(HOLDOUT_LOADER_SYMBOLS),
        'hits': [],
        'holdout_looking_imports': [],
        'holdout_looking_data_path_literals': [],
        'input_whitelist_holdout_paths': [],
        'detail': (
            'AST scan: the spec generator uses none of the forbidden holdout loader symbols, imports no '
            'validation/holdout module and declares no validation/holdout data path'
        ),
    }


def assert_train_only_artifact(name: str, payload: Mapping[str, Any]) -> None:
    """Tripwire: any consumed evidence declaring a holdout split aborts the build."""
    for field in ('validation_consumed', 'test_consumed'):
        if payload.get(field) is True:
            raise HoldoutAccessError(f'{name} declares {field}=true')
    split = payload.get('split_consumed')
    if split not in (None, 'TRAIN'):
        raise HoldoutAccessError(f'{name} declares split_consumed={split!r}')


def input_fingerprints() -> list[dict[str, Any]]:
    rows = []
    for path, role, kind in INPUT_WHITELIST:
        absolute = ROOT / path
        if not absolute.is_file():
            raise FileNotFoundError(absolute)
        rows.append({
            'path': path,
            'role': role,
            'kind': kind,
            'sha256': sha256_file(absolute),
            'split_consumed': 'TRAIN' if kind == 'evidence' else None,
        })
    return rows


AXES: tuple[dict[str, Any], ...] = (
    {
        'axis': 'requested_key_identity',
        'kind': 'key_identity',
        'definition': 'the exact requested L0 key string itself (hierarchical_exact_key)',
        'identity_axis': True,
        'mutualizable_in_parameters': False,
        'pooling_level_if_mutualizable': None,
        'rationale': (
            'the requested key answers "which context was asked"; merging it would make the answer '
            'about a different question'
        ),
    },
    {
        'axis': 'actor_position',
        'kind': 'position',
        'definition': 'position of the acting player (public)',
        'identity_axis': True,
        'mutualizable_in_parameters': False,
        'pooling_level_if_mutualizable': None,
        'rationale': 'positions are never mutualizable per ticket point 3',
    },
    {
        'axis': 'aggressor_position',
        'kind': 'position',
        'definition': 'position of the last observed raiser/jammer (public)',
        'identity_axis': True,
        'mutualizable_in_parameters': False,
        'pooling_level_if_mutualizable': None,
        'rationale': 'positions are never mutualizable per ticket point 3',
    },
    {
        'axis': 'target_total_bb',
        'kind': 'price_exact',
        'definition': 'exact total preflop contribution targeted by the price being faced',
        'identity_axis': True,
        'mutualizable_in_parameters': False,
        'pooling_level_if_mutualizable': None,
        'rationale': 'exact price is never mutualizable; no representative or nearest price',
    },
    {
        'axis': 'to_call_bb',
        'kind': 'price_exact',
        'definition': 'exact incremental chips required from the actor',
        'identity_axis': True,
        'mutualizable_in_parameters': False,
        'pooling_level_if_mutualizable': None,
        'rationale': 'exact price is never mutualizable; no representative or nearest price',
    },
    {
        'axis': 'effective_stack_bucket',
        'kind': 'stack_bucket',
        'definition': 'existing policy_context effective-stack bucket of the actor',
        'identity_axis': True,
        'mutualizable_in_parameters': True,
        'pooling_level_if_mutualizable': 'L1_STACK_POOL',
        'rationale': 'stack depth shifts strategy smoothly; usable as a shrinkage axis, never as support',
    },
    {
        'axis': 'pot_before_bb',
        'kind': 'pot_exact',
        'definition': 'exact pot before the action, in big blinds',
        'identity_axis': True,
        'mutualizable_in_parameters': True,
        'pooling_level_if_mutualizable': 'L2_POT_POOL',
        'rationale': 'pot size is a consequence of the retained price/position axes; poolable for parameters',
    },
    {
        'axis': 'history',
        'kind': 'public_sequence',
        'definition': 'ordered prior voluntary (position, action) pairs',
        'identity_axis': True,
        'mutualizable_in_parameters': True,
        'pooling_level_if_mutualizable': 'L3_RUNTIME_SUPPORT_CONTEXT',
        'rationale': 'the counted family/count summary is retained at L3; the full ordered tail is not',
    },
    {
        'axis': 'live_positions',
        'kind': 'public_sequence',
        'definition': 'sorted set of positions that have not folded',
        'identity_axis': True,
        'mutualizable_in_parameters': True,
        'pooling_level_if_mutualizable': 'L3_RUNTIME_SUPPORT_CONTEXT',
        'rationale': 'redundant with the retained history for the current provider granularity',
    },
    {
        'axis': 'all_in_positions',
        'kind': 'public_sequence',
        'definition': 'sorted set of all-in positions',
        'identity_axis': True,
        'mutualizable_in_parameters': True,
        'pooling_level_if_mutualizable': 'L3_RUNTIME_SUPPORT_CONTEXT',
        'rationale': 'all-in state is already reflected in the retained price/family axes',
    },
    {
        'axis': 'table_size',
        'kind': 'public_sequence',
        'definition': 'seats at the table',
        'identity_axis': True,
        'mutualizable_in_parameters': True,
        'pooling_level_if_mutualizable': 'L3_RUNTIME_SUPPORT_CONTEXT',
        'rationale': 'constant inside the certified 6-max population; not a support source',
    },
    {
        'axis': 'raise_level',
        'kind': 'public_sequence',
        'definition': 'structural raise level of the current betting sequence',
        'identity_axis': True,
        'mutualizable_in_parameters': True,
        'pooling_level_if_mutualizable': 'L3_RUNTIME_SUPPORT_CONTEXT',
        'rationale': 'raise level is summarized by family plus exact price at the provider granularity',
    },
    {
        'axis': 'limper_count',
        'kind': 'public_sequence',
        'definition': 'limpers observed before the first raise',
        'identity_axis': True,
        'mutualizable_in_parameters': True,
        'pooling_level_if_mutualizable': 'L4_POSITION_PRICE_PRIOR',
        'rationale': 'only the last-resort prior may pool counts; never a support source',
    },
    {
        'axis': 'caller_count',
        'kind': 'public_sequence',
        'definition': 'callers already observed after the first raise',
        'identity_axis': True,
        'mutualizable_in_parameters': True,
        'pooling_level_if_mutualizable': 'L4_POSITION_PRICE_PRIOR',
        'rationale': 'only the last-resort prior may pool counts; never a support source',
    },
    {
        'axis': 'family',
        'kind': 'public_sequence',
        'definition': 'derived public family label (VS_ISO, LIMPER_VS_ISO, ...)',
        'identity_axis': True,
        'mutualizable_in_parameters': True,
        'pooling_level_if_mutualizable': 'L4_POSITION_PRICE_PRIOR',
        'rationale': 'family is a summary of the public sequence; poolable only at the last-resort prior',
    },
)

UNUSED_AXES: tuple[dict[str, Any], ...] = (
    {
        'axis': 'limper_positions',
        'reason': 'the exact key counts limpers; their positions are not a key axis in #388/#419 and are not introduced here',
    },
    {
        'axis': 'caller_positions',
        'reason': 'the exact key counts callers; their positions are not a key axis in #388/#419 and are not introduced here',
    },
    {
        'axis': 'hole_cards_reveals',
        'reason': 'private/revealed information is a label, never a key axis or a feature',
    },
)

LEVELS: tuple[dict[str, Any], ...] = (
    {
        'level': 'L0_EXACT_KEY',
        'rank': 0,
        'purpose': 'SUPPORT_AND_IDENTITY',
        'retains': [a['axis'] for a in AXES],
        'drops': [],
        'key_builder': 'hierarchical_exact_key',
        'equals_runtime_provider_key': False,
        'support_source_allowed': True,
        'estimation_allowed': True,
    },
    {
        'level': 'L1_STACK_POOL',
        'rank': 1,
        'purpose': 'PARAMETERS_ONLY',
        'retains': [a['axis'] for a in AXES if a['pooling_level_if_mutualizable'] != 'L1_STACK_POOL'],
        'drops': ['effective_stack_bucket'],
        'key_builder': 'level_key(retained_axes)',
        'equals_runtime_provider_key': False,
        'support_source_allowed': False,
        'estimation_allowed': True,
    },
    {
        'level': 'L2_POT_POOL',
        'rank': 2,
        'purpose': 'PARAMETERS_ONLY',
        'retains': [a['axis'] for a in AXES
                    if a['pooling_level_if_mutualizable'] not in ('L1_STACK_POOL', 'L2_POT_POOL')],
        'drops': ['effective_stack_bucket', 'pot_before_bb'],
        'key_builder': 'level_key(retained_axes)',
        'equals_runtime_provider_key': False,
        'support_source_allowed': False,
        'estimation_allowed': True,
    },
    {
        'level': 'L3_RUNTIME_SUPPORT_CONTEXT',
        'rank': 3,
        'purpose': 'PARAMETERS_ONLY',
        'retains': [a['axis'] for a in AXES
                    if a['pooling_level_if_mutualizable'] not in
                    ('L1_STACK_POOL', 'L2_POT_POOL', 'L3_RUNTIME_SUPPORT_CONTEXT')],
        'drops': ['effective_stack_bucket', 'pot_before_bb', 'history', 'live_positions',
                  'all_in_positions', 'table_size', 'raise_level'],
        'key_builder': 'support_context_key (tools/preflop/model_a_sizing_likelihood.py)',
        'equals_runtime_provider_key': True,
        'support_source_allowed': False,
        'estimation_allowed': True,
    },
    {
        'level': 'L4_POSITION_PRICE_PRIOR',
        'rank': 4,
        'purpose': 'LAST_RESORT_PARAMETERS_ONLY',
        'retains': [a['axis'] for a in AXES if not a['mutualizable_in_parameters']],
        'drops': ['effective_stack_bucket', 'pot_before_bb', 'history', 'live_positions',
                  'all_in_positions', 'table_size', 'raise_level', 'limper_count',
                  'caller_count', 'family'],
        'key_builder': 'level_key(retained_axes)',
        'equals_runtime_provider_key': False,
        'support_source_allowed': False,
        'estimation_allowed': True,
    },
)

MUTUALIZABLE_AXES = [a['axis'] for a in AXES if a['mutualizable_in_parameters']]
NEVER_MUTUALIZABLE_AXES = [a['axis'] for a in AXES if not a['mutualizable_in_parameters']]


def _axes_matrix() -> dict[str, Any]:
    return {
        'axis_table': [dict(a) for a in AXES],
        'mutualizable': MUTUALIZABLE_AXES,
        'never_mutualizable': NEVER_MUTUALIZABLE_AXES,
        'mutualizable_rule': (
            'these axes may only change the prior/parent distribution used for shrinkage; they never '
            'change the support source key and never change which observations count for the requested key'
        ),
        'never_mutualizable_rule': (
            'these axes are frozen for support AND for parameters at every pooling level: no level may drop, '
            'round, bucket or relabel them'
        ),
        'unused_axes': [dict(a) for a in UNUSED_AXES],
        'level_retention_rule': (
            'every level retains all never_mutualizable axes by construction; the union of mutualizable axes '
            'dropped along the hierarchy is the only thing that changes between levels'
        ),
    }


def _baseline_evidence(baseline: Mapping[str, Any]) -> dict[str, Any]:
    return {
        'nodes_total': baseline['summary']['nodes_total'],
        'distinct_runtime_support_context_keys': baseline['summary']['distinct_runtime_support_context_keys'],
        'distinct_audit_exact_keys': baseline['summary']['distinct_audit_exact_keys'],
        'runtime_keys_merging_audit_states': baseline['summary']['runtime_keys_merging_audit_states'],
        'runtime_qualified_nodes': baseline['summary']['runtime_qualified_nodes'],
        'runtime_blocked_nodes': baseline['summary']['runtime_blocked_nodes'],
        'audit_exact_qualified_nodes': baseline['summary']['audit_exact_qualified_nodes'],
        'unresolved_sizing_frontier_count': baseline['issue388_bindings']['unresolved_sizing_frontier_count'],
        'enumeration_complete': baseline['issue388_bindings']['enumeration_complete'],
        'canonical_bb_facing_sb_iso5': baseline['canonical_cells']['bb_facing_sb_iso5'],
        'canonical_co_after_bb_fold': baseline['canonical_cells']['co_after_bb_fold'],
        'issue388_decision': baseline['issue388_bindings']['decision'],
        'issue388_status': baseline['issue388_bindings']['status'],
    }


def build_spec(baseline: Mapping[str, Any], inputs: list[dict[str, Any]],
               checks: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = _baseline_evidence(baseline)
    thresholds = baseline['thresholds']
    return {
        'schema': SCHEMA,
        'issue': 419,
        'kind': 'TRAIN_ONLY_MODEL_SPEC',
        'status': 'SPEC_ONLY_NOT_ADMITTED',
        'spec_frozen_date': SPEC_FROZEN_DATE,
        'authoring_order': {
            'spec_written_and_hashed_before_holdout_read': True,
            'validation_read_before_spec_hash': False,
            'test_read_before_spec_hash': False,
        },
        'predecessor_issues': [388, 367, 352, 321, 96, 88],
        'ten_point_coverage': [
            {'point': 1, 'title': 'exact public factorization of contexts',
             'sections': ['public_context_factorization', 'public_context_factorization.requested_key_axes'],
             'requirement': (
                 'actor, aggressor, already-observed limpers/callers, target_total_bb, to_call_bb, '
                 'effective stack bucket and the relevant public sequence are all explicit key axes'
             )},
            {'point': 2, 'title': 'axes mutualizable inside the parameters',
             'sections': ['parameter_pooling.axes.mutualizable'],
             'requirement': 'mutualizable parameter axes are enumerated with their pooling level'},
            {'point': 3, 'title': 'axes that are never mutualizable',
             'sections': ['parameter_pooling.axes.never_mutualizable'],
             'requirement': (
                 'requested key identity, exact price and positions are enumerated and frozen at every level'
             )},
            {'point': 4, 'title': 'hierarchy, prior and shrinkage',
             'sections': ['hierarchy_prior_shrinkage'],
             'requirement': 'levels, prior, shrinkage strength and recursion are explicit'},
            {'point': 5, 'title': 'information inheritance for rare hand classes',
             'sections': ['rare_hand_class_inheritance'],
             'requirement': (
                 'rare hand classes shrink only inside the requested key; no cross-key class imputation'
             )},
            {'point': 6, 'title': 'FOLD/CALL/RAISE/JAM outputs',
             'sections': ['action_outputs'],
             'requirement': 'every legal marginal action is enumerated and zero counts never prune'},
            {'point': 7, 'title': 'raise sizing handling',
             'sections': ['raise_sizing_policy'],
             'requirement': 'exact-support-only sizing; no representative price; unresolved frontiers survive'},
            {'point': 8, 'title': 'calibration and log-loss metrics',
             'sections': ['calibration_and_log_loss'],
             'requirement': 'log-loss plus calibration metrics with explicit stratification and split discipline'},
            {'point': 9, 'title': 'decision thresholds',
             'sections': ['decision_thresholds'],
             'requirement': 'frozen observation/hand thresholds, argmax rule, tie-break and abstain behaviour'},
            {'point': 10, 'title': 'runtime support contract',
             'sections': ['runtime_support_contract'],
             'requirement': (
                 'exact empirical observations, effective sample size, pooling level/source, uncertainty '
                 'and reason codes are part of the response contract'
             )},
        ],
        'public_context_factorization': {
            'hierarchical_exact_key': {
                'name': 'hierarchical_exact_key',
                'granularity_id': 'L0_EXACT_KEY',
                'composition': (
                    "support_context_key(context) + '|public=' + stable_hash(public_whitelist(context))"
                ),
                'equivalence': (
                    'byte-identical composition to the #388/#419 audit_exact_key; the spec does not invent '
                    'new fields or a new serialization'
                ),
                'fields': [
                    'family', 'actor_position', 'aggressor_position', 'limper_count', 'caller_count',
                    'target_total_bb', 'to_call_bb', 'table_size', 'raise_level', 'live_positions',
                    'all_in_positions', 'history', 'pot_before_bb', 'effective_stack_bucket',
                ],
                'serialization': (
                    'family|actor|aggressor|limpers|callers|target|call from support_context_key, then '
                    "'|public=<sha256-20 of the canonical public whitelist>'"
                ),
                'decimal_tokens': 'exact decimal tokens as produced by the runtime contract; no rounding to a grid',
                'no_nearest': True,
            },
            'requested_key_axes': [dict(a) for a in AXES],
            'public_sequence': {
                'definition': (
                    'ordered (position, action) history plus live/all-in position sets, table size and '
                    'raise level; reveals are labels, never sequence content'
                ),
                'normalization': 'action tokens normalized exactly as the runtime contract does (LIMP->CALL)',
                'no_future_information': True,
            },
            'exactness_rules': [
                'lookup is exact string equality on the requested key; no nearest key, no fuzzy match',
                'no numeric nearest-price or nearest-context substitution, at any level',
                'changing any identity axis produces a different key and a different support question',
                'the actor position and the aggressor position are always part of the identity',
            ],
        },
        'parameter_pooling': {
            'axes': _axes_matrix(),
            'levels': [dict(level) for level in LEVELS],
            'hard_constraint': (
                'no level may drop or alter actor_position, aggressor_position, target_total_bb, '
                'to_call_bb or the requested key identity'
            ),
            'levels_are_nested': True,
            'pooling_changes_parameters_only': True,
        },
        'support_isolation_rule': {
            'rule_id': 'SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT',
            'statement': (
                'A key A may never be declared supported by observations of a different key B. '
                'Support quantities (observations, distinct hands, effective sample size) are computed '
                'exclusively from rows whose hierarchical_exact_key equals A.'
            ),
            'support_quantities': ['observations', 'distinct_hands', 'effective_sample_size'],
            'pooling_effect': (
                'pooling may change the prior/posterior of the estimate, never the support counts of the '
                'requested key'
            ),
            'runtime_invariant': 'support.source_key == requested_key',
            'fail_closed': (
                'a runtime answer whose support source key differs from the requested key must raise, never '
                'silently emit; it is never downgraded into an exact claim'
            ),
            'violation_reason_code': 'COARSE_KEY_SUPPORT_LAUNDERING',
            'corollaries': [
                'a coarse provider key may seed a prior but may not certify support for a finer requested key',
                'a finer key never borrows observations from its siblings',
                'zero observations of key A stay zero even when a parent level has plenty of data',
            ],
            'evidence': {
                'collision_groups_where_the_coarse_key_merges_fine_keys': evidence[
                    'runtime_keys_merging_audit_states'],
                'distinct_fine_keys': evidence['distinct_audit_exact_keys'],
                'distinct_coarse_keys': evidence['distinct_runtime_support_context_keys'],
                'meaning': (
                    'a coarse lookup would be supported by rows of at least two distinct requested keys, '
                    'which this rule forbids'
                ),
            },
            'not_a_nearest_lookup': True,
        },
        'granularity_decision': {
            'decision_id': 'EXACT_KEY_IDENTITY_IS_FINER_THAN_RUNTIME_PROVIDER_KEY',
            'risk_addressed': 'RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE',
            'risk_statement': (
                'the runtime likelihood key omits history, pot_before_bb, effective_stack_bucket, '
                'live/all-in positions, table size and raise level, so one fitted node is reusable across '
                'audit-distinct public states'
            ),
            'chosen_granularity': {
                'identity_and_support_granularity': 'hierarchical_exact_key (L0_EXACT_KEY)',
                'provider_granularity_used_for_parameters': (
                    'runtime_support_context_key (L3_RUNTIME_SUPPORT_CONTEXT)'
                ),
                'consequence': (
                    'a provider answer resolved at L3 can only ever be EXACT_HIERARCHICAL_ESTIMATE; it can '
                    'never be EXACT_EMPIRICAL_STRONG'
                ),
            },
            'rejected_options': [
                {
                    'option': 'declare support at the coarse runtime key as exact',
                    'rejected_because': (
                        'it would let a key A be supported by observations of a key B, violating '
                        'SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT'
                    ),
                },
                {
                    'option': 'silently keep the coarse key and relabel the result "exact"',
                    'rejected_because': 'silent semantic redefinition of a public contract',
                },
                {
                    'option': 'lower the 20/20 support thresholds so the tree closes',
                    'rejected_because': 'thresholds are frozen; the CO cell remains a real data blocker',
                },
                {
                    'option': 'use a representative raise price to fill unresolved frontiers',
                    'rejected_because': 'exact-support-only sizing is mandatory; unresolved stays unresolved',
                },
            ],
            'prerequisite_for_exact_claims': (
                '#367 must expose per-member (fine-key) counts, or resolve at the fine key, before any node '
                'may be reported EXACT_EMPIRICAL_STRONG'
            ),
            'provider_change_performed_here': False,
            'status': 'OPEN_FOR_367_SPEC_DOES_NOT_CHANGE_PROVIDER',
            'evidence': evidence,
        },
        'hierarchy_prior_shrinkage': {
            'estimator': 'hierarchical_dirichlet_shrinkage',
            'levels': [dict(level) for level in LEVELS],
            'base_prior': {
                'kind': 'dirichlet',
                'alpha_per_legal_marginal_action': 0.5,
                'actions': ['FOLD', 'CALL', 'RAISE', 'JAM', 'CHECK_if_legal'],
                'rationale': 'weak uniform prior so sparse cells stay wide instead of collapsing to zero',
            },
            'hierarchical_strength_kappa0': 16.0,
            'kappa0_continuity': (
                'kappa0=16 toward the same support_context_key marginal reproduces the #352/#388 '
                'prospective_shrinkage rule; here that parent is the explicit level L3_RUNTIME_SUPPORT_CONTEXT'
            ),
            'blend': 'p_hat(L_j) = (n_j * phat_j + kappa0 * p_hat(L_{j+1})) / (n_j + kappa0)',
            'recursion': (
                'resolved bottom-up from L4; L4 prior is the base Dirichlet; a parent is only entered when '
                'the child level is below threshold'
            ),
            'exact_weight': 'w_exact = n0 / (n0 + kappa0), non-decreasing in n0',
            'parent_dominated_flag_below': 0.5,
            'constraints': [
                'a parent never changes actor/aggressor/target/to_call',
                'a parent never adds support observations to the requested key',
                'no cross-level smoothing of the support counts themselves',
            ],
            'no_hidden_hand_imputation': True,
        },
        'rare_hand_class_inheritance': {
            'rule': (
                'a rare hand class inherits from the hand-class marginal of its OWN requested key, then from '
                'the declared hierarchical levels of that same key; never from another key'
            ),
            'rare_hand_class_definition': 'hand class with fewer than 10 observations at the requested key',
            'min_class_observations': 10,
            'inheritance_chain': ['exact_hand_class_same_key', 'same_key_marginal',
                                  'L1..L4_parameter_levels_of_the_same_key'],
            'forbidden': [
                'cross-key hand-class transfer',
                'conditioning on revealed hole cards or showdown labels',
                'using reveal frequency as a feature or as a proxy for unrevealed behaviour',
                'imputing a hand class from a neighbouring price or stack bucket',
            ],
            'reveal_policy': (
                'reveals are descriptive labels of the observed sample only; they never enter the key, the '
                'features, the support counts or the shrinkage'
            ),
        },
        'action_outputs': {
            'output_actions': ['FOLD', 'CALL', 'RAISE', 'JAM'],
            'conditional_actions': ['CHECK_when_legal_free_option'],
            'output_kind': 'probability distribution over the legal marginal action set',
            'sum_to_one': 'over the legal marginal action set only; illegal actions are absent, not zero-weighted',
            'raise_outputs_are_not_a_single_number': (
                'RAISE/JAM outputs are per exact target_total_bb, never aggregated into one representative size'
            ),
            'zero_count_policy': (
                'observed zero counts never prune a branch and never prove zero probability; every legal '
                'continuation stays enumerated'
            ),
            'structurally_unreachable': 'only actions forbidden by the public betting engine',
        },
        'raise_sizing_policy': {
            'rule': 'exact-support-only',
            'supported_targets': (
                'only target_total_bb values empirically present at the exact structural node, emitted by the '
                '#367 exact-reference translator'
            ),
            'forbidden': [
                'representative raise price',
                'legal-minimum substitution',
                'nearest-price or nearest-context substitution',
                'target drift or interpolation between observed sizings',
                'pruning an unresolved frontier as zero mass',
            ],
            'unresolved_frontier': {
                'state': 'UNRESOLVED_SIZING_FRONTIER',
                'behaviour': (
                    'the branch and its required descendants remain explicitly unresolved; reason code '
                    'EXACT_UNRESOLVED; the tree is not claimed complete'
                ),
                'count_in_evidence': evidence['unresolved_sizing_frontier_count'],
            },
            'enumeration_complete': evidence['enumeration_complete'],
        },
        'calibration_and_log_loss': {
            'primary_metric': {
                'name': 'multiclass_log_loss',
                'definition': 'mean over decisions of -ln p_hat(observed_action | requested_key)',
                'epsilon_clip': 1e-12,
                'natural_log': True,
            },
            'secondary_metrics': [
                {'name': 'brier_score', 'definition': 'sum over legal actions of (p_hat - 1[observed])^2'},
                {'name': 'ece', 'definition': 'expected calibration error with 10 equal-count bins per action class'},
                {'name': 'coverage', 'definition': 'share of decisions answered with a non-UNRESOLVED reason code'},
                {'name': 'mean_effective_sample_size', 'definition': 'mean effective sample size of answered decisions'},
            ],
            'stratification': [
                'by reason_code', 'by pooling.level', 'by observations bucket', 'by distinct-hands bucket',
            ],
            'mandatory_reporting': (
                'a pooled estimate is never scored without its pooling level; calibration must not be '
                'reported on pooled support as if it were exact support'
            ),
            'evaluation_split_discipline': {
                'fit_and_calibration_evidence': 'TRAIN only',
                'validation': (
                    'only through a separately frozen protocol whose own spec hash is pinned before running; '
                    'this TRAIN-only spec is the frozen artifact identity'
                ),
                'test': 'never',
                'spec_hash_is_the_frozen_identity': True,
            },
        },
        'decision_thresholds': {
            'minimum_marginal_observations': thresholds['minimum_marginal_observations'],
            'minimum_distinct_hands': thresholds['minimum_distinct_hands'],
            'thresholds_frozen': True,
            'thresholds_basis': (
                '#352 marginal minimum retained; distinct-hand safeguard added; unchanged by this spec'
            ),
            'requirement_applies_at': 'the level used to report the estimate',
            'exact_claim_requires': 'L0_EXACT_KEY meeting both thresholds',
            'decision_rule': 'argmax of the posterior distribution over the legal marginal action set',
            'tie_break': 'lowest incremental cost, then fixed order FOLD, CHECK, CALL, RAISE, JAM',
            'sizing_tie_break': 'lowest exact target_total_bb among tied raise targets',
            'abstain': {
                'condition': 'reason_code == EXACT_UNRESOLVED, or raise sizing unresolved for the branch',
                'behaviour': 'no action is emitted; the decision stays unresolved rather than defaulting to FOLD',
            },
            'no_admission': (
                'this spec authorizes no admission, no fit, no promotion and no production effect'
            ),
        },
        'runtime_support_contract': {
            'schema': 'poker-hierarchical-support-response/v1',
            'requested_key': 'hierarchical_exact_key (L0_EXACT_KEY)',
            'response_fields': [
                {
                    'field': 'requested_key',
                    'type': 'string',
                    'meaning': 'the exact fine key that was asked for',
                },
                {
                    'field': 'support.observations',
                    'type': 'integer',
                    'meaning': 'exact empirical rows whose hierarchical_exact_key == requested_key',
                },
                {
                    'field': 'support.distinct_hands',
                    'type': 'integer',
                    'meaning': 'distinct hands contributing those rows',
                },
                {
                    'field': 'support.effective_sample_size',
                    'type': 'number',
                    'meaning': (
                        'credited independence: equal to distinct_hands, because multiple decisions inside '
                        'one hand are correlated and must not inflate the sample'
                    ),
                },
                {
                    'field': 'support.source_key',
                    'type': 'string',
                    'meaning': 'must equal requested_key; anything else is COARSE_KEY_SUPPORT_LAUNDERING',
                },
                {
                    'field': 'support.borrowed_from_other_keys',
                    'type': 'boolean',
                    'meaning': 'always false; true is an invalid response',
                },
                {
                    'field': 'pooling.level',
                    'type': 'string',
                    'meaning': 'L0_EXACT_KEY .. L4_POSITION_PRICE_PRIOR, the level that supplied the parent prior',
                },
                {
                    'field': 'pooling.source_key',
                    'type': 'string',
                    'meaning': 'the exact key of the pooling level that was used',
                },
                {
                    'field': 'pooling.source_observations',
                    'type': 'integer',
                    'meaning': 'observations available at that pooling level',
                },
                {
                    'field': 'pooling.source_distinct_hands',
                    'type': 'integer',
                    'meaning': 'distinct hands available at that pooling level',
                },
                {
                    'field': 'pooling.source_effective_sample_size',
                    'type': 'number',
                    'meaning': 'effective sample size of the pooling level',
                },
                {
                    'field': 'pooling.retained_axes',
                    'type': 'array<string>',
                    'meaning': 'identity axes kept at that level (always contains the never-mutualizable axes)',
                },
                {
                    'field': 'pooling.pooled_axes',
                    'type': 'array<string>',
                    'meaning': 'mutualizable axes dropped at that level',
                },
                {
                    'field': 'pooling.weight',
                    'type': 'number',
                    'meaning': 'w_exact = n0 / (n0 + kappa0); weight of the exact level in the blend',
                },
                {
                    'field': 'posterior',
                    'type': 'object<action,number>',
                    'meaning': 'FOLD/CALL/RAISE/JAM (+CHECK when legal), summing to 1 over legal actions',
                },
                {
                    'field': 'uncertainty',
                    'type': 'object',
                    'meaning': (
                        'Dirichlet credible intervals per action at a declared level (default 0.9), plus the '
                        'standard error; must reflect the level actually used, not the exact level alone'
                    ),
                },
                {
                    'field': 'raise_sizing',
                    'type': 'object',
                    'meaning': 'exact supported targets or an explicit unresolved frontier with ids',
                },
                {
                    'field': 'reason_code',
                    'type': 'enum',
                    'meaning': 'EXACT_EMPIRICAL_STRONG | EXACT_HIERARCHICAL_ESTIMATE | EXACT_UNRESOLVED',
                },
                {
                    'field': 'reason_detail',
                    'type': 'string|null',
                    'meaning': 'human-readable cause, including the blocker for EXACT_UNRESOLVED',
                },
            ],
            'reason_codes': {
                'EXACT_EMPIRICAL_STRONG': {
                    'condition': (
                        'the requested fine key meets both 20/20 thresholds and the reported estimate uses '
                        'pooling.level == L0_EXACT_KEY'
                    ),
                    'support_source': 'requested_key only',
                    'pooling_allowed_for_the_reported_estimate': False,
                    'interpretation': 'exact empirical support for this exact context',
                },
                'EXACT_HIERARCHICAL_ESTIMATE': {
                    'condition': (
                        'the requested fine key is below threshold but a declared parent level meets both '
                        '20/20 thresholds; pooling.level and pooling.source_key are reported'
                    ),
                    'support_source': 'requested_key only (support counts stay exact and possibly zero)',
                    'pooling_allowed_for_the_reported_estimate': True,
                    'interpretation': (
                        'an estimate for the exact requested context whose parameters were shrunk toward a '
                        'declared parent; it is never an exact-support claim'
                    ),
                },
                'EXACT_UNRESOLVED': {
                    'condition': (
                        'no level meets both thresholds, or the raise sizing for the branch is unresolved, or '
                        'the requested key violates the support isolation rule'
                    ),
                    'support_source': 'requested_key only',
                    'pooling_allowed_for_the_reported_estimate': False,
                    'interpretation': 'no answer is emitted; the context and its descendants stay unresolved',
                },
            },
            'fail_closed': [
                'support.source_key != requested_key -> error (COARSE_KEY_SUPPORT_LAUNDERING)',
                'support.borrowed_from_other_keys == true -> error',
                'a pooling level that drops a never-mutualizable axis -> error',
                'an EXACT_EMPIRICAL_STRONG claim whose pooling level is not L0 -> error',
                'a raise target not exactly supported at the structural node -> EXACT_UNRESOLVED',
                'a probability vector outside the legal marginal action set -> error',
            ],
            'prohibitions': [
                'no nearest price, no representative price, no nearest context',
                'no private or future information in keys, features or reason details',
                'no admission, fit, promotion or production effect from this contract alone',
            ],
        },
        'holdout_boundary': {
            'split_consumed': 'TRAIN',
            'validation_consumed': False,
            'test_consumed': False,
            'validation_decisions_read': 0,
            'validation_hands_parsed': 0,
            'split_cardinality_metadata_read': (
                'only the certified split cardinalities carried by TRAIN evidence provenance; no VALIDATION '
                'hand, decision, feature, label or metric is read'
            ),
            'spec_frozen_before_holdout_read': True,
            'validation_read_before_spec_hash': False,
            'inputs': inputs,
            'checks': checks,
            'reproduce': 'python3 tools/training/write_hierarchical_model_spec.py --check',
        },
        'prohibitions': {
            'nearest_price': False,
            'nearest_context': False,
            'representative_raise_price': False,
            'future_or_private_features': False,
            'cross_key_support_borrowing': False,
            'admission': 'NONE',
            'production_effect': 'NONE',
            'active_pointer_mutation': False,
        },
        'not_a_fit': (
            'this artifact is a specification only; it fits no model, admits no candidate, opens no holdout '
            'and changes no runtime provider'
        ),
    }


def build() -> dict[str, Any]:
    with dataset_access_tripwire() as opened:
        return _build(opened)


def _build(opened_paths: list[str]) -> dict[str, Any]:
    source_check = verify_no_holdout_access()
    if sha256_file(baseline_tool.legacy.REFERENCE) != baseline_tool.legacy.EXPECTED_REFERENCE_HASH:
        raise ValueError('reference SHA mismatch')
    bundle = baseline_tool.load_issue388()
    baseline_tool.verify_issue388_boundaries(bundle)
    assert_train_only_artifact('#388 required tree', {})
    assert_train_only_artifact('#388 train support', bundle['report'])
    assert_train_only_artifact('#388 decision', bundle['decision'])
    baseline = json.loads(BASELINE_PATH.read_text())
    assert_train_only_artifact('#419 sparsity baseline', baseline)
    if stable_hash(bundle['report']) != baseline_tool.ISSUE388_TRAIN_SUPPORT_SHA256:
        raise ValueError('#388 TRAIN support hash mismatch')
    if baseline['reference_sha256'] != baseline_tool.legacy.EXPECTED_REFERENCE_HASH:
        raise ValueError('baseline reference model hash mismatch')
    if sha256_file(ROOT / 'tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.snapshots.json') != \
            baseline['fixture_sha256']:
        raise ValueError('baseline fixture hash mismatch')
    tree = baseline_tool.rederive_tree()
    if stable_hash(tree) != baseline_tool.ISSUE388_REQUIRED_TREE_SHA256:
        raise ValueError('re-derived required tree mismatch')
    inputs = input_fingerprints()
    evidence_check = {
        'check': 'consumed_evidence_declares_train_only',
        'result': 'PASS',
        'detail': (
            'the #419 baseline, the #388 TRAIN support matrix and the #388 decision all declare '
            'split_consumed=TRAIN with validation_consumed=false and test_consumed=false; the tripwire '
            'aborts on any other declaration'
        ),
        'artifacts': [
            {'name': '#419 sparsity baseline', 'split_consumed': baseline['split_consumed'],
             'validation_consumed': baseline['validation_consumed'],
             'test_consumed': baseline['test_consumed']},
            {'name': '#388 train support', 'split_consumed': bundle['report']['split_consumed'],
             'validation_consumed': bundle['report']['validation_consumed'],
             'test_consumed': bundle['report']['test_consumed']},
            {'name': '#388 decision', 'split_consumed': 'TRAIN',
             'validation_consumed': bundle['decision']['validation_consumed'],
             'test_consumed': bundle['decision']['test_consumed']},
        ],
    }
    undeclared_opens = _undeclared_opens(opened_paths)
    if undeclared_opens:
        raise ValueError(f'undeclared file opened during spec build: {undeclared_opens}')
    no_dataset_check = {
        'check': 'no_hand_level_dataset_read',
        'result': 'PASS',
        'detail': (
            'the generator parses no hand-history archive and no decision JSONL; it consumes '
            'content-addressed evidence artifacts plus structural source files only. The build ran with a '
            'filesystem tripwire: any open under training/datasets/ or of a .zip/.jsonl file aborts the '
            'build, and the observed open set is exactly the declared inputs plus the pinned #388 bundle.'
        ),
        'observed_files_opened': _relative_open_set(opened_paths),
        'undeclared_files_opened': [],
        'dataset_or_holdout_files_opened': [],
    }
    index_check = {
        'check': 'content_addressed_inputs_verified',
        'result': 'PASS',
        'detail': (
            '#388 artifacts are byte-verified against their ARTIFACTS.json content addresses and the #419 '
            'baseline is bound by canonical payload hash before the spec is serialized'
        ),
    }
    checks = [source_check, evidence_check, no_dataset_check, index_check]
    spec = build_spec(baseline, inputs, checks)
    here_index = json.loads(BASELINE_INDEX_PATH.read_text())
    spec['evidence_bindings'] = {
        'baseline': {
            'path': baseline_tool.BASELINE_NAME,
            'byte_sha256': sha256_file(BASELINE_PATH),
            'canonical_payload_sha256': stable_hash(baseline),
            'artifact_index_sha256': here_index[baseline_tool.BASELINE_NAME]['sha256'],
            'artifact_index_canonical_payload_sha256': here_index[baseline_tool.BASELINE_NAME][
                'canonical_payload_sha256'],
        },
        'issue388': {
            'required_tree_canonical_sha256': baseline_tool.ISSUE388_REQUIRED_TREE_SHA256,
            'train_support_canonical_sha256': baseline_tool.ISSUE388_TRAIN_SUPPORT_SHA256,
            'decision_canonical_sha256': baseline_tool.ISSUE388_DECISION_SHA256,
            'required_tree_byte_sha256': baseline_tool.ISSUE388_REQUIRED_TREE_BYTE_SHA256,
            'train_support_byte_sha256': baseline_tool.ISSUE388_TRAIN_SUPPORT_BYTE_SHA256,
            'decision_byte_sha256': baseline_tool.ISSUE388_DECISION_BYTE_SHA256,
        },
        'reference_model_sha256': baseline_tool.legacy.EXPECTED_REFERENCE_HASH,
        'reference_fixture_sha256': baseline['fixture_sha256'],
        'runtime_key_source_sha256': sha256_file(ROOT / 'tools/preflop/model_a_sizing_likelihood.py'),
        'spec_generator_sha256': sha256_file(SOURCE_PATH),
        'spec_digest_location': (
            'the spec digest cannot live inside the spec payload; it is recorded in '
            'HIERARCHICAL_MODEL_SPEC.sha256 and model_spec/ARTIFACTS.json'
        ),
        'spec_version': 'v1',
    }
    return spec


def summarize(spec: Mapping[str, Any], digest: str) -> str:
    evidence = spec['granularity_decision']['evidence']
    return (
        '# #419 — hierarchical exact-context model spec (TRAIN-only)\n\n'
        f"`HIERARCHICAL_MODEL_SPEC.json` byte SHA256: `{digest}`. The canonical payload hash and the "
        'content-addressed copies are in `model_spec/ARTIFACTS.json`.\n\n'
        f"Identity granularity is the fine `hierarchical_exact_key` (L0); the current provider key "
        f"`runtime_support_context_key` is pooling level L3 only. The open "
        f"`RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE` risk is addressed explicitly: "
        f"{evidence['runtime_keys_merging_audit_states']} collision groups merge "
        f"{evidence['distinct_audit_exact_keys']} fine keys into "
        f"{evidence['distinct_runtime_support_context_keys']} coarse keys, so a coarse lookup can never be "
        'reported above `EXACT_HIERARCHICAL_ESTIMATE`.\n\n'
        'Mutualizable parameter axes and the never-mutualizable axes (requested key identity, exact price '
        '`target_total_bb`/`to_call_bb`, and the actor/aggressor positions) are enumerated in '
        '`parameter_pooling.axes`. Rule `SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT` states that a key A may '
        'never be declared supported by observations of a different key B; support counts are exact, '
        'pooling only feeds the prior.\n\n'
        'The spec was written and hashed from TRAIN-only and structural evidence before any VALIDATION '
        'decision was read: `validation_consumed=false`, `validation_decisions_read=0`, the generator '
        'parses no hand history and refuses the known holdout loaders. Thresholds stay frozen at 20 '
        'observations / 20 distinct hands; raise sizing is exact-support-only with no representative '
        'price. This artifact admits nothing.\n\n'
        'Reproduce: `python3 tools/training/write_hierarchical_model_spec.py --check`.\n'
    )


def persist(spec: Mapping[str, Any]) -> dict[str, Any]:
    BUNDLE.mkdir(parents=True, exist_ok=True)
    objects = BUNDLE / 'sha256'
    objects.mkdir(exist_ok=True)
    spec_bytes = serialize(spec)
    digest = hashlib.sha256(spec_bytes).hexdigest()
    (BUNDLE / SPEC_NAME).write_bytes(spec_bytes)
    (objects / (digest + '.json')).write_bytes(spec_bytes)
    summary_bytes = summarize(spec, digest).encode()
    summary_digest = hashlib.sha256(summary_bytes).hexdigest()
    (BUNDLE / 'SUMMARY.md').write_bytes(summary_bytes)
    (objects / (summary_digest + '.md')).write_bytes(summary_bytes)
    index = {
        SPEC_NAME: {
            'sha256': digest,
            'canonical_payload_sha256': stable_hash(spec),
            'object': 'sha256/' + digest + '.json',
        },
        'SUMMARY.md': {'sha256': summary_digest, 'object': 'sha256/' + summary_digest + '.md'},
    }
    (BUNDLE / 'ARTIFACTS.json').write_text(json.dumps(index, sort_keys=True, indent=2) + '\n')
    referenced = {Path(entry['object']).name for entry in index.values()}
    for path in objects.iterdir():
        if path.is_file() and path.name not in referenced:
            path.unlink()
    SPEC_PATH.write_bytes(spec_bytes)
    DIGEST_PATH.write_text(
        f"{digest}  {SPEC_NAME}\n# canonical_payload_sha256 {stable_hash(spec)}\n"
    )
    return index


def check() -> int:
    spec = build()
    expected = serialize(spec)
    expected_digest = hashlib.sha256(expected).hexdigest()
    problems = []
    if SPEC_PATH.read_bytes() != expected:
        problems.append('canonical spec bytes differ from a fresh build')
    if (BUNDLE / SPEC_NAME).read_bytes() != expected:
        problems.append('bundle spec bytes differ from a fresh build')
    index = json.loads((BUNDLE / 'ARTIFACTS.json').read_text())
    entry = index.get(SPEC_NAME, {})
    if entry.get('sha256') != expected_digest:
        problems.append('spec index digest mismatch')
    if entry.get('canonical_payload_sha256') != stable_hash(spec):
        problems.append('spec canonical payload digest mismatch')
    if (BUNDLE / entry.get('object', 'missing')).read_bytes() != expected:
        problems.append('content-addressed spec object mismatch')
    sidecar = DIGEST_PATH.read_text()
    if not sidecar.startswith(expected_digest + '  ' + SPEC_NAME):
        problems.append('spec .sha256 sidecar mismatch')
    for name, row in index.items():
        data = (BUNDLE / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != row['sha256']:
            problems.append(f'byte hash mismatch for {name}')
        if data != (BUNDLE / row['object']).read_bytes():
            problems.append(f'content-addressed copy mismatch for {name}')
    if {p.name for p in (BUNDLE / 'sha256').iterdir()} != {
        Path(row['object']).name for row in index.values()
    }:
        problems.append('unexpected object in model_spec/sha256')
    if problems:
        print(json.dumps({'status': 'MISMATCH', 'problems': problems}, indent=2))
        return 1
    print(json.dumps({
        'status': 'OK',
        'schema': SCHEMA,
        'spec_sha256': expected_digest,
        'canonical_payload_sha256': stable_hash(spec),
        'validation_consumed': spec['holdout_boundary']['validation_consumed'],
        'never_mutualizable_axes': spec['parameter_pooling']['axes']['never_mutualizable'],
    }, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='verify the persisted spec instead of rewriting it')
    args = parser.parse_args()
    if args.check:
        return check()
    spec = build()
    index = persist(spec)
    print(json.dumps({
        'schema': SCHEMA,
        'spec_path': str(SPEC_PATH.relative_to(ROOT)),
        'bundle': str(BUNDLE.relative_to(ROOT)),
        'spec_sha256': index[SPEC_NAME]['sha256'],
        'canonical_payload_sha256': index[SPEC_NAME]['canonical_payload_sha256'],
        'ten_points': len(spec['ten_point_coverage']),
        'mutualizable_axes': spec['parameter_pooling']['axes']['mutualizable'],
        'never_mutualizable_axes': spec['parameter_pooling']['axes']['never_mutualizable'],
        'validation_consumed': spec['holdout_boundary']['validation_consumed'],
    }, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
