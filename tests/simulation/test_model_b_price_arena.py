#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.model_b_price_arena import (  # noqa: E402
    PriceResponseArenaEnvironment,
    retarget_manifest,
)
from tools.simulation.model_b_price_response import build_response_artifact  # noqa: E402
from tools.simulation.model_b_runtime import ModelBEnvironment  # noqa: E402

BASE = ROOT / "training/runs/20260912_independent_profiles_v2/model"
POPULATION = "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1"


def observation(action: str, *, sizing=None):
    row = {
        "profile": 0,
        "street": "flop",
        "relative_position": "OOP",
        "pot_type": "SRP",
        "sequence": "BET",
        "facing_price_to_pot": 0.5,
        "spr": 3.0,
        "action": action,
    }
    if sizing is not None:
        row["raise_sizing_ratio"] = sizing
    return row


class PriceArenaTests(unittest.TestCase):
    def make_dir(self, root: Path) -> Path:
        candidate = root / "model"
        candidate.mkdir()
        rows = []
        rows += [observation("FOLD") for _ in range(20)]
        rows += [observation("CALL") for _ in range(20)]
        rows += [observation("RAISE", sizing=1.2 + i * 0.01) for i in range(20)]
        artifact = build_response_artifact(
            rows,
            min_support=10,
            sizing_min_support=10,
        )
        (candidate / "response_to_price.json").write_text(
            json.dumps(artifact), encoding="utf-8"
        )
        (candidate / "arena_config.json").write_text(json.dumps({
            "schema": "model-b-response-to-price-arena-config/v1",
            "base_model_dir": BASE.relative_to(ROOT).as_posix(),
            "population_id": POPULATION,
            "response_artifact": "response_to_price.json",
            "production_effect": "NONE",
        }), encoding="utf-8")
        return candidate

    def test_candidate_keeps_scenario_materialization_dependencies(self):
        with tempfile.TemporaryDirectory() as td:
            candidate = self.make_dir(Path(td))
            source = ModelBEnvironment(BASE, alias="reference", population_id=POPULATION)
            target = PriceResponseArenaEnvironment(candidate, population_id=POPULATION)
            source_fp = source.artifact_fingerprints()
            target_fp = target.artifact_fingerprints()
            self.assertEqual(source_fp["profiles.json"], target_fp["profiles.json"])
            self.assertEqual(source_fp["preflop_ranges.json"], target_fp["preflop_ranges.json"])
            self.assertIn("response_to_price.json", target_fp)

            manifest = {
                "schema": "sequential-arena-scenario-manifest/v2",
                "population_id": POPULATION,
                "model_b": {
                    "alias": source.alias,
                    "model_dir": BASE.as_posix(),
                    "artifact_sha256": source_fp,
                },
                "scenario_fingerprint_sha256": "fixture",
                "scenarios": [],
            }
            retargeted = retarget_manifest(manifest, source, target)
            self.assertEqual(
                retargeted["scenario_fingerprint_sha256"],
                manifest["scenario_fingerprint_sha256"],
            )
            self.assertTrue(
                retargeted["scenario_materialization_provenance"]["scenario_fingerprint_unchanged"]
            )

    def test_uncertainty_variants_are_unweighted_local_response_stresses(self):
        with tempfile.TemporaryDirectory() as td:
            candidate = self.make_dir(Path(td))
            old = os.environ.get("MODEL_B_RESPONSE_VARIANT")
            try:
                values = {}
                for variant in ("fold_low", "nominal", "fold_high"):
                    os.environ["MODEL_B_RESPONSE_VARIANT"] = variant
                    env = PriceResponseArenaEnvironment(candidate, population_id=POPULATION)
                    probs = env._response_probabilities(
                        profile=0,
                        street="flop",
                        relative_position="OOP",
                        pot_type="SRP",
                        sequence="BET",
                        facing_price_to_pot=0.5,
                        spr=3.0,
                        can_raise=True,
                    )
                    self.assertAlmostEqual(sum(probs.values()), 1.0, places=12)
                    values[variant] = probs["FOLD"]
                self.assertLess(values["fold_low"], values["nominal"])
                self.assertLess(values["nominal"], values["fold_high"])
            finally:
                if old is None:
                    os.environ.pop("MODEL_B_RESPONSE_VARIANT", None)
                else:
                    os.environ["MODEL_B_RESPONSE_VARIANT"] = old

    def test_facing_raise_sizing_comes_from_response_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            candidate = self.make_dir(Path(td))
            env = PriceResponseArenaEnvironment(candidate, population_id=POPULATION)
            size = env.sample_sizing(
                seed_parts=("fixture",),
                profile=0,
                street="flop",
                mode="FACING",
                action="RAISE",
                pot_type="SRP",
                relative_position="OOP",
                facing_price_to_pot=0.5,
                spr=3.0,
                sequence="BET",
            )
            self.assertGreaterEqual(size, 1.2)
            self.assertLessEqual(size, 1.39)


if __name__ == "__main__":
    unittest.main()
