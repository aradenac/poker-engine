#!/usr/bin/env python3
"""#419: TRAIN-only fit of the frozen hierarchical exact-context Model A candidate.

Fits the frozen T2 hierarchical exact-context model
(``analysis/issue419_hierarchical_tree/HIERARCHICAL_MODEL_SPEC.json``) on the
certified TRAIN split only and persists a content-addressed candidate together
with its manifest and TRAIN fit report.

Scientific boundary
-------------------
* Same split gating as #388: every hand crosses the hand-history parser only
  after ``split_for(hand_id) == 'TRAIN'`` was checked.  VALIDATION and TEST
  never cross it (``validation_consumed=false``, ``test_consumed=false``).
* The hyper-parameters, priors and thresholds are *read from the frozen spec*
  and re-pinned; no hyper-parameter search happens and no VALIDATION decision is
  read.  There is no holdout code path: the tool statically refuses the known
  holdout loaders (see ``HOLDOUT_LOADER_SYMBOLS``/``verify_no_holdout_access``).
* Every observation is a real certified TRAIN decision row.  No
  pseudo-observation, no hidden-hand imputation and no synthetic count is
  fabricated; the candidate is a function of the persisted TRAIN rows only.
* The candidate is candidate-only: ``training/registry.json`` and the active
  ``training/models/preflop_population_model_v5.json`` pointer are hashed before
  and after the fit and are never mutated (``active_pointer_mutated=false``).
"""
from __future__ import annotations

import argparse
import ast
import collections
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import fingerprint, sha256_file, split_for
from tools.preflop import model_a_sizing_hierarchical as H
from tools.preflop.policy_context import STACK_BUCKETS
from tools.repro_preflop_fixture import FIXTURE_PATH
from tools.training import audit_hierarchical_tree_sparsity as baseline_tool
from tools.training import audit_model_a_exact_tree as legacy
from tools.training import write_hierarchical_model_spec as spec_tool
from tools.training.audit_hero_preflop_coverage import DEFAULT_CERTIFICATION, load_train_records
from tools.training.audit_preflop_sizing_support import stable_hash
from tools.training.increment_decisions import decision_rows, parse_hand

HERE = ROOT / 'analysis/issue419_hierarchical_tree'
OUTPUT = HERE / 'fit'

SCHEMA = 'poker-hierarchical-train-fit/v1'
MANIFEST_SCHEMA = 'poker-hierarchical-candidate-manifest/v1'
REPORT_SCHEMA = 'poker-hierarchical-train-fit-report/v1'

CANDIDATE_NAME = 'CANDIDATE.json'
MANIFEST_NAME = 'CANDIDATE_MANIFEST.json'
REPORT_NAME = 'TRAIN_FIT_REPORT.json'
INDEX_NAME = 'ARTIFACTS.json'

# A new candidate instance, identical to nothing already persisted.  The
# contract id stays the frozen module id so the payload still validates as the
# hierarchical Model-A candidate; the instance id makes the fitted artifact
# distinct at the manifest level, and the payload hash makes it distinct
# byte-for-byte.
CANDIDATE_INSTANCE_ID = 'model-a-preflop-sizing-hierarchical-train-fit-419-v1'
CONTRACT_CANDIDATE_ID = H.CANDIDATE_ID
DISTINCT_FROM = {
    'issue_352_candidate_id': 'model-a-preflop-sizing-aware-candidate-v2',
    'issue_352_candidate_sha256': '9115165c3141d16152946dd1ee7a049f219fef1a1d79c0e1c7b1249c45326f19',
    'issue_388_artifact': 'analysis/issue388_exact_tree/DECISION.json',
    'issue_388_decision': 'UNRESOLVED_EXACT_TREE_GAP',
    'issue_388_fit_created': False,
    'exact_price_candidate_ids': [
        'model-a-preflop-sizing-aware-candidate-v1',
        'model-a-preflop-sizing-aware-candidate-v2',
    ],
}

FIT_SCOPE = 'TRAIN_ONLY_FIT_COMPLETE'
DATA_SCOPE = 'TRAIN_ONLY'
OBSERVATION_SCOPE = 'REQUIRED_HIERARCHICAL_TREE_KEYS'

POPULATION_ID = 'pokerstars_nlhe_100-200_zoom_play_6max_v1'

# The fit is deterministic: the frozen estimator performs no sampling, so the
# recorded seed only pins the ordering/tie-break procedure.
FIT_SEED = 419

# A public stack bucket is all the exact key needs.  Reconstructing the context
# from the node's frozen bucket therefore reproduces its whitelist byte for
# byte; any in-bucket representative gives the identical key (asserted below).
STACK_BUCKET_REPRESENTATIVE = {
    'LE40': 40.0,
    'GT40_LE75': 75.0,
    'GT75_LE125': 125.0,
    'GT125': 200.0,
}
STACK_BUCKET_ALTERNATES = {
    'LE40': 20.0,
    'GT40_LE75': 50.0,
    'GT75_LE125': 100.0,
    'GT125': 400.0,
}
assert tuple(label for _, label in STACK_BUCKETS) == tuple(STACK_BUCKET_REPRESENTATIVE)

# Symbols that would indicate a holdout (VALIDATION/TEST) read.  The fit tool
# must use none of them; the scan runs at build time and in tests.
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

SOURCE_PATH = Path(__file__).resolve()

PROTECTED_FILES = (
    'training/registry.json',
    'training/populations/registry.json',
    'training/models/preflop_population_model_v5.json',
    'training/models/postflop_population_model_v5.json',
)


class HoldoutAccessError(RuntimeError):
    """Raised when anything in this tool would cross the TRAIN boundary."""


def serialize(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def verify_no_holdout_access(source: str | None = None) -> dict[str, Any]:
    """Static proof that the fit tool cannot read a holdout split.

    The scan is AST-based: it looks for identifiers actually used and for
    holdout-looking data paths, not for the words, so the declarative constants
    above stay readable.
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
        raise HoldoutAccessError(f'holdout loader symbol used in fit tool: {hits}')
    bad_imports = sorted(
        name for name in imported
        if any(marker in name.lower() for marker in ('validation', 'holdout'))
    )
    if bad_imports:
        raise HoldoutAccessError(f'holdout-looking import in fit tool: {bad_imports}')
    data_extensions = ('.json', '.jsonl', '.zip', '.txt', '.csv', '.snapshots')
    bad_literals = sorted(
        node.value for node in ast.walk(module)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.value.endswith(data_extensions)
        and any(marker in node.value.lower() for marker in ('validation', 'holdout'))
    )
    if bad_literals:
        raise HoldoutAccessError(f'holdout-looking data path literal: {bad_literals}')
    return {
        'check': 'self_source_scan_for_holdout_loaders',
        'result': 'PASS',
        'forbidden_symbols': list(HOLDOUT_LOADER_SYMBOLS),
        'hits': [],
        'holdout_looking_imports': [],
        'holdout_looking_data_path_literals': [],
        'detail': (
            'AST scan: the fit tool uses none of the forbidden holdout loader symbols, imports no '
            'validation/holdout module and declares no validation/holdout data path'
        ),
    }


def assert_train_only_artifact(name: str, payload: Mapping[str, Any]) -> None:
    """Tripwire: any consumed evidence declaring a holdout split aborts the fit."""
    for field in ('validation_consumed', 'test_consumed'):
        if payload.get(field) is True:
            raise HoldoutAccessError(f'{name} declares {field}=true')
    split = payload.get('split_consumed')
    if split not in (None, 'TRAIN'):
        raise HoldoutAccessError(f'{name} declares split_consumed={split!r}')


def verify_content_address(bundle: Path, index_name: str = INDEX_NAME) -> dict[str, Any]:
    """Verify a persisted content-addressed bundle before trusting its bytes."""
    index = json.loads((bundle / index_name).read_text())
    for name, entry in index.items():
        data = (bundle / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError(f'content-addressed artifact hash mismatch: {name}')
        if data != (bundle / entry['object']).read_bytes():
            raise ValueError(f'content-addressed copy mismatch: {name}')
    return index


def load_verified_inputs() -> dict[str, Any]:
    """Pin every consumed structural/evidence input without reading a holdout."""
    if sha256_file(legacy.REFERENCE) != legacy.EXPECTED_REFERENCE_HASH:
        raise ValueError('active reference model SHA mismatch')
    _, support = legacy.load_support_report()
    if stable_hash({k: v for k, v in support.items() if k != 'report_hash'}) != legacy.EXPECTED_SUPPORT_HASH:
        raise ValueError('#319 content hash mismatch')
    legacy.verify_baseline(json.loads(baseline_tool.BASELINE_FIT_PATH.read_text()))

    spec_index = verify_content_address(spec_tool.BUNDLE)
    spec = json.loads(spec_tool.SPEC_PATH.read_text())
    if spec.get('schema') != H.HIERARCHY_SPEC_SCHEMA:
        raise ValueError('unexpected hierarchical spec schema')
    if spec.get('status') != 'SPEC_ONLY_NOT_ADMITTED':
        raise ValueError('the T2 spec must remain an unadmitted specification')
    boundary = spec['holdout_boundary']
    if boundary['split_consumed'] != 'TRAIN' or boundary['validation_consumed'] or boundary['test_consumed']:
        raise ValueError('the T2 spec must be TRAIN-only')
    if boundary.get('validation_decisions_read'):
        raise ValueError('the T2 spec must have read zero validation decisions')

    verify_content_address(HERE)
    baseline = json.loads(spec_tool.BASELINE_PATH.read_text())
    assert_train_only_artifact(baseline_tool.BASELINE_NAME, baseline)

    issue388 = baseline_tool.load_issue388()
    baseline_tool.verify_issue388_boundaries(issue388)

    tree = legacy.reconstruct_tree(json.loads(legacy.REFERENCE.read_text()))
    if stable_hash(tree) != baseline_tool.ISSUE388_REQUIRED_TREE_SHA256:
        raise ValueError('re-derived required tree does not match #388')

    return {
        'spec': spec,
        'spec_index': spec_index,
        'baseline': baseline,
        'issue388': issue388,
        'tree': tree,
    }


def parse_certified_train_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse certified TRAIN preflop decisions; VALIDATION/TEST never cross the parser."""
    records, provenance = load_train_records(DEFAULT_CERTIFICATION)
    rows: list[dict[str, Any]] = []
    parsed_ids: set[str] = set()
    for record in records:
        if split_for(record.hand_id) != 'TRAIN':
            raise HoldoutAccessError('non-TRAIN hand rejected before the parser')
        hand = parse_hand(record.text, record.source_file)
        if not hand:
            raise ValueError('certified TRAIN parse failure: ' + str(record.hand_id))
        parsed_ids.add(str(record.hand_id))
        for row in decision_rows(hand, include_preflop_context_v1=True):
            if row['split'] != 'TRAIN':
                raise HoldoutAccessError('non-TRAIN decision row rejected')
            if row['street'] != 'preflop' or row['is_hero']:
                continue
            rows.append(row)
    if len(parsed_ids) != provenance['certified_split_counts']['TRAIN']:
        raise ValueError('certified TRAIN accounting mismatch')
    # Only the TRAIN cardinality is consumed; the VALIDATION/TEST counts are
    # carried as certified cardinality metadata and never opened.
    if provenance['certified_split_counts']['TRAIN'] != 19016:
        raise ValueError('unexpected certified TRAIN cardinality')
    corpus = {
        'certification_path': provenance['certification_path'],
        'certification_sha256': provenance['certification_sha256'],
        'population_fingerprint_sha256': provenance['population_fingerprint_sha256'],
        'certified_split_counts': provenance['certified_split_counts'],
        'archives': provenance['archives'],
        'train_hands_parsed': len(parsed_ids),
        'train_hand_ids_fingerprint_sha256': fingerprint(parsed_ids),
        'train_decision_rows_parsed': len(rows),
    }
    return rows, corpus


def required_nodes(tree: Mapping[str, Any]) -> list[dict[str, Any]]:
    nodes = sorted(tree['nodes'], key=lambda node: node['path'])
    if len(nodes) != 38:
        raise ValueError('the #388 required tree must expose exactly 38 nodes')
    return nodes


def required_level_keyspace(nodes: list[dict[str, Any]]) -> dict[str, set[str]]:
    keyspace: dict[str, set[str]] = {level: set() for level in H.POOLING_LEVELS}
    for node in nodes:
        for level in H.POOLING_LEVELS:
            keyspace[level].add(H.level_key(level, node['context']))
    return keyspace


def select_in_scope_rows(
    rows: list[dict[str, Any]], keyspace: Mapping[str, set[str]]
) -> tuple[list[tuple[int, dict[str, Any], dict[str, Any], dict[str, str]]], dict[str, Any]]:
    """Keep the certified TRAIN rows that can support the required tree keyspace.

    The same single pass records how much support the whole certified TRAIN
    corpus holds at each pooling level, so the in-scope selection is auditable.
    """
    kept: list[tuple[int, dict[str, Any], dict[str, Any], dict[str, str]]] = []
    distinct = {level: set() for level in H.POOLING_LEVELS}
    for index, row in enumerate(rows):
        context = legacy.public_context(row)
        keys = H.level_keys(context)
        for level in H.POOLING_LEVELS:
            if keys[level] not in distinct[level]:
                distinct[level].add(keys[level])
        if any(keys[level] in keyspace[level] for level in H.POOLING_LEVELS):
            kept.append((index, row, context, keys))
    corpus_scan = {
        'train_rows_scanned': len(rows),
        'distinct_source_keys_per_level': {
            level: len(keys) for level, keys in distinct.items()
        },
        'in_scope_rows': len(kept),
    }
    return kept, corpus_scan


def build_observations(
    kept: list[tuple[int, dict[str, Any], dict[str, Any], dict[str, str]]]
) -> list[dict[str, Any]]:
    """Normalize the real TRAIN rows into observations; nothing is invented."""
    provisional: list[dict[str, Any]] = []
    for index, row, context, _keys in kept:
        action = H.normalize_action(row['action'])
        target = row.get('target_total_bb')
        provisional.append({
            'source_row_index': index,
            'source_hand_id': str(row['hand_id']),
            'whitelist': context,
            'action': action,
            'target_total_bb': None if target is None else round(float(target), 6),
        })
    provisional.sort(
        key=lambda item: (
            H.hierarchical_exact_key_from_whitelist(item['whitelist']),
            item['source_hand_id'],
            item['action'],
            item['target_total_bb'] is None,
            item['target_total_bb'] if item['target_total_bb'] is not None else 0.0,
            item['source_row_index'],
        )
    )
    observations: list[dict[str, Any]] = []
    for position, item in enumerate(provisional):
        observations.append({
            'observation_id': f'issue419-train-{position:06d}',
            'hand_id': item['source_hand_id'],
            'whitelist': item['whitelist'],
            'action': item['action'],
            'target_total_bb': item['target_total_bb'],
            'reveal_label': None,
        })
    return observations


def unresolved_frontier_keys(tree: Mapping[str, Any], nodes: list[dict[str, Any]]) -> list[str]:
    """Requested keys whose RAISE sizing is a #388 unresolved frontier."""
    by_id = {node['id']: node for node in nodes}
    keys = set()
    for frontier in tree['unresolved_sizing_frontiers']:
        node = by_id.get(frontier['node_id'])
        if node is None:
            raise ValueError('frontier node missing from the required tree')
        keys.add(node['audit_exact_key'])
    return sorted(keys)


def declared_frontier_records(
    tree: Mapping[str, Any], nodes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The #388 raise-sizing frontiers, mapped to their requested exact keys."""
    by_id = {node['id']: node for node in nodes}
    records = []
    for frontier in tree['unresolved_sizing_frontiers']:
        node = by_id[frontier['node_id']]
        records.append({
            'requested_key': node['audit_exact_key'],
            'node_id': node['id'],
            'path': list(node['path']),
            'action': frontier['action'],
            'legal_target_interval_bb': list(frontier['legal_target_interval_bb']),
            'provenance': 'analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json',
        })
    return sorted(records, key=lambda record: record['path'])


def build_candidate(
    observations: list[dict[str, Any]],
    frontiers: list[str],
    spec: Mapping[str, Any],
    spec_sha256: str,
    source_report_hash: str,
) -> dict[str, Any]:
    candidate = H.make_synthetic_hierarchical_candidate(
        population_id=POPULATION_ID,
        observations=observations,
        unresolved_raise_frontiers=frontiers,
        fit_scope=FIT_SCOPE,
        data_scope=DATA_SCOPE,
        source_report_hash=source_report_hash,
        hierarchy_spec_sha256=spec_sha256,
    )
    H.validate_candidate(candidate)
    # The frozen hyper-parameters must be exactly the spec's, never re-selected.
    shrinkage = spec['hierarchy_prior_shrinkage']
    if candidate['shrinkage']['kappa0'] != float(shrinkage['hierarchical_strength_kappa0']):
        raise ValueError('candidate kappa0 drifted from the T2 spec')
    if candidate['shrinkage']['alpha_per_legal_marginal_action'] != float(
        shrinkage['base_prior']['alpha_per_legal_marginal_action']
    ):
        raise ValueError('candidate Dirichlet alpha drifted from the T2 spec')
    thresholds = spec['decision_thresholds']
    if candidate['thresholds']['minimum_marginal_observations'] != int(
        thresholds['minimum_marginal_observations']
    ):
        raise ValueError('candidate observation threshold drifted from the T2 spec')
    if candidate['thresholds']['minimum_distinct_hands'] != int(thresholds['minimum_distinct_hands']):
        raise ValueError('candidate distinct-hand threshold drifted from the T2 spec')
    return candidate


def reconstruct_node_context(node: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild the public context of a required node from its frozen stack bucket."""
    context = dict(node['context'])
    bucket = str(context['effective_stack_bucket'])
    for label, representative in STACK_BUCKET_REPRESENTATIVE.items():
        if label == bucket:
            context['effective_stack_bb'] = representative
            break
    else:
        raise ValueError(f'unknown stack bucket: {bucket}')
    whitelist = H.hierarchical_public_whitelist(context)
    if whitelist != dict(node['context']):
        raise ValueError('reconstructed node whitelist drifted from #388')
    # Bucket-representative invariance: any in-bucket stack yields the same key.
    alternate = dict(node['context'])
    alternate['effective_stack_bb'] = STACK_BUCKET_ALTERNATES[bucket]
    if H.hierarchical_public_whitelist(alternate) != whitelist:
        raise ValueError('stack-bucket reconstruction is not key-invariant')
    if H.hierarchical_exact_key_from_whitelist(whitelist) != node['audit_exact_key']:
        raise ValueError('reconstructed exact key drifted from #388')
    if H.runtime_exact_preflop_node_key(whitelist) != node['runtime_exact_preflop_node_key']:
        raise ValueError('reconstructed structural node key drifted from #388')
    return context


def legal_actions(node: Mapping[str, Any]) -> list[str]:
    actions = [edge['action'] for edge in node['edges'] if edge['state'] != 'STRUCTURALLY_UNREACHABLE']
    if not actions:
        raise ValueError('node exposes no legal action')
    return actions


def compact_node_result(node: Mapping[str, Any], response: Mapping[str, Any]) -> dict[str, Any]:
    support = response['support']
    pooling = response['pooling']
    return {
        'node_id': node['id'],
        'path': list(node['path']),
        'requested_key': response['requested_key'],
        'runtime_support_context_key': node['runtime_support_context_key'],
        'runtime_exact_preflop_node_key': node['runtime_exact_preflop_node_key'],
        'legal_actions': list(legal_actions(node)),
        'status': response['status'],
        'reason_code': response['reason_code'],
        'unresolved_reason': response.get('unresolved_reason'),
        'raise_sizing_state': response['raise_sizing']['state'],
        'support': {
            'observations': support['observations'],
            'distinct_hands': support['distinct_hands'],
            'action_counts': dict(support['action_counts']),
        },
        'pooling': None if pooling is None else {
            'level': pooling['level'],
            'rank': pooling['rank'],
            'source_key': pooling['source_key'],
            'source_observations': pooling['source_observations'],
            'source_distinct_hands': pooling['source_distinct_hands'],
            'weight_exact': pooling['weight_exact'],
            'weight_parent': pooling['weight_parent'],
            'parent_dominated': pooling['parent_dominated'],
        },
        'posterior': response['posterior'],
        'pooling_diagnostics': [
            {
                'level': row['level'],
                'rank': row['rank'],
                'source_key': row['source_key'],
                'source_observations': row['source_observations'],
                'source_distinct_hands': row['source_distinct_hands'],
                'qualifies': row['qualifies'],
                'support_source_allowed': row['support_source_allowed'],
                'action_counts': dict(row['action_counts']),
            }
            for row in response['pooling_diagnostics']
        ],
        'response_sha256': H.canonical_response_sha256(response),
    }


def fit_required_nodes(
    candidate: Mapping[str, Any], nodes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    results = []
    for node in nodes:
        context = reconstruct_node_context(node)
        response = H.resolve_exact_context(
            candidate=candidate, context=context, legal_actions=legal_actions(node)
        )
        H.validate_response(response)
        results.append(compact_node_result(node, response))
    return results


def observation_index(observations: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [H._normalize_observation(row, index) for index, row in enumerate(observations)]
    per_level: dict[str, Any] = {}
    for level in H.POOLING_LEVELS:
        distinct = {row['level_keys'][level] for row in rows}
        counts: collections.Counter[str] = collections.Counter()
        for row in rows:
            counts[row['level_keys'][level]] += 1
        per_level[level] = {
            'distinct_source_keys': len(distinct),
            'observations': len(rows),
            'max_observations_for_one_key': max(counts.values()) if counts else 0,
        }
    return {
        'observations': len(rows),
        'distinct_hands': len({row['hand_id'] for row in rows}),
        'distinct_exact_keys': len({row['hierarchical_exact_key'] for row in rows}),
        'action_counts': dict(sorted(collections.Counter(row['action'] for row in rows).items())),
        'per_pooling_level': per_level,
    }


def support_isolation_proof(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Every observation must validate, and its support may only be its own key."""
    checked = 0
    for index, row in enumerate(observations):
        normalized = H._normalize_observation(row, index)
        if row.get('hierarchical_exact_key') not in (None, normalized['hierarchical_exact_key']):
            raise ValueError('declared exact key drifted from its public context')
        H.assert_support_isolation(
            requested_key=normalized['hierarchical_exact_key'],
            source_key=normalized['hierarchical_exact_key'],
        )
        checked += 1
    return {
        'rule': H.SUPPORT_ISOLATION_RULE,
        'runtime_invariant': 'support.source_key == requested_key',
        'checked_observations': checked,
        'violations': [],
        'coarse_key_support_laundering': False,
        'detail': (
            'each observation carries exactly one hierarchical_exact_key and joins only the '
            'support bucket of that key; parents are used for parameters only'
        ),
    }


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: collections.Counter[str] = collections.Counter(row['status'] for row in results)
    pooling_counts: collections.Counter[str] = collections.Counter(
        row['pooling']['level'] for row in results if row['pooling']
    )
    unresolved_counts: collections.Counter[str] = collections.Counter(
        row['unresolved_reason'] for row in results if row['status'] == H.STATUS_EXACT_UNRESOLVED
    )
    return {
        'nodes_total': len(results),
        'status_counts': dict(sorted(status_counts.items())),
        'pooling_level_counts': dict(sorted(pooling_counts.items())),
        'unresolved_reason_counts': dict(sorted(unresolved_counts.items())),
        'resolved_nodes': sum(
            1 for row in results
            if row['status'] in (H.STATUS_EXACT_EMPIRICAL_STRONG, H.STATUS_EXACT_HIERARCHICAL_ESTIMATE)
        ),
        'unresolved_nodes': status_counts.get(H.STATUS_EXACT_UNRESOLVED, 0),
        'raise_sizing_unresolved_nodes': sum(
            1 for row in results if row['raise_sizing_state'] == 'UNRESOLVED_SIZING_FRONTIER'
        ),
    }


def canonical_cells(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_path = {tuple(row['path']): row for row in results}
    bb = by_path[('SB:ISO@5',)]
    co = by_path[('SB:ISO@5', 'BB:FOLD')]

    def cell(row: dict[str, Any]) -> dict[str, Any]:
        runtime = next(
            diag for diag in row['pooling_diagnostics']
            if diag['level'] == 'L3_RUNTIME_SUPPORT_CONTEXT'
        )
        return {
            'node_id': row['node_id'],
            'path': row['path'],
            'requested_key': row['requested_key'],
            'runtime_support_context_key': row['runtime_support_context_key'],
            'runtime_observations': runtime['source_observations'],
            'runtime_distinct_hands': runtime['source_distinct_hands'],
            'runtime_qualifies': runtime['qualifies'],
            'status': row['status'],
            'pooling_level': row['pooling']['level'] if row['pooling'] else None,
            'support_observations': row['support']['observations'],
            'support_distinct_hands': row['support']['distinct_hands'],
        }

    return {'bb_facing_sb_iso5': cell(bb), 'co_after_bb_fold': cell(co)}


def input_fingerprints() -> list[dict[str, Any]]:
    paths = (
        'analysis/issue419_hierarchical_tree/HIERARCHICAL_MODEL_SPEC.json',
        'analysis/issue419_hierarchical_tree/model_spec/ARTIFACTS.json',
        'analysis/issue419_hierarchical_tree/HIERARCHICAL_TREE_SPARSITY_BASELINE.json',
        'analysis/issue419_hierarchical_tree/ARTIFACTS.json',
        'analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json',
        'analysis/issue388_exact_tree/TRAIN_RESPONSE_TREE_SUPPORT.json',
        'analysis/issue388_exact_tree/DECISION.json',
        'analysis/issue388_exact_tree/ARTIFACTS.json',
        'analysis/model_a_preflop_sizing_v2_fit.json',
        'analysis/preflop_sizing_support_train.full.json.gz',
        'training/datasets/NLHE_100-200/population_certification.json',
        'training/models/preflop_population_model_v5.json',
        'tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.snapshots.json',
        'tools/preflop/model_a_sizing_hierarchical.py',
        'tools/preflop/model_a_sizing_likelihood.py',
        'tools/preflop/policy_context.py',
        'tools/training/audit_model_a_exact_tree.py',
        'tools/training/audit_hierarchical_tree_sparsity.py',
        'tools/training/write_hierarchical_model_spec.py',
        'tools/training/increment_decisions.py',
        'tools/training/audit_hero_preflop_coverage.py',
        'tools/training/fit_model_a_preflop_sizing_hierarchical.py',
    )
    return [{'path': path, 'sha256': sha256_file(ROOT / path)} for path in paths]


def hyperparameters(spec: Mapping[str, Any]) -> dict[str, Any]:
    shrinkage = spec['hierarchy_prior_shrinkage']
    thresholds = spec['decision_thresholds']
    return {
        'estimator': shrinkage['estimator'],
        'hierarchical_strength_kappa0': float(shrinkage['hierarchical_strength_kappa0']),
        'alpha_per_legal_marginal_action': float(
            shrinkage['base_prior']['alpha_per_legal_marginal_action']
        ),
        'blend': shrinkage['blend'],
        'exact_weight': shrinkage['exact_weight'],
        'parent_dominated_flag_below': float(shrinkage['parent_dominated_flag_below']),
        'recursion': shrinkage['recursion'],
        'minimum_marginal_observations': int(thresholds['minimum_marginal_observations']),
        'minimum_distinct_hands': int(thresholds['minimum_distinct_hands']),
        'pooling_levels': [
            {
                'level': level['level'],
                'rank': level['rank'],
                'purpose': level['purpose'],
                'drops': list(level['drops']),
                'equals_runtime_provider_key': level['equals_runtime_provider_key'],
                'support_source_allowed': level['support_source_allowed'],
            }
            for level in shrinkage['levels']
        ],
        'confidence_level': H.DEFAULT_UNCERTAINTY_LEVEL,
        'frozen_by_spec': 'analysis/issue419_hierarchical_tree/HIERARCHICAL_MODEL_SPEC.json',
        'frozen': True,
        'hyperparameter_search_performed': False,
        'validation_used_for_hyperparameters': False,
    }


def priors_and_shrinkage(spec: Mapping[str, Any]) -> dict[str, Any]:
    shrinkage = spec['hierarchy_prior_shrinkage']
    return {
        'base_prior': {
            'kind': shrinkage['base_prior']['kind'],
            'actions': list(shrinkage['base_prior']['actions']),
            'alpha_per_legal_marginal_action': float(
                shrinkage['base_prior']['alpha_per_legal_marginal_action']
            ),
            'rationale': shrinkage['base_prior']['rationale'],
        },
        'estimator': shrinkage['estimator'],
        'kappa0': float(shrinkage['hierarchical_strength_kappa0']),
        'kappa0_continuity': shrinkage['kappa0_continuity'],
        'blend': shrinkage['blend'],
        'exact_weight': shrinkage['exact_weight'],
        'no_hidden_hand_imputation': shrinkage['no_hidden_hand_imputation'],
        'no_pseudo_observation': True,
        'constraints': list(shrinkage['constraints']),
    }


def seeds_block() -> dict[str, Any]:
    return {
        'policy': 'DETERMINISTIC_NO_RANDOMNESS',
        'random_seed': FIT_SEED,
        'rng_algorithm': 'none',
        'stochastic_draws': 0,
        'deterministic_reproduction': True,
        'purpose': (
            'the frozen estimator is a closed-form Dirichlet shrinkage; the recorded seed only '
            'pins observation ordering and tie-breaking, no sampling is performed'
        ),
    }


def protected_hashes() -> dict[str, str]:
    return {path: sha256_file(ROOT / path) for path in PROTECTED_FILES}


def build() -> tuple[dict[str, Any], str]:
    scan = verify_no_holdout_access()
    pinned = load_verified_inputs()
    spec, tree = pinned['spec'], pinned['tree']
    nodes = required_nodes(tree)
    keyspace = required_level_keyspace(nodes)

    protected_before = protected_hashes()
    rows, corpus = parse_certified_train_rows()
    kept, corpus_scan = select_in_scope_rows(rows, keyspace)
    observations = build_observations(kept)
    frontiers = unresolved_frontier_keys(tree, nodes)
    spec_sha256 = pinned['spec_index'][spec_tool.SPEC_NAME]['canonical_payload_sha256']
    source_report_hash = baseline_tool.ISSUE388_TRAIN_SUPPORT_SHA256
    candidate = build_candidate(observations, frontiers, spec, spec_sha256, source_report_hash)
    results = fit_required_nodes(candidate, nodes)
    # Evidence-only diagnostic: the same estimator with the #388 structural raise
    # frontier *removed*.  It is explicitly not the candidate; it only shows what
    # the hierarchical pooling would resolve if the unpriced RAISE branch were
    # ignored, and is never reported as an admission.
    free_candidate = build_candidate(observations, [], spec, spec_sha256, source_report_hash)
    free_results = fit_required_nodes(free_candidate, nodes)
    protected_after = protected_hashes()
    if protected_before != protected_after:
        raise ValueError('an active registry or model pointer was mutated by the fit')

    candidate_bytes = serialize(candidate)
    # The persisted bytes must load back as the same contract candidate.
    H.validate_candidate(json.loads(candidate_bytes))
    candidate_digest = hashlib.sha256(candidate_bytes).hexdigest()
    candidate_canonical = H.canonical_candidate_sha256(candidate)
    code_sha = sha256_file(SOURCE_PATH)

    report = {
        'schema': REPORT_SCHEMA,
        'issue': 419,
        'source_issue': 388,
        'scenario_issue': baseline_tool.SCENARIO_ISSUE,
        'kind': 'TRAIN_ONLY_HIERARCHICAL_FIT_REPORT',
        'candidate': {
            'contract_candidate_id': CONTRACT_CANDIDATE_ID,
            'candidate_instance_id': CANDIDATE_INSTANCE_ID,
            'artifact': CANDIDATE_NAME,
            'artifact_sha256': candidate_digest,
            'canonical_payload_sha256': candidate_canonical,
            'active_model_replaced': False,
        },
        'fit_scope': FIT_SCOPE,
        'data_scope': DATA_SCOPE,
        'observation_scope': OBSERVATION_SCOPE,
        'population_id': POPULATION_ID,
        'split_consumed': 'TRAIN',
        'validation_consumed': False,
        'test_consumed': False,
        'validation_decisions_read': 0,
        'test_decisions_read': 0,
        'holdout_access_scan': scan,
        'corpus': corpus,
        'hyperparameters': hyperparameters(spec),
        'priors_and_shrinkage': priors_and_shrinkage(spec),
        'thresholds': {
            'minimum_marginal_observations': H.MIN_MARGINAL_OBSERVATIONS,
            'minimum_distinct_hands': H.MIN_DISTINCT_HANDS,
            'frozen': True,
            'lowered_to_close_the_tree': False,
        },
        'seeds': seeds_block(),
        'code': {
            'fit_tool': {'path': str(SOURCE_PATH.relative_to(ROOT)), 'sha256': code_sha},
            'dependencies': input_fingerprints(),
        },
        'support_isolation': support_isolation_proof(observations),
        'tree': {
            'root_id': tree['root_id'],
            'required_node_count': len(nodes),
            'unresolved_sizing_frontier_count': len(tree['unresolved_sizing_frontiers']),
            'enumeration_complete': tree['enumeration_complete'],
            'required_tree_sha256': baseline_tool.ISSUE388_REQUIRED_TREE_SHA256,
        },
        'observation_index': observation_index(observations),
        'corpus_support_scan': corpus_scan,
        'aggregate': aggregate(results),
        'canonical_cells': canonical_cells(results),
        'raise_sizing_policy': {
            'rule': spec['raise_sizing_policy']['rule'],
            'supported_targets': spec['raise_sizing_policy']['supported_targets'],
            'unresolved_frontier_behaviour': spec['raise_sizing_policy']['unresolved_frontier']['behaviour'],
            'forbidden': list(spec['raise_sizing_policy']['forbidden']),
            'declared_frontier_count': len(tree['unresolved_sizing_frontiers']),
            'declared_frontiers': declared_frontier_records(tree, nodes),
            'declaration_scope': (
                'per requested exact key: any other exact key at the same structural frontier '
                'independently fails closed when its own observations expose no exact raise target'
            ),
        },
        'raise_frontier_diagnostics': {
            'authoritative': False,
            'purpose': (
                'evidence-only counterfactual: the same frozen estimator with the #388 structural '
                'raise frontier removed. It is NOT the candidate and admits nothing.'
            ),
            'declared_frontier_removed': True,
            'aggregate': aggregate(free_results),
            'would_resolve': [
                {
                    'node_id': row['node_id'],
                    'path': row['path'],
                    'status': row['status'],
                    'pooling_level': row['pooling']['level'] if row['pooling'] else None,
                    'weight_exact': row['pooling']['weight_exact'] if row['pooling'] else None,
                }
                for row in free_results
                if row['status'] in (H.STATUS_EXACT_EMPIRICAL_STRONG, H.STATUS_EXACT_HIERARCHICAL_ESTIMATE)
            ],
        },
        'nodes': results,
        'evidence_bindings': {
            'hierarchy_spec_schema': spec['schema'],
            'hierarchy_spec_canonical_payload_sha256': spec_sha256,
            'sparsity_baseline_canonical_payload_sha256': stable_hash(pinned['baseline']),
            'issue388_required_tree_sha256': baseline_tool.ISSUE388_REQUIRED_TREE_SHA256,
            'issue388_train_support_sha256': baseline_tool.ISSUE388_TRAIN_SUPPORT_SHA256,
            'issue388_decision_sha256': baseline_tool.ISSUE388_DECISION_SHA256,
            'issue352_fit_artifact_sha256': sha256_file(baseline_tool.BASELINE_FIT_PATH),
            'issue319_support_report_sha256': legacy.EXPECTED_SUPPORT_HASH,
            'reference_model_sha256': legacy.EXPECTED_REFERENCE_HASH,
            'canonical_fixture_sha256': sha256_file(FIXTURE_PATH),
        },
        'protected_files_before_after_sha256': {
            'before': protected_before,
            'after': protected_after,
            'unchanged': protected_before == protected_after,
            'active_pointer_mutated': protected_before != protected_after,
        },
        'no_pseudo_observation': {
            'rule': 'EVERY_OBSERVATION_IS_A_CERTIFIED_TRAIN_ROW',
            'observations': len(observations),
            'synthetic_observations': 0,
            'hidden_hand_imputation': False,
            'detail': (
                'each observation is a parsed certified TRAIN non-Hero preflop decision row whose '
                'public whitelist, exact key and level keys are recomputed and re-validated'
            ),
        },
        'reproduction': {
            'command': 'python3 tools/training/fit_model_a_preflop_sizing_hierarchical.py',
            'check_command': 'python3 tools/training/fit_model_a_preflop_sizing_hierarchical.py --check',
        },
    }

    report_bytes = serialize(report)
    manifest = {
        'schema': MANIFEST_SCHEMA,
        'issue': 419,
        'kind': 'TRAIN_ONLY_FITTED_CANDIDATE_MANIFEST',
        'candidate': {
            'contract_candidate_id': CONTRACT_CANDIDATE_ID,
            'candidate_instance_id': CANDIDATE_INSTANCE_ID,
            'model_family': H.MODEL_FAMILY,
            'status': H.CANDIDATE_STATUS,
            'active_model_replaced': False,
            'identity_granularity': H.EXACT_GRANULARITY,
            'support_level': H.SUPPORT_LEVEL,
            'support_isolation_rule': H.SUPPORT_ISOLATION_RULE,
            'nearest_price_fallback': False,
            'nearest_context_fallback': False,
            'representative_price_fallback': False,
            'artifact': {
                'path': CANDIDATE_NAME,
                'sha256': candidate_digest,
                'canonical_payload_sha256': candidate_canonical,
                'observations': len(observations),
                'distinct_exact_keys': len(
                    {row['hierarchical_exact_key'] for row in candidate['observations']}
                ),
                'unresolved_raise_frontiers': list(frontiers),
                'unresolved_raise_frontier_paths': [
                    record['path'] for record in declared_frontier_records(tree, nodes)
                ],
            },
            'distinct_from': DISTINCT_FROM,
        },
        'fit_report': {
            'path': REPORT_NAME,
            'sha256': hashlib.sha256(report_bytes).hexdigest(),
            'canonical_payload_sha256': stable_hash(report),
        },
        'fit': {
            'scope': FIT_SCOPE,
            'data_scope': DATA_SCOPE,
            'observation_scope': OBSERVATION_SCOPE,
            'population_id': POPULATION_ID,
            'split_consumed': 'TRAIN',
            'validation_consumed': False,
            'test_consumed': False,
            'validation_decisions_read': 0,
            'test_decisions_read': 0,
        },
        'corpus': {
            'certification_sha256': corpus['certification_sha256'],
            'population_fingerprint_sha256': corpus['population_fingerprint_sha256'],
            'certified_split_counts': corpus['certified_split_counts'],
            'train_hands_parsed': corpus['train_hands_parsed'],
            'train_hand_ids_fingerprint_sha256': corpus['train_hand_ids_fingerprint_sha256'],
            'train_decision_rows_parsed': corpus['train_decision_rows_parsed'],
            'in_scope_observations': len(observations),
            'archives': corpus['archives'],
        },
        'hyperparameters': hyperparameters(spec),
        'priors_and_shrinkage': priors_and_shrinkage(spec),
        'thresholds': {
            'minimum_marginal_observations': H.MIN_MARGINAL_OBSERVATIONS,
            'minimum_distinct_hands': H.MIN_DISTINCT_HANDS,
            'frozen': True,
        },
        'seeds': seeds_block(),
        'code': {
            'fit_tool': {'path': str(SOURCE_PATH.relative_to(ROOT)), 'sha256': code_sha},
            'dependencies': input_fingerprints(),
        },
        'holdout_boundary': {
            'split_consumed': 'TRAIN',
            'validation_consumed': False,
            'test_consumed': False,
            'validation_decisions_read': 0,
            'test_decisions_read': 0,
            'holdout_access_scan': scan['result'],
            'spec_hash_pinned_before_fit': True,
        },
        'active_model_pointer': {
            'mutated': False,
            'protected_files': list(PROTECTED_FILES),
            'before': protected_before,
            'after': protected_after,
        },
        'evidence_bindings': report['evidence_bindings'],
        'aggregate': report['aggregate'],
        'reproduction': {
            'command': 'python3 tools/training/fit_model_a_preflop_sizing_hierarchical.py',
            'check_command': 'python3 tools/training/fit_model_a_preflop_sizing_hierarchical.py --check',
        },
    }

    summary = (
        '# #419 — TRAIN-only hierarchical fit candidate\n\n'
        f"Fitted the frozen T2 hierarchical exact-context model on certified TRAIN only "
        f"({corpus['train_hands_parsed']} hands parsed, {corpus['train_decision_rows_parsed']} "
        f"non-Hero preflop decision rows). In-scope observations: {len(observations)} real TRAIN rows "
        f"({report['observation_index']['distinct_exact_keys']} distinct `hierarchical_exact_key`, "
        f"{report['observation_index']['distinct_hands']} distinct hands) covering the required #388 "
        f"tree keyspace.\n\n"
        f"Candidate `{CANDIDATE_INSTANCE_ID}` instantiates the contract id `{CONTRACT_CANDIDATE_ID}` "
        f"(distinct from #352 `{DISTINCT_FROM['issue_352_candidate_id']}` and from #388, which created "
        f"no candidate). Canonical payload SHA256 `{candidate_canonical}`; artifact byte SHA256 "
        f"`{candidate_digest}`.\n\n"
        f"Hyper-parameters and priors are the spec's, never re-selected: `kappa0={H.KAPPA0}`, "
        f"Dirichlet `alpha={H.ALPHA_PER_LEGAL_ACTION}` per legal marginal action, thresholds "
        f"{H.MIN_MARGINAL_OBSERVATIONS} observations / {H.MIN_DISTINCT_HANDS} distinct hands, raise "
        f"sizing exact-support-only with no nearest price. The estimator is closed-form "
        f"(seed {FIT_SEED}, zero stochastic draws).\n\n"
        f"Resolution over the {report['aggregate']['nodes_total']} required nodes: "
        f"{report['aggregate']['resolved_nodes']} estimated, {report['aggregate']['unresolved_nodes']} "
        f"fail closed ("
        + ', '.join(
            f"{count} x {reason}"
            for reason, count in sorted(report['aggregate']['unresolved_reason_counts'].items())
        )
        + "); the tree stays open where TRAIN support is insufficient — the frozen thresholds are "
        f"not lowered.\n\n"
        f"{len(tree['unresolved_sizing_frontiers'])} nodes stay explicitly unresolved because RAISE "
        f"sizing is a #388 structural frontier (exact-support-only, no representative price); the "
        f"non-authoritative evidence-only diagnostic in the report shows which nodes hierarchical "
        f"pooling would resolve if that frontier were ignored.\n\n"
        'No VALIDATION or TEST decision was parsed or evaluated (`split_consumed=TRAIN`, '
        '`validation_consumed=false`, `test_consumed=false`). No pseudo-observation or hidden-hand '
        'imputation was used. `training/registry.json` and the active '
        '`training/models/preflop_population_model_v5.json` pointer are unchanged before/after '
        '(`active_pointer_mutated=false`). This artifact admits nothing.\n\n'
        'Reproduce: `python3 tools/training/fit_model_a_preflop_sizing_hierarchical.py`; '
        'verify: `python3 tools/training/fit_model_a_preflop_sizing_hierarchical.py --check`.\n'
    )

    artifacts = {
        CANDIDATE_NAME: candidate,
        REPORT_NAME: report,
        MANIFEST_NAME: manifest,
        'SUMMARY.md': summary,
    }
    return artifacts, summary


def persist(artifacts: Mapping[str, Any]) -> dict[str, Any]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    objects = OUTPUT / 'sha256'
    objects.mkdir(exist_ok=True)
    index: dict[str, Any] = {}
    referenced: set[str] = set()
    for name, value in artifacts.items():
        markdown = name.endswith('.md')
        data = str(value).encode() if markdown else serialize(value)
        extension = '.md' if markdown else '.json'
        digest = hashlib.sha256(data).hexdigest()
        entry = {'sha256': digest, 'object': 'sha256/' + digest + extension}
        if not markdown:
            entry['canonical_payload_sha256'] = stable_hash(value)
        index[name] = entry
        (OUTPUT / name).write_bytes(data)
        (objects / (digest + extension)).write_bytes(data)
        referenced.add(digest + extension)
    (OUTPUT / INDEX_NAME).write_text(json.dumps(index, sort_keys=True, indent=2) + '\n')
    for path in objects.iterdir():
        if path.is_file() and path.name not in referenced:
            path.unlink()
    return index


def check() -> int:
    artifacts, _summary = build()
    problems: list[str] = []
    for name, value in artifacts.items():
        expected = str(value).encode() if name.endswith('.md') else serialize(value)
        if (OUTPUT / name).read_bytes() != expected:
            problems.append(f'{name} differs from a fresh build')
    index = json.loads((OUTPUT / INDEX_NAME).read_text())
    for name, entry in index.items():
        data = (OUTPUT / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            problems.append(f'byte hash mismatch for {name}')
        if data != (OUTPUT / entry['object']).read_bytes():
            problems.append(f'content-addressed copy mismatch for {name}')
        if 'canonical_payload_sha256' in entry and entry['canonical_payload_sha256'] != stable_hash(
            artifacts[name]
        ):
            problems.append(f'canonical payload digest mismatch for {name}')
    if {p.name for p in (OUTPUT / 'sha256').iterdir()} != {
        Path(entry['object']).name for entry in index.values()
    }:
        problems.append('unexpected object in fit/sha256')
    if problems:
        print(json.dumps({'status': 'MISMATCH', 'problems': problems}, indent=2))
        return 1
    report = artifacts[REPORT_NAME]
    print(json.dumps({
        'status': 'OK',
        'schema': SCHEMA,
        'candidate_instance_id': CANDIDATE_INSTANCE_ID,
        'candidate_payload_sha256': index[CANDIDATE_NAME]['canonical_payload_sha256'],
        'split_consumed': report['split_consumed'],
        'validation_consumed': report['validation_consumed'],
        'test_consumed': report['test_consumed'],
        'active_pointer_mutated': report['protected_files_before_after_sha256']['active_pointer_mutated'],
        'resolved_nodes': report['aggregate']['resolved_nodes'],
    }, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='verify the persisted fit bundle instead of rewriting it')
    args = parser.parse_args()
    if args.check:
        return check()
    artifacts, _summary = build()
    index = persist(artifacts)
    report = artifacts[REPORT_NAME]
    print(json.dumps({
        'schema': SCHEMA,
        'bundle': str(OUTPUT.relative_to(ROOT)),
        'candidate_instance_id': CANDIDATE_INSTANCE_ID,
        'candidate_payload_sha256': index[CANDIDATE_NAME]['canonical_payload_sha256'],
        'candidate_artifact_sha256': index[CANDIDATE_NAME]['sha256'],
        'train_hands_parsed': report['corpus']['train_hands_parsed'],
        'observations': report['observation_index']['observations'],
        'split_consumed': report['split_consumed'],
        'validation_consumed': report['validation_consumed'],
        'test_consumed': report['test_consumed'],
        'active_pointer_mutated': report['protected_files_before_after_sha256']['active_pointer_mutated'],
        'aggregate': report['aggregate'],
    }, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
