#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import tools.build_pack_engine_artifact as builder
from tools.audit_pack_engine_artifact import EVIDENCE_PATH, ROOT, TARGET, audit
from tools.population_pack_admission import resolve_admission
from tools.population_pack_candidate import sha256_file

class PackEngineArtifactTests(unittest.TestCase):
    def _load(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_temp_evidence(self, doc: dict) -> Path:
        tmp = tempfile.TemporaryDirectory(dir=ROOT / "tests/audit")
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "evidence.json"
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        return path

    def test_materialized_artifact_is_reproducible_content_addressed_and_self_contained(self):
        proof = builder.validate_materialized_artifact()
        self.assertEqual(
            proof["artifact_sha256"],
            "15bfa1ba78b463b63b5b9b8ee47a98fd9b29c2a9b79fa455b791a9781c7d7e08",
        )
        self.assertIn(proof["artifact_sha256"], Path(proof["artifact_path"]).name)
        self.assertEqual(proof["verified_source_files"], 9)
        self.assertEqual(proof["runtime_dependency_closure"], "SELF_CONTAINED")
        self.assertTrue(proof["population_agnostic"])
        self.assertFalse(proof["legacy_relabelled"])
        edges = {(row["source"], row["target"]) for row in proof["dependency_edges"]}
        self.assertIn(
            ("src/training/preflop-decision-adapter.js", "src/analytics/leak-analyzer.js"),
            edges,
        )

    def test_commonjs_distribution_loads_all_declared_modules(self):
        artifact = builder.validate_materialized_artifact()["artifact_path"]
        script = (
            "const a=require('./" + artifact + "');"
            "if(!a||a.schema!=='poker-pack-engine-artifact/v1')process.exit(2);"
            "if(a.runtime_dependency_closure!=='SELF_CONTAINED')process.exit(3);"
            "if(Object.keys(a.modules||{}).length!==9)process.exit(4);"
            "if(!a.modules.PokerNlheGameState||!a.modules.PokerPreflopDecisionAdapter)process.exit(5);"
        )
        subprocess.run(["node", "-e", script], cwd=ROOT, check=True)

    def test_source_subset_drift_fails_closed(self):
        real_sha = builder.sha256_file
        target = (ROOT / "src/preflop/contract.js").resolve()

        def fake_sha(path: Path) -> str:
            if path.resolve() == target:
                return "0" * 64
            return real_sha(path)

        with patch("tools.build_pack_engine_artifact.sha256_file", side_effect=fake_sha):
            with self.assertRaisesRegex(builder.EngineArtifactError, "source SHA-256 drift"):
                builder.validate_source_closure()

    def test_missing_runtime_file_fails_closed(self):
        real_is_file = Path.is_file
        missing = (ROOT / "src/analytics/leak-analyzer.js").resolve()

        def fake_is_file(path: Path) -> bool:
            if path.resolve() == missing:
                return False
            return real_is_file(path)

        with patch.object(Path, "is_file", fake_is_file):
            with self.assertRaisesRegex(builder.EngineArtifactError, "runtime source missing"):
                builder.validate_source_closure()

    def test_undeclared_runtime_dependency_fails_closed(self):
        real_load = builder._load

        def fake_load(path: Path):
            value = real_load(path)
            if path.name == "BUILD_SPEC.json":
                value = copy.deepcopy(value)
                value["runtime_dependency_closure"]["additional_files"] = []
            return value

        with patch("tools.build_pack_engine_artifact._load", side_effect=fake_load):
            with self.assertRaisesRegex(builder.EngineArtifactError, "undeclared runtime dependency"):
                builder.validate_source_closure()

    def test_resolver_305_admits_fresh_engine_only(self):
        result = resolve_admission(EVIDENCE_PATH, expected_population_id=TARGET)
        engine = result["admissions"]["engine"]
        self.assertEqual(engine["status"], "ADMISSIBLE")
        self.assertIn("ROLE_ADMISSIBLE_EXACT", engine["reason_codes"])
        self.assertNotIn("LEGACY_MIXED_RELABEL_REJECTED", engine["reason_codes"])
        candidate = result["candidate_contract"]["components"]["engine"]
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["source_path"], builder.validate_materialized_artifact()["artifact_path"])
        self.assertEqual(candidate["sha256"], builder.validate_materialized_artifact()["artifact_sha256"])
        self.assertEqual(
            result["candidate_contract"]["candidate_status"],
            "BLOCKED_PENDING_SCIENTIFIC_DECISION",
        )
        self.assertIsNone(result["candidate_contract"]["components"]["application_release"])

    def test_resolver_hash_population_and_legacy_injection_fail_closed(self):
        evidence = self._load(EVIDENCE_PATH)

        bad_hash = copy.deepcopy(evidence)
        bad_hash["components"]["engine"]["sha256"] = "0" * 64
        result = resolve_admission(self._write_temp_evidence(bad_hash), expected_population_id=TARGET)
        self.assertEqual(result["admissions"]["engine"]["status"], "INCOMPATIBLE")
        self.assertIn("ARTIFACT_HASH_MISMATCH", result["admissions"]["engine"]["reason_codes"])

        bad_population = copy.deepcopy(evidence)
        bad_population["components"]["engine"]["population_id"] = "wrong-population"
        result = resolve_admission(self._write_temp_evidence(bad_population), expected_population_id=TARGET)
        self.assertEqual(result["admissions"]["engine"]["status"], "INCOMPATIBLE")
        self.assertIn("POPULATION_ID_MISMATCH", result["admissions"]["engine"]["reason_codes"])

        legacy = copy.deepcopy(evidence)
        legacy_path = "user/releases/poker_range_equity_offline_multiway_v83.html"
        legacy["components"]["engine"]["source_path"] = legacy_path
        legacy["components"]["engine"]["sha256"] = sha256_file(ROOT / legacy_path)
        result = resolve_admission(self._write_temp_evidence(legacy), expected_population_id=TARGET)
        self.assertEqual(result["admissions"]["engine"]["status"], "INCOMPATIBLE")
        self.assertIn("LEGACY_MIXED_RELABEL_REJECTED", result["admissions"]["engine"]["reason_codes"])

    def test_full_audit_runs_resolver_and_read_only_preflight(self):
        result = audit()
        self.assertEqual(result["resolver"]["engine_status"], "ADMISSIBLE")
        self.assertEqual(result["preflight"]["result"], "BLOCKED")
        self.assertEqual(result["preflight"]["engine_availability"], "AVAILABLE")
        self.assertEqual(result["preflight"]["engine_compatibility"], "BLOCKED")
        self.assertIn("APPLICATION_RELEASE_NOT_READY", result["preflight"]["blocker_codes"])
        self.assertIn("POPULATION_STATUS_NOT_PROMOTED", result["preflight"]["blocker_codes"])
        self.assertFalse(result["preflight"]["writes_performed"])
        self.assertFalse(result["boundaries"]["test_consumed"])
        self.assertEqual(result["boundaries"]["production_effect"], "NONE")
        self.assertTrue(result["boundaries"]["parent_201_remains_open"])

if __name__ == "__main__":
    unittest.main()
