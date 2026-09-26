#!/usr/bin/env python3
"""#419 terminal decision v2: digest-pinned v1, no new holdout read, no forced admission.

These tests pin the *terminal* state of #419 as two explicit revisions:

* the **v2** decision (``terminal_decision_v2/DECISION_V2.json``) is composed of
  the TRAIN-only exact-tree preflight v2 and the **already-consumed** v1
  VALIDATION result bytes referenced **by digest**; it re-opens no holdout, it
  recomputes no metric, it forces no admission, and it hands ``next_issue=367``
  back to the orchestrator without ever running #367;
* the **v1** decision (``terminal_decision/DECISION.json``) stays byte-identical:
  it is re-verified byte-for-byte, is never rewritten, and ``--revision v1`` is
  refused.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import pathlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training import finalize_hierarchical_exact_tree_decision as tool  # noqa: E402


class HierarchicalTerminalDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = tool.V2_BUNDLE
        cls.index = json.loads((cls.bundle / tool.V2_INDEX_NAME).read_text(encoding="utf-8"))
        cls.decision_bytes = (cls.bundle / tool.V2_NAME).read_bytes()
        cls.decision = json.loads(cls.decision_bytes)
        cls.n8n_bytes = (cls.bundle / tool.V2_N8N_NAME).read_bytes()
        cls.summary = (cls.bundle / tool.V2_SUMMARY_NAME).read_text(encoding="utf-8")
        cls.preflight_v2 = json.loads(tool.PREFLIGHT_V2_PATH.read_text(encoding="utf-8"))
        cls.validation = json.loads(
            tool.V1_VALIDATION_RESULT_PATH.read_text(encoding="utf-8")
        )
        cls.frontier = json.loads(
            (tool.frontier_tool.OUTPUT / tool.frontier_tool.ARTIFACT_NAME).read_text(
                encoding="utf-8"
            )
        )
        cls.v1_decision = json.loads((tool.BUNDLE / tool.DECISION_NAME).read_text(encoding="utf-8"))

    # ---------------------------------------------------------------- bundle
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
        # the two v2 constituents are bound by digest inside the same index
        self.assertEqual(
            self.index['EXACT_TREE_PREFLIGHT_V2.json']['sha256'],
            tool.PREFLIGHT_V2_BYTE_SHA256,
        )
        self.assertEqual(
            self.index[tool.V1_VALIDATION_RESULT_NAME]['sha256'],
            tool.V1_VALIDATION_RESULT_SHA256,
        )

    # ------------------------------------------------------ frozen v1 revision
    def test_v1_decision_stays_byte_identical_and_is_never_regenerated(self):
        for name, pinned in (
            (tool.DECISION_NAME, tool.V1_DECISION_SHA256),
            (tool.SUMMARY_NAME, tool.V1_SUMMARY_SHA256),
            (tool.INDEX_NAME, tool.V1_INDEX_SHA256),
            (tool.N8N_NAME, tool.V1_N8N_SHA256),
        ):
            with self.subTest(artifact=name):
                self.assertEqual(tool.sha256_file(tool.BUNDLE / name), pinned)
        self.assertEqual(
            tool.sha256_file(tool.BUNDLE / tool.DECISION_NAME),
            '9425f30163dcfa5e0a72ca8f6dd1bb4b6a25ce270b4a894aaa57e898a74bd0bc',
        )
        self.assertEqual(
            self.v1_decision['schema'], 'poker-hierarchical-exact-tree-terminal-decision/v1'
        )
        self.assertEqual(tool.stable_hash(self.v1_decision), tool.V1_DECISION_CANONICAL_SHA256)
        custody = tool.verify_frozen_v1_decision()
        self.assertEqual(custody['result'], 'PASS')
        self.assertTrue(custody['never_rewritten'])
        self.assertFalse(custody['supersession']['regeneration_possible'])
        self.assertFalse(custody['v1_code_bindings']['decision_tool_unchanged_since_v1'])
        self.assertNotEqual(
            custody['v1_code_bindings']['recorded_decision_tool_sha256'],
            custody['v1_code_bindings']['live_decision_tool_sha256'],
        )
        # the v2 decision records the v1 identity it was built against
        self.assertEqual(
            self.decision['decision_rule']['inherited_from_v1_decision']['sha256'],
            tool.V1_DECISION_SHA256,
        )
        self.assertEqual(
            self.decision['frozen_inputs_untouched']['v1_decision_sha256'],
            tool.V1_DECISION_SHA256,
        )
        self.assertEqual(
            self.index[tool.DECISION_NAME]['sha256'], tool.V1_DECISION_SHA256
        )

    def test_tools_write_only_versioned_v2_bundles_and_never_v1(self):
        # The reader/writer split is structural: the terminal decision is written
        # only to the versioned v2 bundle, the frontier semantics only to the
        # versioned v2 frontier bundle, and both v1 bundles are pinned custody.
        self.assertEqual(tool.V2_BUNDLE.name, 'terminal_decision_v2')
        self.assertNotEqual(tool.V2_BUNDLE, tool.BUNDLE)
        self.assertNotEqual(tool.V2_SCHEMA, tool.SCHEMA)
        self.assertEqual(tool.frontier_tool.OUTPUT.name, 'raise_sizing_frontiers_v2')
        self.assertNotEqual(tool.frontier_tool.OUTPUT, tool.frontier_tool.V1_OUTPUT)

        v1_frontier = tool.verify_v1_raise_sizing_frontier()
        self.assertEqual(v1_frontier['result'], 'PASS')
        self.assertTrue(v1_frontier['never_rewritten'])
        self.assertEqual(
            v1_frontier['artifacts'][tool.frontier_tool.V1_ARTIFACT_NAME],
            tool.V1_FRONTIER_RESOLUTION_SHA256,
        )
        self.assertEqual(
            tool.sha256_file(
                tool.frontier_tool.V1_OUTPUT / tool.frontier_tool.V1_ARTIFACT_NAME
            ),
            tool.V1_FRONTIER_RESOLUTION_SHA256,
        )
        # v1 predates the re-hosted semantics; the v2 revision carries them.
        v1_payload = json.loads(
            (tool.frontier_tool.V1_OUTPUT / tool.frontier_tool.V1_ARTIFACT_NAME).read_text(
                encoding='utf-8'
            )
        )
        self.assertNotIn('blocker', v1_payload['frontiers'][0])
        self.assertEqual(
            self.decision['raise_sizing_frontier_revision']['schema'],
            tool.frontier_tool.SCHEMA,
        )
        self.assertEqual(
            self.decision['raise_sizing_frontier_revision']['revision'], 'v2'
        )
        self.assertEqual(
            self.decision['sizing_frontiers']['required_tree_complete_effect'],
            tool.frontier_tool.REQUIRED_TREE_COMPLETE_EFFECT,
        )
        # The bound artifact is the v2 frontier, while the frozen v1 frontier and
        # the frozen v1 decision custody are recorded by digest.
        self.assertEqual(
            self.index[tool.frontier_tool.ARTIFACT_NAME]['sha256'],
            tool.sha256_file(
                tool.frontier_tool.OUTPUT / tool.frontier_tool.ARTIFACT_NAME
            ),
        )
        self.assertEqual(
            self.index[tool.DECISION_NAME]['sha256'], tool.V1_DECISION_SHA256
        )
        frozen = self.decision['frozen_inputs_untouched']
        self.assertEqual(
            frozen['v1_terminal_decision_bundle_index_sha256'], tool.V1_INDEX_SHA256
        )
        self.assertEqual(
            frozen['v1_raise_sizing_frontier_sha256'],
            tool.V1_FRONTIER_RESOLUTION_SHA256,
        )
        self.assertEqual(
            frozen['v1_raise_sizing_frontier_bundle_index_sha256'],
            tool.V1_FRONTIER_INDEX_SHA256,
        )
        # A v2 build leaves every v1 bundle byte-identical.
        tool.build()
        self.assertEqual(
            tool.sha256_file(tool.BUNDLE / tool.DECISION_NAME), tool.V1_DECISION_SHA256
        )
        self.assertEqual(
            tool.sha256_file(
                tool.frontier_tool.V1_OUTPUT / tool.frontier_tool.V1_ARTIFACT_NAME
            ),
            tool.V1_FRONTIER_RESOLUTION_SHA256,
        )

    # ------------------------------------------------- terminal decision rules
    def test_v2_decision_never_forces_admission_and_is_coherent_with_preflight_v2(self):
        self.assertEqual(self.decision['schema'], tool.V2_SCHEMA)
        self.assertEqual(self.decision['supersedes_schema'], tool.SCHEMA)
        self.assertEqual(self.decision['issue'], 419)
        self.assertEqual(self.decision['revision'], 'v2')
        self.assertEqual(self.decision['decision'], tool.DECISION_UNRESOLVED)
        self.assertEqual(self.decision['status'], tool.STATUS_BLOCKED)
        self.assertFalse(self.decision['admitted'])
        self.assertFalse(self.decision['candidate']['admitted'])
        self.assertNotEqual(self.decision['decision'], tool.DECISION_ADMIT)
        self.assertFalse(self.decision['required_tree_complete'])
        self.assertEqual(self.decision['next_issue'], 367)
        self.assertEqual(
            (self.decision['candidate_id'], self.decision['candidate_sha256']),
            (tool.H.CANDIDATE_ID, tool.preflight_tool.CANDIDATE_CANONICAL_SHA256),
        )
        self.assertNotEqual(self.decision['candidate_sha256'], tool.ISSUE352_CANDIDATE_SHA256)

        # coherence with the TRAIN-only preflight v2 that produced the tree verdict
        admissibility = self.preflight_v2['admissibility']
        self.assertEqual(
            self.decision['required_tree_complete'],
            self.preflight_v2['required_tree_complete'],
        )
        self.assertEqual(
            self.decision['required_tree_sha256'],
            self.preflight_v2['required_tree']['required_tree_sha256'],
        )
        self.assertEqual(
            self.decision['required_tree_node_count'],
            self.preflight_v2['required_tree']['required_node_count'],
        )
        self.assertEqual(
            self.decision['required_tree_complete_reason_codes'],
            list(self.preflight_v2['required_tree_complete_reason_codes']),
        )
        self.assertEqual(
            self.decision['admissible_exact_node_count'],
            admissibility['admissible_exact_nodes'],
        )
        self.assertEqual(
            self.decision['exact_unresolved_node_count'],
            admissibility['status_counts']['EXACT_UNRESOLVED'],
        )
        self.assertEqual(
            self.decision['unresolved_reason_counts'],
            admissibility['unresolved_reason_counts'],
        )
        self.assertEqual(
            self.decision['nodes_with_no_admissible_pooling_level'],
            admissibility['unresolved_reason_counts']['NO_ADMISSIBLE_POOLING_LEVEL'],
        )
        self.assertEqual(
            self.preflight_v2['boundary']['split_consumed'], 'TRAIN'
        )
        self.assertFalse(self.preflight_v2['boundary']['validation_consumed'])
        self.assertFalse(self.preflight_v2['boundary']['test_consumed'])

    def test_admission_rule_is_live_and_never_forced(self):
        # The rule is a pure function of the frozen evidence: with every condition
        # satisfied it does admit, so the persisted UNRESOLVED verdict is computed
        # rather than hardcoded.
        code, status, blockers = tool.choose_decision(
            {
                'required_tree_complete': True,
                'nearest_substitution_audit': {'substitutions_applied': 0},
            },
            {'outcome': 'ADMIT_CANDIDATE', 'all_gates_pass': True},
            {'unresolved_count': 0},
            {},
        )
        self.assertEqual(code, tool.DECISION_ADMIT)
        self.assertEqual(status, tool.STATUS_READY)
        self.assertEqual(blockers, [])

        # ... and the persisted evidence can never reach that branch by flipping a
        # single flag: the digest-referenced VALIDATION gates stay load-bearing.
        preflight = json.loads(json.dumps(self.preflight_v2))
        validation = json.loads(json.dumps(self.decision['validation_reference']))
        frontier = json.loads(json.dumps(self.frontier))
        bindings = {
            name: {
                'sha256': entry['sha256'],
                'canonical_payload_sha256': entry.get('canonical_payload_sha256'),
            }
            for name, entry in self.index.items()
        }
        preflight['required_tree_complete'] = True
        code, _status, blockers = tool.choose_decision(preflight, validation, frontier, bindings)
        self.assertEqual(code, tool.DECISION_UNRESOLVED)
        self.assertNotEqual(code, tool.DECISION_ADMIT)
        codes = [blocker['code'] for blocker in blockers]
        self.assertIn(tool.BLOCK_REFUSED_CALIBRATION, codes)
        self.assertIn(tool.BLOCK_REFUSED_COVERAGE_FLOOR, codes)
        self.assertIn(tool.BLOCK_UNRESOLVED_RAISE_SIZING, codes)
        self.assertNotIn(tool.BLOCK_NO_ADMISSIBLE_POOLING_LEVEL, codes)

    def test_blockers_are_precise_and_fail_closed(self):
        blockers = {blocker['code']: blocker for blocker in self.decision['blockers']}
        self.assertEqual(
            [blocker['code'] for blocker in self.decision['blockers']],
            [
                tool.BLOCK_NO_ADMISSIBLE_POOLING_LEVEL,
                tool.BLOCK_UNRESOLVED_RAISE_SIZING,
                tool.BLOCK_REFUSED_CALIBRATION,
                tool.BLOCK_REFUSED_COVERAGE_FLOOR,
            ],
        )
        self.assertEqual(
            self.decision['primary_blocker'], tool.BLOCK_NO_ADMISSIBLE_POOLING_LEVEL
        )

        tree = blockers[tool.BLOCK_NO_ADMISSIBLE_POOLING_LEVEL]
        self.assertEqual(tree['nodes_with_no_admissible_pooling_level'], 31)
        self.assertEqual(tree['required_nodes'], 38)
        self.assertEqual(tree['admissible_exact_nodes'], 0)
        self.assertEqual(tree['blocked_nodes'], 38)
        self.assertEqual(tree['status_counts'], {'EXACT_UNRESOLVED': 38})
        self.assertEqual(
            tree['unresolved_reason_counts'],
            {'NO_ADMISSIBLE_POOLING_LEVEL': 31, 'RAISE_SIZING_UNRESOLVED_NO_NEAREST_PRICE': 7},
        )
        self.assertEqual(
            tree['evidence']['sha256'], tool.PREFLIGHT_V2_BYTE_SHA256
        )

        sizing = blockers[tool.BLOCK_UNRESOLVED_RAISE_SIZING]
        self.assertIs(sizing['independent_of_the_response_model'], True)
        self.assertEqual(sizing['unresolved_count'], 7)
        self.assertEqual(sizing['frontiers_total'], 7)
        self.assertEqual(sizing['resolved_count'], 0)
        self.assertEqual(sizing['unresolved_node_ids'], list(self.frontier['unresolved_node_ids']))
        self.assertTrue(sizing['blocker_persisted'])
        self.assertIs(
            self.decision['sizing_frontiers']['independent_of_the_response_model'], True
        )
        self.assertEqual(self.decision['sizing_frontiers']['unresolved_count'], 7)
        self.assertEqual(self.decision['unresolved_raise_sizing_frontier_count'], 7)

        calibration = blockers[tool.BLOCK_REFUSED_CALIBRATION]
        self.assertEqual(calibration['layer_b_gate_id'], 'CALIBRATION')
        self.assertTrue(calibration['gate_evaluated'])
        self.assertFalse(calibration['gate_passed'])
        published = {
            row['gate']: row for row in self.validation['gate']['gates']
        }
        self.assertGreater(
            calibration['measured']['pooled_ece'],
            calibration['measured']['maximum_absolute_ece'],
        )
        self.assertAlmostEqual(
            calibration['measured']['pooled_ece'], 0.13520933424825002, places=15
        )
        self.assertEqual(calibration['measured']['maximum_absolute_ece'], 0.05)
        self.assertEqual(calibration['measured']['bins_meeting_minimum_support'], 0)
        self.assertEqual(calibration['measured']['reliability_bins_required'], 40)
        self.assertEqual(
            calibration['validation_gate']['published_measured']['ece'],
            published['calibration_absolute']['measured']['ece'],
        )
        self.assertEqual(
            calibration['measured']['pooled_ece'],
            published['calibration_absolute']['measured']['ece'],
        )
        self.assertFalse(calibration['validation_gate']['pass'])
        self.assertFalse(published['calibration_absolute']['pass'])
        self.assertTrue(calibration['evidence']['digest_re_derived_from_persisted_bytes'])

        coverage = blockers[tool.BLOCK_REFUSED_COVERAGE_FLOOR]
        self.assertEqual(coverage['measured']['identifiable_decisions'], 9)
        self.assertEqual(coverage['measured']['identifiable_hands'], 9)
        self.assertEqual(coverage['measured']['required_decisions'], 200)
        self.assertEqual(coverage['measured']['required_hands'], 100)
        self.assertFalse(published['coverage_floor']['pass'])
        self.assertEqual(
            coverage['measured'], published['coverage_floor']['measured']
        )
        self.assertEqual(sorted(self.decision['validation_failing_gates']),
                         ['calibration_absolute', 'coverage_floor'])
        self.assertEqual(self.decision['validation_outcome'], self.validation['outcome'])

    # ------------------------------------------------ holdout / digest custody
    def test_validation_is_referenced_by_digest_with_no_new_holdout_read(self):
        reference = self.decision['validation_reference']
        payload = tool.V1_VALIDATION_RESULT_PATH.read_bytes()
        self.assertEqual(reference['byte_sha256'], tool.V1_VALIDATION_RESULT_SHA256)
        self.assertEqual(reference['byte_sha256'], hashlib.sha256(payload).hexdigest())
        self.assertEqual(
            reference['canonical_payload_sha256'], tool.V1_VALIDATION_RESULT_CANONICAL_SHA256
        )
        self.assertEqual(reference['canonical_payload_sha256'], tool.stable_hash(self.validation))
        self.assertTrue(reference['referenced_by_digest'])
        self.assertTrue(reference['digest_re_derived_from_persisted_bytes'])
        self.assertFalse(reference['holdout_reopened_by_this_decision'])
        self.assertFalse(reference['validation_consumed_by_this_decision'])
        self.assertFalse(reference['validation_split_re_evaluated'])
        self.assertEqual(reference['validation_decision_rows_read'], 0)
        self.assertEqual(reference['metrics_recomputed'], 0)
        self.assertFalse(reference['thresholds_re_selected'])
        self.assertEqual(reference['hand_histories_parsed'], 0)

        no_holdout = self.decision['no_new_holdout_read']
        self.assertEqual(no_holdout['result'], 'PASS')
        self.assertFalse(no_holdout['holdout_reopened_by_this_decision'])
        self.assertFalse(no_holdout['validation_split_re_evaluated'])
        self.assertEqual(no_holdout['validation_decision_rows_read'], 0)
        self.assertEqual(no_holdout['metrics_recomputed'], 0)
        self.assertFalse(no_holdout['thresholds_re_selected'])
        self.assertEqual(no_holdout['hand_histories_parsed'], 0)
        self.assertFalse(no_holdout['dataset_archives_opened'])
        self.assertTrue(no_holdout['validation_result_referenced_by_digest'])
        self.assertTrue(no_holdout['digest_re_derived_from_persisted_bytes'])
        self.assertEqual(no_holdout['static_scan']['result'], 'PASS')
        self.assertFalse(
            [path for path in no_holdout['opened_inputs'] if 'training/datasets' in path]
        )

        # the digest is the one the frozen protocol v2 and the preflight v2 attest
        self.assertEqual(
            self.decision['protocol_custody']['validation_result_custody_pin'],
            tool.V1_VALIDATION_RESULT_SHA256,
        )
        attestation = self.preflight_v2['admissibility_protocol']['calibration_gate'][
            'evidence'
        ]['attestation']
        self.assertEqual(attestation['source_byte_sha256'], tool.V1_VALIDATION_RESULT_SHA256)
        self.assertEqual(attestation['protocol_v2_custody_pin'], tool.V1_VALIDATION_RESULT_SHA256)
        self.assertEqual(
            self.decision['calibration_gate']['protocol_v2_custody_pin'],
            tool.V1_VALIDATION_RESULT_SHA256,
        )

    def test_holdout_scan_and_hand_history_tripwire_fail_closed(self):
        self.assertEqual(tool.verify_no_holdout_access()['result'], 'PASS')
        for source in (
            'from tools.training.validate_hierarchical_validation import load_validation_records\n',
            'import load_holdout\n',
            'rows = validation_decision_rows\n',
        ):
            with self.subTest(source=source), self.assertRaises(tool.TerminalDecisionError):
                tool.verify_no_holdout_access(source)
        for path in (
            ROOT / 'training/datasets/anything.jsonl',
            ROOT / 'training/datasets/nested/anything.zip',
        ):
            with self.subTest(path=str(path)), self.assertRaises(tool.TerminalDecisionError):
                with tool.hand_history_tripwire():
                    path.open('rb')

    def test_v2_decision_reads_only_the_published_validation_artifact_and_no_dataset(self):
        opened: list[str] = []
        original_open = pathlib.Path.open

        def counting_open(self, *args, **kwargs):
            opened.append(str(self))
            return original_open(self, *args, **kwargs)

        pathlib.Path.open = counting_open
        try:
            tool.build()
        finally:
            pathlib.Path.open = original_open
        # the only holdout-adjacent input opened is the *published*, digest-referenced
        # VALIDATION result artifact; every read of it is a byte-level digest /
        # binding read, never a decision-row read
        validation_reads = {
            path for path in opened if path == str(tool.V1_VALIDATION_RESULT_PATH)
        }
        self.assertEqual(validation_reads, {str(tool.V1_VALIDATION_RESULT_PATH)})
        self.assertFalse([path for path in opened if 'training/datasets' in path])
        self.assertFalse(
            [path for path in opened if Path(path).suffix.lstrip('.').lower()
             in tool.HAND_HISTORY_SUFFIXES]
        )

    def test_holdout_and_pointer_discipline(self):
        self.assertTrue(self.decision['validation_consumed'])
        self.assertFalse(self.decision['test_consumed'])
        self.assertFalse(self.decision['test_authorized'])
        self.assertFalse(self.decision['active_pointer_mutated'])
        self.assertFalse(self.decision['hero_ev_executed'])
        self.assertFalse(self.decision['issue367_run'])
        self.assertFalse(self.decision['issue367_authorized'])
        self.assertTrue(self.decision['protected_files_before_after_sha256']['unchanged'])
        self.assertEqual(
            self.decision['protected_files_before_after_sha256']['before'],
            self.decision['protected_files_before_after_sha256']['after'],
        )
        self.assertFalse(
            self.decision['holdout_boundary']['validation_consumed_by_this_decision']
        )
        self.assertEqual(
            self.decision['holdout_boundary']['split_consumed_by_the_preflight_v2'], 'TRAIN'
        )
        frozen = self.decision['frozen_inputs_untouched']
        self.assertEqual(tool.sha256_file(tool.HERE / tool.INDEX_NAME),
                         frozen['root_artifacts_sha256'])
        self.assertEqual(tool.sha256_file(tool.HERE / tool.SUMMARY_NAME),
                         frozen['root_summary_sha256'])
        self.assertEqual(tool.sha256_file(tool.spec_tool.SPEC_PATH),
                         frozen['hierarchical_model_spec_sha256'])
        self.assertEqual(tool.sha256_file(tool.PROTOCOL_V1_PATH),
                         frozen['frozen_validation_protocol_sha256'])
        self.assertEqual(tool.sha256_file(tool.HERE / tool.baseline_tool.BASELINE_NAME),
                         frozen['hierarchical_tree_sparsity_baseline_sha256'])
        self.assertEqual(tool.sha256_file(tool.legacy.REFERENCE),
                         frozen['active_reference_sha256'])
        self.assertEqual(tool.sha256_file(tool.V1_VALIDATION_RESULT_PATH),
                         frozen['v1_validation_result_sha256'])
        self.assertEqual(tool.sha256_file(tool.PREFLIGHT_V2_PATH),
                         frozen['exact_tree_preflight_v2_sha256'])
        # the frozen v1 decision and its record are byte-untouched by a v2 build
        self.assertEqual(tool.sha256_file(tool.BUNDLE / tool.DECISION_NAME),
                         frozen['v1_decision_sha256'])
        # the bundles still verify after the terminal v2 decision was written
        tool.verify_content_address(tool.HERE)
        tool.verify_content_address(tool.PREFLIGHT_V2_OUTPUT)

    # ------------------------------------------------------------- n8n block
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
        self.assertEqual(
            block['blockers'],
            [
                tool.BLOCK_NO_ADMISSIBLE_POOLING_LEVEL,
                tool.BLOCK_UNRESOLVED_RAISE_SIZING,
                tool.BLOCK_REFUSED_CALIBRATION,
                tool.BLOCK_REFUSED_COVERAGE_FLOOR,
            ],
        )
        self.assertEqual(block['validation_reference_sha256'], tool.V1_VALIDATION_RESULT_SHA256)
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
        self.assertIn(
            f'validation_reference_sha256: {tool.V1_VALIDATION_RESULT_SHA256}\n', rendered
        )
        self.assertIn(rendered.rstrip('\n'), self.summary)

    # ------------------------------------------------------------ determinism
    def test_deterministic_rebuild_matches_persisted_decision(self):
        decision, summary = tool.build()
        self.assertEqual(tool.serialize(decision), self.decision_bytes)
        self.assertEqual(summary.encode(), (self.bundle / tool.V2_SUMMARY_NAME).read_bytes())
        self.assertEqual(
            tool.render_n8n_block(decision['n8n_task_result']).encode(), self.n8n_bytes
        )
        self.assertEqual(tool.stable_hash(decision),
                         self.index[tool.V2_NAME]['canonical_payload_sha256'])

    def test_tool_cannot_run_issue367(self):
        self.assertEqual(tool.verify_no_issue367_runner()['result'], 'PASS')
        for source in (
            'from tools.simulation import run_issue367_real_iso_ev\n',
            'import run_issue367_real_iso_ev\n',
            'hero_recommendation = None\n',
        ):
            with self.subTest(source=source), self.assertRaises(tool.TerminalDecisionError):
                tool.verify_no_issue367_runner(source)

    def test_check_mode_and_revision_v1_are_pinned(self):
        self.assertEqual(tool.check(), 0)
        self.assertTrue(tool.DECISION_RECORD.exists())
        self.assertTrue(tool.V2_DECISION_RECORD.exists())
        v1_record = tool.DECISION_RECORD.read_text(encoding="utf-8")
        self.assertIn(tool.DECISION_UNRESOLVED, v1_record)
        self.assertIn('367', v1_record)
        v2_record = tool.V2_DECISION_RECORD.read_text(encoding="utf-8")
        self.assertIn(tool.DECISION_UNRESOLVED, v2_record)
        self.assertIn(tool.BLOCK_REFUSED_CALIBRATION, v2_record)
        self.assertIn(tool.V1_VALIDATION_RESULT_SHA256, v2_record)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(tool.main(['--revision', 'v1']), 2)
        self.assertIn('REFUSED_REVISION_V1', stderr.getvalue())
        self.assertEqual(tool.sha256_file(tool.BUNDLE / tool.DECISION_NAME),
                         tool.V1_DECISION_SHA256)


if __name__ == '__main__':
    unittest.main()
