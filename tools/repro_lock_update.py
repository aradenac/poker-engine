#!/usr/bin/env python3
"""Dry-run lock update planner and non-regression gate for issue #203."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

try:
    from tools import repro_container, repro_environment_identity, repro_hardening
except ImportError:
    import repro_container  # type: ignore
    import repro_environment_identity  # type: ignore
    import repro_hardening  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "reproducibility/lock-update-policy.json"
POLICY_SCHEMA = "poker-engine-repro-lock-update-policy/v1"
PLAN_SCHEMA = "poker-engine-repro-lock-update-plan/v1"
SHA_RX = re.compile(r"^[0-9a-f]{64}$")


class LockUpdateError(ValueError):
    pass


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise LockUpdateError(f"missing JSON source: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LockUpdateError(f"invalid JSON source {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LockUpdateError(f"JSON source must be an object: {path}")
    return value


def _sha(path: Path) -> str:
    if not path.is_file():
        raise LockUpdateError(f"missing managed file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_policy(root: Path = ROOT) -> dict[str, Any]:
    policy = _json(root / "reproducibility/lock-update-policy.json")
    if policy.get("schema") != POLICY_SCHEMA:
        raise LockUpdateError("unexpected lock-update policy schema")
    if policy.get("mode") != "DRY_RUN_REVIEW_ONLY":
        raise LockUpdateError("lock-update policy must remain dry-run/review-only")
    managed = policy.get("managed_files")
    components = policy.get("components")
    matrix = policy.get("non_regression_matrix")
    if not isinstance(managed, list) or not managed or len(managed) != len(set(managed)):
        raise LockUpdateError("managed_files must be a non-empty unique list")
    if not isinstance(components, dict) or not components:
        raise LockUpdateError("components policy is required")
    if not isinstance(matrix, dict) or not isinstance(matrix.get("always"), list):
        raise LockUpdateError("non_regression_matrix.always is required")
    for component, cfg in components.items():
        required = cfg.get("required_changed_files") if isinstance(cfg, dict) else None
        if not isinstance(required, list) or not required:
            raise LockUpdateError(f"component {component} missing required_changed_files")
        unknown = sorted(set(required) - set(managed))
        if unknown:
            raise LockUpdateError(f"component {component} references unmanaged files: {unknown}")
    return policy


def _playwright_pin(path: Path) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("playwright=="):
            return stripped.split("==", 1)[1]
    return None


def _docker_arg(text: str, name: str) -> str | None:
    match = re.search(rf"(?m)^ARG\s+{re.escape(name)}=([^\s]+)\s*$", text)
    return match.group(1) if match else None


def _docker_from(text: str) -> str | None:
    match = re.search(r"(?m)^FROM\s+([^\s]+)", text)
    return match.group(1) if match else None


def component_snapshot(root: Path) -> dict[str, Any]:
    env = _json(root / "reproducibility/environment.lock.json")
    os_lock = _json(root / "reproducibility/os-base.lock.json")
    container = _json(root / "reproducibility/container-base.lock.json")
    apt = _json(root / "reproducibility/apt-snapshot.lock.json")
    resolution = _json(root / "reproducibility/system-packages.resolution.lock.json")
    browser = _json(root / "reproducibility/browser-identity.lock.json")
    package = _json(root / "package.json")
    package_lock = _json(root / "package-lock.json")
    docker = (root / "reproducibility/Dockerfile.science").read_text(encoding="utf-8")
    sources = (root / "reproducibility/ubuntu-snapshot.sources").read_text(encoding="utf-8")
    system_packages = [
        x.strip()
        for x in (root / "reproducibility/system-packages.apt.txt").read_text(encoding="utf-8").splitlines()
        if x.strip() and not x.lstrip().startswith("#")
    ]

    return {
        "python_runtime": {
            "dot_version": (root / ".python-version").read_text(encoding="utf-8").strip(),
            "environment": env.get("python"),
            "container_source": container.get("runtime_sources", {}).get("python"),
            "docker_arg_version": _docker_arg(docker, "PYTHON_VERSION"),
            "docker_arg_sha256": _docker_arg(docker, "PYTHON_SHA256"),
        },
        "python_dependencies": {
            "requirements_in_sha256": _sha(root / "requirements.in"),
            "requirements_lock_sha256": _sha(root / "requirements.lock.txt"),
        },
        "node_runtime": {
            "dot_version": (root / ".node-version").read_text(encoding="utf-8").strip(),
            "package_engine": package.get("engines", {}).get("node"),
            "package_lock_engine": package_lock.get("packages", {}).get("", {}).get("engines", {}).get("node"),
            "environment": env.get("node"),
            "container_source": container.get("runtime_sources", {}).get("node"),
            "docker_arg_version": _docker_arg(docker, "NODE_VERSION"),
            "docker_arg_sha256": _docker_arg(docker, "NODE_SHA256"),
        },
        "node_dependencies": {
            "package_json_sha256": _sha(root / "package.json"),
            "package_lock_sha256": _sha(root / "package-lock.json"),
        },
        "playwright_runtime": {
            "requirements_in_playwright": _playwright_pin(root / "requirements.in"),
            "requirements_lock_playwright": _playwright_pin(root / "requirements.lock.txt"),
            "environment_version": env.get("playwright", {}).get("python_package_version"),
            "container_version": container.get("runtime_sources", {}).get("playwright", {}).get("version"),
            "browser_lock_playwright": browser.get("playwright"),
            "docker_arg_playwright": _docker_arg(docker, "PLAYWRIGHT_VERSION"),
        },
        "chromium_runtime": {
            "environment_browser": env.get("playwright", {}).get("browser"),
            "environment_version": env.get("playwright", {}).get("chromium_version"),
            "container_browser": container.get("runtime_sources", {}).get("playwright", {}).get("browser"),
            "container_version": container.get("runtime_sources", {}).get("playwright", {}).get("chromium_version"),
            "browser_lock_browser": browser.get("browser"),
            "archive_identity": browser.get("archive_identity"),
            "executable_identity": browser.get("executable_identity"),
            "provenance": browser.get("provenance"),
            "docker_arg_chromium": _docker_arg(docker, "CHROMIUM_VERSION"),
        },
        "os_base": {
            "environment": env.get("os"),
            "os_lock": os_lock,
            "container_os": container.get("image", {}).get("os"),
        },
        "container_base": {
            "image": container.get("image"),
            "verification": container.get("verification"),
            "docker_from": _docker_from(docker),
        },
        "apt_snapshot": {
            "snapshot_lock": apt,
            "resolution_header": {
                k: resolution.get(k)
                for k in ("snapshot_id", "architecture", "pinning_level", "fully_pinned")
            },
            "sources_sha256": hashlib.sha256(sources.encode("utf-8")).hexdigest(),
            "docker_arg_snapshot": _docker_arg(docker, "APT_SNAPSHOT_ID"),
        },
        "system_packages": {
            "requested": system_packages,
            "resolution_entries": resolution.get("entries"),
        },
    }


def _semantic_diff(before: Any, after: Any, prefix: str = "") -> list[dict[str, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        out: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in before:
                out.append({"path": path, "old": None, "new": after[key]})
            elif key not in after:
                out.append({"path": path, "old": before[key], "new": None})
            else:
                out.extend(_semantic_diff(before[key], after[key], path))
        return out
    if before != after:
        return [{"path": prefix, "old": before, "new": after}]
    return []


def _validate_basic_contract(root: Path) -> None:
    env = _json(root / "reproducibility/environment.lock.json")
    python_version = (root / ".python-version").read_text(encoding="utf-8").strip()
    node_version = (root / ".node-version").read_text(encoding="utf-8").strip()
    if env.get("python", {}).get("version") != python_version:
        raise LockUpdateError(".python-version diverges from environment lock")
    if env.get("node", {}).get("version") != node_version:
        raise LockUpdateError(".node-version diverges from environment lock")
    if _playwright_pin(root / "requirements.in") != env.get("playwright", {}).get("python_package_version"):
        raise LockUpdateError("requirements.in Playwright pin diverges from environment lock")
    if _playwright_pin(root / "requirements.lock.txt") != env.get("playwright", {}).get("python_package_version"):
        raise LockUpdateError("requirements lock Playwright pin diverges from environment lock")
    package = _json(root / "package.json")
    package_lock = _json(root / "package-lock.json")
    if package.get("engines", {}).get("node") != node_version:
        raise LockUpdateError("package.json Node engine diverges from .node-version")
    if package_lock.get("packages", {}).get("", {}).get("engines", {}).get("node") != node_version:
        raise LockUpdateError("package-lock Node engine diverges from .node-version")
    if package_lock.get("lockfileVersion") != 3:
        raise LockUpdateError("package-lock.json must use lockfileVersion 3")
    if env.get("scope", {}).get("workflows_wired") is not False:
        raise LockUpdateError("non-CI update procedure must not claim workflows are wired")


def validate_repro_root(root: Path) -> dict[str, Any]:
    _validate_basic_contract(root)
    try:
        repro_container.validate_contract(root)
        hardening = repro_hardening.expected_identity(root)
        container = repro_container.materialize_manifest(root)
        identity = repro_environment_identity.materialize_identity(root)
    except (
        repro_container.ContainerContractError,
        repro_hardening.HardeningError,
        repro_environment_identity.IdentityError,
        KeyError,
        OSError,
        ValueError,
    ) as exc:
        raise LockUpdateError(f"REPRO contract invalid: {exc}") from exc
    return {
        "environment_identity_sha256": identity["identity_sha256"],
        "container_manifest_sha256": container["manifest_sha256"],
        "hermeticity_level": hardening["hermeticity_level"],
    }


def _required_tests(policy: dict[str, Any], components: list[str]) -> list[str]:
    matrix = policy["non_regression_matrix"]
    commands: list[str] = []
    for command in matrix.get("always", []):
        if command not in commands:
            commands.append(command)
    for component in components:
        for command in matrix.get(component, []):
            if command not in commands:
                commands.append(command)
    return commands


def _state_sha256(root: Path, managed_files: list[str]) -> str:
    rows = [{"path": rel, "sha256": _sha(root / rel)} for rel in sorted(managed_files)]
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _plan_sha256(plan: dict[str, Any]) -> str:
    payload = copy.deepcopy(plan)
    payload.pop("plan_sha256", None)
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def build_plan(
    baseline_root: Path,
    candidate_root: Path,
    *,
    expected_components: list[str] | None = None,
) -> dict[str, Any]:
    baseline_root = baseline_root.resolve()
    candidate_root = candidate_root.resolve()
    policy = load_policy(baseline_root)
    violations: list[dict[str, Any]] = []

    file_changes: list[dict[str, Any]] = []
    changed_files: set[str] = set()
    for rel in policy["managed_files"]:
        before_path = baseline_root / rel
        after_path = candidate_root / rel
        if not before_path.is_file():
            raise LockUpdateError(f"baseline managed file missing: {rel}")
        if not after_path.is_file():
            violations.append({"rule": "MISSING_CANDIDATE_FILE", "path": rel})
            continue
        before_sha = _sha(before_path)
        after_sha = _sha(after_path)
        if before_sha != after_sha:
            changed_files.add(rel)
            file_changes.append({
                "path": rel,
                "old_sha256": before_sha,
                "new_sha256": after_sha,
            })

    before_snapshot = component_snapshot(baseline_root)
    after_snapshot = (
        component_snapshot(candidate_root)
        if not any(v["rule"] == "MISSING_CANDIDATE_FILE" for v in violations)
        else {}
    )
    component_changes: list[dict[str, Any]] = []
    changed_components: list[str] = []
    if after_snapshot:
        for name in sorted(before_snapshot):
            diff = _semantic_diff(before_snapshot[name], after_snapshot[name])
            if not diff:
                continue
            changed_components.append(name)
            required = set(policy["components"][name]["required_changed_files"])
            missing = sorted(required - changed_files)
            if missing:
                violations.append({
                    "rule": "PARTIAL_COMPONENT_UPDATE",
                    "component": name,
                    "missing_required_changed_files": missing,
                })
            component_changes.append({
                "component": name,
                "required_changed_files": sorted(required),
                "semantic_changes": diff,
            })

    if changed_files and not changed_components:
        violations.append({
            "rule": "UNCLASSIFIED_MANAGED_CHANGE",
            "changed_files": sorted(changed_files),
        })

    expected_set = set(expected_components or [])
    if expected_components is not None and expected_set != set(changed_components):
        violations.append({
            "rule": "EXPECTED_COMPONENT_SET_MISMATCH",
            "expected": sorted(expected_set),
            "observed": sorted(changed_components),
        })

    identities: dict[str, Any] = {}
    try:
        identities["old"] = validate_repro_root(baseline_root)
    except LockUpdateError as exc:
        violations.append({"rule": "BASELINE_CONTRACT_INVALID", "detail": str(exc)})
    try:
        identities["new"] = validate_repro_root(candidate_root)
    except LockUpdateError as exc:
        violations.append({"rule": "CANDIDATE_CONTRACT_INVALID", "detail": str(exc)})

    if changed_files and identities.get("old") == identities.get("new"):
        violations.append({
            "rule": "LOCK_CHANGE_WITHOUT_IDENTITY_CHANGE",
            "detail": "managed lock content changed but environment/container identities did not",
        })

    if not changed_files and not violations:
        status = "NO_CHANGE"
    else:
        status = "FAIL" if violations else "PASS"

    plan = {
        "schema": PLAN_SCHEMA,
        "status": status,
        "dry_run": True,
        "policy_sha256": _sha(
            baseline_root / "reproducibility/lock-update-policy.json"
        ),
        "baseline_managed_state_sha256": _state_sha256(
            baseline_root,
            policy["managed_files"],
        ),
        "candidate_managed_state_sha256": (
            _state_sha256(candidate_root, policy["managed_files"])
            if not any(v["rule"] == "MISSING_CANDIDATE_FILE" for v in violations)
            else None
        ),
        "changed_files": sorted(file_changes, key=lambda row: row["path"]),
        "changed_components": changed_components,
        "component_changes": component_changes,
        "identities": identities,
        "identity_changed": (
            identities.get("old") != identities.get("new")
            if "old" in identities and "new" in identities
            else None
        ),
        "required_non_regression_commands": _required_tests(
            policy,
            changed_components,
        ),
        "violations": sorted(
            violations,
            key=lambda row: (
                row.get("rule", ""),
                row.get("component", ""),
                row.get("path", ""),
            ),
        ),
        "review_requirements": policy.get("review_requirements", []),
    }
    plan["plan_sha256"] = _plan_sha256(plan)
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--candidate-root", type=Path, required=True)
    plan.add_argument(
        "--expect-component",
        action="append",
        choices=[
            "python_runtime",
            "python_dependencies",
            "node_runtime",
            "node_dependencies",
            "playwright_runtime",
            "chromium_runtime",
            "os_base",
            "container_base",
            "apt_snapshot",
            "system_packages",
        ],
    )
    plan.add_argument("--output", type=Path)

    sub.add_parser("matrix")

    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "matrix":
            policy = load_policy(root)
            value = {
                "schema": POLICY_SCHEMA,
                "components": policy["components"],
                "non_regression_matrix": policy["non_regression_matrix"],
                "review_requirements": policy.get("review_requirements", []),
            }
        else:
            value = build_plan(
                root,
                args.candidate_root,
                expected_components=args.expect_component,
            )
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(
                        value,
                        indent=2,
                        sort_keys=True,
                        ensure_ascii=False,
                    ) + "\n",
                    encoding="utf-8",
                )
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
        return 2 if value.get("status") == "FAIL" else 0
    except (LockUpdateError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps({
                "schema": PLAN_SCHEMA,
                "status": "FAIL",
                "dry_run": True,
                "violations": [{
                    "rule": "LOCK_UPDATE_ERROR",
                    "detail": str(exc),
                }],
            }, indent=2, sort_keys=True),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
