#!/usr/bin/env python3
"""Validate a poker-population-pack/v1 archive without trusting its source tree."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import PurePosixPath
import zipfile

SCHEMA = "poker-population-pack/v1"
REQUIRED_ROLES = {
    "model_a_preflop", "model_a_postflop", "model_b", "hero_strategy",
    "engine", "hero_ranges", "application_release",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
        if manifest.get("population_status") not in {"PROMOTED", "PROMOTED_LEGACY"}:
            raise ValueError("pack population is not an accepted promoted state")
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
        "release_tag": manifest["release"]["tag"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
