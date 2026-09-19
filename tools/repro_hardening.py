#!/usr/bin/env python3
"""Non-CI reproducibility hardening for apt snapshots and Playwright Chromium identity."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
from typing import Any

try:
    from tools import repro_environment
except ImportError:
    import repro_environment  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_SCHEMA = "poker-engine-apt-snapshot/v1"
RESOLUTION_SCHEMA = "poker-engine-system-packages-resolution/v1"
BROWSER_SCHEMA = "poker-engine-browser-identity/v1"
VERIFY_SCHEMA = "poker-repro-hardening-verification/v1"
SNAPSHOT_RX = re.compile(r"^\d{8}T\d{6}Z$")
SHA256_RX = re.compile(r"^[0-9a-f]{64}$")


class HardeningError(ValueError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise HardeningError(f"missing JSON source: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HardeningError(f"invalid JSON source {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise HardeningError(f"JSON source must be an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    if not path.is_file():
        raise HardeningError(f"missing versioned source: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package_names(path: Path) -> list[str]:
    if not path.is_file():
        raise HardeningError(f"missing system package list: {path}")
    result = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if result != sorted(result):
        raise HardeningError("system package list must remain sorted")
    if len(result) != len(set(result)):
        raise HardeningError("system package list contains duplicates")
    return result


def derive_hermeticity(
    *,
    base_image_pinned: bool,
    system_packages_fully_pinned: bool,
    browser_archive_sha_pinned: bool,
) -> str:
    if not base_image_pinned:
        return "PARTIAL"
    if system_packages_fully_pinned and browser_archive_sha_pinned:
        return "BASE_SYSTEM_BROWSER_PINNED"
    if system_packages_fully_pinned:
        return "BASE_AND_SYSTEM_PACKAGES_PINNED"
    return "BASE_IMAGE_PINNED"


def load_contract(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    env = _read_json(root / "reproducibility/environment.lock.json")
    if env.get("schema") != "poker-engine-repro-environment/v1":
        raise HardeningError("unexpected environment lock schema")
    container = env.get("container")
    if not isinstance(container, dict):
        raise HardeningError("environment lock missing container section")

    refs = {
        "apt_snapshot": "reproducibility/apt-snapshot.lock.json",
        "system_packages_resolution": "reproducibility/system-packages.resolution.lock.json",
        "browser_identity": "reproducibility/browser-identity.lock.json",
        "system_packages": "reproducibility/system-packages.apt.txt",
    }
    for key, expected in refs.items():
        if container.get(key) != expected:
            raise HardeningError(f"environment container {key} must be {expected!r}")

    snapshot_path = root / container["apt_snapshot"]
    resolution_path = root / container["system_packages_resolution"]
    browser_path = root / container["browser_identity"]
    packages_path = root / container["system_packages"]
    snapshot = _read_json(snapshot_path)
    resolution = _read_json(resolution_path)
    browser = _read_json(browser_path)
    packages = _package_names(packages_path)

    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise HardeningError("unexpected apt snapshot lock schema")
    snapshot_id = snapshot.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not SNAPSHOT_RX.fullmatch(snapshot_id):
        raise HardeningError("invalid apt snapshot id")
    service = snapshot.get("snapshot_service")
    if not isinstance(service, dict):
        raise HardeningError("missing apt snapshot provenance")
    if service.get("url") != "https://snapshot.ubuntu.com/":
        raise HardeningError("unexpected Ubuntu snapshot service")
    if service.get("verification_status") != "OFFICIAL_DOCUMENTED_TIME_ADDRESSABLE_SERVICE":
        raise HardeningError("apt snapshot provenance is not verified")
    if snapshot.get("platform") != {
        "os_id": "ubuntu",
        "version_id": "24.04",
        "codename": "noble",
        "architecture": "amd64",
    }:
        raise HardeningError("apt snapshot platform mismatch")

    sources = snapshot.get("sources")
    if not isinstance(sources, dict):
        raise HardeningError("apt snapshot sources identity missing")
    sources_path = root / str(sources.get("path", ""))
    expected_sources_sha = sources.get("sha256")
    if not isinstance(expected_sources_sha, str) or not SHA256_RX.fullmatch(expected_sources_sha):
        raise HardeningError("apt snapshot sources sha256 missing/invalid")
    if sha256_file(sources_path) != expected_sources_sha:
        raise HardeningError("apt snapshot source file sha256 mismatch")
    source_text = sources_path.read_text(encoding="utf-8")
    if f"Snapshot: {snapshot_id}" not in source_text:
        raise HardeningError("apt snapshot source file does not pin snapshot id")

    package_resolution = snapshot.get("package_resolution")
    if not isinstance(package_resolution, dict):
        raise HardeningError("apt snapshot package resolution contract missing")
    if package_resolution.get("lock") != container["system_packages_resolution"]:
        raise HardeningError("apt snapshot resolution lock path mismatch")
    if package_resolution.get("fully_pinned") is not False:
        raise HardeningError("current package contract must not claim fully_pinned=true")

    if resolution.get("schema") != RESOLUTION_SCHEMA:
        raise HardeningError("unexpected system package resolution schema")
    if resolution.get("snapshot_id") != snapshot_id:
        raise HardeningError("system package resolution snapshot mismatch")
    if resolution.get("architecture") != "amd64":
        raise HardeningError("system package resolution architecture mismatch")
    if resolution.get("fully_pinned") is not False:
        raise HardeningError("system package resolution must remain not fully pinned")
    entries = resolution.get("entries")
    if not isinstance(entries, list):
        raise HardeningError("system package resolution entries missing")
    by_name: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise HardeningError("invalid system package resolution entry")
        name = entry.get("requested_package")
        if not isinstance(name, str) or not name or name in by_name:
            raise HardeningError("invalid/duplicate system package resolution entry")
        if entry.get("resolved_version") is not None:
            raise HardeningError("resolved_version must remain null until a real resolver observation is persisted")
        if entry.get("snapshot_status") != f"PINNED_{snapshot_id}":
            raise HardeningError(f"system package snapshot status mismatch: {name}")
        if entry.get("verification_status") != "RESOLVE_AND_COMPARE_AT_BUILD_OR_VERIFY":
            raise HardeningError(f"system package verification status mismatch: {name}")
        by_name[name] = entry
    if sorted(by_name) != packages:
        raise HardeningError("system package resolution entries diverge from requested package list")

    if browser.get("schema") != BROWSER_SCHEMA:
        raise HardeningError("unexpected browser identity lock schema")
    pw = browser.get("playwright")
    br = browser.get("browser")
    archive = browser.get("archive_identity")
    executable = browser.get("executable_identity")
    provenance = browser.get("provenance")
    for label, value in (
        ("playwright", pw), ("browser", br), ("archive_identity", archive),
        ("executable_identity", executable), ("provenance", provenance),
    ):
        if not isinstance(value, dict):
            raise HardeningError(f"browser lock missing {label}")
    if pw.get("version") != env.get("playwright", {}).get("python_package_version"):
        raise HardeningError("Playwright version diverges from environment lock")
    if br.get("name") != env.get("playwright", {}).get("browser"):
        raise HardeningError("browser name diverges from environment lock")
    if br.get("version") != env.get("playwright", {}).get("chromium_version"):
        raise HardeningError("Chromium version diverges from environment lock")
    if br.get("revision") != "1187":
        raise HardeningError("Playwright 1.55.0 Chromium revision must be 1187")
    if br.get("platform") != "ubuntu24.04-x64" or br.get("architecture") != "x86_64":
        raise HardeningError("browser platform/architecture mismatch")
    if archive.get("sha_pinned") is not False or archive.get("sha256") is not None:
        raise HardeningError("browser archive hash must not be claimed pinned without a verified real SHA-256")
    urls = archive.get("source_urls")
    if not isinstance(urls, list) or not urls or any(
        not isinstance(url, str) or not url.startswith("https://") for url in urls
    ):
        raise HardeningError("browser archive source URLs missing/invalid")
    if archive.get("verification_status") != "NO_OFFICIAL_ARCHIVE_SHA256_IN_PLAYWRIGHT_1_55_0_METADATA":
        raise HardeningError("browser archive verification status mismatch")
    if executable.get("expected_version") != br.get("version"):
        raise HardeningError("browser executable expected version mismatch")
    expected_binary_sha = executable.get("expected_sha256")
    if expected_binary_sha is None:
        if executable.get("sha_pinned") is not False:
            raise HardeningError("browser executable sha_pinned must be false without expected hash")
    elif not isinstance(expected_binary_sha, str) or not SHA256_RX.fullmatch(expected_binary_sha):
        raise HardeningError("browser executable expected_sha256 invalid")
    if provenance.get("browsers_json_git_blob_sha") != "169663e8ee3ba2e79091cd9332740b2599865fce":
        raise HardeningError("Playwright browsers.json provenance blob mismatch")

    base_lock = _read_json(root / container["lock"])
    base_h = base_lock.get("hermeticity")
    if not isinstance(base_h, dict) or base_h.get("base_image_pinned") is not True:
        raise HardeningError("base image must remain pinned")
    level = derive_hermeticity(
        base_image_pinned=True,
        system_packages_fully_pinned=bool(resolution["fully_pinned"]),
        browser_archive_sha_pinned=bool(archive["sha_pinned"]),
    )
    return {
        "root": root, "env": env, "container": container,
        "snapshot": snapshot, "snapshot_path": snapshot_path,
        "resolution": resolution, "resolution_path": resolution_path,
        "browser": browser, "browser_path": browser_path,
        "packages_path": packages_path, "packages": packages,
        "sources_path": sources_path, "hermeticity_level": level,
    }


def expected_identity(root: Path = ROOT) -> dict[str, Any]:
    data = load_contract(root)
    snapshot = data["snapshot"]
    resolution = data["resolution"]
    browser = data["browser"]
    executable = browser["executable_identity"]
    return {
        "system_packages_pinning_level": resolution["pinning_level"],
        "apt_snapshot_identity": {
            "snapshot_id": snapshot["snapshot_id"],
            "service": snapshot["snapshot_service"]["url"],
            "architecture": snapshot["platform"]["architecture"],
            "sources_path": snapshot["sources"]["path"],
            "sources_sha256": snapshot["sources"]["sha256"],
            "lock_sha256": sha256_file(data["snapshot_path"]),
            "resolution_lock_sha256": sha256_file(data["resolution_path"]),
            "fully_pinned": resolution["fully_pinned"],
        },
        "browser_archive_identity": {
            "playwright": browser["playwright"]["version"],
            "browser": browser["browser"]["name"],
            "version": browser["browser"]["version"],
            "revision": browser["browser"]["revision"],
            "platform": browser["browser"]["platform"],
            "architecture": browser["browser"]["architecture"],
            "path_template": browser["archive_identity"]["path_template"],
            "sha256": browser["archive_identity"]["sha256"],
            "sha_pinned": browser["archive_identity"]["sha_pinned"],
            "verification_status": browser["archive_identity"]["verification_status"],
            "lock_sha256": sha256_file(data["browser_path"]),
        },
        "browser_binary_identity": {
            "relative_path": executable["relative_path"],
            "expected_version": executable["expected_version"],
            "expected_sha256": executable["expected_sha256"],
            "sha_pinned": executable["sha_pinned"],
            "verification_status": executable["verification_status"],
        },
        "hermeticity_level": data["hermeticity_level"],
    }


def _run(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=20)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip()


def _candidate_resolution(name: str, snapshot_id: str) -> dict[str, Any]:
    output = _run(["apt-cache", "policy", name])
    if not output:
        return {"candidate_version": None, "candidate_source_verified": False}
    match = re.search(r"(?m)^\s*Candidate:\s*(\S+)\s*$", output)
    candidate = None if not match or match.group(1) == "(none)" else match.group(1)
    expected_source = f"snapshot.ubuntu.com/ubuntu/{snapshot_id}"
    return {
        "candidate_version": candidate,
        "candidate_source_verified": expected_source in output,
    }


def _installed_package(name: str, snapshot_id: str) -> dict[str, Any] | None:
    fmt = "-f=" + "$" + "{Status}\\t$" + "{Version}\\t$" + "{Architecture}\\n"
    output = _run(["dpkg-query", "-W", fmt, name])
    if not output:
        return None
    parts = output.split("\t")
    if len(parts) != 3 or parts[0] != "install ok installed":
        return None
    resolution = _candidate_resolution(name, snapshot_id)
    return {
        "installed_version": parts[1],
        "architecture": parts[2],
        **resolution,
    }


def _snapshot_from_runtime() -> str | None:
    path = Path("/etc/apt/apt.conf.d/50poker-engine-snapshot")
    if not path.is_file():
        return None
    match = re.search(r'APT::Snapshot\s+"([^"]+)"\s*;', path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _browser_observation() -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        return {"playwright_version": None, "version": None, "revision": None,
                "executable_path": None, "binary_sha256": None, "archive_sha256": None}
    try:
        playwright_version = importlib.metadata.version("playwright")
    except importlib.metadata.PackageNotFoundError:
        playwright_version = None
    try:
        with sync_playwright() as pw:
            executable = Path(pw.chromium.executable_path)
        version_output = _run([str(executable), "--version"])
        version_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", version_output or "")
        revision_match = re.search(r"chromium-(\d+)", executable.as_posix())
        return {
            "playwright_version": playwright_version,
            "version": version_match.group(1) if version_match else None,
            "revision": revision_match.group(1) if revision_match else None,
            "executable_path": executable.as_posix(),
            "binary_sha256": sha256_file(executable) if executable.is_file() else None,
            "archive_sha256": None,
        }
    except Exception:
        return {"playwright_version": playwright_version, "version": None, "revision": None,
                "executable_path": None, "binary_sha256": None, "archive_sha256": None}


def collect_observation(root: Path = ROOT) -> dict[str, Any]:
    data = load_contract(root)
    runtime_sources = Path("/etc/apt/sources.list.d/ubuntu.sources")
    source_sha = sha256_file(runtime_sources) if runtime_sources.is_file() else None
    return {
        "architecture": _run(["dpkg", "--print-architecture"]),
        "snapshot_id": _snapshot_from_runtime(),
        "sources_sha256": source_sha,
        "packages": {
            name: _installed_package(name, data["snapshot"]["snapshot_id"])
            for name in data["packages"]
        },
        "browser": _browser_observation(),
        "core_runtime": repro_environment.collect_manifest(root),
        "base_image_digest": None,
        "base_image_note": "Base image digest is verified externally by repro_container image labels.",
    }


def _package_violations(expected: dict[str, Any], observation: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    data = load_contract(root)
    violations: list[dict[str, Any]] = []
    apt = expected["apt_snapshot_identity"]
    if observation.get("snapshot_id") != apt["snapshot_id"]:
        violations.append({"rule": "APT_SNAPSHOT_MISMATCH", "expected": apt["snapshot_id"], "observed": observation.get("snapshot_id")})
    if observation.get("sources_sha256") != apt["sources_sha256"]:
        violations.append({"rule": "APT_SOURCE_MISMATCH", "expected": apt["sources_sha256"], "observed": observation.get("sources_sha256")})
    if observation.get("architecture") != apt["architecture"]:
        violations.append({"rule": "APT_ARCHITECTURE_MISMATCH", "expected": apt["architecture"], "observed": observation.get("architecture")})
    observed_packages = observation.get("packages")
    if not isinstance(observed_packages, dict):
        return violations + [{"rule": "PACKAGE_OBSERVATION_MISSING", "expected": len(data["packages"]), "observed": None}]
    locked = {row["requested_package"]: row for row in data["resolution"]["entries"]}
    for name in data["packages"]:
        actual = observed_packages.get(name)
        if not isinstance(actual, dict) or not actual.get("installed_version"):
            violations.append({"rule": "PACKAGE_MISSING", "package": name, "expected": "installed", "observed": None})
            continue
        installed = actual["installed_version"]
        candidate = actual.get("candidate_version")
        source_verified = actual.get("candidate_source_verified")
        architecture = actual.get("architecture")
        if architecture not in ("amd64", "all"):
            violations.append({"rule": "PACKAGE_ARCHITECTURE_MISMATCH", "package": name, "expected": "amd64|all", "observed": architecture})
        if not isinstance(candidate, str) or not candidate:
            violations.append({"rule": "PACKAGE_RESOLUTION_MISSING", "package": name, "expected": "snapshot candidate", "observed": candidate})
        elif installed != candidate:
            violations.append({"rule": "PACKAGE_RESOLUTION_DIFFERENT", "package": name, "expected": candidate, "observed": installed})
        if source_verified is not True:
            violations.append({
                "rule": "PACKAGE_REPOSITORY_SNAPSHOT_UNEXPECTED",
                "package": name,
                "expected": f"snapshot.ubuntu.com/ubuntu/{apt['snapshot_id']}",
                "observed": source_verified,
            })
        locked_version = locked[name].get("resolved_version")
        if locked_version is not None and installed != locked_version:
            violations.append({"rule": "PACKAGE_VERSION_MISMATCH", "package": name, "expected": locked_version, "observed": installed})
    return violations


def _browser_violations(expected: dict[str, Any], observation: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    archive = expected["browser_archive_identity"]
    binary = expected["browser_binary_identity"]
    observed = observation.get("browser")
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not isinstance(observed, dict):
        return ([{"rule": "BROWSER_OBSERVATION_MISSING", "expected": archive["version"], "observed": None}], warnings)
    for rule, key, value in (
        ("PLAYWRIGHT_VERSION_MISMATCH", "playwright_version", archive["playwright"]),
        ("BROWSER_VERSION_MISMATCH", "version", archive["version"]),
        ("BROWSER_REVISION_MISMATCH", "revision", archive["revision"]),
    ):
        if observed.get(key) != value:
            violations.append({"rule": rule, "expected": value, "observed": observed.get(key)})
    path = observed.get("executable_path")
    if not isinstance(path, str) or not path.endswith(binary["relative_path"]) or f"chromium-{archive['revision']}" not in path:
        violations.append({"rule": "BROWSER_EXECUTABLE_IDENTITY_MISMATCH", "expected": f"chromium-{archive['revision']}/.../{binary['relative_path']}", "observed": path})
    observed_binary_sha = observed.get("binary_sha256")
    if not isinstance(observed_binary_sha, str) or not SHA256_RX.fullmatch(observed_binary_sha):
        violations.append({"rule": "BROWSER_BINARY_FINGERPRINT_MISSING", "expected": "sha256", "observed": observed_binary_sha})
    elif binary["expected_sha256"] is not None and observed_binary_sha != binary["expected_sha256"]:
        violations.append({"rule": "BROWSER_BINARY_SHA256_MISMATCH", "expected": binary["expected_sha256"], "observed": observed_binary_sha})
    elif binary["expected_sha256"] is None:
        warnings.append({"rule": "BROWSER_BINARY_SHA256_RUNTIME_ONLY", "observed": observed_binary_sha,
                         "detail": "Installed executable SHA-256 is recorded; no independently verified expected executable hash is versioned."})
    if archive["sha_pinned"]:
        if observed.get("archive_sha256") != archive["sha256"]:
            violations.append({"rule": "BROWSER_ARCHIVE_SHA256_MISMATCH", "expected": archive["sha256"], "observed": observed.get("archive_sha256")})
    else:
        warnings.append({"rule": "BROWSER_ARCHIVE_SHA256_UNPINNED", "observed": observed.get("archive_sha256"), "detail": archive["verification_status"]})
    return violations, warnings


def verify_observation(observation: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    expected = expected_identity(root)
    violations = _package_violations(expected, observation, root)
    browser_violations, warnings = _browser_violations(expected, observation)
    violations.extend(browser_violations)
    core = observation.get("core_runtime")
    if not isinstance(core, dict):
        violations.append({"rule": "CORE_RUNTIME_OBSERVATION_MISSING", "expected": "runtime manifest", "observed": None})
    else:
        for mismatch in repro_environment.runtime_mismatches(core):
            violations.append({"rule": "CORE_RUNTIME_MISMATCH", "expected": "locked runtime", "observed": mismatch})
    if expected["apt_snapshot_identity"]["fully_pinned"] is False:
        warnings.append({"rule": "SYSTEM_PACKAGE_VERSIONS_NOT_PREEXPANDED",
                         "detail": "Official Ubuntu snapshot is pinned; package versions are resolved and compared at build/verify time rather than pre-populated."})
    status = "FAIL" if violations else ("WARN" if warnings else "PASS")
    return {
        "schema": VERIFY_SCHEMA, "status": status, "expected": expected,
        "observed": observation,
        "violations": sorted(violations, key=lambda r: (r.get("rule", ""), r.get("package", ""))),
        "warnings": sorted(warnings, key=lambda r: r.get("rule", "")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("expected")
    sub.add_parser("verify")
    verify_obs = sub.add_parser("verify-observation")
    verify_obs.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "validate":
            value = expected_identity(root)
            print(json.dumps({"status": "PASS", "hermeticity_level": value["hermeticity_level"]}, sort_keys=True))
            return 0
        if args.command == "expected":
            print(json.dumps(expected_identity(root), indent=2, sort_keys=True, ensure_ascii=False))
            return 0
        observation = collect_observation(root) if args.command == "verify" else _read_json(args.input)
        report = verify_observation(observation, root)
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        return 2 if report["status"] == "FAIL" else 0
    except (HardeningError, OSError, ValueError) as exc:
        print(json.dumps({"schema": VERIFY_SCHEMA, "status": "FAIL",
                          "violations": [{"rule": "HARDENING_ERROR", "detail": str(exc)}],
                          "warnings": []}, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
