#!/usr/bin/env python3
"""Fail-closed contract for future population-pack assembly.

This module does not promote, publish, activate or catalogue a pack. It validates
that every component proposed for a population-scoped pack is content-addressed,
provenance-bound and backed by an explicit admissibility decision.
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

from tools.populations.registry import (  # noqa: E402
    PopulationRegistryError,
    load_registry,
    resolve_population,
)

SCHEMA = "poker-population-pack-candidate/v1"
BLOCKED_STATUS = "BLOCKED_PENDING_SCIENTIFIC_DECISION"
READY_STATUS = "READY_FOR_ASSEMBLY"
ADMISSIBLE_DECISION = "ADMISSIBLE_FOR_PACK"
EXPLICIT_FALLBACK = "EXPLICITLY_AUTHORIZED_FOR_PACK"
REQUIRED_ROLES = (
    "model_a_preflop",
    "model_a_postflop",
    "model_b",
    "hero_strategy",
    "engine",
    "hero_ranges",
    "application_release",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CandidateContractError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateContractError(f"cannot read candidate contract {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CandidateContractError(f"candidate contract must be a JSON object: {path}")
    return value


def _repo_path(root: Path, value: str) -> Path:
    rel = PurePosixPath(str(value))
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        raise CandidateContractError(f"unsafe repository-relative path: {value!r}")
    path = root.joinpath(*rel.parts)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise CandidateContractError(f"path escapes repository: {value!r}") from exc
    return path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_tree(path: Path) -> str:
    files = sorted((p for p in path.rglob("*") if p.is_file()), key=lambda p: p.relative_to(path).as_posix())
    if not files:
        raise CandidateContractError(f"component directory is empty: {path}")
    h = hashlib.sha256()
    for item in files:
        rel = item.relative_to(path).as_posix()
        digest = sha256_file(item)
        h.update(f"{rel}\0{item.stat().st_size}\0{digest}\n".encode("utf-8"))
    return h.hexdigest()


def content_identity(path: Path) -> tuple[str, str]:
    if path.is_file():
        return "file_sha256", sha256_file(path)
    if path.is_dir():
        return "tree_sha256", sha256_tree(path)
    raise CandidateContractError(f"component source does not exist: {path}")


def _evidence_errors(root: Path, evidence: Any, label: str) -> list[str]:
    if not isinstance(evidence, dict):
        return [f"{label}: evidence object is required"]
    rel = str(evidence.get("path") or "")
    expected = str(evidence.get("sha256") or "")
    if not rel:
        return [f"{label}: evidence.path is required"]
    if not SHA256_RE.fullmatch(expected):
        return [f"{label}: evidence.sha256 must be a lowercase SHA-256"]
    try:
        path = _repo_path(root, rel)
    except CandidateContractError as exc:
        return [f"{label}: {exc}"]
    if not path.is_file():
        return [f"{label}: evidence file missing: {rel}"]
    actual = sha256_file(path)
    if actual != expected:
        return [f"{label}: evidence hash mismatch for {rel}"]
    return []


def _source_owners(registry: dict[str, Any], source_rel: str) -> list[tuple[str, str]]:
    owners: list[tuple[str, str]] = []
    normalized = PurePosixPath(source_rel).as_posix().rstrip("/")
    for population_id, spec in registry["populations"].items():
        for role, value in (spec.get("artifacts") or {}).items():
            if not isinstance(value, str) or not value:
                continue
            anchor = PurePosixPath(value).as_posix().rstrip("/")
            if normalized == anchor or normalized.startswith(anchor + "/"):
                owners.append((population_id, role))
    return sorted(set(owners))


def _validate_component(
    *,
    root: Path,
    registry: dict[str, Any],
    target_population: dict[str, Any],
    role: str,
    component: Any,
) -> list[str]:
    errors: list[str] = []
    target_id = target_population["population_id"]
    if not isinstance(component, dict):
        return [f"{role}: unresolved component"]

    if component.get("role") != role:
        errors.append(f"{role}: component.role must equal {role!r}")
    if component.get("population_id") != target_id:
        errors.append(f"{role}: population_id must equal target population {target_id}")

    source_rel = str(component.get("source_path") or "")
    expected_sha = str(component.get("sha256") or "")
    expected_kind = str(component.get("hash_kind") or "")
    if not source_rel:
        errors.append(f"{role}: source_path is required")
        source_path = None
    else:
        try:
            source_path = _repo_path(root, source_rel)
        except CandidateContractError as exc:
            errors.append(f"{role}: {exc}")
            source_path = None

    if not SHA256_RE.fullmatch(expected_sha):
        errors.append(f"{role}: sha256 must be a lowercase SHA-256")
    if expected_kind not in {"file_sha256", "tree_sha256"}:
        errors.append(f"{role}: hash_kind must be file_sha256 or tree_sha256")

    if source_path is not None and source_path.exists():
        try:
            actual_kind, actual_sha = content_identity(source_path)
        except CandidateContractError as exc:
            errors.append(f"{role}: {exc}")
        else:
            if expected_kind and actual_kind != expected_kind:
                errors.append(f"{role}: hash_kind mismatch, actual {actual_kind}")
            if SHA256_RE.fullmatch(expected_sha) and actual_sha != expected_sha:
                errors.append(f"{role}: source hash mismatch for {source_rel}")
    elif source_path is not None:
        errors.append(f"{role}: source does not exist: {source_rel}")

    provenance = component.get("provenance")
    if not isinstance(provenance, dict):
        errors.append(f"{role}: provenance object is required")
        source_population_id = None
    else:
        source_population_id = provenance.get("source_population_id")
        if not source_population_id:
            errors.append(f"{role}: provenance.source_population_id is required")
        errors.extend(_evidence_errors(root, provenance.get("evidence"), f"{role}: provenance"))

    decision = component.get("decision")
    if not isinstance(decision, dict):
        errors.append(f"{role}: decision object is required")
    else:
        if decision.get("status") != ADMISSIBLE_DECISION:
            errors.append(f"{role}: decision.status must be {ADMISSIBLE_DECISION}")
        if not decision.get("issue"):
            errors.append(f"{role}: decision.issue is required")
        errors.extend(_evidence_errors(root, decision.get("evidence"), f"{role}: decision"))

    owners = _source_owners(registry, source_rel) if source_rel else []
    foreign_owners = [(pid, owner_role) for pid, owner_role in owners if pid != target_id]
    target_disallows_legacy = not bool(
        target_population.get("compatibility", {}).get("legacy_unscoped_artifacts_allowed", False)
    )

    if foreign_owners and source_population_id == target_id:
        owner_text = ", ".join(f"{pid}:{owner_role}" for pid, owner_role in foreign_owners)
        errors.append(
            f"{role}: source {source_rel} is registered to another population ({owner_text}); "
            "it cannot be silently relabelled as target-scoped"
        )

    if source_population_id and source_population_id != target_id:
        fallback = provenance.get("cross_population_fallback") if isinstance(provenance, dict) else None
        if not isinstance(fallback, dict) or fallback.get("status") != EXPLICIT_FALLBACK:
            errors.append(
                f"{role}: cross-population source {source_population_id} requires "
                f"{EXPLICIT_FALLBACK}"
            )
        else:
            if fallback.get("source_population_id") != source_population_id:
                errors.append(f"{role}: fallback source_population_id mismatch")
            if not fallback.get("issue"):
                errors.append(f"{role}: fallback.issue is required")
            errors.extend(_evidence_errors(root, fallback.get("evidence"), f"{role}: fallback authorization"))
        if target_disallows_legacy and not isinstance(fallback, dict):
            errors.append(f"{role}: target population forbids unscoped legacy fallback")

    return errors


def validate_candidate_contract(
    path: Path,
    *,
    root: Path = ROOT,
    expected_population_id: str | None = None,
    require_ready: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    contract_path = path if path.is_absolute() else root / path
    contract = _load_json(contract_path)

    if contract.get("schema") != SCHEMA:
        raise CandidateContractError(f"unsupported candidate contract schema: {contract.get('schema')!r}")
    population_id = str(contract.get("population_id") or "")
    if not population_id:
        raise CandidateContractError("candidate population_id is required")
    if expected_population_id and population_id != expected_population_id:
        raise CandidateContractError(
            f"candidate population mismatch: expected {expected_population_id}, got {population_id}"
        )
    try:
        target_population = resolve_population(root, population_id)
        registry = load_registry(root)
    except PopulationRegistryError as exc:
        raise CandidateContractError(str(exc)) from exc

    status = str(contract.get("candidate_status") or "")
    if status not in {BLOCKED_STATUS, READY_STATUS}:
        raise CandidateContractError(f"unsupported candidate_status: {status!r}")

    required_roles = contract.get("required_roles")
    if required_roles != list(REQUIRED_ROLES):
        raise CandidateContractError(
            f"required_roles must exactly equal canonical pack roles: {list(REQUIRED_ROLES)}"
        )

    publication = contract.get("publication_policy")
    if not isinstance(publication, dict):
        raise CandidateContractError("publication_policy object is required")
    flags = ("release_allowed", "catalog_eligible", "recommended", "default")
    if any(not isinstance(publication.get(flag), bool) for flag in flags):
        raise CandidateContractError(f"publication_policy must define booleans: {', '.join(flags)}")
    if status == BLOCKED_STATUS and any(publication[flag] for flag in flags):
        raise CandidateContractError("blocked candidate must be non-publishable, non-catalogue and non-default")

    components = contract.get("components")
    if not isinstance(components, dict):
        raise CandidateContractError("components object is required")

    blockers: list[str] = []
    for role in REQUIRED_ROLES:
        blockers.extend(
            _validate_component(
                root=root,
                registry=registry,
                target_population=target_population,
                role=role,
                component=components.get(role),
            )
        )

    if status == READY_STATUS and blockers:
        raise CandidateContractError(
            "candidate declares READY_FOR_ASSEMBLY but is incomplete: " + "; ".join(blockers)
        )
    if require_ready and status != READY_STATUS:
        raise CandidateContractError(
            f"candidate is {status}, not {READY_STATUS}; assembly remains blocked"
        )
    if require_ready and blockers:
        raise CandidateContractError("candidate is not assembly-ready: " + "; ".join(blockers))

    return {
        "schema": SCHEMA,
        "candidate_id": contract.get("candidate_id"),
        "candidate_status": status,
        "population_id": population_id,
        "population_status": target_population.get("status"),
        "ready_for_assembly": status == READY_STATUS and not blockers,
        "publication_policy": publication,
        "blockers": blockers,
        "contract_path": contract_path.relative_to(root).as_posix(),
        "contract_sha256": sha256_file(contract_path),
        "components": components,
    }


def assembly_binding(summary: dict[str, Any]) -> dict[str, Any]:
    if not summary.get("ready_for_assembly"):
        raise CandidateContractError("cannot materialize assembly binding from a blocked candidate")
    return {
        "schema": SCHEMA,
        "candidate_id": summary.get("candidate_id"),
        "candidate_status": summary["candidate_status"],
        "population_id": summary["population_id"],
        "contract": {
            "path": summary["contract_path"],
            "sha256": summary["contract_sha256"],
        },
        "components": summary["components"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    try:
        summary = validate_candidate_contract(args.contract, require_ready=args.require_ready)
    except CandidateContractError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({k: v for k, v in summary.items() if k != "components"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
