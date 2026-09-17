#!/usr/bin/env python3
"""Execute one immutable fresh-recalculation plan for issue #112.

The planner proves *what* must be recalculated.  This module supplies the missing
execution boundary: validate every declared input immediately before use, execute
stages in the frozen dependency order, require new-run-scoped outputs, persist
logs/output hashes, and never silently overwrite an earlier execution.

This executor never promotes production.  A successful recalculation is only
scientific evidence for the separately governed selection/publication path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]

from tools.training.recalculation_plan import load_contract, validate_recalculation_plan

REPORT_SCHEMA = "poker-continuous-recalculation-execution/v1"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"required file missing: {path}")
    return {"sha256": _sha256(path), "size_bytes": path.stat().st_size}


def _resolve(root: Path, raw: str) -> Path:
    path = Path(str(raw))
    return path if path.is_absolute() else root / path


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _path_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _git_worktree_changes(root: Path) -> set[str] | None:
    if not (root / ".git").exists():
        return None
    proc = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError("cannot inspect git worktree: " + proc.stderr.strip())
    changed: set[str] = set()
    for line in proc.stdout.splitlines():
        if not line:
            continue
        raw = line[3:]
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        changed.add(raw.strip().strip('"'))
    return changed


def _verify_source_commit(root: Path, sha: str) -> None:
    if not (root / ".git").exists():
        return
    proc = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        raise ValueError(f"declared component source commit is unavailable in checkout: {sha}")


def _validate_stage_inputs(
    *,
    root: Path,
    stage: Mapping[str, Any],
    completed: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    verified: list[dict[str, Any]] = []
    for row in stage.get("inputs", []):
        path = _resolve(root, str(row["path"]))
        if not path.is_file():
            raise ValueError(f"{stage['role']} input missing: {row['path']}")
        direct_sha = row.get("sha256")
        from_stage = row.get("from_stage")
        actual = _fingerprint(path)
        if direct_sha:
            if actual["sha256"] != str(direct_sha):
                raise ValueError(
                    f"{stage['role']} input hash mismatch for {row['path']}: "
                    f"{actual['sha256']} != {direct_sha}"
                )
        else:
            upstream = completed.get(str(from_stage))
            if upstream is None:
                raise ValueError(f"{stage['role']} dependency {from_stage} has not completed")
            upstream_outputs = {
                str(item["path"]): item for item in upstream.get("outputs", [])
            }
            declared = upstream_outputs.get(str(row["path"]))
            if declared is None:
                raise ValueError(
                    f"{stage['role']} dependency input {row['path']} was not produced by {from_stage}"
                )
            if actual["sha256"] != str(declared["sha256"]):
                raise ValueError(f"{stage['role']} dependency output changed after {from_stage}")
        verified.append({"path": str(row["path"]), **actual, "from_stage": from_stage})
    return verified


def _existing_execution(report_path: Path, plan: Mapping[str, Any]) -> tuple[int, dict[str, Any]] | None:
    if not report_path.exists():
        return None
    existing = _load_json(report_path)
    if existing.get("schema") != REPORT_SCHEMA:
        raise ValueError(f"existing execution report has unexpected schema: {report_path}")
    if existing.get("plan_fingerprint_sha256") != plan.get("plan_fingerprint_sha256"):
        raise ValueError("execution report exists for a different recalculation plan")
    if existing.get("status") == "PASS":
        replay = {
            **existing,
            "status": "NO_OP_ALREADY_EXECUTED",
            "idempotent_replay": True,
            "original_status": "PASS",
        }
        return 0, replay
    raise ValueError(
        "an execution report already exists but is not PASS; preserve it and create an explicit new run/resume plan"
    )


def execute_plan(
    plan: Mapping[str, Any],
    *,
    root: Path = ROOT,
    report_path: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    root = Path(root).resolve()
    contract = load_contract()
    validate_recalculation_plan(plan, contract=contract)
    status = str(plan.get("status"))

    if status == "NO_OP":
        return 0, {
            "schema": REPORT_SCHEMA,
            "status": "NO_OP",
            "plan_fingerprint_sha256": plan["plan_fingerprint_sha256"],
            "source_snapshot_status": plan.get("source_snapshot_status"),
            "population_id": plan.get("population_id"),
            "snapshot_sha256": plan.get("snapshot_sha256"),
            "promotion_authorized": False,
            "stages": [],
        }
    if status == "PREPARED_BLOCKED":
        return 2, {
            "schema": REPORT_SCHEMA,
            "status": "BLOCKED",
            "plan_fingerprint_sha256": plan["plan_fingerprint_sha256"],
            "population_id": plan.get("population_id"),
            "snapshot_sha256": plan.get("snapshot_sha256"),
            "missing_components": list(plan.get("missing_components") or []),
            "promotion_authorized": False,
            "stages": [],
        }
    if status != "EXECUTABLE":
        raise ValueError(f"unsupported recalculation plan status: {status!r}")

    run_dir = _resolve(root, str(plan["run_dir"])).resolve()
    if not _path_under(run_dir, root):
        raise ValueError("recalculation run directory must remain inside the repository checkout")
    report_path = Path(report_path).resolve() if report_path else run_dir / "RECALCULATION_EXECUTION.json"
    if not _path_under(report_path, run_dir):
        raise ValueError("execution report must be scoped under the recalculation run directory")
    previous = _existing_execution(report_path, plan)
    if previous is not None:
        return previous

    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    baseline_changes = _git_worktree_changes(root)
    completed: dict[str, dict[str, Any]] = {}
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "RUNNING",
        "plan_fingerprint_sha256": plan["plan_fingerprint_sha256"],
        "population_id": plan.get("population_id"),
        "snapshot_id": plan.get("snapshot_id"),
        "snapshot_sha256": plan.get("snapshot_sha256"),
        "run_id": plan.get("run_id"),
        "run_dir": str(plan.get("run_dir")),
        "promotion_authorized": False,
        "historical_result_reuse": False,
        "stages": [],
    }
    _write_json_atomic(report_path, report)

    def fail(message: str, *, role: str | None = None, return_code: int = 2) -> tuple[int, dict[str, Any]]:
        report["status"] = "FAIL"
        report["failure"] = {"message": message, "role": role}
        report["promotion_authorized"] = False
        _write_json_atomic(report_path, report)
        return return_code, report

    for stage in plan.get("stages", []):
        role = str(stage["role"])
        try:
            _verify_source_commit(root, str(stage["source_commit_sha"]))
            verified_inputs = _validate_stage_inputs(root=root, stage=stage, completed=completed)
            output_paths = [_resolve(root, str(raw)).resolve() for raw in stage["required_outputs"]]
            if any(not _path_under(path, run_dir) for path in output_paths):
                return fail("stage output escaped immutable run directory", role=role)
            preexisting = [str(stage["required_outputs"][i]) for i, path in enumerate(output_paths) if path.exists()]
            if preexisting:
                return fail(
                    "stage would overwrite pre-existing output(s): " + ", ".join(preexisting),
                    role=role,
                )
            for path in output_paths:
                path.parent.mkdir(parents=True, exist_ok=True)
        except (ValueError, OSError, RuntimeError) as exc:
            return fail(str(exc), role=role)

        stdout_path = logs_dir / f"{role}.stdout.log"
        stderr_path = logs_dir / f"{role}.stderr.log"
        env = os.environ.copy()
        env.update({
            "PYTHONDONTWRITEBYTECODE": "1",
            "POKER_RECALCULATION_ROLE": role,
            "POKER_RECALCULATION_RUN_DIR": str(run_dir),
            "POKER_SNAPSHOT_SHA256": str(plan["snapshot_sha256"]),
        })
        started = time.time()
        try:
            with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
                proc = subprocess.run(list(stage["argv"]), cwd=root, env=env, text=True, stdout=stdout, stderr=stderr)
        except OSError as exc:
            return fail(f"stage could not start: {exc}", role=role)
        elapsed = time.time() - started
        stage_report: dict[str, Any] = {
            "role": role,
            "component_id": stage["component_id"],
            "source_commit_sha": stage["source_commit_sha"],
            "argv": list(stage["argv"]),
            "argv_shell": shlex.join(stage["argv"]),
            "return_code": int(proc.returncode),
            "elapsed_seconds": round(elapsed, 6),
            "inputs": verified_inputs,
            "stdout_log": _relative(root, stdout_path),
            "stderr_log": _relative(root, stderr_path),
            "outputs": [],
            "status": "PASS" if proc.returncode == 0 else "FAIL",
        }
        report["stages"].append(stage_report)
        if proc.returncode != 0:
            return fail(f"stage exited with code {proc.returncode}", role=role, return_code=proc.returncode or 2)

        missing = [str(stage["required_outputs"][i]) for i, path in enumerate(output_paths) if not path.is_file()]
        if missing:
            return fail("stage missing required output(s): " + ", ".join(missing), role=role)
        stage_report["outputs"] = [
            {"path": str(raw), **_fingerprint(path)}
            for raw, path in zip(stage["required_outputs"], output_paths)
        ]
        completed[role] = stage_report

        current_changes = _git_worktree_changes(root)
        if baseline_changes is not None and current_changes is not None:
            unexpected = sorted(
                path for path in (current_changes - baseline_changes)
                if not _path_under(root / path, run_dir)
            )
            if unexpected:
                return fail(
                    "stage modified files outside immutable run directory: " + ", ".join(unexpected),
                    role=role,
                )
        _write_json_atomic(report_path, report)

    report["status"] = "PASS"
    report["completed_roles"] = [str(stage["role"]) for stage in plan["stages"]]
    report["promotion_authorized"] = False
    report["fresh_calculation_verified"] = True
    _write_json_atomic(report_path, report)
    return 0, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    plan = _load_json(args.plan)
    code, report = execute_plan(plan, root=ROOT, report_path=args.report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
