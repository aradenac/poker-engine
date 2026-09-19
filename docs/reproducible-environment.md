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


## Scientific reference container

The reference container is a separate, local/non-CI reproducibility layer. It does not replace the existing host bootstrap, and no current workflow consumes it while #108 remains active.

### Verified base image identity

The versioned source is `reproducibility/container-base.lock.json`.

- repository: `ubuntu`
- informative tag: `24.04`
- platform: `linux/amd64`
- OS identity: Ubuntu 24.04 / x86_64
- immutable amd64 manifest digest: `sha256:496754492fb28b4d3049432f2ca787449331e23fb14f0dd3fffea86bf5a93eb4`
- multi-platform index digest recorded for provenance: `sha256:b3cc40b72b93588182b5410f723c7aaf142363311c2aa993d8a453ddcbb3ae15`
- verification source: Docker Hub official `library/ubuntu:24.04` image detail page, recorded in the lock with the verification date.

The Dockerfile uses the **manifest digest directly**:

```Dockerfile
FROM ubuntu@sha256:496754492fb28b4d3049432f2ca787449331e23fb14f0dd3fffea86bf5a93eb4
```

A tag-only base, `:latest`, a malformed digest, a digest that disagrees with the recorded verification evidence, or a non-amd64 platform fails closed in `tools/repro_container.py`.

### Runtime source pins

The container contract keeps the existing runtime versions:

- Python 3.11.9, built from the python.org source archive with SHA-256 `9b1e896523fc510691126c864406d9360a3d1e986acbda59cda57b5abda45b87`;
- Node.js 22.14.0, installed from the official Linux x64 archive with SHA-256 `69b09dba5c8dcb05c4e4273a4340db1005abeafe3927efda2bc5b249e80437ec`;
- Python dependencies from `requirements.lock.txt`;
- Node dependencies from `package-lock.json`;
- Playwright 1.55.0 and Chromium 140.0.7339.16, verified by the existing runtime checker.

### System-package pinning and hermeticity

The explicit apt package set is versioned in `reproducibility/system-packages.apt.txt`. The package **names** are fixed and reviewed, but there is currently no immutable Ubuntu apt snapshot and no exact version pin for every apt package.

The contract therefore distinguishes:

- `BASE_IMAGE_PINNED = true`;
- `SYSTEM_PACKAGES_FULLY_PINNED = false`.

The declared hermeticity level is:

`BASE_IMAGE_PINNED_PARTIAL_SYSTEM_AND_BROWSER_FETCH`

This is intentionally not described as fully hermetic. Two limits remain explicit:

1. apt resolves package versions from the Ubuntu repositories available at build time;
2. Playwright 1.55.0 selects the Chromium build/revision and the installed version is verified, but this repository does not independently pin the downloaded Chromium archive by SHA-256.

### Local commands

Validate the static contract before any build:

```bash
./scripts/repro-container.sh validate
```

Produce a deterministic content-addressed manifest:

```bash
./scripts/repro-container.sh manifest \
  --output-dir .repro/container-manifests
```

Build the reference image:

```bash
./scripts/repro-container.sh build \
  --image poker-engine-science:local
```

Inspect Docker identity and labels:

```bash
./scripts/repro-container.sh inspect \
  --image poker-engine-science:local
```

Verify the built image against the versioned contract and execute the existing runtime verifier inside it:

```bash
./scripts/repro-container.sh verify \
  --image poker-engine-science:local
```

`build`, `inspect` and `verify` fail closed if Docker is unavailable. There is no fallback to an unverified host image.

### Content-addressed container identity

The container manifest hashes:

- the Dockerfile;
- `container-base.lock.json`;
- the explicit system-package list;
- `environment.lock.json`;
- `requirements.lock.txt`;
- `package-lock.json`.

Its canonical payload produces `manifest_sha256`. A Dockerfile change or any of these lock changes therefore changes the container identity.

Future-run `environment_identity` now embeds:

- base image repository/tag/platform/digest and OS architecture;
- container definition path + SHA-256;
- container lock SHA-256;
- system-package-list SHA-256;
- container manifest SHA-256;
- hermeticity level and the explicit system-package pinning status.

Historical run manifests remain untouched and continue to use the explicit grandfather path.

### Post-#108 workflow use

This tranche does **not** modify `.github/workflows/**`. After #108 releases the frozen workflow area, future scientific jobs can mechanically:

1. validate the container contract;
2. build or select the content-addressed reference image;
3. run `verify` before scientific execution;
4. inject the resulting versioned `environment_identity` into future run provenance;
5. reject publication/promotion if the container or runtime identity diverges.

Until that wiring exists, #203 remains OPEN.
