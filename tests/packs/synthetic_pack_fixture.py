from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from tools.build_user_artifact_bundle import FIXED_ZIP_TIME

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "tests/fixtures/population-packs/zoom_test_only"
TARGET_POPULATION = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
TEST_DECISION = "TEST_ONLY_INTEGRATION"
TEST_READY = "TEST_ONLY_READY_FOR_INTEGRATION"

RUNTIME_ASSETS = {
    "population_manifest": ("population_manifest.json", "population_manifest", "trainer-population-pack/v1"),
    "model_a_preflop": ("model_a_preflop.json", "model_a_preflop", None),
    "model_a_postflop": ("model_a_postflop.json", "model_a_postflop", None),
    "model_b_profiles": ("model_b_profiles.json", "model_b", "independent-opponent-profiles/v2"),
    "model_b_ranges": ("model_b_ranges.json", "model_b", "independent-preflop-ranges/v2"),
    "model_b_actions": ("model_b_actions.json", "model_b", "independent-postflop-actions/v2"),
    "model_b_sizing": ("model_b_sizing.json", "model_b", "independent-postflop-sizing/v2"),
    "model_b_contract": ("model_b_contract.json", "model_b", None),
    "hero_strategy": ("hero_strategy.json", "hero_strategy", "test-only-hero-strategy/v1"),
    "engine": ("engine.json", "engine", "test-only-engine/v1"),
    "hero_ranges": ("hero_ranges.json", "hero_ranges", "trainer-hero-preflop-ranges/v1"),
    "application_release": ("application_release.json", "application_release", "poker-site-release/v3"),
}

ROLE_FILES = {
    "model_a_preflop": ["model_a_preflop.json"],
    "model_a_postflop": ["model_a_postflop.json"],
    "model_b": [
        "model_b_profiles.json",
        "model_b_ranges.json",
        "model_b_actions.json",
        "model_b_sizing.json",
        "model_b_contract.json",
    ],
    "hero_strategy": ["hero_strategy.json"],
    "engine": ["engine.json"],
    "hero_ranges": ["hero_ranges.json"],
    "application_release": ["application_release.json"],
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def fixture_spec() -> dict:
    return json.loads((FIXTURE_DIR / "fixture.json").read_text(encoding="utf-8"))


def fixture_payloads() -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        if path.name in {"fixture.json", "application_release.json"}:
            continue
        payloads[path.name] = path.read_bytes()

    engine_sha = sha256_bytes(payloads["engine.json"])
    app = json.loads((FIXTURE_DIR / "application_release.json").read_text(encoding="utf-8"))
    app["identity"]["engine_release"] = {
        "artifact": "engine.json",
        "sha256": engine_sha,
    }
    payloads["application_release.json"] = _json_bytes(app)
    return payloads


def _combined_role_sha(payloads: dict[str, bytes], role: str) -> str:
    h = hashlib.sha256()
    for name in sorted(ROLE_FILES[role]):
        data = payloads[name]
        h.update(f"{name}\0{len(data)}\0{sha256_bytes(data)}\n".encode("utf-8"))
    return h.hexdigest()


def assembly_contract(payloads: dict[str, bytes]) -> dict:
    evidence_path = "tests/fixtures/population-packs/zoom_test_only/admission_evidence.json"
    evidence_sha = hashlib.sha256((FIXTURE_DIR / "admission_evidence.json").read_bytes()).hexdigest()
    components = {}
    for role, names in ROLE_FILES.items():
        source_name = names[0]
        digest = (
            _combined_role_sha(payloads, role)
            if len(names) > 1
            else sha256_bytes(payloads[source_name])
        )
        components[role] = {
            "role": role,
            "artifact_class": "TEST_ONLY",
            "non_publishable": True,
            "population_id": TARGET_POPULATION,
            "source_path": f"tests/fixtures/population-packs/zoom_test_only/{source_name}",
            "sha256": digest,
            "provenance": {
                "source_population_id": TARGET_POPULATION,
                "kind": "synthetic_integration_fixture",
                "evidence": {"path": evidence_path, "sha256": evidence_sha},
            },
            "decision": {
                "status": TEST_DECISION,
                "issue": "#201",
                "scientific_effect": "NONE_TEST_FIXTURE_ONLY",
                "evidence": {"path": evidence_path, "sha256": evidence_sha},
            },
        }
    return {
        "schema": "poker-population-pack-candidate/v1",
        "candidate_id": f"{TARGET_POPULATION}@synthetic-test-only",
        "candidate_status": TEST_READY,
        "population_id": TARGET_POPULATION,
        "contract": {
            "path": "tests/fixtures/population-packs/zoom_test_only/fixture.json",
            "sha256": hashlib.sha256((FIXTURE_DIR / "fixture.json").read_bytes()).hexdigest(),
        },
        "components": components,
    }


def runtime_entry(*, version_suffix: str = "") -> tuple[dict, dict[str, bytes]]:
    spec = fixture_spec()
    payloads = fixture_payloads()
    version = spec["pack_version"] + version_suffix
    assets = []
    for key, (name, role, expected_schema) in RUNTIME_ASSETS.items():
        data = payloads[name]
        item = {
            "key": key,
            "role": role,
            "url": f"./__test_only__/zoom/{name}",
            "sha256": sha256_bytes(data),
            "size_bytes": len(data),
            "media_type": "application/json",
        }
        if expected_schema:
            item["expected_schema"] = expected_schema
        assets.append(item)
    fingerprint = json.dumps(
        [
            {k: item[k] for k in ("key", "sha256", "size_bytes")}
            for item in assets
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    entry = {
        "schema": "poker-browser-runtime-pack/v1",
        "distribution_class": "TEST_ONLY",
        "test_only": True,
        "non_publishable": True,
        "pack_id": spec["pack_id"],
        "pack_version": version,
        "release_tag": "TEST_ONLY_NO_RELEASE",
        "population_id": TARGET_POPULATION,
        "runtime_revision": sha256_bytes(fingerprint + version.encode("utf-8")),
        "recommended": False,
        "default": False,
        "publication_policy": spec["publication_policy"],
        "engine_version": spec["engine_version"],
        "compatibility": {
            "application_release_schema": "poker-site-release/v3",
            "engine_version": spec["engine_version"],
            "activation_policy": "test_namespace_only_atomic_switch",
        },
        "assets": assets,
        "source_release": {
            "kind": "TEST_ONLY",
            "tag": "NONE",
            "pack_id": spec["pack_id"],
            "note": "Synthetic fixture only; never publish.",
        },
    }
    fetch_payloads = {item["url"]: payloads[RUNTIME_ASSETS[item["key"]][0]] for item in assets}
    fetch_payloads["./RELEASE.json"] = payloads["application_release.json"]
    return entry, fetch_payloads


def distribution_manifest(payloads: dict[str, bytes]) -> dict:
    spec = fixture_spec()
    artifacts = []
    for name in sorted(payloads):
        roles = [role for role, names in ROLE_FILES.items() if name in names]
        if name == "population_manifest.json":
            roles = ["population_manifest"]
        artifacts.append(
            {
                "path": f"artifacts/{name}",
                "roles": roles,
                "source_path": f"tests/fixtures/population-packs/zoom_test_only/{name}",
                "sha256": sha256_bytes(payloads[name]),
                "size_bytes": len(payloads[name]),
                "artifact_class": "TEST_ONLY",
                "non_publishable": True,
            }
        )
    engine = next(item for item in artifacts if "engine" in item["roles"])
    application = next(item for item in artifacts if "application_release" in item["roles"])
    return {
        "schema": "poker-population-pack/v1",
        "distribution_class": "TEST_ONLY",
        "test_only": True,
        "non_publishable": True,
        "pack_id": spec["pack_id"],
        "pack_version": spec["pack_version"],
        "population_id": TARGET_POPULATION,
        "population_status": "TEST_ONLY",
        "population_identity": json.loads(payloads["population_manifest.json"])["population_identity"],
        "coherency": "inseparable_population_pack",
        "recommended": False,
        "default": False,
        "publication_policy": spec["publication_policy"],
        "compatibility": {
            "engine_version": spec["engine_version"],
            "engine_path": engine["path"],
            "engine_sha256": engine["sha256"],
            "application_release_path": application["path"],
            "application_release_sha256": application["sha256"],
        },
        "assembly_contract": assembly_contract(payloads),
        "artifacts": artifacts,
        "required_roles": sorted(ROLE_FILES),
        "release": {
            "tag": "TEST_ONLY_NO_RELEASE",
            "archive": "zoom-test-only.zip",
            "manifest_asset": "zoom-test-only.manifest.json",
            "immutable": True,
            "publishable": False,
            "replacement_policy": "never_publish_test_fixture",
        },
        "scope_notes": [
            "TEST_ONLY / NON_PUBLISHABLE synthetic integration fixture.",
            "Scientific effect: NONE_TEST_FIXTURE_ONLY.",
        ],
    }


def build_test_only_archive(out_dir: Path) -> tuple[Path, dict]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payloads = fixture_payloads()
    manifest = distribution_manifest(payloads)
    root = "zoom-test-only-0.0.0-test.1"

    files: dict[str, bytes] = {
        "MANIFEST.json": _json_bytes(manifest),
        "README.md": (
            "# TEST_ONLY Zoom pack fixture\n\n"
            "NON_PUBLISHABLE. Synthetic integration evidence only.\n"
        ).encode("utf-8"),
    }
    for name, data in payloads.items():
        files[f"artifacts/{name}"] = data
    checksum_lines = [
        f"{sha256_bytes(files[name])}  {name}\n"
        for name in sorted(files)
    ]
    files["CHECKSUMS.sha256"] = "".join(checksum_lines).encode("utf-8")

    zip_path = out_dir / "zoom-test-only.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name in sorted(files):
            info = zipfile.ZipInfo(f"{root}/{name}", FIXED_ZIP_TIME)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, files[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    manifest_path = out_dir / "zoom-test-only.manifest.json"
    manifest_path.write_bytes(files["MANIFEST.json"])
    (out_dir / "zoom-test-only.zip.sha256").write_text(
        f"{sha256_bytes(zip_path.read_bytes())}  {zip_path.name}\n",
        encoding="utf-8",
    )
    return zip_path, manifest


def copy_archive_with_manifest(zip_path: Path, out_path: Path, mutate) -> Path:
    with zipfile.ZipFile(zip_path) as src:
        members = {name: src.read(name) for name in src.namelist()}
    manifest_name = next(name for name in members if name.endswith("/MANIFEST.json"))
    manifest = json.loads(members[manifest_name])
    mutate(manifest)
    members[manifest_name] = _json_bytes(manifest)
    root = manifest_name.split("/", 1)[0]
    checksum_name = f"{root}/CHECKSUMS.sha256"
    lines = []
    for name in sorted(members):
        if name == checksum_name:
            continue
        rel = name.split("/", 1)[1]
        lines.append(f"{sha256_bytes(members[name])}  {rel}\n")
    members[checksum_name] = "".join(lines).encode("utf-8")
    with zipfile.ZipFile(out_path, "w") as zf:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, members[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return out_path
