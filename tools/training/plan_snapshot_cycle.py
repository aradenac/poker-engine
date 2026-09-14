#!/usr/bin/env python3
"""Plan an immutable continuous-training cycle for one explicit population.

Population identity, stake, data roots and artifact pointers are resolved from
training/populations/registry.json. The historical training/registry.json is
never used as an implicit population selector and remains a protected closed-
cycle anchor during migration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from tools.populations.registry import (
    DEFAULT_REGISTRY,
    PopulationRegistryError,
    namespace_path,
    resolve_population,
)

ROOT = Path(__file__).resolve().parents[2]


def canonical(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def exactly_one_zip(source_dir: Path) -> Path:
    zips = sorted(source_dir.glob("*.zip"))
    if len(zips) != 1:
        raise RuntimeError(f"expected exactly one ZIP in {source_dir}, found {len(zips)}")
    return zips[0]


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def discover(
    root: Path,
    *,
    population_id: str,
    snapshot_id: str | None = None,
    registry_path: Path = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    population = resolve_population(root, population_id, registry_path)
    identity = population["identity"]
    data = population["data"]
    stake = str(identity["stake"])
    baseline_raw = data.get("baseline_archive")
    if not baseline_raw:
        raise PopulationRegistryError(
            f"population {population_id} has no baseline_archive; data must be materialized before a cycle"
        )
    baseline = root / str(baseline_raw)
    if not baseline.is_file():
        raise RuntimeError(f"baseline archive missing for {population_id}: {baseline}")

    snapshots_root = namespace_path(root, population, "snapshots")
    increments_root = namespace_path(root, population, "increments")
    runs_root = namespace_path(root, population, "runs")
    snapshots = []
    if snapshots_root.is_dir():
        for directory in sorted(p for p in snapshots_root.iterdir() if p.is_dir()):
            source_dir = directory / "source"
            if not source_dir.is_dir():
                continue
            archive = exactly_one_zip(source_dir)
            snapshots.append({
                "id": directory.name,
                "archive": archive,
                "processed": (increments_root / directory.name / "manifest.json").is_file(),
            })

    if snapshot_id:
        selected = next((item for item in snapshots if item["id"] == snapshot_id), None)
        if selected is None:
            raise RuntimeError(f"snapshot not found for {population_id}: {snapshot_id}")
        if selected["processed"]:
            return {
                "status": "NO_OP_ALREADY_PROCESSED",
                "population_id": population_id,
                "dataset": str(data["dataset_id"]),
                "stake": stake,
                "snapshot_id": snapshot_id,
                "candidate_archive": rel(root, selected["archive"]),
            }
    else:
        pending = [item for item in snapshots if not item["processed"]]
        if not pending:
            return {
                "status": "NO_PENDING_SNAPSHOT",
                "population_id": population_id,
                "dataset": str(data["dataset_id"]),
                "stake": stake,
            }
        if len(pending) != 1:
            raise RuntimeError(
                f"multiple unprocessed snapshots for {population_id}; specify --snapshot-id: "
                + ", ".join(item["id"] for item in pending)
            )
        selected = pending[0]

    known = [baseline]
    for item in snapshots:
        if item["id"] == selected["id"] or not item["processed"]:
            continue
        known.append(item["archive"])
    source_sha = sha256_file(selected["archive"])
    run_id = f"{selected['id']}_continuous_{source_sha[:12]}"
    return {
        "status": "PLANNED",
        "population_id": population_id,
        "population_status": population["status"],
        "dataset": str(data["dataset_id"]),
        "stake": stake,
        "snapshot_id": selected["id"],
        "candidate_archive": rel(root, selected["archive"]),
        "candidate_sha256": source_sha,
        "known_archives": [rel(root, path) for path in known],
        "run_id": run_id,
        "runs_root": rel(root, runs_root),
        "increments_root": rel(root, increments_root),
        "cache_namespace": str(population["storage"]["cache_namespace"]),
        "artifacts": dict(population["artifacts"]),
        "legacy_unscoped_artifacts_allowed": bool(
            population.get("compatibility", {}).get("legacy_unscoped_artifacts_allowed", False)
        ),
    }


def contract_for(root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    run_id = plan["run_id"]
    run_dir = f"{plan['runs_root']}/{run_id}"
    increment_dir = f"{plan['increments_root']}/{plan['snapshot_id']}"
    selected_zip = f"{increment_dir}/source/selected_{plan['stake'].replace('/', '_')}.zip"
    inc_manifest = f"{increment_dir}/manifest.json"
    status_path = f"{run_dir}/data/increment_status.json"
    decisions = f"{run_dir}/data/decisions.jsonl"
    summary = f"{run_dir}/data/decisions_summary.json"
    overlay = f"{run_dir}/artifacts/population_increment_overlay.json"
    overlay_prov = f"{run_dir}/artifacts/population_increment_overlay_provenance.json"
    gate = f"{run_dir}/gate.json"

    known_args: list[str] = []
    for path in plan["known_archives"]:
        known_args += ["--known", path]
    has_new = {"json": status_path, "path": ["has_new_hands"], "equals": True}

    # The population registry itself and the closed legacy registry are immutable
    # during a scientific run. Existing promoted artifacts are protected by their
    # exact paths, without assuming that every population has every role filled.
    protected = ["training/populations/registry.json", "training/registry.json"]
    for role in ("model_a_preflop", "model_a_postflop", "model_b", "hero_strategy", "pack"):
        value = plan["artifacts"].get(role)
        if value and value not in protected:
            protected.append(value)
    if "site" not in protected:
        protected.append("site")

    return {
        "schema": "poker-continuous-cycle/v1",
        "cycle": run_id,
        "population_id": plan["population_id"],
        "dataset_id": plan["dataset"],
        "cache_namespace": plan["cache_namespace"],
        "promotion_mode": "disabled",
        "gate_report": gate,
        "protected_production_paths": protected,
        "stages": [
            {
                "id": "audit-snapshot",
                "argv": ["python3", "tools/datasets/audit_hand_history_archive.py", plan["candidate_archive"], f"{run_dir}/source/snapshot_audit.json"],
                "required_outputs": [f"{run_dir}/source/snapshot_audit.json"],
            },
            {
                "id": "build-deterministic-increment",
                "argv": ["python3", "tools/datasets/build_hand_history_increment.py", *known_args,
                         "--candidate", plan["candidate_archive"], "--stake", plan["stake"],
                         "--manifest", inc_manifest, "--output-zip", selected_zip],
                "required_outputs": [inc_manifest, selected_zip],
            },
            {
                "id": "classify-increment",
                "argv": ["python3", "tools/training/classify_increment.py", "--manifest", inc_manifest, "--out", status_path],
                "required_outputs": [status_path],
            },
            {
                "id": "normalize-decisions",
                "when": has_new,
                "argv": ["python3", "tools/training/build_incremental_decisions_v2.py", "--source", selected_zip, "--out", decisions, "--summary", summary],
                "required_outputs": [decisions, summary],
            },
            {
                "id": "build-train-overlay",
                "when": has_new,
                "argv": ["python3", "tools/training/build_population_increment_overlay_v2.py", "--decisions", decisions, "--out", overlay, "--provenance-out", overlay_prov],
                "required_outputs": [overlay, overlay_prov],
            },
            {
                "id": "write-increment-readiness-gate",
                "argv": ["python3", "tools/training/write_increment_gate.py", "--cycle", run_id, "--increment-status", status_path, "--out", gate],
                "required_outputs": [gate],
            },
        ],
    }


def write_immutable(path: Path, content: str) -> str:
    if path.exists():
        current = path.read_text(encoding="utf-8")
        if current != content:
            raise RuntimeError(f"refusing to replace existing immutable plan/contract: {path}")
        return "UNCHANGED"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return "CREATED"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--population", required=True, help="explicit population_id from training/populations/registry.json")
    parser.add_argument("--population-registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--snapshot-id")
    parser.add_argument("--plan-out", type=Path)
    parser.add_argument("--contract-out", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    plan = discover(
        root,
        population_id=args.population,
        snapshot_id=args.snapshot_id,
        registry_path=args.population_registry,
    )
    if plan["status"] != "PLANNED":
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    contract = contract_for(root, plan)
    run_id = plan["run_id"]
    run_root = root / plan["runs_root"] / run_id
    plan_path = args.plan_out or (run_root / "PLAN.json")
    contract_path = args.contract_out or (
        root / "training/populations" / plan["population_id"] / "automation/generated" / f"{run_id}.json"
    )
    if not plan_path.is_absolute():
        plan_path = root / plan_path
    if not contract_path.is_absolute():
        contract_path = root / contract_path
    plan_record = {
        "schema": "poker-continuous-cycle-plan/v2",
        **plan,
        "contract": rel(root, contract_path),
        "historical_cycles_mutated": False,
        "production_effect": "NONE",
    }
    plan_write = write_immutable(plan_path, canonical(plan_record))
    contract_write = write_immutable(contract_path, canonical(contract))
    print(json.dumps({
        "status": "PLANNED",
        "population_id": plan["population_id"],
        "run_id": run_id,
        "plan": rel(root, plan_path),
        "plan_write": plan_write,
        "contract": rel(root, contract_path),
        "contract_write": contract_write,
        "candidate_sha256": plan["candidate_sha256"],
        "known_archives": plan["known_archives"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
