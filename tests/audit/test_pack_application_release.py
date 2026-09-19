#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.audit_pack_application_release import (
    BOOT_PATH,
    ENGINE_PATH,
    ENGINE_SHA,
    EVIDENCE_PATH,
    RELEASE_PATH,
    RELEASE_SHA,
    ROOT,
    TARGET,
    audit,
    validate_candidate_bytes,
)
from tools.population_pack_admission import resolve_admission
from tools.population_pack_candidate import sha256_file

class PackApplicationReleaseTests(unittest.TestCase):
    def _load(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _node_boot(self, mutation: str = "", mode: str = "PACK_SCOPED_ZOOM") -> dict:
        script = f"""
const Boot=require('./{BOOT_PATH}');
const target=Boot.TARGET_POPULATION;
const component=(role,path='training/artifacts/'+role+'.json',sha='1'.repeat(64))=>({{
  role,population_id:target,source_path:path,sha256:sha,
  lineage:{{population_id:target,format:'ZOOM'}},
  provenance:{{source_population_id:target}},
  decision:{{status:'ADMISSIBLE_FOR_PACK'}}
}});
const pack={{
  population_id:target,
  components:{{
    engine:component('engine',Boot.ENGINE_PATH,Boot.ENGINE_SHA256),
    model_a_preflop:component('model_a_preflop'),
    model_a_postflop:component('model_a_postflop'),
    model_b:component('model_b'),
    hero_strategy:component('hero_strategy'),
    hero_ranges:component('hero_ranges')
  }}
}};
{mutation}
try {{
  const result=Boot.resolve({{mode:{json.dumps(mode)},pack}});
  console.log(JSON.stringify({{ok:true,result}}));
}} catch(err) {{
  console.log(JSON.stringify({{ok:false,code:err.code||null,message:err.message}}));
}}
"""
        proc = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(proc.stdout)

    def _write_temp_evidence(self, doc: dict) -> Path:
        tmp = tempfile.TemporaryDirectory(dir=ROOT / "tests/audit")
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "evidence.json"
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        return path

    def test_release_and_boot_are_content_addressed_and_legacy_anchors_unchanged(self):
        proof = validate_candidate_bytes()
        self.assertEqual(proof["release_sha256"], RELEASE_SHA)
        self.assertIn(RELEASE_SHA, Path(RELEASE_PATH).name)
        self.assertIn(proof["boot_sha256"], Path(BOOT_PATH).name)
        self.assertEqual(proof["engine_path"], ENGINE_PATH)
        self.assertEqual(proof["engine_sha256"], ENGINE_SHA)
        self.assertEqual(
            proof["legacy_anchors_verified"],
            ["site/RELEASE.json", "site/trainer.js", "site/training/preflop-runtime.js"],
        )

    def test_zoom_pack_with_exact_engine_and_scientific_slots_binds(self):
        out = self._node_boot()
        self.assertTrue(out["ok"])
        self.assertEqual(out["result"]["status"], "BOUND")
        self.assertFalse(out["result"]["use_existing_default_runtime"])
        self.assertEqual(out["result"]["fallback_policy"], "NONE_FAIL_CLOSED")
        self.assertEqual(out["result"]["engine_binding"]["source_path"], ENGINE_PATH)
        self.assertEqual(out["result"]["engine_binding"]["sha256"], ENGINE_SHA)

    def test_engine_hash_mismatch_fails_closed(self):
        out = self._node_boot("pack.components.engine.sha256='0'.repeat(64);")
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "ENGINE_BINDING_MISMATCH")

    def test_zoom_pack_without_model_a_fails_closed_without_v5_fallback(self):
        out = self._node_boot("delete pack.components.model_a_preflop;")
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "PACK_COMPONENT_MISSING")

    def test_zoom_pack_without_hero_strategy_fails_closed(self):
        out = self._node_boot("delete pack.components.hero_strategy;")
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "PACK_COMPONENT_MISSING")

    def test_legacy_model_a_v5_injection_is_rejected(self):
        out = self._node_boot(
            "pack.components.model_a_preflop.source_path='training/models/preflop_population_model_v5.json';"
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "LEGACY_FALLBACK_REJECTED")

    def test_legacy_engine_injection_is_rejected(self):
        out = self._node_boot(
            "pack.components.engine.source_path='user/releases/poker_range_equity_offline_multiway_v83.html';"
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "LEGACY_FALLBACK_REJECTED")

    def test_population_mismatch_is_rejected(self):
        out = self._node_boot("pack.population_id='legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1';")
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "PACK_POPULATION_MISMATCH")

    def test_legacy_default_mode_is_passthrough_and_does_not_consume_pack(self):
        out = self._node_boot("pack.population_id='wrong';", mode="LEGACY_DEFAULT")
        self.assertTrue(out["ok"])
        self.assertEqual(out["result"]["status"], "LEGACY_PASSTHROUGH")
        self.assertTrue(out["result"]["use_existing_default_runtime"])
        self.assertIsNone(out["result"]["bindings"])

    def test_resolver_admits_engine_and_application_release_only(self):
        result = resolve_admission(EVIDENCE_PATH, expected_population_id=TARGET)
        self.assertEqual(result["admissions"]["engine"]["status"], "ADMISSIBLE")
        self.assertEqual(result["admissions"]["application_release"]["status"], "ADMISSIBLE")
        for role in ("model_a_preflop", "model_a_postflop", "model_b", "hero_strategy", "hero_ranges"):
            self.assertEqual(result["admissions"][role]["status"], "UNRESOLVED")
        self.assertEqual(
            result["candidate_contract"]["candidate_status"],
            "BLOCKED_PENDING_SCIENTIFIC_DECISION",
        )

    def test_application_release_hash_and_population_mismatch_fail_closed_in_resolver(self):
        evidence = self._load(EVIDENCE_PATH)

        bad_hash = copy.deepcopy(evidence)
        bad_hash["components"]["application_release"]["sha256"] = "0" * 64
        result = resolve_admission(self._write_temp_evidence(bad_hash), expected_population_id=TARGET)
        self.assertEqual(result["admissions"]["application_release"]["status"], "INCOMPATIBLE")
        self.assertIn(
            "ARTIFACT_HASH_MISMATCH",
            result["admissions"]["application_release"]["reason_codes"],
        )

        bad_population = copy.deepcopy(evidence)
        bad_population["components"]["application_release"]["population_id"] = "wrong-population"
        result = resolve_admission(self._write_temp_evidence(bad_population), expected_population_id=TARGET)
        self.assertEqual(result["admissions"]["application_release"]["status"], "INCOMPATIBLE")
        self.assertIn(
            "POPULATION_ID_MISMATCH",
            result["admissions"]["application_release"]["reason_codes"],
        )

    def test_legacy_release_relabel_is_rejected_by_resolver(self):
        evidence = self._load(EVIDENCE_PATH)
        legacy = copy.deepcopy(evidence)
        legacy_path = "site/RELEASE.json"
        legacy["components"]["application_release"]["source_path"] = legacy_path
        legacy["components"]["application_release"]["sha256"] = sha256_file(ROOT / legacy_path)
        result = resolve_admission(self._write_temp_evidence(legacy), expected_population_id=TARGET)
        row = result["admissions"]["application_release"]
        self.assertEqual(row["status"], "INCOMPATIBLE")
        self.assertIn("LEGACY_MIXED_RELABEL_REJECTED", row["reason_codes"])

    def test_full_audit_runs_resolver_and_read_only_preflight(self):
        result = audit()
        self.assertEqual(result["resolver"]["engine_status"], "ADMISSIBLE")
        self.assertEqual(result["resolver"]["application_release_status"], "ADMISSIBLE")
        self.assertEqual(result["preflight"]["result"], "BLOCKED")
        self.assertEqual(result["preflight"]["engine_availability"], "AVAILABLE")
        self.assertEqual(result["preflight"]["application_release_availability"], "AVAILABLE")
        self.assertEqual(result["preflight"]["engine_compatibility"], "BLOCKED")
        self.assertIn("APPLICATION_RELEASE_NOT_PROMOTED", result["preflight"]["blocker_codes"])
        self.assertIn("POPULATION_STATUS_NOT_PROMOTED", result["preflight"]["blocker_codes"])
        self.assertNotIn("ENGINE_ARTIFACT_MISMATCH", result["preflight"]["blocker_codes"])
        self.assertNotIn("ENGINE_HASH_MISMATCH", result["preflight"]["blocker_codes"])
        self.assertNotIn("APPLICATION_RELEASE_NOT_READY", result["preflight"]["blocker_codes"])
        self.assertFalse(result["preflight"]["writes_performed"])
        self.assertFalse(result["boundaries"]["test_consumed"])
        self.assertEqual(result["boundaries"]["production_effect"], "NONE")
        self.assertTrue(result["boundaries"]["parent_201_remains_open"])

if __name__ == "__main__":
    unittest.main()
