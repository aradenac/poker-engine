#!/usr/bin/env python3
"""Build and validate the fresh-recalculation plan required by issue #112.

The existing snapshot planner owns ingestion and a deterministic increment.  This
module owns the next boundary: proving that a new snapshot is wired to fresh
Model-A/Model-B/Hero/benchmark computations rather than to historical reports.
It deliberately does not invent component entrypoints.  Missing real component
bindings produce PREPARED_BLOCKED; malformed bindings fail closed.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "training/automation/RECALCULATION_PIPELINE_CONTRACT.json"
PLAN_SCHEMA = "poker-continuous-recalculation-plan/v1"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
NO_OP_STATUSES = {"NO_PENDING_SNAPSHOT", "NO_OP_ALREADY_PROCESSED"}


def canonical(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(data: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical(dict(data)).encode("utf-8")).hexdigest()


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("recalculation contract must be a JSON object")
    validate_contract(data)
    return data


def validate_contract(contract: Mapping[str, Any]) -> None:
    if contract.get("schema") != "poker-continuous-recalculation-contract/v1":
        raise ValueError("unsupported recalculation contract schema")
    if contract.get("status") != "FROZEN_REQUIREMENTS":
        raise ValueError("recalculation requirements must remain frozen")
    if contract.get("related_issue") != 112:
        raise ValueError("recalculation contract must remain tied to issue #112")
    roles = contract.get("required_stage_roles")
    if not isinstance(roles, list) or not roles:
        raise ValueError("required_stage_roles must be a non-empty list")
    names = [str(row.get("role") or "") for row in roles if isinstance(row, dict)]
    if len(names) != len(roles) or any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("required stage roles must be unique non-empty names")
    known = set(names)
    for row in roles:
        deps = row.get("depends_on", [])
        if not isinstance(deps, list) or len(deps) != len(set(deps)):
            raise ValueError(f"invalid depends_on for {row['role']}")
        if any(dep not in known for dep in deps):
            raise ValueError(f"unknown dependency for {row['role']}")
        if row["role"] in deps:
            raise ValueError(f"stage {row['role']} cannot depend on itself")
    requirements = contract.get("stage_requirements") or {}
    if requirements.get("mode") != "RECALCULATE":
        raise ValueError("required stage mode must remain RECALCULATE")
    if requirements.get("historical_result_may_satisfy_stage") is not False:
        raise ValueError("historical results must not satisfy recalculation stages")
    if requirements.get("required_outputs_must_be_new_run_scoped") is not True:
        raise ValueError("recalculation outputs must remain new-run scoped")
    if (contract.get("promotion") or {}).get("authorized_by_this_contract") is not False:
        raise ValueError("the recalculation contract must not authorize promotion")


def _role_specs(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in contract["required_stage_roles"]]


def _valid_hex(value: Any, regex: re.Pattern[str]) -> bool:
    return isinstance(value, str) and bool(regex.fullmatch(value.lower()))


def _run_dir(snapshot_plan: Mapping[str, Any]) -> str:
    runs_root = str(snapshot_plan.get("runs_root") or "").strip("/")
    run_id = str(snapshot_plan.get("run_id") or "").strip("/")
    if not runs_root or not run_id:
        raise ValueError("PLANNED snapshot requires runs_root and run_id")
    return f"{runs_root}/{run_id}"


def _under_run_dir(path: str, run_dir: str) -> bool:
    clean = str(path).replace("\\", "/").strip("/")
    prefix = run_dir.strip("/") + "/"
    return clean.startswith(prefix) and ".." not in Path(clean).parts


def _normalize_input(row: Any, *, role: str, allowed_dependencies: set[str]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError(f"{role} inputs must contain objects")
    path = str(row.get("path") or "").strip()
    if not path:
        raise ValueError(f"{role} input.path is required")
    sha = row.get("sha256")
    from_stage = row.get("from_stage")
    if bool(sha) == bool(from_stage):
        raise ValueError(f"{role} input {path} requires exactly one of sha256 or from_stage")
    if sha and not _valid_hex(sha, HEX64):
        raise ValueError(f"{role} input {path} has invalid sha256")
    if from_stage and str(from_stage) not in allowed_dependencies:
        raise ValueError(f"{role} input {path} references non-dependency stage {from_stage}")
    return {"path": path, "sha256": str(sha).lower() if sha else None, "from_stage": str(from_stage) if from_stage else None}


def normalize_binding(
    role_spec: Mapping[str, Any],
    binding: Mapping[str, Any],
    *,
    snapshot_sha256: str,
    run_dir: str,
) -> dict[str, Any]:
    role = str(role_spec["role"])
    if str(binding.get("role") or role) != role:
        raise ValueError(f"binding role mismatch for {role}")
    if str(binding.get("mode") or "") != "RECALCULATE":
        raise ValueError(f"{role} must use mode RECALCULATE")
    component_id = str(binding.get("component_id") or "").strip()
    if not component_id:
        raise ValueError(f"{role} component_id is required")
    source_commit_sha = str(binding.get("source_commit_sha") or "").lower()
    if not _valid_hex(source_commit_sha, HEX40):
        raise ValueError(f"{role} requires a 40-hex source_commit_sha")
    argv = binding.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
        raise ValueError(f"{role} argv must be a non-empty string list")
    consumed = str(binding.get("consumes_snapshot_sha256") or "").lower()
    if consumed != snapshot_sha256:
        raise ValueError(f"{role} must consume the selected snapshot SHA-256")
    if binding.get("historical_result_reuse") is not False:
        raise ValueError(f"{role} historical_result_reuse must be false")
    if binding.get("result_source") != "FRESH_CALCULATION":
        raise ValueError(f"{role} result_source must be FRESH_CALCULATION")

    dependencies = set(str(x) for x in role_spec.get("depends_on", []))
    inputs = [_normalize_input(row, role=role, allowed_dependencies=dependencies) for row in binding.get("inputs", [])]
    outputs = binding.get("required_outputs")
    if not isinstance(outputs, list) or not outputs or not all(isinstance(path, str) and path for path in outputs):
        raise ValueError(f"{role} required_outputs must be a non-empty string list")
    if len(outputs) != len(set(outputs)):
        raise ValueError(f"{role} required_outputs contains duplicates")
    for path in outputs:
        if not _under_run_dir(path, run_dir):
            raise ValueError(f"{role} output must be scoped under the new run directory: {path}")

    return {
        "role": role,
        "component_id": component_id,
        "source_commit_sha": source_commit_sha,
        "mode": "RECALCULATE",
        "depends_on": list(role_spec.get("depends_on", [])),
        "argv": list(argv),
        "consumes_snapshot_sha256": snapshot_sha256,
        "inputs": inputs,
        "required_outputs": list(outputs),
        "historical_result_reuse": False,
        "result_source": "FRESH_CALCULATION",
    }


def _with_fingerprint(plan: dict[str, Any]) -> dict[str, Any]:
    unsigned = dict(plan)
    unsigned.pop("plan_fingerprint_sha256", None)
    return {**unsigned, "plan_fingerprint_sha256": fingerprint(unsigned)}


def build_recalculation_plan(
    snapshot_plan: Mapping[str, Any],
    component_bindings: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contract = dict(contract or load_contract())
    validate_contract(contract)
    status = str(snapshot_plan.get("status") or "")
    population_id = str(snapshot_plan.get("population_id") or "")
    if not population_id:
        raise ValueError("snapshot plan requires population_id")

    if status in NO_OP_STATUSES:
        return _with_fingerprint({
            "schema": PLAN_SCHEMA,
            "contract_version": contract["contract_version"],
            "status": "NO_OP",
            "source_snapshot_status": status,
            "population_id": population_id,
            "snapshot_id": snapshot_plan.get("snapshot_id"),
            "snapshot_sha256": snapshot_plan.get("candidate_sha256"),
            "run_id": snapshot_plan.get("run_id"),
            "run_dir": None,
            "missing_components": [],
            "stages": [],
            "promotion_authorized": False,
        })
    if status != "PLANNED":
        raise ValueError(f"unsupported snapshot plan status: {status!r}")

    snapshot_sha = str(snapshot_plan.get("candidate_sha256") or "").lower()
    if not _valid_hex(snapshot_sha, HEX64):
        raise ValueError("PLANNED snapshot requires candidate_sha256")
    run_dir = _run_dir(snapshot_plan)
    bindings = dict(component_bindings or {})
    required_specs = _role_specs(contract)
    known_roles = {row["role"] for row in required_specs}
    unknown = sorted(set(bindings) - known_roles)
    if unknown:
        raise ValueError(f"unknown recalculation component roles: {', '.join(unknown)}")

    stages: list[dict[str, Any]] = []
    missing: list[str] = []
    for spec in required_specs:
        role = str(spec["role"])
        binding = bindings.get(role)
        if binding is None:
            missing.append(role)
            continue
        stages.append(normalize_binding(spec, binding, snapshot_sha256=snapshot_sha, run_dir=run_dir))

    plan = {
        "schema": PLAN_SCHEMA,
        "contract_version": contract["contract_version"],
        "status": "EXECUTABLE" if not missing else "PREPARED_BLOCKED",
        "source_snapshot_status": status,
        "population_id": population_id,
        "snapshot_id": snapshot_plan.get("snapshot_id"),
        "snapshot_sha256": snapshot_sha,
        "run_id": snapshot_plan.get("run_id"),
        "run_dir": run_dir,
        "missing_components": missing,
        "stages": stages,
        "promotion_authorized": False,
    }
    return _with_fingerprint(plan)


def validate_recalculation_plan(plan: Mapping[str, Any], *, contract: Mapping[str, Any] | None = None) -> None:
    contract = dict(contract or load_contract())
    validate_contract(contract)
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("unsupported recalculation plan schema")
    if plan.get("contract_version") != contract.get("contract_version"):
        raise ValueError("recalculation plan contract version mismatch")
    supplied = str(plan.get("plan_fingerprint_sha256") or "").lower()
    unsigned = dict(plan)
    unsigned.pop("plan_fingerprint_sha256", None)
    if supplied != fingerprint(unsigned):
        raise ValueError("recalculation plan fingerprint mismatch")
    if plan.get("promotion_authorized") is not False:
        raise ValueError("recalculation plan must not authorize promotion")

    status = str(plan.get("status") or "")
    if status == "NO_OP":
        if plan.get("stages") or plan.get("missing_components"):
            raise ValueError("NO_OP recalculation plan must contain no stages or missing components")
        if plan.get("source_snapshot_status") not in NO_OP_STATUSES:
            raise ValueError("NO_OP plan must originate from a no-op snapshot state")
        return
    if status not in {"PREPARED_BLOCKED", "EXECUTABLE"}:
        raise ValueError(f"unsupported recalculation plan status {status!r}")

    snapshot_sha = str(plan.get("snapshot_sha256") or "").lower()
    if not _valid_hex(snapshot_sha, HEX64):
        raise ValueError("recalculation plan requires snapshot_sha256")
    run_dir = str(plan.get("run_dir") or "")
    if not run_dir:
        raise ValueError("recalculation plan requires run_dir")
    specs = {row["role"]: row for row in _role_specs(contract)}
    required_roles = list(specs)
    stages = plan.get("stages")
    if not isinstance(stages, list):
        raise ValueError("recalculation plan stages must be a list")
    stage_roles = [str(row.get("role") or "") for row in stages if isinstance(row, dict)]
    if len(stage_roles) != len(stages) or len(stage_roles) != len(set(stage_roles)):
        raise ValueError("recalculation plan stage roles must be unique")
    if any(role not in specs for role in stage_roles):
        raise ValueError("recalculation plan contains an unknown role")
    for stage in stages:
        normalized = normalize_binding(specs[stage["role"]], stage, snapshot_sha256=snapshot_sha, run_dir=run_dir)
        if normalized != stage:
            raise ValueError(f"recalculation stage {stage['role']} is not canonical")

    missing = plan.get("missing_components")
    if not isinstance(missing, list) or len(missing) != len(set(missing)):
        raise ValueError("missing_components must be a unique list")
    expected_missing = [role for role in required_roles if role not in set(stage_roles)]
    if missing != expected_missing:
        raise ValueError("missing_components does not match unbound required roles")
    if status == "EXECUTABLE" and missing:
        raise ValueError("EXECUTABLE plan cannot have missing components")
    if status == "EXECUTABLE" and stage_roles != required_roles:
        raise ValueError("EXECUTABLE plan must bind every required role in contract order")
    if status == "PREPARED_BLOCKED" and not missing:
        raise ValueError("PREPARED_BLOCKED plan requires at least one missing component")


__all__ = [
    "PLAN_SCHEMA",
    "build_recalculation_plan",
    "fingerprint",
    "load_contract",
    "normalize_binding",
    "validate_contract",
    "validate_recalculation_plan",
]
