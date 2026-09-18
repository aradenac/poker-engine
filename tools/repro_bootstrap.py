#!/usr/bin/env python3
"""Local clean-checkout bootstrap for the #203 reproducibility contract."""

from __future__ import annotations

import argparse
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import repro_environment


class BootstrapError(RuntimeError):
    pass


def _node_version() -> str | None:
    raw = repro_environment._command_version(["node", "--version"])
    return raw[1:] if raw and raw.startswith("v") else raw


def prerequisite_mismatches(root: Path = ROOT) -> list[str]:
    expected = repro_environment.expected_runtime(root)
    observed_os = repro_environment._read_os_release()
    observed = {
        "python": platform.python_version(),
        "node": _node_version(),
        "os": {
            "platform": sys.platform,
            "id": observed_os.get("ID"),
            "version_id": observed_os.get("VERSION_ID"),
            "machine": platform.machine(),
        },
    }
    return [key for key in ("python", "node", "os") if observed[key] != expected[key]]


def bootstrap_plan(
    root: Path = ROOT,
    venv: Path | None = None,
    manifest_dir: Path | None = None,
    install_os_deps: bool = True,
) -> list[list[str]]:
    venv = venv or root / ".venv"
    manifest_dir = manifest_dir or root / ".repro" / "environment-manifests"
    python = venv / "bin" / "python"
    playwright_install = [str(python), "-m", "playwright", "install"]
    if install_os_deps:
        playwright_install.append("--with-deps")
    playwright_install.append("chromium")
    return [
        [sys.executable, "-m", "venv", str(venv)],
        [str(python), "-m", "pip", "install", "--no-deps", "-r", str(root / "requirements.lock.txt")],
        ["npm", "ci", "--ignore-scripts"],
        playwright_install,
        [str(python), str(root / "tools" / "repro_bootstrap.py"), "verify", "--manifest-dir", str(manifest_dir)],
    ]


def verify_environment(
    root: Path = ROOT,
    manifest_dir: Path | None = None,
    manifest: dict[str, Any] | None = None,
) -> Path:
    errors = repro_environment.validate_contract(root)
    if errors:
        raise BootstrapError("contract mismatch: " + "; ".join(errors))
    manifest = manifest or repro_environment.collect_manifest(root)
    mismatches = repro_environment.runtime_mismatches(manifest)
    if mismatches:
        raise BootstrapError("runtime mismatch: " + ", ".join(mismatches))
    target = manifest_dir or root / ".repro" / "environment-manifests"
    return repro_environment.write_content_addressed_manifest(manifest, target)


def run_bootstrap(
    root: Path = ROOT,
    venv: Path | None = None,
    manifest_dir: Path | None = None,
    install_os_deps: bool = True,
) -> Path:
    errors = repro_environment.validate_contract(root)
    if errors:
        raise BootstrapError("contract mismatch: " + "; ".join(errors))
    mismatches = prerequisite_mismatches(root)
    if mismatches:
        raise BootstrapError("bootstrap prerequisite mismatch before mutation: " + ", ".join(mismatches))

    for command in bootstrap_plan(root, venv, manifest_dir, install_os_deps):
        subprocess.run(command, cwd=root, check=True)

    target = manifest_dir or root / ".repro" / "environment-manifests"
    manifests = sorted(target.glob("environment-manifest-*.json"))
    if not manifests:
        raise BootstrapError("bootstrap completed without an environment manifest")
    return manifests[-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--venv", type=Path)
    plan.add_argument("--manifest-dir", type=Path)
    plan.add_argument("--no-os-deps", action="store_true")

    verify = sub.add_parser("verify")
    verify.add_argument("--manifest-dir", type=Path)

    bootstrap = sub.add_parser("bootstrap")
    bootstrap.add_argument("--venv", type=Path)
    bootstrap.add_argument("--manifest-dir", type=Path)
    bootstrap.add_argument("--no-os-deps", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "plan":
            for command in bootstrap_plan(ROOT, args.venv, args.manifest_dir, not args.no_os_deps):
                print(" ".join(command))
            return 0
        if args.command == "verify":
            print(verify_environment(ROOT, args.manifest_dir))
            return 0
        print(run_bootstrap(ROOT, args.venv, args.manifest_dir, not args.no_os_deps))
        return 0
    except (BootstrapError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
