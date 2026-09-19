#!/usr/bin/env python3
"""Stable non-CI helper for future workflow consumption of the #203 environment contract."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any, Callable

try:
    from tools import repro_environment_identity
except ImportError:
    import repro_environment_identity  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "poker-repro-ci-environment-helper/v1"
REPORT_SCHEMA = "poker-repro-ci-environment-report/v1"


class HelperError(ValueError):
    pass


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise HelperError(f"missing JSON source: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HelperError(f"JSON source must be an object: {path}")
    return value


def _sha(path: Path) -> str:
    if not path.is_file():
        raise HelperError(f"missing lock: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    env = _json(root / "reproducibility/environment.lock.json")
    if env.get("schema") != "poker-engine-repro-environment/v1":
        raise HelperError("unexpected environment lock schema")

    python_version = str(env.get("python", {}).get("version", ""))
    node_version = str(env.get("node", {}).get("version", ""))
    requirements = root / str(env.get("python", {}).get("requirements", ""))
    package_lock = root / str(env.get("node", {}).get("package_lock", ""))

    if (root / ".python-version").read_text(encoding="utf-8").strip() != python_version:
        raise HelperError(".python-version diverges from environment lock")
    if (root / ".node-version").read_text(encoding="utf-8").strip() != node_version:
        raise HelperError(".node-version diverges from environment lock")
    if not requirements.is_file() or not package_lock.is_file():
        raise HelperError("dependency lock missing")

    return {
        "schema": SCHEMA,
        "expected": {
            "python": python_version,
            "node": node_version,
        },
        "locks": {
            "environment": {
                "path": "reproducibility/environment.lock.json",
                "sha256": _sha(root / "reproducibility/environment.lock.json"),
            },
            "python": {
                "path": requirements.relative_to(root).as_posix(),
                "sha256": _sha(requirements),
            },
            "node": {
                "path": package_lock.relative_to(root).as_posix(),
                "sha256": _sha(package_lock),
            },
        },
    }


def plan(
    root: Path = ROOT,
    *,
    install_python_deps: bool = False,
    install_node_deps: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    spec = contract(root)
    commands: list[list[str]] = []
    if install_python_deps:
        commands.append([
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "-r",
            spec["locks"]["python"]["path"],
        ])
    if install_node_deps:
        commands.append(["npm", "ci", "--ignore-scripts"])
    return {
        "schema": SCHEMA,
        "expected": spec["expected"],
        "locks": spec["locks"],
        "commands": commands,
    }


def _node_version(run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> str | None:
    try:
        result = run(
            ["node", "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip().lstrip("v")


def verify(
    root: Path = ROOT,
    *,
    require_node: bool = False,
    observed_python: str | None = None,
    observed_node: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    spec = contract(root)
    python_version = observed_python or platform.python_version()
    node_version = observed_node if observed_node is not None else (_node_version() if require_node else None)
    violations: list[dict[str, Any]] = []

    if python_version != spec["expected"]["python"]:
        violations.append({
            "rule": "PYTHON_VERSION_MISMATCH",
            "expected": spec["expected"]["python"],
            "observed": python_version,
        })
    if require_node and node_version != spec["expected"]["node"]:
        violations.append({
            "rule": "NODE_VERSION_MISMATCH",
            "expected": spec["expected"]["node"],
            "observed": node_version,
        })

    identity = repro_environment_identity.materialize_identity(root)
    return {
        "schema": REPORT_SCHEMA,
        "status": "FAIL" if violations else "PASS",
        "expected": spec["expected"],
        "observed": {"python": python_version, "node": node_version},
        "lock_sha256": {k: v["sha256"] for k, v in spec["locks"].items()},
        "environment_identity_sha256": identity["identity_sha256"],
        "violations": violations,
    }


def execute(
    root: Path = ROOT,
    *,
    install_python_deps: bool = False,
    install_node_deps: bool = False,
    require_node: bool = False,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    root = root.resolve()
    p = plan(
        root,
        install_python_deps=install_python_deps,
        install_node_deps=install_node_deps,
    )
    for command in p["commands"]:
        run(command, cwd=root, check=True)
    return verify(root, require_node=require_node)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    plan_p = sub.add_parser("plan")
    plan_p.add_argument("--python-deps", action="store_true")
    plan_p.add_argument("--node-deps", action="store_true")

    verify_p = sub.add_parser("verify")
    verify_p.add_argument("--require-node", action="store_true")

    bootstrap_p = sub.add_parser("bootstrap")
    bootstrap_p.add_argument("--python-deps", action="store_true")
    bootstrap_p.add_argument("--node-deps", action="store_true")
    bootstrap_p.add_argument("--require-node", action="store_true")

    identity_p = sub.add_parser("identity")
    identity_p.add_argument("--output", type=Path)

    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "plan":
            value = plan(root, install_python_deps=args.python_deps, install_node_deps=args.node_deps)
        elif args.command == "verify":
            value = verify(root, require_node=args.require_node)
        elif args.command == "bootstrap":
            value = execute(
                root,
                install_python_deps=args.python_deps,
                install_node_deps=args.node_deps,
                require_node=args.require_node,
            )
        else:
            value = repro_environment_identity.materialize_identity(root)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                print(args.output)
                return 0

        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
        return 2 if value.get("status") == "FAIL" else 0
    except (HelperError, repro_environment_identity.IdentityError, subprocess.CalledProcessError) as exc:
        print(json.dumps({
            "schema": REPORT_SCHEMA,
            "status": "FAIL",
            "violations": [{"rule": "HELPER_ERROR", "detail": str(exc)}],
        }, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
