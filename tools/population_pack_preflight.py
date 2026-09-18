#!/usr/bin/env python3
"""Machine-readable, side-effect-free preflight for the Zoom 100/200 pack.

The preflight deliberately performs no publication, activation, catalogue update,
registry mutation, or production-pointer change. It reports whether the existing
population-pack candidate contract is ready to pass the assembly gate introduced
by issue #201 / PR #237.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.population_pack_candidate import (  # noqa: E402
    ADMISSIBLE_DECISION,
    READY_STATUS,
    REQUIRED_ROLES,
    CandidateContractError,
    content_identity,
    sha256_file,
    validate_candidate_contract,
)
from tools.populations.registry import (  # noqa: E402
    PopulationRegistryError,
    load_registry,
    resolve_population,
)

SCHEMA = "poker-population-pack-preflight/v1"
TARGET_POPULATION = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
DEFAULT_CONTRACT = Path(
    "user/packs/pokerstars_nlhe_100-200_zoom_play_6max_v1/candidate.json"
)
ASSEMBLY_READY_POPULATION_STATUS = "PROMOTED"


class PreflightError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PreflightError(f"expected JSON object: {path}")
    return value


def _repo_path(root: Path, value: str) -> Path:
    rel = PurePosixPath(str(value))
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        raise PreflightError(f"unsafe repository-relative path: {value!r}")
    path = root.joinpath(*rel.parts)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise PreflightError(f"path escapes repository: {value!r}") from exc
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
    return sorted(owners, key=lambda row: (row["population_id"], row["role"]))


def _blocker_code(message: str) -> str:
    lower = message.lower()
    if "unresolved component" in lower:
        return "COMPONENT_UNRESOLVED"
    if "silently relabelled" in lower:
        return "LEGACY_MIXED_RELABEL_REJECTED"
    if "cross-population" in lower or "fallback" in lower:
        return "CROSS_POPULATION_FALLBACK_NOT_AUTHORIZED"
    if "decision.status" in lower or "decision.issue" in lower:
        return "SCIENTIFIC_DECISION_NOT_ADMISSIBLE"
    if "provenance" in lower:
        return "PROVENANCE_INVALID"
    if "hash" in lower or "sha256" in lower:
        return "CONTENT_IDENTITY_INVALID"
    if "population_id" in lower or "population mismatch" in lower:
        return "POPULATION_IDENTITY_INVALID"
    if "source does not exist" in lower or "source_path" in lower:
        return "COMPONENT_SOURCE_INVALID"
    return "COMPONENT_CONTRACT_INVALID"


def _role_from_message(message: str) -> str | None:
    role = message.split(":", 1)[0]
    return role if role in REQUIRED_ROLES else None


def _structured_candidate_blockers(messages: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "code": _blocker_code(message),
            "role": _role_from_message(message),
            "message": message,
        }
        for message in messages
    ]


def _component_report(
    *,
    root: Path,
    registry: dict[str, Any],
    target_population_id: str,
    role: str,
    component: Any,
    candidate_messages: list[str],
) -> dict[str, Any]:
    role_messages = [
        message for message in candidate_messages if _role_from_message(message) == role
    ]
    if not isinstance(component, dict):
        return {
            "role": role,
            "availability": "UNRESOLVED",
            "population_id": None,
            "source_path": None,
            "provenance": None,
            "hash": {
                "kind": None,
                "declared_sha256": None,
                "actual_sha256": None,
                "verified": False,
            },
            "scientific_status": {
                "status": "UNRESOLVED",
                "issue": None,
                "evidence": None,
                "admissible": False,
            },
            "registered_source_owners": [],
            "blockers": _structured_candidate_blockers(role_messages),
        }

    source_rel = str(component.get("source_path") or "")
    actual_kind = None
    actual_sha = None
    if source_rel:
        try:
            source = _repo_path(root, source_rel)
            if source.exists():
                actual_kind, actual_sha = content_identity(source)
        except (PreflightError, CandidateContractError):
            pass

    provenance = component.get("provenance")
    provenance_out = provenance if isinstance(provenance, dict) else None
    decision = component.get("decision")
    decision_out = decision if isinstance(decision, dict) else {}
    owners = _source_owners(registry, source_rel) if source_rel else []
    foreign_mixed = [
        owner
        for owner in owners
        if owner["population_id"] != target_population_id
        and owner.get("format") == "MIXED_ZOOM_REGULAR"
    ]
    source_population_id = (
        provenance_out.get("source_population_id") if provenance_out else None
    )
    silently_relabelled = bool(
        foreign_mixed and source_population_id == target_population_id
    )

    declared_sha = str(component.get("sha256") or "") or None
    declared_kind = str(component.get("hash_kind") or "") or None
    hash_verified = bool(
        declared_sha
        and actual_sha
        and declared_sha == actual_sha
        and declared_kind == actual_kind
    )
    admissible = decision_out.get("status") == ADMISSIBLE_DECISION
    valid = not role_messages and hash_verified and admissible and not silently_relabelled

    blockers = _structured_candidate_blockers(role_messages)
    if silently_relabelled and not any(
        row["code"] == "LEGACY_MIXED_RELABEL_REJECTED" for row in blockers
    ):
        blockers.append(
            {
                "code": "LEGACY_MIXED_RELABEL_REJECTED",
                "role": role,
                "message": (
                    f"{role}: MIXED_ZOOM_REGULAR source {source_rel} cannot be "
                    "presented as Zoom-only"
                ),
            }
        )

    return {
        "role": role,
        "availability": "AVAILABLE" if valid else "INVALID",
        "population_id": component.get("population_id"),
        "source_path": source_rel or None,
        "provenance": provenance_out,
        "hash": {
            "kind": declared_kind,
            "declared_sha256": declared_sha,
            "actual_sha256": actual_sha,
            "verified": hash_verified,
        },
        "scientific_status": {
            "status": decision_out.get("status", "UNRESOLVED"),
            "issue": decision_out.get("issue"),
            "evidence": decision_out.get("evidence"),
            "admissible": admissible,
        },
        "registered_source_owners": owners,
        "blockers": blockers,
    }


def _engine_compatibility(
    *,
    root: Path,
    components: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    engine = components["engine"]
    app = components["application_release"]
    blockers: list[dict[str, Any]] = []

    if engine["availability"] != "AVAILABLE":
        blockers.append(
            {
                "code": "ENGINE_COMPONENT_NOT_READY",
                "message": "engine component is not available and admissible",
            }
        )
    if app["availability"] != "AVAILABLE":
        blockers.append(
            {
                "code": "APPLICATION_RELEASE_NOT_READY",
                "message": "application_release component is not available and admissible",
            }
        )

    declared_artifact = None
    declared_sha = None
    release_schema = None
    release_status = None
    app_source = app.get("source_path")
    if app_source:
        try:
            app_path = _repo_path(root, str(app_source))
            release = _load_json(app_path)
            release_schema = release.get("schema")
            release_status = release.get("status")
            identity = (release.get("identity") or {}).get("engine_release") or {}
            declared_artifact = identity.get("artifact")
            declared_sha = identity.get("sha256")
        except PreflightError as exc:
            blockers.append(
                {
                    "code": "APPLICATION_RELEASE_INVALID",
                    "message": str(exc),
                }
            )

    expected_artifact = engine.get("source_path")
    expected_sha = (engine.get("hash") or {}).get("declared_sha256")
    if release_schema is not None and release_schema != "poker-site-release/v3":
        blockers.append(
            {
                "code": "APPLICATION_RELEASE_SCHEMA_INCOMPATIBLE",
                "message": f"application release schema is {release_schema!r}",
            }
        )
    if release_status is not None and release_status != "promoted":
        blockers.append(
            {
                "code": "APPLICATION_RELEASE_NOT_PROMOTED",
                "message": f"application release status is {release_status!r}",
            }
        )
    if declared_artifact is not None and declared_artifact != expected_artifact:
        blockers.append(
            {
                "code": "ENGINE_ARTIFACT_MISMATCH",
                "message": (
                    f"application release declares engine {declared_artifact!r}, "
                    f"candidate declares {expected_artifact!r}"
                ),
            }
        )
    if declared_sha is not None and declared_sha != expected_sha:
        blockers.append(
            {
                "code": "ENGINE_HASH_MISMATCH",
                "message": (
                    f"application release engine SHA-256 {declared_sha!r} "
                    f"does not match candidate {expected_sha!r}"
                ),
            }
        )

    compatible = (
        not blockers
        and declared_artifact == expected_artifact
        and declared_sha == expected_sha
        and release_schema == "poker-site-release/v3"
        and release_status == "promoted"
    )
    if not compatible and not blockers:
        blockers.append(
            {
                "code": "ENGINE_COMPATIBILITY_UNRESOLVED",
                "message": "engine/application release compatibility could not be established",
            }
        )

    return {
        "status": "COMPATIBLE" if compatible else "BLOCKED",
        "candidate_engine": {
            "source_path": expected_artifact,
            "sha256": expected_sha,
        },
        "application_release": {
            "source_path": app_source,
            "schema": release_schema,
            "status": release_status,
            "declared_engine_source_path": declared_artifact,
            "declared_engine_sha256": declared_sha,
        },
        "blockers": blockers,
    }


def preflight(
    contract_path: Path = DEFAULT_CONTRACT,
    *,
    root: Path = ROOT,
    expected_population_id: str = TARGET_POPULATION,
) -> dict[str, Any]:
    root = root.resolve()
    path = contract_path if contract_path.is_absolute() else root / contract_path
    contract = _load_json(path)

    try:
        summary = validate_candidate_contract(
            path,
            root=root,
            expected_population_id=expected_population_id,
            require_ready=False,
        )
        registry = load_registry(root)
        population = resolve_population(root, expected_population_id)
    except (CandidateContractError, PopulationRegistryError) as exc:
        raise PreflightError(str(exc)) from exc

    candidate_messages = list(summary.get("blockers") or [])
    component_rows = {
        role: _component_report(
            root=root,
            registry=registry,
            target_population_id=expected_population_id,
            role=role,
            component=(summary.get("components") or {}).get(role),
            candidate_messages=candidate_messages,
        )
        for role in REQUIRED_ROLES
    }

    blockers = _structured_candidate_blockers(candidate_messages)
    if summary.get("candidate_status") != READY_STATUS:
        blockers.append(
            {
                "code": "CANDIDATE_STATUS_NOT_READY",
                "role": None,
                "message": (
                    f"candidate status is {summary.get('candidate_status')!r}, "
                    f"expected {READY_STATUS!r}"
                ),
            }
        )

    population_status = population.get("status")
    if population_status != ASSEMBLY_READY_POPULATION_STATUS:
        blockers.append(
            {
                "code": "POPULATION_STATUS_NOT_PROMOTED",
                "role": None,
                "message": (
                    f"population status is {population_status!r}, "
                    f"expected {ASSEMBLY_READY_POPULATION_STATUS!r}"
                ),
            }
        )

    for declared in contract.get("blocked_on") or []:
        blockers.append(
            {
                "code": "DECLARED_EXTERNAL_BLOCKER",
                "role": None,
                "message": f"candidate contract remains blocked on {declared}",
            }
        )

    compatibility = _engine_compatibility(root=root, components=component_rows)
    blockers.extend(
        {
            "code": row["code"],
            "role": "engine",
            "message": row["message"],
        }
        for row in compatibility["blockers"]
    )

    # De-duplicate while preserving deterministic order.
    seen: set[tuple[str, str | None, str]] = set()
    unique_blockers: list[dict[str, Any]] = []
    for row in blockers:
        key = (row["code"], row.get("role"), row["message"])
        if key in seen:
            continue
        seen.add(key)
        unique_blockers.append(row)

    all_components_available = all(
        row["availability"] == "AVAILABLE" for row in component_rows.values()
    )
    ready = (
        summary.get("candidate_status") == READY_STATUS
        and population_status == ASSEMBLY_READY_POPULATION_STATUS
        and all_components_available
        and compatibility["status"] == "COMPATIBLE"
        and not unique_blockers
    )

    registry_artifacts = population.get("artifacts") or {}
    return {
        "schema": SCHEMA,
        "result": "READY_FOR_ASSEMBLY" if ready else "BLOCKED",
        "population": {
            "population_id": expected_population_id,
            "status": population_status,
            "identity": population.get("identity"),
            "legacy_unscoped_artifacts_allowed": bool(
                (population.get("compatibility") or {}).get(
                    "legacy_unscoped_artifacts_allowed", False
                )
            ),
        },
        "candidate": {
            "candidate_id": summary.get("candidate_id"),
            "candidate_status": summary.get("candidate_status"),
            "contract_path": summary.get("contract_path"),
            "contract_sha256": summary.get("contract_sha256"),
            "declared_blocked_on": list(contract.get("blocked_on") or []),
            "publication_policy": summary.get("publication_policy"),
        },
        "components": component_rows,
        "registry_component_pointers": {
            role: registry_artifacts.get(role)
            for role in (
                "model_a_preflop",
                "model_a_postflop",
                "model_b",
                "hero_strategy",
                "engine",
                "pack",
            )
        },
        "engine_compatibility": compatibility,
        "blockers": unique_blockers,
        "handoff": {
            "assembly_gate": "tools/build_population_pack.py",
            "candidate_contract_config_field": "candidate_contract",
            "candidate_contract_path": summary.get("contract_path"),
            "candidate_contract_sha256": summary.get("contract_sha256"),
            "ready_without_new_logic": ready,
        },
        "safety": {
            "dry_run": True,
            "writes_performed": False,
            "production_pointer_updates": False,
            "population_registry_updates": False,
            "catalogue_updates": False,
            "recommended_or_default_changes": False,
            "release_publication": False,
            "pack_activation": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=DEFAULT_CONTRACT,
        help="candidate contract to inspect",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="return exit code 2 when the preflight result is BLOCKED",
    )
    args = parser.parse_args()
    try:
        result = preflight(args.contract)
    except PreflightError as exc:
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "result": "BLOCKED",
                    "blockers": [
                        {
                            "code": "PREFLIGHT_INPUT_INVALID",
                            "role": None,
                            "message": str(exc),
                        }
                    ],
                    "safety": {
                        "dry_run": True,
                        "writes_performed": False,
                        "production_pointer_updates": False,
                        "population_registry_updates": False,
                        "catalogue_updates": False,
                        "recommended_or_default_changes": False,
                        "release_publication": False,
                        "pack_activation": False,
                    },
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if args.require_ready and result["result"] != "READY_FOR_ASSEMBLY" else 0


if __name__ == "__main__":
    raise SystemExit(main())
