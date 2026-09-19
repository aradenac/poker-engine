from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "audit/pack-loader-identity-duplication.json"
PARITY = ROOT / "tests/fixtures/packs/pack_identity_parity_v1.json"


class PackIdentityExtractionTests(unittest.TestCase):
    def test_audit_justifies_only_targeted_extraction(self):
        audit = json.loads(AUDIT.read_text(encoding="utf-8"))
        self.assertEqual(audit["schema"], "poker-pack-loader-identity-audit/v1")
        self.assertTrue(audit["extraction"]["justified"])
        self.assertEqual(
            audit["extraction"]["real_consumers"],
            ["site/population-packs.js", "site/manual-import.js"],
        )
        decisions = {
            row["responsibility"]: row["decision"]
            for row in audit["measured_duplication"]["responsibility_overlap"]
        }
        self.assertEqual(decisions["content_sha256"], "EXTRACT")
        self.assertEqual(decisions["pack_population_identity"], "EXTRACT_PARITY_BOUNDARY")
        self.assertEqual(decisions["indexeddb_open"], "KEEP_SEPARATE")
        self.assertEqual(decisions["role_schema_validation"], "KEEP_SEPARATE")
        self.assertEqual(decisions["compatibility_validation"], "KEEP_CONSUMER_SPECIFIC")

    def test_shared_module_is_loaded_before_both_consumers(self):
        packs = (ROOT / "site/packs.html").read_text(encoding="utf-8")
        manual = (ROOT / "site/manual-import.html").read_text(encoding="utf-8")
        for html in (packs, manual):
            self.assertLess(
                html.index('./pack-identity.js'),
                html.index('./population-packs.js'),
            )
        self.assertLess(
            manual.index('./population-packs.js'),
            manual.index('./manual-import.js'),
        )

    def test_identity_primitives_are_shared_without_merging_storage_or_role_policy(self):
        shared = (ROOT / "site/pack-identity.js").read_text(encoding="utf-8")
        packs = (ROOT / "site/population-packs.js").read_text(encoding="utf-8")
        manual = (ROOT / "site/manual-import.js").read_text(encoding="utf-8")

        for symbol in ("contentIdentity", "storageId", "packIdentity", "samePackIdentity"):
            self.assertIn(symbol, shared)
        self.assertNotIn("function bytes(value)", packs)
        self.assertNotIn("function hex(buffer)", packs)
        self.assertNotIn("function storageId(entry)", packs)
        self.assertNotIn("function packIdentity(record)", manual)
        self.assertNotIn("function samePackIdentity(a,b)", manual)

        # Deliberately consumer-specific responsibilities stay local.
        self.assertIn("function openDb()", packs)
        self.assertIn("function openDb()", manual)
        self.assertIn("function validateEntry(", packs)
        self.assertIn("function validatePreflop(", manual)
        self.assertIn("function validatePostflop(", manual)

    def test_release_identity_tracks_shared_static_module(self):
        release = (ROOT / "tools/write_site_release.py").read_text(encoding="utf-8")
        self.assertIn('ROOT / "site" / "pack-identity.js"', release)

    def test_parity_fixture_is_versioned_and_complete(self):
        fixture = json.loads(PARITY.read_text(encoding="utf-8"))
        self.assertEqual(fixture["schema"], "poker-pack-identity-parity/v1")
        self.assertGreaterEqual(len(fixture["sha256_vectors"]), 2)
        self.assertIn("expected", fixture["storage_id"])
        self.assertIn("expected", fixture["active_record"])
        self.assertGreaterEqual(len(fixture["same_identity_cases"]), 3)


if __name__ == "__main__":
    unittest.main()
