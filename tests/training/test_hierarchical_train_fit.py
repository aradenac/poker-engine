#!/usr/bin/env python3
"""#419 TRAIN-only hierarchical fit regressions.

The fit is content-addressed and TRAIN-only: these tests never parse a holdout
hand and never touch an active model.  They pin the candidate identity, the
frozen hyper-parameters/priors, the support-isolation proof and the
``active_pointer_mutated=false`` boundary, then re-run the fit and require it to
reproduce the persisted bytes exactly.
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import sha256_file
from tools.preflop import model_a_sizing_hierarchical as H
from tools.training import fit_model_a_preflop_sizing_hierarchical as fit_tool
from tools.training.audit_preflop_sizing_support import stable_hash

SPEC = json.loads(
    (ROOT / 'analysis/issue419_hierarchical_tree/HIERARCHICAL_MODEL_SPEC.json').read_text()
)


class HierarchicalTrainFitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = fit_tool.OUTPUT
        cls.index = json.loads((cls.output / fit_tool.INDEX_NAME).read_text())
        cls.candidate = json.loads((cls.output / fit_tool.CANDIDATE_NAME).read_text())
        cls.manifest = json.loads((cls.output / fit_tool.MANIFEST_NAME).read_text())
        cls.report = json.loads((cls.output / fit_tool.REPORT_NAME).read_text())

    def test_bundle_is_content_addressed(self):
        for name, entry in self.index.items():
            data = (self.output / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'], name)
            self.assertEqual(data, (self.output / entry['object']).read_bytes(), name)
        self.assertEqual(
            {p.name for p in (self.output / 'sha256').iterdir()},
            {Path(entry['object']).name for entry in self.index.values()},
        )
        self.assertEqual(
            self.index[fit_tool.CANDIDATE_NAME]['sha256'],
            self.manifest['candidate']['artifact']['sha256'],
        )
        self.assertEqual(
            self.index[fit_tool.REPORT_NAME]['sha256'],
            self.manifest['fit_report']['sha256'],
        )
        self.assertEqual(
            self.index[fit_tool.CANDIDATE_NAME]['canonical_payload_sha256'],
            H.canonical_candidate_sha256(self.candidate),
        )

    def test_declares_train_only_and_no_holdout_access(self):
        self.assertEqual(self.report['split_consumed'], 'TRAIN')
        self.assertFalse(self.report['validation_consumed'])
        self.assertFalse(self.report['test_consumed'])
        self.assertEqual(self.report['validation_decisions_read'], 0)
        self.assertEqual(self.report['test_decisions_read'], 0)
        self.assertEqual(self.report['holdout_access_scan']['result'], 'PASS')
        self.assertEqual(self.report['corpus']['train_hands_parsed'], 19016)
        self.assertEqual(self.manifest['fit']['split_consumed'], 'TRAIN')
        self.assertFalse(self.manifest['fit']['validation_consumed'])
        self.assertFalse(self.manifest['fit']['test_consumed'])
        self.assertEqual(self.manifest['fit']['validation_decisions_read'], 0)
        self.assertEqual(self.manifest['holdout_boundary']['holdout_access_scan'], 'PASS')

    def test_candidate_is_new_distinct_and_contract_valid(self):
        H.validate_candidate(self.candidate)
        identity = self.candidate['identity']
        self.assertEqual(identity['candidate_id'], H.CANDIDATE_ID)
        self.assertEqual(self.manifest['candidate']['candidate_instance_id'], fit_tool.CANDIDATE_INSTANCE_ID)
        self.assertNotEqual(
            fit_tool.CANDIDATE_INSTANCE_ID,
            fit_tool.DISTINCT_FROM['issue_352_candidate_id'],
        )
        self.assertNotEqual(fit_tool.CANDIDATE_INSTANCE_ID, H.CANDIDATE_ID)
        self.assertNotIn(fit_tool.CONTRACT_CANDIDATE_ID, fit_tool.DISTINCT_FROM['exact_price_candidate_ids'])
        self.assertEqual(identity['status'], 'CANDIDATE_ONLY_NOT_ACTIVE')
        self.assertFalse(identity['active_model_replaced'])
        for flag in ('nearest_price_fallback', 'nearest_context_fallback', 'representative_price_fallback'):
            self.assertIs(self.candidate[flag], False, flag)
        self.assertEqual(identity['fit_scope'], fit_tool.FIT_SCOPE)
        self.assertEqual(identity['data_scope'], fit_tool.DATA_SCOPE)
        spec_index = json.loads(
            (ROOT / 'analysis/issue419_hierarchical_tree/model_spec/ARTIFACTS.json').read_text()
        )
        self.assertEqual(
            identity['hierarchy_spec_sha256'],
            spec_index['HIERARCHICAL_MODEL_SPEC.json']['canonical_payload_sha256'],
        )
        self.assertEqual(
            identity['source_report_hash'],
            self.report['evidence_bindings']['issue388_train_support_sha256'],
        )

    def test_hyperparameters_priors_and_seeds_match_the_frozen_spec(self):
        shrinkage = SPEC['hierarchy_prior_shrinkage']
        thresholds = SPEC['decision_thresholds']
        for payload in (self.manifest['hyperparameters'], self.report['hyperparameters']):
            self.assertEqual(payload['estimator'], shrinkage['estimator'])
            self.assertEqual(payload['hierarchical_strength_kappa0'], float(
                shrinkage['hierarchical_strength_kappa0']))
            self.assertEqual(payload['alpha_per_legal_marginal_action'], float(
                shrinkage['base_prior']['alpha_per_legal_marginal_action']))
            self.assertEqual(payload['minimum_marginal_observations'], int(
                thresholds['minimum_marginal_observations']))
            self.assertEqual(payload['minimum_distinct_hands'], int(
                thresholds['minimum_distinct_hands']))
            self.assertFalse(payload['hyperparameter_search_performed'])
            self.assertFalse(payload['validation_used_for_hyperparameters'])
        self.assertEqual(self.candidate['shrinkage']['kappa0'], H.KAPPA0)
        self.assertEqual(self.candidate['shrinkage']['alpha_per_legal_marginal_action'], H.ALPHA_PER_LEGAL_ACTION)
        self.assertEqual(self.candidate['thresholds']['minimum_marginal_observations'], H.MIN_MARGINAL_OBSERVATIONS)
        self.assertEqual(self.candidate['thresholds']['minimum_distinct_hands'], H.MIN_DISTINCT_HANDS)
        seeds = self.report['seeds']
        self.assertEqual(seeds['policy'], 'DETERMINISTIC_NO_RANDOMNESS')
        self.assertEqual(seeds['stochastic_draws'], 0)
        self.assertTrue(seeds['deterministic_reproduction'])
        priors = self.report['priors_and_shrinkage']
        self.assertTrue(priors['no_hidden_hand_imputation'])
        self.assertTrue(priors['no_pseudo_observation'])
        self.assertEqual(priors['kappa0'], H.KAPPA0)
        self.assertEqual(
            priors['base_prior']['alpha_per_legal_marginal_action'],
            float(shrinkage['base_prior']['alpha_per_legal_marginal_action']),
        )

    def test_observations_are_real_train_rows_with_support_isolation(self):
        observations = self.candidate['observations']
        self.assertEqual(len(observations), self.report['observation_index']['observations'])
        self.assertEqual(self.report['support_isolation']['checked_observations'], len(observations))
        self.assertEqual(self.report['support_isolation']['violations'], [])
        self.assertFalse(self.report['support_isolation']['coarse_key_support_laundering'])
        self.assertEqual(self.report['no_pseudo_observation']['synthetic_observations'], 0)
        self.assertEqual(self.report['no_pseudo_observation']['observations'], len(observations))
        scan = self.report['corpus_support_scan']
        self.assertEqual(scan['train_rows_scanned'], 101848)
        self.assertEqual(scan['in_scope_rows'], len(observations))
        self.assertTrue(
            scan['distinct_source_keys_per_level']['L0_EXACT_KEY']
            >= scan['distinct_source_keys_per_level']['L3_RUNTIME_SUPPORT_CONTEXT']
        )
        for row in observations:
            normalized = H._normalize_observation(row, 0)
            self.assertEqual(normalized['hierarchical_exact_key'], row['hierarchical_exact_key'])
            self.assertEqual(normalized['level_keys'], row['level_keys'])
            self.assertEqual(row['level_keys']['L0_EXACT_KEY'], row['hierarchical_exact_key'])
        self.assertEqual(
            self.report['no_pseudo_observation']['rule'],
            'EVERY_OBSERVATION_IS_A_CERTIFIED_TRAIN_ROW',
        )

    def test_raise_sizing_stays_exact_only_and_unresolved_is_explicit(self):
        policy = self.report['raise_sizing_policy']
        self.assertEqual(policy['rule'], SPEC['raise_sizing_policy']['rule'])
        self.assertEqual(policy['declared_frontier_count'], 7)
        self.assertEqual(len(policy['declared_frontiers']), 7)
        pinned = fit_tool.load_verified_inputs()
        self.assertEqual(
            sorted(record['requested_key'] for record in policy['declared_frontiers']),
            fit_tool.unresolved_frontier_keys(pinned['tree'], fit_tool.required_nodes(pinned['tree'])),
        )
        self.assertEqual(policy['forbidden'], list(SPEC['raise_sizing_policy']['forbidden']))
        aggregate = self.report['aggregate']
        self.assertEqual(aggregate['nodes_total'], 38)
        self.assertEqual(
            aggregate['resolved_nodes'] + aggregate['unresolved_nodes'], aggregate['nodes_total'])
        for row in self.report['nodes']:
            self.assertIn(row['status'], H.STATUSES)
            if row['status'] == H.STATUS_EXACT_UNRESOLVED:
                self.assertIsNone(row['posterior'])
            else:
                self.assertAlmostEqual(sum(row['posterior'].values()), 1.0, places=9)
        self.assertFalse(self.report['raise_frontier_diagnostics']['authoritative'])

    def test_active_pointer_and_registry_are_unchanged(self):
        boundary = self.report['protected_files_before_after_sha256']
        self.assertTrue(boundary['unchanged'])
        self.assertFalse(boundary['active_pointer_mutated'])
        self.assertFalse(self.manifest['active_model_pointer']['mutated'])
        for path, digest in boundary['after'].items():
            self.assertEqual(sha256_file(ROOT / path), digest, path)

    def test_canonical_cells_reconcile_with_issue388(self):
        cells = self.report['canonical_cells']
        self.assertEqual(cells['bb_facing_sb_iso5']['runtime_observations'], 45)
        self.assertEqual(cells['bb_facing_sb_iso5']['runtime_distinct_hands'], 45)
        self.assertEqual(cells['co_after_bb_fold']['runtime_observations'], 14)
        self.assertEqual(cells['co_after_bb_fold']['runtime_distinct_hands'], 14)
        self.assertEqual(cells['bb_facing_sb_iso5']['support_observations'], 6)
        self.assertEqual(cells['co_after_bb_fold']['support_observations'], 4)

    def test_full_regeneration_reproduces_the_persisted_bytes(self):
        # Expensive: parses every certified TRAIN hand, exactly once.
        artifacts, _summary = fit_tool.build()
        self.assertEqual(
            H.canonical_candidate_sha256(artifacts[fit_tool.CANDIDATE_NAME]),
            self.index[fit_tool.CANDIDATE_NAME]['canonical_payload_sha256'],
        )
        self.assertEqual(
            stable_hash(artifacts[fit_tool.REPORT_NAME]),
            self.index[fit_tool.REPORT_NAME]['canonical_payload_sha256'],
        )
        self.assertEqual(artifacts[fit_tool.MANIFEST_NAME], self.manifest)
        self.assertEqual(
            fit_tool.serialize(artifacts[fit_tool.CANDIDATE_NAME]),
            (self.output / fit_tool.CANDIDATE_NAME).read_bytes(),
        )


if __name__ == '__main__':
    unittest.main()
