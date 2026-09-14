#!/usr/bin/env python3
"""Plan a new immutable continuous-training cycle from persisted snapshots.

This planner is intentionally generic: it discovers the active dataset from the
registry and scans snapshot/increment directories rather than naming historical
dates. It creates a validation-only cycle contract; candidate/model promotion is
never inferred from snapshot presence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def canonical(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return data


def dataset_stake(dataset: str) -> str:
    m = re.search(r"_(\d+)-(\d+)$", dataset)
    if not m:
        raise RuntimeError(f"cannot derive stake from dataset id: {dataset}")
    return f"{m.group(1)}/{m.group(2)}"


def exactly_one_zip(source_dir: Path) -> Path:
    zips = sorted(source_dir.glob("*.zip"))
    if len(zips) != 1:
        raise RuntimeError(f"expected exactly one ZIP in {source_dir}, found {len(zips)}")
    return zips[0]


def discover(root: Path, *, snapshot_id: str | None = None) -> dict[str, Any]:
    registry_path = root / "training/registry.json"
    registry = load(registry_path)
    dataset = str(registry.get("active_dataset") or "")
    if not dataset:
        raise RuntimeError("registry has no active_dataset")
    ds = (registry.get("datasets") or {}).get(dataset)
    if not isinstance(ds, dict):
        raise RuntimeError(f"active dataset missing from registry: {dataset}")
    baseline = root / str(ds.get("baseline_archive") or "")
    if not baseline.is_file():
        raise RuntimeError(f"baseline archive missing: {baseline}")
    stake = dataset_stake(dataset)
    snapshots_root = root / "training/datasets" / dataset / "snapshots"
    increments_root = root / "training/datasets" / dataset / "increments"
    snapshots = []
    if snapshots_root.is_dir():
        for d in sorted(p for p in snapshots_root.iterdir() if p.is_dir()):
            source_dir = d / "source"
            if not source_dir.is_dir():
                continue
            archive = exactly_one_zip(source_dir)
            snapshots.append({
                "id": d.name,
                "archive": archive,
                "processed": (increments_root / d.name / "manifest.json").is_file(),
            })
    if snapshot_id:
        selected = next((x for x in snapshots if x["id"] == snapshot_id), None)
        if selected is None:
            raise RuntimeError(f"snapshot not found: {snapshot_id}")
        if selected["processed"]:
            return {
                "status": "NO_OP_ALREADY_PROCESSED",
                "dataset": dataset,
                "stake": stake,
                "snapshot_id": snapshot_id,
                "candidate_archive": selected["archive"].relative_to(root).as_posix(),
            }
    else:
        pending = [x for x in snapshots if not x["processed"]]
        if not pending:
            return {"status": "NO_PENDING_SNAPSHOT", "dataset": dataset, "stake": stake}
        if len(pending) != 1:
            raise RuntimeError("multiple unprocessed snapshots; specify --snapshot-id: " + ", ".join(x["id"] for x in pending))
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
        "dataset": dataset,
        "stake": stake,
        "snapshot_id": selected["id"],
        "candidate_archive": selected["archive"].relative_to(root).as_posix(),
        "candidate_sha256": source_sha,
        "known_archives": [p.relative_to(root).as_posix() for p in known],
        "run_id": run_id,
    }


def contract_for(root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    run_id = plan["run_id"]
    run_dir = f"training/runs/{run_id}"
    selected_zip = f"{run_dir}/data/selected_{plan['stake'].replace('/', '_')}.zip"
    inc_manifest = f"{run_dir}/data/increment_manifest.json"
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
    model_b_dir = str(load(root / "training/registry.json").get("promoted_independent_model", {}).get("model_dir") or "")
    protected = ["training/registry.json", "training/models"]
    if model_b_dir:
        protected.append(model_b_dir)
    protected += ["user/releases", "site"]
    user_artifacts = root / "user/artifacts"
    if user_artifacts.exists():
        protected.append("user/artifacts")

    return {
        "schema": "poker-continuous-cycle/v1",
        "cycle": run_id,
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
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--snapshot-id")
    ap.add_argument("--plan-out", type=Path)
    ap.add_argument("--contract-out", type=Path)
    args = ap.parse_args()
    root = args.root.resolve()
    plan = discover(root, snapshot_id=args.snapshot_id)
    if plan["status"] != "PLANNED":
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    contract = contract_for(root, plan)
    run_id = plan["run_id"]
    plan_path = args.plan_out or (root / "training/runs" / run_id / "PLAN.json")
    contract_path = args.contract_out or (root / "training/automation/generated" / f"{run_id}.json")
    if not plan_path.is_absolute():
        plan_path = root / plan_path
    if not contract_path.is_absolute():
        contract_path = root / contract_path
    plan_record = {
        "schema": "poker-continuous-cycle-plan/v1",
        **plan,
        "contract": contract_path.relative_to(root).as_posix(),
        "historical_cycles_mutated": False,
        "production_effect": "NONE",
    }
    plan_write = write_immutable(plan_path, canonical(plan_record))
    contract_write = write_immutable(contract_path, canonical(contract))
    print(json.dumps({
        "status": "PLANNED",
        "run_id": run_id,
        "plan": plan_path.relative_to(root).as_posix(),
        "plan_write": plan_write,
        "contract": contract_path.relative_to(root).as_posix(),
        "contract_write": contract_write,
        "candidate_sha256": plan["candidate_sha256"],
        "known_archives": plan["known_archives"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
