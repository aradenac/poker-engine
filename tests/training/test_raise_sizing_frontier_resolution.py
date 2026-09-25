#!/usr/bin/env python3
"""#419 guard: the seven #388 raise-sizing frontiers stay explicitly resolved.

The resolution artifact must be content-addressed, TRAIN-only, free of any
representative/nearest price, and must persist the distinct sizing blocker
whenever at least one frontier stays unresolved. No VALIDATION/TEST hand is
parsed here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training import resolve_raise_sizing_frontiers as resolution_tool


class RaiseSizingFrontierResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = resolution_tool.OUTPUT
        cls.index = json.loads((cls.output / 'ARTIFACTS.json').read_text())
        cls.resolution = json.loads(
            (cls.output / resolution_tool.ARTIFACT_NAME).read_text()
        )
        cls.issue388 = resolution_tool.issue419_baseline.load_issue388()
        cls.frontier_nodes = {
            frontier['node_id'] for frontier in cls.issue388['tree']['unresolved_sizing_frontiers']
        }

    def test_persisted_artifact_is_content_addressed(self):
        self.assertIn(resolution_tool.ARTIFACT_NAME, self.index)
        for name, entry in self.index.items():
            data = (self.output / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'], name)
            self.assertEqual(data, (self.output / entry['object']).read_bytes(), name)
        self.assertEqual(
            {path.name for path in (self.output / 'sha256').iterdir()},
            {Path(entry['object']).name for entry in self.index.values()},
        )
        entry = self.index[resolution_tool.ARTIFACT_NAME]
        self.assertEqual(
            entry['canonical_payload_sha256'],
            resolution_tool.stable_hash(self.resolution),
        )
        self.assertEqual(self.resolution['schema'], resolution_tool.SCHEMA)
        self.assertEqual(self.resolution['issue'], 419)
        self.assertEqual(self.resolution['source_issue'], 388)
        self.assertEqual(self.resolution['scenario_issue'], 321)

    def test_declares_train_only_and_no_holdout(self):
        self.assertEqual(self.resolution['split_consumed'], 'TRAIN')
        self.assertFalse(self.resolution['validation_consumed'])
        self.assertFalse(self.resolution['test_consumed'])
        self.assertTrue(
            self.resolution['protected_files_before_after_sha256']['unchanged']
        )
        self.assertFalse(self.issue388['report']['validation_consumed'])
        self.assertFalse(self.issue388['report']['test_consumed'])
        self.assertTrue(
            self.resolution['reproduction']['tree_rederived_equal_issue388']
        )

    def test_all_seven_frontiers_are_treated_individually(self):
        frontiers = self.resolution['frontiers']
        self.assertEqual(len(frontiers), resolution_tool.UNRESOLVED_FRONTIERS)
        self.assertEqual(len({f['node_id'] for f in frontiers}), len(frontiers))
        self.assertEqual({f['node_id'] for f in frontiers}, self.frontier_nodes)
        self.assertEqual(self.resolution['frontiers_total'], len(frontiers))
        issue388_frontiers = {
            frontier['node_id']: frontier
            for frontier in self.issue388['tree']['unresolved_sizing_frontiers']
        }
        for frontier in frontiers:
            with self.subTest(node=frontier['node_id'][:12]):
                self.assertEqual(frontier['action'], 'RAISE')
                self.assertEqual(
                    frontier['issue388_reason'], 'EXACT_REFERENCE_RAISE_SIZING_UNAVAILABLE'
                )
                self.assertIn(frontier['resolution_state'], {'RESOLVED', 'UNRESOLVED'})
                self.assertTrue(frontier['coded_reasons'])
                self.assertEqual(
                    frontier['legal_target_interval_bb'],
                    issue388_frontiers[frontier['node_id']]['legal_target_interval_bb'],
                )
                # The structural question is answered under both node-key identities.
                self.assertTrue(frontier['runtime_exact_preflop_node_key'].startswith('MAPNODE_'))
                self.assertTrue(
                    frontier['runtime_exact_preflop_node_key_decision_form'].startswith('MAPNODE_')
                )
                self.assertEqual(
                    frontier['train_exact_structural_support']
                    == self.cell(frontier['node_id'])['runtime_exact_preflop_node_support'],
                    True,
                )
                self.assertTrue(
                    frontier['train_structural_support_decision_form_crosscheck'][
                        'identical_to_issue388_identity_support'
                    ]
                )

    def cell(self, node_id: str) -> dict:
        return next(
            cell for cell in self.issue388['report']['matrix'] if cell['node_id'] == node_id
        )

    def test_no_representative_or_nearest_price_is_introduced(self):
        self.assertEqual(
            self.resolution['frozen_rule']['substitutions_forbidden'],
            resolution_tool.SUBSTITUTIONS_FORBIDDEN,
        )
        for name, allowed in resolution_tool.SUBSTITUTIONS_FORBIDDEN.items():
            with self.subTest(forbidden=name):
                self.assertFalse(allowed)
        self.assertFalse(resolution_tool.issue419_baseline.legacy.RULES['nearest_price'])
        self.assertFalse(resolution_tool.issue419_baseline.legacy.RULES['nearest_context'])
        for frontier in self.resolution['frontiers']:
            support = frontier['exact_support']
            with self.subTest(node=frontier['node_id'][:12]):
                self.assertIsNone(support['exactly_supported_target_bb'])
                self.assertIsNone(support['admitted_target_bb'])
                self.assertIsNone(frontier['train_observed_raise_targets'])
                for flag in (
                    'representative_price_substituted',
                    'nearest_price_substituted',
                    'nearest_context_substituted',
                    'legal_minimum_fallback_substituted',
                ):
                    self.assertFalse(support[flag])
                self.assertIn('NO_EXACT_TARGET_EMITTED', frontier['coded_notes'])
                self.assertFalse(
                    support['reference_node_evidence']['has_continuous_sizing_block']
                )
        self.assertFalse(resolution_tool.unprotected(self.resolution['frontiers']))

    def test_exact_support_is_scanned_and_absent_reference_wide(self):
        scan = self.resolution['sizing_scan']
        self.assertEqual(
            scan['reference_nodes_with_translatable_raise_sizing'], 0
        )
        self.assertEqual(
            set(scan['translatable_sizing_key_node_counts']),
            set(resolution_tool.TRANSLATABLE_SIZING_KEYS),
        )
        self.assertTrue(
            all(count == 0 for count in scan['translatable_sizing_key_node_counts'].values())
        )
        self.assertEqual(
            scan, resolution_tool.count_reference_sizing_stat_nodes(
                json.loads(resolution_tool.legacy.REFERENCE.read_text())
            )
        )
        for frontier in self.resolution['frontiers']:
            support = frontier['exact_support']
            with self.subTest(node=frontier['node_id'][:12]):
                self.assertEqual(support['reference_exact_structural_match_count'], 1)
                self.assertEqual(
                    support['reference_node_ids'],
                    support['issue388_identity_reference_node_ids'],
                )
                self.assertEqual(
                    support['runtime_translator_selected_node_id'],
                    support['reference_node_ids'][0],
                )
                self.assertEqual(support['translatable_sizing_stat_keys_present'], [])
                self.assertFalse(
                    support['reference_node_evidence']['has_continuous_sizing_block']
                )
                self.assertTrue(
                    support['reference_node_evidence']['has_response_likelihood_model']
                )

    def test_unresolved_frontiers_persist_a_distinct_blocker(self):
        unresolved = [
            frontier for frontier in self.resolution['frontiers']
            if frontier['resolution_state'] == 'UNRESOLVED'
        ]
        self.assertEqual(self.resolution['unresolved_count'], len(unresolved))
        self.assertEqual(self.resolution['resolved_count'], 7 - len(unresolved))
        self.assertEqual(
            self.resolution['blocker_persisted'], bool(unresolved)
        )
        self.assertEqual(self.resolution['blocker_count'], 1 if unresolved else 0)
        self.assertFalse(self.resolution['enumeration_complete'])
        if not unresolved:
            return
        blocker = self.resolution['blockers'][0]
        self.assertEqual(blocker['blocker_id'], 'UNRESOLVED_RAISE_SIZING_FRONTIER')
        self.assertEqual(blocker['blocker_class'], 'RAISE_SIZING_EXACT_SUPPORT')
        self.assertEqual(blocker['status'], 'OPEN')
        self.assertTrue(blocker['necessary_for_tree_closure'])
        self.assertFalse(blocker['sufficient_for_tree_closure'])
        self.assertTrue(blocker['independent_of_response_model'])
        self.assertEqual(
            blocker['distinct_from_blocker_classes'], ['INSUFFICIENT_RUNTIME_SUPPORT_CONTEXT']
        )
        self.assertEqual(
            sorted(blocker['frontier_node_ids']),
            sorted(frontier['node_id'] for frontier in unresolved),
        )
        self.assertEqual(blocker['frontier_count'], len(unresolved))
        self.assertEqual(
            sorted(blocker['coded_reasons']),
            sorted({reason for frontier in unresolved for reason in frontier['coded_reasons']}),
        )
        # The sizing blocker is distinct from the response-likelihood evidence.
        self.assertEqual(
            self.resolution['issue388_bindings']['decision'], 'UNRESOLVED_EXACT_TREE_GAP'
        )

    def test_descendant_closure_is_not_claimed_enumerable(self):
        for frontier in self.resolution['frontiers']:
            closure = frontier['descendant_closure']
            with self.subTest(node=frontier['node_id'][:12]):
                self.assertFalse(closure['enumerable_without_representative_price'])
                self.assertEqual(
                    closure['coded_reason'], resolution_tool.REASON_DESCENDANTS
                )
                self.assertEqual(
                    closure['issue388_requirement'],
                    'REQUIRED_UNRESOLVED_NOT_PRUNED_AS_ZERO_MASS',
                )

    def test_live_rederivation_reproduces_the_persisted_artifact(self):
        # Expensive: parses every certified TRAIN hand once.
        rederived = resolution_tool.resolve()
        self.assertEqual(
            resolution_tool.stable_hash(rederived),
            self.index[resolution_tool.ARTIFACT_NAME]['canonical_payload_sha256'],
        )
        self.assertEqual(rederived, copy.deepcopy(self.resolution))


if __name__ == '__main__':
    unittest.main()
