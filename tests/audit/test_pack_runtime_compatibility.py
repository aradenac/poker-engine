#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.audit_pack_runtime_compatibility import (
    APPLICATION_RELEASE_PATH,
    ENGINE_PATH,
    EVIDENCE_PATH,
    EXPECTED_APP_BLOCKERS,
    EXPECTED_ENGINE_BLOCKER,
    PROVENANCE_PATH,
    ROOT,
    TARGET,
    RuntimeCompatibilityError,
    audit,
    validate_source_provenance,
)
from tools.population_pack_admission import resolve_admission
from tools.population_pack_candidate import sha256_file


class PackRuntimeCompatibilityTests(unittest.TestCase):
    def _load(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_temp_evidence(self, doc: dict) -> Path:
        tmp = tempfile.TemporaryDirectory(dir=ROOT / "tests/packs")
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "evidence.json"
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        return path

    def test_fresh_runtime_provenance_hashes_and_blockers(self):
        provenance = self._load(PROVENANCE_PATH)
        engine = self._load(ENGINE_PATH)
        app = self._load(APPLICATION_RELEASE_PATH)
        proof = validate_source_provenance(provenance, engine, app)
        self.assertGreaterEqual(proof["generic_files_verified"], 8)
        self.assertEqual(proof["engine_blocker"], EXPECTED_ENGINE_BLOCKER)
        self.assertEqual(set(proof["application_blockers"]), EXPECTED_APP_BLOCKERS)
        self.assertFalse(engine["compatibility"]["pack_role_admissible"])
        self.assertFalse(app["compatibility"]["pack_role_admissible"])
        self.assertFalse(app["published"])
        self.assertEqual(app["status"], "candidate_unpublished")

    def test_resolver_305_consumes_fresh_evidence_fail_closed(self):
        resolution = resolve_admission(
            EVIDENCE_PATH,
            expected_population_id=TARGET,
        )
        self.assertEqual(resolution["admissions"]["engine"]["status"], "UNRESOLVED")
        self.assertEqual(
            resolution["admissions"]["application_release"]["status"],
            "UNRESOLVED",
        )
        self.assertIsNone(resolution["candidate_contract"]["components"]["engine"])
        self.assertIsNone(
            resolution["candidate_contract"]["components"]["application_release"]
        )
        self.assertEqual(
            resolution["candidate_contract"]["candidate_status"],
            "BLOCKED_PENDING_SCIENTIFIC_DECISION",
        )
        self.assertFalse(resolution["safety"]["promotion"])
        self.assertFalse(resolution["safety"]["release_publication"])

    def test_full_audit_is_deterministic_and_read_only(self):
        first = audit()
        second = audit()
        self.assertEqual(first, second)
        self.assertEqual(first["roles"]["engine"]["status"], "UNRESOLVED")
        self.assertEqual(first["roles"]["application_release"]["status"], "UNRESOLVED")
        self.assertEqual(first["preflight"]["result"], "BLOCKED")
        self.assertEqual(first["preflight"]["engine_compatibility"], "BLOCKED")
        self.assertFalse(first["preflight"]["writes_performed"])
        self.assertFalse(first["boundaries"]["test_consumed"])
        self.assertEqual(first["boundaries"]["production_effect"], "NONE")
        self.assertTrue(first["boundaries"]["parent_201_remains_open"])

    def test_legacy_relabel_is_still_rejected(self):
        evidence = self._load(EVIDENCE_PATH)
        legacy = "user/releases/poker_range_equity_offline_multiway_v83.html"
        engine = evidence["components"]["engine"]
        engine["source_path"] = legacy
        engine["sha256"] = sha256_file(ROOT / legacy)
        engine["decision"]["status"] = "ADMISSIBLE_FOR_PACK"
        path = self._write_temp_evidence(evidence)
        result = resolve_admission(path, expected_population_id=TARGET)
        row = result["admissions"]["engine"]
        self.assertEqual(row["status"], "INCOMPATIBLE")
        self.assertIn("LEGACY_MIXED_RELABEL_REJECTED", row["reason_codes"])

    def test_hash_and_population_mismatch_fail_closed(self):
        evidence = self._load(EVIDENCE_PATH)
        bad_hash = copy.deepcopy(evidence)
        bad_hash["components"]["engine"]["sha256"] = "0" * 64
        result = resolve_admission(
            self._write_temp_evidence(bad_hash),
            expected_population_id=TARGET,
        )
        self.assertEqual(result["admissions"]["engine"]["status"], "INCOMPATIBLE")
        self.assertIn(
            "ARTIFACT_HASH_MISMATCH",
            result["admissions"]["engine"]["reason_codes"],
        )

        bad_population = copy.deepcopy(evidence)
        bad_population["components"]["application_release"]["population_id"] = "wrong-pop"
        result = resolve_admission(
            self._write_temp_evidence(bad_population),
            expected_population_id=TARGET,
        )
        self.assertEqual(
            result["admissions"]["application_release"]["status"],
            "INCOMPATIBLE",
        )
        self.assertIn(
            "POPULATION_ID_MISMATCH",
            result["admissions"]["application_release"]["reason_codes"],
        )

    def test_source_commit_mismatch_fails_closed(self):
        provenance = self._load(PROVENANCE_PATH)
        engine = self._load(ENGINE_PATH)
        app = self._load(APPLICATION_RELEASE_PATH)
        engine["runtime_source_commit"] = "0" * 40
        with self.assertRaisesRegex(RuntimeCompatibilityError, "source commit mismatch"):
            validate_source_provenance(provenance, engine, app)


if __name__ == "__main__":
    unittest.main()
