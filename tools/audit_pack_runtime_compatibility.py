#!/usr/bin/env python3
"""Verify #360 fresh runtime compatibility evidence without promotion/publication.

This audit is intentionally fail-closed. It proves only what the current runtime
bytes demonstrate:
- a pure source subset is population-agnostic;
- no fresh distributable pack-engine artifact is materialized yet;
- the current application shell remains coupled to legacy/scientific defaults.

It reuses the #305 admission resolver and #253 preflight. No registry, pointer,
catalogue, release, model or strategy state is mutated.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

from tools.population_pack_admission import resolve_admission
from tools.population_pack_candidate import sha256_file
from tools.population_pack_preflight import preflight

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "training/runs/20260919_pack_runtime_compatibility"
PROVENANCE_PATH = RUN_DIR / "SOURCE_PROVENANCE.json"
ENGINE_PATH = RUN_DIR / "ENGINE_CANDIDATE.json"
APPLICATION_RELEASE_PATH = RUN_DIR / "APPLICATION_RELEASE_CANDIDATE.json"
DECISIONS_PATH = RUN_DIR / "ROLE_DECISIONS.json"
EVIDENCE_PATH = RUN_DIR / "EVIDENCE_SET.json"
TARGET = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
LEGACY = "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1"
EXPECTED_ENGINE_BLOCKER = "NO_FRESH_DISTRIBUTABLE_ENGINE_ARTIFACT"
EXPECTED_APP_BLOCKERS = {
    "CURRENT_RELEASE_BINDS_LEGACY_ENGINE",
    "CURRENT_APPLICATION_LOADS_MODEL_A_V5_DEFAULTS",
    "CURRENT_PREFLOP_RUNTIME_BINDS_RETAINED_REFERENCE",
    "PROMOTION_FORBIDDEN_IN_ISSUE_360",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")


class RuntimeCompatibilityError(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeCompatibilityError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeCompatibilityError(f"expected object: {path}")
    return value


def _git_blob(path: Path, *, root: Path) -> str:
    return subprocess.check_output(
        ["git", "hash-object", str(path.relative_to(root))],
        cwd=root,
        text=True,
    ).strip()


def _sha256_json(value: Any) -> str:
    payload=(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)+"\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _compact_sha256(value: Any) -> str:
    payload=json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_source_provenance(
    provenance: dict[str, Any],
    engine_candidate: dict[str, Any],
    application_candidate: dict[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    if provenance.get("schema") != "poker-pack-runtime-compatibility-provenance/v1":
        raise RuntimeCompatibilityError("invalid provenance schema")
    if provenance.get("population_id") != TARGET:
        raise RuntimeCompatibilityError("provenance population mismatch")
    source_commit = str(provenance.get("runtime_source_commit") or "")
    if not HEX40.fullmatch(source_commit):
        raise RuntimeCompatibilityError("runtime_source_commit must be a lowercase git SHA")

    generic = provenance.get("generic_engine_core") or {}
    if generic.get("status") != "POPULATION_AGNOSTIC_SOURCE_SUBSET_CONFIRMED":
        raise RuntimeCompatibilityError("generic engine source subset is not confirmed")
    if generic.get("distributable_pack_engine_materialized") is not False:
        raise RuntimeCompatibilityError("generic source subset must not masquerade as a pack engine")

    forbidden = list(generic.get("forbidden_markers") or [])
    rows = list(generic.get("files") or [])
    if not rows:
        raise RuntimeCompatibilityError("generic source file set is empty")
    if generic.get("source_set_sha256") not in (None, _compact_sha256([
        {"path": row.get("path"), "git_blob_sha": row.get("git_blob_sha"), "sha256": row.get("sha256")}
        for row in rows
    ])):
        raise RuntimeCompatibilityError("generic source-set aggregate hash mismatch")
    for row in rows:
        rel = str(row.get("path") or "")
        path = root / rel
        if not path.is_file():
            raise RuntimeCompatibilityError(f"source file missing: {rel}")
        if sha256_file(path) != row.get("sha256"):
            raise RuntimeCompatibilityError(f"source SHA-256 mismatch: {rel}")
        if _git_blob(path, root=root) != row.get("git_blob_sha"):
            raise RuntimeCompatibilityError(f"source git blob mismatch: {rel}")
        text = path.read_text(encoding="utf-8")
        hits = [marker for marker in forbidden if marker in text]
        if hits or row.get("forbidden_marker_hits") not in ([], None):
            raise RuntimeCompatibilityError(f"population/scientific marker leaked into generic engine source {rel}: {hits}")

    for doc, label in (
        (engine_candidate, "engine candidate"),
        (application_candidate, "application release candidate"),
    ):
        if doc.get("runtime_source_commit") != source_commit:
            raise RuntimeCompatibilityError(f"{label} source commit mismatch")
        prov_ref = doc.get("provenance") or {}
        if prov_ref.get("path") != PROVENANCE_PATH.relative_to(root).as_posix():
            raise RuntimeCompatibilityError(f"{label} provenance path mismatch")
        if prov_ref.get("sha256") != sha256_file(PROVENANCE_PATH):
            raise RuntimeCompatibilityError(f"{label} provenance hash mismatch")

    if engine_candidate.get("role") != "engine" or engine_candidate.get("population_id") != TARGET:
        raise RuntimeCompatibilityError("engine candidate identity mismatch")
    if (engine_candidate.get("compatibility") or {}).get("pack_role_admissible") is not False:
        raise RuntimeCompatibilityError("engine descriptor must remain non-admissible")
    if (engine_candidate.get("blocker") or {}).get("code") != EXPECTED_ENGINE_BLOCKER:
        raise RuntimeCompatibilityError("engine blocker changed")

    if application_candidate.get("schema") != "poker-site-release/v3":
        raise RuntimeCompatibilityError("application candidate must retain release v3 schema")
    if application_candidate.get("status") != "candidate_unpublished" or application_candidate.get("published") is not False:
        raise RuntimeCompatibilityError("application candidate must remain unpublished")
    app_codes = {
        row.get("code")
        for row in (application_candidate.get("compatibility") or {}).get("blockers") or []
    }
    if app_codes != EXPECTED_APP_BLOCKERS:
        raise RuntimeCompatibilityError("application blocker set changed")
    if (application_candidate.get("compatibility") or {}).get("pack_role_admissible") is not False:
        raise RuntimeCompatibilityError("application candidate must remain non-admissible")

    current = provenance.get("current_application") or {}
    release_row = current.get("release_anchor") or {}
    release_path = root / str(release_row.get("path") or "")
    release = _load(release_path)
    if sha256_file(release_path) != release_row.get("sha256"):
        raise RuntimeCompatibilityError("current release anchor hash mismatch")
    legacy_engine = ((release.get("identity") or {}).get("engine_release") or {}).get("artifact")
    if legacy_engine != (provenance.get("registry") or {}).get("legacy_engine"):
        raise RuntimeCompatibilityError("current release no longer binds the registered legacy engine")
    if release.get("models") != release_row.get("models"):
        raise RuntimeCompatibilityError("current release model identity drift")

    trainer_row = current.get("trainer") or {}
    trainer_path = root / str(trainer_row.get("path") or "")
    if sha256_file(trainer_path) != trainer_row.get("sha256"):
        raise RuntimeCompatibilityError("trainer hash mismatch")
    trainer_text = trainer_path.read_text(encoding="utf-8")
    for marker in trainer_row.get("markers") or []:
        if marker not in trainer_text:
            raise RuntimeCompatibilityError(f"trainer blocker marker disappeared: {marker}")

    pre_row = current.get("preflop_runtime") or {}
    pre_path = root / str(pre_row.get("path") or "")
    if sha256_file(pre_path) != pre_row.get("sha256"):
        raise RuntimeCompatibilityError("preflop runtime hash mismatch")
    pre_text = pre_path.read_text(encoding="utf-8")
    for marker in pre_row.get("markers") or []:
        if marker not in pre_text:
            raise RuntimeCompatibilityError(f"preflop runtime blocker marker disappeared: {marker}")

    registry = provenance.get("registry") or {}
    if registry.get("target_status") != "CERTIFIED_DATA_ONLY":
        raise RuntimeCompatibilityError("target population status changed; refresh proof")
    if registry.get("target_format") != "ZOOM":
        raise RuntimeCompatibilityError("target format changed")
    if registry.get("target_legacy_unscoped_artifacts_allowed") is not False:
        raise RuntimeCompatibilityError("target unexpectedly allows legacy unscoped artifacts")
    if registry.get("legacy_format") != "MIXED_ZOOM_REGULAR":
        raise RuntimeCompatibilityError("legacy lineage format changed")

    return {
        "runtime_source_commit": source_commit,
        "generic_files_verified": len(rows),
        "engine_blocker": EXPECTED_ENGINE_BLOCKER,
        "application_blockers": sorted(EXPECTED_APP_BLOCKERS),
    }


def audit(*, root: Path = ROOT) -> dict[str, Any]:
    provenance = _load(PROVENANCE_PATH)
    engine = _load(ENGINE_PATH)
    app = _load(APPLICATION_RELEASE_PATH)
    decisions = _load(DECISIONS_PATH)
    evidence = _load(EVIDENCE_PATH)

    verification = validate_source_provenance(provenance, engine, app, root=root)
    if decisions.get("runtime_source_commit") != verification["runtime_source_commit"]:
        raise RuntimeCompatibilityError("decision/source commit mismatch")
    if evidence.get("population_id") != TARGET:
        raise RuntimeCompatibilityError("evidence population mismatch")

    resolution = resolve_admission(
        EVIDENCE_PATH,
        root=root,
        expected_population_id=TARGET,
    )
    for role in ("engine", "application_release"):
        if resolution["admissions"][role]["status"] != "UNRESOLVED":
            raise RuntimeCompatibilityError(f"{role} must remain UNRESOLVED")
        if resolution["candidate_contract"]["components"][role] is not None:
            raise RuntimeCompatibilityError(f"{role} must not enter candidate pack components")

    # #253 consumption proof: materialize only the resolver output in a temporary,
    # automatically removed path. No production/config state is modified.
    with tempfile.TemporaryDirectory(dir=root / "tests/packs") as tmp:
        temp = Path(tmp) / "candidate.json"
        temp.write_text(
            json.dumps(resolution["candidate_contract"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        pre = preflight(temp.relative_to(root), root=root, expected_population_id=TARGET)

    if pre["result"] != "BLOCKED" or pre["safety"]["writes_performed"] is not False:
        raise RuntimeCompatibilityError("preflight must remain blocked/read-only")
    if pre["engine_compatibility"]["status"] != "BLOCKED":
        raise RuntimeCompatibilityError("engine/application compatibility must remain blocked")

    core = {
        "schema": "poker-pack-runtime-compatibility-result/v1",
        "issue": 360,
        "parent_issue": 201,
        "population_id": TARGET,
        "runtime_source_commit": verification["runtime_source_commit"],
        "roles": {
            "engine": {
                "status": "UNRESOLVED",
                "blocker_codes": [EXPECTED_ENGINE_BLOCKER],
                "candidate_path": ENGINE_PATH.relative_to(root).as_posix(),
                "candidate_sha256": sha256_file(ENGINE_PATH),
            },
            "application_release": {
                "status": "UNRESOLVED",
                "blocker_codes": sorted(EXPECTED_APP_BLOCKERS),
                "candidate_path": APPLICATION_RELEASE_PATH.relative_to(root).as_posix(),
                "candidate_sha256": sha256_file(APPLICATION_RELEASE_PATH),
            },
        },
        "resolver": {
            "schema": resolution["schema"],
            "input_sha256": resolution["input"]["sha256"],
            "resolution_sha256": resolution["resolution_sha256"],
            "engine_status": resolution["admissions"]["engine"]["status"],
            "application_release_status": resolution["admissions"]["application_release"]["status"],
            "candidate_status": resolution["candidate_contract"]["candidate_status"],
        },
        "preflight": {
            "schema": pre["schema"],
            "result": pre["result"],
            "engine_compatibility": pre["engine_compatibility"]["status"],
            "dry_run": pre["safety"]["dry_run"],
            "writes_performed": pre["safety"]["writes_performed"],
        },
        "proofs": {
            "source_provenance_sha256": sha256_file(PROVENANCE_PATH),
            "role_decisions_sha256": sha256_file(DECISIONS_PATH),
            "evidence_set_sha256": sha256_file(EVIDENCE_PATH),
            "generic_files_verified": verification["generic_files_verified"],
        },
        "boundaries": {
            "legacy_relabelled": False,
            "publication": False,
            "activation": False,
            "promotion": False,
            "registry_mutation": False,
            "pointer_mutation": False,
            "catalogue_mutation": False,
            "model_a_b_modified": False,
            "hero_ev": False,
            "test_consumed": False,
            "production_effect": "NONE",
            "parent_201_remains_open": True,
        },
    }
    result = copy.deepcopy(core)
    result["result_sha256"] = _sha256_json(core)
    return result


def main() -> int:
    print(json.dumps(audit(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
