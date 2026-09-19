#!/usr/bin/env python3
"""Resolve persisted scientific component evidence into pack-role admissions.

This resolver is intentionally read-only and no-promotion. It never mutates the
population registry, catalogue, pointers, releases, or active packs. Its output
contains a deterministic candidate contract compatible with the existing
population_pack_candidate / population_pack_preflight tools.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.population_pack_candidate import (  # noqa: E402
    ADMISSIBLE_DECISION,
    BLOCKED_STATUS,
    EXPLICIT_FALLBACK,
    READY_STATUS,
    REQUIRED_ROLES,
    content_identity,
    sha256_file,
)
from tools.populations.registry import (  # noqa: E402
    PopulationRegistryError,
    load_registry,
    resolve_population,
)

INPUT_SCHEMA = "poker-scientific-component-evidence-set/v1"
OUTPUT_SCHEMA = "poker-scientific-component-admission/v1"
ADMISSIBLE = "ADMISSIBLE"
RETAIN_REFERENCE = "RETAIN_REFERENCE"
UNRESOLVED = "UNRESOLVED"
REJECTED = "REJECTED"
INCOMPATIBLE = "INCOMPATIBLE"
REJECTED_DECISION = "REJECTED"
RETAIN_DECISION = "RETAIN_REFERENCE"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AdmissionResolverError(RuntimeError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdmissionResolverError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AdmissionResolverError(f"{label} must be a JSON object: {path}")
    return value


def _repo_path(root: Path, value: str) -> Path:
    rel = PurePosixPath(str(value))
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        raise AdmissionResolverError(f"unsafe repository-relative path: {value!r}")
    path = root.joinpath(*rel.parts)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise AdmissionResolverError(f"path escapes repository: {value!r}") from exc
    return path


def _source_owners(registry: dict[str, Any], source_rel: str) -> list[dict[str, Any]]:
    normalized = PurePosixPath(source_rel).as_posix().rstrip("/")
    owners: list[dict[str, Any]] = []
    for population_id, spec in registry["populations"].items():
        for role, value in (spec.get("artifacts") or {}).items():
            if not isinstance(value, str) or not value:
                continue
            anchor = PurePosixPath(value).as_posix().rstrip("/")
            if normalized == anchor or normalized.startswith(anchor + "/"):
                owners.append(
                    {
                        "population_id": population_id,
                        "role": role,
                        "format": (spec.get("identity") or {}).get("format"),
                    }
                )
    return sorted(
        owners,
        key=lambda row: (row["population_id"], row["role"], str(row.get("format"))),
    )


def _reason(code: str, *, message: str, severity: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _evidence_ref(
    *,
    root: Path,
    ref: Any,
    label: str,
    reasons: list[dict[str, str]],
    source_refs: list[dict[str, Any]],
) -> bool:
    if not isinstance(ref, dict):
        reasons.append(
            _reason(
                f"{label.upper()}_EVIDENCE_MISSING",
                message=f"{label} evidence object is required",
                severity="UNRESOLVED",
            )
        )
        return False

    rel = str(ref.get("path") or "")
    expected = str(ref.get("sha256") or "")
    if not rel or not SHA256_RE.fullmatch(expected):
        reasons.append(
            _reason(
                f"{label.upper()}_EVIDENCE_MISSING",
                message=f"{label} evidence path and lowercase SHA-256 are required",
                severity="UNRESOLVED",
            )
        )
        return False

    source_refs.append(
        {"kind": f"{label}_evidence", "path": rel, "sha256": expected}
    )
    try:
        path = _repo_path(root, rel)
    except AdmissionResolverError as exc:
        reasons.append(
            _reason(
                f"{label.upper()}_EVIDENCE_INVALID",
                message=str(exc),
                severity="INCOMPATIBLE",
            )
        )
        return False
    if not path.is_file():
        reasons.append(
            _reason(
                f"{label.upper()}_EVIDENCE_MISSING",
                message=f"{label} evidence file missing: {rel}",
                severity="UNRESOLVED",
            )
        )
        return False

    actual = sha256_file(path)
    if actual != expected:
        reasons.append(
            _reason(
                f"{label.upper()}_EVIDENCE_HASH_MISMATCH",
                message=f"{label} evidence hash mismatch for {rel}",
                severity="INCOMPATIBLE",
            )
        )
        return False
    return True


def _fallback_valid(
    *,
    root: Path,
    source_population_id: str,
    provenance: dict[str, Any],
    reasons: list[dict[str, str]],
    source_refs: list[dict[str, Any]],
) -> bool:
    fallback = provenance.get("cross_population_fallback")
    if not isinstance(fallback, dict) or fallback.get("status") != EXPLICIT_FALLBACK:
        reasons.append(
            _reason(
                "CROSS_POPULATION_FALLBACK_NOT_AUTHORIZED",
                message=(
                    f"cross-population source {source_population_id} requires "
                    f"{EXPLICIT_FALLBACK}"
                ),
                severity="INCOMPATIBLE",
            )
        )
        return False
    if fallback.get("source_population_id") != source_population_id:
        reasons.append(
            _reason(
                "CROSS_POPULATION_FALLBACK_SOURCE_MISMATCH",
                message="fallback source_population_id does not match provenance",
                severity="INCOMPATIBLE",
            )
        )
        return False
    if not fallback.get("issue"):
        reasons.append(
            _reason(
                "CROSS_POPULATION_FALLBACK_DECISION_MISSING",
                message="fallback authorization issue/reference is required",
                severity="UNRESOLVED",
            )
        )
        return False
    source_refs.append(
        {
            "kind": "fallback_authorization",
            "issue": str(fallback["issue"]),
            "context_only": True,
        }
    )
    return _evidence_ref(
        root=root,
        ref=fallback.get("evidence"),
        label="fallback",
        reasons=reasons,
        source_refs=source_refs,
    )


def _resolve_role(
    *,
    root: Path,
    registry: dict[str, Any],
    target: dict[str, Any],
    role: str,
    component: Any,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    target_id = target["population_id"]
    target_format = (target.get("identity") or {}).get("format")
    reasons: list[dict[str, str]] = []
    source_refs: list[dict[str, Any]] = []

    if not isinstance(component, dict):
        result = {
            "role": role,
            "status": UNRESOLVED,
            "reason_codes": ["ROLE_MISSING"],
            "reasons": [
                _reason(
                    "ROLE_MISSING",
                    message=f"no persisted component evidence for role {role}",
                    severity="UNRESOLVED",
                )
            ],
            "source_refs": [],
            "artifact": None,
            "lineage": None,
            "scientific_decision": None,
        }
        return result, None

    if component.get("role") != role:
        reasons.append(
            _reason(
                "ROLE_IDENTITY_MISMATCH",
                message=f"component role {component.get('role')!r} does not match {role!r}",
                severity="INCOMPATIBLE",
            )
        )

    component_population = str(component.get("population_id") or "")
    if component_population != target_id:
        reasons.append(
            _reason(
                "POPULATION_ID_MISMATCH",
                message=(
                    f"component population_id {component_population!r} does not match "
                    f"target {target_id!r}"
                ),
                severity="INCOMPATIBLE",
            )
        )

    source_rel = str(component.get("source_path") or "")
    hash_kind = str(component.get("hash_kind") or "")
    declared_sha = str(component.get("sha256") or "")
    artifact_out = {
        "source_path": source_rel or None,
        "hash_kind": hash_kind or None,
        "declared_sha256": declared_sha or None,
        "actual_sha256": None,
        "verified": False,
    }
    if not source_rel:
        reasons.append(
            _reason(
                "ARTIFACT_SOURCE_MISSING",
                message="source_path is required",
                severity="UNRESOLVED",
            )
        )
    elif hash_kind not in {"file_sha256", "tree_sha256"} or not SHA256_RE.fullmatch(
        declared_sha
    ):
        reasons.append(
            _reason(
                "ARTIFACT_IDENTITY_MISSING",
                message="hash_kind and lowercase artifact SHA-256 are required",
                severity="UNRESOLVED",
            )
        )
    else:
        source_refs.append(
            {
                "kind": "artifact",
                "path": source_rel,
                "hash_kind": hash_kind,
                "sha256": declared_sha,
            }
        )
        try:
            source_path = _repo_path(root, source_rel)
        except AdmissionResolverError as exc:
            reasons.append(
                _reason(
                    "ARTIFACT_SOURCE_INVALID",
                    message=str(exc),
                    severity="INCOMPATIBLE",
                )
            )
        else:
            if not source_path.exists():
                reasons.append(
                    _reason(
                        "ARTIFACT_SOURCE_MISSING",
                        message=f"artifact source missing: {source_rel}",
                        severity="UNRESOLVED",
                    )
                )
            else:
                try:
                    actual_kind, actual_sha = content_identity(source_path)
                except Exception as exc:  # candidate helper already fail-closed
                    reasons.append(
                        _reason(
                            "ARTIFACT_SOURCE_INVALID",
                            message=str(exc),
                            severity="INCOMPATIBLE",
                        )
                    )
                else:
                    artifact_out["actual_sha256"] = actual_sha
                    if actual_kind != hash_kind:
                        reasons.append(
                            _reason(
                                "ARTIFACT_HASH_KIND_MISMATCH",
                                message=(
                                    f"declared hash kind {hash_kind!r}, actual "
                                    f"{actual_kind!r}"
                                ),
                                severity="INCOMPATIBLE",
                            )
                        )
                    if actual_sha != declared_sha:
                        reasons.append(
                            _reason(
                                "ARTIFACT_HASH_MISMATCH",
                                message=f"artifact SHA-256 mismatch for {source_rel}",
                                severity="INCOMPATIBLE",
                            )
                        )
                    artifact_out["verified"] = (
                        actual_kind == hash_kind and actual_sha == declared_sha
                    )

    provenance = component.get("provenance")
    provenance_out = provenance if isinstance(provenance, dict) else None
    source_population_id = ""
    if not isinstance(provenance, dict):
        reasons.append(
            _reason(
                "PROVENANCE_MISSING",
                message="persisted provenance object is required",
                severity="UNRESOLVED",
            )
        )
    else:
        source_population_id = str(provenance.get("source_population_id") or "")
        if not source_population_id:
            reasons.append(
                _reason(
                    "PROVENANCE_SOURCE_POPULATION_MISSING",
                    message="provenance.source_population_id is required",
                    severity="UNRESOLVED",
                )
            )
        _evidence_ref(
            root=root,
            ref=provenance.get("evidence"),
            label="provenance",
            reasons=reasons,
            source_refs=source_refs,
        )

    lineage = component.get("lineage")
    lineage_out = lineage if isinstance(lineage, dict) else None
    if not isinstance(lineage, dict):
        reasons.append(
            _reason(
                "LINEAGE_MISSING",
                message="persisted lineage object is required",
                severity="UNRESOLVED",
            )
        )
    else:
        lineage_population = str(lineage.get("population_id") or "")
        lineage_format = str(lineage.get("format") or "")
        if not lineage_population or not lineage_format:
            reasons.append(
                _reason(
                    "LINEAGE_MISSING",
                    message="lineage population_id and format are required",
                    severity="UNRESOLVED",
                )
            )
        if source_population_id and lineage_population != source_population_id:
            reasons.append(
                _reason(
                    "LINEAGE_POPULATION_MISMATCH",
                    message=(
                        f"lineage population {lineage_population!r} does not match "
                        f"provenance source {source_population_id!r}"
                    ),
                    severity="INCOMPATIBLE",
                )
            )
        source_spec = (registry.get("populations") or {}).get(lineage_population)
        registered_format = (
            (source_spec.get("identity") or {}).get("format")
            if isinstance(source_spec, dict)
            else None
        )
        if registered_format and lineage_format != registered_format:
            reasons.append(
                _reason(
                    "LINEAGE_FORMAT_MISMATCH",
                    message=(
                        f"lineage format {lineage_format!r} does not match "
                        f"registered source format {registered_format!r}"
                    ),
                    severity="INCOMPATIBLE",
                )
            )

    owners = _source_owners(registry, source_rel) if source_rel else []
    foreign_mixed = [
        owner
        for owner in owners
        if owner["population_id"] != target_id
        and owner.get("format") == "MIXED_ZOOM_REGULAR"
    ]
    silently_relabelled = bool(
        foreign_mixed
        and source_population_id == target_id
        and isinstance(lineage, dict)
        and lineage.get("population_id") == target_id
    )
    if silently_relabelled:
        reasons.append(
            _reason(
                "LEGACY_MIXED_RELABEL_REJECTED",
                message=(
                    f"MIXED_ZOOM_REGULAR source {source_rel} is registered to a "
                    "foreign population and cannot be presented as Zoom-only"
                ),
                severity="INCOMPATIBLE",
            )
        )

    fallback_ok = True
    if source_population_id and source_population_id != target_id:
        fallback_ok = _fallback_valid(
            root=root,
            source_population_id=source_population_id,
            provenance=provenance if isinstance(provenance, dict) else {},
            reasons=reasons,
            source_refs=source_refs,
        )
    elif isinstance(lineage, dict) and lineage.get("population_id") == target_id:
        if lineage.get("format") != target_format:
            reasons.append(
                _reason(
                    "TARGET_LINEAGE_FORMAT_MISMATCH",
                    message=(
                        f"target-scoped lineage format {lineage.get('format')!r} "
                        f"does not match target format {target_format!r}"
                    ),
                    severity="INCOMPATIBLE",
                )
            )

    decision = component.get("decision")
    decision_out = decision if isinstance(decision, dict) else None
    decision_status = ""
    if not isinstance(decision, dict):
        reasons.append(
            _reason(
                "SCIENTIFIC_DECISION_MISSING",
                message=(
                    "persisted scientific decision is required; issue state alone "
                    "is never admission evidence"
                ),
                severity="UNRESOLVED",
            )
        )
    else:
        decision_status = str(decision.get("status") or "")
        issue = decision.get("issue")
        if issue:
            source_refs.append(
                {
                    "kind": "decision_context",
                    "issue": str(issue),
                    "context_only": True,
                }
            )
        _evidence_ref(
            root=root,
            ref=decision.get("evidence"),
            label="decision",
            reasons=reasons,
            source_refs=source_refs,
        )
        if not decision_status:
            reasons.append(
                _reason(
                    "SCIENTIFIC_DECISION_MISSING",
                    message="scientific decision.status is required",
                    severity="UNRESOLVED",
                )
            )

    incompatible = any(row["severity"] == "INCOMPATIBLE" for row in reasons)
    unresolved = any(row["severity"] == "UNRESOLVED" for row in reasons)

    if incompatible:
        status = INCOMPATIBLE
    elif unresolved:
        status = UNRESOLVED
    elif decision_status == REJECTED_DECISION:
        status = REJECTED
        reasons.append(
            _reason(
                "SCIENTIFIC_DECISION_REJECTED",
                message="persisted scientific decision rejects this artifact",
                severity="TERMINAL",
            )
        )
    elif decision_status == RETAIN_DECISION:
        status = RETAIN_REFERENCE
        reasons.append(
            _reason(
                "SCIENTIFIC_DECISION_RETAIN_REFERENCE",
                message=(
                    "persisted decision retains the existing reference; it is not "
                    "converted into pack admissibility"
                ),
                severity="TERMINAL",
            )
        )
    elif decision_status == ADMISSIBLE_DECISION:
        status = ADMISSIBLE
        reasons.append(
            _reason(
                "ROLE_ADMISSIBLE_EXACT",
                message="artifact, population, lineage, provenance and decision verified",
                severity="PASS",
            )
        )
    else:
        status = UNRESOLVED
        reasons.append(
            _reason(
                "SCIENTIFIC_DECISION_STATUS_UNRESOLVED",
                message=(
                    f"decision status {decision_status!r} has no explicit pack "
                    "admission mapping"
                ),
                severity="UNRESOLVED",
            )
        )

    candidate_component = None
    if status == ADMISSIBLE and fallback_ok:
        candidate_component = {
            "role": role,
            "population_id": target_id,
            "source_path": source_rel,
            "hash_kind": hash_kind,
            "sha256": declared_sha,
            "provenance": provenance,
            "decision": {
                "status": ADMISSIBLE_DECISION,
                "issue": decision.get("issue"),
                "evidence": decision.get("evidence"),
            },
        }

    result = {
        "role": role,
        "status": status,
        "reason_codes": [row["code"] for row in reasons],
        "reasons": reasons,
        "source_refs": source_refs,
        "artifact": artifact_out,
        "lineage": lineage_out,
        "scientific_decision": decision_out,
        "registered_source_owners": owners,
    }
    return result, candidate_component


def resolve_admission(
    evidence_path: Path,
    *,
    root: Path = ROOT,
    expected_population_id: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    path = evidence_path if evidence_path.is_absolute() else root / evidence_path
    evidence = _load_json(path, label="scientific evidence set")
    if evidence.get("schema") != INPUT_SCHEMA:
        raise AdmissionResolverError(
            f"unsupported evidence schema: {evidence.get('schema')!r}"
        )
    population_id = str(evidence.get("population_id") or "")
    if not population_id:
        raise AdmissionResolverError("evidence population_id is required")
    if expected_population_id and population_id != expected_population_id:
        raise AdmissionResolverError(
            f"population mismatch: expected {expected_population_id}, got {population_id}"
        )
    try:
        registry = load_registry(root)
        target = resolve_population(root, population_id)
    except PopulationRegistryError as exc:
        raise AdmissionResolverError(str(exc)) from exc

    components = evidence.get("components")
    if not isinstance(components, dict):
        raise AdmissionResolverError("evidence components object is required")

    input_sha = sha256_file(path)
    admissions: dict[str, Any] = {}
    candidate_components: dict[str, Any] = {}
    for role in REQUIRED_ROLES:
        admission, candidate_component = _resolve_role(
            root=root,
            registry=registry,
            target=target,
            role=role,
            component=components.get(role),
        )
        admissions[role] = admission
        candidate_components[role] = candidate_component

    all_admissible = all(
        admissions[role]["status"] == ADMISSIBLE for role in REQUIRED_ROLES
    )
    candidate = {
        "schema": "poker-population-pack-candidate/v1",
        "candidate_id": f"{population_id}@admission-{input_sha[:16]}",
        "candidate_status": READY_STATUS if all_admissible else BLOCKED_STATUS,
        "population_id": population_id,
        "blocked_on": [],
        "publication_policy": {
            "release_allowed": False,
            "catalog_eligible": False,
            "recommended": False,
            "default": False,
        },
        "required_roles": list(REQUIRED_ROLES),
        "components": candidate_components,
        "resolver": {
            "schema": OUTPUT_SCHEMA,
            "input_path": path.relative_to(root).as_posix(),
            "input_sha256": input_sha,
        },
    }
    candidate_sha = canonical_sha256(candidate)

    core = {
        "schema": OUTPUT_SCHEMA,
        "population_id": population_id,
        "target_population_status": target.get("status"),
        "target_population_identity": target.get("identity"),
        "input": {
            "path": path.relative_to(root).as_posix(),
            "sha256": input_sha,
            "schema": INPUT_SCHEMA,
        },
        "admissions": admissions,
        "summary": {
            status: sum(
                1 for row in admissions.values() if row["status"] == status
            )
            for status in (
                ADMISSIBLE,
                RETAIN_REFERENCE,
                UNRESOLVED,
                REJECTED,
                INCOMPATIBLE,
            )
        },
        "candidate_contract": candidate,
        "preflight_input": {
            "schema": "poker-population-pack-preflight-input/v1",
            "candidate_contract_sha256": candidate_sha,
            "expected_population_id": population_id,
            "materialization_required": True,
            "note": (
                "Serialize candidate_contract canonically to a caller-controlled "
                "temporary/output path, then invoke existing preflight. Resolver "
                "itself performs no writes."
            ),
        },
        "safety": {
            "read_only": True,
            "writes_performed": False,
            "consumes_live_issue_state": False,
            "population_registry_updates": False,
            "production_pointer_updates": False,
            "catalogue_updates": False,
            "recommended_or_default_changes": False,
            "release_publication": False,
            "pack_activation": False,
            "promotion": False,
        },
    }
    result = dict(core)
    result["resolution_sha256"] = canonical_sha256(core)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--population-id")
    args = parser.parse_args()
    try:
        result = resolve_admission(
            args.evidence,
            expected_population_id=args.population_id,
        )
    except AdmissionResolverError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
