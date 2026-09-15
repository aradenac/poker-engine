import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.build_population_pack import PackError, ROOT, build
from tools.validate_population_pack import REQUIRED_ROLES, validate

CONFIG = ROOT / "user/packs/legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1/pack.json"
TARGET_ZOOM = "pokerstars_nlhe_100-200_zoom_play_6max_v1"


class PopulationPackTests(unittest.TestCase):
    def test_build_is_reproducible_complete_and_self_validating(self):
        old = os.environ.get("PACK_SOURCE_COMMIT")
        os.environ["PACK_SOURCE_COMMIT"] = "1" * 40
        try:
            with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
                zip_a = build(CONFIG, Path(a))
                zip_b = build(CONFIG, Path(b))
                self.assertEqual(zip_a.read_bytes(), zip_b.read_bytes())
                manifest = validate(str(zip_a))
                self.assertEqual(manifest["schema"], "poker-population-pack/v1")
                self.assertEqual(manifest["population_status"], "PROMOTED_LEGACY")
                self.assertEqual(
                    manifest["population_id"],
                    "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1",
                )
                roles = {role for item in manifest["artifacts"] for role in item["roles"]}
                self.assertTrue(REQUIRED_ROLES.issubset(roles))
                model_b = [item for item in manifest["artifacts"] if "model_b" in item["roles"]]
                self.assertEqual(len(model_b), 5)
                shared = [
                    item for item in manifest["artifacts"]
                    if {"engine", "hero_strategy"}.issubset(item["roles"])
                ]
                self.assertEqual(len(shared), 1, "identical engine/strategy bytes must be deduplicated")
                with zipfile.ZipFile(zip_a) as zf:
                    names = zf.namelist()
                    self.assertFalse(any("training/datasets/" in name for name in names))
                    self.assertFalse(any(name.lower().endswith(".zip") for name in names))
                    self.assertTrue(any(name.endswith("/hero/custom.json") for name in names))
                    self.assertTrue(any(name.endswith("/application/RELEASE.json") for name in names))
        finally:
            if old is None:
                os.environ.pop("PACK_SOURCE_COMMIT", None)
            else:
                os.environ["PACK_SOURCE_COMMIT"] = old

    def test_data_only_population_cannot_be_distributed_as_complete_pack(self):
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(PackError, "CERTIFIED_DATA_ONLY"):
                build(CONFIG, Path(out), population_override=TARGET_ZOOM)

    def test_release_contract_is_versioned_and_immutable(self):
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(cfg["schema"], "poker-population-pack-config/v1")
        self.assertRegex(cfg["pack_version"], r"^\d{4}\.\d{2}\.\d{2}\.\d+$")
        self.assertTrue(cfg["release_tag"].startswith("poker-pack-"))


if __name__ == "__main__":
    unittest.main()
