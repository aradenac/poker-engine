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

This tranche deliberately does not edit .github/workflows/**, #108 contracts, holdout ledgers or scientific run artifacts. CI enforcement and automatic manifest attachment to scientific runs remain missing, so #203 stays OPEN until lane A releases #108.\n\n## Future scientific run environment identity

The local runtime manifest and the scientific-run `environment_identity` serve different purposes. The runtime manifest records what a machine actually observed. The `environment_identity` is a deterministic **expected identity** built only from versioned REPRO sources, so the same commit and locks produce the same identity on every host.

The versioned contract is `reproducibility/environment-identity.schema.json`. Materialize the fragment locally with:

```bash
python3 tools/repro_environment_identity.py fragment --output /tmp/environment_identity.json
python3 tools/repro_environment_identity.py check-identity /tmp/environment_identity.json
```

The fragment includes exact Python, Node, Playwright, Chromium, OS distribution/version/architecture, SHA-256 for the Python/Node/environment/OS locks, and `identity_sha256`, computed from canonical JSON excluding the hash field itself. Container/image identity is included only when a container identity is explicitly present in a versioned REPRO source; no digest is inferred or invented.

For a **future** run manifest, inject the fragment before execution/persistence:

```bash
python3 tools/repro_environment_identity.py inject \
  --manifest /tmp/FUTURE_RUN.json \
  --output /tmp/FUTURE_RUN.with-environment.json
python3 tools/repro_environment_identity.py check-run /tmp/FUTURE_RUN.with-environment.json
```

After the future activation point, a new scientific run without `environment_identity` is fail-closed. The checker also rejects a missing lock, a missing/divergent critical version, a wrong identity hash, an extra non-canonical identity field, or identity content that does not exactly match the versioned locks.

### Historical runs are immutable

Existing scientific runs and frozen protocols are **not** backfilled. They are grandfathered because rewriting them would destroy the evidence identity they already carry. A historical manifest without `environment_identity` is accepted only when the checker is invoked with `--grandfather-historical`. This is deliberately an **external** mode: old evidence is not edited merely to add a grandfather marker. The versioned audit identifies which current families are historical/grandfathered. A FUTURE_RUN declaring `environment_identity_policy: "REQUIRED"` still fails when the identity is missing, even if the grandfather flag is supplied.

There is deliberately no automatic migration command for `training/runs/**`.

### Post-#108 workflow integration

No current workflow is changed by this tranche. After #108 releases the frozen scientific workflows, the mechanical integration is:

1. materialize `environment_identity` from the checked-out REPRO locks before the scientific command runs;
2. persist the full fragment in the new run manifest/result and freeze its `identity_sha256` in protocol/provenance where appropriate;
3. run `check-run` before artifact publication/promotion;
4. fail the workflow if the identity is absent or diverges from the locks;
5. keep historical runs on the explicit grandfather path only.

`analysis/reproducibility/scientific-run-environment-audit.json` inventories the current Model A, Model B, Hero/PFPC, full-hand, validation/promotion, prospective and other scientific manifest families and their recommended future integration points.
