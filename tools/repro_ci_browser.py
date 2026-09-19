#!/usr/bin/env python3
"""Stable Playwright/Chromium setup and verification helper for future workflow reuse."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "poker-repro-ci-browser-helper/v1"
REPORT_SCHEMA = "poker-repro-ci-browser-report/v1"
SHA_RX = re.compile(r"^[0-9a-f]{64}$")


class BrowserHelperError(ValueError):
    pass


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BrowserHelperError(f"missing JSON source: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BrowserHelperError(f"JSON source must be an object: {path}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    lock_path = root / "reproducibility/browser-identity.lock.json"
    lock = _json(lock_path)
    env = _json(root / "reproducibility/environment.lock.json")
    if lock.get("schema") != "poker-engine-browser-identity/v1":
        raise BrowserHelperError("unexpected browser lock schema")

    pw = lock.get("playwright", {})
    browser = lock.get("browser", {})
    archive = lock.get("archive_identity", {})
    executable = lock.get("executable_identity", {})
    if pw.get("version") != env.get("playwright", {}).get("python_package_version"):
        raise BrowserHelperError("Playwright lock diverges from environment contract")
    if browser.get("version") != env.get("playwright", {}).get("chromium_version"):
        raise BrowserHelperError("Chromium lock diverges from environment contract")
    if browser.get("name") != "chromium":
        raise BrowserHelperError("only locked Chromium is supported")
    if archive.get("sha_pinned") is not False or archive.get("sha256") is not None:
        raise BrowserHelperError("archive SHA pin state diverges from verified #203 evidence")

    return {
        "schema": SCHEMA,
        "expected": {
            "playwright": pw["version"],
            "browser": browser["name"],
            "chromium": browser["version"],
            "revision": browser["revision"],
            "platform": browser["platform"],
            "executable_relative_path": executable["relative_path"],
        },
        "archive_sha_pinned": False,
        "lock_sha256": _sha(lock_path),
    }


def plan(root: Path = ROOT, *, with_system_deps: bool = True) -> dict[str, Any]:
    spec = contract(root)
    command = [sys.executable, "-m", "playwright", "install"]
    if with_system_deps:
        command.append("--with-deps")
    command.append("chromium")
    return {
        "schema": SCHEMA,
        "expected": spec["expected"],
        "archive_sha_pinned": spec["archive_sha_pinned"],
        "lock_sha256": spec["lock_sha256"],
        "commands": [command],
    }


def observe() -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        playwright_version = importlib.metadata.version("playwright")
    except Exception:
        return {
            "playwright": None,
            "chromium": None,
            "revision": None,
            "executable_path": None,
            "binary_sha256": None,
        }

    try:
        with sync_playwright() as pw:
            executable = Path(pw.chromium.executable_path)
        result = subprocess.run(
            [str(executable), "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        version_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", result.stdout)
        revision_match = re.search(r"chromium-(\d+)", executable.as_posix())
        return {
            "playwright": playwright_version,
            "chromium": version_match.group(1) if version_match else None,
            "revision": revision_match.group(1) if revision_match else None,
            "executable_path": executable.as_posix(),
            "binary_sha256": _sha(executable) if executable.is_file() else None,
        }
    except Exception:
        return {
            "playwright": playwright_version,
            "chromium": None,
            "revision": None,
            "executable_path": None,
            "binary_sha256": None,
        }


def verify(root: Path = ROOT, observation: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = contract(root)
    observed = observation if observation is not None else observe()
    expected = spec["expected"]
    violations: list[dict[str, Any]] = []

    for rule, key, expected_value in (
        ("PLAYWRIGHT_VERSION_MISMATCH", "playwright", expected["playwright"]),
        ("CHROMIUM_VERSION_MISMATCH", "chromium", expected["chromium"]),
        ("CHROMIUM_REVISION_MISMATCH", "revision", expected["revision"]),
    ):
        if observed.get(key) != expected_value:
            violations.append({"rule": rule, "expected": expected_value, "observed": observed.get(key)})

    path = observed.get("executable_path")
    if not isinstance(path, str) or not path.endswith(expected["executable_relative_path"]) or f"chromium-{expected['revision']}" not in path:
        violations.append({
            "rule": "CHROMIUM_EXECUTABLE_IDENTITY_MISMATCH",
            "expected": f"chromium-{expected['revision']}/.../{expected['executable_relative_path']}",
            "observed": path,
        })

    binary_sha = observed.get("binary_sha256")
    if not isinstance(binary_sha, str) or not SHA_RX.fullmatch(binary_sha):
        violations.append({"rule": "CHROMIUM_BINARY_SHA256_MISSING", "expected": "sha256", "observed": binary_sha})

    warnings = [{
        "rule": "BROWSER_ARCHIVE_SHA256_UNPINNED",
        "detail": "Playwright 1.55.0 upstream metadata does not provide an independently verified archive SHA-256; runtime binary SHA-256 is evidence, not an invented archive pin.",
    }]

    return {
        "schema": REPORT_SCHEMA,
        "status": "FAIL" if violations else "WARN",
        "expected": expected,
        "observed": observed,
        "archive_sha_pinned": False,
        "lock_sha256": spec["lock_sha256"],
        "violations": violations,
        "warnings": warnings,
    }


def install(
    root: Path = ROOT,
    *,
    with_system_deps: bool = True,
    run: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
) -> dict[str, Any]:
    root = root.resolve()
    p = plan(root, with_system_deps=with_system_deps)
    for command in p["commands"]:
        run(command, cwd=root, check=True)
    return verify(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    plan_p = sub.add_parser("plan")
    plan_p.add_argument("--without-system-deps", action="store_true")

    verify_p = sub.add_parser("verify")
    verify_p.add_argument("--observation", type=Path)

    install_p = sub.add_parser("install")
    install_p.add_argument("--without-system-deps", action="store_true")

    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "plan":
            value = plan(root, with_system_deps=not args.without_system_deps)
        elif args.command == "verify":
            observation = _json(args.observation) if args.observation else None
            value = verify(root, observation)
        else:
            value = install(root, with_system_deps=not args.without_system_deps)
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
        return 2 if value.get("status") == "FAIL" else 0
    except (BrowserHelperError, subprocess.CalledProcessError) as exc:
        print(json.dumps({
            "schema": REPORT_SCHEMA,
            "status": "FAIL",
            "violations": [{"rule": "HELPER_ERROR", "detail": str(exc)}],
        }, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
