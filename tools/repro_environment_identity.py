#!/usr/bin/env python3
"""Deterministic future-run environment identity built only from versioned REPRO sources."""
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
    from tools import repro_container
except ImportError:  # direct script execution from tools/
    import repro_container  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "poker-environment-identity/v1"
VERSION = 1
POLICY_REQUIRED = "REQUIRED"
POLICY_GRANDFATHERED = "GRANDFATHERED_IMMUTABLE"
LOCK_ROLES = ("requirements_lock", "package_lock", "environment_lock", "os_lock")
VERSION_RX = re.compile(r"^[0-9]+(?:\.[0-9A-Za-z-]+)+$")
SHA256_RX = re.compile(r"^[0-9a-f]{64}$")


class IdentityError(ValueError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise IdentityError(f"missing JSON source: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IdentityError(f"invalid JSON source {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise IdentityError(f"JSON source must be an object: {path}")
    return data


def _read_required_text(path: Path) -> str:
    if not path.is_file():
        raise IdentityError(f"missing versioned source: {path}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise IdentityError(f"empty versioned source: {path}")
    return value


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise IdentityError(f"missing lock: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_payload(identity: dict[str, Any]) -> bytes:
    payload = copy.deepcopy(identity)
    payload.pop("identity_sha256", None)
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def canonical_sha256(identity: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload(identity)).hexdigest()


def _critical_version(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IdentityError(f"missing critical version: {label}")
    value = value.strip()
    if not VERSION_RX.match(value):
        raise IdentityError(f"non-canonical critical version {label}: {value}")
    return value


def _validate_sources(
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path]]:
    env_path = root / "reproducibility/environment.lock.json"
    env = _read_json(env_path)
    if env.get("schema") != "poker-engine-repro-environment/v1":
        raise IdentityError("unexpected environment lock schema")

    try:
        requirements_rel = env["python"]["requirements"]
        package_rel = env["node"]["package_lock"]
        os_rel = env["os"]["spec"]
    except (KeyError, TypeError) as exc:
        raise IdentityError(
            f"environment lock missing lock-path contract: {exc}"
        ) from exc

    paths = {
        "requirements_lock": root / str(requirements_rel),
        "package_lock": root / str(package_rel),
        "environment_lock": env_path,
        "os_lock": root / str(os_rel),
    }
    for role, path in paths.items():
        if not path.is_file():
            raise IdentityError(f"missing {role}: {path}")

    os_lock = _read_json(paths["os_lock"])
    if os_lock.get("schema") != "poker-engine-os-base/v1":
        raise IdentityError("unexpected OS lock schema")

    python_version = _critical_version(
        env.get("python", {}).get("version"), "python"
    )
    node_version = _critical_version(env.get("node", {}).get("version"), "node")
    playwright_version = _critical_version(
        env.get("playwright", {}).get("python_package_version"), "playwright"
    )
    chromium_version = _critical_version(
        env.get("playwright", {}).get("chromium_version"), "chromium"
    )
    browser_name = env.get("playwright", {}).get("browser")
    if not isinstance(browser_name, str) or not browser_name.strip():
        raise IdentityError("missing critical browser identity")

    if _read_required_text(root / ".python-version") != python_version:
        raise IdentityError(".python-version diverges from environment lock")
    if _read_required_text(root / ".node-version") != node_version:
        raise IdentityError(".node-version diverges from environment lock")

    req_text = paths["requirements_lock"].read_text(encoding="utf-8")
    if f"playwright=={playwright_version}" not in {
        line.strip() for line in req_text.splitlines()
    }:
        raise IdentityError(
            "requirements lock does not contain the critical Playwright pin"
        )
    for line in req_text.splitlines():
        stripped = line.strip()
        if (
            stripped
            and not stripped.startswith("#")
            and stripped.count("==") != 1
        ):
            raise IdentityError(f"implicit/unpinned Python dependency: {stripped}")

    package_lock = _read_json(paths["package_lock"])
    if package_lock.get("lockfileVersion") != 3:
        raise IdentityError("package lock must use lockfileVersion 3")
    lock_node = (
        package_lock.get("packages", {})
        .get("", {})
        .get("engines", {})
        .get("node")
    )
    if lock_node != node_version:
        raise IdentityError("package lock Node engine diverges from environment lock")

    env_os = env.get("os", {})
    os_distribution = os_lock.get("distribution", {})
    if os_distribution.get("id") != env_os.get("id"):
        raise IdentityError("OS distribution diverges between locks")
    if os_distribution.get("version_id") != env_os.get("version_id"):
        raise IdentityError("OS version diverges between locks")
    if os_lock.get("machine") != env_os.get("machine"):
        raise IdentityError("OS architecture diverges between locks")

    env = copy.deepcopy(env)
    env["python"]["version"] = python_version
    env["node"]["version"] = node_version
    env["playwright"]["python_package_version"] = playwright_version
    env["playwright"]["chromium_version"] = chromium_version
    env["playwright"]["browser"] = browser_name.strip()
    return env, os_lock, paths


def materialize_identity(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    env, os_lock, paths = _validate_sources(root)

    identity: dict[str, Any] = {
        "schema": SCHEMA,
        "version": VERSION,
        "expected": {
            "python": {"version": env["python"]["version"]},
            "node": {"version": env["node"]["version"]},
            "playwright": {
                "version": env["playwright"]["python_package_version"]
            },
            "browser": {
                "name": env["playwright"]["browser"],
                "version": env["playwright"]["chromium_version"],
            },
            "os": {
                "distribution": os_lock["distribution"]["id"],
                "version": os_lock["distribution"]["version_id"],
                "architecture": os_lock["machine"],
            },
        },
        "locks": [
            {
                "role": role,
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256_file(path),
            }
            for role, path in ((role, paths[role]) for role in LOCK_ROLES)
        ],
    }

    if env.get("container") is not None:
        try:
            container_manifest = repro_container.materialize_manifest(root)
        except repro_container.ContainerContractError as exc:
            raise IdentityError(f"invalid container contract: {exc}") from exc

        identity["container"] = {
            "base_image": {
                "repository": container_manifest["base_image"]["repository"],
                "tag": container_manifest["base_image"]["tag"],
                "platform": container_manifest["base_image"]["platform"],
                "digest": container_manifest["base_image"]["manifest_digest"],
                "architecture": container_manifest["base_image"]["os"][
                    "architecture"
                ],
                "os": {
                    "distribution": container_manifest["base_image"]["os"]["id"],
                    "version": container_manifest["base_image"]["os"][
                        "version_id"
                    ],
                },
            },
            "definition": container_manifest["definition"],
            "container_lock_sha256": container_manifest["locks"][
                "container_base_lock_sha256"
            ],
            "system_packages_sha256": container_manifest["locks"][
                "system_packages_sha256"
            ],
            "container_manifest_sha256": container_manifest["manifest_sha256"],
            "hermeticity_level": container_manifest["hermeticity"]["level"],
            "base_image_pinned": container_manifest["hermeticity"][
                "base_image_pinned"
            ],
            "system_packages_fully_pinned": container_manifest["hermeticity"][
                "system_packages_fully_pinned"
            ],
        }

    identity["identity_sha256"] = canonical_sha256(identity)
    return identity


def validate_identity(identity: Any, root: Path = ROOT) -> list[str]:
    errors: list[str] = []

    if not isinstance(identity, dict):
        return ["environment_identity must be an object"]

    allowed = {
        "schema",
        "version",
        "expected",
        "locks",
        "container",
        "identity_sha256",
    }
    extras = sorted(set(identity) - allowed)
    if extras:
        errors.append("non-canonical fields: " + ", ".join(extras))

    if identity.get("schema") != SCHEMA:
        errors.append("invalid environment_identity schema")
    if identity.get("version") != VERSION:
        errors.append("invalid environment_identity version")

    digest = identity.get("identity_sha256")
    if not isinstance(digest, str) or not SHA256_RX.match(digest):
        errors.append("missing/invalid identity_sha256")
    elif digest != canonical_sha256(identity):
        errors.append("identity_sha256 mismatch")

    try:
        expected = materialize_identity(root)
    except IdentityError as exc:
        errors.append(str(exc))
        return errors

    if identity != expected:
        errors.append(
            "environment_identity diverges from versioned REPRO sources"
        )
    return errors


def inject_manifest(
    manifest: dict[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise IdentityError("run manifest must be an object")
    if manifest.get("environment_identity_policy") == POLICY_GRANDFATHERED:
        raise IdentityError(
            "cannot inject future identity into a grandfathered historical manifest"
        )

    identity = materialize_identity(root)
    existing = manifest.get("environment_identity")
    if existing is not None and existing != identity:
        raise IdentityError(
            "existing environment_identity conflicts with current REPRO sources"
        )

    result = copy.deepcopy(manifest)
    result["environment_identity_policy"] = POLICY_REQUIRED
    result["environment_identity"] = identity
    return result


def validate_run_manifest(
    manifest: Any,
    root: Path = ROOT,
    grandfather_historical: bool = False,
) -> list[str]:
    if not isinstance(manifest, dict):
        return ["run manifest must be an object"]

    identity = manifest.get("environment_identity")
    policy = manifest.get("environment_identity_policy")

    if identity is None:
        if policy == POLICY_REQUIRED:
            return ["new/future run missing required environment_identity"]
        if grandfather_historical:
            return []
        return [
            "missing environment_identity; immutable history requires explicit "
            "--grandfather-historical"
        ]

    if policy != POLICY_REQUIRED:
        return ["run with environment_identity must declare policy REQUIRED"]

    return validate_identity(identity, root)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    fragment = sub.add_parser("fragment")
    fragment.add_argument("--output", type=Path)

    inject = sub.add_parser("inject")
    inject.add_argument("--manifest", type=Path, required=True)
    inject.add_argument("--output", type=Path, required=True)

    check_identity = sub.add_parser("check-identity")
    check_identity.add_argument("identity", type=Path)

    check_run = sub.add_parser("check-run")
    check_run.add_argument("manifest", type=Path)
    check_run.add_argument("--grandfather-historical", action="store_true")

    args = parser.parse_args()
    root = args.root.resolve()

    try:
        if args.command == "fragment":
            identity = materialize_identity(root)
            if args.output:
                _write_json(args.output, identity)
                print(args.output)
            else:
                print(
                    json.dumps(
                        identity, indent=2, sort_keys=True, ensure_ascii=False
                    )
                )
            return 0

        if args.command == "inject":
            result = inject_manifest(_read_json(args.manifest), root)
            _write_json(args.output, result)
            print(args.output)
            return 0

        if args.command == "check-identity":
            errors = validate_identity(_read_json(args.identity), root)
        else:
            errors = validate_run_manifest(
                _read_json(args.manifest),
                root,
                args.grandfather_historical,
            )

        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 2

        print("environment identity: OK")
        return 0

    except IdentityError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
