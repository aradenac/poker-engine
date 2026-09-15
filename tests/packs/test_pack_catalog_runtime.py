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
from tools.write_pack_catalog import CATALOG_SCHEMA, RUNTIME_SCHEMA, SITE, build_catalog  # noqa: E402


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
