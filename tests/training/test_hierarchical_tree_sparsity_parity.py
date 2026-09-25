#!/usr/bin/env python3
"""#419 parity guard: the TRAIN sparsity baseline must reproduce #388 exactly.

The baseline is content-addressed and must stay byte-identical to a live
TRAIN-only re-derivation. No VALIDATION/TEST hand is ever parsed here.
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

from tools.training import audit_hierarchical_tree_sparsity as baseline_tool


class HierarchicalTreeSparsityParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = baseline_tool.OUTPUT
        cls.index = json.loads((cls.output / 'ARTIFACTS.json').read_text())
        cls.baseline = json.loads(
            (cls.output / baseline_tool.BASELINE_NAME).read_text()
        )
        cls.issue388 = baseline_tool.load_issue388()

    def test_persisted_baseline_content_addressing(self):
        self.assertIn(baseline_tool.BASELINE_NAME, self.index)
        for name, entry in self.index.items():
            data = (self.output / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'], name)
            self.assertEqual(data, (self.output / entry['object']).read_bytes(), name)
        self.assertEqual(
            {p.name for p in (self.output / 'sha256').iterdir()},
            {Path(entry['object']).name for entry in self.index.values()},
        )
        entry = self.index[baseline_tool.BASELINE_NAME]
        self.assertEqual(entry['canonical_payload_sha256'], baseline_tool.stable_hash(self.baseline))
        self.assertEqual(self.baseline['schema'], baseline_tool.SCHEMA)
        self.assertEqual(self.baseline['issue'], 419)
        self.assertEqual(self.baseline['source_issue'], 388)
        self.assertEqual(self.baseline['scenario_issue'], 321)

    def test_declares_train_only_no_holdout(self):
        self.assertEqual(self.baseline['split_consumed'], 'TRAIN')
        self.assertFalse(self.baseline['validation_consumed'])
        self.assertFalse(self.baseline['test_consumed'])
        self.assertTrue(self.baseline['protected_files_before_after_sha256']['unchanged'])
        self.assertFalse(self.issue388['report']['validation_consumed'])
        self.assertFalse(self.issue388['report']['test_consumed'])

    def test_binds_verified_issue388_hashes_and_boundaries(self):
        # Re-verify the #388 evidence from its persisted bytes.
        baseline_tool.verify_issue388_boundaries(self.issue388)
        bindings = self.baseline['issue388_bindings']
        self.assertEqual(bindings['required_tree_sha256'], baseline_tool.ISSUE388_REQUIRED_TREE_SHA256)
        self.assertEqual(bindings['train_support_sha256'], baseline_tool.ISSUE388_TRAIN_SUPPORT_SHA256)
        self.assertEqual(bindings['decision_sha256'], baseline_tool.ISSUE388_DECISION_SHA256)
        self.assertEqual(
            bindings['required_tree_sha256'],
            '0ab232ae44e4157e2a47d4d3d611ac8ca9c2cdb54caf2568f256f6df35643a25',
        )
        self.assertFalse(bindings['enumeration_complete'])
        self.assertEqual(bindings['unresolved_sizing_frontier_count'], 7)
        self.assertEqual(bindings['train_hands_parsed'], 19016)
        self.assertEqual(bindings['required_node_count'], 38)
        self.assertEqual(
            bindings['required_tree_artifact_sha256'],
            self.index_sha256('REQUIRED_EXACT_TREE.json'),
        )
        self.assertEqual(
            bindings['train_support_artifact_sha256'],
            self.index_sha256('TRAIN_RESPONSE_TREE_SUPPORT.json'),
        )
        self.assertEqual(
            bindings['decision_artifact_sha256'],
            self.index_sha256('DECISION.json'),
        )

    def index_sha256(self, name: str) -> str:
        return self.issue388['index'][name]['sha256']

    def test_matrix_parity_with_issue388_cell_by_cell(self):
        issue388_by_id = {cell['node_id']: cell for cell in self.issue388['report']['matrix']}
        self.assertEqual(len(self.baseline['nodes']), 38)
        self.assertEqual(set(issue388_by_id), {n['node_id'] for n in self.baseline['nodes']})
        for node in self.baseline['nodes']:
            other = issue388_by_id[node['node_id']]
            with self.subTest(node=node['node_id']):
                self.assertEqual(node['path'], other['path'])
                self.assertEqual(
                    node['runtime_support_context_key'], other['runtime_support_context_key']
                )
                self.assertEqual(node['audit_exact_key'], other['audit_exact_key'])
                self.assertEqual(
                    node['runtime_support_context_support'],
                    other['runtime_support_context_support'],
                )
                self.assertEqual(node['audit_exact_support'], other['audit_exact_support'])
        # Both granularities are persisted, hashed and internally consistent.
        runtime_sha = baseline_tool.stable_hash(
            [{'node_id': n['node_id']} | n['runtime_support_context_support']
             for n in self.baseline['nodes']]
        )
        audit_sha = baseline_tool.stable_hash(
            [{'node_id': n['node_id']} | n['audit_exact_support'] for n in self.baseline['nodes']]
        )
        self.assertEqual(self.baseline['baseline_matrix_sha256']['runtime_support_context'], runtime_sha)
        self.assertEqual(self.baseline['baseline_matrix_sha256']['audit_exact'], audit_sha)
        # The runtime granularity is strictly coarser than the audit partition.
        self.assertEqual(
            self.baseline['summary']['distinct_runtime_support_context_keys'], 30
        )
        self.assertEqual(self.baseline['summary']['distinct_audit_exact_keys'], 38)
        self.assertGreater(self.baseline['summary']['runtime_keys_merging_audit_states'], 0)

    def test_canonical_qualification_and_counts(self):
        summary = self.baseline['summary']
        self.assertEqual(summary['nodes_total'], 38)
        self.assertEqual(summary['runtime_qualified_nodes'], 3)
        self.assertEqual(summary['runtime_blocked_nodes'], 35)
        self.assertEqual(len(self.baseline['runtime_support_context_qualified_nodes']), 3)
        bb = self.baseline['canonical_cells']['bb_facing_sb_iso5']
        self.assertTrue(bb['reconciled'])
        self.assertEqual((bb['runtime_observations'], bb['runtime_distinct_hands']), (45, 45))
        self.assertTrue(bb['runtime_qualifies'])
        self.assertEqual((bb['audit_exact_observations'], bb['audit_exact_distinct_hands']), (6, 6))
        co = self.baseline['canonical_cells']['co_after_bb_fold']
        self.assertTrue(co['reconciled'])
        self.assertEqual((co['runtime_observations'], co['runtime_distinct_hands']), (14, 14))
        self.assertFalse(co['runtime_qualifies'])
        self.assertEqual((co['audit_exact_observations'], co['audit_exact_distinct_hands']), (4, 4))
        # Exact reproduction of #388's qualified-node projection.
        self.assertEqual(
            self.baseline['runtime_support_context_qualified_nodes'],
            self.issue388['decision']['runtime_support_context_qualified_nodes'],
        )

    def test_issue352_digest_gap_is_recorded_not_repaired(self):
        gap = self.baseline['issue352_digest_gap']
        self.assertEqual(
            gap['historical_reported_evidence_sha256'],
            'cacf97c80f44856da6e787b230ab1b564d5c0c83821a894e57b70aba92145738',
        )
        self.assertEqual(
            gap['persisted_payload_without_digest_sha256'],
            'ec96d6da20aca0ecb12717ed864ab2df8322a2e28bcb565b8cce9d94a106f367',
        )
        self.assertFalse(gap['historical_digest_recomputed_match'])
        self.assertNotEqual(
            gap['historical_reported_evidence_sha256'],
            gap['persisted_payload_without_digest_sha256'],
        )
        self.assertEqual(gap, baseline_tool.issue352_digest_gap())

    def test_tree_rederivation_matches_issue388(self):
        tree = baseline_tool.rederive_tree()
        self.assertEqual(tree, self.issue388['tree'])
        self.assertEqual(baseline_tool.stable_hash(tree), baseline_tool.ISSUE388_REQUIRED_TREE_SHA256)

    def test_full_train_rederivation_reproduces_persisted_baseline(self):
        # Expensive: parses every certified TRAIN hand once.
        result = baseline_tool.rederive()
        self.assertEqual(
            baseline_tool.stable_hash(result['report']), baseline_tool.ISSUE388_TRAIN_SUPPORT_SHA256
        )
        self.assertTrue(result['parity']['cells_match'])
        self.assertEqual(result['parity']['mismatches'], [])
        self.assertTrue(result['tree_rederived_equal'])
        # Rebuilding the full artifact from the live recount is byte-stable.
        rebuilt = baseline_tool.build_baseline(
            tree=result['tree'], report=result['report'], counts=result['counts'],
            bundle=result['issue388'], provenance=result['report']['provenance'],
            parity=result['parity'], tree_rederived_equal=True,
            protected_before=self.baseline['protected_files_before_after_sha256']['before'],
            protected_after=self.baseline['protected_files_before_after_sha256']['after'],
        )
        self.assertEqual(
            baseline_tool.stable_hash(rebuilt), baseline_tool.stable_hash(self.baseline)
        )
        self.assertEqual(rebuilt, copy.deepcopy(self.baseline))


if __name__ == '__main__':
    unittest.main()
