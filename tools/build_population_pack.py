#!/usr/bin/env python3
"""Build an immutable, population-scoped poker distribution pack.

This is the v1 successor to the narrow NLHE 100-200 user-artifact bundle.
It deliberately reuses its hashing/metadata helpers while sourcing scientific
artifacts exclusively through training/populations/registry.json.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import sys
from pathlib import Path, PurePosixPath
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.build_user_artifact_bundle import (  # noqa: E402
    FIXED_ZIP_TIME,
    git_commit,
    observed_json_metadata,
    sha256_bytes,
    sha256_file,
)
from tools.populations.registry import (  # noqa: E402
    PopulationRegistryError,
    require_artifact_role,
    resolve_population,
)
from tools.population_pack_candidate import (  # noqa: E402
    CandidateContractError,
    assembly_binding,
    validate_candidate_contract,
)

PACK_CONFIG_SCHEMA = "poker-population-pack-config/v1"
PACK_SCHEMA = "poker-population-pack/v1"
ZOOM_100_200_POPULATION = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
ALLOWED_POPULATION_STATUSES = {"PROMOTED", "PROMOTED_LEGACY"}
REQUIRED_DISTRIBUTION_ROLES = {
    "model_a_preflop",
    "model_a_postflop",
    "model_b",
    "hero_strategy",
    "engine",
    "hero_ranges",
    "application_release",
}


class PackError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise PackError(f"expected JSON object: {path}")
    return obj


def repo_path(value: str) -> Path:
    rel = PurePosixPath(str(value))
    if rel.is_absolute() or ".." in rel.parts:
        raise PackError(f"unsafe repository-relative path: {value!r}")
    path = ROOT.joinpath(*rel.parts)
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError as exc:
        raise PackError(f"path escapes repository: {value!r}") from exc
    return path


def safe_destination(value: str) -> PurePosixPath:
    rel = PurePosixPath(str(value))
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        raise PackError(f"unsafe pack destination: {value!r}")
    return rel


def deterministic_tree_zip(zip_path: Path, bundle_name: str, bundle_dir: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as zf:
        for path in sorted((p for p in bundle_dir.rglob("*") if p.is_file()), key=lambda p: p.as_posix()):
            rel = path.relative_to(bundle_dir).as_posix()
            info = zipfile.ZipInfo(f"{bundle_name}/{rel}", FIXED_ZIP_TIME)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _entry(path: Path, destination: PurePosixPath, source_path: str, roles: list[str]) -> dict:
    metadata = {}
    if path.suffix.lower() == ".json":
        try:
            metadata = observed_json_metadata(path.read_bytes())
        except (UnicodeDecodeError, json.JSONDecodeError):
            metadata = {}
    return {
        "path": destination.as_posix(),
        "roles": sorted(set(roles)),
        "source_path": source_path,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "metadata": metadata,
    }


def _copy_file(*, source: Path, source_rel: str, destination: PurePosixPath, roles: list[str], bundle_dir: Path,
               by_source: dict[str, dict], artifacts: list[dict]) -> dict:
    if not source.is_file():
        raise PackError(f"required pack artifact missing: {source_rel}")
    source_key = source.resolve().as_posix()
    if source_key in by_source:
        existing = by_source[source_key]
        existing["roles"] = sorted(set(existing["roles"]) | set(roles))
        return existing
    dest_path = bundle_dir.joinpath(*destination.parts)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest_path)
    item = _entry(dest_path, destination, source_rel, roles)
    artifacts.append(item)
    by_source[source_key] = item
    return item


def _decode_hero_ranges(source_bundle_config: Path) -> tuple[bytes, dict, str]:
    cfg = load_json(source_bundle_config)
    if cfg.get("schema") != "poker-user-artifact-bundle-config/v1":
        raise PackError("hero range source must be a v1 user-artifact bundle config")
    custom = cfg.get("custom_ranges")
    if not isinstance(custom, dict):
        raise PackError("hero range source bundle has no custom_ranges contract")
    encoded_path = repo_path(str(custom["source"]))
    encoded = encoded_path.read_text(encoding="utf-8").strip()
    compressed = base64.b64decode(encoded, validate=True)
    if sha256_bytes(compressed) != custom["compressed_sha256"]:
        raise PackError("compressed hero range source hash mismatch")
    payload = gzip.decompress(compressed)
    if sha256_bytes(payload) != custom["sha256"]:
        raise PackError("hero range source hash mismatch")
    obj = json.loads(payload.decode("utf-8"))
    if obj.get("schemaVersion") != 1 or obj.get("exportType") != "range-folder":
        raise PackError("hero ranges are not the preserved range-folder export")
    return payload, custom, str(encoded_path.relative_to(ROOT))


def _validate_application_release(path: Path, engine_source: str, engine_sha: str) -> dict:
    app = load_json(path)
    if app.get("schema") != "poker-site-release/v3":
        raise PackError("unsupported application release contract")
    identity = app.get("identity", {}).get("engine_release", {})
    if identity.get("artifact") != engine_source or identity.get("sha256") != engine_sha:
        raise PackError("application release and population engine identity disagree")
    if app.get("status") != "promoted":
        raise PackError("application release is not promoted")
    return app


def build(config_path: Path, out_dir: Path, *, population_override: str | None = None) -> Path:
    config_path = config_path.resolve()
    cfg = load_json(config_path)
    if cfg.get("schema") != PACK_CONFIG_SCHEMA:
        raise PackError(f"unsupported pack config schema: {cfg.get('schema')!r}")

    population_id = population_override or str(cfg.get("population_id") or "")
    if not population_id:
        raise PackError("population_id is required")
    try:
        population = resolve_population(ROOT, population_id)
    except PopulationRegistryError as exc:
        raise PackError(str(exc)) from exc
    status = str(population.get("status") or "")
    if status not in ALLOWED_POPULATION_STATUSES:
        raise PackError(f"population {population_id} is {status or 'UNSPECIFIED'}, not an accepted promoted distribution state")

    candidate_binding = None
    if population_id == ZOOM_100_200_POPULATION:
        candidate_rel = str(cfg.get("candidate_contract") or "")
        if not candidate_rel:
            raise PackError(
                f"population {population_id} requires a population-scoped candidate_contract before assembly"
            )
        try:
            candidate_summary = validate_candidate_contract(
                repo_path(candidate_rel),
                root=ROOT,
                expected_population_id=population_id,
                require_ready=True,
            )
            candidate_binding = assembly_binding(candidate_summary)
        except CandidateContractError as exc:
            raise PackError(f"candidate assembly contract rejected: {exc}") from exc

    role_sources: dict[str, str] = {}
    for role in ("model_a_preflop", "model_a_postflop", "model_b", "hero_strategy", "engine"):
        try:
            role_sources[role] = require_artifact_role(population, role)
        except PopulationRegistryError as exc:
            raise PackError(str(exc)) from exc

    engine_path = repo_path(role_sources["engine"])
    if not engine_path.is_file():
        raise PackError(f"engine artifact missing: {role_sources['engine']}")
    engine_sha = sha256_file(engine_path)

    app_release_rel = str(cfg.get("application_release") or "site/RELEASE.json")
    app_release_path = repo_path(app_release_rel)
    app_release = _validate_application_release(app_release_path, role_sources["engine"], engine_sha)

    source_bundle_rel = str(cfg.get("hero_ranges", {}).get("source_bundle_config") or "")
    if not source_bundle_rel:
        raise PackError("hero_ranges.source_bundle_config is required")
    hero_payload, hero_contract, hero_encoded_source = _decode_hero_ranges(repo_path(source_bundle_rel))

    model_b_cfg = cfg.get("model_b")
    if not isinstance(model_b_cfg, dict):
        raise PackError("model_b configuration is required")
    model_b_files = model_b_cfg.get("runtime_files")
    if not isinstance(model_b_files, list) or not model_b_files:
        raise PackError("model_b.runtime_files must be a non-empty list")

    pack_slug = str(cfg.get("pack_slug") or "")
    pack_version = str(cfg.get("pack_version") or "")
    pack_id = str(cfg.get("pack_id") or "")
    release_tag = str(cfg.get("release_tag") or "")
    if not all((pack_slug, pack_version, pack_id, release_tag)):
        raise PackError("pack_slug, pack_version, pack_id and release_tag are required")
    if any(x in pack_slug for x in ("/", "\\", "..")):
        raise PackError("pack_slug must be a single safe path component")

    bundle_name = f"{pack_slug}-{pack_version}"
    out_dir = out_dir.resolve()
    bundle_dir = out_dir / bundle_name
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    artifacts: list[dict] = []
    by_source: dict[str, dict] = {}
    role_destinations = {
        "model_a_preflop": PurePosixPath("model_a") / Path(role_sources["model_a_preflop"]).name,
        "model_a_postflop": PurePosixPath("model_a") / Path(role_sources["model_a_postflop"]).name,
        "engine": PurePosixPath("engine") / Path(role_sources["engine"]).name,
        "hero_strategy": PurePosixPath("strategy") / Path(role_sources["hero_strategy"]).name,
    }
    for role in ("model_a_preflop", "model_a_postflop", "engine", "hero_strategy"):
        source_rel = role_sources[role]
        _copy_file(source=repo_path(source_rel), source_rel=source_rel,
                   destination=safe_destination(role_destinations[role].as_posix()), roles=[role],
                   bundle_dir=bundle_dir, by_source=by_source, artifacts=artifacts)

    model_b_root = repo_path(role_sources["model_b"])
    if not model_b_root.is_dir():
        raise PackError(f"model_b must resolve to a directory: {role_sources['model_b']}")
    for name in sorted({str(x) for x in model_b_files}):
        rel = safe_destination(name)
        if len(rel.parts) != 1:
            raise PackError("model_b runtime file names must not contain directories")
        _copy_file(source=model_b_root / name,
                   source_rel=f"{role_sources['model_b'].rstrip('/')}/{name}",
                   destination=PurePosixPath("model_b") / name, roles=["model_b"],
                   bundle_dir=bundle_dir, by_source=by_source, artifacts=artifacts)

    hero_dest = PurePosixPath("hero") / str(hero_contract.get("filename") or "custom.json")
    hero_path = bundle_dir.joinpath(*hero_dest.parts)
    hero_path.parent.mkdir(parents=True, exist_ok=True)
    hero_path.write_bytes(hero_payload)
    artifacts.append({
        "path": hero_dest.as_posix(), "roles": ["hero_ranges"], "source_path": hero_encoded_source,
        "sha256": sha256_file(hero_path), "size_bytes": hero_path.stat().st_size,
        "metadata": observed_json_metadata(hero_payload),
        "source_semantics": "preserved user range-folder export from the accepted legacy reference",
    })

    _copy_file(source=app_release_path, source_rel=app_release_rel,
               destination=PurePosixPath("application") / "RELEASE.json", roles=["application_release"],
               bundle_dir=bundle_dir, by_source=by_source, artifacts=artifacts)

    roles_present = {role for item in artifacts for role in item["roles"]}
    missing_roles = sorted(REQUIRED_DISTRIBUTION_ROLES - roles_present)
    if missing_roles:
        raise PackError(f"pack is missing required roles: {', '.join(missing_roles)}")

    config_rel = config_path.relative_to(ROOT).as_posix()
    registry_path = ROOT / "training/populations/registry.json"
    source_commit = os.environ.get("PACK_SOURCE_COMMIT") or git_commit()
    manifest = {
        "schema": PACK_SCHEMA,
        "pack_id": pack_id,
        "pack_version": pack_version,
        "population_id": population_id,
        "population_status": status,
        "population_identity": population["identity"],
        "source_commit": source_commit,
        "coherency": "inseparable_population_pack",
        "registry": {"path": "training/populations/registry.json", "sha256": sha256_file(registry_path)},
        "config": {"path": config_rel, "sha256": sha256_file(config_path)},
        "compatibility": {
            "engine_version": population["artifacts"].get("engine_version"),
            "engine_source_path": role_sources["engine"],
            "engine_sha256": engine_sha,
            "application_release": {
                "source_path": app_release_rel, "schema": app_release["schema"],
                "version": app_release.get("version"), "status": app_release.get("status"),
                "sha256": sha256_file(app_release_path),
                "assembled_site": app_release.get("identity", {}).get("assembled_site"),
            },
        },
        "model_b": {
            "source_path": role_sources["model_b"],
            "alias": population["artifacts"].get("model_b_alias"),
            "runtime_files": sorted({str(x) for x in model_b_files}),
        },
        "artifacts": sorted(artifacts, key=lambda x: x["path"]),
        "required_roles": sorted(REQUIRED_DISTRIBUTION_ROLES),
        "release": {
            "tag": release_tag, "archive": f"{bundle_name}.zip",
            "manifest_asset": f"{bundle_name}.manifest.json", "immutable": True,
            "replacement_policy": "refuse_if_existing_bytes_differ",
        },
        "scope_notes": list(cfg.get("scope_notes") or []),
    }
    if candidate_binding is not None:
        manifest["assembly_contract"] = candidate_binding

    manifest_path = bundle_dir / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    readme = f"""# Poker population pack — {pack_version}\n\nPack: `{pack_id}`\nPopulation: `{population_id}`\nPopulation status: `{status}`\nSource commit: `{source_commit}`\n\nThis archive is an inseparable distribution unit. Do not mix files from another\npopulation or pack version. The engine, Model A, Model B runtime, Hero range\nsource and application compatibility identity are all pinned by SHA-256 in\n`MANIFEST.json`.\n\nThis pack distributes the currently accepted reference state only. It does not\nrelabel the legacy mixed Zoom/regular 100/200 models as Zoom-only, and it does\nnot include hand-history archives or rejected/experimental candidates.\n\nUse `CHECKSUMS.sha256` to verify extracted bytes before activation.\n"""
    (bundle_dir / "README.md").write_text(readme, encoding="utf-8")

    checksum_targets = sorted((p for p in bundle_dir.rglob("*") if p.is_file() and p.name != "CHECKSUMS.sha256"),
                              key=lambda p: p.relative_to(bundle_dir).as_posix())
    (bundle_dir / "CHECKSUMS.sha256").write_text(
        "".join(f"{sha256_file(path)}  {path.relative_to(bundle_dir).as_posix()}\n" for path in checksum_targets),
        encoding="utf-8")

    zip_path = out_dir / f"{bundle_name}.zip"
    deterministic_tree_zip(zip_path, bundle_name, bundle_dir)
    shutil.copyfile(manifest_path, out_dir / f"{bundle_name}.manifest.json")
    (out_dir / f"{bundle_name}.zip.sha256").write_text(f"{sha256_file(zip_path)}  {zip_path.name}\n", encoding="utf-8")
    print(zip_path)
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="user/packs/legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1/pack.json")
    parser.add_argument("--out-dir", default="dist/population-packs")
    parser.add_argument("--population", help="override population_id for validation/testing")
    args = parser.parse_args()
    try:
        build(repo_path(args.config), ROOT / args.out_dir, population_override=args.population)
    except PackError as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
