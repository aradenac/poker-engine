#!/usr/bin/env python3
"""#419: hierarchical Model-A sizing candidate -- contract/schema audit.

This tool is the machine-readable proof layer for the hierarchical
exact-context candidate contract.  It never fits, never opens a hand history
and never mutates an active pointer.  It re-derives, from the provider code and
the two JSON-Schema contracts, and pins:

* the new ``candidate_id`` and the mandatory hierarchical response fields
  (status, exact empirical observations, effective sample size, pooling
  level/source, uncertainty, reason codes) are declared by the schema;
* provider/schema parity: every frozen provider constant equals the schema
  ``const``/``enum`` that publishes it, and real provider outputs at all three
  statuses validate against the schema;
* the active pointer is unchanged: ``training/registry.json`` still promotes
  ``training/models/preflop_population_model_v5.json`` (the pinned reference),
  the registry is byte-identical before/after the run, and the candidate is
  never registered as promoted;
* non-regression of the exact-price contracts v1/v2.

The JSON-Schema check is a self-contained stdlib subset validator covering
every keyword used by these two contracts, so the contract gate never depends on
an unpinned third-party package.  The result is written to
``analysis/issue419_hierarchical_tree/contract/``.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import sha256_file
from tools.preflop import model_a_sizing_hierarchical as hierarchical
from tools.preflop import model_a_sizing_likelihood as exact_price
from tools.preflop.context_contract import build_context
from tools.training import audit_model_a_exact_tree as legacy
from tools.training.audit_preflop_sizing_support import stable_hash
from tools.training.fit_model_a_preflop_sizing import EXPECTED_REFERENCE_HASH, REFERENCE

OUTPUT = ROOT / 'analysis/issue419_hierarchical_tree/contract'
SCHEMA = 'poker-hierarchical-candidate-contract/v1'
CONTRACT_NAME = 'CANDIDATE_CONTRACT.json'
SUMMARY_NAME = 'SUMMARY.md'

HIERARCHICAL_SCHEMA_PATH = (
    ROOT / 'contracts/training/model-a-preflop-sizing-hierarchical-likelihood.schema.json'
)
EXACT_SCHEMA_PATH = ROOT / 'contracts/training/model-a-preflop-sizing-likelihood.schema.json'
REGISTRY_PATH = ROOT / 'training/registry.json'
POPULATIONS_REGISTRY_PATH = ROOT / 'training/populations/registry.json'
FIXTURE_PATH = ROOT / 'tests/fixtures/model_a_preflop_sizing_cases.json'

# Frozen active-pointer expectations.  ``PINNED_PROMOTED_PREFLOP`` and
# ``PINNED_REFERENCE_HASH`` come from the canonical #352/#388 reference pin.
PINNED_PROMOTED_PREFLOP = 'training/models/preflop_population_model_v5.json'
PINNED_PROMOTED_POSTFLOP = 'training/models/postflop_population_model_v5.json'
PINNED_PROMOTED_RUN = '20260909_population_increment_v2'
PINNED_REFERENCE_HASH = EXPECTED_REFERENCE_HASH

# The mandatory hierarchical provenance fields, mapped to the schema location
# that publishes them.  A missing location fails the run closed.
REQUIRED_HIERARCHICAL_FIELDS = (
    ('status', '$defs/response/properties/status'),
    ('exact_empirical_observations', '$defs/response/properties/support/properties/observations'),
    ('effective_sample_size', '$defs/response/properties/support/properties/effective_sample_size'),
    ('pooling_level', '$defs/response/properties/pooling/properties/level'),
    ('pooling_source', '$defs/response/properties/pooling/properties/source_key'),
    ('pooling_support_source', '$defs/response/properties/pooling/properties/support_source_key'),
    ('uncertainty', '$defs/response/properties/uncertainty'),
    ('reason_code', '$defs/response/properties/reason_code'),
    ('reason_codes', '$defs/reasonCode'),
    ('reason_detail', '$defs/response/properties/reason_detail'),
    ('unresolved_reason', '$defs/response/properties/unresolved_reason'),
)

# The exact reason codes an EXACT_UNRESOLVED response may carry.  The fourth
# provider constant, COARSE_KEY_SUPPORT_LAUNDERING, is an error code: support
# laundering raises instead of emitting an answer.
PROVIDER_REASON_CODES = (
    hierarchical.REASON_NO_ADMISSIBLE_POOLING,
    hierarchical.REASON_RAISE_SIZING_UNRESOLVED,
    hierarchical.REASON_NO_EXACT_SUPPORT_NO_CONTEXT,
)

_JSON_TYPES = {
    'object': lambda value: isinstance(value, dict),
    'array': lambda value: isinstance(value, list),
    'string': lambda value: isinstance(value, str),
    'boolean': lambda value: isinstance(value, bool),
    'null': lambda value: value is None,
    'integer': lambda value: isinstance(value, int) and not isinstance(value, bool),
    'number': lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
}


def _matches_type(value: Any, name: str) -> bool:
    checker = _JSON_TYPES.get(name)
    if checker is None:
        raise ValueError(f'unsupported JSON schema type: {name}')
    return checker(value)


def _resolve_ref(root: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    if not ref.startswith('#/'):
        raise ValueError(f'only local $ref is supported: {ref}')
    target: Any = root
    for part in ref[2:].split('/'):
        target = target[part]
    return target


def schema_errors(
    schema: Mapping[str, Any],
    value: Any,
    node: Mapping[str, Any] | None = None,
    path: str = '$',
) -> list[str]:
    """Validate ``value`` against the JSON-Schema subset used by the contracts."""
    if node is None:
        node = schema
    if '$ref' in node:
        return schema_errors(schema, value, _resolve_ref(schema, node['$ref']), path)
    errors: list[str] = []
    expected = node.get('type')
    if expected is not None:
        allowed = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(value, name) for name in allowed):
            return [f'{path}: expected {allowed}, got {type(value).__name__}']
    if 'const' in node and value != node['const']:
        errors.append(f'{path}: const {node["const"]!r} != {value!r}')
    if 'enum' in node and value not in node['enum']:
        errors.append(f'{path}: {value!r} not in enum {node["enum"]!r}')
    if isinstance(value, dict):
        for key in node.get('required', []):
            if key not in value:
                errors.append(f'{path}: missing required property {key!r}')
        properties = node.get('properties', {})
        additional = node.get('additionalProperties', True)
        for key, child in value.items():
            if key in properties:
                errors.extend(schema_errors(schema, child, properties[key], f'{path}.{key}'))
            elif additional is False:
                errors.append(f'{path}: unexpected property {key!r}')
            elif isinstance(additional, dict):
                errors.extend(schema_errors(schema, child, additional, f'{path}.{key}'))
        if 'minProperties' in node and len(value) < node['minProperties']:
            errors.append(f'{path}: fewer than {node["minProperties"]} properties')
    if isinstance(value, list):
        if 'minItems' in node and len(value) < node['minItems']:
            errors.append(f'{path}: fewer than {node["minItems"]} items')
        if 'maxItems' in node and len(value) > node['maxItems']:
            errors.append(f'{path}: more than {node["maxItems"]} items')
        items = node.get('items')
        if isinstance(items, dict):
            for index, child in enumerate(value):
                errors.extend(schema_errors(schema, child, items, f'{path}[{index}]'))
    if isinstance(value, str):
        if 'minLength' in node and len(value) < node['minLength']:
            errors.append(f'{path}: shorter than minLength {node["minLength"]}')
        if 'pattern' in node and re.search(node['pattern'], value) is None:
            errors.append(f'{path}: does not match pattern {node["pattern"]!r}')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 'minimum' in node and value < node['minimum']:
            errors.append(f'{path}: below minimum {node["minimum"]}')
        if 'maximum' in node and value > node['maximum']:
            errors.append(f'{path}: above maximum {node["maximum"]}')
        if 'exclusiveMinimum' in node and value <= node['exclusiveMinimum']:
            errors.append(f'{path}: not above exclusiveMinimum {node["exclusiveMinimum"]}')
        if 'exclusiveMaximum' in node and value >= node['exclusiveMaximum']:
            errors.append(f'{path}: not below exclusiveMaximum {node["exclusiveMaximum"]}')
    return errors


def load_schemas() -> tuple[dict[str, Any], dict[str, Any]]:
    hierarchical_schema = json.loads(HIERARCHICAL_SCHEMA_PATH.read_text(encoding='utf-8'))
    exact_schema = json.loads(EXACT_SCHEMA_PATH.read_text(encoding='utf-8'))
    return hierarchical_schema, exact_schema


def _dig(node: Mapping[str, Any], pointer: str) -> Any:
    target: Any = node
    for part in pointer.split('/'):
        target = target[part]
    return target


def required_field_report(hierarchical_schema: Mapping[str, Any]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for field, pointer in REQUIRED_HIERARCHICAL_FIELDS:
        try:
            _dig(hierarchical_schema, pointer)
            present = True
        except (KeyError, TypeError):
            present = False
        report[field] = {'schema_pointer': pointer, 'present': present}
    response_required = set(hierarchical_schema['$defs']['response']['required'])
    report['status']['required_in_response'] = 'status' in response_required
    report['reason_code']['required_in_response'] = 'reason_code' in response_required
    report['uncertainty']['required_in_response'] = 'uncertainty' in response_required
    support_required = set(
        hierarchical_schema['$defs']['response']['properties']['support']['required']
    )
    report['exact_empirical_observations']['required_in_support'] = 'observations' in support_required
    report['effective_sample_size']['required_in_support'] = (
        'effective_sample_size' in support_required
    )
    pooling_required = set(
        hierarchical_schema['$defs']['response']['properties']['pooling']['required']
    )
    report['pooling_level']['required_in_pooling'] = 'level' in pooling_required
    report['pooling_source']['required_in_pooling'] = 'source_key' in pooling_required
    report['pooling_support_source']['required_in_pooling'] = (
        'support_source_key' in pooling_required
    )
    report['reason_codes']['is_enum'] = isinstance(
        hierarchical_schema['$defs']['reasonCode'].get('enum'), list
    )
    report['all_present'] = all(entry['present'] for entry in report.values() if isinstance(entry, dict))
    return report


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))


def _context(base_input: Mapping[str, Any], **overrides: Any) -> dict[str, Any]:
    payload = copy.deepcopy(base_input)
    payload.update(overrides)
    return build_context(**payload)


def _rows(context: Mapping[str, Any], hand_prefix: str, count: int, target: float) -> list[dict[str, Any]]:
    actions = ['FOLD', 'CALL', 'RAISE', 'JAM']
    rows: list[dict[str, Any]] = []
    for index in range(count):
        action = actions[index % len(actions)]
        rows.append(
            {
                'context': context,
                'hand_id': f'{hand_prefix}-{index}',
                'action': action,
                'target_total_bb': target if action in ('RAISE', 'JAM') else None,
            }
        )
    return rows


def build_provider_scenarios() -> dict[str, Any]:
    """Build deterministic synthetic/TRAIN-free provider outputs at each status."""
    fixture = _fixture()
    base_input = fixture['contexts'][0]['input']
    population_id = fixture['population_id']
    context = _context(base_input)
    stacks = dict(base_input['stack_bb_by_position'])
    stacks['BB'] = 60.0
    sibling = _context(base_input, stack_bb_by_position=stacks)

    strong = hierarchical.make_synthetic_hierarchical_candidate(
        population_id=population_id,
        observations=_rows(context, 'strong', hierarchical.MIN_MARGINAL_OBSERVATIONS, 7.0),
    )
    pooled = hierarchical.make_synthetic_hierarchical_candidate(
        population_id=population_id,
        observations=[
            {'context': context, 'hand_id': 'exact', 'action': 'RAISE', 'target_total_bb': 7.0}
        ]
        + _rows(sibling, 'sibling', hierarchical.MIN_MARGINAL_OBSERVATIONS, 9.0),
    )
    unresolved = hierarchical.make_synthetic_hierarchical_candidate(
        population_id=population_id,
        observations=[],
    )

    scenarios: dict[str, Any] = {}
    for name, candidate in (
        ('exact_empirical_strong', strong),
        ('hierarchical_estimate', pooled),
        ('unresolved', unresolved),
    ):
        response = hierarchical.resolve_exact_context(candidate=candidate, context=context)
        scenarios[name] = {
            'candidate': candidate,
            'response': response,
            'status': response['status'],
            'candidate_sha256': hierarchical.canonical_candidate_sha256(candidate),
            'response_sha256': hierarchical.canonical_response_sha256(response),
            'support_observations': response['support']['observations'],
            'support_effective_sample_size': response['support']['effective_sample_size'],
            'pooling_level': (response['pooling'] or {}).get('level'),
            'pooling_source_key': (response['pooling'] or {}).get('source_key'),
            'uncertainty_method': (response['uncertainty'] or {}).get('method'),
            'reason_code': response['reason_code'],
            'unresolved_reason': response.get('unresolved_reason'),
        }
    return scenarios


def _parity_entry(name: str, location: str, provider: Any, schema: Any) -> dict[str, Any]:
    return {'name': name, 'location': location, 'provider': provider, 'schema': schema, 'match': provider == schema}


def provider_schema_parity(hierarchical_schema: Mapping[str, Any]) -> dict[str, Any]:
    identity = hierarchical_schema['$defs']['identity']['properties']
    shrinkage = hierarchical_schema['properties']['shrinkage']['properties']
    thresholds = hierarchical_schema['properties']['thresholds']['properties']
    pooling_enum = list(hierarchical_schema['$defs']['poolingLevel']['properties']['level']['enum'])
    status_enum = list(hierarchical_schema['$defs']['status']['enum'])
    reason_enum = list(hierarchical_schema['$defs']['reasonCode']['enum'])
    granularity = hierarchical_schema['$defs']['response']['properties']['granularity']['properties']
    support = hierarchical_schema['$defs']['response']['properties']['support']['properties']

    entries = [
        _parity_entry('schema', 'properties.schema.const', hierarchical.SCHEMA,
                      hierarchical_schema['properties']['schema']['const']),
        _parity_entry('candidate_id', '$defs.identity.properties.candidate_id.const',
                      hierarchical.CANDIDATE_ID, identity['candidate_id']['const']),
        _parity_entry('model_family', '$defs.identity.properties.model_family.const',
                      hierarchical.MODEL_FAMILY, identity['model_family']['const']),
        _parity_entry('status', '$defs.identity.properties.status.const',
                      hierarchical.CANDIDATE_STATUS, identity['status']['const']),
        _parity_entry('feature_contract', '$defs.identity.properties.feature_contract.const',
                      hierarchical.PUBLIC_CONTEXT_SCHEMA, identity['feature_contract']['const']),
        _parity_entry('likelihood_contract', '$defs.identity.properties.likelihood_contract.const',
                      hierarchical.SCHEMA, identity['likelihood_contract']['const']),
        _parity_entry('response_contract', '$defs.identity.properties.response_contract.const',
                      hierarchical.RESPONSE_SCHEMA, identity['response_contract']['const']),
        _parity_entry('hierarchy_spec_schema', '$defs.identity.properties.hierarchy_spec_schema.const',
                      hierarchical.HIERARCHY_SPEC_SCHEMA, identity['hierarchy_spec_schema']['const']),
        _parity_entry('identity_granularity', '$defs.identity.properties.identity_granularity.const',
                      hierarchical.EXACT_GRANULARITY, identity['identity_granularity']['const']),
        _parity_entry('support_isolation_rule', '$defs.identity.properties.support_isolation_rule.const',
                      hierarchical.SUPPORT_ISOLATION_RULE, identity['support_isolation_rule']['const']),
        _parity_entry('active_model_replaced', '$defs.identity.properties.active_model_replaced.const',
                      False, identity['active_model_replaced']['const']),
        _parity_entry('statuses', '$defs.status.enum', list(hierarchical.STATUSES), status_enum),
        _parity_entry('reason_codes', '$defs.reasonCode.enum', list(PROVIDER_REASON_CODES), reason_enum),
        _parity_entry('support_laundering_is_not_a_response_reason',
                      '$defs.reasonCode.enum excludes support laundering',
                      hierarchical.SUPPORT_LAUNDERING_REASON in reason_enum, False),
        _parity_entry('pooling_levels', '$defs.poolingLevel.properties.level.enum',
                      list(hierarchical.POOLING_LEVELS), pooling_enum),
        _parity_entry('kappa0', 'properties.shrinkage.properties.kappa0.const',
                      hierarchical.KAPPA0, shrinkage['kappa0']['const']),
        _parity_entry('alpha_per_legal_marginal_action',
                      'properties.shrinkage.properties.alpha_per_legal_marginal_action.const',
                      hierarchical.ALPHA_PER_LEGAL_ACTION,
                      shrinkage['alpha_per_legal_marginal_action']['const']),
        _parity_entry('minimum_marginal_observations',
                      'properties.thresholds.properties.minimum_marginal_observations.const',
                      hierarchical.MIN_MARGINAL_OBSERVATIONS,
                      thresholds['minimum_marginal_observations']['const']),
        _parity_entry('minimum_distinct_hands',
                      'properties.thresholds.properties.minimum_distinct_hands.const',
                      hierarchical.MIN_DISTINCT_HANDS, thresholds['minimum_distinct_hands']['const']),
        _parity_entry('granularity.identity',
                      '$defs.response.properties.granularity.properties.identity.const',
                      hierarchical.EXACT_GRANULARITY, granularity['identity']['const']),
        _parity_entry('granularity.support',
                      '$defs.response.properties.granularity.properties.support.const',
                      hierarchical.SUPPORT_LEVEL, granularity['support']['const']),
        _parity_entry('support.effective_sample_size present',
                      '$defs.response.properties.support.properties.effective_sample_size',
                      True, 'effective_sample_size' in support),
    ]
    return {
        'entries': entries,
        'all_match': all(entry['match'] for entry in entries),
        'mismatches': [entry['name'] for entry in entries if not entry['match']],
    }


def active_pointer_report(registry: Mapping[str, Any], registry_text: str) -> dict[str, Any]:
    promoted = registry.get('promoted_model') or {}
    preflop = promoted.get('preflop')
    postflop = promoted.get('postflop')
    promoted_run = registry.get('promoted_run')
    reference_sha = sha256_file(REFERENCE)
    promoted_target = (ROOT / preflop).resolve() if isinstance(preflop, str) else None
    report = {
        'registry_path': str(REGISTRY_PATH.relative_to(ROOT)),
        'registry_sha256': sha256_file(REGISTRY_PATH),
        'promoted_preflop': preflop,
        'promoted_postflop': postflop,
        'promoted_run': promoted_run,
        'reference_model_path': str(REFERENCE.relative_to(ROOT)),
        'reference_model_sha256': reference_sha,
        'reference_pinned_sha256': PINNED_REFERENCE_HASH,
        'reference_matches_pin': reference_sha == PINNED_REFERENCE_HASH,
        'preflop_pointer_unchanged': preflop == PINNED_PROMOTED_PREFLOP,
        'postflop_pointer_unchanged': postflop == PINNED_PROMOTED_POSTFLOP,
        'promoted_run_unchanged': promoted_run == PINNED_PROMOTED_RUN,
        'preflop_pointer_targets_reference': promoted_target == REFERENCE.resolve(),
        'candidate_mentioned_in_registry': hierarchical.CANDIDATE_ID in registry_text,
        'candidate_promoted': hierarchical.CANDIDATE_ID in json.dumps(promoted, sort_keys=True),
    }
    report['pointer_unchanged'] = all(
        [
            report['reference_matches_pin'],
            report['preflop_pointer_unchanged'],
            report['postflop_pointer_unchanged'],
            report['promoted_run_unchanged'],
            report['preflop_pointer_targets_reference'],
            not report['candidate_mentioned_in_registry'],
            not report['candidate_promoted'],
        ]
    )
    return report


def _exact_candidate(candidate_id: str, context: Mapping[str, Any], population_id: str) -> dict[str, Any]:
    candidate = exact_price.make_synthetic_candidate(
        population_id=population_id,
        rows=[
            {
                'context': context,
                'node_id': 'contract-node',
                'probabilities': {'FOLD': 0.25, 'CALL': 0.25, 'RAISE': 0.25, 'JAM': 0.25},
                'support': 8,
            }
        ],
    )
    candidate['identity'] = exact_price.candidate_identity(
        population_id=population_id, candidate_id=candidate_id
    )
    return candidate


def exact_price_non_regression(exact_schema: Mapping[str, Any]) -> dict[str, Any]:
    fixture = _fixture()
    base_input = fixture['contexts'][0]['input']
    population_id = fixture['population_id']
    context = _context(base_input)
    enum = list(exact_schema['properties']['identity']['properties']['candidate_id']['enum'])
    candidates: dict[str, Any] = {}
    for label, candidate_id in (
        ('v1', exact_price.RUNTIME_CANDIDATE_ID),
        ('v2', exact_price.RUNTIME_CANDIDATE_V2_ID),
    ):
        candidate = _exact_candidate(candidate_id, context, population_id)
        exact_price.validate_candidate(candidate)
        errors = schema_errors(exact_schema, candidate)
        resolved = exact_price.resolve_likelihood(candidate=candidate, context=context, hand_class=None)
        candidates[label] = {
            'candidate_id': candidate_id,
            'schema_errors': errors,
            'valid': errors == [],
            'resolved_status': resolved['status'],
            'backoff_level': resolved['backoff_level'],
            'candidate_sha256': exact_price.canonical_candidate_sha256(candidate),
        }
    report = {
        'candidate_enum': enum,
        'v1_present': exact_price.RUNTIME_CANDIDATE_ID in enum,
        'v2_present': exact_price.RUNTIME_CANDIDATE_V2_ID in enum,
        'hierarchical_registered_in_identity_list': hierarchical.CANDIDATE_ID in enum,
        'backoff_policy_unchanged': exact_schema['properties']['backoff_policy']['const']
        == list(exact_price.BACKOFF_POLICY),
        'nearest_price_fallback_false': exact_schema['properties']['nearest_price_fallback']['const'] is False,
        'candidates': candidates,
    }
    report['all_valid'] = all(entry['valid'] for entry in candidates.values())
    report['non_regressed'] = all(
        [
            report['v1_present'],
            report['v2_present'],
            report['hierarchical_registered_in_identity_list'],
            report['backoff_policy_unchanged'],
            report['nearest_price_fallback_false'],
            report['all_valid'],
        ]
    )
    return report


def _validate_provider_outputs(
    hierarchical_schema: Mapping[str, Any], scenarios: Mapping[str, Any]
) -> dict[str, Any]:
    response_ref = {'$ref': '#/$defs/response'}
    outputs: dict[str, Any] = {}
    for name, scenario in scenarios.items():
        candidate_errors = schema_errors(hierarchical_schema, scenario['candidate'])
        response_errors = schema_errors(hierarchical_schema, scenario['response'], response_ref)
        outputs[name] = {
            'status': scenario['status'],
            'candidate_schema_errors': candidate_errors,
            'response_schema_errors': response_errors,
            'valid': candidate_errors == [] and response_errors == [],
            'support_observations': scenario['support_observations'],
            'support_effective_sample_size': scenario['support_effective_sample_size'],
            'pooling_level': scenario['pooling_level'],
            'pooling_source_key': scenario['pooling_source_key'],
            'uncertainty_method': scenario['uncertainty_method'],
            'reason_code': scenario['reason_code'],
            'unresolved_reason': scenario['unresolved_reason'],
            'candidate_sha256': scenario['candidate_sha256'],
            'response_sha256': scenario['response_sha256'],
        }
    return {
        'outputs': outputs,
        'statuses': sorted({entry['status'] for entry in outputs.values()}),
        'all_valid': all(entry['valid'] for entry in outputs.values()),
    }


def build_contract() -> dict[str, Any]:
    hierarchical_schema, exact_schema = load_schemas()
    registry_text = REGISTRY_PATH.read_text(encoding='utf-8')
    registry = json.loads(registry_text)

    protected = [REGISTRY_PATH, POPULATIONS_REGISTRY_PATH, REFERENCE, HIERARCHICAL_SCHEMA_PATH, EXACT_SCHEMA_PATH]
    before = {str(path.relative_to(ROOT)): sha256_file(path) for path in protected}

    required_fields = required_field_report(hierarchical_schema)
    if not required_fields['all_present']:
        missing = [name for name, entry in required_fields.items() if isinstance(entry, dict) and not entry['present']]
        raise ValueError(f'required hierarchical fields missing from schema: {missing}')

    parity = provider_schema_parity(hierarchical_schema)
    if not parity['all_match']:
        raise ValueError(f'provider/schema parity failed: {parity["mismatches"]}')

    scenarios = build_provider_scenarios()
    provider_outputs = _validate_provider_outputs(hierarchical_schema, scenarios)
    if not provider_outputs['all_valid']:
        raise ValueError('provider outputs do not validate against the hierarchical schema')
    expected_statuses = sorted(hierarchical.STATUSES)
    if provider_outputs['statuses'] != expected_statuses:
        raise ValueError(f'provider did not exercise every status: {provider_outputs["statuses"]}')

    active_pointer = active_pointer_report(registry, registry_text)
    if not active_pointer['pointer_unchanged']:
        raise ValueError('active model pointer is not invariant')

    exact_non_regression = exact_price_non_regression(exact_schema)
    if not exact_non_regression['non_regressed']:
        raise ValueError('exact-price v1/v2 contracts regressed')

    after = {str(path.relative_to(ROOT)): sha256_file(path) for path in protected}
    if before != after:
        raise ValueError('protected active files were mutated during the contract audit')

    return {
        'schema': SCHEMA,
        'issue': 419,
        'candidate_id': hierarchical.CANDIDATE_ID,
        'candidate_ids': list(hierarchical.CANDIDATE_IDS),
        'statuses': list(hierarchical.STATUSES),
        'schemas': {
            'hierarchical': {
                'path': str(HIERARCHICAL_SCHEMA_PATH.relative_to(ROOT)),
                '$id': hierarchical_schema['$id'],
                'sha256': sha256_file(HIERARCHICAL_SCHEMA_PATH),
            },
            'exact_price': {
                'path': str(EXACT_SCHEMA_PATH.relative_to(ROOT)),
                '$id': exact_schema['$id'],
                'sha256': sha256_file(EXACT_SCHEMA_PATH),
            },
        },
        'required_hierarchical_fields': required_fields,
        'provider_schema_parity': parity,
        'provider_outputs': provider_outputs,
        'active_pointer': active_pointer,
        'exact_price_non_regression': exact_non_regression,
        'protected_files_before_after_sha256': {
            'before': before,
            'after': after,
            'unchanged': before == after,
        },
        'source_files_sha256': {
            str(path.relative_to(ROOT)): sha256_file(path)
            for path in sorted(
                {
                    Path(__file__),
                    Path(hierarchical.__file__),
                    Path(exact_price.__file__),
                    HIERARCHICAL_SCHEMA_PATH,
                    EXACT_SCHEMA_PATH,
                    REGISTRY_PATH,
                    REFERENCE,
                }
            )
        },
    }


def build_summary(contract: Mapping[str, Any], digest: str) -> str:
    pointer = contract['active_pointer']
    outputs = contract['provider_outputs']['outputs']
    return (
        '# #419 -- hierarchical Model-A sizing candidate contract\n\n'
        f"Candidate `{contract['candidate_id']}` ({', '.join(contract['candidate_ids'])}), "
        f"statuses {', '.join(contract['statuses'])}.\n\n"
        'The contract is declared by the hierarchical schema '
        f"`{contract['schemas']['hierarchical']['path']}` and the exact-price schema "
        f"`{contract['schemas']['exact_price']['path']}`. The mandatory hierarchical fields "
        '(status, exact empirical observations, effective sample size, pooling level/source, '
        'uncertainty, reason codes) are present at their required locations, and every frozen '
        'provider constant equals the schema const/enum that publishes it '
        f'(parity mismatches: {len(contract["provider_schema_parity"]["mismatches"])}).\n\n'
        'Real provider outputs at all three statuses validate against the schema: '
        + ', '.join(
            f"{name}={entry['status']} (obs={entry['support_observations']}, "
            f"ess={entry['support_effective_sample_size']}, pooling={entry['pooling_level']}, "
            f"reason={entry['unresolved_reason'] or entry['reason_code']})"
            for name, entry in sorted(outputs.items())
        )
        + '.\n\n'
        f"Active pointer unchanged: `{pointer['registry_path']}` still promotes "
        f"`{pointer['promoted_preflop']}` (sha256 `{pointer['reference_model_sha256']}`), the pinned "
        f"reference matches ({pointer['reference_matches_pin']}), the candidate is never registered "
        f"(mentioned={pointer['candidate_mentioned_in_registry']}, "
        f"promoted={pointer['candidate_promoted']}), and the protected files are byte-identical "
        'before/after the audit.\n\n'
        f"Exact-price v1/v2 non-regression: v1 present={contract['exact_price_non_regression']['v1_present']}, "
        f"v2 present={contract['exact_price_non_regression']['v2_present']}, "
        f"both validate={contract['exact_price_non_regression']['all_valid']}.\n\n"
        'Reproduce: `python3 tools/training/audit_hierarchical_candidate_contract.py`. '
        f'Contract byte SHA256: `{digest}`.\n'
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()

    if sha256_file(REFERENCE) != EXPECTED_REFERENCE_HASH:
        raise ValueError('active reference SHA mismatch')

    contract = build_contract()
    data = (json.dumps(contract, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    digest = hashlib.sha256(data).hexdigest()
    legacy.persist(args.output, {CONTRACT_NAME: contract}, build_summary(contract, digest))
    print(
        json.dumps(
            {
                'schema': SCHEMA,
                'contract_sha256': digest,
                'canonical_payload_sha256': stable_hash(contract),
                'candidate_id': contract['candidate_id'],
                'provider_schema_parity': contract['provider_schema_parity']['all_match'],
                'provider_outputs_valid': contract['provider_outputs']['all_valid'],
                'statuses': contract['provider_outputs']['statuses'],
                'active_pointer_unchanged': contract['active_pointer']['pointer_unchanged'],
                'exact_price_non_regressed': contract['exact_price_non_regression']['non_regressed'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
