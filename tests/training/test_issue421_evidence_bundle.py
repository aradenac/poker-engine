#!/usr/bin/env python3
"""#421 T12 -- content-addressed evidence bundle regressions.

These tests pin what the ticket requires of the persistence step: the ten
required artifacts exist and are content-addressed, every persisted digest is
recomputed from the persisted bytes and matches the declared value, the SUMMARY
covers coverage/calibration/strata/decision, and the boundary stays documented
(``TEST_CONSUMED=false``, active pointer unchanged).  No holdout is parsed here.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training import build_issue421_evidence_bundle as bundle_tool  # noqa: E402

REQUIRED = [name for name, _role in bundle_tool.REQUIRED_ARTIFACTS]


def digest_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Issue421EvidenceBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not bundle_tool.SPEC_PATH.is_file() or not bundle_tool.INDEX_PATH.is_file():
            raise unittest.SkipTest("the #421 evidence bundle is absent from this worktree")
        cls.index = json.loads(bundle_tool.INDEX_PATH.read_text(encoding="utf-8"))
        cls.summary_raw = bundle_tool.SUMMARY_PATH.read_text(encoding="utf-8")
        cls.summary = " ".join(cls.summary_raw.split())
        cls.decision = json.loads(bundle_tool._abs("DECISION.json").read_text(encoding="utf-8"))
        cls.spec = json.loads(bundle_tool.SPEC_PATH.read_text(encoding="utf-8"))

    # ------------------------------------------------------- completeness
    def test_every_required_artifact_is_present_and_content_addressed(self) -> None:
        self.assertEqual(self.index["required_artifacts"], REQUIRED)
        self.assertEqual(set(self.index["artifacts"]), set(REQUIRED))
        for name in REQUIRED:
            entry = self.index["artifacts"][name]
            with self.subTest(artifact=name):
                source = Path(entry["path"])
                self.assertTrue(source.is_file(), entry["path"])
                data = source.read_bytes()
                self.assertEqual(entry["bytes"], len(data))
                self.assertEqual(entry["sha256"], digest_of(source))
                self.assertTrue(entry["content_addressed"])
                copy = ROOT / entry["object"]
                self.assertTrue(copy.is_file(), entry["object"])
                self.assertEqual(copy.read_bytes(), data)
        for rel, entry in self.index["supporting_evidence"].items():
            with self.subTest(supporting=rel):
                source = ROOT / entry["path"]
                self.assertEqual(entry["sha256"], digest_of(source))
                self.assertEqual((ROOT / entry["object"]).read_bytes(), source.read_bytes())

    def test_no_unreferenced_object_survives_in_the_content_store(self) -> None:
        referenced = {
            Path(entry["object"]).name
            for section in ("artifacts", "supporting_evidence")
            for entry in self.index[section].values()
        }
        present = {path.name for path in bundle_tool.OBJECTS.iterdir() if path.is_file()}
        self.assertEqual(present, referenced)

    # --------------------------------------------------- digest recomputation
    def test_sidecar_digests_are_recomputed_and_match(self) -> None:
        checks = self.index["digest_verification"]["sidecar_checks"]
        self.assertTrue(checks)
        for check in checks:
            entry = self.index["artifacts"][check["artifact"]]
            with self.subTest(artifact=check["artifact"]):
                self.assertTrue(check["match"])
                self.assertTrue(check["canonical_match"])
                self.assertEqual(check["declared"]["sha256"], entry["sha256"])
                self.assertEqual(
                    check["declared"]["canonical_payload_sha256"],
                    entry["canonical_payload_sha256"],
                )
                sidecar = bundle_tool._abs(
                    Path(check["artifact"]).with_suffix(".sha256").name
                ).read_text(encoding="utf-8")
                self.assertTrue(sidecar.startswith(entry["sha256"]))

    def test_cross_reference_digests_are_recomputed_and_match(self) -> None:
        checks = self.index["digest_verification"]["cross_reference_checks"]
        self.assertGreaterEqual(len(checks), 30)
        for check in checks:
            with self.subTest(source=check["source"], field=check["field"]):
                self.assertTrue(check["match"], check)
        self.assertTrue(
            self.index["digest_verification"]["all_recomputed_digests_match_persisted"]
        )
        # The bundle re-derives them independently, not from the persisted index.
        rebuilt = bundle_tool.build()
        self.assertEqual(
            rebuilt["index"]["digest_verification"]["cross_reference_checks"], checks
        )

    def test_the_bundle_is_byte_identical_to_a_fresh_deterministic_build(self) -> None:
        rebuilt = bundle_tool.build()
        self.assertEqual(bundle_tool.SPEC_PATH.read_bytes(), rebuilt["spec_bytes"])
        self.assertEqual(bundle_tool.SUMMARY_PATH.read_bytes(), rebuilt["summary_bytes"])
        self.assertEqual(
            bundle_tool.INDEX_PATH.read_bytes(), bundle_tool.serialize(rebuilt["index"])
        )
        self.assertEqual(bundle_tool.check(), 0)

    # ------------------------------------------------------------- model spec
    def test_the_model_spec_is_content_addressed_and_describes_the_frozen_model(self) -> None:
        spec_bytes = bundle_tool.SPEC_PATH.read_bytes()
        digest = digest_of(bundle_tool.SPEC_PATH)
        entry = self.index["artifacts"][bundle_tool.SPEC_NAME]
        self.assertEqual(digest, entry["sha256"])
        self.assertEqual(spec_bytes, (ROOT / entry["object"]).read_bytes())
        self.assertEqual(
            entry["canonical_payload_sha256"], bundle_tool.canonical_payload_sha256(self.spec)
        )
        sidecar = bundle_tool.SPEC_DIGEST_PATH.read_text(encoding="utf-8").splitlines()
        self.assertEqual(sidecar[0], digest + "  " + bundle_tool.SPEC_NAME)
        self.assertIn("spec_digest_location", self.spec)
        self.assertNotIn("canonical_payload_sha256", self.spec)

        manifest = json.loads(bundle_tool._abs("CANDIDATE_MANIFEST.json").read_text("utf-8"))
        self.assertEqual(self.spec["schema"], bundle_tool.SPEC_SCHEMA)
        self.assertEqual(self.spec["status"], bundle_tool.SPEC_STATUS)
        self.assertEqual(
            self.spec["model_identity"]["candidate_id"], manifest["candidate"]["candidate_id"]
        )
        self.assertEqual(
            self.spec["model_identity"]["candidate_canonical_payload_sha256"],
            manifest["candidate"]["canonical_payload_sha256"],
        )
        self.assertEqual(
            self.spec["input_contract"]["required_fields"],
            manifest["features"]["row_contract_fields"],
        )
        self.assertEqual(
            self.spec["representation"]["sizing_axis_knots"],
            manifest["transformations"]["sizing_axis_knots"],
        )
        self.assertEqual(self.spec["forbidden"], manifest["forbidden"])
        self.assertEqual(
            self.spec["terminal_decision"]["decision"], self.decision["decision"]
        )
        self.assertFalse(self.spec["holdout_boundary"]["test_consumed"])
        self.assertFalse(self.spec["holdout_boundary"]["active_pointer_mutated"])
        for name in REQUIRED:
            if name in (bundle_tool.SUMMARY_NAME, bundle_tool.SPEC_NAME):
                continue
            with self.subTest(binding=name):
                self.assertIn(name, self.spec["evidence_bindings"])
                self.assertEqual(
                    self.spec["evidence_bindings"][name]["sha256"],
                    self.index["artifacts"][name]["sha256"],
                )

    # --------------------------------------------------------------- SUMMARY
    def test_the_summary_covers_coverage_calibration_strata_and_decision(self) -> None:
        validation = json.loads(
            bundle_tool._abs("VALIDATION_RESULT.json").read_text(encoding="utf-8")
        )
        coverage = validation["metrics"]["coverage"]
        for token in (
            "## 1. Decision",
            "## 2. Coverage",
            "## 3. Calibration",
            "## 4. Strata",
            "## 5. OOD gate",
            "## 6. Raise-sizing gate",
            "## 7. #367 preflight",
            "## 8. Digest verification",
            "## 9. Boundaries",
        ):
            self.assertIn(token, self.summary, token)
        self.assertIn(self.decision["decision"], self.summary)
        for gate in self.decision["failed_gates"]:
            self.assertIn(gate, self.summary)
        for stratum in validation["metrics"]["strata"]["share"]:
            self.assertIn(stratum, self.summary)
        self.assertIn(str(coverage["answered_decisions"]), self.summary)
        self.assertIn(str(coverage["distinct_hands_answered"]), self.summary)
        for model in validation["metrics"]["primary"]["per_model"]:
            self.assertIn(model, self.summary)

    def test_the_summary_documents_the_boundary_and_the_digest_recomputation(self) -> None:
        self.assertIn("TEST_CONSUMED=false", self.summary_raw)
        self.assertIn("ACTIVE_POINTER_MUTATED=false", self.summary_raw)
        self.assertIn("VALIDATION_CONSUMED=true", self.summary_raw)
        self.assertIn(
            "recomputed", self.summary
        )
        self.assertIn("all_recomputed_digests_match_persisted", self.summary)
        for name in REQUIRED:
            self.assertIn(name, self.summary)

    def test_the_index_documents_the_boundary_and_the_issue367_rule(self) -> None:
        boundary = self.index["boundary"]
        self.assertFalse(boundary["test_consumed"])
        self.assertFalse(boundary["test_authorized"])
        self.assertFalse(boundary["active_pointer_mutated"])
        self.assertFalse(boundary["active_model_pointer_mutation"])
        self.assertFalse(boundary["issue367_executed"])
        self.assertEqual(boundary["validation_reads"], 1)
        self.assertFalse(self.decision["issue367_authorized"])
        consumption = self.index["issue367_consumption"]
        self.assertFalse(consumption["candidate_authorized_for_367"])
        self.assertEqual(consumption["outcome"], self.decision["protocol_outcome"])

    # -------------------------------------------------------- no holdout read
    def test_the_builder_imports_no_holdout_loader(self) -> None:
        source = Path(bundle_tool.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden = ("load_holdout", "validation_records", "hero_preflop_iso_runner")
        for marker in forbidden:
            with self.subTest(marker=marker):
                self.assertFalse(any(marker in name for name in imported))
                self.assertNotIn(marker, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
