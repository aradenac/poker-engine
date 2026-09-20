#!/usr/bin/env python3
"""#388: TRAIN-only feasibility certificate; never fits or opens a holdout.

Enumerate public preflop continuations with the #367 exact-reference raise
translator. Missing raise sizing is an unresolved frontier, never a zero-mass
branch. No policy probabilities or Hero values are computed.
"""
from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import fingerprint, sha256_file, split_for
from tools.preflop.model_a_sizing_likelihood import support_context_key
from tools.preflop.policy_context import stack_bucket
from tools.repro_preflop_fixture import FIXTURE_PATH, load_verified_reference
from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.model_a_continuation import (
    _empirical_raise_target, _preflop_decision, _semantic_trace, exact_preflop_node,
)
from tools.training.audit_hero_preflop_coverage import DEFAULT_CERTIFICATION, load_train_records
from tools.training.audit_preflop_sizing_support import (
    action_summary, history_features, reveal_summary, stable_hash,
)
from tools.training.fit_model_a_preflop_sizing import (
    EXPECTED_REFERENCE_HASH, EXPECTED_SUPPORT_HASH, REFERENCE, load_support_report,
)
from tools.training.increment_decisions import decision_rows, parse_hand

OUTPUT = ROOT / 'analysis/issue388_exact_tree'
ACTIONS = ('FOLD', 'CALL', 'RAISE', 'JAM')
BASELINE_ID = 'model-a-preflop-sizing-aware-candidate-v2'
BASELINE_SHA = '9115165c3141d16152946dd1ee7a049f219fef1a1d79c0e1c7b1249c45326f19'
BASELINE_FIT_HASH = 'cacf97c80f44856da6e787b230ab1b564d5c0c83821a894e57b70aba92145738'
# Pin the persisted payload separately from its historical self-reported digest.
# #388 does not rewrite or reinterpret #352's admission evidence.
BASELINE_PAYLOAD_HASH = 'ec96d6da20aca0ecb12717ed864ab2df8322a2e28bcb565b8cce9d94a106f367'
# Deliberately fixed before any new TRAIN counts or holdout access.
RULES = {
    'minimum_marginal_observations': 20,
    'minimum_distinct_hands': 20,
    'threshold_basis': '#352 marginal minimum retained; distinct-hand safeguard added',
    'stack_buckets': ['LE40', 'GT40_LE75', 'GT75_LE125', 'GT125'],
    'prospective_candidate_declared_context_merge': (
        'effective stack within the existing policy_context stack bucket only'
    ),
    'implemented_runtime_context_merge': (
        'support_context_key also merges history, pot, stack bucket, live/all-in positions, '
        'table size and raise level; reported as an open #367 risk, not authorized for a new candidate fit'
    ),
    'feasibility_resolution_key': 'support_context_key (resolve_support_likelihood runtime contract)',
    'runtime_support_context_fields': ['family', 'actor_position', 'aggressor_position',
                                       'limper_count', 'caller_count', 'target_total_bb',
                                       'to_call_bb'],
    'runtime_exact_preflop_node_fields': ['history', 'live_positions', 'all_in_positions',
                                          'family', 'actor_position', 'table_size', 'raise_level'],
    'audit_exact_fields': ['family', 'actor_position', 'aggressor_position', 'limper_count',
                           'caller_count', 'target_total_bb', 'to_call_bb', 'table_size',
                           'raise_level', 'live_positions', 'all_in_positions', 'history',
                           'pot_before_bb', 'effective_stack_bucket'],
    'audit_exact_key_role': (
        'strict diagnostic partition only; deliberately finer than both runtime keys so history, '
        'pot and stack-bucket merges remain visible; it is not the #367 likelihood lookup key'
    ),
    'rare_hand_classes': (
        'may shrink only to a qualifying same-support_context_key marginal; no hidden-hand imputation'
    ),
    'prospective_shrinkage': (
        'Dirichlet prior strength 16 to the same support_context_key marginal; '
        'alpha 0.5 per legal marginal action'
    ),
    'zero_probability': 'observed zero counts do not prove zero probability; enumerate every legal action',
    'structurally_unreachable': 'only actions forbidden by the public betting engine',
    'raise_sizing': '#367 exact active structural node empirical translator; missing node or LEGAL_MIN_FALLBACK is unresolved',
    'continuation': 'through preflop round closure, including Hero response requirements; no Hero policy or EV evaluated',
    'initial_iso_target_total_bb': 5,
    'nearest_price': False,
    'nearest_context': False,
    'target_drift': False,
    'future_or_private_features': False,
    'holdout_access': 'NONE: command has no fit, VALIDATION, TEST, or admission execution path',
    'admission': 'audit alone can never admit; every node and sizing frontier must resolve before a separately frozen validation protocol',
}


def public_context(row: dict[str, Any]) -> dict[str, Any]:
    """Explicit whitelist: reveals are labels only, never keys or reachability."""
    history = [{k: str(x[k]) for k in ('position', 'action')} for x in row['history']]
    aggressor, limpers, callers = history_features(history)
    ctx = row.get('preflop_context_v1') or row
    return {
        'family': row['family'], 'actor_position': row['actor_position'],
        'aggressor_position': aggressor, 'limper_count': limpers, 'caller_count': callers,
        'target_total_bb': round(float(row.get('current_price_bb', row.get('target_total_bb'))), 6),
        'to_call_bb': round(float(row['to_call_bb']), 6),
        'table_size': int(row['table_size']), 'raise_level': int(row['raise_level']),
        'live_positions': sorted(row['live_positions']),
        'all_in_positions': sorted(row['all_in_positions']), 'history': history,
        'pot_before_bb': round(float(row['pot_before_bb']), 6),
        'effective_stack_bucket': stack_bucket(ctx['effective_stack_bb']),
    }


def exact_key(context: dict[str, Any]) -> str:
    return support_context_key(context) + '|public=' + stable_hash(context)


def runtime_exact_preflop_node_key(context: dict[str, Any]) -> str:
    """Identity equivalent to exact_preflop_node's public structural comparison."""
    projected = {
        'actor_position': str(context.get('actor_position') or ''),
        'table_size': int(context.get('table_size') or 0),
        'raise_level': int(context.get('raise_level') or 0),
        'family': str(context.get('family') or ''),
        'live_positions': list(context.get('live_positions') or []),
        'all_in_positions': list(context.get('all_in_positions') or []),
        'history': [
            {'position': str(row.get('position')), 'action': str(row.get('action'))}
            for row in context.get('history', [])
        ],
    }
    return 'MAPNODE_' + stable_hash(projected)


def key_contract() -> dict[str, Any]:
    return {
        'audit_exact_key': {
            'builder': 'exact_key',
            'fields': RULES['audit_exact_fields'],
            'role': RULES['audit_exact_key_role'],
        },
        'runtime_support_context_key': {
            'builder': 'support_context_key',
            'consumer': 'resolve_support_likelihood',
            'fields': RULES['runtime_support_context_fields'],
            'role': 'required feasibility and response-likelihood resolution granularity for #367',
        },
        'runtime_exact_preflop_node_key': {
            'builder': 'runtime_exact_preflop_node_key',
            'consumer': 'exact_preflop_node / empirical raise-target lookup',
            'fields': RULES['runtime_exact_preflop_node_fields'],
            'role': 'structural raise-sizing identity; not the response-likelihood support key',
        },
    }


def verify_baseline(fit: dict[str, Any]) -> None:
    if fit['candidate_identity']['candidate_id'] != BASELINE_ID or fit['candidate_sha256'] != BASELINE_SHA:
        raise ValueError('baseline candidate identity/hash mismatch')
    if fit.get('evidence_sha256') != BASELINE_FIT_HASH or stable_hash(
        {k: v for k, v in fit.items() if k != 'evidence_sha256'}
    ) != BASELINE_PAYLOAD_HASH:
        raise ValueError('baseline TRAIN fit evidence hash mismatch')


def reconstruct_tree(reference: dict[str, Any]) -> dict[str, Any]:
    fixture = load_verified_reference(ROOT)
    scenario = fixture['scenario']
    state = NoLimitHoldemState(
        seats=scenario['seats'], button=scenario['button'],
        stacks_bb=scenario['starting_stacks_bb'],
        small_blind_bb=scenario['blinds_bb']['small'], big_blind_bb=scenario['blinds_bb']['big'],
    )
    for action in scenario['actions'][:4]:
        state.apply_action(action['player'], action['action'].upper())
    state.apply_action('Hero', 'RAISE', target_total_bb=5)
    nodes, frontiers, terminals = [], [], []

    def visit(current: NoLimitHoldemState, path: list[str]) -> str:
        node_id = stable_hash(path)
        if current.street != 'preflop' or current.next_actor is None or current.settlement:
            terminals.append({'id': node_id, 'path': path, 'kind': 'PREFLOP_CLOSED'})
            return node_id
        if len(nodes) >= 20000:
            raise ValueError('tree safety bound exceeded; no truncated evidence may be emitted')
        actor = current.next_actor
        _, replay, history, _, _ = _semantic_trace(current)
        if replay.to_snapshot(include_log=False) != current.to_snapshot(include_log=False):
            raise ValueError('public replay diverged')
        decision = _preflop_decision(current, actor, history)
        context = public_context(decision)
        view = current.legal_view(actor)
        node = {
            'id': node_id,
            'path': path,
            'context': context,
            'audit_exact_key': exact_key(context),
            'runtime_support_context_key': support_context_key(context),
            'runtime_exact_preflop_node_key': runtime_exact_preflop_node_key(context),
            'edges': [],
        }
        nodes.append(node)
        for action in (*ACTIONS, 'CHECK'):
            core = 'RAISE' if action == 'JAM' else action
            if core not in view['legal_actions']:
                node['edges'].append({'action': action, 'state': 'STRUCTURALLY_UNREACHABLE'})
                continue
            target, sizing_source = None, None
            if action == 'JAM':
                target, sizing_source = view['max_raise_to_bb'], 'JAM_BOUNDARY'
            elif action == 'RAISE':
                ref_node = exact_preflop_node(reference, decision)
                if ref_node is not None:
                    target, sizing_source = _empirical_raise_target(ref_node, current, actor)
                if ref_node is None or sizing_source == 'LEGAL_MIN_FALLBACK':
                    frontier = {
                        'node_id': node_id, 'action': action,
                        'reason': 'EXACT_REFERENCE_RAISE_SIZING_UNAVAILABLE',
                        'legal_target_interval_bb': [view['min_raise_to_bb'], view['max_raise_to_bb']],
                        'descendants': 'REQUIRED_UNRESOLVED_NOT_PRUNED_AS_ZERO_MASS',
                        'public_state': current.to_snapshot(include_log=True),
                        'expansion_rule': 'apply RAISE at an exactly supported target, then recurse until preflop closes; no representative price is permitted',
                    }
                    frontiers.append(frontier)
                    node['edges'].append({**frontier, 'state': 'UNRESOLVED_FRONTIER'})
                    continue
            child = copy.deepcopy(current)
            child.apply_action(actor, core, target_total_bb=target)
            label = context['actor_position'] + ':' + action + ('' if target is None else f'@{target:g}')
            child_id = visit(child, [*path, label])
            node['edges'].append({'action': action, 'target_total_bb': target,
                                  'sizing_source': sizing_source, 'child_id': child_id, 'state': 'REACHABLE'})
        return node_id

    root = visit(state, ['SB:ISO@5'])
    runtime_groups = collections.defaultdict(list)
    for node in nodes:
        runtime_groups[node['runtime_support_context_key']].append(node)
    merged_groups = [
        {
            'runtime_support_context_key': runtime_key,
            'node_ids': [node['id'] for node in grouped],
            'paths': [node['path'] for node in grouped],
            'distinct_audit_exact_keys': len({node['audit_exact_key'] for node in grouped}),
        }
        for runtime_key, grouped in sorted(runtime_groups.items())
        if len({node['audit_exact_key'] for node in grouped}) > 1
    ]
    runtime_resolution_risks = [{
        'risk_id': 'RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE',
        'status': 'OPEN_FOR_367',
        'consumer': 'resolve_support_likelihood',
        'description': (
            'The runtime likelihood key omits history, pot_before_bb, effective_stack_bucket, '
            'live/all-in positions, table size and raise level, so one fitted likelihood node can '
            'be reused across audit-distinct public states.'
        ),
        'not_a_nearest_lookup': True,
        'scientific_risk': (
            'Although lookup equality is exact at the implemented runtime key, the declared '
            'nearest-context prohibition may require a finer provider contract before #367.'
        ),
        'audit_disposition': (
            'Report the risk and classify current feasibility at the key #367 actually resolves; '
            'this TRAIN-only audit does not change the runtime provider contract.'
        ),
        'tree_collision_group_count': len(merged_groups),
        'tree_collision_groups': merged_groups,
    }]
    return {'schema': 'poker-required-exact-tree/v1', 'issue': 388, 'root_id': root,
            'rules': copy.deepcopy(RULES), 'key_contract': key_contract(),
            'runtime_resolution_risks': runtime_resolution_risks,
            'fixture_sha256': sha256_file(FIXTURE_PATH),
            'rules_sha256': stable_hash(RULES),
            'reference_sha256': sha256_file(REFERENCE), 'nodes': nodes,
            'unresolved_sizing_frontiers': frontiers, 'terminals': terminals,
            'enumeration_complete': not frontiers}


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    hands = {str(r['hand_id']) for r in rows}
    classes = collections.defaultdict(list)
    for row in rows:
        if row.get('known_hand_class'):
            classes[row['known_hand_class']].append(row)
    return {'observations': len(rows), 'distinct_hands': len(hands),
            'hand_ids_fingerprint_sha256': fingerprint(hands),
            'actions': action_summary(rows), 'reveal': reveal_summary(rows),
            'hand_classes': {k: {'observations': len(v), 'actions': action_summary(v)}
                             for k, v in sorted(classes.items())}}


def classify(stats: dict[str, Any]) -> str:
    if not stats['observations']:
        return 'ZERO_EXACT_SUPPORT'
    return 'EXACT_OBSERVED' if stats['hand_classes'] else 'EXACT_MARGINAL_ONLY'


def support_view(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stats = summarize(rows)
    return {
        'support_state': classify(stats),
        **stats,
        'qualifies': stats['observations'] >= RULES['minimum_marginal_observations']
        and stats['distinct_hands'] >= RULES['minimum_distinct_hands'],
    }


def audit_train(tree: dict[str, Any], records, provenance: dict[str, Any]) -> dict[str, Any]:
    required_audit = {n['audit_exact_key'] for n in tree['nodes']}
    required_runtime = {n['runtime_support_context_key'] for n in tree['nodes']}
    required_structural = {n['runtime_exact_preflop_node_key'] for n in tree['nodes']}
    audit_rows = collections.defaultdict(list)
    runtime_rows = collections.defaultdict(list)
    structural_rows = collections.defaultdict(list)
    parsed_ids = set()
    for record in records:
        if split_for(record.hand_id) != 'TRAIN':
            raise ValueError('non-TRAIN hand rejected before parser')
        hand = parse_hand(record.text, record.source_file)
        if not hand:
            raise ValueError('certified TRAIN parse failure: ' + str(record.hand_id))
        parsed_ids.add(str(record.hand_id))
        for row in decision_rows(hand, include_preflop_context_v1=True):
            if row['split'] != 'TRAIN':
                raise ValueError('non-TRAIN row rejected')
            if row['street'] != 'preflop' or row['is_hero']:
                continue
            context = public_context(row)
            support = support_context_key(context)
            if support in required_runtime:
                runtime_rows[support].append(row)
            structural = runtime_exact_preflop_node_key(context)
            if structural in required_structural:
                structural_rows[structural].append(row)
            audit = exact_key(context)
            if audit in required_audit:
                audit_rows[audit].append(row)
    if len(parsed_ids) != provenance['certified_split_counts']['TRAIN']:
        raise ValueError('certified TRAIN accounting mismatch')
    matrix = []
    for node in tree['nodes']:
        matrix.append({
            'node_id': node['id'],
            'path': node['path'],
            'context': node['context'],
            'audit_exact_key': node['audit_exact_key'],
            'runtime_support_context_key': node['runtime_support_context_key'],
            'runtime_exact_preflop_node_key': node['runtime_exact_preflop_node_key'],
            'feasibility_classification_granularity': 'runtime_support_context_key',
            'audit_exact_support': support_view(audit_rows[node['audit_exact_key']]),
            'runtime_support_context_support': support_view(
                runtime_rows[node['runtime_support_context_key']]
            ),
            'runtime_exact_preflop_node_support': support_view(
                structural_rows[node['runtime_exact_preflop_node_key']]
            ),
        })
    return {'schema': 'poker-train-response-tree-support/v1', 'issue': 388,
            'required_tree_sha256': stable_hash(tree), 'split_consumed': 'TRAIN',
            'key_contract': copy.deepcopy(tree['key_contract']),
            'source_issue319_report_hash': EXPECTED_SUPPORT_HASH,
            'validation_consumed': False, 'test_consumed': False,
            'provenance': provenance, 'train_hands_parsed': len(parsed_ids),
            'train_hand_ids_fingerprint_sha256': fingerprint(parsed_ids), 'matrix': matrix,
            'issue319_coarse_diagnostics_not_exact_support': {
                k: summarize(runtime_rows[k]) for k in sorted(required_runtime)}}


def decide(tree: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    if (
        tree['rules'] != RULES
        or tree['rules_sha256'] != stable_hash(RULES)
        or tree.get('key_contract') != key_contract()
        or not tree['nodes']
    ):
        raise ValueError('empty tree or frozen feasibility rules mismatch')
    if report['required_tree_sha256'] != stable_hash(tree):
        raise ValueError('required tree hash mismatch')
    if report.get('key_contract') != tree['key_contract']:
        raise ValueError('TRAIN report key contract mismatch')
    if report['split_consumed'] != 'TRAIN' or report['validation_consumed'] or report['test_consumed']:
        raise ValueError('holdout evidence forbidden')
    expected = {n['id']: n for n in tree['nodes']}
    actual = {n['node_id']: n for n in report['matrix']}
    if len(actual) != len(report['matrix']) or set(actual) != set(expected):
        raise ValueError('incomplete or duplicate required tree matrix')
    blockers = []
    for node_id, node in expected.items():
        cell = actual[node_id]
        if (
            cell['audit_exact_key'] != node['audit_exact_key']
            or node['audit_exact_key'] != exact_key(node['context'])
            or cell['runtime_support_context_key'] != node['runtime_support_context_key']
            or node['runtime_support_context_key'] != support_context_key(node['context'])
            or cell['runtime_exact_preflop_node_key'] != node['runtime_exact_preflop_node_key']
            or node['runtime_exact_preflop_node_key'] != runtime_exact_preflop_node_key(node['context'])
        ):
            raise ValueError('public key contract mismatch')
        runtime = cell['runtime_support_context_support']
        audit = cell['audit_exact_support']
        runtime_qualifies = (
            runtime['observations'] >= RULES['minimum_marginal_observations']
            and runtime['distinct_hands'] >= RULES['minimum_distinct_hands']
        )
        if runtime.get('qualifies') is not runtime_qualifies:
            raise ValueError('runtime support qualification/count mismatch')
        if not runtime_qualifies:
            blockers.append({
                'node_id': node_id,
                'path': node['path'],
                'classification_granularity': 'runtime_support_context_key',
                'runtime_support_context_key': node['runtime_support_context_key'],
                'runtime_observations': runtime['observations'],
                'runtime_distinct_hands': runtime['distinct_hands'],
                'audit_exact_key': node['audit_exact_key'],
                'audit_exact_observations_diagnostic_only': audit['observations'],
                'audit_exact_distinct_hands_diagnostic_only': audit['distinct_hands'],
                'reason': (
                    'ZERO_RUNTIME_SUPPORT_CONTEXT'
                    if not runtime['observations']
                    else 'INSUFFICIENT_RUNTIME_SUPPORT_CONTEXT'
                ),
            })
    if not blockers and not tree['unresolved_sizing_frontiers']:
        raise ValueError('TRAIN feasible: separate frozen fit and validation implementation required; audit cannot admit')
    return {'schema': 'poker-exact-tree-decision/v1', 'issue': 388,
            'decision': 'UNRESOLVED_EXACT_TREE_GAP', 'status': 'BLOCKED_SCIENTIFIC',
            'candidate_id': None, 'candidate_sha256': None, 'required_tree_complete': False,
            'validation_consumed': False, 'test_consumed': False, 'active_pointer_mutated': False,
            'hero_ev_executed': False, 'hero_recommendation': None,
            'required_tree_sha256': stable_hash(tree), 'train_support_sha256': stable_hash(report),
            'feasibility_classification_granularity': 'runtime_support_context_key',
            'runtime_support_context_qualified_node_count': len(tree['nodes']) - len(blockers),
            'runtime_support_context_blocked_node_count': len(blockers),
            'runtime_resolution_risks_for_367': copy.deepcopy(tree['runtime_resolution_risks']),
            'blockers': blockers, 'unresolved_sizing_frontiers': tree['unresolved_sizing_frontiers']}


def persist(output: Path, artifacts: dict[str, Any], summary: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    objects = output / 'sha256'
    objects.mkdir(exist_ok=True)
    index = {}
    referenced_objects = set()
    for name, value in artifacts.items():
        data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
        digest = hashlib.sha256(data).hexdigest()
        (output / name).write_bytes(data)
        (objects / (digest + '.json')).write_bytes(data)
        index[name] = {'sha256': digest, 'canonical_payload_sha256': stable_hash(value),
                       'object': 'sha256/' + digest + '.json'}
        referenced_objects.add(digest + '.json')
    data = summary.encode()
    digest = hashlib.sha256(data).hexdigest()
    (output / 'SUMMARY.md').write_bytes(data)
    (objects / (digest + '.md')).write_bytes(data)
    index['SUMMARY.md'] = {'sha256': digest, 'object': 'sha256/' + digest + '.md'}
    referenced_objects.add(digest + '.md')
    (output / 'ARTIFACTS.json').write_text(json.dumps(index, sort_keys=True, indent=2) + '\n')
    for path in objects.iterdir():
        if path.is_file() and path.name not in referenced_objects:
            path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    # Pin existing TRAIN/reference evidence, without loading #352 VALIDATION.
    if sha256_file(REFERENCE) != EXPECTED_REFERENCE_HASH:
        raise ValueError('reference SHA mismatch')
    _, support = load_support_report()
    if stable_hash({k: v for k, v in support.items() if k != 'report_hash'}) != EXPECTED_SUPPORT_HASH:
        raise ValueError('#319 content hash mismatch')
    baseline_path = ROOT / 'analysis/model_a_preflop_sizing_v2_fit.json'
    verify_baseline(json.loads(baseline_path.read_text()))
    protected = [ROOT / 'training/registry.json', ROOT / 'training/populations/registry.json', REFERENCE]
    before = {str(p.relative_to(ROOT)): sha256_file(p) for p in protected}
    tree = reconstruct_tree(json.loads(REFERENCE.read_text()))
    # Persist the requirement/rules before parsing any new TRAIN decisions.
    persist(args.output, {'REQUIRED_EXACT_TREE.json': tree}, '# #388 — audit in progress\n')
    records, provenance = load_train_records(DEFAULT_CERTIFICATION)
    report = audit_train(tree, records, provenance)
    # Independently reconcile every runtime support key represented by #319.
    legacy_by_key = {support_context_key(cell): cell for cell in support['matrix']}
    for runtime_key, recounted in report['issue319_coarse_diagnostics_not_exact_support'].items():
        legacy = legacy_by_key.get(runtime_key)
        if legacy is None:
            if recounted['observations']:
                raise ValueError('#319 absent runtime key has nonzero TRAIN recount')
            continue
        if recounted['observations'] != legacy['observations'] or recounted['actions'] != legacy['actions']:
            raise ValueError('#319 runtime support recount mismatch')

    bb = next(n for n in tree['nodes'] if n['path'] == ['SB:ISO@5'])
    co = next(n for n in tree['nodes'] if n['path'] == ['SB:ISO@5', 'BB:FOLD'])
    bb_runtime = report['issue319_coarse_diagnostics_not_exact_support'][bb['runtime_support_context_key']]
    co_runtime = report['issue319_coarse_diagnostics_not_exact_support'][co['runtime_support_context_key']]
    decision = decide(tree, report)
    after = {str(p.relative_to(ROOT)): sha256_file(p) for p in protected}
    if before != after:
        raise ValueError('active reference/registry mutation')
    decision['protected_files_before_after_sha256'] = before
    decision['code_sha256'] = sha256_file(Path(__file__))
    decision['baseline_candidate'] = {'candidate_id': BASELINE_ID, 'candidate_sha256': BASELINE_SHA,
                                      'train_fit_artifact_sha256': sha256_file(baseline_path),
                                      'historical_reported_evidence_sha256': BASELINE_FIT_HASH,
                                      'persisted_payload_without_digest_sha256': BASELINE_PAYLOAD_HASH,
                                      'historical_digest_recomputed_match': BASELINE_FIT_HASH == BASELINE_PAYLOAD_HASH,
                                      'use': 'identity provenance only; no admission inferred or reinterpreted'}
    decision['source_files_sha256'] = {
        str(p.relative_to(ROOT)): sha256_file(p) for p in sorted({
            Path(__file__), DEFAULT_CERTIFICATION, FIXTURE_PATH, REFERENCE,
            ROOT / 'analysis/preflop_sizing_support_train.full.json.gz',
            ROOT / 'tools/training/increment_decisions.py',
            ROOT / 'tools/training/audit_hero_preflop_coverage.py',
            ROOT / 'tools/training/audit_preflop_sizing_support.py',
            ROOT / 'tools/datasets/build_hand_history_increment.py',
            ROOT / 'tools/preflop/policy_context.py',
            ROOT / 'tools/preflop/context_contract.py',
            ROOT / 'tools/preflop/model_a_sizing_likelihood.py',
            ROOT / 'tools/simulation/model_a_continuation.py',
            ROOT / 'tools/simulation/game_core.py',
            ROOT / 'tools/repro_preflop_fixture.py',
        })}
    cells = {cell['node_id']: cell for cell in report['matrix']}
    bb_audit = cells[bb['id']]['audit_exact_support']
    co_audit = cells[co['id']]['audit_exact_support']
    decision['key_granularity_reconciliation'] = {
        'bb_facing_iso_5': {
            'path': bb['path'],
            'runtime_support_context_key': bb['runtime_support_context_key'],
            'runtime_observations': bb_runtime['observations'],
            'runtime_distinct_hands': bb_runtime['distinct_hands'],
            'audit_exact_key': bb['audit_exact_key'],
            'audit_exact_observations': bb_audit['observations'],
            'audit_exact_distinct_hands': bb_audit['distinct_hands'],
            'authoritative_issue367_observations': 45,
            'reconciled': bb_runtime['observations'] == 45,
            'feasibility_result': 'QUALIFIES_RUNTIME_SUPPORT_CONTEXT',
            'explanation': (
                'The 45 observations are the exact implemented runtime support-context cell. '
                'The 6-observation value is a finer audit-only history/pot/stack partition and '
                'does not classify #367 feasibility.'
            ),
        },
        'co_after_bb_fold': {
            'path': co['path'],
            'runtime_support_context_key': co['runtime_support_context_key'],
            'runtime_observations': co_runtime['observations'],
            'runtime_distinct_hands': co_runtime['distinct_hands'],
            'audit_exact_key': co['audit_exact_key'],
            'audit_exact_observations': co_audit['observations'],
            'audit_exact_distinct_hands': co_audit['distinct_hands'],
            'source_issue319_observations': 14,
            'reconciled': co_runtime['observations'] == 14,
            'feasibility_result': 'INSUFFICIENT_RUNTIME_SUPPORT_CONTEXT',
            'explanation': (
                'The 14 observations are the exact implemented runtime support-context cell; '
                'the finer audit-only partition contains 4. Both remain below the frozen 20/20 rule.'
            ),
        },
    }
    decision['canonical_bb_runtime_observations'] = bb_runtime['observations']
    decision['canonical_bb_audit_exact_observations'] = bb_audit['observations']
    decision['canonical_co_coarse_observations'] = co_runtime['observations']
    decision['canonical_co_exact_observations'] = co_audit['observations']
    decision['runtime_support_context_qualified_nodes'] = [
        {'node_id': cell['node_id'], 'path': cell['path'],
         'runtime_support_context_key': cell['runtime_support_context_key'],
         'observations': cell['runtime_support_context_support']['observations'],
         'distinct_hands': cell['runtime_support_context_support']['distinct_hands']}
        for cell in report['matrix'] if cell['runtime_support_context_support']['qualifies']
    ]
    summary = (
        '# #388 — exact response-tree TRAIN feasibility\n\n'
        '**UNRESOLVED_EXACT_TREE_GAP**; no candidate created or admitted.\n\n'
        f"Certified TRAIN hands parsed: {report['train_hands_parsed']}. "
        f"Explicit public decision nodes: {len(tree['nodes'])}; unresolved raise-sizing frontiers: {len(tree['unresolved_sizing_frontiers'])}.\n\n"
        'Three identities are kept separate. `support_context_key` is the exact key actually consumed by '
        '`resolve_support_likelihood` and therefore classifies #367 feasibility. `exact_preflop_node` uses '
        'history/live/all-in/family/actor/table-size/raise-level to select structural raise sizing. The audit-only '
        '`audit_exact_key` is strictly finer than both: it additionally exposes exact price, pot and the existing '
        'effective-stack bucket. That finer partition is diagnostic and is not presented as the provider lookup contract.\n\n'
        f"BB facing SB ISO@5 reconciles exactly with #367: {bb_runtime['observations']} observations and "
        f"{bb_runtime['distinct_hands']} hands at the runtime support key, versus {bb_audit['observations']} "
        'in the finer history/pot/stack audit partition. BB therefore qualifies 20/20 and is not a blocker. '
        f"Canonical CO after SB ISO@5 / BB FOLD has {co_runtime['observations']} runtime-key observations "
        f"(12 CALL, 2 FOLD), versus {co_audit['observations']} in the finer audit partition. "
        'This reconciles #319 and remains below the frozen 20 observations / 20 hands rule, so the CO cell '
        'remains a real #367 data blocker. The threshold is not lowered to close the tree.\n\n'
        f"At the runtime-key granularity, {decision['runtime_support_context_qualified_node_count']} of "
        f"{len(tree['nodes'])} tree nodes qualify; {decision['runtime_support_context_blocked_node_count']} do not. "
        'The machine-readable #319 diagnostic enumerates all 30 required runtime keys, including zero-support keys.\n\n'
        'Every legal FOLD/CALL/RAISE/JAM continuation is retained. Empirical zero counts never prune a branch. '
        'Raise sizes use only the #367 exact reference-node translator; missing sizing remains an explicit unresolved frontier, '
        'including its required descendants. Thus the enumerated tree is not claimed complete where sizing cannot be established. '
        'No legal-minimum, nearest-price, or nearest-context substitution is made.\n\n'
        'The current likelihood runtime key intentionally preserves family, actor, aggressor, limpers/callers and exact price. '
        'It nevertheless merges differing history/pot/stack/live/table contexts. This latent coarse-merge risk is recorded as '
        '`RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE` for #367; this audit reports it and does not silently redefine the provider. '
        'Reveals are descriptive labels, never features.\n\n'
        'VALIDATION and TEST decisions were not parsed or evaluated. The certified loader checks shared archive hashes and hand IDs '
        'before allowing only TRAIN hands across the decision-parser boundary, as in #319. '
        'No fit, posterior candidate, validation protocol/result, or preflight is fabricated for this infeasible tree. '
        'Active registries/reference hashes are unchanged. No Hero EV or recommendation; #367 was not run.\n\n'
        'The historical #352 fit self-reported digest differs from the recomputed persisted payload digest. '
        'Both are recorded separately and the persisted bytes are pinned; this audit neither repairs that evidence '
        'nor uses it to infer a new admission.\n\n'
        'Reproduce: `python3 tools/training/audit_model_a_exact_tree.py`. '
        'Artifact byte hashes and content-addressed copies are in ARTIFACTS.json; internal links use canonical payload SHA256.\n'
    )
    persist(args.output, {'REQUIRED_EXACT_TREE.json': tree, 'TRAIN_RESPONSE_TREE_SUPPORT.json': report,
                          'DECISION.json': decision}, summary)
    print(json.dumps({k: decision[k] for k in (
        'decision', 'status', 'canonical_bb_runtime_observations',
        'canonical_bb_audit_exact_observations', 'canonical_co_coarse_observations',
        'canonical_co_exact_observations',
    )}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
