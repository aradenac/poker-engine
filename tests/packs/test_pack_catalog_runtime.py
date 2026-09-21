#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.patches.apply_pack_manager_link import patch_text  # noqa: E402
from tools.write_pack_catalog import (  # noqa: E402
    CATALOG_SCHEMA,
    RUNTIME_SCHEMA,
    SITE,
    build_catalog,
    hero_provenance,
)


class PackCatalogContractTests(unittest.TestCase):
    def test_catalog_is_deterministic_and_complete(self) -> None:
        left = build_catalog()
        right = build_catalog()
        self.assertEqual(left, right)
        self.assertEqual(left["schema"], CATALOG_SCHEMA)
        self.assertEqual(len(left["entries"]), 1)
        entry = left["entries"][0]
        self.assertEqual(entry["schema"], RUNTIME_SCHEMA)
        self.assertEqual(entry["population_id"], "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1")
        self.assertEqual(entry["engine_version"], "v83")
        self.assertTrue(entry["recommended"])
        required = {
            "population_manifest",
            "model_a_preflop",
            "model_a_postflop",
            "model_b_profiles",
            "model_b_ranges",
            "model_b_actions",
            "model_b_sizing",
            "model_b_contract",
            "hero_ranges",
        }
        self.assertEqual({x["key"] for x in entry["assets"]}, required)

    def test_catalog_assets_are_same_origin_and_content_addressed(self) -> None:
        entry = build_catalog()["entries"][0]
        for asset in entry["assets"]:
            self.assertTrue(asset["url"].startswith("./"), asset)
            self.assertNotIn("training/", asset["url"])
            self.assertNotIn("datasets", asset["url"].lower())
            self.assertNotIn("hand", asset["url"].lower())
            path = SITE / asset["url"][2:]
            self.assertTrue(path.is_file(), path)
            payload = path.read_bytes()
            self.assertEqual(asset["size_bytes"], len(payload))
            self.assertEqual(asset["sha256"], hashlib.sha256(payload).hexdigest())
        fingerprint = json.dumps(
            [{k: row[k] for k in ("key", "sha256", "size_bytes")} for row in entry["assets"]],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        self.assertEqual(entry["runtime_revision"], hashlib.sha256(fingerprint).hexdigest())

    def test_catalog_carries_the_population_bound_retained_hero_provenance(self) -> None:
        entry = build_catalog()["entries"][0]
        manifest = json.loads((SITE / "assets/trainer/population.json").read_text(encoding="utf-8"))
        provenance = entry["hero_provenance"]
        self.assertEqual(provenance, manifest["hero_provenance"])
        self.assertEqual(provenance["population_id"], entry["population_id"])
        self.assertEqual(provenance["strategy_id"], entry["hero_strategy"])
        self.assertEqual(provenance["source"]["folder"], "Custom")
        self.assertEqual(provenance["source"]["export_type"], "range-folder")
        self.assertEqual(provenance["ranges_path"], manifest["assets"]["hero"]["ranges"])
        self.assertIn(provenance["status"], ("RETAIN_REFERENCE", "PARTIAL"))
        self.assertEqual(provenance["coverage_status"], "PARTIAL")
        self.assertIs(provenance["admissible"], False)
        self.assertIs(provenance["promotable"], False)
        self.assertNotEqual(entry["hero_strategy"], "Custom")
        self.assertNotIn("zoom", provenance["population_id"])
        hero_asset = next(asset for asset in entry["assets"] if asset["key"] == "hero_ranges")
        self.assertEqual(provenance["sha256"], hero_asset["sha256"])

    def test_retained_hero_provenance_carries_the_null_admission_binding(self) -> None:
        entry = build_catalog()["entries"][0]
        manifest = json.loads((SITE / "assets/trainer/population.json").read_text(encoding="utf-8"))
        provenance = entry["hero_provenance"]
        self.assertEqual(provenance, manifest["hero_provenance"])
        # #task-0jt: the retained reference exposes the explicit binding tokens as
        # null so the runtime never fabricates a candidate identity or a hash.
        for field in ("candidate_id", "generation_id", "binding_sha256"):
            self.assertIn(field, provenance)
            self.assertIsNone(provenance[field])
        self.assertEqual(provenance["status"], "RETAIN_REFERENCE")

    def test_retained_hero_provenance_cannot_fabricate_a_candidate_binding(self) -> None:
        manifest = json.loads((SITE / "assets/trainer/population.json").read_text(encoding="utf-8"))
        fabricated_binding = json.loads(json.dumps(manifest))
        fabricated_binding["hero_provenance"]["binding_sha256"] = "a" * 64
        with self.assertRaises(ValueError):
            hero_provenance(fabricated_binding)
        fabricated_candidate = json.loads(json.dumps(manifest))
        fabricated_candidate["hero_provenance"]["candidate_id"] = "hero-candidate-196"
        with self.assertRaises(ValueError):
            hero_provenance(fabricated_candidate)
        fabricated_generation = json.loads(json.dumps(manifest))
        fabricated_generation["hero_provenance"]["generation_id"] = "gen-196"
        with self.assertRaises(ValueError):
            hero_provenance(fabricated_generation)

    def test_hero_provenance_rejects_relabel_and_admissibility_drift(self) -> None:
        manifest = json.loads((SITE / "assets/trainer/population.json").read_text(encoding="utf-8"))

        relabelled_population = json.loads(json.dumps(manifest))
        relabelled_population["hero_provenance"]["population_id"] = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
        with self.assertRaises(ValueError):
            hero_provenance(relabelled_population)

        relabelled_folder = json.loads(json.dumps(manifest))
        relabelled_folder["hero_provenance"]["source"]["folder"] = "Zoom"
        with self.assertRaises(ValueError):
            hero_provenance(relabelled_folder)

        admissible = json.loads(json.dumps(manifest))
        admissible["hero_provenance"]["admissible"] = True
        with self.assertRaises(ValueError):
            hero_provenance(admissible)

        stale_hash = json.loads(json.dumps(manifest))
        stale_hash["hero_provenance"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            hero_provenance(stale_hash)

    def test_distribution_and_runtime_population_identity_agree(self) -> None:
        entry = build_catalog()["entries"][0]
        self.assertEqual(entry["source_release"]["pack_id"], entry["pack_id"])
        self.assertEqual(entry["source_release"]["tag"], entry["release_tag"])
        self.assertEqual(entry["compatibility"]["engine_version"], entry["engine_version"])
        self.assertEqual(entry["compatibility"]["activation_policy"], "all_assets_valid_then_atomic_switch")

    def test_navigation_patch_is_idempotent(self) -> None:
        source = '<nav><a href="./hero-ranges.html">Ranges Hero</a></nav>'
        once = patch_text(source)
        twice = patch_text(once)
        self.assertEqual(once, twice)
        self.assertEqual(once.count('href="./packs.html"'), 1)


if __name__ == "__main__":
    unittest.main()
