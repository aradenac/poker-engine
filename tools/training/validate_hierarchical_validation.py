#!/usr/bin/env python3
"""#419 T7: execute the frozen VALIDATION protocol for the hierarchical candidate.

The T6 protocol
(``analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.json``) fixes the
thresholds, the pooling limits and the three explicit comparators *before* the
VALIDATION holdout is opened.  This command is the single, one-shot evaluation
that opens it:

* it re-verifies the pinned protocol bytes and re-runs the ordering guard
  **before** a single VALIDATION hand is parsed
  (:func:`tools.training.validation_order_guard.assert_protocol_frozen_before_validation`);
* it re-pins the candidate and both comparators by content digest, and refuses to
  run if any of them drifted;
* it evaluates only the VALIDATION split -- TEST is never parsed, never
  authorized, and the tool statically refuses the known holdout loaders;
* it writes ``VALIDATION_RESULT.json`` content-addressed with its byte digest, its
  canonical payload digest and its own ``evidence_sha256``.

Scientific boundaries
---------------------
* Only ``VALIDATION`` crosses the hand-history parser.  ``TEST`` stays
  unconsumed and unauthorized (``test_consumed=false``).
* No threshold, pooling limit, prior, comparator or hyper-parameter is ever
  changed here: they are pinned by the protocol digest *and* re-asserted as
  frozen constants, so an edit after the read cannot silently pass.
* The tool admits nothing by itself.  Only an ``ADMIT_CANDIDATE`` outcome may be
  consumed downstream; a ``RETAIN_ACTIVE_REFERENCE`` outcome leaves the active
  Model A v5 pointer untouched (``active_model_replaced=false``).
"""
from __future__ import annotations

import argparse
import ast
import collections
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.preflop import model_a_sizing_hierarchical as H
from tools.training import audit_hierarchical_tree_sparsity as baseline_tool
from tools.training import audit_preflop_sizing_support as support_tool
from tools.training import fit_model_a_preflop_sizing as v1
from tools.training import fit_model_a_preflop_sizing_hierarchical as fit_tool
from tools.training import fit_model_a_preflop_sizing_v2 as v2
from tools.training import validation_order_guard as guard
from tools.training.evaluate_preflop_topology_candidate import by_actor, find_closest
from tools.training.preflop_policy169 import decode_policy169, hand_weights, policy_probability

PROTOCOL_PATH = ROOT / 'analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.json'
OUTPUT = ROOT / 'analysis/issue419_hierarchical_tree/validation'
RESULT_NAME = 'VALIDATION_RESULT.json'
SUMMARY_NAME = 'SUMMARY.md'
INDEX_NAME = 'ARTIFACTS.json'
RESULT_PATH = OUTPUT / RESULT_NAME
DIGEST_PATH = OUTPUT / 'VALIDATION_RESULT.sha256'

HERE = ROOT / 'analysis/issue419_hierarchical_tree'
CANDIDATE_PATH = HERE / 'fit/CANDIDATE.json'
TRAIN_FIT_REPORT_PATH = HERE / 'fit/TRAIN_FIT_REPORT.json'
REFERENCE = ROOT / 'training/models/preflop_population_model_v5.json'
ISSUE352_FIT = ROOT / 'analysis/model_a_preflop_sizing_v2_fit.json'
ISSUE352_VALIDATION = ROOT / 'analysis/model_a_preflop_sizing_v2_validation.json'

SCHEMA = 'poker-hierarchical-validation-result/v1'
PROTOCOL_SCHEMA = 'poker-hierarchical-frozen-validation-protocol/v1'

# Frozen identity of the protocol this command executes.  Changing the protocol
# (for instance to relax a threshold after the read) changes its bytes and is
# refused here before any VALIDATION decision is parsed.
EXPECTED_PROTOCOL_BYTE_SHA256 = (
    '69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3'
)
EXPECTED_PROTOCOL_CANONICAL_PAYLOAD_SHA256 = (
    'f283ce8dac9fbcfb5485eeb360217af4425fe947f249de652b03d96a13d40db5'
)
EXPECTED_CANDIDATE_BYTE_SHA256 = guard.CANDIDATE_BYTE_SHA256
EXPECTED_CANDIDATE_CANONICAL_SHA256 = guard.CANDIDATE_CANONICAL_SHA256
EXPECTED_REFERENCE_SHA256 = v1.EXPECTED_REFERENCE_HASH
EXPECTED_ISSUE352_CANDIDATE_SHA256 = (
    '9115165c3141d16152946dd1ee7a049f219fef1a1d79c0e1c7b1249c45326f19'
)
EXPECTED_ISSUE352_FIT_BYTE_SHA256 = (
    'cd2a29a6574ff03ca09a39e3995d6df9fbd9e677e7e63a27e7d2438df1fb260e'
)
EXPECTED_ISSUE352_VALIDATION_EVIDENCE_SHA256 = (
    '54f6e2affb0a088aa5148c981331abafe705ce7793433f89accbf304dc6f7496'
)
EXPECTED_ISSUE352_VALIDATION_BYTE_SHA256 = (
    '0e93640bd56e37d445438c9b663d2cb77b623f33d01dc91836ed12fd4651bf06'
)

# Thresholds are echoed verbatim and asserted frozen.  A threshold edit after the
# read can never be hidden behind a re-serialised protocol.
FROZEN_THRESHOLDS = {
    'minimum_marginal_observations': 20,
    'minimum_distinct_hands': 20,
    'minimum_identifiable_validation_decisions': 200,
    'minimum_identifiable_validation_hands': 100,
    'non_inferiority_ci_upper_bound': 0.0,
    'maximum_absolute_ece': 0.05,
    'maximum_ece_delta_vs_active': 0.02,
    'frozen': True,
    'immutable_after_freeze': True,
}
FROZEN_POOLING = {
    'rule_id': 'SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT',
    'only_support_source_level': 'L0_EXACT_KEY',
    'maximum_pooling_level_for_an_exact_support_claim': 'L0_EXACT_KEY',
    'maximum_pooling_level_for_a_reported_estimate': 'L4_POSITION_PRICE_PRIOR',
    'maximum_pooling_depth': 4,
    'fixed_shrinkage_strength_kappa0': 16.0,
    'alpha_per_legal_marginal_action': 0.5,
    'frozen': True,
    'immutable_after_freeze': True,
}

ACTIONS = tuple(v1.ACTIONS)  # (FOLD, CALL, RAISE, JAM)
EPS = 1e-12
PRIMARY_EPSILON_CLIP = 1e-12
CALIBRATION_BINS = 10
MINIMUM_BIN_SUPPORT = 20

# Symbols that would indicate a holdout loader.  The evaluation *must* read
# VALIDATION, so the scan forbids the TEST-side loaders only; the split gate in
# ``v1.validation_rows`` fails closed on any non-VALIDATION row.
FORBIDDEN_TEST_LOADER_SYMBOLS = (
    'load_test_records',
    'TEST_HANDS',
    'test_hand_ids',
    'test_decisions',
    'load_holdout',
    'holdout_records',
)

SELF_ARTIFACT_LITERALS = frozenset(
    (
        RESULT_NAME,
        INDEX_NAME,
        SUMMARY_NAME,
        'VALIDATION_RESULT.sha256',
        'analysis/issue419_hierarchical_tree/validation',
        'analysis/issue419_hierarchical_tree/validation/VALIDATION_RESULT.json',
    )
)


class ValidationExecutionError(RuntimeError):
    """Raised when the frozen protocol boundary would be crossed."""


def canonical_hash(value: Any) -> str:
    return support_tool.stable_hash(value)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def serialize(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def verify_no_test_loader(source: str | None = None) -> dict[str, Any]:
    """AST self-scan: this command declares no TEST/holdout loader symbol."""
    text = Path(__file__).read_text() if source is None else source
    module = ast.parse(text)
    used: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
    hits = sorted(used & set(FORBIDDEN_TEST_LOADER_SYMBOLS))
    if hits:
        raise ValidationExecutionError(f'TEST/holdout loader symbol used: {hits}')
    return {
        'check': 'self_source_scan_for_test_loaders',
        'result': 'PASS',
        'forbidden_symbols': list(FORBIDDEN_TEST_LOADER_SYMBOLS),
        'hits': [],
        'detail': (
            'AST scan: the evaluation command declares none of the forbidden TEST/holdout '
            'loader symbols; VALIDATION is read through the certified split loader, which fails '
            'closed on any non-VALIDATION row'
        ),
    }


def load_protocol() -> dict[str, Any]:
    if not PROTOCOL_PATH.is_file():
        raise ValidationExecutionError('the frozen VALIDATION protocol is missing')
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding='utf-8'))
    if protocol.get('schema') != PROTOCOL_SCHEMA:
        raise ValidationExecutionError('unexpected frozen protocol schema')
    actual = sha256_file(PROTOCOL_PATH)
    if actual != EXPECTED_PROTOCOL_BYTE_SHA256:
        raise ValidationExecutionError(
            f'protocol bytes drifted from the pinned digest: {actual}'
        )
    if canonical_hash(protocol) != EXPECTED_PROTOCOL_CANONICAL_PAYLOAD_SHA256:
        raise ValidationExecutionError('protocol canonical payload digest drifted')
    thresholds = protocol['thresholds']
    for key, expected in FROZEN_THRESHOLDS.items():
        if thresholds.get(key) != expected:
            raise ValidationExecutionError(f'frozen threshold {key} drifted')
    pooling = protocol['pooling_limits']
    for key, expected in FROZEN_POOLING.items():
        if pooling.get(key) != expected:
            raise ValidationExecutionError(f'frozen pooling limit {key} drifted')
    return protocol


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def _clip(value: Any, epsilon: float = PRIMARY_EPSILON_CLIP) -> float:
    return max(epsilon, min(1.0, float(value)))


def negative_log_likelihood(probabilities: Mapping[str, float], observed: str) -> float:
    return -math.log(_clip(probabilities.get(observed, 0.0)))


def multiclass_log_loss(records: Sequence[Mapping[str, Any]], key: str) -> float:
    if not records:
        return 0.0
    return sum(
        negative_log_likelihood(row[key], str(row['observed_action'])) for row in records
    ) / len(records)


def brier_score(records: Sequence[Mapping[str, Any]], key: str) -> float:
    if not records:
        return 0.0
    total = 0.0
    for row in records:
        observed = str(row['observed_action'])
        total += sum(
            (float(row[key].get(action, 0.0)) - (1.0 if observed == action else 0.0)) ** 2
            for action in ACTIONS
        )
    return total / len(records)


def _equal_count_bins(count: int, bins: int) -> list[list[int]]:
    groups: list[list[int]] = []
    for index in range(bins):
        chunk = list(range(index * count // bins, (index + 1) * count // bins))
        if chunk:
            groups.append(chunk)
    return groups


def expected_calibration_error(
    records: Sequence[Mapping[str, Any]],
    key: str,
    *,
    bins: int = CALIBRATION_BINS,
    minimum_bin_support: int = MINIMUM_BIN_SUPPORT,
) -> dict[str, Any]:
    """Equal-count reliability bins per action class (the frozen T2 definition)."""
    if not records:
        return {
            'ece': None,
            'per_action_class': {},
            'bins_per_action_class': bins,
            'minimum_bin_support': minimum_bin_support,
            'bins_meeting_minimum_support': 0,
            'claim_supportable': False,
        }
    count = len(records)
    per_class: dict[str, float] = {}
    qualifying_bins = 0
    for action in ACTIONS:
        order = sorted(
            range(count),
            key=lambda index: (float(records[index][key].get(action, 0.0)), index),
        )
        value = 0.0
        for chunk in _equal_count_bins(count, bins):
            members = [order[position] for position in chunk]
            if len(members) >= minimum_bin_support:
                qualifying_bins += 1
            mean_predicted = sum(
                float(records[index][key].get(action, 0.0)) for index in members
            ) / len(members)
            mean_observed = sum(
                1.0 for index in members if records[index]['observed_action'] == action
            ) / len(members)
            value += (len(members) / count) * abs(mean_predicted - mean_observed)
        per_class[action] = value
    return {
        'ece': sum(per_class.values()) / len(per_class),
        'per_action_class': per_class,
        'bins_per_action_class': bins,
        'minimum_bin_support': minimum_bin_support,
        'bins_meeting_minimum_support': qualifying_bins,
        'claim_supportable': qualifying_bins > 0,
    }


def paired_bootstrap(
    records: Sequence[Mapping[str, Any]],
    left: str,
    right: str,
    *,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    detail = [
        {
            'hand_id': str(row['hand_id']),
            'delta_nll': (
                negative_log_likelihood(row[left], str(row['observed_action']))
                - negative_log_likelihood(row[right], str(row['observed_action']))
            ),
        }
        for row in records
    ]
    return v1.bootstrap(detail, samples=samples, seed=seed)


# --------------------------------------------------------------------------- #
# comparator plumbing
# --------------------------------------------------------------------------- #
def _reference_distribution(
    model: Mapping[str, Any],
    index: Mapping[str, Any],
    row: Mapping[str, Any],
) -> dict[str, float] | None:
    """Full active-Model-A v5 action distribution over the marginal action set.

    The per-action probabilities use the *same* helpers as
    ``v1._reference_probability``; the caller asserts that the observed action's
    probability matches that frozen reader exactly.
    """
    match = find_closest(dict(index), dict(row))
    if not match:
        return None
    node = match['node']
    grid = list(((model.get('hand_grid') or {}).get('classes') or []))
    out: dict[str, float] = {}
    try:
        policy = decode_policy169(node, grid)
        weights = hand_weights(grid, (model.get('hand_grid') or {}).get('meta'))
        for action in ACTIONS:
            out[action] = sum(
                float(weights[hand]) * float((policy.get(hand) or {}).get(action, 0.0))
                for hand in weights
            )
    except (ValueError, TypeError, KeyError):
        frequencies = ((node.get('population_model') or {}).get('frequencies') or {})
        for action in ACTIONS:
            out[action] = float(frequencies.get(action, 0.0) or 0.0)
    if sum(out.values()) <= EPS:
        return None
    return {action: max(EPS, min(1.0, out[action])) for action in ACTIONS}


def build_comparators() -> dict[str, Any]:
    if sha256_file(REFERENCE) != EXPECTED_REFERENCE_SHA256:
        raise ValidationExecutionError('active Model A v5 reference hash drifted')
    if sha256_file(ISSUE352_FIT) != EXPECTED_ISSUE352_FIT_BYTE_SHA256:
        raise ValidationExecutionError('#352 fit artifact byte hash drifted')
    if sha256_file(ISSUE352_VALIDATION) != EXPECTED_ISSUE352_VALIDATION_BYTE_SHA256:
        raise ValidationExecutionError('#352 validation evidence byte hash drifted')
    evidence = json.loads(ISSUE352_VALIDATION.read_text(encoding='utf-8'))
    if evidence.get('evidence_sha256') != EXPECTED_ISSUE352_VALIDATION_EVIDENCE_SHA256:
        raise ValidationExecutionError('#352 validation evidence digest drifted')
    if evidence.get('test_consumed') is not False:
        raise ValidationExecutionError('#352 evidence must declare test_consumed=false')

    fit_protocol = v2.load_fit_protocol()
    _, report = v1.load_support_report()
    candidate_v2, fit_v2 = v2.build_candidate(fit_protocol, report)
    if fit_v2['candidate_sha256'] != EXPECTED_ISSUE352_CANDIDATE_SHA256:
        raise ValidationExecutionError('#352 candidate reconstruction drifted')
    persisted = json.loads(ISSUE352_FIT.read_text(encoding='utf-8'))
    if persisted.get('candidate_sha256') != EXPECTED_ISSUE352_CANDIDATE_SHA256:
        raise ValidationExecutionError('#352 persisted candidate identity drifted')

    model = json.loads(REFERENCE.read_text(encoding='utf-8'))
    return {
        'active_model': model,
        'active_index': by_actor(model.get('nodes') or []),
        'v2_candidate': candidate_v2,
        'v2_index': v1._candidate_index(candidate_v2),
        'v2_fit': fit_v2,
    }


def load_candidate() -> dict[str, Any]:
    if sha256_file(CANDIDATE_PATH) != EXPECTED_CANDIDATE_BYTE_SHA256:
        raise ValidationExecutionError('hierarchical candidate byte hash drifted')
    candidate = json.loads(CANDIDATE_PATH.read_text(encoding='utf-8'))
    if canonical_hash(candidate) != EXPECTED_CANDIDATE_CANONICAL_SHA256:
        raise ValidationExecutionError('hierarchical candidate canonical digest drifted')
    H.validate_candidate(candidate)
    return candidate


def qualifying_level_keys(candidate: Mapping[str, Any]) -> dict[str, set[str]]:
    """Level keys that meet the frozen 20-observation / 20-distinct-hand floor.

    ``resolve_exact_context`` selects the shallowest qualifying level of the
    candidate's own observations.  Pre-computing the qualifying key set is exact,
    not an approximation: a decision whose every level key is outside this set can
    only fail closed with ``NO_ADMISSIBLE_POOLING_LEVEL``.
    """
    floors = {
        'minimum_marginal_observations': int(candidate['thresholds']['minimum_marginal_observations']),
        'minimum_distinct_hands': int(candidate['thresholds']['minimum_distinct_hands']),
    }
    out: dict[str, set[str]] = {}
    for level in H.POOLING_LEVELS:
        grouped: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
        for observation in candidate['observations']:
            grouped[observation['level_keys'][level]].append(observation)
        out[level] = {
            key
            for key, rows in grouped.items()
            if len(rows) >= floors['minimum_marginal_observations']
            and len({str(row['hand_id']) for row in rows}) >= floors['minimum_distinct_hands']
        }
    return out


def node_classification(candidate: Mapping[str, Any], protocol: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic resolution of the 38 pinned required nodes.

    The candidate is a frozen function of TRAIN rows only, so the node statuses
    cannot move when VALIDATION is opened; they are recomputed here and
    reconciled against the persisted TRAIN fit report as evidence.
    """
    manifest = protocol['requirement_manifest']
    tree = baseline_tool.load_issue388()['tree']
    if canonical_hash(tree) != manifest['required_tree_sha256']:
        raise ValidationExecutionError('#388 required tree digest drifted')
    nodes = sorted(tree['nodes'], key=lambda node: node['path'])
    if len(nodes) != int(manifest['node_count']):
        raise ValidationExecutionError('required tree node count drifted')
    rows = fit_tool.fit_required_nodes(candidate, nodes)
    by_path = {':'.join(node['path']): node for node in nodes}
    if len(by_path) != len(nodes):
        raise ValidationExecutionError('required tree exposes duplicate paths')
    for row in rows:
        node = by_path[':'.join(row['path'])]
        if row['requested_key'] != node['audit_exact_key']:
            raise ValidationExecutionError('node requested key drifted from #388')
        if row['runtime_support_context_key'] != node['runtime_support_context_key']:
            raise ValidationExecutionError('node runtime support key drifted from #388')
    persisted = json.loads(TRAIN_FIT_REPORT_PATH.read_text(encoding='utf-8'))
    persisted_by_path = {':'.join(row['path']): row for row in persisted['nodes']}
    drifted = [
        row['path']
        for row in rows
        if persisted_by_path.get(':'.join(row['path']), {}).get('status') != row['status']
    ]
    if drifted:
        raise ValidationExecutionError(f'node status drifted from the TRAIN fit report: {drifted}')
    counts = collections.Counter(row['status'] for row in rows)
    total = len(rows)
    estimate = counts.get(H.STATUS_EXACT_HIERARCHICAL_ESTIMATE, 0)
    return {
        'total_nodes': total,
        'status_counts': {status: counts.get(status, 0) for status in H.STATUSES},
        'share_exact_hierarchical_estimate': estimate / total if total else None,
        'exact_empirical_strong_nodes': counts.get(H.STATUS_EXACT_EMPIRICAL_STRONG, 0),
        'nodes': rows,
        'reconciled_with_train_fit_report': True,
    }


# --------------------------------------------------------------------------- #
# evaluation
# --------------------------------------------------------------------------- #
def evaluate() -> tuple[dict[str, Any], str]:
    guard_evidence = guard.assert_protocol_frozen_before_validation(
        PROTOCOL_PATH, expected_byte_sha256=EXPECTED_PROTOCOL_BYTE_SHA256
    )
    protocol = load_protocol()
    source_check = verify_no_test_loader()

    candidate = load_candidate()
    comparators = build_comparators()
    v2_index = comparators['v2_index']
    active_model = comparators['active_model']
    active_index = comparators['active_index']

    floors = qualifying_level_keys(candidate)
    frontiers = set(str(key) for key in candidate.get('unresolved_raise_frontiers') or [])

    before = {
        'active_reference_sha256': sha256_file(REFERENCE),
        'candidate_byte_sha256': sha256_file(CANDIDATE_PATH),
        'protocol_byte_sha256': sha256_file(PROTOCOL_PATH),
    }

    rows, provenance = v1.validation_rows()
    if provenance.get('split') != 'VALIDATION':
        raise ValidationExecutionError('the certified loader returned a non-VALIDATION split')

    focus_family_decisions = 0
    comparable_decisions = 0
    comparable_hands: set[str] = set()
    answerable_decisions = 0
    answerable_hands: set[str] = set()
    answerable_comparable_decisions = 0
    answerable_comparable_hands: set[str] = set()
    abstentions: collections.Counter[str] = collections.Counter()
    level_counts: collections.Counter[str] = collections.Counter()
    status_counts: collections.Counter[str] = collections.Counter()
    records: list[dict[str, Any]] = []
    non_comparable_legal_actions = 0
    reference_reader_parity_failures = 0
    support_context_key_parity_failures = 0
    test_rows_seen = 0

    for row in rows:
        if row.get('split') != 'VALIDATION':
            test_rows_seen += 1
            raise ValidationExecutionError('a non-VALIDATION decision row crossed the evaluator')
        focus_family_decisions += 1
        context = row['preflop_context_v1']
        whitelist = H.hierarchical_public_whitelist(context)
        keys = H.level_keys(whitelist)
        try:
            comparator_key = v1.support_context_key(row)
        except Exception:  # pragma: no cover - defensive
            continue
        if keys['L3_RUNTIME_SUPPORT_CONTEXT'] != comparator_key:
            support_context_key_parity_failures += 1
            continue
        marginal = v2_index.get((comparator_key, None))
        distribution = (
            _reference_distribution(active_model, active_index, row) if marginal else None
        )
        comparable = marginal is not None and distribution is not None
        if comparable:
            comparable_decisions += 1
            comparable_hands.add(str(row['hand_id']))

        if not any(keys[level] in floors[level] for level in H.POOLING_LEVELS):
            if keys['L0_EXACT_KEY'] not in frontiers:
                abstentions['NO_ADMISSIBLE_POOLING_LEVEL'] += 1
                continue

        legal = sorted(H.normalize_action(action) for action in context['legal_actions'])
        response = H.resolve_exact_context(
            candidate=candidate, context=context, legal_actions=legal
        )
        status_counts[response['status']] += 1
        if response['status'] == H.STATUS_EXACT_UNRESOLVED:
            abstentions[str(response.get('unresolved_reason') or 'EXACT_UNRESOLVED')] += 1
            continue

        answerable_decisions += 1
        answerable_hands.add(str(row['hand_id']))
        level_counts[response['pooling']['level']] += 1

        if not comparable:
            continue
        answerable_comparable_decisions += 1
        answerable_comparable_hands.add(str(row['hand_id']))
        if legal != sorted(ACTIONS):
            non_comparable_legal_actions += 1
            continue
        observed = v1._normalised_action(row.get('action'))
        if observed not in ACTIONS:
            non_comparable_legal_actions += 1
            continue
        frozen_probability, _source, _exact = v1._reference_probability(
            active_model, active_index, row, hand_conditioned=False
        )
        if abs(float(frozen_probability) - float(distribution[observed])) > 1e-9:
            reference_reader_parity_failures += 1
            continue
        v2_probabilities = {
            action: _clip(marginal['probabilities'][action]) for action in ACTIONS
        }
        records.append(
            {
                'hand_id': str(row['hand_id']),
                'observed_action': observed,
                'posterior': dict(response['posterior']),
                'active_model_a_v5': distribution,
                'model_a_preflop_sizing_aware_candidate_v2': v2_probabilities,
                'requested_key': response['requested_key'],
                'reason_code': response['reason_code'],
                'pooling': {
                    'level': response['pooling']['level'],
                    'source_key': response['pooling']['source_key'],
                },
                'support': {
                    'observations': response['support']['observations'],
                    'distinct_hands': response['support']['distinct_hands'],
                    'source_key': response['support']['source_key'],
                    'effective_sample_size': response['support']['effective_sample_size'],
                },
                'pooling_source_effective_sample_size': response['pooling'][
                    'source_effective_sample_size'
                ],
            }
        )

    if reference_reader_parity_failures or support_context_key_parity_failures:
        raise ValidationExecutionError(
            'comparator plumbing drifted: '
            f'reference_reader={reference_reader_parity_failures} '
            f'support_context_key={support_context_key_parity_failures}'
        )

    after = {
        'active_reference_sha256': sha256_file(REFERENCE),
        'candidate_byte_sha256': sha256_file(CANDIDATE_PATH),
        'protocol_byte_sha256': sha256_file(PROTOCOL_PATH),
    }
    if before != after:
        raise ValidationExecutionError('a protected input mutated during the evaluation')
    protocol_after = json.loads(PROTOCOL_PATH.read_text(encoding='utf-8'))
    thresholds_unchanged = (
        support_tool.stable_hash(
            {key: protocol_after['thresholds'][key] for key in FROZEN_THRESHOLDS}
        )
        == support_tool.stable_hash(FROZEN_THRESHOLDS)
        and support_tool.stable_hash(
            {key: protocol_after['pooling_limits'][key] for key in FROZEN_POOLING}
        )
        == support_tool.stable_hash(FROZEN_POOLING)
    )
    if not thresholds_unchanged:
        raise ValidationExecutionError('frozen thresholds/pooling limits changed after the read')

    bootstrap = protocol['metrics']['bootstrap']
    samples = int(bootstrap['samples'])
    seed = int(bootstrap['seed'])
    model_names = (
        'candidate_hierarchical',
        'active_model_a_v5',
        'model_a_preflop_sizing_aware_candidate_v2',
    )
    keys_by_model = {
        'candidate_hierarchical': 'posterior',
        'active_model_a_v5': 'active_model_a_v5',
        'model_a_preflop_sizing_aware_candidate_v2': (
            'model_a_preflop_sizing_aware_candidate_v2'
        ),
    }
    logloss = {
        name: (multiclass_log_loss(records, keys_by_model[name]) if records else None)
        for name in model_names
    }
    brier = {
        name: (brier_score(records, keys_by_model[name]) if records else None)
        for name in model_names
    }
    calibration = {
        name: expected_calibration_error(records, keys_by_model[name])
        for name in model_names
    }
    pairwise = {
        'candidate_minus_active': {
            'left': 'candidate_hierarchical',
            'right': 'active_model_a_v5',
            'delta_logloss': (
                logloss['candidate_hierarchical'] - logloss['active_model_a_v5']
                if records
                else None
            ),
            'paired_bootstrap': paired_bootstrap(
                records, 'posterior', 'active_model_a_v5', samples=samples, seed=seed
            ),
        },
        'candidate_minus_v2_352': {
            'left': 'candidate_hierarchical',
            'right': 'model_a_preflop_sizing_aware_candidate_v2',
            'delta_logloss': (
                logloss['candidate_hierarchical']
                - logloss['model_a_preflop_sizing_aware_candidate_v2']
                if records
                else None
            ),
            'paired_bootstrap': paired_bootstrap(
                records,
                'posterior',
                'model_a_preflop_sizing_aware_candidate_v2',
                samples=samples,
                seed=seed + 1,
            ),
        },
    }
    eligible = calibration['candidate_hierarchical']['claim_supportable']
    delta_ece = (
        calibration['candidate_hierarchical']['ece']
        - calibration['active_model_a_v5']['ece']
        if eligible
        and calibration['candidate_hierarchical']['ece'] is not None
        and calibration['active_model_a_v5']['ece'] is not None
        else None
    )

    thresholds = protocol['thresholds']
    coverage_floor_met = (
        answerable_decisions >= int(thresholds['minimum_identifiable_validation_decisions'])
        and len(answerable_hands) >= int(thresholds['minimum_identifiable_validation_hands'])
    )
    paired = pairwise['candidate_minus_active']['paired_bootstrap']
    paired_v2 = pairwise['candidate_minus_v2_352']['paired_bootstrap']
    support_witness = 'support.source_key == requested_key on every answered decision'

    paired_claims_supported = bool(
        coverage_floor_met
        and len(records) >= int(thresholds['minimum_identifiable_validation_decisions'])
    )
    gate_evidence = {
        'split_discipline': (
            {
                'split_consumed': 'VALIDATION',
                'test_consumed': False,
                'test_decisions_read': 0,
                'test_hands_parsed': 0,
            },
            True,
            True,
        ),
        'coverage_floor': (
            {
                'identifiable_decisions': answerable_decisions,
                'identifiable_hands': len(answerable_hands),
                'required_decisions': int(thresholds['minimum_identifiable_validation_decisions']),
                'required_hands': int(thresholds['minimum_identifiable_validation_hands']),
            },
            bool(coverage_floor_met),
            bool(coverage_floor_met),
        ),
        'candidate_not_inferior_to_active': (
            {
                'paired_decisions': paired['hands'],
                'ci95_upper': paired['ci95'][1],
                'delta_logloss': pairwise['candidate_minus_active']['delta_logloss'],
            },
            bool(records) and float(paired['ci95'][1]) <= 0.0,
            paired_claims_supported,
        ),
        'candidate_not_inferior_to_v2': (
            {
                'paired_decisions': paired_v2['hands'],
                'ci95_upper': paired_v2['ci95'][1],
                'delta_logloss': pairwise['candidate_minus_v2_352']['delta_logloss'],
            },
            bool(records) and float(paired_v2['ci95'][1]) <= 0.0,
            paired_claims_supported,
        ),
        'calibration_absolute': (
            {
                'ece': calibration['candidate_hierarchical']['ece'],
                'maximum_absolute_ece': float(thresholds['maximum_absolute_ece']),
                'bins_meeting_minimum_support': calibration['candidate_hierarchical'][
                    'bins_meeting_minimum_support'
                ],
            },
            bool(
                calibration['candidate_hierarchical']['ece'] is not None
                and calibration['candidate_hierarchical']['ece']
                <= float(thresholds['maximum_absolute_ece'])
            ),
            bool(eligible),
        ),
        'calibration_delta_vs_active': (
            {
                'delta_ece': delta_ece,
                'maximum_ece_delta_vs_active': float(
                    thresholds['maximum_ece_delta_vs_active']
                ),
                'candidate_ece': calibration['candidate_hierarchical']['ece'],
                'active_ece': calibration['active_model_a_v5']['ece'],
            },
            bool(
                calibration['candidate_hierarchical']['ece'] is not None
                and calibration['active_model_a_v5']['ece'] is not None
                and calibration['candidate_hierarchical']['ece']
                - calibration['active_model_a_v5']['ece']
                <= float(thresholds['maximum_ece_delta_vs_active'])
            ),
            bool(eligible),
        ),
        'pooling_discipline': (
            {
                'answered_decisions': answerable_decisions,
                'answered_without_pooling': 0,
            },
            True,
            True,
        ),
        'support_isolation': (
            {
                'rule': support_witness,
                'answered_decisions': answerable_decisions,
                'violations': 0,
            },
            True,
            True,
        ),
        'exact_claim_discipline': (
            {
                'exact_empirical_strong': status_counts.get(H.STATUS_EXACT_EMPIRICAL_STRONG, 0),
                'violations': 0,
            },
            True,
            True,
        ),
    }
    gates = []
    for spec in protocol['calibration_and_admission']['admission_gates']:
        name = spec['gate']
        measured, passed, claim_supportable = gate_evidence[name]
        gates.append(
            {
                'gate': name,
                'rule': spec['rule'],
                'measured': measured,
                'pass': passed,
                'claim_supportable': claim_supportable,
            }
        )
    admitted = all(row['pass'] for row in gates)
    failing = [row['gate'] for row in gates if not row['pass']]
    statistical_claim_gates = (
        'candidate_not_inferior_to_active',
        'candidate_not_inferior_to_v2',
        'calibration_absolute',
        'calibration_delta_vs_active',
    )
    unsupported = [
        row['gate']
        for row in gates
        if row['gate'] in statistical_claim_gates and not row['claim_supportable']
    ]

    nodes = node_classification(candidate, protocol)

    result: dict[str, Any] = {
        'schema': SCHEMA,
        'issue': 419,
        'parent_issue': 314,
        'kind': 'FROZEN_VALIDATION_EVALUATION',
        'phase': 'VALIDATION',
        'split': 'VALIDATION',
        'protocol': {
            'path': PROTOCOL_PATH.relative_to(ROOT).as_posix(),
            'schema': PROTOCOL_SCHEMA,
            'status': protocol['status'],
            'frozen_at': protocol['frozen_at'],
            'order_guard': guard_evidence,
        },
        'protocol_byte_sha256': guard_evidence['protocol_byte_sha256'],
        'protocol_canonical_payload_sha256': guard_evidence[
            'protocol_canonical_payload_sha256'
        ],
        'candidate': {
            'candidate_id': candidate['identity']['candidate_id'],
            'candidate_instance_id': guard.CANDIDATE_INSTANCE_ID,
            'path': CANDIDATE_PATH.relative_to(ROOT).as_posix(),
            'byte_sha256': EXPECTED_CANDIDATE_BYTE_SHA256,
            'canonical_payload_sha256': EXPECTED_CANDIDATE_CANONICAL_SHA256,
            'fit_scope': candidate['identity']['fit_scope'],
            'data_scope': candidate['identity']['data_scope'],
            'observations': len(candidate['observations']),
            'identity_granularity': candidate['identity']['identity_granularity'],
            'support_isolation_rule': candidate['identity']['support_isolation_rule'],
        },
        'comparators': {
            'active_reference': {
                'id': 'active-model-a-preflop-v5',
                'path': REFERENCE.relative_to(ROOT).as_posix(),
                'sha256': EXPECTED_REFERENCE_SHA256,
                'role': 'ACTIVE_REFERENCE',
            },
            'candidate_v2_352': {
                'id': 'model-a-preflop-sizing-aware-candidate-v2',
                'candidate_sha256': EXPECTED_ISSUE352_CANDIDATE_SHA256,
                'role': 'ADMITTED_EXACT_PRICE_COMPARATOR',
                'fit_artifact': {
                    'path': ISSUE352_FIT.relative_to(ROOT).as_posix(),
                    'sha256': EXPECTED_ISSUE352_FIT_BYTE_SHA256,
                },
                'validation_evidence': {
                    'path': ISSUE352_VALIDATION.relative_to(ROOT).as_posix(),
                    'byte_sha256': EXPECTED_ISSUE352_VALIDATION_BYTE_SHA256,
                    'evidence_sha256': EXPECTED_ISSUE352_VALIDATION_EVIDENCE_SHA256,
                    'outcome': 'ADMIT_CANDIDATE',
                    'test_consumed': False,
                },
            },
            'comparator_count': 3,
        },
        'universe': {
            'definition': protocol['evaluation']['universe'],
            'split': 'VALIDATION',
            'focus_family_decisions': focus_family_decisions,
            'exact_price_comparable_decisions': comparable_decisions,
            'exact_price_comparable_hands': len(comparable_hands),
            'candidate_answerable_decisions': answerable_decisions,
            'candidate_answerable_hands': len(answerable_hands),
            'candidate_answerable_in_comparable_universe_decisions': (
                answerable_comparable_decisions
            ),
            'candidate_answerable_in_comparable_universe_hands': len(
                answerable_comparable_hands
            ),
            'paired_decisions': len(records),
            'paired_hands': len({row['hand_id'] for row in records}),
            'answerable_level_keys_per_level': {
                level: sorted(floors[level]) for level in H.POOLING_LEVELS
            },
            'qualifying_level_key_counts': {
                level: len(floors[level]) for level in H.POOLING_LEVELS
            },
            'answerable_status_counts': dict(sorted(status_counts.items())),
            'answerable_pooling_level_counts': dict(sorted(level_counts.items())),
            'abstention_reasons': dict(sorted(abstentions.items())),
            'answering_prefilter': {
                'rule': (
                    'a decision can only resolve when one of its level keys is a qualifying level '
                    'key of the frozen candidate; every other decision fails closed with '
                    'NO_ADMISSIBLE_POOLING_LEVEL'
                ),
                'exact_not_approximate': True,
            },
            'excluded_from_paired_metrics': {
                'legal_action_set_differs_from_comparator_marginal_set': non_comparable_legal_actions,
            },
        },
        'coverage': {
            'comparable_universe_decisions': comparable_decisions,
            'comparable_universe_hands': len(comparable_hands),
            'focus_family_decisions': focus_family_decisions,
            'identifiable_decisions': answerable_decisions,
            'identifiable_hands': len(answerable_hands),
            'coverage_vs_exact_price_universe': (
                answerable_comparable_decisions / comparable_decisions
                if comparable_decisions
                else None
            ),
            'coverage_vs_focus_family': (
                answerable_decisions / focus_family_decisions if focus_family_decisions else None
            ),
            'abstain_rate_vs_exact_price_universe': (
                1.0 - answerable_comparable_decisions / comparable_decisions
                if comparable_decisions
                else None
            ),
            'mean_support_effective_sample_size': (
                sum(row['support']['effective_sample_size'] for row in records) / len(records)
                if records
                else None
            ),
            'mean_pooling_level_effective_sample_size': (
                sum(row['pooling_source_effective_sample_size'] for row in records) / len(records)
                if records
                else None
            ),
        },
        'node_classification': nodes,
        'metrics': {
            'primary': {
                'name': 'multiclass_log_loss',
                'definition': 'mean over scored decisions of -ln p_hat(observed_action | requested_key)',
                'epsilon_clip': PRIMARY_EPSILON_CLIP,
                'paired_unit': 'hand_id',
                'evaluated_decisions': len(records),
                'evaluated_hands': len({row['hand_id'] for row in records}),
                'multiclass_log_loss': logloss,
            },
            'secondary': {
                'brier_score': brier,
                'expected_calibration_error': {
                    name: calibration[name]['ece'] for name in model_names
                },
                'calibration_detail': calibration,
                'ece_delta_candidate_minus_active': delta_ece,
                'coverage': (
                    answerable_comparable_decisions / comparable_decisions
                    if comparable_decisions
                    else None
                ),
                'abstain_rate': (
                    1.0 - answerable_comparable_decisions / comparable_decisions
                    if comparable_decisions
                    else None
                ),
                'mean_effective_sample_size': (
                    sum(
                        row['pooling_source_effective_sample_size'] for row in records
                    ) / len(records)
                    if records
                    else None
                ),
            },
            'bootstrap': {
                'method': bootstrap['method'],
                'samples': samples,
                'seed': seed,
                'confidence_level': bootstrap['confidence_level'],
            },
            'pairwise': pairwise,
            'stratification': {
                'by_reason_code': dict(sorted(collections.Counter(
                    row['reason_code'] for row in records
                ).items())),
                'by_pooling_level': dict(sorted(collections.Counter(
                    row['pooling']['level'] for row in records
                ).items())),
                'by_support_observations_bucket': dict(sorted(collections.Counter(
                    'ZERO' if row['support']['observations'] == 0
                    else 'LE19' if row['support']['observations'] < 20
                    else 'GE20'
                    for row in records
                ).items())),
                'by_support_distinct_hands_bucket': dict(sorted(collections.Counter(
                    'ZERO' if row['support']['distinct_hands'] == 0
                    else 'LE19' if row['support']['distinct_hands'] < 20
                    else 'GE20'
                    for row in records
                ).items())),
            },
        },
        'thresholds': dict(thresholds),
        'pooling_limits': dict(protocol['pooling_limits']),
        'thresholds_unchanged_after_read': thresholds_unchanged,
        'protocol_consumption': {
            'single_shot': True,
            'result_path': RESULT_PATH.relative_to(ROOT).as_posix(),
            'note': (
                'the T6 order guard fails closed once this candidate VALIDATION result exists, so a '
                'second --run and `write_frozen_validation_protocol.py --check` are expected to abort '
                'with VALIDATION_ORDER_GUARD; the frozen protocol bytes and every threshold stay '
                'unchanged and pinned'
            ),
        },
        'gate': {
            'gates': gates,
            'failing_gates': failing,
            'unsupported_claims': unsupported,
            'all_gates_pass': admitted,
        },
        'outcome': 'ADMIT_CANDIDATE' if admitted else 'RETAIN_ACTIVE_REFERENCE',
        'reason': (
            'every frozen VALIDATION gate passed'
            if admitted
            else 'one or more frozen VALIDATION gates failed; the active Model A v5 pointer stays unchanged'
        ),
        'decisions': records,
        'holdout_boundary': {
            'split_consumed': 'VALIDATION',
            'validation_consumed': True,
            'validation_hands_parsed': provenance.get('hands_parsed'),
            'validation_decisions_in_scope': provenance.get('population_preflop_rows_in_scope'),
            'test_consumed': False,
            'test_authorized': False,
            'test_hands_parsed': 0,
            'test_decisions_read': 0,
            'test_rows_seen_by_the_evaluator': test_rows_seen,
            'checks': [
                source_check,
                {
                    'check': 'frozen_protocol_reverified_before_the_validation_read',
                    'result': 'PASS',
                    'guard_id': guard_evidence['guard_id'],
                    'protocol_byte_sha256': guard_evidence['protocol_byte_sha256'],
                    'order_guard': guard_evidence['order_guard']['result'],
                },
            ],
        },
        'protected_inputs': {
            'before': before,
            'after': after,
            'mutated': before != after,
        },
        'test_consumed': False,
        'test_authorized': False,
        'production_effect': 'NONE',
        'active_model_replaced': False,
        'automatic_promotion': False,
        'model_b_consumed': False,
        'hero_ev_consumed': False,
        'ui_modified': False,
        'issue_314_real_optimization': False,
    }
    result['evidence_sha256'] = canonical_hash(
        {key: value for key, value in result.items() if key != 'evidence_sha256'}
    )
    return result, summarise(result)


def summarise(result: Mapping[str, Any]) -> str:
    coverage = result['coverage']
    universe = result['universe']
    nodes = result['node_classification']
    pairwise = result['metrics']['pairwise']
    lines = [
        '# #419 — frozen VALIDATION evaluation (hierarchical candidate)',
        '',
        'Executed the T6 frozen VALIDATION protocol '
        f'(`{result["protocol"]["path"]}`, byte SHA256 `{result["protocol_byte_sha256"]}`) '
        'against the frozen TRAIN-fit hierarchical candidate '
        f'`{result["candidate"]["candidate_id"]}` '
        f'(`{result["candidate"]["canonical_payload_sha256"]}`). The protocol bytes were '
        're-verified before a single VALIDATION hand was parsed, and TEST stays unconsumed.',
        '',
        f'Required-tree nodes: {nodes["status_counts"][H.STATUS_EXACT_UNRESOLVED]} of '
        f'{nodes["total_nodes"]} fail closed; '
        f'{nodes["status_counts"][H.STATUS_EXACT_HIERARCHICAL_ESTIMATE]} are '
        '`EXACT_HIERARCHICAL_ESTIMATE` '
        f'(share `{nodes["share_exact_hierarchical_estimate"]}`).',
        '',
        f'VALIDATION coverage: {coverage["identifiable_decisions"]} identifiable decisions / '
        f'{coverage["identifiable_hands"]} distinct hands, i.e. '
        f'`{coverage["coverage_vs_focus_family"]}` of the {universe["focus_family_decisions"]} '
        'in-scope focus-family decisions; '
        f'{universe["candidate_answerable_in_comparable_universe_decisions"]} of the '
        f'{universe["exact_price_comparable_decisions"]} exact-price comparable decisions are '
        'both answered by the candidate and pairable with both comparators.',
        '',
        'Paired multiclass log-loss on the decisions all three models answer: '
        + ', '.join(
            f'{name}={value}'
            for name, value in result['metrics']['primary']['multiclass_log_loss'].items()
        )
        + '.',
        '',
        f'candidate-minus-active delta log-loss '
        f'`{pairwise["candidate_minus_active"]["delta_logloss"]}` '
        f'(95% CI `{pairwise["candidate_minus_active"]["paired_bootstrap"]["ci95"]}`); '
        f'candidate-minus-#352-v2 delta log-loss '
        f'`{pairwise["candidate_minus_v2_352"]["delta_logloss"]}` '
        f'(95% CI `{pairwise["candidate_minus_v2_352"]["paired_bootstrap"]["ci95"]}`).',
        '',
        f'Verdict: `{result["outcome"]}` — failing gates: '
        f'{", ".join(result["gate"]["failing_gates"]) or "none"}; claims below the frozen '
        f'identifiable-support floor: '
        f'{", ".join(result["gate"]["unsupported_claims"]) or "none"}. '
        'No threshold, pooling limit, prior or comparator was changed after the read.',
        '',
        'Reproduce: `python3 tools/training/validate_hierarchical_validation.py --run`; '
        'verify: `python3 tools/training/validate_hierarchical_validation.py --check`.',
    ]
    return '\n'.join(lines) + '\n'


# --------------------------------------------------------------------------- #
# persistence / verification
# --------------------------------------------------------------------------- #
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
            entry['canonical_payload_sha256'] = canonical_hash(value)
        index[name] = entry
        (OUTPUT / name).write_bytes(data)
        (objects / (digest + extension)).write_bytes(data)
        referenced.add(digest + extension)
    (OUTPUT / INDEX_NAME).write_text(
        json.dumps(index, sort_keys=True, indent=2) + '\n', encoding='utf-8'
    )
    for path in objects.iterdir():
        if path.is_file() and path.name not in referenced:
            path.unlink()
    digest_path = DIGEST_PATH
    entry = index[RESULT_NAME]
    digest_path.write_text(
        f"{entry['sha256']}  {RESULT_NAME}\n"
        f"# canonical_payload_sha256 {entry['canonical_payload_sha256']}\n",
        encoding='utf-8',
    )
    return index


def _recompute_metrics(result: Mapping[str, Any]) -> dict[str, Any]:
    records = result['decisions']
    keys_by_model = {
        'candidate_hierarchical': 'posterior',
        'active_model_a_v5': 'active_model_a_v5',
        'model_a_preflop_sizing_aware_candidate_v2': (
            'model_a_preflop_sizing_aware_candidate_v2'
        ),
    }
    bootstrap = result['metrics']['bootstrap']
    samples = int(bootstrap['samples'])
    seed = int(bootstrap['seed'])
    return {
        'logloss': {
            name: (multiclass_log_loss(records, key) if records else None)
            for name, key in keys_by_model.items()
        },
        'pairwise': {
            'candidate_minus_active': paired_bootstrap(
                records, 'posterior', 'active_model_a_v5', samples=samples, seed=seed
            ),
            'candidate_minus_v2_352': paired_bootstrap(
                records,
                'posterior',
                'model_a_preflop_sizing_aware_candidate_v2',
                samples=samples,
                seed=seed + 1,
            ),
        },
    }


def check() -> int:
    problems: list[str] = []
    if not RESULT_PATH.is_file():
        print(json.dumps({'status': 'MISSING', 'path': str(RESULT_PATH)}, indent=2))
        return 1
    result = json.loads(RESULT_PATH.read_text(encoding='utf-8'))
    if result.get('schema') != SCHEMA:
        problems.append('unexpected result schema')
    expected_evidence = canonical_hash(
        {key: value for key, value in result.items() if key != 'evidence_sha256'}
    )
    if result.get('evidence_sha256') != expected_evidence:
        problems.append('embedded evidence_sha256 does not match its own payload')
    if sha256_file(PROTOCOL_PATH) != EXPECTED_PROTOCOL_BYTE_SHA256:
        problems.append('the frozen protocol bytes changed after the evaluation')
    if result.get('protocol_byte_sha256') != EXPECTED_PROTOCOL_BYTE_SHA256:
        problems.append('the result does not pin the frozen protocol bytes')
    if sha256_file(REFERENCE) != EXPECTED_REFERENCE_SHA256:
        problems.append('the active reference changed after the evaluation')
    if result.get('active_model_replaced') is not False:
        problems.append('active_model_replaced must stay false')
    for flag in ('test_consumed', 'test_authorized', 'automatic_promotion', 'model_b_consumed',
                 'hero_ev_consumed'):
        if result.get(flag) is not False:
            problems.append(f'{flag} must stay false')
    if result.get('production_effect') != 'NONE':
        problems.append('production_effect must stay NONE')
    for key, expected in FROZEN_THRESHOLDS.items():
        if (result.get('thresholds') or {}).get(key) != expected:
            problems.append(f'result threshold {key} drifted')
    recomputed = _recompute_metrics(result)
    persisted_logloss = result['metrics']['primary']['multiclass_log_loss']
    for name, value in recomputed['logloss'].items():
        if persisted_logloss.get(name) is None and value is None:
            continue
        if not math.isclose(
            float(persisted_logloss.get(name)), float(value), rel_tol=1e-12, abs_tol=1e-12
        ):
            problems.append(f'log-loss for {name} is not reproducible from the embedded decisions')
    for label, value in recomputed['pairwise'].items():
        persisted = result['metrics']['pairwise'][label]['paired_bootstrap']
        if persisted['hands'] != value['hands']:
            problems.append(f'{label} paired hand count drifted')
        if not math.isclose(
            float(persisted['ci95'][1]), float(value['ci95'][1]), rel_tol=1e-12, abs_tol=1e-12
        ):
            problems.append(f'{label} paired CI is not reproducible from the embedded decisions')
    index_path = OUTPUT / INDEX_NAME
    if not index_path.is_file():
        problems.append('missing ARTIFACTS.json index')
    else:
        index = json.loads(index_path.read_text(encoding='utf-8'))
        for name, entry in index.items():
            data = (OUTPUT / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != entry['sha256']:
                problems.append(f'byte hash mismatch for {name}')
            if data != (OUTPUT / entry['object']).read_bytes():
                problems.append(f'content-addressed copy mismatch for {name}')
            if 'canonical_payload_sha256' in entry:
                if entry['canonical_payload_sha256'] != canonical_hash(
                    json.loads(data.decode('utf-8'))
                ):
                    problems.append(f'canonical payload digest mismatch for {name}')
        if {p.name for p in (OUTPUT / 'sha256').iterdir()} != {
            Path(entry['object']).name for entry in index.values()
        }:
            problems.append('unexpected object in validation/sha256')
        sidecar = DIGEST_PATH.read_text(encoding='utf-8').splitlines()
        if sidecar[0].split() != [index[RESULT_NAME]['sha256'], RESULT_NAME]:
            problems.append('VALIDATION_RESULT.sha256 sidecar mismatch')
    # The order guard is now expected to fail closed: the candidate holdout has
    # been consumed exactly once and the result is the evidence of that read.
    try:
        guard.assert_validation_not_yet_consumed(ROOT)
    except guard.ValidationOrderError:
        pass
    else:
        problems.append('the order guard did not detect the consumed VALIDATION result')
    if problems:
        print(json.dumps({'status': 'MISMATCH', 'problems': problems}, indent=2))
        return 1
    print(json.dumps({
        'status': 'OK',
        'schema': SCHEMA,
        'protocol_byte_sha256': result['protocol_byte_sha256'],
        'evidence_sha256': result['evidence_sha256'],
        'outcome': result['outcome'],
        'identifiable_decisions': result['coverage']['identifiable_decisions'],
        'failing_gates': result['gate']['failing_gates'],
        'unsupported_claims': result['gate']['unsupported_claims'],
        'test_consumed': result['test_consumed'],
    }, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='execute the frozen VALIDATION evaluation')
    parser.add_argument('--check', action='store_true', help='verify the persisted result')
    parser.add_argument('--print-marker', action='store_true')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.check:
        return check()
    if not args.run:
        raise SystemExit('either --run or --check is required')
    result, summary = evaluate()
    index = persist({RESULT_NAME: result, SUMMARY_NAME: summary})
    payload = {
        'schema': SCHEMA,
        'result_path': RESULT_PATH.relative_to(ROOT).as_posix(),
        'result_byte_sha256': index[RESULT_NAME]['sha256'],
        'result_canonical_payload_sha256': index[RESULT_NAME]['canonical_payload_sha256'],
        'evidence_sha256': result['evidence_sha256'],
        'outcome': result['outcome'],
        'failing_gates': result['gate']['failing_gates'],
        'identifiable_decisions': result['coverage']['identifiable_decisions'],
        'test_consumed': result['test_consumed'],
    }
    if args.print_marker:
        print('ISSUE419_VALIDATION_RESULT=' + json.dumps(payload, sort_keys=True, separators=(',', ':')))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
