from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "audit/pack-cache-storage-identity.json"
FIXTURE = ROOT / "tests/fixtures/packs/pack_storage_identity_parity_v1.json"


class PackStorageIdentityTests(unittest.TestCase):
    def test_audit_proves_two_real_consumers_before_extraction(self):
        audit = json.loads(AUDIT.read_text(encoding="utf-8"))
        self.assertEqual(audit["schema"], "poker-pack-cache-storage-identity-audit/v1")
        self.assertEqual(
            audit["extraction"]["real_consumers"],
            ["site/population-packs.js", "site/population-pack-sw.js"],
        )
        duplicated = audit["measured_before_extraction"]["exact_duplicated_storage_literals"]
        self.assertGreaterEqual(len(duplicated), 7)
        decisions = {
            row["responsibility"]: row["decision"]
            for row in audit["measured_before_extraction"]["duplicated_responsibilities"]
        }
        self.assertEqual(decisions["indexeddb namespace identity"], "EXTRACT")
        self.assertEqual(decisions["active production pointer location"], "EXTRACT")
        self.assertEqual(decisions["IndexedDB transaction implementation"], "KEEP_SEPARATE")
        self.assertEqual(decisions["request interception/cache serving"], "KEEP_LOCAL")

    def test_storage_contract_is_shared_by_runtime_and_service_worker(self):
        shared = (ROOT / "site/pack-identity.js").read_text(encoding="utf-8")
        runtime = (ROOT / "site/population-packs.js").read_text(encoding="utf-8")
        sw = (ROOT / "site/population-pack-sw.js").read_text(encoding="utf-8")

        for symbol in ("STORAGE_CONTRACT", "storageNamespace", "storageAddress"):
            self.assertIn(symbol, shared)
        self.assertIn("globalThis", shared)
        self.assertIn("storageNamespace(false)", runtime)
        self.assertIn("storageNamespace(true)", runtime)
        self.assertIn('importScripts("./pack-identity.js")', sw)
        self.assertIn("storageNamespace(false)", sw)

        # Shared storage identity is no longer copied into either consumer.
        for literal in (
            '"poker-population-packs-v1"',
            '"test_packs"',
            '"test_meta"',
        ):
            self.assertNotIn(literal, runtime)
            self.assertNotIn(literal, sw)

    def test_service_worker_remains_production_only(self):
        sw = (ROOT / "site/population-pack-sw.js").read_text(encoding="utf-8")
        self.assertIn("PROD_STORAGE.pack_store", sw)
        self.assertIn("PROD_STORAGE.meta_store", sw)
        self.assertIn("PROD_STORAGE.active_key", sw)
        self.assertNotIn("TEST_STORAGE.active_key", sw)
        self.assertNotIn("testActive", sw)

    def test_parity_fixture_covers_legacy_zoom_version_revision_and_test_namespace(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(fixture["schema"], "poker-pack-storage-identity-parity/v1")
        entries = fixture["entries"]
        self.assertNotEqual(entries["legacy"]["population_id"], entries["zoom"]["population_id"])
        self.assertNotEqual(entries["zoom"]["pack_version"], entries["zoom_next_version"]["pack_version"])
        self.assertNotEqual(entries["zoom"]["runtime_revision"], entries["zoom_next_revision"]["runtime_revision"])
        prod = fixture["expected"]["production_namespace"]
        test = fixture["expected"]["test_only_namespace"]
        self.assertEqual(prod["db_name"], test["db_name"])
        self.assertNotEqual(prod["pack_store"], test["pack_store"])
        self.assertNotEqual(prod["meta_store"], test["meta_store"])
        self.assertNotEqual(prod["active_key"], test["active_key"])


if __name__ == "__main__":
    unittest.main()
