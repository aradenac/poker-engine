#!/usr/bin/env python3
"""Versioned population registry helpers.

New scientific workflows must name a population explicitly. The historical
training/registry.json remains an immutable closed-cycle anchor; this module
provides the migration-safe population-scoped view used by new work.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = Path("training/populations/registry.json")
SCHEMA = "poker-population-registry/v1"
REQUIRED_IDENTITY = (
    "platform",
    "variant",
    "game_kind",
    "stake",
    "money",
    "currency",
    "format",
    "max_seats",
    "rake",
)
REQUIRED_ARTIFACT_ROLES = (
    "model_a_preflop",
    "model_a_postflop",
    "model_b",
    "hero_strategy",
    "engine",
    "pack",
)


class PopulationRegistryError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PopulationRegistryError(f"expected JSON object: {path}")
    return data


def validate_registry(registry: dict[str, Any]) -> None:
    if registry.get("schema") != SCHEMA:
        raise PopulationRegistryError(f"unsupported population registry schema: {registry.get('schema')!r}")
    populations = registry.get("populations")
    if not isinstance(populations, dict) or not populations:
        raise PopulationRegistryError("population registry has no populations")
    default_population = registry.get("default_population")
    if default_population not in populations:
        raise PopulationRegistryError("default_population does not resolve")

    namespaces: set[str] = set()
    roots: set[str] = set()
    for population_id, spec in populations.items():
        if not isinstance(spec, dict):
            raise PopulationRegistryError(f"invalid population entry: {population_id}")
        identity = spec.get("identity")
        if not isinstance(identity, dict):
            raise PopulationRegistryError(f"missing identity for {population_id}")
        missing = [field for field in REQUIRED_IDENTITY if field not in identity]
        if missing:
            raise PopulationRegistryError(f"missing identity fields for {population_id}: {', '.join(missing)}")
        if not isinstance(identity["rake"], dict) or not identity["rake"].get("policy"):
            raise PopulationRegistryError(f"rake policy must be explicit for {population_id}")

        data = spec.get("data")
        storage = spec.get("storage")
        artifacts = spec.get("artifacts")
        if not isinstance(data, dict) or not data.get("root") or not data.get("snapshots_root") or not data.get("increments_root"):
            raise PopulationRegistryError(f"incomplete data namespace for {population_id}")
        if not isinstance(storage, dict) or not storage.get("runs_root") or not storage.get("cache_namespace"):
            raise PopulationRegistryError(f"incomplete storage namespace for {population_id}")
        if not isinstance(artifacts, dict):
            raise PopulationRegistryError(f"missing artifacts map for {population_id}")
        missing_roles = [role for role in REQUIRED_ARTIFACT_ROLES if role not in artifacts]
        if missing_roles:
            raise PopulationRegistryError(f"missing artifact roles for {population_id}: {', '.join(missing_roles)}")

        cache_namespace = str(storage["cache_namespace"])
        runs_root = str(storage["runs_root"])
        if cache_namespace in namespaces:
            raise PopulationRegistryError(f"duplicate cache namespace: {cache_namespace}")
        if runs_root in roots:
            raise PopulationRegistryError(f"duplicate runs root: {runs_root}")
        namespaces.add(cache_namespace)
        roots.add(runs_root)


def load_registry(root: Path = ROOT, path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    full = path if path.is_absolute() else root / path
    registry = load_json(full)
    validate_registry(registry)
    return registry


def resolve_population(root: Path, population_id: str, registry_path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    if not population_id:
        raise PopulationRegistryError("population_id is required for scientific work")
    registry = load_registry(root, registry_path)
    spec = registry["populations"].get(population_id)
    if not isinstance(spec, dict):
        known = ", ".join(sorted(registry["populations"]))
        raise PopulationRegistryError(f"unknown population_id {population_id!r}; known: {known}")
    return {"population_id": population_id, **spec}


def require_artifact_role(population: dict[str, Any], role: str) -> str:
    if role not in REQUIRED_ARTIFACT_ROLES:
        raise PopulationRegistryError(f"unknown artifact role: {role}")
    value = population["artifacts"].get(role)
    if not value:
        raise PopulationRegistryError(
            f"population {population['population_id']} has no promoted {role} artifact"
        )
    return str(value)


def assert_artifact_compatible(population_id: str, metadata: dict[str, Any], *, allow_legacy_unscoped: bool = False) -> None:
    artifact_population = metadata.get("population_id")
    if artifact_population is None and allow_legacy_unscoped:
        return
    if artifact_population != population_id:
        raise PopulationRegistryError(
            f"artifact population mismatch: expected {population_id}, got {artifact_population!r}"
        )


def namespace_path(root: Path, population: dict[str, Any], kind: str) -> Path:
    if kind == "runs":
        rel = population["storage"]["runs_root"]
    elif kind == "snapshots":
        rel = population["data"]["snapshots_root"]
    elif kind == "increments":
        rel = population["data"]["increments_root"]
    else:
        raise PopulationRegistryError(f"unsupported namespace kind: {kind}")
    return root / str(rel)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--population")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    registry = load_registry(args.root.resolve(), args.registry)
    if args.list:
        print(json.dumps({
            "schema": registry["schema"],
            "default_population": registry["default_population"],
            "populations": sorted(registry["populations"]),
        }, indent=2, sort_keys=True))
        return 0
    if not args.population:
        raise SystemExit("--population is required unless --list is used")
    print(json.dumps(resolve_population(args.root.resolve(), args.population, args.registry), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
