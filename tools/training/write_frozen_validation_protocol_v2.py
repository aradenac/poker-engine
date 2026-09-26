#!/usr/bin/env python3
"""#419: versioned v2 revision of the frozen hierarchical VALIDATION protocol.

The v1 protocol (``poker-hierarchical-frozen-validation-protocol/v1``) is frozen
byte-for-byte: its own payload pins the digest of the sibling generator
``tools/training/write_frozen_validation_protocol.py``, and the consumed
VALIDATION history, the T8 preflight and the T9/T10 terminal decision pin the v1
bytes.  A v1 *revision* therefore cannot be produced by editing the v1
generator: that would change a pinned digest and break the pre-registration.

This tool authors a **separate, explicitly versioned** artifact,
``FROZEN_VALIDATION_PROTOCOL_V2.json``
(``poker-hierarchical-frozen-validation-protocol/v2``), content-addressed under
``analysis/issue419_hierarchical_tree/validation_protocol_v2/``.  The revision is
**additive and interpretive**: it splits the protocol into two explicit layers
without touching a single threshold, comparator, gate or support rule.

* **Layer A - exact empirical support.**  ``EXACT_EMPIRICAL_STRONG`` is
  unchanged: ``L0_EXACT_KEY`` meeting both frozen thresholds (>= 20 marginal
  observations and >= 20 distinct hands), support never borrowed from another
  key, ``support.source_key == requested_key``.  No relabelling, no weakening.
* **Layer B - exact-context estimate admissibility.**  ``EXACT_HIERARCHICAL_
  ESTIMATE`` for the same exact requested key: key identity preserved, support
  still exclusively the requested key's rows (possibly zero), pooling strictly
  parametric over ``L1..L4``, mandatory effective-sample-size, uncertainty and
  pooling provenance, gated on the seven machine-readable layer-B gates
  (identity, pooling provenance, pooling level, effective sample size,
  uncertainty, calibration, raise-sizing frontier).

Amendment ``V2_AMENDMENT_1_CONDITIONAL_NODE_CLOSURE`` makes node closure explicit
and conditional: an exact-context estimate closes a required node if and only if
every frozen layer-B gate passes, and stays open otherwise with the failing
gate's ``REFUSED_*`` reason code.  The superseded v2 payload is kept
content-addressed under ``validation_protocol_v2/history/`` and cited by the
``amendments`` / ``revision_history`` blocks.  No threshold and no gate value
moved; every gate value is equal to or stricter than its v1 homologue.

The v2 payload records the v1 byte digest, the v1 canonical payload digest, the
v1 generator digest and every frozen v1 surface digest, and re-verifies them from
the persisted bytes on every build and every ``--check``.  The v1 bytes are never
rewritten, so the immutability claim is a *re-derivation*, not an assertion.

This artifact admits nothing.  It changes no model, no fit, no candidate, no
promotion and no production behaviour; it is a protocol/interpretation revision
only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SOURCE_PATH = Path(__file__).resolve()

from tools.training.audit_preflop_sizing_support import stable_hash

HERE = ROOT / 'analysis/issue419_hierarchical_tree'
OUT = HERE / 'validation_protocol_v2'
NAME = 'FROZEN_VALIDATION_PROTOCOL_V2.json'
DIGEST_NAME = 'FROZEN_VALIDATION_PROTOCOL_V2.sha256'
INDEX_NAME = 'ARTIFACTS.json'
SUMMARY_NAME = 'SUMMARY.md'
DIGEST_PATH = OUT / DIGEST_NAME

SCHEMA = 'poker-hierarchical-frozen-validation-protocol/v2'
KIND = 'FROZEN_VALIDATION_PROTOCOL_REVISION'
REVISION = 2
STATUS = 'AUTHORED_AFTER_VALIDATION_READ_NO_THRESHOLD_CHANGE'
DEFAULT_AUTHORED_AT = '2026-09-26T00:00:00Z'

V1_SCHEMA = 'poker-hierarchical-frozen-validation-protocol/v1'
V1_KIND = 'FROZEN_VALIDATION_PROTOCOL'
SPEC_SCHEMA = 'poker-hierarchical-exact-context-model-spec/v1'
CONTRACT_SCHEMA = 'poker-hierarchical-candidate-contract/v1'

# Amendment custody.  The first authored v2 payload said a node answered with
# an exact-context estimate ``does not close the node``.  Amendment 1 replaces
# that flat ``false`` with an explicit conjunction over the frozen layer-B
# gates, exactly as the v1 gates already require.  The superseded bytes are kept
# content-addressed under ``validation_protocol_v2/history/`` and are re-verified
# from disk on every build and every ``--check``.
SUPERSEDED_V2_BYTE_SHA256 = (
    '508a31ec8072a72ca573f65ac6b748e1ce5e67c639fd4388e472153b7ffa4320'
)
SUPERSEDED_V2_CANONICAL_SHA256 = (
    'a97391d2678d66a46cc7a8d2d0893a509c9c2564a5c420f4519d21c05216dd16'
)
SUPERSEDED_V2_AUTHORED_AT = '2026-09-26T00:00:00Z'
AMENDMENT_ID = 'V2_AMENDMENT_1_CONDITIONAL_NODE_CLOSURE'
AMENDED_AT = '2026-09-26T00:00:00Z'
HISTORY_DIR_NAME = 'history'
HISTORY_DIR = OUT / HISTORY_DIR_NAME
HISTORY_KEY = 'history'
HISTORY_OBJECT = f'{HISTORY_DIR_NAME}/{SUPERSEDED_V2_BYTE_SHA256}.json'
HISTORY_DIGEST_SIDECAR = f'{HISTORY_DIR_NAME}/{SUPERSEDED_V2_BYTE_SHA256}.sha256'

# The seven machine-readable layer-B admissibility gates.  Each gate is
# evaluated on the answered node; a node closes only when every gate passes, and
# the first failing gate is reported by its reason code.  No gate value may be
# more permissive than its v1 homologue: every comparison carries an explicit
# monotonicity so the v1/v2 guard is mechanical.
NODE_CLOSURE_RULE_ID = 'NODE_CLOSES_IFF_ALL_FROZEN_LAYER_B_GATES_PASS'
GATE_RAISE_SIZING_FRONTIER = 'RAISE_SIZING_FRONTIER'
GATE_REASON_CODES = (
    'REFUSED_EXACT_KEY_IDENTITY',
    'REFUSED_POOLING_PROVENANCE',
    'REFUSED_POOLING_LEVEL',
    'REFUSED_EFFECTIVE_SAMPLE_SIZE',
    'REFUSED_UNCERTAINTY',
    'REFUSED_CALIBRATION',
    'REFUSED_RAISE_SIZING_FRONTIER',
)

V1_PROTOCOL_PATH = HERE / 'FROZEN_VALIDATION_PROTOCOL.json'
V1_DIGEST_PATH = HERE / 'FROZEN_VALIDATION_PROTOCOL.sha256'
V1_BUNDLE = HERE / 'validation_protocol'
V1_BYTE_SHA256 = '69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3'
V1_CANONICAL_SHA256 = 'f283ce8dac9fbcfb5485eeb360217af4425fe947f249de652b03d96a13d40db5'
V1_GENERATOR_PATH = 'tools/training/write_frozen_validation_protocol.py'
V1_GENERATOR_SHA256 = '91332db8fb2d73d8affc5db270b77b4a69366eb88b33d14133d1656ec96be1b2'

SPEC_PATH = HERE / 'HIERARCHICAL_MODEL_SPEC.json'
CONTRACT_PATH = HERE / 'contract' / 'CANDIDATE_CONTRACT.json'
PROVIDER_SCHEMA_PATH = (
    ROOT / 'contracts/training/model-a-preflop-sizing-hierarchical-likelihood.schema.json'
)
CANDIDATE_ID = 'model-a-preflop-sizing-hierarchical-candidate-v1'
CANDIDATE_CANONICAL_SHA256 = (
    '637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999'
)
SUPPORT_ISOLATION_RULE = 'SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT'
RUNTIME_INVARIANT = 'support.source_key == requested_key'
ISSUE367_RULE_ID = 'ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE'
SUPPORT_LEVEL = 'L0_EXACT_KEY'
STATUS_EXACT_EMPIRICAL_STRONG = 'EXACT_EMPIRICAL_STRONG'
STATUS_EXACT_HIERARCHICAL_ESTIMATE = 'EXACT_HIERARCHICAL_ESTIMATE'
STATUS_EXACT_UNRESOLVED = 'EXACT_UNRESOLVED'
SUPPORT_LABEL_CHANGED = False

# Frozen v1 custody: every digest is the *persisted* one.  A build recomputes
# each value from the bytes on disk and fails closed on any drift, so the
# immutability claim is a re-derivation rather than a restatement.
FROZEN_V1_SURFACES = (
    ('analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.json',
     'FROZEN_V1_PROTOCOL_PAYLOAD',
     '69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3'),
    ('analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.sha256',
     'FROZEN_V1_PROTOCOL_DIGEST_SIDECAR',
     'e2e6d5f0d825ee814f2eaa81fba82e6b0f0ecc2bdb05c8cbc30f098d65f950f8'),
    ('analysis/issue419_hierarchical_tree/validation_protocol/FROZEN_VALIDATION_PROTOCOL.json',
     'FROZEN_V1_PROTOCOL_CONTENT_ADDRESSED_COPY',
     '69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3'),
    ('analysis/issue419_hierarchical_tree/validation_protocol/ARTIFACTS.json',
     'FROZEN_V1_PROTOCOL_BUNDLE_INDEX',
     '85cc57f3d4486cbd0adbdfea1d14d3e1deae85add888eaafdf3852253f21f8b8'),
    ('analysis/issue419_hierarchical_tree/validation_protocol/SUMMARY.md',
     'FROZEN_V1_PROTOCOL_BUNDLE_SUMMARY',
     '6d7672aa7c0b06d9127aadd45fb901b4f21e7e2a8143496bd23c489333ff8dee'),
    ('analysis/issue419_hierarchical_tree/validation/VALIDATION_RESULT.json',
     'CONSUMED_VALIDATION_HISTORY',
     '0b92e5a78ab3ee4cb581c33be351d6b52bcf4fcd8741ab907ebd6dd32ec6ef68'),
    ('analysis/issue419_hierarchical_tree/validation/ARTIFACTS.json',
     'CONSUMED_VALIDATION_BUNDLE_INDEX',
     '4d7081ae6806c5d6fee470b89f4b454e88360b1b18e2255a7c3e26b4eccafccd'),
    ('analysis/issue419_hierarchical_tree/exact_tree_preflight/EXACT_TREE_PREFLIGHT.json',
     'V1_EXACT_TREE_PREFLIGHT',
     'e86b7c6b57d170c0885f46734c41302dcc15608252dfbbd66bff62c258d5c65f'),
    ('analysis/issue419_hierarchical_tree/terminal_decision/DECISION.json',
     'V1_TERMINAL_DECISION',
     'ec010a541636e70eae7d5158611c0a47d9ae926785f50cbf55432f32b46d8cff'),
    ('analysis/issue419_hierarchical_tree/terminal_decision/ARTIFACTS.json',
     'V1_TERMINAL_DECISION_BUNDLE_INDEX',
     'ea5b385d7c692e03a0c87f5e60c4d3f2bb3496733faba089ae84d2279069f102'),
)

BOUND_IDENTITIES = (
    ('analysis/issue419_hierarchical_tree/HIERARCHICAL_MODEL_SPEC.json',
     'FROZEN_ARCHITECTURE_SPEC',
     '5be122e54e9ee07313a7efa0e0a6dbf4e195eceacf78287a9ac5a448964d105c'),
    ('analysis/issue419_hierarchical_tree/HIERARCHICAL_TREE_SPARSITY_BASELINE.json',
     'TRAIN_SPARSITY_BASELINE',
     'ef3995daaf5bc48a09f0785d574f7494754ad3904b87ecd2aa089b5be1b24a36'),
    ('analysis/issue419_hierarchical_tree/contract/CANDIDATE_CONTRACT.json',
     'CANDIDATE_PROVIDER_CONTRACT',
     '5d0fbcaf092f6ebb798df612b10a7e1b15940223b95f071281302b00c4f46a98'),
    ('contracts/training/model-a-preflop-sizing-hierarchical-likelihood.schema.json',
     'PROVIDER_LIKELIHOOD_SCHEMA',
     '10606463066cef6b843612b2404b74ee1a386f9d6aab0e0bf482b71eaa6e1799'),
)


class ProtocolV2Error(RuntimeError):
    """Raised when the v2 revision cannot be authored without a drift."""


def serialize(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _surface_rows(pins: tuple[tuple[str, str, str], ...]) -> list[dict[str, Any]]:
    rows = []
    for relative, role, expected in pins:
        path = ROOT / relative
        if not path.is_file():
            raise ProtocolV2Error(f'missing frozen surface {relative}')
        actual = sha256_file(path)
        if actual != expected:
            raise ProtocolV2Error(
                f'frozen v1 surface drifted: {relative} is {actual}, pinned {expected}'
            )
        rows.append({'path': relative, 'role': role, 'sha256': actual})
    return rows


def _not_more_permissive(*, value: Any, v1_value: Any, monotonicity: str) -> bool:
    """Mechanically decide whether a v2 value stays inside its v1 envelope.

    ``exact`` requires the v2 value to equal the v1 homologue (any drift is an
    undeclared change).  ``non_increasing`` is used where a *larger* number is
    more permissive (e.g. a maximum ECE); ``non_decreasing`` where a *smaller*
    number is more permissive (e.g. a minimum support).  ``superset`` requires
    the v2 forbidden list to contain every v1 entry, so a v2 list can only add
    prohibitions, never drop one.
    """
    if monotonicity == 'exact':
        return value == v1_value
    if monotonicity == 'non_increasing':
        return value <= v1_value
    if monotonicity == 'non_decreasing':
        return value >= v1_value
    if monotonicity == 'superset':
        return set(v1_value) <= set(value)
    raise ProtocolV2Error(f'unknown monotonicity {monotonicity!r}')


def _comparison(
    *,
    gate_id: str,
    field: str,
    value: Any,
    v1_value: Any,
    v1_source: str,
    monotonicity: str,
) -> dict[str, Any]:
    return {
        'gate_id': gate_id,
        'field': field,
        'value': value,
        'v1_value': v1_value,
        'v1_source': v1_source,
        'monotonicity': monotonicity,
        'not_more_permissive_than_v1': _not_more_permissive(
            value=value, v1_value=v1_value, monotonicity=monotonicity
        ),
    }


def _history_custody() -> dict[str, Any]:
    """Re-derive the superseded v2 bytes from the content-addressed history."""
    history_json = OUT / HISTORY_OBJECT
    history_sidecar = OUT / HISTORY_DIGEST_SIDECAR
    if not history_json.is_file():
        raise ProtocolV2Error(
            f'missing content-addressed history object {HISTORY_OBJECT}; the superseded '
            'v2 revision cannot be cited without its bytes'
        )
    actual = sha256_file(history_json)
    if actual != SUPERSEDED_V2_BYTE_SHA256:
        raise ProtocolV2Error(
            f'superseded v2 history bytes drifted: {actual} != {SUPERSEDED_V2_BYTE_SHA256}'
        )
    superseded = _load(history_json)
    if superseded.get('schema') != SCHEMA or int(superseded.get('revision', -1)) != REVISION:
        raise ProtocolV2Error('superseded v2 history object is not the v2 revision')
    if stable_hash(superseded) != SUPERSEDED_V2_CANONICAL_SHA256:
        raise ProtocolV2Error('superseded v2 history canonical payload drifted')
    if not history_sidecar.is_file():
        raise ProtocolV2Error(f'missing history digest sidecar {HISTORY_DIGEST_SIDECAR}')
    sidecar = history_sidecar.read_text(encoding='utf-8')
    if not sidecar.startswith(SUPERSEDED_V2_BYTE_SHA256 + '  '):
        raise ProtocolV2Error('history digest sidecar does not name the superseded digest')
    return {
        'object': HISTORY_OBJECT,
        'digest_sidecar': HISTORY_DIGEST_SIDECAR,
        'byte_sha256': actual,
        'canonical_payload_sha256': stable_hash(superseded),
        'schema': superseded['schema'],
        'revision': int(superseded['revision']),
        'authored_at': superseded.get('authored_at'),
        'sidecar_sha256': sha256_file(history_sidecar),
    }


def verify_v1_custody() -> dict[str, Any]:
    """Re-derive every v1 digest from the persisted bytes before authoring."""
    surfaces = _surface_rows(FROZEN_V1_SURFACES)
    identities = _surface_rows(BOUND_IDENTITIES)

    v1 = _load(V1_PROTOCOL_PATH)
    if v1.get('schema') != V1_SCHEMA:
        raise ProtocolV2Error('v1 schema drifted')
    if v1.get('kind') != V1_KIND:
        raise ProtocolV2Error('v1 kind drifted')
    if stable_hash(v1) != V1_CANONICAL_SHA256:
        raise ProtocolV2Error('v1 canonical payload digest drifted')
    if sha256_file(V1_PROTOCOL_PATH) != V1_BYTE_SHA256:
        raise ProtocolV2Error('v1 byte digest drifted')
    if sha256_file(ROOT / V1_GENERATOR_PATH) != V1_GENERATOR_SHA256:
        raise ProtocolV2Error(
            'the frozen v1 generator was edited; the v1 pre-registration is broken'
        )

    sidecar = V1_DIGEST_PATH.read_text(encoding='utf-8').splitlines()
    if sidecar[0].split() != [V1_BYTE_SHA256, 'FROZEN_VALIDATION_PROTOCOL.json']:
        raise ProtocolV2Error('v1 digest sidecar drifted')
    if sidecar[1].split() != ['#', 'canonical_payload_sha256', V1_CANONICAL_SHA256]:
        raise ProtocolV2Error('v1 canonical payload sidecar line drifted')

    index = _load(V1_BUNDLE / INDEX_NAME)
    entry = index.get('FROZEN_VALIDATION_PROTOCOL.json', {})
    if entry.get('sha256') != V1_BYTE_SHA256:
        raise ProtocolV2Error('v1 bundle index digest drifted')
    if entry.get('canonical_payload_sha256') != V1_CANONICAL_SHA256:
        raise ProtocolV2Error('v1 bundle index canonical digest drifted')

    v1_generator = next(
        row for row in v1['code']['inputs'] if row['role'] == 'PROTOCOL_GENERATOR'
    )
    if v1_generator['path'] != V1_GENERATOR_PATH or v1_generator['sha256'] != V1_GENERATOR_SHA256:
        raise ProtocolV2Error('v1 pins a different protocol generator')

    return {
        'v1': v1,
        'v1_surfaces': surfaces,
        'bound_identities': identities,
        'v1_sidecar_sha256': sha256_file(V1_DIGEST_PATH),
        'v1_bundle_index_sha256': sha256_file(V1_BUNDLE / INDEX_NAME),
        'validation_result_sha256': sha256_file(HERE / 'validation/VALIDATION_RESULT.json'),
    }


def _thresholds_from_v1(v1: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    thresholds = v1['thresholds']
    spec_thresholds = spec['decision_thresholds']
    if int(thresholds['minimum_marginal_observations']) != 20:
        raise ProtocolV2Error('v1 marginal-observation threshold is not 20')
    if int(thresholds['minimum_distinct_hands']) != 20:
        raise ProtocolV2Error('v1 distinct-hands threshold is not 20')
    if int(spec_thresholds['minimum_marginal_observations']) != 20:
        raise ProtocolV2Error('spec marginal-observation threshold is not 20')
    if int(spec_thresholds['minimum_distinct_hands']) != 20:
        raise ProtocolV2Error('spec distinct-hands threshold is not 20')
    return {
        'minimum_marginal_observations': int(thresholds['minimum_marginal_observations']),
        'minimum_distinct_hands': int(thresholds['minimum_distinct_hands']),
        'maximum_absolute_ece': thresholds['maximum_absolute_ece'],
        'maximum_ece_delta_vs_active': thresholds['maximum_ece_delta_vs_active'],
        'non_inferiority_ci_upper_bound': thresholds['non_inferiority_ci_upper_bound'],
        'minimum_identifiable_validation_decisions': int(
            thresholds['minimum_identifiable_validation_decisions']
        ),
        'minimum_identifiable_validation_hands': int(
            thresholds['minimum_identifiable_validation_hands']
        ),
        'exact_claim_requires': thresholds['exact_claim_requires'],
        'inherited_verbatim_from_v1': True,
        'inherited_from': 'FROZEN_VALIDATION_PROTOCOL.json#thresholds',
        'modified_by_this_revision': False,
        're_selected_after_reading_validation': False,
    }


def _pooling_from_v1(v1: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    pooling = v1['pooling_limits']
    shrinkage = spec['hierarchy_prior_shrinkage']
    levels = sorted(
        ({'level': row['level'], 'rank': row['rank'], 'purpose': row['purpose'],
          'support_source_allowed': row['support_source_allowed']}
         for row in pooling['acceptable_levels']),
        key=lambda row: row['rank'],
    )
    return {
        'rule_id': pooling['rule_id'],
        'statement': pooling['statement'],
        'only_support_source_level': pooling['only_support_source_level'],
        'maximum_pooling_level_for_an_exact_support_claim': (
            pooling['maximum_pooling_level_for_an_exact_support_claim']
        ),
        'maximum_pooling_level_for_a_reported_estimate': (
            pooling['maximum_pooling_level_for_a_reported_estimate']
        ),
        'kappa0': shrinkage['hierarchical_strength_kappa0'],
        'alpha_per_legal_marginal_action': shrinkage['base_prior'][
            'alpha_per_legal_marginal_action'
        ],
        'estimator': shrinkage['estimator'],
        'levels': levels,
        'inherited_verbatim_from_v1': True,
        'modified_by_this_revision': False,
    }


def _layer_b_gates(
    *,
    v1: Mapping[str, Any],
    spec: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    pooling: Mapping[str, Any],
    calibration: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """The seven machine-readable layer-B admissibility gates.

    Every gate carries its refusal reason code, the fields it enforces and an
    explicit ``not_more_permissive_than_v1`` comparison list so a v1/v2 guard can
    decide precedence mechanically instead of by prose.
    """
    never_mutualizable = list(spec['parameter_pooling']['axes']['never_mutualizable'])
    v1_thresholds = v1['thresholds']
    v1_pooling = v1['pooling_limits']
    v1_calibration = v1['calibration_and_admission']['calibration']
    v1_gate_rules = {
        row['gate']: row['rule']
        for row in v1['calibration_and_admission']['admission_gates']
    }
    v1_forbidden = list(v1_pooling['forbidden'])
    v1_max_level = v1_pooling['maximum_pooling_level_for_a_reported_estimate']
    v1_max_rank = max(
        row['rank'] for row in v1_pooling['acceptable_levels'] if row['allowed_in_validation_output']
    )
    sizing_rule = spec['raise_sizing_policy']
    forbidden_superset_of_v1 = _comparison(
        gate_id=GATE_RAISE_SIZING_FRONTIER,
        field='forbidden',
        value=list(sizing_rule['forbidden']),
        v1_value=[
            entry for entry in v1_forbidden
            if entry in ('nearest-price or nearest-context substitution', 'representative raise price')
        ],
        v1_source='FROZEN_VALIDATION_PROTOCOL.json#pooling_limits.forbidden',
        monotonicity='superset',
    )

    def identity_gate() -> dict[str, Any]:
        gate_id = 'EXACT_KEY_IDENTITY'
        return {
            'order': 1,
            'gate_id': gate_id,
            'reason_code': 'REFUSED_EXACT_KEY_IDENTITY',
            'dimension': 'identity',
            'applies_to': [STATUS_EXACT_EMPIRICAL_STRONG, STATUS_EXACT_HIERARCHICAL_ESTIMATE],
            'requirement': (
                'support.source_key == requested_key, support.borrowed_from_other_keys == false, '
                'and every never-mutualizable axis retained at every pooling level; any other '
                'support source raises COARSE_KEY_SUPPORT_LAUNDERING'
            ),
            'enforced_fields': [
                'requested_key',
                'support.source_key',
                'support.borrowed_from_other_keys',
                'pooling.retained_axes',
            ],
            'comparisons': [
                _comparison(
                    gate_id=gate_id,
                    field='support_source_key_equals_requested_key',
                    value=True,
                    v1_value=True,
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#calibration_and_admission.'
                    'admission_gates[support_isolation]',
                    monotonicity='exact',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='support_borrowed_from_other_keys',
                    value=False,
                    v1_value=False,
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#calibration_and_admission.'
                    'admission_gates[support_isolation]',
                    monotonicity='exact',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='only_support_source_level',
                    value=pooling['only_support_source_level'],
                    v1_value=v1_pooling['only_support_source_level'],
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#pooling_limits.only_support_source_level',
                    monotonicity='exact',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='never_mutualizable_axes_retained',
                    value=never_mutualizable,
                    v1_value=never_mutualizable,
                    v1_source='HIERARCHICAL_MODEL_SPEC.json#parameter_pooling.axes.never_mutualizable',
                    monotonicity='exact',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='violation_reason_code',
                    value=spec['support_isolation_rule']['violation_reason_code'],
                    v1_value=spec['support_isolation_rule']['violation_reason_code'],
                    v1_source='HIERARCHICAL_MODEL_SPEC.json#support_isolation_rule.violation_reason_code',
                    monotonicity='exact',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='forbidden',
                    value=['cross-key support borrowing', 'coarse-key support laundering'],
                    v1_value=[
                        entry for entry in v1_forbidden
                        if entry in ('cross-key support borrowing', 'coarse-key support laundering')
                    ],
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#pooling_limits.forbidden',
                    monotonicity='superset',
                ),
            ],
            'v1_homologues': [
                'FROZEN_VALIDATION_PROTOCOL.json#calibration_and_admission.admission_gates[support_isolation]',
                'FROZEN_VALIDATION_PROTOCOL.json#pooling_limits',
                'HIERARCHICAL_MODEL_SPEC.json#parameter_pooling.axes.never_mutualizable',
                'HIERARCHICAL_MODEL_SPEC.json#support_isolation_rule.violation_reason_code',
            ],
            'more_permissive_than_v1': False,
            'inherited_from_v1': True,
            'modified_by_this_revision': False,
            'closes_the_node_when_satisfied': True,
            'on_failure': {
                'node_closed': False,
                'reason_code': 'REFUSED_EXACT_KEY_IDENTITY',
                'issue367_consumption': 'REFUSED',
            },
        }

    def pooling_provenance_gate() -> dict[str, Any]:
        gate_id = 'POOLING_PROVENANCE'
        required = [
            'pooling.level',
            'pooling.source_key',
            'pooling.source_observations',
            'pooling.source_distinct_hands',
            'pooling.retained_axes',
            'pooling.pooled_axes',
        ]
        return {
            'order': 2,
            'gate_id': gate_id,
            'reason_code': 'REFUSED_POOLING_PROVENANCE',
            'dimension': 'provenance',
            'applies_to': [STATUS_EXACT_HIERARCHICAL_ESTIMATE],
            'requirement': (
                'an answered decision reports the pooling provenance actually used: pooling.level, '
                'pooling.source_key, the pooling source counts and the retained/pooled axes, so a '
                'reader can always tell which declared parent level supplied the prior'
            ),
            'enforced_fields': required,
            'comparisons': [
                _comparison(
                    gate_id=gate_id,
                    field='report_pooling_level_always',
                    value=bool(v1_calibration['report_pooling_level_always']),
                    v1_value=bool(v1_calibration['report_pooling_level_always']),
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#calibration_and_admission.'
                    'calibration.report_pooling_level_always',
                    monotonicity='exact',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='required_provenance_fields',
                    value=required,
                    v1_value=['pooling.level', 'pooling.source_key'],
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#calibration_and_admission.'
                    'admission_gates[pooling_discipline]',
                    monotonicity='superset',
                ),
            ],
            'v1_homologues': [
                'FROZEN_VALIDATION_PROTOCOL.json#calibration_and_admission.calibration'
                '.report_pooling_level_always',
                'FROZEN_VALIDATION_PROTOCOL.json#calibration_and_admission.'
                'admission_gates[pooling_discipline]',
            ],
            'more_permissive_than_v1': False,
            'inherited_from_v1': True,
            'modified_by_this_revision': False,
            'closes_the_node_when_satisfied': True,
            'on_failure': {
                'node_closed': False,
                'reason_code': 'REFUSED_POOLING_PROVENANCE',
                'issue367_consumption': 'REFUSED',
            },
        }

    def pooling_level_gate() -> dict[str, Any]:
        gate_id = 'POOLING_LEVEL'
        return {
            'order': 3,
            'gate_id': gate_id,
            'reason_code': 'REFUSED_POOLING_LEVEL',
            'dimension': 'pooling_level',
            'applies_to': [STATUS_EXACT_EMPIRICAL_STRONG, STATUS_EXACT_HIERARCHICAL_ESTIMATE],
            'requirement': (
                'the reported pooling.level is a declared level, EXACT_EMPIRICAL_STRONG is emitted '
                'only at L0_EXACT_KEY, and a reported estimate never pools deeper than '
                f"{pooling['maximum_pooling_level_for_a_reported_estimate']}"
            ),
            'enforced_fields': ['pooling.level'],
            'comparisons': [
                _comparison(
                    gate_id=gate_id,
                    field='maximum_level_for_a_reported_estimate',
                    value=pooling['maximum_pooling_level_for_a_reported_estimate'],
                    v1_value=v1_max_level,
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#pooling_limits.'
                    'maximum_pooling_level_for_a_reported_estimate',
                    monotonicity='exact',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='maximum_level_for_a_reported_estimate_rank',
                    value=max(row['rank'] for row in pooling['levels']),
                    v1_value=v1_max_rank,
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#pooling_limits.acceptable_levels[].rank',
                    monotonicity='non_increasing',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='maximum_pooling_depth',
                    value=int(v1_pooling['maximum_pooling_depth']),
                    v1_value=int(v1_pooling['maximum_pooling_depth']),
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#pooling_limits.maximum_pooling_depth',
                    monotonicity='non_increasing',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='exact_claim_requires_level',
                    value=pooling['maximum_pooling_level_for_an_exact_support_claim'],
                    v1_value=v1_pooling['maximum_pooling_level_for_an_exact_support_claim'],
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#pooling_limits.'
                    'maximum_pooling_level_for_an_exact_support_claim',
                    monotonicity='exact',
                ),
            ],
            'v1_homologues': ['FROZEN_VALIDATION_PROTOCOL.json#pooling_limits'],
            'more_permissive_than_v1': False,
            'inherited_from_v1': True,
            'modified_by_this_revision': False,
            'closes_the_node_when_satisfied': True,
            'on_failure': {
                'node_closed': False,
                'reason_code': 'REFUSED_POOLING_LEVEL',
                'issue367_consumption': 'REFUSED',
            },
        }

    def effective_sample_size_gate() -> dict[str, Any]:
        gate_id = 'EFFECTIVE_SAMPLE_SIZE'
        return {
            'order': 4,
            'gate_id': gate_id,
            'reason_code': 'REFUSED_EFFECTIVE_SAMPLE_SIZE',
            'dimension': 'effective_sample_size',
            'applies_to': [STATUS_EXACT_EMPIRICAL_STRONG, STATUS_EXACT_HIERARCHICAL_ESTIMATE],
            'requirement': (
                'support.effective_sample_size and pooling.source_effective_sample_size are '
                'reported, credited at the hand level (equal to distinct hands, because several '
                'decisions inside one hand are correlated), and never inflated by pooling'
            ),
            'enforced_fields': [
                'support.effective_sample_size',
                'pooling.source_effective_sample_size',
                'support.distinct_hands',
            ],
            'comparisons': [
                _comparison(
                    gate_id=gate_id,
                    field='effective_sample_size_credited_at_hand_level',
                    value=True,
                    v1_value=True,
                    v1_source='HIERARCHICAL_MODEL_SPEC.json#runtime_support_contract.'
                    'response_fields[support.effective_sample_size]',
                    monotonicity='exact',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='effective_sample_size_inflated_by_pooling',
                    value=False,
                    v1_value=False,
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#pooling_limits.statement',
                    monotonicity='exact',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='minimum_distinct_hands',
                    value=int(thresholds['minimum_distinct_hands']),
                    v1_value=int(v1_thresholds['minimum_distinct_hands']),
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#thresholds.minimum_distinct_hands',
                    monotonicity='non_decreasing',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='minimum_marginal_observations',
                    value=int(thresholds['minimum_marginal_observations']),
                    v1_value=int(v1_thresholds['minimum_marginal_observations']),
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#thresholds.minimum_marginal_observations',
                    monotonicity='non_decreasing',
                ),
            ],
            'v1_homologues': [
                'FROZEN_VALIDATION_PROTOCOL.json#thresholds',
                'FROZEN_VALIDATION_PROTOCOL.json#pooling_limits.statement',
            ],
            'more_permissive_than_v1': False,
            'inherited_from_v1': True,
            'modified_by_this_revision': False,
            'closes_the_node_when_satisfied': True,
            'on_failure': {
                'node_closed': False,
                'reason_code': 'REFUSED_EFFECTIVE_SAMPLE_SIZE',
                'issue367_consumption': 'REFUSED',
            },
        }

    def uncertainty_gate() -> dict[str, Any]:
        gate_id = 'UNCERTAINTY'
        return {
            'order': 5,
            'gate_id': gate_id,
            'reason_code': 'REFUSED_UNCERTAINTY',
            'dimension': 'uncertainty',
            'applies_to': [STATUS_EXACT_EMPIRICAL_STRONG, STATUS_EXACT_HIERARCHICAL_ESTIMATE],
            'requirement': (
                'the uncertainty band and the posterior are reported and reflect the level '
                'actually used, never the exact level alone; an estimate is never shown without '
                'its uncertainty or its pooling level'
            ),
            'enforced_fields': ['uncertainty', 'posterior', 'pooling.level'],
            'comparisons': [
                _comparison(
                    gate_id=gate_id,
                    field='uncertainty_reported',
                    value=True,
                    v1_value=True,
                    v1_source='HIERARCHICAL_MODEL_SPEC.json#runtime_support_contract.'
                    'response_fields[uncertainty]',
                    monotonicity='exact',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='uncertainty_reported_without_pooling_level',
                    value=False,
                    v1_value=False,
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#calibration_and_admission.'
                    'calibration.report_pooling_level_always',
                    monotonicity='exact',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='required_uncertainty_fields',
                    value=['uncertainty', 'posterior'],
                    v1_value=['uncertainty'],
                    v1_source='HIERARCHICAL_MODEL_SPEC.json#runtime_support_contract.response_fields',
                    monotonicity='superset',
                ),
            ],
            'v1_homologues': [
                'FROZEN_VALIDATION_PROTOCOL.json#calibration_and_admission.'
                'calibration.report_pooling_level_always',
                'HIERARCHICAL_MODEL_SPEC.json#runtime_support_contract.response_fields',
            ],
            'more_permissive_than_v1': False,
            'inherited_from_v1': True,
            'modified_by_this_revision': False,
            'closes_the_node_when_satisfied': True,
            'on_failure': {
                'node_closed': False,
                'reason_code': 'REFUSED_UNCERTAINTY',
                'issue367_consumption': 'REFUSED',
            },
        }

    def calibration_gate() -> dict[str, Any]:
        gate_id = 'CALIBRATION'
        return {
            'order': 6,
            'gate_id': gate_id,
            'reason_code': 'REFUSED_CALIBRATION',
            'dimension': 'calibration',
            'applies_to': [STATUS_EXACT_EMPIRICAL_STRONG, STATUS_EXACT_HIERARCHICAL_ESTIMATE],
            'requirement': (
                'the absolute calibration gate (pooled ECE <= maximum_absolute_ece) and the '
                'relative gate (candidate minus active ECE <= maximum_ece_delta_vs_active) hold, '
                'each reliability bin carries at least minimum_bin_support_for_a_calibration_claim '
                'observations, and a pooled estimate is never scored without its pooling level'
            ),
            'enforced_fields': ['reason_code', 'pooling.level', 'uncertainty'],
            'comparisons': [
                _comparison(
                    gate_id=gate_id,
                    field='maximum_absolute_ece',
                    value=thresholds['maximum_absolute_ece'],
                    v1_value=v1_thresholds['maximum_absolute_ece'],
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#thresholds.maximum_absolute_ece',
                    monotonicity='non_increasing',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='maximum_ece_delta_vs_active',
                    value=thresholds['maximum_ece_delta_vs_active'],
                    v1_value=v1_thresholds['maximum_ece_delta_vs_active'],
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#thresholds.maximum_ece_delta_vs_active',
                    monotonicity='non_increasing',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='minimum_bin_support_for_a_calibration_claim',
                    value=int(calibration['minimum_bin_support_for_a_calibration_claim']),
                    v1_value=int(v1_calibration['minimum_bin_support_for_a_calibration_claim']),
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#calibration_and_admission.'
                    'calibration.minimum_bin_support_for_a_calibration_claim',
                    monotonicity='non_decreasing',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='bins_per_action_class',
                    value=int(calibration['bins_per_action_class']),
                    v1_value=int(v1_calibration['bins_per_action_class']),
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#calibration_and_admission.'
                    'calibration.bins_per_action_class',
                    monotonicity='exact',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='report_pooling_level_always',
                    value=bool(calibration['report_pooling_level_always']),
                    v1_value=bool(v1_calibration['report_pooling_level_always']),
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#calibration_and_admission.'
                    'calibration.report_pooling_level_always',
                    monotonicity='exact',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='absolute_calibration_gate_present',
                    value='calibration_absolute' in v1_gate_rules,
                    v1_value='calibration_absolute' in v1_gate_rules,
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#calibration_and_admission.'
                    'admission_gates[calibration_absolute]',
                    monotonicity='exact',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='relative_calibration_gate_present',
                    value='calibration_delta_vs_active' in v1_gate_rules,
                    v1_value='calibration_delta_vs_active' in v1_gate_rules,
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#calibration_and_admission.'
                    'admission_gates[calibration_delta_vs_active]',
                    monotonicity='exact',
                ),
            ],
            'v1_homologues': [
                'FROZEN_VALIDATION_PROTOCOL.json#thresholds',
                'FROZEN_VALIDATION_PROTOCOL.json#calibration_and_admission',
            ],
            'more_permissive_than_v1': False,
            'inherited_from_v1': True,
            'modified_by_this_revision': False,
            'closes_the_node_when_satisfied': True,
            'on_failure': {
                'node_closed': False,
                'reason_code': 'REFUSED_CALIBRATION',
                'issue367_consumption': 'REFUSED',
            },
        }

    def raise_sizing_gate() -> dict[str, Any]:
        gate_id = GATE_RAISE_SIZING_FRONTIER
        return {
            'order': 7,
            'gate_id': gate_id,
            'reason_code': 'REFUSED_RAISE_SIZING_FRONTIER',
            'dimension': 'raise_sizing',
            'applies_to': [STATUS_EXACT_EMPIRICAL_STRONG, STATUS_EXACT_HIERARCHICAL_ESTIMATE],
            'requirement': (
                'raise sizing is exact-support-only: a raise target is emitted only when the exact '
                'structural node supports it, and a branch whose raise sizing is unresolved stays '
                'an explicit UNRESOLVED_SIZING_FRONTIER / EXACT_UNRESOLVED node, never filled by a '
                'representative, nearest, interpolated, legal-minimum or pruned price'
            ),
            'enforced_fields': ['raise_sizing', 'reason_code'],
            'comparisons': [
                _comparison(
                    gate_id=gate_id,
                    field='unresolved_frontier_closes_the_node',
                    value=False,
                    v1_value=False,
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#calibration_and_admission.'
                    'admission_gates[exact_claim_discipline]',
                    monotonicity='exact',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='representative_raise_price_forbidden',
                    value='representative raise price' in sizing_rule['forbidden'],
                    v1_value='representative raise price' in v1_forbidden,
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#pooling_limits.forbidden',
                    monotonicity='exact',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='nearest_price_substitution_forbidden',
                    value='nearest-price or nearest-context substitution' in sizing_rule['forbidden'],
                    v1_value='nearest-price or nearest-context substitution' in v1_forbidden,
                    v1_source='FROZEN_VALIDATION_PROTOCOL.json#pooling_limits.forbidden',
                    monotonicity='exact',
                ),
                _comparison(
                    gate_id=gate_id,
                    field='unresolved_frontier_state',
                    value=sizing_rule['unresolved_frontier']['state'],
                    v1_value=sizing_rule['unresolved_frontier']['state'],
                    v1_source='HIERARCHICAL_MODEL_SPEC.json#raise_sizing_policy.unresolved_frontier.state',
                    monotonicity='exact',
                ),
                forbidden_superset_of_v1,
            ],
            'v1_homologues': [
                'FROZEN_VALIDATION_PROTOCOL.json#pooling_limits.forbidden',
                'FROZEN_VALIDATION_PROTOCOL.json#calibration_and_admission.'
                'admission_gates[exact_claim_discipline]',
            ],
            'more_permissive_than_v1': False,
            'inherited_from_v1': True,
            'modified_by_this_revision': False,
            'closes_the_node_when_satisfied': True,
            'on_failure': {
                'node_closed': False,
                'reason_code': 'REFUSED_RAISE_SIZING_FRONTIER',
                'issue367_consumption': 'REFUSED',
            },
        }

    gates = [
        identity_gate(),
        pooling_provenance_gate(),
        pooling_level_gate(),
        effective_sample_size_gate(),
        uncertainty_gate(),
        calibration_gate(),
        raise_sizing_gate(),
    ]
    if [row['reason_code'] for row in gates] != list(GATE_REASON_CODES):
        raise ProtocolV2Error('layer-B gate reason codes drifted from the frozen set')
    for row in gates:
        if any(not comparison['not_more_permissive_than_v1'] for comparison in row['comparisons']):
            raise ProtocolV2Error(
                f"layer-B gate {row['gate_id']} is more permissive than its v1 homologue"
            )
    return gates


def _layers(
    *,
    v1: Mapping[str, Any],
    spec: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    pooling: Mapping[str, Any],
) -> dict[str, Any]:
    axes = spec['parameter_pooling']['axes']
    never_mutualizable = list(axes['never_mutualizable'])
    response_fields = {
        row['field']: row for row in spec['runtime_support_contract']['response_fields']
    }

    def field(field_name: str) -> dict[str, Any]:
        row = response_fields[field_name]
        return {'field': field_name, 'type': row['type'], 'meaning': row['meaning']}

    calibration = v1['calibration_and_admission']['calibration']
    gates = _layer_b_gates(
        v1=v1, spec=spec, thresholds=thresholds, pooling=pooling, calibration=calibration
    )
    gate_ids = [row['gate_id'] for row in gates]
    comparisons = [row for gate in gates for row in gate['comparisons']]
    return {
        'layer_a_exact_empirical_support': {
            'layer_id': 'EXACT_EMPIRICAL_SUPPORT',
            'role': (
                'defines what counts as exact empirical support for a requested key; this layer is '
                'the v1 empirical-support definition, restated and never relaxed'
            ),
            'status_label': STATUS_EXACT_EMPIRICAL_STRONG,
            'status_label_changed_by_this_revision': SUPPORT_LABEL_CHANGED,
            'relabelled_from_pooled_support_allowed': False,
            'identity_granularity': 'hierarchical_exact_key',
            'support_level': SUPPORT_LEVEL,
            'support_source': 'requested_key only',
            'support_isolation_rule': SUPPORT_ISOLATION_RULE,
            'runtime_invariant': RUNTIME_INVARIANT,
            'support_never_borrowed': True,
            'exact_claim_requires': thresholds['exact_claim_requires'],
            'thresholds': {
                'minimum_marginal_observations': thresholds['minimum_marginal_observations'],
                'minimum_distinct_hands': thresholds['minimum_distinct_hands'],
                'inherited_verbatim_from_v1': True,
                'modified_by_this_revision': False,
            },
            'pooling_allowed_for_the_reported_estimate': False,
            'counts_from_other_levels_allowed': False,
            'invariants': [
                'exact support is claimed only at L0_EXACT_KEY, never at a pooled level',
                'a parent level never makes a child node exact',
                'support counts are exact and are never smoothed across levels',
                'a pooled estimate is never relabelled EXACT_EMPIRICAL_STRONG',
            ],
            'source': (
                'FROZEN_VALIDATION_PROTOCOL.json#thresholds + #pooling_limits + '
                'HIERARCHICAL_MODEL_SPEC.json#runtime_support_contract'
            ),
        },
        'layer_b_exact_context_estimate_admissibility': {
            'layer_id': 'EXACT_CONTEXT_ESTIMATE_ADMISSIBILITY',
            'role': (
                'defines when a hierarchical estimate for the exact requested context is admissible; '
                'it adds explicit admissibility obligations to the v1 status, it changes no threshold'
            ),
            'status_label': STATUS_EXACT_HIERARCHICAL_ESTIMATE,
            'applies_to': 'the requested hierarchical_exact_key whose own support may be empty',
            'identity_preserved': True,
            'identity_granularity': 'hierarchical_exact_key',
            'identity_axes_retained_at_every_level': never_mutualizable,
            'identity_axes_never_mutualizable': True,
            'support_isolation_rule': SUPPORT_ISOLATION_RULE,
            'runtime_invariant': RUNTIME_INVARIANT,
            'support_source': (
                'requested_key only (support counts stay exact and are possibly zero)'
            ),
            'support_counted_from_pooled_levels': False,
            'counts_as_exact_support': False,
            'counts_as_a_closed_exact_tree_node': {
                'value': 'CONDITIONAL',
                'conditionally_closes': True,
                'unconditionally_closes': False,
                'true_iff_all_layer_b_gates_pass': True,
                'false_if_any_layer_b_gate_fails': True,
                'false_when_unresolved': True,
                'default_when_a_gate_is_unevaluated': False,
                'gate_ids': gate_ids,
                'reason_code_on_refusal': (
                    'the reason_code of the first failing layer-B gate, from '
                    'layer_b_admissibility_gates[].reason_code'
                ),
                'closure_rule_id': NODE_CLOSURE_RULE_ID,
            },
            'node_closure': {
                'rule_id': NODE_CLOSURE_RULE_ID,
                'question': (
                    'does the answer of this exact-context node close the node, and may #367 '
                    'consume it?'
                ),
                'closed_iff': (
                    'every gate in layer_b_admissibility_gates passes for the node answer with its '
                    'frozen values; the node stays open when any gate fails and the failing gate '
                    'reason_code is reported'
                ),
                'gate_ids': gate_ids,
                'refusal_reason_codes': list(GATE_REASON_CODES),
                'closes_the_node_by_status': {
                    STATUS_EXACT_EMPIRICAL_STRONG: (
                        'true when reported at L0_EXACT_KEY with both the 20-observation and '
                        '20-distinct-hands thresholds met and every layer-B gate passing'
                    ),
                    STATUS_EXACT_HIERARCHICAL_ESTIMATE: (
                        'CONDITIONAL: true if and only if every layer-B gate passes, false otherwise'
                    ),
                    STATUS_EXACT_UNRESOLVED: 'false',
                },
                'unresolved_node_closure': False,
                'no_threshold_moved': True,
                'no_gate_value_moved': True,
            },
            'non_loosening_vs_v1': {
                'rule': 'no value in this revision is more permissive than its v1 homologue',
                'comparisons': comparisons,
                'comparisons_checked': len(comparisons),
                'all_not_more_permissive': all(
                    row['not_more_permissive_than_v1'] for row in comparisons
                ),
                'any_comparison_more_permissive': any(
                    row['not_more_permissive_than_v1'] is False for row in comparisons
                ),
                'monotonicity_values': sorted({row['monotonicity'] for row in comparisons}),
                'v1_sources': sorted({row['v1_source'] for row in comparisons}),
            },
            'pooling': {
                'mechanism': 'STRICTLY_PARAMETRIC',
                'estimator': pooling['estimator'],
                'description': (
                    'a declared parent level supplies only the Dirichlet prior the exact posterior is '
                    'shrunk toward; it never supplies observations, distinct hands or effective sample '
                    'size for the requested key'
                ),
                'support_source_levels': [pooling['only_support_source_level']],
                'parameter_prior_levels': [
                    row['level'] for row in pooling['levels']
                    if not row['support_source_allowed']
                ],
                'maximum_parameter_pooling_level': (
                    pooling['maximum_pooling_level_for_a_reported_estimate']
                ),
                'kappa0': pooling['kappa0'],
                'alpha_per_legal_marginal_action': pooling['alpha_per_legal_marginal_action'],
                'counts_smoothed_across_levels': False,
                'parent_prior_only': True,
            },
            'mandatory_reported_fields': {
                'effective_sample_size': [
                    field('support.effective_sample_size'),
                    field('pooling.source_effective_sample_size'),
                ],
                'uncertainty': [field('uncertainty'), field('posterior')],
                'provenance': [
                    field('requested_key'),
                    field('support.observations'),
                    field('support.distinct_hands'),
                    field('support.source_key'),
                    field('support.borrowed_from_other_keys'),
                    field('pooling.level'),
                    field('pooling.source_key'),
                    field('pooling.source_observations'),
                    field('pooling.source_distinct_hands'),
                    field('pooling.retained_axes'),
                    field('pooling.pooled_axes'),
                ],
                'uncertainty_level_used_rule': (
                    'the uncertainty band reports the level actually used, never the exact level alone'
                ),
                'rule': (
                    'an EXACT_HIERARCHICAL_ESTIMATE is never reported without its effective sample '
                    'size, its uncertainty band and its pooling provenance; a reader must be able to '
                    'tell an exact empirical claim from a shrunk estimate'
                ),
            },
            # Machine-readable layer-B gates: each gate carries its id, its
            # refusal reason code, the fields it enforces, and an explicit
            # not-more-permissive-than-v1 comparison list.  A node closes iff
            # every gate passes.
            'admissibility_gates': gates,
            'admissibility_gate_ids': gate_ids,
            'admissibility_gate_reason_codes': list(GATE_REASON_CODES),
            'admissibility_gates_by_dimension': {
                'identity': {
                    'gate_id': 'EXACT_KEY_IDENTITY',
                    'reason_code': 'REFUSED_EXACT_KEY_IDENTITY',
                    'rule_id': SUPPORT_ISOLATION_RULE,
                    'runtime_invariant': RUNTIME_INVARIANT,
                    'support_source_key_equals_requested_key': True,
                    'support_borrowed_from_other_keys': False,
                    'identity_axes_never_mutualizable': True,
                    'violation_reason_code': spec['support_isolation_rule']['violation_reason_code'],
                    'rule': (
                        'every answered decision carries support.source_key == requested_key, '
                        'borrows no support from another key, and retains every never-mutualizable '
                        'axis at every pooling level'
                    ),
                },
                'provenance': {
                    'gate_id': 'POOLING_PROVENANCE',
                    'reason_code': 'REFUSED_POOLING_PROVENANCE',
                    'declared_pooling_required': True,
                    'pooling_level_reported_always': True,
                    'required_provenance_fields': [
                        'pooling.level',
                        'pooling.source_key',
                        'pooling.source_observations',
                        'pooling.source_distinct_hands',
                        'pooling.retained_axes',
                        'pooling.pooled_axes',
                    ],
                    'rule': (
                        'the reported pooling.source_key names the level that supplied the parent '
                        'prior and equals the requested key only when pooling.level == '
                        'L0_EXACT_KEY; the pooling source counts and axes are always reported'
                    ),
                },
                'pooling_level': {
                    'gate_id': 'POOLING_LEVEL',
                    'reason_code': 'REFUSED_POOLING_LEVEL',
                    'maximum_level_for_a_reported_estimate': (
                        pooling['maximum_pooling_level_for_a_reported_estimate']
                    ),
                    'exact_claim_requires_level': SUPPORT_LEVEL,
                    'rule': (
                        'the reported pooling.level is a declared level, EXACT_EMPIRICAL_STRONG is '
                        'emitted only at L0_EXACT_KEY, and a reported estimate never pools deeper '
                        'than the frozen maximum level'
                    ),
                },
                'effective_sample_size': {
                    'gate_id': 'EFFECTIVE_SAMPLE_SIZE',
                    'reason_code': 'REFUSED_EFFECTIVE_SAMPLE_SIZE',
                    'minimum_marginal_observations': thresholds['minimum_marginal_observations'],
                    'minimum_distinct_hands': thresholds['minimum_distinct_hands'],
                    'credited_at_hand_level': True,
                    'inflated_by_pooling': False,
                    'rule': (
                        'support.effective_sample_size equals support.distinct_hands and is never '
                        'inflated by pooled rows'
                    ),
                },
                'uncertainty': {
                    'gate_id': 'UNCERTAINTY',
                    'reason_code': 'REFUSED_UNCERTAINTY',
                    'required_fields': ['uncertainty', 'posterior'],
                    'level_must_match_the_level_actually_used': True,
                    'rule': (
                        'the uncertainty band reflects the level actually used and is never shown '
                        'without its pooling level'
                    ),
                },
                'calibration': {
                    'gate_id': 'CALIBRATION',
                    'reason_code': 'REFUSED_CALIBRATION',
                    'maximum_absolute_ece': thresholds['maximum_absolute_ece'],
                    'maximum_ece_delta_vs_active': thresholds['maximum_ece_delta_vs_active'],
                    'minimum_bin_support_for_a_calibration_claim': (
                        calibration['minimum_bin_support_for_a_calibration_claim']
                    ),
                    'bins_per_action_class': calibration['bins_per_action_class'],
                    'report_pooling_level_always': calibration['report_pooling_level_always'],
                    'rule': (
                        'calibration must not be reported on pooled support as if it were exact '
                        'support, and is never scored without its pooling level'
                    ),
                },
                'raise_sizing': {
                    'gate_id': GATE_RAISE_SIZING_FRONTIER,
                    'reason_code': 'REFUSED_RAISE_SIZING_FRONTIER',
                    'policy': spec['raise_sizing_policy']['rule'],
                    'requirements': [
                        'a raise target is emitted only when the exact structural node supports it',
                        'an unresolved raise-sizing frontier stays EXACT_UNRESOLVED',
                    ],
                    'forbidden': list(spec['raise_sizing_policy']['forbidden']),
                    'tie_break': spec['decision_thresholds']['sizing_tie_break'],
                },
            },
            'source': 'FROZEN_VALIDATION_PROTOCOL.json + HIERARCHICAL_MODEL_SPEC.json',
        },
    }


def _statuses(v1: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    reason_codes = spec['runtime_support_contract']['reason_codes']
    gates = v1['calibration_and_admission']
    return {
        'closed_enum': True,
        'no_implicit_default': True,
        'values': [
            {
                'status': STATUS_EXACT_EMPIRICAL_STRONG,
                'layer': 'EXACT_EMPIRICAL_SUPPORT',
                'condition': reason_codes[STATUS_EXACT_EMPIRICAL_STRONG]['condition'],
                'interpretation': reason_codes[STATUS_EXACT_EMPIRICAL_STRONG]['interpretation'],
                'consumable': True,
                'consumed_as': 'exact empirical support for the exact requested context',
            },
            {
                'status': STATUS_EXACT_HIERARCHICAL_ESTIMATE,
                'layer': 'EXACT_CONTEXT_ESTIMATE_ADMISSIBILITY',
                'condition': reason_codes[STATUS_EXACT_HIERARCHICAL_ESTIMATE]['condition'],
                'interpretation': reason_codes[STATUS_EXACT_HIERARCHICAL_ESTIMATE]['interpretation'],
                'consumable': True,
                'consumed_as': (
                    'an estimate for the exact requested context with its declared pooling level, '
                    'never as exact support'
                ),
            },
            {
                'status': STATUS_EXACT_UNRESOLVED,
                'layer': 'FAIL_CLOSED',
                'condition': reason_codes[STATUS_EXACT_UNRESOLVED]['condition'],
                'interpretation': reason_codes[STATUS_EXACT_UNRESOLVED]['interpretation'],
                'consumable': False,
                'consumed_as': 'nothing; the node and its descendants stay unresolved',
            },
        ],
        'outcome_rule': gates['outcome_rule'],
        'unresolved_nodes_do_not_fail_the_run': gates['unresolved_nodes_do_not_fail_the_run'],
        'source': 'HIERARCHICAL_MODEL_SPEC.json#runtime_support_contract.reason_codes',
    }


def _consumption_rule(v1: Mapping[str, Any], gates: list[dict[str, Any]]) -> dict[str, Any]:
    gate_ids = [row['gate_id'] for row in gates]
    reason_codes = list(GATE_REASON_CODES)
    return {
        'rule_id': 'CONSUME_ONLY_AN_ADMISSIBLE_NODE_ANSWER',
        'question': 'when may a downstream consumer use the answer of a required tree node?',
        'admissible_when': [
            'the node is answered with EXACT_EMPIRICAL_STRONG at L0_EXACT_KEY meeting both the 20 '
            'observation and the 20 distinct-hand thresholds, or',
            'the node is answered with EXACT_HIERARCHICAL_ESTIMATE whose support.source_key == '
            'requested_key and whose pooling provenance, effective sample size and uncertainty are '
            'reported and whose every layer-B admissibility gate passes, or',
            'the node is explicitly reported as EXACT_UNRESOLVED, which is not consumable but is a '
            'valid, non-defective outcome',
        ],
        'consumption_by_status': {
            STATUS_EXACT_EMPIRICAL_STRONG: {
                'consumable': True,
                'as': 'exact empirical support',
                'obligations': [
                    'reported pooling.level must be L0_EXACT_KEY',
                    'support.observations >= 20 and support.distinct_hands >= 20',
                    'support.source_key == requested_key',
                ],
            },
            STATUS_EXACT_HIERARCHICAL_ESTIMATE: {
                'consumable': True,
                'as': 'estimate with its declared pooling level',
                'closes_the_node_conditionally': True,
                'obligations': [
                    'support.source_key == requested_key',
                    'pooling.level, pooling.source_key and the pooling source counts are reported',
                    'support.effective_sample_size and pooling.source_effective_sample_size are '
                    'reported',
                    'the uncertainty band reports the level actually used',
                    'every layer-B admissibility gate passes; the node closes if and only if it '
                    'does, and stays open with the failing gate reason_code otherwise',
                    'never displayed or counted as exact support',
                ],
            },
            STATUS_EXACT_UNRESOLVED: {
                'consumable': False,
                'as': 'nothing',
                'obligations': [
                    'never replaced by FOLD, zero mass, a pruned branch or a nearest/representative '
                    'price',
                    'the blocker is reported as reason_detail and the node is not counted as admissible',
                ],
            },
        },
        'downstream_requirements': [
            'the pooling level actually used is visible wherever an estimate is shown',
            'no EV and no Hero recommendation is exposed on an EXACT_UNRESOLVED node',
            'a pooled estimate is never relabelled as exact support',
        ],
        'tree_closure': {
            'rule_id': NODE_CLOSURE_RULE_ID,
            'question': (
                'when does the answer of a required node close the node, and when may #367 consume '
                'it?'
            ),
            'node_closed_iff': (
                'the node answer passes every gate in layer_b_admissibility_gates with its frozen '
                'values; any failing gate leaves the node open and reports that gate reason_code'
            ),
            'closes_the_node_by_status': {
                STATUS_EXACT_EMPIRICAL_STRONG: (
                    'true when reported at L0_EXACT_KEY with both thresholds met and every layer-B '
                    'gate passing'
                ),
                STATUS_EXACT_HIERARCHICAL_ESTIMATE: (
                    'CONDITIONAL: true if and only if every layer-B gate passes, false otherwise'
                ),
                STATUS_EXACT_UNRESOLVED: 'false',
            },
            'gate_ids': gate_ids,
            'refusal_reason_codes': reason_codes,
            'required_tree_complete_requires': (
                'every required node to be closed, i.e. every node answer to pass every layer-B '
                'gate, and no required branch to keep an unresolved raise-sizing frontier'
            ),
            'authorizes_issue367_consumption_iff': [
                'every required node is closed under the conjunction of the frozen layer-B gates',
                'the frozen VALIDATION evaluation returns ADMIT_CANDIDATE with every frozen gate '
                'passing and the thresholds frozen in the v1 protocol',
                'the VALIDATION result is content-addressed and pinned in a new explicit #367 '
                'protocol revision',
                'that #367 revision names model_a.candidate_id='
                'model-a-preflop-sizing-hierarchical-candidate-v1 and its canonical payload digest',
            ],
            'forbids_issue367_consumption_when': [
                'any required node is open because a layer-B gate failed',
                'any layer-B gate is unevaluated for a required node',
                'the node answer is EXACT_UNRESOLVED',
                'a raise-sizing frontier stays unresolved',
                'the frozen VALIDATION outcome is not ADMIT_CANDIDATE, or the candidate is not '
                'pinned in a new explicit #367 protocol revision',
            ],
            'not_authorized_by_a_single_admissible_node': True,
            'no_threshold_moved': True,
            'no_gate_value_moved': True,
            'source': 'FROZEN_VALIDATION_PROTOCOL.json#issue367_rule + layer_b_admissibility_gates',
        },
        'issue367_consumption': {
            'rule_id': ISSUE367_RULE_ID,
            'carried_from_v1': True,
            'authorized_at_this_revision': bool(v1['issue367_rule']['authorized_at_freeze']),
            'not_authorized_by_a_single_admissible_node': True,
            'node_closure_rule_id': NODE_CLOSURE_RULE_ID,
            'requires': list(v1['issue367_rule']['authorized_when']),
        },
        'source': 'FROZEN_VALIDATION_PROTOCOL.json + HIERARCHICAL_MODEL_SPEC.json',
    }


def build(authored_at: str = DEFAULT_AUTHORED_AT) -> dict[str, Any]:
    custody = verify_v1_custody()
    v1 = custody['v1']
    spec = _load(SPEC_PATH)
    contract = _load(CONTRACT_PATH)
    validation = _load(HERE / 'validation' / 'VALIDATION_RESULT.json')
    if spec.get('schema') != SPEC_SCHEMA:
        raise ProtocolV2Error('model spec schema drifted')
    if contract.get('schema') != CONTRACT_SCHEMA:
        raise ProtocolV2Error('candidate contract schema drifted')
    if contract.get('candidate_id') != CANDIDATE_ID:
        raise ProtocolV2Error('candidate id drifted')
    if sorted(contract['statuses']) != sorted(
        [STATUS_EXACT_EMPIRICAL_STRONG, STATUS_EXACT_HIERARCHICAL_ESTIMATE, STATUS_EXACT_UNRESOLVED]
    ):
        raise ProtocolV2Error('candidate contract statuses drifted')
    recorded_schema = contract['schemas']['hierarchical']
    if recorded_schema['path'] != str(PROVIDER_SCHEMA_PATH.relative_to(ROOT)):
        raise ProtocolV2Error('candidate contract binds a different provider schema path')
    if recorded_schema['sha256'] != sha256_file(PROVIDER_SCHEMA_PATH):
        raise ProtocolV2Error('candidate contract provider schema digest drifted')

    thresholds = _thresholds_from_v1(v1, spec)
    pooling = _pooling_from_v1(v1, spec)
    layers = _layers(v1=v1, spec=spec, thresholds=thresholds, pooling=pooling)
    gates = layers['layer_b_exact_context_estimate_admissibility']['admissibility_gates']
    statuses = _statuses(v1, spec)
    consumption = _consumption_rule(v1, gates)
    history = _history_custody()

    authored_at_epoch = int(
        dt.datetime.strptime(authored_at, '%Y-%m-%dT%H:%M:%SZ')
        .replace(tzinfo=dt.timezone.utc)
        .timestamp()
    )
    return {
        'schema': SCHEMA,
        'kind': KIND,
        'revision': REVISION,
        'revision_of': V1_SCHEMA,
        'issue': 419,
        'parent_issue': int(v1['parent_issue']),
        'name': NAME,
        'status': STATUS,
        'authored_at': authored_at,
        'authored_at_epoch': authored_at_epoch,
        'authored_at_source': (
            'explicit_revision_timestamp_recorded_after_the_validation_result_was_written'
        ),
        'purpose': (
            'An explicitly versioned revision of the frozen VALIDATION protocol that separates the '
            'exact empirical support layer from the exact-context estimate admissibility layer, '
            'without changing any threshold, comparator, gate or support rule.'
        ),
        'amendments': {
            'amendment_count': 1,
            'current_amendment_id': AMENDMENT_ID,
            'superseded_digest': SUPERSEDED_V2_BYTE_SHA256,
            'no_threshold_moved': True,
            'no_gate_value_moved': True,
            'items': [
                {
                    'amendment_id': AMENDMENT_ID,
                    'amends': {
                        'schema': SCHEMA,
                        'revision': REVISION,
                        'name': NAME,
                    },
                    'amended_at': AMENDED_AT,
                    'supersedes': {
                        'byte_sha256': history['byte_sha256'],
                        'canonical_payload_sha256': history['canonical_payload_sha256'],
                        'authored_at': history['authored_at'],
                        'history_object': history['object'],
                        'history_digest_sidecar': history['digest_sidecar'],
                    },
                    'change': (
                        'layers.layer_b_exact_context_estimate_admissibility.'
                        'counts_as_a_closed_exact_tree_node changes from the flat false of the '
                        'superseded revision to CONDITIONAL: an exact-context estimate closes the '
                        'node if and only if every frozen layer-B admissibility gate passes, and '
                        'stays open otherwise with the failing gate reason_code'
                    ),
                    'change_before': {
                        'counts_as_a_closed_exact_tree_node': False,
                        'tree_closure': (
                            'a node answering EXACT_HIERARCHICAL_ESTIMATE is consumable as an '
                            'estimate but does not close the node'
                        ),
                    },
                    'change_after': {
                        'counts_as_a_closed_exact_tree_node': 'CONDITIONAL',
                        'closure_rule_id': NODE_CLOSURE_RULE_ID,
                        'closure_gate_ids': [row['gate_id'] for row in gates],
                    },
                    'reason_codes_added': list(GATE_REASON_CODES),
                    'threshold_change': False,
                    'gate_value_change': False,
                    'tightening_only': True,
                    'admits_anything': False,
                    'changes_admission_rule': False,
                    'reason': (
                        'the superseded revision contradicted the frozen layer-B gate set: it '
                        'declared an exact-context estimate can never close a node, while the v1 '
                        'gates already define the exact conjunction under which a node answer is '
                        'admissible.  The amendment makes the closure determination an explicit '
                        'conjunction over those same frozen gates and changes no value.'
                    ),
                }
            ],
            'source': 'FROZEN_VALIDATION_PROTOCOL.json#issue367_rule + layer_b_admissibility_gates',
        },
        'revision_history': {
            'current_revision': REVISION,
            'current_is_not_self_hashed': True,
            'current_byte_sha256_source': 'FROZEN_VALIDATION_PROTOCOL_V2.sha256 + ARTIFACTS.json',
            'superseded_count': 1,
            'entries': [
                {
                    'schema': history['schema'],
                    'revision': history['revision'],
                    'status': 'SUPERSEDED',
                    'semantic_status': 'SUPERSEDED_BY_AMENDMENT',
                    'byte_sha256': history['byte_sha256'],
                    'canonical_payload_sha256': history['canonical_payload_sha256'],
                    'authored_at': history['authored_at'],
                    'object': history['object'],
                    'digest_sidecar': history['digest_sidecar'],
                    'digest_sidecar_sha256': history['sidecar_sha256'],
                    'superseded_by_amendment_id': AMENDMENT_ID,
                    'amendment_id': AMENDMENT_ID,
                    'node_closure_value': False,
                },
                {
                    'schema': SCHEMA,
                    'revision': REVISION,
                    'status': 'CURRENT',
                    'semantic_status': 'CURRENT_AMENDED',
                    'authored_at': authored_at,
                    'amendment_id': AMENDMENT_ID,
                    'node_closure_value': 'CONDITIONAL',
                },
            ],
        },
        'relationship_to_v1': {
            'kind': 'ADDITIVE_INTERPRETATION_ONLY',
            'v1_gates_and_thresholds_remain_the_source_of_record': True,
            'v1_re_frozen_by_this_revision': False,
            'v1_bytes_rewritten': False,
            'v1_artifacts_superseded': False,
            'changes_admission_rule': False,
            'admits_anything': False,
        },
        'what_changed': [
            'the protocol now names two layers explicitly: (a) exact empirical support and '
            '(b) exact-context estimate admissibility',
            'the exact-context estimate layer states its mandatory effective-sample-size, '
            'uncertainty and pooling-provenance reporting obligations',
            'the admissibility gates of layer (b) are named explicitly as calibration, pooling and '
            'sizing obligations, carried over from the frozen v1 gates',
            'the rule for consuming an admissible node answer is stated once, per status',
            'amendment 1 makes node closure explicit and conditional: an exact-context estimate '
            'closes a required node if and only if every frozen layer-B admissibility gate passes, '
            'and the failing gate reason_code is reported otherwise',
            'the seven layer-B gates are machine-readable with their reason codes and an explicit '
            'not-more-permissive-than-v1 comparison list',
        ],
        'what_did_not_change': [
            'the 20 marginal observations / 20 distinct hands thresholds',
            'the EXACT_EMPIRICAL_STRONG label and its L0_EXACT_KEY-only condition',
            'the SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT rule and support.source_key == requested_key',
            'the three comparators, the admission gates and the outcome rule',
            'every layer-B gate value, which stays equal to or stricter than its v1 homologue',
            'the frozen VALIDATION result, and the terminal decision verdict, blockers and '
            'admission rule (its bytes are re-derived with the provider contract)',
            'the active Model A v5 pointer and the #367 authorization state',
        ],
        'v1_provenance': {
            'schema': v1['schema'],
            'kind': v1['kind'],
            'path': 'analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.json',
            'byte_sha256': V1_BYTE_SHA256,
            'canonical_payload_sha256': V1_CANONICAL_SHA256,
            'status': v1['status'],
            'frozen_at': v1['frozen_at'],
            'frozen_at_epoch': v1['frozen_at_epoch'],
            'digest_sidecar': {
                'path': 'analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.sha256',
                'sha256': custody['v1_sidecar_sha256'],
            },
            'bundle': {
                'path': 'analysis/issue419_hierarchical_tree/validation_protocol',
                'index': 'ARTIFACTS.json',
                'index_sha256': custody['v1_bundle_index_sha256'],
                'object': 'sha256/' + V1_BYTE_SHA256 + '.json',
                'object_sha256': V1_BYTE_SHA256,
            },
            'protocol_generator': {
                'path': V1_GENERATOR_PATH,
                'sha256': V1_GENERATOR_SHA256,
            },
            'protocol_revision_generator': {
                'path': 'tools/training/write_frozen_validation_protocol_v2.py',
                'sha256': sha256_file(SOURCE_PATH),
            },
            'thresholds_sha256': stable_hash(v1['thresholds']),
            'pooling_limits_sha256': stable_hash(v1['pooling_limits']),
            'admission_gates_sha256': stable_hash(
                v1['calibration_and_admission']['admission_gates']
            ),
            'candidate_id': v1['candidate']['candidate_id'],
            'candidate_canonical_payload_sha256': CANDIDATE_CANONICAL_SHA256,
        },
        'v1_custody': {
            'v1_bytes_unchanged': True,
            'v1_immutability_is_re_derived_not_asserted': True,
            # ``v1_bytes_unchanged`` covers the frozen v1 pre-registration (the
            # protocol payload, its digest sidecar, its bundle and the consumed
            # VALIDATION history).  The T8 preflight and the terminal decision
            # are *derived* evidence: they embed the provider source digest and
            # are re-derived whenever the provider contract changes, so their
            # digests below are re-pinned rather than frozen forever.
            'frozen_v1_pre_registration_unchanged': True,
            'derived_evidence_re_derived': True,
            'derived_evidence_roles': [
                'V1_EXACT_TREE_PREFLIGHT',
                'V1_TERMINAL_DECISION',
                'V1_TERMINAL_DECISION_BUNDLE_INDEX',
            ],
            'v1_surfaces': custody['v1_surfaces'],
            'bound_identities': custody['bound_identities'],
            'validation_history_sha256': custody['validation_result_sha256'],
            'superseded_v2_history': {
                'object': history['object'],
                'digest_sidecar': history['digest_sidecar'],
                'byte_sha256': history['byte_sha256'],
                'canonical_payload_sha256': history['canonical_payload_sha256'],
                'sidecar_sha256': history['sidecar_sha256'],
                'cited_by_amendment_id': AMENDMENT_ID,
            },
            'verification': (
                'every recorded sha256 is recomputed from the persisted bytes at authoring time and '
                'again by --check; any drift is a hard failure, and the frozen v1 generator digest '
                'is re-verified so the v1 pre-registration cannot be silently edited.  The derived '
                'T8 preflight and terminal decision are re-derived with the provider contract and '
                're-pinned here; they are not a re-freeze of any threshold, gate or comparator'
            ),
        },
        'layers': layers,
        'thresholds': thresholds,
        'pooling_limits': pooling,
        'statuses': statuses,
        'admissible_node_consumption_rule': consumption,
        'gates': {
            'frozen_admission_gates': [
                {'gate': row['gate'], 'rule': row['rule'], 'carried_from_v1': True, 'modified': False}
                for row in v1['calibration_and_admission']['admission_gates']
            ],
            'gates_modified_by_this_revision': False,
            'layer_b_admissibility_gate_ids': [
                row['gate_id']
                for row in layers['layer_b_exact_context_estimate_admissibility'][
                    'admissibility_gates'
                ]
            ],
            'layer_b_admissibility_gate_reason_codes': list(GATE_REASON_CODES),
            'layer_b_gate_values_modified_by_this_revision': False,
            'layer_b_gates_more_permissive_than_v1': False,
            'node_closure_rule_id': NODE_CLOSURE_RULE_ID,
            'outcome_rule': v1['calibration_and_admission']['outcome_rule'],
            'no_partial_admission': v1['calibration_and_admission']['no_partial_admission'],
            'abstention_is_not_a_failure': v1['thresholds']['abstention_is_not_a_failure'],
            'automatic_promotion': v1['calibration_and_admission']['automatic_promotion'],
            'active_pointer_mutation': v1['calibration_and_admission']['active_pointer_mutation'],
            'gates_sha256': stable_hash(v1['calibration_and_admission']['admission_gates']),
        },
        'holdout_boundary': {
            'validation_split_consumed': True,
            'validation_consumed_by_this_revision': False,
            'validation_result_sha256': custody['validation_result_sha256'],
            'validation_outcome': validation['outcome'],
            'validation_outcome_is_for_this_candidate': True,
            'revision_authored_after_validation_read': True,
            'thresholds_selected_after_reading_the_holdout': False,
            'holdout_reopened_by_this_revision': False,
            'test_consumed': False,
            'test_authorized': False,
            'model_b_consumed': False,
            'hero_ev_consumed': False,
            'issue367_currently_admitted_model': {
                'rule_id': v1['issue367_rule']['rule_id'],
                'candidate_id': v1['issue367_rule']['currently_admitted_model_a_for_367'][
                    'candidate_id'
                ],
                'admission_decision': v1['issue367_rule'][
                    'currently_admitted_model_a_for_367'
                ]['admission_decision'],
                'reference_to_the_hierarchical_candidate_authorized': bool(
                    v1['issue367_rule']['authorized_at_freeze']
                ),
            },
        },
        'publication': {
            'production_effect': 'NONE',
            'active_reference_mutation': 'FORBIDDEN',
            'automatic_promotion': 'FORBIDDEN',
            'admits_anything': False,
        },
        'reproduction': {
            'command': 'python3 tools/training/write_frozen_validation_protocol_v2.py',
            'check_command': 'python3 tools/training/write_frozen_validation_protocol_v2.py --check',
            'v1_check_command': 'python3 tools/training/write_frozen_validation_protocol.py --check',
            'deterministic': True,
            'rng_algorithm': 'none',
            'stochastic_draws': 0,
        },
    }


def summarize(protocol: Mapping[str, Any], digest: str) -> str:
    layers = protocol['layers']
    support = layers['layer_a_exact_empirical_support']
    estimate = layers['layer_b_exact_context_estimate_admissibility']
    return (
        '# FROZEN_VALIDATION_PROTOCOL_v2 (hierarchical exact-context, #419)\n\n'
        f"`{protocol['schema']}` (`{protocol['kind']}`), revision {protocol['revision']}, "
        f"issue {protocol['issue']}, authored `{protocol['authored_at']}` "
        f"(`{protocol['status']}`). Content-addressed here; the payload digest is `{digest}` "
        f"(canonical payload `{stable_hash(protocol)}`).\n\n"
        f"It revises `{protocol['v1_provenance']['schema']}` "
        f"(`{protocol['v1_provenance']['byte_sha256']}`, canonical "
        f"`{protocol['v1_provenance']['canonical_payload_sha256']}`) additively: the v1 bytes are "
        'unchanged and stay the source of record for thresholds, gates and comparators.\n\n'
        f"Layer A (`{support['layer_id']}`) is the exact empirical support layer: "
        f"`{support['status_label']}` (unchanged) at `{support['support_level']}`, both thresholds "
        f"({support['thresholds']['minimum_marginal_observations']} observations / "
        f"{support['thresholds']['minimum_distinct_hands']} distinct hands), support never borrowed "
        f"(`{support['support_isolation_rule']}`).\n\n"
        f"Layer B (`{estimate['layer_id']}`) is the exact-context estimate admissibility layer: "
        f"`{estimate['status_label']}` for the same exact requested key, identity preserved, "
        f"`{estimate['runtime_invariant']}`, pooling strictly parametric over "
        f"`{estimate['pooling']['maximum_parameter_pooling_level']}` with mandatory effective sample "
        'size, uncertainty and pooling provenance, gated on calibration, pooling and sizing.\n\n'
        f"Statuses: {', '.join(row['status'] for row in protocol['statuses']['values'])}. The node "
        f"consumption rule is `{protocol['admissible_node_consumption_rule']['rule_id']}`: an "
        'estimate is consumable as an estimate, an unresolved node is consumable as nothing, and '
        'a required node closes if and only if every frozen layer-B admissibility gate passes '
        f"(`{NODE_CLOSURE_RULE_ID}`); closing the tree still requires every required node to close "
        'and no raise-sizing frontier to stay unresolved.\n\n'
        f"Amendment `{AMENDMENT_ID}` supersedes the earlier v2 payload "
        f"`{SUPERSEDED_V2_BYTE_SHA256}` (kept content-addressed under "
        f"`{HISTORY_OBJECT}` + `.sha256`): the flat `counts_as_a_closed_exact_tree_node = false` is "
        'replaced by `CONDITIONAL`, true if and only if every frozen layer-B gate passes. No '
        f"threshold and no gate value moved, and the superseded canonical payload is "
        f"`{SUPERSEDED_V2_CANONICAL_SHA256}`.\n\n"
        f"Reproduce: `{protocol['reproduction']['command']}`; verify: "
        f"`{protocol['reproduction']['check_command']}`. This revision admits nothing.\n"
    )


def _index_file_entries(index: Mapping[str, Any]) -> dict[str, Any]:
    """The content-addressed file entries of ``ARTIFACTS.json`` (not ``history``)."""
    return {name: row for name, row in index.items() if name != HISTORY_KEY}


def persist(protocol: Mapping[str, Any]) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    objects = OUT / 'sha256'
    objects.mkdir(exist_ok=True)
    HISTORY_DIR.mkdir(exist_ok=True)
    payload_bytes = serialize(protocol)
    digest = hashlib.sha256(payload_bytes).hexdigest()
    (OUT / NAME).write_bytes(payload_bytes)
    (objects / (digest + '.json')).write_bytes(payload_bytes)
    summary_bytes = summarize(protocol, digest).encode()
    summary_digest = hashlib.sha256(summary_bytes).hexdigest()
    (OUT / SUMMARY_NAME).write_bytes(summary_bytes)
    (objects / (summary_digest + '.md')).write_bytes(summary_bytes)
    index = {
        NAME: {
            'sha256': digest,
            'canonical_payload_sha256': stable_hash(protocol),
            'object': 'sha256/' + digest + '.json',
            'revision_of': protocol['v1_provenance']['byte_sha256'],
        },
        SUMMARY_NAME: {'sha256': summary_digest, 'object': 'sha256/' + summary_digest + '.md'},
        HISTORY_KEY: {
            'sha256': SUPERSEDED_V2_BYTE_SHA256,
            'canonical_payload_sha256': SUPERSEDED_V2_CANONICAL_SHA256,
            'object': HISTORY_OBJECT,
            'digest_sidecar': HISTORY_DIGEST_SIDECAR,
            'status': 'SUPERSEDED_BY_AMENDMENT',
            'amendment_id': AMENDMENT_ID,
            'cited_by': NAME,
        },
    }
    (OUT / INDEX_NAME).write_text(json.dumps(index, sort_keys=True, indent=2) + '\n')
    referenced = {
        Path(entry['object']).name
        for entry in _index_file_entries(index).values()
    }
    for path in objects.iterdir():
        if path.is_file() and path.name not in referenced:
            path.unlink()
    DIGEST_PATH.write_text(
        f'{digest}  {NAME}\n# canonical_payload_sha256 {stable_hash(protocol)}\n'
        f"# revision_of {protocol['v1_provenance']['byte_sha256']}\n"
        f"# authored_at {protocol['authored_at']}\n"
    )
    return index


def _persisted_authored_at() -> str:
    if (OUT / NAME).is_file():
        try:
            return str(_load(OUT / NAME).get('authored_at') or DEFAULT_AUTHORED_AT)
        except (OSError, ValueError):
            return DEFAULT_AUTHORED_AT
    return DEFAULT_AUTHORED_AT


def check() -> int:
    protocol = build(authored_at=_persisted_authored_at())
    expected = serialize(protocol)
    expected_digest = hashlib.sha256(expected).hexdigest()
    problems: list[str] = []
    if not (OUT / NAME).is_file() or (OUT / NAME).read_bytes() != expected:
        problems.append('v2 protocol bytes differ from a fresh build')
    index = _load(OUT / INDEX_NAME)
    entry = index.get(NAME, {})
    if entry.get('sha256') != expected_digest:
        problems.append('v2 index digest mismatch')
    if entry.get('canonical_payload_sha256') != stable_hash(protocol):
        problems.append('v2 canonical payload digest mismatch')
    if (OUT / entry.get('object', 'missing')).read_bytes() != expected:
        problems.append('v2 content-addressed object mismatch')
    sidecar = DIGEST_PATH.read_text(encoding='utf-8')
    if not sidecar.startswith(expected_digest + '  ' + NAME):
        problems.append('v2 .sha256 sidecar mismatch')
    file_entries = _index_file_entries(index)
    for name, row in file_entries.items():
        data = (OUT / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != row['sha256']:
            problems.append(f'byte hash mismatch for {name}')
        if data != (OUT / row['object']).read_bytes():
            problems.append(f'content-addressed copy mismatch for {name}')
    if {p.name for p in (OUT / 'sha256').iterdir()} != {
        Path(row['object']).name for row in file_entries.values()
    }:
        problems.append('unexpected object in validation_protocol_v2/sha256')
    history_row = index.get(HISTORY_KEY, {})
    if (
        history_row.get('sha256') != SUPERSEDED_V2_BYTE_SHA256
        or history_row.get('canonical_payload_sha256') != SUPERSEDED_V2_CANONICAL_SHA256
        or history_row.get('object') != HISTORY_OBJECT
    ):
        problems.append('v2 ARTIFACTS.json history entry mismatch')
    try:
        custody = _history_custody()
        if custody['canonical_payload_sha256'] != SUPERSEDED_V2_CANONICAL_SHA256:
            problems.append('superseded v2 history canonical digest mismatch')
        cited = [
            row['byte_sha256']
            for row in protocol['revision_history']['entries']
            if row['status'] == 'SUPERSEDED'
        ]
        if cited != [SUPERSEDED_V2_BYTE_SHA256]:
            problems.append('revision_history does not cite the superseded digest')
        if protocol['amendments']['superseded_digest'] != SUPERSEDED_V2_BYTE_SHA256:
            problems.append('amendments do not cite the superseded digest')
    except ProtocolV2Error as error:
        problems.append(f'superseded v2 history check failed: {error}')
    try:
        verify_v1_custody()
    except ProtocolV2Error as error:
        problems.append(f'v1 custody check failed: {error}')
    if problems:
        print(json.dumps({'status': 'MISMATCH', 'problems': problems}, indent=2))
        return 1
    print(json.dumps({
        'status': 'OK',
        'schema': SCHEMA,
        'revision': protocol['revision'],
        'protocol_sha256': expected_digest,
        'canonical_payload_sha256': stable_hash(protocol),
        'revision_of': protocol['v1_provenance']['byte_sha256'],
        'authored_at': protocol['authored_at'],
        'layers': list(protocol['layers']),
        'statuses': [row['status'] for row in protocol['statuses']['values']],
        'amendments': [row['amendment_id'] for row in protocol['amendments']['items']],
        'superseded_v2_sha256': SUPERSEDED_V2_BYTE_SHA256,
        'node_closure_rule_id': NODE_CLOSURE_RULE_ID,
        'layer_b_gate_reason_codes': list(GATE_REASON_CODES),
        'v1_surfaces_verified': len(protocol['v1_custody']['v1_surfaces']),
    }, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='verify the persisted v2 revision instead of rewriting it')
    parser.add_argument('--authored-at', default=None,
                        help='explicit ISO-8601 revision timestamp (defaults to the persisted one)')
    args = parser.parse_args()
    if args.check:
        return check()
    authored_at = args.authored_at or _persisted_authored_at()
    protocol = build(authored_at=authored_at)
    index = persist(protocol)
    print(json.dumps({
        'schema': SCHEMA,
        'revision': protocol['revision'],
        'protocol_path': str((OUT / NAME).relative_to(ROOT)),
        'bundle': str(OUT.relative_to(ROOT)),
        'protocol_sha256': index[NAME]['sha256'],
        'canonical_payload_sha256': index[NAME]['canonical_payload_sha256'],
        'revision_of': protocol['v1_provenance']['byte_sha256'],
        'authored_at': protocol['authored_at'],
        'layers': list(protocol['layers']),
    }, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
