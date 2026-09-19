from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.audit_population_pack_admission_real import (
    ROOT,
    TARGET,
    build_evidence_set,
    load_json,
    SNAPSHOT_108,
)
from tools.population_pack_admission import resolve_admission
from tools.population_pack_preflight import preflight


class RealPopulationPackAdmissionAuditTests(unittest.TestCase):
    def test_real_evidence_resolves_all_roles_fail_closed_and_deterministically(self):
        evidence = build_evidence_set()
        self.assertEqual(evidence["population_id"], TARGET)
        self.assertEqual(len(evidence["components"]), 7)
        self.assertNotIn(
            "ADMISSIBLE_FOR_PACK",
            {row["decision"]["status"] for row in evidence["components"].values()},
        )

        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as tmp:
            rel = Path(tmp).relative_to(ROOT) / "evidence.json"
            path = ROOT / rel
            path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            first = resolve_admission(rel, root=ROOT, expected_population_id=TARGET)
            second = resolve_admission(rel, root=ROOT, expected_population_id=TARGET)
            self.assertEqual(first, second)

            candidate_rel = Path(tmp).relative_to(ROOT) / "candidate.json"
            (ROOT / candidate_rel).write_text(
                json.dumps(first["candidate_contract"], indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            pre = preflight(candidate_rel, root=ROOT, expected_population_id=TARGET)

        expected = {
            "model_a_preflop": "INCOMPATIBLE",
            "model_a_postflop": "UNRESOLVED",
            "model_b": "UNRESOLVED",
            "hero_strategy": "RETAIN_REFERENCE",
            "engine": "INCOMPATIBLE",
            "hero_ranges": "RETAIN_REFERENCE",
            "application_release": "INCOMPATIBLE",
        }
        self.assertEqual(
            {role: row["status"] for role, row in first["admissions"].items()},
            expected,
        )
        self.assertEqual(first["summary"]["ADMISSIBLE"], 0)
        self.assertEqual(first["summary"]["RETAIN_REFERENCE"], 2)
        self.assertEqual(first["summary"]["UNRESOLVED"], 2)
        self.assertEqual(first["summary"]["INCOMPATIBLE"], 3)
        self.assertEqual(first["candidate_contract"]["candidate_status"], "BLOCKED_PENDING_SCIENTIFIC_DECISION")
        self.assertTrue(all(value is None for value in first["candidate_contract"]["components"].values()))
        self.assertTrue(all(row["artifact"]["verified"] for row in first["admissions"].values()))

        for role in ("hero_strategy", "hero_ranges"):
            self.assertEqual(first["admissions"][role]["scientific_decision"]["status"], "RETAIN_REFERENCE")
            self.assertNotEqual(first["admissions"][role]["status"], "ADMISSIBLE")

        self.assertEqual(
            first["admissions"]["model_b"]["scientific_decision"]["status"],
            "VALIDATION_SUPPORTS_PRICE_AWARE_CANDIDATE__NO_PROMOTION",
        )
        self.assertIn(
            "SCIENTIFIC_DECISION_STATUS_UNRESOLVED",
            first["admissions"]["model_b"]["reason_codes"],
        )

        for role in ("model_a_preflop", "engine", "application_release"):
            self.assertEqual(first["admissions"][role]["lineage"]["format"], "MIXED_ZOOM_REGULAR")
            self.assertNotEqual(first["admissions"][role]["status"], "ADMISSIBLE")
            self.assertIn(
                "CROSS_POPULATION_FALLBACK_NOT_AUTHORIZED",
                first["admissions"][role]["reason_codes"],
            )

        self.assertEqual(pre["result"], "BLOCKED")
        self.assertEqual(pre["population"]["status"], "CERTIFIED_DATA_ONLY")
        self.assertFalse(pre["safety"]["writes_performed"])
        self.assertFalse(pre["safety"]["population_registry_updates"])
        self.assertFalse(pre["safety"]["production_pointer_updates"])
        self.assertFalse(pre["safety"]["release_publication"])
        self.assertFalse(pre["safety"]["pack_activation"])

    def test_issue_108_snapshot_is_verbatim_retained_reference_and_test_unconsumed(self):
        selection = load_json(SNAPSHOT_108)
        self.assertEqual(selection["outcome"], "RETAIN_REFERENCE")
        self.assertFalse(selection["promotion_authorized"])
        self.assertFalse(selection["test_authorized"])
        self.assertFalse(selection["test_consumed"])
        self.assertFalse(selection["test_used_for_selection"])


from tests.audit.test_pack_runtime_compatibility import PackRuntimeCompatibilityTests  # noqa: F401
from tests.audit.test_pack_engine_artifact import PackEngineArtifactTests  # noqa: F401
from tests.audit.test_pack_application_release import PackApplicationReleaseTests  # noqa: F401

if __name__ == "__main__":
    unittest.main()
