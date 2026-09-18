#!/usr/bin/env python3
"""Validate a poker-population-pack/v1 archive without trusting its source tree."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import PurePosixPath
import zipfile

SCHEMA = "poker-population-pack/v1"
ZOOM_100_200_POPULATION = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
CANDIDATE_SCHEMA = "poker-population-pack-candidate/v1"
READY_STATUS = "READY_FOR_ASSEMBLY"
TEST_READY_STATUS = "TEST_ONLY_READY_FOR_INTEGRATION"
ADMISSIBLE_DECISION = "ADMISSIBLE_FOR_PACK"
TEST_DECISION = "TEST_ONLY_INTEGRATION"
EXPLICIT_FALLBACK = "EXPLICITLY_AUTHORIZED_FOR_PACK"
REQUIRED_ROLES = {
    "model_a_preflop", "model_a_postflop", "model_b", "hero_strategy",
    "engine", "hero_ranges", "application_release",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def _validate_assembly_contract(manifest: dict, *, test_only: bool) -> None:
    assembly = manifest.get("assembly_contract")
    if not isinstance(assembly, dict):
        raise ValueError("scoped pack is missing assembly_contract")
    if assembly.get("schema") != CANDIDATE_SCHEMA:
        raise ValueError("unsupported assembly_contract schema")
    expected_status = TEST_READY_STATUS if test_only else READY_STATUS
    if assembly.get("candidate_status") != expected_status:
        raise ValueError(f"assembly_contract is not {expected_status}")
    if assembly.get("population_id") != manifest.get("population_id"):
        raise ValueError("assembly_contract population mismatch")
    contract = assembly.get("contract")
    if not isinstance(contract, dict) or not contract.get("path"):
        raise ValueError("assembly_contract source identity missing")
    if not _valid_sha256(contract.get("sha256")):
        raise ValueError("assembly_contract source hash invalid")
    components = assembly.get("components")
    if not isinstance(components, dict):
        raise ValueError("assembly_contract components missing")
    for role in REQUIRED_ROLES:
        component = components.get(role)
        if not isinstance(component, dict):
            raise ValueError(f"assembly_contract unresolved role: {role}")
        if component.get("role") != role:
            raise ValueError(f"assembly_contract role mismatch: {role}")
        if component.get("population_id") != manifest.get("population_id"):
            raise ValueError(f"assembly_contract population mismatch: {role}")
        if not _valid_sha256(component.get("sha256")):
            raise ValueError(f"assembly_contract component hash invalid: {role}")
        provenance = component.get("provenance")
        if not isinstance(provenance, dict) or not provenance.get("source_population_id"):
            raise ValueError(f"assembly_contract provenance missing: {role}")
        source_population = provenance.get("source_population_id")
        if test_only:
            if component.get("artifact_class") != "TEST_ONLY" or component.get("non_publishable") is not True:
                raise ValueError(f"assembly_contract TEST_ONLY classification missing: {role}")
            if source_population != manifest.get("population_id"):
                raise ValueError(f"TEST_ONLY component belongs to another population: {role}")
            decision = component.get("decision")
            if not isinstance(decision, dict) or decision.get("status") != TEST_DECISION:
                raise ValueError(f"TEST_ONLY decision invalid: {role}")
        else:
            if source_population != manifest.get("population_id"):
                fallback = provenance.get("cross_population_fallback")
                if not isinstance(fallback, dict) or fallback.get("status") != EXPLICIT_FALLBACK:
                    raise ValueError(f"assembly_contract silent cross-population fallback: {role}")
            decision = component.get("decision")
            if not isinstance(decision, dict) or decision.get("status") != ADMISSIBLE_DECISION:
                raise ValueError(f"assembly_contract decision not admissible: {role}")


def validate(zip_path: str) -> dict:
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if not names:
            raise ValueError("empty pack archive")
        roots = {PurePosixPath(name).parts[0] for name in names if PurePosixPath(name).parts}
        if len(roots) != 1:
            raise ValueError("pack must have exactly one archive root")
        root = next(iter(roots))
        for name in names:
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts:
                raise ValueError(f"unsafe archive path: {name}")
            rel = PurePosixPath(*p.parts[1:])
            if rel.parts[:2] == ("training", "datasets") or (rel.parts and rel.parts[0] == "hand_histories"):
                raise ValueError(f"hand-history/training dataset leaked into distribution pack: {name}")

        manifest_name = f"{root}/MANIFEST.json"
        checksums_name = f"{root}/CHECKSUMS.sha256"
        if manifest_name not in names or checksums_name not in names:
            raise ValueError("MANIFEST.json or CHECKSUMS.sha256 missing")
        manifest = json.loads(zf.read(manifest_name))
        if manifest.get("schema") != SCHEMA:
            raise ValueError("unsupported pack manifest schema")
        if manifest.get("coherency") != "inseparable_population_pack":
            raise ValueError("pack is not marked inseparable")
        distribution_class = manifest.get("distribution_class", "PRODUCTION")
        if distribution_class not in {"PRODUCTION", "TEST_ONLY"}:
            raise ValueError("unsupported pack distribution_class")
        test_only = distribution_class == "TEST_ONLY"
        if test_only:
            if manifest.get("test_only") is not True or manifest.get("non_publishable") is not True:
                raise ValueError("TEST_ONLY pack must be explicitly NON_PUBLISHABLE")
            if manifest.get("population_status") != "TEST_ONLY":
                raise ValueError("TEST_ONLY pack must not claim a promoted population status")
            policy = manifest.get("publication_policy")
            required_false = ("release_allowed", "catalog_eligible", "recommended", "default", "registry_promotion_allowed", "production_activation_allowed")
            if not isinstance(policy, dict) or any(policy.get(flag) is not False for flag in required_false):
                raise ValueError("TEST_ONLY publication policy is not fail-closed")
            if manifest.get("recommended") is True or manifest.get("default") is True:
                raise ValueError("TEST_ONLY pack cannot be recommended/default")
            if manifest.get("release", {}).get("publishable") is not False:
                raise ValueError("TEST_ONLY release must be non-publishable")
            _validate_assembly_contract(manifest, test_only=True)
        else:
            if manifest.get("population_status") not in {"PROMOTED", "PROMOTED_LEGACY"}:
                raise ValueError("pack population is not an accepted promoted state")
            if (
                manifest.get("population_status") == "PROMOTED"
                and manifest.get("population_id") == ZOOM_100_200_POPULATION
            ):
                _validate_assembly_contract(manifest, test_only=False)
        if manifest.get("release", {}).get("immutable") is not True:
            raise ValueError("release is not immutable")
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError("manifest artifacts missing")
        roles = {role for item in artifacts for role in item.get("roles", [])}
        missing = REQUIRED_ROLES - roles
        if missing:
            raise ValueError(f"missing required roles: {sorted(missing)}")
        for item in artifacts:
            rel = str(item["path"])
            archive_name = f"{root}/{rel}"
            if archive_name not in names:
                raise ValueError(f"manifest file missing from archive: {rel}")
            payload = zf.read(archive_name)
            if sha256(payload) != item["sha256"]:
                raise ValueError(f"artifact hash mismatch: {rel}")
            if len(payload) != int(item["size_bytes"]):
                raise ValueError(f"artifact size mismatch: {rel}")

        if test_only:
            compatibility = manifest.get("compatibility")
            if not isinstance(compatibility, dict):
                raise ValueError("TEST_ONLY compatibility contract missing")
            engine_items = [item for item in artifacts if "engine" in item.get("roles", [])]
            app_items = [item for item in artifacts if "application_release" in item.get("roles", [])]
            if len(engine_items) != 1 or len(app_items) != 1:
                raise ValueError("TEST_ONLY engine/application role cardinality invalid")
            engine_item, app_item = engine_items[0], app_items[0]
            if compatibility.get("engine_path") != engine_item["path"]:
                raise ValueError("TEST_ONLY engine path mismatch")
            if compatibility.get("engine_sha256") != engine_item["sha256"]:
                raise ValueError("TEST_ONLY engine hash mismatch")
            if compatibility.get("application_release_path") != app_item["path"]:
                raise ValueError("TEST_ONLY application release path mismatch")
            if compatibility.get("application_release_sha256") != app_item["sha256"]:
                raise ValueError("TEST_ONLY application release hash mismatch")
            app_payload = json.loads(zf.read(f"{root}/{app_item['path']}"))
            if app_payload.get("schema") != "poker-site-release/v3":
                raise ValueError("TEST_ONLY application release schema incompatible")
            if app_payload.get("artifact_class") != "TEST_ONLY" or app_payload.get("non_publishable") is not True:
                raise ValueError("TEST_ONLY application release classification missing")
            if app_payload.get("version") != compatibility.get("engine_version"):
                raise ValueError("TEST_ONLY application release version incompatible")
            if app_payload.get("status") != "test_only":
                raise ValueError("TEST_ONLY application release must not claim promoted status")
            engine_identity = (app_payload.get("identity") or {}).get("engine_release") or {}
            expected_engine_name = PurePosixPath(engine_item["path"]).name
            if engine_identity.get("artifact") != expected_engine_name:
                raise ValueError("TEST_ONLY application release engine artifact mismatch")
            if engine_identity.get("sha256") != engine_item["sha256"]:
                raise ValueError("TEST_ONLY application release engine hash mismatch")

        for line in zf.read(checksums_name).decode("utf-8").splitlines():
            expected, rel = line.split("  ", 1)
            archive_name = f"{root}/{rel}"
            if archive_name not in names:
                raise ValueError(f"checksum target missing: {rel}")
            if sha256(zf.read(archive_name)) != expected:
                raise ValueError(f"checksum mismatch: {rel}")
        return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    args = parser.parse_args()
    manifest = validate(args.archive)
    print(json.dumps({
        "pack_id": manifest["pack_id"],
        "pack_version": manifest["pack_version"],
        "population_id": manifest["population_id"],
        "distribution_class": manifest.get("distribution_class", "PRODUCTION"),
        "release_tag": manifest["release"]["tag"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
