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

PREFLIGHT_PATH = (
    ROOT / 'analysis/issue419_hierarchical_tree/exact_tree_preflight/EXACT_TREE_PREFLIGHT.json'
)


class RaiseSizingFrontierResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = resolution_tool.OUTPUT
        cls.index = json.loads((cls.output / 'ARTIFACTS.json').read_text())
        cls.resolution = json.loads(
            (cls.output / resolution_tool.ARTIFACT_NAME).read_text()
        )
        cls.issue388 = resolution_tool.issue419_baseline.load_issue388()
        cls.preflight = json.loads(PREFLIGHT_PATH.read_text())
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

    def test_sizing_blocker_is_independent_of_any_response_model(self):
        sizing_reason_codes = {
            resolution_tool.REASON_NO_STRUCTURAL_NODE,
            resolution_tool.REASON_NO_SIZING_STAT,
            resolution_tool.REASON_FALLBACK,
            resolution_tool.REASON_DESCENDANTS,
            resolution_tool.OBSERVED_RAISES_NOT_ADMITTED,
        }
        for frontier in self.resolution['frontiers']:
            with self.subTest(node=frontier['node_id'][:12]):
                # Every blocking code is a sizing/structural code: none is a
                # response-likelihood or model-calibration code.
                self.assertTrue(frontier['coded_reasons'])
                self.assertLessEqual(set(frontier['coded_reasons']), sizing_reason_codes)
                self.assertFalse(
                    frontier['exact_support']['reference_node_evidence'][
                        'has_continuous_sizing_block'
                    ]
                )
                # The same reference nodes do carry response-likelihood state, so
                # the sizing gap is not a property of any response model.
                self.assertTrue(
                    frontier['exact_support']['reference_node_evidence'][
                        'has_response_likelihood_model'
                    ]
                )

        self.assertEqual(self.resolution['unresolved_count'], 7)
        self.assertEqual(self.resolution['resolved_count'], 0)
        self.assertEqual(self.resolution['blocker_count'], 1)
        blocker = self.resolution['blockers'][0]
        self.assertTrue(blocker['independent_of_response_model'])
        self.assertIn('response-likelihood', blocker['response_model_independence'])
        self.assertTrue(blocker['necessary_for_tree_closure'])
        self.assertFalse(blocker['sufficient_for_tree_closure'])
        self.assertEqual(blocker['status'], 'OPEN')
        self.assertEqual(
            blocker['distinct_from_blocker_classes'],
            ['INSUFFICIENT_RUNTIME_SUPPORT_CONTEXT'],
        )
        self.assertEqual(blocker['frontier_count'], 7)
        self.assertFalse(self.resolution['enumeration_complete'])
        self.assertIn(
            'cannot be closed by one',
            blocker['response_model_independence'],
        )
        # The blocker is derived from the frozen structural rule only, never from
        # the hierarchical response model: the resolution tool does not know it.
        source = Path(resolution_tool.__file__).read_text(encoding='utf-8')
        self.assertNotIn('model_a_sizing_hierarchical', source)
        for relabelling in ('EXACT_HIERARCHICAL_ESTIMATE', 'EXACT_EMPIRICAL_STRONG'):
            self.assertNotIn(relabelling, source)

    def test_each_frontier_is_exposed_as_an_independent_sizing_blocker(self):
        self.assertEqual(
            resolution_tool.BLOCKER_REASON_CODE, 'RAISE_SIZING_UNRESOLVED_NO_NEAREST_PRICE'
        )
        for frontier in self.resolution['frontiers']:
            with self.subTest(node=frontier['node_id'][:12]):
                blocker = frontier['blocker']
                # Every frontier is an explicit blocker carrying the frozen reason
                # code, and it is a property of the structural reference alone.
                self.assertEqual(blocker['reason_code'], resolution_tool.BLOCKER_REASON_CODE)
                self.assertEqual(frontier['blocker_reason_code'], blocker['reason_code'])
                self.assertEqual(blocker['blocker_class'], resolution_tool.BLOCKER_CLASS)
                self.assertEqual(blocker['status'], 'OPEN')
                self.assertTrue(blocker['independent_of_the_response_model'])
                self.assertTrue(frontier['independent_of_the_response_model'])
                # No representative / nearest price and no admitted target exists.
                self.assertIsNone(blocker['exactly_supported_target_bb'])
                self.assertIsNone(blocker['admitted_target_bb'])
                for flag in (
                    'representative_price_substituted',
                    'nearest_price_substituted',
                    'nearest_context_substituted',
                    'legal_minimum_fallback_substituted',
                ):
                    self.assertFalse(blocker[flag], flag)
                # The blocker forces the tree open and never closes it by itself.
                self.assertTrue(blocker['blocks_required_tree_complete'])
                self.assertFalse(blocker['required_tree_complete'])
                self.assertTrue(blocker['necessary_for_tree_closure'])
                self.assertFalse(blocker['sufficient_for_tree_closure'])
        self.assertEqual(self.resolution['blocker_reason_code'], resolution_tool.BLOCKER_REASON_CODE)
        self.assertTrue(self.resolution['independent_of_the_response_model'])
        self.assertEqual(
            self.resolution['blockers'][0]['reason_code'], resolution_tool.BLOCKER_REASON_CODE
        )
        # The exposure is not vacuous: all seven frontiers are unresolved here.
        self.assertEqual(self.resolution['unresolved_count'], resolution_tool.UNRESOLVED_FRONTIERS)
        self.assertEqual(self.resolution['resolved_count'], 0)

    def test_blocker_propagates_the_effect_on_required_tree_complete(self):
        effect = self.resolution['required_tree_complete_effect']
        self.assertEqual(effect['effect'], resolution_tool.REQUIRED_TREE_COMPLETE_EFFECT)
        self.assertEqual(effect['blocker_reason_code'], resolution_tool.BLOCKER_REASON_CODE)
        self.assertTrue(effect['independent_of_the_response_model'])
        self.assertFalse(effect['representative_price_substituted'])
        self.assertFalse(self.resolution['required_tree_complete'])
        self.assertFalse(effect['required_tree_complete'])
        self.assertTrue(effect['blocks_required_tree_complete'])
        self.assertTrue(effect['necessary_for_tree_closure'])
        self.assertFalse(effect['sufficient_for_tree_closure'])
        self.assertEqual(effect['blocking_frontier_count'], self.resolution['unresolved_count'])
        self.assertEqual(
            sorted(effect['blocking_frontier_node_ids']),
            sorted(self.resolution['unresolved_node_ids']),
        )
        self.assertEqual(effect['frontiers_total'], resolution_tool.UNRESOLVED_FRONTIERS)
        # The effect is derived from the #388 tree, never asserted in the void.
        self.assertFalse(self.issue388['tree']['enumeration_complete'])
        self.assertFalse(effect['enumeration_complete'])
        # The same frontier gap keeps the required tree open in the T8 preflight,
        # so the effect is propagated end to end (frontier -> required_tree_complete).
        self.assertFalse(self.preflight['required_tree_complete'])
        frontier_condition = self.preflight['admissibility']['conditions'][
            'no_unresolved_raise_sizing_frontier'
        ]
        self.assertFalse(frontier_condition['satisfied'])
        self.assertEqual(
            frontier_condition['unresolved_frontiers'], self.resolution['unresolved_count']
        )
        # Every required tree-completeness condition stays false because of it.
        self.assertEqual(
            self.preflight['required_tree_complete'],
            all(
                condition['satisfied']
                for condition in self.preflight['admissibility']['conditions'].values()
            ),
        )

    def test_v1_bundle_is_frozen_and_never_a_write_target(self):
        # The re-hosted semantics live *only* in the versioned v2 bundle: the tool
        # writes to a distinct directory whose schema is explicitly v2, and the
        # consumed v1 bundle is pinned, re-verified and never rewritten.
        self.assertEqual(resolution_tool.OUTPUT.name, 'raise_sizing_frontiers_v2')
        self.assertEqual(resolution_tool.V1_OUTPUT.name, 'raise_sizing_frontiers')
        self.assertNotEqual(resolution_tool.OUTPUT, resolution_tool.V1_OUTPUT)
        self.assertEqual(resolution_tool.SCHEMA, 'poker-raise-sizing-frontier-resolution/v2')
        self.assertEqual(resolution_tool.V1_SCHEMA, 'poker-raise-sizing-frontier-resolution/v1')
        self.assertEqual(self.resolution['schema'], resolution_tool.SCHEMA)
        self.assertEqual(self.resolution['revision'], 'v2')
        self.assertEqual(self.resolution['supersedes_schema'], resolution_tool.V1_SCHEMA)

        # The frozen v1 bytes are re-derived from disk, not asserted.
        custody = resolution_tool.verify_v1_custody()
        self.assertEqual(custody['result'], 'PASS')
        self.assertTrue(custody['never_rewritten'])
        for name, pinned in (
            (resolution_tool.V1_ARTIFACT_NAME, resolution_tool.V1_RESOLUTION_SHA256),
            ('SUMMARY.md', resolution_tool.V1_SUMMARY_SHA256),
            ('ARTIFACTS.json', resolution_tool.V1_INDEX_SHA256),
        ):
            with self.subTest(artifact=name):
                data = (resolution_tool.V1_OUTPUT / name).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), pinned)
        v1_payload = json.loads(
            (resolution_tool.V1_OUTPUT / resolution_tool.V1_ARTIFACT_NAME).read_text()
        )
        self.assertEqual(v1_payload['schema'], resolution_tool.V1_SCHEMA)
        # v1 predates the re-hosted semantics: it must not carry the v2 blocker.
        self.assertNotIn('blocker', v1_payload['frontiers'][0])
        # ... while the v2 revision does, and records the v1 custody it supersedes.
        self.assertEqual(self.resolution['supersedes_v1']['result'], 'PASS')
        self.assertEqual(
            self.resolution['supersedes_v1']['artifacts'][resolution_tool.V1_ARTIFACT_NAME],
            resolution_tool.V1_RESOLUTION_SHA256,
        )
        self.assertIn('blocker', self.resolution['frontiers'][0])

        # A write aimed at the v1 directory is refused outright and leaves the
        # frozen bytes untouched.
        before = {
            name: hashlib.sha256((resolution_tool.V1_OUTPUT / name).read_bytes()).hexdigest()
            for name in (
                resolution_tool.V1_ARTIFACT_NAME, 'SUMMARY.md', 'ARTIFACTS.json',
            )
        }
        with self.assertRaises(ValueError):
            resolution_tool.persist(resolution_tool.V1_OUTPUT, {}, '')
        after = {
            name: hashlib.sha256((resolution_tool.V1_OUTPUT / name).read_bytes()).hexdigest()
            for name in (
                resolution_tool.V1_ARTIFACT_NAME, 'SUMMARY.md', 'ARTIFACTS.json',
            )
        }
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
