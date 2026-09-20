#!/usr/bin/env python3
"""#388 audit regressions. Synthetic records never become scientific evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.training import audit_model_a_exact_tree as audit


class ExactTreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = json.loads(audit.REFERENCE.read_text())
        cls.tree = audit.reconstruct_tree(cls.reference)
        cls.co = next(n for n in cls.tree['nodes'] if n['path'] == ['SB:ISO@5', 'BB:FOLD'])

    def report(self):
        return {
            'required_tree_sha256': audit.stable_hash(self.tree),
            'key_contract': copy.deepcopy(self.tree['key_contract']),
            'split_consumed': 'TRAIN', 'validation_consumed': False, 'test_consumed': False,
            'matrix': [{
                'node_id': n['id'],
                'audit_exact_key': n['audit_exact_key'],
                'runtime_support_context_key': n['runtime_support_context_key'],
                'runtime_exact_preflop_node_key': n['runtime_exact_preflop_node_key'],
                'audit_exact_support': {'observations': 0, 'distinct_hands': 0},
                'runtime_support_context_support': {
                    'observations': 0, 'distinct_hands': 0, 'qualifies': False,
                },
            } for n in self.tree['nodes']],
        }

    def test_deterministic_tree_and_canonical_co(self):
        self.assertEqual(self.tree, audit.reconstruct_tree(self.reference))
        self.assertIn(
            'family=LIMPER_VS_ISO|actor=CO|aggressor=SB|limpers=2|callers=0|target=5|call=4',
            self.co['runtime_support_context_key'],
        )
        self.assertEqual(self.co['context']['effective_stack_bucket'], 'GT75_LE125')
        ids = {x['id'] for x in self.tree['nodes'] + self.tree['terminals']}
        for node in self.tree['nodes']:
            self.assertEqual({e['action'] for e in node['edges']}, {*audit.ACTIONS, 'CHECK'})
            for edge in node['edges']:
                if edge['state'] == 'REACHABLE':
                    self.assertIn(edge['child_id'], ids)
        # BB CALL has zero observed exact support but is still expanded.
        self.assertTrue(any(n['path'] == ['SB:ISO@5', 'BB:CALL', 'CO:CALL'] for n in self.tree['nodes']))
        self.assertTrue(self.tree['unresolved_sizing_frontiers'])
        self.assertFalse(self.tree['enumeration_complete'])

    def test_every_public_mismatch_is_distinct_no_nearest_substitution(self):
        ctx = self.co['context']
        variants = {'aggressor_position': 'BTN', 'limper_count': 1, 'caller_count': 1,
                    'target_total_bb': 4, 'to_call_bb': 3, 'effective_stack_bucket': 'GT125',
                    'live_positions': ['CO', 'SB'], 'pot_before_bb': 9, 'actor_position': 'BTN'}
        for field, value in variants.items():
            with self.subTest(field=field):
                self.assertNotEqual(audit.exact_key(ctx), audit.exact_key({**ctx, field: value}))
        self.assertNotEqual(audit.exact_key(ctx), audit.exact_key({**ctx, 'target_total_bb': 6}))
        # The implemented likelihood key is narrower, but price/context fields in its contract stay exact.
        for field in ('aggressor_position', 'limper_count', 'caller_count',
                      'target_total_bb', 'to_call_bb', 'actor_position'):
            self.assertNotEqual(
                audit.support_context_key(ctx),
                audit.support_context_key({**ctx, field: variants[field]}),
            )

    def test_future_and_private_information_cannot_change_context_or_tree(self):
        ctx = self.co['context']
        raw = {**ctx, 'effective_stack_bb': 100}
        baseline = audit.public_context(raw)
        for fields in ({'known_cards': ['As', 'Ah'], 'known_hand_class': 'AA'},
                       {'board': ['As', 'Ks', 'Qs'], 'future_actions': ['JAM']},
                       {'hero_hole_cards': ['7c', '2d']}):
            self.assertEqual(baseline, audit.public_context({**raw, **fields}))

    def test_zero_support_and_incomplete_tree_cannot_admit(self):
        report = self.report()
        result = audit.decide(self.tree, report)
        self.assertEqual(result['decision'], 'UNRESOLVED_EXACT_TREE_GAP')
        self.assertFalse(result['required_tree_complete'])
        self.assertTrue(all(x['reason'] == 'ZERO_RUNTIME_SUPPORT_CONTEXT' for x in result['blockers']))
        report['matrix'].pop()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            audit.decide(self.tree, report)

    def test_support_threshold_and_unresolved_sizing_frontier(self):
        report = self.report()
        for row in report['matrix']:
            row['runtime_support_context_support'].update(
                observations=20, distinct_hands=20, qualifies=True,
            )
        report['matrix'][0]['runtime_support_context_support'].update(
            distinct_hands=19, qualifies=False,
        )
        result = audit.decide(self.tree, report)
        self.assertEqual(len(result['blockers']), 1)
        report['matrix'][0]['runtime_support_context_support'].update(
            distinct_hands=20, qualifies=True,
        )
        result = audit.decide(self.tree, report)
        self.assertEqual(result['blockers'], [])
        self.assertFalse(result['required_tree_complete'])
        self.assertTrue(result['unresolved_sizing_frontiers'])
        report['matrix'][0]['runtime_support_context_support']['qualifies'] = False
        with self.assertRaisesRegex(ValueError, 'qualification/count mismatch'):
            audit.decide(self.tree, report)

    def test_no_admission_path_even_with_synthetic_complete_support(self):
        tree = copy.deepcopy(self.tree)
        tree['unresolved_sizing_frontiers'] = []
        report = self.report()
        report['required_tree_sha256'] = audit.stable_hash(tree)
        for row in report['matrix']:
            row['runtime_support_context_support'].update(
                observations=20, distinct_hands=20, qualifies=True,
            )
        with self.assertRaisesRegex(ValueError, 'audit cannot admit'):
            audit.decide(tree, report)

    def test_train_validation_test_boundary_before_parser(self):
        for split in ('VALIDATION', 'TEST'):
            with self.subTest(split=split), patch.object(audit, 'split_for', return_value=split), patch.object(audit, 'parse_hand') as parser:
                with self.assertRaisesRegex(ValueError, 'before parser'):
                    audit.audit_train(self.tree, [SimpleNamespace(hand_id='123')], {})
                parser.assert_not_called()
        for field in ('validation_consumed', 'test_consumed'):
            report = self.report()
            report[field] = True
            with self.assertRaisesRegex(ValueError, 'holdout'):
                audit.decide(self.tree, report)

    def test_exact_recount_does_not_borrow_neighbor_context(self):
        ctx = self.co['context']
        row = {**ctx, 'effective_stack_bb': 100, 'split': 'TRAIN', 'street': 'preflop',
               'is_hero': False, 'hand_id': '123', 'action': 'CALL', 'known_hand_class': 'KTs'}
        neighbors = [{**row, 'current_price_bb': price} for price in (4, 6)]
        neighbors += [{**row, 'pot_before_bb': 9}, {**row, 'effective_stack_bb': 200}]
        with patch.object(audit, 'split_for', return_value='TRAIN'), patch.object(audit, 'parse_hand', return_value={'id': '123'}), patch.object(audit, 'decision_rows', return_value=[row, *neighbors]):
            report = audit.audit_train(self.tree, [SimpleNamespace(hand_id='123', text='', source_file='synthetic')], {'certified_split_counts': {'TRAIN': 1}})
        co = next(c for c in report['matrix'] if c['node_id'] == self.co['id'])
        self.assertEqual(co['audit_exact_support']['observations'], 1)
        self.assertEqual(co['audit_exact_support']['distinct_hands'], 1)
        self.assertEqual(co['audit_exact_support']['hand_classes']['KTs']['observations'], 1)
        self.assertFalse(co['audit_exact_support']['qualifies'])
        # Same runtime key merges the pot and stack variants, but never the 4/6 prices.
        self.assertEqual(co['runtime_support_context_support']['observations'], 3)
        self.assertEqual(co['runtime_exact_preflop_node_support']['observations'], 5)

    def test_support_state_classification(self):
        self.assertEqual(audit.classify(audit.summarize([])), 'ZERO_EXACT_SUPPORT')
        row = {'hand_id': '123', 'action': 'FOLD'}
        self.assertEqual(audit.classify(audit.summarize([row])), 'EXACT_MARGINAL_ONLY')
        row['known_hand_class'] = 'KTs'
        self.assertEqual(audit.classify(audit.summarize([row])), 'EXACT_OBSERVED')

    def test_candidate_identity_and_hash_fail_closed(self):
        fit = json.loads((ROOT / 'analysis/model_a_preflop_sizing_v2_fit.json').read_text())
        audit.verify_baseline(fit)
        for field in ('id', 'sha', 'payload'):
            broken = copy.deepcopy(fit)
            if field == 'id':
                broken['candidate_identity']['candidate_id'] = 'invented'
            elif field == 'sha':
                broken['candidate_sha256'] = '0' * 64
            else:
                broken['nodes']['total'] += 1
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                audit.verify_baseline(broken)

    def test_artifact_content_addresses_and_requirement_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            audit.persist(path, {'REQUIRED_EXACT_TREE.json': self.tree}, 'summary\n')
            index = json.loads((path / 'ARTIFACTS.json').read_text())
            for name, entry in index.items():
                data = (path / name).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'])
                self.assertEqual(data, (path / entry['object']).read_bytes())
            self.assertEqual(
                {p.name for p in (path / 'sha256').iterdir()},
                {Path(entry['object']).name for entry in index.values()},
            )
        report = self.report()
        report['required_tree_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            audit.decide(self.tree, report)

    def test_persisted_real_train_evidence_and_protected_hashes(self):
        index = json.loads((audit.OUTPUT / 'ARTIFACTS.json').read_text())
        for name, entry in index.items():
            data = (audit.OUTPUT / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'])
            self.assertEqual(data, (audit.OUTPUT / entry['object']).read_bytes())
        self.assertEqual(
            {p.name for p in (audit.OUTPUT / 'sha256').iterdir()},
            {Path(entry['object']).name for entry in index.values()},
        )
        tree = json.loads((audit.OUTPUT / 'REQUIRED_EXACT_TREE.json').read_text())
        report = json.loads((audit.OUTPUT / 'TRAIN_RESPONSE_TREE_SUPPORT.json').read_text())
        decision = json.loads((audit.OUTPUT / 'DECISION.json').read_text())
        self.assertEqual(tree, self.tree)
        self.assertEqual(audit.decide(tree, report)['blockers'], decision['blockers'])
        self.assertEqual(report['train_hands_parsed'], 19016)
        self.assertEqual(len(report['issue319_coarse_diagnostics_not_exact_support']), 30)
        self.assertTrue(any(
            cell['observations'] == 0
            for cell in report['issue319_coarse_diagnostics_not_exact_support'].values()
        ))
        self.assertEqual(decision['canonical_bb_runtime_observations'], 45)
        self.assertEqual(decision['canonical_bb_audit_exact_observations'], 6)
        self.assertEqual(decision['canonical_co_coarse_observations'], 14)
        self.assertEqual(decision['canonical_co_exact_observations'], 4)
        self.assertEqual(decision['runtime_support_context_qualified_node_count'], 3)
        self.assertEqual(len(decision['runtime_support_context_qualified_nodes']), 3)
        self.assertEqual(
            decision['runtime_resolution_risks_for_367'][0]['risk_id'],
            'RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE',
        )
        for field in ('validation_consumed', 'test_consumed', 'active_pointer_mutated', 'hero_ev_executed'):
            self.assertFalse(decision[field])
        self.assertIsNone(decision['candidate_id'])
        self.assertIsNone(decision['hero_recommendation'])
        for name, digest in {**decision['source_files_sha256'], **decision['protected_files_before_after_sha256']}.items():
            self.assertEqual(audit.sha256_file(ROOT / name), digest, name)


if __name__ == '__main__':
    unittest.main()
