#!/usr/bin/env python3
"""Generate the same-origin browser runtime-pack catalogue from reviewed assets.

The catalogue is deliberately generated from the trainer population manifest plus
#110's versioned pack config. It contains hashes for every byte the browser may
activate, but never copies hand histories or scientific working data into site/.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
TRAINER_MANIFEST = SITE / "assets/trainer/population.json"
PACK_CONFIG = ROOT / "user/packs/legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1/pack.json"
OUTPUT = SITE / "packs/catalog.json"
CATALOG_SCHEMA = "poker-population-catalog/v1"
RUNTIME_SCHEMA = "poker-browser-runtime-pack/v1"
HERO_PROVENANCE_SCHEMA = "trainer-hero-provenance/v1"
HERO_PROVENANCE_STATUSES = ("RETAIN_REFERENCE", "PARTIAL")
# #task-0jt: the population provenance carries the explicit admission binding
# tokens the runtime forwards to the resolver. A retained reference declares them
# as null: it never fabricates a candidate/generation identity or a binding hash.
HERO_BINDING_FIELDS = ("candidate_id", "generation_id", "binding_sha256")


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def asset(key: str, role: str, url: str, expected_schema: str | None = None) -> dict:
    if not url.startswith("./"):
        raise ValueError(f"runtime asset must be same-origin relative: {url}")
    path = SITE / url[2:]
    if not path.is_file():
        raise FileNotFoundError(path)
    item = {
        "key": key,
        "role": role,
        "url": url,
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
        "media_type": "application/json",
    }
    if expected_schema:
        item["expected_schema"] = expected_schema
    return item


def assert_public_catalog_entry(entry: dict) -> dict:
    if entry.get("distribution_class") == "TEST_ONLY" or entry.get("test_only") is True:
        raise ValueError("TEST_ONLY pack cannot enter the public catalogue")
    if entry.get("non_publishable") is True:
        raise ValueError("NON_PUBLISHABLE pack cannot enter the public catalogue")
    return entry


def hero_provenance(trainer: dict) -> dict:
    """Return the explicit, population-bound Hero provenance from the trainer manifest.

    The provenance is fail-closed: it must stay bound to the manifest population,
    describe the preserved legacy ``Custom`` range-folder source, match the exact
    Hero ranges bytes, and remain explicitly non-admissible/non-promotable so no
    retained reference or inactive candidate can drift into the active strategy.
    """
    provenance = trainer.get("hero_provenance")
    if not isinstance(provenance, dict):
        raise ValueError("trainer population manifest is missing hero_provenance")
    if provenance.get("schema") != HERO_PROVENANCE_SCHEMA:
        raise ValueError("unsupported trainer hero provenance schema")
    if provenance.get("population_id") != trainer.get("population_id"):
        raise ValueError("trainer hero provenance population disagrees with the manifest")
    ranges_url = trainer["assets"]["hero"]["ranges"]
    if not ranges_url.startswith("./"):
        raise ValueError(f"hero ranges must be same-origin relative: {ranges_url}")
    if provenance.get("ranges_path") != ranges_url:
        raise ValueError("trainer hero provenance ranges_path disagrees with the manifest")
    ranges_file = SITE / ranges_url.removeprefix("./")
    if not ranges_file.is_file():
        raise FileNotFoundError(ranges_file)
    if provenance.get("sha256") != sha256(ranges_file):
        raise ValueError("trainer hero provenance sha256 does not match the Hero ranges bytes")
    source = provenance.get("source")
    ranges_source = load(ranges_file).get("source", {})
    if not isinstance(source, dict) or not isinstance(ranges_source, dict):
        raise ValueError("trainer hero provenance source is missing")
    if source.get("folder") != "Custom" or ranges_source.get("folder") != "Custom":
        raise ValueError("trainer hero provenance must preserve the legacy Custom range-folder")
    if source.get("export_type") != "range-folder" or ranges_source.get("exportType") != "range-folder":
        raise ValueError("trainer hero provenance must preserve the legacy range-folder export")
    if source.get("sha256") != ranges_source.get("sha256"):
        raise ValueError("trainer hero provenance source sha256 disagrees with the Hero ranges source")
    if provenance.get("status") not in HERO_PROVENANCE_STATUSES:
        raise ValueError("trainer hero provenance status must be RETAIN_REFERENCE or PARTIAL")
    for field in HERO_BINDING_FIELDS:
        if field not in provenance:
            raise ValueError(f"trainer hero provenance is missing admission binding field: {field}")
    if provenance.get("status") == "RETAIN_REFERENCE":
        for field in HERO_BINDING_FIELDS:
            if provenance.get(field) not in (None, ""):
                raise ValueError(
                    f"retained trainer hero provenance must not fabricate a candidate binding: {field}"
                )
    if provenance.get("admissible") is not False or provenance.get("promotable") is not False:
        raise ValueError("trainer hero provenance must remain non-admissible and non-promotable")
    if trainer.get("hero_strategy") != provenance.get("strategy_id"):
        raise ValueError("trainer hero_strategy disagrees with the Hero provenance strategy_id")
    return provenance


def build_catalog() -> dict:
    trainer = load(TRAINER_MANIFEST)
    pack = load(PACK_CONFIG)
    if trainer.get("schema") != "trainer-population-pack/v1":
        raise ValueError("unsupported trainer population manifest")
    if pack.get("schema") != "poker-population-pack-config/v1":
        raise ValueError("unsupported #110 pack config")
    if trainer.get("population_id") != pack.get("population_id"):
        raise ValueError("trainer and distribution pack populations disagree")

    a = trainer["assets"]
    provenance = hero_provenance(trainer)
    assets = [
        asset("population_manifest", "population_manifest", "./assets/trainer/population.json", "trainer-population-pack/v1"),
        asset("model_a_preflop", "model_a_preflop", a["modelA"]["preflop"]),
        asset("model_a_postflop", "model_a_postflop", a["modelA"]["postflop"]),
        asset("model_b_profiles", "model_b", a["modelB"]["profiles"], "independent-opponent-profiles/v2"),
        asset("model_b_ranges", "model_b", a["modelB"]["ranges"], "independent-preflop-ranges/v2"),
        asset("model_b_actions", "model_b", a["modelB"]["actions"], "independent-postflop-actions/v2"),
        asset("model_b_sizing", "model_b", a["modelB"]["sizing"], "independent-postflop-sizing/v2"),
        asset("model_b_contract", "model_b", a["modelB"]["contract"]),
        asset("hero_ranges", "hero_ranges", a["hero"]["ranges"], "trainer-hero-preflop-ranges/v1"),
    ]
    fingerprint_payload = json.dumps(
        [{k: row[k] for k in ("key", "sha256", "size_bytes")} for row in assets],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    runtime_revision = hashlib.sha256(fingerprint_payload).hexdigest()
    entry = {
        "schema": RUNTIME_SCHEMA,
        "pack_id": pack["pack_id"],
        "pack_version": pack["pack_version"],
        "release_tag": pack["release_tag"],
        "population_id": trainer["population_id"],
        "population_identity": trainer.get("population_identity", {}),
        "runtime_revision": runtime_revision,
        "recommended": True,
        "engine_version": trainer.get("engine_version"),
        "model_a_version": trainer.get("model_a_version"),
        "model_b_alias": trainer.get("model_b_alias"),
        "hero_strategy": trainer.get("hero_strategy"),
        "hero_provenance": provenance,
        "compatibility": {
            "application_release_schema": "poker-site-release/v3",
            "engine_version": trainer.get("engine_version"),
            "activation_policy": "all_assets_valid_then_atomic_switch",
        },
        "assets": assets,
        "source_release": {
            "kind": "github_release_population_pack",
            "tag": pack["release_tag"],
            "pack_id": pack["pack_id"],
            "note": "Runtime subset uses the same promoted population identity; the complete immutable distribution ZIP is owned by #110.",
        },
    }
    assert_public_catalog_entry(entry)
    return {
        "schema": CATALOG_SCHEMA,
        "generated_from": {
            "trainer_manifest": TRAINER_MANIFEST.relative_to(ROOT).as_posix(),
            "pack_config": PACK_CONFIG.relative_to(ROOT).as_posix(),
        },
        "entries": [entry],
    }


def write_catalog() -> Path:
    value = build_catalog()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return OUTPUT


def main() -> int:
    path = write_catalog()
    print(path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
