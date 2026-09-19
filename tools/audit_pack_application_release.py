#!/usr/bin/env python3
"""Audit #377 fresh Zoom application_release candidate.

Read-only by construction: validates content identities, fail-closed boot policy,
resolver #305 and preflight #253 without publishing, activating or promoting.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any

from tools.population_pack_admission import resolve_admission
from tools.population_pack_candidate import sha256_file
from tools.population_pack_preflight import preflight

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "training/runs/20260919_pack_application_release"
MANIFEST_PATH = RUN_DIR / "APPLICATION_RELEASE_MANIFEST.json"
PROVENANCE_PATH = RUN_DIR / "PROVENANCE.json"
DECISION_PATH = RUN_DIR / "ROLE_DECISION.json"
EVIDENCE_PATH = RUN_DIR / "EVIDENCE_SET.json"
RESULT_PATH = RUN_DIR / "RESULT.json"

TARGET = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
ENGINE_PATH = "training/artifacts/pack-engine/poker-pack-engine-runtime-v1-15bfa1ba78b463b63b5b9b8ee47a98fd9b29c2a9b79fa455b791a9781c7d7e08.js"
ENGINE_SHA = "15bfa1ba78b463b63b5b9b8ee47a98fd9b29c2a9b79fa455b791a9781c7d7e08"
BOOT_PATH = "training/artifacts/application-release/pack-scoped-boot-v1-4af0faa262931e91e49d4e028bf93eed14d508120cfafc29746fbc917f73c38c.js"
BOOT_SHA = "4af0faa262931e91e49d4e028bf93eed14d508120cfafc29746fbc917f73c38c"
RELEASE_PATH = "training/artifacts/application-release/poker-site-release-zoom-100-200-candidate-v1-25afc20cce834fc93ff140f56723548e806034cd892a8b222de21f916d162984.json"
RELEASE_SHA = "25afc20cce834fc93ff140f56723548e806034cd892a8b222de21f916d162984"
REQUIRED_SCIENTIFIC = ("model_a_preflop", "model_a_postflop", "model_b", "hero_strategy", "hero_ranges")
LEGACY_ANCHORS = {
    "site/RELEASE.json": "52edc76bbc4b06713d89490ee4553e6428a39b9e35943f81b983d9786f7d631d",
    "site/trainer.js": "3d323efa24cd76342f953c26447e992162a3c1cca77d9472744d9107fe459e56",
    "site/training/preflop-runtime.js": "35ba3517ac4ccd9564f99fa2eb501da02647a690d819a7725f4059e8ad0ae778",
}

class ApplicationReleaseAuditError(RuntimeError):
    pass

def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApplicationReleaseAuditError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ApplicationReleaseAuditError(f"expected object: {path}")
    return value

def validate_candidate_bytes(*, root: Path = ROOT) -> dict[str, Any]:
    release_path = root / RELEASE_PATH
    boot_path = root / BOOT_PATH
    engine_path = root / ENGINE_PATH
    for path, expected in (
        (release_path, RELEASE_SHA),
        (boot_path, BOOT_SHA),
        (engine_path, ENGINE_SHA),
    ):
        if not path.is_file():
            raise ApplicationReleaseAuditError(f"required artifact missing: {path.relative_to(root)}")
        actual = sha256_file(path)
        if actual != expected:
            raise ApplicationReleaseAuditError(
                f"artifact hash mismatch for {path.relative_to(root)}: {actual} != {expected}"
            )
        if expected not in path.name:
            raise ApplicationReleaseAuditError(f"artifact is not content-addressed: {path.relative_to(root)}")

    release = _load(release_path)
    if release.get("schema") != "poker-site-release/v3":
        raise ApplicationReleaseAuditError("release schema mismatch")
    if release.get("status") != "candidate_unpublished" or release.get("published") is not False:
        raise ApplicationReleaseAuditError("release must remain candidate_unpublished/published=false")
    if release.get("population_id") != TARGET:
        raise ApplicationReleaseAuditError("release population mismatch")

    engine = ((release.get("identity") or {}).get("engine_release") or {})
    if engine != {"artifact": ENGINE_PATH, "sha256": ENGINE_SHA}:
        raise ApplicationReleaseAuditError("release does not bind exact #370 engine")
    boot = ((release.get("identity") or {}).get("pack_scoped_boot") or {})
    if boot != {"artifact": BOOT_PATH, "sha256": BOOT_SHA}:
        raise ApplicationReleaseAuditError("release boot identity mismatch")

    compat = release.get("compatibility") or {}
    if compat.get("mode") != "PACK_SCOPED_ZOOM":
        raise ApplicationReleaseAuditError("release must be explicit PACK_SCOPED_ZOOM")
    if compat.get("legacy_engine_fallback_allowed") is not False:
        raise ApplicationReleaseAuditError("legacy engine fallback must be disabled")
    if compat.get("scientific_component_fallback_allowed") is not False:
        raise ApplicationReleaseAuditError("scientific component fallback must be disabled")
    if compat.get("legacy_default_mode_behavior") != "UNCHANGED_PASSTHROUGH":
        raise ApplicationReleaseAuditError("legacy/default mode preservation is not explicit")

    requirements = release.get("component_requirements") or {}
    for role in REQUIRED_SCIENTIFIC:
        row = requirements.get(role) or {}
        if row.get("required") is not True:
            raise ApplicationReleaseAuditError(f"{role} must be required")
        if row.get("decision_status") != "ADMISSIBLE_FOR_PACK":
            raise ApplicationReleaseAuditError(f"{role} admission requirement mismatch")
        if row.get("source_population_id") != TARGET:
            raise ApplicationReleaseAuditError(f"{role} population requirement mismatch")
        if row.get("fallback") != "NONE":
            raise ApplicationReleaseAuditError(f"{role} fallback must be NONE")
    models = release.get("models") or {}
    if models.get("preflop") is not None or models.get("postflop") is not None:
        raise ApplicationReleaseAuditError("candidate release must not bind legacy/default models")

    for rel, expected in LEGACY_ANCHORS.items():
        path = root / rel
        if sha256_file(path) != expected:
            raise ApplicationReleaseAuditError(f"legacy/default anchor drift: {rel}")

    return {
        "release_path": RELEASE_PATH,
        "release_sha256": RELEASE_SHA,
        "boot_path": BOOT_PATH,
        "boot_sha256": BOOT_SHA,
        "engine_path": ENGINE_PATH,
        "engine_sha256": ENGINE_SHA,
        "legacy_anchors_verified": sorted(LEGACY_ANCHORS),
    }

def audit(*, root: Path = ROOT) -> dict[str, Any]:
    byte_proof = validate_candidate_bytes(root=root)
    manifest = _load(root / MANIFEST_PATH.relative_to(ROOT))
    provenance = _load(root / PROVENANCE_PATH.relative_to(ROOT))
    decision = _load(root / DECISION_PATH.relative_to(ROOT))
    evidence = _load(root / EVIDENCE_PATH.relative_to(ROOT))
    expected = _load(root / RESULT_PATH.relative_to(ROOT))

    if manifest.get("schema") != "poker-pack-application-release-manifest/v1":
        raise ApplicationReleaseAuditError("manifest schema mismatch")
    if provenance.get("schema") != "poker-pack-application-release-provenance/v1":
        raise ApplicationReleaseAuditError("provenance schema mismatch")
    if decision.get("schema") != "poker-pack-application-release-role-decision/v1":
        raise ApplicationReleaseAuditError("decision schema mismatch")
    if decision.get("status") != "ADMISSIBLE_FOR_PACK":
        raise ApplicationReleaseAuditError("application_release role must be ADMISSIBLE_FOR_PACK")
    if decision.get("scientific_performance_claim") is not False:
        raise ApplicationReleaseAuditError("runtime compatibility decision cannot claim performance")
    if decision.get("test_consumed") is not False:
        raise ApplicationReleaseAuditError("scientific TEST must remain unconsumed")

    app = ((evidence.get("components") or {}).get("application_release") or {})
    if app.get("source_path") != RELEASE_PATH or app.get("sha256") != RELEASE_SHA:
        raise ApplicationReleaseAuditError("application_release evidence identity mismatch")
    if app.get("population_id") != TARGET:
        raise ApplicationReleaseAuditError("application_release evidence population mismatch")
    if (app.get("lineage") or {}) != {"population_id": TARGET, "format": "ZOOM"}:
        raise ApplicationReleaseAuditError("application_release lineage mismatch")
    if ((app.get("provenance") or {}).get("evidence") or {}).get("sha256") != sha256_file(root / PROVENANCE_PATH.relative_to(ROOT)):
        raise ApplicationReleaseAuditError("provenance evidence hash mismatch")
    if ((app.get("decision") or {}).get("evidence") or {}).get("sha256") != sha256_file(root / DECISION_PATH.relative_to(ROOT)):
        raise ApplicationReleaseAuditError("decision evidence hash mismatch")

    resolution = resolve_admission(
        root / EVIDENCE_PATH.relative_to(ROOT),
        root=root,
        expected_population_id=TARGET,
    )
    for role in ("engine", "application_release"):
        row = resolution["admissions"][role]
        if row["status"] != "ADMISSIBLE":
            raise ApplicationReleaseAuditError(f"resolver {role} status is {row['status']!r}")
        if "ROLE_ADMISSIBLE_EXACT" not in row["reason_codes"]:
            raise ApplicationReleaseAuditError(f"resolver {role} missing ROLE_ADMISSIBLE_EXACT")
    for role in REQUIRED_SCIENTIFIC:
        if resolution["admissions"][role]["status"] != "UNRESOLVED":
            raise ApplicationReleaseAuditError(f"resolver must leave {role} unresolved")
    if resolution["candidate_contract"]["candidate_status"] != "BLOCKED_PENDING_SCIENTIFIC_DECISION":
        raise ApplicationReleaseAuditError("whole candidate must remain blocked")

    candidate = resolution["candidate_contract"]
    with tempfile.TemporaryDirectory(dir=root / "tests/audit") as tmp:
        path = Path(tmp) / "candidate.json"
        path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        pre = preflight(path, root=root, expected_population_id=TARGET)

    if pre["result"] != "BLOCKED" or pre["safety"]["writes_performed"] is not False:
        raise ApplicationReleaseAuditError("preflight must remain BLOCKED/read-only")
    if pre["components"]["engine"]["availability"] != "AVAILABLE":
        raise ApplicationReleaseAuditError("preflight engine must be AVAILABLE")
    if pre["components"]["application_release"]["availability"] != "AVAILABLE":
        raise ApplicationReleaseAuditError("preflight application_release must be AVAILABLE")
    if pre["engine_compatibility"]["status"] != "BLOCKED":
        raise ApplicationReleaseAuditError("unpromoted candidate release must keep compatibility blocked")

    blocker_codes = {row["code"] for row in pre["blockers"]}
    for code in ("APPLICATION_RELEASE_NOT_PROMOTED", "POPULATION_STATUS_NOT_PROMOTED"):
        if code not in blocker_codes:
            raise ApplicationReleaseAuditError(f"required preflight blocker missing: {code}")
    forbidden = {"ENGINE_ARTIFACT_MISMATCH", "ENGINE_HASH_MISMATCH", "APPLICATION_RELEASE_NOT_READY"}
    if blocker_codes & forbidden:
        raise ApplicationReleaseAuditError(f"unexpected engine/release binding blocker: {sorted(blocker_codes & forbidden)}")

    exp_resolver = expected.get("expected_resolver_305") or {}
    if exp_resolver.get("engine_status") != resolution["admissions"]["engine"]["status"]:
        raise ApplicationReleaseAuditError("persisted engine resolver result drift")
    if exp_resolver.get("application_release_status") != resolution["admissions"]["application_release"]["status"]:
        raise ApplicationReleaseAuditError("persisted application_release resolver result drift")
    exp_pre = expected.get("expected_preflight_253") or {}
    if exp_pre.get("result") != pre["result"]:
        raise ApplicationReleaseAuditError("persisted preflight result drift")

    return {
        "schema": "poker-pack-application-release-audit/v1",
        "issue": 377,
        "parent_issue": 201,
        "population_id": TARGET,
        "artifact": byte_proof,
        "resolver": {
            "engine_status": resolution["admissions"]["engine"]["status"],
            "application_release_status": resolution["admissions"]["application_release"]["status"],
            "candidate_status": candidate["candidate_status"],
        },
        "preflight": {
            "result": pre["result"],
            "engine_availability": pre["components"]["engine"]["availability"],
            "application_release_availability": pre["components"]["application_release"]["availability"],
            "engine_compatibility": pre["engine_compatibility"]["status"],
            "blocker_codes": sorted(blocker_codes),
            "writes_performed": pre["safety"]["writes_performed"],
        },
        "proof_hashes": {
            "manifest": sha256_file(root / MANIFEST_PATH.relative_to(ROOT)),
            "provenance": sha256_file(root / PROVENANCE_PATH.relative_to(ROOT)),
            "decision": sha256_file(root / DECISION_PATH.relative_to(ROOT)),
            "evidence": sha256_file(root / EVIDENCE_PATH.relative_to(ROOT)),
        },
        "boundaries": {
            "final_pack": False,
            "publication": False,
            "activation": False,
            "promotion": False,
            "test_consumed": False,
            "production_effect": "NONE",
            "parent_201_remains_open": True,
        },
    }

def main() -> int:
    print(json.dumps(audit(), indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
