#!/usr/bin/env python3
"""#419 hierarchical exact-context model spec regressions.

The spec is content-addressed, TRAIN-only and authored before any VALIDATION
read. These tests never parse a holdout hand either.
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training import audit_hierarchical_tree_sparsity as baseline_tool
from tools.training import write_hierarchical_model_spec as spec_tool


def resolve(payload, path):
    node = payload
    for part in path.split('.'):
        if isinstance(node, list):
            node = node[int(part)]
        else:
            node = node[part]
    return node


class HierarchicalModelSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec_bytes = spec_tool.SPEC_PATH.read_bytes()
        cls.spec = json.loads(cls.spec_bytes)
        cls.index = json.loads((spec_tool.BUNDLE / 'ARTIFACTS.json').read_text())
        cls.baseline = json.loads(spec_tool.BASELINE_PATH.read_text())
        cls.digest = hashlib.sha256(cls.spec_bytes).hexdigest()

    def test_spec_is_content_addressed_and_byte_identical(self):
        self.assertEqual(self.digest, self.index[spec_tool.SPEC_NAME]['sha256'])
        self.assertEqual(
            self.index[spec_tool.SPEC_NAME]['canonical_payload_sha256'],
            baseline_tool.stable_hash(self.spec),
        )
        self.assertEqual(self.spec_bytes, (spec_tool.BUNDLE / spec_tool.SPEC_NAME).read_bytes())
        self.assertEqual(
            self.spec_bytes,
            (spec_tool.BUNDLE / self.index[spec_tool.SPEC_NAME]['object']).read_bytes(),
        )
        for name, entry in self.index.items():
            data = (spec_tool.BUNDLE / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'], name)
            self.assertEqual(data, (spec_tool.BUNDLE / entry['object']).read_bytes(), name)
        self.assertEqual(
            {p.name for p in (spec_tool.BUNDLE / 'sha256').iterdir()},
            {Path(entry['object']).name for entry in self.index.values()},
        )
        sidecar = spec_tool.DIGEST_PATH.read_text().splitlines()[0].split()
        self.assertEqual(sidecar, [self.digest, spec_tool.SPEC_NAME])
        self.assertEqual(self.spec['schema'], spec_tool.SCHEMA)
        self.assertEqual(self.spec['issue'], 419)
        self.assertEqual(self.spec['status'], 'SPEC_ONLY_NOT_ADMITTED')

    def test_covers_the_ten_points_with_resolvable_sections(self):
        coverage = self.spec['ten_point_coverage']
        self.assertEqual([row['point'] for row in coverage], list(range(1, 11)))
        for row in coverage:
            with self.subTest(point=row['point']):
                self.assertTrue(row['title'])
                self.assertTrue(row['requirement'])
                self.assertTrue(row['sections'])
                for section in row['sections']:
                    self.assertIsNotNone(resolve(self.spec, section), section)

    def test_mutualizable_and_never_mutualizable_axes_are_explicit_and_disjoint(self):
        axes = self.spec['parameter_pooling']['axes']
        mutualizable, frozen = axes['mutualizable'], axes['never_mutualizable']
        self.assertTrue(set(mutualizable).isdisjoint(set(frozen)))
        self.assertEqual(
            set(mutualizable) | set(frozen),
            {row['axis'] for row in axes['axis_table']},
        )
        # ticket point 3: requested key identity, exact price and positions are frozen
        for axis in ('requested_key_identity', 'target_total_bb', 'to_call_bb',
                     'actor_position', 'aggressor_position'):
            self.assertIn(axis, frozen)
        level_ids = [level['level'] for level in self.spec['hierarchy_prior_shrinkage']['levels']]
        for row in axes['axis_table']:
            with self.subTest(axis=row['axis']):
                self.assertEqual(
                    row['mutualizable_in_parameters'],
                    row['axis'] in mutualizable,
                )
                self.assertTrue(row['identity_axis'])
                if row['mutualizable_in_parameters']:
                    self.assertIn(row['pooling_level_if_mutualizable'], level_ids)
                else:
                    self.assertIsNone(row['pooling_level_if_mutualizable'])

    def test_every_level_retains_the_never_mutualizable_axes(self):
        frozen = set(self.spec['parameter_pooling']['axes']['never_mutualizable'])
        for level in self.spec['hierarchy_prior_shrinkage']['levels']:
            with self.subTest(level=level['level']):
                self.assertTrue(frozen.issubset(set(level['retains'])))
                self.assertFalse(frozen & set(level['drops']))
        levels = {level['level']: level for level in self.spec['hierarchy_prior_shrinkage']['levels']}
        self.assertEqual(levels['L0_EXACT_KEY']['purpose'], 'SUPPORT_AND_IDENTITY')
        # only L0 may be a support source
        self.assertTrue(levels['L0_EXACT_KEY']['support_source_allowed'])
        for name, level in levels.items():
            if name != 'L0_EXACT_KEY':
                self.assertFalse(level['support_source_allowed'])
        self.assertTrue(levels['L3_RUNTIME_SUPPORT_CONTEXT']['equals_runtime_provider_key'])

    def test_no_key_may_be_declared_supported_by_another_key(self):
        rule = self.spec['support_isolation_rule']
        self.assertEqual(rule['rule_id'], 'SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT')
        self.assertIn('may never be declared supported by observations of a different key', rule['statement'])
        self.assertEqual(rule['runtime_invariant'], 'support.source_key == requested_key')
        self.assertIn('raise', rule['fail_closed'])
        self.assertEqual(
            rule['violation_reason_code'], 'COARSE_KEY_SUPPORT_LAUNDERING')
        self.assertEqual(
            rule['evidence']['collision_groups_where_the_coarse_key_merges_fine_keys'],
            self.baseline['summary']['runtime_keys_merging_audit_states'],
        )
        self.assertGreater(rule['evidence']['collision_groups_where_the_coarse_key_merges_fine_keys'], 0)
        self.assertGreater(
            rule['evidence']['distinct_fine_keys'], rule['evidence']['distinct_coarse_keys'])
        self.assertIn(
            'support.source_key != requested_key -> error (COARSE_KEY_SUPPORT_LAUNDERING)',
            self.spec['runtime_support_contract']['fail_closed'],
        )
        support_fields = {
            row['field'] for row in self.spec['runtime_support_contract']['response_fields']
        }
        for field in ('support.observations', 'support.distinct_hands', 'support.effective_sample_size',
                      'support.source_key', 'support.borrowed_from_other_keys',
                      'pooling.level', 'pooling.source_key', 'uncertainty', 'reason_code'):
            self.assertIn(field, support_fields)

    def test_granularity_decision_faces_the_coarse_merge_risk(self):
        decision = self.spec['granularity_decision']
        self.assertEqual(decision['risk_addressed'], 'RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE')
        self.assertEqual(
            decision['chosen_granularity']['identity_and_support_granularity'],
            'hierarchical_exact_key (L0_EXACT_KEY)',
        )
        self.assertIn('EXACT_HIERARCHICAL_ESTIMATE',
                      decision['chosen_granularity']['consequence'])
        self.assertIn('EXACT_EMPIRICAL_STRONG',
                      decision['chosen_granularity']['consequence'])
        self.assertGreaterEqual(len(decision['rejected_options']), 3)
        self.assertFalse(decision['provider_change_performed_here'])
        self.assertEqual(decision['evidence']['nodes_total'], 38)
        self.assertEqual(
            decision['evidence']['runtime_keys_merging_audit_states'],
            self.baseline['summary']['runtime_keys_merging_audit_states'],
        )
        self.assertEqual(
            decision['evidence']['canonical_co_after_bb_fold']['runtime_observations'],
            self.baseline['canonical_cells']['co_after_bb_fold']['runtime_observations'],
        )

    def test_reason_code_semantics_are_explicit(self):
        codes = self.spec['runtime_support_contract']['reason_codes']
        self.assertEqual(
            sorted(codes), ['EXACT_EMPIRICAL_STRONG', 'EXACT_HIERARCHICAL_ESTIMATE', 'EXACT_UNRESOLVED'])
        self.assertFalse(codes['EXACT_EMPIRICAL_STRONG']['pooling_allowed_for_the_reported_estimate'])
        self.assertIn('L0_EXACT_KEY', codes['EXACT_EMPIRICAL_STRONG']['condition'])
        self.assertTrue(codes['EXACT_HIERARCHICAL_ESTIMATE']['pooling_allowed_for_the_reported_estimate'])
        self.assertIn('requested_key only', codes['EXACT_HIERARCHICAL_ESTIMATE']['support_source'])
        self.assertIn('never an exact-support claim',
                      codes['EXACT_HIERARCHICAL_ESTIMATE']['interpretation'])
        self.assertIn('no answer is emitted', codes['EXACT_UNRESOLVED']['interpretation'])
        self.assertIn(
            'an EXACT_EMPIRICAL_STRONG claim whose pooling level is not L0 -> error',
            self.spec['runtime_support_contract']['fail_closed'],
        )

    def test_two_admissibility_classes_bind_the_v2_protocol_without_relabelling_support(self):
        codes = self.spec['runtime_support_contract']['reason_codes']
        self.assertEqual(len(codes), 3)
        self.assertIn('EXACT_EMPIRICAL_STRONG', codes)
        self.assertIn('EXACT_HIERARCHICAL_ESTIMATE', codes)
        self.assertIn('EXACT_UNRESOLVED', codes)
        # The estimate class keeps exact-key-only counts and is never relabelled as
        # an exact-support claim, whatever pooling level supplies its parameters.
        estimate = codes['EXACT_HIERARCHICAL_ESTIMATE']
        self.assertTrue(estimate['pooling_allowed_for_the_reported_estimate'])
        self.assertIn('requested_key only', estimate['support_source'])
        self.assertIn('never an exact-support claim', estimate['interpretation'])
        self.assertFalse(
            codes['EXACT_EMPIRICAL_STRONG']['pooling_allowed_for_the_reported_estimate']
        )
        self.assertEqual(
            self.spec['decision_thresholds']['minimum_marginal_observations'], 20
        )
        self.assertEqual(self.spec['decision_thresholds']['minimum_distinct_hands'], 20)

        # The frozen v2 protocol binds exactly these classes and inherits the 20/20
        # thresholds verbatim; it adds the conditional estimate closure, not slack.
        v2 = json.loads(
            (
                ROOT
                / 'analysis/issue419_hierarchical_tree/validation_protocol_v2/'
                'FROZEN_VALIDATION_PROTOCOL_V2.json'
            ).read_text()
        )
        self.assertEqual(
            v2['thresholds']['minimum_marginal_observations'],
            self.spec['decision_thresholds']['minimum_marginal_observations'],
        )
        self.assertEqual(
            v2['thresholds']['minimum_distinct_hands'],
            self.spec['decision_thresholds']['minimum_distinct_hands'],
        )
        self.assertTrue(v2['thresholds']['inherited_verbatim_from_v1'])
        self.assertFalse(v2['thresholds']['modified_by_this_revision'])
        layer_b = v2['layers']['layer_b_exact_context_estimate_admissibility']
        conditional = layer_b['counts_as_a_closed_exact_tree_node']
        self.assertEqual(conditional['value'], 'CONDITIONAL')
        self.assertTrue(conditional['true_iff_all_layer_b_gates_pass'])
        self.assertFalse(conditional['default_when_a_gate_is_unevaluated'])
        self.assertFalse(conditional['unconditionally_closes'])
        self.assertEqual(
            sorted(layer_b['admissibility_gate_ids']),
            [
                'CALIBRATION',
                'EFFECTIVE_SAMPLE_SIZE',
                'EXACT_KEY_IDENTITY',
                'POOLING_LEVEL',
                'POOLING_PROVENANCE',
                'RAISE_SIZING_FRONTIER',
                'UNCERTAINTY',
            ],
        )

    def test_written_without_reading_validation(self):
        boundary = self.spec['holdout_boundary']
        self.assertEqual(boundary['split_consumed'], 'TRAIN')
        self.assertFalse(boundary['validation_consumed'])
        self.assertFalse(boundary['test_consumed'])
        self.assertEqual(boundary['validation_decisions_read'], 0)
        self.assertEqual(boundary['validation_hands_parsed'], 0)
        self.assertTrue(boundary['spec_frozen_before_holdout_read'])
        self.assertFalse(boundary['validation_read_before_spec_hash'])
        self.assertEqual(
            [row['result'] for row in boundary['checks']], ['PASS'] * len(boundary['checks']))
        open_trace = next(row for row in boundary['checks']
                          if row['check'] == 'no_hand_level_dataset_read')
        self.assertEqual(open_trace['dataset_or_holdout_files_opened'], [])
        self.assertEqual(open_trace['undeclared_files_opened'], [])
        self.assertTrue(open_trace['observed_files_opened'])
        for path in open_trace['observed_files_opened']:
            with self.subTest(opened=path):
                self.assertNotIn('training/datasets/', path)
                self.assertNotIn('validation', path.lower())
                self.assertNotIn('holdout', path.lower())
        self.assertTrue(self.spec['authoring_order']['spec_written_and_hashed_before_holdout_read'])
        # the consumed evidence really is TRAIN-only
        self.assertEqual(boundary['inputs'][0]['split_consumed'], 'TRAIN')
        for row in boundary['inputs']:
            with self.subTest(path=row['path']):
                self.assertEqual(len(row['sha256']), 64)
                self.assertEqual(
                    spec_tool.sha256_file(ROOT / row['path']), row['sha256'])
        # and the generator itself cannot load a holdout
        self.assertEqual(spec_tool.verify_no_holdout_access()['result'], 'PASS')

    def test_generator_rejects_holdout_loader_usage(self):
        for source in ('import os\nload_validation_records()\n',
                       'from somewhere import validation_records\n',
                       'import validation_split_loader\n',
                       "PATH = 'data/validation.jsonl'\n"):
            with self.subTest(source=source), self.assertRaises(spec_tool.HoldoutAccessError):
                spec_tool.verify_no_holdout_access(source)
        # the shipped source passes the same scan
        spec_tool.verify_no_holdout_access(spec_tool.SOURCE_PATH.read_text())

    def test_tripwire_rejects_a_non_train_declaration(self):
        spec_tool.assert_train_only_artifact('ok', {'split_consumed': 'TRAIN'})
        for bad in ({'split_consumed': 'VALIDATION'}, {'validation_consumed': True},
                    {'test_consumed': True}):
            with self.subTest(bad=bad), self.assertRaises(spec_tool.HoldoutAccessError):
                spec_tool.assert_train_only_artifact('bad', bad)

    def test_deterministic_regeneration_matches_the_persisted_spec(self):
        rebuilt = spec_tool.build()
        self.assertEqual(spec_tool.serialize(rebuilt), self.spec_bytes)
        self.assertEqual(rebuilt, self.spec)
        self.assertEqual(baseline_tool.stable_hash(rebuilt), self.index[spec_tool.SPEC_NAME]['canonical_payload_sha256'])

    def test_thresholds_and_raise_sizing_are_frozen_and_exact_only(self):
        thresholds = self.spec['decision_thresholds']
        self.assertEqual(thresholds['minimum_marginal_observations'], 20)
        self.assertEqual(thresholds['minimum_distinct_hands'], 20)
        self.assertEqual(
            thresholds['minimum_marginal_observations'],
            self.baseline['thresholds']['minimum_marginal_observations'],
        )
        self.assertEqual(
            thresholds['minimum_distinct_hands'],
            self.baseline['thresholds']['minimum_distinct_hands'],
        )
        self.assertTrue(thresholds['thresholds_frozen'])
        self.assertEqual(thresholds['exact_claim_requires'], 'L0_EXACT_KEY meeting both thresholds')
        self.assertTrue(thresholds['abstain']['condition'].startswith('reason_code == EXACT_UNRESOLVED'))
        sizing = self.spec['raise_sizing_policy']
        self.assertEqual(sizing['rule'], 'exact-support-only')
        self.assertFalse(sizing['enumeration_complete'])
        self.assertEqual(
            sizing['unresolved_frontier']['count_in_evidence'],
            self.baseline['issue388_bindings']['unresolved_sizing_frontier_count'],
        )
        for forbidden in ('representative raise price', 'legal-minimum substitution',
                          'nearest-price or nearest-context substitution'):
            self.assertIn(forbidden, sizing['forbidden'])
        self.assertFalse(self.spec['prohibitions']['nearest_price'])
        self.assertFalse(self.spec['prohibitions']['representative_raise_price'])
        self.assertEqual(self.spec['prohibitions']['admission'], 'NONE')

    def test_outputs_enumerate_every_legal_action(self):
        outputs = self.spec['action_outputs']
        self.assertEqual(outputs['output_actions'], ['FOLD', 'CALL', 'RAISE', 'JAM'])
        self.assertIn('CHECK', ' '.join(outputs['conditional_actions']))
        self.assertIn('never prune', outputs['zero_count_policy'])
        self.assertIn('per exact target_total_bb', outputs['raise_outputs_are_not_a_single_number'])
        posterior = next(
            row for row in self.spec['runtime_support_contract']['response_fields']
            if row['field'] == 'posterior'
        )
        for action in ('FOLD', 'CALL', 'RAISE', 'JAM'):
            self.assertIn(action, posterior['meaning'])

    def test_hierarchy_shrinkage_and_rare_class_rules(self):
        hierarchy = self.spec['hierarchy_prior_shrinkage']
        self.assertEqual(hierarchy['hierarchical_strength_kappa0'], 16.0)
        self.assertEqual(hierarchy['base_prior']['alpha_per_legal_marginal_action'], 0.5)
        self.assertIn('kappa0', hierarchy['blend'])
        self.assertTrue(hierarchy['no_hidden_hand_imputation'])
        rare = self.spec['rare_hand_class_inheritance']
        self.assertIn('OWN requested key', rare['rule'])
        self.assertEqual(rare['min_class_observations'], 10)
        for forbidden in ('cross-key hand-class transfer',
                          'conditioning on revealed hole cards or showdown labels'):
            self.assertIn(forbidden, rare['forbidden'])

    def test_calibration_metrics_are_defined_and_split_disciplined(self):
        metrics = self.spec['calibration_and_log_loss']
        self.assertEqual(metrics['primary_metric']['name'], 'multiclass_log_loss')
        self.assertAlmostEqual(metrics['primary_metric']['epsilon_clip'], 1e-12)
        names = [row['name'] for row in metrics['secondary_metrics']]
        for name in ('brier_score', 'ece', 'coverage', 'mean_effective_sample_size'):
            self.assertIn(name, names)
        discipline = metrics['evaluation_split_discipline']
        self.assertEqual(discipline['fit_and_calibration_evidence'], 'TRAIN only')
        self.assertEqual(discipline['test'], 'never')
        self.assertIn('pooling level', metrics['mandatory_reporting'])

    def test_baseline_and_issue388_evidence_are_not_mutated_by_the_spec(self):
        # the #419 sparsity baseline keeps its own content addressing intact
        here = json.loads(spec_tool.BASELINE_INDEX_PATH.read_text())
        for name, entry in here.items():
            data = (spec_tool.HERE / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'], name)
            self.assertEqual(data, (spec_tool.HERE / entry['object']).read_bytes(), name)
        self.assertEqual(
            {p.name for p in (spec_tool.HERE / 'sha256').iterdir()},
            {Path(entry['object']).name for entry in here.values()},
        )
        bindings = self.spec['evidence_bindings']
        self.assertEqual(
            bindings['baseline']['byte_sha256'], here[baseline_tool.BASELINE_NAME]['sha256'])
        self.assertEqual(
            bindings['baseline']['canonical_payload_sha256'], baseline_tool.stable_hash(self.baseline))
        self.assertEqual(
            bindings['issue388']['train_support_canonical_sha256'],
            baseline_tool.ISSUE388_TRAIN_SUPPORT_SHA256,
        )
        self.assertEqual(
            bindings['runtime_key_source_sha256'],
            spec_tool.sha256_file(ROOT / 'tools/preflop/model_a_sizing_likelihood.py'),
        )
        self.assertEqual(
            bindings['spec_generator_sha256'], spec_tool.sha256_file(spec_tool.SOURCE_PATH))
        self.assertFalse(self.spec['not_a_fit'] == '')
        self.assertEqual(self.spec['prohibitions']['cross_key_support_borrowing'], False)

    def test_docs_and_decision_record_pin_the_frozen_spec_identity(self):
        doc = (ROOT / 'docs/hierarchical-exact-context-model.md').read_text()
        self.assertIn(self.digest, doc)
        self.assertIn(self.index[spec_tool.SPEC_NAME]['canonical_payload_sha256'], doc)
        self.assertIn('HIERARCHICAL_MODEL_SPEC.json', doc)
        decision = (
            ROOT / '.project/decisions/20260925-hierarchical-exact-context-model-spec.md'
        ).read_text()
        self.assertIn('SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT', decision)
        self.assertIn('RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE', decision)
        self.assertIn('EXACT_EMPIRICAL_STRONG', decision)


if __name__ == '__main__':
    unittest.main()
