#!/usr/bin/env python3
"""Build the immutable user-facing NLHE 100-200 artifact bundle.

The bundle is intentionally derived only from the closed training-cycle
FINAL_STATE plus the exact user range-folder export. Rejected/experimental
artifacts cannot be selected by this builder.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "user/artifacts/NLHE_100-200/bundle.json"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob_sha(path: Path) -> str:
    return subprocess.check_output(
        ["git", "hash-object", str(path.relative_to(ROOT))], cwd=ROOT, text=True
    ).strip()


def git_commit() -> str:
    override = os.environ.get("BUNDLE_SOURCE_COMMIT")
    if override:
        return override
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def observed_json_metadata(data: bytes) -> dict:
    obj = json.loads(data.decode("utf-8"))
    if not isinstance(obj, dict):
        return {}
    keys = ("schema", "schemaVersion", "schema_version", "version", "model_version", "exportType")
    out = {}
    for key in keys:
        value = obj.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            if key in obj:
                out[key] = value
    return out


def deterministic_zip(zip_path: Path, bundle_name: str, files: list[Path]) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as zf:
        for path in sorted(files, key=lambda p: p.name):
            info = zipfile.ZipInfo(f"{bundle_name}/{path.name}", FIXED_ZIP_TIME)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build(out_dir: Path) -> Path:
    cfg = load_json(CONFIG_PATH)
    require(cfg.get("schema") == "poker-user-artifact-bundle-config/v1", "unexpected bundle config schema")
    require(cfg.get("population") == "NLHE 100-200", "bundle config population must be NLHE 100-200")

    final_state_path = ROOT / cfg["training_state"]
    final_state = load_json(final_state_path)
    require(final_state.get("schema") == "poker-training-cycle-final-state/v1", "unexpected FINAL_STATE schema")
    require(final_state.get("source_state", {}).get("population") == cfg["population"], "FINAL_STATE population mismatch")
    require(final_state.get("gate", {}).get("status") == "PASS", "FINAL_STATE gate is not PASS")
    require(final_state.get("gate", {}).get("promotion_ready") is True, "FINAL_STATE is not promotion-ready")

    production = final_state["production_state"]
    pre = production["model_a_preflop"]
    post = production["model_a_postflop"]
    engine = production["engine"]

    pre_path = ROOT / pre["path"]
    post_path = ROOT / post["path"]
    engine_path = ROOT / engine["path"]
    for p in (pre_path, post_path, engine_path):
        require(p.is_file(), f"required promoted artifact missing: {p.relative_to(ROOT)}")

    require(sha256_file(pre_path) == pre["sha256"], "promoted preflop model hash mismatch")
    require(sha256_file(post_path) == post["sha256"], "promoted postflop model hash mismatch")
    require(sha256_file(engine_path) == engine["sha256"], "promoted engine hash mismatch")

    registry_path = ROOT / "training/registry.json"
    expected_registry_blob = final_state["rollback"]["registry_git_blob_sha"]
    require(git_blob_sha(registry_path) == expected_registry_blob, "registry identity differs from closed training state")

    custom_cfg = cfg["custom_ranges"]
    encoded_path = ROOT / custom_cfg["source"]
    encoded = encoded_path.read_text(encoding="utf-8").strip()
    compressed = base64.b64decode(encoded, validate=True)
    require(sha256_bytes(compressed) == custom_cfg["compressed_sha256"], "compressed custom range source hash mismatch")
    custom = gzip.decompress(compressed)
    require(sha256_bytes(custom) == custom_cfg["sha256"], "custom.json source hash mismatch")
    custom_obj = json.loads(custom.decode("utf-8"))
    require(custom_obj.get("schemaVersion") == 1, "custom.json schemaVersion mismatch")
    require(custom_obj.get("exportType") == "range-folder", "custom.json must remain a range-folder export")

    bundle_name = f"nlhe-100-200-user-artifacts-{cfg['bundle_version']}"
    bundle_dir = out_dir / bundle_name
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True)

    custom_path = bundle_dir / custom_cfg["filename"]
    pre_out = bundle_dir / "preflop_population_model_v5.json"
    post_out = bundle_dir / "postflop_population_model_v5.json"
    custom_path.write_bytes(custom)
    shutil.copyfile(pre_path, pre_out)
    shutil.copyfile(post_path, post_out)

    source_commit = git_commit()
    final_state_sha256 = sha256_file(final_state_path)
    manifest = {
        "schema": "poker-user-artifact-bundle/v1",
        "bundle_id": cfg["bundle_id"],
        "bundle_version": cfg["bundle_version"],
        "population": cfg["population"],
        "coherency": "inseparable_set",
        "source_commit": source_commit,
        "training_state": {
            "cycle": final_state["cycle"],
            "path": cfg["training_state"],
            "sha256": final_state_sha256,
            "gate_status": final_state["gate"]["status"],
            "production_transition": final_state["production_transition"]["type"],
            "registry_git_blob_sha": expected_registry_blob,
        },
        "engine_compatibility": {
            "path": engine["path"],
            "sha256": engine["sha256"],
        },
        "artifacts": [
            {
                "filename": custom_path.name,
                "role": "custom_ranges",
                "sha256": sha256_file(custom_path),
                "size_bytes": custom_path.stat().st_size,
                "metadata": observed_json_metadata(custom_path.read_bytes()),
                "source_semantics": "user range-folder export; preserved byte-for-byte after deterministic source decompression",
            },
            {
                "filename": pre_out.name,
                "role": "preflop_population",
                "sha256": sha256_file(pre_out),
                "size_bytes": pre_out.stat().st_size,
                "metadata": observed_json_metadata(pre_out.read_bytes()),
                "source_path": pre["path"],
            },
            {
                "filename": post_out.name,
                "role": "postflop_population",
                "sha256": sha256_file(post_out),
                "size_bytes": post_out.stat().st_size,
                "metadata": observed_json_metadata(post_out.read_bytes()),
                "source_path": post["path"],
            },
        ],
        "release": {
            "tag": cfg["release_tag"],
            "archive": f"{bundle_name}.zip",
            "immutable": True,
        },
    }
    manifest_path = bundle_dir / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    readme = f"""# NLHE 100-200 user artifacts — {cfg['bundle_version']}

This archive is one coherent, immutable user-facing set for **NLHE 100-200**.
Do not mix individual JSON files from this archive with population-model files from another bundle version.

Included files:

- `custom.json`: exact user range-folder export (`custom_ranges`);
- `preflop_population_model_v5.json`: promoted integrated preflop population model;
- `postflop_population_model_v5.json`: matching promoted integrated postflop population model;
- `MANIFEST.json`: bundle/training-state/model identities and SHA-256 hashes;
- `CHECKSUMS.sha256`: checksums for all files above plus this README.

Training state: `{cfg['training_state']}`
Cycle: `{final_state['cycle']}`
Source commit: `{source_commit}`
Compatible promoted engine: `{engine['path']}`
Engine SHA-256: `{engine['sha256']}`

The population models are sourced only from the promoted production state recorded by `FINAL_STATE.json`.
Rejected or experimental Model A / Model B / strategy artifacts are not package inputs.
"""
    readme_path = bundle_dir / "README.md"
    readme_path.write_text(readme, encoding="utf-8")

    checksum_targets = [custom_path, pre_out, post_out, manifest_path, readme_path]
    checksums_path = bundle_dir / "CHECKSUMS.sha256"
    checksums_path.write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in sorted(checksum_targets, key=lambda p: p.name)),
        encoding="utf-8",
    )

    # Re-check that MANIFEST payload identities still match the actual files.
    manifest_check = load_json(manifest_path)
    by_role = {x["role"]: x for x in manifest_check["artifacts"]}
    require(by_role["custom_ranges"]["sha256"] == custom_cfg["sha256"], "manifest custom hash mismatch")
    require(by_role["preflop_population"]["sha256"] == pre["sha256"], "manifest preflop hash mismatch")
    require(by_role["postflop_population"]["sha256"] == post["sha256"], "manifest postflop hash mismatch")

    zip_path = out_dir / f"{bundle_name}.zip"
    deterministic_zip(zip_path, bundle_name, list(bundle_dir.iterdir()))
    print(zip_path)
    return zip_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="dist/user-artifacts")
    args = parser.parse_args()
    build((ROOT / args.out_dir).resolve())


if __name__ == "__main__":
    main()
