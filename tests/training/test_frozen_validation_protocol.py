#!/usr/bin/env python3
"""#419 frozen VALIDATION protocol regressions.

The protocol is content-addressed, timestamped and authored before any VALIDATION
read. These tests never parse a holdout hand either: they pin the frozen
identity, the three explicit comparators, the frozen thresholds and pooling
limits, the 38-node requirement manifest, the #367 rule, and — most importantly
— the ordering guard that makes the freeze fail when a candidate VALIDATION
result already exists.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training import audit_hierarchical_tree_sparsity as baseline_tool
from tools.training import validation_order_guard as guard
from tools.training import write_frozen_validation_protocol as write_tool
from tools.training.audit_preflop_sizing_support import stable_hash


class FrozenValidationProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol_bytes = write_tool.PROTOCOL_PATH.read_bytes()
        cls.protocol = json.loads(cls.protocol_bytes)
        cls.index = json.loads((write_tool.BUNDLE / 'ARTIFACTS.json').read_text())
        cls.digest = hashlib.sha256(cls.protocol_bytes).hexdigest()
        cls.issue388 = baseline_tool.load_issue388()

    # ------------------------------------------------------------------ identity
    def test_protocol_is_content_addressed_and_byte_identical(self):
        self.assertEqual(self.digest, self.index[write_tool.NAME]['sha256'])
        self.assertEqual(
            self.index[write_tool.NAME]['canonical_payload_sha256'],
            stable_hash(self.protocol),
        )
        self.assertEqual(self.protocol_bytes, (write_tool.BUNDLE / write_tool.NAME).read_bytes())
        self.assertEqual(
            self.protocol_bytes,
            (write_tool.BUNDLE / self.index[write_tool.NAME]['object']).read_bytes(),
        )
        for name, entry in self.index.items():
            data = (write_tool.BUNDLE / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'], name)
            self.assertEqual(data, (write_tool.BUNDLE / entry['object']).read_bytes(), name)
        self.assertEqual(
            {p.name for p in (write_tool.BUNDLE / 'sha256').iterdir()},
            {Path(entry['object']).name for entry in self.index.values()},
        )
        sidecar = write_tool.DIGEST_PATH.read_text().splitlines()
        self.assertEqual(sidecar[0].split(), [self.digest, write_tool.NAME])
        self.assertEqual(
            sidecar[1].split(),
            ['#', 'canonical_payload_sha256', stable_hash(self.protocol)],
        )
        self.assertEqual(self.protocol['schema'], write_tool.SCHEMA)
        self.assertEqual(self.protocol['issue'], 419)
        self.assertEqual(self.protocol['status'], guard.FROZEN_STATUS)
        self.assertEqual(self.protocol['kind'], 'FROZEN_VALIDATION_PROTOCOL')

    def test_deterministic_regeneration_matches_the_persisted_protocol(self):
        # T7 (`analysis/issue419_hierarchical_tree/validation/VALIDATION_RESULT.json`)
        # consumed the holdout after this freeze, so a live rebuild now aborts in
        # the order guard by design.  Replaying the *pre-freeze* order-guard
        # evidence shows the frozen payload itself did not move: the rebuilt bytes
        # are still identical to the persisted protocol.
        pre_freeze_evidence = dict(self.protocol['holdout_boundary']['checks'][2])
        with mock.patch.object(
            write_tool.guard,
            'assert_validation_not_yet_consumed',
            return_value=pre_freeze_evidence,
        ):
            rebuilt = write_tool.build(frozen_at=self.protocol['frozen_at'])
        self.assertEqual(write_tool.serialize(rebuilt), self.protocol_bytes)
        self.assertEqual(rebuilt, self.protocol)
        self.assertEqual(
            stable_hash(rebuilt),
            self.index[write_tool.NAME]['canonical_payload_sha256'],
        )

    def test_protocol_is_hashed_and_timestamped_before_any_evaluation(self):
        self.assertEqual(self.protocol['status'], 'FROZEN_BEFORE_VALIDATION')
        frozen_at = self.protocol['frozen_at']
        parsed = dt.datetime.strptime(frozen_at, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc)
        self.assertEqual(int(parsed.timestamp()), self.protocol['frozen_at_epoch'])
        self.assertEqual(self.protocol['spec_frozen_date'], '2026-09-25')
        order = self.protocol['authoring_order']
        self.assertTrue(order['protocol_written_and_hashed_before_validation_read'])
        self.assertFalse(order['validation_read_before_protocol_hash'])
        self.assertFalse(order['evaluation_split_opened_during_authoring'])
        boundary = self.protocol['holdout_boundary']
        self.assertEqual(boundary['split_consumed_for_authoring'], 'TRAIN')
        self.assertFalse(boundary['validation_consumed_for_authoring'])
        self.assertEqual(boundary['validation_decisions_read'], 0)
        self.assertEqual(boundary['validation_hands_parsed'], 0)
        self.assertFalse(boundary['test_consumed'])
        self.assertFalse(boundary['validation_read_before_protocol_hash'])
        self.assertTrue(boundary['protocol_frozen_before_holdout_read'])
        self.assertEqual([row['result'] for row in boundary['checks']], ['PASS'] * len(boundary['checks']))
        no_dataset = next(row for row in boundary['checks'] if row['check'] == 'no_hand_level_dataset_read')
        self.assertTrue(no_dataset['filesystem_open_tripwire_enabled'])
        self.assertEqual(no_dataset['dataset_or_holdout_files_opened'], [])

    def test_predecessor_validation_read_is_recorded_not_repaired(self):
        rows = self.protocol['holdout_boundary']['predecessor_validation_reads']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['issue'], 352)
        self.assertEqual(row['candidate_id'], write_tool.ISSUE352_CANDIDATE_ID)
        self.assertEqual(row['outcome'], 'ADMIT_CANDIDATE')
        self.assertTrue(row['read_before_this_freeze'])
        self.assertFalse(row['reads_this_candidate_holdout'])
        self.assertEqual(row['scope'], 'DIFFERENT_CANDIDATE_UNDER_ITS_OWN_FROZEN_PROTOCOL')

    # -------------------------------------------------------------- comparators
    def test_active_v2_and_new_candidate_are_explicitly_listed(self):
        comparators = self.protocol['comparators']
        active = comparators['active_reference']
        self.assertEqual(active['id'], 'active-model-a-preflop-v5')
        self.assertEqual(active['sha256'], write_tool.REFERENCE_SHA256)
        self.assertTrue(active['sha256'].startswith('ff952055'))
        self.assertEqual(active['role'], 'ACTIVE_REFERENCE')
        self.assertFalse(active['is_mutated_by_this_protocol'])

        v2 = comparators['candidate_v2_352']
        self.assertEqual(v2['id'], 'model-a-preflop-sizing-aware-candidate-v2')
        self.assertEqual(v2['candidate_sha256'], write_tool.ISSUE352_CANDIDATE_SHA256)
        self.assertTrue(v2['candidate_sha256'].startswith('9115165c'))
        pinning = v2['evidence_pinning']
        self.assertEqual(pinning['fit_artifact']['sha256'], write_tool.ISSUE352_FIT_BYTE_SHA256)
        self.assertEqual(
            pinning['validation_protocol']['sha256'], write_tool.ISSUE352_VALIDATION_PROTOCOL_SHA256)
        self.assertEqual(
            pinning['validation_protocol']['frozen_train_fit_candidate_sha256'],
            write_tool.ISSUE352_CANDIDATE_SHA256,
        )
        self.assertEqual(
            pinning['validation_evidence']['evidence_sha256'],
            write_tool.ISSUE352_VALIDATION_EVIDENCE_SHA256,
        )
        self.assertEqual(pinning['validation_evidence']['outcome'], 'ADMIT_CANDIDATE')
        self.assertFalse(pinning['validation_evidence']['test_consumed'])
        self.assertFalse(v2['re_reads_this_candidate_holdout'])

        new = comparators['new_candidate']
        self.assertEqual(new['id'], guard.CANDIDATE_ID)
        self.assertEqual(new['canonical_payload_sha256'], guard.CANDIDATE_CANONICAL_SHA256)
        self.assertEqual(new['byte_sha256'], guard.CANDIDATE_BYTE_SHA256)
        self.assertEqual(new['role'], 'CANDIDATE_UNDER_TEST')
        self.assertTrue(new['distinct_from_issue352_candidate'])
        self.assertEqual(comparators['comparator_count'], 3)
        self.assertTrue(comparators['explicitly_listed'])

    # ----------------------------------------------------- thresholds / pooling
    def test_thresholds_and_pooling_limits_are_frozen_and_immutable(self):
        thresholds = self.protocol['thresholds']
        self.assertTrue(thresholds['frozen'])
        self.assertTrue(thresholds['immutable_after_freeze'])
        self.assertEqual(thresholds['minimum_marginal_observations'], 20)
        self.assertEqual(thresholds['minimum_distinct_hands'], 20)
        self.assertEqual(thresholds['minimum_identifiable_validation_decisions'], 200)
        self.assertEqual(thresholds['non_inferiority_ci_upper_bound'], 0.0)
        self.assertEqual(thresholds['maximum_absolute_ece'], 0.05)
        self.assertIn('L0_EXACT_KEY', thresholds['exact_claim_requires'])
        self.assertFalse(thresholds['coverage_is_not_an_admission_gate'] is None)

        pooling = self.protocol['pooling_limits']
        self.assertTrue(pooling['frozen'])
        self.assertTrue(pooling['immutable_after_freeze'])
        self.assertEqual(pooling['only_support_source_level'], 'L0_EXACT_KEY')
        self.assertEqual(pooling['maximum_pooling_level_for_an_exact_support_claim'], 'L0_EXACT_KEY')
        self.assertEqual(pooling['maximum_pooling_level_for_a_reported_estimate'],
                         'L4_POSITION_PRICE_PRIOR')
        self.assertEqual(pooling['maximum_pooling_depth'], 4)
        self.assertEqual(pooling['fixed_shrinkage_strength_kappa0'], 16.0)
        self.assertEqual(pooling['alpha_per_legal_marginal_action'], 0.5)
        levels = {row['level']: row for row in pooling['acceptable_levels']}
        self.assertEqual(sorted(levels), ['L0_EXACT_KEY', 'L1_STACK_POOL', 'L2_POT_POOL',
                                          'L3_RUNTIME_SUPPORT_CONTEXT', 'L4_POSITION_PRICE_PRIOR'])
        self.assertTrue(levels['L0_EXACT_KEY']['support_source_allowed'])
        for name, row in levels.items():
            if name != 'L0_EXACT_KEY':
                self.assertFalse(row['support_source_allowed'], name)
        self.assertTrue(levels['L3_RUNTIME_SUPPORT_CONTEXT']['allowed_in_validation_output'])
        for forbidden in ('cross-key support borrowing', 'nearest-price or nearest-context substitution',
                          'hidden-hand imputation'):
            self.assertIn(forbidden, pooling['forbidden'])
        self.assertEqual(pooling['rule_id'], 'SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT')

    def test_architecture_priors_seeds_metrics_and_schema_are_complete(self):
        architecture = self.protocol['architecture']
        self.assertEqual(architecture['contract_candidate_id'], guard.CANDIDATE_ID)
        self.assertEqual(architecture['estimator'], 'hierarchical_dirichlet_shrinkage')
        self.assertEqual(architecture['hyperparameters']['hierarchical_strength_kappa0'], 16.0)
        self.assertFalse(architecture['hyperparameters']['hyperparameter_search_performed'])
        self.assertFalse(architecture['hyperparameters']['validation_used_for_hyperparameters'])
        self.assertTrue(architecture['hyperparameters']['hyperparameters_immutable_after_freeze'])
        for flag in ('nearest_price_fallback', 'nearest_context_fallback',
                     'representative_price_fallback', 'hidden_hand_imputation',
                     'pseudo_observation'):
            self.assertIs(architecture[flag], False, flag)

        priors = self.protocol['priors_and_shrinkage']
        self.assertEqual(priors['kappa0'], 16.0)
        self.assertTrue(priors['frozen'])
        self.assertTrue(priors['no_hidden_hand_imputation'])
        self.assertTrue(priors['no_pseudo_observation'])

        seeds = self.protocol['seeds']
        self.assertEqual(seeds['random_seed'], 419)
        self.assertEqual(seeds['stochastic_draws'], 0)
        self.assertEqual(seeds['policy'], 'DETERMINISTIC_NO_RANDOMNESS')

        metrics = self.protocol['metrics']
        self.assertEqual(metrics['primary']['name'], 'multiclass_log_loss')
        self.assertEqual(metrics['primary']['epsilon_clip'], 1e-12)
        self.assertEqual(metrics['paired_unit'], 'hand_id')
        self.assertEqual(metrics['bootstrap']['samples'], 5000)
        self.assertEqual(metrics['bootstrap']['seed'], 419)
        names = [row['name'] for row in metrics['secondary']]
        for name in ('brier_score', 'ece', 'coverage', 'abstain_rate', 'mean_effective_sample_size'):
            self.assertIn(name, names)
        self.assertIn('pooling level', metrics['mandatory_reporting'])

        schema = self.protocol['output_schema']
        self.assertEqual(schema['schema'], guard.RESULT_SCHEMA)
        self.assertEqual(schema['path'], guard.DECLARED_RESULT_LOCATIONS[0])
        for field in ('protocol_byte_sha256', 'protocol_canonical_payload_sha256', 'candidate',
                      'comparators', 'metrics', 'gate', 'outcome', 'evidence_sha256'):
            self.assertIn(field, schema['required_fields'])
        self.assertEqual(sorted(schema['outcome_enum']), ['ADMIT_CANDIDATE', 'RETAIN_ACTIVE_REFERENCE'])
        self.assertFalse(schema['fixed_flags']['test_consumed'])
        self.assertEqual(schema['fixed_flags']['production_effect'], 'NONE')

    # ------------------------------------------------------- requirement manifest
    def test_requirement_manifest_pins_the_38_issue388_nodes(self):
        manifest = self.protocol['requirement_manifest']
        self.assertEqual(manifest['node_count'], 38)
        self.assertEqual(manifest['node_count'], len(manifest['nodes']))
        self.assertEqual(manifest['required_tree_sha256'], baseline_tool.ISSUE388_REQUIRED_TREE_SHA256)
        self.assertEqual(manifest['required_tree_byte_sha256'], baseline_tool.ISSUE388_REQUIRED_TREE_BYTE_SHA256)
        self.assertEqual(manifest['unresolved_sizing_frontier_count'],
                         baseline_tool.ISSUE388_UNRESOLVED_FRONTIERS)
        self.assertFalse(manifest['tree_enumeration_complete'])
        self.assertEqual(manifest['support_isolation_rule'], 'SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT')
        expected = {
            ':'.join(node['path']): (
                node['runtime_support_context_key'],
                node['audit_exact_key'],
                node['runtime_exact_preflop_node_key'],
            )
            for node in self.issue388['tree']['nodes']
        }
        rows = {row['path']: row for row in manifest['nodes']}
        self.assertEqual(set(rows), set(expected))
        for path, (runtime_key, audit_key, node_key) in expected.items():
            with self.subTest(path=path):
                self.assertEqual(rows[path]['runtime_support_context_key'], runtime_key)
                self.assertEqual(rows[path]['audit_exact_key'], audit_key)
                self.assertEqual(rows[path]['runtime_exact_preflop_node_key'], node_key)
                self.assertTrue(rows[path]['actions'])
        # the manifest digest is recomputable from its own rows
        digest_input = [dict(row) for row in sorted(
            manifest['nodes'], key=lambda row: row['path'])]
        self.assertEqual(manifest['manifest_canonical_sha256'], stable_hash(digest_input))
        self.assertEqual(
            manifest['manifest_canonical_sha256'], write_tool._digest_nodes(manifest['nodes']))

    def test_code_and_train_corpus_digests_match_the_persisted_files(self):
        code = self.protocol['code']
        self.assertTrue(code['frozen'])
        roles = {row['role'] for row in code['inputs']}
        for role in ('PROTOCOL_GENERATOR', 'ORDER_GUARD', 'CANDIDATE_FIT_TOOL', 'CANDIDATE_MODEL'):
            self.assertIn(role, roles)
        for row in code['inputs']:
            with self.subTest(path=row['path']):
                self.assertEqual(guard.sha256_file(ROOT / row['path']), row['sha256'])
        self.assertEqual(code['order_guard_sha256'], guard.sha256_file(guard.SOURCE_PATH))
        self.assertEqual(code['protocol_generator_sha256'], guard.sha256_file(write_tool.SOURCE_PATH))

        corpus = self.protocol['train_corpus']
        self.assertEqual(corpus['split_consumed_for_authoring'], 'TRAIN')
        self.assertFalse(corpus['validation_consumed_for_authoring'])
        self.assertFalse(corpus['test_consumed_for_authoring'])
        self.assertEqual(corpus['train_hands_parsed'], 19016)
        self.assertEqual(
            corpus['certification']['sha256'],
            guard.sha256_file(ROOT / corpus['certification']['path']),
        )
        candidate_rows = [row for row in corpus['consumed_artifacts']
                          if row['role'] == 'TRAIN_FIT_CANDIDATE']
        self.assertEqual(candidate_rows[0]['canonical_payload_sha256'], guard.CANDIDATE_CANONICAL_SHA256)

    # ------------------------------------------------------------ #367 rule
    def test_issue367_rule_authorizes_or_forbids_exactly(self):
        rule = self.protocol['issue367_rule']
        self.assertEqual(rule['rule_id'], 'ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE')
        self.assertFalse(rule['authorized_at_freeze'])
        condition = ' '.join(rule['authorized_when'])
        self.assertIn('ADMIT_CANDIDATE', condition)
        self.assertIn(guard.CANDIDATE_CANONICAL_SHA256, condition)
        forbidden = ' '.join(rule['forbidden_while'])
        self.assertIn('RETAIN_ACTIVE_REFERENCE', forbidden)
        admitted = rule['currently_admitted_model_a_for_367']
        self.assertEqual(admitted['candidate_id'], write_tool.ISSUE352_CANDIDATE_ID)
        self.assertEqual(admitted['admission_decision'], 'ADMIT_CANDIDATE')
        self.assertFalse(admitted['active_model_pointer_mutation'])
        self.assertTrue(rule['unchanged_by_this_freeze'])
        self.assertFalse(rule['test_consumed'])
        self.assertFalse(rule['model_b_consumed'])
        self.assertFalse(rule['hero_ev_consumed'])
        self.assertFalse(rule['promotion_performed'])
        publication = self.protocol['publication']
        self.assertEqual(publication['automatic_promotion'], 'FORBIDDEN')
        self.assertEqual(publication['active_reference_mutation'], 'FORBIDDEN')
        self.assertEqual(publication['production_effect'], 'NONE')

    # ------------------------------------------------------------ order guard
    def test_guard_reports_the_consumed_validation_result(self):
        # The freeze-time order-guard evidence is immutable: it recorded the tree
        # as clean *before* the VALIDATION holdout was opened.
        self.assertEqual(self.protocol['order_guard']['result'], 'PASS')
        self.assertEqual(self.protocol['order_guard']['violations'], [])
        self.assertTrue(self.protocol['order_guard']['freeze_authored_before_validation'])
        self.assertFalse(self.protocol['order_guard']['validation_read_before_freeze'])
        self.assertEqual(
            self.protocol['order_guard']['guard_source_sha256'],
            guard.sha256_file(guard.SOURCE_PATH),
        )
        # T7 consumed the holdout exactly once, so the live guard must now fail
        # closed instead of letting a second read (or a post-read re-freeze) hide
        # behind the frozen protocol.
        result_path = ROOT / 'analysis/issue419_hierarchical_tree/validation/VALIDATION_RESULT.json'
        self.assertTrue(result_path.is_file())
        self.assertIn(
            result_path.relative_to(ROOT).as_posix(),
            guard.validation_result_artifacts(ROOT),
        )
        with self.assertRaises(guard.ValidationOrderError):
            guard.assert_validation_not_yet_consumed(ROOT)
        with self.assertRaises(guard.ValidationOrderError):
            guard.assert_protocol_frozen_before_validation(
                write_tool.PROTOCOL_PATH, expected_byte_sha256=self.digest
            )

    def test_order_guard_fails_when_a_candidate_validation_result_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            declared = Path(tmp) / guard.DECLARED_RESULT_LOCATIONS[0]
            declared.parent.mkdir(parents=True)
            declared.write_text('{}')
            self.assertEqual(guard.validation_result_artifacts(tmp), [guard.DECLARED_RESULT_LOCATIONS[0]])
            with self.assertRaises(guard.ValidationOrderError):
                guard.assert_validation_not_yet_consumed(tmp)

    def test_order_guard_content_scan_detects_a_candidate_validation_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = Path(tmp) / 'analysis/somewhere/validation_decisions.json'
            result.parent.mkdir(parents=True)
            result.write_text(json.dumps({
                'outcome': 'ADMIT_CANDIDATE',
                'evidence_sha256': 'x' * 64,
                'split_consumed': 'VALIDATION',
                'candidate': {'candidate_id': guard.CANDIDATE_ID},
            }))
            hits = guard.validation_result_artifacts(tmp)
            self.assertEqual(hits, ['analysis/somewhere/validation_decisions.json'])
            with self.assertRaises(guard.ValidationOrderError):
                guard.assert_validation_not_yet_consumed(tmp)

    def test_order_guard_ignores_other_candidates_and_protocols(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp) / 'analysis/model_a_preflop_sizing_v2_validation.json'
            other.parent.mkdir(parents=True)
            other.write_text(json.dumps({
                'outcome': 'ADMIT_CANDIDATE',
                'evidence_sha256': 'x' * 64,
                'selection_split': 'VALIDATION',
                'inputs': {'candidate_v2': {
                    'candidate_id': write_tool.ISSUE352_CANDIDATE_ID,
                    'candidate_sha256': write_tool.ISSUE352_CANDIDATE_SHA256,
                }},
            }))
            protocol = Path(tmp) / 'analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.json'
            protocol.parent.mkdir(parents=True)
            protocol.write_text(json.dumps({
                'schema': write_tool.SCHEMA,
                'status': guard.FROZEN_STATUS,
                'evaluation': {'split': 'VALIDATION'},
                'candidate': {'candidate_id': guard.CANDIDATE_ID},
            }))
            self.assertEqual(guard.validation_result_artifacts(tmp), [])
            self.assertEqual(guard.assert_validation_not_yet_consumed(tmp)['result'], 'PASS')

    def test_evaluation_side_guard_rejects_a_missing_or_mutated_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / 'FROZEN_VALIDATION_PROTOCOL.json'
            with self.assertRaises(guard.ValidationOrderError):
                guard.assert_protocol_frozen_before_validation(missing)
            tampered = Path(tmp) / 'tampered.json'
            payload = dict(self.protocol)
            tampered.write_text(json.dumps(payload))
            with self.assertRaises(guard.ValidationOrderError):
                guard.assert_protocol_frozen_before_validation(
                    tampered, expected_byte_sha256=self.digest, root=ROOT)
            unfrozen = Path(tmp) / 'unfrozen.json'
            unfrozen_payload = dict(self.protocol)
            unfrozen_payload['status'] = 'DRAFT'
            unfrozen.write_text(json.dumps(unfrozen_payload))
            with self.assertRaises(guard.ValidationOrderError):
                guard.assert_protocol_frozen_before_validation(unfrozen, root=ROOT)

    def test_protocol_writer_is_wired_to_the_order_guard(self):
        with mock.patch.object(
            write_tool.guard,
            'assert_validation_not_yet_consumed',
            side_effect=guard.ValidationOrderError('simulated existing VALIDATION result'),
        ):
            with self.assertRaises(guard.ValidationOrderError):
                write_tool.build()

    # ------------------------------------------------------------ holdout scan
    def test_generator_cannot_read_a_holdout(self):
        for source in ('import os\nload_validation_records()\n',
                       'from somewhere import validation_records\n',
                       'import validation_split_loader\n',
                       "PATH = 'data/validation.jsonl'\n",
                       "ARCHIVE = 'training/datasets/NLHE_100-200/source/holdout.zip'\n"):
            with self.subTest(source=source), self.assertRaises(guard.HoldoutAccessError):
                guard.verify_no_holdout_access(source)
        for path in (write_tool.SOURCE_PATH, guard.SOURCE_PATH):
            with self.subTest(path=str(path)):
                if path == guard.SOURCE_PATH:
                    self.assertEqual(guard.verify_guard_is_holdout_free()['result'], 'PASS')
                else:
                    self.assertEqual(
                        guard.verify_no_holdout_access(
                            path.read_text(), allow_literals=write_tool.SELF_ARTIFACT_LITERALS,
                        )['result'],
                        'PASS',
                    )
        self.assertTrue(guard.is_dataset_open('training/datasets/NLHE_100-200/source/x.zip'))
        self.assertTrue(guard.is_dataset_open('some/decisions.jsonl'))
        self.assertFalse(guard.is_dataset_open('analysis/issue419_hierarchical_tree/fit/CANDIDATE.json'))
        with self.assertRaises(guard.HoldoutAccessError):
            with guard.dataset_access_tripwire():
                Path('training/datasets/NLHE_100-200/source/leak.zip').open('rb').read()

    def test_no_consumed_artifact_declares_a_holdout_read(self):
        for row in self.protocol['train_corpus']['consumed_artifacts']:
            payload = json.loads((ROOT / row['path']).read_text())
            if row['role'] in ('TRAIN_FIT_CANDIDATE', 'TRAIN_FIT_MANIFEST', 'TRAIN_FIT_REPORT'):
                guard.assert_train_only_artifact(row['role'], payload.get('fit', payload))
        guard.assert_train_only_artifact('#419 sparsity baseline',
                                        json.loads(write_tool.BASELINE_PATH.read_text()))

    def test_docs_and_decision_record_pin_the_frozen_protocol_identity(self):
        doc = (ROOT / 'docs/hierarchical-exact-context-validation-protocol.md').read_text()
        self.assertIn(self.digest, doc)
        self.assertIn(self.index[write_tool.NAME]['canonical_payload_sha256'], doc)
        self.assertIn('FROZEN_VALIDATION_PROTOCOL.json', doc)
        decision = (
            ROOT / '.project/decisions/20260925-hierarchical-validation-protocol.md'
        ).read_text()
        self.assertIn('VALIDATION_ORDER_GUARD', decision)
        self.assertIn('ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE', decision)
        self.assertIn('SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT', decision)


if __name__ == '__main__':
    unittest.main()
