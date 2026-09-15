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
