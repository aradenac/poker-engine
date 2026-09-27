#!/usr/bin/env python3
"""#423 T9 -- content-addressed evidence bundle regressions.

These tests pin what the ticket requires of the persistence step: the eight
required artifacts exist and are content-addressed, every persisted digest is
recomputed from the persisted bytes and matches the declared value, the terminal
``DECISION.json`` and ``SUMMARY.md`` cover the two valid terminal outcomes and
the boundaries (``TEST_CONSUMED=false``, ``VALIDATION_CONSUMED=false``, active
pointer unchanged, ``next_issue=367`` not executed), and ``--check`` is
byte-stable and fails as soon as a byte drifts.  No holdout is parsed here.

``pytest`` is not a declared dependency of this repository; the suite is a plain
``unittest`` module, run with ``python3 -m unittest`` like its siblings.
"""
from __future__ import annotations

import ast
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training import build_issue423_evidence_bundle as bundle_tool  # noqa: E402

REQUIRED = [name for name, _role in bundle_tool.REQUIRED_ARTIFACTS]
FROZEN = [name for name in REQUIRED if name not in bundle_tool.AUTHORED_ARTIFACTS]


def digest_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _IsolatedLayout:
    """Redirect the tool's bundle directory into a temporary copy.

    Only the six frozen siblings and their ``.sha256`` sidecars are copied; the
    cross-referenced repository evidence is read from the real repository, which
    makes the isolated layout a faithful, disposable copy of the bundle.
    """

    def __init__(self, tmp: Path):
        self.tmp = tmp

    def __enter__(self) -> Path:
        here = self.tmp / "issue423_hybrid_router"
        here.mkdir(parents=True, exist_ok=True)
        for name in FROZEN:
            shutil.copy2(bundle_tool.HERE / name, here / name)
            sidecar = bundle_tool.HERE / (Path(name).with_suffix(".sha256").name)
            if sidecar.is_file():
                shutil.copy2(sidecar, here / sidecar.name)
        derivation = bundle_tool.HERE / "derivation"
        if derivation.is_dir():
            shutil.copytree(derivation, here / "derivation")
        self._patch = mock.patch.object(bundle_tool, "HERE", here)
        self._patch.start()
        return here

    def __exit__(self, *exc):
        self._patch.stop()
        return False


class Issue423EvidenceBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not bundle_tool.decision_path().is_file() or not bundle_tool.index_path().is_file():
            raise unittest.SkipTest("the #423 evidence bundle is absent from this worktree")
        cls.index = json.loads(bundle_tool.index_path().read_text(encoding="utf-8"))
        cls.summary_raw = bundle_tool.summary_path().read_text(encoding="utf-8")
        cls.summary = " ".join(cls.summary_raw.split())
        cls.decision = json.loads(bundle_tool.decision_path().read_text(encoding="utf-8"))
        cls.report = json.loads(bundle_tool._abs("TRAIN_CV_ROUTER_REPORT.json").read_text("utf-8"))

    # ------------------------------------------------------- completeness
    def test_every_required_artifact_is_present_and_content_addressed(self) -> None:
        self.assertEqual(self.index["required_artifacts"], REQUIRED)
        self.assertEqual(set(self.index["artifacts"]), set(REQUIRED))
        for name in REQUIRED:
            entry = self.index["artifacts"][name]
            with self.subTest(artifact=name):
                source = ROOT / entry["path"]
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
        present = {path.name for path in bundle_tool.objects_dir().iterdir() if path.is_file()}
        self.assertEqual(present, referenced)

    # --------------------------------------------------- digest recomputation
    def test_sidecar_digests_are_recomputed_and_match(self) -> None:
        checks = self.index["digest_verification"]["sidecar_checks"]
        self.assertEqual({check["artifact"] for check in checks}, set(FROZEN))
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
        self.assertGreaterEqual(len(checks), 80)
        for check in checks:
            with self.subTest(source=check["source"], kind=check["kind"]):
                self.assertTrue(check["match"], check)
        self.assertTrue(
            self.index["digest_verification"]["all_recomputed_digests_match_persisted"]
        )
        # Every declared digest that pins a persisted artifact is covered: the
        # bundle re-derives them independently, not from the persisted index.
        rebuilt = bundle_tool.build()
        self.assertEqual(
            rebuilt["index"]["digest_verification"]["cross_reference_checks"], checks
        )
        for kind in ("byte", "canonical", "criteria", "nested"):
            with self.subTest(kind=kind):
                self.assertTrue(any(check["kind"] == kind for check in checks))

    def test_the_bundle_is_byte_identical_to_a_fresh_deterministic_build(self) -> None:
        rebuilt = bundle_tool.build()
        self.assertEqual(bundle_tool.decision_path().read_bytes(), rebuilt["decision_bytes"])
        self.assertEqual(bundle_tool.summary_path().read_bytes(), rebuilt["summary_bytes"])
        self.assertEqual(
            bundle_tool.index_path().read_bytes(), bundle_tool.serialize(rebuilt["index"])
        )
        self.assertEqual(bundle_tool.check(), 0)

    # ------------------------------------------------------ terminal decision
    def test_the_terminal_decision_is_content_addressed_and_self_consistent(self) -> None:
        decision_bytes = bundle_tool.decision_path().read_bytes()
        digest = digest_of(bundle_tool.decision_path())
        entry = self.index["artifacts"][bundle_tool.DECISION_NAME]
        self.assertEqual(digest, entry["sha256"])
        self.assertEqual(decision_bytes, (ROOT / entry["object"]).read_bytes())
        self.assertEqual(
            entry["canonical_payload_sha256"],
            bundle_tool.canonical_payload_sha256(self.decision),
        )
        self.assertEqual(
            self.decision["canonical_payload_sha256"],
            bundle_tool.canonical_payload_sha256(self.decision),
        )
        self.assertEqual(self.index["decision"]["sha256"], digest)
        sidecar = bundle_tool.decision_digest_path().read_text(encoding="utf-8").splitlines()
        self.assertEqual(sidecar[0], digest + "  " + bundle_tool.DECISION_NAME)
        self.assertEqual(self.decision["decision"], self.report["outcome"])
        self.assertEqual(self.decision["schema"], bundle_tool.DECISION_SCHEMA)
        self.assertTrue(self.decision["terminal"])

    def test_the_terminal_decision_and_summary_cover_both_terminal_outcomes(self) -> None:
        self.assertEqual(
            [entry["id"] for entry in self.decision["terminal_outcomes"]],
            list(bundle_tool.TERMINAL_OUTCOMES),
        )
        actual = [e["id"] for e in self.decision["terminal_outcomes"] if e["actual"]]
        self.assertEqual(actual, [self.decision["decision"]])
        self.assertEqual(
            self.decision["terminal_outcomes"][0]["id"], bundle_tool.ADMIT_OUTCOME
        )
        self.assertEqual(
            self.decision["terminal_outcomes"][1]["id"], bundle_tool.RETAIN_OUTCOME
        )
        self.assertEqual(self.index["terminal_decision"]["terminal_outcomes"], list(bundle_tool.TERMINAL_OUTCOMES))
        self.assertEqual(
            self.index["terminal_decision"]["actual_terminal_outcome"], self.decision["decision"]
        )
        for token in bundle_tool.TERMINAL_OUTCOMES:
            with self.subTest(outcome=token):
                self.assertIn(token, self.summary)
        self.assertIn("terminal outcomes", self.summary)
        self.assertIn("PRODUCT_ADMISSIBLE", self.summary_raw)

    def test_the_terminal_decision_covers_the_boundaries(self) -> None:
        boundaries = self.decision["boundaries"]
        self.assertFalse(boundaries["test_consumed"])
        self.assertFalse(boundaries["test_authorized"])
        self.assertFalse(boundaries["validation_consumed"])
        self.assertFalse(boundaries["validation_reopened"])
        self.assertFalse(boundaries["active_pointer_mutated"])
        self.assertFalse(boundaries["active_model_pointer_mutation"])
        self.assertFalse(boundaries["product_admissible"])
        self.assertFalse(boundaries["issue367_executed"])
        self.assertFalse(boundaries["hero_ev_executed"])
        self.assertEqual(boundaries["automatic_promotion"], "FORBIDDEN")
        self.assertEqual(self.decision["next_issue"], bundle_tool.NEXT_ISSUE)
        self.assertEqual(self.decision["next_issue_status"], "NOT_EXECUTED")
        self.assertFalse(self.decision["issue367"]["authorized"])
        self.assertFalse(self.decision["issue367"]["executed"])
        self.assertEqual(
            self.decision["issue367"]["terminal_outcome"], self.decision["decision"]
        )
        self.assertEqual(
            self.decision["references"]["admitted_model_for_issue367"]["model_id"],
            bundle_tool.ADMITTED_367_MODEL_ID,
        )

    def test_the_failed_criterion_is_the_only_failed_gate(self) -> None:
        failed = [gate["id"] for gate in self.decision["gates"] if not gate["passed"]]
        self.assertEqual(failed, self.decision["failed_criteria"])
        self.assertEqual(failed, self.report["criteria_evaluation"]["failed"])
        self.assertEqual(
            self.decision["criteria_total"], len(self.report["criteria_evaluation"]["criteria"])
        )
        self.assertEqual(
            self.decision["criteria_passed"] + len(failed), self.decision["criteria_total"]
        )

    # --------------------------------------------------------------- SUMMARY
    def test_the_summary_covers_the_required_sections(self) -> None:
        for token in (
            "## 1. Decision",
            "## 2. Frozen criteria evaluation",
            "## 3. Global non-inferiority",
            "## 4. Sparse strata comparison",
            "## 5. OOD gate",
            "## 6. LIMPER_VS_ISO",
            "## 7. Generalized calibration",
            "## 8. #367 preflight",
            "## 9. Digest verification",
            "## 10. Boundaries",
        ):
            self.assertIn(token, self.summary, token)
        self.assertIn(self.decision["decision"], self.summary)
        for criterion in self.decision["failed_criteria"]:
            self.assertIn(criterion, self.summary)
        for stratum in self.report["strata"]["shares"]:
            self.assertIn(stratum, self.summary)
        for name in REQUIRED:
            self.assertIn(name, self.summary)
        for model in self.report["models"]:
            self.assertIn(model, self.summary)

    def test_the_summary_documents_the_boundary_and_the_digest_recomputation(self) -> None:
        self.assertIn("TEST_CONSUMED=false", self.summary_raw)
        self.assertIn("VALIDATION_CONSUMED=false", self.summary_raw)
        self.assertIn("ACTIVE_POINTER_MUTATED=false", self.summary_raw)
        self.assertIn("ISSUE367_EXECUTED=false", self.summary_raw)
        self.assertIn("next_issue=367", self.summary)
        self.assertIn("recomputed", self.summary)
        self.assertIn("all_recomputed_digests_match_persisted", self.summary)
        self.assertIn("92 cross-references", self.summary)

    def test_the_index_documents_the_boundary_and_the_issue367_rule(self) -> None:
        boundary = self.index["boundary"]
        self.assertFalse(boundary["test_consumed"])
        self.assertFalse(boundary["test_authorized"])
        self.assertFalse(boundary["validation_consumed"])
        self.assertFalse(boundary["validation_reopened"])
        self.assertFalse(boundary["active_pointer_mutated"])
        self.assertFalse(boundary["active_model_pointer_mutation"])
        self.assertFalse(boundary["issue367_executed"])
        self.assertEqual(boundary["next_issue"], bundle_tool.NEXT_ISSUE)
        self.assertEqual(boundary["consumed_splits"], ["TRAIN"])
        self.assertEqual(boundary["refused_splits"], ["VALIDATION", "TEST"])
        self.assertFalse(self.decision["issue367"]["authorized"])
        self.assertEqual(self.index["terminal_decision"]["issue367_authorized"], False)
        self.assertEqual(
            self.index["terminal_decision"]["decision"], self.report["outcome"]
        )

    # --------------------------------------------------- drift detection
    def test_check_fails_closed_when_an_authored_byte_or_input_drifts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedLayout(Path(tmp)) as here:
                self.assertEqual(bundle_tool.persist(), 0)
                self.assertEqual(bundle_tool.check(), 0)

                # 1. a persisted output byte drifts
                decision = here / bundle_tool.DECISION_NAME
                original = decision.read_bytes()
                decision.write_bytes(original[:-1] + b" " + original[-1:])
                self.assertEqual(bundle_tool.check(), 1)
                decision.write_bytes(original)
                self.assertEqual(bundle_tool.check(), 0)

                # 2. a content-addressed copy drifts
                entry = json.loads((here / bundle_tool.INDEX_NAME).read_text("utf-8"))
                copy = ROOT / entry["artifacts"][bundle_tool.SUMMARY_NAME]["object"]
                self.assertTrue(str(copy).startswith(str(ROOT)))
                local_copy = here / "sha256" / copy.name
                saved = local_copy.read_bytes()
                local_copy.write_bytes(saved + b"\n")
                self.assertEqual(bundle_tool.check(), 1)
                local_copy.write_bytes(saved)
                self.assertEqual(bundle_tool.check(), 0)

                # 3. a frozen input drifts from its declared sidecar
                spec = here / "HYBRID_ROUTER_SPEC.json"
                frozen_bytes = spec.read_bytes()
                spec.write_bytes(frozen_bytes.replace(b'"frozen": true', b'"frozen": 1', 1))
                self.assertEqual(bundle_tool.check(), 1)
                spec.write_bytes(frozen_bytes)
                self.assertEqual(bundle_tool.check(), 0)

    def test_check_mode_passes_on_the_persisted_bundle(self) -> None:
        self.assertEqual(bundle_tool.main(["--check"]), 0)

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
