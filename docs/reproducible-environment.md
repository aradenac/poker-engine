# Reproducible environment contract

Issue #203 defines a repository-level environment contract without changing the scientific workflows frozen by #107/#108.

## Pinned identities

- Python: 3.11.9
- Node.js: 22.14.0
- Playwright for Python: 1.55.0
- Chromium: 140.0.7339.16
- base OS identity: Ubuntu 24.04, x86_64

The canonical runtime contract is reproducibility/environment.lock.json.
The base OS contract is reproducibility/os-base.lock.json.

The OS distribution, version and architecture are pinned and verified. Apt package versions are not snapshot-pinned yet; the repository therefore does not claim a fully hermetic OS image in this local tranche.

## Clean checkout

A clean machine must first provide the exact Python, Node and OS identities above. Then one command creates the local environment:

    ./scripts/repro-bootstrap.sh bootstrap

The bootstrap fails before creating the venv when Python, Node or the base OS identity differs from the lock. It then creates .venv, installs the complete Python lock with --no-deps, runs npm ci --ignore-scripts, installs the Chromium build distributed by the pinned Playwright release, runs the fail-closed verifier and writes a content-addressed environment manifest under .repro/environment-manifests/.

For a host where browser OS dependencies are already provisioned:

    ./scripts/repro-bootstrap.sh bootstrap --no-os-deps

## One-command verification

After bootstrap:

    ./scripts/repro-bootstrap.sh verify

The wrapper automatically uses .venv/bin/python when present. Verification fails if Python, Node, Playwright, Chromium, Ubuntu version/architecture or repository lock consistency diverges.

A successful verification writes:

    .repro/environment-manifests/environment-manifest-<sha256>.json

The filename is the SHA-256 of the manifest canonical payload. The manifest also contains hashes of environment.lock.json, os-base.lock.json, requirements.lock.txt and package-lock.json.

Preview the exact bootstrap commands without mutation:

    ./scripts/repro-bootstrap.sh plan

## Direct commands

Contract-only validation:

    python3 tools/repro_environment.py --check-contract

Runtime verification plus content-addressed manifest:

    python tools/repro_environment.py --verify-runtime --manifest-dir .repro/environment-manifests

## Lock update procedure

1. Open a dedicated reproducibility PR; never rewrite an immutable scientific run.
2. Change runtime/dependency versions in the canonical inputs.
3. Keep .python-version, .node-version, package.json, package-lock.json, environment.lock.json and os-base.lock.json consistent.
4. Run the exact REPRO tests and one-command verification.
5. Treat a Playwright/Chromium or base-OS change as an explicit environment change.
6. Re-run representative scientific non-regression tests before promotion.

## Current boundary

This tranche deliberately does not edit .github/workflows/**, #108 contracts, holdout ledgers or scientific run artifacts. CI enforcement and automatic manifest attachment to scientific runs remain missing, so #203 stays OPEN until lane A releases #108.
