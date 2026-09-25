#!/usr/bin/env python3
"""#419 terminal decision: content-addressed bundle, blockers and n8n output block.

These tests pin the *terminal* state of #419: the decision is derived from the
T5/T7/T8 evidence, admission is never forced, the eight required artifacts are
present and content-addressed, the frozen upstream bundles are untouched and the
``N8N_TASK_RESULT`` block hands ``next_issue=367`` back to the orchestrator
without ever running #367.
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training import finalize_hierarchical_exact_tree_decision as tool  # noqa: E402


class HierarchicalTerminalDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = tool.BUNDLE
        cls.index = json.loads((cls.bundle / tool.INDEX_NAME).read_text())
        cls.decision_bytes = (cls.bundle / tool.DECISION_NAME).read_bytes()
        cls.decision = json.loads(cls.decision_bytes)
        cls.n8n_bytes = (cls.bundle / tool.N8N_NAME).read_bytes()
        cls.summary = (cls.bundle / tool.SUMMARY_NAME).read_text()
        cls.preflight = json.loads((tool.preflight_tool.OUTPUT / tool.preflight_tool.NAME).read_text())
        cls.validation = json.loads(
            (tool.validation_tool.OUTPUT / tool.validation_tool.RESULT_NAME).read_text()
        )
        cls.frontier = json.loads(
            (tool.frontier_tool.OUTPUT / tool.frontier_tool.ARTIFACT_NAME).read_text()
        )

    def test_bundle_is_content_addressed_and_required_artifacts_present(self):
        for name in tool.REQUIRED_NAMES:
            with self.subTest(required=name):
                self.assertIn(name, self.index)
                self.assertEqual(len(self.index[name]['sha256']), 64)
                self.assertIn('path', self.index[name])
                self.assertIn('object', self.index[name])
        own_dir = (self.bundle / 'sha256').relative_to(ROOT)
        own_objects = set()
        for name, entry in self.index.items():
            with self.subTest(artifact=name):
                path = ROOT / entry['path']
                obj = ROOT / entry['object']
                self.assertTrue(path.exists(), path)
                data = path.read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'])
                self.assertTrue(obj.exists(), obj)
                self.assertEqual(data, obj.read_bytes())
                if name.endswith('.json'):
                    self.assertEqual(
                        entry['canonical_payload_sha256'],
                        tool.stable_hash(json.loads(data)),
                    )
                if Path(entry['object']).parent == own_dir:
                    own_objects.add(Path(entry['object']).name)
        self.assertEqual({p.name for p in (self.bundle / 'sha256').iterdir()}, own_objects)

    def test_terminal_decision_never_forces_admission(self):
        self.assertEqual(self.decision['schema'], tool.SCHEMA)
        self.assertEqual(self.decision['issue'], 419)
        self.assertEqual(self.decision['decision'], tool.DECISION_UNRESOLVED)
        self.assertEqual(self.decision['status'], tool.STATUS_BLOCKED)
        self.assertFalse(self.decision['admitted'])
        self.assertFalse(self.decision['candidate']['admitted'])
        self.assertNotEqual(self.decision['decision'], tool.DECISION_ADMIT)
        self.assertFalse(self.decision['required_tree_complete'])
        self.assertEqual(
            (self.decision['candidate_id'], self.decision['candidate_sha256']),
            (tool.H.CANDIDATE_ID, tool.preflight_tool.CANDIDATE_CANONICAL_SHA256),
        )
        self.assertNotEqual(self.decision['candidate_sha256'], tool.ISSUE352_CANDIDATE_SHA256)
        self.assertEqual(self.decision['next_issue'], 367)

    def test_decision_is_coherent_with_t5_t7_t8(self):
        admissibility = self.preflight['admissibility']
        self.assertEqual(self.decision['required_tree_complete'],
                         self.preflight['required_tree_complete'])
        self.assertEqual(self.decision['required_tree_sha256'],
                         self.preflight['required_tree']['required_tree_sha256'])
        self.assertEqual(self.decision['admissible_exact_node_count'],
                         admissibility['admissible_exact_nodes'])
        self.assertEqual(self.decision['exact_unresolved_node_count'],
                         admissibility['status_counts']['EXACT_UNRESOLVED'])
        self.assertEqual(self.decision['validation_outcome'], self.validation['outcome'])
        self.assertEqual(self.decision['validation_failing_gates'],
                         self.validation['gate']['failing_gates'])
        self.assertEqual(self.decision['unresolved_raise_sizing_frontier_count'],
                         self.frontier['unresolved_count'])
        codes = [blocker['code'] for blocker in self.decision['blockers']]
        self.assertEqual(codes, [tool.BLOCK_REQUIRED_TREE_INCOMPLETE,
                                 tool.BLOCK_UNRESOLVED_RAISE_SIZING,
                                 tool.BLOCK_VALIDATION_GATES])
        self.assertEqual(self.decision['primary_blocker'], tool.BLOCK_REQUIRED_TREE_INCOMPLETE)
        tree_blocker = self.decision['blockers'][0]
        self.assertEqual(tree_blocker['status_counts'], admissibility['status_counts'])
        self.assertEqual(tree_blocker['unresolved_reason_counts'],
                         admissibility['unresolved_reason_counts'])
        self.assertEqual(tree_blocker['required_nodes'],
                         self.preflight['required_tree']['required_node_count'])
        sizing_blocker = self.decision['blockers'][1]
        self.assertEqual(sizing_blocker['unresolved_count'], self.frontier['unresolved_count'])
        self.assertEqual(sizing_blocker['unresolved_node_ids'],
                         list(self.frontier['unresolved_node_ids']))
        validation_blocker = self.decision['blockers'][2]
        self.assertEqual(validation_blocker['outcome'], self.validation['outcome'])
        self.assertEqual(validation_blocker['failing_gates'],
                         self.validation['gate']['failing_gates'])
        self.assertEqual(
            self.preflight['nearest_substitution_audit']['substitutions_applied'], 0
        )

    def test_holdout_and_pointer_discipline(self):
        self.assertTrue(self.decision['validation_consumed'])
        self.assertFalse(self.decision['test_consumed'])
        self.assertFalse(self.decision['active_pointer_mutated'])
        self.assertFalse(self.decision['hero_ev_executed'])
        self.assertFalse(self.decision['issue367_run'])
        self.assertFalse(self.decision['issue367_authorized'])
        self.assertTrue(self.decision['protected_files_before_after_sha256']['unchanged'])
        self.assertEqual(
            self.decision['protected_files_before_after_sha256']['before'],
            self.decision['protected_files_before_after_sha256']['after'],
        )
        frozen = self.decision['frozen_inputs_untouched']
        self.assertEqual(tool.sha256_file(tool.HERE / tool.INDEX_NAME),
                         frozen['root_artifacts_sha256'])
        self.assertEqual(tool.sha256_file(tool.HERE / tool.SUMMARY_NAME),
                         frozen['root_summary_sha256'])
        self.assertEqual(tool.sha256_file(tool.spec_tool.SPEC_PATH),
                         frozen['hierarchical_model_spec_sha256'])
        self.assertEqual(tool.sha256_file(tool.protocol_tool.PROTOCOL_PATH),
                         frozen['frozen_validation_protocol_sha256'])
        self.assertEqual(tool.sha256_file(tool.HERE / tool.baseline_tool.BASELINE_NAME),
                         frozen['hierarchical_tree_sparsity_baseline_sha256'])
        self.assertEqual(tool.sha256_file(tool.legacy.REFERENCE),
                         frozen['active_reference_sha256'])
        # the baseline bundle still verifies after the terminal decision was written
        tool.verify_content_address(tool.HERE)

    def test_n8n_output_block_is_exact_with_next_issue_367(self):
        block = self.decision['n8n_task_result']
        self.assertEqual(block['type'], 'N8N_TASK_RESULT')
        self.assertEqual(block['issue'], 419)
        self.assertEqual(block['decision'], tool.DECISION_UNRESOLVED)
        self.assertEqual(block['status'], tool.STATUS_BLOCKED)
        self.assertFalse(block['admitted'])
        self.assertEqual(block['candidate_id'], tool.H.CANDIDATE_ID)
        self.assertEqual(block['candidate_sha256'],
                         tool.preflight_tool.CANDIDATE_CANONICAL_SHA256)
        self.assertFalse(block['required_tree_complete'])
        self.assertEqual(block['required_tree_sha256'],
                         tool.baseline_tool.ISSUE388_REQUIRED_TREE_SHA256)
        self.assertEqual(block['blockers'], [tool.BLOCK_REQUIRED_TREE_INCOMPLETE,
                                             tool.BLOCK_UNRESOLVED_RAISE_SIZING,
                                             tool.BLOCK_VALIDATION_GATES])
        self.assertTrue(block['validation_consumed'])
        self.assertFalse(block['test_consumed'])
        self.assertFalse(block['active_pointer_mutated'])
        self.assertFalse(block['hero_ev_executed'])
        self.assertFalse(block['issue367_run'])
        self.assertEqual(block['next_issue'], 367)
        rendered = tool.render_n8n_block(block)
        self.assertEqual(self.n8n_bytes, rendered.encode())
        self.assertTrue(rendered.startswith('N8N_TASK_RESULT\n'))
        self.assertIn('next_issue: 367\n', rendered)
        self.assertIn(rendered.rstrip('\n'), self.summary)

    def test_deterministic_rebuild_matches_persisted_decision(self):
        decision, summary, n8n_text = tool.build()
        self.assertEqual(tool.serialize(decision), self.decision_bytes)
        self.assertEqual(summary.encode(), (self.bundle / tool.SUMMARY_NAME).read_bytes())
        self.assertEqual(n8n_text.encode(), self.n8n_bytes)
        self.assertEqual(tool.stable_hash(decision),
                         self.index[tool.DECISION_NAME]['canonical_payload_sha256'])

    def test_tool_cannot_run_issue367(self):
        self.assertEqual(tool.verify_no_issue367_runner()['result'], 'PASS')
        for source in (
            'from tools.simulation import run_issue367_real_iso_ev\n',
            'import run_issue367_real_iso_ev\n',
            'hero_recommendation = None\n',
        ):
            with self.subTest(source=source), self.assertRaises(tool.TerminalDecisionError):
                tool.verify_no_issue367_runner(source)

    def test_check_mode_passes_on_the_persisted_bundle(self):
        self.assertEqual(tool.check(), 0)
        self.assertTrue(tool.DECISION_RECORD.exists())
        record = tool.DECISION_RECORD.read_text()
        self.assertIn(tool.DECISION_UNRESOLVED, record)
        self.assertIn('367', record)


if __name__ == '__main__':
    unittest.main()
