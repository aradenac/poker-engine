import sys
import tempfile
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
LEGACY = "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1"
sys.path.insert(0, str(ROOT))
from tools.simulation.sequential_postflop import AnalyzerOracle, choose_variant, load_or_build_manifest


class OracleContractTests(unittest.TestCase):
    def test_zero_ev_beats_loss_without_best_label(self):
        detail = {'alternatives': [{'label': 'FOLD', 'evBB': 0}, {'label': 'CALL', 'evBB': -1}]}
        self.assertEqual(choose_variant(detail, 'current', 10)['label'], 'FOLD')

    def test_jam_filters_preserve_nonjam_action(self):
        detail = {'bestLabel': 'CALL', 'alternatives': [{'label': 'CALL', 'evBB': 2}]}
        for policy in ('jam_margin_1', 'weakjam_10'):
            self.assertEqual(choose_variant(detail, policy, 10)['label'], 'CALL')

    def test_unsupported_budget_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '1200'):
            AnalyzerOracle(engine_html=Path('unused'), preflop_model=Path('unused'),
                           postflop_model=Path('unused'), trials=50)

    def test_manifest_cannot_silently_change_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'scenarios.json'
            path.write_text(json.dumps({
                'schema': 'sequential-arena-scenario-manifest/v2',
                'population_id': LEGACY,
                'cache_namespace': LEGACY,
                'model_b': {'artifact_sha256': {'profiles': 'old'}},
            }))
            env = SimpleNamespace(
                population_id=LEGACY,
                artifact_fingerprints=lambda: {'profiles': 'new'},
            )
            args = SimpleNamespace(population=LEGACY, scenario_manifest=str(path))
            with self.assertRaisesRegex(ValueError, 'fingerprints'):
                load_or_build_manifest(args, env)

    def test_manifest_population_mismatch_is_rejected_before_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'scenarios.json'
            path.write_text(json.dumps({
                'schema': 'sequential-arena-scenario-manifest/v2',
                'population_id': 'other-population',
                'cache_namespace': 'other-population',
                'model_b': {'artifact_sha256': {'profiles': 'same'}},
            }))
            env = SimpleNamespace(
                population_id=LEGACY,
                artifact_fingerprints=lambda: {'profiles': 'same'},
            )
            args = SimpleNamespace(population=LEGACY, scenario_manifest=str(path))
            with self.assertRaisesRegex(ValueError, 'population mismatch'):
                load_or_build_manifest(args, env)


if __name__ == '__main__':
    unittest.main()
