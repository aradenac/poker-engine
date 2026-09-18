#!/usr/bin/env python3
"""Validate, verify and fingerprint the reproducible runtime contract for issue #203."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_SCHEMA = "poker-engine-runtime-environment/v2"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalized_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_payload_bytes(manifest: dict[str, Any]) -> bytes:
    payload = dict(manifest)
    payload.pop("payload_sha256", None)
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def payload_sha256(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload_bytes(manifest)).hexdigest()


def attach_payload_sha256(manifest: dict[str, Any]) -> dict[str, Any]:
    result = dict(manifest)
    result["payload_sha256"] = payload_sha256(result)
    return result


def verify_content_address(manifest: dict[str, Any]) -> bool:
    digest = manifest.get("payload_sha256")
    return isinstance(digest, str) and digest == payload_sha256(manifest)


def _read_os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        key, value = raw.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def expected_runtime(root: Path = ROOT) -> dict[str, Any]:
    lock = _read_json(root / "reproducibility" / "environment.lock.json")
    os_lock = _read_json(root / lock["os"]["spec"])
    return {
        "python": lock["python"]["version"],
        "node": lock["node"]["version"],
        "playwright": lock["playwright"]["python_package_version"],
        "chromium": lock["playwright"]["chromium_version"],
        "os": {
            "platform": os_lock["platform"],
            "id": os_lock["distribution"]["id"],
            "version_id": os_lock["distribution"]["version_id"],
            "machine": os_lock["machine"],
        },
    }


def validate_contract(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    lock_path = root / "reproducibility" / "environment.lock.json"
    lock = _read_json(lock_path)

    python_version = (root / ".python-version").read_text(encoding="utf-8").strip()
    node_version = (root / ".node-version").read_text(encoding="utf-8").strip()
    if python_version != lock["python"]["version"]:
        errors.append(".python-version differs from environment.lock.json")
    if node_version != lock["node"]["version"]:
        errors.append(".node-version differs from environment.lock.json")

    direct = set(_normalized_lines(root / "requirements.in"))
    locked = set(_normalized_lines(root / "requirements.lock.txt"))
    expected_playwright = f'playwright=={lock["playwright"]["python_package_version"]}'
    if direct != {expected_playwright}:
        errors.append("requirements.in must contain only the pinned Playwright direct dependency")
    if expected_playwright not in locked:
        errors.append("requirements.lock.txt does not pin Playwright from environment.lock.json")
    for line in locked:
        if line.count("==") != 1:
            errors.append(f"unlocked Python dependency: {line}")

    package = _read_json(root / "package.json")
    package_lock = _read_json(root / "package-lock.json")
    if package.get("engines", {}).get("node") != node_version:
        errors.append("package.json Node engine differs from .node-version")
    lock_engine = package_lock.get("packages", {}).get("", {}).get("engines", {}).get("node")
    if lock_engine != node_version:
        errors.append("package-lock.json Node engine differs from .node-version")
    if package_lock.get("lockfileVersion") != 3:
        errors.append("package-lock.json must use lockfileVersion 3")

    if lock.get("schema") != "poker-engine-repro-environment/v1":
        errors.append("unexpected environment lock schema")
    if lock.get("phase") != 1:
        errors.append("local REPRO tranche must keep phase=1")
    if lock.get("scope", {}).get("workflows_wired") is not False:
        errors.append("local REPRO tranche must not claim workflows are wired")
    if lock.get("scope", {}).get("os_base_pinned") is not True:
        errors.append("OS base identity must be pinned")
    if lock.get("manifest", {}).get("schema") != MANIFEST_SCHEMA:
        errors.append("unexpected runtime manifest schema")
    if lock.get("manifest", {}).get("content_addressed") is not True:
        errors.append("runtime manifests must be content-addressed")

    os_spec = lock.get("os", {}).get("spec")
    if not os_spec or not (root / os_spec).exists():
        errors.append("missing pinned OS base specification")
    else:
        os_lock = _read_json(root / os_spec)
        if os_lock.get("schema") != "poker-engine-os-base/v1":
            errors.append("unexpected OS base schema")
        if os_lock.get("platform") != "linux":
            errors.append("OS base platform must be linux")
        if os_lock.get("distribution", {}).get("id") != lock["os"]["id"]:
            errors.append("OS distribution differs between locks")
        if os_lock.get("distribution", {}).get("version_id") != lock["os"]["version_id"]:
            errors.append("OS version differs between locks")
        if os_lock.get("machine") != lock["os"]["machine"]:
            errors.append("OS machine differs between locks")

    return errors


def _command_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=10
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    text = (result.stdout or result.stderr).strip()
    return text or None


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _numeric_version(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(r"\b(\d+\.\d+\.\d+\.\d+)\b", text)
    return match.group(1) if match else None


def collect_manifest(root: Path = ROOT) -> dict[str, Any]:
    lock_path = root / "reproducibility" / "environment.lock.json"
    lock = _read_json(lock_path)
    expected = expected_runtime(root)

    node_text = _command_version(["node", "--version"])
    node_version = node_text[1:] if node_text and node_text.startswith("v") else node_text

    observed_playwright = _package_version("playwright")
    chromium_version: str | None = None
    if observed_playwright:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore

            with sync_playwright() as playwright:
                chromium_text = _command_version([playwright.chromium.executable_path, "--version"])
                chromium_version = _numeric_version(chromium_text)
        except Exception:
            chromium_version = None

    os_release = _read_os_release()
    observed = {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "node": node_version,
        "playwright": observed_playwright,
        "chromium": chromium_version,
        "os": {
            "platform": sys.platform,
            "id": os_release.get("ID"),
            "version_id": os_release.get("VERSION_ID"),
            "machine": platform.machine(),
        },
    }
    matches = {
        "python": observed["python"] == expected["python"],
        "node": observed["node"] == expected["node"],
        "playwright": observed["playwright"] == expected["playwright"],
        "chromium": observed["chromium"] == expected["chromium"],
        "os": observed["os"] == expected["os"],
    }
    files = {
        "environment_lock_sha256": sha256_file(lock_path),
        "os_base_lock_sha256": sha256_file(root / lock["os"]["spec"]),
        "python_lock_sha256": sha256_file(root / lock["python"]["requirements"]),
        "node_lock_sha256": sha256_file(root / lock["node"]["package_lock"]),
    }
    return attach_payload_sha256({
        "schema": MANIFEST_SCHEMA,
        "contract_schema": lock["schema"],
        "expected": expected,
        "observed": observed,
        "matches": matches,
        "files": files,
    })


def runtime_mismatches(manifest: dict[str, Any]) -> list[str]:
    if not verify_content_address(manifest):
        return ["manifest_content_address"]
    return [key for key, ok in manifest.get("matches", {}).items() if ok is not True]


def write_content_addressed_manifest(manifest: dict[str, Any], directory: Path) -> Path:
    finalized = attach_payload_sha256(manifest)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'environment-manifest-{finalized["payload_sha256"]}.json'
    content = json.dumps(finalized, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise RuntimeError(f"content-address collision at {path}")
    path.write_text(content, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-contract", action="store_true")
    parser.add_argument("--verify-runtime", action="store_true")
    parser.add_argument("--manifest", type=Path, help="legacy explicit manifest path")
    parser.add_argument("--manifest-dir", type=Path, help="write a content-addressed manifest")
    args = parser.parse_args()

    if not (args.check_contract or args.verify_runtime or args.manifest or args.manifest_dir):
        parser.error("choose --check-contract, --verify-runtime, --manifest and/or --manifest-dir")

    if args.check_contract:
        errors = validate_contract()
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print("reproducibility contract: OK")

    manifest: dict[str, Any] | None = None
    if args.verify_runtime or args.manifest or args.manifest_dir:
        manifest = collect_manifest()

    if args.verify_runtime and manifest is not None:
        mismatches = runtime_mismatches(manifest)
        if mismatches:
            print("runtime mismatch: " + ", ".join(mismatches), file=sys.stderr)
            return 2
        print("runtime identity: OK")

    if args.manifest and manifest is not None:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(args.manifest)

    if args.manifest_dir and manifest is not None:
        print(write_content_addressed_manifest(manifest, args.manifest_dir))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
