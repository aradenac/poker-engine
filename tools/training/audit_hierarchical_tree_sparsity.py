#!/usr/bin/env python3
"""#419: TRAIN-only re-derivation of the #388 hierarchical-tree sparsity baseline.

This tool never fits, never reads VALIDATION/TEST and never mutates an active
registry. It rebuilds the 38-node required public tree of scenario #321 from the
canonical fixture and recounts the exact certified-TRAIN support matrix at the
two key granularities:

* ``runtime_support_context_key`` -- the exact key consumed by
  ``resolve_support_likelihood`` (#367 feasibility granularity);
* ``audit_exact_key`` -- the strictly finer diagnostic partition that also
  exposes exact price, pot and the existing effective-stack bucket. It is not a
  provider lookup contract.

The recount is compared cell-by-cell to the persisted #388 artifacts and pinned
into a content-addressed baseline
(``analysis/issue419_hierarchical_tree/HIERARCHICAL_TREE_SPARSITY_BASELINE.json``)
so later hierarchical-tree work can detect runtime-contract drift.
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
from tools.repro_preflop_fixture import FIXTURE_PATH
from tools.training import audit_model_a_exact_tree as legacy
from tools.training.audit_hero_preflop_coverage import DEFAULT_CERTIFICATION, load_train_records
from tools.training.audit_preflop_sizing_support import stable_hash
from tools.training.increment_decisions import decision_rows, parse_hand

OUTPUT = ROOT / 'analysis/issue419_hierarchical_tree'
ISSUE388_OUTPUT = ROOT / 'analysis/issue388_exact_tree'
SCHEMA = 'poker-hierarchical-tree-sparsity-baseline/v1'
BASELINE_NAME = 'HIERARCHICAL_TREE_SPARSITY_BASELINE.json'

# Pinned #388 evidence. Every value below is independently re-verified from the
# persisted bytes; nothing is taken on trust.
ISSUE388_REQUIRED_TREE_SHA256 = '0ab232ae44e4157e2a47d4d3d611ac8ca9c2cdb54caf2568f256f6df35643a25'
ISSUE388_REQUIRED_TREE_BYTE_SHA256 = '2c71f747f188af4d03c37ae145ef06cd53db844a8f064ec84b440fee8a02220c'
ISSUE388_TRAIN_SUPPORT_SHA256 = 'dc6590ae04a9fa3714e3a739d7c850a83fbde33466e2fc31ac56e16864eea1e2'
ISSUE388_TRAIN_SUPPORT_BYTE_SHA256 = '9a05ac6f5ba1e52450b8a58bb9a4f516394922bd86339b7f7a22bcdbba521053'
ISSUE388_DECISION_SHA256 = '87cf59a2bc258f0d86ef085232b8db6bc422413ee4086dc6c203459560abc374'
ISSUE388_DECISION_BYTE_SHA256 = '7eb50d70b6a0af70e18895183303795d94951d44d5fd1971ab7d28b909c52472'
ISSUE388_REQUIRED_NODES = 38
ISSUE388_UNRESOLVED_FRONTIERS = 7
ISSUE388_TRAIN_HANDS = 19016
ISSUE388_RUNTIME_QUALIFIED_NODES = 3
ISSUE388_RUNTIME_DIAGNOSTIC_KEYS = 30
ISSUE388_BB_RUNTIME_OBSERVATIONS = 45
ISSUE388_CO_RUNTIME_OBSERVATIONS = 14
SCENARIO_ISSUE = 321

# #352 digest gap: the historical self-reported fit digest and the recomputed
# persisted payload digest are recorded separately and never conflated.
HISTORICAL_FIT_DIGEST = 'cacf97c80f44856da6e787b230ab1b564d5c0c83821a894e57b70aba92145738'
PERSISTED_PAYLOAD_DIGEST = 'ec96d6da20aca0ecb12717ed864ab2df8322a2e28bcb565b8cce9d94a106f367'
BASELINE_FIT_PATH = ROOT / 'analysis/model_a_preflop_sizing_v2_fit.json'


def load_issue388(output: Path = ISSUE388_OUTPUT) -> dict[str, Any]:
    """Load #388 artifacts and verify their content addressing before trusting them."""
    index = json.loads((output / 'ARTIFACTS.json').read_text())
    for name, entry in index.items():
        data = (output / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError(f'#388 artifact byte hash mismatch: {name}')
        if data != (output / entry['object']).read_bytes():
            raise ValueError(f'#388 content-addressed copy mismatch: {name}')
    return {
        'index': index,
        'tree': json.loads((output / 'REQUIRED_EXACT_TREE.json').read_text()),
        'report': json.loads((output / 'TRAIN_RESPONSE_TREE_SUPPORT.json').read_text()),
        'decision': json.loads((output / 'DECISION.json').read_text()),
    }


def verify_issue388_boundaries(bundle: dict[str, Any]) -> None:
    tree, report, decision = bundle['tree'], bundle['report'], bundle['decision']
    if stable_hash(tree) != ISSUE388_REQUIRED_TREE_SHA256:
        raise ValueError('#388 required-tree canonical payload hash mismatch')
    if bundle['index']['REQUIRED_EXACT_TREE.json']['sha256'] != ISSUE388_REQUIRED_TREE_BYTE_SHA256:
        raise ValueError('#388 required-tree byte hash mismatch')
    if stable_hash(report) != ISSUE388_TRAIN_SUPPORT_SHA256:
        raise ValueError('#388 TRAIN support canonical payload hash mismatch')
    if stable_hash(decision) != ISSUE388_DECISION_SHA256:
        raise ValueError('#388 decision canonical payload hash mismatch')
    if len(tree['nodes']) != ISSUE388_REQUIRED_NODES:
        raise ValueError('#388 required node count mismatch')
    if tree['enumeration_complete'] is not False:
        raise ValueError('#388 enumeration must remain incomplete')
    if len(tree['unresolved_sizing_frontiers']) != ISSUE388_UNRESOLVED_FRONTIERS:
        raise ValueError('#388 unresolved sizing frontier count mismatch')
    if report['train_hands_parsed'] != ISSUE388_TRAIN_HANDS:
        raise ValueError('#388 certified TRAIN hand count mismatch')
    if report['required_tree_sha256'] != ISSUE388_REQUIRED_TREE_SHA256:
        raise ValueError('#388 report/required-tree binding mismatch')
    if decision['required_tree_sha256'] != ISSUE388_REQUIRED_TREE_SHA256:
        raise ValueError('#388 decision/required-tree binding mismatch')
    if decision['train_support_sha256'] != ISSUE388_TRAIN_SUPPORT_SHA256:
        raise ValueError('#388 decision/TRAIN-support binding mismatch')
    if decision['decision'] != 'UNRESOLVED_EXACT_TREE_GAP' or decision['status'] != 'BLOCKED_SCIENTIFIC':
        raise ValueError('#388 decision/status must remain the unresolved scientific block')
    if decision['runtime_support_context_qualified_node_count'] != ISSUE388_RUNTIME_QUALIFIED_NODES:
        raise ValueError('#388 qualified-node count mismatch')
    if len(report['issue319_coarse_diagnostics_not_exact_support']) != ISSUE388_RUNTIME_DIAGNOSTIC_KEYS:
        raise ValueError('#388 runtime diagnostic key count mismatch')
    for field in ('validation_consumed', 'test_consumed'):
        if report[field] or decision[field]:
            raise ValueError(f'#388 {field} must be false')
    if report['split_consumed'] != 'TRAIN':
        raise ValueError('#388 report split must be TRAIN')


def rederive_tree() -> dict[str, Any]:
    """Rebuild the 38-node required tree from the canonical #321 fixture."""
    return legacy.reconstruct_tree(json.loads(legacy.REFERENCE.read_text()))


def parse_train_rows(records: list[Any], provenance: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str]]:
    """Parse certified TRAIN preflop decisions; VALIDATION/TEST never cross the parser."""
    rows: list[dict[str, Any]] = []
    parsed_ids: set[str] = set()
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
            rows.append(row)
    if len(parsed_ids) != provenance['certified_split_counts']['TRAIN']:
        raise ValueError('certified TRAIN accounting mismatch')
    return rows, parsed_ids


def rederived_report(
    tree: dict[str, Any], rows: list[dict[str, Any]], parsed_ids: set[str], provenance: dict[str, Any]
) -> dict[str, Any]:
    """Rebuild the #388 TRAIN support report from raw TRAIN rows, not from #388's output."""
    required_audit = {n['audit_exact_key'] for n in tree['nodes']}
    required_runtime = {n['runtime_support_context_key'] for n in tree['nodes']}
    required_structural = {n['runtime_exact_preflop_node_key'] for n in tree['nodes']}
    audit_rows: collections.defaultdict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    runtime_rows: collections.defaultdict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    structural_rows: collections.defaultdict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        context = legacy.public_context(row)
        support = support_context_key(context)
        if support in required_runtime:
            runtime_rows[support].append(row)
        structural = legacy.runtime_exact_preflop_node_key(context)
        if structural in required_structural:
            structural_rows[structural].append(row)
        audit = legacy.exact_key(context)
        if audit in required_audit:
            audit_rows[audit].append(row)
    matrix = [{
        'node_id': node['id'],
        'path': node['path'],
        'context': node['context'],
        'audit_exact_key': node['audit_exact_key'],
        'runtime_support_context_key': node['runtime_support_context_key'],
        'runtime_exact_preflop_node_key': node['runtime_exact_preflop_node_key'],
        'feasibility_classification_granularity': 'runtime_support_context_key',
        'audit_exact_support': legacy.support_view(audit_rows[node['audit_exact_key']]),
        'runtime_support_context_support': legacy.support_view(
            runtime_rows[node['runtime_support_context_key']]
        ),
        'runtime_exact_preflop_node_support': legacy.support_view(
            structural_rows[node['runtime_exact_preflop_node_key']]
        ),
    } for node in tree['nodes']]
    return {
        'schema': 'poker-train-response-tree-support/v1', 'issue': 388,
        'required_tree_sha256': stable_hash(tree), 'split_consumed': 'TRAIN',
        'key_contract': copy.deepcopy(tree['key_contract']),
        'source_issue319_report_hash': legacy.EXPECTED_SUPPORT_HASH,
        'validation_consumed': False, 'test_consumed': False,
        'provenance': provenance, 'train_hands_parsed': len(parsed_ids),
        'train_hand_ids_fingerprint_sha256': fingerprint(parsed_ids), 'matrix': matrix,
        'issue319_coarse_diagnostics_not_exact_support': {
            k: legacy.summarize(runtime_rows[k]) for k in sorted(required_runtime)},
    }


def independent_counts(tree: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Independent recount path: raw key equality only, no #388 summarization."""
    required_runtime = {n['runtime_support_context_key'] for n in tree['nodes']}
    required_audit = {n['audit_exact_key'] for n in tree['nodes']}
    runtime_obs: collections.Counter[str] = collections.Counter()
    audit_obs: collections.Counter[str] = collections.Counter()
    runtime_hands: dict[str, set[str]] = collections.defaultdict(set)
    audit_hands: dict[str, set[str]] = collections.defaultdict(set)
    for row in rows:
        context = legacy.public_context(row)
        runtime = support_context_key(context)
        if runtime in required_runtime:
            runtime_obs[runtime] += 1
            runtime_hands[runtime].add(str(row['hand_id']))
        audit = legacy.exact_key(context)
        if audit in required_audit:
            audit_obs[audit] += 1
            audit_hands[audit].add(str(row['hand_id']))
    return {
        'train_rows_parsed': len(rows),
        'runtime': {
            key: {'observations': runtime_obs[key], 'distinct_hands': len(runtime_hands[key])}
            for key in sorted(required_runtime)
        },
        'audit_exact': {
            key: {'observations': audit_obs[key], 'distinct_hands': len(audit_hands[key])}
            for key in sorted(required_audit)
        },
    }


def compact_matrix(report: dict[str, Any]) -> dict[str, Any]:
    """Two-granularity view: runtime support_context_key and audit-exact key."""
    return [
        {
            'node_id': cell['node_id'],
            'path': cell['path'],
            'runtime_support_context_key': cell['runtime_support_context_key'],
            'audit_exact_key': cell['audit_exact_key'],
            'runtime_support_context_support': copy.deepcopy(cell['runtime_support_context_support']),
            'audit_exact_support': copy.deepcopy(cell['audit_exact_support']),
        }
        for cell in report['matrix']
    ]


def compare_matrix(rederived: list[dict[str, Any]], issue388: list[dict[str, Any]]) -> dict[str, Any]:
    legacy_by_id = {cell['node_id']: cell for cell in issue388}
    mismatches: list[dict[str, Any]] = []
    for cell in rederived:
        other = legacy_by_id.get(cell['node_id'])
        if other is None:
            mismatches.append({'node_id': cell['node_id'], 'reason': 'MISSING_IN_ISSUE388'})
            continue
        for field in ('path', 'runtime_support_context_key', 'audit_exact_key'):
            if cell[field] != other[field]:
                mismatches.append({'node_id': cell['node_id'], 'reason': field})
        for field in ('runtime_support_context_support', 'audit_exact_support'):
            if cell[field] != other[field]:
                mismatches.append({'node_id': cell['node_id'], 'reason': field})
    if len(legacy_by_id) != len(rederived):
        mismatches.append({'reason': 'NODE_COUNT_MISMATCH',
                           'rederived': len(rederived), 'issue388': len(legacy_by_id)})
    ordered = sorted(cell['node_id'] for cell in rederived) == sorted(legacy_by_id)
    return {'cells_match': not mismatches, 'node_order_identical': ordered, 'mismatches': mismatches}


def coarse_merge_groups(tree: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: collections.defaultdict[list[dict[str, Any]]] = collections.defaultdict(list)
    for node in tree['nodes']:
        grouped[node['runtime_support_context_key']].append(node)
    return [
        {
            'runtime_support_context_key': key,
            'node_ids': [n['id'] for n in nodes],
            'paths': [n['path'] for n in nodes],
            'distinct_audit_exact_keys': len({n['audit_exact_key'] for n in nodes}),
        }
        for key, nodes in sorted(grouped.items())
        if len({n['audit_exact_key'] for n in nodes}) > 1
    ]


def issue352_digest_gap() -> dict[str, Any]:
    fit = json.loads(BASELINE_FIT_PATH.read_text())
    reported = str(fit.get('evidence_sha256') or '')
    recomputed = stable_hash({k: v for k, v in fit.items() if k != 'evidence_sha256'})
    if reported != HISTORICAL_FIT_DIGEST or recomputed != PERSISTED_PAYLOAD_DIGEST:
        raise ValueError('#352 digest gap values drifted')
    return {
        'baseline_candidate_id': legacy.BASELINE_ID,
        'baseline_candidate_sha256': legacy.BASELINE_SHA,
        'artifact': BASELINE_FIT_PATH.relative_to(ROOT).as_posix(),
        'artifact_sha256': sha256_file(BASELINE_FIT_PATH),
        'historical_reported_evidence_sha256': reported,
        'persisted_payload_without_digest_sha256': recomputed,
        'historical_digest_recomputed_match': reported == recomputed,
        'use': 'recorded separately; the persisted bytes are pinned and no admission is inferred or repaired',
    }


def build_baseline(
    *,
    tree: dict[str, Any],
    report: dict[str, Any],
    counts: dict[str, Any],
    bundle: dict[str, Any],
    provenance: dict[str, Any],
    parity: dict[str, Any],
    tree_rederived_equal: bool,
    protected_before: dict[str, str],
    protected_after: dict[str, str],
) -> dict[str, Any]:
    matrix = compact_matrix(report)
    matrix_by_id = {cell['node_id']: cell for cell in matrix}

    def cell(path: list[str]) -> dict[str, Any]:
        return matrix_by_id[next(n['id'] for n in tree['nodes'] if n['path'] == path)]

    bb, co = cell(['SB:ISO@5']), cell(['SB:ISO@5', 'BB:FOLD'])
    runtime_qualified = [c for c in matrix if c['runtime_support_context_support']['qualifies']]
    audit_qualified = [c for c in matrix if c['audit_exact_support']['qualifies']]
    # Cross-check the #388 summarization against the independent raw-count path.
    for c in matrix:
        runtime = counts['runtime'][c['runtime_support_context_key']]
        audit = counts['audit_exact'][c['audit_exact_key']]
        if runtime['observations'] != c['runtime_support_context_support']['observations']:
            raise ValueError('independent runtime count mismatch: ' + c['node_id'])
        if runtime['distinct_hands'] != c['runtime_support_context_support']['distinct_hands']:
            raise ValueError('independent runtime hand count mismatch: ' + c['node_id'])
        if audit['observations'] != c['audit_exact_support']['observations']:
            raise ValueError('independent audit count mismatch: ' + c['node_id'])
        if audit['distinct_hands'] != c['audit_exact_support']['distinct_hands']:
            raise ValueError('independent audit hand count mismatch: ' + c['node_id'])
    if not parity['cells_match'] or not tree_rederived_equal:
        raise ValueError('TRAIN sparsity baseline is not a faithful reproduction of #388')
    if bb['runtime_support_context_support']['observations'] != ISSUE388_BB_RUNTIME_OBSERVATIONS:
        raise ValueError('BB runtime observation count mismatch')
    if bb['runtime_support_context_support']['distinct_hands'] != ISSUE388_BB_RUNTIME_OBSERVATIONS:
        raise ValueError('BB runtime distinct-hand count mismatch')
    if co['runtime_support_context_support']['observations'] != ISSUE388_CO_RUNTIME_OBSERVATIONS:
        raise ValueError('CO runtime observation count mismatch')
    if co['runtime_support_context_support']['distinct_hands'] != ISSUE388_CO_RUNTIME_OBSERVATIONS:
        raise ValueError('CO runtime distinct-hand count mismatch')
    if len(runtime_qualified) != ISSUE388_RUNTIME_QUALIFIED_NODES:
        raise ValueError('qualified runtime node count mismatch')
    if protected_before != protected_after:
        raise ValueError('active reference/registry mutation')
    if report['validation_consumed'] or report['test_consumed'] or report['split_consumed'] != 'TRAIN':
        raise ValueError('holdout evidence forbidden')

    def key_digest(field: str) -> str:
        return stable_hash([{'node_id': c['node_id'], 'key': c[field]} for c in matrix])

    def support_digest(field: str) -> str:
        return stable_hash([{'node_id': c['node_id']} | c[field] for c in matrix])

    baseline = {
        'schema': SCHEMA,
        'issue': 419,
        'source_issue': 388,
        'scenario_issue': SCENARIO_ISSUE,
        'kind': 'TRAIN_ONLY_REPRODUCTION_BASELINE',
        'split_consumed': 'TRAIN',
        'validation_consumed': False,
        'test_consumed': False,
        'fixture_sha256': sha256_file(FIXTURE_PATH),
        'reference_sha256': sha256_file(legacy.REFERENCE),
        'thresholds': {
            'minimum_marginal_observations': legacy.RULES['minimum_marginal_observations'],
            'minimum_distinct_hands': legacy.RULES['minimum_distinct_hands'],
            'feasibility_resolution_key': legacy.RULES['feasibility_resolution_key'],
        },
        'granularities': {
            'runtime_support_context_key': {
                'builder': 'support_context_key',
                'consumer': 'resolve_support_likelihood',
                'role': 'exact #367 feasibility and response-likelihood resolution granularity',
                'key_matrix_sha256': key_digest('runtime_support_context_key'),
                'support_matrix_sha256': support_digest('runtime_support_context_support'),
            },
            'audit_exact_key': {
                'builder': 'exact_key',
                'consumer': 'diagnostic-only faithful partition',
                'role': 'strictly finer than the runtime key; not a provider lookup contract',
                'key_matrix_sha256': key_digest('audit_exact_key'),
                'support_matrix_sha256': support_digest('audit_exact_support'),
            },
        },
        'issue388_bindings': {
            'required_tree_sha256': ISSUE388_REQUIRED_TREE_SHA256,
            'required_tree_artifact_sha256': ISSUE388_REQUIRED_TREE_BYTE_SHA256,
            'train_support_sha256': ISSUE388_TRAIN_SUPPORT_SHA256,
            'train_support_artifact_sha256': ISSUE388_TRAIN_SUPPORT_BYTE_SHA256,
            'decision_sha256': ISSUE388_DECISION_SHA256,
            'decision_artifact_sha256': ISSUE388_DECISION_BYTE_SHA256,
            'required_node_count': ISSUE388_REQUIRED_NODES,
            'enumeration_complete': False,
            'unresolved_sizing_frontier_count': ISSUE388_UNRESOLVED_FRONTIERS,
            'issue319_runtime_diagnostic_key_count': ISSUE388_RUNTIME_DIAGNOSTIC_KEYS,
            'train_hands_parsed': ISSUE388_TRAIN_HANDS,
            'decision': bundle['decision']['decision'],
            'status': bundle['decision']['status'],
            'audit_tool_sha256': sha256_file(Path(legacy.__file__)),
        },
        'reproduction': {
            'tree_rederived_equal_issue388': tree_rederived_equal,
            'rederived_train_support_sha256': stable_hash(report),
            'rederived_support_hash_matches_issue388': stable_hash(report) == ISSUE388_TRAIN_SUPPORT_SHA256,
            'matrix_parity_with_issue388': parity,
            'independent_count_train_rows_parsed': counts['train_rows_parsed'],
            'train_hands_parsed': report['train_hands_parsed'],
            'train_hand_ids_fingerprint_sha256': report['train_hand_ids_fingerprint_sha256'],
        },
        'summary': {
            'nodes_total': len(matrix),
            'runtime_qualified_nodes': len(runtime_qualified),
            'runtime_blocked_nodes': len(matrix) - len(runtime_qualified),
            'audit_exact_qualified_nodes': len(audit_qualified),
            'distinct_runtime_support_context_keys': len({c['runtime_support_context_key'] for c in matrix}),
            'distinct_audit_exact_keys': len({c['audit_exact_key'] for c in matrix}),
            'runtime_keys_merging_audit_states': len(coarse_merge_groups(tree)),
        },
        'canonical_cells': {
            'bb_facing_sb_iso5': {
                'node_id': bb['node_id'],
                'path': bb['path'],
                'runtime_support_context_key': bb['runtime_support_context_key'],
                'runtime_observations': bb['runtime_support_context_support']['observations'],
                'runtime_distinct_hands': bb['runtime_support_context_support']['distinct_hands'],
                'runtime_qualifies': bb['runtime_support_context_support']['qualifies'],
                'audit_exact_key': bb['audit_exact_key'],
                'audit_exact_observations': bb['audit_exact_support']['observations'],
                'audit_exact_distinct_hands': bb['audit_exact_support']['distinct_hands'],
                'audit_exact_qualifies': bb['audit_exact_support']['qualifies'],
                'issue388_runtime_observations': ISSUE388_BB_RUNTIME_OBSERVATIONS,
                'reconciled': bb['runtime_support_context_support']['observations'] == ISSUE388_BB_RUNTIME_OBSERVATIONS,
            },
            'co_after_bb_fold': {
                'node_id': co['node_id'],
                'path': co['path'],
                'runtime_support_context_key': co['runtime_support_context_key'],
                'runtime_observations': co['runtime_support_context_support']['observations'],
                'runtime_distinct_hands': co['runtime_support_context_support']['distinct_hands'],
                'runtime_qualifies': co['runtime_support_context_support']['qualifies'],
                'audit_exact_key': co['audit_exact_key'],
                'audit_exact_observations': co['audit_exact_support']['observations'],
                'audit_exact_distinct_hands': co['audit_exact_support']['distinct_hands'],
                'audit_exact_qualifies': co['audit_exact_support']['qualifies'],
                'issue388_runtime_observations': ISSUE388_CO_RUNTIME_OBSERVATIONS,
                'reconciled': co['runtime_support_context_support']['observations'] == ISSUE388_CO_RUNTIME_OBSERVATIONS,
            },
        },
        'runtime_support_context_qualified_nodes': [
            {'node_id': c['node_id'], 'path': c['path'],
             'runtime_support_context_key': c['runtime_support_context_key'],
             'observations': c['runtime_support_context_support']['observations'],
             'distinct_hands': c['runtime_support_context_support']['distinct_hands']}
            for c in runtime_qualified
        ],
        'runtime_resolution_risks': copy.deepcopy(tree['runtime_resolution_risks']),
        'issue352_digest_gap': issue352_digest_gap(),
        'provenance': copy.deepcopy(provenance),
        'protected_files_before_after_sha256': {
            'before': protected_before, 'after': protected_after, 'unchanged': protected_before == protected_after,
        },
        'source_files_sha256': {
            str(p.relative_to(ROOT)): sha256_file(p) for p in sorted({
                Path(__file__), Path(legacy.__file__), DEFAULT_CERTIFICATION, FIXTURE_PATH,
                legacy.REFERENCE, BASELINE_FIT_PATH,
                ROOT / 'tools/preflop/model_a_sizing_likelihood.py',
                ROOT / 'tools/preflop/policy_context.py',
                ROOT / 'tools/repro_preflop_fixture.py',
                ROOT / 'tools/training/increment_decisions.py',
                ROOT / 'tools/training/audit_hero_preflop_coverage.py',
                ROOT / 'tools/training/audit_preflop_sizing_support.py',
            })
        },
        'nodes': matrix,
    }
    baseline['baseline_matrix_sha256'] = {
        'runtime_support_context': support_digest('runtime_support_context_support'),
        'audit_exact': support_digest('audit_exact_support'),
    }
    return baseline


def rederive() -> dict[str, Any]:
    """Full TRAIN-only re-derivation. Expensive: parses every certified TRAIN hand."""
    bundle = load_issue388()
    verify_issue388_boundaries(bundle)
    tree = rederive_tree()
    if stable_hash(tree) != ISSUE388_REQUIRED_TREE_SHA256:
        raise ValueError('re-derived required tree does not match #388')
    records, provenance = load_train_records(DEFAULT_CERTIFICATION)
    rows, parsed_ids = parse_train_rows(records, provenance)
    report = rederived_report(tree, rows, parsed_ids, provenance)
    if stable_hash(report) != ISSUE388_TRAIN_SUPPORT_SHA256:
        raise ValueError('re-derived TRAIN support does not match the pinned #388 canonical payload')
    parity = compare_matrix(compact_matrix(report), compact_matrix(bundle['report']))
    counts = independent_counts(tree, rows)
    return {'tree': tree, 'report': report, 'rows': rows, 'counts': counts, 'issue388': bundle,
            'parity': parity, 'tree_rederived_equal': True,
            'support_hash_matches_issue388': True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()

    if sha256_file(legacy.REFERENCE) != legacy.EXPECTED_REFERENCE_HASH:
        raise ValueError('reference SHA mismatch')
    _, support = legacy.load_support_report()
    if stable_hash({k: v for k, v in support.items() if k != 'report_hash'}) != legacy.EXPECTED_SUPPORT_HASH:
        raise ValueError('#319 content hash mismatch')
    legacy.verify_baseline(json.loads(BASELINE_FIT_PATH.read_text()))
    protected = [ROOT / 'training/registry.json', ROOT / 'training/populations/registry.json', legacy.REFERENCE]
    before = {str(p.relative_to(ROOT)): sha256_file(p) for p in protected}

    bundle = load_issue388()
    verify_issue388_boundaries(bundle)
    tree = rederive_tree()
    tree_rederived_equal = tree == bundle['tree']
    if not tree_rederived_equal:
        raise ValueError('re-derived required tree does not match #388')
    records, provenance = load_train_records(DEFAULT_CERTIFICATION)
    rows, parsed_ids = parse_train_rows(records, provenance)
    report = rederived_report(tree, rows, parsed_ids, provenance)
    if stable_hash(report) != ISSUE388_TRAIN_SUPPORT_SHA256:
        raise ValueError('re-derived TRAIN support does not match the pinned #388 canonical payload')
    parity = compare_matrix(compact_matrix(report), compact_matrix(bundle['report']))
    counts = independent_counts(tree, rows)
    after = {str(p.relative_to(ROOT)): sha256_file(p) for p in protected}
    if before != after:
        raise ValueError('active reference/registry mutation')

    baseline = build_baseline(tree=tree, report=report, counts=counts, bundle=bundle,
                              provenance=provenance, parity=parity,
                              tree_rederived_equal=tree_rederived_equal,
                              protected_before=before, protected_after=after)
    digest = hashlib.sha256(
        (json.dumps(baseline, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    ).hexdigest()
    summary = (
        '# #419 — hierarchical-tree TRAIN sparsity baseline\n\n'
        f"Re-derived on certified TRAIN only ({report['train_hands_parsed']} hands parsed, "
        f"{counts['train_rows_parsed']} non-Hero preflop decision rows). "
        f"Required tree nodes: {len(tree['nodes'])}; unresolved raise-sizing frontiers: "
        f"{len(tree['unresolved_sizing_frontiers'])}.\n\n"
        'Both granularities are reproduced and pinned: `runtime_support_context_key` (the exact #367 '
        '`resolve_support_likelihood` contract) and the strictly finer audit-only `audit_exact_key`. '
        'Every cell and both node keys match the persisted #388 matrix byte-for-byte at the '
        'canonical-payload level.\n\n'
        f"Runtime-support qualification reproduces {baseline['summary']['runtime_qualified_nodes']} of "
        f"{baseline['summary']['nodes_total']} nodes; the audit-exact partition qualifies "
        f"{baseline['summary']['audit_exact_qualified_nodes']}. "
        f"BB facing SB ISO@5 = {baseline['canonical_cells']['bb_facing_sb_iso5']['runtime_observations']} obs / "
        f"{baseline['canonical_cells']['bb_facing_sb_iso5']['runtime_distinct_hands']} hands; "
        f"CO after SB ISO@5 / BB FOLD = {baseline['canonical_cells']['co_after_bb_fold']['runtime_observations']} obs / "
        f"{baseline['canonical_cells']['co_after_bb_fold']['runtime_distinct_hands']} hands. "
        'Both reconcile exactly with #388 and #319; the CO cell remains a real data blocker.\n\n'
        'No VALIDATION or TEST decision was parsed or evaluated (`split_consumed=TRAIN`, '
        '`validation_consumed=false`, `test_consumed=false`). Active registries and the reference '
        'fixture are unchanged before/after, and the #388 artifacts are byte-verified against their '
        'content addresses. This baseline records evidence only; it admits nothing.\n\n'
        f"The #352 digest gap is recorded, not repaired: historical self-reported "
        f"`{HISTORICAL_FIT_DIGEST}` vs recomputed persisted payload `{PERSISTED_PAYLOAD_DIGEST}`, "
        '`historical_digest_recomputed_match=false`.\n\n'
        'Reproduce: `python3 tools/training/audit_hierarchical_tree_sparsity.py`. '
        f'Baseline byte SHA256: `{digest}`.\n'
    )
    legacy.persist(args.output, {BASELINE_NAME: baseline}, summary)
    print(json.dumps({
        'schema': SCHEMA,
        'baseline_sha256': digest,
        'canonical_payload_sha256': stable_hash(baseline),
        'runtime_qualified_nodes': baseline['summary']['runtime_qualified_nodes'],
        'bb_runtime_observations': baseline['canonical_cells']['bb_facing_sb_iso5']['runtime_observations'],
        'co_runtime_observations': baseline['canonical_cells']['co_after_bb_fold']['runtime_observations'],
        'matrix_parity_with_issue388': parity['cells_match'],
        'train_hands_parsed': report['train_hands_parsed'],
    }))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
