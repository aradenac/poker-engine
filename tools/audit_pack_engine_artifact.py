#!/usr/bin/env python3
"""Audit #370 engine artifact through resolver #305 and preflight #253.

Read-only: no publication, activation, registry/catalogue/pointer mutation or
scientific TEST consumption.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any

from tools.build_pack_engine_artifact import (
    EngineArtifactError,
    RUN_DIR,
    ROOT,
    TARGET,
    sha256_file,
    validate_materialized_artifact,
)
from tools.population_pack_admission import resolve_admission
from tools.population_pack_preflight import preflight

EVIDENCE_PATH = RUN_DIR / "EVIDENCE_SET.json"
MANIFEST_PATH = RUN_DIR / "ENGINE_ARTIFACT_MANIFEST.json"
PROVENANCE_PATH = RUN_DIR / "PROVENANCE.json"
DECISION_PATH = RUN_DIR / "ROLE_DECISION.json"
RESULT_PATH = RUN_DIR / "RESULT.json"

class EngineArtifactAuditError(RuntimeError):
    pass

def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EngineArtifactAuditError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EngineArtifactAuditError(f"expected JSON object: {path}")
    return value

def audit(*, root: Path = ROOT) -> dict[str, Any]:
    materialized = validate_materialized_artifact(root=root)
    run_dir = root / RUN_DIR.relative_to(ROOT)
    evidence_path = run_dir / "EVIDENCE_SET.json"
    manifest_path = run_dir / "ENGINE_ARTIFACT_MANIFEST.json"
    provenance_path = run_dir / "PROVENANCE.json"
    decision_path = run_dir / "ROLE_DECISION.json"
    result_path = run_dir / "RESULT.json"

    evidence = _load(evidence_path)
    manifest = _load(manifest_path)
    provenance = _load(provenance_path)
    decision = _load(decision_path)
    expected = _load(result_path)

    if manifest.get("schema") != "poker-pack-engine-artifact-manifest/v1":
        raise EngineArtifactAuditError("manifest schema mismatch")
    if provenance.get("schema") != "poker-pack-engine-provenance/v1":
        raise EngineArtifactAuditError("provenance schema mismatch")
    if decision.get("schema") != "poker-pack-engine-role-decision/v1":
        raise EngineArtifactAuditError("decision schema mismatch")
    if decision.get("status") != "ADMISSIBLE_FOR_PACK":
        raise EngineArtifactAuditError("engine role decision must be ADMISSIBLE_FOR_PACK")
    if decision.get("scientific_performance_claim") is not False:
        raise EngineArtifactAuditError("runtime compatibility decision cannot claim scientific performance")
    if decision.get("test_consumed") is not False:
        raise EngineArtifactAuditError("scientific TEST must remain unconsumed")

    artifact = manifest.get("artifact") or {}
    if artifact.get("path") != materialized["artifact_path"] or artifact.get("sha256") != materialized["artifact_sha256"]:
        raise EngineArtifactAuditError("manifest/materialized artifact identity mismatch")
    if manifest.get("immutable") is not True or manifest.get("content_addressed") is not True:
        raise EngineArtifactAuditError("artifact manifest must be immutable/content-addressed")
    if (manifest.get("runtime_dependencies") or {}).get("closure") != "SELF_CONTAINED":
        raise EngineArtifactAuditError("runtime dependency closure must be self-contained")
    if (manifest.get("runtime_dependencies") or {}).get("external") not in ([], None):
        raise EngineArtifactAuditError("unexpected external runtime dependency")
    if (manifest.get("compatibility") or {}).get("legacy_mixed_bytes_reused") is not False:
        raise EngineArtifactAuditError("legacy bytes reuse is forbidden")

    evidence_engine = ((evidence.get("components") or {}).get("engine") or {})
    if evidence_engine.get("source_path") != materialized["artifact_path"]:
        raise EngineArtifactAuditError("evidence artifact path mismatch")
    if evidence_engine.get("sha256") != materialized["artifact_sha256"]:
        raise EngineArtifactAuditError("evidence artifact hash mismatch")
    if evidence_engine.get("population_id") != TARGET:
        raise EngineArtifactAuditError("evidence population mismatch")
    if (evidence_engine.get("lineage") or {}) != {"population_id": TARGET, "format": "ZOOM"}:
        raise EngineArtifactAuditError("engine lineage mismatch")

    provenance_ref = (evidence_engine.get("provenance") or {}).get("evidence") or {}
    if provenance_ref.get("path") != PROVENANCE_PATH.relative_to(ROOT).as_posix():
        raise EngineArtifactAuditError("provenance path mismatch")
    if provenance_ref.get("sha256") != sha256_file(provenance_path):
        raise EngineArtifactAuditError("provenance evidence hash mismatch")
    decision_ref = (evidence_engine.get("decision") or {}).get("evidence") or {}
    if decision_ref.get("path") != DECISION_PATH.relative_to(ROOT).as_posix():
        raise EngineArtifactAuditError("decision path mismatch")
    if decision_ref.get("sha256") != sha256_file(decision_path):
        raise EngineArtifactAuditError("decision evidence hash mismatch")

    resolution = resolve_admission(
        evidence_path,
        root=root,
        expected_population_id=TARGET,
    )
    engine_row = resolution["admissions"]["engine"]
    if engine_row["status"] != "ADMISSIBLE":
        raise EngineArtifactAuditError(f"resolver engine status is {engine_row['status']!r}")
    if "ROLE_ADMISSIBLE_EXACT" not in engine_row["reason_codes"]:
        raise EngineArtifactAuditError("resolver did not emit ROLE_ADMISSIBLE_EXACT")
    if "LEGACY_MIXED_RELABEL_REJECTED" in engine_row["reason_codes"]:
        raise EngineArtifactAuditError("fresh artifact was incorrectly classified as legacy relabel")
    candidate_engine = resolution["candidate_contract"]["components"]["engine"]
    if not isinstance(candidate_engine, dict):
        raise EngineArtifactAuditError("resolver did not materialize engine candidate component")
    if candidate_engine.get("source_path") != materialized["artifact_path"]:
        raise EngineArtifactAuditError("resolver candidate engine path mismatch")
    if candidate_engine.get("sha256") != materialized["artifact_sha256"]:
        raise EngineArtifactAuditError("resolver candidate engine hash mismatch")
    if resolution["candidate_contract"]["candidate_status"] != "BLOCKED_PENDING_SCIENTIFIC_DECISION":
        raise EngineArtifactAuditError("whole pack candidate must remain blocked")
    if resolution["candidate_contract"]["components"]["application_release"] is not None:
        raise EngineArtifactAuditError("#370 must not provide application_release")

    with tempfile.TemporaryDirectory() as tmp:
        contract_path = Path(tmp) / "candidate.json"
        contract_path.write_text(
            json.dumps(resolution["candidate_contract"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        pre = preflight(contract_path, root=root, expected_population_id=TARGET)

    if pre["result"] != "BLOCKED":
        raise EngineArtifactAuditError("preflight must remain BLOCKED")
    if pre["safety"]["writes_performed"] is not False:
        raise EngineArtifactAuditError("preflight must be read-only")
    if pre["components"]["engine"]["availability"] != "AVAILABLE":
        raise EngineArtifactAuditError("preflight must recognize engine as AVAILABLE")
    if pre["engine_compatibility"]["status"] != "BLOCKED":
        raise EngineArtifactAuditError("engine/application compatibility must remain blocked without application_release")
    blocker_codes = {row["code"] for row in pre["blockers"]}
    for required in ("APPLICATION_RELEASE_NOT_READY", "POPULATION_STATUS_NOT_PROMOTED"):
        if required not in blocker_codes:
            raise EngineArtifactAuditError(f"expected preflight blocker missing: {required}")

    exp_resolver = expected.get("expected_resolver_305") or {}
    if exp_resolver.get("engine_status") != engine_row["status"]:
        raise EngineArtifactAuditError("persisted resolver result drift")
    if exp_resolver.get("candidate_engine_source_path") != candidate_engine.get("source_path"):
        raise EngineArtifactAuditError("persisted resolver candidate path drift")
    if exp_resolver.get("candidate_engine_sha256") != candidate_engine.get("sha256"):
        raise EngineArtifactAuditError("persisted resolver candidate hash drift")
    exp_preflight = expected.get("expected_preflight_253") or {}
    if exp_preflight.get("result") != pre["result"]:
        raise EngineArtifactAuditError("persisted preflight result drift")
    if exp_preflight.get("engine_component_availability") != pre["components"]["engine"]["availability"]:
        raise EngineArtifactAuditError("persisted preflight engine availability drift")
    if exp_preflight.get("engine_compatibility") != pre["engine_compatibility"]["status"]:
        raise EngineArtifactAuditError("persisted preflight compatibility drift")

    return {
        "schema": "poker-pack-engine-artifact-audit/v1",
        "issue": 370,
        "parent_issue": 201,
        "population_id": TARGET,
        "artifact": materialized,
        "resolver": {
            "schema": resolution["schema"],
            "engine_status": engine_row["status"],
            "engine_reason_codes": engine_row["reason_codes"],
            "candidate_status": resolution["candidate_contract"]["candidate_status"],
            "candidate_engine": {
                "source_path": candidate_engine["source_path"],
                "sha256": candidate_engine["sha256"],
            },
        },
        "preflight": {
            "schema": pre["schema"],
            "result": pre["result"],
            "engine_availability": pre["components"]["engine"]["availability"],
            "engine_compatibility": pre["engine_compatibility"]["status"],
            "blocker_codes": sorted(blocker_codes),
            "writes_performed": pre["safety"]["writes_performed"],
        },
        "proof_hashes": {
            "manifest": sha256_file(manifest_path),
            "provenance": sha256_file(provenance_path),
            "decision": sha256_file(decision_path),
            "evidence": sha256_file(evidence_path),
        },
        "boundaries": {
            "application_release_modified": False,
            "final_pack_created": False,
            "publication": False,
            "activation": False,
            "promotion": False,
            "model_a_b_modified": False,
            "hero_ev": False,
            "test_consumed": False,
            "production_effect": "NONE",
            "parent_201_remains_open": True,
        },
    }

def main() -> int:
    try:
        value = audit()
    except (EngineArtifactError, EngineArtifactAuditError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
