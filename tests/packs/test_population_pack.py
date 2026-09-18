import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.build_population_pack import PackError, ROOT, build
from tools.population_pack_candidate import (
    BLOCKED_STATUS,
    CandidateContractError,
    assembly_binding,
    sha256_file,
    validate_candidate_contract,
)
from tools.validate_population_pack import REQUIRED_ROLES, validate
from tools.write_pack_catalog import build_catalog

CONFIG = ROOT / "user/packs/legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1/pack.json"
CANDIDATE = ROOT / "user/packs/pokerstars_nlhe_100-200_zoom_play_6max_v1/candidate.json"
TARGET_ZOOM = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
LEGACY_POPULATION = "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1"


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


    def test_zoom_candidate_is_explicitly_blocked_and_non_publishable(self):
        summary = validate_candidate_contract(CANDIDATE)
        self.assertEqual(summary["candidate_status"], BLOCKED_STATUS)
        self.assertEqual(summary["population_id"], TARGET_ZOOM)
        self.assertFalse(summary["ready_for_assembly"])
        self.assertTrue(summary["blockers"])
        self.assertTrue(all(value is False for value in summary["publication_policy"].values()))
        with self.assertRaisesRegex(CandidateContractError, "assembly remains blocked"):
            validate_candidate_contract(CANDIDATE, require_ready=True)
        with self.assertRaisesRegex(CandidateContractError, "blocked candidate"):
            assembly_binding(summary)

    def test_legacy_component_cannot_be_silently_relabelled_zoom_only(self):
        doc = copy.deepcopy(json.loads(CANDIDATE.read_text(encoding="utf-8")))
        legacy_engine_rel = "user/releases/poker_range_equity_offline_multiway_v83.html"
        legacy_engine = ROOT / legacy_engine_rel
        evidence_rel = "training/populations/registry.json"
        evidence = ROOT / evidence_rel
        doc["components"]["engine"] = {
            "role": "engine",
            "population_id": TARGET_ZOOM,
            "source_path": legacy_engine_rel,
            "hash_kind": "file_sha256",
            "sha256": sha256_file(legacy_engine),
            "provenance": {
                "source_population_id": TARGET_ZOOM,
                "evidence": {"path": evidence_rel, "sha256": sha256_file(evidence)},
            },
            "decision": {
                "status": "ADMISSIBLE_FOR_PACK",
                "issue": "#108",
                "evidence": {"path": evidence_rel, "sha256": sha256_file(evidence)},
            },
        }
        with tempfile.TemporaryDirectory(dir=ROOT / "tests/packs") as tmp:
            path = Path(tmp) / "candidate.json"
            path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
            summary = validate_candidate_contract(path)
        joined = "\n".join(summary["blockers"])
        self.assertIn("cannot be silently relabelled as target-scoped", joined)
        self.assertIn(LEGACY_POPULATION, joined)

    def test_scoped_promoted_archive_requires_ready_assembly_binding(self):
        manifest = {
            "schema": "poker-population-pack/v1",
            "coherency": "inseparable_population_pack",
            "population_status": "PROMOTED",
            "population_id": TARGET_ZOOM,
            "release": {"immutable": True},
        }
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "scoped.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("scoped/MANIFEST.json", json.dumps(manifest))
                zf.writestr("scoped/CHECKSUMS.sha256", "")
            with self.assertRaisesRegex(ValueError, "missing assembly_contract"):
                validate(str(archive))

    def test_blocked_zoom_candidate_is_not_in_browser_catalog(self):
        catalog = build_catalog()
        self.assertNotIn(TARGET_ZOOM, {entry["population_id"] for entry in catalog["entries"]})
        self.assertTrue(all(entry.get("recommended") is True for entry in catalog["entries"]))


if __name__ == "__main__":
    unittest.main()
