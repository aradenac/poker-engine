#!/usr/bin/env python3
"""#419 T7 regressions: the frozen VALIDATION evaluation and its result.

The T6 protocol froze the thresholds, the pooling limits and the three
comparators before the holdout was opened.  These tests never re-parse a holdout
hand: they pin the content-addressed VALIDATION result, the protocol digests it
embeds, the measured calibration / log-loss / coverage, the explicit comparison
to both comparators, the frozen thresholds and the ``test_consumed=false``
boundary.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training import validate_hierarchical_validation as tool
from tools.training import validation_order_guard as guard


class HierarchicalValidationEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result_bytes = tool.RESULT_PATH.read_bytes()
        cls.result = json.loads(cls.result_bytes)
        cls.index = json.loads((tool.OUTPUT / tool.INDEX_NAME).read_text())
        cls.digest = hashlib.sha256(cls.result_bytes).hexdigest()
        cls.protocol = json.loads(tool.PROTOCOL_PATH.read_text())

    # ------------------------------------------------------------ identity
    def test_result_is_content_addressed_and_byte_identical(self):
        self.assertEqual(self.result['schema'], tool.SCHEMA)
        self.assertEqual(self.result['issue'], 419)
        self.assertEqual(self.result['phase'], 'VALIDATION')
        entry = self.index[tool.RESULT_NAME]
        self.assertEqual(self.digest, entry['sha256'])
        self.assertEqual(entry['canonical_payload_sha256'], tool.canonical_hash(self.result))
        self.assertEqual(
            self.result_bytes, (tool.OUTPUT / entry['object']).read_bytes()
        )
        for name, row in self.index.items():
            data = (tool.OUTPUT / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), row['sha256'], name)
            self.assertEqual(data, (tool.OUTPUT / row['object']).read_bytes(), name)
        self.assertEqual(
            {path.name for path in (tool.OUTPUT / 'sha256').iterdir()},
            {Path(row['object']).name for row in self.index.values()},
        )
        sidecar = tool.DIGEST_PATH.read_text().splitlines()
        self.assertEqual(sidecar[0].split(), [entry['sha256'], tool.RESULT_NAME])

    def test_embedded_evidence_digest_follows_the_protocol_rule(self):
        expected = tool.canonical_hash(
            {key: value for key, value in self.result.items() if key != 'evidence_sha256'}
        )
        self.assertEqual(self.result['evidence_sha256'], expected)

    def test_the_result_pins_the_frozen_protocol_bytes(self):
        self.assertEqual(self.result['protocol_byte_sha256'], tool.EXPECTED_PROTOCOL_BYTE_SHA256)
        self.assertEqual(self.result['protocol_byte_sha256'], guard.sha256_file(tool.PROTOCOL_PATH))
        self.assertEqual(
            self.result['protocol_canonical_payload_sha256'],
            tool.EXPECTED_PROTOCOL_CANONICAL_PAYLOAD_SHA256,
        )
        self.assertEqual(self.result['protocol']['frozen_at'], self.protocol['frozen_at'])
        self.assertEqual(
            self.result['protocol']['order_guard']['protocol_byte_sha256'],
            tool.EXPECTED_PROTOCOL_BYTE_SHA256,
        )

    # ---------------------------------------------------------- comparators
    def test_both_comparators_are_explicit_and_unmoved(self):
        comparators = self.result['comparators']
        active = comparators['active_reference']
        self.assertEqual(active['id'], 'active-model-a-preflop-v5')
        self.assertEqual(active['sha256'], tool.EXPECTED_REFERENCE_SHA256)
        self.assertEqual(active['role'], 'ACTIVE_REFERENCE')
        self.assertEqual(guard.sha256_file(tool.REFERENCE), tool.EXPECTED_REFERENCE_SHA256)
        v2 = comparators['candidate_v2_352']
        self.assertEqual(v2['id'], 'model-a-preflop-sizing-aware-candidate-v2')
        self.assertEqual(v2['candidate_sha256'], tool.EXPECTED_ISSUE352_CANDIDATE_SHA256)
        self.assertEqual(v2['role'], 'ADMITTED_EXACT_PRICE_COMPARATOR')
        self.assertEqual(v2['fit_artifact']['sha256'], tool.EXPECTED_ISSUE352_FIT_BYTE_SHA256)
        self.assertEqual(
            v2['validation_evidence']['byte_sha256'],
            tool.EXPECTED_ISSUE352_VALIDATION_BYTE_SHA256,
        )
        self.assertEqual(
            v2['validation_evidence']['evidence_sha256'],
            tool.EXPECTED_ISSUE352_VALIDATION_EVIDENCE_SHA256,
        )
        self.assertEqual(comparators['comparator_count'], 3)
        self.assertFalse(self.result['active_model_replaced'])

    def test_candidate_identity_is_the_frozen_train_fit(self):
        candidate = self.result['candidate']
        self.assertEqual(candidate['candidate_id'], guard.CANDIDATE_ID)
        self.assertEqual(candidate['byte_sha256'], guard.CANDIDATE_BYTE_SHA256)
        self.assertEqual(
            candidate['canonical_payload_sha256'], guard.CANDIDATE_CANONICAL_SHA256
        )
        self.assertEqual(guard.sha256_file(tool.CANDIDATE_PATH), guard.CANDIDATE_BYTE_SHA256)

    # -------------------------------------------------------------- metrics
    def test_calibration_and_log_loss_are_measured_and_persisted(self):
        metrics = self.result['metrics']
        self.assertEqual(metrics['primary']['name'], 'multiclass_log_loss')
        self.assertEqual(metrics['primary']['epsilon_clip'], 1e-12)
        logloss = metrics['primary']['multiclass_log_loss']
        for name in (
            'candidate_hierarchical',
            'active_model_a_v5',
            'model_a_preflop_sizing_aware_candidate_v2',
        ):
            self.assertIsNotNone(logloss[name], name)
            self.assertGreater(logloss[name], 0.0, name)
        ece = metrics['secondary']['expected_calibration_error']
        for name in logloss:
            self.assertIsNotNone(ece[name], name)
            self.assertGreaterEqual(ece[name], 0.0, name)
        self.assertLessEqual(ece['candidate_hierarchical'], 1.0)
        self.assertEqual(metrics['secondary']['calibration_detail'][
            'candidate_hierarchical']['bins_per_action_class'], 10)
        self.assertEqual(metrics['secondary']['calibration_detail'][
            'candidate_hierarchical']['minimum_bin_support'], 20)
        coverage = self.result['coverage']
        self.assertEqual(
            coverage['identifiable_decisions'],
            self.result['universe']['candidate_answerable_decisions'],
        )
        self.assertEqual(
            len(self.result['decisions']), self.result['universe']['paired_decisions']
        )
        self.assertEqual(coverage['coverage_vs_exact_price_universe'],
                         self.result['universe'][
                             'candidate_answerable_in_comparable_universe_decisions'
                         ] / coverage['comparable_universe_decisions'])
        self.assertEqual(len(self.result['decisions']), self.result['metrics']['primary'][
            'evaluated_decisions'])

    def test_metrics_are_recomputable_from_the_embedded_decisions(self):
        recomputed = tool._recompute_metrics(self.result)
        persisted = self.result['metrics']['primary']['multiclass_log_loss']
        for name, value in recomputed['logloss'].items():
            self.assertAlmostEqual(persisted[name], value, places=12, msg=name)
        for label, value in recomputed['pairwise'].items():
            stored = self.result['metrics']['pairwise'][label]['paired_bootstrap']
            self.assertEqual(stored['hands'], value['hands'])
            self.assertAlmostEqual(stored['ci95'][0], value['ci95'][0], places=12)
            self.assertAlmostEqual(stored['ci95'][1], value['ci95'][1], places=12)

    def test_every_answered_decision_carries_the_mandated_fields(self):
        required = json.loads(tool.PROTOCOL_PATH.read_text())['output_schema'][
            'every_decision_must_carry'
        ]
        for row in self.result['decisions']:
            for field in ('requested_key', 'reason_code', 'posterior'):
                self.assertIn(field, row)
            self.assertIn('level', row['pooling'])
            self.assertIn('source_key', row['pooling'])
            self.assertEqual(row['support']['source_key'], row['requested_key'])
            self.assertTrue(row['requested_key'].startswith('MAPSUP_'))
            self.assertIn('|public=', row['requested_key'])
        self.assertTrue(required)

    def test_explicit_pairing_against_both_comparators(self):
        pairwise = self.result['metrics']['pairwise']
        self.assertEqual(pairwise['candidate_minus_active']['right'], 'active_model_a_v5')
        self.assertEqual(
            pairwise['candidate_minus_v2_352']['right'],
            'model_a_preflop_sizing_aware_candidate_v2',
        )
        for label in ('candidate_minus_active', 'candidate_minus_v2_352'):
            row = pairwise[label]
            self.assertEqual(
                row['left'], 'candidate_hierarchical', label
            )
            self.assertIsNotNone(row['delta_logloss'])
            bootstrap = row['paired_bootstrap']
            self.assertEqual(bootstrap['samples'], 5000)
            self.assertLessEqual(bootstrap['ci95'][0], bootstrap['ci95'][1])
        self.assertEqual(
            self.result['metrics']['bootstrap']['seed'],
            self.protocol['metrics']['bootstrap']['seed'],
        )

    # ---------------------------------------------------------------- nodes
    def test_share_of_nodes_classified_exact_hierarchical_estimate(self):
        nodes = self.result['node_classification']
        manifest = json.loads(tool.PROTOCOL_PATH.read_text())['requirement_manifest']
        self.assertEqual(nodes['total_nodes'], manifest['node_count'])
        total = sum(nodes['status_counts'].values())
        self.assertEqual(total, manifest['node_count'])
        share = nodes['status_counts']['EXACT_HIERARCHICAL_ESTIMATE'] / total
        self.assertEqual(nodes['share_exact_hierarchical_estimate'], share)
        self.assertTrue(nodes['reconciled_with_train_fit_report'])
        persisted = json.loads(tool.TRAIN_FIT_REPORT_PATH.read_text())
        expected = {':'.join(row['path']): row['status'] for row in persisted['nodes']}
        for row in nodes['nodes']:
            self.assertEqual(row['status'], expected[':'.join(row['path'])])

    # ------------------------------------------------------------ thresholds
    def test_thresholds_and_pooling_limits_are_frozen_and_unchanged(self):
        self.assertTrue(self.result['thresholds_unchanged_after_read'])
        self.assertEqual(self.result['thresholds'], self.protocol['thresholds'])
        self.assertEqual(self.result['pooling_limits'], self.protocol['pooling_limits'])
        for key, value in tool.FROZEN_THRESHOLDS.items():
            self.assertEqual(self.result['thresholds'][key], value, key)
        for key, value in tool.FROZEN_POOLING.items():
            self.assertEqual(self.result['pooling_limits'][key], value, key)
        self.assertFalse(self.result['gate']['all_gates_pass'])
        self.assertEqual(
            self.result['outcome'],
            'ADMIT_CANDIDATE' if self.result['gate']['all_gates_pass']
            else 'RETAIN_ACTIVE_REFERENCE',
        )
        for row in self.result['gate']['gates']:
            frozen_rule = next(
                spec for spec in self.protocol['calibration_and_admission']['admission_gates']
                if spec['gate'] == row['gate']
            )
            self.assertEqual(row['rule'], frozen_rule['rule'], row['gate'])

    def test_a_relaxed_protocol_is_refused_before_any_evaluation(self):
        tampered = json.loads(tool.PROTOCOL_PATH.read_text())
        tampered['thresholds']['minimum_identifiable_validation_decisions'] = 1
        tampered['thresholds']['maximum_absolute_ece'] = 1.0
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'FROZEN_VALIDATION_PROTOCOL.json'
            path.write_text(json.dumps(tampered))
            with mock.patch.object(tool, 'PROTOCOL_PATH', path):
                with self.assertRaises(tool.ValidationExecutionError):
                    tool.load_protocol()

    # -------------------------------------------------------------- boundary
    def test_test_split_stays_unconsumed_and_unauthorized(self):
        for flag in (
            'test_consumed',
            'test_authorized',
            'automatic_promotion',
            'model_b_consumed',
            'hero_ev_consumed',
        ):
            self.assertIs(self.result[flag], False, flag)
        self.assertEqual(self.result['production_effect'], 'NONE')
        boundary = self.result['holdout_boundary']
        self.assertEqual(boundary['split_consumed'], 'VALIDATION')
        self.assertEqual(boundary['test_hands_parsed'], 0)
        self.assertEqual(boundary['test_decisions_read'], 0)
        self.assertEqual(boundary['test_rows_seen_by_the_evaluator'], 0)
        self.assertGreater(boundary['validation_hands_parsed'], 0)
        self.assertEqual(tool.verify_no_test_loader()['result'], 'PASS')
        checks = {row['check']: row for row in boundary['checks']}
        self.assertEqual(
            checks['frozen_protocol_reverified_before_the_validation_read'][
                'protocol_byte_sha256'
            ],
            tool.EXPECTED_PROTOCOL_BYTE_SHA256,
        )
        self.assertEqual(
            checks['self_source_scan_for_test_loaders']['result'], 'PASS'
        )

    def test_evaluation_command_cannot_read_a_dataset_holdout(self):
        source = Path(tool.__file__).read_text()
        evidence = guard.verify_no_holdout_access(
            source, allow_literals=tool.SELF_ARTIFACT_LITERALS
        )
        self.assertEqual(evidence['result'], 'PASS')
        self.assertEqual(evidence['hits'], [])

    def test_order_guard_fails_closed_after_the_single_consumption(self):
        hits = guard.validation_result_artifacts(ROOT)
        self.assertIn(tool.RESULT_PATH.relative_to(ROOT).as_posix(), hits)
        with self.assertRaises(guard.ValidationOrderError):
            guard.assert_validation_not_yet_consumed(ROOT)
        with self.assertRaises(guard.ValidationOrderError):
            tool.evaluate()

    def test_check_mode_verifies_the_persisted_result(self):
        self.assertEqual(tool.check(), 0)

    def test_v2_protocol_inherits_the_frozen_v1_thresholds_verbatim(self):
        """The v2 estimate layer adds a class, never slack in the frozen rule."""
        v2_path = (
            ROOT / 'analysis/issue419_hierarchical_tree/validation_protocol_v2/'
            'FROZEN_VALIDATION_PROTOCOL_V2.json'
        )
        v2 = json.loads(v2_path.read_text())
        self.assertEqual(v2['revision_of'], tool.PROTOCOL_SCHEMA)
        self.assertTrue(v2['thresholds']['inherited_verbatim_from_v1'])
        self.assertFalse(v2['thresholds']['modified_by_this_revision'])
        self.assertFalse(v2['thresholds']['re_selected_after_reading_validation'])
        self.assertEqual(
            v2['v1_provenance']['byte_sha256'], tool.EXPECTED_PROTOCOL_BYTE_SHA256
        )
        self.assertTrue(v2['v1_custody']['v1_bytes_unchanged'])
        for flag in ('v1_bytes_rewritten', 'v1_artifacts_superseded'):
            self.assertFalse(v2['relationship_to_v1'][flag], flag)
        self.assertFalse(v2['relationship_to_v1']['changes_admission_rule'])
        self.assertFalse(v2['relationship_to_v1']['admits_anything'])
        self.assertTrue(
            v2['relationship_to_v1']['v1_gates_and_thresholds_remain_the_source_of_record']
        )
        # The still-frozen v1 bytes the VALIDATION result pinned are on disk, and
        # the v2 revision repeats every measurable threshold verbatim.
        self.assertEqual(
            guard.sha256_file(tool.PROTOCOL_PATH), tool.EXPECTED_PROTOCOL_BYTE_SHA256
        )
        for key in (
            'minimum_marginal_observations',
            'minimum_distinct_hands',
            'minimum_identifiable_validation_decisions',
            'minimum_identifiable_validation_hands',
            'non_inferiority_ci_upper_bound',
            'maximum_absolute_ece',
            'maximum_ece_delta_vs_active',
        ):
            with self.subTest(threshold=key):
                self.assertEqual(v2['thresholds'][key], tool.FROZEN_THRESHOLDS[key])
                self.assertEqual(v2['thresholds'][key], self.result['thresholds'][key])
        for key in (
            'rule_id',
            'only_support_source_level',
            'maximum_pooling_level_for_an_exact_support_claim',
            'maximum_pooling_level_for_a_reported_estimate',
            'alpha_per_legal_marginal_action',
        ):
            with self.subTest(pooling=key):
                self.assertEqual(v2['pooling_limits'][key], tool.FROZEN_POOLING[key])
        self.assertEqual(
            v2['pooling_limits']['kappa0'],
            tool.FROZEN_POOLING['fixed_shrinkage_strength_kappa0'],
        )
        self.assertIn(
            'the 20 marginal observations / 20 distinct hands thresholds',
            v2['what_did_not_change'],
        )

    # ---------------------------------------------------------------- helpers
    def test_calibration_helper_is_exact_on_a_perfectly_calibrated_sample(self):
        records = [
            {
                'hand_id': str(index),
                'observed_action': 'FOLD' if index % 2 == 0 else 'CALL',
                'posterior': {'FOLD': 1.0 if index % 2 == 0 else 0.0,
                              'CALL': 0.0 if index % 2 == 0 else 1.0,
                              'RAISE': 0.0,
                              'JAM': 0.0},
            }
            for index in range(400)
        ]
        calibration = tool.expected_calibration_error(records, 'posterior')
        self.assertAlmostEqual(calibration['ece'], 0.0, places=12)
        self.assertTrue(calibration['claim_supportable'])

    def test_log_loss_and_brier_helpers_rank_a_sharper_model_above_a_flat_one(self):
        records = [
            {
                'hand_id': '1',
                'observed_action': 'FOLD',
                'sharp': {'FOLD': 0.9, 'CALL': 0.05, 'RAISE': 0.03, 'JAM': 0.02},
                'flat': {'FOLD': 0.25, 'CALL': 0.25, 'RAISE': 0.25, 'JAM': 0.25},
            }
        ]
        self.assertLess(
            tool.multiclass_log_loss(records, 'sharp'),
            tool.multiclass_log_loss(records, 'flat'),
        )
        self.assertLess(tool.brier_score(records, 'sharp'), tool.brier_score(records, 'flat'))


if __name__ == '__main__':
    unittest.main()
