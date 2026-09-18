"""Mandatory source integrity gate; missing archives must fail, never skip."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.datasets.build_hand_history_increment import (
    build_increment, fingerprint, read_archive, sha256_file,
)
from tools.training.audit_hero_preflop_coverage import (\n    audit as audit_hero_preflop_coverage, render_markdown as render_hero_preflop_coverage_markdown,\n)


class PersistedSnapshotTests(unittest.TestCase):
    def test_source_and_exact_increment(self):
        base = ROOT / 'training/datasets/NLHE_100-200'
        source = base / 'snapshots/20260912/source/RoiDePiqueNique.zip'
        self.assertEqual(sha256_file(source),
                         '374f8dedf5eeeee26b2cd049b1729f80bd2877c6f7ccef806c580019c5f94fcb')
        manifest, selected = build_increment(
            [base / 'source/NLHE 100-200.zip',
             base / 'snapshots/20260909/source/RoiDePiqueNique_training2.zip'],
            source, {'100/200'})
        self.assertEqual(manifest['candidate_archive']['unique_hands'], 11896)
        self.assertEqual(manifest['known_unique_hand_ids'], 27735)
        self.assertEqual(manifest['selected_unique_hands'], 3268)
        self.assertEqual(manifest['split_counts'],
                         {'TRAIN': 2606, 'VALIDATION': 320, 'TEST': 342})
        self.assertEqual(manifest['selected_hand_ids_fingerprint_sha256'],
                         '9eb753baed592b48d697ad6d00652612de6153e5033448f41983bccc9e31be2b')
        persisted = json.loads((base / 'increments/20260912/manifest.json').read_text())
        for key in ('selected_hand_ids', 'split_counts', 'candidate_hand_ids_fingerprint_sha256'):
            self.assertEqual(manifest[key], persisted[key], key)
        archive = base / 'increments/20260912/source/selected_100_200.zip'
        records, _ = read_archive(archive)
        self.assertEqual(len(records), 3268)
        self.assertEqual({r.hand_id: r.text for r in records},
                         {r.hand_id: r.text for r in selected})
        self.assertEqual(sha256_file(archive), persisted['output_zip']['sha256'])
        registry = json.loads((ROOT / 'training/registry.json').read_text())
        dataset = registry['datasets']['NLHE_100-200']
        self.assertEqual(dataset['latest_candidate_snapshot']['status'],
                         'source_verified_increment_materialized')
        self.assertIsNone(registry['pending_import'])

    def test_certified_train_only_hero_preflop_coverage_audit(self):
        report = audit_hero_preflop_coverage()
        self.assertEqual(report['scope']['split_consumed'], 'TRAIN')
        self.assertFalse(report['scope']['validation_consumed'])
        self.assertFalse(report['scope']['test_consumed'])
        self.assertFalse(report['scope']['strategy_generated'])
        self.assertFalse(report['scope']['ev_evaluated'])
        self.assertEqual(report['accounting']['train_hands_expected'], 19016)
        self.assertEqual(report['accounting']['train_hands_parsed'], 19016)
        self.assertEqual(report['accounting']['train_unique_hand_ids_parsed'], 19016)
        self.assertGreater(report['accounting']['targeted_population_preflop_decisions'], 0)
        self.assertTrue(report['matrix'])
        persisted_json = json.loads((ROOT / 'analysis/hero_preflop_coverage_train.json').read_text(encoding='utf-8'))
        self.assertEqual(report, persisted_json)
        persisted_md = (ROOT / 'analysis/hero_preflop_coverage_train.md').read_text(encoding='utf-8')
        self.assertEqual(render_hero_preflop_coverage_markdown(report), persisted_md)
        print('Hero preflop TRAIN coverage audit reproduced:', report['accounting'])


if __name__ == '__main__':
    unittest.main()
