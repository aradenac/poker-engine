#!/usr/bin/env python3
"""Validate and capture the reproducible runtime contract for issue #203."""

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
LOCK_PATH = ROOT / "reproducibility" / "environment.lock.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalized_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def lock_sha256(path: Path = LOCK_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        errors.append("requirements.lock.txt does not pin the Playwright version from the environment lock")
    for line in locked:
        if "==" not in line or line.count("==") != 1:
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
        errors.append("phase-1 branch must keep phase=1")
    if lock.get("scope", {}).get("workflows_wired") is not False:
        errors.append("phase 1 must not claim workflows are wired")

    return errors


def _command_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
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

    observed = {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "node": node_version,
        "playwright": observed_playwright,
        "chromium": chromium_version,
        "platform": platform.platform(),
    }
    expected = {
        "python": lock["python"]["version"],
        "node": lock["node"]["version"],
        "playwright": lock["playwright"]["python_package_version"],
        "chromium": lock["playwright"]["chromium_version"],
    }
    matches = {key: observed.get(key) == value for key, value in expected.items()}
    return {
        "schema": "poker-engine-runtime-environment/v1",
        "contract_schema": lock["schema"],
        "contract_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        "expected": expected,
        "observed": observed,
        "matches": matches,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-contract", action="store_true")
    parser.add_argument("--verify-runtime", action="store_true")
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()

    if not (args.check_contract or args.verify_runtime or args.manifest):
        parser.error("choose --check-contract, --verify-runtime and/or --manifest")

    if args.check_contract:
        errors = validate_contract()
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print("reproducibility contract: OK")

    manifest: dict[str, Any] | None = None
    if args.verify_runtime or args.manifest:
        manifest = collect_manifest()

    if args.verify_runtime and manifest is not None:
        mismatches = [key for key, ok in manifest["matches"].items() if not ok]
        if mismatches:
            print("runtime mismatch: " + ", ".join(mismatches), file=sys.stderr)
            return 2
        print("runtime identity: OK")

    if args.manifest and manifest is not None:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(args.manifest)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
