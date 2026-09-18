import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.population_pack_candidate import sha256_file, sha256_tree
from tools.population_pack_preflight import (
    DEFAULT_CONTRACT,
    ROOT,
    TARGET_POPULATION,
    preflight,
)


class PopulationPackPreflightTests(unittest.TestCase):
    def test_current_zoom_candidate_reports_precise_blocked_state(self):
        result = preflight(DEFAULT_CONTRACT)

        self.assertEqual(result["schema"], "poker-population-pack-preflight/v1")
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["population"]["population_id"], TARGET_POPULATION)
        self.assertEqual(result["population"]["status"], "CERTIFIED_DATA_ONLY")
        self.assertEqual(
            result["candidate"]["candidate_status"],
            "BLOCKED_PENDING_SCIENTIFIC_DECISION",
        )
        self.assertIn("#108", result["candidate"]["declared_blocked_on"])
        self.assertEqual(result["engine_compatibility"]["status"], "BLOCKED")

        for role, row in result["components"].items():
            self.assertEqual(row["role"], role)
            self.assertEqual(row["availability"], "UNRESOLVED")
            self.assertFalse(row["hash"]["verified"])
            self.assertFalse(row["scientific_status"]["admissible"])

        codes = {row["code"] for row in result["blockers"]}
        self.assertIn("COMPONENT_UNRESOLVED", codes)
        self.assertIn("CANDIDATE_STATUS_NOT_READY", codes)
        self.assertIn("POPULATION_STATUS_NOT_PROMOTED", codes)
        self.assertIn("DECLARED_EXTERNAL_BLOCKER", codes)
        self.assertTrue(all(value is False for key, value in result["safety"].items() if key != "dry_run"))
        self.assertTrue(result["safety"]["dry_run"])
        self.assertFalse(result["handoff"]["ready_without_new_logic"])

    def test_silent_mixed_legacy_relabel_is_explicitly_rejected(self):
        doc = copy.deepcopy(json.loads((ROOT / DEFAULT_CONTRACT).read_text(encoding="utf-8")))
        legacy_engine_rel = "user/releases/poker_range_equity_offline_multiway_v83.html"
        registry_rel = "training/populations/registry.json"
        registry_path = ROOT / registry_rel
        doc["components"]["engine"] = {
            "role": "engine",
            "population_id": TARGET_POPULATION,
            "source_path": legacy_engine_rel,
            "hash_kind": "file_sha256",
            "sha256": sha256_file(ROOT / legacy_engine_rel),
            "provenance": {
                "source_population_id": TARGET_POPULATION,
                "evidence": {
                    "path": registry_rel,
                    "sha256": sha256_file(registry_path),
                },
            },
            "decision": {
                "status": "ADMISSIBLE_FOR_PACK",
                "issue": "#108",
                "evidence": {
                    "path": registry_rel,
                    "sha256": sha256_file(registry_path),
                },
            },
        }

        with tempfile.TemporaryDirectory(dir=ROOT / "tests/packs") as tmp:
            path = Path(tmp) / "candidate.json"
            path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
            result = preflight(path.relative_to(ROOT))

        engine = result["components"]["engine"]
        self.assertEqual(engine["availability"], "INVALID")
        self.assertTrue(
            any(
                owner["format"] == "MIXED_ZOOM_REGULAR"
                for owner in engine["registered_source_owners"]
            )
        )
        self.assertIn(
            "LEGACY_MIXED_RELABEL_REJECTED",
            {row["code"] for row in engine["blockers"]},
        )
        self.assertEqual(result["result"], "BLOCKED")

    def test_fully_admitted_scoped_components_are_ready_without_new_logic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "training/populations").mkdir(parents=True)
            (root / "artifacts/model_b").mkdir(parents=True)
            (root / "evidence").mkdir(parents=True)
            (root / "user/packs/zoom").mkdir(parents=True)

            files = {
                "model_a_preflop": "artifacts/model_a_preflop.json",
                "model_a_postflop": "artifacts/model_a_postflop.json",
                "hero_strategy": "artifacts/hero_strategy.json",
                "engine": "artifacts/engine.html",
                "hero_ranges": "artifacts/hero_ranges.json",
            }
            for role, rel in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"role": role}) + "\n", encoding="utf-8")

            (root / "artifacts/model_b/profiles.json").write_text(
                json.dumps({"schema": "test-model-b"}) + "\n",
                encoding="utf-8",
            )
            evidence_rel = "evidence/admission.json"
            (root / evidence_rel).write_text(
                json.dumps({"decision": "ADMISSIBLE_FOR_PACK"}) + "\n",
                encoding="utf-8",
            )
            evidence_sha = sha256_file(root / evidence_rel)

            engine_rel = files["engine"]
            engine_sha = sha256_file(root / engine_rel)
            app_rel = "artifacts/RELEASE.json"
            (root / app_rel).write_text(
                json.dumps(
                    {
                        "schema": "poker-site-release/v3",
                        "status": "promoted",
                        "identity": {
                            "engine_release": {
                                "artifact": engine_rel,
                                "sha256": engine_sha,
                            }
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            identity = {
                "platform": "PokerStars",
                "variant": "NLHE",
                "game_kind": "cash",
                "stake": "100/200",
                "money": "play",
                "currency": "PLAY_CHIPS",
                "format": "ZOOM",
                "max_seats": 6,
                "rake": {"policy": "TEST"},
            }
            registry = {
                "schema": "poker-population-registry/v1",
                "default_population": TARGET_POPULATION,
                "populations": {
                    TARGET_POPULATION: {
                        "status": "PROMOTED",
                        "identity": identity,
                        "compatibility": {
                            "legacy_unscoped_artifacts_allowed": False,
                        },
                        "data": {
                            "root": "data",
                            "snapshots_root": "data/snapshots",
                            "increments_root": "data/increments",
                        },
                        "storage": {
                            "runs_root": "runs",
                            "cache_namespace": TARGET_POPULATION,
                        },
                        "artifacts": {
                            "model_a_preflop": files["model_a_preflop"],
                            "model_a_postflop": files["model_a_postflop"],
                            "model_b": "artifacts/model_b",
                            "hero_strategy": files["hero_strategy"],
                            "engine": engine_rel,
                            "pack": None,
                        },
                        "promotion_history": [],
                    }
                },
            }
            (root / "training/populations/registry.json").write_text(
                json.dumps(registry, indent=2) + "\n",
                encoding="utf-8",
            )

            component_sources = {
                "model_a_preflop": (files["model_a_preflop"], "file_sha256"),
                "model_a_postflop": (files["model_a_postflop"], "file_sha256"),
                "model_b": ("artifacts/model_b", "tree_sha256"),
                "hero_strategy": (files["hero_strategy"], "file_sha256"),
                "engine": (engine_rel, "file_sha256"),
                "hero_ranges": (files["hero_ranges"], "file_sha256"),
                "application_release": (app_rel, "file_sha256"),
            }
            components = {}
            for role, (rel, kind) in component_sources.items():
                digest = (
                    sha256_tree(root / rel)
                    if kind == "tree_sha256"
                    else sha256_file(root / rel)
                )
                components[role] = {
                    "role": role,
                    "population_id": TARGET_POPULATION,
                    "source_path": rel,
                    "hash_kind": kind,
                    "sha256": digest,
                    "provenance": {
                        "source_population_id": TARGET_POPULATION,
                        "evidence": {
                            "path": evidence_rel,
                            "sha256": evidence_sha,
                        },
                    },
                    "decision": {
                        "status": "ADMISSIBLE_FOR_PACK",
                        "issue": "#108",
                        "evidence": {
                            "path": evidence_rel,
                            "sha256": evidence_sha,
                        },
                    },
                }

            contract = {
                "schema": "poker-population-pack-candidate/v1",
                "candidate_id": f"{TARGET_POPULATION}@test-ready",
                "candidate_status": "READY_FOR_ASSEMBLY",
                "population_id": TARGET_POPULATION,
                "blocked_on": [],
                "publication_policy": {
                    "release_allowed": False,
                    "catalog_eligible": False,
                    "recommended": False,
                    "default": False,
                },
                "required_roles": [
                    "model_a_preflop",
                    "model_a_postflop",
                    "model_b",
                    "hero_strategy",
                    "engine",
                    "hero_ranges",
                    "application_release",
                ],
                "components": components,
            }
            contract_rel = Path("user/packs/zoom/candidate.json")
            (root / contract_rel).write_text(
                json.dumps(contract, indent=2) + "\n",
                encoding="utf-8",
            )

            result = preflight(contract_rel, root=root)

        self.assertEqual(result["result"], "READY_FOR_ASSEMBLY")
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["engine_compatibility"]["status"], "COMPATIBLE")
        self.assertTrue(
            all(
                row["availability"] == "AVAILABLE"
                for row in result["components"].values()
            )
        )
        self.assertTrue(result["handoff"]["ready_without_new_logic"])
        self.assertEqual(
            result["handoff"]["candidate_contract_config_field"],
            "candidate_contract",
        )
        self.assertTrue(result["safety"]["dry_run"])
        self.assertFalse(result["safety"]["release_publication"])
        self.assertFalse(result["safety"]["pack_activation"])


if __name__ == "__main__":
    unittest.main()
