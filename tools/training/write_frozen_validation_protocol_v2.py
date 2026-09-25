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
  pooling provenance, gated on calibration, pooling and sizing.

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
     '456d85be57b910d3a56cb0160ba0ba35c988f7f69da9f965f0a887aaac473ae6'),
    ('analysis/issue419_hierarchical_tree/terminal_decision/DECISION.json',
     'V1_TERMINAL_DECISION',
     '9425f30163dcfa5e0a72ca8f6dd1bb4b6a25ce270b4a894aaa57e898a74bd0bc'),
    ('analysis/issue419_hierarchical_tree/terminal_decision/ARTIFACTS.json',
     'V1_TERMINAL_DECISION_BUNDLE_INDEX',
     '08530e37f8ecf232fc032612021f74459e6af771f15fc4097748c0d73f86b7e4'),
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
     'd62b2dca4a6673531c764b283de369f1192fe748eabcb4040f7ae0eda1823cd3'),
    ('contracts/training/model-a-preflop-sizing-hierarchical-likelihood.schema.json',
     'PROVIDER_LIKELIHOOD_SCHEMA',
     '7e85c9b94c7d04d765494f72adb819122eb9abdae178a6675badb91a3d8c385c'),
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
            'counts_as_a_closed_exact_tree_node': False,
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
            'admissibility_gates': {
                'calibration': {
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
                'pooling': {
                    'rule_id': SUPPORT_ISOLATION_RULE,
                    'runtime_invariant': RUNTIME_INVARIANT,
                    'declared_pooling_required': True,
                    'support_source_key_equals_requested_key': True,
                    'support_borrowed_from_other_keys': False,
                    'maximum_level_for_a_reported_estimate': (
                        pooling['maximum_pooling_level_for_a_reported_estimate']
                    ),
                    'exact_claim_requires_level': SUPPORT_LEVEL,
                    'rule': (
                        'every answered decision carries support.source_key == requested_key and '
                        'pooling.support_source_key == requested_key; the reported pooling.source_key '
                        'names the level that supplied the parent prior and equals the requested key '
                        'only when pooling.level == L0_EXACT_KEY'
                    ),
                },
                'sizing': {
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


def _consumption_rule(v1: Mapping[str, Any]) -> dict[str, Any]:
    return {
        'rule_id': 'CONSUME_ONLY_AN_ADMISSIBLE_NODE_ANSWER',
        'question': 'when may a downstream consumer use the answer of a required tree node?',
        'admissible_when': [
            'the node is answered with EXACT_EMPIRICAL_STRONG at L0_EXACT_KEY meeting both the 20 '
            'observation and the 20 distinct-hand thresholds, or',
            'the node is answered with EXACT_HIERARCHICAL_ESTIMATE whose support.source_key == '
            'requested_key and whose pooling provenance, effective sample size and uncertainty are '
            'reported, or',
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
                'obligations': [
                    'support.source_key == requested_key',
                    'pooling.level, pooling.source_key and the pooling source counts are reported',
                    'support.effective_sample_size and pooling.source_effective_sample_size are '
                    'reported',
                    'the uncertainty band reports the level actually used',
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
        'tree_closure': (
            'a node answering EXACT_HIERARCHICAL_ESTIMATE is consumable as an estimate but does not '
            'close the node: closing required_tree_complete still requires an admissible exact answer '
            'at L0_EXACT_KEY for every required node'
        ),
        'issue367_consumption': {
            'rule_id': ISSUE367_RULE_ID,
            'carried_from_v1': True,
            'authorized_at_this_revision': bool(v1['issue367_rule']['authorized_at_freeze']),
            'not_authorized_by_a_single_admissible_node': True,
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
    statuses = _statuses(v1, spec)
    consumption = _consumption_rule(v1)

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
        ],
        'what_did_not_change': [
            'the 20 marginal observations / 20 distinct hands thresholds',
            'the EXACT_EMPIRICAL_STRONG label and its L0_EXACT_KEY-only condition',
            'the SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT rule and support.source_key == requested_key',
            'the three comparators, the admission gates and the outcome rule',
            'the frozen VALIDATION result and the terminal decision',
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
            'v1_surfaces': custody['v1_surfaces'],
            'bound_identities': custody['bound_identities'],
            'validation_history_sha256': custody['validation_result_sha256'],
            'verification': (
                'every recorded sha256 is recomputed from the persisted bytes at authoring time and '
                'again by --check; any drift is a hard failure, and the frozen v1 generator digest '
                'is re-verified so the v1 pre-registration cannot be silently edited'
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
        'closing the tree still requires an admissible exact answer at L0_EXACT_KEY for every '
        'required node.\n\n'
        f"Reproduce: `{protocol['reproduction']['command']}`; verify: "
        f"`{protocol['reproduction']['check_command']}`. This revision admits nothing.\n"
    )


def persist(protocol: Mapping[str, Any]) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    objects = OUT / 'sha256'
    objects.mkdir(exist_ok=True)
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
    }
    (OUT / INDEX_NAME).write_text(json.dumps(index, sort_keys=True, indent=2) + '\n')
    referenced = {Path(entry['object']).name for entry in index.values()}
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
    for name, row in index.items():
        data = (OUT / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != row['sha256']:
            problems.append(f'byte hash mismatch for {name}')
        if data != (OUT / row['object']).read_bytes():
            problems.append(f'content-addressed copy mismatch for {name}')
    if {p.name for p in (OUT / 'sha256').iterdir()} != {
        Path(row['object']).name for row in index.values()
    }:
        problems.append('unexpected object in validation_protocol_v2/sha256')
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
