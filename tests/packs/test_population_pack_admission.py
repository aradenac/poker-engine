from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.population_pack_admission import (
    ADMISSIBLE,
    INCOMPATIBLE,
    REJECTED,
    RETAIN_REFERENCE,
    UNRESOLVED,
    canonical_json_bytes,
    resolve_admission,
)
from tools.population_pack_candidate import REQUIRED_ROLES, content_identity, sha256_file
from tools.population_pack_preflight import preflight

TARGET = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
LEGACY = "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1"


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class AdmissionFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.input_rel = Path("evidence/input.json")
        self.provenance_rel = Path("evidence/provenance.json")
        self.decision_rel = Path("evidence/decision.json")
        self.fallback_rel = Path("evidence/fallback.json")
        self.sources = {
            "model_a_preflop": "artifacts/target/model_a_preflop.json",
            "model_a_postflop": "artifacts/target/model_a_postflop.json",
            "model_b": "artifacts/target/model_b",
            "hero_strategy": "artifacts/target/hero_strategy.json",
            "engine": "artifacts/target/engine.html",
            "hero_ranges": "artifacts/target/hero_ranges.json",
            "application_release": "artifacts/target/application_release.json",
        }
        self.legacy_source = "artifacts/legacy/model_a_preflop.json"
        self._build()

    def _build(self) -> None:
        for rel, payload in {
            self.sources["model_a_preflop"]: {"model_type": "preflop_population", "synthetic": True},
            self.sources["model_a_postflop"]: {"model_type": "postflop_population", "synthetic": True},
            self.sources["hero_strategy"]: {"schema": "synthetic-hero-strategy/v1"},
            self.sources["hero_ranges"]: {"schema": "synthetic-hero-ranges/v1"},
            self.legacy_source: {"model_type": "preflop_population", "legacy_mixed": True},
        }.items():
            write_json(self.root / rel, payload)

        model_b_dir = self.root / self.sources["model_b"]
        model_b_dir.mkdir(parents=True, exist_ok=True)
        write_json(model_b_dir / "profiles.json", {"schema": "synthetic-model-b/v1"})

        engine = self.root / self.sources["engine"]
        engine.parent.mkdir(parents=True, exist_ok=True)
        engine.write_text("<html>synthetic engine</html>\n", encoding="utf-8")
        engine_sha = sha256_file(engine)
        write_json(
            self.root / self.sources["application_release"],
            {
                "schema": "poker-site-release/v3",
                "status": "promoted",
                "identity": {
                    "engine_release": {
                        "artifact": self.sources["engine"],
                        "sha256": engine_sha,
                    }
                },
            },
        )

        write_json(
            self.root / self.provenance_rel,
            {
                "schema": "synthetic-provenance/v1",
                "population_id": TARGET,
                "scientific_effect": "NONE_TEST_FIXTURE_ONLY",
            },
        )
        write_json(
            self.root / self.decision_rel,
            {
                "schema": "synthetic-scientific-decision/v1",
                "population_id": TARGET,
                "decision": "ADMISSIBLE_FOR_PACK",
                "scientific_effect": "NONE_TEST_FIXTURE_ONLY",
            },
        )
        write_json(
            self.root / self.fallback_rel,
            {
                "schema": "synthetic-fallback-authorization/v1",
                "scientific_effect": "NONE_TEST_FIXTURE_ONLY",
            },
        )

        identity_common = {
            "platform": "PokerStars",
            "variant": "NLHE",
            "game_kind": "cash",
            "stake": "100/200",
            "money": "play",
            "currency": "PLAY_CHIPS",
            "max_seats": 6,
            "rake": {"policy": "TEST"},
        }
        registry = {
            "schema": "poker-population-registry/v1",
            "default_population": TARGET,
            "populations": {
                TARGET: {
                    "status": "PROMOTED",
                    "identity": {**identity_common, "format": "ZOOM"},
                    "compatibility": {"legacy_unscoped_artifacts_allowed": False},
                    "data": {
                        "root": "data/target",
                        "snapshots_root": "data/target/snapshots",
                        "increments_root": "data/target/increments",
                    },
                    "storage": {
                        "runs_root": "runs/target",
                        "cache_namespace": TARGET,
                    },
                    "artifacts": {
                        "model_a_preflop": self.sources["model_a_preflop"],
                        "model_a_postflop": self.sources["model_a_postflop"],
                        "model_b": self.sources["model_b"],
                        "hero_strategy": self.sources["hero_strategy"],
                        "engine": self.sources["engine"],
                        "pack": None,
                    },
                    "promotion_history": [],
                },
                LEGACY: {
                    "status": "PROMOTED_LEGACY",
                    "identity": {**identity_common, "format": "MIXED_ZOOM_REGULAR"},
                    "compatibility": {"legacy_unscoped_artifacts_allowed": True},
                    "data": {
                        "root": "data/legacy",
                        "snapshots_root": "data/legacy/snapshots",
                        "increments_root": "data/legacy/increments",
                    },
                    "storage": {
                        "runs_root": "runs/legacy",
                        "cache_namespace": LEGACY,
                    },
                    "artifacts": {
                        "model_a_preflop": self.legacy_source,
                        "model_a_postflop": None,
                        "model_b": None,
                        "hero_strategy": None,
                        "engine": None,
                        "pack": None,
                    },
                    "promotion_history": [],
                },
            },
        }
        write_json(self.root / "training/populations/registry.json", registry)
        self.document = self._base_document()
        self.save()

    def _ref(self, rel: Path) -> dict:
        return {"path": rel.as_posix(), "sha256": sha256_file(self.root / rel)}

    def _base_document(self) -> dict:
        components = {}
        for role in REQUIRED_ROLES:
            rel = self.sources[role]
            kind, digest = content_identity(self.root / rel)
            components[role] = {
                "role": role,
                "population_id": TARGET,
                "source_path": rel,
                "hash_kind": kind,
                "sha256": digest,
                "provenance": {
                    "source_population_id": TARGET,
                    "evidence": self._ref(self.provenance_rel),
                },
                "lineage": {
                    "population_id": TARGET,
                    "format": "ZOOM",
                },
                "decision": {
                    "status": "ADMISSIBLE_FOR_PACK",
                    "issue": "#synthetic",
                    "evidence": self._ref(self.decision_rel),
                },
            }
        return {
            "schema": "poker-scientific-component-evidence-set/v1",
            "population_id": TARGET,
            "artifact_class": "TEST_ONLY",
            "scientific_effect": "NONE_TEST_FIXTURE_ONLY",
            "components": components,
        }

    def save(self) -> None:
        write_json(self.root / self.input_rel, self.document)

    def resolve(self) -> dict:
        self.save()
        return resolve_admission(
            self.input_rel,
            root=self.root,
            expected_population_id=TARGET,
        )


class PopulationPackAdmissionResolverTests(unittest.TestCase):
    def fixture(self, root: Path) -> AdmissionFixture:
        return AdmissionFixture(root)

    def test_exact_roles_are_admissible_and_candidate_is_deterministic_ready_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(Path(tmp))
            result = fx.resolve()

        self.assertEqual(result["schema"], "poker-scientific-component-admission/v1")
        self.assertTrue(all(result["admissions"][role]["status"] == ADMISSIBLE for role in REQUIRED_ROLES))
        self.assertTrue(
            all("ROLE_ADMISSIBLE_EXACT" in result["admissions"][role]["reason_codes"] for role in REQUIRED_ROLES)
        )
        self.assertEqual(result["candidate_contract"]["candidate_status"], "READY_FOR_ASSEMBLY")
        self.assertTrue(all(result["candidate_contract"]["components"][role] for role in REQUIRED_ROLES))
        self.assertFalse(result["safety"]["writes_performed"])
        self.assertFalse(result["safety"]["promotion"])

    def test_retain_reference_is_not_silently_promoted_to_candidate_admissibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(Path(tmp))
            fx.document["components"]["model_a_preflop"]["decision"]["status"] = "RETAIN_REFERENCE"
            result = fx.resolve()

        row = result["admissions"]["model_a_preflop"]
        self.assertEqual(row["status"], RETAIN_REFERENCE)
        self.assertIn("SCIENTIFIC_DECISION_RETAIN_REFERENCE", row["reason_codes"])
        self.assertIsNone(result["candidate_contract"]["components"]["model_a_preflop"])
        self.assertEqual(result["candidate_contract"]["candidate_status"], "BLOCKED_PENDING_SCIENTIFIC_DECISION")

    def test_explicit_rejected_artifact_is_terminal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(Path(tmp))
            fx.document["components"]["hero_strategy"]["decision"]["status"] = "REJECTED"
            result = fx.resolve()

        self.assertEqual(result["admissions"]["hero_strategy"]["status"], REJECTED)
        self.assertIn(
            "SCIENTIFIC_DECISION_REJECTED",
            result["admissions"]["hero_strategy"]["reason_codes"],
        )
        self.assertIsNone(result["candidate_contract"]["components"]["hero_strategy"])

    def test_wrong_population_and_wrong_role_are_incompatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(Path(tmp))
            fx.document["components"]["model_a_postflop"]["population_id"] = LEGACY
            fx.document["components"]["hero_ranges"]["role"] = "hero_strategy"
            result = fx.resolve()

        self.assertEqual(result["admissions"]["model_a_postflop"]["status"], INCOMPATIBLE)
        self.assertIn(
            "POPULATION_ID_MISMATCH",
            result["admissions"]["model_a_postflop"]["reason_codes"],
        )
        self.assertEqual(result["admissions"]["hero_ranges"]["status"], INCOMPATIBLE)
        self.assertIn("ROLE_IDENTITY_MISMATCH", result["admissions"]["hero_ranges"]["reason_codes"])

    def test_artifact_hash_and_provenance_hash_mismatches_are_incompatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(Path(tmp))
            fx.document["components"]["model_a_preflop"]["sha256"] = "0" * 64
            fx.document["components"]["model_a_postflop"]["provenance"]["evidence"]["sha256"] = "1" * 64
            result = fx.resolve()

        self.assertEqual(result["admissions"]["model_a_preflop"]["status"], INCOMPATIBLE)
        self.assertIn("ARTIFACT_HASH_MISMATCH", result["admissions"]["model_a_preflop"]["reason_codes"])
        self.assertEqual(result["admissions"]["model_a_postflop"]["status"], INCOMPATIBLE)
        self.assertIn(
            "PROVENANCE_EVIDENCE_HASH_MISMATCH",
            result["admissions"]["model_a_postflop"]["reason_codes"],
        )

    def test_legacy_mixed_source_cannot_be_silently_relabelled_zoom(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(Path(tmp))
            row = fx.document["components"]["model_a_preflop"]
            row["source_path"] = fx.legacy_source
            row["hash_kind"], row["sha256"] = content_identity(fx.root / fx.legacy_source)
            row["provenance"]["source_population_id"] = TARGET
            row["lineage"] = {"population_id": TARGET, "format": "ZOOM"}
            result = fx.resolve()

        admission = result["admissions"]["model_a_preflop"]
        self.assertEqual(admission["status"], INCOMPATIBLE)
        self.assertIn("LEGACY_MIXED_RELABEL_REJECTED", admission["reason_codes"])
        self.assertIsNone(result["candidate_contract"]["components"]["model_a_preflop"])

    def test_missing_role_and_issue_without_persisted_decision_evidence_are_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(Path(tmp))
            del fx.document["components"]["model_b"]
            fx.document["components"]["engine"]["decision"] = {
                "status": "ADMISSIBLE_FOR_PACK",
                "issue": "#closed-but-not-evidence",
            }
            result = fx.resolve()

        self.assertEqual(result["admissions"]["model_b"]["status"], UNRESOLVED)
        self.assertIn("ROLE_MISSING", result["admissions"]["model_b"]["reason_codes"])
        self.assertEqual(result["admissions"]["engine"]["status"], UNRESOLVED)
        self.assertIn(
            "DECISION_EVIDENCE_MISSING",
            result["admissions"]["engine"]["reason_codes"],
        )

    def test_same_persisted_input_produces_same_output_and_resolution_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = self.fixture(Path(tmp))
            first = fx.resolve()
            second = fx.resolve()

        self.assertEqual(first, second)
        self.assertEqual(first["resolution_sha256"], second["resolution_sha256"])
        self.assertEqual(
            first["preflight_input"]["candidate_contract_sha256"],
            second["preflight_input"]["candidate_contract_sha256"],
        )

    def test_candidate_output_feeds_existing_preflight_without_registry_side_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fx = self.fixture(root)
            result = fx.resolve()
            registry_path = root / "training/populations/registry.json"
            registry_before = registry_path.read_bytes()

            candidate_rel = Path("tmp/admission-candidate.json")
            candidate_path = root / candidate_rel
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_path.write_bytes(canonical_json_bytes(result["candidate_contract"]))

            self.assertEqual(
                hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
                result["preflight_input"]["candidate_contract_sha256"],
            )
            report = preflight(
                candidate_rel,
                root=root,
                expected_population_id=TARGET,
            )
            registry_after = registry_path.read_bytes()

        self.assertEqual(report["result"], "READY_FOR_ASSEMBLY")
        self.assertTrue(report["handoff"]["ready_without_new_logic"])
        self.assertTrue(report["safety"]["dry_run"])
        self.assertFalse(report["safety"]["writes_performed"])
        self.assertFalse(report["safety"]["population_registry_updates"])
        self.assertFalse(report["safety"]["release_publication"])
        self.assertFalse(report["safety"]["pack_activation"])
        self.assertEqual(registry_before, registry_after)


if __name__ == "__main__":
    unittest.main()
