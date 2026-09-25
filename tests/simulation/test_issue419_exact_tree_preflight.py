#!/usr/bin/env python3
"""#419 exact-tree #367 preflight regressions (no Hero EV, no holdout).

The preflight walks the 38 required nodes of the #388/#419 exact tree of
scenario #321 plus its 7 raise-sizing frontiers, queries the hierarchical
Model-A provider per exact key and records the exact key, node identity,
empirical support, pooling provenance, uncertainty and posterior identity.

These tests pin that behaviour and the boundary: no nearest-* substitution is
applied, no Hero EV/recommendation is computed, no VALIDATION/TEST hand is read
and ``required_tree_complete`` follows strict admissibility only.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation import issue419_exact_tree_preflight as preflight_tool  # noqa: E402
from tools.training import validation_order_guard as guard  # noqa: E402
from tools.training.audit_preflop_sizing_support import stable_hash  # noqa: E402


class ExactTreePreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = preflight_tool.OUTPUT
        cls.index = json.loads((cls.output / preflight_tool.INDEX_NAME).read_text())
        cls.preflight = json.loads((cls.output / preflight_tool.NAME).read_text())
        cls.raw_bytes = (cls.output / preflight_tool.NAME).read_bytes()
        cls.tree = json.loads(
            (ROOT / "analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json").read_text()
        )

    def test_bundle_is_content_addressed_and_canonical(self):
        self.assertIn(preflight_tool.NAME, self.index)
        self.assertIn(preflight_tool.SUMMARY_NAME, self.index)
        for name, entry in self.index.items():
            data = (self.output / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'], name)
            self.assertEqual(data, (self.output / entry['object']).read_bytes(), name)
        self.assertEqual(
            {p.name for p in (self.output / 'sha256').iterdir()},
            {Path(entry['object']).name for entry in self.index.values()},
        )
        entry = self.index[preflight_tool.NAME]
        self.assertEqual(entry['canonical_payload_sha256'], stable_hash(self.preflight))
        self.assertEqual(self.preflight['schema'], preflight_tool.SCHEMA)
        self.assertEqual(self.preflight['issue'], 419)
        self.assertEqual(self.preflight['source_issue'], 388)
        self.assertEqual(self.preflight['scenario_issue'], 321)

    def test_walks_every_required_node_and_sizing_frontier_by_exact_key(self):
        nodes = self.preflight['nodes']
        self.assertEqual(self.preflight['nodes_queried'], 38)
        self.assertEqual(len(nodes), 38)
        self.assertEqual(self.preflight['sizing_frontiers_queried'], 7)
        self.assertEqual(len(self.preflight['sizing_frontiers']), 7)
        by_id = {node['id']: node for node in self.tree['nodes']}
        seen_paths = set()
        for index, record in enumerate(nodes):
            with self.subTest(node=record['node_identity']['node_id']):
                identity = record['node_identity']
                source = by_id[identity['node_id']]
                self.assertEqual(record['index'], index)
                self.assertEqual(record['exact_key'], source['audit_exact_key'])
                self.assertEqual(identity['audit_exact_key'], source['audit_exact_key'])
                self.assertEqual(
                    identity['runtime_support_context_key'], source['runtime_support_context_key']
                )
                self.assertEqual(
                    identity['runtime_exact_preflop_node_key'],
                    source['runtime_exact_preflop_node_key'],
                )
                self.assertEqual(identity['path'], list(source['path']))
                self.assertTrue(identity['exact_key_matches_manifest'])
                self.assertTrue(identity['exact_key_matches_required_tree'])
                self.assertEqual(identity['identity_granularity'], 'hierarchical_exact_key')
                for field in (
                    'empirical_support',
                    'pooling_provenance',
                    'pooling_diagnostics',
                    'uncertainty',
                    'posterior_identity',
                ):
                    self.assertIn(field, record)
                self.assertIn('observations', record['empirical_support'])
                self.assertIn('distinct_hands', record['empirical_support'])
                self.assertEqual(len(record['pooling_diagnostics']), 5)
                seen_paths.add(tuple(identity['path']))
        self.assertEqual(len(seen_paths), 38)

        required_keys = {node['audit_exact_key'] for node in by_id.values()}
        frontier_paths = set()
        for frontier in self.preflight['sizing_frontiers']:
            self.assertEqual(frontier['exact_key'], frontier['requested_key'])
            self.assertEqual(frontier['action'], 'RAISE')
            self.assertIn(frontier['exact_key'], required_keys)
            self.assertIsNone(frontier['exactly_supported_target_bb'])
            self.assertIsNone(frontier['admitted_target_bb'])
            self.assertFalse(
                frontier['descendant_closure']['enumerable_without_a_representative_price']
            )
            self.assertFalse(frontier['descendant_closure']['pruned_as_zero_mass'])
            self.assertEqual(frontier['disposition'], 'UNRESOLVED_FRONTIER_NOT_PRUNED')
            frontier_paths.add(tuple(frontier['path']))
        self.assertEqual(len(frontier_paths), 7)

    def test_required_tree_complete_reflects_strict_admissibility(self):
        admissibility = self.preflight['admissibility']
        conditions = admissibility['conditions']
        self.assertFalse(self.preflight['required_tree_complete'])
        self.assertEqual(
            self.preflight['required_tree_complete'],
            all(condition['satisfied'] for condition in conditions.values()),
        )
        self.assertEqual(admissibility['admissible_exact_nodes'], 0)
        self.assertEqual(admissibility['blocked_nodes'], 38)
        self.assertEqual(len(admissibility['blocked_node_paths']), 38)
        self.assertFalse(self.preflight['required_tree']['tree_enumeration_complete'])
        self.assertEqual(self.preflight['required_tree']['required_node_count'], 38)
        self.assertEqual(self.preflight['required_tree']['unresolved_sizing_frontier_count'], 7)
        self.assertEqual(self.preflight['required_tree']['distinct_exact_keys'], 38)
        self.assertGreater(self.preflight['required_tree']['runtime_keys_merging_exact_states'], 0)
        self.assertFalse(
            conditions['every_required_node_has_an_admissible_exact_answer']['satisfied']
        )
        self.assertFalse(conditions['no_unresolved_raise_sizing_frontier']['satisfied'])
        self.assertFalse(conditions['required_tree_fully_enumerated']['satisfied'])
        self.assertTrue(conditions['no_nearest_or_borrowed_substitution_applied']['satisfied'])
        self.assertTrue(conditions['no_hero_ev_or_recommendation_computed']['satisfied'])
        self.assertEqual(
            self.preflight['nodes'][0]['empirical_support']['thresholds'],
            {'minimum_marginal_observations': 20, 'minimum_distinct_hands': 20},
        )
        for record in self.preflight['nodes']:
            self.assertFalse(record['admissible_exact_answer'])
            self.assertEqual(record['posterior_identity']['status'], 'EXACT_UNRESOLVED')
            self.assertFalse(record['posterior_identity']['probability_emitted'])
            self.assertIsNone(record['posterior_identity']['posterior'])
            self.assertIsNone(record['posterior_identity']['posterior_sha256'])
            self.assertIsNone(record['pooling_provenance'])
            self.assertIsNone(record['uncertainty'])

    def test_refuses_and_traces_every_nearest_substitution(self):
        audit = self.preflight['nearest_substitution_audit']
        for counter in (
            'substitutions_applied',
            'nearest_price_substitutions_applied',
            'nearest_context_substitutions_applied',
            'representative_price_substitutions_applied',
            'interpolated_price_substitutions_applied',
            'legal_minimum_substitutions_applied',
            'cross_key_support_borrowings_applied',
        ):
            self.assertEqual(audit[counter], 0, counter)
        self.assertGreater(audit['refusals_recorded'], 0)
        self.assertTrue(audit['key_separation_probes_passed'])
        self.assertTrue(audit['support_source_equals_requested_key_for_every_node'])
        for record in self.preflight['nodes']:
            classes = {row['substitution_class'] for row in record['substitution_refusals']}
            self.assertEqual(classes, set(preflight_tool.SUBSTITUTION_CLASSES))
            for row in record['substitution_refusals']:
                self.assertEqual(row['disposition'], 'REFUSED_NOT_SUBSTITUTED')
                self.assertFalse(row['applied'])
            self.assertEqual(record['empirical_support']['source_key'], record['exact_key'])
            self.assertFalse(record['empirical_support']['borrowed_from_other_keys'])
        for probe in audit['key_separation_probes']:
            self.assertTrue(probe['keys_distinct'])
            self.assertFalse(probe['base_support_reused_for_probe'])
            self.assertEqual(probe['disposition'], 'REFUSED_NOT_SUBSTITUTED')
        price_probes = [
            probe
            for probe in audit['key_separation_probes']
            if probe['substitution_class'] == 'NEAREST_PRICE'
        ]
        self.assertEqual(
            {probe['probe_target_total_bb'] for probe in price_probes},
            set(preflight_tool.ADJACENT_ISO_TARGETS_BB),
        )
        for frontier in self.preflight['sizing_frontiers']:
            classes = {row['substitution_class'] for row in frontier['substitution_refusals']}
            self.assertTrue(
                {'NEAREST_PRICE', 'REPRESENTATIVE_PRICE', 'LEGAL_MINIMUM_FALLBACK'}
                <= classes
            )

    def test_no_hero_ev_no_holdout_and_no_pointer_mutation(self):
        boundary = self.preflight['boundary']
        self.assertEqual(boundary['split_consumed'], 'TRAIN')
        for flag in (
            'validation_consumed',
            'test_consumed',
            'test_authorized',
            'dataset_archives_opened',
            'model_b_consumed',
            'hero_ev_executed',
            'recommendation_computed',
            'active_model_pointer_mutated',
            'ui_modified',
        ):
            self.assertFalse(boundary[flag], flag)
        self.assertEqual(boundary['test_decisions_read'], 0)
        self.assertEqual(boundary['hand_histories_parsed'], 0)
        self.assertEqual(boundary['rollouts_executed'], 0)
        self.assertEqual(boundary['ev_values_computed'], 0)
        self.assertEqual(boundary['holdout_access_scan']['result'], 'PASS')
        self.assertEqual(boundary['hero_ev_scan']['result'], 'PASS')
        self.assertEqual(boundary['hero_ev_scan']['ev_values_computed'], 0)
        self.assertEqual(boundary['hero_ev_scan']['forbidden_modules_imported_during_build'], [])
        self.assertFalse(boundary['hero_ev_scan']['runner_module_imported_by_preflight'])
        self.assertEqual(boundary['dataset_access_tripwire']['result'], 'PASS')
        self.assertEqual(boundary['dataset_access_tripwire']['hand_history_or_dataset_opens'], [])
        self.assertFalse(boundary['issue367_authorization']['authorized'])
        self.assertFalse(boundary['issue367_authorization']['authorized_at_freeze'])
        protected = self.preflight['protected_files_before_after_sha256']
        self.assertTrue(protected['unchanged'])
        self.assertEqual(protected['before'], protected['after'])
        self.assertFalse(self.preflight['reproduction']['hero_ev_runner_invoked'])
        self.assertFalse(self.preflight['provider']['authorized_for_367'])
        text = self.raw_bytes.decode()
        for forbidden in ('"ev_bb"', 'recommendation":', 'selected_alternative', 'indifference'):
            self.assertNotIn(forbidden, text)

    def test_pins_protocol_provider_tree_and_fixture_identities(self):
        bindings = self.preflight['evidence_bindings']
        self.assertEqual(bindings['protocol_byte_sha256'], preflight_tool.PROTOCOL_BYTE_SHA256)
        self.assertEqual(
            bindings['protocol_canonical_payload_sha256'],
            preflight_tool.PROTOCOL_CANONICAL_PAYLOAD_SHA256,
        )
        self.assertEqual(
            bindings['protocol_digest_sidecar_sha256'], preflight_tool.PROTOCOL_BYTE_SHA256
        )
        self.assertEqual(bindings['protocol_status'], preflight_tool.PROTOCOL_STATUS)
        self.assertEqual(
            bindings['candidate_canonical_payload_sha256'],
            preflight_tool.CANDIDATE_CANONICAL_SHA256,
        )
        self.assertEqual(bindings['candidate_byte_sha256'], preflight_tool.CANDIDATE_BYTE_SHA256)
        self.assertEqual(
            bindings['required_tree_sha256'],
            '0ab232ae44e4157e2a47d4d3d611ac8ca9c2cdb54caf2568f256f6df35643a25',
        )
        self.assertEqual(bindings['feasibility_decision'], 'UNRESOLVED_EXACT_TREE_GAP')
        self.assertEqual(bindings['feasibility_status'], 'BLOCKED_SCIENTIFIC')
        self.assertEqual(bindings['canonical_fixture_sha256'], self.tree['fixture_sha256'])
        self.assertEqual(
            self.preflight['provider']['candidate_id'],
            'model-a-preflop-sizing-hierarchical-candidate-v1',
        )
        self.assertEqual(
            self.preflight['provider']['candidate_instance_id'],
            preflight_tool.CANDIDATE_INSTANCE_ID,
        )
        self.assertEqual(self.preflight['provider']['support_level'], 'L0_EXACT_KEY')
        self.assertEqual(
            self.preflight['provider']['support_isolation_rule'],
            'SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT',
        )
        for flag in (
            'nearest_price_fallback',
            'nearest_context_fallback',
            'representative_price_fallback',
        ):
            self.assertFalse(self.preflight['provider'][flag], flag)
        self.assertTrue(self.preflight['required_tree']['manifest_matches_required_tree'])
        self.assertEqual(self.preflight['scenario']['root_path'], ['SB:ISO@5'])
        self.assertEqual(self.preflight['scenario']['root_actor_position'], 'BB')
        self.assertEqual(self.preflight['scenario']['hero_position'], 'SB')

    def test_scan_helpers_fail_closed_on_forbidden_sources(self):
        with self.assertRaises(preflight_tool.PreflightError):
            preflight_tool.verify_no_holdout_access('import load_test_records\n')
        with self.assertRaises(preflight_tool.PreflightError):
            preflight_tool.verify_no_holdout_access('from tools.x import validation_records\n')
        with self.assertRaises(preflight_tool.PreflightError):
            preflight_tool.verify_no_hero_ev_execution(
                'from tools.simulation.run_issue367_real_iso_ev import main\n'
            )
        with self.assertRaises(preflight_tool.PreflightError):
            preflight_tool.verify_no_hero_ev_execution('import paired_adaptive_preflop_ev\n')
        self.assertEqual(preflight_tool.verify_no_holdout_access()['result'], 'PASS')
        self.assertEqual(preflight_tool.verify_no_hero_ev_execution()['result'], 'PASS')

    def test_admissibility_rule_matches_frozen_thresholds(self):
        requested = {
            'status': 'EXACT_EMPIRICAL_STRONG',
            'pooling': {'level': 'L0_EXACT_KEY'},
            'requested_key': 'MAPSUP_x|public=y',
            'support': {
                'source_key': 'MAPSUP_x|public=y',
                'observations': 20,
                'distinct_hands': 20,
            },
        }
        self.assertTrue(preflight_tool.is_admissible(requested))
        thin = copy.deepcopy(requested)
        thin['support']['observations'] = 19
        self.assertFalse(preflight_tool.is_admissible(thin))
        fewer_hands = copy.deepcopy(requested)
        fewer_hands['support']['distinct_hands'] = 19
        self.assertFalse(preflight_tool.is_admissible(fewer_hands))
        pooled = copy.deepcopy(requested)
        pooled['status'] = 'EXACT_HIERARCHICAL_ESTIMATE'
        pooled['pooling']['level'] = 'L1_STACK_POOL'
        self.assertFalse(preflight_tool.is_admissible(pooled))
        borrowed = copy.deepcopy(requested)
        borrowed['support']['source_key'] = 'MAPSUP_other|public=z'
        self.assertFalse(preflight_tool.is_admissible(borrowed))

    def test_repo_guard_accepts_the_preflight_and_its_artifact(self):
        source = preflight_tool.SOURCE_PATH.read_text(encoding='utf-8')
        self.assertEqual(guard.verify_no_holdout_access(source)['result'], 'PASS')
        artifact = preflight_tool._relative(preflight_tool.OUTPUT / preflight_tool.NAME)
        self.assertNotIn(artifact, guard.validation_result_artifacts())

    def test_hero_ev_build_scan_is_environment_independent(self):
        """A sibling test that already imported the runner must not flip the verdict."""
        import types

        name = 'tools.simulation.run_issue367_real_iso_ev'
        stub = types.ModuleType(name)
        sys.modules[name] = stub
        try:
            artifacts, _summary = preflight_tool.build()
            scan = artifacts[preflight_tool.NAME]['boundary']['hero_ev_scan']
            self.assertEqual(scan['forbidden_modules_imported_during_build'], [])
            self.assertFalse(scan['runner_module_imported_by_preflight'])
            self.assertFalse(artifacts[preflight_tool.NAME]['boundary']['hero_ev_executed'])
            self.assertIn(name, preflight_tool.hero_ev_modules_present())
            self.assertEqual(
                preflight_tool.serialize(artifacts[preflight_tool.NAME]), self.raw_bytes
            )
        finally:
            sys.modules.pop(name, None)
        self.assertEqual(
            preflight_tool.verify_no_hero_ev_execution()['result'], 'PASS'
        )

    def test_bundle_reproduces_byte_identically(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(preflight_tool.check(), 0)
        artifacts, summary = preflight_tool.build()
        self.assertEqual(preflight_tool.serialize(artifacts[preflight_tool.NAME]), self.raw_bytes)
        self.assertEqual(summary, artifacts[preflight_tool.SUMMARY_NAME])


if __name__ == '__main__':
    unittest.main()
