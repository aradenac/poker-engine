#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

try:
    from tools import repro_hardening
except ImportError:
    import repro_hardening  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
LOCK_SCHEMA = "poker-engine-container-base/v1"
MANIFEST_SCHEMA = "poker-engine-science-container/v1"
DIGEST_RX = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA_RX = re.compile(r"^[0-9a-f]{64}$")


class ContainerContractError(ValueError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ContainerContractError(f"missing JSON source: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContainerContractError(f"invalid JSON source {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContainerContractError(f"JSON source must be an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    if not path.is_file():
        raise ContainerContractError(f"missing versioned source: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_payload_bytes(manifest: dict[str, Any]) -> bytes:
    payload = copy.deepcopy(manifest)
    payload.pop("manifest_sha256", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def manifest_sha256(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload_bytes(manifest)).hexdigest()


def _package_names(path: Path) -> list[str]:
    if not path.is_file():
        raise ContainerContractError(f"missing system package list: {path}")
    names = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not names:
        raise ContainerContractError("system package list must be non-empty")
    if len(names) != len(set(names)):
        raise ContainerContractError("system package list contains duplicates")
    if names != sorted(names):
        raise ContainerContractError("system package list must be sorted for deterministic review")
    for name in names:
        if any(ch.isspace() for ch in name):
            raise ContainerContractError(f"invalid system package token: {name!r}")
    return names


def validate_contract(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    env_path = root / "reproducibility/environment.lock.json"
    env = _read_json(env_path)
    if env.get("schema") != "poker-engine-repro-environment/v1":
        raise ContainerContractError("unexpected environment lock schema")

    container_cfg = env.get("container")
    if not isinstance(container_cfg, dict):
        raise ContainerContractError("environment lock missing container contract")
    for key in ("lock", "definition", "system_packages"):
        if not isinstance(container_cfg.get(key), str) or not container_cfg[key]:
            raise ContainerContractError(f"environment container contract missing {key}")

    lock_path = root / container_cfg["lock"]
    dockerfile_path = root / container_cfg["definition"]
    packages_path = root / container_cfg["system_packages"]

    lock = _read_json(lock_path)
    if lock.get("schema") != LOCK_SCHEMA:
        raise ContainerContractError("unexpected container base lock schema")
    if lock.get("definition") != container_cfg["definition"]:
        raise ContainerContractError("container definition path diverges between locks")
    if lock.get("system_packages") != container_cfg["system_packages"]:
        raise ContainerContractError("system package path diverges between locks")

    image = lock.get("image")
    if not isinstance(image, dict):
        raise ContainerContractError("container lock missing image object")

    repository = image.get("repository")
    tag = image.get("tag")
    digest = image.get("manifest_digest")
    index_digest = image.get("index_digest")
    platform = image.get("platform")

    if not isinstance(repository, str) or not repository or "@" in repository:
        raise ContainerContractError("base image repository must be a plain repository name")
    if not isinstance(tag, str) or not tag or tag.lower() == "latest":
        raise ContainerContractError("base image tag is required for provenance and must not be latest")
    if not isinstance(digest, str) or not DIGEST_RX.fullmatch(digest):
        raise ContainerContractError(
            "immutable base image manifest digest is required; tag-only references are forbidden"
        )
    if not isinstance(index_digest, str) or not DIGEST_RX.fullmatch(index_digest):
        raise ContainerContractError("base image index digest must be an immutable sha256 digest")
    if platform != "linux/amd64":
        raise ContainerContractError(f"container platform must be linux/amd64, got {platform!r}")

    verification = lock.get("verification")
    if not isinstance(verification, dict):
        raise ContainerContractError("base image digest requires explicit verification provenance")
    if verification.get("observed_manifest_digest") != digest:
        raise ContainerContractError("verified manifest digest does not match locked digest")
    if verification.get("observed_index_digest") != index_digest:
        raise ContainerContractError("verified index digest does not match locked index digest")
    if (
        not isinstance(verification.get("source_url"), str)
        or not verification["source_url"].startswith("https://")
    ):
        raise ContainerContractError("base image digest verification requires an https source_url")
    if not isinstance(verification.get("verified_at"), str) or not verification["verified_at"]:
        raise ContainerContractError("base image digest verification requires verified_at")

    os_lock = _read_json(root / env["os"]["spec"])
    image_os = image.get("os")
    if not isinstance(image_os, dict):
        raise ContainerContractError("container lock missing image OS identity")
    expected_arch = os_lock.get("machine")
    if image_os.get("id") != os_lock.get("distribution", {}).get("id"):
        raise ContainerContractError("container OS distribution diverges from OS lock")
    if image_os.get("version_id") != os_lock.get("distribution", {}).get("version_id"):
        raise ContainerContractError("container OS version diverges from OS lock")
    if image_os.get("architecture") != expected_arch:
        raise ContainerContractError("container architecture diverges from OS lock")
    if expected_arch != "x86_64":
        raise ContainerContractError("current container contract requires x86_64 OS identity")

    sources = lock.get("runtime_sources")
    if not isinstance(sources, dict):
        raise ContainerContractError("container lock missing runtime_sources")

    python_src = sources.get("python", {})
    node_src = sources.get("node", {})
    playwright = sources.get("playwright", {})

    if python_src.get("version") != env.get("python", {}).get("version"):
        raise ContainerContractError("container Python version diverges from environment lock")
    if node_src.get("version") != env.get("node", {}).get("version"):
        raise ContainerContractError("container Node version diverges from environment lock")
    if playwright.get("version") != env.get("playwright", {}).get("python_package_version"):
        raise ContainerContractError("container Playwright version diverges from environment lock")
    if playwright.get("browser") != env.get("playwright", {}).get("browser"):
        raise ContainerContractError("container browser name diverges from environment lock")
    if playwright.get("chromium_version") != env.get("playwright", {}).get("chromium_version"):
        raise ContainerContractError("container Chromium version diverges from environment lock")

    for label, src in (("python", python_src), ("node", node_src)):
        if not isinstance(src.get("url"), str) or not src["url"].startswith("https://"):
            raise ContainerContractError(f"{label} runtime source URL must be explicit https")
        if not isinstance(src.get("sha256"), str) or not SHA_RX.fullmatch(src["sha256"]):
            raise ContainerContractError(f"{label} runtime source requires a sha256 pin")

    packages = _package_names(packages_path)

    hermeticity = lock.get("hermeticity")
    if not isinstance(hermeticity, dict):
        raise ContainerContractError("container lock missing hermeticity declaration")
    if hermeticity.get("base_image_pinned") is not True:
        raise ContainerContractError("BASE_IMAGE_PINNED must be true")
    if hermeticity.get("system_packages_fully_pinned") is not False:
        raise ContainerContractError(
            "current contract must explicitly declare SYSTEM_PACKAGES_FULLY_PINNED=false"
        )
    if hermeticity.get("browser_archive_sha_pinned") is not False:
        raise ContainerContractError(
            "browser archive SHA must remain explicitly unpinned unless a verified hash is versioned"
        )
    if hermeticity.get("apt_snapshot_pinned") is not True:
        raise ContainerContractError("official apt snapshot identity must be pinned")
    try:
        hardening_identity = repro_hardening.expected_identity(root)
    except repro_hardening.HardeningError as exc:
        raise ContainerContractError(f"invalid REPRO hardening contract: {exc}") from exc

    if not dockerfile_path.is_file():
        raise ContainerContractError(f"missing container definition: {dockerfile_path}")
    dockerfile = dockerfile_path.read_text(encoding="utf-8")

    expected_from = f"FROM {repository}@{digest}"
    first_from = next(
        (line.strip() for line in dockerfile.splitlines() if line.strip().startswith("FROM ")),
        None,
    )
    if first_from != expected_from:
        raise ContainerContractError(
            f"Dockerfile must start from immutable locked digest: {expected_from}"
        )
    if re.search(r"(?im)^FROM\s+[^\s]+:latest(?:\s|$)", dockerfile):
        raise ContainerContractError("Dockerfile must not use latest")

    required_literals = (
        env["python"]["version"],
        python_src["sha256"],
        env["node"]["version"],
        node_src["sha256"],
        env["playwright"]["chromium_version"],
        digest,
    )
    for literal in required_literals:
        if str(literal) not in dockerfile:
            raise ContainerContractError(f"Dockerfile missing locked literal: {literal}")

    return {
        "root": root,
        "env": env,
        "lock": lock,
        "lock_path": lock_path,
        "dockerfile_path": dockerfile_path,
        "packages_path": packages_path,
        "packages": packages,
        "hardening_identity": hardening_identity,
    }


def materialize_manifest(root: Path = ROOT) -> dict[str, Any]:
    data = validate_contract(root)
    root = data["root"]
    env = data["env"]
    lock = data["lock"]
    image = lock["image"]

    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "base_image": {
            "repository": image["repository"],
            "tag": image["tag"],
            "platform": image["platform"],
            "manifest_digest": image["manifest_digest"],
            "index_digest": image["index_digest"],
            "os": image["os"],
            "verification": lock["verification"],
        },
        "definition": {
            "path": data["dockerfile_path"].relative_to(root).as_posix(),
            "sha256": sha256_file(data["dockerfile_path"]),
        },
        "locks": {
            "container_base_lock_sha256": sha256_file(data["lock_path"]),
            "system_packages_sha256": sha256_file(data["packages_path"]),
            "environment_lock_sha256": sha256_file(
                root / "reproducibility/environment.lock.json"
            ),
            "requirements_lock_sha256": sha256_file(
                root / env["python"]["requirements"]
            ),
            "package_lock_sha256": sha256_file(root / env["node"]["package_lock"]),
            "apt_snapshot_lock_sha256": sha256_file(root / env["container"]["apt_snapshot"]),
            "system_packages_resolution_lock_sha256": sha256_file(root / env["container"]["system_packages_resolution"]),
            "browser_identity_lock_sha256": sha256_file(root / env["container"]["browser_identity"]),
            "apt_sources_sha256": sha256_file(root / "reproducibility/ubuntu-snapshot.sources"),
        },
        "expected_runtime": {
            "python": env["python"]["version"],
            "node": env["node"]["version"],
            "playwright": env["playwright"]["python_package_version"],
            "browser": env["playwright"]["browser"],
            "chromium": env["playwright"]["chromium_version"],
        },
        "system_packages": {
            "path": data["packages_path"].relative_to(root).as_posix(),
            "count": len(data["packages"]),
            "fully_pinned": data["hardening_identity"]["apt_snapshot_identity"]["fully_pinned"],
            "pinning_level": data["hardening_identity"]["system_packages_pinning_level"],
            "apt_snapshot_identity": data["hardening_identity"]["apt_snapshot_identity"],
        },
        "browser": {
            "archive_identity": data["hardening_identity"]["browser_archive_identity"],
            "binary_identity": data["hardening_identity"]["browser_binary_identity"],
        },
        "hermeticity": {
            "level": data["hardening_identity"]["hermeticity_level"],
            "base_image_pinned": lock["hermeticity"]["base_image_pinned"],
            "system_packages_fully_pinned": data["hardening_identity"]["apt_snapshot_identity"]["fully_pinned"],
            "browser_archive_sha_pinned": data["hardening_identity"]["browser_archive_identity"]["sha_pinned"],
        },
    }
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    return manifest


def write_manifest(root: Path, directory: Path) -> Path:
    manifest = materialize_manifest(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"container-manifest-{manifest['manifest_sha256']}.json"
    content = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise ContainerContractError(f"content-address collision at {path}")
    path.write_text(content, encoding="utf-8")
    return path


def _docker() -> str:
    binary = shutil.which("docker")
    if not binary:
        raise ContainerContractError(
            "docker executable is required for build/inspect/verify"
        )
    return binary


def _default_image(manifest: dict[str, Any]) -> str:
    return f"poker-engine-science:{manifest['manifest_sha256'][:16]}"


def build_image(root: Path = ROOT, image: str | None = None) -> str:
    manifest = materialize_manifest(root)
    data = validate_contract(root)
    tag = image or _default_image(manifest)

    labels = {
        "org.poker-engine.repro.manifest-sha256": manifest["manifest_sha256"],
        "org.poker-engine.repro.container-definition-sha256": manifest["definition"][
            "sha256"
        ],
        "org.poker-engine.repro.container-lock-sha256": manifest["locks"][
            "container_base_lock_sha256"
        ],
        "org.poker-engine.repro.base-image-digest": manifest["base_image"][
            "manifest_digest"
        ],
        "org.poker-engine.repro.hermeticity": manifest["hermeticity"]["level"],
    }

    command = [
        _docker(),
        "build",
        "--platform",
        manifest["base_image"]["platform"],
        "-f",
        str(data["dockerfile_path"]),
        "-t",
        tag,
    ]
    for key in sorted(labels):
        command.extend(["--label", f"{key}={labels[key]}"])
    command.append(str(root))
    subprocess.run(command, check=True)
    return tag


def inspect_image(image: str) -> dict[str, Any]:
    result = subprocess.run(
        [_docker(), "image", "inspect", image],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    if (
        not isinstance(payload, list)
        or len(payload) != 1
        or not isinstance(payload[0], dict)
    ):
        raise ContainerContractError("unexpected docker image inspect output")

    item = payload[0]
    return {
        "image": image,
        "id": item.get("Id"),
        "os": item.get("Os"),
        "architecture": item.get("Architecture"),
        "labels": (item.get("Config") or {}).get("Labels") or {},
    }


def verify_image(image: str, root: Path = ROOT) -> list[str]:
    manifest = materialize_manifest(root)
    observed = inspect_image(image)
    errors: list[str] = []

    if observed.get("os") != "linux":
        errors.append(f"image OS mismatch: {observed.get('os')!r}")
    if observed.get("architecture") != "amd64":
        errors.append(
            f"image architecture mismatch: {observed.get('architecture')!r}"
        )

    labels = observed.get("labels", {})
    expected_labels = {
        "org.poker-engine.repro.manifest-sha256": manifest["manifest_sha256"],
        "org.poker-engine.repro.container-definition-sha256": manifest["definition"][
            "sha256"
        ],
        "org.poker-engine.repro.container-lock-sha256": manifest["locks"][
            "container_base_lock_sha256"
        ],
        "org.poker-engine.repro.base-image-digest": manifest["base_image"][
            "manifest_digest"
        ],
        "org.poker-engine.repro.hermeticity": manifest["hermeticity"]["level"],
    }

    for key, expected in expected_labels.items():
        if labels.get(key) != expected:
            errors.append(
                f"image label mismatch {key}: expected {expected!r}, "
                f"got {labels.get(key)!r}"
            )

    if errors:
        return errors

    process = subprocess.run(
        [
            _docker(),
            "run",
            "--rm",
            "--platform",
            manifest["base_image"]["platform"],
            image,
            "python3",
            "tools/repro_environment.py",
            "--verify-runtime",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        detail = (process.stderr or process.stdout).strip()
        errors.append(f"container runtime verification failed: {detail}")

    hardening = subprocess.run(
        [
            _docker(),
            "run",
            "--rm",
            "--platform",
            manifest["base_image"]["platform"],
            image,
            "python3",
            "tools/repro_hardening.py",
            "verify",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if hardening.returncode != 0:
        detail = (hardening.stderr or hardening.stdout).strip()
        errors.append(f"container hardening verification failed: {detail}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build and verify the locked scientific reference container."
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate")

    manifest_p = sub.add_parser("manifest")
    manifest_p.add_argument("--output-dir", type=Path)
    manifest_p.add_argument("--json", action="store_true")

    build_p = sub.add_parser("build")
    build_p.add_argument("--image")

    inspect_p = sub.add_parser("inspect")
    inspect_p.add_argument("--image", required=True)

    verify_p = sub.add_parser("verify")
    verify_p.add_argument("--image", required=True)

    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        if args.command == "validate":
            manifest = materialize_manifest(root)
            print(
                f"container contract: OK "
                f"{manifest['base_image']['manifest_digest']} "
                f"{manifest['base_image']['platform']}"
            )
            print(f"hermeticity: {manifest['hermeticity']['level']}")
            return 0

        if args.command == "manifest":
            manifest = materialize_manifest(root)
            if args.output_dir:
                print(write_manifest(root, args.output_dir))
            if args.json or not args.output_dir:
                print(
                    json.dumps(
                        manifest, indent=2, sort_keys=True, ensure_ascii=False
                    )
                )
            return 0

        if args.command == "build":
            print(build_image(root, args.image))
            return 0

        if args.command == "inspect":
            print(
                json.dumps(
                    inspect_image(args.image),
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                )
            )
            return 0

        errors = verify_image(args.image, root)
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 2
        print("container identity: OK")
        return 0

    except (
        ContainerContractError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
