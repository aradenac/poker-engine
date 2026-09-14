#!/usr/bin/env python3
"""Execute a continuous-training cycle without permitting implicit promotion.

Version 1 is intentionally validation-only. It executes an ordered argv-only
stage plan, snapshots all declared protected paths before the first stage, and
restores them byte-for-byte if a stage fails or mutates protected state.
Promotion will be layered on later behind an explicit atomic promotion plan;
this runner never treats a green training command as authorization to move a
pointer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_SCHEMA = "poker-continuous-cycle/v1"
REPORT_SCHEMA = "poker-continuous-cycle-execution/v1"
GATE_SCHEMA = "poker-promotion-gate-report/v1"


def canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise RuntimeError(f"protected path may not be a symlink: {path}")
    if path.is_file():
        return {"type": "file", "sha256": sha256_file(path), "size_bytes": path.stat().st_size}
    if path.is_dir():
        files: list[dict[str, Any]] = []
        for child in sorted(p for p in path.rglob("*") if p.is_file()):
            if child.is_symlink():
                raise RuntimeError(f"protected tree may not contain symlink: {child}")
            files.append({
                "path": child.relative_to(path).as_posix(),
                "sha256": sha256_file(child),
                "size_bytes": child.stat().st_size,
            })
        aggregate = hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {"type": "directory", "tree_sha256": aggregate, "files": files}
    return {"type": "missing"}


def resolve(root: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else root / p


class ProductionSnapshot:
    def __init__(self, root: Path, protected: list[str], backup_root: Path):
        self.root = root
        self.items: list[dict[str, Any]] = []
        seen: set[Path] = set()
        for index, raw in enumerate(protected):
            path = resolve(root, raw).resolve()
            if path in seen:
                raise RuntimeError(f"duplicate protected path: {raw}")
            seen.add(path)
            if not path.exists():
                raise RuntimeError(f"protected production path missing before cycle: {raw}")
            rel_backup = backup_root / f"item-{index}"
            if path.is_dir():
                shutil.copytree(path, rel_backup)
            else:
                rel_backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, rel_backup)
            self.items.append({
                "declared": raw,
                "path": path,
                "backup": rel_backup,
                "before": fingerprint(path),
            })

    def identities(self) -> dict[str, Any]:
        return {item["declared"]: fingerprint(item["path"]) for item in self.items}

    def changed(self) -> list[str]:
        return [
            item["declared"]
            for item in self.items
            if fingerprint(item["path"]) != item["before"]
        ]

    def restore(self) -> None:
        for item in self.items:
            path: Path = item["path"]
            backup: Path = item["backup"]
            if path.exists():
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            if backup.is_dir():
                shutil.copytree(backup, path)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, path)

    def before_identities(self) -> dict[str, Any]:
        return {item["declared"]: item["before"] for item in self.items}


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return data


def json_value(data: Any, path: list[Any]) -> Any:
    value = data
    for item in path:
        if isinstance(value, dict) and isinstance(item, str) and item in value:
            value = value[item]
        elif isinstance(value, list) and isinstance(item, int) and 0 <= item < len(value):
            value = value[item]
        else:
            raise RuntimeError(f"conditional JSON path not found at {item!r}")
    return value


def evaluate_condition(root: Path, condition: dict[str, Any]) -> tuple[bool, Any]:
    source = condition.get("json")
    path = condition.get("path", [])
    if not isinstance(source, str) or not source:
        raise RuntimeError("stage when.json must be a non-empty path")
    if not isinstance(path, list) or not all(isinstance(x, (str, int)) for x in path):
        raise RuntimeError("stage when.path must be a list of object keys/list indexes")
    if "equals" not in condition:
        raise RuntimeError("stage when condition requires equals")
    source_path = resolve(root, source)
    if not source_path.is_file():
        raise RuntimeError(f"conditional JSON source missing: {source}")
    actual = json_value(load_json(source_path), path)
    return actual == condition["equals"], actual


def write_report(path: Path | None, report: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(report), encoding="utf-8")


def execute(
    *,
    root: Path,
    config_path: Path,
    report_path: Path | None = None,
    require_ready: bool = False,
) -> tuple[int, dict[str, Any]]:
    root = root.resolve()
    config = load_json(config_path)
    if config.get("schema") != CONFIG_SCHEMA:
        raise RuntimeError(f"unexpected cycle config schema: {config.get('schema')!r}")
    if config.get("promotion_mode", "disabled") != "disabled":
        raise RuntimeError("v1 orchestrator only supports promotion_mode=disabled")

    cycle = str(config.get("cycle") or "")
    if not cycle:
        raise RuntimeError("cycle config requires a non-empty cycle")
    protected = config.get("protected_production_paths")
    if not isinstance(protected, list) or not protected or not all(isinstance(x, str) and x for x in protected):
        raise RuntimeError("protected_production_paths must be a non-empty string list")
    stages = config.get("stages")
    if not isinstance(stages, list):
        raise RuntimeError("stages must be a list")

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "cycle": cycle,
        "promotion_mode": "disabled",
        "status": "RUNNING",
        "stages": [],
        "production_restored": False,
    }

    with tempfile.TemporaryDirectory(prefix="poker-cycle-production-backup-") as tmp:
        snapshot = ProductionSnapshot(root, protected, Path(tmp))
        report["production_before"] = snapshot.before_identities()

        def fail(reason: str, *, code: int = 2) -> tuple[int, dict[str, Any]]:
            changed = snapshot.changed()
            if changed:
                snapshot.restore()
                report["production_restored"] = True
            remaining = snapshot.changed()
            report.update({
                "status": "FAIL",
                "reason": reason,
                "production_changed_paths_detected": changed,
                "production_after": snapshot.identities(),
                "production_restoration_verified": not remaining,
            })
            if remaining:
                report["restoration_error_paths"] = remaining
                code = 3
            write_report(report_path, report)
            return code, report

        for raw_stage in stages:
            if not isinstance(raw_stage, dict):
                return fail("stage must be an object")
            stage_id = str(raw_stage.get("id") or "")
            argv = raw_stage.get("argv")
            if not stage_id or not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
                return fail(f"invalid stage contract: {stage_id or '<unnamed>'}")

            condition = raw_stage.get("when")
            if condition is not None:
                if not isinstance(condition, dict):
                    return fail(f"stage {stage_id} when must be an object")
                try:
                    should_run, actual = evaluate_condition(root, condition)
                except RuntimeError as exc:
                    return fail(f"stage {stage_id} condition invalid: {exc}")
                if not should_run:
                    report["stages"].append({
                        "id": stage_id,
                        "status": "SKIPPED",
                        "when": {
                            "json": condition["json"],
                            "path": condition.get("path", []),
                            "equals": condition["equals"],
                            "actual": actual,
                        },
                    })
                    continue

            try:
                proc = subprocess.run(argv, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except OSError as exc:
                report["stages"].append({"id": stage_id, "status": "ERROR", "error": str(exc)})
                return fail(f"stage {stage_id} could not start")

            stage_result: dict[str, Any] = {
                "id": stage_id,
                "argv": argv,
                "return_code": proc.returncode,
                "status": "PASS" if proc.returncode == 0 else "FAIL",
            }
            report["stages"].append(stage_result)
            if proc.returncode != 0:
                stage_result["stderr"] = proc.stderr[-4000:]
                return fail(f"stage {stage_id} failed with exit code {proc.returncode}", code=proc.returncode or 2)

            for output in raw_stage.get("required_outputs", []):
                if not resolve(root, str(output)).exists():
                    return fail(f"stage {stage_id} missing required output: {output}")

            changed = snapshot.changed()
            if changed:
                return fail(f"stage {stage_id} attempted to mutate protected production paths")

        gate_path = resolve(root, str(config.get("gate_report") or ""))
        if not gate_path.is_file():
            return fail(f"gate report missing: {gate_path}")
        gate = load_json(gate_path)
        if gate.get("schema") != GATE_SCHEMA:
            return fail("unexpected promotion gate report schema")
        if gate.get("cycle") != cycle:
            return fail(f"gate report cycle mismatch: {gate.get('cycle')!r} != {cycle!r}")
        report["gate"] = {
            "path": os.path.relpath(gate_path, root) if gate_path.is_relative_to(root) else str(gate_path),
            "status": gate.get("status"),
            "promotion_ready": gate.get("promotion_ready"),
        }
        if require_ready and (gate.get("status") != "PASS" or gate.get("promotion_ready") is not True):
            return fail("promotion gate is not PASS/promotion_ready")

        changed = snapshot.changed()
        if changed:
            return fail("production changed during validation-only cycle")

        report.update({
            "status": "PASS",
            "reason": "all required stages and gate checks passed; validation-only execution left protected state unchanged",
            "production_after": snapshot.identities(),
            "production_changed_paths_detected": [],
            "production_restoration_verified": True,
            "promotion_applied": False,
        })
        write_report(report_path, report)
        return 0, report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--root", default=str(REPO_ROOT))
    ap.add_argument("--report")
    ap.add_argument("--require-ready", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    config_path = resolve(root, args.config)
    report_path = resolve(root, args.report) if args.report else None
    try:
        code, report = execute(
            root=root,
            config_path=config_path,
            report_path=report_path,
            require_ready=args.require_ready,
        )
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"continuous-cycle contract error: {exc}")
        return 2
    print(canonical_json(report), end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
