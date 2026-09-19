from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.build_population_pack import PackError, build
from tools.build_user_artifact_bundle import FIXED_ZIP_TIME
from tools.validate_population_pack import REQUIRED_ROLES, validate
from tools.write_pack_catalog import assert_public_catalog_entry, build_catalog
from tests.packs.synthetic_pack_fixture import (
    ROOT,
    TARGET_POPULATION,
    build_test_only_archive,
    fixture_spec,
    runtime_entry,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rewrite_archive(source: Path, destination: Path, *, mutate_manifest=None, mutate_members=None) -> Path:
    with zipfile.ZipFile(source) as zf:
        members = {name: zf.read(name) for name in zf.namelist()}
    root = next(iter({name.split("/", 1)[0] for name in members}))
    manifest_name = f"{root}/MANIFEST.json"
    checksums_name = f"{root}/CHECKSUMS.sha256"
    manifest = json.loads(members[manifest_name])

    if mutate_members:
        mutate_members(members, manifest, root)
    if mutate_manifest:
        mutate_manifest(manifest)

    members[manifest_name] = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    lines = []
    for name in sorted(members):
        if name == checksums_name:
            continue
        rel = name.split("/", 1)[1]
        lines.append(f"{_sha(members[name])}  {rel}\n")
    members[checksums_name] = "".join(lines).encode("utf-8")

    with zipfile.ZipFile(destination, "w") as zf:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(
                info,
                members[name],
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    return destination


class SyntheticPopulationPackIntegrationTests(unittest.TestCase):
    def _build(self, directory: Path) -> tuple[Path, dict]:
        return build_test_only_archive(directory)

    def test_reproducible_build_manifest_and_file_order(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            zip_a, manifest_a = self._build(Path(a))
            zip_b, manifest_b = self._build(Path(b))
            self.assertEqual(zip_a.read_bytes(), zip_b.read_bytes())
            self.assertEqual(_sha(zip_a.read_bytes()), _sha(zip_b.read_bytes()))
            self.assertEqual(manifest_a, manifest_b)
            with zipfile.ZipFile(zip_a) as zf:
                self.assertEqual(zf.namelist(), sorted(zf.namelist()))
                manifest_from_zip = json.loads(
                    zf.read(next(n for n in zf.namelist() if n.endswith("/MANIFEST.json")))
                )
            self.assertEqual(manifest_from_zip, manifest_a)

    def test_complete_test_only_pack_validates_all_roles_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive, _ = self._build(Path(tmp))
            manifest = validate(str(archive))

        self.assertEqual(manifest["distribution_class"], "TEST_ONLY")
        self.assertTrue(manifest["test_only"])
        self.assertTrue(manifest["non_publishable"])
        self.assertEqual(manifest["population_id"], TARGET_POPULATION)
        self.assertEqual(manifest["population_status"], "TEST_ONLY")
        self.assertFalse(manifest["recommended"])
        self.assertFalse(manifest["default"])
        self.assertTrue(all(value is False for value in manifest["publication_policy"].values()))

        components = manifest["assembly_contract"]["components"]
        self.assertEqual(set(components), REQUIRED_ROLES)
        for role, component in components.items():
            self.assertEqual(component["role"], role)
            self.assertEqual(component["artifact_class"], "TEST_ONLY")
            self.assertTrue(component["non_publishable"])
            self.assertEqual(component["population_id"], TARGET_POPULATION)
            self.assertEqual(component["provenance"]["source_population_id"], TARGET_POPULATION)
            self.assertEqual(component["provenance"]["kind"], "synthetic_integration_fixture")
            self.assertEqual(component["decision"]["status"], "TEST_ONLY_INTEGRATION")
            self.assertEqual(component["decision"]["scientific_effect"], "NONE_TEST_FIXTURE_ONLY")
            self.assertRegex(component["sha256"], r"^[0-9a-f]{64}$")
            self.assertNotIn("legacy", component["source_path"].lower())

    def test_production_builder_and_public_catalog_reject_test_only(self):
        entry, _ = runtime_entry()
        with self.assertRaisesRegex(ValueError, "TEST_ONLY"):
            assert_public_catalog_entry(entry)

        catalog = build_catalog()
        self.assertNotIn(TARGET_POPULATION, {row["population_id"] for row in catalog["entries"]})

        registry = ROOT / "training/populations/registry.json"
        before = _sha(registry.read_bytes())
        with tempfile.TemporaryDirectory(dir=ROOT / "tests/packs") as tmp:
            cfg = Path(tmp) / "test-only-pack.json"
            cfg.write_text(
                json.dumps(
                    {
                        "schema": "poker-population-pack-config/v1",
                        "distribution_class": "TEST_ONLY",
                        "test_only": True,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PackError, "cannot use the production pack builder"):
                build(cfg, Path(tmp) / "out")
        self.assertEqual(_sha(registry.read_bytes()), before)

    def test_wrong_engine_version_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive, _ = self._build(tmp / "base")
            bad = _rewrite_archive(
                archive,
                tmp / "bad-engine.zip",
                mutate_manifest=lambda m: m["compatibility"].__setitem__("engine_version", "wrong-engine"),
            )
            with self.assertRaisesRegex(ValueError, "application release version incompatible"):
                validate(str(bad))

    def test_wrong_application_release_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive, _ = self._build(tmp / "base")

            def mutate_members(members, manifest, root):
                app_item = next(a for a in manifest["artifacts"] if "application_release" in a["roles"])
                name = f"{root}/{app_item['path']}"
                app = json.loads(members[name])
                app["schema"] = "wrong-release-schema/v1"
                payload = (json.dumps(app, indent=2, sort_keys=True) + "\n").encode()
                members[name] = payload
                app_item["sha256"] = _sha(payload)
                app_item["size_bytes"] = len(payload)
                manifest["compatibility"]["application_release_sha256"] = _sha(payload)

            bad = _rewrite_archive(archive, tmp / "bad-app.zip", mutate_members=mutate_members)
            with self.assertRaisesRegex(ValueError, "application release schema incompatible"):
                validate(str(bad))

    def test_population_id_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive, _ = self._build(tmp / "base")
            bad = _rewrite_archive(
                archive,
                tmp / "bad-population.zip",
                mutate_manifest=lambda m: m.__setitem__("population_id", "other_population"),
            )
            with self.assertRaisesRegex(ValueError, "assembly_contract population mismatch"):
                validate(str(bad))

    def test_component_from_other_population_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive, _ = self._build(tmp / "base")

            def mutate(m):
                m["assembly_contract"]["components"]["model_b"]["population_id"] = "legacy_mixed_population"

            bad = _rewrite_archive(archive, tmp / "foreign-component.zip", mutate_manifest=mutate)
            with self.assertRaisesRegex(ValueError, "population mismatch: model_b"):
                validate(str(bad))

    def test_missing_role_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive, _ = self._build(tmp / "base")

            def mutate(m):
                del m["assembly_contract"]["components"]["hero_strategy"]

            bad = _rewrite_archive(archive, tmp / "missing-role.zip", mutate_manifest=mutate)
            with self.assertRaisesRegex(ValueError, "unresolved role: hero_strategy"):
                validate(str(bad))

    def test_invalid_hash_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive, _ = self._build(tmp / "base")

            def mutate(m):
                item = next(a for a in m["artifacts"] if "hero_ranges" in a["roles"])
                item["sha256"] = "0" * 64

            bad = _rewrite_archive(archive, tmp / "bad-hash.zip", mutate_manifest=mutate)
            with self.assertRaisesRegex(ValueError, "artifact hash mismatch"):
                validate(str(bad))

    def test_missing_provenance_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive, _ = self._build(tmp / "base")

            def mutate(m):
                del m["assembly_contract"]["components"]["engine"]["provenance"]

            bad = _rewrite_archive(archive, tmp / "missing-provenance.zip", mutate_manifest=mutate)
            with self.assertRaisesRegex(ValueError, "provenance missing: engine"):
                validate(str(bad))

    def test_non_admissible_scientific_decision_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive, _ = self._build(tmp / "base")

            def mutate(m):
                m["assembly_contract"]["components"]["model_a_preflop"]["decision"]["status"] = "ADMISSIBLE_FOR_PACK"

            bad = _rewrite_archive(archive, tmp / "scientific-status.zip", mutate_manifest=mutate)
            with self.assertRaisesRegex(ValueError, "TEST_ONLY decision invalid"):
                validate(str(bad))

    def test_publishable_or_recommended_test_fixture_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive, _ = self._build(tmp / "base")

            def mutate(m):
                m["publication_policy"]["recommended"] = True
                m["recommended"] = True
                m["release"]["publishable"] = True

            bad = _rewrite_archive(archive, tmp / "publishable.zip", mutate_manifest=mutate)
            with self.assertRaisesRegex(ValueError, "publication policy is not fail-closed"):
                validate(str(bad))


if __name__ == "__main__":
    unittest.main()
