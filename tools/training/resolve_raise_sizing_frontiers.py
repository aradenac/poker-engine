#!/usr/bin/env python3
"""#419: TRAIN-only resolution of the seven unresolved #388 raise-sizing frontiers.

#388 left the required response tree incomplete because seven RAISE decisions
carry reason ``EXACT_REFERENCE_RAISE_SIZING_UNAVAILABLE``. This tool re-derives
each frontier from the canonical fixture, re-derives its certified-TRAIN exact
structural support, and decides per frontier whether an *exactly supported*
raise target exists at its ``runtime_exact_preflop_node_key`` and whether the
required descendants are enumerable without a representative price.

The frozen #367 rule is authoritative and is not relaxed here:
``raise_sizing = #367 exact active structural node empirical translator;
missing node or LEGAL_MIN_FALLBACK is unresolved``. A frontier is therefore
``RESOLVED`` only when the active reference carries the exact structural node
*and* that node exposes a translatable raise-size statistic. No legal-minimum,
nearest-price, nearest-context, target-drift, or observed-empirical
substitution is emitted: ``admitted_target_bb`` stays ``null``.

Output is content-addressed into a **v2** bundle
(``analysis/issue419_hierarchical_tree/raise_sizing_frontiers_v2/``, schema
``poker-raise-sizing-frontier-resolution/v2``) and, when at least one frontier
stays unresolved, a distinct blocker is persisted. That blocker is a necessary
but *not* sufficient condition for closing the required tree and is independent
of the response model: the same reference nodes do carry response likelihoods
(``population_model`` / ``policy169_q_b64``) while carrying no raise sizing at
all.

The v1 bundle (``.../raise_sizing_frontiers/``, schema
``poker-raise-sizing-frontier-resolution/v1``, byte SHA256
``93e7e3ede0a69e6b3e35f40217bd53ff95d1fbbb847ca3fbc9181c0689d0152e``) is a
consumed, immutable evidence surface: it is only ever re-verified byte-for-byte
against the digests pinned below and is **never** a write target.  The blocker
semantics added after that bundle was frozen (the per-frontier
``RAISE_SIZING_UNRESOLVED_NO_NEAREST_PRICE`` blocker, its response-model
independence and its ``BLOCKS_REQUIRED_TREE_COMPLETE`` effect) therefore live
exclusively in the v2 revision.

TRAIN only: no VALIDATION/TEST hand is parsed, no active registry or reference
is mutated, and no candidate is admitted.
"""
from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import fingerprint, sha256_file
from tools.repro_preflop_fixture import FIXTURE_PATH, load_verified_reference
from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.model_a_continuation import (
    _empirical_raise_target, _preflop_decision, _semantic_trace, _stat_value,
)
from tools.training import audit_model_a_exact_tree as legacy
from tools.training import audit_hierarchical_tree_sparsity as issue419_baseline
from tools.training.audit_hierarchical_tree_sparsity import stable_hash

# The v1 bundle is frozen evidence: pinned, re-verified, never written.
V1_OUTPUT = ROOT / 'analysis/issue419_hierarchical_tree/raise_sizing_frontiers'
V1_ARTIFACT_NAME = 'RAISE_SIZING_FRONTIER_RESOLUTION.json'
V1_SCHEMA = 'poker-raise-sizing-frontier-resolution/v1'
V1_RESOLUTION_SHA256 = '93e7e3ede0a69e6b3e35f40217bd53ff95d1fbbb847ca3fbc9181c0689d0152e'
V1_RESOLUTION_CANONICAL_SHA256 = (
    '29b87a82533a69b083034035dd9e2867e4dcf68bea099324675be5441a8f8174'
)
V1_SUMMARY_SHA256 = 'cf092d67b1b09d604f1de14b6c9335de32e4bbbf30410d0b7d758ac40ccc850c'
V1_INDEX_SHA256 = '86ab23239979b9ee5a0e5cf4111cc7bc9525b417b567fb324699594fbc2ba3cf'

# This tool's only write target: the versioned v2 bundle.
OUTPUT = ROOT / 'analysis/issue419_hierarchical_tree/raise_sizing_frontiers_v2'
ARTIFACT_NAME = 'RAISE_SIZING_FRONTIER_RESOLUTION.json'
SCHEMA = 'poker-raise-sizing-frontier-resolution/v2'
SCENARIO_ISSUE = 321
UNRESOLVED_FRONTIERS = 7
FRONTIER_ACTION = 'RAISE'

# Statistic keys consumed by ``_empirical_raise_target`` in
# ``tools/simulation/model_a_continuation.py``. They are mirrored here so the
# support scan is explicit; the authoritative check remains the translator's
# own returned ``sizing_source``.
TRANSLATABLE_SIZING_KEYS = (
    'target_total_bb', 'raise_to_bb',
    'action_add_bb', 'raise_add_bb',
    'own_size_pot', 'raise_size_pot', 'action_size_pot',
)

# Blocking codes. Each unresolved frontier is explained by at least one.
REASON_NO_STRUCTURAL_NODE = 'NO_EXACT_REFERENCE_STRUCTURAL_NODE_AT_RUNTIME_EXACT_PREFLOP_NODE_KEY'
REASON_NO_SIZING_STAT = 'REFERENCE_NODE_PRESENT_BUT_NO_TRANSLATABLE_RAISE_SIZING_STAT'
REASON_FALLBACK = 'RUNTIME_TRANSLATOR_RETURNS_LEGAL_MIN_FALLBACK_NOT_EXACT_SUPPORT'
REASON_DESCENDANTS = 'DESCENDANT_CLOSURE_REQUIRES_EXACT_RAISE_TARGET'
OBSERVED_RAISES_NOT_ADMITTED = 'TRAIN_OBSERVED_RAISE_ACTIONS_NOT_ADMITTED_AS_A_PRICE'

SUBSTITUTIONS_FORBIDDEN = {
    'legal_minimum_fallback': False,
    'nearest_price': False,
    'nearest_context': False,
    'empirical_observed_target': False,
    'target_drift': False,
    'representative_price': False,
}

# The distinct, machine-readable blocker every unresolved frontier exposes. The
# value is the frozen #419 sizing abstention reason code (no nearest/representative
# price is ever substituted); it is mirrored here as a literal so this TRAIN-only
# audit stays independent of any response model or provider module.
BLOCKER_REASON_CODE = 'RAISE_SIZING_UNRESOLVED_NO_NEAREST_PRICE'
BLOCKER_CLASS = 'RAISE_SIZING_EXACT_SUPPORT'
# The frontier class is a *necessary* condition for tree closure: an unresolved
# frontier forces ``required_tree_complete=false`` regardless of any response
# likelihood, and never suffices to close the tree on its own.
REQUIRED_TREE_COMPLETE_EFFECT = 'BLOCKS_REQUIRED_TREE_COMPLETE'


def structural_projection(context: Mapping[str, Any]) -> dict[str, Any]:
    """The ``runtime_exact_preflop_node_key`` field projection, as given.

    This is the comparison form actually used by ``exact_preflop_node`` and by
    ``_empirical_raise_target`` at runtime: the live and all-in position lists
    keep the caller's (pre-order) sequence.
    """
    return {
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


def canonical_projection(context: Mapping[str, Any]) -> dict[str, Any]:
    """The #388 persisted form: ``public_context`` canonicalizes live/all-in order."""
    projection = structural_projection(context)
    projection['live_positions'] = sorted(projection['live_positions'])
    projection['all_in_positions'] = sorted(projection['all_in_positions'])
    return projection


def node_key(context: Mapping[str, Any]) -> str:
    """Decision/reference-form structural identity (pre-order lists)."""
    return 'MAPNODE_' + stable_hash(structural_projection(context))


def canonical_node_key(context: Mapping[str, Any]) -> str:
    """The ``runtime_exact_preflop_node_key`` exactly as #388 persists it."""
    return 'MAPNODE_' + stable_hash(canonical_projection(context))


def assert_key_contract(context: Mapping[str, Any]) -> str:
    """Prove both local projections reproduce the audit's persisted identity."""
    key = node_key(context)
    if key != legacy.runtime_exact_preflop_node_key(context):
        raise ValueError('structural projection drifted from the runtime node key')
    if canonical_node_key(context) != legacy.runtime_exact_preflop_node_key(
        legacy.public_context(context)
    ):
        raise ValueError('canonical projection drifted from the #388 persisted node key')
    return key


def translatable_sizing_keys(node: Mapping[str, Any]) -> list[str]:
    """Exact raise-size statistics the #367 translator could consume, if any."""
    present: list[str] = []
    containers = (node.get('continuous'), (node.get('population_model') or {}).get('continuous'))
    for container in containers:
        if not isinstance(container, Mapping):
            continue
        for key in TRANSLATABLE_SIZING_KEYS:
            if key in present:
                continue
            if _stat_value(container.get(key)) is not None:
                present.append(key)
    return present


def reference_structural_indexes(
    reference: Mapping[str, Any],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Both structural identities of the active reference node universe."""
    decision_form: dict[str, list[str]] = collections.defaultdict(list)
    persisted_form: dict[str, list[str]] = collections.defaultdict(list)
    for node in reference.get('nodes', []):
        context = node.get('context') or {}
        decision_form[node_key(context)].append(str(node['id']))
        persisted_form[canonical_node_key(context)].append(str(node['id']))
    return dict(decision_form), dict(persisted_form)


def count_reference_sizing_stat_nodes(reference: Mapping[str, Any]) -> dict[str, Any]:
    """Global scan: how many reference nodes carry any translatable raise sizing."""
    per_key = {key: 0 for key in TRANSLATABLE_SIZING_KEYS}
    nodes_with_sizing = 0
    for node in reference.get('nodes', []):
        present = translatable_sizing_keys(node)
        if present:
            nodes_with_sizing += 1
        for key in present:
            per_key[key] += 1
    return {
        'reference_nodes': len(reference.get('nodes', [])),
        'reference_nodes_with_translatable_raise_sizing': nodes_with_sizing,
        'translatable_sizing_key_node_counts': per_key,
    }


def rebuild_frontier_state(snapshot: Mapping[str, Any], scenario: Mapping[str, Any]) -> NoLimitHoldemState:
    """Replay the recorded public action log into a fresh canonical state."""
    state = NoLimitHoldemState(
        seats=scenario['seats'], button=scenario['button'],
        stacks_bb=scenario['starting_stacks_bb'],
        small_blind_bb=scenario['blinds_bb']['small'], big_blind_bb=scenario['blinds_bb']['big'],
    )
    for event in snapshot['action_log']:
        state.apply_action(
            str(event['player']), str(event['action']),
            target_total_bb=event.get('target_total_bb'),
        )
    recorded = {k: v for k, v in snapshot.items() if k != 'action_log'}
    if state.to_snapshot(include_log=False) != recorded:
        raise ValueError('frontier replay did not reproduce the recorded public state')
    return state


def frontier_decision(frontier: Mapping[str, Any], scenario: Mapping[str, Any]) -> dict[str, Any]:
    """Re-derive the exact preflop decision context of one frontier."""
    state = rebuild_frontier_state(frontier['public_state'], scenario)
    actor = state.next_actor
    if actor is None:
        raise ValueError('frontier node is not an open decision point')
    _, replay, history, _, _ = _semantic_trace(state)
    if replay.to_snapshot(include_log=False) != state.to_snapshot(include_log=False):
        raise ValueError('public replay diverged at frontier')
    return {
        'state': state, 'actor': actor,
        'decision': _preflop_decision(state, actor, history),
        'legal_view': state.legal_view(actor),
    }


def resolve_frontier(
    *,
    frontier: Mapping[str, Any],
    tree_node: Mapping[str, Any],
    issue388_cell: Mapping[str, Any],
    derived: Mapping[str, Any],
    reference: Mapping[str, Any],
    structural_indexes: tuple[Mapping[str, list[str]], Mapping[str, list[str]]],
    support_rows: Sequence[Mapping[str, Any]],
    decision_form_support_rows: Sequence[Mapping[str, Any]],
    sizing_scan: Mapping[str, Any],
) -> dict[str, Any]:
    """One frontier, analyzed individually and classified on the frozen rule."""
    if frontier['action'] != FRONTIER_ACTION:
        raise ValueError('unexpected frontier action')
    state, actor, decision = derived['state'], derived['actor'], derived['decision']
    key = assert_key_contract(decision)
    persisted_key = canonical_node_key(decision)
    if persisted_key != tree_node['runtime_exact_preflop_node_key']:
        raise ValueError('frontier decision does not reproduce the #388 node key')
    if persisted_key != issue388_cell['runtime_exact_preflop_node_key']:
        raise ValueError('frontier node key does not match the #388 support matrix')
    if issue388_cell['path'] != tree_node['path'] or issue388_cell['node_id'] != frontier['node_id']:
        raise ValueError('#388 matrix cell does not match the frontier node')
    view = derived['legal_view']
    engine_interval = [
        round(float(view['min_raise_to_bb']), 6), round(float(view['max_raise_to_bb']), 6),
    ]
    if engine_interval != [round(float(value), 6) for value in frontier['legal_target_interval_bb']]:
        raise ValueError('engine legal raise interval drifted from the #388 frontier record')

    decision_form_index, persisted_form_index = structural_indexes
    matches = sorted(decision_form_index.get(key, []))
    persisted_matches = sorted(persisted_form_index.get(persisted_key, []))
    if matches != persisted_matches:
        raise ValueError('the two structural node-key identities select different reference nodes')
    nodes_by_id = {str(node['id']): node for node in reference.get('nodes', [])}
    translator_node = legacy.exact_preflop_node(reference, decision)
    translator_node_id = None if translator_node is None else str(translator_node['id'])
    if translator_node_id is not None and translator_node_id not in matches:
        raise ValueError('runtime translator selected a node outside the exact structural match set')
    reference_node_evidence = None
    if translator_node is not None:
        observed = translator_node.get('population_observed') or {}
        reference_node_evidence = {
            'node_id': translator_node_id,
            'population_decisions': (translator_node.get('coverage') or {}).get('population_decisions'),
            'observed_action_counts': {
                str(action): int(stats.get('count', 0))
                for action, stats in sorted((observed.get('actions') or {}).items())
            },
            'has_response_likelihood_model': bool(translator_node.get('population_model')),
            'has_continuous_sizing_block': bool(
                translatable_sizing_keys(translator_node)
                or translator_node.get('continuous')
                or (translator_node.get('population_model') or {}).get('continuous')
            ),
            'role': (
                'the exact structural node answers the response-likelihood question; it carries no '
                'raise-size statistic, which is why sizing stays unresolved'
            ),
        }
    # The runtime translator's own verdict. Only its source label is retained;
    # its numeric fallback target is deliberately discarded, never persisted.
    if translator_node is None:
        runtime_sizing_source = 'MISSING_EXACT_REFERENCE_NODE'
    else:
        _, runtime_sizing_source = _empirical_raise_target(translator_node, state, actor)

    sizing_keys = sorted({k for node_id in matches for k in translatable_sizing_keys(nodes_by_id[node_id])})
    support = legacy.support_view(list(support_rows))
    if support != issue388_cell['runtime_exact_preflop_node_support']:
        raise ValueError('re-derived structural support does not match #388')
    decision_form_support = legacy.support_view(list(decision_form_support_rows))
    if decision_form_support != support:
        raise ValueError('decision-form structural support differs from the #388 identity')
    observed_raise_actions = int((support['actions']['counts'] or {}).get('RAISE', 0))

    reasons: list[str] = []
    if not matches:
        reasons.append(REASON_NO_STRUCTURAL_NODE)
    if not sizing_keys:
        reasons.append(REASON_NO_SIZING_STAT)
    if matches and not sizing_keys:
        reasons.append(REASON_FALLBACK)
    reasons.append(REASON_DESCENDANTS)
    resolved = bool(matches) and bool(sizing_keys) and runtime_sizing_source != 'LEGAL_MIN_FALLBACK'
    if resolved:
        raise ValueError(
            'frontier unexpectedly resolvable; this tool persists only an exact supported target'
        )
    # Each frontier is exposed as an explicit, independent blocker. It carries no
    # numeric target and no representative/nearest price, it is a property of the
    # active structural reference (never of a response model) and it forces
    # ``required_tree_complete=false`` while it stays unresolved.
    blocker = {
        'reason_code': BLOCKER_REASON_CODE,
        'blocker_class': BLOCKER_CLASS,
        'status': 'OPEN',
        'independent_of_the_response_model': True,
        'independent_of_the_response_model_scope': (
            'a property of the active structural reference node key, not of any '
            'response-likelihood model'
        ),
        'blocks_required_tree_complete': True,
        'blocks_what': 'required_tree_complete',
        'required_tree_complete': False,
        'necessary_for_tree_closure': True,
        'sufficient_for_tree_closure': False,
        'exactly_supported_target_bb': None,
        'admitted_target_bb': None,
        'representative_price_substituted': False,
        'nearest_price_substituted': False,
        'nearest_context_substituted': False,
        'legal_minimum_fallback_substituted': False,
    }
    return {
        'node_id': frontier['node_id'],
        'path': list(tree_node['path']),
        'action': frontier['action'],
        'issue388_reason': frontier['reason'],
        'issue388_descendants': frontier['descendants'],
        'issue388_expansion_rule': frontier['expansion_rule'],
        'legal_target_interval_bb': list(frontier['legal_target_interval_bb']),
        'legal_interval_reverified_from_engine': list(engine_interval),
        'runtime_exact_preflop_node_key': persisted_key,
        'runtime_exact_preflop_node_key_decision_form': key,
        'node_key_identities_agree': key == persisted_key,
        'node_key_canonicalization_note': (
            'The value persisted by #388 is the audit canonicalization: public_context() sorts '
            'live_positions/all_in_positions before hashing. exact_preflop_node compares the '
            'pre-order (PRE_ORDER) lists. Both identities were evaluated against the reference '
            'node universe and select the same node set here, so the resolution is '
            'identity-robust.'
        ),
        'structural_context': structural_projection(decision),
        'resolution_state': 'RESOLVED' if resolved else 'UNRESOLVED',
        'coded_reasons': reasons,
        'exact_support': {
            'reference_exact_structural_match_count': len(matches),
            'reference_node_ids': matches,
            'issue388_identity_reference_match_count': len(persisted_matches),
            'issue388_identity_reference_node_ids': persisted_matches,
            'runtime_translator_selected_node_id': translator_node_id,
            'translatable_sizing_stat_keys_present': sizing_keys,
            'runtime_translator_sizing_source': runtime_sizing_source,
            'reference_node_evidence': reference_node_evidence,
            'trained_reference_sizing_stat_nodes_total': (
                sizing_scan['reference_nodes_with_translatable_raise_sizing']
            ),
            'exactly_supported_target_bb': None,
            'admitted_target_bb': None,
            'representative_price_substituted': False,
            'nearest_price_substituted': False,
            'nearest_context_substituted': False,
            'legal_minimum_fallback_substituted': False,
        },
        'target_independence_of_structural_key': {
            'structural_key_is_price_independent': True,
            'explanation': (
                'For a fixed public state runtime_exact_preflop_node_key consumes history '
                'actions/positions, live and all-in positions, family, actor, table size and raise '
                'level only; it never consumes the raise amount. The existence question is therefore '
                'well posed for every target in the legal interval, and no unsearched target could '
                'unlock exact support at this node.'
            ),
        },
        'train_exact_structural_support': support,
        'train_structural_support_decision_form_crosscheck': {
            'observations': decision_form_support['observations'],
            'distinct_hands': decision_form_support['distinct_hands'],
            'action_counts': dict(decision_form_support['actions']['counts']),
            'identical_to_issue388_identity_support': decision_form_support == support,
        },
        'train_observed_raise_actions': observed_raise_actions,
        'train_observed_raise_targets': None,
        'blocker': blocker,
        'blocker_reason_code': BLOCKER_REASON_CODE,
        'independent_of_the_response_model': True,
        'blocks_required_tree_complete': True,
        'required_tree_complete': False,
        'coded_notes': (
            ([OBSERVED_RAISES_NOT_ADMITTED] if observed_raise_actions else [])
            + ['NO_EXACT_TARGET_EMITTED']
        ),
        'descendant_closure': {
            'issue388_requirement': frontier['descendants'],
            'enumerable_without_representative_price': False,
            'coded_reason': REASON_DESCENDANTS,
            'required_expansion_rule': frontier['expansion_rule'],
            'argument': (
                'Enumerating the required descendants requires applying RAISE at an exactly supported '
                'target and recursing to preflop closure. The target is not decorative: it sets the '
                'post-raise pot, the per-seat commitments and therefore the descendant public states '
                'themselves, so without it the descendant states cannot even be enumerated. No '
                'exactly supported target exists at this node key, and the pinned reference carries '
                'no translatable raise-size statistic at any node (0 of '
                f"{sizing_scan['reference_nodes']} nodes), so every downstream RAISE edge would also "
                'resolve to LEGAL_MIN_FALLBACK. The closure is therefore not enumerable under the '
                'frozen rule and stays explicitly unresolved instead of being pruned as zero mass.'
            ),
        },
    }


def unprotected(frontiers: Sequence[Mapping[str, Any]]) -> bool:
    """No frontier may carry a numeric target, derived price or the fallback."""
    for frontier in frontiers:
        support = frontier['exact_support']
        if support['exactly_supported_target_bb'] is not None:
            return True
        if support['admitted_target_bb'] is not None:
            return True
        if frontier['train_observed_raise_targets'] is not None:
            return True
        for flag in ('representative_price_substituted', 'nearest_price_substituted',
                     'nearest_context_substituted', 'legal_minimum_fallback_substituted'):
            if support[flag]:
                return True
        # The exposed blocker must never smuggle a target or a substituted price.
        blocker = frontier.get('blocker', {})
        if blocker.get('exactly_supported_target_bb') is not None:
            return True
        if blocker.get('admitted_target_bb') is not None:
            return True
        for flag in ('representative_price_substituted', 'nearest_price_substituted',
                     'nearest_context_substituted', 'legal_minimum_fallback_substituted'):
            if blocker.get(flag):
                return True
    return False


def verify_v1_custody() -> dict[str, Any]:
    """Re-derive the frozen v1 frontier digests; v1 is pinned, never rewritten."""
    expected = {
        V1_ARTIFACT_NAME: V1_RESOLUTION_SHA256,
        'SUMMARY.md': V1_SUMMARY_SHA256,
        'ARTIFACTS.json': V1_INDEX_SHA256,
    }
    indexed = {
        V1_ARTIFACT_NAME: V1_RESOLUTION_SHA256,
        'SUMMARY.md': V1_SUMMARY_SHA256,
    }
    digests: dict[str, str] = {}
    for name, pinned in expected.items():
        path = V1_OUTPUT / name
        if not path.is_file():
            raise ValueError(f'the frozen v1 raise-sizing artifact is missing: {path}')
        actual = sha256_file(path)
        if actual != pinned:
            raise ValueError(
                f'the frozen v1 raise-sizing artifact drifted: {name} {actual} != {pinned}'
            )
        digests[name] = actual
    index = json.loads((V1_OUTPUT / 'ARTIFACTS.json').read_text())
    for name, pinned in indexed.items():
        if str(index[name]['sha256']) != pinned:
            raise ValueError(f'the frozen v1 raise-sizing index disagrees on {name}')
        if (V1_OUTPUT / str(index[name]['object'])).read_bytes() != (V1_OUTPUT / name).read_bytes():
            raise ValueError(f'the frozen v1 raise-sizing object copy disagrees on {name}')
    payload = json.loads((V1_OUTPUT / V1_ARTIFACT_NAME).read_text())
    if payload.get('schema') != V1_SCHEMA:
        raise ValueError('the frozen v1 raise-sizing schema drifted')
    if stable_hash(payload) != V1_RESOLUTION_CANONICAL_SHA256:
        raise ValueError('the frozen v1 raise-sizing canonical payload drifted')
    if 'blocker' in payload.get('frontiers', [{}])[0]:
        raise ValueError('the frozen v1 raise-sizing bundle must not carry the v2 blocker')
    return {
        'check': 'frozen_v1_raise_sizing_frontier_bytes_re_derived',
        'result': 'PASS',
        'bundle': str(V1_OUTPUT.relative_to(ROOT)),
        'schema': V1_SCHEMA,
        'artifacts': digests,
        'canonical_payload_sha256': V1_RESOLUTION_CANONICAL_SHA256,
        'never_rewritten': True,
        'superseded_by': str(OUTPUT.relative_to(ROOT)) + '/' + ARTIFACT_NAME,
    }


def build_resolution(
    *,
    tree: Mapping[str, Any],
    sizing_scan: Mapping[str, Any],
    frontiers: list[dict[str, Any]],
    bundle: Mapping[str, Any],
    provenance: Mapping[str, Any],
    parity: Mapping[str, Any],
    protected_before: Mapping[str, str],
    protected_after: Mapping[str, str],
    v1_custody: Mapping[str, Any],
) -> dict[str, Any]:
    unresolved = [f for f in frontiers if f['resolution_state'] == 'UNRESOLVED']
    if len(frontiers) != UNRESOLVED_FRONTIERS:
        raise ValueError('frontier count mismatch')
    if len({f['node_id'] for f in frontiers}) != len(frontiers):
        raise ValueError('duplicate frontier node ids')
    if unprotected(frontiers):
        raise ValueError('a frontier leaked a target price')
    if not parity['structural_support_matches_issue388']:
        raise ValueError('TRAIN structural support does not reconcile with #388')
    if protected_before != protected_after:
        raise ValueError('active reference/registry mutation')
    blocker_reasons = sorted({r for f in unresolved for r in f['coded_reasons']})
    enumeration_complete = bool(tree.get('enumeration_complete'))
    # The frontier effect on tree completeness is propagated explicitly: as long
    # as any frontier is unresolved the required tree cannot be complete, while
    # clearing every frontier is necessary but not sufficient (the enumeration
    # must also be complete, which this TRAIN-only audit never claims).
    required_tree_complete = bool(not unresolved) and enumeration_complete
    if required_tree_complete:
        assert not unresolved and enumeration_complete
    return {
        'schema': SCHEMA,
        'revision': 'v2',
        'supersedes_schema': V1_SCHEMA,
        'supersedes_v1': copy.deepcopy(dict(v1_custody)),
        'issue': 419,
        'source_issue': 388,
        'scenario_issue': SCENARIO_ISSUE,
        'kind': 'TRAIN_ONLY_RAISE_SIZING_FRONTIER_RESOLUTION',
        'split_consumed': 'TRAIN',
        'validation_consumed': False,
        'test_consumed': False,
        'fixture_sha256': sha256_file(FIXTURE_PATH),
        'reference_sha256': sha256_file(legacy.REFERENCE),
        'reference_expected_sha256': legacy.EXPECTED_REFERENCE_HASH,
        'frozen_rule': {
            'raise_sizing': legacy.RULES['raise_sizing'],
            'nearest_price': legacy.RULES['nearest_price'],
            'nearest_context': legacy.RULES['nearest_context'],
            'target_drift': legacy.RULES['target_drift'],
            'zero_probability': legacy.RULES['zero_probability'],
            'substitutions_forbidden': copy.deepcopy(SUBSTITUTIONS_FORBIDDEN),
        },
        'key_contract': copy.deepcopy(tree['key_contract']['runtime_exact_preflop_node_key']),
        'frontiers_total': len(frontiers),
        'resolved_count': len(frontiers) - len(unresolved),
        'unresolved_count': len(unresolved),
        'unresolved_node_ids': [f['node_id'] for f in unresolved],
        'enumeration_complete': enumeration_complete,
        'required_tree_complete': required_tree_complete,
        'required_tree_complete_effect': {
            'required_tree_complete': required_tree_complete,
            'blocker_reason_code': BLOCKER_REASON_CODE,
            'blocker_class': BLOCKER_CLASS,
            'independent_of_the_response_model': True,
            'representative_price_substituted': False,
            'blocks_required_tree_complete': bool(unresolved),
            'effect': REQUIRED_TREE_COMPLETE_EFFECT if unresolved else 'NO_EFFECT',
            'blocking_frontier_count': len(unresolved),
            'blocking_frontier_node_ids': [f['node_id'] for f in unresolved],
            'frontiers_total': len(frontiers),
            'enumeration_complete': enumeration_complete,
            'necessary_for_tree_closure': True,
            'sufficient_for_tree_closure': False,
            'propagated_to': [
                'raise_sizing_frontiers.required_tree_complete',
                'exact_tree_preflight.required_tree_complete',
                'terminal_decision.required_tree_complete',
            ],
            'argument': (
                'Each unresolved RAISE frontier is a sizing/structural gap that no response model can '
                'close without a representative price: its descendant states depend on the raise '
                'target, so the required #388 tree stays open and required_tree_complete stays false '
                'until every frontier is exactly resolved and the enumeration is complete. Clearing '
                'the frontiers is necessary but not sufficient for closure.'
            ),
        },
        'blocker_persisted': bool(unresolved),
        'blocker_count': 1 if unresolved else 0,
        'blocker_reason_code': BLOCKER_REASON_CODE,
        'independent_of_the_response_model': True,
        'blockers': [{
            'blocker_id': 'UNRESOLVED_RAISE_SIZING_FRONTIER',
            'reason_code': BLOCKER_REASON_CODE,
            'blocker_class': BLOCKER_CLASS,
            'status': 'OPEN',
            'independent_of_response_model': True,
            'necessary_for_tree_closure': True,
            'sufficient_for_tree_closure': False,
            'blocks_required_tree_complete': bool(unresolved),
            'required_tree_complete': required_tree_complete,
            'distinct_from_blocker_classes': ['INSUFFICIENT_RUNTIME_SUPPORT_CONTEXT'],
            'frontier_count': len(unresolved),
            'frontier_node_ids': [f['node_id'] for f in unresolved],
            'coded_reasons': blocker_reasons,
            'frozen_rule': legacy.RULES['raise_sizing'],
            'closure_condition': (
                'Every required RAISE frontier must resolve to an exactly supported target whose '
                'descendant closure is enumerable without a representative price. Closing the tree '
                'also still requires the independent runtime-support-context conditions, so this '
                'blocker is necessary but not sufficient.'
            ),
            'response_model_independence': (
                'The same active reference nodes already carry response-likelihood state '
                '(population_model/frequencies, response_model_key, policy169_q_b64) while carrying '
                'no raise-size statistic at all; the sizing gap is therefore not a property of any '
                'response model and cannot be closed by one.'
            ),
            'not_authorized_here': (
                'This TRAIN-only audit neither fabricates a sizing estimator nor relaxes the rule; '
                'resolving the frontier requires a separately frozen exact raise-sizing estimator or '
                'an active reference that carries the exact structural node with translatable '
                'raise-size statistics.'
            ),
            'observed_evidence': {
                'reference_nodes': sizing_scan['reference_nodes'],
                'reference_nodes_with_translatable_raise_sizing': (
                    sizing_scan['reference_nodes_with_translatable_raise_sizing']
                ),
            },
        }],
        'sizing_scan': copy.deepcopy(dict(sizing_scan)),
        'frontiers': frontiers,
        'issue388_bindings': {
            'required_tree_sha256': issue419_baseline.ISSUE388_REQUIRED_TREE_SHA256,
            'required_tree_artifact_sha256': issue419_baseline.ISSUE388_REQUIRED_TREE_BYTE_SHA256,
            'train_support_sha256': issue419_baseline.ISSUE388_TRAIN_SUPPORT_SHA256,
            'decision_sha256': issue419_baseline.ISSUE388_DECISION_SHA256,
            'decision': bundle['decision']['decision'],
            'status': bundle['decision']['status'],
            'unresolved_sizing_frontier_count': len(tree['unresolved_sizing_frontiers']),
            'required_node_count': len(tree['nodes']),
            'train_hands_parsed': bundle['report']['train_hands_parsed'],
            'audit_tool_sha256': sha256_file(Path(legacy.__file__)),
        },
        'reproduction': {
            'tree_rederived_equal_issue388': True,
            'structural_support_parity_with_issue388': dict(parity),
            'train_hands_parsed': provenance['certified_split_counts']['TRAIN'],
            'train_hand_ids_fingerprint_sha256': fingerprint(provenance['train_hand_ids']),
        },
        'provenance': copy.deepcopy(dict(provenance['provenance'])),
        'protected_files_before_after_sha256': {
            'before': dict(protected_before), 'after': dict(protected_after),
            'unchanged': protected_before == protected_after,
        },
        'source_files_sha256': {
            str(path.relative_to(ROOT)): sha256_file(path) for path in sorted({
                Path(__file__), Path(legacy.__file__), Path(issue419_baseline.__file__),
                legacy.REFERENCE, FIXTURE_PATH,
                ROOT / 'tools/simulation/model_a_continuation.py',
                ROOT / 'tools/simulation/game_core.py',
                ROOT / 'tools/repro_preflop_fixture.py',
                ROOT / 'analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json',
                ROOT / 'analysis/issue388_exact_tree/TRAIN_RESPONSE_TREE_SUPPORT.json',
            })
        },
    }


def resolve() -> dict[str, Any]:
    """Full TRAIN-only derivation: rebuild every frontier and its TRAIN support."""
    bundle = issue419_baseline.load_issue388()
    issue419_baseline.verify_issue388_boundaries(bundle)
    tree = bundle['tree']
    if sha256_file(legacy.REFERENCE) != legacy.EXPECTED_REFERENCE_HASH:
        raise ValueError('reference SHA mismatch')
    reference = json.loads(legacy.REFERENCE.read_text())
    sizing_scan = count_reference_sizing_stat_nodes(reference)
    structural_indexes = reference_structural_indexes(reference)
    fixture = load_verified_reference(ROOT)
    scenario = fixture['scenario']
    nodes_by_id = {node['id']: node for node in tree['nodes']}
    cells_by_id = {cell['node_id']: cell for cell in bundle['report']['matrix']}

    records, provenance = legacy.load_train_records(legacy.DEFAULT_CERTIFICATION)
    rows, parsed_ids = issue419_baseline.parse_train_rows(records, provenance)
    frontier_keys = set()
    for frontier in tree['unresolved_sizing_frontiers']:
        decision = frontier_decision(frontier, scenario)['decision']
        frontier_keys.add(assert_key_contract(decision))
        frontier_keys.add(canonical_node_key(decision))
    structural_rows: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    decision_form_rows: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        persisted = legacy.runtime_exact_preflop_node_key(legacy.public_context(row))
        if persisted in frontier_keys:
            structural_rows[persisted].append(row)
        decision_form = node_key(row)
        if decision_form in frontier_keys:
            decision_form_rows[decision_form].append(row)
    if len(parsed_ids) != provenance['certified_split_counts']['TRAIN']:
        raise ValueError('certified TRAIN accounting mismatch')

    frontiers = []
    for frontier in tree['unresolved_sizing_frontiers']:
        derived = frontier_decision(frontier, scenario)
        frontiers.append(resolve_frontier(
            frontier=frontier,
            tree_node=nodes_by_id[frontier['node_id']],
            issue388_cell=cells_by_id[frontier['node_id']],
            derived=derived,
            reference=reference,
            structural_indexes=structural_indexes,
            support_rows=structural_rows[canonical_node_key(derived['decision'])],
            decision_form_support_rows=decision_form_rows[node_key(derived['decision'])],
            sizing_scan=sizing_scan,
        ))
    parity = {
        'structural_support_cells_compared': len(frontiers),
        'structural_support_matches_issue388': all(
            f['train_exact_structural_support']
            == cells_by_id[f['node_id']]['runtime_exact_preflop_node_support'] for f in frontiers
        ),
        'mismatches': [
            f['node_id'] for f in frontiers
            if f['train_exact_structural_support']
            != cells_by_id[f['node_id']]['runtime_exact_preflop_node_support']
        ],
    }
    protected = [
        ROOT / 'training/registry.json', ROOT / 'training/populations/registry.json',
        legacy.REFERENCE,
    ]
    v1_custody = verify_v1_custody()
    before = {str(p.relative_to(ROOT)): sha256_file(p) for p in protected}
    resolution = build_resolution(
        tree=tree, sizing_scan=sizing_scan, frontiers=frontiers, bundle=bundle,
        provenance={'certified_split_counts': provenance['certified_split_counts'],
                    'train_hand_ids': parsed_ids, 'provenance': provenance},
        parity=parity, protected_before=before, protected_after=before,
        v1_custody=v1_custody,
    )
    after = {str(p.relative_to(ROOT)): sha256_file(p) for p in protected}
    if before != after:
        raise ValueError('active reference/registry mutation')
    resolution['protected_files_before_after_sha256'] = {
        'before': before, 'after': after, 'unchanged': before == after,
    }
    return resolution


def persist(output: Path, artifacts: dict[str, Any], summary: str) -> None:
    """Content-addressed write into this tool's own **v2** artifact directory."""
    if output.resolve() == V1_OUTPUT.resolve():
        raise ValueError(
            f'refusing to write the frozen v1 raise-sizing bundle {V1_OUTPUT}'
        )
    output.mkdir(parents=True, exist_ok=True)
    objects = output / 'sha256'
    objects.mkdir(exist_ok=True)
    index: dict[str, Any] = {}
    referenced = set()
    for name, value in artifacts.items():
        data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
        digest = hashlib.sha256(data).hexdigest()
        (output / name).write_bytes(data)
        (objects / (digest + '.json')).write_bytes(data)
        index[name] = {'sha256': digest, 'canonical_payload_sha256': stable_hash(value),
                       'object': 'sha256/' + digest + '.json'}
        referenced.add(digest + '.json')
    data = summary.encode()
    digest = hashlib.sha256(data).hexdigest()
    (output / 'SUMMARY.md').write_bytes(data)
    (objects / (digest + '.md')).write_bytes(data)
    index['SUMMARY.md'] = {'sha256': digest, 'object': 'sha256/' + digest + '.md'}
    referenced.add(digest + '.md')
    (output / 'ARTIFACTS.json').write_text(json.dumps(index, sort_keys=True, indent=2) + '\n')
    for path in objects.iterdir():
        if path.is_file() and path.name not in referenced:
            path.unlink()


def summary_text(resolution: Mapping[str, Any]) -> str:
    unresolved = [f for f in resolution['frontiers'] if f['resolution_state'] == 'UNRESOLVED']
    frontier_list = ', '.join('`' + f['node_id'][:12] + '`' for f in unresolved)
    return '\n'.join([
        '# #419 — raise-sizing frontier resolution v2 (TRAIN only)',
        '',
        'This is the **v2** revision '
        f"(`schema={resolution['schema']}`), written to "
        f"`{OUTPUT.relative_to(ROOT)}/`. The superseded v1 bundle "
        f"(`raise_sizing_frontiers/{V1_ARTIFACT_NAME}`, byte SHA256 `{V1_RESOLUTION_SHA256}`) is "
        'frozen, consumed evidence: it is re-verified byte-for-byte and never rewritten. The '
        'per-frontier blocker below was added after v1 was frozen and therefore lives only here.',
        '',
        f"**{resolution['unresolved_count']} of {resolution['frontiers_total']} raise-sizing "
        'frontiers remain UNRESOLVED**; the required #388 tree stays open and no candidate is '
        'admitted.',
        '',
        f"Each of the {resolution['frontiers_total']} `EXACT_REFERENCE_RAISE_SIZING_UNAVAILABLE` "
        'frontiers was re-derived individually from the canonical fixture, and its certified-TRAIN '
        'exact structural support was recounted. Every frontier selects exactly one active '
        'reference node at its `runtime_exact_preflop_node_key`, but that node carries no '
        'translatable raise-size statistic, so the #367 exact translator returns '
        '`LEGAL_MIN_FALLBACK` — which the frozen rule does not admit.',
        '',
        'The pinned active reference has '
        f"{resolution['sizing_scan']['reference_nodes_with_translatable_raise_sizing']} of "
        f"{resolution['sizing_scan']['reference_nodes']} nodes carrying any translatable raise "
        'sizing (`target_total_bb`, `raise_to_bb`, `action_add_bb`, `raise_add_bb`, '
        '`own_size_pot`, `raise_size_pot`, `action_size_pot`). The structural node key is '
        'price-independent (it never consumes the raise amount), so no unsearched target could '
        'unlock exact support, and every downstream RAISE edge in any descendant closure would '
        'fall back as well. Descendants therefore stay '
        '`REQUIRED_UNRESOLVED_NOT_PRUNED_AS_ZERO_MASS`.',
        '',
        'No representative price, nearest price, nearest context, target drift, observed empirical '
        'raise target, or legal-minimum substitution is introduced: every frontier persists '
        '`exactly_supported_target_bb=null` and `admitted_target_bb=null`. TRAIN RAISE actions '
        'observed at some structural keys are recorded as counts only, never as a price.',
        '',
        'Every frontier is exposed as a distinct blocker '
        '`RAISE_SIZING_UNRESOLVED_NO_NEAREST_PRICE` (blocker id '
        '`UNRESOLVED_RAISE_SIZING_FRONTIER`, class `RAISE_SIZING_EXACT_SUPPORT`) with '
        '`independent_of_the_response_model=true`: it is necessary but not sufficient for tree '
        'closure and it forces `required_tree_complete=false` while it stays open. The same '
        'reference nodes already carry response likelihoods (`population_model`, '
        '`response_model_key`, `policy169_q_b64`) while carrying no raise sizing.',
        '',
        'No VALIDATION or TEST decision was parsed or evaluated (`split_consumed=TRAIN`, '
        '`validation_consumed=false`, `test_consumed=false`); active registries and the active '
        'reference are unchanged before/after. This artifact records evidence only; it admits '
        'nothing.',
        '',
        'Reproduce: `python3 tools/training/resolve_raise_sizing_frontiers.py`. '
        f'Unresolved frontiers: {frontier_list}.',
        '',
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    resolution = resolve()
    persist(args.output, {ARTIFACT_NAME: resolution}, summary_text(resolution))
    print(json.dumps({
        'schema': SCHEMA,
        'canonical_payload_sha256': stable_hash(resolution),
        'frontiers_total': resolution['frontiers_total'],
        'resolved_count': resolution['resolved_count'],
        'unresolved_count': resolution['unresolved_count'],
        'blocker_persisted': resolution['blocker_persisted'],
        'structural_support_parity_with_issue388': (
            resolution['reproduction']['structural_support_parity_with_issue388']
            ['structural_support_matches_issue388']
        ),
    }))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
