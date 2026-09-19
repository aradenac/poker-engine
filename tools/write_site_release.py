#!/usr/bin/env python3
"""Generate or verify site/RELEASE.json from the functional site bytes.

The release metadata deliberately separates:
- immutable engine release identity;
- assembled static application identity;
- live deployment verification, which is tracked separately by issue #45.

The application identity covers the analyser, shared preflop contract, Hero range
editor, trainer, population-pack manager/catalog and the complete site/assets tree.
The pack catalogue is generated on demand so pre-existing CI callers of --check do
not need special knowledge of #111. The index identity is computed after the same
idempotent navigation patch used by the Cloudflare build.

The checked-in RELEASE.json is a source anchor. Build-only products such as the
catalogue and patched navigation are materialized by this script, so --check verifies
that the checked-in anchor still matches every byte it claims plus the immutable
engine contract, while a normal invocation writes the exact assembled-site identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RELEASE_PATH = ROOT / "site" / "RELEASE.json"
ENGINE_PATH = ROOT / "user" / "releases" / "poker_range_equity_offline_multiway_v83.html"
INDEX_PATH = ROOT / "site" / "index.html"
CATALOG_PATH = ROOT / "site" / "packs" / "catalog.json"
NAV_SOURCE = '<a href="./hero-ranges.html">Stratégie Hero</a>'
NAV_TARGET = NAV_SOURCE + '\n      <a href="./packs.html">Packs de population</a>'
FUNCTIONAL_FILES = (
    INDEX_PATH,
    ROOT / "site" / "preflop-contract.js",
    ROOT / "site" / "hero-ranges.html",
    ROOT / "site" / "hero-ranges.js",
    ROOT / "site" / "hero-ranges-app.js",
    ROOT / "site" / "hero-ranges.css",
    ROOT / "site" / "hero-compliance.js",
    ROOT / "site" / "hero-compliance-replayer.js",
    ROOT / "site" / "trainer.js",
    ROOT / "site" / "trainer.css",
    ROOT / "site" / "action-sizing-ev.js",
    ROOT / "site" / "packs.html",
    ROOT / "site" / "packs.css",
    ROOT / "site" / "packs-app.js",
    ROOT / "site" / "pack-identity.js",
    ROOT / "site" / "population-packs.js",
    ROOT / "site" / "population-pack-sw.js",
    CATALOG_PATH,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def git_hash_bytes(payload: bytes) -> str:
    return subprocess.check_output(
        ["git", "hash-object", "--stdin"], cwd=ROOT, input=payload
    ).decode().strip()


def patched_index_bytes() -> bytes:
    text = INDEX_PATH.read_text(encoding="utf-8")
    if '<a href="./packs.html">Packs de population</a>' not in text:
        if NAV_SOURCE not in text:
            raise ValueError("hero-ranges navigation anchor not found")
        text = text.replace(NAV_SOURCE, NAV_TARGET, 1)
    return text.encode("utf-8")


def ensure_pack_catalog() -> None:
    subprocess.run(
        ["python3", "tools/write_pack_catalog.py"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )


def source_blob_sha(path: Path) -> str:
    return git_output("hash-object", str(path.relative_to(ROOT)))


def git_blob_sha(path: Path) -> str:
    if path == INDEX_PATH:
        return git_hash_bytes(patched_index_bytes())
    return source_blob_sha(path)


def assets_tree_sha() -> str:
    return git_output("rev-parse", "HEAD:site/assets")


def build_identity(existing: dict[str, Any]) -> dict[str, Any]:
    ensure_pack_catalog()
    release = dict(existing)
    engine_sha256 = sha256_file(ENGINE_PATH)
    missing = [str(path.relative_to(ROOT)) for path in FUNCTIONAL_FILES if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"functional site file(s) missing: {', '.join(missing)}")

    release["schema"] = "poker-site-release/v3"
    release["application"] = release.get("application", "Poker Range Equity Offline")
    release["version"] = release.get("version", "v83")
    release["artifact"] = "site/index.html"
    release["release_artifact"] = str(ENGINE_PATH.relative_to(ROOT))
    release["sha256"] = engine_sha256
    release["identity"] = {
        "engine_release": {
            "artifact": str(ENGINE_PATH.relative_to(ROOT)),
            "sha256": engine_sha256,
        },
        "assembled_site": {
            "functional_files": {
                str(path.relative_to(ROOT)): {"git_blob_sha": git_blob_sha(path)}
                for path in FUNCTIONAL_FILES
            },
            "assets_tree_git_sha": assets_tree_sha(),
            "excluded_build_metadata": [
                "site/RELEASE.json",
                "site/deployment-meta.css",
            ],
        },
    }
    release["status"] = release.get("status", "promoted")
    release["published"] = release.get("published", True)
    release["publication_verification"] = {
        "status": "UNVERIFIED_LIVE",
        "tracked_by_issue": 45,
        "meaning": (
            "Repository/build identity only. A successful build or published=true "
            "does not prove the canonical live Cloudflare URL or deployed revision."
        ),
    }
    release["models"] = release.get(
        "models",
        {
            "preflop": "training/models/preflop_population_model_v5.json",
            "postflop": "training/models/postflop_population_model_v5.json",
        },
    )
    release["notes"] = (
        "Engine v83 and assembled application identities are distinct. "
        "The assembled_site identity is derived from content-addressed Git objects, "
        "including the generated population-pack catalogue and build-patched index; "
        "live production verification remains issue #45."
    )
    return release


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def validate_source_anchor(current: dict[str, Any], generated: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in (
        "schema",
        "application",
        "version",
        "artifact",
        "release_artifact",
        "sha256",
        "models",
        "status",
        "published",
    ):
        if current.get(key) != generated.get(key):
            errors.append(f"source release field changed: {key}")

    if current.get("identity", {}).get("engine_release") != generated.get("identity", {}).get("engine_release"):
        errors.append("engine release identity changed")

    publication = current.get("publication_verification", {})
    if publication.get("tracked_by_issue") != 45 or publication.get("status") != "UNVERIFIED_LIVE":
        errors.append("live publication boundary is not anchored to issue #45")

    assembled = current.get("identity", {}).get("assembled_site", {})
    files = assembled.get("functional_files", {})
    if not isinstance(files, dict) or not files:
        errors.append("source release has no functional file identity")
    else:
        for rel, descriptor in sorted(files.items()):
            path = ROOT / rel
            if not path.is_file():
                errors.append(f"source release file missing: {rel}")
                continue
            actual = source_blob_sha(path)
            expected = descriptor.get("git_blob_sha") if isinstance(descriptor, dict) else None
            if actual != expected:
                errors.append(f"source release file changed: {rel}")

    recorded_assets = assembled.get("assets_tree_git_sha")
    if recorded_assets and recorded_assets != assets_tree_sha():
        errors.append("site/assets tree changed without refreshing the source release anchor")

    generated_files = generated.get("identity", {}).get("assembled_site", {}).get("functional_files", {})
    required = {str(path.relative_to(ROOT)) for path in FUNCTIONAL_FILES}
    missing = required - set(generated_files)
    if missing:
        errors.append("assembled release identity missing: " + ", ".join(sorted(missing)))

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the checked-in source release anchor and assembled release contract",
    )
    parser.add_argument("--output", type=Path, default=RELEASE_PATH)
    args = parser.parse_args()

    existing: dict[str, Any] = {}
    if RELEASE_PATH.exists():
        existing = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))

    generated_value = build_identity(existing)
    generated = canonical_json(generated_value)
    output = args.output if args.output.is_absolute() else ROOT / args.output

    if args.check:
        if not output.exists():
            print(f"release anchor missing: {display_path(output)}")
            return 1
        try:
            current_value = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"invalid release anchor {display_path(output)}: {exc}")
            return 1
        errors = validate_source_anchor(current_value, generated_value)
        if errors:
            for error in errors:
                print(f"release identity error: {error}")
            return 1
        print(
            f"release source anchor verified: {display_path(output)}; "
            "assembled identity can be materialized"
        )
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(generated, encoding="utf-8")
    print(f"wrote {display_path(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())