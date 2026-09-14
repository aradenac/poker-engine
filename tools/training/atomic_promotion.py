#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

PLAN_SCHEMA = "poker-atomic-promotion/v1"


class PromotionError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve(root: Path, value: str) -> Path:
    p = Path(value)
    return (p if p.is_absolute() else root / p).resolve()


def _within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _protected_owner(destination: Path, protected: dict[str, Path]) -> str | None:
    owners = [name for name, path in protected.items() if destination == path or _within(destination, path)]
    if not owners:
        return None
    owners.sort(key=lambda name: len(protected[name].parts), reverse=True)
    return owners[0]


def replace_file(staged: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{destination.name}.promote-", dir=destination.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(staged.read_bytes())
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, destination)
    finally:
        if tmp.exists():
            tmp.unlink()


def load_plan(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PromotionError("promotion plan must be a JSON object")
    return data


def apply_promotion(
    *,
    root: Path,
    protected_paths: list[str],
    plan: dict[str, Any],
) -> dict[str, Any]:
    root = root.resolve()
    if plan.get("schema") != PLAN_SCHEMA:
        raise PromotionError(f"unexpected promotion plan schema: {plan.get('schema')!r}")
    operations = plan.get("operations")
    if not isinstance(operations, list) or not operations:
        raise PromotionError("promotion plan requires a non-empty operations list")

    protected = {name: _resolve(root, name) for name in protected_paths}
    prepared: list[dict[str, Any]] = []
    ids: set[str] = set()
    destinations: set[Path] = set()

    for index, raw in enumerate(operations):
        if not isinstance(raw, dict):
            raise PromotionError(f"promotion operation {index} must be an object")
        op_id = str(raw.get("id") or "")
        source_raw = raw.get("source")
        destination_raw = raw.get("destination")
        source_sha = raw.get("source_sha256")
        before_sha = raw.get("destination_sha256_before")
        if not op_id or op_id in ids:
            raise PromotionError(f"invalid or duplicate promotion operation id: {op_id!r}")
        ids.add(op_id)
        if not isinstance(source_raw, str) or not source_raw or not isinstance(destination_raw, str) or not destination_raw:
            raise PromotionError(f"{op_id}: source and destination must be non-empty paths")
        if not isinstance(source_sha, str) or len(source_sha) != 64:
            raise PromotionError(f"{op_id}: source_sha256 must be a SHA-256 hex string")
        if before_sha is not None and (not isinstance(before_sha, str) or len(before_sha) != 64):
            raise PromotionError(f"{op_id}: destination_sha256_before must be SHA-256 or null")

        source = _resolve(root, source_raw)
        destination = _resolve(root, destination_raw)
        if source in destinations or destination in destinations:
            raise PromotionError(f"{op_id}: duplicate or chained destination is not allowed")
        destinations.add(destination)
        if not source.is_file() or source.is_symlink():
            raise PromotionError(f"{op_id}: source is not a regular file: {source_raw}")
        if any(source == p or _within(source, p) for p in protected.values()):
            raise PromotionError(f"{op_id}: source must be outside protected production paths")
        owner = _protected_owner(destination, protected)
        if owner is None:
            raise PromotionError(f"{op_id}: destination is outside protected production paths")
        if destination.exists() and (not destination.is_file() or destination.is_symlink()):
            raise PromotionError(f"{op_id}: destination is not a regular file")

        actual_source_sha = sha256_file(source)
        if actual_source_sha != source_sha:
            raise PromotionError(f"{op_id}: source SHA-256 mismatch")
        if destination.exists():
            actual_before = sha256_file(destination)
            if before_sha is None or actual_before != before_sha:
                raise PromotionError(f"{op_id}: destination precondition mismatch")
        elif before_sha is not None:
            raise PromotionError(f"{op_id}: destination expected to exist before promotion")

        prepared.append({
            "id": op_id,
            "source": source,
            "source_declared": source_raw,
            "destination": destination,
            "destination_declared": destination_raw,
            "source_sha256": source_sha,
            "destination_sha256_before": before_sha,
            "protected_owner": owner,
        })

    registry_indexes = [i for i, op in enumerate(prepared) if op["destination_declared"] == "training/registry.json"]
    if registry_indexes and registry_indexes != [len(prepared) - 1]:
        raise PromotionError("training/registry.json must be the final promotion operation")

    with tempfile.TemporaryDirectory(prefix="poker-promotion-stage-") as raw_stage:
        stage_root = Path(raw_stage)
        for index, op in enumerate(prepared):
            staged = stage_root / f"{index:04d}.payload"
            staged.write_bytes(op["source"].read_bytes())
            if sha256_file(staged) != op["source_sha256"]:
                raise PromotionError(f"{op['id']}: staged payload SHA-256 mismatch")
            op["staged"] = staged

        applied: list[dict[str, Any]] = []
        for op in prepared:
            replace_file(op["staged"], op["destination"])
            actual_after = sha256_file(op["destination"])
            if actual_after != op["source_sha256"]:
                raise PromotionError(f"{op['id']}: destination verification failed after replace")
            applied.append({
                "id": op["id"],
                "source": op["source_declared"],
                "destination": op["destination_declared"],
                "sha256": actual_after,
                "protected_owner": op["protected_owner"],
            })

    return {
        "schema": "poker-atomic-promotion-result/v1",
        "status": "APPLIED",
        "operations": applied,
        "affected_protected_paths": sorted({op["protected_owner"] for op in prepared}),
    }
