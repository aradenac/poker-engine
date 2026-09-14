#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

EXPECTED_CUSTOM_SHA256 = "1248258112562757e49df545e97f9e54b2dde163fdc755adf0029e89e580e8cb"
EXPECTED_ROLES = {"custom_ranges", "preflop_population", "postflop_population"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("archive")
    args = ap.parse_args()
    archive = Path(args.archive)
    if not archive.is_file():
        raise SystemExit(f"bundle archive missing: {archive}")

    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        roots = {name.split("/", 1)[0] for name in names if "/" in name}
        if len(roots) != 1:
            raise SystemExit(f"bundle must contain exactly one root directory: {sorted(roots)}")
        root = next(iter(roots))
        required = {
            "custom.json",
            "preflop_population_model_v5.json",
            "postflop_population_model_v5.json",
            "MANIFEST.json",
            "README.md",
            "CHECKSUMS.sha256",
        }
        present = {name[len(root) + 1:] for name in names if name.startswith(root + "/") and not name.endswith("/")}
        if present != required:
            raise SystemExit(f"unexpected bundle file set: {sorted(present)}")

        def read(name: str) -> bytes:
            return zf.read(f"{root}/{name}")

        manifest = json.loads(read("MANIFEST.json").decode("utf-8"))
        if manifest.get("schema") != "poker-user-artifact-bundle/v1":
            raise SystemExit("unexpected bundle manifest schema")
        if manifest.get("population") != "NLHE 100-200":
            raise SystemExit("bundle population mismatch")
        if manifest.get("coherency") != "inseparable_set":
            raise SystemExit("bundle coherency marker missing")
        if manifest.get("training_state", {}).get("cycle") != "2026-09-12":
            raise SystemExit("bundle training cycle mismatch")
        if manifest.get("training_state", {}).get("gate_status") != "PASS":
            raise SystemExit("bundle training state is not accepted")
        if manifest.get("release", {}).get("immutable") is not True:
            raise SystemExit("bundle is not marked immutable")

        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list) or {x.get("role") for x in artifacts} != EXPECTED_ROLES:
            raise SystemExit("bundle artifact roles mismatch")
        for item in artifacts:
            filename = item.get("filename")
            if filename not in required:
                raise SystemExit(f"manifest references unexpected file: {filename}")
            actual = read(filename)
            if sha256(actual) != item.get("sha256"):
                raise SystemExit(f"manifest hash mismatch: {filename}")
            if len(actual) != item.get("size_bytes"):
                raise SystemExit(f"manifest size mismatch: {filename}")

        if sha256(read("custom.json")) != EXPECTED_CUSTOM_SHA256:
            raise SystemExit("custom.json is not the exact user range-folder export")
        custom = json.loads(read("custom.json").decode("utf-8"))
        if custom.get("schemaVersion") != 1 or custom.get("exportType") != "range-folder":
            raise SystemExit("custom.json range-folder contract mismatch")

        checksums: dict[str, str] = {}
        for line in read("CHECKSUMS.sha256").decode("utf-8").splitlines():
            digest, filename = line.split("  ", 1)
            checksums[filename] = digest
        for filename in required - {"CHECKSUMS.sha256"}:
            if checksums.get(filename) != sha256(read(filename)):
                raise SystemExit(f"checksum file mismatch: {filename}")

    print(json.dumps({
        "status": "PASS",
        "archive": str(archive),
        "bundle_id": manifest["bundle_id"],
        "bundle_version": manifest["bundle_version"],
        "population": manifest["population"],
        "training_cycle": manifest["training_state"]["cycle"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
